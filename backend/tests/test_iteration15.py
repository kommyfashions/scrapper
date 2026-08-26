"""Iteration 15 — cancel-stuck, scheduler-status, pdf-sorter delete run,
inventory-sync note/debug_dir surfacing."""
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient
from bson import ObjectId

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
    "https://inventory-sync-hub-18.preview.emergentagent.com"
MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "meesho"

ADMIN_EMAIL = "admin@meesho-dash.local"
ADMIN_PASSWORD = "admin123"


# -- fixtures ---------------------------------------------------------------
@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


# -- cancel-stuck -----------------------------------------------------------
class TestCancelStuck:
    def test_cancel_stuck_marks_failed(self, mongo, auth):
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        res = mongo.jobs.insert_one({
            "type": "inventory_sync", "status": "pending",
            "created_at": old, "test_seed": "iter15-cs1",
        })
        jid = res.inserted_id
        try:
            r = requests.post(
                f"{BASE_URL}/api/jobs/cancel-stuck",
                params={"older_than_minutes": 5, "job_type": "inventory_sync"},
                headers=auth, timeout=15,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body.get("deleted") is False
            assert body.get("cancelled", 0) >= 1
            doc = mongo.jobs.find_one({"_id": jid})
            assert doc["status"] == "failed"
        finally:
            mongo.jobs.delete_one({"_id": jid})

    def test_cancel_stuck_delete_true(self, mongo, auth):
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        res = mongo.jobs.insert_one({
            "type": "inventory_sync", "status": "pending",
            "created_at": old, "test_seed": "iter15-cs2",
        })
        jid = res.inserted_id
        try:
            r = requests.post(
                f"{BASE_URL}/api/jobs/cancel-stuck",
                params={"older_than_minutes": 5,
                        "job_type": "inventory_sync", "delete": "true"},
                headers=auth, timeout=15,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body.get("deleted") is True
            assert body.get("cancelled", 0) >= 1
            assert mongo.jobs.find_one({"_id": jid}) is None
        finally:
            mongo.jobs.delete_one({"_id": jid})


# -- pdf-sorter delete run --------------------------------------------------
class TestPdfSorterDelete:
    def test_delete_seeded_run(self, mongo, auth):
        run_id = f"iter15-test-{int(time.time())}"
        mongo.pdf_sorter_runs.insert_one({
            "run_id": run_id, "created_at": datetime.now(timezone.utc),
            "test_seed": "iter15", "matched": [], "unmatched": [],
        })
        try:
            r = requests.delete(
                f"{BASE_URL}/api/pdf-sorter/runs/{run_id}",
                headers=auth, timeout=15,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body.get("ok") is True
            assert body.get("run_id") == run_id
            assert "files_removed" in body
            assert mongo.pdf_sorter_runs.find_one({"run_id": run_id}) is None
        finally:
            mongo.pdf_sorter_runs.delete_one({"run_id": run_id})

    def test_delete_unknown_returns_404(self, auth):
        r = requests.delete(
            f"{BASE_URL}/api/pdf-sorter/runs/does-not-exist-xyz",
            headers=auth, timeout=15,
        )
        assert r.status_code == 404


# -- scheduler-status -------------------------------------------------------
class TestSchedulerStatus:
    def test_status_shape(self, auth):
        r = requests.get(f"{BASE_URL}/api/scheduler-status",
                         headers=auth, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "scheduler_running" in body
        assert "jobs" in body
        assert "server_time" in body
        assert isinstance(body["jobs"], list)
        # auto_accept_poll job present
        ids = [j.get("id") for j in body["jobs"]]
        assert "auto_accept_poll" in ids, f"jobs = {ids}"
        aa = next(j for j in body["jobs"] if j["id"] == "auto_accept_poll")
        assert "*/5" in aa.get("trigger", "") or "5" in aa.get("trigger", "")
        # next_run_time must be non-null in the future
        assert aa.get("next_run_time"), aa
        assert (aa.get("seconds_until_next") or 0) >= 0

    def test_status_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/scheduler-status", timeout=15)
        assert r.status_code in (401, 403), r.status_code


# -- inventory-sync history exposes note+debug_dir --------------------------
class TestInventorySyncHistoryFields:
    def test_note_and_debug_dir_surfaced(self, mongo, auth):
        job = {
            "type": "inventory_sync",
            "status": "done",
            "account": "Account1",
            "created_at": datetime.now(timezone.utc),
            "finished_at": datetime.now(timezone.utc),
            "result": {
                "catalogs_scanned": 0, "skus_captured": 0,
                "pages_visited": 1, "note": "test-note",
                "debug_dir": "/tmp/meesho-inv-debug/x_1",
            },
            "test_seed": "iter15-invhist",
        }
        ins = mongo.jobs.insert_one(job)
        jid = ins.inserted_id
        try:
            r = requests.get(
                f"{BASE_URL}/api/inventory-sync/history",
                headers=auth, timeout=15,
            )
            assert r.status_code == 200, r.text
            items = r.json().get("items", [])
            row = next((i for i in items if i.get("id") == str(jid)), None)
            assert row is not None, "seeded job not returned"
            assert row.get("result", {}).get("note") == "test-note"
            assert row.get("result", {}).get("debug_dir") == \
                "/tmp/meesho-inv-debug/x_1"
        finally:
            mongo.jobs.delete_one({"_id": jid})
