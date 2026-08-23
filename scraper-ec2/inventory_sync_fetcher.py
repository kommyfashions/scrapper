"""Meesho Live Inventory scraper — job type: `inventory_sync`.

STATUS: still tuning against real Meesho DOM. This build dumps heavy
diagnostics into the job.result so the operator can share back what the
scraper actually saw.

Landing URL candidates tried in order:
  1. https://supplier.meesho.com/panel/v3/new/services/<suffix>/inventory
  2. https://supplier.meesho.com/panel/v3/new/services/<suffix>/inventory/product
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
MONEY_RE = re.compile(r"[\d,]+(?:\.\d+)?")


def _urls(suffix: str) -> List[str]:
    return [
        f"https://supplier.meesho.com/panel/v3/new/services/{suffix}/inventory",
        f"https://supplier.meesho.com/panel/v3/new/services/{suffix}/inventory/product",
    ]


def _safe_text(node, timeout_ms: int = 1500) -> str:
    try:
        return (node.inner_text(timeout=timeout_ms) or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _first_number(s: str) -> Optional[float]:
    m = MONEY_RE.search(s or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except Exception:  # noqa: BLE001
        return None


def _screenshot(page: Page, out_dir: Path, name: str) -> str:
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{name}.png"
        page.screenshot(path=str(path), full_page=False)
        return str(path)
    except Exception:  # noqa: BLE001
        return ""


def _select_active_tab(page: Page) -> None:
    for label in ("Active", "ACTIVE"):
        try:
            loc = page.locator(f'xpath=//*[normalize-space(text())="{label}"]').first
            if loc.count() > 0:
                loc.click(timeout=3000)
                page.wait_for_timeout(1500)
                return
        except Exception:  # noqa: BLE001
            continue


def _diagnose(page: Page) -> Dict[str, Any]:
    """Return a snapshot of page state — useful when scraping fails to find
    the expected cards."""
    d: Dict[str, Any] = {
        "url": None,
        "title": None,
        "body_preview": "",
        "has_catalog_id_text": False,
        "has_style_id_text": False,
        "has_search_input": False,
        "has_pagination_next": False,
        "row_count": 0,
    }
    try:
        d["url"] = page.url
    except Exception:  # noqa: BLE001
        pass
    try:
        d["title"] = page.title()
    except Exception:  # noqa: BLE001
        pass
    try:
        d["body_preview"] = (
            (page.locator("body").first.inner_text(timeout=3000) or "")[:600]
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        d["has_catalog_id_text"] = (
            page.locator('text=Catalog ID').count() > 0
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        d["has_style_id_text"] = (
            page.locator('text=Style ID').count() > 0
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        d["has_search_input"] = (
            page.locator('input[placeholder*="Search"]').count() > 0
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        d["has_pagination_next"] = (
            page.locator('button[aria-label="Go to next page"]').count() > 0
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        d["row_count"] = page.locator("tbody tr").count()
    except Exception:  # noqa: BLE001
        pass
    return d


def _try_land_on_inventory(page: Page, suffix: str,
                            debug_dir: Path) -> Dict[str, Any]:
    """Navigate through URL candidates and return diagnostics for the one
    that actually shows inventory content."""
    for i, url in enumerate(_urls(suffix), 1):
        try:
            page.goto(url, wait_until="domcontentloaded",
                      timeout=PAGE_LOAD_MS)
            try:
                page.wait_for_load_state("networkidle", timeout=12_000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(2500)
            _select_active_tab(page)
            page.wait_for_timeout(1500)
            d = _diagnose(page)
            d["tried_url"] = url
            d["screenshot"] = _screenshot(
                page, debug_dir, f"land_{i}")
            if d["has_catalog_id_text"] or d["has_style_id_text"] or d["row_count"] > 0:
                return d
        except Exception as e:  # noqa: BLE001
            d = {"tried_url": url, "error": f"{type(e).__name__}: {e}"}
            continue
    return d


def _extract_catalog_cards(page: Page) -> List[Dict[str, str]]:
    """Try multiple selector strategies to find the catalog list."""
    seen: Set[str] = set()
    out: List[Dict[str, str]] = []
    # Strategy A: XPath contains "Catalog ID:" — earliest hypothesis
    try:
        cards = page.locator(
            'xpath=//div[.//*[contains(normalize-space(text()), '
            '"Catalog ID")] and .//*[contains(normalize-space(text()), '
            '"Category")]]'
        )
        n = cards.count()
        for i in range(n):
            text = _safe_text(cards.nth(i))
            if not text:
                continue
            cid = None
            cat = None
            name = None
            for line in [ln.strip() for ln in text.splitlines()
                         if ln.strip()]:
                low = line.lower()
                if low.startswith("catalog id"):
                    cid = line.split(":", 1)[1].strip()
                elif low.startswith("category"):
                    cat = line.split(":", 1)[1].strip()
                elif name is None and ":" not in line and len(line) < 120:
                    name = line
            if cid and cid not in seen:
                seen.add(cid)
                out.append({"name": name or "", "catalog_id": cid,
                            "category": cat or ""})
    except Exception:  # noqa: BLE001
        pass
    # Strategy B: tbody tr rows on catalog list — some tenants use tables
    if not out:
        try:
            rows = page.locator("tbody tr")
            n = rows.count()
            for i in range(n):
                text = _safe_text(rows.nth(i))
                m = re.search(r"Catalog ID[:\s]*(\S+)", text)
                if not m:
                    continue
                cid = m.group(1).strip().rstrip(",")
                if cid in seen:
                    continue
                seen.add(cid)
                catm = re.search(r"Category[:\s]*([^\n]+)", text)
                out.append({
                    "name": text.split("\n", 1)[0].strip(),
                    "catalog_id": cid,
                    "category": (catm.group(1).strip() if catm else ""),
                })
        except Exception:  # noqa: BLE001
            pass
    return out


def _click_catalog_by_id(page: Page, cid: str) -> bool:
    for _ in range(3):
        try:
            card = page.locator(
                f'xpath=//*[contains(normalize-space(.), "{cid}")]').first
            if card.count() == 0:
                page.wait_for_timeout(400)
                continue
            card.scroll_into_view_if_needed(timeout=2000)
            card.click(timeout=3000)
            page.wait_for_timeout(1200)
            return True
        except Exception:  # noqa: BLE001
            page.wait_for_timeout(400)
    return False


def _extract_skus(page: Page, cat: Dict[str, str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        page.wait_for_selector(
            'xpath=//*[contains(normalize-space(.), "Style ID")]',
            timeout=6_000,
        )
    except Exception:  # noqa: BLE001
        return rows
    try:
        blocks = page.locator(
            'xpath=//*[contains(normalize-space(.), "Style ID:") and '
            'contains(normalize-space(.), "SKU:")]'
        )
        n = blocks.count()
    except Exception:  # noqa: BLE001
        return rows
    for i in range(n):
        try:
            text = _safe_text(blocks.nth(i))
        except Exception:  # noqa: BLE001
            continue
        if not text:
            continue
        style_id = None
        sku = None
        price = None
        for line in [ln.strip() for ln in text.splitlines() if ln.strip()]:
            low = line.lower()
            if low.startswith("style id"):
                style_id = line.split(":", 1)[1].strip()
            elif low.startswith("sku"):
                sku = line.split(":", 1)[1].strip()
            elif "meesho price" in low or "₹" in line:
                p = _first_number(line)
                if p is not None:
                    price = p
        if not sku:
            continue
        variation = None
        try:
            row_container = blocks.nth(i).locator(
                'xpath=ancestor::*[self::tr or (@role="row")][1]').first
            row_text = _safe_text(row_container)
        except Exception:  # noqa: BLE001
            row_text = ""
        m = re.search(
            r"\b(IND-\d+|S|M|L|XL|XXL|XXXL|Free\s*Size)\b",
            row_text, re.IGNORECASE,
        )
        if m:
            variation = m.group(1).upper().replace(" ", "")
        rows.append({
            "catalog_id": cat.get("catalog_id"),
            "catalog_name": cat.get("name"),
            "category": cat.get("category"),
            "style_id": style_id or sku,
            "sku": sku,
            "variation": variation,
            "price": price,
            "current_stock": None,
        })
    return rows


def _click_next_page(page: Page) -> bool:
    try:
        btn = page.locator('button[aria-label="Go to next page"]').first
        if btn.count() == 0:
            return False
        if not btn.is_visible(timeout=1500):
            return False
        if btn.is_disabled(timeout=1500):
            return False
        btn.click(timeout=3000)
        page.wait_for_timeout(1500)
        return True
    except Exception:  # noqa: BLE001
        return False


def run_inventory_sync_for_account(acc: dict, payload: dict) -> Dict[str, Any]:
    port = int(acc["debug_port"])
    suffix = (acc.get("name") or "").strip()
    if not suffix:
        raise RuntimeError("account has no `name` — cannot derive URL suffix")

    account_id = str(acc["_id"])
    account_name = acc.get("name")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    debug_dir = DEBUG_DIR / f"{suffix}_{ts}"

    all_rows: List[Dict[str, Any]] = []
    catalogs_scanned = 0
    pages_visited = 0
    diagnostics: List[Dict[str, Any]] = []

    p, _browser, _ctx, page = cdp_context_page(port)
    try:
        landing = _try_land_on_inventory(page, suffix, debug_dir)
        diagnostics.append({"stage": "landing", **landing})

        # Bail out early with diagnostics if we didn't find anything
        if not (landing.get("has_catalog_id_text")
                or landing.get("has_style_id_text")
                or (landing.get("row_count") or 0) > 0):
            return {
                "catalogs_scanned": 0,
                "skus_captured": 0,
                "pages_visited": 0,
                "note": (
                    f"Inventory page loaded but no expected markers found. "
                    f"landed_url={landing.get('url')}  "
                    f"title={landing.get('title')}  "
                    f"body_preview={(landing.get('body_preview') or '')[:200]!r}  "
                    f"Screenshot: {landing.get('screenshot')}"
                ),
                "diagnostics": diagnostics,
                "debug_dir": str(debug_dir),
            }

        MAX_PAGES = 100
        seen: Set[str] = set()
        while pages_visited < MAX_PAGES:
            pages_visited += 1
            cards = _extract_catalog_cards(page)
            _screenshot(page, debug_dir, f"page_{pages_visited}")
            diagnostics.append({
                "stage": f"list_page_{pages_visited}",
                "cards_seen": len(cards),
            })
            new_before = catalogs_scanned
            for cat in cards:
                cid = cat["catalog_id"]
                if cid in seen:
                    continue
                seen.add(cid)
                if not _click_catalog_by_id(page, cid):
                    diagnostics.append({
                        "stage": "click_failed", "catalog_id": cid,
                    })
                    continue
                _screenshot(page, debug_dir, f"catalog_{cid[:24]}")
                rows = _extract_skus(page, cat)
                for r in rows:
                    r["account_id"] = account_id
                    r["account_name"] = account_name
                all_rows.extend(rows)
                catalogs_scanned += 1
                time.sleep(0.4)
            if catalogs_scanned == new_before and not _click_next_page(page):
                break
            if not _click_next_page(page):
                break
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        diagnostics.append({"stage": "fatal",
                            "error": f"{type(e).__name__}: {e}"})
    finally:
        try:
            page.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            p.stop()
        except Exception:  # noqa: BLE001
            pass

    # persist — atomic replace for this account (only if we captured something)
    mongo_url = os.environ.get("MESHO_MONGO_URI") or os.environ.get(
        "MONGO_URL", "mongodb://127.0.0.1:27017/")
    db_name = os.environ.get("MESHO_DB_NAME") or os.environ.get(
        "DB_NAME", "meesho")
    now = datetime.now(timezone.utc)
    try:
        client = MongoClient(mongo_url)
        db = client[db_name]
        if all_rows:
            db.meesho_live_skus.delete_many({"account_id": account_id})
            for r in all_rows:
                r["synced_at"] = now
            db.meesho_live_skus.insert_many(all_rows, ordered=False)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        raise RuntimeError(f"persist failed: {e}")

    note = ""
    if not all_rows:
        note = (f"0 rows captured. Check screenshots in {debug_dir}. "
                f"Diagnostics: {diagnostics}")
    return {
        "catalogs_scanned": catalogs_scanned,
        "skus_captured": len(all_rows),
        "pages_visited": pages_visited,
        "note": note,
        "diagnostics": diagnostics,
        "debug_dir": str(debug_dir),
    }
