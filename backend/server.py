"""Ecommerce Data Extractor - Phase 1 backend (auth + jobs CRUD)."""
from __future__ import annotations

import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field, field_validator
from starlette.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------------
# Env + JWT secret bootstrap
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).parent
ENV_PATH = ROOT_DIR / ".env"
load_dotenv(ENV_PATH)


def _ensure_jwt_secret() -> str:
    """Generate JWT_SECRET on first run and persist it in /app/backend/.env."""
    secret = os.environ.get("JWT_SECRET")
    if secret:
        return secret
    secret = secrets.token_hex(32)
    # Append to .env so it survives restarts
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

# ---------------------------------------------------------------------------
# App + router
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Ecommerce Data Extractor API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url="/api/redoc",
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
        try:
            parsed = urlparse(v)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("Invalid URL") from exc
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:  # noqa: BLE001
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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@api_router.get("/")
async def root():
    return {"name": "Ecommerce Data Extractor", "version": "0.1.0"}


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
    return _job_to_public(job)


@api_router.get("/jobs", response_model=list[Job])
async def list_jobs(user: dict = Depends(get_current_user)):
    cursor = db.jobs.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1)
    docs = await cursor.to_list(length=500)
    return [_job_to_public(d) for d in docs]


@api_router.get("/jobs/{job_id}", response_model=Job)
async def get_job(job_id: str, user: dict = Depends(get_current_user)):
    doc = await db.jobs.find_one({"id": job_id, "user_id": user["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_public(doc)


@api_router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(job_id: str, user: dict = Depends(get_current_user)):
    res = await db.jobs.delete_one({"id": job_id, "user_id": user["id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Job not found")
    await db.products.delete_many({"job_id": job_id})
    await db.logs.delete_many({"job_id": job_id})
    return None


# ---------------------------------------------------------------------------
# Startup: seed admin + indexes
# ---------------------------------------------------------------------------
SEED_ADMIN_EMAIL = "admin@extractor.app"
SEED_ADMIN_PASSWORD = "admin123"


@app.on_event("startup")
async def _on_startup():
    # Unique email index
    await db.users.create_index("email", unique=True)
    await db.jobs.create_index([("user_id", 1), ("created_at", -1)])
    await db.products.create_index("job_id")
    await db.logs.create_index([("job_id", 1), ("ts", 1)])

    # Seed admin if no users exist
    existing = await db.users.count_documents({})
    if existing == 0:
        admin = {
            "id": str(uuid.uuid4()),
            "email": SEED_ADMIN_EMAIL,
            "password_hash": _hash_password(SEED_ADMIN_PASSWORD),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one(dict(admin))
        logging.getLogger(__name__).info("Seeded admin user: %s", SEED_ADMIN_EMAIL)


@app.on_event("shutdown")
async def _on_shutdown():
    client.close()


# ---------------------------------------------------------------------------
# Middleware + include
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
