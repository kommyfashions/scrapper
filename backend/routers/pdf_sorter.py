"""PDF Sorter endpoints (`/api/pdf-sorter/...`).

Independent of Product Master (per user requirement §20).
Uses its own SKU normalization + courier rules stored in Mongo.
"""
from __future__ import annotations

import io
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from services.pdf_sorter import (
    OUTPUT_DIR, UPLOAD_DIR, process_pdfs,
)

router = APIRouter(prefix="/pdf-sorter", tags=["pdf-sorter"])

_db = None


def configure(db):
    global _db
    _db = db


def get_db():
    if _db is None:
        raise RuntimeError("pdf-sorter router not configured")
    return _db


class SkuNormRow(BaseModel):
    raw_sku: str
    normalized_sku: str


class CourierRuleRow(BaseModel):
    courier_name: str
    match_text: str


# ---------- Config ----------
@router.get("/config")
async def get_config():
    db = get_db()
    sku_rows = [{k: v for k, v in x.items() if k != "_id"}
                async for x in db.sku_normalization.find({}, {"_id": 0})]
    courier_rows = [{k: v for k, v in x.items() if k != "_id"}
                     async for x in db.courier_rules.find({}, {"_id": 0})]
    return {"sku_normalization": sku_rows, "courier_rules": courier_rows}


