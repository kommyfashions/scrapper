"""Auto-accept new orders on Meesho — job type: `accept_labels`.

Uses the EXACT SAME URL and flow as the proven labels.py:
    https://supplier.meesho.com/panel/v3/new/fulfillment/<suffix>/orders/pending

Flow (bulk, matches labels.py accept_pending()):
  1. Goto PENDING_URL
  2. Wait for UI (text=Orders count > 0)
  3. Wait for tbody tr rows (there's an order)
  4. Click the first checkbox = select all
  5. Click "Accept Selected Orders"
  6. Click "Accept Order" in confirm modal
  7. Sleep 10 s for backend

NO PDF DOWNLOAD — this is polling for auto-accept only.

Returns:
    {accepted_count, already_accepted_count, failed_count, orders_seen, note}
"""
from __future__ import annotations

import time
import traceback
from typing import Any, Dict

from _meesho_ui import cdp_context_page
from playwright.sync_api import Page, TimeoutError as PWTimeout  # noqa: F401


def _pending_url(suffix: str) -> str:
    return (f"https://supplier.meesho.com/panel/v3/new/fulfillment/"
            f"{suffix}/orders/pending")


def _wait_for_ui(page: Page, seconds: int = 60) -> bool:
    for _ in range(seconds):
        try:
            if page.locator("text=Orders").count() > 0:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
    return False


def _count_rows(page: Page) -> int:
    try:
        return page.locator("tbody tr").count()
    except Exception:  # noqa: BLE001
        return 0


def _wait_for_orders(page: Page, seconds: int = 20) -> int:
    for _ in range(seconds):
        n = _count_rows(page)
        if n > 0:
            return n
        time.sleep(1)
    return 0


def _select_all(page: Page) -> bool:
    for _ in range(10):
        try:
            checkboxes = page.locator("input[type='checkbox']")
            if checkboxes.count() > 0:
                try:
                    checkboxes.first.click(timeout=3000)
                except Exception:  # noqa: BLE001
                    page.evaluate(
                        "document.querySelectorAll('input[type=\"checkbox\"]')[0]?.click()"
                    )
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
    return False


def run_accept_labels_for_account(acc: dict, payload: dict) -> Dict[str, Any]:
    port = int(acc["debug_port"])
    suffix = (acc.get("name") or "").strip()
    if not suffix:
        raise RuntimeError("account has no `name` — cannot derive URL suffix")

    accepted = 0
    already = 0
    failed = 0
    orders_seen = 0
    note = ""

    p, _browser, _ctx, page = cdp_context_page(port)
    try:
        page.goto(_pending_url(suffix), wait_until="domcontentloaded",
                  timeout=45_000)
        time.sleep(3)

        if not _wait_for_ui(page):
            note = "UI did not load (Orders header not visible)"
            failed = 1
            return {
                "accepted_count": accepted, "already_accepted_count": already,
                "failed_count": failed, "orders_seen": orders_seen,
                "note": note,
            }

        # explicit reload — mirrors labels.py.refresh()
        try:
            page.reload()
            time.sleep(4)
        except Exception:  # noqa: BLE001
            pass

        orders_seen = _wait_for_orders(page)
        if orders_seen == 0:
            already = 1
            note = "no pending orders"
            return {
                "accepted_count": accepted, "already_accepted_count": already,
                "failed_count": failed, "orders_seen": orders_seen,
                "note": note,
            }

        if not _select_all(page):
            failed = 1
            note = "could not tick select-all checkbox"
            return {
                "accepted_count": accepted, "already_accepted_count": already,
                "failed_count": failed, "orders_seen": orders_seen,
                "note": note,
            }

        # Click "Accept Selected Orders" toolbar button
        try:
            page.locator("text=Accept Selected Orders").first.click(
                timeout=8000)
        except Exception as e:  # noqa: BLE001
            failed = 1
            note = f"Accept Selected Orders button not clickable: {e}"
            return {
                "accepted_count": accepted, "already_accepted_count": already,
                "failed_count": failed, "orders_seen": orders_seen,
                "note": note,
            }
        time.sleep(2)

        # Confirm modal
        try:
            page.locator("button:has-text('Accept Order')").first.click(
                timeout=6000)
        except Exception:  # noqa: BLE001
            # Some flows accept without the modal; not a hard fail
            note = "no confirm modal (accepted inline)"

        time.sleep(10)  # backend needs time — matches labels.py
        accepted = orders_seen

        return {
            "accepted_count": accepted,
            "already_accepted_count": already,
            "failed_count": failed,
            "orders_seen": orders_seen,
            "note": note,
        }
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return {
            "accepted_count": accepted,
            "already_accepted_count": already,
            "failed_count": failed + 1,
            "orders_seen": orders_seen,
            "note": f"{type(e).__name__}: {e}",
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
