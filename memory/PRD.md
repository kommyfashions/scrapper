# Meesho Seller Central — PRD

## Product goal
Web dashboard for Meesho seller ops:
- Ingest Meesho product URLs → scrape reviews/ratings/analytics
- P&L Analyzer over uploaded Order Payments Excels + ad-spend + returns
- Auto-download shipping labels via EC2 workers (Playwright CDP-attach)
- **Product Master** — single source of truth for product metadata
- **PDF Sorter** — Meesho label PDFs sorted by SKU into TIER1/TIER2/MASTER

## Personas
- Seller admin (single user in practice; hardcoded admin)

## Core architecture
- **Backend**: FastAPI + Motor (async MongoDB) at `/api/*`
- **Frontend**: React + Tailwind + Warm Slate theme
- **Workers**: EC2 laptops with headless Chrome + Xvfb + systemd (out-of-scope for preview env)

## Collections
```
users, jobs, products              # existing scraper
accounts                           # Meesho seller accounts
pl_orders, pl_uploads, pl_ads_cost # P&L data
articles, article_sku_map, pl_sku_costs   # LEGACY — kept for fallback, will be dropped
pm_products                        # NEW  (unique: account_id + main_category + color)
pm_skus                            # NEW  (unique: account_id + sku)
pm_sizes                           # NEW
sku_normalization, courier_rules   # NEW  (PDF Sorter config)
pdf_sorter_runs                    # NEW  (run history)
```

## Product Master (Feb 2026)
- Business key: `(account_id, main_category, color)` — one row per combo
- Sizes & SKUs normalised into `pm_sizes` / `pm_skus` (arrays exploded from CSV Excel)
- Excel columns (exact, locked): `Account, Main Category, Color, Size, SKU, Cost`
- Endpoints: `/api/pm/products` (CRUD + filter + sort + paginate),
  `/api/pm/upload` (dry-run + commit), `/api/pm/upload/commit`,
  `/api/pm/template`, `/api/pm/export`, `/api/pm/facets`,
  `/api/pm/bulk-delete`, `/api/pm/admin/wipe-legacy`
- SKU Analysis rewritten as tree: `Category → Color → Account → SKUs → metrics`
  (`/api/pl/sku-analysis-tree`) — existing math preserved verbatim.

## PDF Sorter → Printout Labels (Feb 2026, revised)
- Renamed to **Printout Labels** at `/printout-labels` (old `/pdf-sorter` still routes here).
- **No account attribution** — upload PDFs from any mix of accounts in one shot.
- **Uses Product Master SKUs** as the primary grouping source: raw SKU on the
  label is looked up in `pm_skus` → grouped by the product's Category / Color.
- **Overrides tab** (renamed from "Config") only for edge-case raw SKUs that
  are not in Product Master, plus courier detection rules.
- **Analytics tab** — historical courier totals, SKU/Product totals, daily
  volume bar chart, date range filter + search. Endpoint:
  `GET /api/pdf-sorter/analytics?start_date=&end_date=&q=`
- Run history tab removed (aggregated view is now the analytics tab).
- Order-No dedupe within a run + CANCELLED/RTO warnings from `pl_orders`
  remain.

## Live Inventory Sync — finalised (Feb 24, 2026)
- **Scraper** (`/app/scraper-ec2/inventory_sync_fetcher.py`, EC2, job type
  `inventory_sync`): Rewritten with real DOM knowledge from operator's flow doc.
  Loads `https://supplier.meesho.com/panel/v3/new/services/{account.name}/inventory`,
  forces `Active > All Stock`, opens `Sort catalogs by` dropdown → picks
  `Newest First`, iterates catalog cards (via `Catalog ID` text), clicks each,
  extracts the **first** `Style ID:` value from the right panel (one
  representative Style ID per catalog), scrolls the left panel via
  `scroll_into_view_if_needed` to reveal more cards, and paginates via next-
  page button. Screenshots saved to `/tmp/meesho-inv-debug/<suffix>_<ts>/`.
- **Configurable pages** — job payload `pages` (default 20, cap 200) — driven
  from the UI's `Pages to scrape` input.
- **`POST /api/inventory-sync/run`** now accepts `{account_id, pages}` where
  `account_id` may be `"all"` (fan-out one job per enabled account, worker
  processes sequentially).
- **Backend enrichment at read-time**: each scraped `style_id` is looked up
  in `pm_skus` → linked `pm_products` → `main_category` shown on the
  dashboard. Unmatched Style IDs go to the Missing tab with
  `Main Category = "Unmapped"`, tagged with the account we scraped from.
- Dashboard table columns: `Account | Main Category | Style ID | Last Synced`.
- Two Excel exports: `GET /inventory-sync/live/export`, `/missing/export`
  (same 4 columns).
- Fresh snapshot each run (`meesho_live_skus.delete_many({account_id: aid})`
  before insert). SYNC HISTORY tab shows job-run metadata only.
- **`WorkerDriftBanner`** now has a **`Clear all stuck jobs`** button that
  purges every pending job older than 15 min (any type) — solves the
  recurring 254 stuck `product_scrape` legacy leftovers.

## Bulk Pause via Product Master (Feb 2026)
- New page **`/inventory-actions`** (sidebar: "Bulk Pause").
- User picks **Account → Main Category → Color → sizes** (or "whole product").
- Preview shows Style IDs + estimated Meesho SKUs.
- **`POST /api/inventory-actions/pause`** queues a `jobs.type=pause_skus` doc.
- **Multi-account** from day 1 — each `accounts` doc's own `debug_port`
  Chrome profile is used (same routing as `label_download`).
- Scraper worker (`/app/scraper-ec2/pause_skus_fetcher.py`) opens supplier
  panel, searches each Style ID, ticks matching sizes only, clicks
  **Pause Selected**, waits for the success toast. Records per-Style-ID
  status: `paused | already_paused | failed`.
- Endpoints: `/api/inventory-actions/options` (cascade),
  `/preview`, `/pause`, `/history`, `/{job_id}`.
- Idempotent: duplicate pause of same product returns `already_queued=true`.
- Tests: `/app/backend/tests/test_inventory_actions.py` — 5 pass.

## Theme (Feb 2026)
Warm Slate palette. Deep indigo-slate background `#0F172A`, cards `#1E293B`,
accent emerald `#10B981`. Chips/tags for sizes and SKUs.

## Backlog (P1/P2)
- Refactor server.py into `routers/` (still 3000+ lines).
- Export SKU Analysis to Excel.
- Inventory Loss column (units_returned × cost_price).
- GST/Tax "Re-run from yesterday" button.
- Worker heartbeat indicator.
- Suppress Playwright `TargetClosedError` traces.
- Pagination for Jobs & Products pages.
- 7-day rating movement card.
- Resend email → auto-mail CA the 7-day GST/Tax signed links.
- Bulk Resume (un-pause) — user explicitly said "not now, later".

## Dev/testing notes
- Preview env cannot reach EC2 Mongo. Backend/.env `MONGO_URL` switched to
  `mongodb://localhost:27017` for local testing. **User must revert to their
  EC2 IP before deploying.**
- Backend tests: `cd /app/backend && python -m pytest tests/ -q`.
- EC2 deploy after this change requires the user to `git pull` on both the
  dashboard box AND the scraper box, then restart `meesho-label-worker`
  systemd service so the new `pause_skus_fetcher.py` is picked up.
