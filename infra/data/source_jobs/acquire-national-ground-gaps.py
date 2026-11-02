"""Bounded, resumable acquisition of original NGII terrain layers via VWorld WFS."""
import source_job_paths as sjp
import concurrent.futures, hashlib, json, math, os, sys, time
from pathlib import Path
import msvcrt

sys.path.insert(0, str(sjp.AGENT_ROOT / 'SiteContextAgent'))
from sitecontextagent.surroundings import vworld_context as vworld

ROOT = Path(str(sjp.NGII_DEM_ROOT))
OUTPUT = Path(str(sjp.DATA_ROOT / 'ngii-ground-gap-sources'))

def atomic(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)

def acquire(region, key):
    z, x, y = map(int, region['key'].split('/'))
    folder = OUTPUT / f'{z}-{x}-{y}'
    folder.mkdir(parents=True, exist_ok=True)
    receipt = folder / 'receipt.json'
    if receipt.exists():
        saved = json.loads(receipt.read_text(encoding='utf-8'))
        if saved.get('state') in ('original_data_acquired', 'original_source_empty'):
            valid = all((folder / row['file']).exists() and hashlib.sha256((folder / row['file']).read_bytes()).hexdigest() == row['sha256'] for row in saved['layers'].values())
            if valid: return saved
    latitude = lambda row: math.degrees(math.atan(math.sinh(math.pi * (1 - 2*row/2**z))))
    bbox = [x/2**z*360-180-.004, latitude(y+1)-.004,
            (x+1)/2**z*360-180+.004, latitude(y)+.004]
    result = {'region': region['key'], 'bbox': bbox, 'missingDatum': region['missingDatum'],
              'provider': 'VWorld WFS / NGII contours and spot heights', 'layers': {}, 'at': time.time()}
    for kind in ('contours', 'spot_heights'):
        layer = vworld.LAYERS[kind]
        for attempt in range(3):
            try:
                rows = vworld.features(layer, tuple(bbox), key)
                path = folder / f'{kind}.geojson'
                body = json.dumps({'type': 'FeatureCollection', 'features': rows,
                                  'crs': {'type':'name','properties':{'name':'EPSG:4326'}}}, ensure_ascii=False).encode('utf-8')
                path.write_bytes(body)
                result['layers'][kind] = {'layer': layer, 'features': len(rows), 'file': path.name,
                                          'sha256': hashlib.sha256(body).hexdigest()}
                break
            except Exception as error:
                if attempt == 2:
                    # HTTP exception text may contain the credential-bearing URL.
                    result['state'] = 'request_failed'
                    result['errorType'] = type(error).__name__
                    atomic(receipt, result)
                    return result
                time.sleep(2 ** attempt)
    result['state'] = 'original_data_acquired' if any(row['features'] for row in result['layers'].values()) else 'original_source_empty'
    atomic(receipt, result)
    return result

def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    lock = (OUTPUT/'acquisition.lock').open('a+b')
    if os.fstat(lock.fileno()).st_size == 0: lock.write(b'0'); lock.flush()
    lock.seek(0)
    try: msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError: raise SystemExit('Original source acquisition already running')
    key = vworld.vworld_key()
    if not key: raise SystemExit('Configured VWorld API credential unavailable')
    regions = sorted(json.loads((ROOT/'national-buildings-pass-3.json').read_text())['missingRegions'],
                     key=lambda row: row['missingDatum'], reverse=True)
    results = []
    def status(state):
        counts = {name: sum(row['state'] == name for row in results) for name in
                  ('original_data_acquired', 'original_source_empty', 'request_failed')}
        atomic(ROOT/'national-gap-acquisition.json', {'pid': os.getpid(), 'at': time.time(), 'state': state,
               'total': len(regions), 'completed': len(results), 'counts': counts, 'output': str(OUTPUT),
               'published': False, 'note': 'Source feature presence is not proof of building ground coverage.'})
    status('acquiring_original_sources')
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(acquire, region, key) for region in regions]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            status('acquiring_original_sources')
            print(json.dumps({'completed': len(results), 'total':len(regions), 'region':result['region'],
                              'state': result['state'], 'features': {k:v['features'] for k,v in result['layers'].items()}}), flush=True)
    atomic(ROOT/'national-gap-acquisition-results.json', results)
    status('source_acquisition_finished')

if __name__ == '__main__': main()
