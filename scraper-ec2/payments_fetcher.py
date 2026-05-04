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
import re
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

PERIOD_LABEL = {
    "previous_week": "Previous Week",
    "previous_month": "Previous Month",
    "last_payment": "Last Payment",
}


def _payments_url(identifier: str) -> str:
    return f"https://supplier.meesho.com/panel/v3/new/payouts/{identifier}/payments"


def _wait_for_zip(folder: Path, started_at: float, timeout: int = 180) -> Optional[Path]:
    """Poll the download folder for a .zip created after `started_at`.
    Ignore Chrome's `.crdownload` partial files."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        candidates = sorted(
            (p for p in folder.iterdir()
             if p.suffix.lower() == ".zip" and p.stat().st_mtime >= started_at),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            # ensure it isn't still being written to
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


def _click_download_flow(page, period_label: str):
    """Replicate the manual UI flow shown in user's screenshots."""
    # 1. Top-right "Download" button (split button)
    page.get_by_role("button", name=re.compile(r"^\s*Download\s*$", re.I)).first.click()
    page.wait_for_timeout(800)

    # 2. Dropdown item "Payments to Date"
    page.get_by_text("Payments to Date", exact=True).click()
    page.wait_for_timeout(800)

    # 3. Modal radio
    radio = page.get_by_text(period_label, exact=True)
    radio.click()
    page.wait_for_timeout(400)

    # 4. Modal "Download" button
    page.get_by_role("button", name=re.compile(r"^\s*Download\s*$", re.I)).last.click()


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
            _click_download_flow(page, label)
        finally:
            try:
                page.close()
            except Exception:
                pass

    zip_path = _wait_for_zip(DOWNLOAD_DIR, started_at)
    if not zip_path:
        raise RuntimeError(f"no .zip appeared in {DOWNLOAD_DIR} within timeout")
    print(f"[payments_fetcher] zip downloaded: {zip_path.name}")

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
