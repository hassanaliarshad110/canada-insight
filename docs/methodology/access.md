# Indicator method: access to everyday amenities

Code: `insight/indicators/access.py` (the formulas), `insight/pipeline.py` (data preparation).
Tests: `tests/test_access.py`, `tests/test_pipeline.py`.

## The question

Can residents walk to everyday amenities, and are homes built since the last Census as well served as older homes?

This replaces Calgary Data Desk's "amenity level" and "Needs attention" tiers, which counted assets inside community
boundaries per resident (see `docs/audit-calgary-data-desk-2026-11.md`, finding 1).

## Units of analysis

| Item | Definition | Kind |
|---|---|---|
| Home | One residential record on the city's property assessment roll (Calgary: residential class, land with a building, residential use code). A house, townhouse or condominium unit. | Official |
| Rental building | Listed once on the roll. Counted as its number of units: from a matching building permit (official) or estimated from assessed value (estimate). | Official / estimate |
| Home location | The mean of the vertices of the parcel's outline. | Calculated |
| Amenity | A feature in the city's own inventory, filtered as stated in `cities/<city>/city.json`. | Official |
| Area | A community (Calgary's Community District Boundaries), using the community code the city puts on each roll record. | Official |

## Formulas

For each home *h* and amenity kind *k*:

    d(h, k) = straight-line distance in metres from h to the nearest amenity of kind k
              (points: the amenity's location; parks: the nearest point on the park's edge, 0 inside the park)

For an area *A* (or the whole city), with *w(h)* the units a record stands for:

    share_primary(A, k)   = Σ w(h) for h in A with d(h,k) ≤ T1(k)  /  Σ w(h) for h in A
    share_secondary(A, k) = the same at T2(k)
    share_new(A, k)       = share_primary over homes built in or after the growth year (2021)
    share_older(A, k)     = share_primary over homes built before it (homes with no year are in neither)
    median_m(A, k)        = median of d over the area's records, reported only if ≤ T2

The amenity can be in any community. A playground across the street in the next community counts.

## Thresholds

| Amenity | T1 | T2 | Basis |
|---|---|---|---|
| Playground | 400 m | 800 m | Platform choice: about a five- and ten-minute walk |
| Public park (edge) | 400 m | 800 m | Platform choice |
| Transit stop | 400 m | 800 m | Calgary Transit Service Guidelines (May 2025) measure local coverage as residents within 400 m of service |
| Community centre | 800 m | 1.6 km | Platform choice |
| Indoor recreation centre | 2 km | 5 km | Platform choice, district facility |
| Public library | 2 km | 5 km | Platform choice, district facility |

Every threshold is in the city config with its basis. Results are published at both thresholds so the effect of the
choice is visible (`sensitivity` in `access.json`: how many communities read as a gap at each).

## How a community is read (a stated rule, not a score)

| Reading | Rule |
|---|---|
| Too few homes | Fewer than 100 units |
| Measured gap | Fewer than half of units within T1 |
| Check inventory | A measured gap where 25% or more of units were built in the last five years |
| Most homes within reach | Half or more within T1 |

"Check inventory" exists because developers often build and maintain parks and playgrounds in new communities
before they are handed over to the city, and inventories can lag. A measured gap there may not be a gap on the
ground.

Readings are never combined across amenity kinds. There is no overall score.

## What this does not measure (limitations)

- **Straight-line, not walking, distance.** Walking routes are longer (curved streets, cul-de-sacs, rivers, rail
  lines, major roads). Every share here is the most generous reading. Planned: network distance on the
  OpenStreetMap path network.
- **Presence, not adequacy.** A transit stop is not a service level (frequency is not measured yet; planned from
  the GTFS timetable). A playground's size, condition and age group are not measured. Recreation centres and
  libraries: size, hours and programs are not measured.
- **The city's inventory only.** School, developer, condominium and private amenities are not counted.
- **Homes, not people.** Results are per dwelling unit. Household size differs by community; residents are not
  modelled, which avoids depending on population estimates between Censuses.
- **Rental units partly estimated.** 32,163 of about 75,800 purpose-built rental units in Calgary are estimated
  from assessed value; the rest come from building permits. Published as `units_estimated`.
- **Parcel centre.** Large parcels (a big apartment complex) are placed at one point.
- **Correlation, not cause.** A gap in a community says nothing about why it exists or whether it will be filled.

## Independent checks

- `tests/test_access.py` compares the fast nearest-neighbour search with brute force on random data, and
  park-edge distances with an exact point-to-segment calculation (agreement within the 10 m edge-sampling
  tolerance).
- `tests/test_pipeline.py` runs the whole pipeline on a two-community test city whose every figure was worked out
  by hand, including the case this method exists for: a playground just over the community boundary.
- The Calgary playground figure (73.2% of homes within 400 m, 5 November 2026) was first calculated during the audit
  with separate JavaScript code against the City's API, before this pipeline was written; each build can be checked
  against it.
