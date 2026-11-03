"""Back up local source folders to the private R2 archive bucket (not the public map bucket).

Layout is by dataset, not by local drive: each `--map PREFIX=LOCAL_DIR` stores LOCAL_DIR/<rel> as PREFIX/<rel>
(e.g. sources/ngii/original-batch, records/ngii-orders). `_index/<prefix with / as __>.json` records the local
directory, file count, bytes and keys, so a restore puts files back where they came from. Each object carries its
sha256 in metadata. A rerun skips objects that already exist with the same size. Nothing local is deleted here.

  python r2_archive.py --map sources/ngii/canonical=C:/Data/25_ACE/ngii-canonical --env-file ../../.env.r2.local
"""
import argparse
import datetime
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
PREFIX = re.compile(r'(sources|records)(/[a-z0-9][a-z0-9-]*)+')


def mapping(value):
    prefix, _, local = value.partition('=')
    if not PREFIX.fullmatch(prefix) or not local: raise argparse.ArgumentTypeError(f'expected PREFIX=LOCAL_DIR, got {value}')
    return prefix, Path(local).resolve()


def client_for(env_file, workers=16):
    import boto3
    from botocore.config import Config
    s = load_settings(env_file)
    return boto3.client('s3', endpoint_url=f"https://{s['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com", region_name='auto',
        aws_access_key_id=s['R2_ACCESS_KEY_ID'], aws_secret_access_key=s['R2_SECRET_ACCESS_KEY'],
        config=Config(retries={'max_attempts': 5}, max_pool_connections=workers + 4))


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while block := f.read(4 * 1024 * 1024): h.update(block)
    return h.hexdigest()


def files(local):
    for base, _, names in os.walk(local):
        for name in names:
            path = Path(base) / name
            rel = path.relative_to(local).as_posix()
            if not PRIVATE.search(rel): yield rel, path


def existing(client, prefix):
    sizes, token = {}, None
    while True:
        page = client.list_objects_v2(Bucket=BUCKET, Prefix=prefix, **({'ContinuationToken': token} if token else {}))
        for item in page.get('Contents', []): sizes[item['Key']] = item['Size']
        if not page.get('IsTruncated'): return sizes
        token = page['NextContinuationToken']


def write_index(client, prefix, local):
    have = existing(client, prefix + '/')
    index = {'schema': 'latent-archive-index-v2', 'prefix': prefix, 'localDir': local.as_posix(),
             'generatedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
             'files': len(have), 'bytes': sum(have.values()),
             'note': 'Restore: download <prefix>/<rel> to <localDir>/<rel>. sha256 per object in metadata. '
                     'Private files (*.private.*) are never archived and stay local.',
             'objects': [{'key': k, 'bytes': v} for k, v in sorted(have.items())]}
    client.put_object(Bucket=BUCKET, Key=f"_index/{prefix.replace('/', '__')}.json",
                      Body=json.dumps(index, ensure_ascii=False).encode(), ContentType='application/json')
    return index


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--map', type=mapping, action='append', required=True); p.add_argument('--env-file', type=Path)
    p.add_argument('--workers', type=int, default=16)
    args = p.parse_args()
    client = client_for(args.env_file, args.workers)
    totals = {'uploaded': 0, 'skipped': 0, 'failed': 0, 'bytes': 0}
    for prefix, local in args.map:
        have = existing(client, prefix + '/')

        def put(item):
            rel, path = item; key = f'{prefix}/{rel}'; size = path.stat().st_size
            if have.get(key) == size: return 'skipped', 0
            try:
                client.upload_file(str(path), BUCKET, key, ExtraArgs={'Metadata': {'sha256': sha256(path)}})
                if client.head_object(Bucket=BUCKET, Key=key)['ContentLength'] != size: return 'failed', 0
                return 'uploaded', size
            except Exception as error:
                print(json.dumps({'failed': key, 'error': type(error).__name__}), flush=True)
                return 'failed', 0

        with ThreadPoolExecutor(args.workers) as pool:
            for n, (state, size) in enumerate(pool.map(put, files(local)), 1):
                totals[state] += 1; totals['bytes'] += size
                if n % 2000 == 0: print(json.dumps({'prefix': prefix, 'files': n, **totals}), flush=True)
        index = write_index(client, prefix, local)
        print(json.dumps({'prefix': prefix, 'done': True, 'indexFiles': index['files'], **totals}), flush=True)
    return 1 if totals['failed'] else 0


if __name__ == '__main__': sys.exit(main())
