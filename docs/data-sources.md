# Data-source register

Each build writes the live register to `site/data/<city>/sources.json` (and the site's Sources section): title,
publisher, URL, API, filter, licence, coverage, period, unit, limitations, the publisher's last update, when it was
read, rows read, a SHA-256 hash of the rows and every transformation applied. This page is the register as of the
first Calgary build (5 November 2026).

## Calgary

Licence for City data: Open Government Licence – City of Calgary.

| Dataset | Publisher | Last updated by publisher | Rows read | Filter | Used for |
|---|---|---|---|---|---|
| [Community District Boundaries](https://data.calgary.ca/d/surr-xmvs) | City of Calgary | 2026-11-01 | 313 | none | Community outlines and names |
| [Current Year Property Assessments (Parcel)](https://data.calgary.ca/d/4bsw-nn7w) | City of Calgary | 2026-11-03 | 502,628 | `assessment_class='RE' AND property_type='LI' AND starts_with(sub_property_use,'R')` | Homes: location, community, year built |
| Rental building units (`cities/calgary/rental_units.json`) | Calgary Data Desk growth model (Hassan Ali), from City data | built 2026-10-28 | 2,227 buildings | none | Units in purpose-built rental buildings (permits or estimated from assessed value) |
| [Calgary Data Desk: growth model](https://hassanaliarshad110.github.io/calgary-data-desk/) (`data/model/w0.json`) | Calgary Data Desk (Hassan Ali) | daily | about 215 communities | communities with 100+ residents | Residents and children by community (estimate), homes lived in |
| Calgary Data Desk: 2021 Census (`data/census2021/w0.json`) | Statistics Canada, via the City and Calgary Data Desk | daily build of a 2021 count | about 200 communities | communities with 100+ residents | Residents and children by community, no growth |
| [Playground Equipment](https://data.calgary.ca/d/bdu9-amk8) | City of Calgary | 2026-11-01 | 1,115 | `type_description='MULTI PLAY COMPLEX' AND life_cycle_status in('ACTIVE','INSTALLED')` | Playgrounds |
| [Parks Sites](https://data.calgary.ca/d/kami-qbfh) | City of Calgary | 2026-10-29 | 2,955 | `planning_category not in('NON-PARK','PARKS DEPOT')` | Public parks (outlines) |
| [Calgary Transit Stops](https://data.calgary.ca/d/muzh-c9qc) | City of Calgary | 2026-09-30 | 6,213 | `status='ACTIVE'` | Transit stops |
| [Community Services](https://data.calgary.ca/d/x34e-bcjz) | City of Calgary | 2026-11-01 | 109 / 21 | `type='Community Centre'` / `type='Library'` | Community centres, libraries |
| [Recreation Facilities](https://data.calgary.ca/d/hxfu-6d96) | City of Calgary | 2026-11-01 | 27 | leisure, aquatic and fitness centres, fieldhouses | Indoor recreation centres |

Threshold reference: [Calgary Transit Service Guidelines (May 2025)](https://transit-prd.calgary.ca/content/dam/transit/plans---projects/Calgary%20Transit%20Service%20Guidelines%20May%202025.pdf),
local coverage measured as residents within 400 metres of transit service.

## Known limitations of the sources

- The property roll is the current year only; year of construction gives the build history, but demolished homes
  are not in it.
- Rental buildings are one record each on the roll; 31,970 of the units used are estimated from assessed value.
- Inventories list City-owned or City-maintained assets. Developer-held amenities in new communities and school,
  private and condominium amenities are missing.
- The transit stop list does not describe service frequency.
