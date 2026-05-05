"""
Meesho Tax Invoice auto-downloader (EC2).

Driven by `tax_invoice_fetch` jobs from the dashboard. For each job:
  1. CDP-attach to the account's Chrome.
  2. Navigate to payments URL.
  3. Click Download → Tax Invoice. Modal "Download Tax invoice" opens
     with a calendar that defaults to the current month.
  4. Click the left arrow on the calendar until the header reads the
     target month/year. Click day 1 → "From" populates. Click last day
     of month → "To" populates.
  5. Click modal Download. Wait up to 180s for the .zip to appear.
  6. Extract `Tax_invoice_details.xlsx`, rename to
        <acct>_<YYYY-MM>_TAX_INVOICE.xlsx
     Discard the per-order PDFs (per user spec).
  7. POST the xlsx to /api/pl/tax-invoice/upload using X-Worker-Key.
"""
from __future__ import annotations

import calendar
import os
import shutil
import zipfile
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
DOWNLOAD_TIMEOUT_MS = 240_000  # tax invoice generation can take a couple minutes

MONTHS = ["", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def _account_dir(acc_name: str, year: int, month: int) -> Path:
    period = f"{year}-{month:02d}"
    p = DOWNLOAD_DIR / safe_dirname(acc_name) / "tax_invoices" / period
    p.mkdir(parents=True, exist_ok=True)
    return p


def _open_tax_modal(page):
    open_top_download_dropdown(page)
    click_first_visible(page, [
        lambda p: p.get_by_text("Tax Invoice", exact=True),
        'text="Tax Invoice"',
        '[role="menuitem"]:has-text("Tax Invoice")',
    ], what="'Tax Invoice' menu item")
    page.wait_for_timeout(1500)


def _calendar_header_text(page) -> str:
    """Return e.g. 'May 2026' from the modal calendar header."""
    for sel in [
        '[role="dialog"] :text-matches("\\\\b(January|February|March|April|May|June|July|August|September|October|November|December)\\\\s+\\\\d{4}\\\\b")',
    ]:
        try:
            loc = page.locator(sel).first
            if loc.is_visible():
                txt = (loc.text_content() or "").strip()
                if txt:
                    return txt
        except Exception:  # noqa: BLE001
            continue
    return ""


def _navigate_calendar_to(page, year: int, month: int):
    target = f"{MONTHS[month]} {year}"
    print(f"[tax_invoice]   navigating calendar to {target}")
    # click left arrow until header matches target. Cap at 36 hops (3 yrs)
    for _ in range(36):
        cur = _calendar_header_text(page)
        if cur.startswith(MONTHS[month]) and cur.endswith(str(year)):
            return
        # click left arrow
        click_first_visible(page, [
            '[role="dialog"] button[aria-label*="prev" i]',
            '[role="dialog"] button:has-text("‹")',
            '[role="dialog"] button:has-text("←")',
            '[role="dialog"] svg[aria-label*="prev" i]',
            # last resort: click first svg in the calendar header row
            lambda p: p.locator('[role="dialog"] button').first,
        ], what="calendar prev arrow", timeout=5_000)
        page.wait_for_timeout(400)
    raise RuntimeError(f"could not navigate calendar to {target}")


def _click_day(page, day: int):
    click_first_visible(page, [
        f'[role="dialog"] [role="gridcell"]:has-text("{day}")',
        f'[role="dialog"] button:has-text("{day}"):not(:has-text("0{day}"))',
        lambda p: p.locator('[role="dialog"]').get_by_text(str(day), exact=True),
    ], what=f"calendar day {day}", timeout=10_000)
    page.wait_for_timeout(400)


def _click_modal_download(page):
    click_first_visible(page, [
        '[role="dialog"] button:has-text("Download")',
        '[role="dialog"] [role="button"]:has-text("Download")',
        lambda p: p.locator('button:has-text("Download")').last,
    ], what="modal Tax Invoice Download button")


_NO_DATA_LOCATORS = [
    lambda p: p.get_by_text("No tax invoice", exact=False),
    'text=No tax invoice is available',
]


def _extract_only_xlsx(zip_path: Path, out_path: Path) -> Optional[Path]:
    with zipfile.ZipFile(zip_path) as zf:
        cands = [n for n in zf.namelist() if n.lower().endswith(".xlsx")]
        if not cands:
            return None
        target = max(cands, key=lambda n: zf.getinfo(n).file_size)
        with zf.open(target) as src, open(out_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return out_path


def _upload(xlsx_path: Optional[Path], account_id: str, job_id: str,
            year: int, month: int, from_date: str, to_date: str,
            original_zip_name: str, available: bool, reason: str) -> dict:
    if not WORKER_API_KEY:
        raise RuntimeError("WORKER_API_KEY env not set on worker")
    url = f"{DASHBOARD_URL.rstrip('/')}/api/pl/tax-invoice/upload"
    params = {
        "account_id": account_id, "job_id": job_id,
        "year": year, "month": month,
        "from_date": from_date, "to_date": to_date,
        "original_filename": original_zip_name,
        "available": "true" if available else "false",
        "reason": reason or "",
    }
    headers = {"X-Worker-Key": WORKER_API_KEY}
    if available and xlsx_path:
        with open(xlsx_path, "rb") as f:
            files = {"file": (xlsx_path.name, f,
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
            r = requests.post(url, params=params, files=files, headers=headers, timeout=180)
    else:
        r = requests.post(url, params=params, headers=headers, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"upload failed: HTTP {r.status_code} {r.text[:300]}")
    return r.json()


def run_tax_invoice_fetch_for_account(acc: dict, year: int, month: int, job_id: str) -> dict:
    if not (1 <= month <= 12):
        raise ValueError(f"invalid month: {month}")
    identifier = (acc.get("name") or "").strip()
    if not identifier:
        raise RuntimeError(f"account {acc.get('_id')} has empty name")
    port = int(acc["debug_port"])
    last_day = calendar.monthrange(year, month)[1]
    from_date = f"{year:04d}-{month:02d}-01"
    to_date = f"{year:04d}-{month:02d}-{last_day:02d}"
    out_dir = _account_dir(identifier, year, month)
    print(f"[tax_invoice] account='{identifier}' port={port} {from_date} → {to_date} → {out_dir}")

    p, browser, context, page = cdp_context_page(port)
    try:
        page.goto(payments_url(identifier), wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3500)

        outcome = None
        for attempt in range(1, DOWNLOAD_RETRIES + 1):
            print(f"[tax_invoice] attempt {attempt}/{DOWNLOAD_RETRIES}")
            try:
                _open_tax_modal(page)
                _navigate_calendar_to(page, year, month)
                _click_day(page, 1)         # From = day 1
                _click_day(page, last_day)  # To   = last day
                page.wait_for_timeout(500)
                _click_modal_download(page)
                kind, payload = watch_for_download_or_text(
                    page, _NO_DATA_LOCATORS, DOWNLOAD_TIMEOUT_MS,
                )
                if kind == "download":
                    suggested = payload.suggested_filename
                    zip_target = out_dir / f"{safe_dirname(identifier)}_{year:04d}-{month:02d}_TAX_INVOICE_RAW.zip"
                    payload.save_as(str(zip_target))
                    print(f"[tax_invoice]   ↓ saved zip {zip_target.name} ({zip_target.stat().st_size} bytes)")
                    xlsx_target = out_dir / f"{safe_dirname(identifier)}_{year:04d}-{month:02d}_TAX_INVOICE.xlsx"
                    if not _extract_only_xlsx(zip_target, xlsx_target):
                        raise RuntimeError("zip contained no xlsx")
                    outcome = ("ok", xlsx_target, zip_target, suggested)
                    break
                if kind == "no_data":
                    print(f"[tax_invoice]   ⚠ no-data: {payload}")
                    outcome = ("no_data", None, None, payload)
                    break
                print(f"[tax_invoice]   ! timeout on attempt {attempt}")
                screenshot_on_fail(page, out_dir, f"tax_timeout_a{attempt}")
            except Exception as e:  # noqa: BLE001
                print(f"[tax_invoice]   ! attempt {attempt} failed: {type(e).__name__}: {e}")
                screenshot_on_fail(page, out_dir, f"tax_fail_a{attempt}")
            if attempt < DOWNLOAD_RETRIES:
                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(500)
                    page.reload(wait_until="domcontentloaded", timeout=45_000)
                    page.wait_for_timeout(3000)
                except Exception as re:  # noqa: BLE001
                    print(f"[tax_invoice]   reload failed: {re}")

        if not outcome:
            raise RuntimeError(f"Tax invoice download did not start after {DOWNLOAD_RETRIES} attempts")
    finally:
        try:
            page.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            p.stop()
        except Exception:  # noqa: BLE001
            pass

    kind, xlsx_path, zip_path, payload = outcome
    if kind == "no_data":
        return _upload(None, str(acc["_id"]), job_id, year, month,
                       from_date, to_date, "",
                       available=False, reason=payload or "no tax invoice in selected period")

    try:
        result = _upload(xlsx_path, str(acc["_id"]), job_id, year, month,
                         from_date, to_date, payload,
                         available=True, reason="")
        result["source_filename"] = payload
        return result
    finally:
        for f in (xlsx_path, zip_path):
            try:
                if f:
                    f.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
