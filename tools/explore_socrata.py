"""Survey a Socrata open data portal for a new city: search the catalogue for each topic, then describe the best
matches (columns, rows, last update, geometry). Output: explore/<domain>.json and a readable .md.

    python tools/explore_socrata.py data.edmonton.ca
"""
import json
import os
import sys
import urllib.parse
import urllib.request

TOPICS = {
    'neighbourhoods': ['neighbourhood boundaries', 'neighbourhoods'],
    'wards': ['ward boundaries', 'wards 2021'],
    'property': ['property assessment current', 'property assessment', 'property information'],
    'playgrounds': ['playground', 'playgrounds'],
    'parks': ['parks', 'park land', 'parkland'],
    'transit_stops': ['bus stops', 'transit stops', 'ets stops'],
    'community_halls': ['community league', 'community halls', 'community centres'],
    'recreation': ['recreation facilities', 'recreation centres', 'leisure centres'],
    'libraries': ['library branches', 'libraries', 'public library'],
    'population': ['population by neighbourhood', 'census neighbourhood population', 'federal census 2021 neighbourhood',
                   'municipal census population age'],
    '311': ['311 service requests', '311 requests'],
    'crime': ['crime', 'neighbourhood criminal occurrences', 'police occurrences'],
    'permits': ['building permits', 'development permits'],
    'traffic': ['traffic collisions', 'collisions'],
    'schools': ['schools'],
    'child_care': ['child care', 'daycare'],
    'budget': ['budget', 'capital budget', 'operating budget'],
}


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'canada-insight/0.5 (city readiness survey)'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode('utf-8'))


def main(domain):
    base = f'https://{domain}'
    out = {'domain': domain, 'topics': {}}
    seen = {}
    for topic, queries in TOPICS.items():
        hits = []
        for q in queries:
            try:
                d = get(f'{base}/api/catalog/v1?' + urllib.parse.urlencode(
                    {'domains': domain, 'search_context': domain, 'q': q, 'limit': 8, 'only': 'dataset,map'}))
            except Exception as e:                                   # noqa: BLE001
                hits.append({'error': str(e), 'q': q})
                continue
            for x in d.get('results', []):
                r = x['resource']
                if r['id'] in {h.get('id') for h in hits}:
                    continue
                hits.append({'id': r['id'], 'name': r['name'], 'type': r.get('type'),
                             'updated': (r.get('data_updated_at') or r.get('updatedAt') or '')[:10],
                             'description': (r.get('description') or '')[:300], 'q': q})
        out['topics'][topic] = hits[:12]
        for h in hits[:6]:
            if 'id' in h and h['id'] not in seen:
                try:
                    m = get(f'{base}/api/views/{h["id"]}.json')
                    cnt = get(f'{base}/resource/{h["id"]}.json?$select=count(*) as n')
                    sample = get(f'{base}/resource/{h["id"]}.json?$limit=1')
                    seen[h['id']] = {
                        'name': m.get('name'), 'rows': cnt[0].get('n') if cnt else None,
                        'updated': m.get('rowsUpdatedAt'),
                        'columns': [(c['fieldName'], c['dataTypeName']) for c in m.get('columns', [])][:60],
                        'sample': {k: (str(v)[:120]) for k, v in (sample[0] if sample else {}).items()},
                    }
                except Exception as e:                               # noqa: BLE001
                    seen[h['id']] = {'error': str(e)[:200]}
    out['datasets'] = seen
    os.makedirs('explore', exist_ok=True)
    with open(f'explore/{domain}.json', 'w') as f:
        json.dump(out, f, indent=1)
    lines = [f'# {domain}\n']
    for t, hits in out['topics'].items():
        lines.append(f'\n## {t}\n')
        for h in hits:
            if 'id' not in h:
                lines.append(f'- error ({h["q"]}): {h["error"]}')
                continue
            ds = seen.get(h['id'], {})
            lines.append(f"- `{h['id']}` {h['name']} ({h['type']}, updated {h['updated']}, rows {ds.get('rows')})")
            if ds.get('columns'):
                lines.append('  - columns: ' + ', '.join(f'{a}:{b}' for a, b in ds['columns']))
    with open(f'explore/{domain}.md', 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main(sys.argv[1])
