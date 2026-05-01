"""
Meesho product review scraper — v2.2

Fixes vs v2.1:
  * Product meta (product_name, product_image_*) is now captured via a
    FULL recursive scan of every review/review_summary response — not just
    the block that holds the `reviews` array.  This handles any nesting
    shape Meesho uses.
  * Handler callbacks are hardened against late responses that fire while
    the browser is closing (swallows CancelledError / TargetClosedError).
  * Optional --debug flag dumps the first matching response to
    debug_response.json so you can inspect the exact structure.
"""
import time
import json
import os
import sys
from playwright.sync_api import sync_playwright

DEBUG_PORT = "http://127.0.0.1:9222"

META_KEYS = (
    "product_name",
    "product_description",
    "product_image_thumb_url",
    "product_image_large_url",
)


def _scan_meta_anywhere(obj, meta):
    """Walk the full tree and copy any META_KEYS found at ANY depth."""
    if isinstance(obj, dict):
        for k in META_KEYS:
            if not meta.get(k):
                v = obj.get(k)
                if isinstance(v, str) and v:
                    meta[k] = v
        for v in obj.values():
            _scan_meta_anywhere(v, meta)
    elif isinstance(obj, list):
        for it in obj:
            _scan_meta_anywhere(it, meta)


def _find_reviews_list(obj):
    """Return the first non-empty list of review dicts found in `obj`."""
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and (
            "review_id" in obj[0] or "rating" in obj[0] or "comments" in obj[0]
        ):
            return obj
        for it in obj:
            found = _find_reviews_list(it)
            if found:
                return found
    elif isinstance(obj, dict):
        # fast path: explicit "reviews" key
        r = obj.get("reviews")
        if isinstance(r, list) and r and isinstance(r[0], dict):
            return r
        for v in obj.values():
            found = _find_reviews_list(v)
            if found:
                return found
    return None


def _find_rating_distribution(obj):
    """Pull `rating_count_map` or `rating_distribution` from anywhere in the tree."""
    if isinstance(obj, dict):
        for key in ("rating_count_map", "rating_distribution"):
            v = obj.get(key)
            if isinstance(v, dict) and any(v.values()):
                return v
        for v in obj.values():
            found = _find_rating_distribution(v)
            if found:
                return found
    elif isinstance(obj, list):
        for it in obj:
            found = _find_rating_distribution(it)
            if found:
                return found
    return None


def _extract_rating_from_next_data(page):
    try:
        data = page.evaluate("() => window.__NEXT_DATA__")
    except Exception:
        return {}
    return _find_rating_distribution(data) or {}


def extract_seller(page):
    try:
        return (
            page.locator("text=Sold By")
            .locator("..")
            .locator("text=/./")
            .nth(1)
            .inner_text()
            .strip()
        )
    except Exception:
        return None


def scrape_product(product_url: str, debug: bool = False) -> dict:
    all_reviews = {}
    meta = {k: None for k in META_KEYS}
    rating_distribution = {}
    debug_dumped = [False]  # mutable so nested fn can flip it

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(DEBUG_PORT)
        context = browser.contexts[0]

        page = next((pg for pg in context.pages if "meesho.com" in pg.url), None)
        if page is None:
            page = context.new_page()

        page.goto(product_url, wait_until="domcontentloaded")
        time.sleep(5)

        seller_name = extract_seller(page)
        d0 = _extract_rating_from_next_data(page)
        if d0:
            rating_distribution.update(d0)

        def handle_response(response):
            try:
                url = response.url
            except Exception:
                return
            if "review" not in url:
                return
            try:
                data = response.json()
            except Exception:
                # Browser closing / request aborted / non-JSON — ignore.
                return

            if debug and not debug_dumped[0]:
                try:
                    with open("debug_response.json", "w", encoding="utf-8") as fh:
                        json.dump({"url": url, "data": data}, fh, indent=2, default=str)
                    print(f"[debug] dumped first review response to debug_response.json ({url})")
                    debug_dumped[0] = True
                except Exception:
                    pass

            # --- product meta (full-tree scan) ---
            _scan_meta_anywhere(data, meta)

            # --- rating distribution ---
            rd = _find_rating_distribution(data)
            if rd:
                rating_distribution.clear()
                rating_distribution.update(rd)

            # --- reviews ---
            reviews = _find_reviews_list(data)
            if reviews:
                for r in reviews:
                    rid = r.get("review_id")
                    if rid is None:
                        continue
                    all_reviews[rid] = {
                        "review_id": rid,
                        "text": r.get("comments"),
                        "rating": r.get("rating"),
                        "customer": (r.get("author") or {}).get("name"),
                        "helpful": r.get("helpful_count", 0),
                        "media": r.get("media", []),
                        "created_at": r.get("created"),
                    }
                print(
                    f"[reviews] total: {len(all_reviews):>3} | "
                    f"name={'Y' if meta.get('product_name') else 'N'} "
                    f"img={'Y' if meta.get('product_image_large_url') else 'N'} "
                    f"thumb={'Y' if meta.get('product_image_thumb_url') else 'N'}"
                )

        page.on("response", handle_response)

        # Open the review panel
        try:
            page.locator("text=/view all reviews/i").first.click(force=True)
        except Exception:
            try:
                page.evaluate(
                    "() => { const el = [...document.querySelectorAll('*')]"
                    ".find(e => /view all reviews/i.test(e.textContent || ''));"
                    " if (el) el.click(); }"
                )
            except Exception:
                pass
        time.sleep(5)

        # Paginate / infinite-scroll
        last = 0
        for _ in range(50):
            page.mouse.wheel(0, 3000)
            time.sleep(2)
            try:
                btn = page.locator("text=/view more/i").last
                if btn.count() == 0:
                    break
                btn.click(force=True)
                time.sleep(2)
            except Exception:
                break
            if len(all_reviews) == last:
                break
            last = len(all_reviews)

        # drain: give in-flight responses a moment to arrive
        time.sleep(2)
        try:
            page.remove_listener("response", handle_response)
        except Exception:
            pass

        product_id = product_url.rstrip("/").split("/p/")[-1].split("?")[0]

        return {
            "product_id": product_id,
            "product_url": product_url,
            "seller": {"name": seller_name},
            "product_name": meta["product_name"],
            "product_description": meta["product_description"],
            "product_image_thumb_url": meta["product_image_thumb_url"],
            "product_image_large_url": meta["product_image_large_url"],
            "rating_distribution": rating_distribution,
            "total_reviews": len(all_reviews),
            "reviews": list(all_reviews.values()),
        }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python product_review.py <product_url> [--debug]")
        sys.exit(1)
    url = sys.argv[1]
    debug = "--debug" in sys.argv[2:]
    out = scrape_product(url, debug=debug)
    preview = dict(out)
    preview["reviews"] = f"[{len(out['reviews'])} reviews]"
    print(json.dumps(preview, indent=2, default=str))
