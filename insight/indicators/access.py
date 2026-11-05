"""Access to everyday amenities: how far homes are from the nearest one, and whether new homes are as well served.

This file is the method. docs/methodology/access.md explains it in words; tests/test_access.py checks it.

For every home (a residential record on the city's property roll, placed at its parcel's centre) and every amenity
kind in the city config:
    d = straight-line distance in metres to the nearest amenity of that kind (0 if the home is inside a park)

For every area (community) and the city as a whole, weighted by dwelling units:
    share_primary     = units with d <= primary threshold / all units                     (calculated)
    share_secondary   = the same at the secondary threshold (sensitivity)                   (calculated)
    share_new_primary = share_primary for units built in or after the growth year (2021)    (calculated)
    share_old_primary = share_primary for units built before the growth year                (calculated)
    median_m          = median distance of the area's home records, capped at the largest threshold

Status of an area for an amenity kind (a description of the measurement, not a score):
    too_few_homes     fewer than min_units units: no status
    gap               share_primary below gap_share (default 0.5: most homes are beyond walking distance)
    gap_check         a gap, but recent_share or more of its units were built in the last recent_years years:
                      amenities built by developers may not yet be in the City's inventory, so the gap needs checking
                      on the ground before it is treated as real
    no_gap            otherwise
Nothing is combined across amenity kinds. There is no overall score.
"""
import math

import numpy as np
from scipy.spatial import cKDTree

DEFAULT_RULES = {'gap_share': 0.5, 'min_units': 100, 'recent_years': 5, 'recent_share': 0.25}


def densify(ring_xy, spacing):
    """Points along a ring every `spacing` metres (vertices included)."""
    out = []
    for i in range(1, len(ring_xy)):
        (ax, ay), (bx, by) = ring_xy[i - 1], ring_xy[i]
        n = max(1, int(math.ceil(math.hypot(bx - ax, by - ay) / spacing)))
        for k in range(n):
            t = k / n
            out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    if ring_xy:
        out.append(ring_xy[-1])
    return out


def distances_to_points(homes_xy, pts_xy, max_dist):
    """Distance from each home to the nearest point; np.inf beyond max_dist (or when there are no points)."""
    homes_xy = np.asarray(homes_xy, dtype=float).reshape(-1, 2)
    if len(pts_xy) == 0:
        return np.full(len(homes_xy), np.inf)
    tree = cKDTree(np.asarray(pts_xy, dtype=float))
    d, _ = tree.query(homes_xy, k=1, distance_upper_bound=max_dist)
    return d


def distances_to_polygons(homes_xy, polygons_xy, max_dist, spacing=20.0, inside=None):
    """Distance from each home to the nearest polygon edge, 0 for homes inside a polygon.

    Edges are sampled every `spacing` metres, so a distance can read up to spacing / 2 too long (10 m by default).
    inside: function (x, y) -> bool; homes inside a polygon get 0 (checked for every home not already within
    spacing / 2 of an edge)."""
    pts = [p for mp in polygons_xy for poly in mp for ring in poly for p in densify(ring, spacing)]
    d = distances_to_points(homes_xy, pts, max_dist)
    if inside is not None:
        homes_xy = np.asarray(homes_xy, dtype=float).reshape(-1, 2)
        for i in np.where(d > spacing / 2)[0]:
            if inside(homes_xy[i, 0], homes_xy[i, 1]):
                d[i] = 0.0
    return d


def _share(mask, w):
    tot = w.sum()
    return float((w * mask).sum() / tot) if tot > 0 else None


def summarise(d, weights, built, thresholds, growth_year, recent_from):
    """Access figures for one group of homes (an area or the city) and one amenity kind."""
    p, s = thresholds
    w = np.asarray(weights, dtype=float)
    built = np.asarray(built, dtype=float)          # NaN where the year is unknown
    new = built >= growth_year
    old = built < growth_year                      # unknown years fall in neither
    recent = built >= recent_from
    within_p, within_s = d <= p, d <= s
    cap = max(thresholds)
    finite = np.where(np.isfinite(d), d, np.inf)
    med = float(np.median(finite)) if len(finite) else None
    out = {
        'units': round(float(w.sum()), 1),
        'records': int(len(w)),
        'units_new': round(float(w[new].sum()), 1),
        'units_recent': round(float(w[recent].sum()), 1),
        'share_primary': _share(within_p, w),
        'share_secondary': _share(within_s, w),
        'share_new_primary': _share(within_p[new], w[new]) if new.any() else None,
        'share_old_primary': _share(within_p[old], w[old]) if old.any() else None,
        'units_beyond_primary': round(float(w[~within_p].sum()), 1),
        'median_m': None if med is None else (round(med) if med <= cap else None),
        'median_beyond_cap': bool(med is not None and med > cap),
    }
    for k in ('share_primary', 'share_secondary', 'share_new_primary', 'share_old_primary'):
        if out[k] is not None:
            out[k] = round(out[k], 4)
    return out


def status(stats, rules):
    r = {**DEFAULT_RULES, **(rules or {})}
    if stats['units'] < r['min_units'] or stats['share_primary'] is None:
        return 'too_few_homes'
    if stats['share_primary'] >= r['gap_share']:
        return 'no_gap'
    if stats['units'] and stats['units_recent'] / stats['units'] >= r['recent_share']:
        return 'gap_check'
    return 'gap'


def compute(homes, distances, kinds, growth_year, current_year, rules=None):
    """homes: dict of arrays {'area': [...], 'weight': [...], 'built': [...]} (same order as each distance array);
    distances: {kind: np.array}; kinds: {kind: {'thresholds_m': [primary, secondary], ...}}.

    Returns {'city': {kind: stats}, 'areas': {code: {kind: stats + status}}, 'sensitivity': {...}}."""
    r = {**DEFAULT_RULES, **(rules or {})}
    recent_from = current_year - r['recent_years'] + 1
    area = np.asarray(homes['area'], dtype=object)
    w = np.asarray(homes['weight'], dtype=float)
    built = np.asarray([np.nan if b is None else b for b in homes['built']], dtype=float)
    codes = sorted({a for a in area if a})
    idx = {c: np.where(area == c)[0] for c in codes}
    out = {'city': {}, 'areas': {c: {} for c in codes}, 'sensitivity': {}}
    for k, spec in kinds.items():
        th = spec['thresholds_m']
        d = distances[k]
        out['city'][k] = summarise(d, w, built, th, growth_year, recent_from)
        gaps_p = gaps_s = 0
        for c in codes:
            i = idx[c]
            st = summarise(d[i], w[i], built[i], th, growth_year, recent_from)
            st['status'] = status(st, r)
            out['areas'][c][k] = st
            if st['status'] in ('gap', 'gap_check'):
                gaps_p += 1
            if st['status'] != 'too_few_homes' and st['share_secondary'] is not None and st['share_secondary'] < r['gap_share']:
                gaps_s += 1
        out['sensitivity'][k] = {'gaps_at_primary': gaps_p, 'gaps_at_secondary': gaps_s,
                                 'primary_m': th[0], 'secondary_m': th[1]}
    out['rules'] = {**r, 'recent_from_year': recent_from, 'growth_year': growth_year}
    return out
