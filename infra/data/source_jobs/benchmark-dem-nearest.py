import source_job_paths as sjp
from pathlib import Path
import numpy as np,time,json
from scipy.spatial import cKDTree
paths=sorted(Path(str(sjp.NGII_DEM_ROOT / 'national-work')).glob('*.npy'),key=lambda p:p.stat().st_size,reverse=True)
for path in paths:
 try: points=np.load(path);break
 except FileNotFoundError:continue
x0,y0=map(int,path.stem.split('_')[-2:])
tree=cKDTree(points[:,:2]); xs=x0+(np.arange(2000)+.5)*5;ys=y0+10000-(np.arange(2000)+.5)*5
result=[]; reference=None
for workers in [1,2,1,2]:
 start=time.perf_counter();masks=[]
 for i in range(0,2000,128):
  x,y=np.meshgrid(xs,ys[i:i+128]);dist,_=tree.query(np.column_stack([x.ravel(),y.ravel()]),distance_upper_bound=1000,workers=workers);masks.append(np.isinf(dist))
 mask=np.concatenate(masks)
 if reference is None:reference=mask
 result.append({'workers':workers,'seconds':round(time.perf_counter()-start,3),'identical_void_mask':bool(np.array_equal(reference,mask))})
report={'block':path.stem,'points':len(points),'runs':result}
Path(str(sjp.INDEX_STATE_ROOT / 'dem-nearest-parallel-benchmark.json')).write_text(json.dumps(report,indent=2))
print(json.dumps(report))
