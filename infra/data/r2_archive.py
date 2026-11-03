"""Back up local source folders to the private R2 archive bucket (not the public map bucket).

Each file goes to <prefix>/<path relative to the data root> with its sha256 in metadata. A rerun skips objects that
already exist with the same size, so an interrupted run resumes. Nothing local is deleted here.

  python r2_archive.py --data-root C:/Data/25_ACE --folder ngii-canonical --env-file ../../.env.r2.local
"""
import argparse
import hashlib
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from r2_release import load_settings

BUCKET = 'latent-archive'
# Same spirit as r2_release.safe_key: management/ also holds private settings and NGII order responses with the
# orderer's personal data (*.private.json/html), which never leave the machine.
PRIVATE = re.compile(r'(^|[\\/._-])(env|secret|secrets|credential|credentials|token|tokens|apikey|api-key|password|private)([\\/._-]|$)|\.env', re.I)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while block := f.read(4 * 1024 * 1024): h.update(block)
    return h.hexdigest()


def files(root, folder):
    for base, _, names in os.walk(root / folder):
        for name in names:
            path = Path(base) / name
            key = path.relative_to(root).as_posix()
            if not PRIVATE.search(key): yield key, path


def existing(client, prefix):
    sizes, token = {}, None
    while True:
        page = client.list_objects_v2(Bucket=BUCKET, Prefix=prefix, **({'ContinuationToken': token} if token else {}))
        for item in page.get('Contents', []): sizes[item['Key']] = item['Size']
        if not page.get('IsTruncated'): return sizes
        token = page['NextContinuationToken']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root', type=Path, required=True); p.add_argument('--folder', action='append', required=True)
    p.add_argument('--env-file', type=Path); p.add_argument('--workers', type=int, default=16)
    args = p.parse_args()
    import boto3
    from botocore.config import Config
    s = load_settings(args.env_file)
    client = boto3.client('s3', endpoint_url=f"https://{s['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com", region_name='auto',
        aws_access_key_id=s['R2_ACCESS_KEY_ID'], aws_secret_access_key=s['R2_SECRET_ACCESS_KEY'],
        config=Config(retries={'max_attempts': 5}, max_pool_connections=args.workers + 4))
    root = args.data_root.resolve()
    totals = {'uploaded': 0, 'skipped': 0, 'failed': 0, 'bytes': 0}

    def put(item):
        key, path = item
        size = path.stat().st_size
        if have.get(key) == size: return 'skipped', 0
        try:
            client.upload_file(str(path), BUCKET, key, ExtraArgs={'Metadata': {'sha256': sha256(path)}})
            if client.head_object(Bucket=BUCKET, Key=key)['ContentLength'] != size: return 'failed', 0
            return 'uploaded', size
        except Exception as error:
            print(json.dumps({'failed': key, 'error': type(error).__name__}), flush=True)
            return 'failed', 0

    for folder in args.folder:
        have = existing(client, folder.rstrip('/') + '/')
        with ThreadPoolExecutor(args.workers) as pool:
            for n, (state, size) in enumerate(pool.map(put, files(root, folder)), 1):
                totals[state] += 1; totals['bytes'] += size
                if n % 2000 == 0: print(json.dumps({'folder': folder, 'files': n, **totals}), flush=True)
        print(json.dumps({'folder': folder, 'done': True, **totals}), flush=True)
    return 1 if totals['failed'] else 0


if __name__ == '__main__': sys.exit(main())
