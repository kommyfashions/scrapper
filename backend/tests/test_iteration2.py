"""Backend API tests for Meesho Seller Dashboard — ITERATION 2.

Covers new iteration-2 endpoints:
  - /api/health
  - /api/products {image, tracked}
  - /api/products/{pid}/track
  - /api/products/{pid}/history
  - /api/labels/run-now, /api/labels/runs
  - /api/settings (GET/PUT) — also validates HH:MM
  - /api/scheduler/run-now?what=scrape|label|garbage
  - regression: /api/jobs filter by type

Uses real remote MongoDB at mongodb://43.205.229.129:27017/meesho.
Preserves existing products aeop5q / 8sa1ay and restores settings to defaults.
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "admin@meesho-dash.local"
ADMIN_PASSWORD = "admin123"

EXISTING_PIDS = ["aeop5q", "8sa1ay"]


@pytest.fixture(scope="module")
def auth():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return s


@pytest.fixture(scope="module", autouse=True)
def restore_settings(auth):
    """Snapshot settings before and restore after module run."""
    r = auth.get(f"{BASE_URL}/api/settings", timeout=15)
    before = None
    if r.status_code == 200:
        d = r.json()
        before = {
            "scrape_enabled": d.get("scrape_enabled", True),
            "scrape_time": d.get("scrape_time", "11:00"),
            "label_enabled": d.get("label_enabled", False),
            "label_time": d.get("label_time", "09:30"),
        }
    yield
    if before is not None:
        try:
            auth.put(f"{BASE_URL}/api/settings", json=before, timeout=15)
        except Exception:
            pass


# ---------- Health ----------
class TestHealth:
    def test_health_ok(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=15)
        assert r.status_code == 200
        assert r.json() == {"ok": True}


# ---------- Products: image + tracked ----------
class TestProductsImageTracked:
    def test_list_includes_image_and_tracked(self, auth):
        r = auth.get(f"{BASE_URL}/api/products?limit=50", timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        pid_map = {i["product_id"]: i for i in items if "product_id" in i}
        for pid in EXISTING_PIDS:
            assert pid in pid_map, f"{pid} missing in products list"
            assert "image" in pid_map[pid], f"'image' key missing for {pid}"
            assert "tracked" in pid_map[pid], f"'tracked' key missing for {pid}"
            assert isinstance(pid_map[pid]["tracked"], bool)

    def test_detail_image_is_valid_url_for_existing(self, auth):
        for pid in EXISTING_PIDS:
            r = auth.get(f"{BASE_URL}/api/products/{pid}", timeout=30)
            assert r.status_code == 200, f"{pid}: {r.text}"
            d = r.json()
            assert d["product_id"] == pid
            assert "avg_rating" in d
            assert "tracked" in d
            img = d.get("image")
            assert isinstance(img, str) and img.startswith("http"), \
                f"{pid} image expected http URL via review-media fallback, got: {img!r}"

    def test_list_image_falls_back_to_review_media(self, auth):
        """Review request says list endpoint must also expose image derived from review media."""
        r = auth.get(f"{BASE_URL}/api/products?limit=50", timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        for pid in EXISTING_PIDS:
            p = next((i for i in items if i["product_id"] == pid), None)
            assert p is not None
            img = p.get("image")
            assert isinstance(img, str) and img.startswith("http"), \
                f"List endpoint image for {pid} is {img!r} — expected fallback to review media URL"


# ---------- Track toggle ----------
class TestTrackToggle:
    def test_toggle_off_and_on(self, auth):
        pid = "aeop5q"
        r = auth.post(f"{BASE_URL}/api/products/{pid}/track",
                      json={"tracked": False}, timeout=15)
        assert r.status_code == 200
        assert r.json() == {"ok": True, "tracked": False}

        # verify via detail
        d = auth.get(f"{BASE_URL}/api/products/{pid}", timeout=15).json()
        assert d["tracked"] is False

        # restore
        r2 = auth.post(f"{BASE_URL}/api/products/{pid}/track",
                       json={"tracked": True}, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["tracked"] is True

        d2 = auth.get(f"{BASE_URL}/api/products/{pid}", timeout=15).json()
        assert d2["tracked"] is True

    def test_toggle_unknown_pid_404(self, auth):
        r = auth.post(f"{BASE_URL}/api/products/nope_{uuid.uuid4().hex[:6]}/track",
                      json={"tracked": True}, timeout=15)
        assert r.status_code == 404


# ---------- History ----------
class TestProductHistory:
    def test_history_empty_items(self, auth):
        r = auth.get(f"{BASE_URL}/api/products/aeop5q/history?days=30", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "items" in body and isinstance(body["items"], list)


# ---------- Jobs type filter (regression) ----------
class TestJobsType:
    def test_create_job_default_type(self, auth):
        u = uuid.uuid4().hex[:8]
        url = f"https://www.meesho.com/test-{u}/p/TEST{u}"
        r = auth.post(f"{BASE_URL}/api/jobs", json={"product_url": url}, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j.get("type") == "product_scrape"
        # cleanup
        auth.delete(f"{BASE_URL}/api/jobs/{j['id']}", timeout=15)

    def test_filter_by_type(self, auth):
        r = auth.get(f"{BASE_URL}/api/jobs?type=product_scrape&limit=10", timeout=15)
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert it.get("type") == "product_scrape"

        r2 = auth.get(f"{BASE_URL}/api/jobs?type=label_download&limit=10", timeout=15)
        assert r2.status_code == 200
        for it in r2.json()["items"]:
            assert it.get("type") == "label_download"

        r3 = auth.get(f"{BASE_URL}/api/jobs?type=all&limit=10", timeout=15)
        assert r3.status_code == 200


# ---------- Labels ----------
class TestLabels:
    def test_run_now_and_idempotent(self, auth):
        # make sure no pending/processing label first (best-effort: list + delete non-done)
        r0 = auth.get(f"{BASE_URL}/api/labels/runs?limit=200", timeout=15)
        if r0.status_code == 200:
            for j in r0.json().get("items", []):
                if j.get("status") in ("pending", "processing"):
                    auth.delete(f"{BASE_URL}/api/jobs/{j['id']}", timeout=10)

        r1 = auth.post(f"{BASE_URL}/api/labels/run-now", timeout=15)
        assert r1.status_code == 200
        d1 = r1.json()
        first_id = d1.get("id")
        assert first_id, d1
        # second call should indicate already_queued
        r2 = auth.post(f"{BASE_URL}/api/labels/run-now", timeout=15)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2.get("already_queued") is True
        assert d2.get("id") == first_id

        # cleanup
        auth.delete(f"{BASE_URL}/api/jobs/{first_id}", timeout=15)

    def test_runs_sorted_and_type(self, auth):
        r = auth.get(f"{BASE_URL}/api/labels/runs?limit=20", timeout=15)
        assert r.status_code == 200
        items = r.json()["items"]
        for it in items:
            assert it.get("type") == "label_download"
        # check desc by created_at (strings ISO compare)
        for a, b in zip(items, items[1:]):
            ca = a.get("created_at") or ""
            cb = b.get("created_at") or ""
            assert ca >= cb


# ---------- Settings ----------
class TestSettings:
    def test_get_settings_shape(self, auth):
        r = auth.get(f"{BASE_URL}/api/settings", timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ("scrape_enabled", "scrape_time", "label_enabled",
                  "label_time", "next_runs", "timezone"):
            assert k in d, f"missing {k}"
        assert d["timezone"] == "Asia/Kolkata"
        assert isinstance(d["next_runs"], dict)

    def test_put_valid_settings_updates_next_runs(self, auth):
        body = {
            "scrape_enabled": True, "scrape_time": "11:30",
            "label_enabled": True, "label_time": "09:45",
        }
        r = auth.put(f"{BASE_URL}/api/settings", json=body, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["scrape_time"] == "11:30"
        assert d["label_time"] == "09:45"
        assert d["label_enabled"] is True
        assert isinstance(d["next_runs"], dict)
        # both schedule job ids should be present
        assert "daily_scrape" in d["next_runs"]
        assert "daily_label" in d["next_runs"]
        assert d["next_runs"]["daily_scrape"] is not None

    def test_put_invalid_time_hour(self, auth):
        r = auth.put(f"{BASE_URL}/api/settings", json={
            "scrape_enabled": True, "scrape_time": "25:00",
            "label_enabled": False, "label_time": "09:00",
        }, timeout=15)
        assert r.status_code == 400

    def test_put_invalid_time_garbage(self, auth):
        r = auth.put(f"{BASE_URL}/api/settings", json={
            "scrape_enabled": True, "scrape_time": "11:00",
            "label_enabled": False, "label_time": "abc",
        }, timeout=15)
        assert r.status_code == 400

    def test_label_disabled_omits_job(self, auth):
        body = {
            "scrape_enabled": True, "scrape_time": "11:00",
            "label_enabled": False, "label_time": "09:30",
        }
        r = auth.put(f"{BASE_URL}/api/settings", json=body, timeout=15)
        assert r.status_code == 200
        nr = r.json()["next_runs"]
        assert "daily_scrape" in nr
        assert "daily_label" not in nr  # disabled ⇒ no scheduled job


# ---------- Scheduler manual run ----------
class TestSchedulerRunNow:
    def test_run_now_scrape_idempotent(self, auth):
        # ensure aeop5q is tracked
        auth.post(f"{BASE_URL}/api/products/aeop5q/track", json={"tracked": True}, timeout=15)
        r1 = auth.post(f"{BASE_URL}/api/scheduler/run-now?what=scrape", timeout=20)
        assert r1.status_code == 200
        assert r1.json()["ok"] is True

        # count pending scrape jobs for aeop5q
        def pending_count():
            resp = auth.get(f"{BASE_URL}/api/jobs?type=product_scrape&status=pending&limit=200",
                            timeout=15)
            return sum(1 for i in resp.json()["items"] if i.get("product_id") == "aeop5q")

        c1 = pending_count()
        # call again — should NOT create duplicate for aeop5q
        r2 = auth.post(f"{BASE_URL}/api/scheduler/run-now?what=scrape", timeout=20)
        assert r2.status_code == 200
        c2 = pending_count()
        assert c2 == c1, f"Scheduler produced duplicate pending jobs for aeop5q (was {c1}, now {c2})"

        # cleanup: delete any jobs we created with submitted_by=scheduler for aeop5q
        resp = auth.get(f"{BASE_URL}/api/jobs?type=product_scrape&status=pending&limit=200",
                        timeout=15)
        for it in resp.json()["items"]:
            if it.get("product_id") == "aeop5q" and it.get("submitted_by") == "scheduler":
                auth.delete(f"{BASE_URL}/api/jobs/{it['id']}", timeout=10)

    def test_run_now_label(self, auth):
        # cleanup pending labels first
        r0 = auth.get(f"{BASE_URL}/api/labels/runs?limit=50", timeout=15)
        for j in r0.json().get("items", []):
            if j.get("status") in ("pending", "processing"):
                auth.delete(f"{BASE_URL}/api/jobs/{j['id']}", timeout=10)

        r = auth.post(f"{BASE_URL}/api/scheduler/run-now?what=label", timeout=15)
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # verify at least one label_download pending job exists now
        r2 = auth.get(f"{BASE_URL}/api/labels/runs?limit=10", timeout=15)
        items = r2.json()["items"]
        assert any(i.get("status") == "pending" for i in items)

        # cleanup
        for it in items:
            if it.get("status") in ("pending", "processing"):
                auth.delete(f"{BASE_URL}/api/jobs/{it['id']}", timeout=10)

    def test_run_now_garbage_400(self, auth):
        r = auth.post(f"{BASE_URL}/api/scheduler/run-now?what=garbage", timeout=15)
        assert r.status_code == 400
