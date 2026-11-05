import json, urllib.parse, urllib.request
B = 'https://data.edmonton.ca'
def get(path, **q):
    url = B + path + ('?' + urllib.parse.urlencode(q) if q else '')
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'canada-insight/0.5'}), timeout=300) as r:
        return json.loads(r.read().decode('utf-8'))
def show(label, path, **q):
    try:
        print('##', label); print(json.dumps(get(path, **q))[:2500])
    except Exception as e:
        print('##', label, 'ERROR', str(e)[:200])


import urllib.request as U
def cat(q):
    url = 'https://api.us.socrata.com/api/catalog/v1?' + urllib.parse.urlencode({'domains': 'data.edmonton.ca', 'q': q, 'limit': 20})
    with U.urlopen(U.Request(url, headers={'User-Agent': 'canada-insight/0.5'}), timeout=120) as r:
        d = json.loads(r.read().decode())
    print('## catalogue', q)
    for x in d['results']:
        print(x['resource']['id'], '|', x['resource']['name'], '|', x['resource'].get('columns_field_name', [])[:15])
for q in ['2021 federal census dwelling', 'census structure type', 'census household', 'dwelling unit']:
    try: cat(q)
    except Exception as e: print('##', q, 'ERROR', e)
