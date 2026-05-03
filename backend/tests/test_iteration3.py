"""Iteration-3 backend tests: Accounts CRUD, Labels multi-account run-now,
Settings skip rules, Scheduler snapshot, Alerts endpoints.

Creates accounts prefixed 'qa_' and cleans them up after the suite.
Restores settings (skip_dates/skip_weekdays=[]) at end.
Does NOT delete the existing 'Main' account (debug_port 9222).
"""
import os
import uuid
import time
import pytest
import requests
from datetime import datetime

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://meesho-scraper-fix.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@meesho-dash.local"
ADMIN_PASSWORD = "admin123"


@pytest.fixture(scope="module")
def auth():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    s.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
    return s


@pytest.fixture(scope="module")
def created_accounts(auth):
    ids = []
    yield ids
    for aid in ids:
        try:
            auth.delete(f"{BASE_URL}/api/accounts/{aid}", timeout=15)
        except Exception:
            pass


@pytest.fixture(scope="module", autouse=True)
def restore_settings(auth):
    # snapshot current settings
    r = auth.get(f"{BASE_URL}/api/settings", timeout=30)
    orig = r.json() if r.status_code == 200 else None
    yield
    if orig:
        body = {
            "scrape_enabled": orig.get("scrape_enabled", True),
            "scrape_time": orig.get("scrape_time", "11:00"),
            "label_enabled": orig.get("label_enabled", False),
            "label_time": orig.get("label_time", "09:30"),
            "skip_dates": [],
            "skip_weekdays": [],
        }
        try:
            auth.put(f"{BASE_URL}/api/settings", json=body, timeout=30)
        except Exception:
            pass


