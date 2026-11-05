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



show('households characteristics', '/resource/xgkv-ii9t.json', **{'$select': 'question_type, characteristic, sum(value) as v, count(*) as n', '$group': 'question_type, characteristic', '$order': 'question_type, characteristic', '$limit': '100'})
show('2019 dwelling status citywide', '/resource/7uuj-bhr2.json')
rows = get('/resource/xgkv-ii9t.json', **{'$limit': '50000'})
print('## households by neighbourhood (all rows, compact)')
print(json.dumps([[r.get('neighbourhood_number'), r.get('question_type'), r.get('characteristic'), r.get('value')] for r in rows]))
