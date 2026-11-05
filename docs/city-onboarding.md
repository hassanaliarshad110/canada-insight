# Adding a city

A city is added by writing `cities/<id>/city.json`. No core code changes unless the city's portal type has no
connector yet (today: Socrata).

## 1. Readiness assessment (status `planned`)

Fill the `readiness` block first, from the city's portal:

| Item | Question |
|---|---|
| Data availability | Is there a residential property layer with location and year built? Inventories for each amenity kind? |
| Data quality | Missing locations, duplicate IDs, codes without boundaries (run a trial build with warnings) |
| Geographic compatibility | What are the local areas called, how many, do they nest in wards? |
| Historical coverage | How far back does each source go? |
| Indicator comparability | Which amenity definitions match the reference city's, and which differ? |
| Update frequency | How often is each source refreshed? |

A city with a missing source is still onboarded for the indicators it can support. It must never be shown beside
other cities on an indicator it cannot produce with the same definition.

## 2. Configuration (status `pilot`)

Copy `cities/calgary/city.json` and change:

- `portal`: base URL, publisher, licence.
- `areas`: dataset, code and name fields, geometry field, level name (community, neighbourhood…).
- `homes`: dataset, filter for residential dwellings, ID, area code, year built and geometry fields. If the city
  lists rental buildings as one record, supply a unit-weights file with its provenance.
- `amenities`: for each kind, the dataset, filter, geometry type and field, thresholds and `threshold_basis`
  (cite a local standard where one exists).
- `quality.max_age_days`: how stale each source may be before a warning.
- `terms`: the local words for area and ward.

## 3. Build and check

```
python -m insight build --city <id> --out site/data
python -m pytest -q
```

Read `site/data/<id>/quality.json`. Compare a few communities' figures against a map or local knowledge. Record
anything surprising in the city's `readiness` notes.

## 4. Go live

Add the build line to `.github/workflows/build.yml`, set status `live`, and push.
