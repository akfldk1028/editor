"""Preserve an execution artifact tree without retaining its runtime dependency."""
import argparse
import json

from .artifacts import ArtifactArchive, ArtifactArchiveError, import_artifacts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--source-id', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = import_artifacts(ArtifactArchive(args.destination), args.source, args.source_id, dry_run=not args.apply)
        print(json.dumps(result))
        return 0
    except (ArtifactArchiveError, OSError):
        print(json.dumps({'valid': False, 'error': 'Artifact capture rejected; inspect conflicts, source stability or storage'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
