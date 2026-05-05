"""
Tiny shared helpers used by every Meesho UI scraper running on the EC2
worker. Keeps the actual scrapers focused on the page-flow they automate.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable, List, Optional, Union

from playwright.sync_api import Page, sync_playwright, TimeoutError as PWTimeout


def payments_url(identifier: str) -> str:
    return f"https://supplier.meesho.com/panel/v3/new/payouts/{identifier}/payments"


def safe_dirname(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", (name or "unknown").strip()) or "unknown"


def click_first_visible(
    page: Page,
    selectors: List[Union[str, Callable]],
    what: str,
    timeout: int = 20_000,
) -> None:
    """Try a list of locators in order. First one visible within `timeout`
    gets clicked. Raises with a helpful error if none match."""
    last_err = None
    deadline = time.time() + (timeout / 1000)
    for sel in selectors:
        try:
            loc = sel(page) if callable(sel) else page.locator(sel)
            loc = loc.first
            remaining = max(1_000, int((deadline - time.time()) * 1000))
            loc.wait_for(state="visible", timeout=remaining)
            loc.click()
            print(f"[meesho_ui]   ✓ clicked {what}")
            return
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise RuntimeError(
        f"could not find clickable '{what}': "
        f"{type(last_err).__name__ if last_err else 'NotFound'}: {last_err}"
    )


def open_top_download_dropdown(page: Page) -> None:
    """Click the top-right 'Download' split button on the Payments page."""
    try:
        page.wait_for_load_state("networkidle", timeout=30_000)
    except PWTimeout:
        pass
    page.wait_for_timeout(1500)
    click_first_visible(page, [
        'button:has-text("Download")',
        '[role="button"]:has-text("Download")',
        'div:has-text("Download"):not(:has(*:has-text("Download")))',
        lambda p: p.get_by_text("Download", exact=True),
    ], what="top-right Download button")
    page.wait_for_timeout(1000)


def cdp_context_page(port: int):
    """Returns (playwright, browser, context, page) bound to an existing
    Chrome instance running with --remote-debugging-port=<port>.

    Caller MUST close the page and stop playwright when done."""
    p = sync_playwright().start()
    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
    if not browser.contexts:
        p.stop()
        raise RuntimeError(f"no browser context on port {port}; is Chrome started?")
    context = browser.contexts[0]
    page = context.new_page()
    return p, browser, context, page


def screenshot_on_fail(page: Page, debug_dir: Path, prefix: str) -> Optional[Path]:
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        path = debug_dir / f"{prefix}_{ts}.png"
        page.screenshot(path=str(path), full_page=True)
        print(f"[meesho_ui] ✗ saved failure screenshot → {path}")
        return path
    except Exception as e:  # noqa: BLE001
        print(f"[meesho_ui] could not save screenshot: {e}")
        return None


def watch_for_download_or_text(
    page: Page,
    no_data_locators: List[Union[str, Callable]],
    timeout_ms: int,
):
    """After triggering an action, wait either for a download event or for
    one of the `no_data_locators` to become visible.

    Returns:
      ('download', Download)  — file download fired
      ('no_data', str)        — one of the no-data text locators appeared
      ('timeout', None)       — neither happened within timeout

    The caller must trigger the click *before* calling this. The page.on
    download listener is set up here.
    """
    download_holder = {"value": None}

    def _on_dl(d):
        download_holder["value"] = d

    page.on("download", _on_dl)
    try:
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            if download_holder["value"]:
                return ("download", download_holder["value"])
            for sel in no_data_locators:
                try:
                    loc = sel(page) if callable(sel) else page.locator(sel)
                    if loc.first.is_visible():
                        return ("no_data", str(loc.first.text_content() or "")[:300])
                except Exception:  # noqa: BLE001
                    continue
            time.sleep(0.5)
        return ("timeout", None)
    finally:
        try:
            page.remove_listener("download", _on_dl)
        except Exception:  # noqa: BLE001
            pass
