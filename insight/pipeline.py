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
from .indicators import access, crowding, scores
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
    def __init__(self, cfg, client=None, today=None, previous=None, previous_dir=None):
        self.cfg = cfg
        self.client = client or SocrataClient(cfg['portal']['base_url'])
        self.today = today or date.today()
        self.proj = geo.Projection(cfg['centre']['lat'])
        self.sources, self.checks = {}, []
        self.previous = previous or {}          # {source id: rows} from the last published build
        self.qcfg = cfg.get('quality') or {}
        self.previous_dir = previous_dir

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
        wards = self.wards()
        homes = self.homes(set(areas))
        ams = self.amenities()
        blocking = [c for c in self.checks if c.status == 'fail']
        if blocking:
            raise BuildFailed(blocking)
        # each home's ward, by its exact location
        if wards:
            wl = geo.AreaLocator({w: self.proj.multipolygon(v['mp']) for w, v in wards.items()}, cell=1000.0)
            homes['ward'] = [(f'ward:{w}' if w is not None else None)
                             for w in (wl.find(x, y) for x, y in homes['xy'])]
            n_out = sum(1 for w in homes['ward'] if w is None)
            self.checks.append(quality.QualityCheck(f"{cfg['id']}.wards", 'homes_outside_wards',
                                                    'warn' if n_out else 'pass',
                                                    f'{n_out:,} of {len(homes["ward"]):,} homes fall outside every ward',
                                                    n_out))
        kinds, ams = self.amenity_sets(ams, areas)
        self.kinds_expanded = kinds
        distances = {}
        part_cache = {}

        def part_dist(key, a, am, lo, hi):
            base_key = a.get('variant_of') or key
            ck = (base_key, lo, hi)
            if ck not in part_cache:
                cap = a['thresholds_m'][1]
                if a['geometry'] == 'point':
                    part_cache[ck] = access.distances_to_points(homes['xy'], am['xy'][lo:hi], cap)
                else:
                    polys = am['polys'][lo:hi]
                    loc = geo.AreaLocator({i: p for i, p in enumerate(polys)}, cell=1000.0)
                    part_cache[ck] = access.distances_to_polygons(homes['xy'], polys, cap,
                                                                  inside=lambda x, y, loc=loc: loc.find(x, y) is not None)
            return part_cache[ck]
        for key, a in kinds.items():
            am = ams[key]
            n = len(am['xy']) if a['geometry'] == 'point' else len(am['polys'])
            parts = am.get('parts') or [(0, n)]
            ds = [part_dist(key, a, am, lo, hi) for lo, hi in parts if hi > lo]
            distances[key] = np.minimum.reduce(ds) if len(ds) > 1 else (ds[0] if ds else np.full(len(homes['xy']), np.inf))
        res = access.compute(homes, distances, kinds, cfg['growth_year'], self.today.year, cfg.get('rules'))
        if wards:
            hw = dict(homes, area=homes['ward'])
            res['wards'] = access.compute(hw, distances, kinds, cfg['growth_year'], self.today.year,
                                          dict(cfg.get('rules') or {}, min_units=0))['areas']
        res['crowding'] = self.crowding(homes, ams, distances, kinds)
        if res['crowding'] and res['crowding']['kinds']:
            any_k = next(iter(cfg['amenities']))
            eligible = [c for c, v in res['areas'].items() if v[any_k]['status'] != 'too_few_homes']
            eligible += list(res.get('wards') or {})
            base = {k: a for k, a in kinds.items() if not a.get('variant_of')}
            res['scores'] = scores.compute(res['crowding'], base, eligible)
        res['ward_info'] = {w: {'name': v['name'], 'councillor': v.get('councillor')} for w, v in (wards or {}).items()}
        self.wards_data = wards
        return areas, homes, ams, res

    # ---- wards ---------------------------------------------------------------------------------------------------
    def wards(self):
        wc = self.cfg.get('wards')
        if not wc:
            return None
        fields = [wc['code_field'], wc['geometry_field']] + [f for f in (wc.get('name_field'), wc.get('councillor_field')) if f]
        s = self._source('wards', wc['dataset'], wc.get('title', 'Wards'), None, 'one ward boundary', 'whole city',
                         'current boundaries', wc.get('limitations'),
                         ['each home placed in the ward that contains it (point in polygon)'])
        rows = self.client.rows(wc['dataset'], select=','.join(fields))
        self.checks.append(quality.required_fields(s.id, rows, [wc['code_field'], wc['geometry_field']]))
        self._count_check('wards', len(rows))
        s.rows = len(rows)
        s.sha256 = rows_hash([{k: r.get(k) for k in fields if k != wc['geometry_field']} for r in rows])
        out = {}
        for r in rows:
            mp = geo.as_multipolygon(r.get(wc['geometry_field']))
            if not mp or r.get(wc['code_field']) in (None, ''):
                continue
            try:
                code = int(float(r[wc['code_field']]))
            except (TypeError, ValueError):
                code = str(r[wc['code_field']])
            out[code] = {'mp': mp, 'name': f"{wc.get('label', 'Ward')} {code}",
                         'councillor': r.get(wc.get('councillor_field')) if wc.get('councillor_field') else None}
        return out

    # ---- amenity sets: the city's own, plus non-city ones open to everyone, plus private ones --------------------------
    def amenity_sets(self, ams, areas):
        """Expand amenity kinds that have non-city additions into three sets:
              <kind>           the city's own + non-city ones open to everyone (the default, as Calgary Data Desk)
              <kind>|city      the city's own only
              <kind>|private   + private, residents-only ones
        Returns (kinds config, amenities) including the variants."""
        cfg = self.cfg
        kinds = {k: dict(a) for k, a in cfg['amenities'].items()}
        sup = (cfg.get('supplements') or {}).get('osm')
        self.osm_result = None
        if not sup:
            return kinds, ams
        feats = self._osm_features(sup, ams, areas)
        if feats is None:
            return kinds, ams
        out = dict(ams)
        for k in sup['kinds']:
            if k not in kinds:
                continue
            pub = [f for f in feats if f['kind'] == k and not f['private']]
            pri = [f for f in feats if f['kind'] == k and f['private']]
            base = ams[k]
            city_label = kinds[k]['label']

            def merged(extra, base=base):
                if kinds[k]['geometry'] == 'point':
                    xy = list(base['xy']) + [(f['x'], f['y']) for f in extra]
                    return {'xy': xy, 'polys': [], 'supply': [1.0] * len(xy), 'features': base['features']}
                polys = list(base['polys']) + [f['mp'] for f in extra]
                return {'xy': [], 'polys': polys, 'supply': list(base['supply']) + [f['ha'] for f in extra],
                        'features': base['features']}
            out[f'{k}|city'] = base
            out[k] = merged(pub)
            out[f'{k}|private'] = merged(pub + pri)
            nb = len(base['xy']) if kinds[k]['geometry'] == 'point' else len(base['polys'])
            # each set = the city's items, then public additions, then private ones: parts let distances and
            # catchments be worked out once per part and combined (much faster than redoing whole sets)
            out[f'{k}|city']['parts'] = [(0, nb)]
            out[k]['parts'] = [(0, nb), (nb, nb + len(pub))]
            out[f'{k}|private']['parts'] = [(0, nb), (nb, nb + len(pub)), (nb + len(pub), nb + len(pub) + len(pri))]
            kinds[f'{k}|city'] = dict(kinds[k], variant_of=k, set='city', label=f'{city_label} (city only)')
            kinds[f'{k}|private'] = dict(kinds[k], variant_of=k, set='private', label=f'{city_label} (with private)')
            kinds[k]['set'] = 'public'
            out[k]['osm_features'] = pub
            out[f'{k}|private']['osm_features'] = pub + pri
        self.osm_result['added'] = {k: {'public': sum(1 for f in feats if f['kind'] == k and not f['private']),
                                        'private': sum(1 for f in feats if f['kind'] == k and f['private'])}
                                    for k in sup['kinds']}
        return kinds, out

    def _osm_features(self, sup, ams, areas):
        """Non-city features (projected), fetched from OpenStreetMap; if it cannot be reached, the last build's copy
        (kept up to max_age_days) is used and the source says so; with neither, the city's own only."""
        from .supplements import osm
        key = 'osm'
        s = Source(id=f"{self.cfg['id']}.{key}", title=osm.SOURCE['title'], publisher='OpenStreetMap contributors',
                   url=osm.SOURCE['url'], api=osm.ENDPOINTS[0], licence=osm.SOURCE['licence'], coverage='whole city',
                   period='current map', unit='one mapped playground or park',
                   limitations=['Volunteer-mapped: coverage is uneven, and a missing feature means nobody has mapped it.',
                                'Only features not already in the city\'s inventory are added (matching rules in the method).'],
                   fetched_at=_now(), transformations=['matched against the city\'s own playgrounds and park sites; '
                                                       'duplicates and features outside every community left out'])
        self.sources[key] = s
        area_loc = geo.AreaLocator({c: self.proj.multipolygon(v['mp']) for c, v in areas.items()}, cell=1000.0)
        try:
            elements = self.client.overpass(sup['bbox']) if hasattr(self.client, 'overpass') else osm.fetch(sup['bbox'])
            res = osm.select(elements, self.proj, ams['playground']['xy'] if 'playground' in ams else [],
                             ams['park']['polys'] if 'park' in ams else [], area_loc,
                             tuple(sup.get('owner_words') or ()))
            s.rows = len(elements)
            s.sha256 = rows_hash([{'t': e.get('type'), 'i': e.get('id')} for e in elements])
            s.publisher_updated = self.today.isoformat()
            self.osm_result = {'stats': res['stats'], 'rules': res['rules'], 'reused': None}
            self._count_check('osm', len(elements))
            return res['features']
        except Exception as e:                              # noqa: BLE001
            prev = os.path.join(self.previous_dir or '', self.cfg['id'], 'osm_features.json')
            if self.previous_dir and os.path.exists(prev):
                with open(prev, encoding='utf-8') as f:
                    saved = json.load(f)
                age = (self.today - date.fromisoformat(saved['read_on'])).days
                if age <= sup.get('max_age_days', 30):
                    feats = [dict(ft, x=self.proj.xy(*ft['lonlat'])[0], y=self.proj.xy(*ft['lonlat'])[1],
                                  mp=[[self.proj.ring(r) for r in poly] for poly in ft['rings']] if ft.get('rings') else None)
                             for ft in saved['features']]
                    self.checks.append(quality.QualityCheck(s.id, 'read', 'warn',
                                                            f'OpenStreetMap unreachable ({e}); the copy read {saved["read_on"]} is used'))
                    s.publisher_updated = saved['read_on']
                    s.rows = saved.get('rows')
                    self.osm_result = {'stats': saved.get('stats'), 'rules': saved.get('rules'), 'reused': saved['read_on']}
                    return feats
            self.checks.append(quality.QualityCheck(s.id, 'read', 'warn',
                                                    f'OpenStreetMap unreachable ({e}) and no recent copy: city amenities only'))
            del self.sources[key]
            return None

    def crowding(self, homes, ams, distances, kinds):
        """Two-step floating catchment for amenities with a `crowding` section, under each people option.
        Averages are kept for communities and for wards ('ward:N')."""
        cfg = self.cfg
        units = np.asarray(homes['weight'], dtype=float)
        area = np.asarray(homes['area'], dtype=object)
        ward = np.asarray(homes.get('ward') or [None] * len(units), dtype=object)
        area_units = {}
        for a_, u in zip(homes['area'], homes['weight']):
            if a_:
                area_units[a_] = area_units.get(a_, 0) + u
        opts = self.people(area_units)
        if not opts:
            return None
        out = {'options': {k: {'label': v['label'], 'about': v['about']} for k, v in opts.items()},
               'default': cfg['people'].get('default'), 'kinds': {}}
        pair_cache = {}
        for key, a in kinds.items():
            cr = a.get('crowding')
            if not cr:
                continue
            am = ams[key]
            n = len(am['xy']) if a['geometry'] == 'point' else len(am['polys'])
            parts = am.get('parts') or [(0, n)]
            base_key = a.get('variant_of') or key
            pairs_by_d = []
            for d in a['thresholds_m']:
                js, is_ = [], []
                for lo, hi in parts:
                    if hi <= lo:
                        continue
                    ck = (base_key, lo, hi, d)
                    if ck not in pair_cache:
                        if a['geometry'] == 'point':
                            pair_cache[ck] = crowding.pairs_points(homes['xy'], am['xy'][lo:hi], d)
                        else:
                            polys = am['polys'][lo:hi]
                            inside_c = np.where(distances[key] == 0)[0]
                            pair_cache[ck] = crowding.pairs_polygons(
                                homes['xy'], polys, d,
                                inside=lambda k, x, y, polys=polys: geo.point_in_multipolygon(x, y, polys[k]),
                                inside_candidates=inside_c)
                    j, i = pair_cache[ck]
                    js.append(j + lo)
                    is_.append(i)
                pairs_by_d.append((np.concatenate(js) if js else np.zeros(0, dtype=np.int64),
                                   np.concatenate(is_) if is_ else np.zeros(0, dtype=np.int64)))
            res_k = {'people': cr['people'], 'unit': cr['unit'], 'short': cr.get('short', cr['unit']),
                     'per': cr.get('per', 1000), 'by_option': {}}
            for opt, o in opts.items():
                per_unit = {c: (v[cr['people']] / area_units[c]) for c, v in o['by_area'].items()
                            if area_units.get(c)}
                people = units * np.asarray([per_unit.get(c, 0.0) for c in area], dtype=float)
                vals = {}
                for di, d in enumerate(a['thresholds_m']):
                    r, demand = crowding.reach(pairs_by_d[di], people, am['supply'], len(units), cr.get('per', 1000))
                    avg = crowding.area_average(r, people, area)
                    if ward.any():
                        wavg = crowding.area_average(r, people, ward)
                        avg.update({k2: v for k2, v in wavg.items() if k2 != '_all'})
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
    kcfg = getattr(builder, 'kinds_expanded', None) or cfg['amenities']
    kinds = {k: {f: a.get(f) for f in ('label', 'plural', 'group', 'geometry', 'thresholds_m', 'threshold_basis',
                                       'threshold_url', 'limitations', 'variant_of', 'set')} for k, a in kcfg.items()}
    # each community's ward: the ward holding most of its homes
    comm_ward = {}
    if homes.get('ward'):
        tally = {}
        for a_, w_, u_ in zip(homes['area'], homes['ward'], homes['weight']):
            if a_ and w_:
                tally.setdefault(a_, {}).setdefault(w_, 0)
                tally[a_][w_] += u_
        comm_ward = {a_: int(max(t.items(), key=lambda kv: kv[1])[0].split(':')[1]) for a_, t in tally.items()}
    # areas with homes, in name order
    table = {}
    for code in sorted(res['areas'], key=lambda c: (areas.get(c) or {}).get('name', c)):
        a = areas.get(code) or {'name': code, 'attrs': {}}
        any_k = next(iter(res['areas'][code].values()))
        table[code] = {'name': a['name'], 'attrs': a.get('attrs', {}), 'units': any_k['units'],
                       'records': any_k['records'], 'units_new': any_k['units_new'],
                       'units_recent': any_k['units_recent'], 'access': res['areas'][code],
                       'ward': comm_ward.get(code)}
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
        'scores': res.get('scores'),
        'wards': ({str(int(w.split(':')[1])): {**(res.get('ward_info') or {}).get(int(w.split(':')[1]), {}),
                                               'units': next(iter(v.values()))['units'],
                                               'units_new': next(iter(v.values()))['units_new'], 'access': v}
                   for w, v in sorted((res.get('wards') or {}).items(), key=lambda kv: int(kv[0].split(':')[1]))}
                  if res.get('wards') else None),
        'osm': getattr(builder, 'osm_result', None),
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
        fts = [dict(ft, properties=dict(ft.get('properties') or {}, source='city')) for ft in v['features']]
        for o in v.get('osm_features') or []:
            if o.get('mp'):
                simp = geo.simplify_multipolygon(o['mp'], 8, digits=1)
                geom = {'type': 'MultiPolygon', 'coordinates': [[[[round(c, 6) for c in builder.proj.lonlat(x, y)]
                                                                  for x, y in ring] for ring in poly] for poly in simp]}
            else:
                geom = {'type': 'Point', 'coordinates': [round(c, 6) for c in builder.proj.lonlat(o['x'], o['y'])]}
            fts.append({'type': 'Feature', 'geometry': geom,
                        'properties': {'id': o['osm'], 'name': o['name'], 'source': 'osm', 'private': o['private']}})
        with open(os.path.join(d, 'amenities', f'{k.replace("|", "-")}.geojson'), 'w', encoding='utf-8') as f:
            json.dump(_feature_collection(fts), f, separators=(',', ':'))
    if getattr(builder, 'wards_data', None):
        wf = []
        for w, v in builder.wards_data.items():
            simp = geo.simplify_multipolygon(builder.proj.multipolygon(v['mp']), 20, digits=1)
            wf.append({'type': 'Feature', 'properties': {'ward': w, 'name': v['name'], 'councillor': v.get('councillor')},
                       'geometry': {'type': 'MultiPolygon', 'coordinates': [[[[round(c, 5) for c in builder.proj.lonlat(x, y)]
                                                                              for x, y in ring] for ring in poly] for poly in simp]}})
        with open(os.path.join(d, 'wards.geojson'), 'w', encoding='utf-8') as f:
            json.dump(_feature_collection(wf), f, separators=(',', ':'))
    osm_all = []
    for k, v in ams.items():
        if k.endswith('|private'):
            for o in v.get('osm_features') or []:
                osm_all.append({'kind': o['kind'], 'private': o['private'], 'ha': o['ha'], 'name': o['name'], 'osm': o['osm'],
                                'area': o['area'], 'lonlat': list(builder.proj.lonlat(o['x'], o['y'])),
                                'rings': [[[list(builder.proj.lonlat(x, y)) for x, y in ring] for ring in poly]
                                          for poly in o['mp']] if o.get('mp') else None})
    if osm_all:
        o_r = getattr(builder, 'osm_result', None) or {}
        with open(os.path.join(d, 'osm_features.json'), 'w', encoding='utf-8') as f:
            json.dump({'read_on': o_r.get('reused') or builder.today.isoformat(), 'stats': o_r.get('stats'),
                       'rules': o_r.get('rules'), 'features': osm_all}, f, separators=(',', ':'))
    # the table for spreadsheets
    with open(os.path.join(d, 'access_by_area.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['code', 'name', 'amenity', 'units', 'units_built_since_' + str(cfg['growth_year']),
                    'share_within_primary', 'primary_m', 'share_within_secondary', 'secondary_m',
                    'share_new_within_primary', 'share_older_within_primary', 'median_m', 'status'])
        for code, r in table.items():
            for k, st in r['access'].items():
                th = kcfg[k]['thresholds_m']
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
    b = Builder(cfg, client=client, today=today, previous=previous_counts(previous_dir, city_id), previous_dir=previous_dir)
    areas, homes, ams, res = b.run()
    d = write(b, areas, homes, ams, res, out_dir)
    write_linked(cfg, d, previous_dir)
    return d


def write_linked(cfg, d, previous_dir=None, fetch=None):
    """dashboard.json from the linked source; if it cannot be read, the last build's copy is kept (and marked)."""
    lc = cfg.get('linked_dashboard')
    if not lc:
        return None
    from . import linked
    path = os.path.join(d, 'dashboard.json')
    try:
        data = linked.build(lc, **({'fetch': fetch} if fetch else {}))
        data['read_at'] = _now()
        data['stale'] = False
    except Exception as e:                                  # noqa: BLE001
        prev = os.path.join(previous_dir or '', cfg['id'], 'dashboard.json')
        if not (previous_dir and os.path.exists(prev)):
            print(f'linked dashboard not available: {e}')
            return None
        with open(prev, encoding='utf-8') as f:
            data = json.load(f)
        data['stale'] = True
        data['stale_reason'] = str(e)[:200]
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, separators=(',', ':'))
    return path
