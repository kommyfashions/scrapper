"""Meesho Live Inventory scraper — job type: `inventory_sync`.

FLOW (finalised with operator, Feb 2026):
  1. Load `https://supplier.meesho.com/panel/v3/new/services/{suffix}/inventory`
  2. Dismiss the "Find all your live catalogs here" coach-mark.
  3. Ensure top tab = Active, sub-tab = All Stock.
  4. Sort catalogs by → Newest First.
  5. Iterate catalog cards in the left panel:
       - click each card
       - read the first `Style ID:` from the right panel
       - scroll the left panel to reveal more cards
  6. Advance the paginator; repeat until `pages_to_scrape` or last page.

Uses `page.evaluate` instead of brittle XPath because Meesho's DOM splits
label text across nested spans (so `text()="Catalog ID"` matches nothing).
"""
from __future__ import annotations

import os
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
DEFAULT_PAGES = 20
CATALOGS_PER_PAGE = 10


def _inventory_url(suffix: str) -> str:
    return f"https://supplier.meesho.com/panel/v3/new/services/{suffix}/inventory"


def _screenshot(page: Page, out_dir: Path, name: str) -> str:
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{name}.png"
        page.screenshot(path=str(path), full_page=False)
        return str(path)
    except Exception:  # noqa: BLE001
        return ""


# ---------- popup / onboarding ----------
def _dismiss_onboarding(page: Page) -> int:
    """Meesho shows a coach-mark tooltip ("Find all your live catalogs
    here — GOT IT") that intercepts every click. Also handles Skip Tour /
    Got It variants. Returns how many popups it dismissed."""
    return int(page.evaluate("""
        () => {
            const wanted = ["GOT IT","Got it","Got It","Skip Tour",
                            "Skip","Next"];
            let killed = 0;
            for (let round = 0; round < 6; round++) {
                let hit = false;
                const btns = document.querySelectorAll(
                    'button,[role="button"],div,span,a');
                for (const b of btns) {
                    if (!b || !b.offsetParent) continue;
                    const t = (b.innerText || b.textContent || '').trim();
                    if (!wanted.includes(t)) continue;
                    try { b.click(); killed++; hit = true; break; }
                    catch(e){}
                }
                if (!hit) break;
            }
            return killed;
        }
    """) or 0)


# ---------- tabs ----------
def _click_by_text(page: Page, text: str) -> bool:
    return bool(page.evaluate(f"""
        () => {{
            const target = {text!r};
            const nodes = document.querySelectorAll(
                'button,a,div,span,li,p');
            for (const n of nodes) {{
                if (!n.offsetParent) continue;
                const t = (n.innerText || n.textContent || '').trim();
                // exact match or with " (nnn)" suffix (Meesho tab counters)
                if (t === target
                    || t.startsWith(target + " (")
                    || t.startsWith(target + "(")) {{
                    try {{ n.click(); return true; }} catch(e) {{}}
                }}
            }}
            return false;
        }}
    """))


def _ensure_active_all_stock(page: Page) -> None:
    for label in ("Active", "All Stock"):
        try:
            _click_by_text(page, label)
            page.wait_for_timeout(700)
        except Exception:  # noqa: BLE001
            continue


