# Canada Insight

Independent civic research on Canadian cities from official open data, by Hassan Ali. Calgary is the first city;
others are added by configuration, not code.

Site: https://hassanaliarshad110.github.io/canada-insight/ (custom domain to follow)

## What it answers today

**Can people walk to everyday amenities, and are new homes keeping up?** For every home on the city's property
roll: the distance to the nearest playground, public park, transit stop, community centre, indoor recreation centre
and library in the city's own inventory. Results by community at two walking distances, with homes built since the
2021 Census measured separately. Each community gets a stated reading per amenity (measured gap, check inventory,
most homes within reach). There is no composite score.

Calgary, 5 November 2026 (share of homes within the shorter distance, homes built before 2021 against since):

| Amenity | Distance | Older homes | Homes built since 2021 |
|---|---|---|---|
| Playground | 400 m | 72% | 68% |
| Public park | 400 m | 99% | 97% |
| Transit stop | 400 m | 97% | 70% |
| Community centre | 800 m | 41% | 18% |
| Indoor recreation centre | 2 km | 52% | 30% |
| Public library | 2 km | 53% | 33% |

Straight-line distance; the city's inventory only. See the method for what this does and does not show.

**Crowding** (playgrounds and parks): how much is within reach for the people who share it, with residents and
children taken from Calgary Data Desk's growth model or the 2021 Census (your choice on the site).

**Amenity scores**: each amenity against Calgary's level, local and district summaries, worked out under every
combination of distance, population count and weighting. A community is called a consistent gap only when it is
below 0.80 under all of them.

## Documentation

| | |
|---|---|
| [Audit of Calgary Data Desk](docs/audit-calgary-data-desk-2026-11.md) | What the existing product does, what is sound and what could mislead, with recalculations |
| [Architecture](docs/architecture.md) | City-independent core, data model, data flow, technology choices |
| [Method: access to everyday amenities](docs/methodology/access.md) | Formulas, thresholds, readings, limitations, checks |
| [Method: crowding at playgrounds and parks](docs/methodology/crowding.md) | Two-step floating catchment, people estimates, limitations |
| [Method: amenity scores and consistent gaps](docs/methodology/scores.md) | Scores against Calgary, ranges across assumptions |
| [Data-source register](docs/data-sources.md) | Every dataset, its publisher, dates and filters |
| [Data quality](docs/data-quality.md) | The checks, and the latest results |
| [Adding a city](docs/city-onboarding.md) | Readiness assessment and configuration |
| [Deployment](docs/deployment.md) | Build schedule, GitHub Pages, custom domain |
| [Changelog](CHANGELOG.md) | |

## Run it

```
pip install -r requirements.txt pytest
python -m pytest -q
python -m insight build --city calgary --out site/data
python -m http.server -d site 8000
```

## Status

Calgary: pilot. Edmonton: planned (readiness assessment not started). Calgary Data Desk remains online unchanged.

Not an official City of Calgary or Government of Canada product. City data under the Open Government Licence –
City of Calgary.
