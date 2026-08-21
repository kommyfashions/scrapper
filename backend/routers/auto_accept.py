"""Auto-accept labels (`/api/auto-accept/...`).

Polling-based: a scheduler tick runs every N minutes; for each enabled
account whose `auto_accept_enabled=True` and whose last successful
`accept_labels` run is older than the account's `auto_accept_interval_minutes`,
we enqueue an `accept_labels` job for the EC2 scraper. The scraper opens
Meesho Orders and clicks Accept on every pending order — NO download.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/auto-accept", tags=["auto-accept"])

_db = None
DEFAULT_INTERVAL_MIN = 15


def configure(db):
    global _db
    _db = db


def get_db():
    if _db is None:
        raise RuntimeError("auto_accept router not configured")
    return _db


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception:
        raise HTTPException(status_code=400, detail=f"invalid id: {s}")


def _iso(d):
    if isinstance(d, datetime):
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.isoformat().replace("+00:00", "Z")
    return None


class SettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    interval_minutes: Optional[int] = Field(None, ge=5, le=240)


@router.get("/settings")
async def list_settings():
    db = get_db()
    out = []
    async for a in db.accounts.find({}, {"_id": 1, "name": 1, "alias": 1,
                                          "enabled": 1,
                                          "auto_accept_enabled": 1,
                                          "auto_accept_interval_minutes": 1}):
        last = await db.jobs.find_one(
            {"type": "accept_labels", "account_id": str(a["_id"]),
             "status": {"$in": ["done", "failed"]}},
            sort=[("finished_at", -1)],
        )
        out.append({
            "account_id": str(a["_id"]),
            "account_name": a.get("name"),
            "account_alias": a.get("alias"),
            "account_enabled": bool(a.get("enabled", True)),
            "auto_accept_enabled": bool(a.get("auto_accept_enabled", False)),
            "interval_minutes": int(a.get("auto_accept_interval_minutes")
                                    or DEFAULT_INTERVAL_MIN),
            "last_run": {
                "status": last.get("status") if last else None,
                "finished_at": _iso(last.get("finished_at")) if last else None,
                "accepted_count": int(
                    (last.get("result") or {}).get("accepted_count") or 0
                ) if last else 0,
            },
        })
    return {"items": out}


@router.put("/settings/{account_id}")
async def update_settings(account_id: str, body: SettingsUpdate):
    db = get_db()
    changes: Dict[str, Any] = {}
    if body.enabled is not None:
        changes["auto_accept_enabled"] = bool(body.enabled)
    if body.interval_minutes is not None:
        changes["auto_accept_interval_minutes"] = int(body.interval_minutes)
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = await db.accounts.update_one(
        {"_id": _oid(account_id)}, {"$set": changes})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"ok": True, "updated": changes}


@router.post("/run-now/{account_id}")
async def run_now(account_id: str):
    db = get_db()
    acc = await db.accounts.find_one({"_id": _oid(account_id)})
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    existing = await db.jobs.find_one({
        "type": "accept_labels", "account_id": account_id,
        "status": {"$in": ["pending", "processing"]},
    })
    if existing:
        return {"ok": True, "already_queued": True,
                "job_id": str(existing["_id"])}
    res = await db.jobs.insert_one({
        "type": "accept_labels",
        "status": "pending",
        "account_id": account_id,
        "account_name": acc.get("name"),
        "submitted_by": "dashboard",
        "created_at": datetime.now(timezone.utc),
        "payload": {},
    })
    return {"ok": True, "already_queued": False, "job_id": str(res.inserted_id)}


def _serialize_job(j: dict) -> dict:
    r = j.get("result") or {}
    return {
        "id": str(j["_id"]),
        "status": j.get("status"),
        "account_id": j.get("account_id"),
        "account_name": j.get("account_name"),
        "submitted_by": j.get("submitted_by"),
        "created_at": _iso(j.get("created_at")),
        "started_at": _iso(j.get("started_at")),
        "finished_at": _iso(j.get("finished_at")),
        "error": j.get("error"),
        "result": {
            "accepted_count": int(r.get("accepted_count") or 0),
            "already_accepted_count": int(r.get("already_accepted_count") or 0),
            "failed_count": int(r.get("failed_count") or 0),
        },
    }


@router.get("/history")
async def history(
    limit: int = Query(50, ge=1, le=500),
    account_id: Optional[str] = None,
    status: Optional[str] = Query(
        None, pattern="^(pending|processing|done|failed)$"),
):
    db = get_db()
    q: Dict[str, Any] = {"type": "accept_labels"}
    if account_id:
        q["account_id"] = account_id
    if status:
        q["status"] = status
    items = [_serialize_job(d) async for d in
             db.jobs.find(q).sort("created_at", -1).limit(limit)]
    return {"items": items}


async def scheduler_tick(db):
    """Called by APScheduler every few minutes. Enqueues accept_labels for
    every account whose auto_accept is on and whose interval has elapsed."""
    now = datetime.now(timezone.utc)
    enqueued: List[str] = []
    async for acc in db.accounts.find({
        "enabled": True,
        "auto_accept_enabled": True,
    }):
        aid = str(acc["_id"])
        interval = int(acc.get("auto_accept_interval_minutes")
                       or DEFAULT_INTERVAL_MIN)
        # skip if job already in flight
        pending = await db.jobs.find_one({
            "type": "accept_labels", "account_id": aid,
            "status": {"$in": ["pending", "processing"]},
        })
        if pending:
            continue
        # respect the interval since last run
        last = await db.jobs.find_one(
            {"type": "accept_labels", "account_id": aid,
             "status": {"$in": ["done", "failed"]}},
            sort=[("finished_at", -1)],
        )
        if last and isinstance(last.get("finished_at"), datetime):
            elapsed = (now - last["finished_at"].replace(
                tzinfo=timezone.utc if last["finished_at"].tzinfo is None
                else last["finished_at"].tzinfo)).total_seconds() / 60.0
            if elapsed < interval:
                continue
        await db.jobs.insert_one({
            "type": "accept_labels",
            "status": "pending",
            "account_id": aid,
            "account_name": acc.get("name"),
            "submitted_by": "scheduler",
            "created_at": now,
            "payload": {},
        })
        enqueued.append(aid)
    return enqueued
