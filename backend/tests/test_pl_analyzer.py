"""Backend tests for the P&L Analyzer endpoints (iteration 7).

Covers:
- Auth login (admin credentials from test_credentials.md)
- GET /api/pl/analyzer/kpis  -> kpis array of 6 items
- GET /api/pl/analyzer/trend -> series array
- GET /api/pl/analyzer/accounts -> items array
- GET /api/pl/sku-analysis-tree -> categories array
- GET /api/pl/analyzer/export -> xlsx binary (non-empty, correct content-type)
"""
import io
import os
import zipfile
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
    "https://order-scraper.preview.emergentagent.com"

ADMIN_EMAIL = "admin@meesho-dash.local"
ADMIN_PASSWORD = "admin123"


@pytest.fixture(scope="session")
def auth_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=30)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    data = r.json()
    token = data.get("access_token") or data.get("token")
    assert token, f"No token in login response: {data}"
    return token


@pytest.fixture
def headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


# --- KPIs -----------------------------------------------------------------
def test_analyzer_kpis(headers):
    r = requests.get(f"{BASE_URL}/api/pl/analyzer/kpis", headers=headers, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert "kpis" in j
    kpis = j["kpis"]
    assert isinstance(kpis, list)
    assert len(kpis) == 6, f"expected 6 KPIs, got {len(kpis)}"
    keys = [k["key"] for k in kpis]
    assert keys == ["orders", "delivered", "returned", "revenue", "profit", "net_margin"]
    for k in kpis:
        assert "label" in k and "value" in k


# --- Trend ----------------------------------------------------------------
def test_analyzer_trend(headers):
    r = requests.get(f"{BASE_URL}/api/pl/analyzer/trend", headers=headers, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert "series" in j and isinstance(j["series"], list)


# --- Accounts -------------------------------------------------------------
def test_analyzer_accounts(headers):
    r = requests.get(f"{BASE_URL}/api/pl/analyzer/accounts", headers=headers, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert "items" in j and isinstance(j["items"], list)


# --- Tree -----------------------------------------------------------------
def test_sku_analysis_tree(headers):
    r = requests.get(f"{BASE_URL}/api/pl/sku-analysis-tree", headers=headers, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    assert "categories" in j and isinstance(j["categories"], list)


# --- Export ---------------------------------------------------------------
def test_analyzer_export_xlsx(headers):
    r = requests.get(f"{BASE_URL}/api/pl/analyzer/export", headers=headers, timeout=60)
    assert r.status_code == 200, r.text
    ct = r.headers.get("content-type", "")
    assert "spreadsheetml" in ct or "openxmlformats" in ct, f"bad content-type: {ct}"
    body = r.content
    assert len(body) > 0
    # xlsx == zip container; verify sheet names
    zf = zipfile.ZipFile(io.BytesIO(body))
    names = zf.namelist()
    assert any(n.startswith("xl/") for n in names), "not a valid xlsx"
    cd = r.headers.get("content-disposition", "")
    assert "pl_analyzer_" in cd and ".xlsx" in cd


# --- Auth guard ----------------------------------------------------------
def test_analyzer_kpis_requires_auth():
    r = requests.get(f"{BASE_URL}/api/pl/analyzer/kpis", timeout=30)
    assert r.status_code in (401, 403), r.status_code
