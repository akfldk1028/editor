"""Publish the active world-ground descriptor and its PMTiles archives to R2. Upload is explicit; secrets never enter output.

Archives keep their content-addressed folders under world-ground/ and are immutable. The descriptor is rewritten to
absolute R2 URLs, stored once under world-ground/releases/<sha>/imagery.json and then pointed at by world-ground/latest.json.
The editor reads it through NEXT_PUBLIC_WORLD_GROUND_BASE_URL=<R2_PUBLIC_BASE_URL>/world-ground.
"""
import argparse
import copy
import hashlib
import json
import random
import re
from pathlib import Path
from r2_release import Failure, IMMUTABLE, SHORT, head, load_settings, public_base, remote_digest
from release_store import encoded

PREFIX = '/api/map-data/world-ground/'
# Archives are 2-16 GB: a full GET-back would re-download everything. Size, stored sha256 and sampled ranges instead.
SAMPLES = 4
SAMPLE_BYTES = 64 * 1024


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while block := f.read(8 * 1024 * 1024): h.update(block)
    return h.hexdigest()


def plan(root):
    """(descriptor, [(key, path, sha256, bytes)]) for every archive the active descriptor names."""
    raw = (root/'latest.json').read_bytes()
    descriptor = json.loads(raw)
    if descriptor.get('schema') != 'world-ground/imagery-v1': raise Failure('UNSUPPORTED_GROUND_SCHEMA')
    # The editor's validator (ground-imagery.ts) reads at most 32 KB and one or two layers; fail here, not in the browser.
    # On-demand detail tiles live on the API server, not in an archive: R2 cannot serve them.
    if len(raw) > 24 * 1024 or not 1 <= len(descriptor.get('layers') or []) <= 2 or any('detail' in layer for layer in descriptor['layers']):
        raise Failure('GROUND_DESCRIPTOR_NOT_PUBLISHABLE')
    rows = []
    for layer in [*descriptor['layers'], *([descriptor['vector']] if 'vector' in descriptor else [])]:
        url, sha = layer.get('url'), layer.get('sha256')
        rel = url.removeprefix(PREFIX) if isinstance(url, str) and url.startswith(PREFIX) else ''
        if not re.fullmatch(r'[a-z-]+/[a-f0-9]{64}/[a-z]+\.pmtiles', rel) or not re.fullmatch('[a-f0-9]{64}', sha or ''): raise Failure('INVALID_GROUND_URL')
        path = root/rel
        if not path.is_file(): raise Failure('GROUND_ARCHIVE_MISSING')
        rows.append(('world-ground/'+rel, path, sha, path.stat().st_size))
    return descriptor, rows


def remote_descriptor(descriptor, base):
    result = copy.deepcopy(descriptor)
    for layer in [*result['layers'], *([result['vector']] if 'vector' in result else [])]:
        layer['url'] = public_base(base)+'/world-ground/'+layer['url'].removeprefix(PREFIX)
    return result


def sampled(client, bucket, key, path, size):
    offsets = [0, max(0, size-SAMPLE_BYTES)] + [random.randrange(max(1, size-SAMPLE_BYTES)) for _ in range(SAMPLES-2)]
    with path.open('rb') as f:
        for offset in offsets:
            f.seek(offset); local = f.read(SAMPLE_BYTES)
            body = client.get_object(Bucket=bucket, Key=key, Range=f'bytes={offset}-{offset+len(local)-1}')['Body']
            try: remote = body.read()
            finally: body.close()
            if remote != local: return False
    return True


def current_pointer(client, bucket):
    """(descriptor sha256 or 'none', ETag) of the live world-ground/latest.json."""
    existing = head(client, bucket, 'world-ground/latest.json')
    if existing is None: return 'none', None
    return remote_digest(client, bucket, 'world-ground/latest.json')[0], existing['ETag']


