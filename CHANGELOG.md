# Changelog

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
