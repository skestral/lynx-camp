# Developer Guide

## Local Setup

Use Python 3.12 and Node.js 22 to match the Docker build. Run from the repository root. Keep the database on local disk and use a dedicated development database, not production appdata or a cloud-synced SQLite file.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
$env:CAMPFINDER_DB = "$env:LOCALAPPDATA\CampFinder\dev.db"
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8080
```

Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
export CAMPFINDER_DB="$HOME/.local/share/campfinder/dev.db"
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8080
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` to port 8080. For a single-process preview, run `npm run build` in `frontend`, then open the backend's `http://localhost:8080` address. The backend serves `frontend/dist` when it exists. If 8080 is occupied, use another port and update the Vite proxy for that local session.

The Python process reads exported environment variables, not `.env` files automatically. Docker Compose supplies the environment for container deployments. Settings saved through the UI override environment defaults in the database. Restart the backend after changing Python code or environment variables; rebuild the frontend for a static preview.

Active watches start background work as soon as the server starts. Use the read-only screenshot demo below when you do not want real provider requests. Do not run multiple workers or containers against one database.

## Code Layout

| Location | Responsibility |
| --- | --- |
| `backend/app/main.py` | FastAPI routes, application lifecycle, background scheduler |
| `backend/app/scanner.py` | Stay windows, queued campground checks, pacing, cancellation, cooldowns, ETA |
| `backend/app/recreation.py` | Recreation.gov client and HTTP 429/Retry-After handling |
| `backend/app/db.py` | SQLite schema, transactions, watch groups, results, logs, saved settings |
| `backend/app/notifications.py` | Channel configuration, alert formatting, tests, delivery records |
| `backend/app/scan_config.py` | UI/environment scan-control precedence and validation |
| `backend/app/presets.py`, `sources.py` | Bundled targets and source discovery |
| `frontend/src/App.tsx`, `WatchGroup.tsx` | Dashboard, drawers, logs, regional watch controls |
| `frontend/src/api.ts`, `types.ts` | Frontend API calls and response contracts |
| `backend/tests/` | Unit and API tests with isolated databases and fake providers |

## Scan Lifecycle

The background scheduler selects due active watches and processes one campground check at a time. A regional watch has a shared group ID but a separate schedule and scan history for each member. Completion schedules the next check using the watch/target interval and global minimum. Finished members are not rechecked within the same pending cycle.

The `scanner_runtime` app setting stores the queue, counters, pause state, adaptive delay, and cooldown deadline. It is deliberately excluded from configuration JSON exports. A full appdata backup preserves it. On restart, an in-progress queue becomes eligible to resume, while abandoned scan-run rows are marked interrupted. In-memory month-response caches are not persisted.

Watch deletion uses `Scanner.delete_watches` for both the bulk and individual endpoints. It holds the scanner lock while a worker thread performs the SQLite transaction, then prunes and persists the pending queue. Request cancellation does not release that lock while the worker is still running. Do not replace this with a direct synchronous store call inside an async route, or remove the lock when offloading work.

`Store.init` creates missing foreign-key child indexes with `CREATE INDEX IF NOT EXISTS`. This startup migration applies to existing databases as well as fresh ones; `cart_attempts.result_id` already has a UNIQUE index. Regression tests in `test_bulk_watch_delete.py` drop the new indexes from a populated database to reproduce the old schema, reopen and migrate it twice, check query plans, and verify retained settings and history.

| Endpoint | Contract |
| --- | --- |
| `GET /api/scans/status` | Queue state, counts, retry deadline, effective spacing, and estimated remaining seconds |
| `POST /api/scans/run-all` | Returns HTTP 202 immediately; starts a full queue or returns the pending one without duplicating it |
| `POST /api/scans/cancel` | Pauses background crawling and requests cancellation at a safe checkpoint |
| `POST /api/watches/{id}/scan` | Checks one watch; returns 409 if a background crawl is pending or active |
| `GET /api/scans` | Recent persisted campground scan runs |
| `GET /api/scans/events` | Recent diagnostic checkpoints |
| `GET /api/notifications/status` | Whether channels are configured; not proof of delivery |
| `POST /api/notifications/test` | Sends a real test to every configured channel; use deliberately |

