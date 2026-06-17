# Camp Finder

Camp Finder is a local-network web app for monitoring Recreation.gov campground availability. It is designed to run in Docker, persist its data in SQLite, and notify you when a configured campground/date rule has availability.

The app is still notification-first. It opens Recreation.gov booking links when a match appears, and it can flag selected watches as high priority for Cart Assist logging. The current Cart Assist implementation is a guarded audit trail and readiness check; it does not automatically click Add to Cart, submit payment, or try to get around Recreation.gov login or CAPTCHA checks.

## What It Does

- Add campground targets from Recreation.gov search.
- Import preset target packs for Pacific Northwest, Northern Rockies, Greater Yellowstone, or California national parks, then trim targets you do not want.
- Check preset packs against live Recreation.gov campground search and optionally import the discovered source list.
- Edit target display names, park/state labels, booking links, and day/week/month release-window settings.
- Detect a likely release window from Recreation.gov campsite reservation-window data when available.
- Pause and resume targets or individual watch rules without deleting them.
- Create watch rules with one or more arrival weekdays and a stay length, such as Friday or Saturday starts for two nights.
- Create exact arrival/departure date watches.
- Edit watch names, targets, dates, day patterns, stay length, and site filters after creation.
- Filter watch matches by campsite type, loop text, site text, and minimum people capacity.
- Poll availability on a configurable interval, with a default minimum of 10 minutes.
- Reuse fresh Recreation.gov month responses across watches and back off automatically after HTTP 429 rate limits.
- Temporarily increase scan cadence around calculated release times.
- Run every active watch on demand with the Scan All control.
- See the latest scan state at the top of the dashboard, including manual scans and background scans that are still running.
- Revalidate previously available matches on each successful scan and remove matches that Recreation.gov no longer returns.
- Review recent scan activity, including candidate counts, matches, status, and messages.
- Calculate likely release windows from a target-specific booking window, release time, and timezone.
- Store availability matches once so notifications are deduped.
- Send one bulk notification per scan when multiple new site/date matches appear.
- Mark selected watches as high priority with Cart Assist, then record one guarded assist attempt when a new match appears.
- Show Cart Assist server readiness and recent attempt history without exposing Recreation.gov credentials in the browser.
- Configure server-level Cart Assist from the dashboard or from Docker environment variables.
- Triage availability results as opened, booked, dismissed, or active again.
- Filter, sort, select, and bulk-update availability results from the dashboard.
- Show notification channel status and send a test notification.
- Notify by webhook, ntfy mobile push, and/or SMTP email when configured.
- Export and restore target/watch configuration backups.
- Run as a single Docker Compose service on your local network.

## Dashboard Workflow

The dashboard is organized around the work that usually matters first:

1. Scan state and summary counts show whether Camp Finder is idle, scanning, or showing the last completed scan.
2. The map uses Leaflet with OpenStreetMap tiles to show saved targets plus preset park/campground options. Selecting a marker filters the results list.
3. Availability Results stay in the main working area so new matches are not buried below target and watch configuration.
4. Target and watch setup live in the slide-out drawer. Use the Targets and Watches buttons in the header or sidebar to open it.
5. Result filters let you switch between active, all, available, opened, booked, and dismissed results.
6. Result search matches park name, campground, site, loop, campsite type, watch name, and stay dates.
7. Sort controls support newest first, arrival date, and park/campground grouping.
8. Select Visible lets you bulk dismiss, mark booked, or reopen the results currently in view.

In normal use, you add or import targets, create watch rules, then spend most of your time in the map, scan status, and results sections. Release hints, recent scan activity, notifications, and server settings stay beside the results on desktop and stack underneath on smaller screens.

## Preset Packs

The app currently ships with static park packs that were built from Recreation.gov campground search:

- PNW and Northern Rockies National Parks: Olympic, Mount Rainier, Crater Lake, North Cascades, and Glacier Recreation.gov campground facilities.
- Individual park packs: Olympic, Mount Rainier, Crater Lake, North Cascades, Glacier, Yellowstone, and Grand Teton.
- California National Parks: Yosemite, Sequoia/Kings Canyon, and Joshua Tree starter campgrounds.

