"""Meesho Live Inventory scraper — job type: `inventory_sync`.

Walks the Active tab (supplier.meesho.com/panel/v3/new/services/<suffix>
/inventory) and captures every visible (catalog, style_id, sku, size,
price, stock) row.

Approach:
  1. Open Inventory > Active tab, wait for "10 Items / page" pagination.
  2. For each pagination page (1..last):
       a. For each catalog card in the left rail:
          - Click the card. Wait for right pane to load SKU rows.
          - For each row, capture: SKU, Variation, Estimated Order, Stock,
            Style ID and Meesho Price (both shown under the SKU name).
       b. Scroll the LEFT rail (not the page) so more catalog cards render;
          the left rail uses infinite-scroll-within-page.
       c. Click "next page" once every catalog on the current page has been
          processed.
  3. Persist: bulk-replace the account's rows in `meesho_live_skus`.

Return dict merged into the job:
    {catalogs_scanned, skus_captured, pages_visited}
"""
from __future__ import annotations

import re
import time
import traceback
from typing import Any, Dict, List

from _meesho_ui import cdp_context_page
from playwright.sync_api import Page, TimeoutError as PWTimeout
from pymongo import MongoClient
import os

PAGE_LOAD_MS = 40_000
CARD_WAIT_MS = 10_000
ROW_WAIT_MS = 8_000

MONEY_RE = re.compile(r"[\d,]+(?:\.\d+)?")


def _inventory_url(suffix: str) -> str:
    return (f"https://supplier.meesho.com/panel/v3/new/services/{suffix}"
            f"/inventory")


def _txt(node, timeout_ms=2000) -> str:
    try:
        return (node.inner_text(timeout=timeout_ms) or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _int_or_none(s: str):
    m = MONEY_RE.search(s or "")
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", "").split(".")[0])
    except Exception:  # noqa: BLE001
        return None


def _float_or_none(s: str):
    m = MONEY_RE.search(s or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except Exception:  # noqa: BLE001
        return None


def _extract_rows_from_right_pane(page: Page,
                                   catalog_name: str,
                                   catalog_id: str,
                                   category: str) -> List[Dict[str, Any]]:
    """Scrape SKU rows from the currently-open catalog on the right pane.

    Each row shows: checkbox | SKU (multi-line with Style ID + SKU + Meesho
    Price) | Variation (IND-6) | Estimated Order | Stock | Actions.
    """
    rows: List[Dict[str, Any]] = []
    try:
        page.wait_for_selector(
            'xpath=//*[contains(normalize-space(.), "Style ID")]',
            timeout=ROW_WAIT_MS)
    except PWTimeout:
        return rows

    # Each SKU row is the closest ancestor container of the "Style ID:" text.
    # Meesho panel uses <div class="MuiBox-root ..."> — climb 4-5 levels.
    sku_blocks = page.locator(
        'xpath=//*[contains(normalize-space(.), "Style ID:") and '
        'contains(normalize-space(.), "SKU:") and '
        'contains(normalize-space(.), "Meesho Price")]'
    )
    n = sku_blocks.count()
    for i in range(n):
        blk = sku_blocks.nth(i)
        text = _txt(blk, timeout_ms=1500)
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
                price = _float_or_none(line.split(":", 1)[-1])
        if not sku:
            continue
        # variation & stock: climb to the enclosing row (tr or grid row)
        try:
            row_container = blk.locator(
                'xpath=ancestor::*[self::tr or (@role="row")][1]').first
            row_text = _txt(row_container, timeout_ms=1500)
        except Exception:  # noqa: BLE001
            row_text = ""
        variation = None
        m = re.search(r"\b(IND-\d+|S|M|L|XL|XXL|XXXL|Free\s*Size)\b",
                      row_text, re.IGNORECASE)
        if m:
            variation = m.group(1).upper().replace(" ", "")
        current_stock = None
        # look for a <input value="..."> near the row for current stock
        try:
            stock_input = row_container.locator(
                'input[type="text"], input[type="number"]').first
            v = stock_input.get_attribute("value", timeout=1000)
            current_stock = _int_or_none(v or "")
        except Exception:  # noqa: BLE001
            pass

        rows.append({
            "catalog_id": catalog_id,
            "catalog_name": catalog_name,
            "category": category,
            "style_id": style_id or sku,
            "sku": sku,
            "variation": variation,
            "price": price,
            "current_stock": current_stock,
        })
    return rows


def _left_rail_cards(page: Page):
    """The left rail holds catalog cards. Each card shows the catalog name,
    "Catalog ID:", and "Category:". Returns a locator handle."""
    return page.locator(
        'xpath=//*[contains(normalize-space(.), "Catalog ID:") and '
        'contains(normalize-space(.), "Category:")]'
    )


def _card_meta(card) -> Dict[str, str]:
    text = _txt(card, timeout_ms=1500)
    name = ""
    cid = ""
    cat = ""
    for line in [ln.strip() for ln in text.splitlines() if ln.strip()]:
        low = line.lower()
        if low.startswith("catalog id"):
            cid = line.split(":", 1)[1].strip()
        elif low.startswith("category"):
            cat = line.split(":", 1)[1].strip()
        else:
            if not name:
                name = line
    return {"name": name, "catalog_id": cid, "category": cat}


def _click_next_page(page: Page) -> bool:
    """Click the pagination next-page (▶) arrow. Returns False if disabled."""
    try:
        nxt = page.locator(
            'xpath=(//button[.//*[name()="svg"]][following-sibling::* or '
            'preceding-sibling::*])[last()]'
        ).first
        # Simpler: aria-label based
        nxt = page.locator('button[aria-label="Go to next page"]').first
        if not nxt.is_visible(timeout=1500):
            return False
        if nxt.is_disabled(timeout=1500):
            return False
        nxt.click()
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

    p, browser, _ctx, page = cdp_context_page(port)
    try:
        page.goto(_inventory_url(suffix),
                  wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except PWTimeout:
            pass
        # Ensure "Active" tab is selected
        try:
            page.locator(
                'xpath=//*[normalize-space(text())="Active"][1]'
            ).first.click(timeout=3000)
            page.wait_for_timeout(1500)
        except Exception:  # noqa: BLE001
            pass

        while True:
            pages_visited += 1
            cards = _left_rail_cards(page)
            card_count = cards.count()
            print(f"[inv_sync] page {pages_visited}: {card_count} catalog cards")
            for i in range(card_count):
                # re-fetch each iteration since DOM is virtualized
                cards2 = _left_rail_cards(page)
                if i >= cards2.count():
                    break
                card = cards2.nth(i)
                meta = _card_meta(card)
                try:
                    card.scroll_into_view_if_needed(timeout=2000)
                    card.click(timeout=3000)
                    page.wait_for_timeout(1000)
                except Exception:  # noqa: BLE001
                    continue
                rows = _extract_rows_from_right_pane(
                    page, meta["name"], meta["catalog_id"], meta["category"])
                for r in rows:
                    r["account_id"] = account_id
                    r["account_name"] = account_name
                all_rows.extend(rows)
                catalogs_scanned += 1
                time.sleep(0.4)
            if not _click_next_page(page):
                break
            # safety cap: hard stop at 100 pagination pages
            if pages_visited >= 100:
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
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "meesho")
    now = _now_utc()
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
    }


def _now_utc():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
