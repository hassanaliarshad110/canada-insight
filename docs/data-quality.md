# Data quality

## The framework

Every build runs these checks (`insight/quality.py`). A **fail** stops the build and the site keeps its last good
data. A **warn** is published on the site's Data quality section.

| Check | What it catches | Fails when |
|---|---|---|
| schema | A renamed or removed field (would silently empty an indicator) | Any expected field missing |
| missing geometry / location | Records that cannot be placed | Over 5% of homes; over 20% of an amenity layer |
| duplicate IDs | Repeated records | Over 1% (areas: any) |
| invalid area code | Records whose community has no boundary | Over 5% |
| outside city extent | Wrong coordinates or the wrong city | Over 2% |
| year out of range | Impossible construction years | Over 10% |
| count change | A large swing against the last build (filter or schema change) | Over 25% |
| stale | The publisher has not updated within the expected time | Warns only |
| metadata | The publisher's metadata could not be read | Warns only |

Tolerances are set per city in `city.json` (`quality`).

## Calgary, first build (5 November 2026)

Overall: **warn**. 43 checks: 42 passed, 1 warning, 0 failures.

| Source | Check | Result |
|---|---|---|
| Property assessments | duplicate roll numbers | Warning: 2,544 repeated records left out (the roll lists some properties more than once; each is counted once) |
| Property assessments | missing outline | Passed |
| Property assessments | community codes | Passed: every home's community has a boundary |
| All amenity layers | location, extent, schema | Passed |
| Transit stops | stale | Passed (last updated 30 September 2026; expected within 120 days) |

## Reconciliation with an independent calculation

During the audit, before this pipeline existed, the playground figure was calculated in separate JavaScript code
against the City's API: 73.2% of 502,008 property records within 400 m of a City playground. The pipeline's
record-count share (`share_primary_records`, each roll record once, duplicates removed) is the comparable figure;
the headline share weights rental buildings by their units.

| Calculation | Records | Within 400 m of a playground |
|---|---|---|
| Audit, independent JavaScript (5 Nov 2026, duplicates not removed) | 502,008 | 73.2% |
| Pipeline, each record once (`share_primary_records`) | 500,028 | 73.3% |
| Pipeline, weighted by dwelling units (headline) | 573,451 units | 71.2% |

The two independent record-count calculations agree within 0.1 percentage points. Weighting rental buildings by
their units lowers the share by 2.2 points: large rental buildings are, on average, farther from City playgrounds.
