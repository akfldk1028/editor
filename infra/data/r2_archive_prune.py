"""Delete local copies that the private archive already holds (same key and size), keeping what must stay local.

Dry run by default; --delete removes. Same `--map PREFIX=LOCAL_DIR` pairs as r2_archive.py. Kept: files missing
from R2 or with a different size, private files (r2_archive.PRIVATE), each folder's small top-level metadata
(catalogues, manifests, status, scripts) that the acquisition tools read, and any file listed in a sealed release
receipt under --data-root (verify() needs those local). Empty directories are removed afterwards, and a
MOVED-TO-R2.md note is left in each folder.
"""
import argparse
import json
import os
from pathlib import Path

from r2_archive import BUCKET, PRIVATE, client_for, existing, mapping

KEEP_TOP = {'.json', '.jsonl', '.js', '.cjs', '.md', '.csv', '.txt', '.html'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--map', type=mapping, action='append', required=True); p.add_argument('--env-file', type=Path)
    p.add_argument('--data-root', type=Path, default=Path('C:/Data/25_ACE')); p.add_argument('--delete', action='store_true')
    args = p.parse_args()
    client = client_for(args.env_file)
    root = args.data_root.resolve()
    # String paths, not resolve(): ten receipts hold ~4.5 M keys, and a filesystem call per key took minutes.
    # Sealed releases list some source files (e.g. ngii-canonical plans) in their receipts; verify() needs them local.
    sealed = set()
    for receipt in (root / 'management/releases').glob('*/files.jsonl'):
        with open(receipt, encoding='utf-8') as lines: sealed.update(os.path.normcase(os.path.join(root, json.loads(line)['key'])) for line in lines)
    for prefix, local in args.map:
        have = existing(client, prefix + '/')
        report = {'prefix': prefix, 'local': local.as_posix(), 'delete': 0, 'deleteBytes': 0, 'keepPrivate': 0,
                  'keepRelease': 0, 'keepTopLevel': 0, 'keepMissing': 0, 'keepSizeDiff': 0}
        for base, _, names in os.walk(local):
            for name in names:
                path = Path(base) / name; rel = path.relative_to(local).as_posix(); size = path.stat().st_size
                if PRIVATE.search(rel): report['keepPrivate'] += 1; continue
                if os.path.normcase(str(path)) in sealed: report['keepRelease'] += 1; continue
                if Path(base) == local and path.suffix.lower() in KEEP_TOP: report['keepTopLevel'] += 1; continue
                key = f'{prefix}/{rel}'
                if key not in have: report['keepMissing'] += 1; continue
                if have[key] != size: report['keepSizeDiff'] += 1; continue
                report['delete'] += 1; report['deleteBytes'] += size
                if args.delete: path.unlink()
        if args.delete:
            for base, _, _ in os.walk(local, topdown=False):
                if Path(base) != local and not os.listdir(base): os.rmdir(base)
            (local / 'MOVED-TO-R2.md').write_text(
                f'# {local.name}\n\nThe files of this folder live in the private R2 bucket `{BUCKET}` under `{prefix}/` (same relative\n'
                f"paths), listed in `_index/{prefix.replace('/', '__')}.json`. Restore: download `{prefix}/<rel>` to this folder\n"
                'with infra/data/r2_archive.py credentials. Private files (*.private.*) were never uploaded and stay here.\n', encoding='utf-8')
        print(json.dumps({**report, 'deleteGB': round(report['deleteBytes'] / 2**30, 2), 'applied': args.delete}), flush=True)


if __name__ == '__main__': main()
