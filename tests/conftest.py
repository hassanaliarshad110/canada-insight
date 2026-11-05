import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LAT0 = 51.0
M_LAT = 1 / 111_132.0          # degrees of latitude per metre


def sq(lon0, lat0, w_deg, h_deg):
    ring = [[lon0, lat0], [lon0 + w_deg, lat0], [lon0 + w_deg, lat0 + h_deg], [lon0, lat0 + h_deg], [lon0, lat0]]
    return {'type': 'MultiPolygon', 'coordinates': [[ring]]}


class FakeClient:
    """Stands in for the portal: answers from in-memory tables, filtering only what the tests need."""

    def __init__(self, tables, meta=None, page_size=3):
        self.tables, self.meta, self.page_size = tables, meta or {}, page_size
        self.calls = []

    def _match(self, dataset, where):
        rows = self.tables[dataset]
        if where and ' in(' in where and where.split(' in(')[0].strip() in ('roll_number',):
            ids = {v.strip("'") for v in where.split(' in(')[1].rstrip(')').split(',')}
            return [r for r in rows if str(r.get('roll_number')) in ids]
        flt = self.tables.get(dataset + ':where', {}).get(where)
        return [r for r in rows if flt(r)] if flt else rows

    def _select(self, rows, select):
        if not select:
            return rows
        keys = [s.strip() for s in select.split(',')]
        return [{k: r[k] for k in keys if k in r} for r in rows]

    def pages(self, dataset, select=None, where=None, order=':id'):
        self.calls.append((dataset, where))
        rows = self._select(self._match(dataset, where), select)
        for i in range(0, len(rows), self.page_size):
            yield rows[i:i + self.page_size]

    def rows(self, dataset, select=None, where=None, order=':id'):
        return [r for p in self.pages(dataset, select, where, order) for r in p]

    def fetch_json(self, url):
        if url not in self.tables:
            raise OSError('not found')
        return self.tables[url]

    def overpass(self, bbox):
        if 'overpass' not in self.tables:
            raise OSError('unreachable')
        return self.tables['overpass']

    def metadata(self, dataset):
        return self.meta.get(dataset, {'title': dataset, 'publisher_updated': '2026-11-01', 'licence': 'OGL',
                                       'page': f'https://example.test/d/{dataset}'})


def parcel(roll, comm, year, lon, lat, d=0.00005):
    return {'roll_number': roll, 'comm_code': comm, 'year_of_construction': None if year is None else f'{year}.0',
            'multipolygon': sq(lon - d, lat - d, 2 * d, 2 * d)}


@pytest.fixture
def tiny_city(tmp_path):
    """Two communities side by side, each 1,000 m x 1,000 m. A playground sits at the west edge of community B,
    so homes in community A near the shared boundary reach it even though A has none of its own."""
    kx = 111_132.0 * 0.6293203910498374          # cos(51 degrees)
    m_lon = 1 / kx
    lon0, lat0 = -114.0, LAT0
    A = sq(lon0, lat0, 1000 * m_lon, 1000 * M_LAT)
    B = sq(lon0 + 1000 * m_lon, lat0, 1000 * m_lon, 1000 * M_LAT)
    mid = lat0 + 500 * M_LAT
    play = [lon0 + 1000 * m_lon, mid]            # on the A/B boundary
    homes = []
    # community A: homes at 100, 300, 500, 700, 900 m from the west edge, along the middle line
    for i, xm in enumerate([100, 300, 500, 700, 900]):
        homes.append(parcel(f'A{i}', 'AAA', 2021 if xm == 900 else 1990, lon0 + xm * m_lon, mid, d=0.000002))
    # community B: homes at 1,100 to 1,900 m (100 to 900 m east of the playground)
    for i, xm in enumerate([1100, 1300, 1500, 1700, 1900]):
        homes.append(parcel(f'B{i}', 'BBB', 2024 if xm >= 1700 else 2000, lon0 + xm * m_lon, mid, d=0.000002))
    homes.append(parcel('NOGEO', 'AAA', 1990, 0, 0) | {'multipolygon': None})
    park = sq(lon0 + 50 * m_lon, lat0 + 880 * M_LAT, 100 * m_lon, 50 * M_LAT)     # small park in the north-west of A
    tables = {
        'areas': [{'comm_code': 'AAA', 'name': 'Alpha', 'class': 'Residential', 'multipolygon': A},
                  {'comm_code': 'BBB', 'name': 'Beta', 'class': 'Residential', 'multipolygon': B}],
        'homes': homes,
        'rental': [],
        'play': [{'asset_cd': 'P1', 'point': {'type': 'Point', 'coordinates': play}}],
        'parks': [{'asset_cd': 'K1', 'the_geom': park}],
    }
    weights = {'properties': [{'roll': 'A0', 'units': 10, 'source': 'permit'}]}
    d = tmp_path / 'tiny'
    d.mkdir()
    (d / 'weights.json').write_text(json.dumps(weights))
    cfg = {
        'id': 'tiny', 'name': 'Tiny', 'province': 'Test', 'status': 'pilot', 'centre': {'lat': LAT0, 'lon': lon0},
        'portal': {'type': 'socrata', 'base_url': 'https://example.test', 'publisher': 'Test City', 'licence': 'OGL'},
        'growth_year': 2021,
        'areas': {'level': 'community', 'dataset': 'areas', 'code_field': 'comm_code', 'name_field': 'name',
                  'geometry_field': 'multipolygon', 'extra_fields': ['class']},
        'homes': {'dataset': 'homes', 'id_field': 'roll_number', 'area_field': 'comm_code',
                  'built_field': 'year_of_construction', 'geometry_field': 'multipolygon',
                  'unit_weights': {'file': 'weights.json', 'list': 'properties', 'id': 'roll', 'units': 'units',
                                   'kind': 'source', 'title': 'weights'}},
        'amenities': {
            'playground': {'label': 'Playground', 'group': 'local', 'dataset': 'play', 'geometry': 'point',
                           'geometry_field': 'point', 'id_field': 'asset_cd', 'thresholds_m': [400, 800]},
            'park': {'label': 'Park', 'group': 'local', 'dataset': 'parks', 'geometry': 'polygon',
                     'geometry_field': 'the_geom', 'id_field': 'asset_cd', 'thresholds_m': [400, 800]}},
        'rules': {'gap_share': 0.5, 'min_units': 1, 'recent_years': 5, 'recent_share': 0.25},
        'quality': {'max_age_days': {'default': 45}, 'homes_missing_geometry_fail': 0.2},
        '_dir': str(d),
    }
    return cfg, FakeClient(tables)
