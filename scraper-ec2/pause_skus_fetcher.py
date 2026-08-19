"""
Meesho bulk-pause worker (per-Style-ID) — CDP-attached Playwright.

Job payload (from `jobs.payload`):
    {
      "product_id": "<pm_products _id>",
      "main_category": "Vertis-301",
      "color": "Grey",
      "target_sizes": ["IND-6", "IND-7", "IND-8", "IND-9", "IND-10"],
      "style_ids":    ["MSS-VTX-GREY-001", "MSS-VTX-GREY", "HP+MSS-VTX-GREY", ...]
    }

For each Style ID we:
  1. Navigate to  supplier.meesho.com/panel/v3/new/services/{suffix}/inventory
     /search?query=<STYLE_ID>&type=product
  2. Wait for the size-variation rows to render (IND-3, IND-4, ...).
  3. Tick only the checkboxes whose variation label matches a target size
     (exact match, e.g. "IND-6"). Skip any size not in target_sizes.
  4. Click "Pause Selected". Wait for the success toast
        "Product paused and moved to 'Paused' tab"
     Meesho's flow removes the row after pause, so if no rows match at all
     (all already paused/blocked) we record "already_paused" for those.

IMPORTANT: never call browser.close() — this is a CDP-attached shared Chrome
that other workers (labels, gst, payments) also use. Only close the page
we opened and stop the playwright driver.
"""
from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Any, Dict, List

from _meesho_ui import cdp_context_page, safe_dirname, screenshot_on_fail
from playwright.sync_api import Page, TimeoutError as PWTimeout

DEBUG_DIR = Path("/tmp/meesho-pause-debug")

# Timings
PAGE_LOAD_MS = 30_000
ROW_WAIT_MS = 15_000
TOAST_WAIT_MS = 15_000


def _inventory_search_url(suffix: str, style_id: str) -> str:
    # URL-encode Style ID (contains "+" and spaces on some accounts)
    from urllib.parse import quote
    q = quote(style_id, safe="")
    return (
        f"https://supplier.meesho.com/panel/v3/new/services/{suffix}"
        f"/inventory/search?query={q}&type=product"
    )


def _safe_is_checked(cb) -> bool:
    """Playwright's is_checked() raises TargetClosedError if the locator's
    target is gone. We swallow and treat as not-checked so click() below
    can try; if click also fails it will be caught in _select_rows."""
    try:
        return cb.is_checked(timeout=1_500)
    except Exception:  # noqa: BLE001
        return False


def _select_rows_matching_sizes(page: Page, target_sizes: List[str]) -> int:
    """Return count of ticked checkboxes.

    Meesho renders one row per size variation. Each row contains the
    variation label (e.g. "IND-6") and a checkbox on the left. We use an
    XPath ancestor climb from the size text to the row, then click the
    first checkbox within.
    """
    ticked = 0
    for size in target_sizes:
        try:
            size_cell = page.locator(
                f'xpath=//*[normalize-space(text())="{size}"]'
            ).first
            size_cell.wait_for(state="visible", timeout=3_000)
        except PWTimeout:
            # Size not on the page — likely already paused/blocked or the
            # Style ID doesn't have this size. Skip silently.
            continue
        except Exception:  # noqa: BLE001
            continue
        try:
            row = size_cell.locator(
                'xpath=ancestor::*[self::tr or self::div][.//input[@type="checkbox"]][1]'
            ).first
            cb = row.locator('input[type="checkbox"]').first
            if not _safe_is_checked(cb):
                cb.click(timeout=3_000)
                ticked += 1
                page.wait_for_timeout(200)
        except Exception:  # noqa: BLE001
            continue
    return ticked


def _click_pause_selected(page: Page) -> bool:
    try:
        btn = page.locator('button:has-text("Pause Selected")').first
        btn.wait_for(state="visible", timeout=5_000)
        btn.click(timeout=3_000)
        return True
    except Exception:  # noqa: BLE001
        return False


