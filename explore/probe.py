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

cur = {str(int(float(r['neighbourhood_number']))): r['descriptive_name'] for r in get('/resource/65fr-66s6.json', **{'$select': 'neighbourhood_number, descriptive_name', '$limit': '1000'})}
cen = get('/resource/eg3i-f4bj.json', **{'$select': 'neighbourhood_number, neighbourhood, total_population', '$limit': '1000'})
missing = [(r['neighbourhood_number'], r['neighbourhood'], r['total_population']) for r in cen if str(int(float(r['neighbourhood_number']))) not in cur]
print('## census codes not current', json.dumps(sorted(missing, key=lambda x: -float(x[2] or 0))))
old = get('/resource/5bk4-5txu.json', **{'$select': 'neighbourh, name', '$limit': '1000'})
oldc = {str(int(float(r['neighbourh']))): r['name'] for r in old}
print('## current codes not in 2021 boundaries', json.dumps([(c, n) for c, n in cur.items() if c not in oldc]))
print('## 2021 codes not current', json.dumps([(c, n) for c, n in oldc.items() if c not in cur]))
show('homes no nbhd by class', '/resource/q7d6-ambg.json', **{'$select': 'tax_class, ward, count(*) as n', '$where': "neighbourhood_id IS NULL AND tax_class in('Residential','Other Residential') AND assessed_value >= 40000", '$group': 'tax_class, ward', '$order': 'n DESC', '$limit': '30'})
show('homes no nbhd sample', '/resource/q7d6-ambg.json', **{'$select': 'account_number, suite, house_number, street_name, neighbourhood, ward, latitude, longitude', '$where': "neighbourhood_id IS NULL AND tax_class='Residential' AND assessed_value >= 40000", '$limit': '10'})
