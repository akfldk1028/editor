import source_job_paths as sjp
import collections,json,re,time
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
from pyproj import Transformer
ROOT=Path(str(sjp.NGII_ORIGINAL_ROOT))
records=json.loads(Path(str(sjp.NGII_DEM_ROOT / 'national-gap-exact-points.json')).read_text(encoding='utf-8'))
ll=np.array([r['point'] for r in records]);x,y=Transformer.from_crs(4326,5179,always_xy=True).transform(ll[:,0],ll[:,1]);points=np.column_stack([x,y]);tree=cKDTree(points)
available=set();geometry_files=0
for path in ROOT.glob('*-manifest.json'):
 for file in json.loads(path.read_text(encoding='utf-8'))['files']:
  if not file['name'].endswith(('.zip','.dxf')):continue
  match=re.search(r'_(\d{8,9})_\d{4}_',file['name'])
  if match:available.add(match[1]);geometry_files+=1
catalogue=set();covered=set();downloadable_covered=set()
for path in ROOT.glob('*-catalogue.json'):
 for row in json.loads(path.read_text(encoding='utf-8')):
  if int(row.get('scale') or 999999)>5000 or row.get('projection')!='GRS80':continue
  sheet=row['sheet']
  if sheet in catalogue:continue
  catalogue.add(sheet);a,b,c,d=[row[k] for k in ['minx','miny','maxx','maxy']]
  nearby=tree.query_ball_point([(a+c)/2,(b+d)/2],np.hypot(c-a,d-b)/2)
  exact=[i for i in nearby if a<=x[i]<=c and b<=y[i]<=d];covered.update(exact)
  if sheet in available:downloadable_covered.update(exact)
result={'at':time.time(),'knownMissingRecordsBeforeLast2PointRepair':len(records),'preciseCatalogueSheets':len(catalogue),'preciseDownloadableSheets':len(available&catalogue),'missingPointsInsideCatalogueRectangles':len(covered),'missingPointsInsideDownloadableRectangles':len(downloadable_covered),'missingPointsOutsideAvailableRectangles':len(records)-len(downloadable_covered),'scope':'Optimistic bounding-rectangle coverage only, not actual contour/spot support or repair completion'}
(ROOT/'catalogue-coverage.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
