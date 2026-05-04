"""
Meesho Payments-File auto-downloader.

Driven by `payments_fetch` jobs from the dashboard. For each job the
worker:
  1. CDP-attaches to the account's already-running Chrome (port from
     `accounts.debug_port`).
  2. Navigates to https://supplier.meesho.com/panel/v3/new/payouts/{name}/payments
  3. Clicks Download → Payments to Date → selects the requested period
     radio → clicks Download (modal).
  4. Waits for the .zip download in DOWNLOAD_DIR.
  5. Extracts the .xlsx out of the zip.
  6. POSTs the xlsx to the dashboard /api/pl/upload?account_id=&job_id=
     using the shared X-Worker-Key header.
  7. Cleans up the zip + xlsx.

This module is single-purpose and stateless; the dispatcher in
`label_worker.py` calls `run_payments_fetch_for_account(acc, period, job_id)`.
"""
from __future__ import annotations

import os
import time
import zipfile
import shutil
from pathlib import Path
from typing import Optional

import requests
from playwright.sync_api import sync_playwright

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:8001")
WORKER_API_KEY = os.environ.get("WORKER_API_KEY", "")
DOWNLOAD_DIR = Path(os.environ.get("MESHO_DOWNLOAD_DIR", "/home/ubuntu/meesho-downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Chrome often drops downloads into its default ~/Downloads regardless of our
# Page.setDownloadBehavior call — especially when the site opens a new tab to
# trigger the zip. We therefore watch both our configured folder AND the
# system default, and pick up whichever fires first.
WATCH_DIRS = [DOWNLOAD_DIR, Path.home() / "Downloads"]

PERIOD_LABEL = {
    "previous_week": "Previous Week",
    "previous_month": "Previous Month",
    "last_payment": "Last Payment",
}


def _payments_url(identifier: str) -> str:
    return f"https://supplier.meesho.com/panel/v3/new/payouts/{identifier}/payments"


def _wait_for_zip(folders, started_at: float, timeout: int = 180) -> Optional[Path]:
    """Poll the given download folders for a .zip created after `started_at`.
    Ignores Chrome's `.crdownload` partial files. Returns the first stable zip
    found across all folders."""
    existing = set()
    for folder in folders:
        if folder.exists():
            for p in folder.iterdir():
                existing.add(p.resolve())
    deadline = time.time() + timeout
    while time.time() < deadline:
        candidates = []
        for folder in folders:
            if not folder.exists():
                continue
            for p in folder.iterdir():
                if (p.suffix.lower() == ".zip"
                        and p.stat().st_mtime >= started_at
                        and p.resolve() not in existing):
                    candidates.append(p)
        if candidates:
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            p = candidates[0]
            size1 = p.stat().st_size
            time.sleep(2)
            if p.stat().st_size == size1 and size1 > 0:
                return p
        time.sleep(2)
    return None


def _extract_xlsx(zip_path: Path, out_dir: Path) -> Optional[Path]:
    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if n.lower().endswith(".xlsx")]
        if not members:
            return None
        # if multiple, pick the largest (Meesho zip usually has 1)
        target = max(members, key=lambda n: zf.getinfo(n).file_size)
        out = out_dir / Path(target).name
        with zf.open(target) as src, open(out, "wb") as dst:
            shutil.copyfileobj(src, dst)
        return out


def _upload_to_dashboard(xlsx_path: Path, account_id: str, job_id: str) -> dict:
    if not WORKER_API_KEY:
        raise RuntimeError("WORKER_API_KEY env not set on worker")
    url = f"{DASHBOARD_URL.rstrip('/')}/api/pl/upload"
    with open(xlsx_path, "rb") as f:
        files = {"file": (xlsx_path.name, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        params = {"account_id": account_id, "job_id": job_id}
        headers = {"X-Worker-Key": WORKER_API_KEY}
        r = requests.post(url, params=params, files=files, headers=headers, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"upload failed: HTTP {r.status_code} {r.text[:300]}")
    return r.json()


def _click_first_visible(page, selectors, what: str, timeout: int = 20_000):
    """Try a list of locators in order. First one that becomes visible
    within `timeout` gets clicked. Raises with a helpful message if none match."""
    last_err = None
    deadline = time.time() + (timeout / 1000)
    for sel in selectors:
        try:
            loc = sel(page) if callable(sel) else page.locator(sel)
            loc = loc.first
            remaining = max(1_000, int((deadline - time.time()) * 1000))
            loc.wait_for(state="visible", timeout=remaining)
            loc.click()
            print(f"[payments_fetcher]   ✓ clicked {what}  via {sel if isinstance(sel, str) else 'lambda'}")
            return
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"could not find clickable '{what}': {type(last_err).__name__}: {last_err}")


def _click_download_flow(page, period_label: str, debug_dir: Path):
    """Replicate the manual UI flow shown in user's screenshots.
    Robust to Meesho rendering Download as <div role=button> vs <button>."""
    # Wait for the SPA to finish its initial XHR burst.
    try:
        page.wait_for_load_state("networkidle", timeout=30_000)
    except Exception:
        pass
    page.wait_for_timeout(2000)

    try:
        # 1. Top-right "Download" split button
        _click_first_visible(page, [
            'button:has-text("Download")',
            '[role="button"]:has-text("Download")',
            'div:has-text("Download"):not(:has(*:has-text("Download")))',
            lambda p: p.get_by_text("Download", exact=True),
        ], what="top-right Download button")
        page.wait_for_timeout(1200)

        # 2. Dropdown item "Payments to Date"
        _click_first_visible(page, [
            lambda p: p.get_by_text("Payments to Date", exact=True),
            'text="Payments to Date"',
            '[role="menuitem"]:has-text("Payments to Date")',
        ], what="'Payments to Date' menu item")
        page.wait_for_timeout(1200)

        # 3. Modal radio (Previous Week / Previous Month / Last Payment)
        _click_first_visible(page, [
            lambda p: p.get_by_text(period_label, exact=True),
            f'text="{period_label}"',
            f'label:has-text("{period_label}")',
            f'[role="radio"]:has-text("{period_label}")',
        ], what=f"radio '{period_label}'")
        page.wait_for_timeout(800)

        # 4. Modal "Download" button (the one inside the dialog).
        # We scope to the dialog if it exists; otherwise grab the LAST
        # visible Download (the modal one renders later than the page-level one).
        _click_first_visible(page, [
            '[role="dialog"] button:has-text("Download")',
            '[role="dialog"] [role="button"]:has-text("Download")',
            lambda p: p.locator('button:has-text("Download")').last,
            lambda p: p.locator('[role="button"]:has-text("Download")').last,
        ], what="modal Download button")
    except Exception:
        # capture a debug screenshot so user can see UI state at failure
        ts = time.strftime("%Y%m%d-%H%M%S")
        path = debug_dir / f"payments_fetch_fail_{ts}.png"
        try:
            page.screenshot(path=str(path), full_page=True)
            print(f"[payments_fetcher] ✗ saved failure screenshot → {path}")
        except Exception as e2:
            print(f"[payments_fetcher] could not save screenshot: {e2}")
        raise


def run_payments_fetch_for_account(acc: dict, period: str, job_id: str) -> dict:
    if period not in PERIOD_LABEL:
        raise ValueError(f"unsupported period: {period}")
    label = PERIOD_LABEL[period]
    identifier = (acc.get("name") or "").strip()
    if not identifier:
        raise RuntimeError(f"account {acc.get('_id')} has empty name (Meesho identifier)")
    port = int(acc["debug_port"])
    cdp = f"http://127.0.0.1:{port}"

    started_at = time.time()
    print(f"[payments_fetcher] account={identifier} port={port} period={period}")

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp)
        # Use the first existing context (the user's logged-in window).
        if not browser.contexts:
            raise RuntimeError(f"no browser context on port {port}; is Chrome started?")
        context = browser.contexts[0]
        # Tell Chrome where to drop the download.  CDP sets it on the browser.
        # (`Page.setDownloadBehavior` works via send_cdp().)
        page = context.new_page()
        try:
            client = context.new_cdp_session(page)
            client.send("Page.setDownloadBehavior", {
                "behavior": "allow",
                "downloadPath": str(DOWNLOAD_DIR),
            })
            page.goto(_payments_url(identifier), wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(4000)  # let the SPA fetch boot
            _click_download_flow(page, label, DOWNLOAD_DIR)
        finally:
            try:
                page.close()
            except Exception:
                pass

    zip_path = _wait_for_zip(WATCH_DIRS, started_at)
    if not zip_path:
        watched = ", ".join(str(p) for p in WATCH_DIRS)
        raise RuntimeError(f"no .zip appeared in any of: {watched} within timeout")
    print(f"[payments_fetcher] zip downloaded: {zip_path}")

    # If Chrome saved into ~/Downloads (or anywhere else), relocate into our
    # managed folder so cleanup is consistent.
    if zip_path.parent.resolve() != DOWNLOAD_DIR.resolve():
        moved = DOWNLOAD_DIR / zip_path.name
        try:
            shutil.move(str(zip_path), str(moved))
            zip_path = moved
            print(f"[payments_fetcher] relocated → {zip_path}")
        except Exception as e:
            print(f"[payments_fetcher] could not relocate (will still process): {e}")

    try:
        xlsx_path = _extract_xlsx(zip_path, DOWNLOAD_DIR)
        if not xlsx_path:
            raise RuntimeError("zip contained no .xlsx")
        print(f"[payments_fetcher] uploading {xlsx_path.name} → dashboard")
        result = _upload_to_dashboard(xlsx_path, str(acc["_id"]), job_id)
        print(f"[payments_fetcher] upload result: {result}")
        return result
    finally:
        # cleanup
        try:
            zip_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            if 'xlsx_path' in locals() and xlsx_path:
                xlsx_path.unlink(missing_ok=True)
        except Exception:
            pass
