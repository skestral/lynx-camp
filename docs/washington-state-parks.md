# Washington State Parks Integration

## Status

Washington State Parks now has an **experimental native API connector** in the regular Camp Finder backend. It adapts GoCamp's discovery/search workflow to the newer availability-map contract. There is no browser-console requirement, separate worker dependency, or account login. Sources exposes Check and Import, and imported targets use the existing watch, notification, and scan-log pipeline.

Live compatibility is **not verified**. On November 17, 2026, the direct catalog request returned HTTP 403 from the development host, and testing stopped. Earlier normal browser access from that host also encountered a firewall denial. No workaround was attempted. Access from the production Docker host has not been verified. Retrying through another host, copying challenge cookies, or rotating browser identities is not an integration solution.

The remaining requirement is a permitted data-access path and validation against current responses. Passing synthetic tests proves the integration behavior, not provider access or complete campground coverage. The source is deliberately not counted among verified live sources.

## Setup

1. Update the regular Camp Finder image using the [README installation instructions](../README.md). Existing databases require no destructive migration; connection state uses the existing app-settings table.
2. Open **Targets > Sources > Washington state**. Washington State Parks is labeled **Experimental API**. Check requests the park and accommodation catalogs; Import discovers and saves supported targets. Neither action makes a reservation.
3. A successful import creates separate Camping and Roofed targets per park when those categories are recognized. Day-use-only locations are excluded. A Washington regional watch with **Include future imports** enabled picks them up automatically; otherwise edit the watch's saved coverage or create a watch for the Washington State Parks group.
4. For Friday and Saturday nights, use Friday arrival and two nights. Leave site type blank to include both categories, or use `Camping` or `Roofed`. The experimental response does not establish individual cabin/yurt type, loop, or capacity, so those detailed filters produce an explicit error instead of a misleading empty result.
5. Existing Discord, Home Assistant, and email settings apply to new matches. Review the provider's final rules, party size, equipment, and eligibility before booking. Results are candidates, not reservations or cart holds.

No new environment variable, API key, or browser profile is required. The optional browser worker can remain stopped. Do not delete the database to clear an access problem.

### Access Stops and Rate Limits

The connector makes serialized requests with at least five seconds between responses and subsequent requests. Scan requests also honor **Settings > Scan controls**. A complete park check may require many nested maps and two availability requests per map; completion estimates are approximate and can grow as those maps are discovered.

HTTP 429 waits at least one hour, or longer when Retry-After requires it. The existing crawler also applies its provider-specific cooldown. A 401/403, redirect, or HTML challenge stops API requests until reviewed, even across a container restart. It never falls back to a browser or turns a denial into "no availability." Previously saved results remain intact on failed checks.

Sources shows the saved error and earliest review time. Check and Import are disabled while stopped or cooling down. After resolving access and waiting out the cooldown, **Reset access stop** asks for confirmation. Resetting does not send a provider request, but active watches may resume requests on their next scheduled run. Pause those watches first when you want to make only a manual Check. Logs records scan errors and request stages.

## Implementation and Limits

- Catalog requests use `/api/resourcelocation` and `/api/resourcecategory`, require recognized Camping and Roofed category metadata, and use each location's `rootMapId`. Complete metadata is cached for 24 hours; explicit Check/Import refreshes it.
- Searches use GET `/api/availability/map`, JSON-encoded `filterData`, booking category 0 or 1, and the requested arrival/departure. Camping uses the upstream tent-equipment default; Roofed omits camping equipment. This does not prove suitability for every RV size or party.
- Each map is requested with full-stay and daily availability. A candidate must be open in the full-stay result and on every occupied night. Child maps are traversed completely with cycle, duplicate, and size checks. Incomplete or conflicting records raise an error.
- Site names fall back to provider IDs; capacity, facilities, eligibility restrictions, and specific roofed type remain unknown. Party size is one in the upstream query. Booking links carry category, park, leaf map, arrival, departure, and nights, but current provider date-prefill behavior has not been verified.
- The full-stay/nightly response shapes are assumptions from public upstream code, not captured live fixtures. Changed contracts fail visibly. Availability code zero is the only accepted positive status; nonzero codes are not emitted as matches.
- Targets and watches are included in normal configuration exports. Runtime denial/cooldown state is not portable configuration and stays in appdata. This connector stores no account credentials or browser cookies.

