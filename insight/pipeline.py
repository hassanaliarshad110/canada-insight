"""Build one city's published data: fetch, validate, compute, record provenance, write.

    python -m insight build --city calgary --out site/data [--previous DIR]

Every source read is recorded in sources.json (publisher's title, URL, filter, publisher's last update, when it was
read, rows, a hash of the extracted rows, and the transformations applied). Every check is in quality.json. A
check that fails stops the build before anything is written, so a broken feed never replaces good published data.
"""
import csv
import hashlib
import json
import math
import re
import os
from datetime import date, datetime, timezone

import numpy as np

from . import __version__, config, geo, quality
from .indicators import access, crowding
from .model import Source
from .socrata import SocrataClient, rows_hash


class BuildFailed(RuntimeError):
    def __init__(self, checks):
        self.checks = checks
        super().__init__('; '.join(f'{c.source} {c.check}: {c.detail}' for c in checks))


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _first_ring(geom):
    mp = geo.as_multipolygon(geom)
    if not mp or not mp[0] or not mp[0][0]:
        return None
    return mp[0][0]


def tidy_name(name, case=None):
    """Publisher names as people write them: 'MCKENZIE TOWNE' -> 'McKenzie Towne' when the config asks for title case."""
    name = (name or '').strip()
    if case != 'title' or not name.isupper():
        return name
    out = re.sub(r"[A-Za-z]+('[A-Za-z]+)?", lambda m: m.group(0).capitalize(), name.lower())
    out = re.sub(r'\bMc([a-z])', lambda m: 'Mc' + m.group(1).upper(), out)
    return re.sub(r'\b(Sw|Se|Nw|Ne|Ii|Iii)\b', lambda m: m.group(0).upper(), out)


def _num_year(v):
    try:
        y = int(float(v))
    except (TypeError, ValueError):
        return None
    return y if y > 0 else None


