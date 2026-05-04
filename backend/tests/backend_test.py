"""Backend API tests for Meesho Seller Dashboard.

Covers: auth (login / me), jobs (create/bulk/list/stats/retry/reset-stuck/delete),
products (list/detail) and analytics overview. Uses real remote MongoDB.

Cleans up only its own test-created jobs. Leaves the two existing products
(8sa1ay, aeop5q) untouched.
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://meesho-pl.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@meesho-dash.local"
ADMIN_PASSWORD = "admin123"

PRESERVE_PRODUCTS = {"8sa1ay", "aeop5q"}


# --- fixtures ----------------------------------------------------------------
@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def token(api):
    r = api.post(f"{BASE_URL}/api/auth/login",
                 json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def auth(api, token):
    api.headers.update({"Authorization": f"Bearer {token}"})
    return api


@pytest.fixture(scope="session")
def created_job_ids():
    ids: list[str] = []
    yield ids
    # cleanup
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    if r.status_code == 200:
        tok = r.json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        for jid in ids:
            try:
                s.delete(f"{BASE_URL}/api/jobs/{jid}", headers=h, timeout=15)
            except Exception:
                pass


def _unique_meesho_url() -> str:
    u = uuid.uuid4().hex[:8]
    return f"https://www.meesho.com/test-product-{u}/p/TEST{u}"


# --- Auth --------------------------------------------------------------------
class TestAuth:
    def test_login_success(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login",
                     json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data and isinstance(data["access_token"], str)
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == ADMIN_EMAIL

    def test_login_invalid(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login",
                     json={"email": ADMIN_EMAIL, "password": "wrongpass"}, timeout=30)
        assert r.status_code == 401

    def test_me_requires_token(self):
        r = requests.get(f"{BASE_URL}/api/auth/me", timeout=30)
        assert r.status_code == 401

    def test_me_with_token(self, auth):
        r = auth.get(f"{BASE_URL}/api/auth/me", timeout=30)
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == ADMIN_EMAIL
        assert "id" in body


# --- Jobs --------------------------------------------------------------------
class TestJobs:
    def test_create_job_valid(self, auth, created_job_ids):
        url = _unique_meesho_url()
        r = auth.post(f"{BASE_URL}/api/jobs", json={"product_url": url}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "pending"
        assert data["product_url"] == url
        assert data["product_id"].startswith("TEST")
        assert "id" in data
        created_job_ids.append(data["id"])

    def test_create_job_invalid_url(self, auth):
        r = auth.post(f"{BASE_URL}/api/jobs", json={"product_url": "not a url"}, timeout=30)
        assert r.status_code == 400

    def test_bulk_create(self, auth, created_job_ids):
        urls = [_unique_meesho_url(), _unique_meesho_url(), "not a url", "https://example.com/foo"]
        r = auth.post(f"{BASE_URL}/api/jobs/bulk", json={"product_urls": urls}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert len(data["created"]) == 2
        assert len(data["skipped"]) == 2
        for j in data["created"]:
            created_job_ids.append(j["id"])

    def test_list_jobs_filter(self, auth):
        r = auth.get(f"{BASE_URL}/api/jobs?status=pending&limit=50", timeout=30)
        assert r.status_code == 200
        body = r.json()
        assert "items" in body and "total" in body
        for item in body["items"]:
            assert item["status"] == "pending"

    def test_list_jobs_search(self, auth, created_job_ids):
        # search for one of our unique urls
        # create a fresh known URL
        marker = uuid.uuid4().hex[:10]
        url = f"https://www.meesho.com/srch-{marker}/p/SRCH{marker}"
        r = auth.post(f"{BASE_URL}/api/jobs", json={"product_url": url}, timeout=30)
        assert r.status_code == 200
        created_job_ids.append(r.json()["id"])
        r2 = auth.get(f"{BASE_URL}/api/jobs?q={marker}", timeout=30)
        assert r2.status_code == 200
        items = r2.json()["items"]
        assert any(marker in i["product_url"] for i in items)

    def test_jobs_stats(self, auth):
        r = auth.get(f"{BASE_URL}/api/jobs/stats", timeout=30)
        assert r.status_code == 200
        body = r.json()
        for k in ("pending", "processing", "done", "failed", "stuck"):
            assert k in body
            assert isinstance(body[k], int)

    def test_retry_job(self, auth, created_job_ids):
        # create a job, then retry it
        r = auth.post(f"{BASE_URL}/api/jobs", json={"product_url": _unique_meesho_url()}, timeout=30)
        jid = r.json()["id"]
        created_job_ids.append(jid)
        r2 = auth.post(f"{BASE_URL}/api/jobs/{jid}/retry", timeout=30)
        assert r2.status_code == 200
        assert r2.json()["ok"] is True

    def test_retry_invalid_id(self, auth):
        r = auth.post(f"{BASE_URL}/api/jobs/not-an-oid/retry", timeout=30)
        assert r.status_code == 400

    def test_retry_missing_id(self, auth):
        r = auth.post(f"{BASE_URL}/api/jobs/507f1f77bcf86cd799439011/retry", timeout=30)
        assert r.status_code == 404

    def test_delete_invalid_id(self, auth):
        r = auth.delete(f"{BASE_URL}/api/jobs/bad-id", timeout=30)
        assert r.status_code == 400

    def test_delete_missing_id(self, auth):
        r = auth.delete(f"{BASE_URL}/api/jobs/507f1f77bcf86cd799439099", timeout=30)
        assert r.status_code == 404

    def test_delete_created_job(self, auth):
        r = auth.post(f"{BASE_URL}/api/jobs", json={"product_url": _unique_meesho_url()}, timeout=30)
        jid = r.json()["id"]
        r2 = auth.delete(f"{BASE_URL}/api/jobs/{jid}", timeout=30)
        assert r2.status_code == 200
        # verify gone (retry should 404)
        r3 = auth.post(f"{BASE_URL}/api/jobs/{jid}/retry", timeout=30)
        assert r3.status_code == 404

    def test_reset_stuck(self, auth):
        r = auth.post(f"{BASE_URL}/api/jobs/reset-stuck", timeout=30)
        assert r.status_code == 200
        assert "reset" in r.json()


# --- Products ----------------------------------------------------------------
class TestProducts:
    def test_list_products(self, auth):
        r = auth.get(f"{BASE_URL}/api/products?limit=50", timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data and "total" in data
        # existing products should be present
        pids = {i["product_id"] for i in data["items"] if "product_id" in i}
        assert PRESERVE_PRODUCTS.issubset(pids), f"Expected {PRESERVE_PRODUCTS} in {pids}"
        # avg_rating computed
        for i in data["items"]:
            assert "avg_rating" in i  # may be None

    def test_products_search(self, auth):
        r = auth.get(f"{BASE_URL}/api/products?q=8sa1ay", timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        assert any(i.get("product_id") == "8sa1ay" for i in items)

    def test_products_sort(self, auth):
        r = auth.get(f"{BASE_URL}/api/products?sort=total_reviews&order=desc", timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        if len(items) >= 2:
            a = items[0].get("total_reviews") or 0
            b = items[1].get("total_reviews") or 0
            assert a >= b

    def test_product_detail(self, auth):
        r = auth.get(f"{BASE_URL}/api/products/8sa1ay", timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data["product_id"] == "8sa1ay"
        assert isinstance(data.get("reviews", []), list)
        assert "avg_rating" in data

    def test_product_detail_missing(self, auth):
        r = auth.get(f"{BASE_URL}/api/products/doesnotexist_{uuid.uuid4().hex[:8]}", timeout=30)
        assert r.status_code == 404


# --- Analytics ---------------------------------------------------------------
class TestAnalytics:
    def test_overview(self, auth):
        r = auth.get(f"{BASE_URL}/api/analytics/overview", timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("total_products", "total_reviews", "avg_rating", "rating_distribution",
                  "jobs_today", "job_status_breakdown", "top_sellers",
                  "review_volume", "helpful_reviews"):
            assert k in d, f"missing {k}"
        assert isinstance(d["total_products"], int)
        assert isinstance(d["top_sellers"], list)
        assert isinstance(d["helpful_reviews"], list)
        for s in ("pending", "processing", "done", "failed"):
            assert s in d["job_status_breakdown"]
        for s in ("1", "2", "3", "4", "5"):
            assert s in d["rating_distribution"]
