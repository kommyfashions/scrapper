"""Meesho Live Inventory scraper — job type: `inventory_sync`.

URL:  https://supplier.meesho.com/panel/v3/new/services/<suffix>/inventory

Approach (defensive — no IndexError on virtualized lists):
  1. Open Inventory page, ensure the "Active" tab is selected.
  2. On each pagination page, snapshot the LEFT rail catalog cards by
     extracting their text (name + Catalog ID + Category) as a stable
     de-duped list.
  3. For each unique Catalog ID:
        a. Click the card whose text CONTAINS that Catalog ID.
        b. Wait for the right pane to render "Style ID:" text.
        c. Read every SKU block visible in the right pane.
  4. Click pagination Next; stop when disabled or unchanged.

We NEVER index by ordinal position across DOM refreshes — always find by
Catalog ID text. That eliminates the IndexError seen in the previous
implementation.

Return dict merged into the job:
    {catalogs_scanned, skus_captured, pages_visited, note}
"""
from __future__ import annotations

import os
import re
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from _meesho_ui import cdp_context_page
from playwright.sync_api import Page, TimeoutError as PWTimeout  # noqa: F401
from pymongo import MongoClient

MONEY_RE = re.compile(r"[\d,]+(?:\.\d+)?")
PAGE_LOAD_MS = 45_000


def _inventory_url(suffix: str) -> str:
    return (f"https://supplier.meesho.com/panel/v3/new/services/{suffix}"
            f"/inventory")