A 429 leaves the current and later checks pending. The scanner waits for the longer of the provider's Retry-After and its exponential local backoff, then resumes. Successful cycles gradually reduce adaptive spacing toward the configured minimum. ETA is based on remaining monthly requests, spacing, observed latency, and known cooldown; it is not a completion deadline.

New matches are deduplicated and notified after each campground check, or before returning from a rate-limited partial check. Enabling a channel later does not resend all existing matches. Delivery failures are recorded but are not managed by a durable retry queue.

## Verification

From the repository root, using the environment's Python executable:

```bash
python -m pytest backend/tests -q
```

From `frontend`:

```bash
npm run build
```

Use fake availability clients and temporary SQLite stores for scanner changes. Cover cooldown suppression, queue recovery after restart, partial-result notifications, and pause/resume behavior when touching the crawl lifecycle. Successful unit tests do not establish live provider limits, production storage health, or notification delivery.

For watch deletion changes, also run `python -m pytest backend/tests/test_bulk_watch_delete.py -q`. The suite covers cross-batch cascades, transaction rollback, queue recovery, preserved cooldowns, concurrent dashboard reads, exclusion of the crawler, and cancelled requests. It does not send provider requests or notifications.

Validate both Compose files without printing resolved secrets: `docker compose -f compose.yaml config --quiet` (requires its configured env file) and `docker compose -f docker-compose.yml config --quiet`. Review the [deployment instructions](../README.md#implementation-guide) before updating a running container.

## Secret Handling

`.gitignore` excludes `.env`, runtime files under `appdata/`, local `data/`, and screenshot working files under `output/playwright/`. Only `.env.example` and `appdata/config/.env.example` are tracked configuration templates. Keep their secret fields blank. `.dockerignore` also excludes `.env`, `appdata`, and `data` from the build context.

An ignore rule does not untrack an existing file and can be bypassed with `git add -f`. Before committing, inspect `git status --short` and `git diff --cached`; never force-add runtime data. Secret-inclusive exports and backups placed outside ignored directories are not automatically protected. Store those outside the checkout. If a real secret reaches Git history, rotate it with the provider; removing the current file alone is not enough.

## Documentation Screenshots

Build the frontend, then run from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts/docs_demo.py --port 8093
```

On Linux/macOS use `.venv/bin/python scripts/docs_demo.py --port 8093`. Open `http://localhost:8093`. This serves the real UI with synthetic targets, a four-campground regional watch, tent/cabin matches, simulated cooldown progress, and example delivery records.

The helper creates a temporary database, clears inherited Camp Finder environment settings in its own process, disables the scheduler and provider client, and rejects write requests. The example webhook uses `.invalid`; no alert is sent. Do not use this helper for real monitoring. Stop it with Ctrl+C when finished; the temporary database is removed. The map may still load public OpenStreetMap tiles in the browser.

Capture the dashboard at 1440 x 1100 and mobile views at 390 x 844. Use the actual Settings and Watches drawers, their native scrolling, and the Logs link; do not edit rendered text to manufacture a state. Store capture work in `output/playwright/`, inspect the images, and copy approved screenshots into `docs/screenshots/`.

Current documentation images:

| Image | View |
| --- | --- |
| `dashboard-overview.png` | Crawl cooldown, progress, and grouped results with dismissal controls |
| `crawl-mobile.png` | Mobile crawl status and summary |
| `regional-watch-demo.png` | Mobile regional watch and member campgrounds |
| `notification-settings.png` | Configured example webhook with no credential shown |
| `scan-controls.png` | Repeat interval, request spacing, cache, and backoff settings |
| `crawl-logs.png` | Diagnostic events, run outcomes, and demo deliveries |

Never capture a real webhook input, secret-inclusive export, account credential, or private delivery error for public documentation. Describe demo data as simulated; configured channels and seeded delivery records are not live verification.
