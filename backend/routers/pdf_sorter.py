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
    account_id: Optional[str] = Query(None),
    files: List[UploadFile] = File(...),
):
    db = get_db()
    if not files:
        raise HTTPException(status_code=400, detail="no files uploaded")
    # Stash uploads under a fresh dir keyed by timestamp
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
    try:
        result = await process_pdfs(db, paths, account_id=account_id,
                                     actor_email="dashboard")
    finally:
        # keep input pdfs for a while for debugging; caller need not see them
        pass
    return {
        "run_id": result.run_id,
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
    }


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
    # basic path traversal guard
    safe = Path(filename).name
    fp = OUTPUT_DIR / run_id / safe
    if not fp.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(fp, filename=safe,
                        media_type="application/pdf")
