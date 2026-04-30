"""
Meesho Seller Central — local worker (v2).

What's new vs v1:
  * Handles two job types:
      - type == "product_scrape"  -> runs product_review.scrape_product(url)
      - type == "label_download"  -> runs labels.main()  (Meesho supplier portal bot)
    Older jobs without a "type" field are treated as "product_scrape" for
    backwards compatibility.
  * On a successful product scrape, writes a snapshot to `product_history`
    so the dashboard can draw trend charts.
  * Reads MongoDB connection from environment variable MESHO_MONGO_URI if set,
    otherwise defaults to the value you used before.
  * Cleaner error reporting — full exception text is stored on the job.

Prerequisites on the local machine:
  * Chrome running with remote-debugging-port=9222 (the CDP port used by both
    scripts). Recommended: shortcut
      "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222 --user-data-dir=C:\\meesho_profile
  * Python deps: pip install pymongo playwright && playwright install chromium
  * For `label_download` jobs, be already signed in to supplier.meesho.com in that Chrome session.

Run:
  python worker.py
"""
import os
import time
import traceback
from datetime import datetime, timezone

from pymongo import MongoClient

# Local modules (must be in the same folder as this file)
from product_review import scrape_product
import labels

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MONGO_URI = os.environ.get("MESHO_MONGO_URI", "mongodb://43.205.229.129:27017/")
DB_NAME = os.environ.get("MESHO_DB_NAME", "meesho")
POLL_SLEEP_SECONDS = int(os.environ.get("MESHO_POLL_SECONDS", "5"))

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
products = db["products"]
jobs = db["jobs"]
product_history = db["product_history"]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def _avg_rating(distribution):
    if not isinstance(distribution, dict):
        return None
    total, weighted = 0, 0
    for k, v in distribution.items():
        try:
            star = int(k)
            count = int(v)
        except Exception:
            continue
        total += count
        weighted += star * count
    if total == 0:
        return None
    return round(weighted / total, 2)


def handle_product_scrape(job):
    url = job.get("product_url")
    if not url:
        raise ValueError("job has no product_url")

    print(f"[product_scrape] {url}")
    result = scrape_product(url)

    # sort reviews newest-first
    def _created(r):
        return r.get("created_at") or ""
    reviews_sorted = sorted(result.get("reviews", []), key=_created, reverse=True)

    now = datetime.now(timezone.utc)
    doc = {
        "product_id": result["product_id"],
        "product_url": result["product_url"],
        "seller": result.get("seller"),
        "product_name": result.get("product_name"),
        "product_description": result.get("product_description"),
        "product_image_thumb_url": result.get("product_image_thumb_url"),
        "product_image_large_url": result.get("product_image_large_url"),
        "rating_distribution": result.get("rating_distribution") or {},
        "total_reviews": len(reviews_sorted),
        "reviews": reviews_sorted,
        "updated_at": now,
    }
    products.update_one(
        {"product_id": result["product_id"]},
        {
            "$set": doc,
            # auto-track any product we scrape, but don't override an explicit False
            "$setOnInsert": {"tracked": True},
        },
        upsert=True,
    )

    # history snapshot (always insert; one per scrape)
    product_history.insert_one({
        "product_id": result["product_id"],
        "snapshot_at": now,
        "total_reviews": doc["total_reviews"],
        "avg_rating": _avg_rating(doc["rating_distribution"]),
        "rating_distribution": doc["rating_distribution"],
    })

    print(f"[product_scrape] saved {doc['total_reviews']} reviews for {result['product_id']}")


def handle_label_download(job):
    print("[label_download] running labels.main()")
    labels.main()
    print("[label_download] finished")


HANDLERS = {
    "product_scrape": handle_product_scrape,
    "label_download": handle_label_download,
}


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------
def worker_loop():
    print(f"🚀 Worker started (EC2 Mongo: {MONGO_URI}, db={DB_NAME})")
    print(f"   handlers: {list(HANDLERS.keys())}")
    while True:
        job = jobs.find_one_and_update(
            {"status": "pending"},
            {"$set": {"status": "processing", "started_at": datetime.now(timezone.utc)}},
            sort=[("created_at", 1)],
        )
        if not job:
            time.sleep(POLL_SLEEP_SECONDS)
            continue

        job_type = job.get("type") or "product_scrape"  # legacy default
        print(f"\n=== Picked job {job.get('_id')} type={job_type} ===")

        handler = HANDLERS.get(job_type)
        if handler is None:
            msg = f"Unknown job type: {job_type}"
            print(f"❌ {msg}")
            jobs.update_one(
                {"_id": job["_id"]},
                {"$set": {"status": "failed", "finished_at": datetime.now(timezone.utc), "error": msg}},
            )
            continue

        try:
            handler(job)
            jobs.update_one(
                {"_id": job["_id"]},
                {"$set": {"status": "done", "finished_at": datetime.now(timezone.utc)}},
            )
            print("✅ Done")
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            print(f"❌ Failed: {err}")
            traceback.print_exc()
            jobs.update_one(
                {"_id": job["_id"]},
                {
                    "$set": {
                        "status": "failed",
                        "finished_at": datetime.now(timezone.utc),
                        "error": err[:1000],
                    }
                },
            )


if __name__ == "__main__":
    worker_loop()
