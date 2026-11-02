"""Build GDAL's persistent quadtree indexes for the installed national shapefiles."""
import source_job_paths as sjp
import ctypes
import json
from pathlib import Path

import pyogrio

root = sjp.SOURCE_DATA_ROOT
library = next((Path(pyogrio.__file__).parent.parent / 'pyogrio.libs').glob('*gdal*.dll'))
gdal = ctypes.CDLL(str(library))
gdal.GDALAllRegister()
gdal.GDALOpenEx.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
gdal.GDALOpenEx.restype = ctypes.c_void_p
gdal.GDALDatasetExecuteSQL.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_char_p]
gdal.GDALDatasetExecuteSQL.restype = ctypes.c_void_p
gdal.GDALDatasetReleaseResultSet.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdal.GDALClose.argtypes = [ctypes.c_void_p]
results = []
for path in sorted((root / 'raw/ngii_map/b020/_전국').rglob('N3*.shp')):
    if (path.parent / '.sitecontext-install-incomplete.json').exists():
        raise RuntimeError('Source installation still in progress')
    index = path.with_suffix('.qix')
    if not index.exists() or index.stat().st_mtime_ns < path.stat().st_mtime_ns:
        handle = gdal.GDALOpenEx(str(path).encode('utf-8'), 5, None, None, None)
        if not handle:
            raise RuntimeError(f'Cannot open {path.name} for indexing')
        try:
            result = gdal.GDALDatasetExecuteSQL(handle, f'CREATE SPATIAL INDEX ON {path.stem}'.encode(), None, None)
            if result:
                gdal.GDALDatasetReleaseResultSet(handle, result)
        finally:
            gdal.GDALClose(handle)
    if not index.is_file() or index.stat().st_size == 0:
        raise RuntimeError(f'No spatial index created for {path.name}')
    results.append({'source': str(path), 'index': str(index), 'bytes': index.stat().st_size})
    print('indexed', path.name, flush=True)
(sjp.INDEX_STATE_ROOT / 'national-spatial-indexes-20261023.json').write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print('indexes', len(results), flush=True)
