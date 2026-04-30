# Meesho Seller Central — Local Worker (Windows Setup)

This folder contains everything that runs on **your Windows laptop** to talk to the dashboard on EC2.

## Files

| File | Purpose |
|---|---|
| `product_review.py` | Playwright scraper for Meesho product reviews + product image/name (v2 — now captures `product_image_large_url`, `product_image_thumb_url`, `product_name`, `product_description`). |
| `labels.py` | Meesho supplier-portal bot: accepts pending orders + downloads RTS labels. |
| `worker.py` | Polls MongoDB `jobs` collection, dispatches `product_scrape` or `label_download` jobs, writes history snapshots. |
| `run_worker.bat` | Windows launcher — starts debug Chrome (port 9222) if not running, then `python worker.py`. |
| `meesho_worker_task.xml` | Task Scheduler template to auto-start the worker on laptop sign-in + daily 11 AM fallback. |

## One-time setup

1. **Copy this folder to** `C:\meesho-worker\` (or edit the paths in `run_worker.bat` + the XML to match your real path).
2. **Install Python deps** (admin PowerShell or cmd):
   ```
   pip install pymongo playwright
   playwright install chromium
   ```
3. **Start Chrome in debug mode once, manually:**
   ```
   "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
     --remote-debugging-port=9222 ^
     --user-data-dir=C:\meesho_profile
   ```
   Log in to `meesho.com` and `supplier.meesho.com` in that window. This profile is reused by both scrapers, so you stay logged in.
4. **Auto-start on boot:**
   - Open Task Scheduler (`taskschd.msc`)
   - Action → **Import Task…**
   - Pick `meesho_worker_task.xml`
   - On the General tab ensure **"Run only when user is logged on"** is selected (the bot needs a visible Chrome window).
   - Save.

Now every time you sign in to Windows, the worker auto-starts. If the laptop is already on at 11:00 AM, the daily trigger fires too.

## Manual run

Just double-click `run_worker.bat`. You should see:

```
🚀 Worker started (EC2 Mongo: mongodb://43.205.229.129:27017/, db=meesho)
   handlers: ['product_scrape', 'label_download']
```

If it hangs on startup: another process may already have Chrome locked on `C:\meesho_profile`. Close all Chrome windows and relaunch.

## How jobs flow

```
[Dashboard on EC2]
   │   user clicks "Submit Job" / "Run Now" / scheduler fires at 11:00 IST
   ▼
[MongoDB `jobs` collection]   ←── same collection your worker polls
   │   status: pending
   ▼
[Worker on your Windows laptop]
   │   status: processing → running handler →
   ▼
   ├── product_scrape  → saves product + history snapshot to `products` / `product_history`
   └── label_download  → runs labels.main() against supplier.meesho.com (PDFs saved to local Downloads)
```

## Overriding Mongo URI / DB name

Set environment variables before launching (or add `set` lines in `run_worker.bat`):

```
set MESHO_MONGO_URI=mongodb://43.205.229.129:27017/
set MESHO_DB_NAME=meesho
set MESHO_POLL_SECONDS=5
```

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `ECONNREFUSED 127.0.0.1:9222` | Chrome isn't running in debug mode. Close all Chrome windows, then run `run_worker.bat` (it will launch a debug Chrome) or launch Chrome manually with `--remote-debugging-port=9222`. |
| Worker picks up label job but nothing happens | Make sure you're logged in to `supplier.meesho.com` in that Chrome profile. |
| Historical trend chart stays empty | History is written *per successful scrape*. Run daily scrapes for a few days. |
| Dashboard shows stuck processing jobs | The laptop went to sleep / worker was killed mid-job. Click "Reset stuck" on the dashboard. |
