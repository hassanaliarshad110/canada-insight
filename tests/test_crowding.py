import numpy as np

from insight import geo
from insight.indicators import crowding


def test_hand_worked_two_playgrounds():
    """Playground P1 has 100 children within reach, P2 has 400. A home near only P1 gets 1/100 x 1,000 = 10
    playgrounds per 1,000 children; near only P2, 2.5; near both, 12.5."""
    homes = [(0, 0), (1000, 0), (500, 0)]           # near P1, near P2, near both
    pts = [(-100, 0), (1100, 0)]
    pairs = crowding.pairs_points(homes, pts, 650)
    children = [40, 340, 60]                       # P1 reaches homes 0 and 2 (100); P2 reaches homes 1 and 2 (400)
    r, demand = crowding.reach(pairs, children, [1, 1], 3)
    assert list(demand) == [100, 400]
    assert np.allclose(r, [10.0, 2.5, 12.5])


def test_supply_is_conserved():
    """Sum over homes of reach x people / 1,000 = the supply of amenities that have anyone within reach."""
    rnd = np.random.default_rng(4)
    homes = rnd.uniform(0, 5000, size=(2000, 2))
    people = rnd.uniform(0, 3, size=2000)
    pts = rnd.uniform(0, 5000, size=(60, 2))
    supply = rnd.uniform(0.5, 4, size=60)
    pairs = crowding.pairs_points(homes, pts, 400)
    r, demand = crowding.reach(pairs, people, supply, len(homes))
    assert np.isclose((r * people).sum() / 1000, supply[demand > 0].sum())


def test_nobody_within_reach():
    r, demand = crowding.reach(crowding.pairs_points([(0, 0)], [(5000, 0)], 400), [3], [1], 1)
    assert r[0] == 0 and demand[0] == 0


def test_polygon_pairs_edge_and_inside():
    park = [[[[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]]]]     # a list holding one MultiPolygon
    homes = [(50, 50), (150, 50), (600, 50)]       # inside, 50 m from the edge, 500 m away
    loc = lambda k, x, y: geo.point_in_multipolygon(x, y, park[k])
    j, i = crowding.pairs_polygons(homes, park, 400, inside=loc, inside_candidates=[0])
    assert sorted(i.tolist()) == [0, 1]
    # without the inside test, the middle of a large park would be missed
    big = [[[[[0, 0], [2000, 0], [2000, 2000], [0, 2000], [0, 0]]]]]
    j, i = crowding.pairs_polygons([(1000, 1000)], big, 400)
    assert len(i) == 0
    j, i = crowding.pairs_polygons([(1000, 1000)], big, 400,
                                   inside=lambda k, x, y: geo.point_in_multipolygon(x, y, big[k]), inside_candidates=[0])
    assert i.tolist() == [0]


def test_area_average_weights_by_people():
    out = crowding.area_average([10, 2, 4], [1, 3, 0], ['A', 'A', 'B'])
    assert out['A'] == 4.0                          # (10 x 1 + 2 x 3) / 4
    assert out['B'] is None                         # no people
    assert out['_all'] == 4.0
