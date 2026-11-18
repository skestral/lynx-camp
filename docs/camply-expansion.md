# Additional Providers and Watch Filters

Camp Finder uses Camply's provider contracts as references for its native async
adapters. It retains one scheduler, result store, and notification pipeline.
There is no browser console, browser-cookie export, or second polling service.
The full Camply package is not installed because it requires a different Pydantic
major version. Apprise is installed separately for additional alert destinations.

## Provider Coverage

Open **Targets > Sources**, leave Region set to All regions, and expand the
appropriate source group. Check a source to preview its catalog, then import it.
Imports preserve existing target IDs and watches. Regional watches enroll future
imports only when that option is enabled.

| Source | Coverage | Verification on November 17, 2026 (Pacific) |
| --- | --- | --- |
| Tacoma Power Parks | Alder Lake, Mayfield Lake, Mossyrock, Taidnapam; Camping only | Four catalog targets. Mossyrock May 7-9, 2027 returned a complete search with no matches. |
| BC Parks | Catalog locations with frontcountry Camping categories | Public catalog accepted. Exact stays not live-verified; a homepage request encountered an access challenge. |
| Parks Canada | Catalog locations with frontcountry Camping categories | Public catalog accepted. Exact stays not live-verified; a homepage request encountered an access challenge. |
| Oregon Metro | Oxbow campground and group camp | Two targets. December 4-6, 2026 returned a valid calendar with no matches. This is not Oregon State Parks. |
| ReserveCalifornia | Conservative campground/lodging discovery, currently 238 targets | Docker check at Borrego Palm Canyon, sites 53-89, found 23 full-stay matches for December 7-9, 2026. All supplied equipment and length data. |

These new sources remain **experimental**. A successful catalog request does not
prove every campground or accommodation category works. Counts are observations,
not permanent inventory totals or guaranteed availability. No reservation was
held or booked, and no real notification was sent during verification.

Washington retains its existing Camping and Roofed coverage, including cabins and
yurts. The new GoingToCamp tenants intentionally exclude Roofed, backcountry,
group, day-use, and ticket categories until their individual contracts are verified.
Parks Canada targets use `CAN` for country-wide grouping and the provider's park
timezone; BC Parks uses `BC`. Missing coordinates remain missing.

UseDirect catalogs mix campground facilities with permits and day-use rentals.
Metro is limited to its two verified Oxbow facility IDs. California discovery
uses overnight facility names plus the verified Borrego Palm Canyon facility;
it is not an exhaustive state inventory. Calendar matches additionally require
a recognized overnight category, a complete set of occupied nights, online
eligibility, season dates, and valid booking/stay limits. Walk-ins, draws, blocked
nights, and temporary locks are not matches. Lodging categories are supported by
the parser but cabin-specific live coverage has not yet been verified.

Booking links open the provider website for manual checkout. UseDirect links do
not prefill dates or select a campsite. Check the result's dates and site name on
the provider website before booking.

## Equipment and Campsite Selection

In **Watches**, choose equipment and optionally enter vehicle length in feet.
Equipment-fit filtering currently supports Recreation.gov and UseDirect targets.
Separate other providers into an unfiltered watch; mixed-provider equipment
watches are rejected by the editor, and restored unsupported watches fail with
an explicit scan error rather than reporting a misleading empty result.

- Recreation.gov supplies permitted equipment and per-equipment length limits.
  Metadata is fetched only for available sites matching the other filters, paced
  through the scanner, and cached for 24 hours, up to 2,000 sites in memory.
- UseDirect supplies sleeping-unit types and a site-level vehicle limit when
  available. Some Metro sites omit this metadata. Those sites cannot satisfy
  equipment or length requirements that cannot be verified.
- A missing or zero length is unknown, not unlimited. Site type text such as
  "RV" is not a substitute for equipment compatibility.
- **Specific campsites** lists campsite IDs from loaded availability results for
  the selected targets, plus any IDs already saved on the watch. It is not a full
  provider inventory. No selection means any site; Clear Selection removes the
  whitelist. The same selection survives configuration export and import.

