import source_job_paths as sjp
import importlib.util,json,time
from pathlib import Path
import pyogrio
from pyproj import Transformer
root=Path(str(sjp.SOURCE_DATA_ROOT / 'raw/ngii_map/b020/_전국/(B020)연속수치지형도_전국'))
tx=Transformer.from_crs(4326,5179,always_xy=True)
spec=importlib.util.spec_from_file_location('sampler',str(sjp.EDITOR_ROOT / 'frontend/app/editor/tools/sample-building-dem.py'));sampler=importlib.util.module_from_spec(spec);spec.loader.exec_module(sampler)
cities={'Daegu':[128.6014,35.8714],'Busan':[129.0756,35.1796]};rows=[]
for city,point in cities.items():
 x,y=tx.transform(*point);bbox=(x-1000,y-1000,x+1000,y+1000);sources=[]
 for path in [*root.glob('N3L_F001*.shp'),root/'N3P_F0020000.shp',*root.glob('N3L_A002*.shp'),*root.glob('N3A_A001*.shp')]:
  info=pyogrio.read_info(path);a,b,c,d=info['total_bounds']
  if c<bbox[0] or a>bbox[2] or d<bbox[1] or b>bbox[3]:continue
  frame=pyogrio.read_dataframe(path,bbox=bbox,read_geometry=False)
  if len(frame):sources.append({'file':path.name,'features':len(frame),'crs':info['crs']})
 heights=sampler.sample(str(sjp.NGII_DEM_ROOT / 'ngii_dem.vrt'),[point])['heights']
 app=Path(str(sjp.DATA_ROOT))
 catalog=json.loads((app/'world-buildings/catalog.json').read_text(encoding='utf-8'))
 region=next(r for r in catalog['regions'] if r['bounds'][0]<=point[0]<=r['bounds'][2] and r['bounds'][1]<=point[1]<=r['bounds'][3])
 footprints=json.loads((app/region['footprints'].lstrip('/')).read_text(encoding='utf-8'))
 rows.append({'city':city,'point':point,'sampleWindowMeters':2000,'originalSources':sources,'liveLocalTerrainHeight':heights[0],'buildingTile':region['id'],'buildingTileRecordCount':len(footprints),'buildingHeightCategories':region['counts']})
report={'at':time.time(),'scope':'Two city-center source/terrain samples; not citywide or visual validation','samples':rows}
Path(str(sjp.NGII_DEM_ROOT / 'busan-daegu-source-check.json')).write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
