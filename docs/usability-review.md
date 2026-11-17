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
- Demo screenshots are in `docs/screenshots/availability-first-demo.png` and `docs/screenshots/regional-watch-demo.png`.

## Operational follow-up

### Continuous crawl verification (2026-11-17)

- Backend suite: 92 tests passed, including durable queue recovery, cooldown suppression, Retry-After dates, adaptive pacing, partial-result notifications, and pausing one watch without pausing the entire crawl.
- The full-scan endpoint returns HTTP 202 before provider work finishes; repeated starts reuse the pending cycle.
- The frontend production build passed. Desktop and 390px mobile checks confirmed the pending counts, cooldown deadline, conditional ETA, and missing-notification warning.
- An isolated two-watch queue retained its pending work through pause and resume. The local Washington watch retained all 312 pending checks and its existing cooldown. No test bypassed the provider cooldown.
- Production deployment and a full live 312-campground cycle remain unverified. Automated tests use fake provider responses; passing them does not establish a rate-limit-free request interval.

Production logs confirmed `sqlite3.OperationalError: database is locked` on a settings read while the old health endpoint reported success. They do not identify the lock holder. The supplied host mount is local Unraid appdata, so an SMB/NFS mount has not been established as the cause. Check competing database users, share placement, backup/mover activity, and storage health before changing production storage.

The local WAL/concurrency tests do not prove that production's underlying lock cause is resolved. Production deployment and post-deployment checks remain operator-controlled. Stop the container and back up the full appdata directory before updating. Never remove SQLite journal files to force a lock clear.

Regional membership is a creation-time snapshot. Existing ungrouped rules are preserved, and newly imported campgrounds are not silently enrolled in existing watches. A future explicit membership editor would make changing an established region easier.
