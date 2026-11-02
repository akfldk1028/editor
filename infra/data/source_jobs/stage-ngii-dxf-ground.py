"""Stage supported original terrain for gap filling or opt-in existing-ground refinement."""
import source_job_paths as sjp
import argparse,hashlib,importlib.util,json,os,re,time,zipfile
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import ezdxf,numpy as np,rasterio,pyogrio
from shapely import get_coordinates
from pyproj import Transformer
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import cKDTree
from rasterio.transform import from_origin
from ngii_sheet_match import select_sheet, elevation_kind
from ngii_ngi import parse_elevation
from ngii_stage_policy import acquire_stage_lock, attribute_companion_arrived, load_source_list, may_stage, should_retry, supported_values
from ngii_dxf import parse_elevation as parse_dxf_elevation, PARSER_VERSION as DXF_PARSER_VERSION, needs_reparse, raster_name

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--refine-existing',action='store_true',help='Stage supported original terrain even without known missing buildings')
parser.add_argument('--once',action='store_true',help='Process currently available files once, even while downloads continue')
parser.add_argument('--source-list',type=Path,help='JSON array of exact original filenames; preserve all other source results')
args=parser.parse_args()
ROOT=Path(str(sjp.NGII_ORIGINAL_ROOT));OUT=ROOT/'terrain-staging';OUT.mkdir(exist_ok=True)
stage_lock=acquire_stage_lock(ROOT/'terrain-stage.lock')
source_list=load_source_list(args.source_list,ROOT)
selected_source=lambda name:source_list is None or name in source_list
spec=importlib.util.spec_from_file_location('sampler',str(sjp.EDITOR_ROOT / 'frontend/app/editor/tools/sample-building-dem.py'))
sampler=importlib.util.module_from_spec(spec);spec.loader.exec_module(sampler)
records=json.loads(Path(str(sjp.NGII_DEM_ROOT / 'national-gap-exact-points.json')).read_text())
ll=np.array([r['point'] for r in records],dtype=float).reshape(-1,2);tx=Transformer.from_crs(4326,5179,always_xy=True);qx,qy=tx.transform(ll[:,0],ll[:,1]);query5179=np.column_stack([qx,qy])
report_path=ROOT/'terrain-stage-status.json'
results={}
if report_path.exists():results=json.loads(report_path.read_text(encoding='utf-8')).get('results',{})
previous_dxf={k:v for k,v in results.items() if selected_source(k) and needs_reparse(k,v)}
results={k:v for k,v in results.items() if k not in previous_dxf}
results={k:v for k,v in results.items() if not (selected_source(k) and k.endswith('.zip') and v.get('state')=='no_elevation_geometry')}
results={k:v for k,v in results.items() if not (selected_source(k) and v.get('state')=='conflicting_catalogue_rejected')}
results={k:v for k,v in results.items() if not (selected_source(k) and should_retry(v.get('state'),args.refine_existing))}
results={k:v for k,v in results.items() if not (selected_source(k) and attribute_companion_arrived(k,v,ROOT))}
def checkpoint(state):
 for name,result in results.items():
  if selected_source(name) and Path(name).suffix.lower()=='.dxf':
   result.setdefault('parserVersion',DXF_PARSER_VERSION)
   if name in previous_dxf and previous_dxf[name].get('file'):
    result.setdefault('supersedes',{'file':previous_dxf[name]['file'],'sourceSHA256':previous_dxf[name].get('sourceSHA256'),'parserVersion':previous_dxf[name].get('parserVersion','legacy-lwpolyline-only')})
 keys=set(k for r in results.values() for k in r.get('verifiedKeys',[]))
 data={'pid':os.getpid(),'state':state,'at':time.time(),'mode':'precision-refinement' if args.refine_existing else 'missing-ground',
  'filesChecked':len(results),'stagedPatches':sum(r.get('state')=='staged' for r in results.values()),
  'precisionStagedPatches':sum(r.get('state')=='staged' and r.get('stagingMode')=='precision-refinement' for r in results.values()),
  'failedSources':sum(r.get('state')=='failed' for r in results.values()),
  'excludedSources':sum(r.get('state') not in ('staged','failed') for r in results.values()),
  'validation':'completed_with_failures' if any(r.get('state')=='failed' for r in results.values()) else 'checked_with_source_exclusions' if any(r.get('state')!='staged' for r in results.values()) else 'checked',
  'verifiedMissingRecords':len(keys),'published':False,'results':results}
 temp=report_path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
 for attempt in range(30):
  try:temp.replace(report_path);break
  except PermissionError:
   if attempt==29:raise
   time.sleep(.1)
