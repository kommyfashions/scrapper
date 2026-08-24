"""Live Inventory Sync (`/api/inventory-sync/...`).

Finalised spec (Feb 2026):
  - Scraper captures only `style_id` per catalog (one representative row
    per catalog), plus `catalog_id`, `account_id`, `account_name`,
    `page_no`, `scraped_at`. See `scraper-ec2/inventory_sync_fetcher.py`.
  - Backend enriches at read-time via Product Master:
      style_id ⟶ pm_skus.sku ⟶ pm_products.{account_id, main_category}
      • matched   → Live SKUs tab
      • unmatched → Missing tab (Main Category = "Unmapped")
  - `POST /run` accepts a single account_id OR "all" (fan-out one job
    per enabled account) and a `pages` integer (default 20).
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/inventory-sync", tags=["inventory-sync"])

_db = None
UNMAPPED = "Unmapped"


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


# ------------------------- enrichment helpers -------------------------
async def _load_pm_lookup(db) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """(account_id, sku) → {main_category, account_name, account_alias}."""
    accounts: Dict[str, Dict[str, Any]] = {}
    async for a in db.accounts.find(
            {}, {"_id": 1, "name": 1, "alias": 1}):
        accounts[str(a["_id"])] = {
            "account_name": a.get("name"),
            "account_alias": a.get("alias"),
        }
    products: Dict[str, Dict[str, Any]] = {}
    async for p in db.pm_products.find(
            {}, {"_id": 1, "account_id": 1, "main_category": 1}):
        products[str(p["_id"])] = {
            "account_id": p.get("account_id"),
            "main_category": p.get("main_category"),
        }
    lookup: Dict[Tuple[str, str], Dict[str, Any]] = {}
    async for s in db.pm_skus.find({}, {"_id": 0, "account_id": 1,
                                        "sku": 1, "product_id": 1}):
        sku = (s.get("sku") or "").strip()
        aid = s.get("account_id") or ""
        if not sku or not aid:
            continue
        prod = products.get(str(s.get("product_id"))) or {}
        acc = accounts.get(aid, {})
        lookup[(aid, sku)] = {
            "main_category": prod.get("main_category") or UNMAPPED,
            "account_name": acc.get("account_name"),
            "account_alias": acc.get("account_alias"),
        }
    # Also index by sku alone (in case the scraped account_id doesn't
    # match master inventory's account_id for the same SKU — falls back
    # to the master entry that owns the SKU).
    return lookup


async def _account_map(db) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    async for a in db.accounts.find({}, {"_id": 1, "name": 1, "alias": 1,
                                          "enabled": 1}):
        out[str(a["_id"])] = {
            "name": a.get("name"),
            "alias": a.get("alias"),
            "enabled": a.get("enabled", True),
        }
    return out


async def _iter_live_rows(db, account_id: Optional[str]):
    q: Dict[str, Any] = {}
    if account_id and account_id != "all":
        q["account_id"] = account_id
    async for r in db.meesho_live_skus.find(q, {"_id": 0}):
        yield r


async def _build_view(db, account_id: Optional[str], search: Optional[str],
                     main_category: Optional[str]):
    """Returns (matched_rows, unmatched_rows) already enriched + filtered."""
    pm = await _load_pm_lookup(db)
    accs = await _account_map(db)

    # style_id → matched pm entry (first hit wins if same style_id lives
    # under multiple accounts in master).
    sku_index: Dict[str, Dict[str, Any]] = {}
    for (aid, sku), info in pm.items():
        # prefer entries whose account_id matches the row's account_id
        # (handled at lookup time); keep any as fallback
        sku_index.setdefault(sku, {"account_id": aid, **info})

    matched: List[Dict[str, Any]] = []
    unmatched: List[Dict[str, Any]] = []

    async for r in _iter_live_rows(db, account_id):
        sid = (r.get("style_id") or "").strip()
        scraped_aid = r.get("account_id") or ""
        scraped_aname = r.get("account_name")
        scraped_at = _iso(r.get("scraped_at"))

        # 1) exact (account, sku)
        hit = pm.get((scraped_aid, sid))
        # 2) style_id alone
        if not hit:
            hit = sku_index.get(sid)
        if hit:
            aid = hit.get("account_id") or scraped_aid
            acc = accs.get(aid, {})
            acc_display = (acc.get("alias") or acc.get("name")
                           or scraped_aname or "—")
            row = {
                "account": acc_display,
                "account_id": aid,
                "main_category": hit.get("main_category") or UNMAPPED,
                "style_id": sid,
                "last_synced": scraped_at,
            }
            matched.append(row)
        else:
            acc = accs.get(scraped_aid, {})
            acc_display = (acc.get("alias") or acc.get("name")
                           or scraped_aname or "—")
            unmatched.append({
                "account": acc_display,
                "account_id": scraped_aid,
                "main_category": UNMAPPED,
                "style_id": sid,
                "last_synced": scraped_at,
            })

    # apply filters
    def _keep(row: Dict[str, Any]) -> bool:
        if main_category and row["main_category"] != main_category:
            return False
        if search:
            s = search.strip().lower()
            if s and s not in (row["style_id"] or "").lower():
                return False
        return True

    matched = [r for r in matched if _keep(r)]
    unmatched = [r for r in unmatched if _keep(r)]
    matched.sort(key=lambda r: (r["account"] or "", r["main_category"] or "",
                                r["style_id"] or ""))
    unmatched.sort(key=lambda r: (r["account"] or "", r["style_id"] or ""))
    return matched, unmatched


# ------------------------------- run --------------------------------
class RunIn(BaseModel):
    account_id: str = Field(..., description="Account id or 'all'")
    pages: int = Field(20, ge=1, le=200)


async def _queue_one(db, acc: Dict[str, Any], pages: int) -> Dict[str, Any]:
    """Insert a pending inventory_sync job for a single account (idempotent)."""
    account_id = str(acc["_id"])
    existing = await db.jobs.find_one({
        "type": "inventory_sync",
        "account_id": account_id,
        "status": {"$in": ["pending", "processing"]},
    })
    if existing:
        return {"account_id": account_id, "account_name": acc.get("name"),
                "already_queued": True, "job_id": str(existing["_id"])}
    res = await db.jobs.insert_one({
        "type": "inventory_sync",
        "status": "pending",
        "account_id": account_id,
        "account_name": acc.get("name"),
        "submitted_by": "dashboard",
        "created_at": datetime.now(timezone.utc),
        "payload": {"pages": int(pages)},
    })
    return {"account_id": account_id, "account_name": acc.get("name"),
            "already_queued": False, "job_id": str(res.inserted_id)}


@router.post("/run")
async def run_sync(body: RunIn):
    db = get_db()
    pages = int(body.pages or 20)

    if body.account_id == "all":
        # fan out across every enabled account, sequentially processed
        # by the worker (one Chrome profile at a time).
        queued: List[Dict[str, Any]] = []
        async for acc in db.accounts.find({"enabled": {"$ne": False}}):
            queued.append(await _queue_one(db, acc, pages))
        return {"ok": True, "fanned_out": True, "jobs": queued,
                "pages": pages}

    acc = await db.accounts.find_one({"_id": _oid(body.account_id)})
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    if not acc.get("enabled", True):
        raise HTTPException(status_code=400, detail="Account disabled")
    info = await _queue_one(db, acc, pages)
    return {"ok": True, "fanned_out": False, "job_id": info["job_id"],
            "already_queued": info["already_queued"], "pages": pages}


# --------------------------- history --------------------------------
def _serialize_job(j: dict) -> dict:
    r = j.get("result") or {}
    return {
        "id": str(j["_id"]),
        "status": j.get("status"),
        "account_id": j.get("account_id"),
        "account_name": j.get("account_name"),
        "pages_requested": int((j.get("payload") or {}).get("pages")
                               or r.get("pages_requested") or 0),
        "created_at": _iso(j.get("created_at")),
        "started_at": _iso(j.get("started_at")),
        "finished_at": _iso(j.get("finished_at")),
        "error": j.get("error"),
        "result": {
            "catalogs_scanned": int(r.get("catalogs_scanned") or 0),
            "skus_captured": int(r.get("skus_captured") or 0),
            "pages_visited": int(r.get("pages_visited") or 0),
            "note": r.get("note") or "",
            "debug_dir": r.get("debug_dir") or "",
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
    if account_id and account_id != "all":
        q["account_id"] = account_id
    if status:
        q["status"] = status
    items = [_serialize_job(d) async for d in
             db.jobs.find(q).sort("created_at", -1).limit(limit)]
    counts_q: Dict[str, Any] = {"type": "inventory_sync"}
    if account_id and account_id != "all":
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
    if account_id and account_id != "all":
        q["account_id"] = account_id
        j = await db.jobs.find_one(q, sort=[("finished_at", -1)])
        return {"item": _serialize_job(j) if j else None}
    items: Dict[str, Any] = {}
    async for j in db.jobs.find(q).sort("finished_at", -1):
        aid = j.get("account_id")
        if aid and aid not in items:
            items[aid] = _serialize_job(j)
    return {"items": list(items.values())}


# ------------------------- live SKUs listing -------------------------
@router.get("/live")
async def live_skus(
    account_id: Optional[str] = None,
    main_category: Optional[str] = Query(None, alias="category"),
    search: Optional[str] = None,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    db = get_db()
    matched, _unmatched = await _build_view(
        db, account_id, search, main_category)
    total = len(matched)
    page_rows = matched[offset: offset + limit]

    facets_by_account: Dict[str, int] = {}
    facets_by_category: Dict[str, int] = {}
    for r in matched:
        facets_by_account[r["account"]] = (
            facets_by_account.get(r["account"], 0) + 1)
        facets_by_category[r["main_category"]] = (
            facets_by_category.get(r["main_category"], 0) + 1)
    return {
        "items": page_rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "facets": {
            "by_account": [{"account": k, "count": v}
                           for k, v in sorted(facets_by_account.items(),
                                              key=lambda kv: -kv[1])],
            "by_category": [{"category": k, "count": v}
                            for k, v in sorted(facets_by_category.items(),
                                               key=lambda kv: -kv[1])],
        },
    }


@router.get("/missing")
async def missing(
    account_id: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    db = get_db()
    _matched, unmatched = await _build_view(db, account_id, search, None)
    total = len(unmatched)
    page_rows = unmatched[offset: offset + limit]
    facets_by_account: Dict[str, int] = {}
    for r in unmatched:
        facets_by_account[r["account"]] = (
            facets_by_account.get(r["account"], 0) + 1)
    return {
        "items": page_rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "facets": {
            "by_account": [{"account": k, "count": v}
                           for k, v in sorted(facets_by_account.items(),
                                              key=lambda kv: -kv[1])],
        },
    }


def _to_excel(rows: List[Dict[str, Any]], sheet_name: str,
              filename: str) -> StreamingResponse:
    df = pd.DataFrame(rows or [{"Account": "", "Main Category": "",
                                "Style ID": "", "Last Synced": ""}])
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name=sheet_name)
    out.seek(0)
    return StreamingResponse(
        out,
        media_type=("application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"),
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _rows_to_export(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{
        "Account": r.get("account") or "",
        "Main Category": r.get("main_category") or "",
        "Style ID": r.get("style_id") or "",
        "Last Synced": r.get("last_synced") or "",
    } for r in rows]


@router.get("/live/export")
async def live_export(
    account_id: Optional[str] = None,
    main_category: Optional[str] = Query(None, alias="category"),
    search: Optional[str] = None,
):
    db = get_db()
    matched, _ = await _build_view(db, account_id, search, main_category)
    fn = f"live_skus_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return _to_excel(_rows_to_export(matched), "Live SKUs", fn)


@router.get("/missing/export")
async def missing_export(
    account_id: Optional[str] = None,
    search: Optional[str] = None,
):
    db = get_db()
    _, unmatched = await _build_view(db, account_id, search, None)
    fn = f"missing_live_skus_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return _to_excel(_rows_to_export(unmatched), "Missing", fn)
