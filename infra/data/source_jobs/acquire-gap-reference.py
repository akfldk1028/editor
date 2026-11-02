"""Acquire public DSM references separately; never install them as NGII ground."""
import source_job_paths as sjp
import concurrent.futures, hashlib, json, math, time
from pathlib import Path
import httpx
import rasterio

ROOT = Path(str(sjp.DATA_ROOT / 'copernicus-gap-reference'))
REPORT = Path(str(sjp.NGII_DEM_ROOT / 'national-buildings-pass-3.json'))

def acquire(tile):
    lat, lon = tile
    name = f'Copernicus_DSM_COG_10_N{lat:02}_00_E{lon:03}_00_DEM'
    url = f'https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif'
    target = ROOT / f'{name}.tif'
    for attempt in range(3):
        try:
            if not target.exists():
                partial = target.with_suffix('.part')
                with httpx.stream('GET', url, timeout=120, follow_redirects=True) as response:
                    if response.status_code == 404:
                        return {'tile': tile, 'state': 'not_available', 'url': url}
                    response.raise_for_status()
                    with partial.open('wb') as output:
                        for chunk in response.iter_bytes(1024 * 1024): output.write(chunk)
                    expected = response.headers.get('content-length')
                    if expected and partial.stat().st_size != int(expected):
                        raise ValueError('Truncated download')
                with rasterio.open(partial) as raster:
                    if raster.crs.to_epsg() != 4326 or raster.count != 1:
                        raise ValueError('Unexpected raster schema')
                    for _, window in raster.block_windows(1): raster.read(1, window=window)
                partial.replace(target)
            with rasterio.open(target) as raster:
                metadata = {'crs': str(raster.crs), 'bounds': list(raster.bounds), 'resolution': raster.res}
            with target.open('rb') as source:
                digest = hashlib.file_digest(source, 'sha256').hexdigest()
            return {'tile': tile, 'state': 'validated', 'url': url, 'file': str(target),
                    'bytes': target.stat().st_size, 'sha256': digest, **metadata}
        except Exception as error:
            if attempt == 2: return {'tile': tile, 'state': 'failed', 'error': str(error), 'url': url}
            time.sleep(2 ** attempt)

def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    tiles = set()
    for region in json.loads(REPORT.read_text())['missingRegions']:
        z, x, y = map(int, region['key'].split('/'))
        for dx in (0, 1):
            for dy in (0, 1):
                lon = (x + dx) / 2**z * 360 - 180
                lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2*(y+dy)/2**z))))
                tiles.add((math.floor(lat), math.floor(lon)))
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        for result in executor.map(acquire, sorted(tiles)):
            results.append(result)
            receipt = {'updatedAt': time.time(), 'purpose': 'reference comparison only; DSM includes structures and vegetation; EGM2008',
                       'installedAsGround': False, 'total': len(tiles), 'completed': len(results), 'results': results}
            temp = ROOT / 'receipt.tmp'
            temp.write_text(json.dumps(receipt, indent=2))
            temp.replace(ROOT / 'receipt.json')
            print(json.dumps({'completed': len(results), 'total': len(tiles), **result}), flush=True)

if __name__ == '__main__': main()