# ---------- sort ----------
def _select_newest_first(page: Page) -> Dict[str, Any]:
    """Open the Sort dropdown and select 'Newest First' via JS to bypass
    any residual overlay."""
    _dismiss_onboarding(page)
    result = page.evaluate("""
        async () => {
            const sleep = ms => new Promise(r => setTimeout(r, ms));
            // (1) Locate the current sort trigger. The trigger is the
            // clickable element that shows the currently-selected value.
            const findTrigger = () => {
                const candidates = ["Highest Estimated Orders",
                                    "Newest First",
                                    "Lowest Estimated Orders"];
                const all = Array.from(document.querySelectorAll(
                    'button,div,span,p'));
                for (const el of all) {
                    if (!el.offsetParent) continue;
                    const t = (el.innerText || el.textContent || '').trim();
                    if (candidates.includes(t)) {
                        // Prefer the leaf-most match
                        if (el.children.length <= 3) return el;
                    }
                }
                return null;
            };
            const trigger = findTrigger();
            if (!trigger) {
                return {ok:false, reason:'no-trigger'};
            }
            const before = (trigger.innerText || '').trim();
            if (before === 'Newest First') {
                return {ok:true, already:true};
            }
            trigger.scrollIntoView({block:'center'});
            trigger.click();
            await sleep(700);
            // (2) After the menu opens, click "Newest First".
            const menuItems = Array.from(document.querySelectorAll(
                'div,button,span,li,p'));
            for (const el of menuItems) {
                if (!el.offsetParent) continue;
                const t = (el.innerText || el.textContent || '').trim();
                if (t === 'Newest First' && el.children.length <= 3) {
                    try { el.click(); }
                    catch (e) {
                        try { el.parentElement?.click(); } catch(e2){}
                    }
                    await sleep(1200);
                    // (3) verify
                    const t2 = findTrigger()?.innerText?.trim();
                    return {ok: t2 === 'Newest First',
                            before, after: t2};
                }
            }
            return {ok:false, reason:'no-menu-item', before};
        }
    """)
    return result or {"ok": False, "reason": "eval-failed"}


# ---------- catalog cards ----------
def _list_cards(page: Page) -> List[Dict[str, Any]]:
    """Return a list of {catalog_id, x, y, top} for every visible catalog
    card currently rendered in the left panel. Uses JS TreeWalker so it
    works regardless of how Meesho splits the DOM text."""
    return page.evaluate("""
        () => {
            const results = [];
            const seen = new Set();
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_TEXT, null, false);
            let node;
            const cards = [];
            while (node = walker.nextNode()) {
                const parent = node.parentElement;
                if (!parent) continue;
                const parentText = (parent.textContent || '').trim();
                const m = /Catalog ID[:\\s]*(\\d[\\d\\w-]*)/i.exec(parentText);
                if (!m) continue;
                const cid = m[1].replace(/[,\\s]+$/, '');
                if (seen.has(cid)) continue;
                // Walk up to the card container: nearest ancestor that
                // (a) contains an <img>, (b) does NOT contain more than
                // one "Catalog ID" occurrence.
                let el = parent;
                let card = null;
                for (let i = 0; i < 10 && el; i++) {
                    const hasImg = !!el.querySelector('img');
                    if (hasImg) {
                        const txt = (el.textContent || '');
                        const occ = (txt.match(/Catalog ID/gi) || []).length;
                        if (occ === 1) { card = el; break; }
                    }
                    el = el.parentElement;
                }
                if (!card) continue;
                const r = card.getBoundingClientRect();
                if (r.width < 40 || r.height < 30) continue;
                seen.add(cid);
                cards.push({
                    catalog_id: cid,
                    x: r.left + Math.min(80, r.width/2),
                    y: r.top + r.height/2,
                    top: r.top,
                    bottom: r.bottom,
                    height: r.height,
                });
            }
            // sort by vertical position (top-down)
            cards.sort((a,b) => a.top - b.top);
            return cards;
        }
    """) or []


def _click_card(page: Page, card: Dict[str, Any]) -> bool:
    try:
        page.mouse.click(card["x"], card["y"])
        page.wait_for_timeout(1200)
        return True
    except Exception:  # noqa: BLE001
        try:
            _dismiss_onboarding(page)
            page.mouse.click(card["x"], card["y"])
            page.wait_for_timeout(1200)
            return True
        except Exception:  # noqa: BLE001
            return False


def _scroll_left_panel(page: Page) -> bool:
    """Scroll the left-panel container that holds the catalog cards."""
    return bool(page.evaluate("""
        () => {
            // find a catalog card, then walk up to find its scrollable
            // ancestor.
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_TEXT, null, false);
            let node, target = null;
            while (node = walker.nextNode()) {
                if (/Catalog ID/i.test(node.nodeValue || '')) {
                    target = node.parentElement; break;
                }
            }
            if (!target) return false;
            let el = target;
            while (el && el !== document.body) {
                const s = getComputedStyle(el);
                if ((s.overflowY === 'auto' || s.overflowY === 'scroll')
                    && el.scrollHeight > el.clientHeight + 20) {
                    const before = el.scrollTop;
                    el.scrollTop = before + el.clientHeight * 0.8;
                    return el.scrollTop > before;
                }
                el = el.parentElement;
            }
            return false;
        }
    """) or False)


