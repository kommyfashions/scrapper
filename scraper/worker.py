"""
Meesho product worker — Windows.

Polls the EC2 MongoDB `jobs` collection for jobs of type "product_scrape",
runs the v2.1 scraper for each, writes a snapshot to `product_history`.

This worker only handles product scrapes. Label downloads run on a
separate worker on the EC2 Ubuntu machine.

Env overrides:
  MESHO_MONGO_URI   default: mongodb://43.205.229.129:27017/
  MESHO_DB_NAME     default: meesho
  MESHO_POLL_SECONDS default: 5
"""
import os
import time
import traceback
from datetime import datetime, timezone

from pymongo import MongoClient

from product_review import scrape_product

MONGO_URI = os.environ.get("MESHO_MONGO_URI", "mongodb://43.205.229.129:27017/")
DB_NAME = os.environ.get("MESHO_DB_NAME", "meesho")
POLL = int(os.environ.get("MESHO_POLL_SECONDS", "5"))

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
products = db["products"]
jobs = db["jobs"]
product_history = db["product_history"]


def _avg_rating(distribution):
    if not isinstance(distribution, dict):
        return None
    total, weighted = 0, 0
    for k, v in distribution.items():
        try:
            total += int(v)
            weighted += int(k) * int(v)
        except Exception:
            continue
    return round(weighted / total, 2) if total else None


def handle_product_scrape(job):
    url = job.get("product_url")
    if not url:
        raise ValueError("job has no product_url")

    print(f"[product_scrape] {url}")
    result = scrape_product(url)

    reviews_sorted = sorted(
        result.get("reviews", []),
        key=lambda r: r.get("created_at") or "",
        reverse=True,
    )

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
        {"$set": doc, "$setOnInsert": {"tracked": True}},
        upsert=True,
    )

    product_history.insert_one({
        "product_id": result["product_id"],
        "snapshot_at": now,
        "total_reviews": doc["total_reviews"],
        "avg_rating": _avg_rating(doc["rating_distribution"]),
        "rating_distribution": doc["rating_distribution"],
    })

    print(f"[product_scrape] saved {doc['total_reviews']} reviews | "
          f"image={'Y' if doc['product_image_large_url'] else 'N'}")


def loop():
    print(f"🚀 Product worker (Windows) — Mongo: {MONGO_URI} db={DB_NAME}")
    while True:
        # claim only product_scrape jobs (label jobs are handled by EC2 worker)
        job = jobs.find_one_and_update(
            {"status": "pending", "$or": [{"type": "product_scrape"}, {"type": {"$exists": False}}]},
            {"$set": {"status": "processing", "started_at": datetime.now(timezone.utc)}},
            sort=[("created_at", 1)],
        )
        if not job:
            time.sleep(POLL)
            continue

        print(f"\n=== job {job.get('_id')} ===")
        try:
            handle_product_scrape(job)
            jobs.update_one(
                {"_id": job["_id"]},
                {"$set": {"status": "done", "finished_at": datetime.now(timezone.utc)}},
            )
            print("✅ done")
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            print(f"❌ {err}")
            traceback.print_exc()
            jobs.update_one(
                {"_id": job["_id"]},
                {"$set": {
                    "status": "failed",
                    "finished_at": datetime.now(timezone.utc),
                    "error": err[:1000],
                }},
            )


if __name__ == "__main__":
    loop()
