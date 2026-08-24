"""Meesho Live Inventory scraper — job type: `inventory_sync`.

FLOW (finalised with operator, Feb 2026):
  1. Load `https://supplier.meesho.com/panel/v3/new/services/{suffix}/inventory`
  2. Ensure top tab = Active, sub-tab = All Stock.
  3. Open `Sort catalogs by` dropdown → click `Newest First`.
  4. Iterate catalogs in the left panel. Each catalog card shows a
     `Catalog ID: <n>` line. Click each catalog, wait for the right panel,
     extract the first `Style ID:` (that catalog's representative Style ID).
     Scroll the left panel via `scroll_into_view_if_needed` on the last
     card to reveal more. Each page holds 10 catalogs.
  5. After all 10 catalogs on the current page are processed, click the
     paginator's "next page" arrow / next number button.
  6. Repeat until `pages_to_scrape` reached (default 20) or last page.

STORED FIELDS (raw, no enrichment on scraper side):
    {account_id, account_name, style_id, catalog_id, scraped_at}

Enrichment (account + main category from Product Master) is done by the
backend at read time.
"""
from __future__ import annotations

import os
import re
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from _meesho_ui import cdp_context_page
from playwright.sync_api import Page, TimeoutError as PWTimeout  # noqa: F401
from pymongo import MongoClient

DEBUG_DIR = Path("/tmp/meesho-inv-debug")
PAGE_LOAD_MS = 45_000
DEFAULT_PAGES = 20
CATALOGS_PER_PAGE = 10


def _inventory_url(suffix: str) -> str:
    return f"https://supplier.meesho.com/panel/v3/new/services/{suffix}/inventory"


def _screenshot(page: Page, out_dir: Path, name: str) -> str:
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{name}.png"
        page.screenshot(path=str(path), full_page=False)
        return str(path)
    except Exception:  # noqa: BLE001
        return ""


