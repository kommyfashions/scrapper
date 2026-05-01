"""
Meesho product review scraper — v2.1

Runs on user's Windows laptop. Connects to a pre-existing Chrome over CDP (port 9222)
and scrapes the Meesho product page. Captures reviews + product metadata
(name, description, large image, thumbnail) from the same `review_summary`
API response that already powers the rating distribution.
"""
import time
from playwright.sync_api import sync_playwright

DEBUG_PORT = "http://127.0.0.1:9222"

META_KEYS = (
    "product_name",
    "product_description",
    "product_image_thumb_url",
    "product_image_large_url",
)


def _find_review_block(payload):
    """Locate the dict in the API response that contains the `reviews` array.
    Product metadata fields (image, name, description) sit at the same level."""
    if isinstance(payload, dict):
        if isinstance(payload.get("reviews"), list):
            return payload
        for v in payload.values():
            found = _find_review_block(v)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_review_block(item)
            if found is not None:
                return found
    return None


def _capture_meta_from_block(block, meta):
    """Copy product_name / image fields from the review block into `meta`."""
    if not isinstance(block, dict):
        return
    for k in META_KEYS:
        if not meta.get(k) and block.get(k):
            meta[k] = block[k]


def _extract_rating_from_next_data(page):
    """Pull rating_count_map from window.__NEXT_DATA__ as a fallback."""
    try:
        data = page.evaluate("() => window.__NEXT_DATA__")
    except Exception:
        return {}

    def walk(obj):
        if isinstance(obj, dict):
            if "review_summary" in obj:
                return obj.get("review_summary", {}).get("data", {}) or {}
            for v in obj.values():
                f = walk(v)
                if f:
                    return f
        elif isinstance(obj, list):
            for it in obj:
                f = walk(it)
                if f:
                    return f
        return None

    summary = walk(data) or {}
    return summary.get("rating_count_map") or {}


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


def scrape_product(product_url: str) -> dict:
    all_reviews = {}
    meta = {k: None for k in META_KEYS}
    rating_distribution = {}

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(DEBUG_PORT)
        context = browser.contexts[0]

        page = next((pg for pg in context.pages if "meesho.com" in pg.url), None)
        if page is None:
            page = context.new_page()

        page.goto(product_url, wait_until="domcontentloaded")
        time.sleep(5)

        seller_name = extract_seller(page)
        # 1) initial rating distribution from __NEXT_DATA__
        rating_distribution = _extract_rating_from_next_data(page) or {}

        def handle_response(response):
            try:
                if "review" not in response.url:
                    return
                data = response.json()
            except Exception:
                return

            block = _find_review_block(data)
            if block is None:
                return

            # capture product meta (anchored to where reviews live)
            _capture_meta_from_block(block, meta)

            # update rating_distribution if API returns it
            rcm = block.get("rating_count_map") or block.get("rating_distribution")
            if isinstance(rcm, dict):
                # only overwrite if non-empty
                if any(rcm.values()):
                    rating_distribution.clear()
                    rating_distribution.update(rcm)

            # collect reviews
            for r in block.get("reviews") or []:
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
            print(f"[reviews] total so far: {len(all_reviews)} | meta: "
                  f"name={'Y' if meta.get('product_name') else 'N'} "
                  f"img={'Y' if meta.get('product_image_large_url') else 'N'}")

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

        page.remove_listener("response", handle_response)

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
    import sys, json
    if len(sys.argv) < 2:
        print("Usage: python product_review.py <product_url>")
        sys.exit(1)
    out = scrape_product(sys.argv[1])
    out["reviews"] = f"[{len(out['reviews'])} reviews]"
    print(json.dumps(out, indent=2, default=str))
