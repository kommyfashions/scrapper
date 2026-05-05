from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Any, Dict

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # py<3.9 fallback

import bcrypt
import jwt
from bson import ObjectId
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, Query
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# --------------------------------------------------------------------------------------
# Config / DB
# --------------------------------------------------------------------------------------
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGO = "HS256"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@meesho-dash.local").lower()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
STUCK_JOB_MINUTES = int(os.environ.get("STUCK_JOB_MINUTES", "30"))
SCHED_TZ = ZoneInfo("Asia/Kolkata")
WORKER_API_KEY = os.environ.get("WORKER_API_KEY", "")  # shared secret for EC2 worker upload

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("dashboard")

app = FastAPI(title="Meesho Seller Dashboard API")
api = APIRouter(prefix="/api")

scheduler: Optional[AsyncIOScheduler] = None

# --------------------------------------------------------------------------------------
# Auth helpers
# --------------------------------------------------------------------------------------
def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()

def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except Exception:
        return False

def create_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id, "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

async def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = auth[7:]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return {"id": str(user["_id"]), "email": user["email"], "name": user.get("name", "")}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_user_or_worker(request: Request) -> dict:
    """Allow JWT-authenticated dashboard users OR the EC2 worker (shared secret)."""
    wk = request.headers.get("X-Worker-Key", "")
    if WORKER_API_KEY and wk and wk == WORKER_API_KEY:
        return {"id": "worker", "email": "worker@ec2", "name": "EC2 Worker"}
    return await get_current_user(request)

# --------------------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------------------
class LoginIn(BaseModel):
    email: str
    password: str

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]

class JobCreate(BaseModel):
    product_url: str

class JobsBulkCreate(BaseModel):
    product_urls: List[str]

class TrackToggle(BaseModel):
    tracked: bool

class ScheduleSettings(BaseModel):
    scrape_enabled: bool = True
    scrape_time: str = "11:00"   # HH:MM 24h IST
    label_enabled: bool = False
    label_time: str = "09:30"
    skip_dates: List[str] = []        # ["2026-05-03", ...]
    skip_weekdays: List[int] = []     # 0=Mon ... 6=Sun (Python weekday())

class AccountIn(BaseModel):
    name: str
    alias: Optional[str] = None
    debug_port: int
    profile_dir: str
    pending_url: Optional[str] = None
    ready_url: Optional[str] = None
    enabled: bool = True

class AccountUpdate(BaseModel):
    name: Optional[str] = None
    alias: Optional[str] = None
    debug_port: Optional[int] = None
    profile_dir: Optional[str] = None
    pending_url: Optional[str] = None
    ready_url: Optional[str] = None
    enabled: Optional[bool] = None

class LabelRunIn(BaseModel):
    account_id: Optional[str] = None
    all_accounts: bool = False

# --------------------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------------------
MEESHO_PRODUCT_URL_RE = re.compile(r"https?://(www\.)?meesho\.com/.+/p/([A-Za-z0-9_-]+)/?", re.IGNORECASE)
HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

def extract_product_id(url: str) -> Optional[str]:
    m = MEESHO_PRODUCT_URL_RE.search(url.strip())
    return m.group(2) if m else None

def serialize_doc(d: Optional[dict]) -> Optional[dict]:
    if d is None:
        return None
    out = {}
    for k, v in d.items():
        if k == "_id":
            out["id"] = str(v)
        elif isinstance(v, ObjectId):
            out[k] = str(v)
        elif isinstance(v, datetime):
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            out[k] = v.isoformat().replace("+00:00", "Z")
        else:
            out[k] = v
    return out

def avg_rating_from_distribution(dist: Optional[Dict[str, int]]) -> Optional[float]:
    if not dist:
        return None
    total = 0
    weighted = 0
    for k, v in dist.items():
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

def pick_product_image(p: dict) -> Optional[str]:
    """Return the proper product image URL captured by the scraper.
    No review-media fallback — UI shows a placeholder if these aren't set."""
    for k in ("product_image_large_url", "product_image_thumb_url"):
        v = p.get(k)
        if v:
            return v
    return None

# --------------------------------------------------------------------------------------
# Scheduler
# --------------------------------------------------------------------------------------
async def get_settings_doc() -> dict:
    doc = await db.settings.find_one({"_id": "schedule"})
    if not doc:
        doc = {"_id": "schedule", **ScheduleSettings().model_dump()}
        await db.settings.insert_one(doc)
    return doc

async def enqueue_daily_scrape_jobs():
    """Enqueue one pending product_scrape job per tracked product."""
    try:
        now = datetime.now(timezone.utc)
        count = 0
        async for p in db.products.find({"tracked": True}, {"product_id": 1, "product_url": 1}):
            pid = p.get("product_id")
            url = p.get("product_url")
            if not pid or not url:
                continue
            # skip if there's already a pending/processing job for this product_id
            existing = await db.jobs.find_one({
                "product_id": pid,
                "status": {"$in": ["pending", "processing"]},
                "type": "product_scrape",
            })
            if existing:
                continue
            await db.jobs.insert_one({
                "product_url": url,
                "product_id": pid,
                "type": "product_scrape",
                "status": "pending",
                "created_at": now,
                "submitted_by": "scheduler",
            })
            count += 1
        logger.info(f"[scheduler] Enqueued {count} daily scrape job(s)")
    except Exception as e:
        logger.exception(f"[scheduler] scrape enqueue failed: {e}")

async def is_skipped_today() -> bool:
    s = await get_settings_doc()
    today_local = datetime.now(SCHED_TZ)
    iso = today_local.strftime("%Y-%m-%d")
    if iso in (s.get("skip_dates") or []):
        return True
    if today_local.weekday() in (s.get("skip_weekdays") or []):
        return True
    return False


async def detect_alerts():
    """Run every 30min: detect review-velocity & rating-drop anomalies vs ~24h ago.
    Dedup with key = (product_id, type, YYYY-MM-DD)."""
    try:
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        cutoff_lo = now - timedelta(hours=30)
        cutoff_hi = now - timedelta(hours=20)
        new_count = 0
        async for p in db.products.find({"tracked": True}, {
            "_id": 0, "product_id": 1, "product_name": 1,
            "rating_distribution": 1, "total_reviews": 1,
        }):
            pid = p.get("product_id")
            if not pid:
                continue
            cur_dist = p.get("rating_distribution") or {}
            cur_avg = avg_rating_from_distribution(cur_dist)

            # find a snapshot from ~24h ago
            prev = await db.product_history.find_one(
                {"product_id": pid, "snapshot_at": {"$gte": cutoff_lo, "$lte": cutoff_hi}},
                sort=[("snapshot_at", -1)],
            )
            if not prev:
                # also accept "earliest snapshot older than 20h" if present
                prev = await db.product_history.find_one(
                    {"product_id": pid, "snapshot_at": {"$lte": cutoff_hi}},
                    sort=[("snapshot_at", -1)],
                )
            if not prev:
                continue

            prev_dist = prev.get("rating_distribution") or {}
            prev_avg = prev.get("avg_rating")

            # 1-star spike
            cur_1 = int(cur_dist.get("1") or cur_dist.get(1) or 0)
            prev_1 = int(prev_dist.get("1") or prev_dist.get(1) or 0)
            delta_1 = cur_1 - prev_1
            if delta_1 >= 3:
                key = f"{pid}:one_star_spike:{today}"
                exists = await db.alerts.find_one({"dedup_key": key})
                if not exists:
                    await db.alerts.insert_one({
                        "type": "one_star_spike",
                        "severity": "high",
                        "product_id": pid,
                        "product_name": p.get("product_name"),
                        "message": f"+{delta_1} new 1★ reviews in last 24h",
                        "details": {"prev_1star": prev_1, "cur_1star": cur_1},
                        "created_at": now,
                        "read": False,
                        "dedup_key": key,
                    })
                    new_count += 1

            # rating drop
            if cur_avg is not None and prev_avg is not None:
                drop = round(prev_avg - cur_avg, 2)
                if drop >= 0.2:
                    key = f"{pid}:rating_drop:{today}"
                    exists = await db.alerts.find_one({"dedup_key": key})
                    if not exists:
                        await db.alerts.insert_one({
                            "type": "rating_drop",
                            "severity": "medium",
                            "product_id": pid,
                            "product_name": p.get("product_name"),
                            "message": f"avg rating dropped {prev_avg} → {cur_avg} ({drop:.2f}) in 24h",
                            "details": {"prev_avg": prev_avg, "cur_avg": cur_avg, "drop": drop},
                            "created_at": now,
                            "read": False,
                            "dedup_key": key,
                        })
                        new_count += 1

        if new_count:
            logger.info(f"[scheduler] alerts: {new_count} new alert(s) raised")
    except Exception as e:
        logger.exception(f"[scheduler] detect_alerts failed: {e}")


async def snapshot_all_products():
    """Capture a daily snapshot of every tracked product into product_history."""
    try:
        now = datetime.now(timezone.utc)
        count = 0
        async for p in db.products.find({"tracked": True}, {
            "_id": 0, "product_id": 1, "total_reviews": 1, "rating_distribution": 1,
        }):
            pid = p.get("product_id")
            if not pid:
                continue
            dist = p.get("rating_distribution") or {}
            await db.product_history.insert_one({
                "product_id": pid,
                "snapshot_at": now,
                "total_reviews": p.get("total_reviews") or 0,
                "rating_distribution": dist,
                "avg_rating": avg_rating_from_distribution(dist),
            })
            count += 1
        logger.info(f"[scheduler] snapshot wrote {count} product_history rows")
    except Exception as e:
        logger.exception(f"[scheduler] snapshot failed: {e}")


async def enqueue_daily_label_job():
    try:
        if await is_skipped_today():
            logger.info("[scheduler] today is in skip rules — label job not enqueued")
            return
        now = datetime.now(timezone.utc)
        count = 0
        async for acc in db.accounts.find({"enabled": True}):
            existing = await db.jobs.find_one({
                "type": "label_download",
                "account_id": str(acc["_id"]),
                "status": {"$in": ["pending", "processing"]},
            })
            if existing:
                continue
            await db.jobs.insert_one({
                "type": "label_download",
                "status": "pending",
                "account_id": str(acc["_id"]),
                "account_name": acc.get("name"),
                "created_at": now,
                "submitted_by": "scheduler",
            })
            count += 1
        logger.info(f"[scheduler] Enqueued {count} label_download job(s)")
    except Exception as e:
        logger.exception(f"[scheduler] label enqueue failed: {e}")

def _parse_hhmm(s: str) -> tuple:
    m = HHMM_RE.match(s or "")
    if not m:
        return (11, 0)
    return (int(m.group(1)), int(m.group(2)))

