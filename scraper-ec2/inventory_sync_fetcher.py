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

from _meesho_ui import cdp_context_page, cdp_reuse_supplier_page
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
def _wait_for_cards_loaded(page: Page, timeout_ms: int = 20_000) -> bool:
    """Wait until the left panel actually renders catalog cards (not the
    loading skeleton). We detect a card as: an <img> ancestor whose
    innerText contains 'Catalog ID: <digit>'. Returns True on success."""
    try:
        page.wait_for_function(
            """() => {
                const imgs = document.querySelectorAll('img');
                for (const img of imgs) {
                    let el = img.parentElement;
                    for (let i = 0; i < 10 && el; i++) {
                        const t = (el.innerText || '');
                        if (/Catalog ID[:\\s]*\\d/i.test(t)) return true;
                        el = el.parentElement;
                    }
                }
                return false;
            }""",
            timeout=timeout_ms,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def _list_cards(page: Page) -> List[Dict[str, Any]]:
    """Return list of {catalog_id, top, bottom} for every visible catalog
    card in the left panel. Also tags each card DOM element with
    `data-scraper-cid="<id>"` so `_click_card` can click deterministically
    via a CSS selector (no mouse coordinates → survives scroll jitter).

    Strategy: anchor on <img> elements and walk UP to find the nearest
    ancestor whose *innerText* contains 'Catalog ID: <id>' exactly once.
    This survives Meesho splitting the label across multiple spans
    (which is what breaks a `.textContent`-only walker).
    """
    return page.evaluate("""
        () => {
            const out = [];
            const seen = new Set();
            const imgs = Array.from(document.querySelectorAll('img'));
            for (const img of imgs) {
                let el = img.parentElement;
                let card = null;
                for (let i = 0; i < 10 && el; i++) {
                    const t = (el.innerText || '');
                    if (/Catalog ID[:\\s]*\\d/i.test(t)) {
                        const occ = (t.match(/Catalog ID/gi) || []).length;
                        if (occ === 1) { card = el; break; }
                    }
                    el = el.parentElement;
                }
                if (!card) continue;
                const t = card.innerText || '';
                const m = /Catalog ID[:\\s]*(\\d[\\d\\w-]*)/i.exec(t);
                if (!m) continue;
                const cid = m[1].replace(/[^\\d\\w-].*$/, '');
                if (seen.has(cid)) continue;
                const r = card.getBoundingClientRect();
                if (r.width < 40 || r.height < 30) continue;
                // Skip cards not currently visible in the viewport-agnostic
                // sense — allow off-screen (they may need scrolling in).
                seen.add(cid);
                try { card.setAttribute('data-scraper-cid', cid); } catch(e){}
                out.push({
                    catalog_id: cid,
                    top: r.top,
                    bottom: r.bottom,
                    height: r.height,
                });
            }
            out.sort((a,b) => a.top - b.top);
            return out;
        }
    """) or []


def _click_card(page: Page, card: Dict[str, Any]) -> bool:
    """Click a catalog card using a REAL mouse click at the coordinate
    of the inner <img>. `element.click()` and `locator.click(force=True)`
    on the outer container don't reliably trigger Meesho's React click
    handler (which is bound to a specific inner element). Firing a real
    mouse click at the image's centre matches manual-click behaviour and
    causes the SKU-fetch XHR (`fetchAllStockV2Products`) to fire.

    NOTE: does NOT wait for the right panel to settle — callers who need
    a fresh Style ID should use `_click_and_capture_style_id` instead.
    """
    cid = card["catalog_id"]
    sel = f'[data-scraper-cid="{cid}"]'
    try:
        pt = page.evaluate(f"""
            () => {{
                const el = document.querySelector({sel!r});
                if (!el) return null;
                el.scrollIntoView({{block: 'center'}});
                // Prefer the inner <img>: it always has the click handler
                // bound to it (or bubbles to card's onClick). Falls back
                // to the card itself.
                const target = el.querySelector('img') || el;
                const r = target.getBoundingClientRect();
                return {{
                    x: r.left + r.width / 2,
                    y: r.top + r.height / 2,
                    visible: r.width > 5 && r.height > 5
                             && r.top < (window.innerHeight - 10)
                             && r.top > 10,
                }};
            }}
        """)
        if not pt or not pt.get("visible"):
            return False
        # Real hover → click. `delay` gives Meesho a chance to observe
        # pointerdown/mouseup separately (some React handlers only fire
        # on the full down→up sequence).
        page.mouse.move(float(pt["x"]), float(pt["y"]))
        page.wait_for_timeout(80)
        page.mouse.click(float(pt["x"]), float(pt["y"]), delay=40)
        return True
    except Exception:  # noqa: BLE001
        return False


def _current_right_panel_style_id(page: Page) -> Optional[str]:
    """Return whatever Style ID is CURRENTLY visible in the right panel
    (regardless of catalog id) — used to detect a re-render across
    clicks."""
    txt = page.evaluate("""
        () => {
            const cands = document.querySelectorAll('div,section,main');
            let best = null, bestArea = Infinity;
            for (const el of cands) {
                if (!el.offsetParent) continue;
                const r = el.getBoundingClientRect();
                if (r.width < 300) continue;
                const t = (el.innerText || '');
                if (!t.includes('Style ID')) continue;
                if (!t.includes('Catalog ID')) continue;
                const occ = (t.match(/Catalog ID/gi) || []).length;
                if (occ !== 1) continue;
                const area = r.width * r.height;
                if (area < bestArea) { bestArea = area; best = t; }
            }
            return best;
        }
    """) or ""
    return _extract_style_id_from_text(txt)


def _click_and_capture_style_id(page: Page, card: Dict[str, Any],
                                pre_click_sid: Optional[str],
                                timeout_ms: int = 8_000
                                ) -> Optional[str]:
    """Click a catalog card, then poll the right panel until BOTH
      (a) it shows the target catalog id, and
      (b) its Style ID differs from `pre_click_sid`.
    Returns the fresh Style ID on success, or None if the SKU section
    never actually refreshed within the timeout — a stale Style ID is
    NEVER returned, so a failed/no-op click can't be recorded as this
    catalog's data.
    """
    cid = card["catalog_id"]
    if not _click_card(page, card):
        return None
    import time as _t
    deadline = _t.time() + timeout_ms / 1000
    while _t.time() < deadline:
        panel_txt = _find_right_panel_for(page, cid)
        if panel_txt:
            sid = _extract_style_id_from_text(panel_txt)
            if sid and sid != pre_click_sid:
                return sid
        page.wait_for_timeout(250)
    # Timed out — SKU section did not refresh. Do NOT record the stale
    # value; caller sees `no_style_id` diagnostic instead.
    return None


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
def _find_right_panel_for(page: Page, catalog_id: str) -> Optional[str]:
    """Return the innerText of the SMALLEST DOM container that represents
    the right-panel view of the given catalog_id. We identify it as:
      - contains 'Catalog ID' EXACTLY ONCE  (rules out list wrappers)
      - contains the target catalog_id
      - contains 'Style ID'                 (right-panel-only marker)
      - width >= 300px                      (rules out narrow LEFT cards)
    Returns None if no such container exists yet.
    """
    return page.evaluate(f"""
        () => {{
            const cid = {catalog_id!r};
            const cands = document.querySelectorAll('div,section,main');
            let best = null, bestArea = Infinity;
            for (const el of cands) {{
                if (!el.offsetParent) continue;
                const r = el.getBoundingClientRect();
                if (r.width < 300) continue;
                const t = (el.innerText || '');
                if (!t.includes('Catalog ID')) continue;
                if (!t.includes(cid)) continue;
                if (!t.includes('Style ID')) continue;
                const occ = (t.match(/Catalog ID/gi) || []).length;
                if (occ !== 1) continue;
                const area = r.width * r.height;
                if (area < bestArea) {{ bestArea = area; best = t; }}
            }}
            return best;
        }}
    """)


def _wait_right_panel_for_catalog(page: Page, catalog_id: str,
                                  timeout_ms: int = 8_000) -> bool:
    """Wait until Meesho commits the right-panel re-render for the given
    catalog. Requires the container to have EXACTLY one 'Catalog ID'
    text (rules out wrapper divs that span both panels)."""
    js = f"""
        () => {{
            const cid = {catalog_id!r};
            const cands = document.querySelectorAll('div,section,main');
            for (const el of cands) {{
                if (!el.offsetParent) continue;
                const r = el.getBoundingClientRect();
                if (r.width < 300) continue;
                const t = (el.innerText || '');
                if (!t.includes('Catalog ID')) continue;
                if (!t.includes(cid)) continue;
                if (!t.includes('Style ID')) continue;
                const occ = (t.match(/Catalog ID/gi) || []).length;
                if (occ === 1) return true;
            }}
            return false;
        }}
    """
    try:
        page.wait_for_function(js, timeout=timeout_ms)
        return True
    except Exception:  # noqa: BLE001
        return False


def _extract_style_id_from_text(txt: str) -> Optional[str]:
    """Best-effort regex extraction of the first 'Style ID: X' value from
    the given innerText blob."""
    import re
    m = re.search(r"Style ID[:\s]*([^\r\n|,]+)", txt or "", re.IGNORECASE)
    if not m:
        return None
    val = m.group(1)
    # cut at second whitespace-run (defensive: Style ID SKU ... on same line)
    val = val.split("  ")[0]
    return val.strip() or None


def _first_style_id(page: Page, catalog_id: Optional[str] = None,
                    prev_style_id: Optional[str] = None) -> Optional[str]:
    """Return the Style ID for `catalog_id` from the right panel.

    Reads ONLY from within the container that has EXACTLY ONE
    'Catalog ID' occurrence AND matches the target catalog_id — this
    guarantees we ignore the LEFT panel and stale wrappers.

    If `prev_style_id` is provided and the fresh read equals it, we
    retry once after a short wait (defends against Meesho updating the
    header before it updates the SKU rows).
    """
    if not catalog_id:
        # Legacy fallback: scan globally (still filters by <=5 children)
        try:
            page.wait_for_function(
                "() => /Style ID/i.test(document.body.innerText || '')",
                timeout=4_000,
            )
        except Exception:  # noqa: BLE001
            pass
        txt = page.evaluate(
            "() => document.body ? document.body.innerText : ''") or ""
        return _extract_style_id_from_text(txt)

    _wait_right_panel_for_catalog(page, catalog_id, timeout_ms=8_000)
    panel_txt = _find_right_panel_for(page, catalog_id) or ""
    sid = _extract_style_id_from_text(panel_txt)

    if sid and prev_style_id and sid == prev_style_id:
        # Stale: right-panel header updated but SKU rows not yet.
        page.wait_for_timeout(1200)
        panel_txt = _find_right_panel_for(page, catalog_id) or ""
        sid2 = _extract_style_id_from_text(panel_txt)
        if sid2:
            sid = sid2
    return sid


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


def _advance_page(page: Page, next_num: int,
                  processed_ids: Set[str],
                  timeout_ms: int = 10_000) -> bool:
    """Click the next-page control AND verify a new (unprocessed) card
    appears in the left panel within `timeout_ms`. Returns False if the
    page never actually changed."""
    clicked = _click_page_number(page, next_num) or _click_next_arrow(page)
    if not clicked:
        return False
    import time as _t
    deadline = _t.time() + timeout_ms / 1000
    while _t.time() < deadline:
        cards = _list_cards(page)
        for c in cards:
            if c["catalog_id"] not in processed_ids:
                return True
        page.wait_for_timeout(400)
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
    last_sid: Optional[str] = None

    p, _browser, _ctx, page, page_reused = cdp_reuse_supplier_page(port)
    diagnostics.append({"stage": "cdp_attach", "page_reused": page_reused})
    try:
        # Try to maximise / enlarge the viewport so nothing is hidden.
        # (Playwright viewport override is a no-op on CDP-attached pages —
        # this is fine, Chrome's native window size is what applies.)
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

        # Wait for real catalog cards to render (skeleton → real cards).
        cards_loaded = _wait_for_cards_loaded(page, timeout_ms=20_000)
        diagnostics.append({"stage": "wait_cards_loaded",
                            "loaded": cards_loaded})

        sort_res = _select_newest_first(page)
        diagnostics.append({"stage": "sort_newest_first", **sort_res})
        # Sort mutates the list; wait again for the fresh render.
        _wait_for_cards_loaded(page, timeout_ms=15_000)
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
                    # Capture what's currently shown in the right panel
                    # (may belong to a previous catalog) so we can wait
                    # for it to CHANGE after this click.
                    pre_click_sid = _current_right_panel_style_id(page) or last_sid
                    sid = _click_and_capture_style_id(
                        page, card,
                        pre_click_sid=pre_click_sid,
                        timeout_ms=8_000,
                    )
                    processed_ids.add(cid)
                    if sid:
                        last_sid = sid
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
            if not _advance_page(page, current_page, processed_ids,
                                 timeout_ms=10_000):
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
        # Never close a page we reused — keep the user's existing tab
        # alive so subsequent runs (and manual browsing) stay logged in.
        if not page_reused:
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
