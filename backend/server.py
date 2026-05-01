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
    debug_port: int
    profile_dir: str
    pending_url: Optional[str] = None
    ready_url: Optional[str] = None
    enabled: bool = True

class AccountUpdate(BaseModel):
    name: Optional[str] = None
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
            out[k] = v.isoformat()
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
    # alerts run every 30 minutes regardless of toggles
    scheduler.add_job(
        detect_alerts,
        CronTrigger(minute="*/30", timezone=SCHED_TZ),
        id="alerts_check", replace_existing=True,
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
    except Exception as e:
        logger.warning(f"Index creation issue: {e}")

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
