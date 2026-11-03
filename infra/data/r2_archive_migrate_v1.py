"""One-off (2026-11-03): move latent-archive objects from local-path keys (v1) to dataset prefixes (v2), server side.

Copies each object (metadata kept; multipart copy above 5 GB), checks the copy's size and sha256 metadata, then
deletes the old key and the old v1 index. Rerunnable: objects already at the new key are not copied again.
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from r2_archive import BUCKET, client_for, existing, write_index

MOVES = [  # (v1 prefix, v2 prefix, local dir for the new index)
    ('ngii-original-batch', 'sources/ngii/original-batch', 'C:/Data/25_ACE/ngii-original-batch'),
    ('ngii-canonical', 'sources/ngii/canonical', 'C:/Data/25_ACE/ngii-canonical'),
    ('ngii-ground-gap-sources', 'sources/ngii/ground-gap', 'C:/Data/25_ACE/ngii-ground-gap-sources'),
    ('copernicus-gap-reference', 'sources/copernicus/gap-reference', 'C:/Data/25_ACE/copernicus-gap-reference'),
    ('management/national-source-expansion', 'records/ngii-orders', 'C:/Data/25_ACE/management/national-source-expansion'),
]


def main(env_file):
    client = client_for(Path(env_file), 32)
    for old, new, local in MOVES:
        src = existing(client, old + '/'); dst = existing(client, new + '/')
        def move(item):
            key, size = item; target = new + key[len(old):]
            try:
                if dst.get(target) != size:
                    head = client.head_object(Bucket=BUCKET, Key=key)
                    if size < 5 * 1024**3:
                        client.copy_object(Bucket=BUCKET, Key=target, CopySource={'Bucket': BUCKET, 'Key': key}, MetadataDirective='COPY')
                    else:
                        client.copy({'Bucket': BUCKET, 'Key': key}, BUCKET, target, ExtraArgs={'Metadata': head.get('Metadata', {})})
                    copied = client.head_object(Bucket=BUCKET, Key=target)
                    if copied['ContentLength'] != size or copied.get('Metadata', {}).get('sha256') != head.get('Metadata', {}).get('sha256'):
                        return 'mismatch', key
                return 'ok', key
            except Exception as error:
                return 'error:' + type(error).__name__, key
        results = {'ok': [], 'bad': []}
        with ThreadPoolExecutor(32) as pool:
            for n, (state, key) in enumerate(pool.map(move, src.items()), 1):
                (results['ok'] if state == 'ok' else results['bad']).append(key if state == 'ok' else (state, key))
                if n % 5000 == 0: print(json.dumps({'move': old, 'done': n, 'of': len(src), 'bad': len(results['bad'])}), flush=True)
        if results['bad']:
            print(json.dumps({'move': old, 'stopped': True, 'bad': results['bad'][:5], 'badCount': len(results['bad'])}), flush=True)
            return 1
        for i in range(0, len(results['ok']), 1000):
            client.delete_objects(Bucket=BUCKET, Delete={'Objects': [{'Key': k} for k in results['ok'][i:i + 1000]], 'Quiet': True})
        client.delete_object(Bucket=BUCKET, Key=f"_index/{old.replace('/', '__')}.json")
        index = write_index(client, new, Path(local))
        print(json.dumps({'move': old, 'to': new, 'moved': len(results['ok']), 'indexFiles': index['files'], 'left': len(existing(client, old + '/'))}), flush=True)
    return 0


if __name__ == '__main__': sys.exit(main(sys.argv[1]))
