import math
import random

from insight import geo


def test_point_in_polygon_with_hole():
    outer = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    hole = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]
    mp = [[outer, hole]]
    assert geo.point_in_multipolygon(1, 1, mp)
    assert not geo.point_in_multipolygon(5, 5, mp)          # in the hole
    assert not geo.point_in_multipolygon(11, 5, mp)


def test_area_subtracts_holes():
    outer = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    hole = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]
    assert geo.area([[outer, hole]]) == 96


def test_projection_matches_known_distance():
    # one degree of latitude is about 111.1 km; at 51 N one degree of longitude is about 69.9 km
    p = geo.Projection(51.0)
    x0, y0 = p.xy(-114.0, 51.0)
    x1, y1 = p.xy(-113.0, 51.0)
    assert abs((x1 - x0) - 69_937) < 100
    assert abs(p.lonlat(*p.xy(-114.06, 51.04))[0] + 114.06) < 1e-12


def test_point_index_matches_brute_force():
    rnd = random.Random(1)
    pts = [(rnd.uniform(0, 5000), rnd.uniform(0, 5000)) for _ in range(300)]
    idx = geo.PointIndex(pts, cell=250)
    for _ in range(200):
        x, y = rnd.uniform(-500, 5500), rnd.uniform(-500, 5500)
        brute = min(math.hypot(px - x, py - y) for px, py in pts)
        got = idx.nearest(x, y, 1000)
        if brute <= 1000:
            assert abs(got - brute) < 1e-9
        else:
            assert got is None


def test_polygon_index_inside_and_outside():
    sqr = [[[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]]]
    idx = geo.PolygonIndex([sqr], cell=50)
    assert idx.distance(50, 50, 500) == 0.0
    assert abs(idx.distance(150, 50, 500) - 50) < 1e-9
    assert abs(idx.distance(200, 200, 500) - math.hypot(100, 100)) < 1e-9
    assert idx.distance(1000, 1000, 500) is None


def test_area_locator():
    loc = geo.AreaLocator({'A': [[[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]],
                           'B': [[[[10, 0], [20, 0], [20, 10], [10, 10], [10, 0]]]]}, cell=5)
    assert loc.find(5, 5) == 'A'
    assert loc.find(15, 5) == 'B'
    assert loc.find(25, 5) is None


def test_simplify_keeps_shape_closed():
    ring = [[math.cos(t / 100 * 2 * math.pi) * 100, math.sin(t / 100 * 2 * math.pi) * 100] for t in range(100)]
    ring.append(ring[0])
    out = geo.simplify_ring(ring, 2.0)
    assert out[0] == out[-1]
    assert 8 < len(out) < len(ring)
    assert abs(geo.ring_area(out) - geo.ring_area(ring)) / geo.ring_area(ring) < 0.05


def test_tidy_name():
    from insight.pipeline import tidy_name
    assert tidy_name('MCKENZIE TOWNE', 'title') == 'McKenzie Towne'
    assert tidy_name('BRIDGELAND/RIVERSIDE', 'title') == 'Bridgeland/Riverside'
    assert tidy_name('CITYSCAPE', None) == 'CITYSCAPE'


def test_vectorised_point_in_polygon_matches_simple():
    import numpy as np
    rnd = random.Random(5)
    outer = [[math.cos(t / 40 * 2 * math.pi) * (100 + rnd.uniform(-30, 30)), math.sin(t / 40 * 2 * math.pi) * (100 + rnd.uniform(-30, 30))] for t in range(40)]
    outer.append(outer[0])
    hole = [[-20, -20], [20, -20], [20, 20], [-20, 20], [-20, -20]]
    mp = [[outer, hole]]
    xs = np.array([rnd.uniform(-150, 150) for _ in range(3000)])
    ys = np.array([rnd.uniform(-150, 150) for _ in range(3000)])
    got = geo.points_in_multipolygon(xs, ys, mp)
    want = [geo.point_in_multipolygon(x, y, mp) for x, y in zip(xs, ys)]
    assert list(got) == want
    loc = geo.locate_many(xs, ys, {'A': mp})
    assert [v == 'A' for v in loc] == want
