"""Integration tests for the Product Master router.
Exercises the live FastAPI app against local MongoDB (mongodb://localhost:27017).
Run with: cd /app/backend && python -m pytest tests/test_product_master_api.py -q
"""
import io
import os

import pandas as pd
import pytest
import requests

API = "http://localhost:8001"
ADMIN = "admin@meesho-dash.local"
PW = "admin123"

REQUIRED_COLUMNS = ["Account", "Main Category", "Color", "Size", "SKU", "Cost"]


def _xlsx_bytes(rows):
    df = pd.DataFrame(rows, columns=REQUIRED_COLUMNS)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Product Master")
    buf.seek(0)
    return buf


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/api/auth/login",
                      json={"email": ADMIN, "password": PW}, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def accounts(headers):
    """Ensure Account1 and Account2 exist. Returns {alias: account_id}."""
    r = requests.get(f"{API}/api/accounts", headers=headers, timeout=10)
    existing = {a["name"]: a["id"] for a in r.json()["items"]}
    out = {}
    for i, nm in enumerate(("Account1", "Account2")):
        if nm in existing:
            out[nm] = existing[nm]
            continue
        rr = requests.post(f"{API}/api/accounts", headers=headers, json={
            "name": nm, "alias": nm,
            "debug_port": 9500 + i, "profile_dir": f"/tmp/pt-{i}",
        }, timeout=10)
        assert rr.status_code == 200, rr.text
        out[nm] = rr.json()["id"]
    return out


@pytest.fixture(autouse=True)
def _wipe(headers, accounts):
    """Wipe PM collections before each test for isolation."""
    requests.post(f"{API}/api/pm/admin/wipe-legacy", headers=headers, timeout=10)
    # also drop any PM data left over
    for pid in _list_ids(headers):
        requests.delete(f"{API}/api/pm/products/{pid}",
                        headers=headers, timeout=10)
    yield


def _list_ids(headers):
    r = requests.get(f"{API}/api/pm/products?page_size=500",
                     headers=headers, timeout=10)
    return [p["id"] for p in r.json()["items"]]


class TestUpload:
    def test_dry_run_then_commit(self, headers, accounts):
        buf = _xlsx_bytes([
            ["Account1", "Vertis", "Blue", "IND-3,IND-4", "SKU1,SKU2", 110],
            ["Account2", "Sofia", "White", "IND-5", "SKU9", 130],
        ])
        r = requests.post(f"{API}/api/pm/upload", headers=headers,
                          files={"file": ("t.xlsx", buf.getvalue())},
                          timeout=20)
        assert r.status_code == 200
        body = r.json()
        assert body["committed"] is False
        assert body["plan"]["inserted"] == 2
        token = body["parse_token"]
        # commit
        r2 = requests.post(f"{API}/api/pm/upload/commit", headers=headers,
                           json={"parse_token": token,
                                 "upload_source": "unit-test"}, timeout=10)
        assert r2.status_code == 200
        assert r2.json()["result"] == {
            "inserted": 2, "updated": 0, "skipped": 0}
        # list
        r3 = requests.get(f"{API}/api/pm/products", headers=headers, timeout=10)
        assert r3.json()["total"] == 2

    def test_skip_confirmation_direct_commit(self, headers, accounts):
        buf = _xlsx_bytes([
            ["Account1", "Vertis", "Blue", "S1", "K1", 100],
        ])
        r = requests.post(f"{API}/api/pm/upload?skip_confirmation=true",
                          headers=headers,
                          files={"file": ("t.xlsx", buf.getvalue())},
                          timeout=10)
        assert r.status_code == 200
        assert r.json()["committed"] is True
        assert r.json()["result"]["inserted"] == 1

    def test_upsert_updates_existing(self, headers, accounts):
        b1 = _xlsx_bytes([["Account1", "V", "Blue", "S", "K1", 100]])
        b2 = _xlsx_bytes([["Account1", "V", "Blue", "S", "K1,K2", 120]])
        requests.post(f"{API}/api/pm/upload?skip_confirmation=true",
                      headers=headers,
                      files={"file": ("a.xlsx", b1.getvalue())}, timeout=10)
        r = requests.post(f"{API}/api/pm/upload?skip_confirmation=true",
                         headers=headers,
                         files={"file": ("b.xlsx", b2.getvalue())}, timeout=10)
        assert r.json()["result"] == {
            "inserted": 0, "updated": 1, "skipped": 0}
        # Verify cost + skus updated
        items = requests.get(f"{API}/api/pm/products",
                            headers=headers, timeout=10).json()["items"]
        assert len(items) == 1
        assert items[0]["cost_price"] == 120
        assert set(items[0]["skus"]) == {"K1", "K2"}

    def test_unknown_account_surfaces(self, headers, accounts):
        buf = _xlsx_bytes([["Ghost", "V", "Blue", "S", "K", 100]])
        r = requests.post(f"{API}/api/pm/upload", headers=headers,
                          files={"file": ("g.xlsx", buf.getvalue())},
                          timeout=10)
        assert r.status_code == 200
        assert "Ghost" in r.json()["plan"]["unknown_accounts"]

    def test_sku_clash_detected(self, headers, accounts):
        # Seed one product with SKU X
        b1 = _xlsx_bytes([["Account1", "V", "Blue", "S", "X", 100]])
        requests.post(f"{API}/api/pm/upload?skip_confirmation=true",
                      headers=headers,
                      files={"file": ("a.xlsx", b1.getvalue())}, timeout=10)
        # Attempt to move SKU X to a different color
        b2 = _xlsx_bytes([["Account1", "V", "Black", "S", "X", 100]])
        r = requests.post(f"{API}/api/pm/upload", headers=headers,
                          files={"file": ("b.xlsx", b2.getvalue())},
                          timeout=10)
        clashes = r.json()["plan"]["sku_clashes"]
        assert len(clashes) == 1
        assert clashes[0]["sku"] == "X"


