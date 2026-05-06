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

## Implemented — Iteration 12 (2026-05-06) — SKU Analysis hierarchical view + search + clash-safe articles
**Root cause acknowledged**: previous SKU Analysis aggregated by `sku` only (lost per-account view) and "By Article" produced a single roll-up row (lost per-SKU drilldown). User couldn't tell which SKU on which account was performing.

**Backend `/pl/sku-analysis` rewritten**
- Aggregation now at `(account_id, sku)` granularity — same SKU on different accounts gets distinct rows.
- Each row carries `account_id`, `account_name`, `account_alias`, `article_name`.
- `group_by=article` returns **interleaved** `[header_row, child_row, child_row, ...]` so frontend can render hierarchy: header rows have `is_header=True`, `sku_count`, aggregated metrics; children have `is_child=True`, `parent_article`.
- `q` query param: server-side text search across SKU, article name, account name, account alias, product name (case-insensitive contains).
- Articles sorted by metric (mapped first, "Unmapped" bucket always last).

**Backend bug fix** — `_validate_sku_map()` now runs *before* `db.articles.insert_one()` on POST, so a SKU clash returns 409 cleanly without leaving an orphan article.

**Frontend `PLSKUAnalysis.js` rewritten**
- New columns: Article | Account | SKU | Product | Ordered | Delivered | Returned | RR% | Ship Out | Ship Return | Profit | Loss | Net | P/U | Class.
- Debounced search box (350ms) wired to the new `q` param.
- Group-by-article view: header rows are bold + caret + `N skus` chip; **click toggles collapse** of children. Children are visually indented with `↳`.
- Summary cards relabel to "Winner / Risky / Loser Articles" in by-article view.

## Implemented — Iteration 11 (2026-05-06) — Multi-SKU per article + Article-grouped SKU Analysis + Multi-time label cron + Shipping cols
**Multi-SKU chip input on Articles form**
- Each per-account input is now a chip-list. Type → Enter or `,` → adds chip; × removes; Backspace deletes last chip when input empty. Articles table cell renders all SKUs as chips (handles cases like Sofia-Blue → `WSS-SFA-Blue`, `WSS-Sofiya(Blue)` on the same account).
- Save commits any uncommitted draft text. Existing comma-blob entries auto-split on edit.

**Shipping charge columns persisted (no calc impact)**
- `pl_upload` now writes `shipping_charge` and `return_shipping_charge` raw fields on every `pl_orders` row (sourced from columns AD + AB of Meesho payment XLSX). Existing P&L Profit/Loss/Net calculations untouched.

**SKU Analysis page redesign**
- Top-right toggle **By SKU / By Article** (`?group_by=sku|article` on backend).
- New `Article` column on both views; `Ship Out` (sum of `shipping_charge` for delivered) and `Ship Return` (sum of `return_shipping_charge` for returns) columns.
- By-Article view rolls up all SKUs per article; everything without a mapping collapses into one **"Unmapped — please define an article"** bucket row with `sku_count` and tooltip listing the SKUs.
- Backend gated with `Query("sku", regex="^(sku|article)$")`.

