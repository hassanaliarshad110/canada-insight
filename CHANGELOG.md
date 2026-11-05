# Changelog

## 0.5.0 (5 November 2026)

Added
- Edmonton (pilot): 407 neighbourhoods in 12 named wards; homes from the property roll (points, year built from
  Property Information, apartment buildings estimated from floor area); residents and children from the 2021 Census
  by neighbourhood, with residents added for homes built since (default) or unchanged; the same six amenities,
  distances, crowding, scores and OpenStreetMap supplements as Calgary.
- Build: census population types (`census`, `census_plus_new`), point homes, joined year built, unit estimates from
  floor area, named wards. New check: census residents in areas with no homes. Residents and children per ward
  published with each build. A pilot city that fails keeps its last data and does not stop the others.
- Site: named wards, each city's own word for its areas, city-specific method text, and a dashboard of people,
  homes and amenities for cities without a linked dashboard. Switching city in the address now opens that city.
- Research assistant: Edmonton's portal; named wards.

Fixed (after the first Edmonton build)
- The default way of counting Edmonton's residents (2021 Census plus new homes) was left out because it was listed
  before the census it builds on; options are now built in dependency order.
- About 7,600 Edmonton homes with no neighbourhood code are placed by location instead of left without one.
- 36,340 census residents in four neighbourhoods renamed or renumbered since 2021 (Oliver, now Wîhkwêntôwin, and
  three others) carried no homes; they are now placed by the census-day boundary.
- Edmonton apartment homes: 185 m² of gross floor area per home instead of 85 m². At 85 m² apartment neighbourhoods
  had 1.4 to 1.9 times as many homes as the 2021 Census counted households; 185 m² is fitted on households by neighbourhood.
- Calgary: when OpenStreetMap can't be reached, the saved copy's row count is recorded.
- The audit tool works for any city (ward count and population options from the city's settings).


## 0.4.0 (5 November 2026)

Added
- Dashboard page: Calgary at a glance, every figure filterable by ward: people and homes, 311, safety and traffic,
  children, child care and schools, development, amenities and property tax. City figures are read from Calgary
  Data Desk's daily build so both sites match; residents can be counted with any of the Data Desk's four methods.
- Ward picker on every page (map zooms to the ward, tables filter to its communities), and a ward-by-ward
  comparison for every topic, including amenities by ward (homes placed in wards by exact location).
- Playgrounds and parks that are not the City's but open to everyone (OpenStreetMap), counted by default with the
  same matching rules as Calgary Data Desk; filters for the City's only and for adding private ones. If
  OpenStreetMap can't be reached, the last build's copy (up to 30 days old) is used and the page says so.
- Map tiles from OpenStreetMap (no key needed). Tests: 39.
- Ask the data: research assistant (quick answer, thorough, research report) on a Cloudflare Worker that holds the
  key; answers only from data it reads, cites sources, daily limits. Node tests for the worker.

## 0.3.0 (5 November 2026)

Added
- Amenity scores against Calgary for all six amenities (crowding extended to transit stops, community centres,
  recreation centres and libraries), local and district group scores, and an all-amenities score.
- Each score worked out 4 or 8 ways (both distances, growth model and 2021 Census, two weightings), shown as a
  range; "consistent gap" only where a community is below 0.80 in every way.
- Site: "Where amenities fall behind, under every assumption" table, scores in each community profile, map "Score"
  view. Tests: 36.

## 0.2.0 (5 November 2026)

Added
- Crowding at playgrounds and parks (two-step floating catchment): playgrounds per 1,000 children within reach and
  park hectares per 1,000 residents within reach, at both walking distances. Labelled as an estimate.
- Residents and children read from Calgary Data Desk's published estimates, with a switch between the growth model
  and the 2021 Census, so both sites show the same people figures.
- Each community shows Calgary Data Desk's "homes lived in" beside Canada Insight's "homes on the property roll".
- Map toggle between "Near" and "Crowding"; crowding column in the table and comparison.
- Tests: 32.

## 0.1.0 (5 November 2026)

First release, built after an audit of Calgary Data Desk (`docs/audit-calgary-data-desk-2026-11.md`). Calgary Data
Desk stays online unchanged.

Added
- City-independent core: config loader and validation, common data model, Socrata connector with publisher
  metadata and row hashes, data quality checks that stop a bad build, dated snapshots on the `data` branch.
- Calgary configuration (pilot) and Edmonton readiness placeholder (planned).
- Access to everyday amenities: distance from every home on the property roll to the nearest playground, park,
  transit stop, community centre, indoor recreation centre and library; shares within two walking distances;
  homes built since 2021 against older homes; a stated reading per community with an "inventory may lag" caution;
  no composite score. Replaces the boundary-count "amenity level" and "Needs attention" tiers.
- Website: map, community profiles, comparison of up to three communities, sortable table, CSV download, sources
  and data quality pages; light and dark themes; keyboard and screen-reader support.
- Reconciliation: playground access recomputed independently during the audit (73.2% of records within 400 m)
  against the pipeline's record-count share (73.3%).
- Tests: 25 (geometry, indicator formulas against brute force and exact distances, config validation, quality
  checks, end-to-end on a hand-worked test city).
