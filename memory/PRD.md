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

### Phase 2 — Scraper + worker pool + SSE (DONE, Feb 2026)
**Backend**
- `/app/backend/scraper.py` — async Playwright scraper:
  - Intelligence probe (framework detect + 3s XHR/JSON sniff for API endpoints).
  - 4-tier extraction: JSON-LD → microdata → Open Graph → heuristic DOM scan (most-repeated container with price+heading).
  - Auto-pagination: `rel=next` → `aria-label*=Next` → `.pagination .next` → text match ("Next"/"Load more"/"Show more") → infinite scroll fallback (2-streak zero-growth stop).
  - UA rotation (5 desktop UAs), 0.5–2s jitter, 2s/4s retry backoff, 3 retries per page, hard-fail on initial page unreachable.
  - Caps enforced: `MAX_PAGES`, `MAX_PRODUCTS`.
- `/app/backend/worker.py` — `WorkerPool` with `asyncio.Queue` + `MAX_CONCURRENT_JOBS=3` consumers. Start/stop in FastAPI lifespan; re-enqueues any `queued` jobs on restart. Live `$inc` of `pages_scraped` / `products_count`. Detects DELETE by polling `_job_exists()` between pages.
- `server.py` migrated from deprecated `@app.on_event` to `@asynccontextmanager lifespan`.
- New endpoints (all user-scoped):
  - `GET /api/jobs/{id}/products?limit&offset`
  - `GET /api/jobs/{id}/logs?level&limit&offset`
  - `GET /api/jobs/{id}/logs/stream?token=<jwt>` — SSE (`text/event-stream`), replays last 50 logs then tails (500ms poll); emits `event: end` when job terminal.
- New env: `MAX_CONCURRENT_JOBS`, `MAX_PAGES`, `MAX_PRODUCTS`, `MIN_DELAY_SEC`, `MAX_DELAY_SEC`, `NAV_TIMEOUT_MS`, `PLAYWRIGHT_BROWSERS_PATH`.

**Frontend — `/jobs/:id`**
- Live metric cards: status badge, pages_scraped, products_count, elapsed, started_at.
- Auto-polls `GET /api/jobs/{id}` every 2s while status ∈ {queued, running}.
- Live Logs panel: `EventSource` to `/api/jobs/{id}/logs/stream?token=...`, colored level pills (INFO/DEBUG/WARN/ERROR), autoscroll, deduplicates by log id. Streaming indicator (emerald pulse).
- Log level filter (shadcn Select).
- Delete action with stop-the-scraper confirmation.

**Verified end-to-end**
- `books.toscrape.com` → 50 pages, 1000 products in ~90s.
- 5 rapid POSTs → exactly 3 running + 2 queued.
- Invalid host → `failed` status with error message.
- Testing agent: 11/11 Phase-2 tests pass, 14/14 Phase-1 regression intact.

### Phase 3 — CSV (PENDING)
- 200+ column Swagify schema (exact order). Unmapped → empty string.
- CSV download endpoint + copy-to-clipboard (CSV / plain text) on job detail.

---

## Backlog (prioritised)
- **P0** Phase 3 Swagify CSV export + job detail product table + copy-to-clipboard.
- **P1** Cancel / retry job buttons in dashboard row actions.
- **P1** Multi-user support (sign-up flow + per-user admin page).
- **P2** Scheduled / recurring scrapes.
- **P2** Diff detection between scrape runs.
- **P2** Per-job rate-limit / domain throttle.

## Next Tasks
1. Await Phase 3 brief with full 200+ column Swagify header list.