@router.post("/config/sku")
async def upsert_sku(body: SkuNormRow):
    db = get_db()
    raw = body.raw_sku.strip()
    norm = body.normalized_sku.strip()
    if not raw or not norm:
        raise HTTPException(status_code=400,
                            detail="raw_sku and normalized_sku required")
    await db.sku_normalization.update_one(
        {"raw_sku": raw},
        {"$set": {"raw_sku": raw, "normalized_sku": norm,
                  "updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return {"ok": True}


@router.delete("/config/sku/{raw_sku}")
async def delete_sku(raw_sku: str):
    db = get_db()
    await db.sku_normalization.delete_one({"raw_sku": raw_sku})
    return {"ok": True}


@router.post("/config/courier")
async def upsert_courier(body: CourierRuleRow):
    db = get_db()
    name = body.courier_name.strip()
    text = body.match_text.strip()
    if not name or not text:
        raise HTTPException(
            status_code=400,
            detail="courier_name and match_text required",
        )
    await db.courier_rules.update_one(
        {"courier_name": name},
        {"$set": {"courier_name": name, "match_text": text,
                  "updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return {"ok": True}


@router.delete("/config/courier/{courier_name}")
async def delete_courier(courier_name: str):
    db = get_db()
    await db.courier_rules.delete_one({"courier_name": courier_name})
    return {"ok": True}


@router.post("/config/upload-sku-map")
async def upload_sku_map(file: UploadFile = File(...)):
    """Excel with columns: RawSKU | NormalizedSKU"""
    db = get_db()
    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400,
                            detail=f"Failed to read excel: {e}")
    df.columns = [str(c).strip() for c in df.columns]
    if "RawSKU" not in df.columns or "NormalizedSKU" not in df.columns:
        raise HTTPException(
            status_code=400,
            detail="Excel must have columns: RawSKU, NormalizedSKU",
        )
    upserts = 0
    for _, r in df.iterrows():
        raw = str(r["RawSKU"] or "").strip()
        norm = str(r["NormalizedSKU"] or "").strip()
        if not raw or not norm or raw.lower() == "nan":
            continue
        await db.sku_normalization.update_one(
            {"raw_sku": raw},
            {"$set": {"raw_sku": raw, "normalized_sku": norm,
                      "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        upserts += 1
    return {"ok": True, "upserted": upserts}


@router.post("/config/upload-courier-rules")
async def upload_courier_rules(file: UploadFile = File(...)):
    """Excel with columns: CourierName | MatchText"""
    db = get_db()
    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400,
                            detail=f"Failed to read excel: {e}")
    df.columns = [str(c).strip() for c in df.columns]
    if "CourierName" not in df.columns or "MatchText" not in df.columns:
        raise HTTPException(
            status_code=400,
            detail="Excel must have columns: CourierName, MatchText",
        )
    upserts = 0
    for _, r in df.iterrows():
        name = str(r["CourierName"] or "").strip()
        text = str(r["MatchText"] or "").strip()
        if not name or not text or name.lower() == "nan":
            continue
        await db.courier_rules.update_one(
            {"courier_name": name},
            {"$set": {"courier_name": name, "match_text": text,
                      "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        upserts += 1
    return {"ok": True, "upserted": upserts}


# ---------- Process ----------
@router.post("/process")
async def process(
    files: List[UploadFile] = File(...),
):
    """Sort PDFs by SKU using the Product Master. Upload PDFs from any/multi
    accounts in one batch — SKU matching is what groups them."""
    db = get_db()
    if not files:
        raise HTTPException(status_code=400, detail="no files uploaded")
    stamp = "IN_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    in_dir = UPLOAD_DIR / stamp
    in_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for f in files:
        if not f.filename or not f.filename.lower().endswith(".pdf"):
            continue
        target = in_dir / Path(f.filename).name
        with target.open("wb") as fh:
            shutil.copyfileobj(f.file, fh)
        paths.append(target)
    if not paths:
        raise HTTPException(status_code=400, detail="no valid PDF files")
    result = await process_pdfs(db, paths, account_id=None,
                                 actor_email="dashboard")
    return {
        "run_id": result.run_id,
        "total_files": result.total_files,
        "total_pages": result.total_pages,
        "unique_orders": result.unique_orders,
        "duplicates_skipped": result.duplicates_skipped,
        "unknown_sku": result.unknown_sku,
        "unknown_courier": result.unknown_courier,
        "sku_totals": result.sku_totals,
        "courier_totals": result.courier_totals,
        "size_totals": result.size_totals,
        "warnings": result.warnings,
        "files": result.files,
        "unmatched_skus": result.unmatched_skus,
    }


# ---------- Analytics ----------
@router.get("/analytics")
async def analytics(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    q: Optional[str] = None,
):
    """Aggregated view across all past runs.

    Filters:
      - start_date/end_date: 'YYYY-MM-DD' (inclusive, on run created_at)
      - q: text filter on SKU/product/courier keys (server-side, case-insens)
    """
    db = get_db()
    match: Dict[str, Any] = {}
    if start_date or end_date:
        cr: Dict[str, Any] = {}
        if start_date:
            cr["$gte"] = datetime.fromisoformat(start_date + "T00:00:00+00:00")
        if end_date:
            cr["$lte"] = datetime.fromisoformat(end_date + "T23:59:59+00:00")
        match["created_at"] = cr

    total_runs = 0
    total_pages = 0
    total_files = 0
    unique_orders = 0
    duplicates_skipped = 0
    unknown_sku_total = 0
    sku_totals: Dict[str, int] = {}
    courier_totals: Dict[str, int] = {}
    daily: Dict[str, int] = {}
    latest_run: Optional[Dict[str, Any]] = None
    async for r in db.pdf_sorter_runs.find(match).sort("created_at", -1):
        total_runs += 1
        total_pages += int(r.get("total_pages") or 0)
        total_files += int(r.get("total_files") or 0)
        unique_orders += int(r.get("unique_orders") or 0)
        duplicates_skipped += int(r.get("duplicates_skipped") or 0)
        unknown_sku_total += int(r.get("unknown_sku") or 0)
        for k, v in (r.get("sku_totals") or {}).items():
            sku_totals[k] = sku_totals.get(k, 0) + int(v or 0)
        for k, v in (r.get("courier_totals") or {}).items():
            courier_totals[k] = courier_totals.get(k, 0) + int(v or 0)
        d = r.get("created_at")
        if isinstance(d, datetime):
            key = d.strftime("%Y-%m-%d")
            daily[key] = daily.get(key, 0) + int(r.get("total_pages") or 0)
        if latest_run is None:
            latest_run = {
                "run_id": r.get("run_id"),
                "created_at": r["created_at"].isoformat().replace("+00:00", "Z")
                    if isinstance(r.get("created_at"), datetime) else None,
                "files": r.get("files") or [],
                "total_pages": r.get("total_pages") or 0,
                "sorted": (r.get("total_pages") or 0) - (r.get("unknown_sku") or 0),
                "unmatched": r.get("unknown_sku") or 0,
                "unique_orders": r.get("unique_orders") or 0,
                "input_files_count": r.get("total_files") or 0,
                "sku_totals": r.get("sku_totals") or {},
                "courier_totals": r.get("courier_totals") or {},
                "unmatched_skus": r.get("unmatched_skus") or [],
                "warnings": r.get("warnings") or [],
            }

    # Groups Filled X / Y — Y = distinct products in Product Master.
    # X = distinct products that had ≥1 label matched (across the window).
    y_total = await db.pm_products.estimated_document_count()
    matched_products = set()
    async for r in db.pdf_sorter_runs.find(match, {"product_ids": 1}):
        for pid in (r.get("product_ids") or []):
            matched_products.add(pid)
    groups_filled = len(matched_products)

    if q:
        needle = q.strip().lower()
        if needle:
            sku_totals = {k: v for k, v in sku_totals.items()
                          if needle in k.lower()}
            courier_totals = {k: v for k, v in courier_totals.items()
                              if needle in k.lower()}

    def _rows(d: Dict[str, int]) -> List[Dict[str, Any]]:
        return sorted(
            [{"name": k, "count": v} for k, v in d.items()],
            key=lambda x: -x["count"],
        )

    return {
        "total_runs": total_runs,
        "total_files": total_files,
        "total_pages": total_pages,
        "unique_orders": unique_orders,
        "duplicates_skipped": duplicates_skipped,
        "unknown_sku_total": unknown_sku_total,
        "groups_filled": groups_filled,
        "groups_total": y_total,
        "latest_run": latest_run,
        "sku_totals": _rows(sku_totals),
        "courier_totals": _rows(courier_totals),
        "daily_series": sorted(
            [{"date": k, "count": v} for k, v in daily.items()],
            key=lambda x: x["date"],
        ),
    }


@router.get("/recent-runs")
async def recent_runs(days: int = Query(7, ge=1, le=90)):
    """Runs in the last N days for the downloads history strip."""
    db = get_db()
    since = datetime.now(timezone.utc).timestamp() - days * 86400
    since_dt = datetime.fromtimestamp(since, tz=timezone.utc)
    rows = []
    async for r in db.pdf_sorter_runs.find(
        {"created_at": {"$gte": since_dt}},
        {"_id": 0, "run_id": 1, "created_at": 1, "total_pages": 1,
         "total_files": 1, "files": 1, "unknown_sku": 1, "unique_orders": 1},
    ).sort("created_at", -1):
        if isinstance(r.get("created_at"), datetime):
            r["created_at"] = r["created_at"].isoformat().replace(
                "+00:00", "Z")
        rows.append(r)
    return {"items": rows, "window_days": days}


@router.get("/runs")
async def list_runs(limit: int = Query(30, le=200)):
    db = get_db()
    rows = []
    async for r in db.pdf_sorter_runs.find(
        {}, {"_id": 0}
    ).sort("created_at", -1).limit(limit):
        if isinstance(r.get("created_at"), datetime):
            r["created_at"] = r["created_at"].isoformat().replace(
                "+00:00", "Z")
        rows.append(r)
    return {"items": rows}


@router.get("/runs/{run_id}/files/{filename}")
async def download(run_id: str, filename: str):
    # Basic path traversal guard
    safe = Path(filename).name
    fp = OUTPUT_DIR / run_id / safe
    if not fp.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    # Human-readable timestamp suffix — e.g.
    # TIER1_HIGH_VOLUME__2026-08-03_14-58-12.pdf
    stem = fp.stem
    suffix = fp.suffix
    ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    download_name = f"{stem}__{ts}{suffix}"
    return FileResponse(
        fp,
        filename=download_name,
        media_type="application/pdf",
        headers={
            # Force browsers to fetch fresh every click so re-downloads work.
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.post("/admin/reset")
async def admin_reset():
    """Wipe ALL past runs: DB history + uploads/ + outputs/ directories.
    Idempotent. Danger — intended for pre-production testing only."""
    import shutil as _sh
    db = get_db()
    deleted = await db.pdf_sorter_runs.delete_many({})
    for base in (UPLOAD_DIR, OUTPUT_DIR):
        try:
            for child in base.iterdir():
                if child.is_dir():
                    _sh.rmtree(child, ignore_errors=True)
        except Exception:
            continue
    return {"ok": True, "runs_deleted": deleted.deleted_count}
