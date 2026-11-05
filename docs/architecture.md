# Architecture

## Principles

1. **A city is configuration.** Everything that differs between cities (portal, dataset IDs, field names, filters,
   area names, thresholds and their basis, quality tolerances) lives in `cities/<id>/city.json`. The core never
   names a city.
2. **Static first.** A scheduled build turns open data into static files; the website reads only those files. No
   server, no database, nothing to keep running. Hosting: GitHub Pages (custom domain supported).
3. **Provenance travels with every number.** Each build writes `sources.json` (what was read, when, the publisher's
   last update, filter, row count, hash, transformations) and `quality.json` (every check and its result).
4. **A failed check stops publication.** The last good data stays online.
5. **No composite scores.** Indicators stand alone; any future composite needs a documented weighting,
   uncertainty and sensitivity analysis.
6. **Value kinds are explicit:** official, calculated, estimate, AI (see `insight/model.py`).

## Layout

```
cities/<id>/city.json        city configuration (and small model inputs, e.g. Calgary's rental_units.json)
insight/
  config.py                  load and validate city configs
  model.py                   common data model (Source, QualityCheck, Area, Facility, Home, Observation)
  socrata.py                 connector: paged reads, retries, publisher metadata, row hashing
  geo.py                     projection, point-in-polygon, areas, simplification, spatial indexes
  quality.py                 data quality checks
  indicators/access.py       access indicator (the method itself)
  pipeline.py                fetch → validate → compute → write, with provenance
  __main__.py                CLI: python -m insight build --city calgary
site/                        static website (HTML, CSS, JS; Leaflet bundled)
site/data/<id>/              build output (not in git on main; see "Snapshots")
tests/                       unit, independent-check and end-to-end tests
.github/workflows/build.yml  test → build → snapshot → deploy, daily and on every push
```

## Data flow

```
city.json ──► connector (Socrata) ──► rows + publisher metadata
                                         │
                                 quality checks ── fail? ──► stop, keep last published data
                                         │
                       common model (areas, homes, amenities, in projected metres)
                                         │
                                 indicator modules (access, …)
                                         │
             access.json · areas.geojson · amenities/*.geojson · access_by_area.csv
             sources.json · quality.json · manifest.json (SHA-256 of every file)
                                         │
                        data branch: latest/ and snapshots/<city>/<date>/
                                         │
                                 GitHub Pages site
```

## Common data model

| Entity | Fields (phase 1) | Status |
|---|---|---|
| City | id, name, province, status (live / pilot / planned), readiness | Built |
| Area | code, name, level (city, ward, community, neighbourhood, census tract, dissemination area), parent | Built (community) |
| Home | publisher id, area, location, year built, weight (units), weight kind | Built |
| Facility | id, kind, location or shape, capacity | Built (no capacity yet) |
| Observation | metric, area, level, value, kind, period, sources | Defined |
| Source | publisher, title, URL, API, licence, coverage, period, unit, limitations, dates, rows, query, hash, transformations | Built |
| QualityCheck | source, check, status, detail, value, threshold | Built |
| Population observation, demographic indicator, service request, development activity, capital investment, metric definition | | Next modules |

## Geography and crosswalks

Areas are taken as each city publishes them. Units are not assumed equivalent between cities (Calgary communities
and Edmonton neighbourhoods differ in size and definition). Comparisons across cities are made only at levels that
are comparable (the whole city, Census geography) and only for indicators both cities can produce with the same
definition. Crosswalks between levels (community to ward, community to census tract) are computed from boundaries
with their area-overlap shares and published with the data. For Calgary, the audit found communities nest almost
exactly in wards (2 of 223 residential communities have more than 5% of their area in another ward).

## Snapshots and reproducibility

Each build pushes its full output to the `data` branch twice: `latest/<city>/` (used by the next build's
count-change checks) and `snapshots/<city>/<date>/`. Every snapshot carries `sources.json` with row hashes of what
was read and `manifest.json` with hashes of what was written. Raw inputs are not stored (the parcel layer is
several hundred megabytes); the hashes show whether a re-run read the same data.

## Technology choices

| Considered | Decision | Why |
|---|---|---|
| Python, NumPy, SciPy | Used | Nearest-neighbour search over 500,000 homes in under a second per amenity kind |
| Pandas, GeoPandas, Shapely | Not yet | Not needed for phase 1; avoids heavy GIS dependencies |
| PostgreSQL / PostGIS | Not yet | Static files are enough at this scale; revisit when time series or many cities need querying |
| FastAPI | Not yet | Needed only for the AI assistant's key-holding proxy |
| React / Next.js | Not used | A plain static page loads fast and has no build step |
| Leaflet | Used | Bundled; MapLibre adds little for choropleths |
| GitHub Actions + Pages | Used | Free, scheduled, versioned, custom domain |

## AI research assistant (planned)

The assistant will answer only from published indicator files and `sources.json`, through a small server function
that holds the API key (never sent to the browser), rate-limited per visitor with a monthly spend cap. Every answer
cites the source records it used and is labelled as AI-generated.
