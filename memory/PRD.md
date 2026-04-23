# Ecommerce Data Extractor — PRD

## Original Problem Statement
Build a full-stack web app ("Ecommerce Data Extractor") on the FARM stack
(FastAPI + React + MongoDB, no Celery/Redis) where a user pastes any
e-commerce product listing / category / catalog URL and a background
Playwright scraper autonomously walks all pagination and outputs a CSV in a
fixed 200+ column Swagify schema, with live extraction logs streamed over SSE.

## Tech
- Backend: FastAPI, Motor (async Mongo), Playwright (chromium, async), BeautifulSoup, Python `csv`.
- Background jobs: FastAPI BackgroundTasks + asyncio queue + worker pool (MAX_CONCURRENT_JOBS=3).
- Real-time logs: SSE via FastAPI StreamingResponse (`/api/jobs/{id}/logs/stream`).
- Frontend: React + Tailwind + shadcn/ui. **Dark theme only.** Emerald accent.
- Auth: JWT, seeded single admin (`admin@extractor.app` / `admin123`). JWT_SECRET auto-generated on first run.

## User Personas
- **Operator / Data ops engineer** — pastes catalog URLs, monitors jobs, downloads Swagify-formatted CSVs.

## Data Model (Mongo)
- `users` { id, email (unique), password_hash, created_at }
- `jobs`  { id, user_id, url, status (queued|running|completed|failed), created_at, started_at, finished_at, pages_scraped, products_count, error }
- `products` { id, job_id, data (dict keyed by Swagify column names), scraped_at }
- `logs`  { id, job_id, level, message, meta, ts }

## Pages
1. `/login` — email + password → `POST /api/auth/login`.
2. `/` dashboard — URL input + Extract button + jobs table.
3. `/jobs/:id` — detail: status + metadata + (future) product table, SSE logs, CSV download.

---

## Implementation Status

### Phase 1 — Skeleton (DONE, Feb 2026)
**Backend**
- FastAPI app at `/app/backend/server.py`.
- Motor/Mongo via `MONGO_URL` + `DB_NAME` from `.env`.
- JWT auth (pyjwt + bcrypt). `JWT_SECRET` auto-generated on first startup and persisted to `/app/backend/.env`.
- Endpoints (all `/api` prefix, protected except login):
  - `POST /api/auth/login` { email, password } → { access_token }
  - `GET  /api/auth/me`
  - `POST /api/jobs` { url } → 201, status=`queued` (URL validated: http/https + valid host)
  - `GET  /api/jobs` (current user, newest first)
  - `GET  /api/jobs/{id}`
  - `DELETE /api/jobs/{id}` → 204, cascades products + logs
- Admin seed on startup (`admin@extractor.app` / `admin123`).
- Swagger UI at `/api/docs`.

**Frontend**
- Dark-only dashboard, near-black (`#0a0a0a`) backgrounds, emerald-500 accent, subtle `#262626` borders.
- Pages: `/login`, `/`, `/jobs/:id`.
- shadcn/ui: Button, Input, Label, Table, Badge, AlertDialog, Sonner (toasts).
- Axios instance with Bearer token interceptor; 401 → redirect to `/login`.
- `ProtectedRoute` guard.
- `data-testid` attributes on all interactive elements.

### Phase 2 — Scraper (PENDING)
- Playwright-based autonomous scraper with intelligence probe (framework detect, XHR intercept).
- Selector strategies: JSON-LD → microdata → OG → heuristic DOM.
- Auto-pagination: rel=next, aria-label, `.next`, "Load more", infinite scroll.
- UA rotation (5 UAs), 0.5-2s jitter, exp backoff 2/4/8s on 429, 3-retry cap.
- Caps: `MAX_PAGES=500`, `MAX_PRODUCTS=10000`, `MAX_CONCURRENT_JOBS=3`.
- Background worker pool + asyncio queue.
- SSE live log stream.

### Phase 3 — CSV (PENDING)
- 200+ column Swagify schema (exact order). Unmapped → empty string.
- CSV download endpoint + copy-to-clipboard (CSV / plain text) on job detail.

---

## Backlog (prioritised)
- **P0** Phase 2 scraper + SSE + worker pool.
- **P0** Phase 3 Swagify CSV export + job detail product table.
- **P1** Cancel / retry job actions.
- **P1** Multi-user support (sign-up flow + per-user admin page).
- **P2** Scheduled / recurring scrapes.
- **P2** Diff detection between scrape runs.

## Next Tasks
1. Await Phase 2 brief (scraper + SSE + worker pool).
2. Await Phase 3 brief (Swagify 200-column schema).
