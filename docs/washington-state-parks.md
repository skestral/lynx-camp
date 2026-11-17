# Washington State Parks Integration

## Status

Washington State Parks is the next provider priority, ahead of additional county connectors. It is not connected to live availability yet. The Sources drawer links to the official reservation directory, but importing and scanning state-park inventory remain disabled.

On November 17, 2026, a normal browser request to the Washington GoingToCamp service from the development host returned a firewall denial. No workaround was attempted. Access from the production Docker host has not been verified. Retrying through another host, copying challenge cookies, or rotating browser identities is not an integration solution.

The first requirement is a permitted data-access path and its usage limits. Do not enable a scanner or advertise complete coverage based only on offline fixtures.

## Browser-Based Option

The owner reports that the reservation site works in their ordinary browser. That is useful evidence, but does not establish access from a Docker browser or identify why the development browser was denied.

A browser connector is an alternative to a direct API integration where permitted. The next diagnostic is to inspect a working, user-authorized session's normal search interface and confirm complete camping and roofed stays. Do not export challenge cookies or replay browser credentials through a denied API.

For unattended remote hosting, the proposed design is a dedicated browser worker alongside Camp Finder, with a separate persistent profile under appdata. It would operate the normal search UI one stay at a time, feed validated results into the existing scan pipeline, and expose waiting/error/cancel states. An authenticated, private interactive console could let the owner handle required login or human-verification steps. It must pause for those steps and stop on denial, not solve or evade them automatically. Manual completion is not a guarantee that unattended use is supported.

[Playwright supports Docker](https://playwright.dev/python/docs/docker), but a production crawler needs a non-root sandboxed browser and private control endpoints. Browser profiles are sensitive; [Playwright's authentication guidance](https://playwright.dev/python/docs/auth) warns against committing stored browser state. Exclude profiles from Git, image build contexts, ordinary settings exports, and diagnostic screenshots. Do not use the owner's everyday browser profile as the server profile.

A local browser helper would require the owner's computer to remain available, so it does not meet the remote-only deployment requirement. A permitted API/feed remains the lighter operational option. Neither approach has been implemented or verified for Washington in Camp Finder yet.

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

A normal request from the development host received a firewall denial, so integration testing has stopped. Please advise on the supported access method, any credentials or approval required, acceptable polling and caching intervals, and coverage of cabins and yurts as well as campsites.

Thank you.
