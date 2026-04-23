"""Phase 3 backend tests: Swagify CSV export + mapper + product table endpoints."""
import csv
import io
import json
import os
import time
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ecom-extractor-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"email": "admin@extractor.app", "password": "admin123"}
SHORT_URL = "https://books.toscrape.com/catalogue/category/books_1/page-1.html"

# Load canonical header list from the repo (source of truth)
HEADERS_JSON = "/app/backend/data/swagify_headers.json"
with open(HEADERS_JSON) as f:
    SWAGIFY_HEADERS = json.load(f)


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{API}/auth/login", json=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def completed_job(auth):
    """Find a completed job with products, else create one on SHORT_URL."""
    r = requests.get(f"{API}/jobs", headers=auth)
    assert r.status_code == 200
    for j in r.json():
        if j["status"] == "completed" and j.get("products_count", 0) > 0:
            return j
    # create fresh
    r = requests.post(f"{API}/jobs", headers=auth, json={"url": SHORT_URL})
    jid = r.json()["id"]
    end = time.time() + 180
    while time.time() < end:
        g = requests.get(f"{API}/jobs/{jid}", headers=auth)
        if g.json()["status"] in ("completed", "failed"):
            return g.json()
        time.sleep(2)
    pytest.fail("could not obtain completed job")


class TestHeadersFile:
    def test_headers_count_and_bounds(self):
        assert len(SWAGIFY_HEADERS) >= 190
        assert SWAGIFY_HEADERS[0] == "Swagify SKU"
        assert SWAGIFY_HEADERS[-1] == "Additional Infos"


class TestMapper:
    def test_mapper_fields(self):
        from backend.csv_mapper import to_swagify_row, SWAGIFY_HEADERS as H
        p = {
            "name": "Widget",
            "price": 12.5,
            "image_url": "http://x/i.jpg",
            "sku": "SKU1",
            "category": "A > B > C",
            "availability": "In stock",
            "rating": 4.5,
            "review_count": 10,
            "product_url": "http://x/p",
        }
        row = to_swagify_row(p)
        assert row["Product Name"] == "Widget"
        assert row["Price1"] == "12.5"
        assert row["Main Image"] == "http://x/i.jpg"
        assert row["Gallery Images"] == "http://x/i.jpg"
        assert row["Lifestyle Image"] == "http://x/i.jpg"
        assert row["Swagify SKU"] == "SKU1"
        assert row["Supplier SKU"] == "SKU1"
        assert row["Variant SKU"] == "SKU1"
        assert row["Parent SKU"] == "SKU1"
        assert row["Category-1"] == "A"
        assert row["Sub-Category-1-1"] == "B"
        assert row["Sub-Category-1-1-1"] == "C"
        assert row["Inventory Quantity"] == "1"
        assert row["Active"] == "1"
        assert row["Product Type"] == "Product"
        assert row["Variant Type"] == "Product"
        assert row["Minimum Order Qty"] == "1"
        assert row["QtyBreak1"] == "1"
        leftover = json.loads(row["Additional Infos"])
        assert leftover.get("rating") == 4.5
        assert leftover.get("review_count") == 10
        assert leftover.get("product_url") == "http://x/p"

    def test_out_of_stock(self):
        from backend.csv_mapper import to_swagify_row
        assert to_swagify_row({"name": "n", "availability": "Out of stock"})["Inventory Quantity"] == "0"
        assert to_swagify_row({"name": "n", "availability": "weird"})["Inventory Quantity"] == ""
        assert to_swagify_row({"name": ""})["Active"] == ""


class TestExportCSV:
    def test_auth_required(self, completed_job):
        r = requests.get(f"{API}/jobs/{completed_job['id']}/export.csv")
        assert r.status_code == 401

    def test_csv_headers_and_content(self, auth, completed_job):
        jid = completed_job["id"]
        r = requests.get(f"{API}/jobs/{jid}/export.csv", headers=auth)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd and f"job_{jid}" in cd and ".csv" in cd
        reader = csv.reader(io.StringIO(r.text))
        rows = list(reader)
        assert rows[0] == SWAGIFY_HEADERS, f"first differ at: {[i for i,(a,b) in enumerate(zip(rows[0],SWAGIFY_HEADERS)) if a!=b][:5]}"
        assert len(rows[0]) == 217
        assert len(rows) - 1 == completed_job["products_count"]
        # every row has same width
        for row in rows[1:5]:
            assert len(row) == 217
        # Product Name column non-empty for most rows
        name_idx = SWAGIFY_HEADERS.index("Product Name")
        names = [row[name_idx] for row in rows[1:]]
        assert sum(1 for n in names if n) >= len(names) * 0.9

    def test_txt_tsv_same_content(self, auth, completed_job):
        jid = completed_job["id"]
        r = requests.get(f"{API}/jobs/{jid}/export.txt", headers=auth)
        assert r.status_code == 200
        assert "tab-separated" in r.headers.get("content-type", "")
        # Header line split by tab
        first_line = r.text.split("\n", 1)[0]
        cols = first_line.split("\t")
        assert cols == SWAGIFY_HEADERS

    def test_other_user_404(self, auth, completed_job):
        # Register a second user, use their token to hit this job
        email = f"t_{uuid.uuid4().hex[:8]}@t.io"
        rr = requests.post(f"{API}/auth/register", json={"email": email, "password": "xxxxxx123"})
        if rr.status_code not in (200, 201):
            pytest.skip(f"register not available: {rr.status_code}")
        tok = rr.json().get("access_token")
        if not tok:
            lg = requests.post(f"{API}/auth/login", json={"email": email, "password": "xxxxxx123"})
            tok = lg.json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        r = requests.get(f"{API}/jobs/{completed_job['id']}/export.csv", headers=h)
        assert r.status_code == 404

    def test_unknown_job_404(self, auth):
        r = requests.get(f"{API}/jobs/{uuid.uuid4()}/export.csv", headers=auth)
        assert r.status_code == 404
