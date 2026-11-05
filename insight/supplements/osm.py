"""Amenities that are not the city's own, from OpenStreetMap, with every one the city already lists taken out.

Why: a city's open data lists what the city owns. Developer-held parks and playgrounds in new communities, school
playgrounds, and condominium and homeowners' association parks are missing, so new and dense areas look emptier
than they are. OpenStreetMap (© OpenStreetMap contributors, Open Database Licence) fills part of that gap; its
coverage is uneven (a missing feature means nobody has mapped it).

These rules are the same as Calgary Data Desk's (osm.py there), so both sites count the same things:

A feature is the city's own (and not added) when:
  playground   a city playground within 80 m of its middle, or inside its outline
  park         30% or more of its area inside the city's park sites
  any kind     tagged as operated or owned by the city
The same thing mapped twice in OpenStreetMap counts once: a playground within 25 m of, or inside the outline of, one
already counted; a park with 30% or more of its area inside one already counted (outlines before points, larger parks
before smaller ones).
Left out: access=no or customers, fee=yes, indoor ones; parks under 0.05 ha (bits of lawn) or over 20 ha (natural
areas, not neighbourhood parks); features outside every community.
Private ones (access=private: homeowners' association, condominium, residents only) are kept apart and counted only
when the reader includes them.
"""
import json
import time
import urllib.parse
import urllib.request

from .. import geo

ENDPOINTS = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter']
MATCH_M = {'playground': 80}
SAME_M = 25
PARK_OVERLAP = 0.30
PARK_MIN_HA, PARK_MAX_HA = 0.05, 20.0
SOURCE = {'title': 'OpenStreetMap (Overpass API)', 'licence': '© OpenStreetMap contributors, Open Database Licence (ODbL)',
          'url': 'https://www.openstreetmap.org/copyright'}
RULES = {'match_m': MATCH_M, 'same_m': SAME_M, 'park_overlap': PARK_OVERLAP, 'park_min_ha': PARK_MIN_HA,
         'park_max_ha': PARK_MAX_HA}


def query_text(bbox):
    b = ','.join(str(x) for x in bbox)
    return (f'[out:json][timeout:180];(nwr["leisure"="playground"]({b});'
            f'way["leisure"="park"]({b});relation["leisure"="park"]({b}););out tags geom;')


def fetch(bbox, timeout=200, wait=20):
    body = urllib.parse.urlencode({'data': query_text(bbox)}).encode()
    last = None
    for url in ENDPOINTS:
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, data=body, headers={'User-Agent': 'canada-insight/0.3 (civic open data)'})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read().decode('utf-8'))['elements']
            except Exception as e:                    # noqa: BLE001 - busy or down: wait, then the other server
                last = e
                time.sleep(wait if attempt == 0 else 2)
    raise RuntimeError(f'OpenStreetMap could not be reached ({last})')


def _rings(el, role='outer'):
    """Closed rings [[lon, lat], ...] of a way or a multipolygon relation (outer ways joined end to end, or holes)."""
    if el.get('type') == 'way':
        g = [[p['lon'], p['lat']] for p in el.get('geometry') or []]
        return [g] if role == 'outer' and len(g) >= 4 and g[0] == g[-1] else []
    if el.get('type') != 'relation':
        return []
    roles = ('outer', '') if role == 'outer' else ('inner',)
    parts = [[[p['lon'], p['lat']] for p in m.get('geometry') or []] for m in el.get('members') or []
             if m.get('type') == 'way' and m.get('role', 'outer') in roles and m.get('geometry')]
    rings = []
    while parts:
        ring = parts.pop(0)
        grew = True
        while ring[0] != ring[-1] and grew:
            grew = False
            for i, p in enumerate(parts):
                if p[0] == ring[-1]:
                    ring += p[1:]
                elif p[-1] == ring[-1]:
                    ring += p[::-1][1:]
                else:
                    continue
                parts.pop(i)
                grew = True
                break
        if len(ring) >= 4 and ring[0] == ring[-1]:
            rings.append(ring)
    return rings


def kind_of(tags):
    l = tags.get('leisure')
    return 'playground' if l == 'playground' else 'park' if l == 'park' else None


def open_to_all(tags):
    return ((tags.get('access') or '') not in ('no', 'customers') and (tags.get('fee') or '') != 'yes'
            and (tags.get('indoor') or 'no') == 'no')


def private(tags):
    return (tags.get('access') or '').strip().lower() == 'private'


def citys(tags, owner_words):
    who = ' '.join(str(tags.get(k) or '') for k in ('operator', 'owner', 'operator:type', 'ownership')).lower()
    return any(w in who for w in owner_words)


def _share_inside(mp_xy, locator, samples=16):
    """Share of a projected outline's area inside any polygon of `locator` (by a grid of test points)."""
    x0, y0, x1, y1 = geo.bbox(mp_xy)
    inside = hit = 0
    for i in range(samples):
        for j in range(samples):
            x, y = x0 + (i + 0.5) * (x1 - x0) / samples, y0 + (j + 0.5) * (y1 - y0) / samples
            if geo.point_in_multipolygon(x, y, mp_xy):
                inside += 1
                hit += locator.find(x, y) is not None
    return hit / inside if inside else 0.0


