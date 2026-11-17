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
| `backend/app/providers.py`, `provider_ids.py`, `camava.py`, `activenet.py`, `cedar.py` | Provider routing, namespaced IDs, and county search clients |
| `backend/app/db.py` | SQLite schema, transactions, watch groups, results, logs, saved settings |
| `backend/app/notifications.py` | Channel configuration, alert formatting, tests, delivery records |
| `backend/app/scan_config.py` | UI/environment scan-control precedence and validation |
| `backend/app/presets.py`, `sources.py` | Bundled targets and source discovery |
| `frontend/src/App.tsx`, `WatchGroup.tsx`, `SavedTargets.tsx` | Dashboard, drawers, logs, regional watch controls, grouped target inventory |
| `frontend/src/api.ts`, `types.ts` | Frontend API calls and response contracts |
| `backend/tests/` | Unit and API tests with isolated databases and fake providers |

## Scan Lifecycle

The background scheduler selects due active watches and processes one campground check at a time. A regional watch has a shared group ID but a separate schedule and scan history for each member. Completion schedules the next check using the watch/target interval and global minimum. Finished members are not rechecked within the same pending cycle.

## Regional Coverage

`regions.py` validates provider-independent selectors: a two-letter state code, exact park-group names, or ordered map bounds. `watch_regions` stores opt-in selectors and excluded campground IDs, keyed by the existing watch group ID. The table is created at startup on existing databases without changing any old watch's membership. No live provider discovery or network request runs during enrollment.

Target creation/update enrolls active matching targets within the same database transaction. A group/target membership check prevents duplicate watches on repeated imports. New members copy the group's shared watch criteria and are enabled only if at least one existing member is enabled. Individual criteria edits on automatic groups are rejected; group edits keep the template consistent. The saved bounding box never tracks later map panning, and missing coordinates cannot match it.

Deleting members records stable campground-ID exclusions; deleting the last member or its target removes the orphaned selector. Bulk deletion keeps the existing 500-ID transaction batches and scanner lock. Turning expansion off removes the selector and exclusions, not the current member watches. Changing a selector is additive: existing members outside the new area remain until explicitly removed. Enrollment emits a `region_expanded` diagnostic event.

`POST /api/watch-groups` accepts optional `region_scope`. `PATCH /api/watch-groups/{id}` preserves it when omitted, clears it on `null`, and reconciles currently imported targets when set. The PATCH database work runs in a worker thread. JSON configuration backups carry an optional `regions` list; old backups remain accepted. Restore defers enrollment until target active flags, member criteria, and exclusions have been restored. A restored automatic group's criteria also apply to retained local members that were imported after the backup.

`test_regional_coverage.py` covers old-database migration, opt-in compatibility, state/park/map membership, inactive targets, duplicate imports, pause/delete behavior, exclusions, rollback, chunked deletion, and backup restoration. The county suite also verifies that importing Snohomish after creating a state watch enrolls the new target and delivers a fake notification while Recreation.gov is cooling down.

## Queue and Recovery

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

A 429 leaves that provider's checks pending. The scanner waits for the longer of its Retry-After and exponential local backoff, while eligible checks for other providers continue. Cooldowns survive restart. Successful cycles gradually reduce adaptive spacing toward the configured minimum. ETA counts monthly requests for Recreation.gov and full-stay searches for county providers, plus spacing, observed latency, and known cooldown. A county stay can require several paginated or rule-check requests, so initial estimates can be low. It is not a completion deadline.

## Adding Providers

Recreation.gov IDs stay unchanged. Snohomish IDs use `camava:snoco:<park-id>`; campsite IDs use the same prefix with the site ID. King County currently allows only `activenet:king:66`, the verified Tolt-MacDonald center; its site IDs use `activenet:king:<facility-id>`. Skagit County allows only `cedar:skagit:hmsp`, Howard Miller Steelhead Park; site IDs use `cedar:skagit:<venue-portion-uuid>`. The namespace prevents numeric collisions without rewriting existing target/watch IDs or foreign keys. `provider_ids.py` is the allowlist for routing and booking URLs. Never accept a user-supplied provider host as an HTTP destination.

`CampgroundClient` routes external discovery and full-stay searches. Recreation.gov still uses monthly maps. Snohomish uses the public campground search page with a GET request for an exact arrival/departure range. `camava.py` parses HTML with Beautiful Soup, checks echoed dates and selected park, and only accepts enabled Reserve buttons inside matching site cards. It never submits those buttons. The map JSON is deliberately not used for availability: it may contain sites from other parks. Blank pages, changed markup, and denied responses must raise errors rather than expire existing matches.

The scanner caches exact county stays separately from federal months. Both paths share result filtering, persistence, notifications, cancellation, and provider-specific pacing. County release dates are not guessed from federal six-month defaults. Cart Assist remains Recreation.gov-only. Booking URLs are generated from an allowlisted provider and survive database initialization and configuration import/export; startup URL backfills only rewrite legacy federal results.

King County uses ActiveNet's public overnight resource catalog and full-stay map-availability query. Catalog pagination follows the returned search ID and next index, validates total counts, and excludes non-camping/day-use resources. A response must contain exactly the requested facility IDs and known availability statuses. Only fully available sites become candidates; each candidate must also pass its current detail record's stay-length and booking-window rules. The API publishes lead-time limits as generated English strings, so unrecognized/missing resident or non-resident rules fail closed rather than falling back to general website policy.

The King County client caches complete catalog/detail responses for 24 hours and serializes all its calls with a five-second floor. During scans, every HTTP request also invokes the scanner's `before_request(stage)` gate for configured pacing, cancellation, and diagnostic events. Keep that callback on metadata/detail requests as well as availability calls. HTTP 429 enters the common persisted provider-specific cooldown. Other denied, malformed, partial, or failed responses raise `ProviderResponseError`; they must not expire existing matches. The two POST endpoints used by this client are read-only resource searches; no cart, proceed, reservation form, login, or payment endpoint is used.

