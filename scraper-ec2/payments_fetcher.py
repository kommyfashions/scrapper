"""
Meesho Payments-File auto-downloader (EC2).

Driven by `payments_fetch` jobs from the dashboard. For each job the worker:

  1. CDP-attaches to the account's already-running Chrome (port from
     `accounts.debug_port`).
  2. Navigates to https://supplier.meesho.com/panel/v3/new/payouts/{name}/payments
  3. Clicks Download → Payments to Date → selects the requested period
     radio → clicks Download (modal). The download is captured via
     Playwright's expect_download() so we get the *exact* filename Meesho
     proposes (e.g. 2356789_SP_ORDER_ADS_REFERRAL_PAYMENT_FILE_PREVIOUS_PAYMENT_2026-04-01_2026-04-30.zip).
  4. Saves the .zip into a *per-account, per-period* folder:
        <DOWNLOAD_DIR>/<safe_account>/<period>/<filename>.zip
     This keeps multi-account runs from colliding even if scheduling overlaps.
  5. Retries the modal Download click up to 3 times with a page.reload()
     in between if no download event fires within 30s. After that the job
     fails with a clear error.
  6. Extracts the .xlsx out of the zip.
  7. POSTs the xlsx to the dashboard /api/pl/upload?account_id=&job_id=&source_filename=
     using the shared X-Worker-Key header. The dashboard validates and
     persists `source_filename` on the upload record for traceability.
  8. Cleans up the zip + xlsx (the per-account folder stays for audit).

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
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:8001")
WORKER_API_KEY = os.environ.get("WORKER_API_KEY", "")
DOWNLOAD_DIR = Path(os.environ.get("MESHO_DOWNLOAD_DIR", "/home/ubuntu/meesho-downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

PERIOD_LABEL = {
    "previous_week": "Previous Week",
    "previous_month": "Previous Month",
    "last_payment": "Last Payment",
}

DOWNLOAD_RETRIES = 3
DOWNLOAD_EVENT_TIMEOUT_MS = 30_000  # how long expect_download() waits per try


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _safe_dirname(name: str) -> str:
    """Make an account name safe to use as a folder."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", (name or "unknown").strip()) or "unknown"


def _payments_url(identifier: str) -> str:
    return f"https://supplier.meesho.com/panel/v3/new/payouts/{identifier}/payments"


def _account_dir(acc_name: str, period: str) -> Path:
    p = DOWNLOAD_DIR / _safe_dirname(acc_name) / _safe_dirname(period)
    p.mkdir(parents=True, exist_ok=True)
    return p


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


