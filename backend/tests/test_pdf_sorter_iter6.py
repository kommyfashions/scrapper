"""Iteration 6 - PDF Sorter fixes:
 (1) Latest Run shows Matched + Unmatched
 (2) Downloads work more than once (cache-control headers)
 (3) admin/reset wipes runs + files
 (4) Numbers consistent (sorted + unmatched = total; TIER1+TIER2=MASTER=total)
 (5) Default courier rules auto-seeded on startup
"""
import io
import os
import time
from pathlib import Path

import pytest
import requests
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

REQUIRED_COURIERS = [
    "Delhivery", "Ecom Express", "Xpressbees", "Shadowfax", "DTDC",
    "India Post", "Bluedart", "Ekart", "Valmo",
]


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": "admin@meesho-dash.local", "password": "admin123"},
                      timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def client(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def _make_fake_pdf(path: Path, labels):
    c = canvas.Canvas(str(path), pagesize=A4)
    for sku, size, ono, cr in labels:
        c.drawString(50, 800, "Product Details")
        c.drawString(50, 770, "SKU Size Qty Color Order No.")
        c.drawString(50, 750, f"{sku} {size} 1 Blue {ono}")
        c.drawString(50, 700, f"Handled by {cr}")
        c.showPage()
    c.save()


# ----- Default courier rules seeded on startup -----
def test_default_courier_rules_seeded(client):
    r = client.get(f"{API}/pdf-sorter/config", timeout=10)
    assert r.status_code == 200
    names_ci = {row["courier_name"].lower() for row in r.json().get("courier_rules", [])}
    missing = [c for c in REQUIRED_COURIERS if c.lower() not in names_ci]
    assert not missing, f"missing default couriers: {missing}"


# ----- admin/reset wipes runs + directories -----
def test_admin_reset_wipes_everything(client):
    r = client.post(f"{API}/pdf-sorter/admin/reset", timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok") is True
    assert "runs_deleted" in data and isinstance(data["runs_deleted"], int)

    a = client.get(f"{API}/pdf-sorter/analytics", timeout=15)
    assert a.status_code == 200
    j = a.json()
    assert j["total_runs"] == 0
    assert j["total_files"] == 0
    assert j["total_pages"] == 0
    assert j["unknown_sku_total"] == 0
    assert j["latest_run"] is None

    # Files on disk removed
    for base in ("/app/backend/pdf_sorter/uploads", "/app/backend/pdf_sorter/outputs"):
        p = Path(base)
        if p.exists():
            children = [c for c in p.iterdir() if c.is_dir()]
            assert children == [], f"expected {base} empty, got {children}"


# ----- Upload → analytics consistency + download twice + Matched count -----
@pytest.fixture(scope="module")
def fresh_run(client, tmp_path_factory):
    # Reset then upload
    client.post(f"{API}/pdf-sorter/admin/reset", timeout=15)
    pdf_path = tmp_path_factory.mktemp("pdfs") / "fake.pdf"
    # 3 labels: 1 known (SKU1 → Vertis/Blue), 2 unknown → sorted=1, unmatched=2
    _make_fake_pdf(pdf_path, [
        ("SKU1", "M", "12345678901234", "Delhivery"),
        ("SKUX", "L", "12345678901235", "Ecom Express"),
        ("SKUY", "S", "12345678901236", "Xpressbees"),
    ])
    with pdf_path.open("rb") as fh:
        r = client.post(f"{API}/pdf-sorter/process",
                        files=[("files", ("fake.pdf", fh, "application/pdf"))],
                        timeout=120)
    assert r.status_code == 200, r.text
    return r.json()


def test_process_returns_expected_shape(fresh_run):
    assert fresh_run["total_files"] == 1
    assert fresh_run["total_pages"] == 3
    assert fresh_run["unknown_sku"] == 2  # SKUX, SKUY not in PM
    # sorted = total_pages - unknown_sku = 1
    sorted_ = fresh_run["total_pages"] - fresh_run["unknown_sku"]
    assert sorted_ == 1
    assert set(fresh_run["files"]) == {
        "MASTER_PRINT.pdf", "TIER1_HIGH_VOLUME.pdf", "TIER2_LOW_VOLUME.pdf"}


def test_analytics_matches_run(client, fresh_run):
    a = client.get(f"{API}/pdf-sorter/analytics", timeout=15).json()
    assert a["total_runs"] == 1
    assert a["total_files"] == fresh_run["total_files"]
    assert a["total_pages"] == fresh_run["total_pages"]
    assert a["unknown_sku_total"] == fresh_run["unknown_sku"]

    lr = a["latest_run"]
    assert lr is not None
    assert lr["run_id"] == fresh_run["run_id"]
    assert lr["total_pages"] == 3
    assert lr["unmatched"] == 2
    assert lr["sorted"] == 1  # total_pages - unmatched
    # Consistency: sorted + unmatched = total_pages
    assert lr["sorted"] + lr["unmatched"] == lr["total_pages"]


def test_analytics_date_filter_today(client, fresh_run):
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    a = client.get(f"{API}/pdf-sorter/analytics",
                   params={"start_date": today, "end_date": today},
                   timeout=15).json()
    assert a["total_runs"] == 1
    assert a["total_pages"] == 3


def _download(client, run_id, fname, ts=None):
    params = {"_ts": ts} if ts is not None else None
    return client.get(f"{API}/pdf-sorter/runs/{run_id}/files/{fname}",
                      params=params, timeout=30)


def test_download_headers_and_filename(client, fresh_run):
    r = _download(client, fresh_run["run_id"], "TIER1_HIGH_VOLUME.pdf")
    assert r.status_code == 200
    assert r.headers.get("Content-Type", "").startswith("application/pdf")
    cd = r.headers.get("Content-Disposition", "")
    # Pattern: TIER1_HIGH_VOLUME__YYYY-MM-DD_HH-MM-SS.pdf
    import re
    assert re.search(r'filename="?TIER1_HIGH_VOLUME__\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.pdf"?', cd), cd
    cc = r.headers.get("Cache-Control", "")
    for token in ("no-store", "no-cache", "must-revalidate", "max-age=0"):
        assert token in cc, f"Cache-Control missing '{token}': {cc}"
    assert int(r.headers.get("Content-Length", "0")) > 0 or len(r.content) > 0


def test_download_twice_same_url(client, fresh_run):
    """Regression: 'downloads only work once' bug."""
    for i, ts in enumerate([None, int(time.time()*1000), int(time.time()*1000)+1]):
        r = _download(client, fresh_run["run_id"], "MASTER_PRINT.pdf", ts=ts)
        assert r.status_code == 200, f"attempt {i} got {r.status_code}"
        assert len(r.content) > 0, f"attempt {i} empty body"
        # It's a valid PDF
        assert r.content[:4] == b"%PDF"


def test_tier1_plus_tier2_equals_master_equals_total(client, fresh_run):
    """TIER1 + TIER2 page counts should equal MASTER page count = total_pages."""
    counts = {}
    for f in ("MASTER_PRINT.pdf", "TIER1_HIGH_VOLUME.pdf", "TIER2_LOW_VOLUME.pdf"):
        r = _download(client, fresh_run["run_id"], f)
        assert r.status_code == 200
        reader = PdfReader(io.BytesIO(r.content))
        counts[f] = len(reader.pages)
    assert counts["TIER1_HIGH_VOLUME.pdf"] + counts["TIER2_LOW_VOLUME.pdf"] == counts["MASTER_PRINT.pdf"]
    assert counts["MASTER_PRINT.pdf"] == fresh_run["total_pages"], counts


def test_download_404_for_missing_file(client, fresh_run):
    r = _download(client, fresh_run["run_id"], "NOPE.pdf")
    assert r.status_code == 404
