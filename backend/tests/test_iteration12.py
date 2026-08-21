"""Iteration 12 tests: Live Inventory Sync + Auto-Accept Labels."""
import os
import io
import pytest
import requests
from datetime import datetime, timezone
from bson import ObjectId
from pymongo import MongoClient

def _read_env(path, key):
    try:
        for line in open(path):
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return None


BASE = (os.environ.get("REACT_APP_BACKEND_URL")
        or _read_env("/app/frontend/.env", "REACT_APP_BACKEND_URL")).rstrip("/")
MONGO = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "meesho")


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": "admin@meesho-dash.local",
                            "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"] if "access_token" in r.json() else r.json().get("token")


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO)[DB_NAME]


@pytest.fixture(scope="module")
def account_ids(db):
    ids = [str(a["_id"]) for a in db.accounts.find({}, {"_id": 1})]
    assert len(ids) >= 1, "need at least one account"
    return ids


# ---------------- inventory-sync ----------------
class TestInventorySync:
    def test_history(self, h):
        r = requests.get(f"{BASE}/api/inventory-sync/history", headers=h)
        assert r.status_code == 200
        j = r.json()
        assert "items" in j and "counts" in j
        for k in ("pending", "processing", "done", "failed"):
            assert k in j["counts"]

    def test_last_sync_all(self, h):
        r = requests.get(f"{BASE}/api/inventory-sync/last-sync", headers=h)
        assert r.status_code == 200
        assert "items" in r.json()

    def test_live(self, h):
        r = requests.get(f"{BASE}/api/inventory-sync/live", headers=h)
        assert r.status_code == 200
        j = r.json()
        for k in ("items", "total", "limit", "offset", "facets"):
            assert k in j
        assert "by_account" in j["facets"]
        assert "by_category" in j["facets"]

    def test_missing(self, h):
        r = requests.get(f"{BASE}/api/inventory-sync/missing", headers=h)
        assert r.status_code == 200
        j = r.json()
        for k in ("only_on_meesho", "only_in_pm", "counts",
                  "by_account_meesho", "by_account_pm"):
            assert k in j

    def test_live_export(self, h):
        r = requests.get(f"{BASE}/api/inventory-sync/live/export", headers=h)
        assert r.status_code == 200
        assert "spreadsheet" in r.headers.get("content-type", "")
        assert len(r.content) > 100

    def test_missing_export(self, h):
        r = requests.get(f"{BASE}/api/inventory-sync/missing/export",
                         headers=h)
        assert r.status_code == 200
        assert "spreadsheet" in r.headers.get("content-type", "")

    def test_run_dedupe(self, h, account_ids, db):
        aid = account_ids[0]
        # cleanup any leftover pending
        db.jobs.delete_many({"type": "inventory_sync",
                             "account_id": aid,
                             "status": {"$in": ["pending", "processing"]}})
        r1 = requests.post(f"{BASE}/api/inventory-sync/run",
                           json={"account_id": aid}, headers=h)
        assert r1.status_code == 200, r1.text
        j1 = r1.json()
        assert j1["already_queued"] is False
        r2 = requests.post(f"{BASE}/api/inventory-sync/run",
                           json={"account_id": aid}, headers=h)
        assert r2.status_code == 200
        j2 = r2.json()
        assert j2["already_queued"] is True
        assert j2["job_id"] == j1["job_id"]
        # cleanup
        db.jobs.delete_one({"_id": ObjectId(j1["job_id"])})

    def test_run_rejects_all(self, h):
        r = requests.post(f"{BASE}/api/inventory-sync/run",
                          json={"account_id": "all"}, headers=h)
        assert r.status_code in (400, 404, 422), r.text


