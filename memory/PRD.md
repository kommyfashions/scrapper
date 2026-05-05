# Meesho Seller Central — Product Requirements Doc

## Original Problem Statement
User shared two Python files (`product_review.py` Playwright Meesho scraper, `worker.py` MongoDB job worker) and asked to build a **centralized seller-operations dashboard**. Dashboard + MongoDB live on user's EC2 (Ubuntu) at `mongodb://43.205.229.129:27017/` (DB: `meesho`). Worker + scraper run on user's local Windows machine, pickup jobs whenever laptop is on. Future modules: Label Auto-Download (now built — iteration 2), Profit/Loss calculator.

## Architecture
- **Backend**: FastAPI + Motor (async MongoDB), JWT Bearer auth, APScheduler (Asia/Kolkata), single seeded admin.
- **Frontend**: React 19 (CRA + craco), Tailwind, Recharts, Phosphor icons, dark "Control Room" theme (Outfit / IBM Plex Sans / JetBrains Mono).
- **Database**: Remote EC2 MongoDB. Collections: `users`, `jobs`, `products`, `product_history`, `settings`.
- **Local scripts** (`/app/scraper/`): `product_review.py` (v2), `worker.py` (v2), `labels.py`, `run_worker.bat`, `meesho_worker_task.xml`, `README.md`.

## User Persona
Single admin (Meesho seller) managing their own products + daily label printing.

## Core Requirements
- JWT login (single admin), ProtectedRoutes.
- Submit Meesho product URLs → `pending` jobs.
- Job lifecycle UI (pending/processing/done/failed) + retry/delete/reset-stuck.
- Browse products with search + sort + **tracking toggle** + thumbnail.
- Product detail with hero image, clickable live link, seller, reviews + media, **trend chart** (7/30/90 days), rating distribution.
- Analytics dashboard (KPIs, top sellers, helpful reviews, review volume).
- **Label Download module** — one-click `label_download` job; run history.
- **Settings page** — editable daily schedule times (Asia/Kolkata), manual "Run now" triggers.
- Extensible sidebar (AUTOMATION section) for future modules.

## Implemented — Iteration 6 (2026-05-05) — Robust payments-fetcher + Jobs UI
**Worker (`scraper-ec2/payments_fetcher.py`) hardened**
- Switched from folder-polling to Playwright `page.expect_download()`. We now capture the *exact* `suggested_filename` Meesho proposes, eliminating cross-account file mix-ups when multiple jobs run close together.
- Per-account, per-period download folder: `<DOWNLOAD_DIR>/<safe_account>/<period>/`.
- Click-flow retried up to **3×** with `page.reload()` between attempts when no download event fires within 30 s. Failures take a debug screenshot.
- Both `.zip` and bare `.xlsx` downloads supported.
- Source filename is forwarded to `/api/pl/upload?source_filename=…` for traceability.

**Backend (`server.py`)**
- `/api/pl/upload` accepts new `source_filename` query param; persisted on `pl_uploads.source_filename` and on the job's `result.source_filename`.
- After a worker upload, the related `accounts` document gets stamped with `last_payment_filename` + `last_payment_at` for the dashboard.

**Frontend**
- `JobsPage.js` — added `PAYMENT` type filter and badge, with inline display of the captured filename, period, account, and inserted/updated/ads counts per job.
- `pl/PLUploads.js` — shows "Last fetched: <filename> · <when>" line below the Auto-fetch panel for the picked account.

## Implemented — Iteration 5 (2026-05-04) — SKU-cost dedupe + Auto-fetch payments
**SKU cost fix (Option B)**
- New helper `_pl_norm_acc()` normalises `""`/`"all"`/`"global"`/`"none"` → `None` on every cost write (POST + Excel upload + DELETE).
- New helper `_pl_lookup_cost()` makes priority explicit: account-specific cost first, global fallback second.
- `_pl_load_costs()` now sorts by `updated_at ASC` so the most-recent global wins deterministically.
- Startup migration `_pl_dedupe_sku_costs()` consolidates legacy duplicate `(account_id, sku)` rows.
- `GET /api/pl/sku-costs` joins `accounts` to return `account_name` so UI no longer shows ambiguous "—".
- Frontend `PLSKUCosts.js` renders `account_name` (or "Global") instead of "—".
- Applied user's IST datetime serialisation tweak (`.replace("+00:00", "Z")` with `tzinfo` fallback).

