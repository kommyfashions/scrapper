"""Auto-accept labels — job type: `accept_labels`.

Opens supplier.meesho.com/panel/v3/new/services/<suffix>/orders?stage=RTS
(Ready-to-Ship) and clicks "Accept Order" on every visible pending order.
NO PDF download — this is polling-only for order acceptance.

The scheduler tick in the dashboard (aa_router.scheduler_tick) enqueues
one job per enabled account at each cadence tick. The label_worker on
the EC2 box dispatches to this fetcher.

Return dict merged into the job:
    {accepted_count, already_accepted_count, failed_count, per_order}
"""
from __future__ import annotations

import time
import traceback
from typing import Any, Dict, List

from _meesho_ui import cdp_context_page
from playwright.sync_api import Page, TimeoutError as PWTimeout

PAGE_LOAD_MS = 40_000
BUTTON_WAIT_MS = 6_000

ACCEPT_LABELS = [
    "Accept Order", "Accept", "Accept All", "Confirm Order",
]


def _orders_url(suffix: str) -> str:
    return (f"https://supplier.meesho.com/panel/v3/new/services/{suffix}"
            f"/orders?tab=RTS")


def _try_click_accept(page: Page) -> bool:
    """Click any single Accept button visible on the page.
    Returns True if a click happened."""
    for label in ACCEPT_LABELS:
        try:
            btn = page.locator(
                f'button:has-text("{label}")').first
            if btn.is_visible(timeout=1500) and not btn.is_disabled(
                    timeout=1000):
                btn.click(timeout=3000)
                page.wait_for_timeout(1200)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _confirm_modal_if_any(page: Page) -> None:
    """Some Meesho flows show a confirm modal; click Yes/Confirm."""
    for label in ("Yes, Accept", "Confirm", "Yes", "Proceed"):
        try:
            btn = page.locator(f'button:has-text("{label}")').first
            if btn.is_visible(timeout=1000):
                btn.click(timeout=2000)
                page.wait_for_timeout(800)
                return
        except Exception:  # noqa: BLE001
            continue


def run_accept_labels_for_account(acc: dict, payload: dict) -> Dict[str, Any]:
    port = int(acc["debug_port"])
    suffix = (acc.get("name") or "").strip()
    if not suffix:
        raise RuntimeError("account has no `name` — cannot derive URL suffix")

    accepted = 0
    already = 0
    failed = 0
    per_order: List[Dict[str, Any]] = []

    p, browser, _ctx, page = cdp_context_page(port)
    try:
        page.goto(_orders_url(suffix),
                  wait_until="domcontentloaded", timeout=PAGE_LOAD_MS)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except PWTimeout:
            pass
        page.wait_for_timeout(2000)

        # If there is no Accept button at all → already accepted / nothing to do.
        try:
            body_text = page.locator("body").first.inner_text(timeout=3000) or ""
        except Exception:  # noqa: BLE001
            body_text = ""
        if not any(label in body_text for label in ACCEPT_LABELS):
            already += 1
            return {
                "accepted_count": accepted, "already_accepted_count": already,
                "failed_count": failed, "per_order": per_order,
            }

        # Click Accept repeatedly. After each click, wait for the button to
        # disappear or the row to update, then look again.
        max_iters = 500  # safety cap
        no_progress = 0
        for _ in range(max_iters):
            clicked = _try_click_accept(page)
            if not clicked:
                no_progress += 1
                if no_progress >= 3:
                    break
                time.sleep(1.0)
                continue
            no_progress = 0
            _confirm_modal_if_any(page)
            accepted += 1
            per_order.append({"status": "accepted"})
            time.sleep(0.5)

        return {
            "accepted_count": accepted,
            "already_accepted_count": already,
            "failed_count": failed,
            "per_order": per_order,
        }
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        failed += 1
        return {
            "accepted_count": accepted,
            "already_accepted_count": already,
            "failed_count": failed,
            "per_order": per_order,
            "error": f"{type(e).__name__}: {e}",
        }
    finally:
        try:
            page.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            p.stop()
        except Exception:  # noqa: BLE001
            pass
