"""python -m insight build --city calgary --out site/data [--previous DIR]
python -m insight index --out site/data"""
import argparse
import sys

from . import config, pipeline


def main(argv=None):
    ap = argparse.ArgumentParser(prog='insight')
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='build one city')
    b.add_argument('--city', required=True)
    b.add_argument('--out', default='site/data')
    b.add_argument('--previous', help='the last published data folder, for count-change checks')
    i = sub.add_parser('index', help='write the list of cities')
    i.add_argument('--out', default='site/data')
    a = ap.parse_args(argv)
    if a.cmd == 'build':
        try:
            d = pipeline.build_city(a.city, a.out, a.previous)
        except pipeline.BuildFailed as e:
            print('Build stopped by data quality checks (nothing was published):', file=sys.stderr)
            for c in e.checks:
                print(f'  FAIL {c.source} {c.check}: {c.detail}', file=sys.stderr)
            return 2
        print('built', d)
    pipeline.write_index(a.out, config.all_cities())
    return 0


if __name__ == '__main__':
    sys.exit(main())