class Builder:
    def __init__(self, cfg, client=None, today=None, previous=None):
        self.cfg = cfg
        self.client = client or SocrataClient(cfg['portal']['base_url'])
        self.today = today or date.today()
        self.proj = geo.Projection(cfg['centre']['lat'])
        self.sources, self.checks = {}, []
        self.previous = previous or {}          # {source id: rows} from the last published build
        self.qcfg = cfg.get('quality') or {}

    # ---- provenance --------------------------------------------------------------------------------------------
    def _source(self, key, dataset, title, query, unit, coverage, period, limitations, transformations):
        p = self.cfg['portal']
        try:
            meta = self.client.metadata(dataset)
        except Exception as e:                  # metadata is informative; a failure is recorded, not fatal
            meta = {'title': None, 'publisher_updated': None, 'licence': None, 'page': f"{p['base_url']}/d/{dataset}"}
            self.checks.append(quality.QualityCheck(key, 'metadata', 'warn', f'could not read metadata: {e}'))
        s = Source(id=f"{self.cfg['id']}.{key}", title=meta.get('title') or title, publisher=p['publisher'],
                   url=meta.get('page') or f"{p['base_url']}/d/{dataset}", api=f"{p['base_url']}/resource/{dataset}.json",
                   licence=p.get('licence') or meta.get('licence') or '', coverage=coverage, period=period, unit=unit,
                   limitations=list(limitations or []), publisher_updated=meta.get('publisher_updated'),
                   fetched_at=_now(), query=query, transformations=list(transformations or []))
        self.sources[key] = s
        ages = self.qcfg.get('max_age_days') or {}
        self.checks.append(quality.stale(s.id, s.publisher_updated, ages.get(dataset, ages.get('default', 45)), self.today))
        return s

    def _count_check(self, key, n):
        self.checks.append(quality.count_change(f"{self.cfg['id']}.{key}", n, self.previous.get(key)))

    # ---- areas -------------------------------------------------------------------------------------------------
    def areas(self):
        a = self.cfg['areas']
        fields = [a['code_field'], a['name_field'], a['geometry_field']] + list(a.get('extra_fields') or [])
        s = self._source('areas', a['dataset'], a.get('title', 'Areas'), None, f"one {a['level']} boundary",
                         'whole city', 'current boundaries', a.get('limitations'),
                         ['polygons simplified for display (Douglas-Peucker, %s m)' % a.get('simplify_m', 15)])
        rows = self.client.rows(a['dataset'], select=','.join(fields))
        self.checks.append(quality.required_fields(s.id, rows, fields))
        self.checks.append(quality.missing(s.id, rows, a['geometry_field'], warn=0.0, fail=0.05, label='geometry'))
        self.checks.append(quality.duplicates(s.id, rows, a['code_field'], warn=0.0, fail=0.0))
        self._count_check('areas', len(rows))
        s.rows = len(rows)
        s.sha256 = rows_hash([{k: r.get(k) for k in fields if k != a['geometry_field']} for r in rows])
        out = {}
        for r in rows:
            mp = geo.as_multipolygon(r.get(a['geometry_field']))
            code = r.get(a['code_field'])
            if not mp or not code:
                continue
            out[code] = {'code': code, 'name': tidy_name(r.get(a['name_field']) or code, a.get('name_case')),
                         'attrs': {f: r.get(f) for f in a.get('extra_fields') or []}, 'mp': mp}
        lons = [p[0] for v in out.values() for poly in v['mp'] for p in poly[0]]
        lats = [p[1] for v in out.values() for poly in v['mp'] for p in poly[0]]
        m = self.qcfg.get('extent_margin_deg', 0.05)
        self.extent = (min(lons) - m, min(lats) - m, max(lons) + m, max(lats) + m)
        return out

    # ---- homes -------------------------------------------------------------------------------------------------
    def homes(self, area_codes):
        h = self.cfg['homes']
        fields = [h['id_field'], h['area_field'], h['built_field'], h['geometry_field']]
        uw = h.get('unit_weights')
        weights = {}
        if uw:
            with open(os.path.join(self.cfg['_dir'], uw['file']), encoding='utf-8') as f:
                wf = json.load(f)
            for p in wf[uw['list']]:
                weights[str(p[uw['id']])] = (float(p[uw['units']]), p.get(uw.get('kind')) or 'estimated')
        s = self._source('homes', h['dataset'], h.get('title', 'Homes'), h.get('where'), h.get('unit', 'one home'),
                         'whole city', f'current roll (read {self.today.isoformat()})', h.get('limitations'),
                         ['each record placed at the mean of its parcel outline\'s vertices',
                          'records listed in the unit-weights file count as their number of units'
                          if uw else 'each record counts as one home'])
        ids, area, built, xy, wt, wkind = [], [], [], [], [], []
        h_hash = hashlib.sha256()
        nogeo = 0
        seen = set()

        def take(page):
            nonlocal nogeo
            for r in page:
                rid = str(r.get(h['id_field']))
                ring = _first_ring(r.get(h['geometry_field']))
                yb = _num_year(r.get(h['built_field']))
                h_hash.update(f"{rid}|{r.get(h['area_field'])}|{yb}".encode())
                if ring is None:
                    nogeo += 1
                    continue
                if rid in seen:
                    continue
                seen.add(rid)
                lon, lat = geo.centroid(ring)
                ids.append(rid)
                area.append(r.get(h['area_field']))
                built.append(yb)
                xy.append(self.proj.xy(lon, lat))
                u, k = weights.get(rid, (1.0, 'official'))
                wt.append(u)
                wkind.append('official' if k in ('official', 'permit') else 'estimate')

        n_read = 0
        first = None
        for page in self.client.pages(h['dataset'], select=','.join(fields), where=h.get('where')):
            if first is None:
                first = page
                self.checks.append(quality.required_fields(s.id, page, fields))
            n_read += len(page)
            take(page)
        dup_n = n_read - nogeo - len(ids)
        # rental buildings outside the residential filter, read by id
        extra = [rid for rid in weights if rid not in seen]
        extra_read = 0
        for i in range(0, len(extra), 200):
            batch = extra[i:i + 200]
            where = f"{h['id_field']} in(" + ','.join("'" + b.replace("'", "''") + "'" for b in batch) + ')'
            rows = self.client.rows(h['dataset'], select=','.join(fields), where=where)
            extra_read += len(rows)
            take(rows)
        s.rows = n_read + extra_read
        s.sha256 = h_hash.hexdigest()
        if uw:
            missing_w = sum(1 for rid in extra if rid not in seen)
            s.transformations.append(f'{len(extra) - missing_w:,} rental buildings outside the residential filter added by '
                                     f'roll number ({extra_read:,} rows read); {missing_w:,} buildings listed in the '
                                     f'weights file were not found on the current roll and are not counted')
            used = sum(weights[rid][0] for rid in weights if rid in seen)
            self.weights_note = {'buildings_listed': len(weights), 'buildings_found': len(weights) - missing_w,
                                 'units_used': round(used, 1)}
        fail_at = self.qcfg.get('homes_missing_geometry_fail', 0.05)
        self.checks.append(quality.QualityCheck(s.id, 'missing_geometry',
                                                'fail' if nogeo / max(n_read, 1) > fail_at else 'warn' if nogeo else 'pass',
                                                f'{nogeo:,} of {n_read:,} records have no parcel outline (left out)',
                                                round(nogeo / max(n_read, 1), 5), 0.0))
        self.checks.append(quality.QualityCheck(s.id, f"duplicate_{h['id_field']}", 'warn' if dup_n > 0 else 'pass',
                                                f'{dup_n:,} repeated records left out', dup_n))
        lonlat = [self.proj.lonlat(x, y) for x, y in xy]
        self.checks.append(quality.outside_bbox(s.id, lonlat, self.extent))
        self.checks.append(quality.unknown_codes(s.id, area, area_codes))
        self.checks.append(quality.year_range(s.id, built, hi=self.today.year + 1))
        self._count_check('homes', s.rows)
        if uw:
            path = f"cities/{self.cfg['id']}/{uw['file']}"
            with open(os.path.join(self.cfg['_dir'], uw['file']), 'rb') as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            self.sources['unit_weights'] = Source(
                id=f"{self.cfg['id']}.unit_weights", title=uw['title'],
                publisher='Calgary Data Desk (Hassan Ali), derived from City of Calgary open data', url=path, api=path,
                licence='Derived from open data under the publisher\'s licence', coverage='whole city',
                period='as built by the model', unit='one rental building', limitations=[uw.get('note', '')],
                publisher_updated=None, fetched_at=_now(), rows=len(weights), query=None, sha256=digest,
                transformations=['joined to the roll by roll number'])
        return {'id': ids, 'area': area, 'built': built, 'xy': np.asarray(xy, dtype=float),
                'weight': wt, 'weight_kind': wkind}

    # ---- amenities ---------------------------------------------------------------------------------------------
    def amenities(self):
        out = {}
        for key, a in self.cfg['amenities'].items():
            fields = [a['geometry_field']] + ([a['id_field']] if a.get('id_field') else [])
            s = self._source(f'amenity.{key}', a['dataset'], a.get('title', key), a.get('where'),
                             f"one {a['label'].lower()}", 'whole city', 'current inventory', a.get('limitations'),
                             ['distance to the nearest one from every home' +
                              (', to the polygon edge (edges sampled every 20 m)' if a['geometry'] == 'polygon' else '')])
            rows = self.client.rows(a['dataset'], select=','.join(fields), where=a.get('where'))
            self.checks.append(quality.required_fields(s.id, rows, [a['geometry_field']]))
            self.checks.append(quality.missing(s.id, rows, a['geometry_field'], warn=0.0, fail=0.2, label='location'))
            self._count_check(f'amenity.{key}', len(rows))
            s.rows = len(rows)
            s.sha256 = rows_hash(rows)
            feats, xy, polys = [], [], []
            for r in rows:
                g = r.get(a['geometry_field'])
                if not g:
                    continue
                if a['geometry'] == 'point':
                    c = g.get('coordinates') if isinstance(g, dict) else None
                    if not c:
                        continue
                    xy.append(self.proj.xy(c[0], c[1]))
                    feats.append({'type': 'Feature', 'properties': {'id': r.get(a.get('id_field'))},
                                  'geometry': {'type': 'Point', 'coordinates': [round(c[0], 6), round(c[1], 6)]}})
                else:
                    mp = geo.as_multipolygon(g)
                    if not mp:
                        continue
                    pxy = self.proj.multipolygon(mp)
                    polys.append(pxy)
                    simp = [[[list(self.proj.lonlat(x, y)) for x, y in ring] for ring in poly]
                            for poly in geo.simplify_multipolygon(pxy, 8, digits=1)]
                    if simp:
                        feats.append({'type': 'Feature', 'properties': {'id': r.get(a.get('id_field'))},
                                      'geometry': {'type': 'MultiPolygon', 'coordinates': [[[[round(p[0], 6), round(p[1], 6)]
                                                                                              for p in ring] for ring in poly]
                                                                                            for poly in simp]}})
            pts_ll = [self.proj.lonlat(x, y) for x, y in xy] if xy else \
                [self.proj.lonlat(*mp[0][0][0]) for mp in polys if mp and mp[0] and mp[0][0]]
            self.checks.append(quality.outside_bbox(s.id, pts_ll, self.extent))
            supply = [1.0] * len(xy) if a['geometry'] == 'point' else [geo.area(p) / 10_000 for p in polys]
            out[key] = {'xy': xy, 'polys': polys, 'features': feats, 'supply': supply}
        return out

    # ---- people (estimates, for crowding) ---------------------------------------------------------------------------
    def people(self, area_units):
        """{option: {'by_area': {code: {'residents', 'children'}}, ...}} from each source in the config's `people`
        section. A source that cannot be read is skipped with a warning: crowding is then left out for that option,
        and the distance figures are unaffected."""
        pc = self.cfg.get('people')
        if not pc:
            return {}
        out = {}
        for opt, o in pc['options'].items():
            key = f'people.{opt}'
            s = Source(id=f"{self.cfg['id']}.{key}", title=o['title'], publisher=o['publisher'], url=o.get('page', o['url']),
                       api=o['url'], licence=o.get('licence', ''), coverage='whole city', period=o.get('period', ''),
                       unit=f"one {self.cfg['areas']['level']}", limitations=list(o.get('limitations') or []),
                       fetched_at=_now(), transformations=[
                           'each area\'s residents and children spread evenly over its dwelling units',
                           'areas with fewer than %s residents are not in the source and get none' % o.get('min_residents', 100)])
            try:
                raw = self._fetch_json(o['url'])
            except Exception as e:
                self.checks.append(quality.QualityCheck(s.id, 'read', 'warn', f'could not read: {e}; crowding left out'))
                continue
            node = raw
            for k in pc['path']:
                node = node[k]
            rows = node if isinstance(node, list) else list(node.values())
            s.rows = len(rows)
            s.sha256 = rows_hash(rows)
            s.publisher_updated = (str(raw.get(pc.get('updated_field', 'built_at')) or '')[:10]) or None
            by = {}
            for r in rows:
                code = r.get(pc['code_field'])
                if code:
                    by[code] = {'residents': float(r.get(pc['residents_field']) or 0),
                                'children': float(r.get(pc['children_field']) or 0)}
            covered = sum(u for c, u in area_units.items() if c in by)
            total = sum(area_units.values()) or 1
            share = covered / total
            self.checks.append(quality.QualityCheck(
                s.id, 'coverage', 'warn' if share < 0.97 else 'pass',
                f'{share:.1%} of dwelling units are in areas with an estimate', round(share, 4), 0.97))
            self.checks.append(quality.stale(s.id, s.publisher_updated, o.get('max_age_days', 7), self.today))
            self.sources[key] = s
            out[opt] = {'by_area': by, 'label': o['label'], 'about': o.get('about', '')}
            ref = pc.get('homes_reference')
            if ref and opt == pc.get('default'):
                try:
                    node = raw
                    for k in ref['path']:
                        node = node[k]
                    self.homes_ref = {'label': ref['label'], 'note': ref.get('note', ''),
                                      'by_area': {r[ref['code_field']]: r.get(ref['field']) for r in node
                                                  if r.get(ref['code_field']) and r.get(ref['field']) is not None}}
                except (KeyError, TypeError) as e:
                    self.checks.append(quality.QualityCheck(s.id, 'homes_reference', 'warn', f'not found: {e}'))
        return out

    def _fetch_json(self, url):
        if hasattr(self.client, 'fetch_json'):
            return self.client.fetch_json(url)
        import urllib.request
        req = urllib.request.Request(url, headers={'User-Agent': 'canada-insight/0.1'})
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read().decode('utf-8'))

    # ---- build -------------------------------------------------------------------------------------------------
    def run(self):
        cfg = self.cfg
        areas = self.areas()
        homes = self.homes(set(areas))
        ams = self.amenities()
        blocking = [c for c in self.checks if c.status == 'fail']
        if blocking:
            raise BuildFailed(blocking)
        distances = {}
        for key, a in cfg['amenities'].items():
            cap = a['thresholds_m'][1]
            if a['geometry'] == 'point':
                distances[key] = access.distances_to_points(homes['xy'], ams[key]['xy'], cap)
            else:
                loc = geo.AreaLocator({i: p for i, p in enumerate(ams[key]['polys'])}, cell=1000.0)
                distances[key] = access.distances_to_polygons(homes['xy'], ams[key]['polys'], cap,
                                                              inside=lambda x, y, loc=loc: loc.find(x, y) is not None)
        res = access.compute(homes, distances, {k: a for k, a in cfg['amenities'].items()},
                             cfg['growth_year'], self.today.year, cfg.get('rules'))
        res['crowding'] = self.crowding(homes, ams, distances)
        return areas, homes, ams, res

    def crowding(self, homes, ams, distances):
        """Two-step floating catchment for amenities with a `crowding` section, under each people option."""
        cfg = self.cfg
        units = np.asarray(homes['weight'], dtype=float)
        area = np.asarray(homes['area'], dtype=object)
        area_units = {}
        for a_, u in zip(homes['area'], homes['weight']):
            if a_:
                area_units[a_] = area_units.get(a_, 0) + u
        opts = self.people(area_units)
        if not opts:
            return None
        out = {'options': {k: {'label': v['label'], 'about': v['about']} for k, v in opts.items()},
               'default': cfg['people'].get('default'), 'kinds': {}}
        for key, a in cfg['amenities'].items():
            cr = a.get('crowding')
            if not cr:
                continue
            am = ams[key]
            pairs_by_d = []
            for d in a['thresholds_m']:
                if a['geometry'] == 'point':
                    pairs_by_d.append(crowding.pairs_points(homes['xy'], am['xy'], d))
                else:
                    inside_c = np.where(distances[key] == 0)[0]
                    pairs_by_d.append(crowding.pairs_polygons(
                        homes['xy'], am['polys'], d,
                        inside=lambda k, x, y, polys=am['polys']: geo.point_in_multipolygon(x, y, polys[k]),
                        inside_candidates=inside_c))
            res_k = {'people': cr['people'], 'unit': cr['unit'], 'by_option': {}}
            for opt, o in opts.items():
                per_unit = {c: (v[cr['people']] / area_units[c]) for c, v in o['by_area'].items()
                            if area_units.get(c)}
                people = units * np.asarray([per_unit.get(c, 0.0) for c in area], dtype=float)
                vals = {}
                for di, d in enumerate(a['thresholds_m']):
                    r, demand = crowding.reach(pairs_by_d[di], people, am['supply'], len(units))
                    avg = crowding.area_average(r, people, area)
                    vals[str(d)] = {k2: (None if v is None else round(v, 3)) for k2, v in avg.items()}
                    vals[str(d)]['_amenities_with_people'] = int((demand > 0).sum())
                res_k['by_option'][opt] = vals
            out['kinds'][key] = res_k
        return out


