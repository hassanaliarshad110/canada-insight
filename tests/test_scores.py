import pytest

from insight.indicators import scores

KINDS = {'playground': {'thresholds_m': [400, 800], 'group': 'local'},
         'transit_stop': {'thresholds_m': [400, 800], 'group': 'local'},
         'library': {'thresholds_m': [2000, 5000], 'group': 'district'}}


def crowd(values):
    """values: {kind: {opt: {dist: {area: v}}}} with city values set to 10 so a score is v / 10."""
    out = {'default': 'model', 'kinds': {}}
    for k, by_opt in values.items():
        out['kinds'][k] = {'by_option': {o: {d: {**areas, '_all': 10.0} for d, areas in dd.items()}
                                         for o, dd in by_opt.items()}}
    return out


def same_everywhere(kind_values):
    """{kind: {area: v}} -> the same value in every scenario."""
    return {k: {o: {str(KINDS[k]['thresholds_m'][0]): a, str(KINDS[k]['thresholds_m'][1]): a}
                for o in ('model', 'census2021')} for k, a in kind_values.items()}


def test_score_band_and_consistent_gap():
    c = crowd(same_everywhere({'playground': {'A': 4.0, 'B': 12.0}, 'transit_stop': {'A': 6.0, 'B': 30.0},
                               'library': {'A': 9.0, 'B': 9.0}}))
    out = scores.compute(c, KINDS, ['A', 'B'])['areas']
    a = out['A']
    assert a['amenities']['playground']['score'] == 0.4
    assert a['amenities']['playground']['band'] == 'well_below'
    assert a['amenities']['playground']['consistency'] == 'consistent_gap'
    assert a['amenities']['library']['band'] == 'around' and a['amenities']['library']['consistency'] == 'none'
    assert a['groups']['local']['score'] == 0.5                                # (0.4 + 0.6) / 2
    # overall, equal: (0.4 + 0.6 + 0.9) / 3; local-heavy: 2/3 x 0.5 + 1/3 x 0.9
    assert a['overall']['low'] == pytest.approx(min(1.9 / 3, 2 / 3 * 0.5 + 0.9 / 3), abs=1e-3)
    assert a['overall']['scenarios'] == 8 and a['overall']['consistency'] == 'consistent_gap'
    # B: transit 3.0 is capped at 2.0 in the group, so it cannot hide anything
    assert out['B']['groups']['local']['score'] == pytest.approx((1.2 + 2.0) / 2)
    assert out['B']['amenities']['transit_stop']['score'] == 3.0               # the amenity score itself is not capped


def test_depends_when_one_assumption_flips_it():
    v = same_everywhere({'playground': {'A': 7.0}, 'transit_stop': {'A': 10.0}, 'library': {'A': 10.0}})
    v['playground']['census2021']['400'] = {'A': 9.0}                          # above 0.80 under the census only
    out = scores.compute(crowd(v), KINDS, ['A'])['areas']['A']
    assert out['amenities']['playground']['consistency'] == 'depends'
    assert out['amenities']['playground']['low'] == 0.7 and out['amenities']['playground']['high'] == 0.9


def test_missing_census_count_is_reported_not_hidden():
    v = same_everywhere({'playground': {'N': 5.0}, 'transit_stop': {'N': 5.0}, 'library': {'N': 5.0}})
    for k in v:
        for d in v[k]['census2021']:
            v[k]['census2021'][d] = {}                                         # a community new since 2021
    out = scores.compute(crowd(v), KINDS, ['N'])['areas']['N']
    assert out['amenities']['playground']['scenarios'] == 2
    assert out['amenities']['playground']['scenarios_possible'] == 4
    assert out['amenities']['playground']['consistency'] == 'consistent_gap'
    assert out['overall']['scenarios'] == 4 and out['overall']['scenarios_possible'] == 8


def test_bands():
    assert [scores.band(x) for x in (0.2, 0.5, 0.79, 0.8, 1.25, 3)] == \
        ['well_below', 'below', 'below', 'around', 'above', 'above']
