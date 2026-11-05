"""City configuration: everything that differs between cities lives in cities/<id>/city.json.

The core reads a city only through this file. Adding a city means writing its config (see docs/city-onboarding.md);
the pipeline, indicators and website stay the same.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CITIES_DIR = os.path.join(ROOT, 'cities')

REQUIRED = ['id', 'name', 'province', 'status', 'portal', 'centre', 'areas', 'homes', 'amenities', 'growth_year']
STATUSES = ('live', 'pilot', 'planned')


class ConfigError(ValueError):
    pass


def validate(cfg):
    miss = [k for k in REQUIRED if k not in cfg]
    if miss:
        raise ConfigError(f"{cfg.get('id', '?')}: missing {', '.join(miss)}")
    if cfg['status'] not in STATUSES:
        raise ConfigError(f"{cfg['id']}: status must be one of {STATUSES}")
    if cfg['status'] == 'planned':
        return cfg                      # a planned city only needs its readiness assessment
    if cfg['portal'].get('type') != 'socrata':
        raise ConfigError(f"{cfg['id']}: no connector for portal type {cfg['portal'].get('type')!r} yet")
    for key, a in cfg['amenities'].items():
        th = a.get('thresholds_m')
        if not (isinstance(th, list) and len(th) == 2 and 0 < th[0] < th[1]):
            raise ConfigError(f"{cfg['id']}: amenity {key} needs thresholds_m [primary, secondary], primary < secondary")
        if a.get('geometry') not in ('point', 'polygon'):
            raise ConfigError(f"{cfg['id']}: amenity {key} geometry must be point or polygon")
        for f in ('label', 'dataset', 'geometry_field', 'group'):
            if not a.get(f):
                raise ConfigError(f"{cfg['id']}: amenity {key} needs {f}")
    for f in ('dataset', 'code_field', 'name_field', 'geometry_field', 'level'):
        if not cfg['areas'].get(f):
            raise ConfigError(f"{cfg['id']}: areas needs {f}")
    for f in ('dataset', 'id_field', 'area_field', 'built_field', 'geometry_field'):
        if not cfg['homes'].get(f):
            raise ConfigError(f"{cfg['id']}: homes needs {f}")
    return cfg


def load(city_id, cities_dir=CITIES_DIR):
    path = os.path.join(cities_dir, city_id, 'city.json')
    with open(path, encoding='utf-8') as f:
        cfg = json.load(f)
    cfg['_dir'] = os.path.dirname(path)
    return validate(cfg)


def all_cities(cities_dir=CITIES_DIR):
    out = []
    for d in sorted(os.listdir(cities_dir)):
        if os.path.exists(os.path.join(cities_dir, d, 'city.json')):
            out.append(load(d, cities_dir))
    return out
