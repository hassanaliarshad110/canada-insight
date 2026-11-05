"""Describe chosen Edmonton datasets in detail (columns, rows, a sample, value counts for key fields)."""
import json
import urllib.parse
import urllib.request

B = 'https://data.edmonton.ca'


def get(path, **q):
    url = B + path + ('?' + urllib.parse.urlencode(q) if q else '')
    req = urllib.request.Request(url, headers={'User-Agent': 'canada-insight/0.5'})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode('utf-8'))


IDS = ['65fr-66s6', 'b4er-5rp2', 'q7d6-ambg', 'dkk9-cj3x', 'dm3i-bp8w', '9nqb-w48x', 'gdd9-eqv9', '4vt2-8zrq', 'fhxi-cnhe',
       'kaps-rk7z', 'nz3t-vyg3', 'jn25-zspi', 'eg3i-f4bj', 'wpfd-8bii', '5bk4-5txu', 'q7ua-agfg', '24uj-dj8v', 'a6zx-dzqn',
       'jyra-si4k']
GROUPS = {'q7d6-ambg': ['mill_class_1', 'assessment_class_1', 'tax_class', 'garage', 'ward'],
          'dkk9-cj3x': ['building_type', 'zoning', 'legal_description'],
          '9nqb-w48x': ['type', 'surface', 'status'], 'gdd9-eqv9': ['type', 'class', 'status'],
          'nz3t-vyg3': ['type', 'facility_type', 'category'], 'kaps-rk7z': ['status']}
out = {}
for i in IDS:
    try:
        m = get(f'/api/views/{i}.json')
        n = get(f'/resource/{i}.json', **{'$select': 'count(*) as n'})
        s = get(f'/resource/{i}.json', **{'$limit': '2'})
        cols = [(c['fieldName'], c['dataTypeName']) for c in m.get('columns', [])]
        rec = {'name': m.get('name'), 'rows': n[0].get('n') if n else None, 'updated': m.get('rowsUpdatedAt'),
               'columns': cols, 'sample': [{k: str(v)[:100] for k, v in r.items()} for r in s]}
        for f in GROUPS.get(i, []):
            if f in [c for c, _ in cols]:
                try:
                    rec.setdefault('values', {})[f] = get(f'/resource/{i}.json', **{'$select': f'{f}, count(*) as n', '$group': f,
                                                                                  '$order': 'n DESC', '$limit': '25'})
                except Exception as e:                       # noqa: BLE001
                    rec.setdefault('values', {})[f] = str(e)[:100]
        out[i] = rec
    except Exception as e:                                   # noqa: BLE001
        out[i] = {'error': str(e)[:300]}
json.dump(out, open('explore/probe.json', 'w'), indent=1)
for i, r in out.items():
    print('==', i, r.get('name'), 'rows', r.get('rows'), r.get('error', ''))
    for c, t in r.get('columns', []):
        print('   ', c, t)
    for s in r.get('sample', [])[:1]:
        print('   sample:', s)
    for f, v in (r.get('values') or {}).items():
        print('   values', f, v)