Preset targets use campground IDs verified through Recreation.gov search results and include facilities whose Recreation.gov parent is the named park. Some parks also have concession-run or non-reservable campgrounds outside Recreation.gov, so those cannot be scanned by this Recreation.gov-backed app yet. The release settings still remain editable at the target level in the database model, because Recreation.gov booking windows can vary by facility.

The target drawer has three ways to use each preset:

- Import bundled list: imports the static fallback list that ships with the app.
- Check source: queries Recreation.gov search for each park in the pack and compares the live campground IDs against the bundled list.
- Import source list: imports the campgrounds returned by the live source check.

The source check is intentionally visible instead of automatic. It pages through Recreation.gov campground search for each park, keeps only exact parent-park matches, and verifies bundled campground IDs that the broad search misses. It shows how many campgrounds Recreation.gov returned, how many are new compared with the bundled list, and how many bundled targets were not returned by the current source search. That keeps the app useful when the network or upstream API is unavailable while still letting the campground lists drift with Recreation.gov over time.

Paused targets are skipped by background scans and Scan All. Paused watch rules are kept in the dashboard but are also skipped until resumed.

## Watch Filters

Watch filters are optional. If left blank, Camp Finder reports every campsite that is available for the requested stay. If set, all populated filters must match:

- Site type: case-insensitive contains match against Recreation.gov campsite type.
- Loop: case-insensitive contains match against loop name.
- Site text: case-insensitive contains match against site label.
- Minimum people: excludes known sites with lower max occupancy.

## Cart Assist Boundaries

Recreation.gov says booking windows are set by individual facilities and lists booking-window details under each facility's Seasons & Booking tab. It also describes active bot mitigation and notes that Add to Cart holds a campsite for a limited checkout window. For that reason, Camp Finder keeps Cart Assist conservative:

- Cart Assist is off by default at the server and off by default on every watch rule.
- A watch must opt in before a new match can create a Cart Assist attempt.
- The server records at most one configured attempt per scan by default.
- A cooldown prevents repeated attempts from piling up.
- Credentials, if used, belong in the server `.env` file or in the dashboard-managed appdata settings, not in browser local storage.
- Attempt records can be marked opened, booked, dismissed, failed, or ready again from the dashboard.
- This build records readiness and manual-checkout attempts. It does not run an automated browser worker yet, does not submit payment, and does not bypass login, CAPTCHA, or any ambiguous Recreation.gov screen.

The next safe step is a separate browser worker that can use one persistent Recreation.gov session, stop on any challenge or uncertainty, and hand the final checkout decision back to you. That worker should be explicitly enabled only after reviewing current Recreation.gov terms and the behavior of your account.

## Local Development

Backend:

```powershell
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8080
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` for Vite development, or build the frontend and use the backend on `http://localhost:8080`.

## Docker

For local builds from this checkout:

```powershell
Copy-Item .env.example .env
docker compose -f docker-compose.yml up --build
```

Then open `http://localhost:8080`.

To expose the app to your LAN, visit `http://<this-computer-ip>:8080` from another device on the same network.

## Server Deployment

Every push to `main` publishes a Docker image to GitHub Container Registry as `ghcr.io/skestral/lynx-camp:main`. The root [compose.yaml](/compose.yaml) is the portable server file that pulls that image and stores runtime state under `./appdata`.

On the server:

```bash
mkdir -p appdata/config
cp appdata/config/.env.example appdata/config/.env
nano appdata/config/.env
docker compose pull
docker compose up -d
```

Keep `appdata/config/.env` on the server only. It is where notification secrets such as ntfy topics, webhook URLs, and SMTP credentials belong. The SQLite database is stored at `appdata/campfinder.db`, so the app data folder can be backed up or moved with the deployment.

Do not expose the Camp Finder web UI directly to the public internet. The app is built for a trusted local network or a private VPN and does not include user accounts or login protection yet.

If you prefer file-managed secrets, keep the Recreation.gov username and password in that same server-only `.env` file:

```text
CAMPFINDER_CART_ASSIST_ENABLED=true
CAMPFINDER_CART_ASSIST_COOLDOWN_MINUTES=30
CAMPFINDER_CART_ASSIST_MAX_ATTEMPTS_PER_SCAN=1
CAMPFINDER_RECREATION_GOV_USERNAME=you@example.com
CAMPFINDER_RECREATION_GOV_PASSWORD=your-password-or-app-secret
```

