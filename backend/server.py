from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Any, Dict

import bcrypt
import jwt
from bson import ObjectId
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, Query
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

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

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("dashboard")

app = FastAPI(title="Meesho Seller Dashboard API")
api = APIRouter(prefix="/api")

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
        "sub": user_id,
        "email": email,
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

# --------------------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------------------
MEESHO_PRODUCT_URL_RE = re.compile(r"https?://(www\.)?meesho\.com/.+/p/([A-Za-z0-9_-]+)/?", re.IGNORECASE)

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

# --------------------------------------------------------------------------------------
# Startup
# --------------------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    try:
        await db.users.create_index("email", unique=True)
        await db.jobs.create_index("status")
        await db.jobs.create_index("created_at")
        await db.products.create_index("product_id", unique=False)
    except Exception as e:
        logger.warning(f"Index creation issue: {e}")

    existing = await db.users.find_one({"email": ADMIN_EMAIL})
    if not existing:
        await db.users.insert_one({
            "email": ADMIN_EMAIL,
            "password_hash": hash_password(ADMIN_PASSWORD),
            "name": "Admin",
            "role": "admin",
            "created_at": datetime.now(timezone.utc),
        })
        logger.info(f"Seeded admin user: {ADMIN_EMAIL}")
    elif not verify_password(ADMIN_PASSWORD, existing["password_hash"]):
        await db.users.update_one(
            {"email": ADMIN_EMAIL},
            {"$set": {"password_hash": hash_password(ADMIN_PASSWORD)}},
        )
        logger.info("Admin password updated from env.")

@app.on_event("shutdown")
async def shutdown():
    client.close()

# --------------------------------------------------------------------------------------
# Auth endpoints
# --------------------------------------------------------------------------------------
@api.post("/auth/login", response_model=TokenOut)
async def login(body: LoginIn):
    email = body.email.strip().lower()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_token(str(user["_id"]), email)
    return TokenOut(
        access_token=token,
        user={"id": str(user["_id"]), "email": email, "name": user.get("name", "")},
    )

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
        "product_url": url,
        "product_id": pid,
        "status": "pending",
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
            "product_url": u,
            "product_id": pid,
            "status": "pending",
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
    q: Optional[str] = None,
    limit: int = Query(50, le=200),
    skip: int = 0,
    user: dict = Depends(get_current_user),
):
    query: dict = {}
    if status and status != "all":
        query["status"] = status
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
    # Stuck = processing older than threshold, OR processing without started_at
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
    # also handle processing without started_at (legacy)
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
            {"product_id": regex},
            {"product_url": regex},
            {"seller.name": regex},
        ]
    sort_field = sort if sort in ("updated_at", "total_reviews", "product_id") else "updated_at"
    direction = -1 if order == "desc" else 1
    cursor = db.products.find(query, {"reviews": 0}).sort(sort_field, direction).skip(skip).limit(limit)
    items = []
    async for d in cursor:
        d = serialize_doc(d)
        d["avg_rating"] = avg_rating_from_distribution(d.get("rating_distribution"))
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
    return out

# --------------------------------------------------------------------------------------
# Analytics
# --------------------------------------------------------------------------------------
@api.get("/analytics/overview")
async def analytics_overview(user: dict = Depends(get_current_user)):
    total_products = await db.products.count_documents({})
    # total reviews + global rating distribution
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

    # top sellers by total_reviews
    top_sellers_pipe = [
        {"$group": {"_id": "$seller.name", "products": {"$sum": 1}, "reviews": {"$sum": "$total_reviews"}}},
        {"$match": {"_id": {"$ne": None}}},
        {"$sort": {"reviews": -1}},
        {"$limit": 10},
    ]
    top_sellers = []
    async for row in db.products.aggregate(top_sellers_pipe):
        top_sellers.append({"seller": row["_id"], "products": row["products"], "reviews": row["reviews"]})

    # jobs today
    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    jobs_today = await db.jobs.count_documents({"created_at": {"$gte": start_of_day}})

    # job status breakdown
    status_breakdown = {"pending": 0, "processing": 0, "done": 0, "failed": 0}
    async for row in db.jobs.aggregate([{"$group": {"_id": "$status", "count": {"$sum": 1}}}]):
        if row["_id"] in status_breakdown:
            status_breakdown[row["_id"]] = row["count"]

    # review volume by day (last 30 days) — based on reviews array created_at
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    volume_pipe = [
        {"$unwind": "$reviews"},
        {"$addFields": {
            "review_dt": {
                "$dateFromString": {
                    "dateString": "$reviews.created_at",
                    "onError": None,
                    "onNull": None,
                }
            }
        }},
        {"$match": {"review_dt": {"$gte": thirty_days_ago}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$review_dt"}},
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
    ]
    review_volume = []
    try:
        async for row in db.products.aggregate(volume_pipe):
            review_volume.append({"date": row["_id"], "count": row["count"]})
    except Exception as e:
        logger.warning(f"Review volume aggregation failed: {e}")

    # most helpful reviews (top 10)
    helpful_pipe = [
        {"$unwind": "$reviews"},
        {"$match": {"reviews.helpful": {"$gt": 0}}},
        {"$sort": {"reviews.helpful": -1}},
        {"$limit": 10},
        {"$project": {
            "_id": 0,
            "product_id": 1,
            "seller": "$seller.name",
            "review": "$reviews",
        }},
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
# Mount
# --------------------------------------------------------------------------------------
@api.get("/health")
async def health():
    return {"ok": True}

app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
