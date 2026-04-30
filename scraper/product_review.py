"""
Meesho product review scraper (v2).

Changes vs v1:
  * Also captures product_name, product_description, product_image_thumb_url,
    product_image_large_url from the same `review_summary` API response.
  * Still connects to a pre-existing Chrome over CDP (port 9222).

Returned dict schema:
{
    "product_id": str,
    "product_url": str,
    "seller": {"name": str | None},
    "product_name": str | None,
    "product_description": str | None,
    "product_image_thumb_url": str | None,
    "product_image_large_url": str | None,
    "rating_distribution": {"1": int, ..., "5": int},
    "total_reviews": int,
    "reviews": [ {review_id, text, rating, customer, helpful, media, created_at}, ... ],
}
"""
import time
from playwright.sync_api import sync_playwright

DEBUG_PORT = "http://127.0.0.1:9222"


def extract_rating_and_product_meta_from_json(page):
    """Read window.__NEXT_DATA__ and return (rating_distribution, product_meta)."""
    rating_distribution = {}
    product_meta = {
        "product_name": None,
        "product_description": None,
        "product_image_thumb_url": None,
        "product_image_large_url": None,
    }
    try:
        data = page.evaluate("() => window.__NEXT_DATA__")
    except Exception as e:
        print(f"[meta] __NEXT_DATA__ read failed: {e}")
        return rating_distribution, product_meta

    def find_review(obj):
        if isinstance(obj, dict):
            if "review_summary" in obj:
                return obj
            for v in obj.values():
                f = find_review(v)
                if f:
                    return f
        elif isinstance(obj, list):
            for item in obj:
                f = find_review(item)
                if f:
                    return f
        return None

    try:
        container = find_review(data)
        if container:
            summary = container.get("review_summary", {}).get("data", {}) or {}
            rating_distribution = summary.get("rating_count_map") or {}
            # some product meta may live at the same level or slightly above
            for key in ("product_name", "product_description",
                        "product_image_thumb_url", "product_image_large_url"):
                if summary.get(key):
                    product_meta[key] = summary.get(key)
            # also check parent container
            for key in list(product_meta.keys()):
                if not product_meta[key] and container.get(key):
                    product_meta[key] = container.get(key)
    except Exception as e:
        print(f"[meta] parse error: {e}")

    return rating_distribution, product_meta


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


def _merge_product_meta_from_response(payload, product_meta):
    """Look inside a review_summary/reviews API JSON response for product meta."""
    if not isinstance(payload, dict):
        return
    # direct keys
    for key in ("product_name", "product_description",
                "product_image_thumb_url", "product_image_large_url"):
        if not product_meta.get(key) and payload.get(key):
            product_meta[key] = payload[key]
    # common nesting patterns
    for nest in ("payload", "data"):
        sub = payload.get(nest)
        if isinstance(sub, dict):
            _merge_product_meta_from_response(sub, product_meta)


def scrape_product(product_url: str) -> dict:
    all_reviews = {}
    product_meta_from_api = {
        "product_name": None,
        "product_description": None,
        "product_image_thumb_url": None,
        "product_image_large_url": None,
    }

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(DEBUG_PORT)
        context = browser.contexts[0]

        page = None
        for pg in context.pages:
            if "meesho.com" in pg.url:
                page = pg
                break
        if page is None:
            page = context.new_page()

        page.goto(product_url, wait_until="domcontentloaded")
        time.sleep(5)

        seller_name = extract_seller(page)
        rating_distribution, product_meta_from_next = extract_rating_and_product_meta_from_json(page)

        def handle_response(response):
            try:
                if "review" not in response.url:
                    return
                data = response.json()
                _merge_product_meta_from_response(data, product_meta_from_api)

                reviews = None
                if isinstance(data, dict):
                    reviews = (
                        data.get("payload", {}).get("data", {}).get("reviews")
                        or data.get("data", {}).get("reviews")
                        or data.get("reviews")
                    )

                if not reviews:
                    return

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
                print(f"[reviews] total so far: {len(all_reviews)}")
            except Exception:
                pass

        page.on("response", handle_response)

        # open review panel
        try:
            page.locator("text=/view all reviews/i").first.click(force=True)
        except Exception:
            try:
                page.evaluate(
                    "() => { const el = [...document.querySelectorAll('*')]"
                    ".find(e => /view all reviews/i.test(e.textContent || '')); if (el) el.click(); }"
                )
            except Exception:
                pass
        time.sleep(5)

        # paginate / infinite-scroll
        last_count = 0
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
            if len(all_reviews) == last_count:
                break
            last_count = len(all_reviews)

        page.remove_listener("response", handle_response)

        # prefer API values; fall back to __NEXT_DATA__
        final_meta = {}
        for key in ("product_name", "product_description",
                    "product_image_thumb_url", "product_image_large_url"):
            final_meta[key] = product_meta_from_api.get(key) or product_meta_from_next.get(key)

        product_id = product_url.rstrip("/").split("/p/")[-1].split("?")[0]

        return {
            "product_id": product_id,
            "product_url": product_url,
            "seller": {"name": seller_name},
            **final_meta,
            "rating_distribution": rating_distribution,
            "total_reviews": len(all_reviews),
            "reviews": list(all_reviews.values()),
        }
