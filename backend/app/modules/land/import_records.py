"""Explicit offline import; defaults to validation without destination writes."""
import argparse
import json
import sqlite3

from .repository import LandRepository


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='kind', required=True)
    history = commands.add_parser('history', help='Preserve historical query and result rows')
    history.add_argument('--source', required=True)
    history.add_argument('--source-id', required=True)
    caches = commands.add_parser('cache', help='Import timestamped provider caches')
    caches.add_argument('--land-dir')
    caches.add_argument('--zone-dir')
    for command in (history, caches):
        command.add_argument('--destination', required=True, help='Absolute Editor land data directory')
        command.add_argument('--apply', action='store_true', help='Commit the validated import')
    args = parser.parse_args(argv)
    try:
        repository = LandRepository(args.destination)
        if args.kind == 'history':
            from .history import import_history
            report = import_history(repository, args.source, args.source_id, dry_run=not args.apply)
        else:
            if not (args.land_dir or args.zone_dir):
                parser.error('cache requires --land-dir or --zone-dir')
            from .cache_import import import_caches
            report = import_caches(repository, args.land_dir, args.zone_dir, dry_run=not args.apply)
        print(json.dumps(report, ensure_ascii=True, allow_nan=False))
        return 0 if report.get('valid', True) else 1
    except (ValueError, OSError, sqlite3.Error):
        print(json.dumps({'valid': False, 'error': 'Import rejected; inspect source schema, data and destination conflicts'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
