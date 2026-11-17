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
