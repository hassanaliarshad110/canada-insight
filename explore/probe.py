import json, urllib.parse, urllib.request
B = 'https://data.edmonton.ca'
def get(path, **q):
    url = B + path + ('?' + urllib.parse.urlencode(q) if q else '')
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'canada-insight/0.5'}), timeout=300) as r:
        return json.loads(r.read().decode('utf-8'))
def show(label, path, **q):
    try:
        print('##', label); print(json.dumps(get(path, **q))[:3000])
    except Exception as e:
        print('##', label, 'ERROR', str(e)[:200])
show('age values', '/resource/wpfd-8bii.json', **{'$select': 'age_range, gender, count(*) as n, sum(value) as v', '$group': 'age_range, gender', '$order': 'age_range', '$limit': '200'})
show('census total', '/resource/eg3i-f4bj.json', **{'$select': 'sum(total_population) as p, count(*) as n'})
show('parks meta', '/api/views/gdd9-eqv9.json')
show('parks sample', '/resource/gdd9-eqv9.json', **{'$limit': '1'})
show('parks count', '/resource/gdd9-eqv9.json', **{'$select': 'count(*) as n'})
show('rec types', '/resource/nz3t-vyg3.json', **{'$select': 'facility_type, count(*) as n', '$group': 'facility_type', '$limit': '60'})
show('rec centres', '/resource/nz3t-vyg3.json', **{'$select': 'facility_name, facility_type', '$where': "facility_type in('Recreation Centre','Leisure Centre','Multi-purpose Recreation Centre')", '$limit': '60'})
show('year built residential', '/resource/dkk9-cj3x.json', **{'$select': 'count(*) as n, count(year_built) as with_year, min(year_built) as mn, max(year_built) as mx'})
show('built since 2021', '/resource/dkk9-cj3x.json', **{'$select': 'count(*) as n', '$where': 'year_built >= 2021'})
show('residential with suite', '/resource/q7d6-ambg.json', **{'$select': 'count(*) as n', '$where': "tax_class='Residential' AND suite IS NOT NULL"})
show('residential low value', '/resource/q7d6-ambg.json', **{'$select': 'count(*) as n', '$where': "tax_class='Residential' AND assessed_value < 40000"})
show('residential no year', '/resource/q7d6-ambg.json', **{'$select': 'count(*) as n', '$where': "tax_class='Residential'"})
show('neighbourhood ids', '/resource/65fr-66s6.json', **{'$select': 'neighbourhood_number, name, district', '$limit': '3'})
show('other residential sample', '/resource/q7d6-ambg.json', **{'$where': "tax_class='Other Residential'", '$limit': '3'})
show('permits units since 2021', '/resource/24uj-dj8v.json', **{'$select': 'year, sum(units_added) as u', '$group': 'year', '$where': 'year >= 2018', '$order': 'year'})
show('311 recent', '/resource/q7ua-agfg.json', **{'$select': 'year, count(*) as n', '$group': 'year', '$where': 'year >= 2023', '$order': 'year'})
