"""Amenity scores: each community's amenities within reach, per person, against Calgary's, under every reasonable
assumption, and which gaps hold under all of them.

This file is the method. docs/methodology/scores.md explains it in words; tests/test_scores.py checks it.

AMENITY SCORE (one amenity, one scenario)
    score = community's crowding figure / the city's crowding figure          (1.00 = the city level)
    The crowding figure (crowding.py) is supply within reach per person who shares it, so the score already
    combines distance and population. Capped at CAP (2.00) where scores are averaged, so a surplus of one amenity
    cannot hide a shortage of another.

SCENARIOS
    distance:  the amenity's shorter and longer walking distance                                    (2)
    people:    each people option in the city config (Calgary: growth model, 2021 Census)          (2)
    weights:   for the overall score only: equal across all amenities, or local amenities weighted
               more (local group 2/3 of the weight, district group 1/3)                            (2)
    Amenity and group scores have 4 scenarios; the overall score has 8.

GROUP AND OVERALL SCORES
    local     = mean of capped scores of the local amenities (playground, park, transit stop)
    district  = mean of capped scores of the district facilities (community centre, recreation, library)
    overall   = weighted mean of capped amenity scores, under each weight scheme

BANDS (for the figure shown: the default scenario, shorter distance, default people option, equal weights)
    under 0.50 well below; 0.50 to 0.80 below; 0.80 to 1.25 around; over 1.25 above

CONSISTENCY (the replacement for a single ranking)
    consistent_gap   below 0.80 in every scenario with a figure
    depends          below 0.80 in some scenarios but not all
    none             never below 0.80
    A community with figures in fewer scenarios than the full set (e.g. no 2021 Census count) says so
    (`scenarios` against `scenarios_possible`).
"""
from itertools import product

CAP = 2.0
BELOW = 0.80
BANDS = ((0.50, 'well_below'), (0.80, 'below'), (1.25, 'around'), (float('inf'), 'above'))
WEIGHTS = {'equal': None, 'local_heavy': {'local': 2 / 3, 'district': 1 / 3}}


def band(v):
    if v is None:
        return None
    for top, name in BANDS:
        if v < top:
            return name
    return 'above'


def consistency(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    below = sum(1 for v in vals if v < BELOW)
    return 'consistent_gap' if below == len(vals) else 'depends' if below else 'none'


def summary(values, default):
    vals = [v for v in values.values() if v is not None]
    return {'score': None if default is None else round(default, 3),
            'band': band(default),
            'low': round(min(vals), 3) if vals else None,
            'high': round(max(vals), 3) if vals else None,
            'consistency': consistency(values.values()),
            'scenarios': len(vals), 'scenarios_possible': len(values)}


def compute(crowding_out, kinds_cfg, eligible):
    """crowding_out: the pipeline's crowding result ({'kinds': {k: {'by_option': {opt: {dist: {area: value}}}}}}).
    kinds_cfg: the city config's amenities (thresholds_m, group). eligible: area codes with enough homes to score.

    Returns {'areas': {code: {'amenities': {k: summary}, 'groups': {g: summary}, 'overall': summary}},
             'scenarios': {...}, 'rules': {...}}."""
    kinds = [k for k in kinds_cfg if k in crowding_out['kinds']]
    opts = list(next(iter(crowding_out['kinds'].values()))['by_option'].keys()) if kinds else []
    default_opt = crowding_out.get('default') if crowding_out.get('default') in opts else (opts[0] if opts else None)
    groups = {}
    for k in kinds:
        groups.setdefault(kinds_cfg[k]['group'], []).append(k)

    def raw(k, opt, di, code):
        d = str(kinds_cfg[k]['thresholds_m'][di])
        by = crowding_out['kinds'][k]['by_option'].get(opt, {}).get(d)
        if not by:
            return None
        v, city = by.get(code), by.get('_all')
        return None if v is None or not city else v / city

    scen = list(product(opts, (0, 1)))                      # (people option, distance index)
    out = {}
    for code in sorted(eligible):
        am, per_scen = {}, {}
        for k in kinds:
            vals = {f'{o}|{di}': raw(k, o, di, code) for o, di in scen}
            am[k] = summary(vals, vals.get(f'{default_opt}|0'))
            for s, v in vals.items():
                per_scen.setdefault(s, {})[k] = v
        gr = {}
        for g, ks in groups.items():
            vals = {}
            for s, v in per_scen.items():
                xs = [min(v[k], CAP) for k in ks if v.get(k) is not None]
                vals[s] = sum(xs) / len(xs) if len(xs) == len(ks) else None      # every amenity in the group needed
            gr[g] = summary(vals, vals.get(f'{default_opt}|0'))
        ov = {}
        for s, v in per_scen.items():
            for wname, w in WEIGHTS.items():
                if any(v.get(k) is None for k in kinds):
                    ov[f'{s}|{wname}'] = None
                    continue
                if w is None:
                    ov[f'{s}|{wname}'] = sum(min(v[k], CAP) for k in kinds) / len(kinds)
                else:
                    tot = 0.0
                    for g, ks in groups.items():
                        tot += w.get(g, 0) * sum(min(v[k], CAP) for k in ks) / len(ks)
                    ov[f'{s}|{wname}'] = tot / sum(w.get(g, 0) for g in groups)
        out[code] = {'amenities': am, 'groups': gr, 'overall': summary(ov, ov.get(f'{default_opt}|0|equal'))}
    return {'areas': out,
            'scenarios': {'people': opts, 'default_people': default_opt, 'distances': ['shorter', 'longer'],
                          'weights': list(WEIGHTS)},
            'groups': groups,
            'rules': {'cap': CAP, 'below': BELOW, 'bands': [[t if t != float('inf') else None, n] for t, n in BANDS],
                      'local_heavy': WEIGHTS['local_heavy']}}