**Label download — multiple schedule times**
- `ScheduleSettings.label_times: List[str]` (legacy `label_time` kept for back-compat).
- `reconfigure_scheduler` now registers one `daily_label_<idx>` cron per HH:MM in `label_times`.
- `PUT /settings` validates HH:MM each entry, dedupes, sorts.
- Settings page: time list with `+ Add time` and `×` per row (the last one can't be removed). All times run for every enabled account.

## Implemented — Iteration 10 (2026-05-05) — Article Master (canonical product)
**Schema (new collections)**
- `articles`: `{_id, name (unique), default_cost_price, created_at, updated_at, created_by}`
- `article_sku_map`: `{_id, article_id, account_id, sku}` — unique on `(account_id, sku)` (one SKU per account can only map to one article).

**Cost lookup migrated**
- `_pl_load_costs` and `_pl_lookup_cost` now resolve cost via `article_sku_map → articles.default_cost_price`. Old `pl_sku_costs` records are no longer read for P&L (kept on disk for audit; user can clear later).
- Unmapped (account, sku) pairs resolve to `0` and surface in Missing Articles.

**Endpoints**
- `GET /api/pl/articles` — list with embedded sku_map
- `POST /api/pl/articles` — create (rejects duplicate name + clashing (account, sku))
- `PUT /api/pl/articles/{id}` — update name/cost/sku_map (replaces map atomically; same clash protection)
- `DELETE /api/pl/articles/{id}` — drops article + all its mappings
- `GET /api/pl/articles/missing-skus` — every (account, sku) pair seen in `pl_orders` that isn't yet mapped, with order count, last_seen, account name + alias.
- `/api/pl/orders` enriched with `article_name` per row (resolved via `_pl_load_sku_article_labels`).

**Frontend**
- `PLSKUCosts.js` rewritten as a 2-tab page:
  - **Articles** (default): table with column-per-account (label = `alias (name)`), inline edit form auto-renders an SKU input per enabled account (new accounts show empty slots automatically). Global Cost field stores the canonical cost.
  - **Missing Articles**: list of unmapped (account, sku) pairs with order counts, search filter, and a `Map` button that jumps to the Articles tab to create/attach.
- `PLOrders.js`: SKU column now shows `Article Name` as primary (white) with the SKU as sub-text (grey). Falls back to the SKU alone if no article mapping exists.

**Verified end-to-end via curl**
- Create / dup-name 409 / cross-article SKU clash 409 / orders enrichment / missing-skus filter / delete.

## Implemented — Iteration 9 (2026-05-05) — Share URL fix + Tax depends on GST + alias rename
**Fixes**
- Share link 500 → root cause was `_as_aware_utc` was referenced but never committed to `server.py` (silent edit-loss). Helper now lives alongside `_mk_share_token` and both public endpoints use it. Verified: share POST 200, public GET returns proper 410 when file not on disk (vs previous 500).
- Share URL now honors `PUBLIC_BASE_URL` env var so production EC2 links point at the externally-reachable hostname (not the internal ingress).
- Cron: `tax_invoice_fetch` is now gated on a successful GST record existing for the same period. Tax is Meesho's downstream artifact — skipping saves a pointless browser run when GST isn't ready.
- Stored filenames now use the account's **alias** when set (fallback to `name`): `KommyHrbib_2026-03_GST_REPORT.zip`, `KommyHrbib_2026-03_TAX_INVOICE.xlsx`.

## Implemented — Iteration 8 (2026-05-05) — Bug fixes + Account alias
**Fixes**
- GST fetcher: month-picker popover was blocking the modal Download button. Now after ticking the month, the worker clicks a neutral spot at the modal's top-left (via bounding-box mouse click) to collapse the popover, with `Escape` as fallback.
- Public share URL was returning 500 (naive-vs-aware `datetime` comparison). Added `_as_aware_utc()` helper; both GST & Tax public endpoints now compare correctly.
- Authenticated download on GST & Tax pages returned `Not authenticated` because `<a href>` can't carry the Bearer token. Replaced with axios blob download.

**Account alias**
- New `alias` field on accounts (optional). System `name` is still used for scraping/URLs; `alias` is shown in the UI (dropdowns + Accounts table) as `Kommy Fashions (hrbib)`.
- Backend: `AccountIn`/`AccountUpdate` models accept alias; it's persisted and returned in `/api/accounts`.
- Frontend: input added to the Accounts form with help text, alias shown everywhere an account appears.

## Implemented — Iteration 7 (2026-05-05) — GST Report + Tax Invoice scrapers
**Workers (`scraper-ec2/`)**
- New `_meesho_ui.py` shared helpers (CDP attach, click-first-visible, watch-for-download-or-text race).
- New `gst_report_fetcher.py`: navigates Download → GST Report → year + month, races download vs "No GST report" toast. 3× retry, per-account folder, saves zip renamed `<acct>_<YYYY-MM>_GST_REPORT.zip`.
- New `tax_invoice_fetcher.py`: navigates Download → Tax Invoice, walks calendar back to target month using ← arrow, picks day-1 + last-day, captures download. Extracts only `Tax_invoice_details.xlsx` (PDFs discarded), saves as `<acct>_<YYYY-MM>_TAX_INVOICE.xlsx`.
- `label_worker.py` dispatches both new job types alongside `label_download` + `payments_fetch`.

**Backend (`server.py`)**
- New collections: `pl_gst_reports`, `pl_tax_invoices` with indexes.
- File storage on dashboard at `/app/backend/uploads/{gst_reports,tax_invoices}/<acct>/<YYYY-MM>/…`.
- Endpoints (per kind): `POST .../fetch-now`, `POST .../upload` (worker, multipart), `GET .../`, `GET .../{id}/download` (auth), `POST .../{id}/share` → 7-day signed URL, `GET .../{id}/public/{token}` (no auth, for CA), `DELETE .../{id}`.
- Worker reports `available=false` cleanly when Meesho says "no orders" — job is `done`, cron retries next day.
- Daily cron `daily_gst_tax_fetch` 02:00 IST; self-gates to days 7–15 and only enqueues for accounts/months without an `available=true` record yet.
- "Already fetched" guard — `409` on `fetch-now` if a successful record exists.

**Frontend**
- New page `/pl/tax-docs` (`PLTaxDocs.js`) with two panels (GST Report, Tax Invoice). Account/year/month picker (no defaults), per-row Download + Share-link (7-day) + Delete actions, NO DATA badge for `available=false` rows.
- Sidebar: new "GST & Tax Docs" item under P&L.
- JobsPage: added `GST` (cyan) + `TAX` (violet) badges and rich row content (period, account, file/no-data reason).

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
