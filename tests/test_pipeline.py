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
    sc = data['scores']['areas']['BBB']
    assert set(sc['groups']) == {'local'} and sc['amenities']['playground']['scenarios'] == 4
    assert sc['amenities']['playground']['score'] == round(pg['BBB'] / pg['_all'], 3)


def test_unreadable_people_source_only_warns(tiny_city, tmp_path):
    cfg, client = tiny_city
    with_people(cfg, client, missing_census=True)
    b, data, out = run(cfg, client, tmp_path)
    assert set(data['crowding']['options']) == {'model'}
    q = json.load(open(os.path.join(out, 'quality.json')))
    assert any(c['source'] == 'tiny.people.census2021' and c['status'] == 'warn' for c in q['checks'])


def with_osm_and_wards(cfg, client):
    from conftest import sq, M_LAT
    kx = 111_132.0 * 0.6293203910498374
    m_lon = 1 / kx
    lon0, lat0 = -114.0, 51.0
    mid = lat0 + 500 * M_LAT
    node = lambda i, xm, ym, **tags: {'type': 'node', 'id': i, 'lon': lon0 + xm * m_lon, 'lat': lat0 + ym * M_LAT,
                                      'tags': {'leisure': 'playground', **tags}}
    client.tables['overpass'] = [
        node(1, 120, 500),                       # in A, far from the city playground: added (public)
        node(2, 130, 500),                       # 10 m from node 1: the same playground mapped twice
        node(3, 1010, 500),                      # 10 m from the city playground: the city's own
        node(4, 300, 900, access='private'),     # residents only: added only with private ones
        node(5, 500, 100, fee='yes'),            # paid: left out
    ]
    cfg['supplements'] = {'osm': {'kinds': ['playground', 'park'], 'bbox': [0, 0, 1, 1]}}
    client.tables['wards'] = [{'ward_num': '1', 'councillor': 'One', 'multipolygon': sq(lon0, lat0, 1000 * m_lon, 1000 * M_LAT)},
                              {'ward_num': '2', 'councillor': 'Two', 'multipolygon': sq(lon0 + 1000 * m_lon, lat0, 1000 * m_lon, 1000 * M_LAT)}]
    cfg['wards'] = {'dataset': 'wards', 'code_field': 'ward_num', 'councillor_field': 'councillor', 'geometry_field': 'multipolygon'}


def test_non_city_amenities_and_wards(tiny_city, tmp_path):
    cfg, client = tiny_city
    with_osm_and_wards(cfg, client)
    b, data, out = run(cfg, client, tmp_path)
    st = data['osm']['stats']['playground']
    assert (st['public'], st['private'], st['city'], st['twice'], st['left_out']) == (1, 1, 1, 1, 1)
    A = data['areas']['AAA']['access']
    # city only: 2 of 14 units within 400 m (as before). With the public playground at x = 120 m, the homes at
    # 100 m (10 units), 300 m and 500 m are 20, 180 and 380 m from it: all 14 units are within reach
    assert A['playground|city']['share_primary'] == round(2 / 14, 4)
    assert A['playground']['share_primary'] == 1.0
    assert A['playground|private']['share_primary'] >= A['playground']['share_primary']
    assert data['kinds']['playground|city']['variant_of'] == 'playground'
    assert data['areas']['AAA']['ward'] == '1' and data['areas']['BBB']['ward'] == '2'
    assert data['wards']['1']['access']['playground|city']['share_primary'] == round(2 / 14, 4)
    assert data['wards']['2']['councillor'] == 'Two'
    assert os.path.exists(os.path.join(out, 'wards.geojson')) and os.path.exists(os.path.join(out, 'osm_features.json'))


def test_osm_unreachable_reuses_last_copy(tiny_city, tmp_path):
    cfg, client = tiny_city
    with_osm_and_wards(cfg, client)
    _, first, out = run(cfg, client, tmp_path)
    prev = os.path.dirname(out)
    del client.tables['overpass']
    b = pipeline.Builder(cfg, client=client, today=date(2026, 11, 20), previous_dir=prev)
    areas, homes, ams, res = b.run()
    assert res['areas']['AAA']['playground']['share_primary'] == first['areas']['AAA']['access']['playground']['share_primary']
    assert any(c.check == 'read' and 'copy read' in c.detail for c in b.checks)


