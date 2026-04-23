"""Backend API tests for Ecommerce Data Extractor Phase 1."""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ecom-extractor-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@extractor.app"
ADMIN_PASSWORD = "admin123"


@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---- Auth ----
class TestAuth:
    def test_login_ok(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200
        d = r.json()
        assert d["token_type"] == "bearer"
        assert isinstance(d["access_token"], str) and len(d["access_token"]) > 20

    def test_login_wrong_password(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"})
        assert r.status_code == 401

    def test_login_invalid_email(self):
        r = requests.post(f"{API}/auth/login", json={"email": "not-an-email", "password": "x"})
        assert r.status_code == 422

    def test_me_no_token(self):
        r = requests.get(f"{API}/auth/me")
        assert r.status_code == 401

    def test_me_with_token(self, auth):
        r = requests.get(f"{API}/auth/me", headers=auth)
        assert r.status_code == 200
        d = r.json()
        assert d["email"] == ADMIN_EMAIL
        assert "id" in d and "created_at" in d


# ---- Jobs CRUD ----
class TestJobs:
    def test_list_no_token(self):
        r = requests.get(f"{API}/jobs")
        assert r.status_code == 401

    def test_list_ok(self, auth):
        r = requests.get(f"{API}/jobs", headers=auth)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_create_ok(self, auth):
        r = requests.post(f"{API}/jobs", headers=auth, json={"url": "https://example.com"})
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["status"] == "queued"
        assert d["products_count"] == 0
        assert d["pages_scraped"] == 0
        assert d["url"] == "https://example.com"
        # cleanup
        requests.delete(f"{API}/jobs/{d['id']}", headers=auth)

    def test_create_invalid_url(self, auth):
        r = requests.post(f"{API}/jobs", headers=auth, json={"url": "not-a-url"})
        assert r.status_code == 422

    def test_create_ftp_rejected(self, auth):
        r = requests.post(f"{API}/jobs", headers=auth, json={"url": "ftp://example.com"})
        assert r.status_code == 422

    def test_create_host_without_dot(self, auth):
        r = requests.post(f"{API}/jobs", headers=auth, json={"url": "http://nohost"})
        assert r.status_code == 422

    def test_get_by_id_and_404(self, auth):
        c = requests.post(f"{API}/jobs", headers=auth, json={"url": "https://example.org/page"})
        assert c.status_code == 201
        jid = c.json()["id"]

        g = requests.get(f"{API}/jobs/{jid}", headers=auth)
        assert g.status_code == 200
        assert g.json()["id"] == jid

        # Random UUID 404 (user-scoped)
        r404 = requests.get(f"{API}/jobs/{uuid.uuid4()}", headers=auth)
        assert r404.status_code == 404

        # Delete
        d = requests.delete(f"{API}/jobs/{jid}", headers=auth)
        assert d.status_code == 204
        # Now 404
        g2 = requests.get(f"{API}/jobs/{jid}", headers=auth)
        assert g2.status_code == 404

    def test_list_newest_first(self, auth):
        c1 = requests.post(f"{API}/jobs", headers=auth, json={"url": "https://a.example.com"})
        c2 = requests.post(f"{API}/jobs", headers=auth, json={"url": "https://b.example.com"})
        assert c1.status_code == 201 and c2.status_code == 201
        r = requests.get(f"{API}/jobs", headers=auth)
        ids = [j["id"] for j in r.json()]
        assert ids.index(c2.json()["id"]) < ids.index(c1.json()["id"])
        for jid in (c1.json()["id"], c2.json()["id"]):
            requests.delete(f"{API}/jobs/{jid}", headers=auth)


# ---- Docs ----
class TestDocs:
    def test_swagger_ui(self):
        r = requests.get(f"{API}/docs")
        assert r.status_code == 200
        assert "swagger" in r.text.lower()