Tolt-MacDonald's map point is the address location linked by the official county camping page, not an individual campsite coordinate. Result links select the site's map section, but no date-prefill URL contract has been verified for ActiveNet. Do not invent query parameters or claim that its link preserves dates. Future county centers require their own policy and inventory review before extending the allowlist.

Before enabling another source, verify discovery IDs, all overnight accommodation categories, full-stay rules, denial handling, date-aware booking links, and rate limits. Add fixture tests and bounded read-only live checks. Do not mark an unverified connector ready, retry through a firewall denial, or treat first-come campground directories as availability feeds.

Washington State Parks is the next integration priority. Its [implementation notes](washington-state-parks.md) separate public upstream contracts from the provider access and live evidence still needed. Keep its source in `research` until that checklist passes; neither an upstream library nor a campground directory establishes live coverage.

Skagit County uses Cedar's public GraphQL calendar. `cedar.py` sends query operations only to a fixed endpoint with an allowlisted organization and campground. The requested fields deliberately omit customer bookings and hold details. Each page also validates the campground's current public/unarchived catalog record. Pagination requires stable totals and rules, unique venue/portion identities, and a complete final page. Missing pages, GraphQL errors, unknown rule units, contradictory date flags, or foreign IDs are errors, never empty availability.

The calendar query covers arrival midnight through the millisecond before departure midnight in America/Los_Angeles, with DST-aware conversion to UTC. Every occupied night must be available. Hidden/admin-only sites and pending-only dates are excluded. Site settings inherit from the facility unless their override flag is true; older records omit these flags. Current-year release policy and the 14-night cap come from the county's official campground page, while lead times, minimum stays, and venue overrides come from live records. Weekend and holiday overrides apply conservatively to any occupied night. Account-dependent cumulative stay limits are not knowable from the anonymous calendar and are left to checkout.

Cedar's public form uses the US `date-holidays` calendar and an observance-name exclusion list. A bounded 2026-2035 date snapshot avoids hand-maintaining holiday arithmetic or adding Node to the Docker runtime. Regenerate it with `npm run generate:cedar-holidays` in `frontend`; unknown years fail closed. The pinned generator dependency is not imported into the UI bundle. See [third-party data attribution](third-party-data.md) for the snapshot's source and license.

Skagit requests use the same per-HTTP-request scanner gate as King County, plus a five-second floor and serialized transport. Discovery and availability cannot burst concurrently. The common stay cache, cancellation, notification deduplication, and persisted Skagit-specific cooldown need no separate scheduling system. The verified booking link opens the campground calendar without dates. No mutation, login, cart, or payment endpoint is called.

`test_county_provider.py` covers parsing, unknown responses, cross-provider IDs, notification handoff, independent cooldowns, backup restoration, and repeated database initialization. Live development checks on November 17, 2026 discovered eight county parks, returned cabin and campsite results for a Flowing Lake weekend, and recognized a closed Whitehorse stay. No reservations or real notifications were sent. Washington State Parks was firewall-denied and remains unconnected; production-host behavior is unverified.

`test_king_county.py` covers paginated overnight discovery, per-site restrictions, partial/unknown responses, cache behavior, denial handling, cancellation between rule checks, import/scan/notification handoff, and backup compatibility. A paced read-only development scan on November 17, 2026 discovered 53 Tolt-MacDonald sites and returned 49 validated matches for June 4-6, 2027, including six yurts. That cold-cache run made 54 catalog, availability, and rule requests. These are point-in-time results, not reserved inventory. Tests do not send real notifications or submit reservations.

`test_skagit_county.py` covers tent/cabin/RV classification, hidden and partial sites, paginated response failures, inherited rules, lead times, holiday minimums, DST boundaries, annual release limits, cancellation, and regional import/scan/backup integration. A read-only server check on November 17, 2026 read three availability pages for November 20-22 and returned 51 public matches: 41 RV sites, seven tent sites, two cabins, and one paired Adirondack shelter. The response included 68 records, of which 15 were hidden and two public sites were not available for the whole stay. No reservation, hold, or real notification was submitted. Production-host access remains unverified.

Clallam research on the same date confirmed the official Salt Creek and Dungeness CampLife links. The normal browser availability response required registration/login; a plain server request to the observed map endpoint returned HTTP 403. No credentials, browser challenge tokens, alternate routes, or access workarounds were used. Leave this source unconnected until there is an authorized, verified integration path.

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

`.gitignore` excludes `.env`, runtime files under `appdata/`, local `data/`, and screenshot working files under `output/playwright/`. Only `.env.example` and `appdata/config/.env.example` are tracked configuration templates. Keep their secret fields blank. `.dockerignore` also excludes `.env`, `appdata`, `data`, `.playwright-cli`, and `output/playwright` from the build context. Browser traces and inspection files must not be uploaded as part of an image build.

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
| `regional-coverage.png` | State watch editor with future-import coverage enabled |
| `notification-settings.png` | Configured example webhook with no credential shown |
| `scan-controls.png` | Repeat interval, request spacing, cache, and backoff settings |
| `crawl-logs.png` | Diagnostic events, run outcomes, and demo deliveries |
| `county-sources.png` | Everett and North Sound catalog with live Snohomish and Skagit County coverage |
| `county-sources-mobile.png` | Skagit County source controls at 390px |
| `saved-targets-mobile.png` | Searchable saved inventory with an expanded campground group |

Never capture a real webhook input, secret-inclusive export, account credential, or private delivery error for public documentation. Describe demo data as simulated; configured channels and seeded delivery records are not live verification.
