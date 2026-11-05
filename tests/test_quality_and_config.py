from datetime import date

import pytest

from insight import config, quality


def test_missing_thresholds():
    rows = [{'g': 1}] * 98 + [{'g': None}] * 2
    assert quality.missing('s', rows, 'g', warn=0.01, fail=0.1).status == 'warn'
    assert quality.missing('s', rows, 'g', warn=0.05, fail=0.1).status == 'pass'
    assert quality.missing('s', rows, 'g', warn=0.0, fail=0.01).status == 'fail'


def test_duplicates_and_codes():
    assert quality.duplicates('s', [{'id': 1}, {'id': 1}, {'id': 2}], 'id').status == 'fail'
    assert quality.unknown_codes('s', ['A', 'A', 'Z', None], {'A'}).status == 'fail'
    assert quality.unknown_codes('s', ['A'] * 10_000 + ['Z'] * 20, {'A'}).status == 'warn'


def test_count_change_and_stale():
    assert quality.count_change('s', 100, None).status == 'pass'
    assert quality.count_change('s', 103, 100).status == 'pass'
    assert quality.count_change('s', 110, 100).status == 'warn'
    assert quality.count_change('s', 60, 100).status == 'fail'
    assert quality.stale('s', '2026-10-01', 45, date(2026, 11, 5)).status == 'pass'
    assert quality.stale('s', '2026-08-01', 45, date(2026, 11, 5)).status == 'warn'


def test_schema_check():
    assert quality.required_fields('s', [{'a': 1}], ['a', 'b']).status == 'fail'
    assert quality.worst([quality.required_fields('s', [{'a': 1}], ['a'])]) == 'pass'


def test_every_city_config_is_valid():
    cities = {c['id']: c for c in config.all_cities()}
    assert cities['calgary']['status'] == 'pilot'
    assert cities['edmonton']['status'] == 'pilot'
    for key, a in cities['calgary']['amenities'].items():
        assert a['threshold_basis'], key


def test_bad_thresholds_rejected():
    cfg = config.load('calgary')
    cfg['amenities']['playground']['thresholds_m'] = [800, 400]
    with pytest.raises(config.ConfigError):
        config.validate(cfg)