def publish(*, client, bucket, root, base, expected_current, retries=2, transfer_config=None):
    """`expected_current`: the live latest.json sha256 this run replaces, or 'none'. A stale run cannot roll it back."""
    if expected_current != 'none' and not re.fullmatch('[a-f0-9]{64}', expected_current): raise Failure('INVALID_EXPECTED_CURRENT')
    descriptor, rows = plan(root)
    for key, path, sha, size in rows:
        if sha256(path) != sha: raise Failure('LOCAL_ARCHIVE_CHANGED')
        existing = head(client, bucket, key)
        if existing and (existing.get('Metadata', {}).get('sha256') != sha or existing['ContentLength'] != size): raise Failure('IMMUTABLE_OBJECT_COLLISION')
        for attempt in range(retries+1):
            try:
                if not existing:
                    opts = {'Config': transfer_config} if transfer_config is not None else {}
                    client.upload_file(str(path), bucket, key, ExtraArgs={'Metadata': {'sha256': sha}, 'CacheControl': IMMUTABLE,
                        'ContentType': 'application/vnd.pmtiles'}, **opts)
                stored = head(client, bucket, key)
                if not stored or stored['ContentLength'] != size or stored.get('Metadata', {}).get('sha256') != sha \
                        or not sampled(client, bucket, key, path, size): raise Failure('RANGE_VERIFY_FAILED')
                break
            except Exception:
                existing = None
                if attempt == retries: raise Failure('OBJECT_VERIFICATION_FAILED') from None
    remote = remote_descriptor(descriptor, base)
    data = encoded(remote); digest = hashlib.sha256(data).hexdigest()
    release = f'world-ground/releases/{digest}/imagery.json'
    client.put_object(Bucket=bucket, Key=release, Body=data, ContentType='application/json', CacheControl=IMMUTABLE, Metadata={'sha256': digest})
    if remote_digest(client, bucket, release) != (digest, len(data)): raise Failure('POINTER_VERIFY_FAILED')
    current, etag = current_pointer(client, bucket)
    if current != digest:
        if current != expected_current: raise Failure('CURRENT_POINTER_CHANGED')
        condition = {'IfMatch': etag} if etag else {'IfNoneMatch': '*'}
        try:
            client.put_object(Bucket=bucket, Key='world-ground/latest.json', Body=data, ContentType='application/json', CacheControl=SHORT,
                Metadata={'sha256': digest}, **condition)
        except Exception as error:
            if getattr(error, 'response', {}).get('Error', {}).get('Code') in ('PreconditionFailed', '412', 'ConditionalRequestConflict', '409'): raise Failure('CURRENT_POINTER_CHANGED') from None
            raise Failure('POINTER_WRITE_FAILED') from None
        if current_pointer(client, bucket)[0] != digest: raise Failure('CURRENT_POINTER_CHANGED')
    # Size, our sha256 metadata and sampled ranges, not a full read-back of every byte.
    return {'state': 'uploaded', 'verification': 'size+metadata+sampled-ranges', 'descriptorSHA256': digest, 'previous': current,
        'archives': len(rows), 'bytes': sum(r[3] for r in rows), 'groundBaseUrl': public_base(base)+'/world-ground'}


def check_cors(url, origin):
    """The browser's view: a Range GET from the editor origin must expose Content-Range."""
    from urllib.request import Request, urlopen
    # r2.dev answers 403 to Python-urllib's default User-Agent.
    with urlopen(Request(url, headers={'Origin': origin, 'Range': 'bytes=0-126', 'User-Agent': 'r2-ground-check/1'}), timeout=30) as response:
        allowed = response.headers.get('Access-Control-Allow-Origin') in (origin, '*')
        exposed = 'content-range' in (response.headers.get('Access-Control-Expose-Headers') or '').lower()
        if response.status != 206 or not allowed or not exposed: raise Failure('CORS_RANGE_BLOCKED')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ground-root', type=Path, required=True)
    mode = p.add_mutually_exclusive_group(required=True); mode.add_argument('--dry-run', action='store_true'); mode.add_argument('--upload', action='store_true')
    p.add_argument('--env-file', type=Path); p.add_argument('--retries', type=int, default=2)
    p.add_argument('--expected-current', help='--upload: live world-ground/latest.json sha256 this run replaces, or none')
    p.add_argument('--origin', action='append', default=[], help='--upload: editor origin(s) whose Range reads must pass CORS')
    args = p.parse_args()
    try:
        root = args.ground_root.resolve()
        if args.dry_run:
            descriptor, rows = plan(root)
            mismatched = [key for key, path, sha, _ in rows if sha256(path) != sha]
            if mismatched: raise Failure('LOCAL_ARCHIVE_CHANGED')
            print(json.dumps({'state': 'dry-run', 'archives': [key for key, *_ in rows], 'bytes': sum(r[3] for r in rows),
                'hashesVerified': True, 'networkWrites': False})); return 0
        if not args.expected_current: raise Failure('EXPECTED_CURRENT_REQUIRED')
        if not args.origin: raise Failure('CORS_ORIGIN_REQUIRED')
        settings = load_settings(args.env_file)
        import boto3
        from boto3.s3.transfer import TransferConfig
        from botocore.config import Config
        client = boto3.client('s3', endpoint_url='https://'+settings['R2_ACCOUNT_ID']+'.r2.cloudflarestorage.com',
            aws_access_key_id=settings['R2_ACCESS_KEY_ID'], aws_secret_access_key=settings['R2_SECRET_ACCESS_KEY'], region_name='auto',
            config=Config(connect_timeout=15, read_timeout=120, retries={'max_attempts': 2}))
        result = publish(client=client, bucket=settings['R2_BUCKET'], root=root, base=settings['R2_PUBLIC_BASE_URL'], retries=args.retries,
            expected_current=args.expected_current, transfer_config=TransferConfig(multipart_chunksize=64*1024*1024, max_concurrency=4))
        archive = plan(root)[1][0][0]
        for origin in args.origin: check_cors(public_base(settings['R2_PUBLIC_BASE_URL'])+'/'+archive, public_base(origin))
        result['corsChecked'] = args.origin
        print(json.dumps(result)); return 0
    except Failure as error:
        print(json.dumps({'state': 'failed', 'code': str(error)})); return 1
    except Exception:
        print(json.dumps({'state': 'failed', 'code': 'R2_OPERATION_FAILED'})); return 1


if __name__ == '__main__': raise SystemExit(main())
