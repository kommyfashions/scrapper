"""Backend tests for /api/worker-health (deploy-drift diagnostic)."""
from __future__ import annotations

import os
import pytest
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://label-sorter-pro.preview.emergentagent.com",
).rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "meesho")

EMAIL = "admin@meesho-dash.local"
PW = "admin123"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": EMAIL, "password": PW}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_worker_health_shape_empty(headers):
    # ensure no workers registered
    coll = MongoClient(MONGO_URL)[DB_NAME].worker_capabilities
    coll.delete_many({})
    r = requests.get(f"{BASE_URL}/api/worker-health",
                     headers=headers, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j.keys()) == {"workers", "dashboard_known_types",
                             "missing_from_workers", "stuck_pending_by_type"}
    assert j["workers"] == []
    assert "inventory_sync" in j["dashboard_known_types"]
    assert "accept_labels" in j["dashboard_known_types"]
    # every known type is missing when no worker registered
    assert set(j["missing_from_workers"]) == set(j["dashboard_known_types"])


def test_worker_health_detects_partial_worker(headers):
    """Seed a fake worker that only advertises old types; endpoint should
    flag the new ones as missing."""
    coll = MongoClient(MONGO_URL)[DB_NAME].worker_capabilities
    coll.delete_many({})
    coll.insert_one({
        "host": "test-old-worker",
        "job_types": ["label_download", "payments_fetch",
                      "gst_report_fetch", "tax_invoice_fetch",
                      "pause_skus"],  # missing inventory_sync + accept_labels
        "updated_at": datetime.now(timezone.utc),
        "worker_file": "/home/ubuntu/meesho-label-worker/label_worker.py",
    })
    try:
        r = requests.get(f"{BASE_URL}/api/worker-health",
                         headers=headers, timeout=15)
        j = r.json()
        assert len(j["workers"]) == 1
        assert j["workers"][0]["host"] == "test-old-worker"
        assert "inventory_sync" in j["missing_from_workers"]
        assert "accept_labels" in j["missing_from_workers"]
        assert "label_download" not in j["missing_from_workers"]
    finally:
        coll.delete_many({"host": "test-old-worker"})


def test_worker_health_healthy_worker(headers):
    """When worker advertises every known type, missing_from_workers is []."""
    coll = MongoClient(MONGO_URL)[DB_NAME].worker_capabilities
    coll.delete_many({})
    coll.insert_one({
        "host": "test-fresh-worker",
        "job_types": ["label_download", "payments_fetch",
                      "gst_report_fetch", "tax_invoice_fetch",
                      "pause_skus", "inventory_sync", "accept_labels"],
        "updated_at": datetime.now(timezone.utc),
        "worker_file": "/home/ubuntu/meesho-label-worker/label_worker.py",
    })
    try:
        r = requests.get(f"{BASE_URL}/api/worker-health",
                         headers=headers, timeout=15)
        assert r.json()["missing_from_workers"] == []
    finally:
        coll.delete_many({"host": "test-fresh-worker"})