def _wait_for_success_toast(page: Page) -> bool:
    """Wait for 'Product paused and moved to \"Paused\" tab' toast."""
    try:
        page.locator(
            'xpath=//*[contains(normalize-space(.), "paused") '
            'and contains(normalize-space(.), "Paused")]'
        ).first.wait_for(state="visible", timeout=TOAST_WAIT_MS)
        return True
    except Exception:  # noqa: BLE001
        return False


def _pause_one_style_id(
    page: Page, suffix: str, style_id: str, target_sizes: List[str]
) -> Dict[str, Any]:
    url = _inventory_search_url(suffix, style_id)
    result: Dict[str, Any] = {
        "style_id": style_id,
        "target_sizes": list(target_sizes),
        "ticked": 0,
        "status": "unknown",
        "error": None,
    }
    print(f"[pause_skus]   → {style_id}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
    except Exception as e:  # noqa: BLE001
        result["status"] = "failed"
        result["error"] = f"page load: {type(e).__name__}: {e}"
        return result

    try:
        page.wait_for_load_state("networkidle", timeout=ROW_WAIT_MS)
    except PWTimeout:
        pass
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(1500)

    # If the search returns nothing on the "Active" tab, treat as
    # "already_paused" — the Style ID is already in Paused or Blocked.
    try:
        body_text = page.locator("body").first.inner_text(timeout=3_000) or ""
    except Exception:  # noqa: BLE001
        body_text = ""
    if "Showing Results (0)" in body_text or "No results found" in body_text:
        result["status"] = "already_paused"
        return result

    ticked = _select_rows_matching_sizes(page, target_sizes)
    result["ticked"] = ticked
    if ticked == 0:
        result["status"] = "already_paused"
        return result

    if not _click_pause_selected(page):
        result["status"] = "failed"
        result["error"] = "Pause Selected button not visible / not clickable"
        screenshot_on_fail(page, DEBUG_DIR / safe_dirname(suffix), f"pause_{style_id}")
        return result

    if not _wait_for_success_toast(page):
        result["status"] = "failed"
        result["error"] = "no success toast after clicking Pause Selected"
        screenshot_on_fail(page, DEBUG_DIR / safe_dirname(suffix), f"toast_{style_id}")
        return result

    result["status"] = "paused"
    return result


def run_pause_skus_for_account(acc: dict, payload: dict) -> Dict[str, Any]:
    """Called by label_worker.py dispatcher. Returns a `result` dict to be
    stored on the job document."""
    port = int(acc["debug_port"])
    suffix = (acc.get("name") or "").strip()
    if not suffix:
        raise RuntimeError(
            f"account {acc.get('_id')} has no `name` — cannot derive URL suffix"
        )
    style_ids: List[str] = list(payload.get("style_ids") or [])
    target_sizes: List[str] = list(payload.get("target_sizes") or [])
    if not style_ids or not target_sizes:
        raise RuntimeError("payload missing style_ids or target_sizes")

    per_sku: List[Dict[str, Any]] = []
    paused = already = failed = 0

    # NOTE: never call browser.close() — it disconnects the shared Chrome
    # that labels/gst/payments workers also use. Only close our page +
    # stop playwright, matching gst_report_fetcher's pattern.
    p, browser, _ctx, page = cdp_context_page(port)
    try:
        for sid in style_ids:
            try:
                r = _pause_one_style_id(page, suffix, sid, target_sizes)
            except Exception as e:  # noqa: BLE001
                r = {
                    "style_id": sid, "target_sizes": target_sizes,
                    "ticked": 0, "status": "failed",
                    "error": f"{type(e).__name__}: {e}",
                }
                traceback.print_exc()
            per_sku.append(r)
            if r["status"] == "paused":
                paused += 1
            elif r["status"] == "already_paused":
                already += 1
            else:
                failed += 1
            # Brief cool-down between Style IDs to avoid rate-limits
            time.sleep(1.0)
    finally:
        try:
            page.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            p.stop()
        except Exception:  # noqa: BLE001
            pass

    return {
        "paused_count": paused,
        "already_paused_count": already,
        "failed_count": failed,
        "per_sku": per_sku,
    }
