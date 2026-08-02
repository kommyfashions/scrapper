"""Product Master endpoints (`/api/pm/...`).

Single-source-of-truth CRUD, Excel upload (dry-run + commit), export, template.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from services.product_master import (
    REQUIRED_COLUMNS,
    build_upload_plan,
    bulk_hydrate_products,
    commit_upload,
    parse_excel,
    resolve_accounts,
)

router = APIRouter(prefix="/pm", tags=["product-master"])


# --- injected by server.py via `configure(db, auth_dep)` ------------
_db = None
_auth = None


def configure(db, auth_dep):
    """Wire the router to the app's Motor DB + JWT auth dependency."""
    global _db, _auth
    _db = db
    _auth = auth_dep


def get_db():
    if _db is None:
        raise RuntimeError("product_master router not configured")
    return _db


async def _require_user(request):
    """FastAPI dependency shim — delegates to the app's JWT verifier."""
    if _auth is None:
        raise HTTPException(status_code=500,
                            detail="Auth dependency not configured")
    return await _auth(request)


def user_dep():
    from fastapi import Request

    async def _dep(request: Request):
        return await _require_user(request)
    return _dep


# ------------- Pydantic models -------------
class ProductIn(BaseModel):
    account_id: str
    main_category: str
    color: str
    cost_price: float = Field(ge=0)
    skus: List[str] = []
    sizes: List[str] = []
    extra: Dict[str, Any] = {}


class ProductUpdate(BaseModel):
    account_id: Optional[str] = None
    main_category: Optional[str] = None
    color: Optional[str] = None
    cost_price: Optional[float] = Field(default=None, ge=0)
    skus: Optional[List[str]] = None
    sizes: Optional[List[str]] = None
    extra: Optional[Dict[str, Any]] = None


class BulkDeleteIn(BaseModel):
    ids: List[str]


class CommitIn(BaseModel):
    """Payload from FE after user reviewed the dry-run."""
    parse_token: str
    upload_source: str = "excel-upload"


# In-memory cache for parsed uploads awaiting confirmation.
# Keyed by short token; cleared on commit or after 30 minutes.
_pending_uploads: Dict[str, Dict[str, Any]] = {}


