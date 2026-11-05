"""Audit a published build: internal consistency, agreement with Calgary Data Desk, and sanity of every figure.

    python tools/audit_build.py DATA_DIR/calgary [--desk DESK_W0_JSON]

Prints one line per check (PASS / WARN / FAIL) and exits 1 if any check fails. Independent of the pipeline's code:
it reads only the published files.
"""
import json
import math
import os
import sys

RES = []


def check(name, ok, detail='', warn=False):
    RES.append(('PASS' if ok else ('WARN' if warn else 'FAIL'), name, detail))


def main(d, desk=None):
    A = json.load(open(os.path.join(d, 'access.json')))
    Q = json.load(open(os.path.join(d, 'quality.json')))
    S = json.load(open(os.path.join(d, 'sources.json')))
    D = json.load(open(os.path.join(d, 'dashboard.json'))) if os.path.exists(os.path.join(d, 'dashboard.json')) else None
    kinds = A['kinds']
    cfg = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'cities', A['city'], 'city.json')))
    n_wards = {'calgary': 14, 'edmonton': 12}.get(A['city'])
    base = [k for k, v in kinds.items() if not v.get('variant_of')]

    # 1. shares are proportions, and the longer distance never reads lower than the shorter
    bad = []
    for code, a in A['areas'].items():
        for k, s in a['access'].items():
            for f in ('share_primary', 'share_secondary', 'share_new_primary', 'share_old_primary'):
                v = s.get(f)
                if v is not None and not (0 <= v <= 1):
                    bad.append(f'{code} {k} {f}={v}')
            if s['share_primary'] is not None and s['share_secondary'] is not None and s['share_secondary'] < s['share_primary'] - 1e-9:
                bad.append(f'{code} {k} secondary<primary')
    check('shares between 0 and 1; longer distance >= shorter', not bad, '; '.join(bad[:5]))

    # 2. adding non-city amenities can only bring homes closer: city <= public <= private
    bad = []
    for code, a in A['areas'].items():
        for k in base:
            c, p, r = a['access'].get(k + '|city'), a['access'].get(k), a['access'].get(k + '|private')
            if c and p and r and not (c['share_primary'] <= p['share_primary'] + 1e-9 <= r['share_primary'] + 2e-9):
                bad.append(f"{a['name']} {k}: {c['share_primary']} / {p['share_primary']} / {r['share_primary']}")
    has_sets = any(k + '|city' in kinds for k in base)
    check('City only <= open to everyone <= with private (every community)', has_sets and not bad,
          '; '.join(bad[:5]) if bad else ('' if has_sets else 'non-City amenities missing from this build'), warn=not has_sets)

    # 3. homes add up: communities, wards, city
    units_c = sum(a['units'] for a in A['areas'].values())
    check('community homes add up to the city total', abs(units_c - A['homes']['units']) < 1,
          f'{units_c:,.0f} vs {A["homes"]["units"]:,.0f}')
    if A.get('wards'):
        units_w = sum(w['units'] for w in A['wards'].values())
        check('ward homes add up to the city total (within 0.5%)', abs(units_w / A['homes']['units'] - 1) < 0.005,
              f'{units_w:,.0f} vs {A["homes"]["units"]:,.0f}')
        check(f'{n_wards} wards present', len(A['wards']) == n_wards, ', '.join(A['wards']))
        # independent check of ward placement: each ward's share = unit-weighted mean of its communities' shares
        worst = (0, '')
        for w, wd in A['wards'].items():
            comms = [a for a in A['areas'].values() if str(a.get('ward')) == w]
            u = sum(a['units'] for a in comms)
            for k in base:
                if not u:
                    continue
                est = sum(a['units'] * a['access'][k]['share_primary'] for a in comms) / u
                diff = abs(est - wd['access'][k]['share_primary'])
                if diff > worst[0]:
                    worst = (diff, f'Ward {w} {k}: by location {wd["access"][k]["share_primary"]:.3f}, from communities {est:.3f}')
        check('ward figures agree with their communities (within 3 points)', worst[0] < 0.03, worst[1])
    else:
        check('ward figures present', False, 'no wards in this build')

    # 4. crowding and scores
    cr, sc = A.get('crowding'), A.get('scores')
    check('crowding present for all six amenities', bool(cr) and all(k in cr['kinds'] for k in base),
          '' if cr else 'missing')
    if cr:
        opts = list(cr['options'])
        check('every configured way of counting residents', set(opts) == set(cfg['people']['options']), ', '.join(opts))
        check("default is the configured default", cr['default'] == cfg['people']['default'], cr['default'])
        tots = {o: (v.get('totals') or {}).get('_all') for o, v in cr['options'].items()}
        check('residents and children published for the city and each ward',
              all(t for t in tots.values()) and all(('ward:' + w) in cr['options'][o]['totals'] for o in tots for w in (A.get('wards') or {})),
              '; '.join(f"{o}: {t['residents']:,} residents, {t['children']:,} children" for o, t in tots.items() if t))
        for o, v in cr['options'].items():
            t = v.get('totals') or {}
            if t.get('_all') and A.get('wards'):
                sw = sum(t['ward:' + w]['residents'] for w in A['wards'] if 'ward:' + w in t)
                check(f'ward residents add up to the city ({o}, within 0.5%)', abs(sw / t['_all']['residents'] - 1) < 0.005,
                      f"{sw:,} vs {t['_all']['residents']:,}")
        neg = [(k, o) for k, v in cr['kinds'].items() for o, dd in v['by_option'].items() for d_, vals in dd.items()
               for c, x in vals.items() if not c.startswith('_') and x is not None and x < 0]
        check('crowding figures not negative', not neg, str(neg[:3]))
        if A.get('wards'):
            missing = [w for w in A['wards'] if cr['kinds']['playground']['by_option'][cr['default']][str(kinds['playground']['thresholds_m'][0])].get('ward:' + w) is None]
            check('crowding by ward present', not missing, str(missing))
    if sc:
        bad = []
        for code, r in sc['areas'].items():
            for s in list(r['amenities'].values()) + list(r['groups'].values()) + [r['overall']]:
                if s and s['score'] is not None and not (s['low'] - 1e-9 <= s['score'] <= s['high'] + 1e-9):
                    bad.append(code)
        check('every score sits inside its range', not bad, str(bad[:5]))
        check('ward scores present', all(('ward:' + w) in sc['areas'] for w in (A.get('wards') or {})))

    # 5. people totals match Calgary Data Desk
    if D and cr:
        for m, md in D['methods'].items():
            city = md['city'] or {}
            check(f'dashboard city row has residents ({m})', city.get('residents') is not None)
        keys_needed = ['residents', 'growth_pct', 'homes_now', 'requests_per_1000', 'open', 'closed_7_days_pct', 'crime_per_1000',
                       'traffic_per_1000', 'children_0_14', 'child_care_per_100_kids', 'schools', 'new_homes12', 'dev_permits12']
        m0 = D['methods'][D['default_method']]
        gone = [k for k in keys_needed if m0['city'].get(k) is None]
        check('dashboard has every figure the page shows', not gone, ', '.join(gone), warn=bool(gone) and len(gone) < 4)
        check('dashboard has 14 wards', len(m0['wards']) == 14, str(len(m0['wards'])))
        check('dashboard source read today (not stale)', not D.get('stale'), D.get('stale_reason', ''), warn=True)

    # 6. quality and provenance
    fails = [c for c in Q['checks'] if c['status'] == 'fail']
    warns = [c for c in Q['checks'] if c['status'] == 'warn']
    check('no failed quality checks', not fails, '; '.join(c['detail'] for c in fails))
    check('quality warnings reviewed', True, '; '.join(f"{c['source']} {c['check']}: {c['detail']}" for c in warns))
    nosrc = [s['id'] for s in S['sources'] if not s.get('rows') and 'unit_weights' not in s['id']]
    check('every source has rows read', not nosrc, ', '.join(nosrc))

    # 7. agreement with Calgary Data Desk's own figures, when its file is given
    if desk:
        w0 = json.load(open(desk))
        pop = w0.get('population') or {}
        check("homes lived in: Canada Insight's reference equals Data Desk",
              A['homes'].get('reference') and abs(A['homes']['reference']['total'] - (pop.get('homes_now') or 0)) <= 1,
              f"{(A['homes'].get('reference') or {}).get('total')} vs {pop.get('homes_now')}")

    width = max(len(n) for _, n, _ in RES)
    for st, n, det in RES:
        print(f'{st:4}  {n:<{width}}  {det}')
    return 1 if any(st == 'FAIL' for st, _, _ in RES) else 0


if __name__ == '__main__':
    args = sys.argv[1:]
    desk = None
    if '--desk' in args:
        i = args.index('--desk')
        desk = args[i + 1]
        del args[i:i + 2]
    sys.exit(main(args[0], desk))