**Auto-fetch payments worker (P1 from previous fork)**
- New `payments_fetch` job type alongside `scrape` and `label_download`.
- Backend: `POST /api/pl/fetch-now` for manual trigger; `enqueue_payments_fetch_jobs(period)` for cron.
- Two cron entries (timezone Asia/Kolkata):
   - **Every Monday 09:00 IST** → period `previous_week`
   - **Every 5th of month 09:00 IST** → period `previous_month`
- New shared-secret auth: `WORKER_API_KEY` (in `backend/.env`); `get_user_or_worker` allows the EC2 worker to POST `/api/pl/upload` via `X-Worker-Key` header without owning a JWT.
- `/api/pl/upload` now accepts optional `job_id` query param and marks the job `done` with `result.{inserted, updated, skipped, ads_rows, filename, upload_id}`.
- `scraper-ec2/payments_fetcher.py` (NEW) — Playwright + CDP-attach driver: navigates to `https://supplier.meesho.com/panel/v3/new/payouts/{name}/payments`, clicks `Download → Payments to Date → <radio> → Download`, waits for .zip, extracts xlsx, POSTs to dashboard `/api/pl/upload`, cleans up.
- `scraper-ec2/label_worker.py` is now a single dispatcher handling both `label_download` and `payments_fetch` types (`JOB_TYPES = ["label_download", "payments_fetch"]`).
- `scraper-ec2/install.sh` adds `requests` dep + copies `payments_fetcher.py` + creates `/home/ubuntu/meesho-downloads/`.
- `meesho-label-worker.service` adds env vars `DASHBOARD_URL`, `WORKER_API_KEY`, `MESHO_DOWNLOAD_DIR`.
- Frontend `PLUploads.js` adds period dropdown (Previous Week / Previous Month / Last Payment) + "Fetch latest now" button → calls `/api/pl/fetch-now` → user watches Jobs page for completion.
- `README.md` rewritten: explains both cron schedules, worker env vars, and per-account flow.

## Implemented — Iteration 4 (2026-05-04) — Profit & Loss module
**Backend additions** (in `server.py` under `/api/pl/*`)
- New collections: `pl_orders` (compound unique key `{account_id, sub_order_no}`), `pl_sku_costs`, `pl_uploads`, `pl_ads_cost`.
- `POST /api/pl/upload?account_id=…` — parses Meesho monthly xlsx (sheets `Order Payments` + `Ads Cost`); dedupes by Sub Order No; idempotent bulk upserts; tracks `upload_ids[]` per order so uploads can be rolled back.
- `GET /api/pl/uploads`, `DELETE /api/pl/uploads/{id}` — upload audit trail with safe rollback (deletes only orders not also covered by other uploads).
- `GET /api/pl/dashboard` — KPIs: net realized profit, return loss (`|settlement|+return_charges−compensation`), net contribution, profit/order, total ads cost, net after ads, exposure, pending settlement. Filters by `account_id` and `start_date/end_date`.
- `GET /api/pl/orders` (paginated, search, status filter), `GET /api/pl/orders/export` (xlsx).
- `GET /api/pl/sku-analysis` — per-SKU rollup with Winner/Risky/Loser classification.
- `GET /api/pl/exchange-analysis`, `GET /api/pl/ad-orders-analysis` — separate cohorts.
- `GET/POST/DELETE /api/pl/sku-costs`, `POST /api/pl/sku-costs/upload-excel`, `GET /api/pl/missing-sku-costs` — per-account or "global" cost prices (account_id null = fallback).

