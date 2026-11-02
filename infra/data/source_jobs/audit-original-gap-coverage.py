"""Test whether acquired original contours can interpolate the actual missing locations."""
import source_job_paths as sjp
import collections, json, time, os
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
import numpy as np
from pyproj import Transformer
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import cKDTree, QhullError
from shapely import get_coordinates
from shapely.geometry import shape

ROOT = Path(str(sjp.NGII_DEM_ROOT))
SOURCES = Path(str(sjp.DATA_ROOT / 'ngii-ground-gap-sources'))
to_dem = Transformer.from_crs(4326, 5186, always_xy=True)
groups = collections.defaultdict(list)
for row in json.loads((ROOT/'national-gap-exact-points.json').read_text()): groups[row['region']].append(row)
results = {}
while True:
    for region, records in groups.items():
        if region in results: continue
        folder = SOURCES / region.replace('/', '-')
        receipt_path = folder/'receipt.json'
        if not receipt_path.exists(): continue
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        row = {'region':region, 'missingRecords':len(records), 'supportedByOriginalTIN':0,
               'state':receipt['state']}
        if receipt['state'] == 'original_data_acquired':
            chunks = []
            for layer, column in [('contours','cont'),('spot_heights','nume')]:
                for feature in json.loads((folder/f'{layer}.geojson').read_text(encoding='utf-8'))['features']:
                    try: z = float(feature['properties'][column])
                    except (KeyError, ValueError, TypeError): continue
                    if not np.isfinite(z) or not -500 <= z <= 9000 or not feature.get('geometry'): continue
                    xy = get_coordinates(shape(feature['geometry']))
                    x,y = to_dem.transform(xy[:,0],xy[:,1])
                    chunks.append(np.column_stack([x,y,np.full(len(xy),z)]))
            if chunks:
                points = np.unique(np.vstack(chunks),axis=0)
                row['sourceVertices'] = len(points)
                if len(points) >= 3:
                    query = np.asarray([record['point'] for record in records])
                    x,y = to_dem.transform(query[:,0],query[:,1]); xy=np.column_stack([x,y])
                    try:
                        heights = LinearNDInterpolator(points[:,:2],points[:,2])(xy)
                        distances,_ = cKDTree(points[:,:2]).query(xy,distance_upper_bound=1000)
                        valid = np.isfinite(heights) & np.isfinite(distances)
                        row['supportedByOriginalTIN'] = int(valid.sum())
                        row['supportedKeys'] = [record['key'] for record, ok in zip(records,valid) if ok]
                    except QhullError: row['state']='insufficient_spatial_support'
        results[region] = row
    report = {'pid':os.getpid(),'at':time.time(),'regionsAudited':len(results),'totalRegions':len(groups),
              'missingRecords':sum(row['missingRecords'] for row in results.values()),
              'supportedByOriginalTIN':sum(row['supportedByOriginalTIN'] for row in results.values()),
              'published':False,'method':'Original NGII contours/spot heights; Delaunay TIN; inside hull and within1000m of original vertex. Point support only, not published raster coverage.',
              'regions':list(results.values())}
    tmp=ROOT/'national-original-gap-coverage.tmp';tmp.write_text(json.dumps(report,indent=2));tmp.replace(ROOT/'national-original-gap-coverage.json')
    print(json.dumps({k:v for k,v in report.items() if k!='regions'}),flush=True)
    status=json.loads((ROOT/'national-gap-acquisition.json').read_text())
    if status['state']=='source_acquisition_finished' and len(results)==len(groups): break
    time.sleep(10)
