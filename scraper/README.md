# Meesho Seller Central — Windows Product Scraper

Runs on **your Windows laptop**. Handles only `product_scrape` jobs (label downloads run on EC2).

## Files

| File | Purpose |
|---|---|
| `product_review.py` | v2.1 scraper — captures product image, name, description, reviews. |
| `worker.py` | Polls MongoDB for `product_scrape` jobs only. |
| `run_worker.bat` | Launches debug Chrome on 9222 if not running, then starts worker. |
| `meesho_worker_task.xml` | Task Scheduler template for auto-start on Windows sign-in. |

## One-time setup

1. **Copy this folder to** `C:\meesho-worker\`.
2. **Install Python deps** (admin cmd):
   ```
   pip install pymongo playwright
   playwright install chromium
   ```
3. **Start Chrome once manually and log in to meesho.com**:
   ```
   "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
       --remote-debugging-port=9222 ^
       --user-data-dir=C:\meesho_profile
   ```
4. **Auto-start on boot:** Task Scheduler → Import Task → `meesho_worker_task.xml`. On the General tab keep "Run only when user is logged on".

## Manual run

Double-click `run_worker.bat`. Expected output:
```
🚀 Product worker (Windows) — Mongo: mongodb://43.205.229.129:27017/ db=meesho
```

## Job lifecycle

```
[Dashboard] Submit Job
   → [MongoDB jobs collection]  type=product_scrape, status=pending
   → [Windows worker]            picks up, runs scraper
   → [products collection]       upsert product (now WITH product_image_large_url)
   → [product_history]           snapshot for trend chart
```
