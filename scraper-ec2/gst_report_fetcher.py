"""
Meesho GST Report auto-downloader (EC2).

Driven by `gst_report_fetch` jobs from the dashboard. For each job:
  1. CDP-attach to the account's Chrome (port from `accounts.debug_port`).
  2. Navigate to https://supplier.meesho.com/panel/v3/new/payouts/{name}/payments
  3. Click Download → GST Report. Modal "Download GST reports" opens.
  4. Pick year (e.g. "2026") + tick month (e.g. "March").
  5. Click modal Download. Two outcomes:
       a) Download event fires → we get a .zip (renamed to
          <acct>_<YYYY-MM>_GST_REPORT.zip)
       b) Red toast: "No GST report is available for download due to
          no orders in the selected month(s)" → mark job DONE with
          available=false so the daily cron can retry tomorrow.
  6. POST the zip (or the no-data marker) to
     /api/pl/gst-report/upload using the X-Worker-Key header.
"""
from __future__ import annotations

import calendar
import os
import time
from pathlib import Path
from typing import Optional

import requests

from _meesho_ui import (
    cdp_context_page, click_first_visible, open_top_download_dropdown,
    payments_url, safe_dirname, screenshot_on_fail, watch_for_download_or_text,
)

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:8001")
WORKER_API_KEY = os.environ.get("WORKER_API_KEY", "")
DOWNLOAD_DIR = Path(os.environ.get("MESHO_DOWNLOAD_DIR", "/home/ubuntu/meesho-downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

DOWNLOAD_RETRIES = 3
DOWNLOAD_TIMEOUT_MS = 180_000  # GST takes a while to generate

MONTHS = ["", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def _account_dir(acc_name: str, year: int, month: int) -> Path:
    period = f"{year}-{month:02d}"
    p = DOWNLOAD_DIR / safe_dirname(acc_name) / "gst_reports" / period
    p.mkdir(parents=True, exist_ok=True)
    return p


def _open_gst_modal(page, year: int, month_num: int):
    """Open Download → GST Report and pick year/month."""
    open_top_download_dropdown(page)

    # 1. Click "GST Report" item in the dropdown
    click_first_visible(page, [
        lambda p: p.get_by_text("GST Report", exact=True),
        'text="GST Report"',
        '[role="menuitem"]:has-text("GST Report")',
    ], what="'GST Report' menu item")
    page.wait_for_timeout(1500)

    # 2. Year selector — click the first dropdown in the modal, then the year
    click_first_visible(page, [
        '[role="dialog"] [role="combobox"]',
        '[role="dialog"] select',
        '[role="dialog"] input[readonly]',
        # fallback: click the visible text of the current year shown in the dropdown
        lambda p: p.locator('[role="dialog"]').get_by_text(
            "2022", exact=True),
    ], what="year dropdown")
    page.wait_for_timeout(700)
    click_first_visible(page, [
        f'text="{year}"',
        f'li:has-text("{year}")',
        f'[role="option"]:has-text("{year}")',
        lambda p: p.get_by_text(str(year), exact=True),
    ], what=f"year {year}")
    page.wait_for_timeout(700)

    # 3. Month selector — click the second dropdown then tick month
    click_first_visible(page, [
        '[role="dialog"] [role="combobox"] >> nth=1',
        # generic: any element labelled "Select month"
        lambda p: p.get_by_text("Select month", exact=True),
        # fallback: any combobox in the dialog
        '[role="dialog"] select >> nth=1',
    ], what="month dropdown")
    page.wait_for_timeout(700)
    month_label = MONTHS[month_num]
    click_first_visible(page, [
        f'label:has-text("{month_label}")',
        f'[role="option"]:has-text("{month_label}")',
        f'text="{month_label}"',
        lambda p: p.get_by_text(month_label, exact=True),
    ], what=f"month {month_label}")
    page.wait_for_timeout(700)

    # close the month dropdown by clicking the title (so the Download
    # button is reachable again) — clicking the modal title is harmless.
    try:
        page.locator('[role="dialog"]').get_by_text("Download GST reports", exact=True).click()
    except Exception:  # noqa: BLE001
        page.keyboard.press("Escape")
    page.wait_for_timeout(500)


def _click_modal_download(page):
    click_first_visible(page, [
        '[role="dialog"] button:has-text("Download")',
        '[role="dialog"] [role="button"]:has-text("Download")',
        lambda p: p.locator('button:has-text("Download")').last,
    ], what="modal GST Download button")


_NO_DATA_LOCATORS = [
    lambda p: p.get_by_text("No GST report is available", exact=False),
    'text=No GST report is available',
]


def _upload(zip_path: Optional[Path], account_id: str, job_id: str,
            year: int, month: int, original_name: str,
            available: bool, reason: str) -> dict:
    if not WORKER_API_KEY:
        raise RuntimeError("WORKER_API_KEY env not set on worker")
    url = f"{DASHBOARD_URL.rstrip('/')}/api/pl/gst-report/upload"
    params = {
        "account_id": account_id, "job_id": job_id,
        "year": year, "month": month,
        "original_filename": original_name,
        "available": "true" if available else "false",
        "reason": reason or "",
    }
    headers = {"X-Worker-Key": WORKER_API_KEY}
    if available and zip_path:
        with open(zip_path, "rb") as f:
            files = {"file": (zip_path.name, f, "application/zip")}
            r = requests.post(url, params=params, files=files, headers=headers, timeout=180)
    else:
        r = requests.post(url, params=params, headers=headers, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"upload failed: HTTP {r.status_code} {r.text[:300]}")
    return r.json()


def run_gst_report_fetch_for_account(acc: dict, year: int, month: int, job_id: str) -> dict:
    if not (1 <= month <= 12):
        raise ValueError(f"invalid month: {month}")
    identifier = (acc.get("name") or "").strip()
    if not identifier:
        raise RuntimeError(f"account {acc.get('_id')} has empty name")
    port = int(acc["debug_port"])
    out_dir = _account_dir(identifier, year, month)
    print(f"[gst_report] account='{identifier}' port={port} year={year} month={month} → {out_dir}")

    p, browser, context, page = cdp_context_page(port)
    try:
        page.goto(payments_url(identifier), wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3500)

        outcome = None
        suggested = None
        for attempt in range(1, DOWNLOAD_RETRIES + 1):
            print(f"[gst_report] attempt {attempt}/{DOWNLOAD_RETRIES}")
            try:
                _open_gst_modal(page, year, month)
                _click_modal_download(page)
                kind, payload = watch_for_download_or_text(
                    page, _NO_DATA_LOCATORS, DOWNLOAD_TIMEOUT_MS,
                )
                if kind == "download":
                    suggested = payload.suggested_filename
                    target = out_dir / f"{safe_dirname(identifier)}_{year:04d}-{month:02d}_GST_REPORT.zip"
                    payload.save_as(str(target))
                    print(f"[gst_report]   ↓ saved {target.name}")
                    outcome = ("ok", target, suggested)
                    break
                if kind == "no_data":
                    print(f"[gst_report]   ⚠ no-data toast: {payload}")
                    outcome = ("no_data", None, payload)
                    break
                # timeout — retry
                print(f"[gst_report]   ! timeout on attempt {attempt}")
                screenshot_on_fail(page, out_dir, f"gst_timeout_a{attempt}")
            except Exception as e:  # noqa: BLE001
                print(f"[gst_report]   ! attempt {attempt} failed: {type(e).__name__}: {e}")
                screenshot_on_fail(page, out_dir, f"gst_fail_a{attempt}")
            # reload before retrying
            if attempt < DOWNLOAD_RETRIES:
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(500)
                    page.reload(wait_until="domcontentloaded", timeout=45_000)
                    page.wait_for_timeout(3000)
                except Exception as re:  # noqa: BLE001
                    print(f"[gst_report]   reload failed: {re}")

        if not outcome:
            raise RuntimeError(f"GST download did not start after {DOWNLOAD_RETRIES} attempts")
    finally:
        try:
            page.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            p.stop()
        except Exception:  # noqa: BLE001
            pass

    kind, file_path, payload = outcome
    if kind == "no_data":
        return _upload(None, str(acc["_id"]), job_id, year, month,
                       "", available=False, reason=payload or "no orders in selected month")

    # ok
    try:
        result = _upload(file_path, str(acc["_id"]), job_id, year, month,
                         payload, available=True, reason="")
        result["source_filename"] = payload
        return result
    finally:
        try:
            file_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


# helper that the cron / dispatcher uses
def last_day_of_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]
