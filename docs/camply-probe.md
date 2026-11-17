# Camply Washington Probe

This is an isolated compatibility test for Camply 0.34.4, not a second crawler or a replacement for Camp Finder. It uses the published Python package in its own Docker image because Camply requires Pydantic 1 and the application uses Pydantic 2. Nothing is installed into the main backend environment.

The probe has no web interface, browser worker, exposed port, appdata mount, account login, or notification configuration. It does not import targets, create watches, change the application's access stop, or reserve inventory. Default execution is offline.

## Build and Offline Check

Run from the repository root with Docker available:

```sh
docker build -t lynx-camp:camply-wa-probe scripts/camply_probe
docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --cap-drop ALL --security-opt no-new-privileges lynx-camp:camply-wa-probe
docker run --rm --network none --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m --cap-drop ALL --security-opt no-new-privileges lynx-camp:camply-wa-probe python -m unittest -v
```

The first run verifies imports and Washington's recreation-area mapping without network access. The tests cover destination/method restrictions, redaction, timeouts, pacing, request limits, cooldown validation, and stopping on denied or malformed responses. The container runs as an unprivileged user. It exits after the check and `--rm` removes that test container; the image remains available.

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

Requests are GET-only to five fixed public Washington API paths, at least five seconds apart, with a 20-second per-request timeout and a maximum of 12 requests. No redirects or automatic retries are allowed. Any HTTP failure, non-JSON response, invalid JSON, or oversized response ends the run. Exit code `2` means the provider check stopped or Camply failed; it does not mean there are no campsites.

## What Is Being Tested

Camply's discovery, query generation, and parsing are unchanged. A guarded Requests session replaces its transport to enforce the limits above, use Camp Finder's fixed application User-Agent instead of random browser identities, and suppress upstream raw-body error logging. This is a guarded library compatibility check, not an unmodified CLI benchmark. It does not copy cookies from a browser; ordinary anonymous cookies returned during this one session stay only in memory until the process exits.

Each request prints a small JSON record, followed by a final report. The report includes package versions, request count, endpoint, status, timing, response type/size, header-presence flags, coarse denial classifications, and the failing library stage. A library exception records its type and Camply file/line/function locations, not its potentially sensitive message or local variables. It never prints raw bodies, cookies, authorization headers, or proxy addresses.

An HTTP 200 alone is not proof of a complete search. `library_error` means access reached the service but Camply could not complete its workflow, when the preceding records show successful HTTP responses. `provider_returned_results` only means the bounded workflow returned; candidates must still be compared with the normal reservation interface. This probe does not validate cabin/yurt coverage, minimum stays, equipment eligibility, or every nested map. The reviewed Camply GoingToCamp connector searches Camping category `0`, not Roofed category `1`.

Do not rerun a denial with different browser identities, copied challenge cookies, or alternative network routes. Stop and review access requirements. Reports remain separate from the application's Logs page because this test has no access to its store.

## Verification

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

Camply installation is verified, but Washington live discovery, Camping availability, Roofed coverage, and production Unraid access are not. The separate report is not imported into the application's diagnostic history. Do not enable continuous polling on the basis of this test.

References: [Camply on PyPI](https://pypi.org/project/camply/0.34.4/), [upstream Docker usage](https://juftin.com/camply/how_to_run/#running-in-docker), and [our Washington integration notes](washington-state-parks.md).
