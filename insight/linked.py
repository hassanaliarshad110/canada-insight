"""City dashboard figures from a linked source: for Calgary, Calgary Data Desk's own daily build.

Why: Calgary Data Desk already works out 311, safety, growth, development, families, transit and tax figures for the
whole city and every ward, every morning. Reading its published build means both sites always show the same numbers.
Modules are rebuilt inside Canada Insight one at a time (with the audit's fixes, applied to both sites together);
until then, this is where those figures come from, and the dashboard says so.

Left out on purpose: the old boundary-count amenity figures (amenity level, playgrounds per 1,000 children by
boundary, facilities per 10,000), replaced by Canada Insight's access, crowding and score measures.
"""
import json
import urllib.request

DROP_KEYS = ('amenity_level', 'playgrounds_per_1000_kids', 'facilities_per_10000', 'stops_per_1000',
             'amenity_level_all', 'amenity_level_all_private', 'facilities', 'playgrounds', 'stops')


def _get(url, timeout=300):
    req = urllib.request.Request(url, headers={'User-Agent': 'canada-insight/0.4'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def _scalars(d, depth=0):
    """Numbers, short strings and booleans from a dict, nested one level (lists and long text left out)."""
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, bool) or isinstance(v, (int, float)) or v is None:
            out[k] = v
        elif isinstance(v, str) and len(v) <= 200:
            out[k] = v
        elif isinstance(v, dict) and depth == 0:
            sub = _scalars(v, 1)
            if sub:
                out[k] = sub
    return out


def _clean_row(r):
    return {k: v for k, v in (r or {}).items() if k not in DROP_KEYS}


def build(cfg, fetch=_get):
    """The compact dashboard file. cfg: the city config's `linked_dashboard` section."""
    base = cfg['base_url'].rstrip('/') + '/'
    out = {'source': {'title': cfg['title'], 'publisher': cfg['publisher'], 'url': cfg['page']},
           'methods': {}, 'default_method': cfg['default_method']}
    for m, label in cfg['methods'].items():
        d = fetch(f'{base}data/{m}/w0.json')
        ws = d.get('wards_summary') or {}
        pop = d.get('population') or {}
        out['methods'][m] = {
            'label': label,
            'about': pop.get('method_about'),
            'built_at': d.get('built_at'),
            'period': d.get('period'), 'prev_period': d.get('prev_period'),
            'crime_period': ws.get('crime_period'),
            'note': ws.get('note'),
            'city': _clean_row(ws.get('city')),
            'wards': [_clean_row(r) for r in ws.get('wards') or []],
            'population': {k: pop.get(k) for k in ('as_of', 'model_total', 'census_total', 'city_now', 'growth_model_city',
                                                   'census_city', 'homes_now', 'homes_census', 'method_label')},
            'summary': _scalars(d.get('summary')),
        }
    for name in ('tax', 'budget'):
        try:
            t = fetch(f'{base}data/{name}.json')
        except Exception:                                   # noqa: BLE001 - optional parts
            continue
        if name == 'tax':
            out['tax'] = {**_scalars({k: v for k, v in t.items() if k not in ('by_comm', 'by_ward', 'wards')}),
                          'by_ward': t.get('by_ward')}
        else:
            out['budget'] = {'years': t.get('years'), 'totals': t.get('totals'), 'unit': t.get('unit'),
                             'note': t.get('note'), 'page': t.get('budget_page')}
    return out
