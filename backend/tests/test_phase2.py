"""Phase 2 backend tests: scraper, worker pool, SSE logs."""
import os
import time
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ecom-extractor-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"email": "admin@extractor.app", "password": "admin123"}
SHORT_URL = "https://books.toscrape.com/catalogue/category/books_1/page-1.html"
INVALID_URL = "https://nonexistent-host-xyz123.invalid/"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login", json=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


def _wait_terminal(jid, headers, timeout=180):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        r = requests.get(f"{API}/jobs/{jid}", headers=headers, timeout=15)
        if r.status_code == 200:
            last = r.json()
            if last["status"] in ("completed", "failed", "cancelled"):
                return last
        time.sleep(2)
    return last


# ---- End-to-end scrape ----
class TestScrape:
    def test_scrape_short_completes(self, auth):
        r = requests.post(f"{API}/jobs", headers=auth, json={"url": SHORT_URL})
        assert r.status_code == 201
        jid = r.json()["id"]
        assert r.json()["status"] == "queued"
        final = _wait_terminal(jid, auth, timeout=180)
        assert final is not None
        assert final["status"] == "completed", f"Job ended with {final}"
        assert final["pages_scraped"] >= 1
        assert final["products_count"] >= 10
        pytest.scrape_job_id = jid  # share

    def test_products_list(self, auth):
        jid = pytest.scrape_job_id
        r = requests.get(f"{API}/jobs/{jid}/products?limit=5", headers=auth)
        assert r.status_code == 200
        ps = r.json()
        assert len(ps) >= 1
        for p in ps:
            assert p["job_id"] == jid
            assert isinstance(p["data"], dict)
            assert p["data"].get("name")
            price = p["data"].get("price")
            assert isinstance(price, (int, float)) and price > 0

    def test_products_wrong_id_404(self, auth):
        r = requests.get(f"{API}/jobs/{uuid.uuid4()}/products", headers=auth)
        assert r.status_code == 404

    def test_logs_latest_first(self, auth):
        jid = pytest.scrape_job_id
        r = requests.get(f"{API}/jobs/{jid}/logs?limit=20", headers=auth)
        assert r.status_code == 200
        logs = r.json()
        assert len(logs) >= 1
        for lg in logs:
            assert {"id", "job_id", "level", "message", "meta", "ts"} <= set(lg.keys())
            assert lg["job_id"] == jid
        ts = [l["ts"] for l in logs]
        assert ts == sorted(ts, reverse=True)

    def test_logs_level_filter(self, auth):
        jid = pytest.scrape_job_id
        r = requests.get(f"{API}/jobs/{jid}/logs?level=INFO&limit=50", headers=auth)
        assert r.status_code == 200
        for lg in r.json():
            assert lg["level"] == "INFO"


# ---- SSE ----
class TestSSE:
    def test_sse_no_token_401(self, auth):
        jid = pytest.scrape_job_id
        r = requests.get(f"{API}/jobs/{jid}/logs/stream", timeout=10)
        assert r.status_code == 401

    def test_sse_streams(self, token, auth):
        jid = pytest.scrape_job_id
        url = f"{API}/jobs/{jid}/logs/stream?token={token}"
        with requests.get(url, stream=True, timeout=20) as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers.get("content-type", "")
            got = False
            end = time.time() + 15
            for raw in r.iter_lines(decode_unicode=True):
                if raw and raw.startswith("data:"):
                    got = True
                    break
                if time.time() > end:
                    break
            assert got, "no SSE data received"


# ---- Concurrency guard ----
class TestConcurrency:
    def test_max_3_running(self, auth):
        ids = []
        for _ in range(5):
            r = requests.post(f"{API}/jobs", headers=auth, json={"url": SHORT_URL})
            assert r.status_code == 201
            ids.append(r.json()["id"])
        time.sleep(5)
        statuses = []
        for jid in ids:
            r = requests.get(f"{API}/jobs/{jid}", headers=auth)
            statuses.append(r.json()["status"])
        running = sum(1 for s in statuses if s == "running")
        queued = sum(1 for s in statuses if s == "queued")
        # Allow some to have already completed (fast short URL); but running must be <= 3
        assert running <= 3, f"too many running: {statuses}"
        # If any queued, running should be exactly 3
        if queued > 0:
            assert running == 3, f"expected 3 running when queued>0: {statuses}"
        # cleanup: wait for completion
        for jid in ids:
            _wait_terminal(jid, auth, timeout=180)


# ---- Invalid URL ----
class TestInvalidUrl:
    def test_unreachable_fails(self, auth):
        r = requests.post(f"{API}/jobs", headers=auth, json={"url": INVALID_URL})
        assert r.status_code == 201
        jid = r.json()["id"]
        final = _wait_terminal(jid, auth, timeout=120)
        assert final is not None
        assert final["status"] == "failed", f"expected failed, got {final}"
        assert final.get("error"), "error field should be set"


# ---- Cancel (delete running job) ----
class TestCancel:
    def test_delete_while_running(self, auth):
        r = requests.post(f"{API}/jobs", headers=auth, json={"url": "https://books.toscrape.com/"})
        assert r.status_code == 201
        jid = r.json()["id"]
        # wait until running
        end = time.time() + 20
        while time.time() < end:
            g = requests.get(f"{API}/jobs/{jid}", headers=auth)
            if g.status_code == 200 and g.json()["status"] == "running":
                break
            time.sleep(1)
        d = requests.delete(f"{API}/jobs/{jid}", headers=auth)
        assert d.status_code == 204
        # Should 404 now
        g = requests.get(f"{API}/jobs/{jid}", headers=auth)
        assert g.status_code == 404


# ---- Lifespan (no deprecated on_event) ----
class TestLifespan:
    def test_no_on_event_in_source(self):
        with open("/app/backend/server.py") as f:
            src = f.read()
        assert "@app.on_event" not in src
        assert "lifespan=lifespan" in src
