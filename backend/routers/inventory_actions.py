"""Bulk Pause Inventory endpoints (`/api/inventory-actions/...`).

Lets the user pick Account → Main Category → Color → sizes, then queues a
`pause_skus` job for the EC2 scraper. The scraper opens supplier.meesho.com's
Inventory page, searches each Style ID from the Product Master, ticks only
the checkboxes matching the chosen sizes, and clicks "Pause Selected".

Multi-account from day 1 — each `accounts` doc already carries `debug_port`
and `profile_dir` for its own logged-in Chrome, exactly like label_download
and gst_report_fetch.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/inventory-actions", tags=["inventory-actions"])

# injected from server.py
_db = None


def configure(db):
    global _db
    _db = db


def get_db():
    if _db is None:
        raise RuntimeError("inventory_actions router not configured")
    return _db


# ---------------- Pydantic models ----------------
class PreviewIn(BaseModel):
    account_id: str
    main_category: str
    color: str
    sizes: List[str] = Field(default_factory=list)  # empty = "whole product"


class PauseIn(PreviewIn):
    pass


# ---------------- Helpers ----------------
def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail=f"invalid id: {s}")


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


async def _resolve_product(db, account_id: str, main_category: str, color: str) -> dict:
    _oid(account_id)
    prod = await db.pm_products.find_one({
        "account_id": account_id,
        "main_category": main_category,
        "color": color,
    })
    if not prod:
        raise HTTPException(
            status_code=404,
            detail=f"No Product Master entry for {main_category} / {color}",
        )
    return prod


async def _sizes_for_product(db, product_id) -> List[str]:
    out: List[str] = []
    async for s in db.pm_sizes.find({"product_id": product_id}, {"_id": 0, "size": 1}):
        out.append(s.get("size"))
    return sorted([s for s in out if s], key=lambda x: (len(x), x))


async def _style_ids_for_product(db, product_id) -> List[str]:
    """Each row in pm_skus is a Style ID (Meesho's Style ID from panel).
    The actual per-size SKU on Meesho is derived by the panel itself when
    we search a Style ID."""
    out: List[str] = []
    async for s in db.pm_skus.find({"product_id": product_id}, {"_id": 0, "sku": 1}):
        v = (s.get("sku") or "").strip()
        if v:
            out.append(v)
    # de-dupe preserving order
    seen: set = set()
    uniq: List[str] = []
    for x in out:
        k = x.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(x)
    return uniq


# =========================================================================== #
# OPTIONS — cascading dropdowns
# =========================================================================== #
@router.get("/options")
async def options(
    account_id: Optional[str] = None,
    main_category: Optional[str] = None,
    color: Optional[str] = None,
):
    """Cascade:
       - no filter → list accounts
       - account_id → list main_categories for that account
       - account_id + main_category → list colors
       - account_id + main_category + color → list sizes + style_ids
    """
    db = get_db()

    # accounts
    accounts = []
    async for a in db.accounts.find({}, {"_id": 1, "name": 1, "alias": 1, "enabled": 1}):
        accounts.append({
            "id": str(a["_id"]),
            "name": a.get("name"),
            "alias": a.get("alias"),
            "enabled": bool(a.get("enabled", True)),
        })

    if not account_id:
        return {"accounts": accounts}

    filt: Dict[str, Any] = {"account_id": account_id}
    cats = sorted([c for c in await db.pm_products.distinct("main_category", filt) if c])

    if not main_category:
        return {"accounts": accounts, "main_categories": cats}

    filt["main_category"] = main_category
    colors = sorted([c for c in await db.pm_products.distinct("color", filt) if c])

    if not color:
        return {"accounts": accounts, "main_categories": cats, "colors": colors}

    prod = await _resolve_product(db, account_id, main_category, color)
    sizes = await _sizes_for_product(db, prod["_id"])
    style_ids = await _style_ids_for_product(db, prod["_id"])
    return {
        "accounts": accounts,
        "main_categories": cats,
        "colors": colors,
        "sizes": sizes,
        "style_ids": style_ids,
        "product_id": str(prod["_id"]),
    }


# =========================================================================== #
# PREVIEW — what we'll do without doing it
# =========================================================================== #
@router.post("/preview")
async def preview(body: PreviewIn):
    db = get_db()
    prod = await _resolve_product(db, body.account_id, body.main_category, body.color)
    all_sizes = await _sizes_for_product(db, prod["_id"])
    style_ids = await _style_ids_for_product(db, prod["_id"])
    # If no sizes chosen, treat as "whole product" = all sizes.
    target_sizes = body.sizes or all_sizes

    # sanity: every requested size must exist for this product
    unknown = [s for s in body.sizes if s not in all_sizes]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Sizes not in Product Master: {unknown}",
        )

    acc = await db.accounts.find_one({"_id": _oid(body.account_id)})
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    return {
        "account": {
            "id": str(acc["_id"]),
            "name": acc.get("name"),
            "alias": acc.get("alias"),
            "enabled": bool(acc.get("enabled", True)),
            "has_chrome_profile": bool(acc.get("debug_port")),
        },
        "product": {
            "id": str(prod["_id"]),
            "main_category": prod.get("main_category"),
            "color": prod.get("color"),
        },
        "all_sizes": all_sizes,
        "target_sizes": target_sizes,
        "style_ids": style_ids,
        "estimated_meesho_skus": len(style_ids) * len(target_sizes),
        "is_whole_product": len(target_sizes) == len(all_sizes),
    }


# =========================================================================== #
# PAUSE — queue the job
# =========================================================================== #
@router.post("/pause")
async def pause(body: PauseIn):
    db = get_db()
    prod = await _resolve_product(db, body.account_id, body.main_category, body.color)
    all_sizes = await _sizes_for_product(db, prod["_id"])
    style_ids = await _style_ids_for_product(db, prod["_id"])
    if not style_ids:
        raise HTTPException(
            status_code=400,
            detail="This product has no Style IDs in Product Master — nothing to pause.",
        )
    target_sizes = body.sizes or all_sizes
    unknown = [s for s in body.sizes if s not in all_sizes]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Sizes not in Product Master: {unknown}",
        )

    acc = await db.accounts.find_one({"_id": _oid(body.account_id)})
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    if not acc.get("enabled", True):
        raise HTTPException(
            status_code=400,
            detail=f"Account '{acc.get('name')}' is disabled",
        )

    # Refuse if a pause_skus job for this same product+account is already in flight
    existing = await db.jobs.find_one({
        "type": "pause_skus",
        "account_id": body.account_id,
        "payload.product_id": str(prod["_id"]),
        "status": {"$in": ["pending", "processing"]},
    })
    if existing:
        return {
            "ok": True,
            "already_queued": True,
            "job_id": str(existing["_id"]),
        }

    now = datetime.now(timezone.utc)
    doc = {
        "type": "pause_skus",
        "status": "pending",
        "account_id": body.account_id,
        "account_name": acc.get("name"),
        "created_at": now,
        "submitted_by": "dashboard",
        "payload": {
            "product_id": str(prod["_id"]),
            "main_category": prod.get("main_category"),
            "color": prod.get("color"),
            "target_sizes": target_sizes,
            "style_ids": style_ids,
        },
    }
    res = await db.jobs.insert_one(doc)
    return {
        "ok": True,
        "already_queued": False,
        "job_id": str(res.inserted_id),
        "queued": {
            "style_ids": style_ids,
            "target_sizes": target_sizes,
            "estimated_meesho_skus": len(style_ids) * len(target_sizes),
        },
    }


# =========================================================================== #
# HISTORY / STATUS
# =========================================================================== #
def _serialize_job(j: dict) -> dict:
    payload = j.get("payload") or {}
    result = j.get("result") or {}
    return {
        "id": str(j["_id"]),
        "status": j.get("status"),
        "account_id": j.get("account_id"),
        "account_name": j.get("account_name"),
        "main_category": payload.get("main_category"),
        "color": payload.get("color"),
        "target_sizes": payload.get("target_sizes") or [],
        "style_ids": payload.get("style_ids") or [],
        "estimated_meesho_skus": (
            len(payload.get("style_ids") or []) * len(payload.get("target_sizes") or [])
        ),
        "submitted_by": j.get("submitted_by"),
        "created_at": _iso(j.get("created_at")),
        "started_at": _iso(j.get("started_at")),
        "finished_at": _iso(j.get("finished_at")),
        "error": j.get("error"),
        "result": {
            "paused_count": int(result.get("paused_count") or 0),
            "already_paused_count": int(result.get("already_paused_count") or 0),
            "failed_count": int(result.get("failed_count") or 0),
            "per_sku": result.get("per_sku") or [],
        },
    }


@router.get("/history")
async def history(
    limit: int = Query(50, ge=1, le=200),
    account_id: Optional[str] = None,
    status: Optional[str] = Query(
        None, pattern="^(pending|processing|done|failed)$"),
):
    db = get_db()
    q: Dict[str, Any] = {"type": "pause_skus"}
    if account_id:
        q["account_id"] = account_id
    if status:
        q["status"] = status
    cursor = db.jobs.find(q).sort("created_at", -1).limit(limit)
    items = [_serialize_job(d) async for d in cursor]
    # counts by status (ignoring the status filter so the tabs stay accurate)
    counts_q: Dict[str, Any] = {"type": "pause_skus"}
    if account_id:
        counts_q["account_id"] = account_id
    counts: Dict[str, int] = {"pending": 0, "processing": 0, "done": 0, "failed": 0}
    async for row in db.jobs.aggregate([
        {"$match": counts_q},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ]):
        counts[row["_id"]] = int(row["n"])
    return {"items": items, "counts": counts}


@router.get("/{job_id}")
async def job_status(job_id: str):
    db = get_db()
    j = await db.jobs.find_one({"_id": _oid(job_id), "type": "pause_skus"})
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    return _serialize_job(j)
