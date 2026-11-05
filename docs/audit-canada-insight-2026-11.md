# Audit of Canada Insight (5 November 2026, build of 18:43 UTC)

Two parts: an automatic check of every published figure (`tools/audit_build.py`, run on the real Calgary build), and
a check of every page on desktop (1366 px) and phone (390 px) with the real data in a browser.

## Data checks: 23 passed, 0 failed

| Check | Result |
|---|---|
| Every share between 0 and 1; longer walking distance never lower than the shorter | Passed |
| City's only ≤ open to everyone ≤ with private, for every community and amenity | Passed |
| Community homes add up to the city (573,451) | Passed |
| Ward homes add up to the city (573,451) | Passed |
| 14 wards present; ward figures agree with their communities (largest difference under 0.1 point) | Passed |
| Crowding for all six amenities, by community and by ward, never negative | Passed |
| All four ways of counting residents, default "City's total, shared by actual growth" (as Calgary Data Desk) | Passed |
| Every score inside its range; ward scores present | Passed |
| Dashboard: every figure shown is present, 14 wards, read today | Passed |
| Residents: Calgary 1,598,075 and the 14 wards add up to it exactly (same as Calgary Data Desk) | Passed |
| Homes lived in: 565,996, identical to Calgary Data Desk | Passed |
| No failed quality checks; every source has rows | Passed (1 warning: 2,544 repeated roll records counted once) |

## Page checks

| Found | Fixed |
|---|---|
| On phones the ward picker was wider than the screen (sideways scrolling on every page) | Yes |
| Choosing a ward through a link inside the page updated the picker but not the dashboard | Yes |
| The dashboard and ward comparison ignored the "City's only / with private" filter | Yes |
| "a indoor recreation centre" | Yes |
| No script errors, no "undefined"/"NaN" on any page, either width | Checked |

## What changed in the findings with non-City amenities

Adding playgrounds and parks open to everyone that the City doesn't list (600 playgrounds, 290 parks from
OpenStreetMap, after removing 968 and 2,249 that the City already lists):

| | City's only | City + open to everyone |
|---|---|---|
| Calgary homes within 400 m of a playground | 71% | 85% |
| Ward 5 | 79% | 89% |
| Beltline | 30% | 61% |
| Downtown West End | 0% | 0% |

## Open issues (not fixable in code)

- **Community centres**: several large communities, most of Ward 5 among them, show none within 800 m. The City's
  "Community Services" list may not include every community association hall. Flagged on the site with a "Check" label;
  the district scores depend on it. Needs a check against the Federation of Calgary Communities' list.
- **Research assistant**: built and tested, waiting for the Cloudflare account and three repository secrets.
- **Build time**: about 28 minutes, mostly park distances; within the 2-hour limit.