**Frontend additions** (`/app/frontend/src/pages/pl/`)
- `PLLayout.js` — shared shell: account selector (persisted), sub-nav, date-range filter, `usePL()` context.
- `PLDashboard.js` — 8 KPI cards + status summary + quick links.
- `PLOrders.js` — paginated ledger with status/search filters + xlsx export.
- `PLSKUAnalysis.js` — Winner/Risky/Loser table with sortable metrics.
- `PLSKUCosts.js` — inline-edit cost prices, bulk Excel import, missing-SKU chips.
- `PLExchangeAnalysis.js` — separate exchange cohort metrics.
- `PLAdOrdersAnalysis.js` — Ad vs Normal side-by-side table.
- `PLUploads.js` — drag-and-drop upload + history + rollback.
- Sidebar: new "PROFIT & LOSS" section (5 sub-links). "Future Modules" replaced with Auto Payment Scraper, Inventory Loss.
- Routing: `/pl/*` nested under `PLLayout`, default redirects to `/pl/dashboard`.

**Multi-account**: every endpoint accepts `account_id` query (omit / "all" = consolidated). Compound unique key prevents cross-account collisions.

**Verified end-to-end** with a real Meesho payment file (1543 rows / 1515 unique orders inserted in ~5s using bulk_write):
- Dashboard: ₹1,06,083 net contribution, ₹1,92,547 profit, ₹86,464 return loss, ₹6,993 ads cost.
- SKU Analysis: 94 SKUs classified.
- Exchange: 37 orders, P&L −₹671.
- Ad vs Normal: 17.55% ad share, ad RR 23.17% vs normal 31.55% (Δ −8.38pp).

