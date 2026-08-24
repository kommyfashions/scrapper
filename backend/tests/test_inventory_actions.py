"""Backend tests for /api/inventory-actions/* (Bulk Pause feature).

Runs against the live running server (matches pattern of test_pl_analyzer.py).

Covers:
  - options cascade (accounts → main_categories → colors → sizes+style_ids)
  - preview validation (unknown size rejected, whole-product expansion)
  - pause queues a jobs.type=pause_skus doc + dedupe
  - history + single job lookup
"""
from __future__ import annotations

import os
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
    "https://label-sorter-pro.preview.emergentagent.com"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "meesho")

ADMIN_EMAIL = "admin@meesho-dash.local"
ADMIN_PASSWORD = "admin123"


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}"}


def _find_seed_product(headers):
    """Return (account_id, main_category, color, {sizes, style_ids}) for a
    Product Master row that has ≥1 SKU and ≥1 size."""
    r = requests.get(
        f"{BASE_URL}/api/inventory-actions/options", headers=headers, timeout=15,
    )
    assert r.status_code == 200
    for acc in r.json()["accounts"]:
        r1 = requests.get(
            f"{BASE_URL}/api/inventory-actions/options",
            headers=headers, params={"account_id": acc["id"]}, timeout=15,
        )
        for cat in r1.json().get("main_categories", []):
            r2 = requests.get(
                f"{BASE_URL}/api/inventory-actions/options",
                headers=headers,
                params={"account_id": acc["id"], "main_category": cat},
                timeout=15,
            )
            for color in r2.json().get("colors", []):
                r3 = requests.get(
                    f"{BASE_URL}/api/inventory-actions/options",
                    headers=headers,
                    params={"account_id": acc["id"],
                            "main_category": cat, "color": color},
                    timeout=15,
                )
                d = r3.json()
                if d.get("sizes") and d.get("style_ids"):
                    return acc["id"], cat, color, d
    pytest.skip("No product with sizes+style_ids in Product Master")


def test_options_root(headers):
    r = requests.get(
        f"{BASE_URL}/api/inventory-actions/options", headers=headers, timeout=15,
    )
    assert r.status_code == 200
    j = r.json()
    assert "accounts" in j
    assert isinstance(j["accounts"], list)


def test_preview_rejects_unknown_size(headers):
    aid, cat, color, _ = _find_seed_product(headers)
    r = requests.post(
        f"{BASE_URL}/api/inventory-actions/preview",
        headers=headers, timeout=15,
        json={"account_id": aid, "main_category": cat, "color": color,
              "sizes": ["__NOT_A_REAL_SIZE__"]},
    )
    assert r.status_code == 400
    assert "Sizes not in Product Master" in r.json()["detail"]


def test_preview_whole_product(headers):
    aid, cat, color, d = _find_seed_product(headers)
    r = requests.post(
        f"{BASE_URL}/api/inventory-actions/preview",
        headers=headers, timeout=15,
        json={"account_id": aid, "main_category": cat, "color": color,
              "sizes": []},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["is_whole_product"] is True
    assert j["target_sizes"] == d["sizes"]
    assert j["estimated_meesho_skus"] == len(d["sizes"]) * len(d["style_ids"])


def test_pause_queues_and_dedupes(headers):
    aid, cat, color, _ = _find_seed_product(headers)
    coll = MongoClient(MONGO_URL)[DB_NAME].jobs
    coll.delete_many({"type": "pause_skus", "account_id": aid})

    body = {"account_id": aid, "main_category": cat, "color": color,
            "sizes": []}
    r1 = requests.post(f"{BASE_URL}/api/inventory-actions/pause",
                       headers=headers, json=body, timeout=15)
    assert r1.status_code == 200, r1.text
    j1 = r1.json()
    assert j1["ok"] is True
    assert j1["already_queued"] is False
    job_id = j1["job_id"]

    r2 = requests.post(f"{BASE_URL}/api/inventory-actions/pause",
                       headers=headers, json=body, timeout=15)
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["already_queued"] is True
    assert j2["job_id"] == job_id

    r3 = requests.get(f"{BASE_URL}/api/inventory-actions/history",
                      headers=headers, timeout=15)
    assert r3.status_code == 200
    ids = [x["id"] for x in r3.json()["items"]]
    assert job_id in ids

    r4 = requests.get(f"{BASE_URL}/api/inventory-actions/{job_id}",
                      headers=headers, timeout=15)
    assert r4.status_code == 200
    assert r4.json()["status"] == "pending"

    coll.delete_many({"type": "pause_skus", "account_id": aid})


def test_history_empty_filter(headers):
    r = requests.get(
        f"{BASE_URL}/api/inventory-actions/history",
        headers=headers,
        params={"account_id": "000000000000000000000000"},
        timeout=15,
    )
    assert r.status_code == 200
    assert r.json()["items"] == []
