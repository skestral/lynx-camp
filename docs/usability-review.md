# Availability and watch management review

## Scope

This review covers finding available campsites, managing regional watches, bulk watch actions, and understanding dashboard/API failures. Verification used an isolated local SQLite database and synthetic availability, with no production mutations or Recreation.gov booking requests.

## Changes

| Finding | Resolution |
| --- | --- |
| Availability sat below a large map and park queue. | Results now precede the map; mobile summary metrics use two columns and planning widgets follow the working area. |
| Small result sets required several expansions before sites were visible. | Up to 12 filtered results open by default; larger sets remain grouped. |
| A collapsed result group sometimes needed two clicks to open. | Toggling now uses the same default state as rendering. |
| Creating a regional watch filled the drawer with independent listings. | One persistent regional listing contains expandable campground checks. Shared edits are transactional. |
| Watch management was below the creation form. | Existing watches and bulk controls precede the collapsible editor. |
| There was no bulk pause or removal. | Selected/all watches can be paused, resumed, or deleted, with destructive confirmation and an active-scan deletion guard. |
| Any failed dashboard request hid other successful updates. | Each section refreshes independently and identifies failed endpoints. |
| Health returned success during database read failures. | Health performs a database read; lock failures return 503 and server logs retain the traceback. |

## Verification

