# Third-Party Data

## Cedar Holiday Calendar

`backend/app/cedar_holidays.json` is generated from the US calendar in
[date-holidays](https://github.com/commenthol/date-holidays), version 3.39.2.
The date-holidays project credits these sources for its US calendar:

- [Public holidays in the United States](https://en.wikipedia.org/wiki/Public_holidays_in_the_United_States)
- [Washington's Birthday](https://en.wikipedia.org/wiki/Washington%27s_Birthday)
- [5 USC 6103](https://uscode.house.gov/view.xhtml?edition=prelim&req=granuleid%3AUSC-prelim-title5-section6103&f=treesort&num=0)

The generated calendar is distributed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), as is the upstream
holiday dataset. Changes: restricted to US dates in 2026-2035, removed the
observance names excluded by Cedar's reservation form, and retained only ISO
calendar dates. Exclusions use the provider's exact name strings; holidays with
different names in the pinned library remain included conservatively. This data
license does not change the application's code license.

Regenerate it from `frontend` with `npm ci` and `npm run generate:cedar-holidays`.
Review changes against the provider's public booking rules before committing.
Years outside this snapshot fail closed rather than guessing holiday minimums.

## Campground Map Point

Howard Miller Steelhead Park's map point uses
[OpenStreetMap node 4360829121](https://www.openstreetmap.org/node/4360829121),
copyright OpenStreetMap contributors, available under the
[Open Database License](https://www.openstreetmap.org/copyright).
The reservation provider currently returns no site coordinates. The map point
identifies the campground entrance, not an individual campsite.

## Canadian Location Reference

`backend/app/canadian_locations.json` contains public park/campground names,
reference coordinates, and source links derived from:

- [BC Parks protected-area directory](https://bcparks.api.gov.bc.ca/api/protected-areas),
  published by the Province of British Columbia. Each selected park retains its
  official `bcparks.ca` page URL.
- [Parks Canada accommodations open dataset](https://open.canada.ca/data/en/dataset/74054d44-68cf-41af-8919-5f09f80dcd02),
  published by Parks Canada. The generator reads its
  [accommodation feature layer](https://services2.arcgis.com/wCOMu5IS7YdSyPNx/ArcGIS/rest/services/Accommodation_Hebergement_APCA_OpenOuvert/FeatureServer/0).
- [Parks Canada national park boundaries](https://services2.arcgis.com/wCOMu5IS7YdSyPNx/ArcGIS/rest/services/PCA_Boundaries_NP/FeatureServer/8),
  used only to check the park identity of accommodation points.

Changes: selected the supported reservation targets, normalized names for
matching, rejected ambiguous or geographically dispersed matches, and selected
one representative accommodation point per matched campground. The reference
does not reproduce park descriptions, photographs, or boundary geometry and is
not endorsed by these providers. See [Canadian locations](canadian-locations.md)
for precision, known gaps, and regeneration instructions.
