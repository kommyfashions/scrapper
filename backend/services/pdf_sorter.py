"""PDF Sorter service.

Ported (and cleaned) from kommyfashions/print. Bug fixes applied:
 - Order-No extraction + dedupe within a single run
 - Missing `import json` fixed (uses this module's own persistence)
 - No import-time Excel reads — SKU normalisation + courier rules read from
   MongoDB (`sku_normalization`, `courier_rules` collections)
 - Atomic writes: runs are self-contained; no global JSON state files
 - Per-account attribution
 - Warns when order is CANCELLED / RTO in `pl_orders` (surfaced via response)

Storage layout:
  /app/backend/pdf_sorter/uploads/<run_id>/*.pdf   # inbound
  /app/backend/pdf_sorter/outputs/<run_id>/*.pdf   # results
"""
from __future__ import annotations

import copy
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pdfplumber
from pypdf import PdfReader, PdfWriter

# ---- Config (kept in-service; no external env deps) -----------------------
BASE = Path("/app/backend/pdf_sorter")
UPLOAD_DIR = BASE / "uploads"
OUTPUT_DIR = BASE / "outputs"
TIER1_MIN_PAGES = 5

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _purge_old_runs(days: int = 7) -> None:
    """Delete run directories older than N days from both uploads/ and outputs/.
    Best-effort; failures are swallowed."""
    import shutil as _sh
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    for base in (UPLOAD_DIR, OUTPUT_DIR):
        try:
            for child in base.iterdir():
                if not child.is_dir():
                    continue
                try:
                    if child.stat().st_mtime < cutoff:
                        _sh.rmtree(child, ignore_errors=True)
                except Exception:
                    continue
        except Exception:
            continue


@dataclass
class PageMeta:
    reader_idx: int
    page_idx: int
    size: str
    sku_raw: str
    sku_norm: str
    courier: str
    order_no: Optional[str]
    file_name: str
    main_category: Optional[str] = None  # from Product Master; None if unmatched


@dataclass
class RunResult:
    run_id: str
    total_files: int
    total_pages: int
    unique_orders: int
    duplicates_skipped: int
    unknown_sku: int
    unknown_courier: int
    sku_totals: Dict[str, int] = field(default_factory=dict)
    courier_totals: Dict[str, int] = field(default_factory=dict)
    size_totals: Dict[str, int] = field(default_factory=dict)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    product_ids: List[str] = field(default_factory=list)
    unmatched_skus: List[Dict[str, Any]] = field(default_factory=list)
    tier1_pages: int = 0
    tier2_pages: int = 0
    tier1_categories: List[Dict[str, Any]] = field(default_factory=list)
    tier2_categories: List[Dict[str, Any]] = field(default_factory=list)


# ---- Regex helpers ---------------------------------------------------------
SKU_LINE_RE = re.compile(r"SKU Size Qty Color Order No\.?\s+(?P<rest>.+)",
                          re.IGNORECASE)
# Order number appears after color column; Meesho order numbers are alnum ~15+ chars
ORDER_NO_RE = re.compile(r"\b(\d{8,20}[_-]?\d{0,20})\b")
SIZE_TOKENS = ["XXS", "XS", "SM", "MD", "LG", "XL", "XXL", "3XL", "4XL", "5XL",
                "S", "M", "L"]


def _extract_size(rest: str) -> str:
    """Grab size token after SKU (best-effort)."""
    parts = rest.split()
    if len(parts) < 2:
        return ""
    # Numeric size (IND-3, 32, 42.5)
    tok = parts[1]
    if any(c.isdigit() for c in tok):
        return tok
    if tok.upper() in SIZE_TOKENS:
        return tok
    return tok


def _size_sort_key(size: str) -> Tuple[int, float, str]:
    nums = re.findall(r"\d+\.?\d*", size or "")
    if nums:
        return (0, float(nums[0]), size or "")
    return (1, 999.0, size or "")


# ---- Config loaders (Mongo-backed) ---------------------------------------
async def load_sku_normalisation(db) -> Dict[str, str]:
    """raw_sku -> normalized_sku. Reads from `sku_normalization` collection."""
    out: Dict[str, str] = {}
    async for m in db.sku_normalization.find({}, {"_id": 0}):
        raw = str(m.get("raw_sku") or "").strip()
        norm = str(m.get("normalized_sku") or "").strip()
        if raw and norm:
            out[raw] = norm
    return out


async def load_pm_sku_map(db) -> Dict[str, Dict[str, Any]]:
    """raw_sku → {product_id, main_category, color, group_label}.

    Product Master is the primary source of truth. Any label whose SKU is
    mapped here groups by (main_category / color).  Case-insensitive lookup.
    """
    products: Dict[Any, Dict[str, Any]] = {}
    async for p in db.pm_products.find(
        {}, {"_id": 1, "main_category": 1, "color": 1}
    ):
        products[p["_id"]] = {
            "main_category": p.get("main_category"),
            "color": p.get("color"),
        }
    out: Dict[str, Dict[str, Any]] = {}
    async for m in db.pm_skus.find({}, {"_id": 0}):
        prod = products.get(m.get("product_id"))
        if not prod:
            continue
        raw = str(m.get("sku") or "").strip()
        if not raw:
            continue
        label = f"{prod.get('main_category') or '-'} / {prod.get('color') or '-'}"
        out[raw.lower()] = {
            "product_id": str(m.get("product_id")),
            "main_category": prod.get("main_category"),
            "color": prod.get("color"),
            "group_label": label,
        }
    return out