async def reconfigure_scheduler():
    global scheduler
    if scheduler is None:
        return
    # remove existing jobs
    for j in scheduler.get_jobs():
        scheduler.remove_job(j.id)
    s = await get_settings_doc()
    if s.get("scrape_enabled", True):
        h, m = _parse_hhmm(s.get("scrape_time", "11:00"))
        scheduler.add_job(
            enqueue_daily_scrape_jobs,
            CronTrigger(hour=h, minute=m, timezone=SCHED_TZ),
            id="daily_scrape", replace_existing=True,
        )
        # snapshot 5 minutes after the scrape to give workers time to refresh data
        sm = (m + 5) % 60
        sh = (h + (1 if m + 5 >= 60 else 0)) % 24
        scheduler.add_job(
            snapshot_all_products,
            CronTrigger(hour=sh, minute=sm, timezone=SCHED_TZ),
            id="daily_snapshot", replace_existing=True,
        )
    if s.get("label_enabled", False):
        h, m = _parse_hhmm(s.get("label_time", "09:30"))
        scheduler.add_job(
            enqueue_daily_label_job,
            CronTrigger(hour=h, minute=m, timezone=SCHED_TZ),
            id="daily_label", replace_existing=True,
        )
    # Payments-file auto-fetch (always on; toggle later if needed)
    # Every Monday 09:00 IST → previous_week
    scheduler.add_job(
        enqueue_payments_fetch_jobs,
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=SCHED_TZ),
        id="weekly_payments_fetch", replace_existing=True,
        kwargs={"period": "previous_week"},
    )
    # Every 5th of month 09:00 IST → previous_month
    scheduler.add_job(
        enqueue_payments_fetch_jobs,
        CronTrigger(day=5, hour=9, minute=0, timezone=SCHED_TZ),
        id="monthly_payments_fetch", replace_existing=True,
        kwargs={"period": "previous_month"},
    )
    # alerts run every 30 minutes regardless of toggles
    scheduler.add_job(
        detect_alerts,
        CronTrigger(minute="*/30", timezone=SCHED_TZ),
        id="alerts_check", replace_existing=True,
    )
    # GST + Tax Invoice — daily 02:00 IST, function self-gates to days 7–15
    scheduler.add_job(
        enqueue_gst_and_tax_jobs,
        CronTrigger(hour=2, minute=0, timezone=SCHED_TZ),
        id="daily_gst_tax_fetch", replace_existing=True,
    )
    logger.info(f"[scheduler] reconfigured: jobs={[j.id for j in scheduler.get_jobs()]}")

# --------------------------------------------------------------------------------------
# Startup
# --------------------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    global scheduler
    try:
        await db.users.create_index("email", unique=True)
        await db.jobs.create_index("status")
        await db.jobs.create_index("created_at")
        await db.jobs.create_index("type")
        await db.products.create_index("product_id", unique=False)
        await db.product_history.create_index([("product_id", 1), ("snapshot_at", -1)])
        await db.accounts.create_index("name", unique=True)
        await db.accounts.create_index("debug_port", unique=True)
        await db.alerts.create_index([("created_at", -1)])
        await db.alerts.create_index("dedup_key", unique=True, sparse=True)
        # Profit & Loss
        await db.pl_orders.create_index([("account_id", 1), ("sub_order_no", 1)], unique=True)
        await db.pl_orders.create_index("order_status")
        await db.pl_orders.create_index("sku")
        await db.pl_orders.create_index("order_date")
        await db.pl_sku_costs.create_index([("account_id", 1), ("sku", 1)], unique=True)
        await db.pl_uploads.create_index([("uploaded_at", -1)])
        await db.pl_ads_cost.create_index(
            [("account_id", 1), ("campaign_id", 1), ("deduction_date", 1)], unique=True
        )
        # GST reports + Tax invoices
        await db.pl_gst_reports.create_index(
            [("account_id", 1), ("year", 1), ("month", 1)]
        )
        await db.pl_gst_reports.create_index([("fetched_at", -1)])
        await db.pl_gst_reports.create_index("share_token", sparse=True)
        await db.pl_tax_invoices.create_index(
            [("account_id", 1), ("year", 1), ("month", 1)]
        )
        await db.pl_tax_invoices.create_index([("fetched_at", -1)])
        await db.pl_tax_invoices.create_index("share_token", sparse=True)
    except Exception as e:
        logger.warning(f"Index creation issue: {e}")

    # one-time SKU-cost dedupe / account_id normalization
    try:
        await _pl_dedupe_sku_costs()
    except Exception as e:
        logger.warning(f"[pl-migration] sku-cost dedupe failed: {e}")

    # seed admin
    existing = await db.users.find_one({"email": ADMIN_EMAIL})
    if not existing:
        await db.users.insert_one({
            "email": ADMIN_EMAIL,
            "password_hash": hash_password(ADMIN_PASSWORD),
            "name": "Admin", "role": "admin",
            "created_at": datetime.now(timezone.utc),
        })
        logger.info(f"Seeded admin user: {ADMIN_EMAIL}")
    elif not verify_password(ADMIN_PASSWORD, existing["password_hash"]):
        await db.users.update_one(
            {"email": ADMIN_EMAIL},
            {"$set": {"password_hash": hash_password(ADMIN_PASSWORD)}},
        )
        logger.info("Admin password updated from env.")

    # seed settings
    await get_settings_doc()

    # stamp legacy jobs with default type
    await db.jobs.update_many({"type": {"$exists": False}}, {"$set": {"type": "product_scrape"}})

    # auto-track existing products that don't have a tracked flag yet
    await db.products.update_many({"tracked": {"$exists": False}}, {"$set": {"tracked": True}})

    # start scheduler
    scheduler = AsyncIOScheduler(timezone=SCHED_TZ)
    scheduler.start()
    await reconfigure_scheduler()

@app.on_event("shutdown")
async def shutdown():
    if scheduler:
        scheduler.shutdown(wait=False)
    client.close()

# --------------------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------------------
@api.post("/auth/login", response_model=TokenOut)
async def login(body: LoginIn):
    email = body.email.strip().lower()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_token(str(user["_id"]), email)
    return TokenOut(access_token=token, user={"id": str(user["_id"]), "email": email, "name": user.get("name", "")})

@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return user

# --------------------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------------------
@api.post("/jobs")
async def create_job(body: JobCreate, user: dict = Depends(get_current_user)):
    url = body.product_url.strip()
    pid = extract_product_id(url)
    if not pid:
        raise HTTPException(status_code=400, detail="Not a valid Meesho product URL (expected /p/<id>)")
    doc = {
        "product_url": url, "product_id": pid,
        "type": "product_scrape", "status": "pending",
        "created_at": datetime.now(timezone.utc),
        "submitted_by": user["email"],
    }
    res = await db.jobs.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize_doc(doc)

@api.post("/jobs/bulk")
async def create_jobs_bulk(body: JobsBulkCreate, user: dict = Depends(get_current_user)):
    created, skipped = [], []
    for raw in body.product_urls:
        u = raw.strip()
        if not u:
            continue
        pid = extract_product_id(u)
        if not pid:
            skipped.append({"url": u, "reason": "invalid"})
            continue
        doc = {
            "product_url": u, "product_id": pid,
            "type": "product_scrape", "status": "pending",
            "created_at": datetime.now(timezone.utc),
            "submitted_by": user["email"],
        }
        res = await db.jobs.insert_one(doc)
        doc["_id"] = res.inserted_id
        created.append(serialize_doc(doc))
    return {"created": created, "skipped": skipped}

@api.get("/jobs")
async def list_jobs(
    status: Optional[str] = None,
    type: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(50, le=200),
    skip: int = 0,
    user: dict = Depends(get_current_user),
):
    query: dict = {}
    if status and status != "all":
        query["status"] = status
    if type and type != "all":
        query["type"] = type
    if q:
        query["product_url"] = {"$regex": re.escape(q), "$options": "i"}
    cursor = db.jobs.find(query).sort("created_at", -1).skip(skip).limit(limit)
    items = [serialize_doc(d) for d in await cursor.to_list(length=limit)]
    total = await db.jobs.count_documents(query)
    return {"items": items, "total": total}

@api.get("/jobs/stats")
async def jobs_stats(user: dict = Depends(get_current_user)):
    pipe = [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]
    out = {"pending": 0, "processing": 0, "done": 0, "failed": 0}
    async for row in db.jobs.aggregate(pipe):
        out[row["_id"]] = row["count"]
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_JOB_MINUTES)
    stuck = await db.jobs.count_documents({
        "status": "processing",
        "$or": [
            {"started_at": {"$lt": cutoff}},
            {"started_at": {"$exists": False}},
        ],
    })
    out["stuck"] = stuck
    return out

