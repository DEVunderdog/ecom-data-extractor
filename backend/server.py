"""Ecommerce Data Extractor - backend.

Phase 1: auth + jobs CRUD.
Phase 2: background Playwright scraper (worker pool) + SSE live logs.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncGenerator, Optional
from urllib.parse import urlparse

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field, field_validator
from starlette.middleware.cors import CORSMiddleware

from csv_mapper import SWAGIFY_HEADERS, to_swagify_row
from worker import WorkerPool

# ---------------------------------------------------------------------------
# Env + JWT secret bootstrap
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).parent
ENV_PATH = ROOT_DIR / ".env"
load_dotenv(ENV_PATH)


def _ensure_jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET")
    if secret:
        return secret
    secret = secrets.token_hex(32)
    with ENV_PATH.open("a", encoding="utf-8") as f:
        f.write(f'\nJWT_SECRET="{secret}"\n')
    os.environ["JWT_SECRET"] = secret
    return secret


JWT_SECRET = _ensure_jwt_secret()
JWT_ALGO = "HS256"
JWT_TTL_HOURS = 24

# ---------------------------------------------------------------------------
# Mongo
# ---------------------------------------------------------------------------
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

# Shared worker pool, started in lifespan
worker_pool = WorkerPool(db)

# ---------------------------------------------------------------------------
# App lifespan: startup + shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # indexes
    await db.users.create_index("email", unique=True)
    await db.jobs.create_index([("user_id", 1), ("created_at", -1)])
    await db.products.create_index("job_id")
    await db.logs.create_index([("job_id", 1), ("ts", 1)])

    # seed admin
    if await db.users.count_documents({}) == 0:
        admin = {
            "id": str(uuid.uuid4()),
            "email": "admin@extractor.app",
            "password_hash": bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode("utf-8"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one(dict(admin))
        logging.getLogger(__name__).info("Seeded admin user: admin@extractor.app")

    # start worker pool
    await worker_pool.start()
    try:
        yield
    finally:
        await worker_pool.stop()
        client.close()


app = FastAPI(
    title="Ecommerce Data Extractor API",
    version="0.2.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)
api_router = APIRouter(prefix="/api")
security = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    created_at: str


class JobCreate(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def _valid_http_url(cls, v: str) -> str:
        v = v.strip()
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("URL must start with http:// or https://")
        if not parsed.netloc or "." not in parsed.netloc:
            raise ValueError("URL must have a valid host")
        return v


class Job(BaseModel):
    id: str
    user_id: str
    url: str
    status: str
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    pages_scraped: int = 0
    products_count: int = 0
    error: Optional[str] = None


class LogEntry(BaseModel):
    id: str
    job_id: str
    level: str
    message: str
    meta: dict = Field(default_factory=dict)
    ts: str


class Product(BaseModel):
    id: str
    job_id: str
    data: dict
    scraped_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _create_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_TTL_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await db.users.find_one({"id": payload.get("sub")}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _job_to_public(doc: dict) -> Job:
    return Job(
        id=doc["id"],
        user_id=doc["user_id"],
        url=doc["url"],
        status=doc["status"],
        created_at=doc["created_at"],
        started_at=doc.get("started_at"),
        finished_at=doc.get("finished_at"),
        pages_scraped=doc.get("pages_scraped", 0),
        products_count=doc.get("products_count", 0),
        error=doc.get("error"),
    )


async def _require_own_job(job_id: str, user: dict) -> dict:
    doc = await db.jobs.find_one({"id": job_id, "user_id": user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    return doc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@api_router.get("/")
async def root():
    return {"name": "Ecommerce Data Extractor", "version": "0.2.0"}


@api_router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    user = await db.users.find_one({"email": body.email.lower()}, {"_id": 0})
    if not user or not _verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = _create_token(user["id"], user["email"])
    return TokenResponse(access_token=token)


@api_router.get("/auth/me", response_model=UserPublic)
async def me(user: dict = Depends(get_current_user)):
    return UserPublic(id=user["id"], email=user["email"], created_at=user["created_at"])


@api_router.post("/jobs", response_model=Job, status_code=201)
async def create_job(body: JobCreate, user: dict = Depends(get_current_user)):
    job = {
        "id": str(uuid.uuid4()),
        "user_id": user["id"],
        "url": body.url,
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "started_at": None,
        "finished_at": None,
        "pages_scraped": 0,
        "products_count": 0,
        "error": None,
    }
    await db.jobs.insert_one(dict(job))
    await worker_pool.enqueue(job["id"])
    return _job_to_public(job)


@api_router.get("/jobs", response_model=list[Job])
async def list_jobs(user: dict = Depends(get_current_user)):
    cursor = db.jobs.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1)
    docs = await cursor.to_list(length=500)
    return [_job_to_public(d) for d in docs]


@api_router.get("/jobs/{job_id}", response_model=Job)
async def get_job(job_id: str, user: dict = Depends(get_current_user)):
    doc = await _require_own_job(job_id, user)
    return _job_to_public(doc)


@api_router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(job_id: str, user: dict = Depends(get_current_user)):
    res = await db.jobs.delete_one({"id": job_id, "user_id": user["id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Job not found")
    await db.products.delete_many({"job_id": job_id})
    await db.logs.delete_many({"job_id": job_id})
    return None


@api_router.get("/jobs/{job_id}/products", response_model=list[Product])
async def list_products(
    job_id: str,
    user: dict = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    await _require_own_job(job_id, user)
    cursor = (
        db.products.find({"job_id": job_id}, {"_id": 0})
        .sort("scraped_at", 1)
        .skip(offset)
        .limit(limit)
    )
    docs = await cursor.to_list(length=limit)
    return [Product(**d) for d in docs]


@api_router.get("/jobs/{job_id}/logs", response_model=list[LogEntry])
async def list_logs(
    job_id: str,
    user: dict = Depends(get_current_user),
    level: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    await _require_own_job(job_id, user)
    q: dict = {"job_id": job_id}
    if level:
        q["level"] = level.upper()
    cursor = (
        db.logs.find(q, {"_id": 0})
        .sort("ts", -1)
        .skip(offset)
        .limit(limit)
    )
    docs = await cursor.to_list(length=limit)
    return [LogEntry(**d) for d in docs]


@api_router.get("/jobs/{job_id}/logs/stream")
async def stream_logs(
    job_id: str,
    request: Request,
    token: Optional[str] = Query(None),
):
    """SSE log stream. Accepts JWT via ?token= since EventSource cannot set headers."""
    # Manual auth (EventSource can't set Authorization header reliably)
    if not token:
        raise HTTPException(status_code=401, detail="token query param required")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await db.users.find_one({"id": payload.get("sub")}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    await _require_own_job(job_id, user)

    async def gen() -> AsyncGenerator[bytes, None]:
        # Replay the last 50 logs (oldest first), then tail.
        seen_ts: Optional[str] = None
        initial = await db.logs.find({"job_id": job_id}, {"_id": 0}).sort("ts", -1).limit(50).to_list(50)
        initial.reverse()
        for doc in initial:
            yield f"data: {json.dumps(doc)}\n\n".encode("utf-8")
            seen_ts = doc["ts"]

        # Tail loop
        idle_ticks = 0
        while True:
            if await request.is_disconnected():
                return
            q: dict = {"job_id": job_id}
            if seen_ts:
                q["ts"] = {"$gt": seen_ts}
            batch = await db.logs.find(q, {"_id": 0}).sort("ts", 1).limit(100).to_list(100)
            if batch:
                idle_ticks = 0
                for doc in batch:
                    yield f"data: {json.dumps(doc)}\n\n".encode("utf-8")
                    seen_ts = doc["ts"]
            else:
                # send heartbeat every ~10 idle ticks (~5s)
                idle_ticks += 1
                if idle_ticks % 10 == 0:
                    yield b": ping\n\n"
                # Stop tailing if the job is terminal AND we've caught up
                job = await db.jobs.find_one({"id": job_id}, {"_id": 0, "status": 1})
                if not job:
                    return
                if job["status"] in ("completed", "failed", "cancelled") and idle_ticks > 6:
                    # emit a sentinel event then close
                    yield f"event: end\ndata: {json.dumps({'status': job['status']})}\n\n".encode("utf-8")
                    return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@api_router.get("/jobs/{job_id}/export.csv")
async def export_csv(job_id: str, user: dict = Depends(get_current_user)):
    await _require_own_job(job_id, user)
    return StreamingResponse(
        _stream_export(job_id, delimiter=","),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="job_{job_id}_{int(datetime.now(timezone.utc).timestamp())}.csv"',
            "Cache-Control": "no-store",
        },
    )


@api_router.get("/jobs/{job_id}/export.txt")
async def export_txt(job_id: str, user: dict = Depends(get_current_user)):
    await _require_own_job(job_id, user)
    return StreamingResponse(
        _stream_export(job_id, delimiter="\t"),
        media_type="text/tab-separated-values",
        headers={"Cache-Control": "no-store"},
    )


async def _stream_export(job_id: str, delimiter: str) -> AsyncGenerator[bytes, None]:
    """Yield Swagify-formatted rows for a job, streamed."""
    import csv as _csv
    import io as _io

    def _serialize(row_values: list[str]) -> bytes:
        buf = _io.StringIO()
        w = _csv.writer(buf, delimiter=delimiter, quoting=_csv.QUOTE_MINIMAL, lineterminator="\n")
        w.writerow(row_values)
        return buf.getvalue().encode("utf-8")

    # Header
    yield _serialize(SWAGIFY_HEADERS)

    cursor = db.products.find({"job_id": job_id}, {"_id": 0}).sort("scraped_at", 1)
    async for doc in cursor:
        mapped = to_swagify_row(doc.get("data") or {})
        yield _serialize([mapped.get(col, "") for col in SWAGIFY_HEADERS])


# ---------------------------------------------------------------------------
app.include_router(api_router)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
