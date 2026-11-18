# Camply Integration Opportunities

Reviewed November 17, 2026. These are candidate improvements, not newly enabled
providers. Camp Finder currently connects Recreation.gov, Washington State Parks,
Snohomish County, King County's Tolt-MacDonald campground, and Skagit's Howard
Miller Steelhead Park. Washington already adapts the successful Camply request
behavior into our async client; the full library is not installed in the app.

## Coverage Priorities

| Priority | Candidate | Benefit and next check |
| --- | --- | --- |
| 1 | Tacoma Power Parks | Our catalog currently marks this source unconnected. Camply lists its GoingToCamp tenant. Verify the catalog and exact stays before enabling discovery and watches. |
| 2 | BC Parks and Parks Canada | Camply lists both GoingToCamp tenants. Useful for trips north of Washington; validate each host and accommodation category independently. |
| 3 | Oregon Metro | Camply has a UseDirect variation for the Portland-area system. This is not Oregon State Parks coverage. Verify the current inventory and booking contract. |
| 4 | ReserveCalifornia | Another supported UseDirect variation, useful for broader West Coast trips after a shared adapter is proven. |
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

- **Equipment filters:** use Camply's equipment-type and length handling as a
  reference for RV/trailer compatibility. Our text Site type filter is not an
  equipment-fit check. Unknown dimensions must remain unknown, not become zero.
- **More alert destinations:** Apprise, Pushover, Telegram, and SMS are useful
  references. Add selected channels behind the current notification service so
  delivery history, secret handling, and pending-result recovery remain shared.
- **Site selection:** a provider-aware campsite picker could replace some free-text
  filtering. It must only show names and attributes actually supplied by that
  provider; Camply cannot recover Washington labels from a retired endpoint.

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
provider search. No extra providers were polled during this review.

Camply does not supply inventory for first-come-only campgrounds, eliminate
provider rate limits, establish account eligibility, or turn alerts into holds.
The unused browser prototype has been [retired](browser-worker.md); it is not a
requirement for any of the proposed API integrations.
