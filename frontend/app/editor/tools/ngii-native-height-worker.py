"""Read-only JSONL native DEM verifier; errors never become confirmed NoData."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.windows import Window
from incremental_terrain_archive import source_stamps, signature


class NativeSampler:
    def __init__(self, path, expected=None, check_seconds=60):
        self.path = Path(path).resolve()
        self.check_seconds = check_seconds
        self.direct = source_stamps(self.path)
        self.recursive = source_stamps(self.path, recursive=True)
        self.fingerprint = {
            'sourceVrtSHA256': hashlib.sha256(self.path.read_bytes()).hexdigest(),
            'sourceFilesSHA256': signature(self.direct),
            'recursiveSourceFilesSHA256': signature(self.recursive),
        }
        for key, value in (expected or {}).items():
            if value and self.fingerprint[key] != value:
                raise ValueError('Pinned source mismatch: ' + key)
        self.src = rasterio.open(self.path)
        if self.src.crs is None:
            self.src.close()
            raise ValueError('DEM has no coordinate reference system')
        self.transformer = Transformer.from_crs('EPSG:4326', self.src.crs, always_xy=True)
        self.last_check = time.monotonic()
        self.verify(full=True)

    def verify(self, full=False):
        for path, size, mtime in self.recursive:
            stamp = Path(path).stat()
            if (stamp.st_size, stamp.st_mtime_ns) != (size, mtime):
                raise ValueError('DEM source changed: ' + path)
        if full or time.monotonic() - self.last_check >= self.check_seconds:
            current = {'sourceVrtSHA256': hashlib.sha256(self.path.read_bytes()).hexdigest(),
                       'sourceFilesSHA256': signature(source_stamps(self.path)),
                       'recursiveSourceFilesSHA256': signature(source_stamps(self.path, recursive=True))}
            if current != self.fingerprint:
                raise ValueError('DEM source fingerprint changed')
            self.last_check = time.monotonic()

    def sample(self, points):
        self.verify()
        points = np.asarray(points, dtype=np.float64)
        if points.size == 0:
            return []
        if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all() \
                or np.any(np.abs(points[:, 0]) > 180) or np.any(np.abs(points[:, 1]) > 90):
            raise ValueError('Invalid coordinate')
        x, y = self.transformer.transform(points[:, 0], points[:, 1])
        inverse = ~self.src.transform
        col = inverse.a*x + inverse.b*y + inverse.c
        row = inverse.d*x + inverse.e*y + inverse.f
        inside = np.isfinite(col) & np.isfinite(row) & (col >= 0) & (row >= 0) & (col < self.src.width) & (row < self.src.height)
        output = [None] * len(points)
        indices = np.flatnonzero(inside)
        if len(indices):
            blocks = np.stack((np.floor(col[indices]/512), np.floor(row[indices]/512)), axis=1).astype(np.int64)
            unique, groups = np.unique(blocks, axis=0, return_inverse=True)
            for group, (bx, by) in enumerate(unique):
                ids = indices[groups == group]
                left, top = max(0, int(bx)*512-1), max(0, int(by)*512-1)
                right, bottom = min(self.src.width, int(bx+1)*512+1), min(self.src.height, int(by+1)*512+1)
                grid = self.src.read(1, window=Window(left, top, right-left, bottom-top), masked=True)
                data = np.asarray(grid.data, dtype=np.float64)
                valid = ~np.ma.getmaskarray(grid) & np.isfinite(data) & (data >= -500) & (data <= 9000)
                c, r = np.floor(col[ids]-.5).astype(int), np.floor(row[ids]-.5).astype(int)
                cc, rr = np.floor(col[ids]).astype(int)-left, np.floor(row[ids]).astype(int)-top
                values = np.where(valid[rr, cc], data[rr, cc], np.nan)
                eligible = (c >= 0) & (r >= 0) & (c+1 < self.src.width) & (r+1 < self.src.height)
                local = np.flatnonzero(eligible)
                lc, lr = c[local]-left, r[local]-top
                good = valid[lr,lc] & valid[lr,lc+1] & valid[lr+1,lc] & valid[lr+1,lc+1]
                local, lc, lr = local[good], lc[good], lr[good]
                u, v = col[ids[local]]-.5-c[local], row[ids[local]]-.5-r[local]
                # NumPy scalar raster samples retain their dtype at each arithmetic
                # operation in the original sampler, before its millimetre rounding.
                native = grid.data
                dtype = native.dtype if np.issubdtype(native.dtype, np.floating) else np.dtype('float64')
                a, b, cu, cv = (factor.astype(dtype) for factor in (1-u, 1-v, u, v))
                values[local] = native[lr,lc]*a*b + native[lr,lc+1]*cu*b + native[lr+1,lc]*a*cv + native[lr+1,lc+1]*cu*cv
                for index, value in zip(ids, values):
                    output[int(index)] = round(float(value), 3) if np.isfinite(value) else None
        self.verify()
        return output

    def close(self):
        try:
            self.verify(full=True)
        finally:
            self.src.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vrt', required=True)
    parser.add_argument('--source-vrt-sha256', required=True)
    parser.add_argument('--source-files-sha256')
    parser.add_argument('--recursive-source-files-sha256')
    args = parser.parse_args()
    sampler, request = None, {}
    emit = lambda value: print(json.dumps(value, allow_nan=False), flush=True)
    try:
        sampler = NativeSampler(args.vrt, dict(sourceVrtSHA256=args.source_vrt_sha256,
            sourceFilesSHA256=args.source_files_sha256, recursiveSourceFilesSHA256=args.recursive_source_files_sha256))
        emit({'type': 'ready', **sampler.fingerprint, 'method': 'bilinear; valid containing cell at NoData edges'})
        for line in sys.stdin:
            request = json.loads(line)
            if request.get('op') == 'close':
                fingerprint = sampler.fingerprint
                sampler.close(); sampler = None
                emit({'id': request.get('id'), 'type': 'closed', **fingerprint})
                return
            if len(request['points']) > 100000:
                raise ValueError('Batch exceeds 100000 points')
            heights = sampler.sample(request['points'])
            emit({'id': request.get('id'), 'heights': heights, **sampler.fingerprint})
        sampler.close(); sampler = None
    except Exception as error:
        emit({'type': 'error', 'id': request.get('id'), 'error': str(error)})
        raise SystemExit(1)
    finally:
        if sampler is not None:
            sampler.src.close()


if __name__ == '__main__':
    main()