# ---------- style id extraction ----------
def _first_style_id(page: Page) -> Optional[str]:
    """Return the first 'Style ID: X' visible in the right panel."""
    try:
        page.wait_for_function(
            "() => /Style ID/i.test(document.body.innerText || '')",
            timeout=6_000,
        )
    except Exception:  # noqa: BLE001
        pass
    return page.evaluate("""
        () => {
            // Find the leaf-most element whose text starts with
            // "Style ID:". Prefer nodes that also contain an SKU line
            // (they're in the right panel product row).
            const all = Array.from(document.querySelectorAll(
                'div,span,p,td'));
            for (const el of all) {
                if (el.children.length > 5) continue;
                const t = (el.innerText || el.textContent || '').trim();
                const m = /^Style ID[:\\s]*([^\\n\\r]+)/i.exec(t);
                if (m) {
                    // Strip trailing "SKU:..." if it flowed together
                    return m[1].split(/\\s{2,}|\\n/)[0].trim();
                }
            }
            return null;
        }
    """)


# ---------- pagination ----------
def _click_page_number(page: Page, n: int) -> bool:
    return bool(page.evaluate(f"""
        () => {{
            const btns = Array.from(document.querySelectorAll(
                'button,li,a,span,div'));
            for (const b of btns) {{
                if (!b.offsetParent) continue;
                const t = (b.innerText || b.textContent || '').trim();
                if (t === {n!r}) {{
                    try {{
                        b.scrollIntoView({{block:'center'}});
                        b.click();
                        return true;
                    }} catch(e) {{}}
                }}
            }}
            return false;
        }}
    """) or False)


def _click_next_arrow(page: Page) -> bool:
    return bool(page.evaluate("""
        () => {
            const sel = [
                'button[aria-label="Go to next page"]',
                'button[aria-label="next page"]',
                'button[aria-label="Next page"]',
                'li.ant-pagination-next button',
            ];
            for (const s of sel) {
                const el = document.querySelector(s);
                if (el && el.offsetParent && !el.disabled) {
                    el.click(); return true;
                }
            }
            // fallback: chevron text
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                const t = (b.innerText || '').trim();
                if ((t === '›' || t === '>') && b.offsetParent
                    && !b.disabled) {
                    b.click(); return true;
                }
            }
            return false;
        }
    """) or False)


def _advance_page(page: Page, next_num: int) -> bool:
    if _click_page_number(page, next_num):
        page.wait_for_timeout(1500)
        return True
    if _click_next_arrow(page):
        page.wait_for_timeout(1500)
        return True
    return False