def select(elements, proj, city_playgrounds_xy, city_parks_xy, area_locator, owner_words=('city of calgary', 'calgary parks')):
    """Non-city amenities to add. Inputs are projected (metres). Returns
    {'features': [{'kind', 'x', 'y', 'mp' (parks), 'ha' (parks), 'private', 'name', 'osm', 'area'}], 'stats': {...}}."""
    play_idx = geo.PointIndex(city_playgrounds_xy, cell=100)
    parks_loc = geo.AreaLocator({i: p for i, p in enumerate(city_parks_xy)}, cell=500) if city_parks_xy else None
    stats = {k: {'found': 0, 'city': 0, 'left_out': 0, 'twice': 0, 'public': 0, 'private': 0} for k in ('playground', 'park')}

    def order(el):
        g = el.get('geometry') or []
        span = ((max(p['lon'] for p in g) - min(p['lon'] for p in g)) * (max(p['lat'] for p in g) - min(p['lat'] for p in g))
                if g else 0)
        return (el.get('type') == 'node', -span)

    kept_pts = {'playground': geo.PointIndex([], cell=100)}
    kept_outlines = {'playground': [], 'park': []}
    out, seen = [], set()
    for el in sorted(elements, key=order):
        tags = el.get('tags') or {}
        k = kind_of(tags)
        key = (el.get('type'), el.get('id'))
        if not k or key in seen:
            continue
        seen.add(key)
        st = stats[k]
        st['found'] += 1
        rings = _rings(el) if el.get('type') != 'node' else []
        mp_xy = [[proj.ring(r)] for r in rings] if rings else None
        if el.get('type') == 'node':
            x, y = proj.xy(el['lon'], el['lat'])
        elif mp_xy:
            x, y = geo.centroid(mp_xy[0][0])
        else:
            g = el.get('geometry') or []
            if not g:
                st['left_out'] += 1
                continue
            x, y = proj.xy(sum(p['lon'] for p in g) / len(g), sum(p['lat'] for p in g) / len(g))
        if not open_to_all(tags):
            st['left_out'] += 1
            continue
        ha = None
        if k == 'park':
            if not mp_xy:
                st['left_out'] += 1
                continue
            holes = [[proj.ring(r)] for r in _rings(el, 'inner')]
            ha = max(0.0, geo.area(mp_xy) - (geo.area(holes) if holes else 0)) / 10_000
            if not (PARK_MIN_HA <= ha <= PARK_MAX_HA):
                st['left_out'] += 1
                continue
        if citys(tags, owner_words):
            is_city = True
        elif k == 'playground':
            is_city = (play_idx.nearest(x, y, MATCH_M['playground']) is not None or
                       bool(mp_xy and any(geo.point_in_multipolygon(px, py, mp_xy) for px, py in _pts_in_box(play_idx, mp_xy))))
        else:
            is_city = bool(parks_loc and _share_inside(mp_xy, parks_loc) >= PARK_OVERLAP)
        if is_city:
            st['city'] += 1
            continue
        if any(geo.point_in_multipolygon(x, y, o) for o in kept_outlines[k] if _in_box(x, y, o)):
            st['twice'] += 1
            continue
        if k == 'playground' and kept_pts['playground'].nearest(x, y, SAME_M) is not None:
            st['twice'] += 1
            continue
        if k == 'park' and kept_outlines['park']:
            near = [o for o in kept_outlines['park'] if _boxes_touch(o, mp_xy)]
            if near and _share_inside(mp_xy, geo.AreaLocator({i: o for i, o in enumerate(near)}, cell=500)) >= PARK_OVERLAP:
                st['twice'] += 1
                continue
        area = area_locator.find(x, y)
        if not area:
            st['left_out'] += 1
            continue
        priv = private(tags)
        st['private' if priv else 'public'] += 1
        if k == 'playground':
            kept_pts['playground'].add(x, y)
        if mp_xy:
            kept_outlines[k].append(mp_xy)
        out.append({'kind': k, 'x': x, 'y': y, 'mp': mp_xy if k == 'park' else None, 'ha': None if ha is None else round(ha, 3),
                    'private': priv, 'name': tags.get('name') or '', 'osm': f'{key[0]}/{key[1]}', 'area': area})
    return {'features': out, 'stats': stats, 'rules': RULES, 'source': SOURCE}


def _pts_in_box(idx, mp):
    x0, y0, x1, y1 = geo.bbox(mp)
    for i in range(int(x0 // idx.cell), int(x1 // idx.cell) + 1):
        for j in range(int(y0 // idx.cell), int(y1 // idx.cell) + 1):
            for p in idx.grid.get((i, j), ()):
                if x0 <= p[0] <= x1 and y0 <= p[1] <= y1:
                    yield p


def _in_box(x, y, mp):
    x0, y0, x1, y1 = geo.bbox(mp)
    return x0 <= x <= x1 and y0 <= y <= y1


def _boxes_touch(a, b):
    ax0, ay0, ax1, ay1 = geo.bbox(a)
    bx0, by0, bx1, by1 = geo.bbox(b)
    return not (ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0)