while True:
 status=ROOT/'download-status.json'
 downloads_finished_at_start=status.exists() and json.loads(status.read_text(encoding='utf-8')).get('state','').startswith('finished')
 catalogue={}
 for path in ROOT.glob('*-catalogue.json'):
  for row in json.loads(path.read_text(encoding='utf-8')):
   if row.get('projection')=='GRS80' and int(row.get('scale') or 999999)<=5000:catalogue.setdefault(row['sheet'],[]).append(row)
 for path in [*(ROOT/'files').glob('*.zip'),*(ROOT/'files').glob('*.dxf'),*(ROOT/'files').glob('*.ngi')]:
  if not selected_source(path.name):continue
  if path.name in results or not path.with_suffix(path.suffix+'.receipt.json').exists():continue
  match=re.search(r'_(\d{8,9})_(\d{4})_',path.name)
  if not match:results[path.name]={'state':'coarse_or_unknown_scale_excluded'};continue
  try:row=select_sheet(catalogue.get(match[1],[]),match[1],match[2])
  except ValueError:
   results[path.name]={'state':'conflicting_catalogue_rejected'};continue
  if row is None:
   results[path.name]={'state':'no_precise_catalogue_match'};continue
  bounds=np.array([row[k] for k in ['minx','miny','maxx','maxy']])
  nearby=np.where((qx>=bounds[0])&(qx<=bounds[2])&(qy>=bounds[1])&(qy<=bounds[3]))[0]
  if not may_stage(len(nearby),args.refine_existing):results[path.name]={'state':'no_known_missing_point_in_sheet'};continue
  try:
   source_hash=hashlib.file_digest(path.open('rb'),'sha256').hexdigest()
   receipt=json.loads(path.with_suffix(path.suffix+'.receipt.json').read_text(encoding='utf-8'))
   if source_hash!=receipt['sha256']:raise ValueError('source checksum changed')
   chunks=[];contours=spots=0;declared_crs=None;attribute_source={}
   if path.suffix=='.zip':
    with zipfile.ZipFile(path) as archive:
     for member in archive.namelist():
      kind=elevation_kind(member)
      if kind is None:continue
      frame=pyogrio.read_dataframe('/vsizip/'+path.as_posix()+'/'+member)
      if not frame.crs:raise ValueError('Missing source CRS')
      frame=frame.to_crs(5186);declared_crs=5186
      column='등고수치' if kind=='contour' else '수치'
      if column not in frame:
       frame=pyogrio.read_dataframe('/vsizip/'+path.as_posix()+'/'+member,encoding='CP949').to_crs(5186)
      if column not in frame:raise ValueError('Missing measured height column')
      for _,feature in frame.iterrows():
       z=float(feature[column]);xy=get_coordinates(feature.geometry)
       if len(xy):chunks.append(np.column_stack([xy,np.full(len(xy),z)]))
      if kind=='contour':contours+=len(frame)
      else:spots+=len(frame)
   elif path.suffix=='.ngi':
    nda=path.with_suffix('.nda');nda_receipt=json.loads(nda.with_suffix('.nda.receipt.json').read_text(encoding='utf-8'))
    nda_hash=hashlib.file_digest(nda.open('rb'),'sha256').hexdigest()
    if nda_hash!=nda_receipt['sha256']:raise ValueError('Attribute source checksum changed')
    chunks,contours,spots=parse_elevation(path.read_text(encoding='cp949'),nda.read_text(encoding='cp949'))
    attribute_source={'attributeSource':nda.name,'attributeSHA256':nda_hash}
   else:
    doc=ezdxf.readfile(path)
    chunks,contours,spots=parse_dxf_elevation(doc)
   if not chunks:results[path.name]={'state':'no_elevation_geometry'};continue
   points=np.unique(np.vstack(chunks),axis=0);points=points[np.isfinite(points).all(axis=1)&(points[:,2]>=-500)&(points[:,2]<=9000)]
   if len(points)<3:results[path.name]={'state':'insufficient_elevation_geometry'};continue
   candidates=[]
   sample=points[::max(1,len(points)//2000)]
   for epsg in ([declared_crs] if declared_crs else [5181,5182,5183,5184,5185,5186,5187,5188]):
    x,y=Transformer.from_crs(epsg,5179,always_xy=True).transform(sample[:,0],sample[:,1])
    inside=(x>=bounds[0]-30)&(x<=bounds[2]+30)&(y>=bounds[1]-30)&(y<=bounds[3]+30)
    if inside.mean()>.98:candidates.append(epsg)
   if len(candidates)!=1:results[path.name]={'state':'ambiguous_crs_rejected','candidates':candidates};continue
   crs=candidates[0];x,y=Transformer.from_crs(crs,5186,always_xy=True).transform(points[:,0],points[:,1]);points[:,:2]=np.column_stack([x,y])
   unique,idx=np.unique(points[:,:2],axis=0,return_index=True)
   if len(unique)!=len(points):
    groups={}
    for x,y,z in points:groups.setdefault((x,y),[]).append(z)
    if any(max(z)-min(z)>.2 for z in groups.values()):results[path.name]={'state':'conflicting_elevations_rejected'};continue
    points=points[idx]
   interp=LinearNDInterpolator(points[:,:2],points[:,2]);tree=cKDTree(points[:,:2])
   x,y=Transformer.from_crs(4326,5186,always_xy=True).transform(ll[nearby,0],ll[nearby,1]);query=np.column_stack([x,y])
   supported=np.isfinite(supported_values(interp,tree,query))
   selected=nearby[supported]
   if not may_stage(len(selected),args.refine_existing):results[path.name]={'state':'no_missing_point_supported','sourceEPSG':crs};continue
   left,bottom=np.floor(points[:,:2].min(axis=0)/5)*5;right,top=np.ceil(points[:,:2].max(axis=0)/5)*5
   width,height=int((right-left)/5),int((top-bottom)/5)
   if width*height>4_000_000:raise ValueError('Raster budget exceeded')
   gx,gy=np.meshgrid(left+(np.arange(width)+.5)*5,top-(np.arange(height)+.5)*5);grid=np.column_stack([gx.ravel(),gy.ravel()])
   values=supported_values(interp,tree,grid);supported_cells=int(np.isfinite(values).sum())
   if not supported_cells:results[path.name]={'state':'no_supported_raster_cells','sourceEPSG':crs};continue
   values[~np.isfinite(values)]=-9999
   dest=OUT/raster_name(match[1],source_hash,path.name)
   grid_values=values.reshape(height,width).astype('float32');transform=from_origin(left,top,5,5)
   if dest.exists():
    with rasterio.open(dest) as existing:
     if existing.crs.to_epsg()!=5186 or existing.transform!=transform or existing.nodata!=-9999 or not np.array_equal(existing.read(1),grid_values):raise ValueError('Existing staged raster differs; refusing to overwrite')
   else:
    temporary=dest.with_suffix('.tif.tmp')
    with rasterio.open(temporary,'w',driver='GTiff',crs='EPSG:5186',transform=transform,width=width,height=height,count=1,dtype='float32',nodata=-9999,compress='deflate',tiled=True) as target:target.write(grid_values,1)
    temporary.replace(dest)
   positions=ll[selected].tolist();before=sampler.sample(str(sjp.NGII_DEM_ROOT / 'ngii_dem.vrt'),positions)['heights'] if positions else [];after=sampler.sample(str(dest),positions)['heights'] if positions else []
   keys=[records[i]['key'] for i,a,b in zip(selected,before,after) if a is None and b is not None]
   results[path.name]={'state':'staged','file':str(dest),'sourceSHA256':source_hash,'sourceEPSG':crs,'sourceVertices':len(points),'contours':contours,'spotSymbols':spots,'verifiedKeys':keys,'scale':row['scale'],'resolution_m':5,'published':False,
    'stagingMode':'precision-refinement' if args.refine_existing else 'missing-ground','supportedCells':supported_cells,**attribute_source}
  except Exception as error:results[path.name]={'state':'failed','errorType':type(error).__name__}
  checkpoint('running')
 checkpoint('running')
 status=ROOT/'download-status.json'
 if args.once or downloads_finished_at_start:break
 time.sleep(10)
checkpoint('finished')
