"""Data quality checks. Each returns a QualityCheck; a 'fail' stops the build from publishing (see pipeline.py).

Thresholds come from the city config (quality section) so a city with known gaps can say so openly, not silently.
"""
from datetime import date

from .model import QualityCheck


def _ratio(n, total):
    return n / total if total else 0.0


def missing(source, rows, field, warn=0.01, fail=0.10, label=None):
    n = sum(1 for r in rows if r.get(field) in (None, '', {}))
    share = _ratio(n, len(rows))
    st = 'fail' if share > fail else 'warn' if share > warn else 'pass'
    return QualityCheck(source, f'missing_{label or field}', st,
                        f'{n:,} of {len(rows):,} rows ({share:.2%}) have no {label or field}', round(share, 5), warn)


def duplicates(source, rows, key, warn=0.0, fail=0.01):
    seen, dup = set(), 0
    for r in rows:
        k = r.get(key)
        if k is None:
            continue
        if k in seen:
            dup += 1
        seen.add(k)
    share = _ratio(dup, len(rows))
    st = 'fail' if share > fail else 'warn' if share > warn else 'pass'
    return QualityCheck(source, f'duplicate_{key}', st, f'{dup:,} repeated {key} values in {len(rows):,} rows',
                        round(share, 5), warn)


def outside_bbox(source, points, box, warn=0.001, fail=0.02):
    """Points (lon, lat) outside the city's bounding box (with a margin): wrong coordinates or wrong city."""
    x0, y0, x1, y1 = box
    n = sum(1 for x, y in points if not (x0 <= x <= x1 and y0 <= y <= y1))
    share = _ratio(n, len(points))
    st = 'fail' if share > fail else 'warn' if share > warn else 'pass'
    return QualityCheck(source, 'outside_city_extent', st, f'{n:,} of {len(points):,} locations fall outside the city extent',
                        round(share, 5), warn)


def unknown_codes(source, codes, known, warn=0.001, fail=0.05, what='community code'):
    n = sum(1 for c in codes if c and c not in known)
    blank = sum(1 for c in codes if not c)
    share = _ratio(n + blank, len(codes))
    st = 'fail' if share > fail else 'warn' if share > warn else 'pass'
    return QualityCheck(source, 'invalid_area_code', st,
                        f'{n:,} records carry a {what} with no boundary, {blank:,} have none ({share:.2%})',
                        round(share, 5), warn)


def year_range(source, years, lo=1850, hi=None, warn=0.01, fail=0.10):
    hi = hi or date.today().year + 1
    n = sum(1 for y in years if y is not None and not (lo <= y <= hi))
    unknown = sum(1 for y in years if y is None)
    share = _ratio(n, len(years))
    st = 'fail' if share > fail else 'warn' if share > warn else 'pass'
    return QualityCheck(source, 'year_out_of_range', st,
                        f'{n:,} years outside {lo} to {hi}; {unknown:,} unknown', round(share, 5), warn)


def count_change(source, now, before, warn=0.05, fail=0.25):
    """Row count against the previous published build: a large swing usually means a schema or filter change."""
    if not before:
        return QualityCheck(source, 'count_change', 'pass', f'{now:,} rows; no previous build to compare')
    ch = now / before - 1
    st = 'fail' if abs(ch) > fail else 'warn' if abs(ch) > warn else 'pass'
    return QualityCheck(source, 'count_change', st, f'{now:,} rows against {before:,} in the previous build ({ch:+.1%})',
                        round(ch, 4), warn)


def stale(source, publisher_updated, max_age_days, today=None):
    today = today or date.today()
    if not publisher_updated:
        return QualityCheck(source, 'stale', 'warn', 'the publisher does not state when the data was last updated')
    age = (today - date.fromisoformat(publisher_updated[:10])).days
    st = 'warn' if age > max_age_days else 'pass'
    return QualityCheck(source, 'stale', st, f'last updated by the publisher {publisher_updated} ({age} days ago; '
                                             f'expected within {max_age_days})', age, max_age_days)


def required_fields(source, rows, fields):
    """Schema check: every expected field appears in the data (a renamed field silently empties an indicator)."""
    present = set()
    for r in rows[:1000]:
        present.update(r.keys())
    gone = [f for f in fields if f not in present]
    return QualityCheck(source, 'schema', 'fail' if gone else 'pass',
                        ('missing fields: ' + ', '.join(gone)) if gone else 'all expected fields present')


def worst(checks):
    order = {'pass': 0, 'warn': 1, 'fail': 2}
    return max((c.status for c in checks), key=order.get, default='pass')
