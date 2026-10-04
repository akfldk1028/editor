"""Import preserved design jobs, candidate rows and revision evidence explicitly."""
import argparse
import json

from .history import import_history, DesignHistoryError
from .repository import DesignRepository


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--source-id', default='arr-design-main')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    try:
        report = import_history(DesignRepository(args.destination), args.source, args.source_id, dry_run=not args.apply)
        print(json.dumps(report, allow_nan=False))
        return 0
    except (DesignHistoryError, ValueError, OSError):
        print(json.dumps({'valid':False, 'error':'Design import rejected; inspect source or destination conflicts'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