class TestCrudAndFilters:
    def _seed(self, headers, accounts):
        buf = _xlsx_bytes([
            ["Account1", "Vertis", "Blue", "IND-3,IND-4", "SKU1,SKU2", 110],
            ["Account1", "Vertis", "Black", "IND-3,IND-4", "SKU4", 110],
            ["Account2", "Sofia", "White", "IND-4,IND-5", "SKU9", 130],
        ])
        requests.post(f"{API}/api/pm/upload?skip_confirmation=true",
                     headers=headers,
                     files={"file": ("s.xlsx", buf.getvalue())}, timeout=10)

    def test_filter_by_category(self, headers, accounts):
        self._seed(headers, accounts)
        r = requests.get(f"{API}/api/pm/products?main_category=Vertis",
                        headers=headers, timeout=10)
        assert r.json()["total"] == 2

    def test_filter_by_account(self, headers, accounts):
        self._seed(headers, accounts)
        r = requests.get(
            f"{API}/api/pm/products?account_id={accounts['Account1']}",
            headers=headers, timeout=10)
        assert r.json()["total"] == 2

    def test_search_by_sku(self, headers, accounts):
        self._seed(headers, accounts)
        r = requests.get(f"{API}/api/pm/products?q=SKU9",
                        headers=headers, timeout=10)
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["color"] == "White"

    def test_search_by_color(self, headers, accounts):
        self._seed(headers, accounts)
        r = requests.get(f"{API}/api/pm/products?q=blue",
                        headers=headers, timeout=10)
        assert r.json()["total"] == 1

    def test_has_sku_false(self, headers, accounts):
        # Create a product with no SKUs
        r = requests.post(f"{API}/api/pm/products", headers=headers, json={
            "account_id": accounts["Account1"],
            "main_category": "Zeta", "color": "Cyan",
            "cost_price": 50, "skus": [], "sizes": []},
            timeout=10)
        assert r.status_code == 200
        rr = requests.get(f"{API}/api/pm/products?has_sku=false",
                         headers=headers, timeout=10)
        assert rr.json()["total"] == 1
        assert rr.json()["items"][0]["color"] == "Cyan"

    def test_sort_cost_asc(self, headers, accounts):
        self._seed(headers, accounts)
        r = requests.get(
            f"{API}/api/pm/products?sort=cost_price&order=asc",
            headers=headers, timeout=10)
        costs = [p["cost_price"] for p in r.json()["items"]]
        assert costs == sorted(costs)

    def test_pagination(self, headers, accounts):
        self._seed(headers, accounts)
        r = requests.get(f"{API}/api/pm/products?page=1&page_size=2",
                        headers=headers, timeout=10)
        assert r.json()["total"] == 3
        assert len(r.json()["items"]) == 2
        r2 = requests.get(f"{API}/api/pm/products?page=2&page_size=2",
                         headers=headers, timeout=10)
        assert len(r2.json()["items"]) == 1

    def test_create_update_delete(self, headers, accounts):
        r = requests.post(f"{API}/api/pm/products", headers=headers, json={
            "account_id": accounts["Account1"],
            "main_category": "Nova", "color": "Teal",
            "cost_price": 88, "skus": ["N1"], "sizes": ["S", "M"]},
            timeout=10)
        assert r.status_code == 200
        pid = r.json()["product"]["id"]
        # duplicate business-key should 409
        dup = requests.post(f"{API}/api/pm/products", headers=headers, json={
            "account_id": accounts["Account1"],
            "main_category": "Nova", "color": "Teal",
            "cost_price": 90, "skus": [], "sizes": []}, timeout=10)
        assert dup.status_code == 409
        # update
        upd = requests.put(f"{API}/api/pm/products/{pid}", headers=headers,
                          json={"cost_price": 99, "skus": ["N1", "N2"]},
                          timeout=10)
        assert upd.status_code == 200
        assert upd.json()["product"]["cost_price"] == 99
        assert set(upd.json()["product"]["skus"]) == {"N1", "N2"}
        # delete
        d = requests.delete(f"{API}/api/pm/products/{pid}",
                           headers=headers, timeout=10)
        assert d.status_code == 200


