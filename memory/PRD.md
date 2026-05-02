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
