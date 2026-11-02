"""Stage patches supported by original NGII vertices, without modifying the live mosaic."""
import source_job_paths as sjp
import hashlib, importlib.util, json, math, os, time
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import numpy as np
import rasterio
from rasterio.transform import from_origin
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import cKDTree
from pyproj import Transformer
from shapely import get_coordinates
from shapely.geometry import shape

ROOT=Path(str(sjp.NGII_DEM_ROOT))
SOURCE=Path(str(sjp.DATA_ROOT / 'ngii-ground-gap-sources'))
OUTPUT=SOURCE/'validated-patches'
OUTPUT.mkdir(exist_ok=True)
to_dem=Transformer.from_crs(4326,5186,always_xy=True)
spec=importlib.util.spec_from_file_location('sampler',str(sjp.EDITOR_ROOT / 'frontend/app/editor/tools/sample-building-dem.py'))
sampler=importlib.util.module_from_spec(spec);spec.loader.exec_module(sampler)
candidates=json.loads((ROOT/'national-gap-exact-points.json').read_text())
rows=[]
for region in json.loads((ROOT/'national-original-gap-coverage.json').read_text())['regions']:
    if not region['supportedByOriginalTIN']:continue
    folder=SOURCE/region['region'].replace('/','-')
    receipt=json.loads((folder/'receipt.json').read_text(encoding='utf-8'))
    parts=[]
    for layer,column in [('contours','cont'),('spot_heights','nume')]:
        path=folder/f'{layer}.geojson'
        if hashlib.sha256(path.read_bytes()).hexdigest()!=receipt['layers'][layer]['sha256']:raise ValueError('Original source changed')
        for feature in json.loads(path.read_text(encoding='utf-8'))['features']:
            try:z=float(feature['properties'][column])
            except (TypeError,ValueError,KeyError):continue
            if not math.isfinite(z) or not -500<=z<=9000 or not feature.get('geometry'):continue
            xy=get_coordinates(shape(feature['geometry']));x,y=to_dem.transform(xy[:,0],xy[:,1])
            parts.append(np.column_stack([x,y,np.full(len(xy),z)]))
    points=np.unique(np.vstack(parts),axis=0)
    west,south,east,north=receipt['bbox']
    corners=np.array([to_dem.transform(lon,lat) for lon in (west,east) for lat in (south,north)])
    left,bottom=np.floor(corners.min(axis=0)/5)*5;right,top=np.ceil(corners.max(axis=0)/5)*5
    width,height=int((right-left)/5),int((top-bottom)/5)
    if width*height>4000000:raise ValueError('Patch exceeds bounded grid budget')
    gx,gy=np.meshgrid(left+(np.arange(width)+.5)*5,top-(np.arange(height)+.5)*5)
    query=np.column_stack([gx.ravel(),gy.ravel()])
    values=LinearNDInterpolator(points[:,:2],points[:,2])(query)
    distances,_=cKDTree(points[:,:2]).query(query,distance_upper_bound=1000)
    values[~np.isfinite(distances)]=-9999
    values[~np.isfinite(values)]=-9999
    path=OUTPUT/(region['region'].replace('/','-')+'.tif')
    with rasterio.open(path,'w',driver='GTiff',crs='EPSG:5186',transform=from_origin(left,top,5,5),width=width,height=height,count=1,dtype='float32',nodata=-9999,compress='deflate',tiled=True) as target:
        target.write(values.reshape(height,width).astype('float32'),1)
    keys=set(region['supportedKeys']);selected=[r for r in candidates if r['key'] in keys]
    query=[r['point'] for r in selected]
    before=sampler.sample(str(ROOT/'ngii_dem.vrt'),query)['heights']
    after=sampler.sample(str(path),query)['heights']
    row={'region':region['region'],'file':str(path),'sourceReceipt':str(folder/'receipt.json'),
         'before':before,'after':after,'keys':[r['key'] for r in selected],
         'verifiedNewSamples':sum(a is None and b is not None for a,b in zip(before,after)),
         'resolution_m':5,'kind':'derived','method':'Original NGII contours and spot heights; linear TIN;1000m support limit',
         'published':False}
    path.with_suffix('.json').write_text(json.dumps(row,indent=2));rows.append(row)
report={'at':time.time(),'patches':rows,'published':False,'verifiedNewSamples':sum(r['verifiedNewSamples'] for r in rows)}
(ROOT/'national-ground-patches.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