@api.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(job_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid job id")
    res = await db.jobs.update_one(
        {"_id": oid},
        {"$set": {"status": "pending"}, "$unset": {"error": "", "started_at": "", "finished_at": ""}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True}

@api.post("/jobs/reset-stuck")
async def reset_stuck(user: dict = Depends(get_current_user)):
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_JOB_MINUTES)
    res = await db.jobs.update_many(
        {"status": "processing", "started_at": {"$lt": cutoff}},
        {"$set": {"status": "pending"}, "$unset": {"started_at": ""}},
    )
    res2 = await db.jobs.update_many(
        {"status": "processing", "started_at": {"$exists": False}},
        {"$set": {"status": "pending"}},
    )
    return {"reset": res.modified_count + res2.modified_count}

@api.delete("/jobs/{job_id}")
async def delete_job(job_id: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(job_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid job id")
    res = await db.jobs.delete_one({"_id": oid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True}

# --------------------------------------------------------------------------------------
# Products
# --------------------------------------------------------------------------------------
@api.get("/products")
async def list_products(
    q: Optional[str] = None,
    tracked: Optional[bool] = None,
    sort: str = "updated_at",
    order: str = "desc",
    limit: int = Query(50, le=200),
    skip: int = 0,
    user: dict = Depends(get_current_user),
):
    query: dict = {}
    if q:
        regex = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [
            {"product_id": regex}, {"product_url": regex},
            {"seller.name": regex}, {"product_name": regex},
        ]
    if tracked is not None:
        query["tracked"] = tracked
    sort_field = sort if sort in ("updated_at", "total_reviews", "product_id") else "updated_at"
    direction = -1 if order == "desc" else 1
    # keep payload light: exclude review text/customer/etc, keep only media (for image fallback)
    projection = {
        "reviews.text": 0, "reviews.rating": 0, "reviews.customer": 0,
        "reviews.helpful": 0, "reviews.review_id": 0, "reviews.created_at": 0,
    }
    cursor = db.products.find(query, projection).sort(sort_field, direction).skip(skip).limit(limit)
    items = []
    async for d in cursor:
        image = pick_product_image(d)
        d = serialize_doc(d)
        d.pop("reviews", None)  # don't ship media list to UI
        d["avg_rating"] = avg_rating_from_distribution(d.get("rating_distribution"))
        d["image"] = image
        items.append(d)
    total = await db.products.count_documents(query)
    return {"items": items, "total": total}

@api.get("/products/{product_id}")
async def product_detail(product_id: str, user: dict = Depends(get_current_user)):
    doc = await db.products.find_one({"product_id": product_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Product not found")
    out = serialize_doc(doc)
    out["avg_rating"] = avg_rating_from_distribution(out.get("rating_distribution"))
    out["image"] = pick_product_image(doc)
    return out

@api.post("/products/{product_id}/track")
async def toggle_track(product_id: str, body: TrackToggle, user: dict = Depends(get_current_user)):
    res = await db.products.update_one({"product_id": product_id}, {"$set": {"tracked": body.tracked}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"ok": True, "tracked": body.tracked}

@api.get("/products/{product_id}/history")
async def product_history(product_id: str, days: int = 30, user: dict = Depends(get_current_user)):
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))
    cursor = db.product_history.find(
        {"product_id": product_id, "snapshot_at": {"$gte": since}},
        {"_id": 0},
    ).sort("snapshot_at", 1)
    items = []
    async for d in cursor:
        if isinstance(d.get("snapshot_at"), datetime):
            d["snapshot_at"] = d["snapshot_at"].isoformat()
        items.append(d)
    return {"items": items}

# --------------------------------------------------------------------------------------
# Accounts (per Meesho seller account, used for label downloads on EC2)
# --------------------------------------------------------------------------------------
def _slugify(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-") or "account"

async def _suggest_account_defaults() -> dict:
    """Suggest next free port + profile dir for a new account."""
    used_ports = set()
    async for a in db.accounts.find({}, {"debug_port": 1}):
        if a.get("debug_port"):
            used_ports.add(int(a["debug_port"]))
    port = 9222
    while port in used_ports:
        port += 1
    n = await db.accounts.count_documents({}) + 1
    return {
        "debug_port": port,
        "profile_dir": f"/home/ubuntu/chrome-profile{n}",
    }

@api.get("/accounts/defaults")
async def account_defaults(user: dict = Depends(get_current_user)):
    return await _suggest_account_defaults()

@api.get("/accounts")
async def list_accounts(user: dict = Depends(get_current_user)):
    items = []
    async for a in db.accounts.find().sort("created_at", 1):
        items.append(serialize_doc(a))
    return {"items": items}

@api.post("/accounts")
async def create_account(body: AccountIn, user: dict = Depends(get_current_user)):
    # uniqueness: name and port
    if await db.accounts.find_one({"name": body.name}):
        raise HTTPException(status_code=400, detail=f"Account name '{body.name}' already exists")
    if await db.accounts.find_one({"debug_port": body.debug_port}):
        raise HTTPException(status_code=400, detail=f"Port {body.debug_port} already used by another account")
    doc = {
        **body.model_dump(),
        "slug": _slugify(body.name),
        "created_at": datetime.now(timezone.utc),
        "last_used_at": None,
        "last_status": None,
    }
    res = await db.accounts.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize_doc(doc)

@api.put("/accounts/{account_id}")
async def update_account(account_id: str, body: AccountUpdate, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(account_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid account_id")
    update = {k: v for k, v in body.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="nothing to update")
    if "name" in update:
        clash = await db.accounts.find_one({"name": update["name"], "_id": {"$ne": oid}})
        if clash:
            raise HTTPException(status_code=400, detail=f"Account name '{update['name']}' already exists")
        update["slug"] = _slugify(update["name"])
    if "debug_port" in update:
        clash = await db.accounts.find_one({"debug_port": update["debug_port"], "_id": {"$ne": oid}})
        if clash:
            raise HTTPException(status_code=400, detail=f"Port {update['debug_port']} already used")
    res = await db.accounts.update_one({"_id": oid}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Account not found")
    doc = await db.accounts.find_one({"_id": oid})
    return serialize_doc(doc)

@api.delete("/accounts/{account_id}")
async def delete_account(account_id: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(account_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid account_id")
    res = await db.accounts.delete_one({"_id": oid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"ok": True}

# --------------------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------------------
@api.post("/labels/run-now")
async def label_run_now(body: Optional[LabelRunIn] = None, user: dict = Depends(get_current_user)):
    body = body or LabelRunIn()
    # ── multi-account / fan-out path ─────────────────────────────────────────
    if body.all_accounts or not body.account_id:
        now = datetime.now(timezone.utc)
        queued, skipped = [], []
        async for acc in db.accounts.find({"enabled": True}):
            existing = await db.jobs.find_one({
                "type": "label_download",
                "account_id": str(acc["_id"]),
                "status": {"$in": ["pending", "processing"]},
            })
            if existing:
                skipped.append({"account_id": str(acc["_id"]), "name": acc.get("name"), "reason": "already_queued"})
                continue
            doc = {
                "type": "label_download",
                "status": "pending",
                "account_id": str(acc["_id"]),
                "account_name": acc.get("name"),
                "created_at": now,
                "submitted_by": user["email"],
            }
            r = await db.jobs.insert_one(doc)
            queued.append({"id": str(r.inserted_id), "account_id": str(acc["_id"]), "name": acc.get("name")})
        if not queued and not skipped:
            raise HTTPException(status_code=400, detail="No enabled accounts. Add an account first.")
        return {"ok": True, "queued": queued, "skipped": skipped}

    # ── single-account path ──────────────────────────────────────────────────
    try:
        oid = ObjectId(body.account_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid account_id")
    acc = await db.accounts.find_one({"_id": oid})
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    if not acc.get("enabled", True):
        raise HTTPException(status_code=400, detail=f"Account '{acc.get('name')}' is disabled")
    existing = await db.jobs.find_one({
        "type": "label_download",
        "account_id": body.account_id,
        "status": {"$in": ["pending", "processing"]},
    })
    if existing:
        return {"ok": True, "already_queued": True, "id": str(existing["_id"])}
    doc = {
        "type": "label_download",
        "status": "pending",
        "account_id": body.account_id,
        "account_name": acc.get("name"),
        "created_at": datetime.now(timezone.utc),
        "submitted_by": user["email"],
    }
    res = await db.jobs.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize_doc(doc)

@api.get("/labels/runs")
async def label_runs(limit: int = Query(50, le=200), user: dict = Depends(get_current_user)):
    cursor = db.jobs.find({"type": "label_download"}).sort("created_at", -1).limit(limit)
    items = [serialize_doc(d) for d in await cursor.to_list(length=limit)]
    return {"items": items}

# --------------------------------------------------------------------------------------
# Settings / Scheduler
# --------------------------------------------------------------------------------------
@api.get("/settings")
async def get_settings(user: dict = Depends(get_current_user)):
    s = await get_settings_doc()
    s.pop("_id", None)
    # include next run info
    next_runs = {}
    if scheduler:
        for j in scheduler.get_jobs():
            next_runs[j.id] = j.next_run_time.isoformat() if j.next_run_time else None
    s["next_runs"] = next_runs
    s["timezone"] = "Asia/Kolkata"
    return s

@api.put("/settings")
async def put_settings(body: ScheduleSettings, user: dict = Depends(get_current_user)):
    if not HHMM_RE.match(body.scrape_time):
        raise HTTPException(status_code=400, detail="scrape_time must be HH:MM (24h)")
    if not HHMM_RE.match(body.label_time):
        raise HTTPException(status_code=400, detail="label_time must be HH:MM (24h)")
    await db.settings.update_one(
        {"_id": "schedule"},
        {"$set": body.model_dump()},
        upsert=True,
    )
    await reconfigure_scheduler()
    return await get_settings(user)  # echo updated

@api.post("/scheduler/run-now")
async def manual_run(what: str = Query("scrape"), user: dict = Depends(get_current_user)):
    """Manually trigger a daily run right now (scrape | label)."""
    if what == "scrape":
        await enqueue_daily_scrape_jobs()
    elif what == "snapshot":
        await snapshot_all_products()
    elif what == "label":
        await enqueue_daily_label_job()
    else:
        raise HTTPException(status_code=400, detail="what must be 'scrape' | 'label' | 'snapshot'")
    return {"ok": True}

# --------------------------------------------------------------------------------------
# Analytics
# --------------------------------------------------------------------------------------
@api.get("/analytics/overview")
async def analytics_overview(user: dict = Depends(get_current_user)):
    total_products = await db.products.count_documents({})
    pipe_global = [
        {"$group": {
            "_id": None,
            "total_reviews": {"$sum": "$total_reviews"},
            "r1": {"$sum": {"$ifNull": ["$rating_distribution.1", 0]}},
            "r2": {"$sum": {"$ifNull": ["$rating_distribution.2", 0]}},
            "r3": {"$sum": {"$ifNull": ["$rating_distribution.3", 0]}},
            "r4": {"$sum": {"$ifNull": ["$rating_distribution.4", 0]}},
            "r5": {"$sum": {"$ifNull": ["$rating_distribution.5", 0]}},
        }}
    ]
    overall = {"total_reviews": 0, "rating_distribution": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}, "avg_rating": None}
    async for row in db.products.aggregate(pipe_global):
        dist = {"1": row["r1"], "2": row["r2"], "3": row["r3"], "4": row["r4"], "5": row["r5"]}
        overall = {
            "total_reviews": row["total_reviews"],
            "rating_distribution": dist,
            "avg_rating": avg_rating_from_distribution(dist),
        }

    top_sellers_pipe = [
        {"$group": {"_id": "$seller.name", "products": {"$sum": 1}, "reviews": {"$sum": "$total_reviews"}}},
        {"$match": {"_id": {"$ne": None}}},
        {"$sort": {"reviews": -1}}, {"$limit": 10},
    ]
    top_sellers = []
    async for row in db.products.aggregate(top_sellers_pipe):
        top_sellers.append({"seller": row["_id"], "products": row["products"], "reviews": row["reviews"]})

    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    jobs_today = await db.jobs.count_documents({"created_at": {"$gte": start_of_day}})

    status_breakdown = {"pending": 0, "processing": 0, "done": 0, "failed": 0}
    async for row in db.jobs.aggregate([{"$group": {"_id": "$status", "count": {"$sum": 1}}}]):
        if row["_id"] in status_breakdown:
            status_breakdown[row["_id"]] = row["count"]

    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    volume_pipe = [
        {"$unwind": "$reviews"},
        {"$addFields": {"review_dt": {"$dateFromString": {"dateString": "$reviews.created_at", "onError": None, "onNull": None}}}},
        {"$match": {"review_dt": {"$gte": thirty_days_ago}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$review_dt"}}, "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    review_volume = []
    try:
        async for row in db.products.aggregate(volume_pipe):
            review_volume.append({"date": row["_id"], "count": row["count"]})
    except Exception as e:
        logger.warning(f"Review volume aggregation failed: {e}")

    helpful_pipe = [
        {"$unwind": "$reviews"},
        {"$match": {"reviews.helpful": {"$gt": 0}}},
        {"$sort": {"reviews.helpful": -1}}, {"$limit": 10},
        {"$project": {"_id": 0, "product_id": 1, "seller": "$seller.name", "review": "$reviews"}},
    ]
    helpful_reviews = []
    async for row in db.products.aggregate(helpful_pipe):
        helpful_reviews.append({
            "product_id": row.get("product_id"),
            "seller": row.get("seller"),
            "text": row["review"].get("text"),
            "rating": row["review"].get("rating"),
            "customer": row["review"].get("customer"),
            "helpful": row["review"].get("helpful"),
            "created_at": row["review"].get("created_at"),
        })

    return {
        "total_products": total_products,
        "total_reviews": overall["total_reviews"],
        "avg_rating": overall["avg_rating"],
        "rating_distribution": overall["rating_distribution"],
        "jobs_today": jobs_today,
        "job_status_breakdown": status_breakdown,
        "top_sellers": top_sellers,
        "review_volume": review_volume,
        "helpful_reviews": helpful_reviews,
    }

# --------------------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------------------
@api.get("/alerts")
async def list_alerts(
    unread_only: bool = False,
    limit: int = Query(50, le=200),
    user: dict = Depends(get_current_user),
):
    q: dict = {}
    if unread_only:
        q["read"] = False
    cursor = db.alerts.find(q).sort("created_at", -1).limit(limit)
    items = [serialize_doc(d) for d in await cursor.to_list(length=limit)]
    unread = await db.alerts.count_documents({"read": False})
    total = await db.alerts.count_documents({})
    return {"items": items, "unread": unread, "total": total}

@api.post("/alerts/{alert_id}/read")
async def mark_alert_read(alert_id: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(alert_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid alert_id")
    res = await db.alerts.update_one({"_id": oid}, {"$set": {"read": True}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True}

@api.post("/alerts/read-all")
async def mark_all_read(user: dict = Depends(get_current_user)):
    res = await db.alerts.update_many({"read": False}, {"$set": {"read": True}})
    return {"ok": True, "updated": res.modified_count}

@api.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: str, user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(alert_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid alert_id")
    res = await db.alerts.delete_one({"_id": oid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True}

@api.post("/alerts/check-now")
async def alerts_check_now(user: dict = Depends(get_current_user)):
    """Manually run the alerts detector right now."""
    await detect_alerts()
    return {"ok": True}

# --------------------------------------------------------------------------------------
# Profit & Loss (Meesho payment file analyzer)
# --------------------------------------------------------------------------------------
import io
import pandas as pd
from fastapi import UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse
from pymongo import UpdateOne

PL_VALID_TRANSITIONS = {
    "CREATED": {"SHIPPED", "CANCELLED"},
    "SHIPPED": {"DELIVERED", "RTO", "CANCELLED"},
    "DELIVERED": {"RETURNED", "EXCHANGE"},
    "RTO": set(),
    "RETURNED": set(),
    "CANCELLED": set(),
    "EXCHANGE": set(),
}

PL_STATUS_MAP = {
    "delivered": "DELIVERED",
    "return": "RETURNED",
    "returned": "RETURNED",
    "rto": "RTO",
    "shipped": "SHIPPED",
    "cancelled": "CANCELLED",
    "canceled": "CANCELLED",
    "exchange": "EXCHANGE",
    "created": "CREATED",
}

def pl_safe_float(v) -> float:
    if v is None:
        return 0.0
    try:
        if isinstance(v, float) and pd.isna(v):
            return 0.0
    except Exception:
        pass
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return 0.0
    try:
        return float(s.replace(",", ""))
    except Exception:
        return 0.0

def pl_normalize_status(v) -> Optional[str]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return PL_STATUS_MAP.get(str(v).strip().lower())

def pl_payment_status(settlement: float, payment_date) -> str:
    if settlement > 0 and payment_date and str(payment_date).strip() not in ("", "nan", "NaT"):
        return "PAID"
    if settlement > 0:
        return "PENDING"
    return "ADJUSTED"

def pl_oid_or_400(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid id")

def _pl_norm_acc(v) -> Optional[str]:
    """Normalise account_id to either a real id-string or None.
    Empty string, 'all', 'global', 'none', 'null' -> None."""
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() in ("all", "global", "none", "null"):
        return None
    return s

def _pl_lookup_cost(costs: dict, account_id, sku) -> float:
    """Account-specific cost takes priority over global (None) fallback."""
    if (account_id, sku) in costs:
        return costs[(account_id, sku)] or 0
    return costs.get((None, sku), 0) or 0

async def _pl_load_costs(sku_costs_q: dict) -> dict:
    """Load costs sorted by updated_at ASC so the most recent write wins
    (handles the rare residual duplicate after migration)."""
    costs = {}
    async for c in db.pl_sku_costs.find(sku_costs_q, {"_id": 0}).sort("updated_at", 1):
        costs[(c.get("account_id"), c["sku"])] = c.get("cost_price") or 0
    return costs

async def _pl_dedupe_sku_costs():
    """Normalise legacy account_id values and merge duplicate (account_id, sku)
    rows by keeping the row with the latest updated_at."""
    rows = []
    async for d in db.pl_sku_costs.find({}):
        rows.append(d)
    if not rows:
        return
    groups: Dict[tuple, list] = {}
    for r in rows:
        key = (_pl_norm_acc(r.get("account_id")), r.get("sku"))
        groups.setdefault(key, []).append(r)
    deletes, updates = [], []
    for (norm_acc, _sku), docs in groups.items():
        if len(docs) > 1:
            docs.sort(
                key=lambda d: (
                    d.get("updated_at") or datetime.min.replace(tzinfo=timezone.utc),
                    d["_id"].generation_time,
                ),
                reverse=True,
            )
            for d in docs[1:]:
                deletes.append(d["_id"])
        survivor = docs[0]
        if survivor.get("account_id") != norm_acc:
            updates.append((survivor["_id"], norm_acc))
    if deletes:
        await db.pl_sku_costs.delete_many({"_id": {"$in": deletes}})
        logger.info(f"[pl-migration] removed {len(deletes)} duplicate SKU cost rows")
    for _id, new_acc in updates:
        await db.pl_sku_costs.update_one({"_id": _id}, {"$set": {"account_id": new_acc}})
    if updates:
        logger.info(f"[pl-migration] normalised account_id on {len(updates)} SKU cost rows")

async def pl_resolve_account_filter(account_id: Optional[str]) -> dict:
    """Return mongo filter for an account_id query param.
    None / 'all' / '' -> no filter (all accounts). Otherwise validate account exists."""
    if not account_id or account_id == "all":
        return {}
    oid = pl_oid_or_400(account_id)
    acc = await db.accounts.find_one({"_id": oid})
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"account_id": account_id}

class PLSkuCostIn(BaseModel):
    sku: str
    cost_price: float
    account_id: Optional[str] = None

# ---------- Excel upload ----------
@api.post("/pl/upload")
async def pl_upload(
    account_id: str = Query(..., description="Account this file belongs to"),
    job_id: Optional[str] = Query(None, description="Optional job to mark done after success"),
    source_filename: Optional[str] = Query(
        None,
        description="Filename Meesho proposed (worker uploads only). Stored for audit.",
    ),
    file: UploadFile = File(...),
    user: dict = Depends(get_user_or_worker),
):
    # validate account
    oid = pl_oid_or_400(account_id)
    acc = await db.accounts.find_one({"_id": oid})
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents), sheet_name="Order Payments", header=1)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read 'Order Payments' sheet: {e}")
    df = df[df["Sub Order No"].notna()]
    df = df[df["Sub Order No"].astype(str).str.strip() != ""]
    df = df[df["Sub Order No"].astype(str).str.lower() != "nan"]
    # dedupe within the file: keep last occurrence per sub_order_no (latest snapshot)
    df = df.drop_duplicates(subset=["Sub Order No"], keep="last")

    required = ["Sub Order No", "Supplier SKU", "Order Date", "Live Order Status"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required columns: {missing}")

    # create upload record (so we can roll back later)
    upload_doc = {
        "account_id": account_id,
        "account_name": acc.get("name"),
        "filename": file.filename,
        "source_filename": source_filename or file.filename,
        "uploaded_at": datetime.now(timezone.utc),
        "uploaded_by": user["email"],
        "row_count": int(len(df)),
        "status": "processing",
    }
    up_res = await db.pl_uploads.insert_one(upload_doc)
    upload_id = str(up_res.inserted_id)

    inserted, updated, skipped = 0, 0, 0
    min_date, max_date = None, None
    settlement_total = 0.0

    # pre-fetch existing sub_order_no set to compute insert vs update counts
    existing_keys = set()
    async for d in db.pl_orders.find({"account_id": account_id}, {"_id": 0, "sub_order_no": 1}):
        existing_keys.add(d["sub_order_no"])

    ops = []
    for _, row in df.iterrows():
        try:
            sub_order_no = str(row["Sub Order No"]).strip()
            if not sub_order_no or sub_order_no.lower() == "nan":
                skipped += 1
                continue
            status = pl_normalize_status(row.get("Live Order Status"))
            if not status:
                skipped += 1
                continue
            settlement = pl_safe_float(row.get("Final Settlement Amount", 0))
            commission = abs(pl_safe_float(row.get("Meesho Commission (Incl. GST)", 0)))
            shipping = abs(pl_safe_float(row.get("Shipping Charge (Incl. GST)", 0)))
            tds = abs(pl_safe_float(row.get("TDS", 0)))
            tcs = abs(pl_safe_float(row.get("TCS", 0)))
            recovery = abs(pl_safe_float(row.get("Recovery", 0)))
            return_shipping = abs(pl_safe_float(row.get("Return Shipping Charge (Incl. GST)", 0)))
            compensation = abs(pl_safe_float(row.get("Compensation", 0)))
            order_date_str = str(row.get("Order Date", "")).strip()
            payment_date_v = row.get("Payment Date")
            payment_date_str = (
                str(payment_date_v) if payment_date_v is not None and not (isinstance(payment_date_v, float) and pd.isna(payment_date_v))
                else None
            )
            order_source = (
                str(row.get("Order source", "")).strip()
                if row.get("Order source") is not None and not (isinstance(row.get("Order source"), float) and pd.isna(row.get("Order source")))
                else ""
            )
            payment_status = pl_payment_status(settlement, payment_date_str)

            data = {
                "account_id": account_id,
                "account_name": acc.get("name"),
                "sub_order_no": sub_order_no,
                "sku": str(row.get("Supplier SKU", "")).strip(),
                "product_name": str(row.get("Product Name", "")).strip() if row.get("Product Name") is not None else "",
                "catalog_id": str(row.get("Catalog ID", "")).strip() if row.get("Catalog ID") is not None else "",
                "order_date": order_date_str,
                "order_status": status,
                "net_settlement_amount": settlement,
                "payment_status": payment_status,
                "payment_date": payment_date_str,
                "total_deductions": round(commission + shipping + tds + tcs + recovery, 2),
                "return_charges": round(return_shipping, 2),
                "compensation_amount": round(compensation, 2),
                "order_source": order_source,
                "quantity": int(pl_safe_float(row.get("Quantity", 1))) or 1,
                "last_updated": datetime.now(timezone.utc),
            }
            ops.append(UpdateOne(
                {"account_id": account_id, "sub_order_no": sub_order_no},
                {"$set": data, "$addToSet": {"upload_ids": upload_id}},
                upsert=True,
            ))
            if sub_order_no in existing_keys:
                updated += 1
            else:
                inserted += 1
                existing_keys.add(sub_order_no)

            settlement_total += settlement
            if order_date_str and order_date_str.lower() != "nan":
                if min_date is None or order_date_str < min_date:
                    min_date = order_date_str
                if max_date is None or order_date_str > max_date:
                    max_date = order_date_str
        except Exception as e:
            skipped += 1
            logger.warning(f"[pl/upload] row error: {e}")

    if ops:
        for i in range(0, len(ops), 500):
            await db.pl_orders.bulk_write(ops[i:i+500], ordered=False)

    # ingest Ads Cost sheet (optional)
    ads_inserted = 0
    try:
        ads = pd.read_excel(io.BytesIO(contents), sheet_name="Ads Cost", header=1)
        ads = ads[ads["Campaign ID"].notna()]
        ads_ops = []
        for _, row in ads.iterrows():
            try:
                campaign_id = str(row.get("Campaign ID", "")).strip()
                ded_date = str(row.get("Deduction Date", "")).strip()
                if not campaign_id or campaign_id.lower() == "nan":
                    continue
                doc = {
                    "account_id": account_id,
                    "account_name": acc.get("name"),
                    "campaign_id": campaign_id,
                    "deduction_date": ded_date,
                    "deduction_duration": str(row.get("Deduction Duration", "")).strip(),
                    "ad_cost": pl_safe_float(row.get("Ad Cost", 0)),
                    "credits": pl_safe_float(row.get("Credits / Waivers / Discounts", 0)),
                    "ad_cost_incl_credits": pl_safe_float(row.get("Ad Cost incl. Credits/Waivers/Discounts", 0)),
                    "gst": pl_safe_float(row.get("GST", 0)),
                    "total_ads_cost": pl_safe_float(row.get("Total Ads Cost", 0)),
                    "upload_id": upload_id,
                }
                ads_ops.append(UpdateOne(
                    {"account_id": account_id, "campaign_id": campaign_id, "deduction_date": ded_date},
                    {"$set": doc},
                    upsert=True,
                ))
                ads_inserted += 1
            except Exception as e:
                logger.warning(f"[pl/upload] ads row error: {e}")
        if ads_ops:
            for i in range(0, len(ads_ops), 500):
                await db.pl_ads_cost.bulk_write(ads_ops[i:i+500], ordered=False)
    except Exception as e:
        logger.info(f"[pl/upload] no ads cost sheet or unreadable: {e}")

    await db.pl_uploads.update_one(
        {"_id": up_res.inserted_id},
        {"$set": {
            "status": "done",
            "inserted": inserted, "updated": updated, "skipped": skipped,
            "ads_rows": ads_inserted,
            "settlement_total": round(settlement_total, 2),
            "min_order_date": min_date, "max_order_date": max_date,
            "finished_at": datetime.now(timezone.utc),
        }},
    )

    # If this upload was triggered by a worker job, mark that job done so it
    # surfaces in the Jobs page with the same lifecycle as scrape/label jobs.
    if job_id:
        try:
            await db.jobs.update_one(
                {"_id": pl_oid_or_400(job_id)},
                {"$set": {
                    "status": "done",
                    "finished_at": datetime.now(timezone.utc),
                    "result": {
                        "upload_id": upload_id,
                        "inserted": inserted, "updated": updated, "skipped": skipped,
                        "ads_rows": ads_inserted, "filename": file.filename,
                        "source_filename": source_filename or file.filename,
                        "settlement_total": round(settlement_total, 2),
                        "min_order_date": min_date, "max_order_date": max_date,
                    },
                }},
            )
        except Exception as e:
            logger.warning(f"[pl/upload] job_id update failed: {e}")

        # Also stamp the account so the dashboard can show "Last fetched: …"
        try:
            await db.accounts.update_one(
                {"_id": oid},
                {"$set": {
                    "last_payment_filename": source_filename or file.filename,
                    "last_payment_at": datetime.now(timezone.utc),
                }},
            )
        except Exception as e:
            logger.warning(f"[pl/upload] account stamp failed: {e}")

    return {
        "ok": True, "upload_id": upload_id,
        "inserted": inserted, "updated": updated, "skipped": skipped,
        "ads_rows": ads_inserted,
        "total_processed": int(len(df)),
    }

# ---------- Auto-fetch payment file: enqueue + manual trigger ----------
PL_PERIODS = {"previous_week", "previous_month", "last_payment", "custom"}

class PLFetchNowIn(BaseModel):
    account_id: str
    period: str = "previous_week"

@api.post("/pl/fetch-now")
async def pl_fetch_now(body: PLFetchNowIn, user: dict = Depends(get_current_user)):
    if body.period not in PL_PERIODS:
        raise HTTPException(status_code=400, detail=f"period must be one of {sorted(PL_PERIODS)}")
    oid = pl_oid_or_400(body.account_id)
    acc = await db.accounts.find_one({"_id": oid})
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    # avoid duplicate active jobs for same (account, period)
    dup = await db.jobs.find_one({
        "type": "payments_fetch",
        "account_id": body.account_id,
        "payload.period": body.period,
        "status": {"$in": ["pending", "processing"]},
    })
    if dup:
        return {"ok": True, "job_id": str(dup["_id"]), "status": dup["status"], "duplicate": True}
    res = await db.jobs.insert_one({
        "type": "payments_fetch",
        "status": "pending",
        "account_id": body.account_id,
        "account_name": acc.get("name"),
        "payload": {"period": body.period},
        "created_at": datetime.now(timezone.utc),
        "submitted_by": user.get("email", "user"),
    })
    return {"ok": True, "job_id": str(res.inserted_id), "status": "pending"}

async def enqueue_payments_fetch_jobs(period: str):
    """Cron: enqueue one payments_fetch job per enabled account."""
    if period not in PL_PERIODS:
        logger.warning(f"[scheduler] payments_fetch invalid period={period}")
        return
    try:
        now = datetime.now(timezone.utc)
        count = 0
        async for acc in db.accounts.find({"enabled": True}):
            existing = await db.jobs.find_one({
                "type": "payments_fetch",
                "account_id": str(acc["_id"]),
                "payload.period": period,
                "status": {"$in": ["pending", "processing"]},
            })
            if existing:
                continue
            await db.jobs.insert_one({
                "type": "payments_fetch",
                "status": "pending",
                "account_id": str(acc["_id"]),
                "account_name": acc.get("name"),
                "payload": {"period": period},
                "created_at": now,
                "submitted_by": "scheduler",
            })
            count += 1
        logger.info(f"[scheduler] Enqueued {count} payments_fetch job(s) period={period}")
    except Exception as e:
        logger.exception(f"[scheduler] payments_fetch enqueue failed: {e}")

@api.get("/pl/uploads")
async def pl_list_uploads(
    account_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    q = await pl_resolve_account_filter(account_id)
    cursor = db.pl_uploads.find(q).sort("uploaded_at", -1).limit(200)
    items = []
    async for d in cursor:
        items.append(serialize_doc(d))
    return {"items": items}

@api.delete("/pl/uploads/{upload_id}")
async def pl_delete_upload(upload_id: str, user: dict = Depends(get_current_user)):
    oid = pl_oid_or_400(upload_id)
    up = await db.pl_uploads.find_one({"_id": oid})
    if not up:
        raise HTTPException(status_code=404, detail="Upload not found")
    # pull this upload_id from every order; delete orders whose upload_ids list becomes empty
    await db.pl_orders.update_many(
        {"upload_ids": upload_id},
        {"$pull": {"upload_ids": upload_id}},
    )
    res_del_orders = await db.pl_orders.delete_many({"upload_ids": {"$size": 0}})
    res_del_ads = await db.pl_ads_cost.delete_many({"upload_id": upload_id})
    await db.pl_uploads.delete_one({"_id": oid})
    return {
        "ok": True,
        "orders_deleted": res_del_orders.deleted_count,
        "ads_deleted": res_del_ads.deleted_count,
    }

# ---------- Date range ----------
@api.get("/pl/date-range")
async def pl_date_range(account_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    q = await pl_resolve_account_filter(account_id)
    q.update({"order_date": {"$ne": "", "$exists": True}})
    pipeline = [
        {"$match": q},
        {"$group": {"_id": None,
                    "min_date": {"$min": "$order_date"},
                    "max_date": {"$max": "$order_date"}}},
    ]
    out = await db.pl_orders.aggregate(pipeline).to_list(None)
    if out:
        return {"min_date": out[0].get("min_date") or "", "max_date": out[0].get("max_date") or ""}
    return {"min_date": "", "max_date": ""}

# ---------- Common date filter helper ----------
def _pl_date_query(account_id, start_date, end_date, status_filter=None):
    q = {}
    if status_filter is not None:
        q.update(status_filter)
    if account_id and account_id != "all":
        q["account_id"] = account_id
    if start_date or end_date:
        df = {}
        if start_date:
            df["$gte"] = start_date
        if end_date:
            df["$lte"] = end_date + " 23:59:59"
        if df:
            q["order_date"] = df
    return q

# ---------- Dashboard ----------
@api.get("/pl/dashboard")
async def pl_dashboard(
    account_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    if account_id and account_id != "all":
        await pl_resolve_account_filter(account_id)
    q = _pl_date_query(account_id, start_date, end_date, {"order_status": {"$ne": "CANCELLED"}})
    orders = await db.pl_orders.find(q, {"_id": 0}).to_list(None)
    sku_costs_q = await pl_resolve_account_filter(account_id)
    costs = await _pl_load_costs(sku_costs_q)

    net_profit = 0.0
    return_loss = 0.0
    open_exposure = 0.0
    pending = 0.0
    delivered = shipped = returned = rto = total = 0
    ads_cost_in_period = 0.0

    for o in orders:
        if o["order_status"] == "EXCHANGE":
            continue
        total += 1
        cost = _pl_lookup_cost(costs, o.get("account_id"), o["sku"])
        if o["order_status"] == "DELIVERED" and o["payment_status"] == "PAID":
            net_profit += o["net_settlement_amount"] - cost
            delivered += 1
        elif o["order_status"] == "SHIPPED":
            open_exposure += o["net_settlement_amount"]
            shipped += 1
        if o["order_status"] in ("RTO", "RETURNED"):
            # full formula: |settlement| + return_charges − compensation
            return_loss += abs(o["net_settlement_amount"]) + (o.get("return_charges") or 0) - (o.get("compensation_amount") or 0)
            if o["order_status"] == "RETURNED":
                returned += 1
            else:
                rto += 1
        if o["payment_status"] == "PENDING":
            pending += o["net_settlement_amount"]

    # Ads cost for the same window (best-effort using deduction_date YYYY-MM-DD)
    ads_q = {}
    if account_id and account_id != "all":
        ads_q["account_id"] = account_id
    if start_date or end_date:
        df = {}
        if start_date:
            df["$gte"] = start_date
        if end_date:
            df["$lte"] = end_date
        if df:
            ads_q["deduction_date"] = df
    async for a in db.pl_ads_cost.find(ads_q, {"_id": 0, "total_ads_cost": 1}):
        ads_cost_in_period += abs(a.get("total_ads_cost") or 0)

    net_contribution = net_profit - return_loss
    return {
        "net_realized_profit": round(net_profit, 2),
        "total_return_loss": round(return_loss, 2),
        "net_contribution": round(net_contribution, 2),
        "profit_per_delivered_order": round(net_profit / delivered, 2) if delivered else 0,
        "open_exposure": round(open_exposure, 2),
        "pending_settlement_amount": round(pending, 2),
        "total_ads_cost": round(ads_cost_in_period, 2),
        "net_contribution_after_ads": round(net_contribution - ads_cost_in_period, 2),
        "total_orders": total,
        "delivered_orders": delivered,
        "shipped_orders": shipped,
        "returned_orders": returned,
        "rto_orders": rto,
    }

# ---------- Orders ----------
@api.get("/pl/orders")
async def pl_orders(
    account_id: Optional[str] = None,
    status: Optional[str] = None,
    sku: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(100, le=500),
    skip: int = 0,
    user: dict = Depends(get_current_user),
):
    if account_id and account_id != "all":
        await pl_resolve_account_filter(account_id)
    query = {}
    if account_id and account_id != "all":
        query["account_id"] = account_id
    if status and status != "all":
        query["order_status"] = status.upper()
    if sku:
        query["sku"] = sku
    if q:
        regex = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [{"sub_order_no": regex}, {"sku": regex}, {"product_name": regex}]
    cursor = db.pl_orders.find(query, {"_id": 0}).sort("last_updated", -1).skip(skip).limit(limit)
    items = []
    async for d in cursor:
        if isinstance(d.get("last_updated"), datetime):
            d["last_updated"] = d["last_updated"].isoformat()
        items.append(d)
    total = await db.pl_orders.count_documents(query)
    return {"items": items, "total": total}

@api.get("/pl/orders/export")
async def pl_orders_export(
    account_id: Optional[str] = None,
    status: Optional[str] = None,
    sku: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    query = {}
    if account_id and account_id != "all":
        await pl_resolve_account_filter(account_id)
        query["account_id"] = account_id
    if status and status != "all":
        query["order_status"] = status.upper()
    if sku:
        query["sku"] = sku
    rows = []
    async for d in db.pl_orders.find(query, {"_id": 0, "upload_ids": 0}):
        if isinstance(d.get("last_updated"), datetime):
            d["last_updated"] = d["last_updated"].isoformat()
        rows.append(d)
    if not rows:
        raise HTTPException(status_code=404, detail="No orders to export")
    df = pd.DataFrame(rows)
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Orders")
    out.seek(0)
    fn = f"pl_orders_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        out, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fn}"},
    )

# ---------- SKU Analysis ----------
@api.get("/pl/sku-analysis")
async def pl_sku_analysis(
    account_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    if account_id and account_id != "all":
        await pl_resolve_account_filter(account_id)
    q = _pl_date_query(account_id, start_date, end_date, {"order_status": {"$nin": ["CANCELLED", "EXCHANGE"]}})
    orders = await db.pl_orders.find(q, {"_id": 0}).to_list(None)
    sku_costs_q = await pl_resolve_account_filter(account_id)
    costs = await _pl_load_costs(sku_costs_q)

    sku_data = {}
    for o in orders:
        s = o["sku"]
        if s not in sku_data:
            sku_data[s] = {"units_ordered": 0, "units_delivered": 0, "units_returned": 0,
                           "exposure_units": 0, "profit": 0.0, "loss": 0.0,
                           "product_name": o.get("product_name", "")}
        sku_data[s]["units_ordered"] += 1
        if o["order_status"] == "DELIVERED":
            sku_data[s]["units_delivered"] += 1
            if o["payment_status"] == "PAID":
                cost = _pl_lookup_cost(costs, o.get("account_id"), s)
                sku_data[s]["profit"] += o["net_settlement_amount"] - cost
        if o["order_status"] in ("RTO", "RETURNED"):
            sku_data[s]["units_returned"] += 1
            sku_data[s]["loss"] += abs(o["net_settlement_amount"]) + (o.get("return_charges") or 0) - (o.get("compensation_amount") or 0)
        if o["order_status"] == "SHIPPED":
            sku_data[s]["exposure_units"] += 1

    out = []
    for sku, d in sku_data.items():
        ordered = d["units_ordered"]
        rr = (d["units_returned"] / ordered * 100) if ordered else 0
        ppu = d["profit"] / d["units_delivered"] if d["units_delivered"] else 0
        lpu = d["loss"] / d["units_returned"] if d["units_returned"] else 0
        contrib = d["profit"] - d["loss"]
        if contrib > 0 and rr < 20:
            cls = "Winner"
        elif rr > 40 or contrib < 0:
            cls = "Loser"
        else:
            cls = "Risky"
        out.append({
            "sku": sku, "product_name": d["product_name"],
            "units_ordered": ordered, "units_delivered": d["units_delivered"],
            "units_returned": d["units_returned"], "return_rate": round(rr, 2),
            "net_realized_profit": round(d["profit"], 2),
            "total_return_loss": round(d["loss"], 2),
            "net_sku_contribution": round(contrib, 2),
            "exposure_units": d["exposure_units"],
            "profit_per_delivered_unit": round(ppu, 2),
            "loss_per_returned_unit": round(lpu, 2),
            "classification": cls,
        })
    out.sort(key=lambda x: x["net_sku_contribution"], reverse=True)
    return {"items": out}

# ---------- Exchange Analysis ----------
@api.get("/pl/exchange-analysis")
async def pl_exchange_analysis(
    account_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    if account_id and account_id != "all":
        await pl_resolve_account_filter(account_id)
    q = _pl_date_query(account_id, start_date, end_date, {"order_status": "EXCHANGE"})
    orders = await db.pl_orders.find(q, {"_id": 0}).to_list(None)
    sku_costs_q = await pl_resolve_account_filter(account_id)
    costs = await _pl_load_costs(sku_costs_q)

    total_settlement = 0.0
    total_pl = 0.0
    pos_n = neg_n = 0
    pos_t = neg_t = 0.0
    by_sku = {}
    for o in orders:
        cost = _pl_lookup_cost(costs, o.get("account_id"), o["sku"])
        s = o["net_settlement_amount"]
        pl = s - cost
        total_settlement += s
        total_pl += pl
        if s >= 0:
            pos_n += 1; pos_t += s
        else:
            neg_n += 1; neg_t += s
        d = by_sku.setdefault(o["sku"], {"sku": o["sku"], "count": 0, "total_settlement": 0,
                                         "total_profit_loss": 0, "sku_cost": cost,
                                         "product_name": o.get("product_name", "")})
        d["count"] += 1; d["total_settlement"] += s; d["total_profit_loss"] += pl
    sku_breakdown = sorted(by_sku.values(), key=lambda x: x["total_profit_loss"])
    for o in orders:
        if isinstance(o.get("last_updated"), datetime):
            o["last_updated"] = o["last_updated"].isoformat()
    return {
        "total_exchange_orders": len(orders),
        "total_settlement": round(total_settlement, 2),
        "total_profit_loss": round(total_pl, 2),
        "positive_settlement_count": pos_n,
        "negative_settlement_count": neg_n,
        "positive_settlement_total": round(pos_t, 2),
        "negative_settlement_total": round(neg_t, 2),
        "avg_profit_loss_per_exchange": round(total_pl / len(orders), 2) if orders else 0,
        "sku_breakdown": sku_breakdown,
        "orders": orders,
    }

# ---------- Ad Orders Analysis ----------
@api.get("/pl/ad-orders-analysis")
async def pl_ad_orders_analysis(
    account_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    if account_id and account_id != "all":
        await pl_resolve_account_filter(account_id)
    q = _pl_date_query(account_id, start_date, end_date, {"order_status": {"$nin": ["CANCELLED", "EXCHANGE"]}})
    orders = await db.pl_orders.find(q, {"_id": 0}).to_list(None)
    sku_costs_q = await pl_resolve_account_filter(account_id)
    costs = await _pl_load_costs(sku_costs_q)

    def fresh():
        return {"orders": 0, "delivered": 0, "returned": 0, "rto": 0, "shipped": 0,
                "profit": 0.0, "loss": 0.0, "settlement": 0.0}
    ad = fresh(); norm = fresh()
    for o in orders:
        is_ad = (o.get("order_source") or "").strip().lower() == "ad order"
        bucket = ad if is_ad else norm
        bucket["orders"] += 1
        cost = _pl_lookup_cost(costs, o.get("account_id"), o["sku"])
        if o["order_status"] == "DELIVERED":
            bucket["delivered"] += 1
            if o["payment_status"] == "PAID":
                bucket["profit"] += o["net_settlement_amount"] - cost
                bucket["settlement"] += o["net_settlement_amount"]
        elif o["order_status"] == "SHIPPED":
            bucket["shipped"] += 1
        elif o["order_status"] == "RETURNED":
            bucket["returned"] += 1
            bucket["loss"] += abs(o["net_settlement_amount"]) + (o.get("return_charges") or 0) - (o.get("compensation_amount") or 0)
        elif o["order_status"] == "RTO":
            bucket["rto"] += 1
            bucket["loss"] += abs(o["net_settlement_amount"]) + (o.get("return_charges") or 0) - (o.get("compensation_amount") or 0)

    def metrics(b):
        t = b["orders"]
        rr = ((b["returned"] + b["rto"]) / t * 100) if t else 0
        ppo = b["profit"] / b["delivered"] if b["delivered"] else 0
        return {
            "total_orders": t, "delivered": b["delivered"], "returned": b["returned"],
            "rto": b["rto"], "shipped": b["shipped"], "return_rate": round(rr, 2),
            "total_profit": round(b["profit"], 2), "total_loss": round(b["loss"], 2),
            "net_contribution": round(b["profit"] - b["loss"], 2),
            "profit_per_delivered_order": round(ppo, 2),
            "total_settlement": round(b["settlement"], 2),
        }
    total = len(orders) or 1
    return {
        "ad_orders": metrics(ad),
        "normal_orders": metrics(norm),
        "comparison": {
            "ad_order_percentage": round(ad["orders"] / total * 100, 2),
            "normal_order_percentage": round(norm["orders"] / total * 100, 2),
            "ad_return_rate_vs_normal": round(metrics(ad)["return_rate"] - metrics(norm)["return_rate"], 2),
        },
    }

# ---------- SKU Costs ----------
@api.get("/pl/sku-costs")
async def pl_list_sku_costs(account_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    q = await pl_resolve_account_filter(account_id)
    # cache account_id -> name lookup so we can label rows nicely
    name_cache: Dict[str, str] = {}
    items = []
    async for d in db.pl_sku_costs.find(q, {"_id": 0}).sort("sku", 1):
        aid = d.get("account_id")
        if aid and aid not in name_cache:
            try:
                acc = await db.accounts.find_one({"_id": ObjectId(aid)}, {"_id": 0, "name": 1})
                name_cache[aid] = acc["name"] if acc else aid
            except Exception:
                name_cache[aid] = aid
        d["account_name"] = name_cache.get(aid)  # None -> rendered as "Global" by FE
        if isinstance(d.get("updated_at"), datetime):
            ua = d["updated_at"]
            if ua.tzinfo is None:
                ua = ua.replace(tzinfo=timezone.utc)
            d["updated_at"] = ua.isoformat().replace("+00:00", "Z")
        items.append(d)
    return {"items": items}

@api.post("/pl/sku-costs")
async def pl_upsert_sku_cost(body: PLSkuCostIn, user: dict = Depends(get_current_user)):
    if body.account_id:
        await pl_resolve_account_filter(body.account_id)
    sku = body.sku.strip()
    if not sku:
        raise HTTPException(status_code=400, detail="sku required")
    if body.cost_price < 0:
        raise HTTPException(status_code=400, detail="cost_price must be >= 0")
    norm_acc = _pl_norm_acc(body.account_id)
    key = {"account_id": norm_acc, "sku": sku}
    await db.pl_sku_costs.update_one(
        key, {"$set": {**key, "cost_price": float(body.cost_price), "updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return {"ok": True, "sku": sku, "cost_price": body.cost_price, "account_id": norm_acc}

@api.delete("/pl/sku-costs")
async def pl_delete_sku_cost(
    sku: str = Query(...),
    account_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    res = await db.pl_sku_costs.delete_one({"account_id": _pl_norm_acc(account_id), "sku": sku})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="SKU not found")
    return {"ok": True}

@api.post("/pl/sku-costs/upload-excel")
async def pl_sku_costs_upload(
    account_id: Optional[str] = None,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    if account_id:
        await pl_resolve_account_filter(account_id)
    norm_acc = _pl_norm_acc(account_id)
    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read excel: {e}")
    cols = {c.lower().strip(): c for c in df.columns}
    sku_col = cols.get("sku") or cols.get("supplier sku")
    cost_col = cols.get("cost price") or cols.get("cost_price") or cols.get("cost")
    if not sku_col or not cost_col:
        raise HTTPException(status_code=400, detail="Excel must have columns: SKU, Cost Price")
    inserted = updated = 0
    errors = []
    for idx, row in df.iterrows():
        try:
            sku = str(row[sku_col]).strip()
            cost = pl_safe_float(row[cost_col])
            if not sku or sku.lower() == "nan" or cost <= 0:
                errors.append(f"Row {idx+2}: invalid")
                continue
            existing = await db.pl_sku_costs.find_one({"account_id": norm_acc, "sku": sku})
            await db.pl_sku_costs.update_one(
                {"account_id": norm_acc, "sku": sku},
                {"$set": {"account_id": norm_acc, "sku": sku, "cost_price": cost,
                          "updated_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
            if existing:
                updated += 1
            else:
                inserted += 1
        except Exception as e:
            errors.append(f"Row {idx+2}: {e}")
    return {"ok": True, "inserted": inserted, "updated": updated, "errors": errors[:20]}

@api.get("/pl/missing-sku-costs")
async def pl_missing_sku_costs(account_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    if account_id and account_id != "all":
        await pl_resolve_account_filter(account_id)
    order_q = {} if not account_id or account_id == "all" else {"account_id": account_id}
    order_skus = await db.pl_orders.distinct("sku", order_q)
    cost_q = {} if not account_id or account_id == "all" else {"$or": [{"account_id": account_id}, {"account_id": None}]}
    cost_skus = set()
    async for c in db.pl_sku_costs.find(cost_q, {"_id": 0, "sku": 1}):
        cost_skus.add(c["sku"])
    missing = sorted([s for s in order_skus if s and s not in cost_skus])
    return {"missing_skus": missing, "total_missing": len(missing),
            "total_order_skus": len(order_skus), "total_with_costs": len(cost_skus)}

# --------------------------------------------------------------------------------------
# GST Report + Tax Invoice — auto-fetch & file storage
# --------------------------------------------------------------------------------------
import secrets as _secrets
import shutil as _shutil

UPLOAD_BASE_DIR = Path(os.environ.get("PL_UPLOAD_DIR", str(ROOT_DIR / "uploads")))
GST_DIR = UPLOAD_BASE_DIR / "gst_reports"
TAX_DIR = UPLOAD_BASE_DIR / "tax_invoices"
GST_DIR.mkdir(parents=True, exist_ok=True)
TAX_DIR.mkdir(parents=True, exist_ok=True)

MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]


def _safe_dir(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", (name or "unknown").strip()) or "unknown"


def _mk_share_token() -> tuple[str, datetime]:
    return _secrets.token_urlsafe(24), datetime.now(timezone.utc) + timedelta(days=7)


def _public_share_url(req_base: str, kind: str, doc_id: str, token: str) -> str:
    return f"{req_base.rstrip('/')}/api/pl/{kind}/{doc_id}/public/{token}"


# ---------- helpers shared by GST + Tax endpoints ----------
def _resolve_period_year_month(year: int, month: int) -> tuple[int, int, str]:
    if not (1 <= month <= 12):
        raise HTTPException(status_code=400, detail="month must be 1..12")
    if year < 2020 or year > 2099:
        raise HTTPException(status_code=400, detail="year out of range")
    return year, month, f"{year:04d}-{month:02d}"


def _previous_month(now_utc: datetime) -> tuple[int, int]:
    ist_now = now_utc.astimezone(SCHED_TZ)
    if ist_now.month == 1:
        return ist_now.year - 1, 12
    return ist_now.year, ist_now.month - 1


# =============== GST REPORT ===============
class PLGstFetchIn(BaseModel):
    account_id: str
    year: int
    month: int  # 1..12


@api.post("/pl/gst-report/fetch-now")
async def pl_gst_fetch_now(body: PLGstFetchIn, user: dict = Depends(get_current_user)):
    year, month, period = _resolve_period_year_month(body.year, body.month)
    oid = pl_oid_or_400(body.account_id)
    acc = await db.accounts.find_one({"_id": oid})
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    # block if already fetched and available=true
    existing = await db.pl_gst_reports.find_one({
        "account_id": body.account_id, "year": year, "month": month,
        "available": True,
    })
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"GST report already fetched for {acc.get('name')} {period}. "
                   f"Download the existing file or delete it first.",
        )
    dup = await db.jobs.find_one({
        "type": "gst_report_fetch",
        "account_id": body.account_id,
        "payload.year": year, "payload.month": month,
        "status": {"$in": ["pending", "processing"]},
    })
    if dup:
        return {"ok": True, "job_id": str(dup["_id"]), "status": dup["status"], "duplicate": True}
    res = await db.jobs.insert_one({
        "type": "gst_report_fetch", "status": "pending",
        "account_id": body.account_id, "account_name": acc.get("name"),
        "payload": {"year": year, "month": month, "period": period},
        "created_at": datetime.now(timezone.utc),
        "submitted_by": user.get("email", "user"),
    })
    return {"ok": True, "job_id": str(res.inserted_id), "status": "pending"}


@api.post("/pl/gst-report/upload")
async def pl_gst_upload(
    account_id: str = Query(...),
    job_id: str = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    original_filename: str = Query(""),
    available: str = Query("true"),
    reason: str = Query(""),
    file: Optional[UploadFile] = File(None),
    user: dict = Depends(get_user_or_worker),
):
    """Worker pushes the downloaded GST zip here. If available=false the
    worker only sends the no-data marker."""
    is_available = available.lower() in ("1", "true", "yes")
    oid = pl_oid_or_400(account_id)
    acc = await db.accounts.find_one({"_id": oid})
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    doc = {
        "account_id": account_id,
        "account_name": acc.get("name"),
        "year": year, "month": month,
        "period": f"{year:04d}-{month:02d}",
        "original_filename": original_filename,
        "available": is_available,
        "reason": reason,
        "fetched_at": datetime.now(timezone.utc),
        "fetched_by": user.get("email", "worker"),
        "job_id": job_id,
    }

    if is_available:
        if not file:
            raise HTTPException(status_code=400, detail="file missing for available=true")
        target_dir = GST_DIR / _safe_dir(acc.get("name") or "unknown") / f"{year:04d}-{month:02d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{_safe_dir(acc.get('name') or 'acct')}_{year:04d}-{month:02d}_GST_REPORT.zip"
        target_path = target_dir / stored_name
        with open(target_path, "wb") as out:
            _shutil.copyfileobj(file.file, out)
        doc.update({
            "stored_filename": stored_name,
            "file_path": str(target_path),
            "size_bytes": target_path.stat().st_size,
        })

    res = await db.pl_gst_reports.insert_one(doc)
    rec_id = str(res.inserted_id)

    # mark the job
    try:
        await db.jobs.update_one(
            {"_id": pl_oid_or_400(job_id)},
            {"$set": {
                "status": "done",
                "finished_at": datetime.now(timezone.utc),
                "result": {
                    "gst_id": rec_id,
                    "available": is_available,
                    "reason": reason,
                    "stored_filename": doc.get("stored_filename"),
                    "source_filename": original_filename,
                },
            }},
        )
    except Exception as e:
        logger.warning(f"[gst-report/upload] job update failed: {e}")

    return {"ok": True, "id": rec_id, "available": is_available,
            "stored_filename": doc.get("stored_filename")}


@api.get("/pl/gst-report")
async def pl_gst_list(
    account_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    q = await pl_resolve_account_filter(account_id)
    cursor = db.pl_gst_reports.find(q).sort("fetched_at", -1).limit(200)
    items = []
    async for d in cursor:
        items.append(serialize_doc(d))
    return {"items": items}


@api.delete("/pl/gst-report/{rec_id}")
async def pl_gst_delete(rec_id: str, user: dict = Depends(get_current_user)):
    oid = pl_oid_or_400(rec_id)
    rec = await db.pl_gst_reports.find_one({"_id": oid})
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")
    fp = rec.get("file_path")
    if fp:
        try:
            Path(fp).unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"[gst-report/delete] file unlink failed: {e}")
    await db.pl_gst_reports.delete_one({"_id": oid})
    return {"ok": True}


@api.get("/pl/gst-report/{rec_id}/download")
async def pl_gst_download(rec_id: str, user: dict = Depends(get_current_user)):
    oid = pl_oid_or_400(rec_id)
    rec = await db.pl_gst_reports.find_one({"_id": oid})
    if not rec or not rec.get("available"):
        raise HTTPException(status_code=404, detail="No file for this record")
    fp = rec.get("file_path")
    if not fp or not Path(fp).exists():
        raise HTTPException(status_code=410, detail="File no longer on disk")
    return FileResponse(fp, filename=rec.get("stored_filename") or Path(fp).name,
                        media_type="application/zip")


@api.post("/pl/gst-report/{rec_id}/share")
async def pl_gst_share(rec_id: str, request: Request, user: dict = Depends(get_current_user)):
    oid = pl_oid_or_400(rec_id)
    rec = await db.pl_gst_reports.find_one({"_id": oid})
    if not rec or not rec.get("available"):
        raise HTTPException(status_code=404, detail="No file for this record")
    token, expires = _mk_share_token()
    await db.pl_gst_reports.update_one(
        {"_id": oid},
        {"$set": {"share_token": token, "share_token_expires_at": expires}},
    )
    base = str(request.base_url).rstrip("/")
    return {"ok": True, "url": _public_share_url(base, "gst-report", rec_id, token),
            "expires_at": expires.isoformat().replace("+00:00", "Z")}


@api.get("/pl/gst-report/{rec_id}/public/{token}")
async def pl_gst_public(rec_id: str, token: str):
    """Public download — used by 3rd parties (CA etc) without auth."""
    oid = pl_oid_or_400(rec_id)
    rec = await db.pl_gst_reports.find_one({"_id": oid})
    if (not rec or rec.get("share_token") != token
            or not rec.get("available")):
        raise HTTPException(status_code=404, detail="invalid or expired link")
    exp = _as_aware_utc(rec.get("share_token_expires_at"))
    if exp and exp < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="link expired")
    fp = rec.get("file_path")
    if not fp or not Path(fp).exists():
        raise HTTPException(status_code=410, detail="file missing")
    return FileResponse(fp, filename=rec.get("stored_filename") or Path(fp).name,
                        media_type="application/zip")


# =============== TAX INVOICE ===============
class PLTaxInvoiceFetchIn(BaseModel):
    account_id: str
    year: int
    month: int  # 1..12


@api.post("/pl/tax-invoice/fetch-now")
async def pl_tax_fetch_now(body: PLTaxInvoiceFetchIn, user: dict = Depends(get_current_user)):
    year, month, period = _resolve_period_year_month(body.year, body.month)
    oid = pl_oid_or_400(body.account_id)
    acc = await db.accounts.find_one({"_id": oid})
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    existing = await db.pl_tax_invoices.find_one({
        "account_id": body.account_id, "year": year, "month": month,
        "available": True,
    })
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Tax invoice already fetched for {acc.get('name')} {period}. "
                   f"Download the existing file or delete it first.",
        )
    dup = await db.jobs.find_one({
        "type": "tax_invoice_fetch",
        "account_id": body.account_id,
        "payload.year": year, "payload.month": month,
        "status": {"$in": ["pending", "processing"]},
    })
    if dup:
        return {"ok": True, "job_id": str(dup["_id"]), "status": dup["status"], "duplicate": True}
    res = await db.jobs.insert_one({
        "type": "tax_invoice_fetch", "status": "pending",
        "account_id": body.account_id, "account_name": acc.get("name"),
        "payload": {"year": year, "month": month, "period": period},
        "created_at": datetime.now(timezone.utc),
        "submitted_by": user.get("email", "user"),
    })
    return {"ok": True, "job_id": str(res.inserted_id), "status": "pending"}


@api.post("/pl/tax-invoice/upload")
async def pl_tax_upload(
    account_id: str = Query(...),
    job_id: str = Query(...),
    year: int = Query(...),
    month: int = Query(...),
    from_date: str = Query(""),
    to_date: str = Query(""),
    original_filename: str = Query(""),
    available: str = Query("true"),
    reason: str = Query(""),
    file: Optional[UploadFile] = File(None),
    user: dict = Depends(get_user_or_worker),
):
    is_available = available.lower() in ("1", "true", "yes")
    oid = pl_oid_or_400(account_id)
    acc = await db.accounts.find_one({"_id": oid})
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")

    doc = {
        "account_id": account_id,
        "account_name": acc.get("name"),
        "year": year, "month": month,
        "period": f"{year:04d}-{month:02d}",
        "from_date": from_date, "to_date": to_date,
        "original_filename": original_filename,
        "available": is_available,
        "reason": reason,
        "fetched_at": datetime.now(timezone.utc),
        "fetched_by": user.get("email", "worker"),
        "job_id": job_id,
    }

    if is_available:
        if not file:
            raise HTTPException(status_code=400, detail="file missing for available=true")
        target_dir = TAX_DIR / _safe_dir(acc.get("name") or "unknown") / f"{year:04d}-{month:02d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{_safe_dir(acc.get('name') or 'acct')}_{year:04d}-{month:02d}_TAX_INVOICE.xlsx"
        target_path = target_dir / stored_name
        with open(target_path, "wb") as out:
            _shutil.copyfileobj(file.file, out)
        doc.update({
            "stored_filename": stored_name,
            "file_path": str(target_path),
            "size_bytes": target_path.stat().st_size,
        })

    res = await db.pl_tax_invoices.insert_one(doc)
    rec_id = str(res.inserted_id)

    try:
        await db.jobs.update_one(
            {"_id": pl_oid_or_400(job_id)},
            {"$set": {
                "status": "done",
                "finished_at": datetime.now(timezone.utc),
                "result": {
                    "tax_id": rec_id,
                    "available": is_available,
                    "reason": reason,
                    "stored_filename": doc.get("stored_filename"),
                    "source_filename": original_filename,
                },
            }},
        )
    except Exception as e:
        logger.warning(f"[tax-invoice/upload] job update failed: {e}")

    return {"ok": True, "id": rec_id, "available": is_available,
            "stored_filename": doc.get("stored_filename")}


@api.get("/pl/tax-invoice")
async def pl_tax_list(
    account_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    q = await pl_resolve_account_filter(account_id)
    cursor = db.pl_tax_invoices.find(q).sort("fetched_at", -1).limit(200)
    items = []
    async for d in cursor:
        items.append(serialize_doc(d))
    return {"items": items}


@api.delete("/pl/tax-invoice/{rec_id}")
async def pl_tax_delete(rec_id: str, user: dict = Depends(get_current_user)):
    oid = pl_oid_or_400(rec_id)
    rec = await db.pl_tax_invoices.find_one({"_id": oid})
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")
    fp = rec.get("file_path")
    if fp:
        try:
            Path(fp).unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"[tax-invoice/delete] file unlink failed: {e}")
    await db.pl_tax_invoices.delete_one({"_id": oid})
    return {"ok": True}


@api.get("/pl/tax-invoice/{rec_id}/download")
async def pl_tax_download(rec_id: str, user: dict = Depends(get_current_user)):
    oid = pl_oid_or_400(rec_id)
    rec = await db.pl_tax_invoices.find_one({"_id": oid})
    if not rec or not rec.get("available"):
        raise HTTPException(status_code=404, detail="No file for this record")
    fp = rec.get("file_path")
    if not fp or not Path(fp).exists():
        raise HTTPException(status_code=410, detail="File no longer on disk")
    return FileResponse(
        fp, filename=rec.get("stored_filename") or Path(fp).name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@api.post("/pl/tax-invoice/{rec_id}/share")
async def pl_tax_share(rec_id: str, request: Request, user: dict = Depends(get_current_user)):
    oid = pl_oid_or_400(rec_id)
    rec = await db.pl_tax_invoices.find_one({"_id": oid})
    if not rec or not rec.get("available"):
        raise HTTPException(status_code=404, detail="No file for this record")
    token, expires = _mk_share_token()
    await db.pl_tax_invoices.update_one(
        {"_id": oid},
        {"$set": {"share_token": token, "share_token_expires_at": expires}},
    )
    base = str(request.base_url).rstrip("/")
    return {"ok": True, "url": _public_share_url(base, "tax-invoice", rec_id, token),
            "expires_at": expires.isoformat().replace("+00:00", "Z")}


@api.get("/pl/tax-invoice/{rec_id}/public/{token}")
async def pl_tax_public(rec_id: str, token: str):
    oid = pl_oid_or_400(rec_id)
    rec = await db.pl_tax_invoices.find_one({"_id": oid})
    if (not rec or rec.get("share_token") != token
            or not rec.get("available")):
        raise HTTPException(status_code=404, detail="invalid or expired link")
    exp = _as_aware_utc(rec.get("share_token_expires_at"))
    if exp and exp < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="link expired")
    fp = rec.get("file_path")
    if not fp or not Path(fp).exists():
        raise HTTPException(status_code=410, detail="file missing")
    return FileResponse(
        fp, filename=rec.get("stored_filename") or Path(fp).name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------- Cron: enqueue daily 7th–15th, fetches previous month ----------
async def enqueue_gst_and_tax_jobs():
    """Runs daily 02:00 IST. Days 7–15 of month: for every enabled account,
    if no available=true record exists for the previous month, enqueue
    one gst_report_fetch and one tax_invoice_fetch."""
    now = datetime.now(timezone.utc)
    ist_now = now.astimezone(SCHED_TZ)
    if not (7 <= ist_now.day <= 15):
        return
    year, month = _previous_month(now)
    period = f"{year:04d}-{month:02d}"
    enq_gst = enq_tax = 0
    try:
        async for acc in db.accounts.find({"enabled": True}):
            acc_id = str(acc["_id"])
            # GST
            done = await db.pl_gst_reports.find_one(
                {"account_id": acc_id, "year": year, "month": month, "available": True})
            active = await db.jobs.find_one({
                "type": "gst_report_fetch", "account_id": acc_id,
                "payload.year": year, "payload.month": month,
                "status": {"$in": ["pending", "processing"]},
            })
            if not done and not active:
                await db.jobs.insert_one({
                    "type": "gst_report_fetch", "status": "pending",
                    "account_id": acc_id, "account_name": acc.get("name"),
                    "payload": {"year": year, "month": month, "period": period},
                    "created_at": now, "submitted_by": "scheduler",
                })
                enq_gst += 1
            # Tax Invoice
            done = await db.pl_tax_invoices.find_one(
                {"account_id": acc_id, "year": year, "month": month, "available": True})
            active = await db.jobs.find_one({
                "type": "tax_invoice_fetch", "account_id": acc_id,
                "payload.year": year, "payload.month": month,
                "status": {"$in": ["pending", "processing"]},
            })
            if not done and not active:
                await db.jobs.insert_one({
                    "type": "tax_invoice_fetch", "status": "pending",
                    "account_id": acc_id, "account_name": acc.get("name"),
                    "payload": {"year": year, "month": month, "period": period},
                    "created_at": now, "submitted_by": "scheduler",
                })
                enq_tax += 1
        logger.info(f"[scheduler] gst/tax enqueue period={period} gst={enq_gst} tax={enq_tax}")
    except Exception as e:
        logger.exception(f"[scheduler] gst/tax enqueue failed: {e}")


# --------------------------------------------------------------------------------------
# Health + Mount
# --------------------------------------------------------------------------------------
@api.get("/health")
async def health():
    return {"ok": True}

app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"], allow_headers=["*"],
)

app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"], allow_headers=["*"],
)
