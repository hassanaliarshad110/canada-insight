"""Crowding: how many people share the amenities within reach (two-step floating catchment).

This file is the method. docs/methodology/crowding.md explains it in words; tests/test_crowding.py checks it.

Distance (access.py) says whether an amenity is near. It cannot tell a playground shared by 80 children from one
shared by 400. This measure can:

  Step 1, for each amenity j:
      demand(j) = sum of people (children for playgrounds, residents for parks) living in homes within distance d of j
      ratio(j)  = supply(j) / demand(j)          supply: 1 per playground, hectares per park
                  (an amenity with nobody within reach is left out: it serves no one in the data)
  Step 2, for each home i:
      reach(i) = 1,000 x sum of ratio(j) over amenities within d of i     (0 if none within reach)
  An area's figure is the people-weighted average of reach(i) over its homes:
      playgrounds per 1,000 children within reach; park hectares per 1,000 residents within reach.

Property (checked in the tests): sum over homes of reach(i) x people(i) / 1,000 = total supply of the amenities that
have anyone within reach. The measure shares out the supply; it neither creates nor loses any.

People per home are ESTIMATES: each community's estimated children or residents spread evenly over its dwelling
units (see the city config's `people` section for where the estimates come from).
"""
import numpy as np
from scipy.spatial import cKDTree


def pairs_points(homes_xy, pts_xy, d):
    """(amenity index, home index) for every home within d of every point amenity."""
    homes_xy = np.asarray(homes_xy, dtype=float).reshape(-1, 2)
    if not len(pts_xy) or not len(homes_xy):
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    tree = cKDTree(homes_xy)
    hits = tree.query_ball_point(np.asarray(pts_xy, dtype=float), r=d)
    j = np.repeat(np.arange(len(hits)), [len(h) for h in hits]).astype(np.int64)
    i = np.fromiter((x for h in hits for x in h), dtype=np.int64, count=len(j))
    return j, i


def pairs_polygons(homes_xy, polygons_xy, d, spacing=20.0, inside=None, inside_candidates=None):
    """(amenity index, home index) for every home within d of a polygon's edge, or inside it.

    Edges are sampled every `spacing` metres (as in access.distances_to_polygons), so a home up to spacing / 2
    beyond d can be counted. inside(k, x, y) -> bool says whether a home is inside polygon k; it is asked only for
    homes in inside_candidates (indices of homes whose distance to the nearest polygon is 0), which keeps the
    point-in-polygon work small."""
    from .access import densify
    homes_xy = np.asarray(homes_xy, dtype=float).reshape(-1, 2)
    if not len(homes_xy):
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    tree = cKDTree(homes_xy)
    cand_tree = None
    if inside is not None and inside_candidates is not None and len(inside_candidates):
        cand_idx = np.asarray(inside_candidates, dtype=np.int64)
        cand_tree = cKDTree(homes_xy[cand_idx])
    J, I = [], []
    for k, mp in enumerate(polygons_xy):
        pts = [p for poly in mp for ring in poly for p in densify(ring, spacing)]
        if not pts:
            continue
        hits = tree.query_ball_point(np.asarray(pts), r=d)
        near = set(x for h in hits for x in h)
        if cand_tree is not None:
            arr = np.asarray(pts)
            x0, y0 = arr.min(axis=0)
            x1, y1 = arr.max(axis=0)
            half = float(np.hypot(x1 - x0, y1 - y0) / 2)
            for c in cand_tree.query_ball_point(((x0 + x1) / 2, (y0 + y1) / 2), r=half):
                h = int(cand_idx[c])
                if h not in near and inside(k, homes_xy[h, 0], homes_xy[h, 1]):
                    near.add(h)
        if near:
            sel = np.fromiter(near, dtype=np.int64, count=len(near))
            J.append(np.full(len(sel), k, dtype=np.int64))
            I.append(sel)
    if not J:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    return np.concatenate(J), np.concatenate(I)


def reach(pairs, people, supply, n_homes, per=1000.0):
    """Two-step floating catchment. pairs: (amenity idx, home idx); people: per home; supply: per amenity.
    Returns reach per home (supply per `per` people within reach, default 1,000) and the demand on each amenity."""
    j, i = pairs
    people = np.asarray(people, dtype=float)
    supply = np.asarray(supply, dtype=float)
    demand = np.zeros(len(supply))
    np.add.at(demand, j, people[i])
    ratio = np.divide(supply, demand, out=np.zeros_like(supply), where=demand > 0)
    r = np.zeros(n_homes)
    np.add.at(r, i, ratio[j])
    return r * per, demand


def area_average(values, people, groups):
    """People-weighted average of values per group label, and for everything ('_all')."""
    values = np.asarray(values, dtype=float)
    people = np.asarray(people, dtype=float)
    out = {}
    tot = people.sum()
    out['_all'] = float((values * people).sum() / tot) if tot > 0 else None
    labels = np.asarray(groups, dtype=object)
    for g in sorted({x for x in labels if x}):
        m = labels == g
        p = people[m].sum()
        out[g] = float((values[m] * people[m]).sum() / p) if p > 0 else None
    return out
