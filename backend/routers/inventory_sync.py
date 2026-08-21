"""Live Inventory Sync (`/api/inventory-sync/...`).

Scrapes the Active tab of Meesho's Inventory panel and stores every live
(catalog, style_id, sku, size, price, stock) row. Uses the existing EC2
job-queue pattern (jobs collection, type=`inventory_sync`).

Extra endpoints:
  - /live       list currently live SKUs (with filters)
  - /missing    SKUs live on Meesho but not in Product Master (or vice versa)
  - /*/export   Excel downloads
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/inventory-sync", tags=["inventory-sync"])

_db = None


def configure(db):
    global _db
    _db = db


def get_db():
    if _db is None:
        raise RuntimeError("inventory_sync router not configured")
    return _db


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail=f"invalid id: {s}")


def _iso(d):
    if isinstance(d, datetime):
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.isoformat().replace("+00:00", "Z")
    return None


# ---------------- run ----------------
class RunIn(BaseModel):
    account_id: str


@router.post("/run")
async def run_sync(body: RunIn):
    db = get_db()
    if not body.account_id or body.account_id == "all":
        raise HTTPException(status_code=400,
                            detail="Pick a specific account to sync — 'all' is not allowed.")
    acc = await db.accounts.find_one({"_id": _oid(body.account_id)})
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    if not acc.get("enabled", True):
        raise HTTPException(status_code=400, detail="Account disabled")

    existing = await db.jobs.find_one({
        "type": "inventory_sync",
        "account_id": body.account_id,
        "status": {"$in": ["pending", "processing"]},
    })
    if existing:
        return {"ok": True, "already_queued": True, "job_id": str(existing["_id"])}

    res = await db.jobs.insert_one({
        "type": "inventory_sync",
        "status": "pending",
        "account_id": body.account_id,
        "account_name": acc.get("name"),
        "submitted_by": "dashboard",
        "created_at": datetime.now(timezone.utc),
        "payload": {},
    })
    return {"ok": True, "already_queued": False, "job_id": str(res.inserted_id)}


# ---------------- history / status ----------------
def _serialize_job(j: dict) -> dict:
    r = j.get("result") or {}
    return {
        "id": str(j["_id"]),
        "status": j.get("status"),
        "account_id": j.get("account_id"),
        "account_name": j.get("account_name"),
        "created_at": _iso(j.get("created_at")),
        "started_at": _iso(j.get("started_at")),
        "finished_at": _iso(j.get("finished_at")),
        "error": j.get("error"),
        "result": {
            "catalogs_scanned": int(r.get("catalogs_scanned") or 0),
            "skus_captured": int(r.get("skus_captured") or 0),
            "pages_visited": int(r.get("pages_visited") or 0),
        },
    }


@router.get("/history")
async def history(
    limit: int = Query(30, ge=1, le=200),
    account_id: Optional[str] = None,
    status: Optional[str] = Query(
        None, pattern="^(pending|processing|done|failed)$"),
):
    db = get_db()
    q: Dict[str, Any] = {"type": "inventory_sync"}
    if account_id:
        q["account_id"] = account_id
    if status:
        q["status"] = status
    items = [_serialize_job(d) async for d in
             db.jobs.find(q).sort("created_at", -1).limit(limit)]
    counts_q: Dict[str, Any] = {"type": "inventory_sync"}
    if account_id:
        counts_q["account_id"] = account_id
    counts = {"pending": 0, "processing": 0, "done": 0, "failed": 0}
    async for row in db.jobs.aggregate([
        {"$match": counts_q},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ]):
        counts[row["_id"]] = int(row["n"])
    return {"items": items, "counts": counts}


@router.get("/last-sync")
async def last_sync(account_id: Optional[str] = None):
    """Newest DONE sync per account (or for one account)."""
    db = get_db()
    q: Dict[str, Any] = {"type": "inventory_sync", "status": "done"}
    if account_id:
        q["account_id"] = account_id
        j = await db.jobs.find_one(q, sort=[("finished_at", -1)])
        return {"item": _serialize_job(j) if j else None}
    items = {}
    async for j in db.jobs.find(q).sort("finished_at", -1):
        aid = j.get("account_id")
        if aid and aid not in items:
            items[aid] = _serialize_job(j)
    return {"items": list(items.values())}


# ---------------- live SKUs listing ----------------
@router.get("/live")
async def live_skus(
    account_id: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    db = get_db()
    q: Dict[str, Any] = {}
    if account_id and account_id != "all":
        q["account_id"] = account_id
    if category:
        q["category"] = category
    if search:
        s = search.strip()
        q["$or"] = [
            {"sku": {"$regex": s, "$options": "i"}},
            {"style_id": {"$regex": s, "$options": "i"}},
            {"catalog_name": {"$regex": s, "$options": "i"}},
        ]
    total = await db.meesho_live_skus.count_documents(q)
    rows = []
    async for r in db.meesho_live_skus.find(q, {"_id": 0}).sort(
            [("account_id", 1), ("catalog_name", 1), ("style_id", 1), ("variation", 1)]
    ).skip(offset).limit(limit):
        r["synced_at"] = _iso(r.get("synced_at"))
        rows.append(r)

    # top-level totals per account/category for filter badges
    facets: Dict[str, Any] = {"by_account": [], "by_category": []}
    async for row in db.meesho_live_skus.aggregate([
        {"$match": q},
        {"$group": {"_id": "$account_name", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ]):
        facets["by_account"].append({"account": row["_id"], "count": row["n"]})
    async for row in db.meesho_live_skus.aggregate([
        {"$match": q},
        {"$group": {"_id": "$category", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ]):
        facets["by_category"].append({"category": row["_id"], "count": row["n"]})
    return {"items": rows, "total": total, "limit": limit, "offset": offset,
            "facets": facets}


@router.get("/live/export")
async def live_export(
    account_id: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
):
    db = get_db()
    q: Dict[str, Any] = {}
    if account_id and account_id != "all":
        q["account_id"] = account_id
    if category:
        q["category"] = category
    if search:
        s = search.strip()
        q["$or"] = [
            {"sku": {"$regex": s, "$options": "i"}},
            {"style_id": {"$regex": s, "$options": "i"}},
            {"catalog_name": {"$regex": s, "$options": "i"}},
        ]
    rows = []
    async for r in db.meesho_live_skus.find(q, {"_id": 0}):
        rows.append({
            "Account": r.get("account_name") or "",
            "Catalog": r.get("catalog_name") or "",
            "Catalog ID": r.get("catalog_id") or "",
            "Category": r.get("category") or "",
            "Style ID": r.get("style_id") or "",
            "SKU": r.get("sku") or "",
            "Variation (Size)": r.get("variation") or "",
            "Price": r.get("price") or "",
            "Current Stock": r.get("current_stock") or 0,
            "Synced At": _iso(r.get("synced_at")) or "",
        })
    if not rows:
        rows = [{"Account": "", "Catalog": "", "Catalog ID": "", "Category": "",
                 "Style ID": "", "SKU": "", "Variation (Size)": "",
                 "Price": "", "Current Stock": 0, "Synced At": ""}]
    df = pd.DataFrame(rows)
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Live SKUs")
    out.seek(0)
    fn = f"live_skus_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fn}"},
    )


# ---------------- missing SKUs ----------------
async def _missing_pairs(db, account_id: Optional[str]):
    """Return (only_on_meesho, only_in_pm) as lists of dicts."""
    q_live: Dict[str, Any] = {}
    q_pm: Dict[str, Any] = {}
    if account_id and account_id != "all":
        q_live["account_id"] = account_id
        q_pm["account_id"] = account_id

    live_pairs: set = set()
    live_rows: Dict[Any, dict] = {}
    async for r in db.meesho_live_skus.find(q_live, {"_id": 0}):
        key = (r.get("account_id"), (r.get("style_id") or "").strip())
        live_pairs.add(key)
        live_rows[key] = r
    pm_pairs: set = set()
    pm_rows: Dict[Any, dict] = {}
    async for r in db.pm_skus.find(q_pm, {"_id": 0}):
        key = (r.get("account_id"), (r.get("sku") or "").strip())
        pm_pairs.add(key)
        pm_rows[key] = r

    acc_lookup: Dict[str, dict] = {}
    async for a in db.accounts.find({}, {"_id": 1, "name": 1, "alias": 1}):
        acc_lookup[str(a["_id"])] = {"name": a.get("name"),
                                     "alias": a.get("alias")}

    only_on_meesho = []
    for (aid, sid) in sorted(live_pairs - pm_pairs):
        r = live_rows.get((aid, sid), {})
        only_on_meesho.append({
            "account_id": aid,
            "account_name": acc_lookup.get(aid, {}).get("name"),
            "account_alias": acc_lookup.get(aid, {}).get("alias"),
            "style_id": sid,
            "catalog_name": r.get("catalog_name"),
            "category": r.get("category"),
        })
    only_in_pm = []
    for (aid, sid) in sorted(pm_pairs - live_pairs):
        r = pm_rows.get((aid, sid), {})
        only_in_pm.append({
            "account_id": aid,
            "account_name": acc_lookup.get(aid, {}).get("name"),
            "account_alias": acc_lookup.get(aid, {}).get("alias"),
            "style_id": sid,
            "product_id": str(r.get("product_id")) if r.get("product_id") else None,
        })
    return only_on_meesho, only_in_pm


@router.get("/missing")
async def missing(account_id: Optional[str] = None):
    db = get_db()
    on_meesho, in_pm = await _missing_pairs(db, account_id)
    by_account_meesho: Dict[str, int] = {}
    for it in on_meesho:
        k = it["account_alias"] or it["account_name"] or "—"
        by_account_meesho[k] = by_account_meesho.get(k, 0) + 1
    by_account_pm: Dict[str, int] = {}
    for it in in_pm:
        k = it["account_alias"] or it["account_name"] or "—"
        by_account_pm[k] = by_account_pm.get(k, 0) + 1
    return {
        "only_on_meesho": on_meesho,
        "only_in_pm": in_pm,
        "counts": {
            "only_on_meesho": len(on_meesho),
            "only_in_pm": len(in_pm),
        },
        "by_account_meesho": [{"account": k, "count": v}
                              for k, v in sorted(by_account_meesho.items(),
                                                 key=lambda kv: -kv[1])],
        "by_account_pm": [{"account": k, "count": v}
                          for k, v in sorted(by_account_pm.items(),
                                             key=lambda kv: -kv[1])],
    }


@router.get("/missing/export")
async def missing_export(account_id: Optional[str] = None):
    db = get_db()
    on_meesho, in_pm = await _missing_pairs(db, account_id)
    df_meesho = pd.DataFrame([{
        "Account": (r.get("account_alias") or r.get("account_name") or ""),
        "Account ID": r.get("account_id") or "",
        "Style ID": r.get("style_id") or "",
        "Catalog": r.get("catalog_name") or "",
        "Category": r.get("category") or "",
    } for r in on_meesho] or [{
        "Account": "", "Account ID": "", "Style ID": "", "Catalog": "", "Category": ""
    }])
    df_pm = pd.DataFrame([{
        "Account": (r.get("account_alias") or r.get("account_name") or ""),
        "Account ID": r.get("account_id") or "",
        "Style ID": r.get("style_id") or "",
    } for r in in_pm] or [{"Account": "", "Account ID": "", "Style ID": ""}])
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        df_meesho.to_excel(w, index=False,
                           sheet_name="On Meesho, NOT in PM")
        df_pm.to_excel(w, index=False, sheet_name="In PM, NOT on Meesho")
    out.seek(0)
    fn = f"missing_live_skus_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fn}"},
    )
