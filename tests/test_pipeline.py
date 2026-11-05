"""End to end on a two-community test city, with every expected figure worked out by hand."""
import csv
import json
import os
from datetime import date

import pytest

from insight import pipeline


def run(cfg, client, tmp_path):
    b = pipeline.Builder(cfg, client=client, today=date(2026, 11, 5))
    areas, homes, ams, res = b.run()
    out = pipeline.write(b, areas, homes, ams, res, str(tmp_path / 'out'))
    return b, json.load(open(os.path.join(out, 'access.json'))), out


def test_boundary_does_not_hide_a_playground_next_door(tiny_city, tmp_path):
    cfg, client = tiny_city
    b, data, out = run(cfg, client, tmp_path)
    A = data['areas']['AAA']['access']['playground']
    B = data['areas']['BBB']['access']['playground']
    # A has no playground of its own. Homes at 700 and 900 m from A's west edge are 300 and 100 m from the playground
    # just over the boundary; the home at 100 m (A0) is a 10-unit rental building, 900 m away.
    assert A['units'] == 14                          # 10 + 4 other homes (the record with no outline is left out)
    assert A['share_primary'] == round(2 / 14, 4)    # 700 m and 900 m homes
    assert A['share_secondary'] == round(4 / 14, 4)  # plus 300 m (700 m away) and 500 m (500 m away)
    assert A['status'] == 'gap'
    # B: 100, 300 m within 400 m; 500, 700 within 800 m; 900 beyond
    assert B['share_primary'] == 0.4 and B['share_secondary'] == 0.8
    assert B['share_new_primary'] == 0.0             # the 2024 homes are 700 and 900 m away
    assert B['status'] == 'gap_check'                # 2 of 5 homes built in the last five years
    assert data['city_access']['playground']['units'] == 19


def test_park_edge_distance(tiny_city, tmp_path):
    cfg, client = tiny_city
    _, data, _ = run(cfg, client, tmp_path)
    # the park spans x 50-150 m, y 880-930 m; homes are on y = 500 m: the home at x = 100 m is 380 m from its edge,
    # the one at x = 300 m is 408 m from its corner
    A = data['areas']['AAA']['access']['park']
    assert A['share_primary'] == round(10 / 14, 4)    # only the rental building at x = 100 m (10 units)


def test_provenance_quality_and_files(tiny_city, tmp_path):
    cfg, client = tiny_city
    b, data, out = run(cfg, client, tmp_path)
    src = {s['id']: s for s in json.load(open(os.path.join(out, 'sources.json')))['sources']}
    assert set(src) == {'tiny.areas', 'tiny.homes', 'tiny.unit_weights', 'tiny.amenity.playground', 'tiny.amenity.park'}
    assert src['tiny.homes']['rows'] == 11 and src['tiny.homes']['sha256']
    q = json.load(open(os.path.join(out, 'quality.json')))
    checks = {(c['source'], c['check']): c for c in q['checks']}
    assert checks[('tiny.homes', 'missing_geometry')]['status'] == 'warn'
    assert q['overall'] in ('pass', 'warn')
    man = json.load(open(os.path.join(out, 'manifest.json')))
    assert {'access.json', 'areas.geojson', 'sources.json', 'quality.json', 'access_by_area.csv',
            'amenities/playground.geojson', 'amenities/park.geojson'} <= set(man['files'])
    rows = list(csv.DictReader(open(os.path.join(out, 'access_by_area.csv'))))
    assert len(rows) == 4 and {r['status'] for r in rows} <= {'gap', 'gap_check', 'no_gap', 'too_few_homes'}


def test_schema_change_stops_the_build(tiny_city, tmp_path):
    cfg, client = tiny_city
    for r in client.tables['homes']:
        r.pop('year_of_construction', None)
    with pytest.raises(pipeline.BuildFailed):
        pipeline.Builder(cfg, client=client, today=date(2026, 11, 5)).run()


def test_large_drop_in_rows_stops_the_build(tiny_city, tmp_path):
    cfg, client = tiny_city
    b = pipeline.Builder(cfg, client=client, today=date(2026, 11, 5), previous={'homes': 1000})
    with pytest.raises(pipeline.BuildFailed):
        b.run()


def with_people(cfg, client, a_children=40, b_children=100, missing_census=False):
    client.tables['https://people.test/model'] = {'built_at': '2026-11-05', 'amenity_gap': {'by_comm': [
        {'code': 'AAA', 'residents': 140, 'children_0_14': a_children},
        {'code': 'BBB', 'residents': 50, 'children_0_14': b_children}]},
        'communities': [{'code': 'AAA', 'homes_now': 13}, {'code': 'BBB', 'homes_now': 3}]}
    cfg['people'] = {'path': ['amenity_gap', 'by_comm'], 'code_field': 'code', 'residents_field': 'residents',
                     'children_field': 'children_0_14', 'default': 'model', 'options': {
                         'model': {'label': 'Growth model', 'title': 't', 'publisher': 'p', 'url': 'https://people.test/model'},
                         'census2021': {'label': '2021 Census', 'title': 't', 'publisher': 'p',
                                        'url': 'https://people.test/missing' if missing_census else 'https://people.test/model'}}}
    cfg['people']['homes_reference'] = {'path': ['communities'], 'code_field': 'code', 'field': 'homes_now',
                                        'label': 'Homes lived in (reference)'}
    cfg['amenities']['playground']['crowding'] = {'people': 'children', 'unit': 'playgrounds per 1,000 children'}
    cfg['amenities']['park']['crowding'] = {'people': 'residents', 'unit': 'park ha per 1,000 residents'}


def test_crowding_end_to_end(tiny_city, tmp_path):
    """Community A: 14 units, 40 children (2.857 per unit). B: 5 units, 100 children (20 per unit).
    At 400 m the playground reaches A's homes at 700 and 900 m (2 units, 5.714 children) and B's at 1,100 and 1,300 m
    (2 units, 40 children): 45.714 children in all, so each reaching child's home gets 1,000 / 45.714 = 21.875."""
    cfg, client = tiny_city
    with_people(cfg, client)
    _, data, _ = run(cfg, client, tmp_path)
    pg = data['crowding']['kinds']['playground']['by_option']['model']['400']
    reach = 1000 / (2 * 40 / 14 + 2 * 20)
    assert abs(pg['AAA'] - round(reach * (2 * 40 / 14) / 40, 3)) < 1e-3       # children-weighted over all of A
    assert abs(pg['BBB'] - round(reach * 40 / 100, 3)) < 1e-3
    # conservation: one playground, all of it shared out among the children within reach
    total_children = 140
    assert abs(pg['_all'] * total_children / 1000 - 1.0) < 1e-3
    assert data['crowding']['default'] == 'model'
    assert set(data['crowding']['kinds']) == {'playground', 'park'}
    assert data['areas']['BBB']['homes_reference'] == 3 and data['homes']['reference']['total'] == 16


def test_unreadable_people_source_only_warns(tiny_city, tmp_path):
    cfg, client = tiny_city
    with_people(cfg, client, missing_census=True)
    b, data, out = run(cfg, client, tmp_path)
    assert set(data['crowding']['options']) == {'model'}
    q = json.load(open(os.path.join(out, 'quality.json')))
    assert any(c['source'] == 'tiny.people.census2021' and c['status'] == 'warn' for c in q['checks'])
