import math
import random

import numpy as np

from insight import geo
from insight.indicators import access


def test_shares_are_weighted_by_units():
    d = np.array([100.0, 500.0, np.inf, 300.0])
    w = [10, 1, 1, 1]
    built = [1990, 2022, 1980, None]
    s = access.summarise(d, w, built, (400, 800), 2021, 2022)
    assert s['units'] == 13
    assert s['share_primary'] == round(11 / 13, 4)              # 100 m (10 units) and 300 m (1 unit)
    assert s['share_secondary'] == round(12 / 13, 4)
    assert s['share_new_primary'] == 0.0                       # the only new home is 500 m away
    assert s['share_old_primary'] == round(10 / 11, 4)         # unknown year is in neither group
    assert s['units_beyond_primary'] == 2
    assert s['units_recent'] == 1


def test_median_is_capped():
    s = access.summarise(np.array([np.inf, np.inf, 100.0]), [1, 1, 1], [1990] * 3, (400, 800), 2021, 2022)
    assert s['median_m'] is None and s['median_beyond_cap']
    s = access.summarise(np.array([10.0, 20.0, 30.0]), [1, 1, 1], [1990] * 3, (400, 800), 2021, 2022)
    assert s['median_m'] == 20


def test_status_rules():
    rules = {'gap_share': 0.5, 'min_units': 100, 'recent_years': 5, 'recent_share': 0.25}
    base = {'units': 1000, 'units_recent': 0, 'share_primary': 0.8}
    assert access.status(base, rules) == 'no_gap'
    assert access.status({**base, 'share_primary': 0.4}, rules) == 'gap'
    assert access.status({**base, 'share_primary': 0.4, 'units_recent': 300}, rules) == 'gap_check'
    assert access.status({**base, 'units': 50}, rules) == 'too_few_homes'
    assert access.status({**base, 'share_primary': 0.5}, rules) == 'no_gap'      # exactly half is not a gap


def test_point_distances_match_brute_force():
    rnd = random.Random(7)
    pts = [(rnd.uniform(0, 3000), rnd.uniform(0, 3000)) for _ in range(50)]
    homes = [(rnd.uniform(0, 3000), rnd.uniform(0, 3000)) for _ in range(500)]
    d = access.distances_to_points(homes, pts, 800)
    for (x, y), got in zip(homes, d):
        brute = min(math.hypot(px - x, py - y) for px, py in pts)
        assert (abs(got - brute) < 1e-6) if brute <= 800 else math.isinf(got)


def test_polygon_distances_within_half_sampling_step():
    """Independent check: sampled-edge distances against exact point-to-segment distances (geo.PolygonIndex)."""
    rnd = random.Random(3)
    polys = []
    for _ in range(20):
        x, y, w, h = rnd.uniform(0, 4000), rnd.uniform(0, 4000), rnd.uniform(20, 300), rnd.uniform(20, 300)
        polys.append([[[[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y]]]])
    exact = geo.PolygonIndex(polys, cell=200)
    homes = [(rnd.uniform(-200, 4400), rnd.uniform(-200, 4400)) for _ in range(800)]
    loc = geo.AreaLocator({i: p for i, p in enumerate(polys)}, cell=500)
    d = access.distances_to_polygons(homes, polys, 800, spacing=20, inside=lambda x, y: loc.find(x, y) is not None)
    for (x, y), got in zip(homes, d):
        e = exact.distance(x, y, 800)
        if e is None:
            assert math.isinf(got) or got > 790
        elif e == 0:
            assert got <= 10.0 + 1e-9
        else:
            assert e - 1e-6 <= got <= e + 10.0 + 1e-6


def test_compute_by_area_and_sensitivity():
    homes = {'area': ['A', 'A', 'B', 'B'], 'weight': [1, 1, 1, 1], 'built': [1990, 2024, 1990, 1990]}
    d = {'k': np.array([100.0, 600.0, 900.0, 700.0])}
    out = access.compute(homes, d, {'k': {'thresholds_m': [400, 800]}}, 2021, 2026,
                         {'gap_share': 0.5, 'min_units': 1, 'recent_years': 5, 'recent_share': 0.25})
    assert out['areas']['A']['k']['share_primary'] == 0.5
    assert out['areas']['A']['k']['status'] == 'no_gap'
    assert out['areas']['B']['k']['share_primary'] == 0.0
    assert out['areas']['B']['k']['status'] == 'gap'
    assert out['city']['k']['share_primary'] == 0.25
    # at 800 m: A all within; B half within (700 m), so B is no longer below half
    assert out['sensitivity']['k'] == {'gaps_at_primary': 1, 'gaps_at_secondary': 0, 'primary_m': 400, 'secondary_m': 800}
