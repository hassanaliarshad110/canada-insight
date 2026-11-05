# Indicator method: crowding at playgrounds and parks

Code: `insight/indicators/crowding.py`, `insight/pipeline.py` (`Builder.crowding`, `Builder.people`).
Tests: `tests/test_crowding.py`, `tests/test_pipeline.py::test_crowding_end_to_end`.

## The question

Nearness (see `access.md`) can't tell a playground shared by 80 children from one shared by 400. This measure asks:
**how much playground or park is there within reach, for the people who share it?**

## Method: two-step floating catchment

For each walking distance *d* (the same two distances as the access measure):

    Step 1, each amenity j:
        demand(j) = people living in homes within d of j
        ratio(j)  = supply(j) / demand(j)      supply: 1 per playground; hectares per park
                    amenities with nobody within reach are left out

    Step 2, each home i:
        reach(i)  = 1,000 x sum of ratio(j) over amenities within d of i     (0 if none)

    Area figure = people-weighted average of reach(i) over the area's homes

| Amenity | People | Unit |
|---|---|---|
| Playground | children aged 0 to 14 | playgrounds per 1,000 children within reach |
| Public park | residents | park hectares per 1,000 residents within reach |

"Within reach" uses the same geometry as the access measure: straight-line distance; parks to their nearest edge,
0 inside. Borders don't matter: children from the next community who can reach the same playground share it.

The measure shares supply out; it creates none and loses none: the sum over homes of reach x people / 1,000 equals the
supply of the amenities that anyone can reach (tested).

## People per home (estimates)

Residents and children by community come from **Calgary Data Desk's published estimates**, so both sites show the
same figures. The reader chooses which:

| Option | What it is |
|---|---|
| Growth model (default) | 2021 Census for each community, grown with the homes built since on the City's property roll. Children: 2021 Census children plus children for residents added since, at the share seen in communities new at the 2021 Census. |
| 2021 Census | Each community's 2021 count, unchanged. Communities built since 2021 have no count, so they carry no people and get no figure. |

Each community's estimate is spread evenly over its dwelling units (the same units as the access measure). Communities
with fewer than 100 residents are not in the source and carry no people.

## Home counts on both sites

Canada Insight counts every home on the current property roll. Calgary Data Desk counts a home as lived in from one
year after it is built. Both figures are shown side by side on each community, so the difference is visible, not a
contradiction.

## Limitations

- **Estimates.** People per home are spread evenly within each community; a community with a family-heavy
  subdivision and an adult-only building gets the same children per unit in both.
- **Size and capacity of amenities not measured.** Each playground counts as one, whatever its size. Park hectares
  include large regional parks, which lift figures for homes near them.
- **City inventory only, straight-line distance**, as for the access measure.
- **No tier and no combined score.** The figure is shown beside Calgary's; the map compares each community with
  Calgary's figure.
- The 2026 Census age data (released during 2027) will replace the 2021-based children estimates.
