# Camply Washington Probe

This is an isolated compatibility test for Camply, not a second crawler or a replacement for Camp Finder. There are separate Docker images for published version 0.34.4 and the pinned fixes from PR #398. Camply requires Pydantic 1 and the application uses Pydantic 2, so nothing is installed into the main backend environment.

The probe has no web interface, browser worker, exposed port, appdata mount, account login, or notification configuration. It does not import targets, create watches, change the application's access stop, or reserve inventory. Default execution is offline.

For normal watches, use the integrated [Washington State Parks connector](washington-state-parks.md). The app now incorporates the successful request behavior and exact-stay contract, adds Roofed searches, and keeps its existing pacing/notification pipeline. This standalone probe remains useful for upstream comparisons, not scheduled scanning. Verification below describes each historical probe run, not the current app's full capabilities.

## Build and Offline Check

Run from the repository root with Docker available:

```sh
docker build -t lynx-camp:camply-wa-probe scripts/camply_probe
docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --cap-drop ALL --security-opt no-new-privileges lynx-camp:camply-wa-probe
docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --cap-drop ALL --security-opt no-new-privileges lynx-camp:camply-wa-probe python -m unittest -v
```

The first run verifies imports and Washington's recreation-area mapping without network access. The tests cover destination/method restrictions, redaction, timeouts, pacing, request limits, cooldown validation, and stopping on denied or malformed responses. The container runs as an unprivileged user. It exits after the check and `--rm` removes that test container; the image remains available.

### PR #398 Image

