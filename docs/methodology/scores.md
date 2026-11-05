# Indicator method: amenity scores and consistent gaps

Code: `insight/indicators/scores.py`. Tests: `tests/test_scores.py`, `tests/test_pipeline.py::test_crowding_end_to_end`.

## What the score is

For each amenity, the crowding figure (`crowding.md`) is the amenity within reach, per person who shares it. It
already combines distance (what counts as within reach) and population (who shares it). The score sets it against
the city:

    amenity score = community's crowding figure / Calgary's crowding figure        (1.00 = Calgary)

| Amenity | Crowding figure | People |
|---|---|---|
| Playground | playgrounds per 1,000 children within reach | children 0 to 14 |
| Public park | park hectares per 1,000 residents within reach | residents |
| Transit stop | stops per 1,000 residents within reach | residents |
| Community centre | centres per 100,000 residents within reach | residents |
| Indoor recreation centre | centres per 100,000 residents within reach | residents |
| Public library | libraries per 100,000 residents within reach | residents |

Bands: under 0.50 well below Calgary; 0.50 to 0.80 below; 0.80 to 1.25 around; over 1.25 above.

## Group and overall scores

| Score | Formula |
|---|---|
| Local amenities | mean of the playground, park and transit stop scores, each capped at 2.00 |
| District facilities | mean of the community centre, recreation centre and library scores, each capped at 2.00 |
| All amenities | mean of all six capped scores, either equal weights, or local amenities two thirds and district facilities one third |

The cap stops a surplus of one amenity hiding a shortage of another. A group score needs every amenity in the group.

## Every reasonable assumption

| Choice | Options |
|---|---|
| Walking distance | each amenity's shorter and longer distance |
| People | growth model; 2021 Census |
| Weights (all-amenities score only) | equal; local-heavy |

Amenity and group scores are worked out 4 ways; the all-amenities score 8 ways. The figure shown is the default
(shorter distance, growth model, equal weights); the range is the lowest to the highest across all of them.

| Label | Rule |
|---|---|
| Consistent gap | below 0.80 in every way that has a figure |
| Depends on assumptions | below 0.80 in some, not all |
| No gap | never below 0.80 |

Communities built since 2021 have no 2021 Census count, so they are scored fewer ways; the site marks them.

## Why this design

- No single assumption decides a result: a consistent gap holds whichever distance, population count or weighting
  you prefer.
- Ranges are shown instead of one falsely precise figure.
- Local and district scores are kept apart, because new areas tend to differ between the two.

## Limitations

Everything in `access.md` and `crowding.md` applies: straight-line distance, City inventory only, each facility
counts as one whatever its size, people per home estimated. The 0.80 line and the bands are platform choices,
stated here and applied the same way to every community. The comparison is with Calgary's own level, not with a
standard of adequate provision; where the City publishes a standard (transit: 400 m coverage), the access measure
reports against it.
