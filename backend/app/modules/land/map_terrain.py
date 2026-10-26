"""Display terrain from the installed mosaic, without starting an agent."""
import os
import hashlib
from functools import lru_cache
from pathlib import Path

from backend.app.adapters.elevation import ElevationClient, ElevationFetchError


def identity():
    path = Path(os.environ.get('NGII_DEM_LOCAL_PATH') or
                str(Path(os.environ.get('NGII_DEM_DIR', 'D:/Data/NGII_DEM')) / 'ngii_dem.vrt'))
    try:
        stat = path.stat()
    except OSError:
        raise ElevationFetchError('Local map terrain is not installed') from None
    return str(path.resolve()), stat.st_size, stat.st_mtime_ns


@lru_cache(maxsize=4)
def _metadata(source):
    revision = hashlib.sha256(repr(source).encode()).hexdigest()
    digest = None
    if Path(source[0]).suffix.lower() == '.vrt':
        digest = hashlib.sha256(Path(source[0]).read_bytes()).hexdigest()
    if identity() != source:
        raise ElevationFetchError('Local map terrain changed while reading metadata; retry')
    return {'revision': revision, 'vrt_sha256': digest}


def metadata():
    return dict(_metadata(identity()))


def ground_heights(points):
    before = identity()
    client = ElevationClient(provider='ngii_local_dem', local_dem_path=before[0])
    heights = client.fetch(points)
    if identity() != before:
        raise ElevationFetchError('Local map terrain changed while sampling; retry')
    return heights, {'name': 'ngii_local_dem', 'sampling': 'nearest raster cell',
                     'revision': hashlib.sha256(repr(before).encode()).hexdigest(), 'fallback_used': False}