async def load_courier_rules(db) -> List[Tuple[str, re.Pattern]]:
    """[(courier_name, compiled_regex), ...]"""
    rules: List[Tuple[str, re.Pattern]] = []
    async for m in db.courier_rules.find({}, {"_id": 0}):
        name = str(m.get("courier_name") or "").strip()
        pattern = str(m.get("match_text") or "").strip()
        if not name or not pattern:
            continue
        rules.append((name, re.compile(re.escape(pattern), re.IGNORECASE)))
    return rules


def _extract_courier(label_text: str, rules) -> str:
    for name, rgx in rules:
        if rgx.search(label_text):
            return name
    return "UNKNOWN"


# ---- Core processor -------------------------------------------------------
async def process_pdfs(
    db,
    pdf_paths: List[Path],
    account_id: Optional[str] = None,
    actor_email: str = "upload",
) -> RunResult:
    # Housekeeping: purge outputs older than 7 days on every run.
    _purge_old_runs(days=7)

    sku_map = await load_sku_normalisation(db)   # optional overrides
    pm_map = await load_pm_sku_map(db)            # primary source
    courier_rules = await load_courier_rules(db)

    readers: List[PdfReader] = []
    pages: List[PageMeta] = []
    seen_orders: set = set()
    duplicates_skipped = 0
    unknown_sku = 0
    unknown_courier = 0
    matched_pids: set = set()
    unmatched_counter: Dict[str, int] = {}

    for idx, pdf_path in enumerate(pdf_paths):
        readers.append(PdfReader(str(pdf_path)))
        with pdfplumber.open(pdf_path) as pdf:
            for p_idx, page in enumerate(pdf.pages):
                text = (page.extract_text() or "").replace("\n", " ")
                if "Product Details" not in text:
                    continue
                m = SKU_LINE_RE.search(text)
                if not m:
                    continue
                rest = m.group("rest")
                parts = rest.split()
                sku_raw = parts[0] if parts else ""
                # Lookup in Product Master first (case-insensitive); then
                # fall back to sku_normalization override; else use raw.
                pm_hit = pm_map.get(sku_raw.lower())
                if pm_hit:
                    sku_norm = pm_hit["group_label"]  # "Vertis / Blue"
                    main_cat = pm_hit.get("main_category")
                    is_known = True
                else:
                    override = sku_map.get(sku_raw)
                    sku_norm = override or sku_raw
                    main_cat = None
                    is_known = bool(override)
                size = _extract_size(rest)
                order_no_m = ORDER_NO_RE.search(rest)
                order_no = order_no_m.group(1) if order_no_m else None
                courier = _extract_courier(text, courier_rules)
                if not sku_raw:
                    continue
                if not is_known:
                    unknown_sku += 1
                if courier == "UNKNOWN":
                    unknown_courier += 1
                if order_no and order_no in seen_orders:
                    duplicates_skipped += 1
                    continue
                if order_no:
                    seen_orders.add(order_no)
                pages.append(PageMeta(
                    reader_idx=idx, page_idx=p_idx, size=size,
                    sku_raw=sku_raw, sku_norm=sku_norm,
                    courier=courier, order_no=order_no,
                    file_name=pdf_path.name,
                    main_category=main_cat,
                ))
                # Track matched product ids + unmatched raw SKUs
                if pm_hit:
                    matched_pids.add(pm_hit["product_id"])
                elif not is_known:
                    unmatched_counter[sku_raw] = unmatched_counter.get(sku_raw, 0) + 1

    # Cross-check against pl_orders — RTO / CANCELLED warnings
    warnings: List[Dict[str, Any]] = []
    if pages and account_id:
        order_nos = [p.order_no for p in pages if p.order_no]
        if order_nos:
            async for o in db.pl_orders.find({
                "account_id": account_id,
                "sub_order_no": {"$in": order_nos},
                "order_status": {"$in": ["CANCELLED", "RTO"]},
            }, {"_id": 0, "sub_order_no": 1, "order_status": 1}):
                warnings.append({
                    "order_no": o.get("sub_order_no"),
                    "status": o.get("order_status"),
                })

    # Group by normalized SKU (kept for stats / totals)
    by_sku: Dict[str, List[PageMeta]] = defaultdict(list)
    for pg in pages:
        by_sku[pg.sku_norm].append(pg)

    # NEW tier rule (Aug 2026): tier by MAIN CATEGORY.
    #   • Categories with >= TIER1_MIN_PAGES (5) go to Tier 1
    #   • Everything else (small categories + all unmatched pages) → Tier 2
    by_cat: Dict[str, List[PageMeta]] = defaultdict(list)
    unmatched_pages: List[PageMeta] = []
    for pg in pages:
        if pg.main_category:
            by_cat[pg.main_category].append(pg)
        else:
            unmatched_pages.append(pg)

    tier1_cats = {c: pgs for c, pgs in by_cat.items() if len(pgs) >= TIER1_MIN_PAGES}
    tier2_cats = {c: pgs for c, pgs in by_cat.items() if len(pgs) < TIER1_MIN_PAGES}
    tier1_sorted = sorted(tier1_cats.keys(), key=lambda k: -len(tier1_cats[k]))
    tier2_sorted = sorted(tier2_cats.keys())

    run_id = "RUN_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    master = PdfWriter()
    t1 = PdfWriter()
    t2 = PdfWriter()

    # ---- Tier 1: high-volume main categories ----
    # Sort pages within a category by (sku_norm, size) so identical products
    # stay adjacent; last page of each category is flipped 180° as separator.
    for cat in tier1_sorted:
        group = sorted(
            tier1_cats[cat],
            key=lambda x: (x.sku_norm or "", _size_sort_key(x.size)),
        )
        for i, pg in enumerate(group):
            original = readers[pg.reader_idx].pages[pg.page_idx]
            page1 = copy.copy(original)
            page2 = copy.copy(original)
            if i == len(group) - 1:  # flip last page as separator
                page1.rotate(180)
                page2.rotate(180)
            master.add_page(page1)
            t1.add_page(page2)

    # ---- Tier 2: small categories + all unmatched pages ----
    for cat in tier2_sorted:
        group = sorted(
            tier2_cats[cat],
            key=lambda x: (x.sku_norm or "", _size_sort_key(x.size)),
        )
        for pg in group:
            original = readers[pg.reader_idx].pages[pg.page_idx]
            master.add_page(copy.copy(original))
            t2.add_page(copy.copy(original))

    unmatched_pages_sorted = sorted(
        unmatched_pages, key=lambda x: (x.sku_raw or "", _size_sort_key(x.size))
    )
    for pg in unmatched_pages_sorted:
        original = readers[pg.reader_idx].pages[pg.page_idx]
        master.add_page(copy.copy(original))
        t2.add_page(copy.copy(original))

    files = []
    for fname, writer in [("MASTER_PRINT.pdf", master),
                           ("TIER1_HIGH_VOLUME.pdf", t1),
                           ("TIER2_LOW_VOLUME.pdf", t2)]:
        with (run_dir / fname).open("wb") as fh:
            writer.write(fh)
        files.append(fname)

    # Stats
    sku_totals: Dict[str, int] = defaultdict(int)
    courier_totals: Dict[str, int] = defaultdict(int)
    size_totals: Dict[str, int] = defaultdict(int)
    for pg in pages:
        sku_totals[pg.sku_norm] += 1
        courier_totals[pg.courier] += 1
        if pg.size:
            size_totals[pg.size] += 1

    unmatched_list = sorted(
        [{"sku": k, "count": v} for k, v in unmatched_counter.items()],
        key=lambda x: -x["count"],
    )

    # Tier stats
    tier1_page_count = sum(len(v) for v in tier1_cats.values())
    tier2_page_count = sum(len(v) for v in tier2_cats.values()) + len(unmatched_pages)
    tier1_summary = sorted(
        [{"main_category": c, "count": len(pgs)} for c, pgs in tier1_cats.items()],
        key=lambda x: -x["count"],
    )
    tier2_summary = sorted(
        [{"main_category": c, "count": len(pgs)} for c, pgs in tier2_cats.items()],
        key=lambda x: -x["count"],
    )
    if unmatched_pages:
        tier2_summary.append({
            "main_category": "Unmatched",
            "count": len(unmatched_pages),
        })

    result = RunResult(
        run_id=run_id,
        total_files=len(pdf_paths),
        total_pages=len(pages),
        unique_orders=len(seen_orders),
        duplicates_skipped=duplicates_skipped,
        unknown_sku=unknown_sku,
        unknown_courier=unknown_courier,
        sku_totals=dict(sku_totals),
        courier_totals=dict(courier_totals),
        size_totals=dict(size_totals),
        warnings=warnings,
        files=files,
        product_ids=list(matched_pids),
        unmatched_skus=unmatched_list,
        tier1_pages=tier1_page_count,
        tier2_pages=tier2_page_count,
        tier1_categories=tier1_summary,
        tier2_categories=tier2_summary,
    )

    # Persist run metadata for history views
    await db.pdf_sorter_runs.insert_one({
        "run_id": run_id,
        "account_id": account_id,
        "created_at": datetime.now(timezone.utc),
        "created_by": actor_email,
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
        "product_ids": result.product_ids,
        "unmatched_skus": result.unmatched_skus,
        "tier1_pages": result.tier1_pages,
        "tier2_pages": result.tier2_pages,
        "tier1_categories": result.tier1_categories,
        "tier2_categories": result.tier2_categories,
    })

    return result