# ==================================================================
def run_inventory_sync_for_account(acc: dict, payload: dict) -> Dict[str, Any]:
    port = int(acc["debug_port"])
    suffix = (acc.get("name") or "").strip()
    if not suffix:
        raise RuntimeError("account has no `name` — cannot derive URL suffix")

    pages_to_scrape = int((payload or {}).get("pages") or DEFAULT_PAGES)
    pages_to_scrape = max(1, min(200, pages_to_scrape))

    account_id = str(acc["_id"])
    account_name = acc.get("name")
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    debug_dir = DEBUG_DIR / f"{suffix}_{ts}"

    all_rows: List[Dict[str, Any]] = []
    catalogs_scanned = 0
    pages_visited = 0
    diagnostics: List[Dict[str, Any]] = []
    processed_ids: Set[str] = set()

    p, _browser, _ctx, page = cdp_context_page(port)
    try:
        # Try to maximise / enlarge the viewport so nothing is hidden
        try:
            page.set_viewport_size({"width": 1600, "height": 1000})
        except Exception:  # noqa: BLE001
            pass

        page.goto(_inventory_url(suffix), wait_until="domcontentloaded",
                  timeout=PAGE_LOAD_MS)
        try:
            page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(2500)

        popups = _dismiss_onboarding(page)
        diagnostics.append({"stage": "dismiss_onboarding",
                            "popups_dismissed": popups})
        _screenshot(page, debug_dir, "00_after_onboarding")

        _ensure_active_all_stock(page)
        page.wait_for_timeout(1200)
        _dismiss_onboarding(page)

        sort_res = _select_newest_first(page)
        diagnostics.append({"stage": "sort_newest_first", **sort_res})
        _screenshot(page, debug_dir, "01_after_sort")

        # early sanity: are there any cards?
        cards = _list_cards(page)
        diagnostics.append({"stage": "initial_cards_check",
                            "cards_seen": len(cards)})
        if not cards:
            _screenshot(page, debug_dir, "no_cards")
            return {
                "catalogs_scanned": 0,
                "skus_captured": 0,
                "pages_visited": 0,
                "pages_requested": pages_to_scrape,
                "note": (f"0 catalog cards visible after landing + sort. "
                         f"Screenshots: {debug_dir}"),
                "diagnostics": diagnostics,
                "debug_dir": str(debug_dir),
            }

        current_page = 1
        while pages_visited < pages_to_scrape:
            pages_visited += 1
            _screenshot(page, debug_dir, f"page_{current_page}_start")
            iter_count = 0
            no_new_streak = 0
            page_ids_before = len(processed_ids)
            while iter_count < 40:
                iter_count += 1
                cards = _list_cards(page)
                new_cards = [c for c in cards
                             if c["catalog_id"] not in processed_ids]
                if not new_cards:
                    # try to scroll left panel to reveal more
                    scrolled = _scroll_left_panel(page)
                    if not scrolled:
                        no_new_streak += 1
                        if no_new_streak >= 2:
                            break
                    page.wait_for_timeout(600)
                    continue
                no_new_streak = 0
                for card in new_cards:
                    cid = card["catalog_id"]
                    if not _click_card(page, card):
                        diagnostics.append({"stage": "click_failed",
                                            "page": current_page,
                                            "catalog_id": cid})
                        processed_ids.add(cid)
                        continue
                    sid = _first_style_id(page)
                    processed_ids.add(cid)
                    if sid:
                        all_rows.append({
                            "account_id": account_id,
                            "account_name": account_name,
                            "style_id": sid,
                            "catalog_id": cid,
                            "page_no": current_page,
                        })
                        catalogs_scanned += 1
                    else:
                        diagnostics.append({"stage": "no_style_id",
                                            "page": current_page,
                                            "catalog_id": cid})
                    time.sleep(0.35)
                # nudge left panel down to reveal more of the same page
                _scroll_left_panel(page)
                page.wait_for_timeout(500)
                if len(processed_ids) - page_ids_before >= CATALOGS_PER_PAGE:
                    break

            _screenshot(page, debug_dir, f"page_{current_page}_end")

            if pages_visited >= pages_to_scrape:
                break
            current_page += 1
            if not _advance_page(page, current_page):
                diagnostics.append({"stage": "pagination_exhausted",
                                    "reached_page": current_page - 1})
                break
            _dismiss_onboarding(page)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        diagnostics.append({"stage": "fatal",
                            "error": f"{type(e).__name__}: {e}"})
        _screenshot(page, debug_dir, "fatal")
    finally:
        try:
            page.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            p.stop()
        except Exception:  # noqa: BLE001
            pass

    # persist — replace this account's snapshot atomically
    mongo_url = os.environ.get("MESHO_MONGO_URI") or os.environ.get(
        "MONGO_URL", "mongodb://127.0.0.1:27017/")
    db_name = os.environ.get("MESHO_DB_NAME") or os.environ.get(
        "DB_NAME", "meesho")
    now = datetime.now(timezone.utc)
    try:
        client = MongoClient(mongo_url)
        db = client[db_name]
        db.meesho_live_skus.delete_many({"account_id": account_id})
        if all_rows:
            for r in all_rows:
                r["scraped_at"] = now
            db.meesho_live_skus.insert_many(all_rows, ordered=False)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        raise RuntimeError(f"persist failed: {e}")

    note = ""
    if not all_rows:
        note = (f"0 rows captured across {pages_visited} page(s). "
                f"Screenshots: {debug_dir}")
    return {
        "catalogs_scanned": catalogs_scanned,
        "skus_captured": len(all_rows),
        "pages_visited": pages_visited,
        "pages_requested": pages_to_scrape,
        "note": note,
        "diagnostics": diagnostics,
        "debug_dir": str(debug_dir),
    }