def _upload_to_dashboard(xlsx_path: Path, account_id: str, job_id: str,
                         source_filename: str) -> dict:
    if not WORKER_API_KEY:
        raise RuntimeError("WORKER_API_KEY env not set on worker")
    url = f"{DASHBOARD_URL.rstrip('/')}/api/pl/upload"
    with open(xlsx_path, "rb") as f:
        files = {
            "file": (
                xlsx_path.name,
                f,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        }
        params = {
            "account_id": account_id,
            "job_id": job_id,
            "source_filename": source_filename,
        }
        headers = {"X-Worker-Key": WORKER_API_KEY}
        r = requests.post(url, params=params, files=files, headers=headers, timeout=180)
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
            print(f"[payments_fetcher]   ✓ clicked {what}")
            return
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise RuntimeError(
        f"could not find clickable '{what}': "
        f"{type(last_err).__name__ if last_err else 'NotFound'}: {last_err}"
    )


def _open_download_menu(page, period_label: str):
    """Click Download → Payments to Date → select period radio. Stops
    just before the modal Download button so the caller can wrap that
    click inside expect_download()."""
    try:
        page.wait_for_load_state("networkidle", timeout=30_000)
    except PWTimeout:
        pass
    page.wait_for_timeout(1500)

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


def _click_modal_download(page):
    """Click the Download button inside the modal. Caller wraps this
    in expect_download()."""
    _click_first_visible(page, [
        '[role="dialog"] button:has-text("Download")',
        '[role="dialog"] [role="button"]:has-text("Download")',
        lambda p: p.locator('button:has-text("Download")').last,
        lambda p: p.locator('[role="button"]:has-text("Download")').last,
    ], what="modal Download button")


def _try_capture_download(page, period_label: str, debug_dir: Path):
    """Run the click flow, capture the Download event. Returns Playwright
    Download object on success. Saves a debug screenshot and re-raises on
    failure."""
    try:
        _open_download_menu(page, period_label)
        with page.expect_download(timeout=DOWNLOAD_EVENT_TIMEOUT_MS) as dl_info:
            _click_modal_download(page)
        return dl_info.value
    except Exception:
        ts = time.strftime("%Y%m%d-%H%M%S")
        path = debug_dir / f"payments_fetch_fail_{ts}.png"
        try:
            page.screenshot(path=str(path), full_page=True)
            print(f"[payments_fetcher] ✗ saved failure screenshot → {path}")
        except Exception as e2:  # noqa: BLE001
            print(f"[payments_fetcher] could not save screenshot: {e2}")
        raise


# ---------------------------------------------------------------------------
# main entry
# ---------------------------------------------------------------------------
def run_payments_fetch_for_account(acc: dict, period: str, job_id: str) -> dict:
    if period not in PERIOD_LABEL:
        raise ValueError(f"unsupported period: {period}")
    label = PERIOD_LABEL[period]
    identifier = (acc.get("name") or "").strip()
    if not identifier:
        raise RuntimeError(f"account {acc.get('_id')} has empty name (Meesho identifier)")
    port = int(acc["debug_port"])
    cdp = f"http://127.0.0.1:{port}"

    out_dir = _account_dir(identifier, period)
    print(f"[payments_fetcher] account='{identifier}' port={port} period={period} → {out_dir}")

    download = None
    suggested = None
    last_err: Optional[Exception] = None

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp)
        if not browser.contexts:
            raise RuntimeError(f"no browser context on port {port}; is Chrome started?")
        context = browser.contexts[0]
        page = context.new_page()
        try:
            page.goto(_payments_url(identifier), wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3500)

            for attempt in range(1, DOWNLOAD_RETRIES + 1):
                print(f"[payments_fetcher] download attempt {attempt}/{DOWNLOAD_RETRIES}")
                try:
                    download = _try_capture_download(page, label, out_dir)
                    suggested = download.suggested_filename
                    print(f"[payments_fetcher]   ↓ captured filename={suggested}")
                    break
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    print(f"[payments_fetcher]   ! attempt {attempt} failed: {type(e).__name__}: {e}")
                    if attempt < DOWNLOAD_RETRIES:
                        try:
                            # close any modal/menu and refresh
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(500)
                            page.reload(wait_until="domcontentloaded", timeout=45_000)
                            page.wait_for_timeout(3000)
                        except Exception as re:  # noqa: BLE001
                            print(f"[payments_fetcher]   reload failed: {re}")
                    continue

            if not download or not suggested:
                raise RuntimeError(
                    f"download did not start after {DOWNLOAD_RETRIES} attempts: {last_err}"
                )

            zip_path = out_dir / suggested
            try:
                download.save_as(str(zip_path))
            except Exception as e:  # noqa: BLE001
                raise RuntimeError(f"could not save downloaded file: {e}")
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass

    if not zip_path.exists() or zip_path.stat().st_size == 0:
        raise RuntimeError(f"downloaded file missing or empty: {zip_path}")

    print(f"[payments_fetcher] zip saved: {zip_path} ({zip_path.stat().st_size} bytes)")

    # Meesho sometimes serves the .xlsx directly (no zip). Handle both.
    try:
        if zip_path.suffix.lower() == ".zip":
            xlsx_path = _extract_xlsx(zip_path, out_dir)
            if not xlsx_path:
                raise RuntimeError("zip contained no .xlsx")
        elif zip_path.suffix.lower() in (".xlsx", ".xls"):
            xlsx_path = zip_path  # treat as the xlsx itself
        else:
            raise RuntimeError(f"unsupported downloaded file type: {zip_path.suffix}")

        print(f"[payments_fetcher] uploading {xlsx_path.name} → dashboard")
        result = _upload_to_dashboard(
            xlsx_path,
            str(acc["_id"]),
            job_id,
            source_filename=suggested,
        )
        print(f"[payments_fetcher] upload result: {result}")
        # surface the suggested filename so the dispatcher can store it on the job
        result["source_filename"] = suggested
        return result
    finally:
        # cleanup transient files; per-account folder is preserved for audit
        try:
            if zip_path.suffix.lower() == ".zip":
                zip_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        try:
            if 'xlsx_path' in locals() and xlsx_path and xlsx_path != zip_path:
                xlsx_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