# --- Accounts ----------------------------------------------------------------
class TestAccountsDefaults:
    def test_defaults_returns_free_port_and_profile(self, auth):
        r = auth.get(f"{BASE_URL}/api/accounts/defaults", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "debug_port" in d and isinstance(d["debug_port"], int)
        assert d["debug_port"] >= 9222
        assert "profile_dir" in d and d["profile_dir"].startswith("/")
        # port must not collide with existing
        r2 = auth.get(f"{BASE_URL}/api/accounts", timeout=30)
        used = {a["debug_port"] for a in r2.json()["items"]}
        assert d["debug_port"] not in used


class TestAccountsCRUD:
    def test_create_account(self, auth, created_accounts):
        defaults = auth.get(f"{BASE_URL}/api/accounts/defaults", timeout=30).json()
        name = f"qa_{uuid.uuid4().hex[:6]}"
        body = {
            "name": name,
            "debug_port": defaults["debug_port"],
            "profile_dir": defaults["profile_dir"],
            "enabled": True,
        }
        r = auth.post(f"{BASE_URL}/api/accounts", json=body, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == name
        assert d["debug_port"] == body["debug_port"]
        assert d["enabled"] is True
        assert "id" in d
        created_accounts.append(d["id"])

    def test_create_duplicate_name_rejected(self, auth, created_accounts):
        # reuse first created account's name
        list_r = auth.get(f"{BASE_URL}/api/accounts", timeout=30).json()
        existing = [a for a in list_r["items"] if a["name"].startswith("qa_")]
        assert existing, "precondition: at least one qa_ account"
        dup_name = existing[0]["name"]
        free = auth.get(f"{BASE_URL}/api/accounts/defaults", timeout=30).json()
        r = auth.post(f"{BASE_URL}/api/accounts", json={
            "name": dup_name,
            "debug_port": free["debug_port"],
            "profile_dir": free["profile_dir"],
        }, timeout=30)
        assert r.status_code == 400
        assert "already exists" in r.text.lower()

    def test_create_duplicate_port_rejected(self, auth):
        list_r = auth.get(f"{BASE_URL}/api/accounts", timeout=30).json()
        existing = [a for a in list_r["items"] if a["name"].startswith("qa_")]
        assert existing
        used_port = existing[0]["debug_port"]
        r = auth.post(f"{BASE_URL}/api/accounts", json={
            "name": f"qa_{uuid.uuid4().hex[:6]}",
            "debug_port": used_port,
            "profile_dir": "/tmp/profile-dup",
        }, timeout=30)
        assert r.status_code == 400

    def test_update_account_toggle_enabled(self, auth, created_accounts):
        aid = created_accounts[0]
        r = auth.put(f"{BASE_URL}/api/accounts/{aid}", json={"enabled": False}, timeout=30)
        assert r.status_code == 200
        assert r.json()["enabled"] is False
        # flip back
        r2 = auth.put(f"{BASE_URL}/api/accounts/{aid}", json={"enabled": True}, timeout=30)
        assert r2.status_code == 200
        assert r2.json()["enabled"] is True

    def test_update_invalid_id(self, auth):
        r = auth.put(f"{BASE_URL}/api/accounts/bad-id", json={"enabled": True}, timeout=30)
        assert r.status_code == 400

    def test_delete_account(self, auth):
        # make a throwaway account just for delete
        defaults = auth.get(f"{BASE_URL}/api/accounts/defaults", timeout=30).json()
        name = f"qa_del_{uuid.uuid4().hex[:6]}"
        r = auth.post(f"{BASE_URL}/api/accounts", json={
            "name": name, "debug_port": defaults["debug_port"],
            "profile_dir": defaults["profile_dir"],
        }, timeout=30)
        aid = r.json()["id"]
        d = auth.delete(f"{BASE_URL}/api/accounts/{aid}", timeout=30)
        assert d.status_code == 200
        # GET list should not contain it
        lst = auth.get(f"{BASE_URL}/api/accounts", timeout=30).json()["items"]
        assert not any(a["id"] == aid for a in lst)


# --- Labels run-now ----------------------------------------------------------
class TestLabelsRunNow:
    def _cleanup_label_jobs(self, auth):
        r = auth.get(f"{BASE_URL}/api/labels/runs?limit=200", timeout=30).json()
        for j in r.get("items", []):
            if j.get("status") in ("pending",):
                try:
                    auth.delete(f"{BASE_URL}/api/jobs/{j['id']}", timeout=15)
                except Exception:
                    pass

    def test_run_now_all_accounts_true(self, auth, created_accounts):
        self._cleanup_label_jobs(auth)
        r = auth.post(f"{BASE_URL}/api/labels/run-now", json={"all_accounts": True}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "queued" in d and isinstance(d["queued"], list)
        assert "skipped" in d and isinstance(d["skipped"], list)
        # at least one enabled account (Main or qa_) should produce activity
        assert (len(d["queued"]) + len(d["skipped"])) >= 1

    def test_run_now_empty_body_defaults_all(self, auth):
        # second call right after — existing pendings should now be skipped
        r = auth.post(f"{BASE_URL}/api/labels/run-now", data="", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "queued" in d and "skipped" in d
        # every enabled account should already have a pending job → skipped reason already_queued
        for s in d["skipped"]:
            assert s.get("reason") == "already_queued"

    def test_run_now_single_account(self, auth, created_accounts):
        self._cleanup_label_jobs(auth)
        aid = created_accounts[0]
        r = auth.post(f"{BASE_URL}/api/labels/run-now", json={"account_id": aid}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        # either returns the created job (with id) or already_queued payload
        assert "id" in d
        assert d.get("status") in ("pending", None) or d.get("already_queued") or d.get("ok")

    def test_run_now_single_account_duplicate(self, auth, created_accounts):
        aid = created_accounts[0]
        r = auth.post(f"{BASE_URL}/api/labels/run-now", json={"account_id": aid}, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d.get("already_queued") is True
        assert isinstance(d.get("id"), str)


# --- Settings: skip rules ----------------------------------------------------
class TestSettingsSkipRules:
    def test_put_skip_dates_and_weekdays_persist(self, auth):
        body = {
            "scrape_enabled": True, "scrape_time": "11:00",
            "label_enabled": False, "label_time": "09:30",
            "skip_dates": ["2026-05-03", "2026-12-25"],
            "skip_weekdays": [6],  # Sunday
        }
        r = auth.put(f"{BASE_URL}/api/settings", json=body, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["skip_dates"] == ["2026-05-03", "2026-12-25"]
        assert d["skip_weekdays"] == [6]
        # GET echoes them
        g = auth.get(f"{BASE_URL}/api/settings", timeout=30).json()
        assert g["skip_dates"] == ["2026-05-03", "2026-12-25"]
        assert g["skip_weekdays"] == [6]

    def test_next_runs_includes_expected_ids(self, auth):
        # ensure label_enabled=True so daily_label is scheduled
        body = {
            "scrape_enabled": True, "scrape_time": "11:00",
            "label_enabled": True, "label_time": "09:30",
            "skip_dates": [], "skip_weekdays": [],
        }
        r = auth.put(f"{BASE_URL}/api/settings", json=body, timeout=30)
        assert r.status_code == 200
        g = auth.get(f"{BASE_URL}/api/settings", timeout=30).json()
        nr = g.get("next_runs", {})
        for jid in ("daily_scrape", "daily_snapshot", "alerts_check", "daily_label"):
            assert jid in nr, f"next_runs missing {jid}: {nr}"
        # now disable label and confirm daily_label disappears
        body["label_enabled"] = False
        auth.put(f"{BASE_URL}/api/settings", json=body, timeout=30)
        nr2 = auth.get(f"{BASE_URL}/api/settings", timeout=30).json().get("next_runs", {})
        assert "daily_label" not in nr2
        assert "daily_scrape" in nr2
        assert "daily_snapshot" in nr2
        assert "alerts_check" in nr2

    def test_skip_today_blocks_label_enqueue(self, auth):
        # set today's date in skip_dates (UTC — backend uses Asia/Kolkata;
        # using both today UTC and today IST to be safe)
        from datetime import datetime, timezone, timedelta
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_ist = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        body = {
            "scrape_enabled": True, "scrape_time": "11:00",
            "label_enabled": True, "label_time": "09:30",
            "skip_dates": list({today_utc, today_ist}),
            "skip_weekdays": [],
        }
        r = auth.put(f"{BASE_URL}/api/settings", json=body, timeout=30)
        assert r.status_code == 200

        # snapshot scheduler-created label jobs BEFORE
        def _sched_label_count():
            runs = auth.get(f"{BASE_URL}/api/labels/runs?limit=200", timeout=30).json().get("items", [])
            return sum(1 for j in runs if j.get("submitted_by") == "scheduler")

        before = _sched_label_count()
        r2 = auth.post(f"{BASE_URL}/api/scheduler/run-now?what=label", timeout=30)
        assert r2.status_code == 200
        time.sleep(1.5)
        after = _sched_label_count()
        assert after == before, f"skip_dates not honored: before={before} after={after}"


# --- Snapshot ---------------------------------------------------------------
class TestSnapshot:
    def test_snapshot_writes_history_rows(self, auth):
        # get baseline history length for existing product 8sa1ay
        r0 = auth.get(f"{BASE_URL}/api/products/8sa1ay/history?days=1", timeout=30)
        assert r0.status_code == 200
        before = len(r0.json().get("items", []))

        r = auth.post(f"{BASE_URL}/api/scheduler/run-now?what=snapshot", timeout=60)
        assert r.status_code == 200
        time.sleep(1.5)

        r2 = auth.get(f"{BASE_URL}/api/products/8sa1ay/history?days=1", timeout=30)
        assert r2.status_code == 200
        after = len(r2.json().get("items", []))
        assert after >= before + 1, f"snapshot did not write history: before={before} after={after}"
        latest = r2.json()["items"][-1]
        assert "snapshot_at" in latest
        assert "total_reviews" in latest


# --- Alerts -----------------------------------------------------------------
class TestAlerts:
    def test_check_now_returns_ok(self, auth):
        r = auth.post(f"{BASE_URL}/api/alerts/check-now", timeout=60)
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_list_alerts_shape(self, auth):
        r = auth.get(f"{BASE_URL}/api/alerts", timeout=30)
        assert r.status_code == 200
        d = r.json()
        for k in ("items", "unread", "total"):
            assert k in d
        assert isinstance(d["items"], list)
        assert isinstance(d["unread"], int)
        assert isinstance(d["total"], int)

    def test_mark_read_and_delete(self, auth):
        # insert a synthetic alert by calling check-now is not guaranteed to
        # produce one (no 24h-old snapshot in preview). We skip if empty.
        lst = auth.get(f"{BASE_URL}/api/alerts", timeout=30).json()
        if not lst["items"]:
            pytest.skip("no alerts to mark/delete (expected in preview env)")
        aid = lst["items"][0]["id"]
        r = auth.post(f"{BASE_URL}/api/alerts/{aid}/read", timeout=30)
        assert r.status_code == 200
        r2 = auth.post(f"{BASE_URL}/api/alerts/read-all", timeout=30)
        assert r2.status_code == 200
        r3 = auth.delete(f"{BASE_URL}/api/alerts/{aid}", timeout=30)
        assert r3.status_code == 200

    def test_read_invalid_id(self, auth):
        r = auth.post(f"{BASE_URL}/api/alerts/bad-id/read", timeout=30)
        assert r.status_code == 400

    def test_read_missing_id(self, auth):
        r = auth.post(f"{BASE_URL}/api/alerts/507f1f77bcf86cd799439099/read", timeout=30)
        assert r.status_code == 404
