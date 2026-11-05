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
# join check: other residential accounts in property information (gross area, year)
acc = [r['account_number'] for r in get('/resource/q7d6-ambg.json', **{'$select': 'account_number', '$where': "tax_class='Other Residential'", '$limit': '8'})]
show('other residential info', '/resource/dkk9-cj3x.json', **{'$select': 'account_number, total_gross_area, year_built, zoning, lot_size', '$where': 'account_number in(' + ','.join(f"'{a}'" for a in acc) + ')'})
show('low value residential sample', '/resource/q7d6-ambg.json', **{'$select': 'account_number, suite, house_number, street_name, assessed_value', '$where': "tax_class='Residential' AND assessed_value < 40000", '$limit': '8'})
acc2 = [r['account_number'] for r in get('/resource/q7d6-ambg.json', **{'$select': 'account_number', '$where': "tax_class='Residential' AND assessed_value < 40000", '$limit': '8'})]
show('low value info', '/resource/dkk9-cj3x.json', **{'$select': 'account_number, total_gross_area, year_built, zoning', '$where': 'account_number in(' + ','.join(f"'{a}'" for a in acc2) + ')'})
show('value bands', '/resource/q7d6-ambg.json', **{'$select': "case(assessed_value < 20000, 'a <20k', assessed_value < 40000, 'b 20-40k', assessed_value < 80000, 'c 40-80k', true, 'd 80k+') as band, count(*) as n", '$where': "tax_class='Residential'", '$group': 'band', '$order': 'band'})
show('other residential gross area sum', '/resource/dkk9-cj3x.json', **{'$select': 'count(*) as n', '$where': "total_gross_area IS NOT NULL AND total_gross_area != '0'"})
show('neighbourhood code types', '/resource/q7d6-ambg.json', **{'$select': 'neighbourhood_id', '$limit': '3'})
show('ward names', '/resource/b4er-5rp2.json', **{'$select': 'name_1, name_2, councillor'})
show('dk ward vs nbhd', '/resource/65fr-66s6.json', **{'$select': 'count(*) as n, count(geometry_multipolygon) as g', '$where': 'effective_end_date IS NULL'})
show('parks classes', '/resource/gdd9-eqv9.json', **{'$select': 'class, status, count(*) as n, sum(area) as a', '$group': 'class, status', '$order': 'n DESC', '$limit': '40'})