def test_linked_dashboard_and_fallback(tmp_path):
    from insight import linked
    w0 = {'built_at': '2026-11-05 02:12', 'period': 'Nov 2025 to Oct 2026', 'population': {'model_total': 10, 'method_about': 'x'},
          'summary': {'requests12': 5, 'nested': {'a': 1, 'list': [1]}},
          'wards_summary': {'city': {'ward': 0, 'requests_per_1000': 300.0, 'amenity_level': 1.0},
                            'wards': [{'ward': 1, 'requests_per_1000': 250.0, 'amenity_level': 0.5}], 'note': 'n'}}
    cfg = {'id': 'tiny', 'linked_dashboard': {'title': 't', 'publisher': 'p', 'page': 'https://x.test/', 'base_url': 'https://x.test/',
                                              'default_method': 'm', 'methods': {'m': 'Method'}}}
    calls = []

    def fetch(url):
        calls.append(url)
        if url.endswith('w0.json'):
            return w0
        raise OSError('none')
    d = tmp_path / 'tiny'
    d.mkdir()
    pipeline.write_linked(cfg, str(d), fetch=fetch)
    out = json.load(open(d / 'dashboard.json'))
    m = out['methods']['m']
    assert m['wards'][0] == {'ward': 1, 'requests_per_1000': 250.0}         # old amenity level dropped
    assert m['summary'] == {'requests12': 5, 'nested': {'a': 1}}
    # unreachable: the previous copy is kept and marked stale
    prev = tmp_path / 'prev' / 'tiny'
    prev.mkdir(parents=True)
    (prev / 'dashboard.json').write_text(json.dumps(out))
    d2 = tmp_path / 'new' / 'tiny'
    d2.mkdir(parents=True)
    pipeline.write_linked(cfg, str(d2), previous_dir=str(tmp_path / 'prev'), fetch=lambda u: (_ for _ in ()).throw(OSError('down')))
    assert json.load(open(d2 / 'dashboard.json'))['stale'] is True


def test_point_homes_join_census_and_new_homes(tiny_city, tmp_path):
    """Edmonton-style data: homes as points, year built and floor area in a second dataset, apartment units
    estimated from floor area, residents from census tables, and residents added for homes built since."""
    from conftest import M_LAT
    cfg, client = tiny_city
    kx = 111_132.0 * 0.6293203910498374
    lon0, lat0 = -114.0, 51.0
    mid = lat0 + 500 * M_LAT
    pts = lambda xm: {'type': 'Point', 'coordinates': [lon0 + xm / kx, mid]}
    client.tables['props'] = [
        {'acct': '1', 'nbhd': '10.0', 'cls': 'Residential', 'pt': pts(100)},
        {'acct': '2', 'nbhd': '10', 'cls': 'Residential', 'pt': pts(300)},
        {'acct': '3', 'nbhd': '10', 'cls': 'Other Residential', 'pt': pts(500)},     # apartment, 850 m2 -> 10 homes
        {'acct': '4', 'nbhd': '10', 'cls': 'Residential', 'pt': pts(700)},           # vacant: no year built
        {'acct': '5', 'nbhd': '20', 'cls': 'Residential', 'pt': pts(1100)},          # new home, area 20
    ]
    client.tables['info'] = [{'acct': '1', 'yb': '1980'}, {'acct': '2', 'yb': '1990'}, {'acct': '3', 'yb': '1975', 'gfa': '850'},
                             {'acct': '5', 'yb': '2023'}]
    for a in client.tables['areas']:
        a['comm_code'] = {'AAA': '10', 'BBB': '20'}[a['comm_code']]
    cfg['homes'] = {'dataset': 'props', 'id_field': 'acct', 'area_field': 'nbhd', 'built_field': 'yb', 'geometry_field': 'pt',
                    'require_built': True,
                    'join': {'dataset': 'info', 'id_field': 'acct', 'built_field': 'yb', 'area_field': 'gfa'},
                    'unit_estimate': {'class_field': 'cls', 'equals': 'Other Residential', 'm2_per_unit': 85, 'note': 'n'}}
    client.tables['pop'] = [{'n': '10', 'p': '24'}]
    client.tables['age'] = [{'n': '10.0', 'v': '6'}]
    cfg['people'] = {'default': 'plus', 'options': {
        'census': {'type': 'census', 'label': '2021 Census', 'title': 't', 'dataset': 'pop', 'code_field': 'n',
                   'residents_field': 'p', 'children_dataset': 'age', 'children_code_field': 'n', 'children_field': 'v'},
        'plus': {'type': 'census_plus_new', 'based_on': 'census', 'label': 'Census plus new homes', 'title': 't'}}}
    cfg['amenities']['playground']['crowding'] = {'people': 'children', 'unit': 'u'}
    b, data, out = run(cfg, client, tmp_path)
    A = data['areas']['10']
    assert A['units'] == 12 and A['records'] == 3              # 1 + 1 + 10 estimated; the vacant property left out
    assert data['homes']['units_estimated'] == 10
    res = b.sources['people.census']
    assert res.rows == 2
    pg = data['crowding']['kinds']['playground']['by_option']
    # census: area 20 has no count, so no children there; plus-new: 1 new home x city people per home (24 / 12 = 2)
    assert pg['census']['400'].get('20') in (None, 0.0)
    assert pg['plus']['400']['20'] is not None and pg['plus']['400']['20'] > 0
    tot = data['crowding']['options']
    assert tot['census']['totals']['_all']['residents'] == 24          # every census resident is placed in a home
    assert tot['plus']['totals']['_all']['residents'] == 26            # plus 1 new home x 2 people per home
