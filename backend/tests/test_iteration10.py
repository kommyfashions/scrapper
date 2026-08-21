"""Backend regression tests for iteration 10 fixes (FIX 2, 3, 4)."""
import os
import pytest
import requests
from pymongo import MongoClient
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv("/app/frontend/.env")
BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE}/api/auth/login", json={
        "email": "admin@meesho-dash.local", "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"] if "access_token" in r.json() else r.json()["token"]


@pytest.fixture(scope="module")
def h(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient("mongodb://localhost:27017")
    return c["meesho"]


# ---------- FIX 2: /pl/analyzer/kpis ----------
class TestAnalyzerKPIs:
    def test_profit_is_net_after_ads(self, h):
        r = requests.get(f"{BASE}/api/pl/analyzer/kpis", headers=h)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "kpis" in data and "current" in data
        profit_kpi = next((k for k in data["kpis"] if k["key"] == "profit"), None)
        assert profit_kpi is not None
        assert profit_kpi["label"] == "Net Profit"
        assert profit_kpi.get("sub") == "after returns & ads"
        curr = data["current"]
        expected = round(curr["profit"] - curr["loss"] - curr["ads_cost"], 2)
        assert profit_kpi["value"] == expected, (
            f"profit KPI={profit_kpi['value']} != net_after_ads={expected}")


# ---------- FIX 3: /pl/missing-sku-costs + export ----------
class TestMissingSKUCosts:
    def test_response_shape(self, h):
        r = requests.get(f"{BASE}/api/pl/missing-sku-costs", headers=h)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("items", "by_account", "total_with_costs",
                  "total_order_pairs", "missing_skus", "total_missing"):
            assert k in d, f"missing key {k}"
        assert isinstance(d["items"], list)
        assert isinstance(d["by_account"], list)
        assert isinstance(d["missing_skus"], list)
        assert isinstance(d["total_missing"], int)

    def test_export_xlsx(self, h):
        r = requests.get(f"{BASE}/api/pl/missing-sku-costs/export",
                         headers=h)
        assert r.status_code == 200
        assert "spreadsheetml.sheet" in r.headers.get("content-type", "")
        cd = r.headers.get("content-disposition", "")
        assert "missing_sku_costs_" in cd
        assert len(r.content) > 0


# ---------- FIX 4: pdf_sorter tier + unmatched export ----------
class TestPdfSorterTier:
    def test_tier_constant(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from services.pdf_sorter import TIER1_MIN_PAGES
        assert TIER1_MIN_PAGES == 5

    def test_recent_runs_has_tier_fields(self, h):
        r = requests.get(f"{BASE}/api/pdf-sorter/recent-runs", headers=h)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d
        # tier fields only present if at least one run exists
        for it in d["items"]:
            assert "tier1_pages" in it
            assert "tier2_pages" in it

    def test_runs_has_tier_fields(self, h):
        r = requests.get(f"{BASE}/api/pdf-sorter/runs", headers=h)
        assert r.status_code == 200
        d = r.json()
        for it in d["items"]:
            assert "tier1_pages" in it
            assert "tier2_pages" in it

    def test_unmatched_export(self, h, mongo):
        run_id = "TEST_iter10_unmatched"
        mongo.pdf_sorter_runs.delete_many({"run_id": run_id})
        mongo.pdf_sorter_runs.insert_one({
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc),
            "unmatched_skus": [{"sku": "FOO", "count": 3},
                               {"sku": "BAR", "count": 1}],
            "tier1_pages": 0, "tier2_pages": 4,
        })
        try:
            r = requests.get(
                f"{BASE}/api/pdf-sorter/runs/{run_id}/unmatched.xlsx",
                headers=h)
            assert r.status_code == 200, r.text
            assert "spreadsheetml.sheet" in r.headers.get("content-type", "")
            assert len(r.content) > 0
        finally:
            mongo.pdf_sorter_runs.delete_many({"run_id": run_id})


# ---------- Regression: /inventory-actions/history ----------
class TestInventoryHistoryRegression:
    def test_history(self, h):
        r = requests.get(f"{BASE}/api/inventory-actions/history", headers=h)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d and "counts" in d