- Backend: `python -m pytest backend/tests -q` passed 81 tests, including atomic group creation, shared edits, backup round trips, duplicate group names, bulk actions, WAL reads during writes, rollback, and database health errors.
- Frontend: `npm run build` passed TypeScript checking and the production build.
- Browser, desktop and 390px mobile: created a two-campground park watch, confirmed one listing, edited both members to three nights, paused the group, and selected both members with one checkbox.
- Browser: resumed, paused, and deleted local test watches using bulk controls; targets remained.
- Browser: injected a failed notification-status response and confirmed other dashboard sections still loaded.
- Browser: verified site visibility for two matches and one-click campground/date expansion for a 15-match result set.
- The current screenshot set and capture instructions are listed in [the developer guide](development.md#documentation-screenshots).

## Operational follow-up

### Continuous crawl verification (2026-11-17)

- Backend suite: 92 tests passed, including durable queue recovery, cooldown suppression, Retry-After dates, adaptive pacing, partial-result notifications, and pausing one watch without pausing the entire crawl.
- The full-scan endpoint returns HTTP 202 before provider work finishes; repeated starts reuse the pending cycle.
- The frontend production build passed. Desktop and 390px mobile checks confirmed the pending counts, cooldown deadline, conditional ETA, and missing-notification warning.
- An isolated two-watch queue retained its pending work through pause and resume. The local Washington watch retained all 312 pending checks and its existing cooldown. No test bypassed the provider cooldown.
- Production deployment and a full live 312-campground cycle remain unverified. Automated tests use fake provider responses; passing them does not establish a rate-limit-free request interval.

### Documentation and screenshot refresh (2026-11-17)

- Updated installation, upgrade, notification, scan-state, cabin-filter, and backup instructions against the current source and UI labels.
- Captured a synthetic four-campground regional watch with tent/cabin matches, a simulated cooldown, and demo notification records. The capture server used a temporary database, no scheduler, a disabled provider client, and a read-only API; a test-send request returned 403 without sending anything.
- Reviewed desktop and mobile screenshots of the dashboard, regional watch, notification settings, scan controls, and Logs. Used Dashboard to return from Logs.
- Confirmed that `.env`, appdata, local data, and SQLite journal files are ignored. Only the two configuration templates are tracked, their webhook/password fields are blank, and no Discord webhook URL was found in tracked text. Secret-inclusive exports outside ignored paths still need manual care.
- Backend tests: 92 passed. Frontend build and local-source Compose validation passed. Server Compose validation could not run because this checkout has no `appdata/config/.env`; no production environment file was created or read.

### Bulk deletion regression checks (2026-11-17)

- Added eleven child-key indexes for watch, scan, result, notification, and Cart Assist cascades. A populated database with the previous index set received them on `Store.init`; a second startup preserved all data and settings. Query plans confirmed indexed child-key lookups.
- Bulk and single-watch deletion now use a worker thread while holding the scanner lock. Concurrent health, status, target, watch, and result reads returned successfully during an intentionally stalled write. A queued crawler waited until deletion finished.
- Deletion across more than 500 IDs preserved unselected watches, targets, and saved settings. An injected failure in a later batch rolled back the entire deletion and its related history. Cancelled requests retained the lock until completion; pending queue changes survived reload without resetting cooldown or pause state.
- Local timing sample: 550 watches, 550 scan runs/events, and 11,000 rows each in results, notifications, and Cart Assist. Deletion took 4.877 seconds without the new indexes and 0.076 seconds after migration; migration took 0.023 seconds. These are synthetic local measurements, not a production latency guarantee.
- Backend suite: 100 tests passed. Frontend production build passed. Production data was not modified; production recovery still needs verification after deploying the updated image.

Production logs confirmed `sqlite3.OperationalError: database is locked` on a settings read while the old health endpoint reported success. They do not identify the lock holder. The supplied host mount is local Unraid appdata, so an SMB/NFS mount has not been established as the cause. Check competing database users, share placement, backup/mover activity, and storage health before changing production storage.

The local WAL/concurrency tests do not prove that production's underlying lock cause is resolved. Production deployment and post-deployment checks remain operator-controlled. Stop the container and back up the full appdata directory before updating. Never remove SQLite journal files to force a lock clear.

Regional membership was initially a creation-time snapshot. The opt-in coverage update below adds saved state, park-group, and map-area selectors while preserving that default for existing watches.

### County monitoring and target catalog (2026-11-17)

- Split Targets into Sources and Saved tabs. Source packs start collapsed; saved campgrounds have search and expandable park/county groups. Checked keyboard tab switching, filtering, expanded rows, and desktop/mobile layouts at 1440 x 1100 and 390 x 844.
- Added an Everett/Puget Sound live provider for Snohomish County. Read-only live checks discovered eight parks and returned Flowing Lake cabin and campsite matches for a full weekend. A closed Whitehorse search returned no matches. No reservation, cart, or notification action was sent.
- Added visible coverage entries for Washington State Parks and nearby county/regional systems. Only verified connectors have import actions. State Parks was denied by the provider firewall and remains unconnected; other county directories are not claimed as live feeds.
- Backend suite: 123 tests passed, including mixed-provider cooldowns, ETA with a blocked provider, date/park validation, denial handling, exact-stay caching, cancellation, notification handoff, and backup compatibility. Frontend production build passed.
- Refreshed catalog and saved-target screenshots with the isolated, read-only demo. The browser had no console errors; synthetic UI verification does not establish production deployment, external alert delivery, or continuous live provider reliability.

### King County integration (2026-11-17)

- Added Tolt-MacDonald as one live King County target covering all three camping sections. The provider catalog returned 53 overnight sites across tents, RVs, yurts, the camping container, and groups. No picnic or day-use facilities were imported.
- A full read-only search for June 4-6, 2027 returned 49 matches after per-site reservation-rule checks, including six yurts. The uncached run used 54 requests with at least five seconds between requests. A smaller browser search agreed with the west-section availability response. No Reserve button was submitted and no alert was sent.
- The reservation system's current lead-time restrictions were stricter than the general county camping page. The connector now validates each candidate's rules and caches the successful response, instead of treating an Available map marker alone as a bookable stay.
- Added provider-request checkpoints to diagnostic logs. A cancellation test exposed that zero configured request spacing skipped the cancellation check; cancellation now runs regardless of spacing.
- Backend: 149 tests passed. Frontend production build passed. Desktop and 390px mobile checks confirmed King County in the Puget Sound source group, readable controls, no horizontal overflow, and no browser console errors. Refreshed the regional catalog screenshot with synthetic dashboard data.
- Tacoma Power's interactive page loaded, but its direct API challenged a server-style request. No access workaround was attempted. Washington State Parks, Tacoma Power, and the other unconnected county systems remain outside live scan coverage. Production Docker deployment was not changed.

### Saved Regional Coverage (2026-11-17)

- Added Include future imports to the regional watch editor. Saved selectors apply across connected providers; existing groups remain fixed until explicitly opted in. Group listings identify automatic coverage, and Logs record new members.
- Verified migration without a database reset, duplicate imports, inactive targets, paused groups, removed-member exclusions, full group deletion, rollback, and backup round trips. A 601-member group exercised deletion across parameter batches. A mixed-provider test enrolled a new county target into a state watch and delivered its fake match while federal requests were cooling down.
- On an isolated local server, created a Washington watch through the browser, added a synthetic county target, and observed the group grow from two to three members. Turning expansion off prevented the next target from joining. Clear All Watches removed all three member rules and preserved all five targets. No provider requests, real alerts, or production mutations were made by this verification server.
- Reviewed desktop and 390px mobile views, including the saved coverage label and group edit controls. No horizontal overflow or browser console errors. Refreshed screenshots from synthetic data.
- Backend suite: 179 tests passed. Frontend production build passed. These checks do not establish production storage performance or live alert delivery.
- Clallam's CampLife search required an account and its direct server endpoint returned 403. Its source remains explicitly unconnected; broad regional selectors do not imply unsupported provider coverage. Production Docker deployment remains unverified.

### Skagit County Integration (2026-11-17)

- Connected Howard Miller Steelhead Park as one target in Everett and North Sound / Snoqualmie and Cascades. Importing it into an opted-in Washington watch uses the existing shared criteria and notification workflow. Other Skagit campgrounds remain outside this connector's coverage.
- A paced, read-only server search for November 20-22 returned 51 public full-stay matches, including two cabins and seven tent sites. All three pages were validated. Fifteen hidden records and two partially/unavailable public sites were excluded. No account credentials, holds, reservations, or real alerts were used.
- Added regression checks for incomplete pages, hidden sites, inherited booking rules, lead times, holiday minimums, DST transitions, annual release limits, cancellation, notification deduplication, and regional-watch backup restoration. A failed later page preserves existing matches instead of marking them booked.
- Backend suite: 215 tests passed, with one existing Starlette/AnyIO deprecation warning. Frontend production build passed. The new holiday-calendar generator is a development-only dependency; it is not bundled into the UI or required in the Python runtime.
- Checked the source drawer at 1440 x 1000 and 390 x 844. No horizontal overflow or browser console errors. Refreshed desktop and mobile source screenshots using the isolated read-only demo with synthetic dashboard data.
- `npm audit` still reports seven high-severity findings in the existing Vite/build-tool dependency tree; the new holiday dependency was not implicated. These were recorded, not silently fixed through unrelated package upgrades.
- Production Docker was not redeployed. Washington State Parks, Tacoma Power, and the remaining county systems still need verified connectors; this change does not make them live sources.

### Washington Native API (2026-11-17)

- Added an experimental direct API adapter based on GoCamp's workflow. It runs in the regular backend without a browser console. Sources distinguishes Experimental API from verified Live monitoring and shows persisted access stops/cooldowns with a guarded reset action.
- A bounded direct catalog request returned HTTP 403. Live testing stopped; no browser-token replay, alternate route, or reservation action was used. This remains unverified live coverage, not a claim of a working statewide feed.
- Synthetic tests cover Camping and Roofed discovery, full-stay/nightly checks, nested maps and cycles, malformed payloads, persisted denial handling, cooldown isolation, cancellation, regional-watch import, notification deduplication, and backup restoration. No real alerts were sent.
- Reviewed the real Sources drawer at 1440 x 1100 and 390 x 844 using the read-only demo. Both layouts fit without horizontal overflow; Check, Import, and Reset correctly used disabled controls and a not-allowed cursor during the simulated cooldown. No application console errors were observed.
- Added desktop/mobile screenshots with an explicitly labeled simulated access failure. Documentation explains unsupported metadata filters, date-link verification limits, and the distinction between implemented integration and permitted live access. Production was not redeployed.
- Backend suite: 275 tests passed, with one existing Starlette/AnyIO deprecation warning. Frontend production build passed. These checks establish local integration behavior, not live Washington availability.

### Washington HTTP Diagnostics (2026-11-17)

- Added an expandable Provider Diagnostics section to Logs and a shortcut from Washington Sources. Refresh and JSON download read saved evidence only; they do not send provider requests or clear access stops.
- Verified the expanded layout at 1440 x 1000 and 390 x 844, the source shortcut, refresh, and downloaded JSON. The mobile document had no horizontal overflow. Screenshots use a labeled synthetic denial from `scripts/docs_demo.py --washington-access-stop`.
- Backend suite: 292 tests passed, with the existing Starlette/AnyIO deprecation warning. Frontend production build passed. Tests cover redaction, retention, restart persistence, read-only access, and denial handling when diagnostics fail.
- A normal Edge catalog and Camping availability request returned HTTP 200 JSON. No cookies were exported or replayed, no booking action was submitted, and the existing Docker denial stop was preserved. The original 403's origin and native full-stay compatibility remain unverified.