def _oid_or_400(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


async def _serialize(p: dict, db) -> dict:
    return {
        "id": str(p["_id"]),
        "account_id": p.get("account_id"),
        "main_category": p.get("main_category"),
        "color": p.get("color"),
        "cost_price": float(p.get("cost_price") or 0),
        "skus": p.get("skus", []),
        "sizes": p.get("sizes", []),
        "extra": p.get("extra") or {},
        "created_at": (p.get("created_at").isoformat().replace("+00:00", "Z")
                       if isinstance(p.get("created_at"), datetime) else None),
        "updated_at": (p.get("updated_at").isoformat().replace("+00:00", "Z")
                       if isinstance(p.get("updated_at"), datetime) else None),
        "created_by": p.get("created_by"),
        "updated_by": p.get("updated_by"),
        "upload_source": p.get("upload_source"),
    }


# =========================================================================== #
# LIST / SEARCH / FILTER / SORT
# =========================================================================== #
@router.get("/products")
async def list_products(
    q: Optional[str] = None,
    account_id: Optional[str] = None,
    main_category: Optional[str] = None,
    color: Optional[str] = None,
    cost_min: Optional[float] = None,
    cost_max: Optional[float] = None,
    has_sku: Optional[bool] = None,
    has_cost: Optional[bool] = None,
    sort: str = Query("updated_at",
                      pattern="^(main_category|color|account|cost_price|updated_at|created_at)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    db = get_db()
    filt: Dict[str, Any] = {}
    if account_id and account_id != "all":
        filt["account_id"] = account_id
    if main_category:
        filt["main_category"] = main_category
    if color:
        filt["color"] = color
    if cost_min is not None or cost_max is not None:
        cf: Dict[str, Any] = {}
        if cost_min is not None:
            cf["$gte"] = float(cost_min)
        if cost_max is not None:
            cf["$lte"] = float(cost_max)
        filt["cost_price"] = cf
    if has_cost is False:
        filt["$or"] = [{"cost_price": {"$exists": False}},
                       {"cost_price": None}, {"cost_price": 0}]

    # Text search: SKU / Category / Color / Cost.
    # SKU requires joining product_skus.
    if q:
        needle = q.strip()
        if needle:
            regex = {"$regex": needle, "$options": "i"}
            # Products matching category/color directly
            or_clauses = [{"main_category": regex}, {"color": regex}]
            # Account name/alias match → resolve to account_ids
            acc_ids = []
            async for a in db.accounts.find(
                {"$or": [{"name": regex}, {"alias": regex}]},
                {"_id": 1},
            ):
                acc_ids.append(str(a["_id"]))
            if acc_ids:
                or_clauses.append({"account_id": {"$in": acc_ids}})
            # SKU match → product_ids
            sku_pids = set()
            async for s in db.pm_skus.find({"sku": regex},
                                                {"product_id": 1}):
                sku_pids.add(s["product_id"])
            if sku_pids:
                or_clauses.append({"_id": {"$in": list(sku_pids)}})
            # Cost equals numeric needle
            try:
                needle_num = float(needle.replace(",", ""))
                or_clauses.append({"cost_price": needle_num})
            except ValueError:
                pass
            filt.setdefault("$and", []).append({"$or": or_clauses})

    # has_sku filter — needs product_skus
    if has_sku is not None:
        pids_with_sku = set()
        async for s in db.pm_skus.find({}, {"product_id": 1}):
            pids_with_sku.add(s["product_id"])
        if has_sku:
            filt.setdefault("$and", []).append(
                {"_id": {"$in": list(pids_with_sku)}})
        else:
            filt.setdefault("$and", []).append(
                {"_id": {"$nin": list(pids_with_sku)}})

    sort_field = {"main_category": "main_category",
                  "color": "color",
                  "account": "account_id",
                  "cost_price": "cost_price",
                  "updated_at": "updated_at",
                  "created_at": "created_at"}[sort]
    sort_dir = 1 if order == "asc" else -1

    total = await db.pm_products.count_documents(filt)
    cursor = (db.pm_products.find(filt)
              .sort(sort_field, sort_dir)
              .skip((page - 1) * page_size)
              .limit(page_size))
    docs = [d async for d in cursor]
    await bulk_hydrate_products(db, docs)

    # Attach account names
    acc_ids = list({d["account_id"] for d in docs if d.get("account_id")})
    acc_lookup: Dict[str, dict] = {}
    if acc_ids:
        oids = []
        for a in acc_ids:
            try:
                oids.append(ObjectId(a))
            except Exception:
                continue
        async for a in db.accounts.find(
            {"_id": {"$in": oids}},
            {"_id": 1, "name": 1, "alias": 1},
        ):
            acc_lookup[str(a["_id"])] = {
                "name": a.get("name"), "alias": a.get("alias"),
            }
    items = []
    for d in docs:
        row = await _serialize(d, db)
        info = acc_lookup.get(row["account_id"], {})
        row["account_name"] = info.get("name")
        row["account_alias"] = info.get("alias")
        items.append(row)
    return {"items": items, "total": total, "page": page,
            "page_size": page_size}


@router.get("/facets")
async def list_facets():
    """Distinct categories, colors, accounts for filter dropdowns."""
    db = get_db()
    categories = await db.pm_products.distinct("main_category")
    colors = await db.pm_products.distinct("color")
    accounts = []
    async for a in db.accounts.find({}, {"_id": 1, "name": 1, "alias": 1}):
        accounts.append({"id": str(a["_id"]),
                         "name": a.get("name"),
                         "alias": a.get("alias")})
    return {
        "categories": sorted([c for c in categories if c]),
        "colors": sorted([c for c in colors if c]),
        "accounts": accounts,
    }


# =========================================================================== #
# CREATE / UPDATE / DELETE
# =========================================================================== #
async def _validate_business_key(db, account_id, cat, color, exclude_id=None):
    q = {"account_id": account_id, "main_category": cat, "color": color}
    if exclude_id is not None:
        q["_id"] = {"$ne": exclude_id}
    dup = await db.pm_products.find_one(q, {"_id": 1})
    if dup:
        raise HTTPException(
            status_code=409,
            detail=f"Product already exists for {cat}/{color} on this account",
        )


async def _apply_children(db, product_id, account_id, skus, sizes):
    if sizes is not None:
        await db.pm_sizes.delete_many({"product_id": product_id})
        cleaned = [s.strip() for s in sizes if s and s.strip()]
        if cleaned:
            await db.pm_sizes.insert_many(
                [{"product_id": product_id, "size": s} for s in cleaned])
    if skus is not None:
        # Detach these SKUs from any other product
        cleaned = [s.strip() for s in skus if s and s.strip()]
        if cleaned:
            await db.pm_skus.delete_many({
                "account_id": account_id, "sku": {"$in": cleaned},
            })
        await db.pm_skus.delete_many({"product_id": product_id})
        if cleaned:
            await db.pm_skus.insert_many([
                {"product_id": product_id, "account_id": account_id, "sku": s}
                for s in cleaned
            ])


@router.post("/products")
async def create_product(body: ProductIn):
    db = get_db()
    _oid_or_400(body.account_id)
    acc = await db.accounts.find_one({"_id": ObjectId(body.account_id)})
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    cat = body.main_category.strip()
    color = body.color.strip()
    if not cat or not color:
        raise HTTPException(status_code=400,
                            detail="main_category and color required")
    await _validate_business_key(db, body.account_id, cat, color)
    now = datetime.now(timezone.utc)
    doc = {
        "account_id": body.account_id,
        "main_category": cat, "color": color,
        "cost_price": float(body.cost_price),
        "extra": body.extra or {},
        "created_at": now, "updated_at": now,
        "created_by": "api", "updated_by": "api",
        "upload_source": "manual",
    }
    res = await db.pm_products.insert_one(doc)
    await _apply_children(db, res.inserted_id, body.account_id,
                          body.skus, body.sizes)
    doc["_id"] = res.inserted_id
    await bulk_hydrate_products(db, [doc])
    return {"ok": True, "product": await _serialize(doc, db)}


@router.put("/products/{product_id}")
async def update_product(product_id: str, body: ProductUpdate):
    db = get_db()
    oid = _oid_or_400(product_id)
    ex = await db.pm_products.find_one({"_id": oid})
    if not ex:
        raise HTTPException(status_code=404, detail="Product not found")

    aid = body.account_id or ex["account_id"]
    cat = (body.main_category or ex["main_category"]).strip()
    color = (body.color or ex["color"]).strip()
    if body.account_id or body.main_category or body.color:
        await _validate_business_key(db, aid, cat, color, exclude_id=oid)

    upd: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if body.account_id is not None:
        upd["account_id"] = aid
    if body.main_category is not None:
        upd["main_category"] = cat
    if body.color is not None:
        upd["color"] = color
    if body.cost_price is not None:
        upd["cost_price"] = float(body.cost_price)
    if body.extra is not None:
        upd["extra"] = body.extra
    upd["updated_by"] = "api"
    await db.pm_products.update_one({"_id": oid}, {"$set": upd})

    if body.skus is not None or body.sizes is not None:
        await _apply_children(db, oid, aid, body.skus, body.sizes)

    doc = await db.pm_products.find_one({"_id": oid})
    await bulk_hydrate_products(db, [doc])
    return {"ok": True, "product": await _serialize(doc, db)}


@router.delete("/products/{product_id}")
async def delete_product(product_id: str):
    db = get_db()
    oid = _oid_or_400(product_id)
    ex = await db.pm_products.find_one({"_id": oid})
    if not ex:
        raise HTTPException(status_code=404, detail="Product not found")
    await db.pm_skus.delete_many({"product_id": oid})
    await db.pm_sizes.delete_many({"product_id": oid})
    await db.pm_products.delete_one({"_id": oid})
    return {"ok": True}


@router.post("/products/bulk-delete")
async def bulk_delete(body: BulkDeleteIn):
    db = get_db()
    oids = []
    for i in body.ids:
        try:
            oids.append(ObjectId(i))
        except Exception:
            continue
    if not oids:
        return {"ok": True, "deleted": 0}
    await db.pm_skus.delete_many({"product_id": {"$in": oids}})
    await db.pm_sizes.delete_many({"product_id": {"$in": oids}})
    res = await db.pm_products.delete_many({"_id": {"$in": oids}})
    return {"ok": True, "deleted": res.deleted_count}


# =========================================================================== #
# EXCEL: template / upload (dry-run) / commit / export
# =========================================================================== #
@router.get("/template")
async def download_template():
    df = pd.DataFrame(columns=REQUIRED_COLUMNS)
    sample = [
        ["Account1", "Vertis", "Blue", "IND-3,IND-4,IND-5", "SKU1,SKU2,SKU3", 110],
        ["Account1", "Vertis", "Black", "IND-3,IND-4", "SKU4", 110],
        ["Account2", "Vertis", "Grey", "IND-6,IND-7", "SKU7,SKU8", 115],
    ]
    df = pd.DataFrame(sample, columns=REQUIRED_COLUMNS)
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Product Master")
    out.seek(0)
    fn = "product_master_template.xlsx"
    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fn}"},
    )


def _stash(rows, acc_map, errors) -> str:
    import secrets
    tok = secrets.token_urlsafe(12)
    # prune old tokens (>30 min)
    cutoff = datetime.now(timezone.utc).timestamp() - 30 * 60
    stale = [k for k, v in _pending_uploads.items() if v["ts"] < cutoff]
    for k in stale:
        _pending_uploads.pop(k, None)
    _pending_uploads[tok] = {
        "rows": rows, "acc_map": acc_map, "errors": errors,
        "ts": datetime.now(timezone.utc).timestamp(),
    }
    return tok


@router.post("/upload")
async def upload_excel(
    skip_confirmation: bool = Query(False),
    file: UploadFile = File(...),
):
    """Parse Excel → dry-run plan (or immediate commit if skip_confirmation)."""
    db = get_db()
    contents = await file.read()
    rows, errors = parse_excel(contents)
    plan = await build_upload_plan(db, rows)
    plan["errors"] = errors

    if skip_confirmation:
        result = await commit_upload(
            db, rows, plan["acc_map"],
            actor_email="upload",
            upload_source=file.filename or "excel-upload",
        )
        plan.pop("acc_map", None)
        return {
            "committed": True,
            "result": result,
            "plan": plan,
        }

    # Otherwise stash the parsed rows and return the plan for review
    token = _stash(rows, plan["acc_map"], errors)
    plan.pop("acc_map", None)
    return {
        "committed": False,
        "parse_token": token,
        "plan": plan,
    }


@router.post("/upload/commit")
async def commit_stashed(body: CommitIn):
    """Second step after user reviewed the dry-run."""
    db = get_db()
    stash = _pending_uploads.pop(body.parse_token, None)
    if not stash:
        raise HTTPException(
            status_code=404,
            detail="Upload token expired or invalid. Please re-upload.",
        )
    result = await commit_upload(
        db, stash["rows"], stash["acc_map"],
        actor_email="upload",
        upload_source=body.upload_source,
    )
    return {"committed": True, "result": result,
            "errors": stash.get("errors", [])}


@router.get("/export")
async def export_products(
    q: Optional[str] = None,
    account_id: Optional[str] = None,
    main_category: Optional[str] = None,
    color: Optional[str] = None,
    has_sku: Optional[bool] = None,
    has_cost: Optional[bool] = None,
):
    """Export current filtered view to Excel matching the upload format."""
    db = get_db()
    # Reuse list_products with a huge page_size — simpler than re-filtering.
    resp = await list_products(
        q=q, account_id=account_id, main_category=main_category,
        color=color, has_sku=has_sku, has_cost=has_cost,
        sort="main_category", order="asc",
        page=1, page_size=100000,
    )
    rows = []
    for p in resp["items"]:
        rows.append({
            "Account": p.get("account_alias") or p.get("account_name") or "",
            "Main Category": p.get("main_category"),
            "Color": p.get("color"),
            "Size": ",".join(p.get("sizes") or []),
            "SKU": ",".join(p.get("skus") or []),
            "Cost": p.get("cost_price"),
        })
    if not rows:
        rows = [{c: "" for c in REQUIRED_COLUMNS}]
    df = pd.DataFrame(rows, columns=REQUIRED_COLUMNS)
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Product Master")
    out.seek(0)
    fn = f"product_master_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fn}"},
    )


# =========================================================================== #
# ADMIN: wipe legacy data
# =========================================================================== #
@router.post("/admin/wipe-legacy")
async def wipe_legacy():
    """Delete legacy articles / article_sku_map / pl_sku_costs collections.
    Product Master becomes the sole source after this. Idempotent."""
    db = get_db()
    ops = {
        "articles": await db.articles.delete_many({}),
        "article_sku_map": await db.article_sku_map.delete_many({}),
        "pl_sku_costs": await db.pl_sku_costs.delete_many({}),
    }
    return {"ok": True,
            "deleted": {k: v.deleted_count for k, v in ops.items()}}