Equipment checks may add requests to a large Recreation.gov scan. The crawl can
continue in the background; initial ETA does not know how many new site metadata
requests will be needed. Logs records those requests and cancellation is checked
before each request.

![Equipment and campsite selection in a watch](screenshots/equipment-watch.png)

[Mobile watch editor](screenshots/equipment-watch-mobile.png)

## Additional Alerts

Existing Discord, Home Assistant, ntfy, and SMTP settings continue to work.
**Settings > Apprise destinations** adds Pushover, Telegram, and Twilio SMS. Use
one service URL per line, up to ten unique URLs. Only those three URL schemes are
accepted; file/config loaders and custom notification plugins are not enabled.

Get the exact URL syntax from the official service documentation:

- [Pushover](https://appriseit.com/services/pushover/)
- [Telegram](https://appriseit.com/services/telegram/)
- [Twilio](https://appriseit.com/services/twilio/)

Generic shapes, with placeholders rather than working credentials:

```text
pushover://USER_KEY@APP_TOKEN
tgram://BOT_TOKEN/CHAT_ID
twilio://ACCOUNT_SID:AUTH_TOKEN@FROM_NUMBER/TO_NUMBER
```

Save Notifications stores the URLs in appdata. A blank field retains the existing
destinations. Clear Secrets removes all saved notification secrets, including
these URLs; environment defaults still apply. `CAMPFINDER_APPRISE_URLS` is the
environment alternative. Normal exports redact it. Explicit secret-bearing
exports include it and must be protected like a password file.

Test Notifications is a real send to all configured channels. SMS charges may
apply. Automated tests use fake delivery and do not prove your account credentials
or messaging-service permissions. Delivery history reports Apprise as one channel;
a partial failure reports an error without exposing tokens or provider responses.
Each attempt has a 30-second delivery deadline. The app never logs raw Apprise
errors or notification URLs.

[Mobile alert settings](screenshots/apprise-settings-mobile.png)

## Diagnostics and Upgrades

The normal Docker image contains these integrations; rebuild/pull it and recreate
the existing container while preserving `/data`. No schema reset is required.
New watch fields use the existing JSON filter column; new notification secrets use
the existing app-settings table. Existing Washington IDs, results, and credentials
are unchanged.

Open **Logs > Provider Diagnostics** and choose the provider. The source's log icon
selects it directly. Refresh and Download read saved diagnostics, not the provider.
Each tenant has independent pacing, cooldowns, a manual access stop, and a bounded
history of 30 redacted HTTP records. Requests are serialized with at least five
seconds between them, in addition to scanner pacing. Catalogs are cached for a day.
An HTTP 429 waits for at least an hour or the provider's longer Retry-After value.
Denials, redirects, and HTML responses stop access until reviewed and manually reset.
Do not repeatedly reset a stop to work around a challenge.

![Provider-specific diagnostic history](screenshots/provider-diagnostics.png)

The local Docker upgrade test preserved 102 targets, two watch members, 20 results,
and the paused crawl. The backend suite passed 377 tests inside the Docker image
with external networking disabled. Tests cover malformed/partial calendars,
eligibility flags, cancellation, persisted tenant stops, equipment matching,
watch-result-notification deduplication, secret redaction, and backup restoration.
Desktop and mobile checks cover provider selection and the new watch controls.

## Yellowstone

NPS says all Yellowstone campground reservations move to Recreation.gov for the
2027 summer season. The bounded search on November 17 still returned only the five
already bundled: Tower Fall, Indian Creek, Lewis Lake, Mammoth, and Slough Creek.
No IDs were invented or removed. Use the Yellowstone pack's **Check source** and
**Import source list** as more listings appear. Existing watch membership remains
intact. See the [NPS campground notice](https://www.nps.gov/yell/planyourvisit/campgrounds.htm).

Tickets and timed entry are deliberately deferred. They need a separate quantity
and time-slot model rather than campsite-night watches.
