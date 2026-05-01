"""
Meesho Label-Download worker — EC2 Ubuntu.

Polls the `jobs` collection for jobs of type "label_download" and dispatches
them to the right Chrome instance based on the job's `account_id`.

Each `accounts` document carries:
  {
    _id, name, slug, debug_port (e.g. 9222),
    profile_dir (e.g. /home/ubuntu/chrome-profile1),
    pending_url, ready_url,    # supplier-portal URLs (per-account)
    enabled,
  }

For each account you must launch its Chrome separately:
  google-chrome --remote-debugging-port=<port> --user-data-dir=<profile_dir>

`start_chromes.sh` does this automatically by reading enabled accounts from
MongoDB.  This worker assumes the Chrome is already running on the configured
port and connects to it via CDP.

If the port isn't reachable, the job is failed with a clear error message
("Chrome not running on port 9222 for account 'Main' — run start_chromes.sh").
"""
import os
import time
import traceback
import urllib.request
import urllib.error
from datetime import datetime, timezone

from pymongo import MongoClient
from bson import ObjectId

import labels  # the user's labels.py — we override its globals per-job

MONGO_URI = os.environ.get("MESHO_MONGO_URI", "mongodb://43.205.229.129:27017/")
DB_NAME = os.environ.get("MESHO_DB_NAME", "meesho")
POLL = int(os.environ.get("MESHO_POLL_SECONDS", "5"))

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
jobs_col = db["jobs"]
accounts_col = db["accounts"]


def chrome_alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3):
            return True
    except (urllib.error.URLError, ConnectionError, OSError):
        return False


def get_account(job) -> dict:
    aid = job.get("account_id")
    if not aid:
        raise ValueError("label_download job has no account_id")
    try:
        oid = ObjectId(aid)
    except Exception:
        raise ValueError(f"invalid account_id: {aid}")
    acc = accounts_col.find_one({"_id": oid})
    if not acc:
        raise ValueError(f"account not found: {aid}")
    if not acc.get("enabled", True):
        raise ValueError(f"account '{acc.get('name')}' is disabled")
    if not acc.get("debug_port"):
        raise ValueError(f"account '{acc.get('name')}' has no debug_port")
    return acc


def run_label_for_account(acc: dict):
    port = int(acc["debug_port"])
    if not chrome_alive(port):
        raise RuntimeError(
            f"Chrome not running on port {port} for account "
            f"'{acc.get('name')}'.  Start it with:\n"
            f"  google-chrome --remote-debugging-port={port} "
            f"--user-data-dir={acc.get('profile_dir', '/home/ubuntu/chrome-profile')}\n"
            f"or run ./start_chromes.sh"
        )

    # ── derive per-account supplier URLs ────────────────────────────────────
    # Account `name` IS the Meesho URL suffix (e.g. 'hrbib', 'uobfs').
    # We always derive the URLs from the name so adding a new account just
    # works.  An explicit pending_url / ready_url on the account doc still
    # wins (escape hatch).
    suffix = (acc.get("name") or "").strip()
    derived_pending = (
        f"https://supplier.meesho.com/panel/v3/new/fulfillment/{suffix}/orders/pending"
        if suffix else None
    )
    derived_ready = (
        f"https://supplier.meesho.com/panel/v3/new/fulfillment/{suffix}/orders/ready-to-ship"
        if suffix else None
    )
    pending_url = acc.get("pending_url") or derived_pending
    ready_url = acc.get("ready_url") or derived_ready

    if not pending_url or not ready_url:
        raise RuntimeError(
            f"account '{acc.get('name')}' has no name suffix and no "
            f"pending_url/ready_url — cannot derive Meesho URLs."
        )

    # Override the labels module globals for this run
    labels.DEBUG_PORT = f"http://127.0.0.1:{port}"
    labels.PENDING_URL = pending_url
    labels.READY_URL = ready_url

    print(
        f"[label_worker] account='{acc.get('name')}' port={port} "
        f"→ pending={pending_url}"
    )
    labels.main()


def loop():
    print(f"🚀 Label worker (EC2) — Mongo: {MONGO_URI} db={DB_NAME}")
    while True:
        job = jobs_col.find_one_and_update(
            {"status": "pending", "type": "label_download"},
            {"$set": {"status": "processing", "started_at": datetime.now(timezone.utc)}},
            sort=[("created_at", 1)],
        )
        if not job:
            time.sleep(POLL)
            continue

        print(f"\n=== label job {job.get('_id')} ===")
        try:
            acc = get_account(job)
            run_label_for_account(acc)
            jobs_col.update_one(
                {"_id": job["_id"]},
                {"$set": {
                    "status": "done",
                    "finished_at": datetime.now(timezone.utc),
                    "account_name": acc.get("name"),
                }},
            )
            accounts_col.update_one(
                {"_id": acc["_id"]},
                {"$set": {"last_used_at": datetime.now(timezone.utc), "last_status": "ok"}},
            )
            print("✅ done")
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            print(f"❌ {err}")
            traceback.print_exc()
            jobs_col.update_one(
                {"_id": job["_id"]},
                {"$set": {
                    "status": "failed",
                    "finished_at": datetime.now(timezone.utc),
                    "error": err[:1500],
                }},
            )
            try:
                aid = job.get("account_id")
                if aid:
                    accounts_col.update_one(
                        {"_id": ObjectId(aid)},
                        {"$set": {"last_status": f"failed: {err[:200]}"}},
                    )
            except Exception:
                pass


if __name__ == "__main__":
    loop()