def _feature_collection(features):
    return {'type': 'FeatureCollection', 'features': features}


def write(builder, areas, homes, ams, res, out_dir):
    cfg = builder.cfg
    d = os.path.join(out_dir, cfg['id'])
    os.makedirs(os.path.join(d, 'amenities'), exist_ok=True)
    built_at = _now()
    est_units = round(sum(w for w, k in zip(homes['weight'], homes['weight_kind']) if k == 'estimate'), 1)
    kinds = {k: {f: a.get(f) for f in ('label', 'plural', 'group', 'geometry', 'thresholds_m', 'threshold_basis',
                                       'threshold_url', 'limitations')} for k, a in cfg['amenities'].items()}
    # areas with homes, in name order
    table = {}
    for code in sorted(res['areas'], key=lambda c: (areas.get(c) or {}).get('name', c)):
        a = areas.get(code) or {'name': code, 'attrs': {}}
        any_k = next(iter(res['areas'][code].values()))
        table[code] = {'name': a['name'], 'attrs': a.get('attrs', {}), 'units': any_k['units'],
                       'records': any_k['records'], 'units_new': any_k['units_new'],
                       'units_recent': any_k['units_recent'], 'access': res['areas'][code]}
        href = getattr(builder, 'homes_ref', None)
        if href and href['by_area'].get(code) is not None:
            table[code]['homes_reference'] = href['by_area'][code]
    payload = {
        'city': cfg['id'], 'name': cfg['name'], 'built_at': built_at, 'version': __version__,
        'level': cfg['areas']['level'], 'terms': cfg.get('terms', {}), 'growth_year': cfg['growth_year'],
        'growth_year_note': cfg.get('growth_year_note'), 'kinds': kinds, 'rules': res['rules'],
        'sensitivity': res['sensitivity'], 'city_access': res['city'],
        'homes': {'records': len(homes['id']), 'units': round(float(sum(homes['weight'])), 1),
                  'units_estimated': est_units, 'unit': cfg['homes'].get('unit'),
                  'not_in_an_area': sum(1 for a in homes['area'] if not a or a not in areas),
                  'rental_weights': getattr(builder, 'weights_note', None),
                  'reference': ({'label': builder.homes_ref['label'], 'note': builder.homes_ref['note'],
                                 'total': round(sum(v for v in builder.homes_ref['by_area'].values() if v))}
                                if getattr(builder, 'homes_ref', None) else None)},
        'value_kinds': {'units': 'official (one per roll record) except rental buildings, whose units are from building '
                                 'permits (official) or estimated from assessed value (estimate)',
                        'share_*': 'calculated', 'status': 'calculated (a stated rule, not a score)',
                        'crowding': 'estimate (people per home are estimated)'},
        'areas': table,
        'crowding': res.get('crowding'),
    }
    with open(os.path.join(d, 'access.json'), 'w', encoding='utf-8') as f:
        json.dump(payload, f, separators=(',', ':'))
    # boundaries for the map
    tol = cfg['areas'].get('simplify_m', 15)
    feats = []
    for code, a in areas.items():
        pxy = builder.proj.multipolygon(a['mp'])
        simp = geo.simplify_multipolygon(pxy, tol, digits=1)
        coords = [[[[round(v, 5) for v in builder.proj.lonlat(x, y)] for x, y in ring] for ring in poly] for poly in simp]
        if coords:
            feats.append({'type': 'Feature', 'properties': {'code': code, 'name': a['name'], **a['attrs']},
                          'geometry': {'type': 'MultiPolygon', 'coordinates': coords}})
    with open(os.path.join(d, 'areas.geojson'), 'w', encoding='utf-8') as f:
        json.dump(_feature_collection(feats), f, separators=(',', ':'))
    for k, v in ams.items():
        with open(os.path.join(d, 'amenities', f'{k}.geojson'), 'w', encoding='utf-8') as f:
            json.dump(_feature_collection(v['features']), f, separators=(',', ':'))
    # the table for spreadsheets
    with open(os.path.join(d, 'access_by_area.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['code', 'name', 'amenity', 'units', 'units_built_since_' + str(cfg['growth_year']),
                    'share_within_primary', 'primary_m', 'share_within_secondary', 'secondary_m',
                    'share_new_within_primary', 'share_older_within_primary', 'median_m', 'status'])
        for code, r in table.items():
            for k, st in r['access'].items():
                th = cfg['amenities'][k]['thresholds_m']
                w.writerow([code, r['name'], k, st['units'], st['units_new'], st['share_primary'], th[0],
                            st['share_secondary'], th[1], st['share_new_primary'], st['share_old_primary'],
                            st['median_m'] if st['median_m'] is not None else f'>{th[1]}', st['status']])
    with open(os.path.join(d, 'sources.json'), 'w', encoding='utf-8') as f:
        json.dump({'city': cfg['id'], 'built_at': built_at, 'sources': [s.to_dict() for s in builder.sources.values()]},
                  f, indent=1)
    with open(os.path.join(d, 'quality.json'), 'w', encoding='utf-8') as f:
        json.dump({'city': cfg['id'], 'built_at': built_at, 'overall': quality.worst(builder.checks),
                   'checks': [c.to_dict() for c in builder.checks]}, f, indent=1)
    manifest = {'city': cfg['id'], 'built_at': built_at, 'version': __version__,
                'files': sorted(os.path.relpath(os.path.join(r, n), d) for r, _, ns in os.walk(d) for n in ns
                                if n != 'manifest.json')}
    manifest['sha256'] = {p: hashlib.sha256(open(os.path.join(d, p), 'rb').read()).hexdigest() for p in manifest['files']}
    with open(os.path.join(d, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=1)
    return d


def write_index(out_dir, cities):
    """site/data/cities.json: every configured city, its status and readiness, and what is published."""
    out = []
    for c in cities:
        m = os.path.join(out_dir, c['id'], 'manifest.json')
        built = json.load(open(m, encoding='utf-8')).get('built_at') if os.path.exists(m) else None
        out.append({'id': c['id'], 'name': c['name'], 'province': c['province'], 'status': c['status'],
                    'centre': c['centre'], 'built_at': built, 'readiness': c.get('readiness', {}),
                    'modules': ['access'] if built else []})
    with open(os.path.join(out_dir, 'cities.json'), 'w', encoding='utf-8') as f:
        json.dump({'cities': out}, f, indent=1)


def previous_counts(prev_dir, city):
    p = os.path.join(prev_dir or '', city, 'sources.json')
    if not prev_dir or not os.path.exists(p):
        return {}
    data = json.load(open(p, encoding='utf-8'))
    pre = city + '.'
    return {s['id'][len(pre):]: s.get('rows') for s in data.get('sources', []) if s['id'].startswith(pre)}


def build_city(city_id, out_dir, previous_dir=None, client=None, today=None):
    cfg = config.load(city_id)
    b = Builder(cfg, client=client, today=today, previous=previous_counts(previous_dir, city_id))
    areas, homes, ams, res = b.run()
    return write(b, areas, homes, ams, res, out_dir)
