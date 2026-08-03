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

## Dev/testing notes
- Preview env cannot reach EC2 Mongo. Backend/.env `MONGO_URL` switched to
  `mongodb://localhost:27017` for local testing. **User must revert to their
  EC2 IP before deploying.**
- Backend tests: `cd /app/backend && python -m pytest tests/ -q` — 35 pass.