def _safe_text(node, timeout_ms: int = 1500) -> str:
    try:
        return (node.inner_text(timeout=timeout_ms) or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _first_number(s: str) -> Optional[float]:
    m = MONEY_RE.search(s or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except Exception:  # noqa: BLE001
        return None


def _select_active_tab(page: Page) -> None:
    for label in ("Active", "ACTIVE"):
        try:
            loc = page.locator(f'xpath=//*[normalize-space(text())="{label}"]').first
            if loc.count() > 0 and loc.is_visible(timeout=1500):
                loc.click(timeout=3000)
                page.wait_for_timeout(1500)
                return
        except Exception:  # noqa: BLE001
            continue


def _snapshot_catalog_ids(page: Page) -> List[Dict[str, str]]:
    """Return a de-duped list of catalog metadata visible in the left rail.
    Each item: {name, catalog_id, category}. Ordered top-to-bottom."""
    out: List[Dict[str, str]] = []
    seen: Set[str] = set()
    try:
        cards = page.locator(
            'xpath=//*[contains(normalize-space(.), "Catalog ID:") and '
            'contains(normalize-space(.), "Category:")]'
        )
        n = cards.count()
    except Exception:  # noqa: BLE001
        return out
    for i in range(n):
        try:
            text = _safe_text(cards.nth(i))
        except Exception:  # noqa: BLE001
            continue
        if not text:
            continue
        name = ""
        cid = ""
        cat = ""
        for line in [ln.strip() for ln in text.splitlines() if ln.strip()]:
            low = line.lower()
            if low.startswith("catalog id"):
                cid = line.split(":", 1)[1].strip()
            elif low.startswith("category"):
                cat = line.split(":", 1)[1].strip()
            elif not name:
                name = line
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append({"name": name, "catalog_id": cid, "category": cat})
    return out


def _click_catalog_by_id(page: Page, catalog_id: str) -> bool:
    """Find and click the catalog card containing this Catalog ID text."""
    for _ in range(3):
        try:
            card = page.locator(
                f'xpath=//*[contains(normalize-space(.), "Catalog ID:") '
                f'and contains(normalize-space(.), "{catalog_id}")]'
            ).first
            if card.count() == 0:
                page.wait_for_timeout(400)
                continue
            card.scroll_into_view_if_needed(timeout=2000)
            card.click(timeout=3000)
            page.wait_for_timeout(1000)
            return True
        except Exception:  # noqa: BLE001
            page.wait_for_timeout(400)
    return False


def _extract_skus_from_right_pane(
    page: Page, catalog: Dict[str, str],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        page.wait_for_selector(
            'xpath=//*[contains(normalize-space(.), "Style ID")]',
            timeout=8_000,
        )
    except PWTimeout:
        return rows
    except Exception:  # noqa: BLE001
        return rows

    try:
        blocks = page.locator(
            'xpath=//*[contains(normalize-space(.), "Style ID:") and '
            'contains(normalize-space(.), "SKU:") and '
            'contains(normalize-space(.), "Meesho Price")]'
        )
        n = blocks.count()
    except Exception:  # noqa: BLE001
        return rows

    for i in range(n):
        try:
            text = _safe_text(blocks.nth(i))
        except Exception:  # noqa: BLE001
            continue
        if not text:
            continue
        style_id = None
        sku = None
        price = None
        for line in [ln.strip() for ln in text.splitlines() if ln.strip()]:
            low = line.lower()
            if low.startswith("style id"):
                style_id = line.split(":", 1)[1].strip()
            elif low.startswith("sku"):
                sku = line.split(":", 1)[1].strip()
            elif "meesho price" in low:
                price = _first_number(line.split(":", 1)[-1])
        if not sku:
            continue
        variation = None
        try:
            row_container = blocks.nth(i).locator(
                'xpath=ancestor::*[self::tr or (@role="row")][1]').first
            row_text = _safe_text(row_container)
        except Exception:  # noqa: BLE001
            row_text = ""
        m = re.search(
            r"\b(IND-\d+|S|M|L|XL|XXL|XXXL|Free\s*Size)\b",
            row_text, re.IGNORECASE,
        )
        if m:
            variation = m.group(1).upper().replace(" ", "")
        rows.append({
            "catalog_id": catalog["catalog_id"],
            "catalog_name": catalog["name"],
            "category": catalog["category"],
            "style_id": style_id or sku,
            "sku": sku,
            "variation": variation,
            "price": price,
            "current_stock": None,
        })
    return rows


def _click_next_page(page: Page) -> bool:
    try:
        btn = page.locator('button[aria-label="Go to next page"]').first
        if btn.count() == 0:
            return False
        if not btn.is_visible(timeout=1500):
            return False
        if btn.is_disabled(timeout=1500):
            return False
        btn.click(timeout=3000)
        page.wait_for_timeout(1500)
        return True
    except Exception:  # noqa: BLE001
        return False


def run_inventory_sync_for_account(acc: dict, payload: dict) -> Dict[str, Any]:
    port = int(acc["debug_port"])
    suffix = (acc.get("name") or "").strip()
    if not suffix:
        raise RuntimeError("account has no `name` — cannot derive URL suffix")

    account_id = str(acc["_id"])
    account_name = acc.get("name")
    all_rows: List[Dict[str, Any]] = []
    catalogs_scanned = 0
    pages_visited = 0
    seen_catalog_ids: Set[str] = set()

    p, _browser, _ctx, page = cdp_context_page(port)
    try:
        page.goto(_inventory_url(suffix),
                  wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:  # noqa: BLE001
            pass
        _select_active_tab(page)
        page.wait_for_timeout(1500)

        MAX_PAGES = 100
        while pages_visited < MAX_PAGES:
            pages_visited += 1
            snapshot = _snapshot_catalog_ids(page)
            print(f"[inv_sync] page {pages_visited}: "
                  f"{len(snapshot)} catalogs snapshotted")
            for cat in snapshot:
                cid = cat["catalog_id"]
                if cid in seen_catalog_ids:
                    continue
                seen_catalog_ids.add(cid)
                if not _click_catalog_by_id(page, cid):
                    continue
                rows = _extract_skus_from_right_pane(page, cat)
                for r in rows:
                    r["account_id"] = account_id
                    r["account_name"] = account_name
                all_rows.extend(rows)
                catalogs_scanned += 1
                time.sleep(0.4)
            if not _click_next_page(page):
                break
    finally:
        try:
            page.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            p.stop()
        except Exception:  # noqa: BLE001
            pass

    # persist — atomic replace for this account
    mongo_url = os.environ.get("MESHO_MONGO_URI") or os.environ.get(
        "MONGO_URL", "mongodb://127.0.0.1:27017/")
    db_name = os.environ.get("MESHO_DB_NAME") or os.environ.get(
        "DB_NAME", "meesho")
    now = datetime.now(timezone.utc)
    try:
        client = MongoClient(mongo_url)
        db = client[db_name]
        db.meesho_live_skus.delete_many({"account_id": account_id})
        if all_rows:
            for r in all_rows:
                r["synced_at"] = now
            db.meesho_live_skus.insert_many(all_rows, ordered=False)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        raise RuntimeError(f"persist failed: {e}")

    return {
        "catalogs_scanned": catalogs_scanned,
        "skus_captured": len(all_rows),
        "pages_visited": pages_visited,
        "note": "" if all_rows else "0 rows captured — DOM selectors may need tuning for this account",
    }
