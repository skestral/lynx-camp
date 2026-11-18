# Camply Integration Opportunities

Reviewed and implemented November 17, 2026. The campground-first expansion now
includes native adapters, equipment filters, a result-backed campsite picker,
and selected Apprise destinations. See the [implementation guide](camply-expansion.md)
for installation, verification evidence, and limitations. The full Camply library
is not installed in the app.

## Coverage Priorities

| Priority | Candidate | Benefit and next check |
| --- | --- | --- |
| 1 | Tacoma Power Parks | Experimental connector enabled for four Camping locations. Catalog and one exact stay verified; broader seasonal checks remain. |
| 2 | BC Parks and Parks Canada | Experimental Camping connectors. Catalog verified; exact-stay access remains unverified. No Roofed or backcountry coverage claim. |
| 3 | Oregon Metro | Experimental UseDirect connector for two Oxbow facilities. Empty-calendar stay verified. This is not Oregon State Parks coverage. |
| 4 | ReserveCalifornia | Experimental UseDirect connector; 23 full-stay matches verified in Docker at one campground. Discovery is deliberately not exhaustive. |
| Separate workflow | Recreation.gov tickets and timed entry | Camply provides search implementations, but these need time-slot and quantity models rather than pretending a permit is a campsite night. |

Provider listings establish implementation references, not proof that requests
will succeed from our Docker host. Sources: [Camply providers](https://juftin.com/camply/providers/)
and [UseDirect variations](https://juftin.com/camply/reference/providers/usedirect/variations/).
Tacoma's official directory lists [Alder Lake, Mayfield Lake, Mossyrock, and Taidnapam](https://www.mytpu.org/community-environment-parks/parks-recreation/),
which makes it the most directly relevant local expansion.
Its [reservation instructions](https://www.mytpu.org/community-environment-parks/parks-recreation/reservations-fees/)
confirm a separate GoingToCamp service. Earlier development requests encountered
an access challenge, so the working Washington connector is not proof that this
tenant will accept unattended searches. Seasonal first-come periods also need to
be distinguished from reservable dates.

### Yellowstone Transition

Camply documents a separate Xanterra camping connector, but NPS now says all
Yellowstone campground reservations move to Recreation.gov for the 2027 summer
season. First audit our Yellowstone discovery against the new listings and
preserve existing watch membership. Building another backend for the old
concessionaire inventory is lower priority unless a remaining need is verified.
See the [current NPS campground notice](https://www.nps.gov/yell/planyourvisit/campgrounds.htm).

## Improvements Beyond Coverage

- **Equipment filters:** implemented for Recreation.gov and UseDirect. Other
  providers remain unsupported for fit checks; unknown lengths do not pass.
- **More alert destinations:** Pushover, Telegram, and Twilio SMS are available
  through Apprise behind the existing notification service and secret handling.
- **Site selection:** a picker now uses loaded results and preserves selected IDs
  in backups. Full inventory browsing remains a follow-up. Washington labels
  are still unavailable; the picker does not invent campsite names.

Camply documents [equipment filters, site IDs, and notification options](https://juftin.com/camply/command_line_usage/).
We already have weekday/date windows, consecutive nights, background crawling,
deduplication, persisted cooldowns, and several alert channels. Replacing those
with a second search loop would duplicate state and risk extra provider traffic.

## Implementation Approach

Prefer focused adapters using Camply's contracts and upstream tests as references,
as with Washington. Its current [package metadata](https://github.com/juftin/camply/blob/main/pyproject.toml)
requires Pydantic 1; our backend uses Pydantic 2. Do not install it into the same
environment or downgrade the app merely to gain another provider. An isolated,
one-shot JSON worker remains an option if a future connector needs enough of the
library to justify that boundary. It should not own polling or notifications.

For additional GoingToCamp tenants, keep existing `gtc:wa:` IDs stable and add an
allowlisted host/tenant mapping. Categories, equipment IDs, booking links,
timezones, cache keys, cooldowns, and diagnostic state must stay tenant-specific.
Do not assume Washington's category IDs or reservation rules apply elsewhere.

Before marking any new source live, test discovery, full stays, no availability,
partial/malformed data, cancellation, 403/429 handling, deduplication, alerts,
and backup restoration. Then make a bounded Docker check and compare a normal
provider search. See the implementation guide for the checks actually performed;
synthetic contract tests are not proof of live provider access.

Camply does not supply inventory for first-come-only campgrounds, eliminate
provider rate limits, establish account eligibility, or turn alerts into holds.
The unused browser prototype has been [retired](browser-worker.md); it is not a
requirement for any of the proposed API integrations.