# ---------------- auto-accept ----------------
class TestAutoAccept:
    def test_settings_list(self, h, db):
        r = requests.get(f"{BASE}/api/auto-accept/settings", headers=h)
        assert r.status_code == 200
        j = r.json()
        assert "items" in j
        n_acc = db.accounts.count_documents({})
        assert len(j["items"]) == n_acc
        for it in j["items"]:
            for k in ("account_id", "account_name",
                      "auto_accept_enabled", "interval_minutes", "last_run"):
                assert k in it

    def test_put_toggle(self, h, account_ids):
        aid = account_ids[0]
        r = requests.put(f"{BASE}/api/auto-accept/settings/{aid}",
                         json={"enabled": True}, headers=h)
        assert r.status_code == 200
        assert r.json()["updated"].get("auto_accept_enabled") is True
        r2 = requests.get(f"{BASE}/api/auto-accept/settings", headers=h)
        got = next(x for x in r2.json()["items"] if x["account_id"] == aid)
        assert got["auto_accept_enabled"] is True
        # revert
        requests.put(f"{BASE}/api/auto-accept/settings/{aid}",
                     json={"enabled": False}, headers=h)

    def test_put_interval_reject_small(self, h, account_ids):
        r = requests.put(f"{BASE}/api/auto-accept/settings/{account_ids[0]}",
                         json={"interval_minutes": 2}, headers=h)
        assert r.status_code == 422

    def test_put_interval_ok(self, h, account_ids):
        aid = account_ids[0]
        r = requests.put(f"{BASE}/api/auto-accept/settings/{aid}",
                         json={"interval_minutes": 30}, headers=h)
        assert r.status_code == 200
        assert r.json()["updated"].get("auto_accept_interval_minutes") == 30

    def test_run_now_dedupe(self, h, account_ids, db):
        aid = account_ids[0]
        db.jobs.delete_many({"type": "accept_labels", "account_id": aid,
                             "status": {"$in": ["pending", "processing"]}})
        r1 = requests.post(f"{BASE}/api/auto-accept/run-now/{aid}",
                           headers=h)
        assert r1.status_code == 200
        j1 = r1.json()
        assert j1["already_queued"] is False
        # verify persisted
        assert db.jobs.find_one({"_id": ObjectId(j1["job_id"]),
                                 "type": "accept_labels"}) is not None
        r2 = requests.post(f"{BASE}/api/auto-accept/run-now/{aid}",
                           headers=h)
        assert r2.status_code == 200
        j2 = r2.json()
        assert j2["already_queued"] is True
        assert j2["job_id"] == j1["job_id"]
        db.jobs.delete_one({"_id": ObjectId(j1["job_id"])})

    def test_history(self, h):
        r = requests.get(f"{BASE}/api/auto-accept/history", headers=h)
        assert r.status_code == 200
        assert "items" in r.json()


# ---------------- missing with seeded data ----------------
class TestMissingSeeded:
    def test_only_on_meesho_after_seed(self, h, db, account_ids):
        aid = account_ids[0]
        acc = db.accounts.find_one({"_id": ObjectId(aid)})
        seeds = [
            {"account_id": aid, "account_name": acc.get("name"),
             "catalog_name": "TESTCAT", "catalog_id": "TESTC1",
             "category": "TESTCAT", "style_id": "TEST_ONLY_MEESHO_1",
             "sku": "TEST_ONLY_MEESHO_1-M", "variation": "M",
             "price": "100", "current_stock": 5,
             "synced_at": datetime.now(timezone.utc)},
            {"account_id": aid, "account_name": acc.get("name"),
             "catalog_name": "TESTCAT", "catalog_id": "TESTC1",
             "category": "TESTCAT", "style_id": "TEST_ONLY_MEESHO_2",
             "sku": "TEST_ONLY_MEESHO_2-L", "variation": "L",
             "price": "150", "current_stock": 3,
             "synced_at": datetime.now(timezone.utc)},
        ]
        db.meesho_live_skus.insert_many(seeds)
        try:
            r = requests.get(f"{BASE}/api/inventory-sync/missing",
                             params={"account_id": aid}, headers=h)
            assert r.status_code == 200
            j = r.json()
            styles = {x["style_id"] for x in j["only_on_meesho"]}
            assert "TEST_ONLY_MEESHO_1" in styles
            assert "TEST_ONLY_MEESHO_2" in styles
            assert j["counts"]["only_on_meesho"] >= 2

            # live listing shows the seeded rows
            r2 = requests.get(f"{BASE}/api/inventory-sync/live",
                              params={"account_id": aid, "search": "TEST_ONLY"},
                              headers=h)
            assert r2.status_code == 200
            assert r2.json()["total"] >= 2
        finally:
            db.meesho_live_skus.delete_many(
                {"style_id": {"$regex": "^TEST_ONLY_MEESHO"}})


# ---------------- scheduler ----------------
class TestScheduler:
    def test_auto_accept_poll_registered(self):
        import subprocess
        out = subprocess.check_output(
            ["grep", "reconfigured", "/var/log/supervisor/backend.err.log"]
        ).decode()
        last = out.strip().splitlines()[-1]
        assert "auto_accept_poll" in last, last


# ---------------- worker sanity ----------------
class TestWorkerSanity:
    def test_job_types(self):
        with open("/app/scraper-ec2/label_worker.py") as f:
            src = f.read()
        assert '"inventory_sync"' in src
        assert '"accept_labels"' in src