## Implemented — Iteration 2 (2026-04-30)
**Backend additions**
- APScheduler on startup; configurable via `/api/settings` PUT (reconfigures live).
- New endpoints: `POST /api/products/{pid}/track`, `GET /api/products/{pid}/history?days=N`, `POST /api/labels/run-now`, `GET /api/labels/runs`, `GET /PUT /api/settings`, `POST /api/scheduler/run-now?what=scrape|label`.
- `jobs.type` field (`product_scrape` default, `label_download`). Legacy jobs auto-stamped.
- `products.tracked` field (auto-true for existing) + tracked filter on list endpoint.
- `product_history` collection (1 snapshot per successful scrape — written by updated worker).
- `image` derivation (falls back to first review-media URL when scraper-captured product image isn't present yet).

**Frontend additions**
- Sidebar: new AUTOMATION section (Label Download, Settings); FUTURE MODULES only Profit/Loss.
- Products list: thumbnail column, Track ON/OFF toggle button, tracked/untracked filter.
- Product detail: hero image (clickable to Meesho), product name/description in header, **Trend chart** with 7/30/90-day range buttons + delta metrics, "Track" toggle button in header.
- New Labels page: Run Now button + run history with auto-refresh while pending.
- New Settings page: two schedule sections with enable toggle, time picker, next-run display, and "Run now" manual triggers.
- Jobs page: job-type filter pills (ALL TYPES / SCRAPE / LABEL), LABEL badge on label rows.

## Implemented — Iteration 3 (2026-05-01)
**Backend additions**
- New endpoints: `GET/POST/PUT/DELETE /api/accounts`, `GET /api/accounts/defaults` (suggests next free port + profile_dir), `GET/POST/DELETE /api/alerts`, `POST /api/alerts/{id}/read`, `POST /api/alerts/read-all`, `POST /api/alerts/check-now`, `POST /api/scheduler/run-now?what=snapshot`.
- `LabelRunIn` body now `Optional` with `all_accounts` flag — `POST /api/labels/run-now` fans out to every enabled account when called with `{}` or `{all_accounts: true}`, returning `{ok, queued, skipped}`; single-account path still returns the job doc.
- `ScheduleSettings` persists `skip_dates` (YYYY-MM-DD list) and `skip_weekdays` (int 0-6 list); `enqueue_daily_label_job` is no-op when today matches.
- New scheduler jobs: `daily_snapshot` (5 min after `daily_scrape`, into `product_history`) and `alerts_check` (every 30 min).
- `detect_alerts()` compares current state vs ~24h-old snapshot — raises `one_star_spike` (≥3 new 1★ in 24h) or `rating_drop` (avg ↓ ≥0.20). Deduped per-day per-product via unique sparse index on `alerts.dedup_key`.

**Frontend additions**
- Sidebar AUTOMATION: new **Accounts** entry above Label Download.
- New `/accounts` page: full CRUD UI with Add Account modal (auto-fills defaults from backend), enabled toggle, edit, delete-with-confirm.
- Labels page rewrite: account selector dropdown, Account column in Run History.
- Settings page: new **Label Skip Rules** panel (MON-SUN chips + date picker) + "Snapshot now" trigger.
- Global **Alerts Bell**: fixed top-right with unread badge + drawer (Check Now / Mark All Read / Open Product / Mark Read / Delete); polls every 60s.

**Verified — Iteration 3**
- 19/20 new backend tests pass.
- UI smoke screenshots (Accounts, Labels, Settings, Alerts drawer) — all rendering as designed.

## Implemented — Iteration 4 (2026-05-02)
**Label worker fixes** (`/app/scraper-ec2/label_worker.py`, `install.sh`)
- Per-account Meesho URL derivation now uses **account `name` as the URL suffix** (e.g. `hrbib`, `uobfs`) and **always wins over stored `pending_url`/`ready_url`**. Stored URLs are a fallback escape-hatch when no name is set. Fixes the bug where multi-account runs kept navigating to one account's fulfillment page inside another account's Chrome (bouncing back to /growth/{x}/home).
- `install.sh` `pip3 install` now uses `--break-system-packages` for Ubuntu 24+ compatibility and the seed-example doc no longer hardcodes pending_url/ready_url.

**Product Detail — Compare section** (`/app/frontend/src/pages/ProductDetailPage.js`)
- Inside the Trend panel, above the timeline chart, new "/ compare" block:
  - Two dropdowns (Date A → Date B) populated from this product's `product_history` snapshots within the active 7D/30D/90D window.
  - Defaults to oldest ↔ latest; presets "oldest ↔ latest" and "last vs prev".
  - Comparison table: Total reviews, Avg rating, and each star bucket (5★…1★), with Δ column. Δ is green when direction is favourable (more reviews / higher rating / fewer 1★-2★ / more 4★-5★), red otherwise, "—" when unchanged.

**Scraper + Worker (local files — `/app/scraper/`)**
- `product_review.py` v2: now also captures `product_name`, `product_description`, `product_image_thumb_url`, `product_image_large_url` from the same `review_summary` API response.
- `worker.py` v2: dispatch by job `type` (`product_scrape` | `label_download`), writes a `product_history` snapshot on each successful scrape, cleaner error reporting, reads MongoDB URI from env.
- `labels.py`: unchanged (copy of user's file) — imported by worker for label jobs.
- `run_worker.bat`: auto-launches debug Chrome on port 9222 if not running, then starts `python worker.py`.
- `meesho_worker_task.xml`: Task Scheduler template → auto-run on Windows sign-in + daily 11:00 local fallback.
- `README.md`: step-by-step Windows setup guide.

**Verified**
- Iteration 1 regression: 23/23 ✅
- Iteration 2: 18/19 (remaining 1 was the list-image bug — now fixed)
- Sidebar bug (FUTURE MODULES still showing Label Auto-Download) — fixed
- Product detail hero image — confirmed already correct (`product.image`)

## Default Credentials
Admin: `admin@meesho-dash.local` / `admin123` (from backend `.env`; auto-seeded).

## Backlog
**P1** — Worker heartbeat/online indicator, pagination, side-by-side product comparison, label-download PDF file list (requires worker reporting back filenames).

**P2** — Profit/Loss module, LLM review summaries (skipped per user), brute-force lockout on login.

**P3** — Multi-user, audit log, CSV export.

## Key Files
| Path | Purpose |
|---|---|
| `/app/backend/server.py` | FastAPI app + APScheduler |
| `/app/backend/.env` | MONGO_URL, JWT_SECRET, ADMIN_*, STUCK_JOB_MINUTES |
| `/app/frontend/src/App.js` | Router |
| `/app/frontend/src/pages/*` | Page components |
| `/app/scraper/*` | **Files to copy to the Windows laptop** |
| `/app/memory/PRD.md` | This doc |
| `/app/memory/test_credentials.md` | Login info |