You can also configure Cart Assist from the dashboard. Dashboard-saved values are stored in the SQLite database under `appdata/campfinder.db`, which makes them part of the normal server appdata backup. The dashboard only shows whether credentials are configured. It never prints the username or password, and config backups exported from the UI do not include those credentials.

Protect `appdata` the same way you would protect a `.env` file. This app does not encrypt dashboard-saved Recreation.gov credentials at rest yet; the current tradeoff is simple remote-server setup over secret-manager complexity. For now, those values make the server status read as ready and allow guarded attempt records for high-priority watches; they are not used to complete checkout.

If GitHub Container Registry requires authentication on the server, run:

```bash
echo "<github-token>" | docker login ghcr.io -u skestral --password-stdin
```

For local development, continue using [docker-compose.yml](/docker-compose.yml), which builds from source instead of pulling the packaged image.

## Scanning

Camp Finder scans active watches in the background and respects the minimum poll interval configured by `CAMPFINDER_MIN_POLL_INTERVAL_MINUTES`. The UI also has a Scan All button for a manual sweep across every active watch. Manual scans are useful when you import a preset pack, add filters, or want to check the current Recreation.gov response immediately.

Release-aware scanning is enabled by default. Targets can use release windows in days, weeks, or months. If a watched stay has a calculated release time coming up, Camp Finder wakes up before that release and temporarily uses `CAMPFINDER_RELEASE_SCAN_INTERVAL_MINUTES` during the window configured by `CAMPFINDER_RELEASE_SCAN_BEFORE_MINUTES` and `CAMPFINDER_RELEASE_SCAN_AFTER_MINUTES`. Defaults are 15 minutes before, 60 minutes after, and a 10-minute release-window interval. Lower intervals should be an explicit choice after considering Recreation.gov's bot mitigation and shared API impact.

Camp Finder also has guardrails for off-season scans and rate limits:

- `CAMPFINDER_AVAILABILITY_CACHE_MINUTES` defaults to `5`. Fresh monthly availability responses are reused across watches for the same campground/month, which keeps multiple weekend rules from making duplicate API calls.
- `CAMPFINDER_API_REQUEST_DELAY_SECONDS` defaults to `1`. The scanner waits between uncached Recreation.gov month requests.
- `CAMPFINDER_RATE_LIMIT_BACKOFF_MINUTES` defaults to `60`. If Recreation.gov returns HTTP 429, the scanner records the scan as `rate_limited`, schedules the affected watches after the backoff, and skips additional API calls while the backoff is active.

The Target Settings form includes a Detect Window action. It samples Recreation.gov campsite reservation-window metadata for the selected campground and applies the most common window it finds, such as a 14-day rolling window when a facility exposes that rule.

For campgrounds with staggered releases, use View Profiles in Target Settings. It groups sampled Recreation.gov campsite metadata by loop, site type, and reservation window, which helps you decide whether a watch should filter to a specific loop and use a different day/week/month release window.

The scan status strip at the top of the dashboard changes as soon as a manual scan starts. It also uses recent scan-run records, so background scans that are still marked `running` can surface after the periodic dashboard refresh. The Recent Scan Activity panel keeps the detailed history: watch name, target, candidate stays, matches, status, timestamp, and scanner message. That combination is meant to answer two different questions quickly: what is happening right now, and what happened during the last few scans.

## Booking Assist

Availability results include the Recreation.gov booking link plus status actions. Open marks a fresh match as opened, Copy puts a booking brief on your clipboard with the campground, watch, site, loop, type, stay dates, and Recreation.gov link. If the browser blocks clipboard access, the same brief appears above the results for manual selection. Booked records that you successfully reserved it, Dismiss removes it from active attention, and Reopen moves a handled result back to active availability. Future scans preserve booked and dismissed decisions for the same campsite/date result instead of notifying you about the same handled match again.

Each successful scan also revalidates active results for the same watch and date ranges. If a previously active site/date match is not returned again, Camp Finder marks it booked and removes it from the active list. Scan errors and Recreation.gov rate limits do not clear old results, because those runs did not prove the match disappeared.

