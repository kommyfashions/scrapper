"""Product Master service.

Single source of truth for product metadata. Every module (SKU Cost, SKU
Analysis, Orders, Reports, PDF Sorter, …) reads from here.

Business uniqueness: (account_id, main_category, color).

Collections
-----------
products        one document per unique (account_id, main_category, color)
                {_id, account_id, main_category, color, cost_price,
                 extra: {...open-ended future fields...},
                 created_at, created_by, updated_at, updated_by,
                 upload_source}

product_skus    normalized child: (account_id, sku) → product_id
                unique index (account_id, sku)

product_sizes   normalized child: (product_id, size)
                index (product_id), (size)

Comma-separated Size/SKU in Excel are exploded into rows here.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from bson import ObjectId
from fastapi import HTTPException

# ---- Excel column contract (locked - do not change without user approval) ----
REQUIRED_COLUMNS = ["Account", "Main Category", "Color", "Size", "SKU", "Cost"]

SPLIT_RE = re.compile(r"[,\n;|]+")


def split_csv_field(raw: Any) -> List[str]:
    """Split comma-separated (or newline/semicolon/pipe) values, trim, dedupe
    while preserving order, drop empties."""
    if raw is None:
        return []
    if isinstance(raw, float) and pd.isna(raw):
        return []
    text = str(raw).strip()
    if not text or text.lower() == "nan":
        return []
    parts = [p.strip() for p in SPLIT_RE.split(text)]
    seen: set = set()
    out: List[str] = []
    for p in parts:
        if not p:
            continue
        # case-preserving dedupe (case-insensitive comparison)
        k = p.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def norm_key(s: Any) -> str:
    """Normalise business key components (account/category/color)."""
    if s is None:
        return ""
    if isinstance(s, float) and pd.isna(s):
        return ""
    t = str(s).strip()
    if t.lower() == "nan":
        return ""
    return t


def safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        if isinstance(v, float) and pd.isna(v):
            return None
        f = float(str(v).strip().replace(",", ""))
        return f
    except (ValueError, TypeError):
        return None


# ============================================================================ #
# Excel parsing
# ============================================================================ #
class ParsedRow(Dict[str, Any]):
    """Just a dict, aliased for readability."""


def parse_excel(contents: bytes) -> Tuple[List[ParsedRow], List[Dict[str, Any]]]:
    """Read Excel bytes → (rows, errors).
    Each row is a dict with keys: account, main_category, color, sizes[],
    skus[], cost, row_num (1-based Excel row).
    Errors are validation errors surfaced to the user."""
    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400,
                            detail=f"Failed to read Excel: {e}")
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required columns: {missing}. "
                   f"Expected exactly: {REQUIRED_COLUMNS}",
        )

    rows: List[ParsedRow] = []
    errors: List[Dict[str, Any]] = []
    for idx, r in df.iterrows():
        row_num = int(idx) + 2  # header is row 1 in Excel
        account = norm_key(r.get("Account"))
        main_cat = norm_key(r.get("Main Category"))
        color = norm_key(r.get("Color"))
        cost = safe_float(r.get("Cost"))
        sizes = split_csv_field(r.get("Size"))
        skus = split_csv_field(r.get("SKU"))

        row_errors = []
        if not account:
            row_errors.append("Missing Account")
        if not main_cat:
            row_errors.append("Missing Main Category")
        if not color:
            row_errors.append("Missing Color")
        if cost is None:
            row_errors.append("Invalid or missing Cost")
        elif cost < 0:
            row_errors.append("Cost cannot be negative")
        # sizes/skus may be empty — allowed. Just flagged in stats.

        if row_errors:
            errors.append({"row": row_num, "errors": row_errors})
            continue

        rows.append({
            "row_num": row_num,
            "account": account,
            "main_category": main_cat,
            "color": color,
            "sizes": sizes,
            "skus": skus,
            "cost": float(cost),
        })
    return rows, errors


# ============================================================================ #
# Upload plan (dry-run) & commit
# ============================================================================ #
async def resolve_accounts(db, account_names: List[str]) -> Dict[str, str]:
    """Map account alias/name (case-insensitive) → account _id (str).
    Raises 400 with the missing accounts list."""
    wanted = {n.lower() for n in account_names if n}
    if not wanted:
        return {}
    resolved: Dict[str, str] = {}
    async for a in db.accounts.find({}, {"_id": 1, "name": 1, "alias": 1}):
        aid = str(a["_id"])
        for k in (a.get("name"), a.get("alias")):
            if k and k.strip().lower() in wanted:
                resolved[k.strip().lower()] = aid
    return resolved


async def build_upload_plan(db, rows: List[ParsedRow]) -> Dict[str, Any]:
    """Compute inserts/updates/skips WITHOUT touching the DB.
    Returns a plan describing the outcome for the confirm step."""
    if not rows:
        return {"inserted": 0, "updated": 0, "skipped": 0,
                "sku_clashes": [], "unknown_accounts": [], "diffs": []}

    account_names = [r["account"] for r in rows]
    acc_map = await resolve_accounts(db, account_names)

    unknown = sorted({r["account"] for r in rows
                     if r["account"].lower() not in acc_map})

    # Fetch existing products for the (account, cat, color) triples in this batch
    triples = list({(acc_map.get(r["account"].lower()),
                     r["main_category"], r["color"]) for r in rows
                    if acc_map.get(r["account"].lower())})
    or_clauses = [
        {"account_id": t[0], "main_category": t[1], "color": t[2]}
        for t in triples
    ]
    existing: Dict[Tuple[str, str, str], dict] = {}
    if or_clauses:
        async for p in db.pm_products.find({"$or": or_clauses}):
            key = (p["account_id"], p["main_category"], p["color"])
            existing[key] = p

    existing_ids = [p["_id"] for p in existing.values()]

    # child collections for existing products
    existing_skus: Dict[Any, List[str]] = {}
    existing_sizes: Dict[Any, List[str]] = {}
    if existing_ids:
        async for s in db.pm_skus.find(
            {"product_id": {"$in": existing_ids}}, {"_id": 0}
        ):
            existing_skus.setdefault(s["product_id"], []).append(s["sku"])
        async for s in db.pm_sizes.find(
            {"product_id": {"$in": existing_ids}}, {"_id": 0}
        ):
            existing_sizes.setdefault(s["product_id"], []).append(s["size"])

    # Also fetch every SKU that already belongs to a *different* product than
    # the one we're about to write to (for SKU clash detection).
    incoming_skus_by_key: Dict[Tuple[str, str, str], List[str]] = {}
    for r in rows:
        aid = acc_map.get(r["account"].lower())
        if not aid:
            continue
        k = (aid, r["main_category"], r["color"])
        incoming_skus_by_key.setdefault(k, []).extend(r["skus"])

    sku_clashes: List[Dict[str, Any]] = []
    flat_skus = list({(aid, sku)
                      for (aid, _, _), skus in incoming_skus_by_key.items()
                      for sku in skus})
    if flat_skus:
        or_ = [{"account_id": a, "sku": s} for (a, s) in flat_skus]
        async for m in db.pm_skus.find({"$or": or_}, {"_id": 0}):
            # this sku already lives under some product; find which
            other = await db.pm_products.find_one(
                {"_id": m["product_id"]},
                {"main_category": 1, "color": 1, "account_id": 1},
            )
            if not other:
                continue
            owner_key = (other["account_id"],
                         other.get("main_category"),
                         other.get("color"))
            # Where does this SKU appear in the upload?
            for (aid, cat, color), skus in incoming_skus_by_key.items():
                if aid == m["account_id"] and m["sku"] in skus:
                    if (aid, cat, color) != owner_key:
                        sku_clashes.append({
                            "sku": m["sku"],
                            "account_id": aid,
                            "already_on": {
                                "main_category": other.get("main_category"),
                                "color": other.get("color"),
                            },
                            "attempting_to_move_to": {
                                "main_category": cat,
                                "color": color,
                            },
                        })

    inserted = updated = 0
    diffs: List[Dict[str, Any]] = []
    seen_keys: set = set()
    skipped = 0

    for r in rows:
        aid = acc_map.get(r["account"].lower())
        if not aid:
            continue
        key = (aid, r["main_category"], r["color"])
        if key in seen_keys:
            # duplicate row for same key inside the same upload → last wins,
            # but we still count it as "skipped" for transparency.
            skipped += 1
        seen_keys.add(key)

        ex = existing.get(key)
        if ex is None:
            inserted += 1
            diffs.append({
                "action": "insert",
                "account": r["account"], "account_id": aid,
                "main_category": r["main_category"], "color": r["color"],
                "cost_before": None, "cost_after": r["cost"],
                "sizes_before": [], "sizes_after": r["sizes"],
                "skus_before": [], "skus_after": r["skus"],
            })
        else:
            cost_before = float(ex.get("cost_price") or 0)
            sizes_before = sorted(existing_sizes.get(ex["_id"], []))
            skus_before = sorted(existing_skus.get(ex["_id"], []))
            sizes_after = sorted(r["sizes"])
            skus_after = sorted(r["skus"])
            if (cost_before == r["cost"]
                    and sizes_before == sizes_after
                    and skus_before == skus_after):
                # no-op update
                continue
            updated += 1
            diffs.append({
                "action": "update",
                "account": r["account"], "account_id": aid,
                "main_category": r["main_category"], "color": r["color"],
                "cost_before": cost_before, "cost_after": r["cost"],
                "sizes_before": sizes_before, "sizes_after": r["sizes"],
                "skus_before": skus_before, "skus_after": r["skus"],
            })

    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "total_rows": len(rows),
        "unknown_accounts": unknown,
        "sku_clashes": sku_clashes,
        "diffs": diffs[:500],   # cap payload size
        "acc_map": acc_map,     # returned so /commit can reuse it
    }


async def commit_upload(db, rows: List[ParsedRow], acc_map: Dict[str, str],
                        actor_email: str, upload_source: str = "excel-upload"
                        ) -> Dict[str, int]:
    """Apply the upload. SKU clashes trigger a re-parent (remove SKU from old
    product, add to new). This is destructive by design — user asked for
    upsert semantics."""
    now = datetime.now(timezone.utc)
    inserted = updated = skipped = 0

    for r in rows:
        aid = acc_map.get(r["account"].lower())
        if not aid:
            skipped += 1
            continue
        key = {"account_id": aid,
               "main_category": r["main_category"],
               "color": r["color"]}
        existing = await db.pm_products.find_one(key)
        if existing is None:
            doc = {
                **key,
                "cost_price": float(r["cost"]),
                "extra": {},
                "created_at": now, "updated_at": now,
                "created_by": actor_email, "updated_by": actor_email,
                "upload_source": upload_source,
            }
            res = await db.pm_products.insert_one(doc)
            pid = res.inserted_id
            inserted += 1
        else:
            pid = existing["_id"]
            await db.pm_products.update_one(
                {"_id": pid},
                {"$set": {
                    "cost_price": float(r["cost"]),
                    "updated_at": now,
                    "updated_by": actor_email,
                    "upload_source": upload_source,
                }},
            )
            updated += 1

        # Replace sizes for this product
        await db.pm_sizes.delete_many({"product_id": pid})
        if r["sizes"]:
            await db.pm_sizes.insert_many([
                {"product_id": pid, "size": s} for s in r["sizes"]
            ])

        # SKUs: re-parent any that live elsewhere, then replace
        if r["skus"]:
            # Detach these SKUs from any other product (they now belong here)
            await db.pm_skus.delete_many({
                "account_id": aid,
                "sku": {"$in": r["skus"]},
            })
        # Also wipe any previous SKUs of this product not in the new list
        await db.pm_skus.delete_many({"product_id": pid})
        if r["skus"]:
            await db.pm_skus.insert_many([
                {"product_id": pid, "account_id": aid, "sku": s}
                for s in r["skus"]
            ])

    return {"inserted": inserted, "updated": updated, "skipped": skipped}


# ============================================================================ #
# Read helpers (used by SKU Analysis / Orders / etc.)
# ============================================================================ #
async def load_cost_map(db) -> Dict[Tuple[str, str], float]:
    """(account_id, sku) → cost_price. O(products+skus) memory."""
    costs: Dict[Any, float] = {}
    async for p in db.pm_products.find({}, {"_id": 1, "cost_price": 1}):
        costs[p["_id"]] = float(p.get("cost_price") or 0)
    out: Dict[Tuple[str, str], float] = {}
    async for m in db.pm_skus.find({}, {"_id": 0}):
        price = costs.get(m.get("product_id"))
        if price is None:
            continue
        out[(m.get("account_id"), m.get("sku"))] = price
    return out


async def load_product_label_map(db) -> Dict[Tuple[str, str], Dict[str, str]]:
    """(account_id, sku) → {main_category, color}. For SKU-level enrichment."""
    labels: Dict[Any, Dict[str, str]] = {}
    async for p in db.pm_products.find(
        {}, {"_id": 1, "main_category": 1, "color": 1}
    ):
        labels[p["_id"]] = {
            "main_category": p.get("main_category"),
            "color": p.get("color"),
        }
    out: Dict[Tuple[str, str], Dict[str, str]] = {}
    async for m in db.pm_skus.find({}, {"_id": 0}):
        lbl = labels.get(m.get("product_id"))
        if not lbl:
            continue
        out[(m.get("account_id"), m.get("sku"))] = lbl
    return out


async def bulk_hydrate_products(db, products: List[dict]) -> List[dict]:
    """Attach `skus[]` and `sizes[]` to each product doc.
    Efficient: one $in query per child collection."""
    if not products:
        return []
    ids = [p["_id"] for p in products]
    skus_by: Dict[Any, List[str]] = {}
    sizes_by: Dict[Any, List[str]] = {}
    async for s in db.pm_skus.find(
        {"product_id": {"$in": ids}}, {"_id": 0}
    ):
        skus_by.setdefault(s["product_id"], []).append(s["sku"])
    async for s in db.pm_sizes.find(
        {"product_id": {"$in": ids}}, {"_id": 0}
    ):
        sizes_by.setdefault(s["product_id"], []).append(s["size"])

    for p in products:
        p["skus"] = sorted(skus_by.get(p["_id"], []))
        p["sizes"] = sorted(sizes_by.get(p["_id"], []),
                            key=lambda x: (len(x), x))
    return products
