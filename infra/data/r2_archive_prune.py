"""Delete local copies that the private archive already holds byte-for-byte in size, keeping private files.

Dry run by default; --delete removes. Files missing from R2, with a different size, or matching r2_archive.PRIVATE
stay, and so do small top-level metadata files and files listed in a sealed release receipt. Empty directories are removed afterwards, and a MOVED-TO-R2.md note is left in each folder.
"""
import argparse
import json
import os
from pathlib import Path

from r2_archive import BUCKET, PRIVATE, existing
from r2_release import load_settings

KEEP_TOP = {'.json', '.jsonl', '.js', '.cjs', '.md', '.csv', '.txt', '.html'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root', type=Path, required=True); p.add_argument('--folder', action='append', required=True)
    p.add_argument('--env-file', type=Path); p.add_argument('--delete', action='store_true')
    args = p.parse_args()
    import boto3
    s = load_settings(args.env_file)
    client = boto3.client('s3', endpoint_url=f"https://{s['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com", region_name='auto',
        aws_access_key_id=s['R2_ACCESS_KEY_ID'], aws_secret_access_key=s['R2_SECRET_ACCESS_KEY'])
    root = args.data_root.resolve()
    # Sealed releases list some source files (e.g. ngii-canonical plans) in their receipts; verify() needs them local.
    sealed = set()
    for receipt in (root / 'management/releases').glob('*/files.jsonl'):
        with open(receipt, encoding='utf-8') as lines: sealed.update(json.loads(line)['key'] for line in lines)
    for folder in args.folder:
        have = existing(client, folder.rstrip('/') + '/')
        report = {'folder': folder, 'delete': 0, 'deleteBytes': 0, 'keepPrivate': 0, 'keepRelease': 0, 'keepTopLevel': 0, 'keepMissing': 0, 'keepSizeDiff': 0}
        for base, _, names in os.walk(root / folder):
            for name in names:
                path = Path(base) / name; key = path.relative_to(root).as_posix(); size = path.stat().st_size
                if PRIVATE.search(key): report['keepPrivate'] += 1; continue
                if key in sealed: report['keepRelease'] += 1; continue
                # Each folder's own catalogues, manifests, status and order scripts: the acquisition tools read them.
                if Path(base) == root / folder and path.suffix.lower() in KEEP_TOP: report['keepTopLevel'] += 1; continue
                if key not in have: report['keepMissing'] += 1; continue
                if have[key] != size: report['keepSizeDiff'] += 1; continue
                report['delete'] += 1; report['deleteBytes'] += size
                if args.delete: path.unlink()
        if args.delete:
            for base, dirs, names in os.walk(root / folder, topdown=False):
                if Path(base) != root / folder and not os.listdir(base): os.rmdir(base)
            (root / folder / 'MOVED-TO-R2.md').write_text(
                f'# {folder}\n\nThe files of this folder live in the private R2 bucket `{BUCKET}` under the same relative path\n'
                f'(`{folder}/...`), listed in `_index/{folder.replace("/", "__")}.json`. Restore with infra/data/r2_archive.py\'s\n'
                'layout: download each key below C:/Data/25_ACE. Private files (*.private.*) were never uploaded and stay here.\n', encoding='utf-8')
        print(json.dumps({**report, 'deleteGB': round(report['deleteBytes'] / 2**30, 2), 'applied': args.delete}), flush=True)


if __name__ == '__main__': main()
