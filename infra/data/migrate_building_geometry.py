"""Bounded geometry migration under the same byte lock as the national ground baker."""
import argparse
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from paths import DataPaths


@contextmanager
def building_lock(dem_root):
    import msvcrt
    path = Path(dem_root) / 'national-buildings.lock'
    with path.open('a+b') as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError('National building writer is already running; migration was not started') from error
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dem-root', type=Path, required=True, help='Existing NGII_DEM_ROOT used by the ground writer')
    parser.add_argument('--regions-file', type=Path, required=True, help='Explicit JSON list containing at most 256 z14 keys')
    parser.add_argument('--limit', type=int, default=16)
    parser.add_argument('--reserve-bytes', type=int, default=20_000_000_000)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.limit <= 256 or args.reserve_bytes < 0:
        parser.error('limit must be 1..256 and reserve-bytes nonnegative')
    selected = json.loads(args.regions_file.read_text(encoding='utf-8-sig'))
    if not isinstance(selected, list) or not 1 <= len(selected) <= 256 or not all(isinstance(k, str) for k in selected):
        parser.error('regions-file must contain 1..256 region keys')
    env = dict(os.environ, NGII_DEM_ROOT=str(args.dem_root.resolve()))
    paths = DataPaths.from_env(env)
    with building_lock(paths.dem):
        catalog = json.loads((paths.catalog / 'catalog.json').read_text(encoding='utf-8'))
        env = paths.building_env(catalog['source'], env=env)
        env.update(WORLD_GEOMETRY_LOCK_HELD='1', WORLD_BUILDINGS_REGIONS_FILE=str(args.regions_file.resolve()),
                   WORLD_GEOMETRY_LIMIT=str(args.limit), WORLD_GEOMETRY_RESERVE_BYTES=str(args.reserve_bytes),
                   WORLD_GEOMETRY_RESUME='1' if args.resume else '0')
        child = subprocess.Popen([paths.bun, 'tools/migrate-building-geometry.ts'], cwd=paths.app, env=env,
                                 stdout=sys.stdout, stderr=sys.stderr,
                                 creationflags=subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        try:
            code = child.wait()
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        if code:
            raise SystemExit(code)


if __name__ == '__main__':
    main()
