# Meesho Seller Central — Product Requirements Doc

## Original Problem Statement
User shared two Python files (`product_review.py` Playwright Meesho scraper, `worker.py` MongoDB job worker) and asked to build a **centralized seller-operations dashboard**. Existing scraper + worker run on user's local Windows machine with Chrome via CDP. Dashboard + MongoDB live on user's EC2 (Ubuntu) at `mongodb://43.205.229.129:27017/` (DB: `meesho`). Single worker, once-a-day scraping. Future modules: Label Auto-Download, Profit/Loss calculator, etc.

## User Personas
- **Single Admin (Meesho Seller / Operator)** — submits product URLs, monitors jobs, reviews scraped data and analytics for their listings + competitors.

## Architecture
- **Backend**: FastAPI + Motor (async MongoDB), JWT (HS256) Bearer auth, single seeded admin from `.env`.
- **Frontend**: React 19 (CRA + craco), TailwindCSS, Recharts, Phosphor Icons, dark "Control Room" theme (Outfit / IBM Plex Sans / JetBrains Mono).
- **Database**: Real EC2 MongoDB (read+write). Collections: `users` (auth), `jobs` (queue), `products` (scraped data).
- **Worker**: External — user's `worker.py` runs locally on Windows and connects to same EC2 Mongo. Not modified.

## Core Requirements (Static)
- JWT-based login (single admin), no public registration.
- Submit Meesho product URL(s) → enqueue as `pending` jobs.
- Job lifecycle visibility (pending / processing / done / failed) + retry / delete / reset-stuck.
- Browse scraped products; full product detail with reviews, rating distribution, media, helpful counts.
- Analytics: KPIs, overall rating distribution, review volume (30d), top sellers, most helpful reviews.
- Sidebar layout extensible for future modules (placeholders: Label Auto-Download, Profit/Loss).

## What's Been Implemented (2026-04-30)
**Backend (`/app/backend/server.py`)**
- `POST /api/auth/login`, `GET /api/auth/me`
- `POST /api/jobs`, `POST /api/jobs/bulk`, `GET /api/jobs`, `GET /api/jobs/stats`
- `POST /api/jobs/{id}/retry`, `POST /api/jobs/reset-stuck`, `DELETE /api/jobs/{id}`
- `GET /api/products` (search/sort), `GET /api/products/{product_id}`
- `GET /api/analytics/overview` (KPIs + top sellers + review volume + helpful reviews)
- `GET /api/health`
- Admin seeding on startup; bcrypt password hash; JWT 7-day Bearer tokens.
- Stuck-job detection (processing > 30min OR missing `started_at`).

**Frontend (`/app/frontend/src/`)**
- Pages: `LoginPage`, `DashboardPage`, `SubmitJobPage`, `JobsPage`, `ProductsPage`, `ProductDetailPage`, `AnalyticsPage`.
- Sidebar with sections (Operations, Insights, Future Modules placeholders).
- Auth via `AuthContext` + `ProtectedRoute`; token stored in `localStorage` (`md_token`).
- Live status pills, animated rating-distribution bars, recharts visuals, star/sort filters on reviews, bulk URL submission.
- Auto-refresh on Jobs page when pending/processing > 0.

**Verified (testing agent — iteration 1)**
- Backend: 23/23 pytest tests passing.
- Frontend: All e2e flows passing (login, nav, submit job, filters, retry, products, detail, analytics, logout).

## Backlog (Prioritized)
**P1**
- Real-time worker presence indicator (last heartbeat / last `started_at`).
- Pagination controls on Jobs & Products tables (currently capped at 100/page).
- Compare 2 products side-by-side (rating split, common reviewers).

**P2**
- Label Auto-Download module (next dashboard feature per user roadmap).
- Profit/Loss calculator module.
- LLM-powered review summaries / sentiment (deferred — user wanted to skip until free option discussed).
- Product image / thumbnail support (scraper currently doesn't capture).

**P3**
- Multiple users / role-based access.
- Audit log for job submissions.
- Export reviews CSV.
- Brute-force lockout on /api/auth/login.

## Notes / Operational
- Backend `.env`: `MONGO_URL`, `DB_NAME=meesho`, `JWT_SECRET`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `STUCK_JOB_MINUTES=30`.
- Existing data preserved: products `8sa1ay` (Kommy Fashions, 8 reviews) and `aeop5q` (OnlyU Fashions, 18 reviews).
- The user's `worker.py` is NOT running inside this preview env; submitted jobs stay `pending` until they run it locally.
