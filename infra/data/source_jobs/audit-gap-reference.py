"""Compare exact building sample coordinates; do not change published assets."""
import source_job_paths as sjp
import collections, importlib.util, json, math, time
from pathlib import Path
import rasterio

ROOT = Path(str(sjp.NGII_DEM_ROOT))
REF = Path(str(sjp.DATA_ROOT / 'copernicus-gap-reference'))
spec = importlib.util.spec_from_file_location('sampler', str(sjp.EDITOR_ROOT / 'frontend/app/editor/tools/sample-building-dem.py'))
sampler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sampler)
points = json.loads((ROOT/'national-gap-candidate-points.json').read_text())
missing = []
counts = collections.Counter()
for start in range(0, len(points), 4096):
    batch = points[start:start+4096]
    result = sampler.sample(str(ROOT/'ngii_dem.vrt'), [p['point'] for p in batch])
    for point, height in zip(batch, result['heights']):
        if height is None:
            missing.append(point)
            counts[point['region']] += 1
    print(json.dumps({'sampled': min(start+4096, len(points)), 'missing': len(missing)}), flush=True)
(ROOT/'national-gap-exact-points.json').write_text(json.dumps(missing))
deadline = time.monotonic() + 600
while time.monotonic() < deadline:
    receipt = json.loads((REF/'receipt.json').read_text()) if (REF/'receipt.json').exists() else {}
    if receipt.get('completed') == receipt.get('total') and receipt: break
    time.sleep(5)
rasters = {tuple(item['tile']): rasterio.open(item['file']) for item in receipt.get('results', []) if item['state'] == 'validated'}
reference_valid = 0
uncovered = collections.Counter()
try:
    for point in missing:
        lon, lat = point['point']
        # Pixel-is-point COG bounds extend half a pixel across nominal degree tiles.
        raster = next((r for r in rasters.values() if r.bounds.left <= lon < r.bounds.right
                       and r.bounds.bottom < lat <= r.bounds.top), None)
        if raster is not None:
            value = next(raster.sample([(lon, lat)], masked=True))[0]
            if not getattr(value, 'mask', False) and math.isfinite(float(value)):
                reference_valid += 1
                continue
        uncovered[point['region']] += 1
finally:
    for raster in rasters.values(): raster.close()
report = {'checkedAt': time.time(), 'candidateRecords': len(points), 'exactMissingRecords': len(missing),
          'missingRegions': len(counts), 'referenceCoveredRecords': reference_valid,
          'referenceUncoveredRecords': sum(uncovered.values()), 'uncoveredRegions': dict(uncovered),
          'installedAsGround': False, 'limitation': 'Reference coverage only. DSM is not bare earth; no ground accuracy or vertical datum equivalence established.'}
(ROOT/'national-gap-reference-audit.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report), flush=True)