Results are grouped by national park, campground, and stay dates. Campground and stay sections start collapsed so the list is easier to scan after large result bursts. Use the status filter and search field to narrow the dashboard before selecting results. Bulk actions apply to selected results only; Clear All dismisses every active availability result, which is useful when a scan finds many sites that you do not want to pursue.

For high-priority trips, enable Cart Assist on the watch rule. When a new match appears, the scanner writes a Cart Assist attempt with one of these statuses:

- `off`: the watch is not using Cart Assist.
- `disabled`: the watch asked for Cart Assist, but the server feature flag is off.
- `needs credentials`: the server flag is on, but Recreation.gov credentials are not configured.
- `manual required`: the server is ready and the match should be handled in Recreation.gov manually.
- `opened`: the booking link was opened from the dashboard and still needs a final decision.
- `booked`: you successfully reserved the site.
- `dismissed`: you reviewed the hit and decided not to pursue it.
- `failed`: checkout could not continue or the page did not match expectations.
- `cooldown`: a recent attempt already happened and the cooldown is still active.
- `skipped`: the per-scan attempt cap has already been reached.

These records are shown in the Notifications & Server Settings panel. They are intentionally boring and explicit, because a hold workflow needs a trustworthy log more than it needs surprises.

Use Open on a ready Cart Assist record to open the Recreation.gov booking page and mark the attempt as opened. After you decide what happened, mark it Booked, Dismissed, or Failed. Booked and dismissed attempts also update the matching availability result, and resolved attempts no longer count against the cooldown. If an attempt was created before credentials were configured, use Ready after the server settings are fixed to make it an active manual-checkout task without creating a duplicate record.

## Map Provider

The dashboard map uses Leaflet with OpenStreetMap's public raster tile endpoint by default. The map keeps OpenStreetMap attribution visible. For heavier use, private deployments, or stricter tile-policy control, point the frontend at a different compatible tile service before building:

```text
VITE_CAMPFINDER_TILE_URL=https://tile.openstreetmap.org/{z}/{x}/{y}.png
VITE_CAMPFINDER_TILE_ATTRIBUTION=&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors
```

If you use the default OpenStreetMap tile service, keep the attribution visible and avoid prefetching or bulk tile downloads.

When a scan discovers several new site/date matches at once, Camp Finder sends one bulk alert instead of one notification per campsite. `CAMPFINDER_MAX_NOTIFICATION_RESULTS` controls how many examples appear in that notification and defaults to `5`; the rest remain visible in the results dashboard.

## Notification Setup

For a webhook, set:

```text
CAMPFINDER_WEBHOOK_URL=https://...
```

Discord webhooks work because Camp Finder sends a simple `content` payload.

For ntfy phone push, subscribe to a private topic in the ntfy mobile app and set:

```text
CAMPFINDER_NTFY_SERVER=https://ntfy.sh
CAMPFINDER_NTFY_TOPIC=your-hard-to-guess-topic
CAMPFINDER_NTFY_PRIORITY=high
```

If your ntfy server requires a token, also set:

```text
CAMPFINDER_NTFY_TOKEN=...
```

For SMTP, set:

```text
CAMPFINDER_SMTP_HOST=smtp.example.com
CAMPFINDER_SMTP_PORT=587
CAMPFINDER_SMTP_USERNAME=you@example.com
CAMPFINDER_SMTP_PASSWORD=app-password
CAMPFINDER_SMTP_FROM=you@example.com
CAMPFINDER_SMTP_TO=you@example.com
```

The Notifications & Server Settings panel shows which channels are configured and which environment variables are missing. Use the test button there after changing `.env` to confirm delivery before relying on background scans.

## Notes From OpenCamp

This project uses the same Recreation.gov availability pattern that makes OpenCamp useful: campground search plus monthly campground availability calls. Camp Finder wraps that idea in a persistent local web app with watch rules, release-window hints, dedupe, and Docker hosting.

## Next Useful Phases

1. Add filters for equipment, max vehicle length, accessible sites, and electric/water hookups when the API exposes them consistently.
2. Add notification channels such as Pushover, Telegram, or richer email templates.
3. Add the guarded browser worker for Cart Assist, using one persistent Recreation.gov session and stopping on login challenges, CAPTCHA, unexpected pages, or any payment step.
