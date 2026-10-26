"""Sample an installed raster only; never acquire data or replace NoData with zero."""
import hashlib
import json
import math
import sys
from pathlib import Path
from datetime import datetime, timezone

import rasterio
from pyproj import Transformer
from rasterio.windows import Window


def source_signature(files):
    signature = [(str(p.resolve()), p.stat().st_size, p.stat().st_mtime_ns) for p in files]
    return hashlib.sha256(json.dumps(signature).encode()).hexdigest()


def sample(path, points):
    with rasterio.open(path) as src:
        files = [Path(p) for p in src.files]
        revision = source_signature(files)
        stamps = []
        if not points:
            for file in files:
                info = file.stat()
                stamps.append({'path': str(file.resolve()), 'size': str(info.st_size), 'mtimeNs': str(info.st_mtime_ns)})
        if src.crs is None:
            raise ValueError('DEM has no coordinate reference system')
        transform = Transformer.from_crs('EPSG:4326', src.crs, always_xy=True)
        inverse = ~src.transform
        heights = []
        for lon, lat in points:
            if not all(math.isfinite(v) for v in (lon, lat)):
                raise ValueError('Invalid coordinate')
            x, y = transform.transform(lon, lat)
            col, row = inverse * (x, y)
            if not (0 <= col < src.width and 0 <= row < src.height):
                heights.append(None)
                continue
            c, r = math.floor(col - .5), math.floor(row - .5)
            grid = src.read(1, window=Window(c, r, 2, 2), masked=True)
            valid = lambda v: not getattr(v, 'mask', False) and math.isfinite(float(v)) and -500 <= float(v) <= 9000
            if c >= 0 and r >= 0 and grid.shape == (2, 2) and all(valid(v) for v in grid.flat):
                u, v = col - .5 - c, row - .5 - r
                z = grid[0, 0] * (1-u) * (1-v) + grid[0, 1] * u * (1-v) + grid[1, 0] * (1-u) * v + grid[1, 1] * u * v
                heights.append(round(float(z), 3))
            else:
                nearest = src.read(1, window=Window(math.floor(col), math.floor(row), 1, 1), masked=True)[0, 0]
                heights.append(round(float(nearest), 3) if valid(nearest) else None)
        if source_signature(files) != revision:
            raise ValueError('DEM source changed during sampling')
        return {'heights': heights, **({'revisionFiles': stamps} if not points else {}), 'source': {'raster': Path(path).name, 'crs': str(src.crs),
            'kind': 'derived', 'sampledAt': datetime.now(timezone.utc).isoformat(),
            'method': 'bilinear; valid containing cell at NoData edges',
            'fileSignature': revision}}


if __name__ == '__main__':
    print(json.dumps(sample(sys.argv[1], json.load(sys.stdin))))