def _safe_text(node, timeout_ms: int = 1500) -> str:
    try:
        return (node.inner_text(timeout=timeout_ms) or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _ensure_active_all_stock(page: Page) -> None:
    """Meesho defaults land on Active > All Stock, but a session may
    remember the last-used sub-tab. Force it."""
    for label in ("Active", "All Stock"):
        try:
            btn = page.locator(
                f'xpath=//*[normalize-space(text())="{label}"]'
            ).first
            if btn.count() > 0 and btn.is_visible(timeout=1500):
                btn.click(timeout=3000)
                page.wait_for_timeout(800)
        except Exception:  # noqa: BLE001
            continue


def _select_newest_first(page: Page) -> bool:
    """Open `Sort catalogs by` dropdown and pick `Newest First`."""
    try:
        # The dropdown label sits next to the value. Robust approach:
        # click the visible current value ("Highest Estimated Orders"
        # or whichever) which acts as the dropdown trigger.
        trigger_candidates = [
            'xpath=//*[contains(normalize-space(text()), "Sort catalogs by")]/following::*[self::div or self::button][1]',
            'xpath=//*[text()="Highest Estimated Orders"]',
            'xpath=//*[text()="Newest First"]',
        ]
        for sel in trigger_candidates:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible(timeout=1500):
                try:
                    loc.click(timeout=2500)
                    break
                except Exception:  # noqa: BLE001
                    continue
        page.wait_for_timeout(600)
        # Pick "Newest First" from the opened menu
        newest = page.locator(
            'xpath=//*[normalize-space(text())="Newest First"]'
        ).first
        if newest.count() > 0:
            newest.click(timeout=3000)
            page.wait_for_timeout(1500)  # let list re-sort
            return True
    except Exception:  # noqa: BLE001
        return False
    return False


CATALOG_CARD_XPATH = (
    '//div[.//*[contains(normalize-space(text()), "Catalog ID")]'
    ' and .//*[contains(normalize-space(text()), "Category")]]'
)


def _list_catalog_cards(page: Page):
    """Locator collection of the catalog cards currently rendered in the
    left panel."""
    return page.locator(f"xpath={CATALOG_CARD_XPATH}")


def _catalog_id_from_card(card) -> Optional[str]:
    text = _safe_text(card)
    if not text:
        return None
    m = re.search(r"Catalog ID[:\s]*(\S+)", text)
    if not m:
        return None
    return m.group(1).strip().rstrip(",")


def _click_catalog_card(page: Page, card) -> bool:
    for _ in range(2):
        try:
            card.scroll_into_view_if_needed(timeout=2500)
            card.click(timeout=3000)
            page.wait_for_timeout(1200)
            return True
        except Exception:  # noqa: BLE001
            page.wait_for_timeout(400)
    return False


STYLE_ID_XPATH = (
    '//*[starts-with(normalize-space(text()), "Style ID")]'
)


def _extract_first_style_id(page: Page) -> Optional[str]:
    """Return the first `Style ID:` value visible in the right panel."""
    try:
        page.wait_for_selector(f"xpath={STYLE_ID_XPATH}", timeout=6_000)
    except Exception:  # noqa: BLE001
        return None
    try:
        node = page.locator(f"xpath={STYLE_ID_XPATH}").first
        line = _safe_text(node)
    except Exception:  # noqa: BLE001
        return None
    if not line:
        return None
    # line looks like: "Style ID: RM-LEOO-5-NAVY BLUE-123"
    m = re.search(r"Style ID[:\s]*(.+)", line)
    if not m:
        return None
    return m.group(1).strip()


def _click_next_page(page: Page, next_page_num: int) -> bool:
    """Advance the left-panel paginator to `next_page_num`.

    Strategy: try `button:text-is("<n>")` first (visible page number);
    fallback to a next-arrow button (aria-label / › character)."""
    # exact page number
    try:
        btn = page.locator(
            f'xpath=(//button[normalize-space(text())="{next_page_num}"])[last()]'
        ).first
        if btn.count() > 0:
            btn.scroll_into_view_if_needed(timeout=2000)
            btn.click(timeout=3000)
            page.wait_for_timeout(1500)
            return True
    except Exception:  # noqa: BLE001
        pass
    # aria-label
    try:
        btn = page.locator(
            'button[aria-label="Go to next page"], '
            'button[aria-label="next page"], '
            'button[aria-label="Next page"], '
            'li.ant-pagination-next button'
        ).first
        if btn.count() > 0 and btn.is_visible(timeout=1500):
            btn.click(timeout=3000)
            page.wait_for_timeout(1500)
            return True
    except Exception:  # noqa: BLE001
        pass
    # unicode chevron
    try:
        btn = page.locator('xpath=//button[normalize-space(text())="›"]').first
        if btn.count() > 0 and btn.is_visible(timeout=1500):
            btn.click(timeout=3000)
            page.wait_for_timeout(1500)
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def run_inventory_sync_for_account(acc: dict, payload: dict) -> Dict[str, Any]:
    port = int(acc["debug_port"])
    suffix = (acc.get("name") or "").strip()
    if not suffix:
        raise RuntimeError("account has no `name` — cannot derive URL suffix")

    pages_to_scrape = int((payload or {}).get("pages") or DEFAULT_PAGES)
    pages_to_scrape = max(1, min(200, pages_to_scrape))

    account_id = str(acc["_id"])
    account_name = acc.get("name")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    debug_dir = DEBUG_DIR / f"{suffix}_{ts}"

    all_rows: List[Dict[str, Any]] = []
    catalogs_scanned = 0
    pages_visited = 0
    diagnostics: List[Dict[str, Any]] = []
    processed_ids: Set[str] = set()

    p, _browser, _ctx, page = cdp_context_page(port)
    try:
        page.goto(_inventory_url(suffix), wait_until="domcontentloaded",
                  timeout=PAGE_LOAD_MS)
        try:
            page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(2500)

        _ensure_active_all_stock(page)
        page.wait_for_timeout(1200)
        sorted_ok = _select_newest_first(page)
        diagnostics.append({"stage": "sort_newest_first", "ok": sorted_ok})
        _screenshot(page, debug_dir, "01_after_sort")

        # early-exit if the inventory page didn't actually load
        try:
            has_catalog = page.locator("text=Catalog ID").count() > 0
        except Exception:  # noqa: BLE001
            has_catalog = False
        if not has_catalog:
            _screenshot(page, debug_dir, "01_no_catalog_id")
            return {
                "catalogs_scanned": 0,
                "skus_captured": 0,
                "pages_visited": 0,
                "pages_requested": pages_to_scrape,
                "note": ("Inventory page loaded but no 'Catalog ID' text "
                         "found — likely not logged in or wrong URL. "
                         f"Screenshots: {debug_dir}"),
                "diagnostics": diagnostics,
                "debug_dir": str(debug_dir),
            }

        current_page = 1
        while pages_visited < pages_to_scrape:
            pages_visited += 1
            _screenshot(page, debug_dir, f"page_{current_page}_start")

            # iterate catalogs on this page — scroll the left panel via
            # scroll_into_view_if_needed on newly-appearing cards
            last_new_at_iter = 0
            no_new_streak = 0
            iterations = 0
            page_ids_before = len(processed_ids)
            while iterations < 60:  # safety cap
                iterations += 1
                cards = _list_catalog_cards(page)
                n = cards.count()
                new_cards = []
                for i in range(n):
                    cid = _catalog_id_from_card(cards.nth(i))
                    if cid and cid not in processed_ids:
                        new_cards.append((i, cid))
                if not new_cards:
                    no_new_streak += 1
                    if no_new_streak >= 3:
                        break
                    # try scrolling the last card into view to prompt
                    # virtualisation to render more
                    try:
                        cards.nth(n - 1).scroll_into_view_if_needed(
                            timeout=1500)
                        page.wait_for_timeout(600)
                    except Exception:  # noqa: BLE001
                        pass
                    continue
                no_new_streak = 0
                for i, cid in new_cards:
                    card = cards.nth(i)
                    if not _click_catalog_card(page, card):
                        diagnostics.append({
                            "stage": "click_failed",
                            "page": current_page,
                            "catalog_id": cid,
                        })
                        processed_ids.add(cid)  # skip permanently
                        continue
                    style_id = _extract_first_style_id(page)
                    processed_ids.add(cid)
                    if style_id:
                        all_rows.append({
                            "account_id": account_id,
                            "account_name": account_name,
                            "style_id": style_id,
                            "catalog_id": cid,
                            "page_no": current_page,
                        })
                        catalogs_scanned += 1
                    else:
                        diagnostics.append({
                            "stage": "no_style_id",
                            "page": current_page,
                            "catalog_id": cid,
                        })
                    time.sleep(0.35)
                # after processing this batch, keep looping to find more
                # (virtualisation may reveal new cards below)
                if len(processed_ids) - last_new_at_iter == 0:
                    no_new_streak += 1
                last_new_at_iter = len(processed_ids)
                # stop early once we've gathered ~CATALOGS_PER_PAGE
                page_ids_now = len(processed_ids) - page_ids_before
                if page_ids_now >= CATALOGS_PER_PAGE:
                    break

            _screenshot(page, debug_dir, f"page_{current_page}_end")

            # advance to next page if there's more to scrape
            if pages_visited >= pages_to_scrape:
                break
            current_page += 1
            if not _click_next_page(page, current_page):
                diagnostics.append({
                    "stage": "pagination_exhausted",
                    "reached_page": current_page - 1,
                })
                break
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        diagnostics.append({"stage": "fatal",
                            "error": f"{type(e).__name__}: {e}"})
        _screenshot(page, debug_dir, "fatal")
    finally:
        try:
            page.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            p.stop()
        except Exception:  # noqa: BLE001
            pass

    # persist — replace this account's snapshot atomically
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
                r["scraped_at"] = now
            db.meesho_live_skus.insert_many(all_rows, ordered=False)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        raise RuntimeError(f"persist failed: {e}")

    note = ""
    if not all_rows:
        note = (f"0 rows captured across {pages_visited} page(s). "
                f"Screenshots: {debug_dir}")
    return {
        "catalogs_scanned": catalogs_scanned,
        "skus_captured": len(all_rows),
        "pages_visited": pages_visited,
        "pages_requested": pages_to_scrape,
        "note": note,
        "diagnostics": diagnostics,
        "debug_dir": str(debug_dir),
    }
