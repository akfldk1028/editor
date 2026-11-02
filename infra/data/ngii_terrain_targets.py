"""Freeze the exact still-missing building cohort before candidate terrain work."""
import argparse
import hashlib
import json
from pathlib import Path
from collections import defaultdict
import math
from pyproj import Transformer
from ngii_terrain_candidate import packed, reserve


def freeze(points_path, provinces_path, filled_path, output, expected_count=None):
    inputs = {}
    def read(path):
        data = Path(path).read_bytes()
        inputs[str(Path(path).resolve())] = hashlib.sha256(data).hexdigest()
        return json.loads(data)
    points = {r['key']: r for r in read(points_path)}
    provinces = read(provinces_path)['keyProvinces']
    filled = set(read(filled_path)['newlyFilledKeys'])
    keys = sorted(set(provinces) - filled)
    if expected_count is not None and len(keys) != expected_count:
        raise ValueError(f'Target cohort changed: expected {expected_count}, found {len(keys)}')
    if any(key not in points for key in keys):
        raise ValueError('Missing exact coordinate for a target building')
    records = [points[key] for key in keys]
    data = packed(records); digest = hashlib.sha256(data).hexdigest()
    output = Path(output); reserve(output, len(data) * 2)
    output.mkdir(parents=True, exist_ok=True)
    points_file = output / f'exact-missing-{digest}.json'
    if points_file.exists() and points_file.read_bytes() != data:
        raise ValueError('Immutable cohort path changed')
    points_file.write_bytes(data)
    project = Transformer.from_crs(4326, 5186, always_xy=True)
    jobs = defaultdict(list)
    for row in records:
        lon, lat = row['point']; x, y = project.transform(lon, lat)
        if not all(math.isfinite(v) for v in [x, y]):
            raise ValueError('Invalid target coordinate')
        jobs[(math.floor(x/1000), math.floor(y/1000))].append(row['key'])
    queue = [{'cell': list(key), 'bounds5186': [key[0]*1000,key[1]*1000,(key[0]+1)*1000,(key[1]+1)*1000],
              'targetKeys': rows, 'targetCount': len(rows)} for key, rows in jobs.items()]
    queue.sort(key=lambda row: (-row['targetCount'], row['cell']))
    report = {'schema': 'ngii-exact-terrain-targets-v1', 'points': str(points_file.resolve()), 'sha256': digest,
              'count': len(records), 'patches': len(queue), 'inputSHA256': inputs,
              'selection': 'keyProvinces minus activated c748 newlyFilledKeys; do not subtract unactivated candidates',
              'jobs': queue}
    report_path = output / f'priority-{digest}.json'; report_path.write_bytes(packed(report))
    return {k: v for k, v in report.items() if k != 'jobs'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--points', type=Path, required=True); p.add_argument('--provinces', type=Path, required=True)
    p.add_argument('--filled', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--expected-count', type=int)
    a = p.parse_args(); print(json.dumps(freeze(a.points, a.provinces, a.filled, a.output, a.expected_count)))