The alternate Dockerfile installs [PR #398](https://github.com/juftin/camply/pull/398) at commit `09b69e4ed502cae2f259bee54e33f36cc7c07bbd`. This branch reports package version **0.34.1**, not 0.34.4. It is the PR source itself, not the latest release with a local patch applied. The report records both version and commit to distinguish the builds.

```sh
docker build -f scripts/camply_probe/Dockerfile.pr398 -t lynx-camp:camply-pr398-probe scripts/camply_probe
docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --cap-drop ALL --security-opt no-new-privileges lynx-camp:camply-pr398-probe
docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --cap-drop ALL --security-opt no-new-privileges lynx-camp:camply-pr398-probe python -m unittest -v
```

This image defaults to an offline check with `--user-agent camply`. When overriding the image command, specify the mode explicitly:

```sh
docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --cap-drop ALL --security-opt no-new-privileges --pids-limit 128 --memory 512m lynx-camp:camply-pr398-probe python probe.py --live --user-agent camply --arrival 2026-11-28 --departure 2026-11-29
```

Review the live-check precautions below before running. This is a single diagnostic search, not a background service. Do not put it on a timer.

## One Live Check

Review **Sources > Washington State Parks** and its saved diagnostics first. Honor any existing cooldown and pause Washington watches before a controlled test. Do not reset the application's access stop just to run this probe. `--not-before` accepts the existing cooldown timestamp, with its timezone; it rejects an early run rather than waiting or contacting the provider.

Choose a future one- or two-night stay. This example uses November 28-29, 2026; update the dates for later tests:

```sh
docker run --rm --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --cap-drop ALL --security-opt no-new-privileges --pids-limit 128 --memory 512m lynx-camp:camply-wa-probe python probe.py --live --arrival 2026-11-28 --departure 2026-11-29
```

When a cooldown exists, append `--not-before` followed by its exact quoted ISO timestamp. The probe deliberately does not mount or open the application's database, so it cannot discover that timestamp itself.

The live sequence is:

1. Use Camply's campground discovery for Washington recreation area `3`, filtered to Bogachiel.
2. Only when exactly one matching campground is returned, ask Camply for that stay's availability.
3. When candidates exist, inspect one candidate's public site-detail response. Do not request every site's details or submit any booking action.

Requests are GET-only to five fixed public Washington API paths, at least five seconds apart, with a 20-second per-request timeout and a maximum of 12 requests. No redirects or automatic retries are allowed. HTTP failures, non-JSON responses, invalid JSON, or oversized JSON responses end the run, with one exception: a 404 from `/api/resource/details` is passed to Camply so the PR's optional-details fallback can run. A 401, 403, or 429 there still stops the check. Exit code `2` means the provider check stopped or Camply failed; it does not mean there are no campsites.

## What Is Being Tested

Camply's discovery, query generation, and parsing are unchanged within the chosen source build. A guarded Requests session replaces its transport to enforce the limits above and suppress upstream raw-body error logging. `--user-agent fixed`, the script default, uses Camp Finder's application identity. `--user-agent camply` preserves the Chrome User-Agent generated by Camply for each request; it does not supply our own browser fingerprint or retry denied requests with new identities. A missing upstream User-Agent in that mode stops before sending.

This is a guarded library compatibility check, not an unmodified CLI benchmark. It does not copy cookies from a browser; ordinary anonymous cookies returned during this one session stay only in memory until the process exits. Authorization and manually supplied Cookie headers are removed in both modes.

Each request prints a small JSON record, followed by a final report. The report includes package versions, the PR commit when applicable, User-Agent mode, request count, endpoint, status, timing, response type/size, header-presence flags, coarse denial classifications, and the failing library stage. A library exception records its type and Camply file/line/function locations, not its potentially sensitive message or local variables. It never prints raw bodies, cookies, authorization headers, or proxy addresses. `site_details_fallback: true` means Camply substituted placeholder details; site names, capacity, and amenities are not verified by that response.

An HTTP 200 alone is not proof of a complete search. `library_error` means access reached the service but Camply could not complete its workflow, when the preceding records show successful HTTP responses. `provider_returned_results` only means the bounded workflow returned; candidates must still be compared with the normal reservation interface. This probe does not validate cabin/yurt coverage, minimum stays, equipment eligibility, or every nested map. The reviewed Camply GoingToCamp connector searches Camping category `0`, not Roofed category `1`.

The User-Agent option is for an explicit compatibility comparison, not an automatic denial-recovery strategy. Stop after a denial; do not loop through identities, replay challenge cookies, or rotate network routes. Reports remain separate from the application's Logs page because this test has no access to its store.

## Verification

### Published Release With Fixed Identity

On November 17, 2026, the image built on local Docker Desktop. Camply reported version 0.34.4 and Pydantic 1.10.27. All ten offline tests passed with networking disabled, including the real library's synthetic discovery/availability workflow and a separate schema-failure case.

At 3:17 PM Pacific, an explicitly requested one-shot live test stopped on its first request:

| Field | Observation |
| --- | --- |
| Operation | GET `/api/resourceLocation`, before campground filtering or date searching |
| Response | HTTP 403, `text/html`, 11,677 bytes |
| Elapsed | 184 ms |
| Classification | Human-verification text detected in the response prefix |
| Headers present | X-Azure-Ref and X-Cache; no Set-Cookie or Via |
| Request context | Fixed application User-Agent, no request cookies, no configured proxy detected |
| Outcome | Discovery stopped; no availability or site-detail request followed |

This is consistent with an access/challenge response rather than a Camply parsing error. It does not identify the exact rule or prove which infrastructure component issued the denial. Absence of proxy configuration does not rule out a transparent intermediary. The browser's earlier successful search does not establish that a fresh server session is allowed.

The test used the guarded transport described above, not Camply's default randomized browser User-Agent. No identity change, browser-cookie replay, redirect, retry, or alternative route was attempted after the denial. The owner's explicit manual test did not clear or shorten the application's automatic access stop. The stopped test container was removed; its image remains available for offline checks.

That initial test verified installation but not live Washington discovery or availability. The separate report is not imported into the application's diagnostic history.

### PR #398 With Camply's Default User-Agent

At 3:25 PM Pacific on November 17, 2026, the explicitly requested PR comparison completed on local Docker Desktop. The pinned branch reported Camply 0.34.1 and Pydantic 1.10.27. All 15 offline tests passed with networking disabled, including preservation of the library-generated header, `rootMapId` discovery, JSON filter encoding, the removed-details fallback, and stopping after an access denial. The rebuilt 0.34.4 image passed 14 tests and skipped the PR-only regression; it was not used for another live request.

| Field | Observation |
| --- | --- |
| Search | Bogachiel, Camping, November 28-29, 2026; one night |
| Catalog | HTTP 200 JSON; 167 raw location records, one matching campground |
| Maps | HTTP 200 JSON; all six records lacked a usable resource-location ID, but the PR used `rootMapId` successfully |
| Availability | Three map requests returned HTTP 200 JSON; Camply returned 19 candidate sites |
| Details | Attribute metadata returned 200; `/api/resource/details` returned 404 and the PR returned placeholder details |
| Traffic | Seven requests in about 32 seconds, at least five seconds apart; no 403, 429, or retries |
| Session | Camply-generated User-Agent; no cookies on the first request, ordinary response cookies on subsequent requests |
| Outcome | `provider_returned_results`, with `site_details_fallback: true` |

This establishes that the pinned Camply branch can retrieve Washington Camping candidates from local Docker without a browser console or login. It does not prove the User-Agent was the sole cause of the changed outcome: the source version, time, and anonymous session also differ from the first run. No cookies were copied from Edge, no proxy was configured, and no reservation or alert was sent.

The 19 candidates were not individually checked in the reservation interface. Roofed accommodations, equipment suitability, multi-night correctness, deeper map hierarchies, statewide coverage, sustained polling, and production Unraid access remain unverified. Site-detail placeholders must not be presented as confirmed names or capacities. Camp Finder's main backend, saved access stop, and production deployment are unchanged; this image is not connected to watches or notifications.

The local report is ignored under `output/playwright/camply-pr398-probe-2026-11-17.log`. The test container was removed after completion; the image remains available. These results support further integration work, not enabling unattended statewide scans yet.

References: [Camply on PyPI](https://pypi.org/project/camply/0.34.4/), [upstream Docker usage](https://juftin.com/camply/how_to_run/#running-in-docker), and [our Washington integration notes](washington-state-parks.md).