[Camply PR 391](https://github.com/juftin/camply/pull/391) and [PR 398](https://github.com/juftin/camply/pull/398) describe newer `rootMapId`, removed-detail-endpoint, and filter serialization changes. They inform this adapter; their authors' live checks are not Camp Finder verification. [GoCamp attribution](../third_party/gocamp/NOTICE.md) and its MIT license are included in the repository and Docker image.

[Desktop source status](screenshots/washington-source.png) | [Mobile source status](screenshots/washington-source-mobile.png)

## Optional Browser Diagnostics

The reservation workflow was inspected in the owner's existing Edge session on November 17, 2026, after an explicit handoff. Anonymous camping and roofed results loaded there. This does not establish access from a Docker browser or identify why the development browser was denied.

A browser connector is an alternative to a direct API integration where permitted. An [isolated Docker browser worker](browser-worker.md) now provides a private console and read-only inspection of a manually submitted search. Its runtime and synthetic-page checks pass; Washington access from that worker and complete live-result collection have not been verified. Do not export challenge cookies or replay browser credentials through a denied API.

The earlier browser-based proposal is not the chosen scanning architecture. The worker remains an optional diagnostic tool with a separate persistent profile and private console. It does not feed watches or notifications, solve challenges, or establish permission for unattended use.

[Playwright supports Docker](https://playwright.dev/python/docs/docker), but a production crawler needs a non-root sandboxed browser and private control endpoints. Browser profiles are sensitive; [Playwright's authentication guidance](https://playwright.dev/python/docs/auth) warns against committing stored browser state. Exclude profiles from Git, image build contexts, ordinary settings exports, and diagnostic screenshots. Do not use the owner's everyday browser profile as the server profile.

A local browser helper would require the owner's computer to remain available, so it does not meet the remote-only deployment requirement. The native adapter runs with Camp Finder on the server; only its live access and compatibility remain unverified.

## Interactive Verification

The November 17 inspection used only the normal search interface, with no sign-in, cookie export, direct API replay, notification subscription, reservation, or cart action. These are point-in-time UI observations, not held inventory or proof of unattended access:

- Camping: Bogachiel's Campground list showed Site 2 as Available for November 28-29, 2026, with an enabled Reserve button. Expanded details allowed tents and a van/camper, listed capacity eight, and distinguished `ADA Only: No` from `ADA Accessible: Yes`.
- Roofed: Lincoln Rock's Deluxe Cabins list showed C7 as Available for November 28-30, 2026, with an enabled Reserve button and capacity six. The cabin was labeled ADA accessible; checkout eligibility was not tested.
- The Camping search URL used `searchTabGroupId=0` and `bookingCategoryId=0`; Roofed used `1` for both and omitted camping equipment parameters. These are observed browser-navigation parameters, not a verified API contract.
- Navigation followed region, park, section, and individual site levels. `View more` appeared at regional and campsite levels. Exhausting one page is not a complete inventory scan.
- Switching the form from Camping to Roofed left the previous camping results visible until a new search was submitted. A collector must match the submitted URL category, park, dates, and rendered results to the requested stay, not merely read the current form selection.
- Availability initially remained in a loading-placeholder state. The collector must distinguish loading, explicit empty results, and failures, with bounded waits and cancellation. Blank markup is never proof of no availability.

Observed controls include `park-autocomplete-input`, `arrival-date-field`, `departure-date-field`, `nightsTab`, `nights-field`, `actionSearch`, `list-view-button-button`, and `loadMoreButton`. Map-navigation buttons used `mapLink-button-*`; individual-site results expanded into a named Details region with a separate Reserve button. Follow navigation and detail controls only. Never click Reserve to test whether a site is available.

The provider also exposes a Notify me action. Its account requirements, delivery behavior, and automation interface have not been verified; Camp Finder does not subscribe to those alerts.

## Intended Coverage

- Discover reservable Washington state parks and their overnight accommodation categories dynamically.
- Search complete stays for tent/RV sites, cabins, yurts, and other verified roofed accommodations. Exclude day-use inventory.
- Reuse Washington, park-group, and map-area watches. New imports join existing matching groups only when Include future imports is enabled.
- Use the existing paced crawl, provider-specific cooldown, cancellation, diagnostic events, and Discord/Home Assistant/email notification paths.
- Open the provider's booking page for manual checkout. Availability monitoring does not require implementing account login, cart holds, or payment.

First-come sites, closed loops, and inventory outside the reservation window must not appear as bookable matches. A park directory is useful for discovery, but does not answer whether a specific stay is available.

## Public References

[Washington's reservation instructions](https://parks.wa.gov/passes-permits/reservations/making-reservations) identify GoingToCamp as the booking service. They describe a nine-month reservation window for ordinary stays, distinct last-minute cutoffs by accommodation, and roofed-accommodation minimum stays. ADA-only sites require eligibility. These rules need to be checked against the current provider response before a match is emitted; a generic federal booking window is not appropriate.

The [reservation parks directory](https://parks.wa.gov/passes-permits/reservations/reservation-parks) and [winter schedule](https://parks.wa.gov/find-activities/winter-schedule) describe seasonal differences. Do not assume that every park or loop accepts reservations year-round.

[OpenCamp](https://github.com/opencamp-hq/cli) targets Recreation.gov and does not supply a Washington State Parks connector.

[Camply's GoingToCamp implementation](https://github.com/juftin/camply/blob/9c4eee52c51bd734ddd72c223c0a4fd0f6f066b0/camply/providers/going_to_camp/going_to_camp_provider.py) is a useful public contract reference. It was reviewed at commit `9c4eee52c51bd734ddd72c223c0a4fd0f6f066b0`; it is not installed as a Camp Finder dependency. There are important gaps to resolve before reuse:

- [Issue 377](https://github.com/juftin/camply/issues/377) reports a Washington discovery failure when maps have no resource-location ID. Validate the location's `rootMapId` relationship instead of joining every map by location ID.
- The reviewed search fixes `bookingCategoryId` to `0` and limits discovery to named camping categories. This does not establish roofed-accommodation coverage. Discover and verify the applicable categories and equipment requirements.
- The reviewed traversal visits the root map and one additional level. Verify the full map hierarchy, including deeper children, repeated links, and cycle detection.
- Its availability parser accepts the first status entry with value `0`. Verify what each status and array entry means for the requested full stay, rather than copying that assumption.
- Its request wrapper selects a browser user agent. Do not use identity rotation or challenge-token reuse to work around access denial.

Public source code is a starting point for contract research, not evidence that current Washington responses match it or that unattended requests are permitted.

### GoCamp Review

[peckjon/gocamp](https://github.com/peckjon/gocamp) was reviewed on November 17,
2026 at commit `21d1000bef6df9f1d53a12881599ad60a87661fd`. It is an MIT-licensed,
Washington-specific Python HTTP wrapper, not a browser driver. Its API structure
is useful reference material, but it has not been installed or run against the
provider in this project.

The [current search code](https://github.com/peckjon/gocamp/blob/21d1000bef6df9f1d53a12881599ad60a87661fd/app.py)
fixes `bookingCategoryId` to camping and party size to one, passes the same value
for equipment and sub-equipment, and expects older map fields. It calls
`requests.get/post(...).json()` without timeouts, HTTP status checks, pacing, or
Retry-After handling. Its booking helper creates a link; it does not reserve sites.
Do not infer working cabin coverage from the category menu in its console example.

[Issue 3](https://github.com/peckjon/gocamp/issues/3) records upstream schema changes,
including missing `mapLinkLocalizedValues`, and a 2022 comment pointing to Camply's
replacement implementation. These historical reports do not establish today's
service behavior. The latest repository change is a September 2025 contributor
workflow; the last `app.py` change is July 2021.

GoCamp is an additional contract reference, not a drop-in connector or a solution
to denied access. A permitted direct API integration remains an option; the browser
diagnostic worker does not commit Camp Finder to browser-only scanning.

## Enablement Checklist

1. Establish a permitted API/feed or browser workflow, authentication requirements if any, request limits, and caching guidance. Keep any credentials outside Git. Resolve the observed denial before unattended testing; do not switch request routes to evade it.
2. Validate discovery against current campground, root-map, and accommodation-category records. Preserve provider-qualified IDs without changing existing federal or county IDs.
3. Verify at least one tent/RV stay and one cabin/yurt stay against the normal booking interface. Include a sold-out stay, partially available stay, closed period, and dates outside the release window. Check minimum stays, capacity, equipment, and eligibility restrictions.
4. Confirm that every occupied night belongs to the same campsite. Validate pagination and nested maps completely before treating a scan as successful. Unknown or partial responses must preserve existing matches and report an error, not return an empty success.
5. Route every HTTP request, including discovery and detail lookups, through serialized pacing and the scanner's cancellation/progress gate. Cache stable metadata. Honor Retry-After and persisted provider-specific cooldowns; stop on access denial or a login/challenge page.
6. Add fixture tests for malformed responses, unknown statuses/categories, missing maps, duplicates/cycles, full-stay rules, cancellation, and cooldown behavior. Cover regional import, watch expansion, notification deduplication, and backup round trips with isolated stores and fake notifications.
7. Verify booking links with the selected park, arrival, departure, and accommodation. Do not claim date-prefill support until tested. Test the target import and watch flows at desktop and mobile widths.
8. Run the backend suite and frontend build, perform a bounded read-only deployment check through the permitted access path, and record the verification date and limits. Only then change the source to `ready`, update user documentation, and capture screenshots.

## Access Inquiry Draft

This draft has not been sent. The official [Washington State Parks information center](https://parks.wa.gov/passes-permits/reservations) lists `infocent@parks.wa.gov`; [Camis](https://www.camis.com/contact) also has an integration inquiry contact form.

Subject: Read-only reservation availability integration for Washington State Parks

Hello,

I maintain a self-hosted campground availability monitor for personal trip planning. I would like to include Washington State Parks camping and roofed accommodations alongside other reservation systems.

Is there an approved API, data feed, or integration program for retrieving campground metadata and checking complete-stay availability? The application would cache metadata, serialize requests, honor your polling limits and Retry-After responses, and link visitors to your website for booking. It would not create reservations or access customer records.

A development browser received a firewall denial, while manual searches in an existing interactive browser worked. Unattended access has not been verified. Please advise on the supported access method, any credentials or approval required, acceptable polling and caching intervals, and coverage of cabins and yurts as well as campsites.

Thank you.