class TestTemplateAndExport:
    def test_template_download(self, headers, accounts):
        r = requests.get(f"{API}/api/pm/template", headers=headers,
                        timeout=10)
        assert r.status_code == 200
        df = pd.read_excel(io.BytesIO(r.content))
        assert list(df.columns) == REQUIRED_COLUMNS

    def test_export_roundtrip(self, headers, accounts):
        buf = _xlsx_bytes([
            ["Account1", "Vertis", "Blue", "IND-3", "SKU1", 100],
        ])
        requests.post(f"{API}/api/pm/upload?skip_confirmation=true",
                     headers=headers,
                     files={"file": ("s.xlsx", buf.getvalue())}, timeout=10)
        r = requests.get(f"{API}/api/pm/export", headers=headers, timeout=10)
        assert r.status_code == 200
        df = pd.read_excel(io.BytesIO(r.content))
        assert list(df.columns) == REQUIRED_COLUMNS
        assert len(df) == 1


class TestSkuAnalysisTree:
    def test_empty_tree_when_no_products(self, headers, accounts):
        r = requests.get(f"{API}/api/pl/sku-analysis-tree",
                        headers=headers, timeout=10)
        assert r.status_code == 200
        assert r.json()["categories"] == []

    def test_tree_reflects_pm_shape(self, headers, accounts):
        buf = _xlsx_bytes([
            ["Account1", "Vertis", "Blue", "S", "SKU1", 100],
            ["Account1", "Vertis", "Black", "S", "", 100],  # no SKUs
            ["Account2", "Sofia", "White", "S", "SKU9", 130],
        ])
        requests.post(f"{API}/api/pm/upload?skip_confirmation=true",
                     headers=headers,
                     files={"file": ("s.xlsx", buf.getvalue())}, timeout=10)
        r = requests.get(f"{API}/api/pl/sku-analysis-tree",
                        headers=headers, timeout=10)
        cats = {c["main_category"]: c for c in r.json()["categories"]}
        assert "Vertis" in cats and "Sofia" in cats
        vertis_black = next(
            a for c in cats["Vertis"]["colors"] if c["color"] == "Black"
            for a in c["accounts"])
        assert vertis_black["no_skus"] is True
