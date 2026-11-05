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

## Edmonton (pilot, added 5 November 2026)

Licence for City data: City of Edmonton Open Data Terms of Use. Row counts and update dates from a survey of the
portal on 5 November 2026; the build records the exact figures in `sources.json` every day.

| Dataset | Publisher | Updated | Rows | Filter | Used for |
|---|---|---|---|---|---|
| [City of Edmonton - Neighbourhoods](https://data.edmonton.ca/d/65fr-66s6) | City of Edmonton | 2026-11-02 | 407 | none | Neighbourhood outlines and names |
| [Ward Boundary and Council Composition (Current)](https://data.edmonton.ca/d/b4er-5rp2) | City of Edmonton | 2026-11-02 | 12 | none | Ward outlines, names, councillors |
| [Property Assessment Data (Current Calendar Year)](https://data.edmonton.ca/d/q7d6-ambg) | City of Edmonton | 2026-11-02 | 439,825 (all classes) | `tax_class in('Residential','Other Residential') AND assessed_value >= 40000` | Homes: location, neighbourhood, class |
| [Property Information (Current Calendar Year)](https://data.edmonton.ca/d/dkk9-cj3x) | City of Edmonton | 2026-11-02 | 439,825 | `year_built IS NOT NULL` | Year built; floor area of apartment buildings |
| [2021 Federal Census: Population](https://data.edmonton.ca/d/eg3i-f4bj) | Statistics Canada, via the City | 2023-09-27 | 278 neighbourhoods (1,010,595 residents) | none | Residents by neighbourhood |
| [2021 Federal Census: Neighbourhoods as of Official Census Day](https://data.edmonton.ca/d/5bk4-5txu) | City of Edmonton | 2021 | 403 | none | Census-day boundaries, used only for the 4 census neighbourhoods whose code has changed (Oliver, now Wîhkwêntôwin; Chappelle; Heritage Valley Town Centre; Horse Hill Neighbourhood 1A) |
| [2021 Federal Census: Age and Gender](https://data.edmonton.ca/d/wpfd-8bii) | Statistics Canada, via the City | 2023-06-28 | 20,925 | `age_range='0 to 14 years' AND gender='Total'` | Children by neighbourhood (184,105) |
| [Playgrounds](https://data.edmonton.ca/d/9nqb-w48x) | City of Edmonton | 2026-11-02 | 661 | none | Playgrounds |
| [Parks](https://data.edmonton.ca/d/gdd9-eqv9) | City of Edmonton | 2026-11-02 | 1,197 | `status='Active' AND class not in('PUL','Unknown','Other Land Type')` | Public parks (outlines) |
| [ETS Bus Schedule GTFS Data Feed - Stops](https://data.edmonton.ca/d/4vt2-8zrq) | City of Edmonton | 2026-10-30 | 6,797 | `location_type = 0` | Bus and LRT stops |
| [Community League Halls](https://data.edmonton.ca/d/kaps-rk7z) | City of Edmonton | 2026-11-02 | 141 | none | Community league halls |
| [Recreation Facilities](https://data.edmonton.ca/d/nz3t-vyg3) | City of Edmonton | 2026-11-05 | 19 of 107 | `facility_type='Recreation Centre'` | Indoor recreation centres |
| [Public Libraries](https://data.edmonton.ca/d/jn25-zspi) | Edmonton Public Library, via the City | 2026-11-04 | 22 | none | Public libraries |

How Edmonton differs from Calgary:
- Homes are points the City publishes for each property, not parcel centres. Condominium units are one account each;
  apartment buildings ("Other Residential", 4,404 accounts) are one account each, so their homes are estimated as
  floor area / 85 m² (an estimate, labelled as such). About 7,600 homes carry no neighbourhood code on the roll
  (for example in Anthony Henday Southeast and the Chappelle area) and are placed in the neighbourhood that contains them. Properties assessed under $40,000 (about 45,000, mostly $0
  parking stalls, storage units and remnant parcels) are left out, as are properties with no year built (no building).
- Residents and children come from the 2021 Census by neighbourhood on the City's portal, with residents added for
  homes built since 2021 (default) or unchanged. There is no Calgary Data Desk for Edmonton, so the dashboard shows
  people, homes and amenities only; 311, safety and development figures are not built yet.
- Neighbourhoods are not Calgary's communities: compare the two cities only at the city level, and scores only
  within a city (each is against its own city's level).

## Known limitations of the sources

- The property roll is the current year only; year of construction gives the build history, but demolished homes
  are not in it.
- Rental buildings are one record each on the roll; 31,970 of the units used are estimated from assessed value.
- Inventories list City-owned or City-maintained assets. Developer-held amenities in new communities and school,
  private and condominium amenities are missing.
- The transit stop list does not describe service frequency.
