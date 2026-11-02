"""Publish original-source additions only into currently empty ground cells."""
import source_job_paths as sjp
import hashlib,importlib.util,json,msvcrt,os,shutil,time,xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np,rasterio
from rasterio.windows import from_bounds

ROOT=Path(str(sjp.NGII_DEM_ROOT));SOURCE=Path(str(sjp.NGII_ORIGINAL_ROOT));STAGE=SOURCE/'publication-staging';STAGE.mkdir(exist_ok=True)
live=ROOT/'ngii_dem.vrt';receipt_path=SOURCE/'terrain-install-receipt.json'
lock=(ROOT/'ngii-package-install.lock').open('a+b');lock.write(b'0');lock.flush();lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
previous=json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.exists() else {'installed':[]}
done={r['sourceSHA256'] for r in previous['installed']}
report=json.loads((SOURCE/'terrain-stage-status.json').read_text(encoding='utf-8'))
rows=[(name,row) for name,row in report['results'].items() if row.get('verifiedKeys') and row['sourceSHA256'] not in done]
rows.sort(key=lambda nr:(0 if nr[0].endswith('.zip') else 1,-int(nr[0].split('_')[2]),nr[0]))
original=live.read_bytes();tree=ET.fromstring(original);band=tree.find('VRTRasterBand')
candidate=ROOT/'ngii-package-validation.vrt';candidate.write_bytes(original)
staged=[]
for name,row in rows:
 source=SOURCE/'files'/name
 if hashlib.file_digest(source.open('rb'),'sha256').hexdigest()!=row['sourceSHA256']:raise ValueError('Original source changed')
 if row.get('attributeSource'):
  attribute=SOURCE/'files'/row['attributeSource']
  if attribute.name!=row['attributeSource'] or hashlib.file_digest(attribute.open('rb'),'sha256').hexdigest()!=row['attributeSHA256']:raise ValueError('Attribute source changed')
 with rasterio.open(candidate) as base,rasterio.open(row['file']) as patch:
  if patch.crs!=base.crs or patch.res!=base.res or patch.res!=(5,5):raise ValueError('Raster alignment mismatch')
  offset=from_bounds(*patch.bounds,transform=base.transform)
  if any(abs(v-round(v))>1e-6 for v in (offset.col_off,offset.row_off,offset.width,offset.height)):raise ValueError('Subpixel offset')
  if offset.col_off<0 or offset.row_off<0 or offset.col_off+offset.width>base.width or offset.row_off+offset.height>base.height:raise ValueError('Patch outside existing mosaic')
  a=base.read(1,window=offset,masked=True);b=patch.read(1,masked=True)
  new=np.ma.getmaskarray(a)&~np.ma.getmaskarray(b)
  if not np.any(new):continue
  masked=np.full(b.shape,-9999,dtype='float32');masked[new]=b.data[new]
  filename='original_patch_b010_'+Path(row['file']).stem+'-'+hashlib.sha256(original).hexdigest()[:8]+'.tif'
  output=STAGE/filename;profile=patch.profile.copy();profile.update(nodata=-9999)
  with rasterio.open(output,'w',**profile) as target:target.write(masked,1)
  node=ET.Element('ComplexSource');ET.SubElement(node,'SourceFilename',relativeToVRT='0').text=str(output)
  ET.SubElement(node,'SourceBand').text='1';ET.SubElement(node,'NODATA').text='-9999'
  ET.SubElement(node,'SrcRect',xOff='0',yOff='0',xSize=str(patch.width),ySize=str(patch.height))
  ET.SubElement(node,'DstRect',xOff=str(round(offset.col_off)),yOff=str(round(offset.row_off)),xSize=str(patch.width),ySize=str(patch.height))
  band.insert(1,node)
  staged.append({'name':name,'sourceSHA256':row['sourceSHA256'],'output':str(output),'target':str(ROOT/'tiles'/filename),'newCells':int(new.sum()),'verifiedKeys':row['verifiedKeys'],'window':offset,'node':node})
  if row.get('attributeSource'):staged[-1].update(attributeSource=row['attributeSource'],attributeSHA256=row['attributeSHA256'])
 candidate.write_bytes(ET.tostring(tree))
if not staged:print(json.dumps({'newPatches':0}));raise SystemExit(0)
with rasterio.open(live) as before,rasterio.open(candidate) as after:
 for row in staged:
  a=before.read(1,window=row['window'],masked=True);b=after.read(1,window=row['window'],masked=True);valid=~np.ma.getmaskarray(a)
  if not np.array_equal(a.data[valid],b.data[valid]) or np.any(np.ma.getmaskarray(b)[valid]):raise ValueError('Existing ground changed')
  row['existingCellsPreserved']=int(valid.sum())
if live.read_bytes()!=original:raise ValueError('Mosaic changed before publication; retry against current version')
total=sum(Path(r['output']).stat().st_size for r in staged)
if shutil.disk_usage(ROOT).free<total+15_000_000_000:raise OSError('D drive reserve')
backup=ROOT/f'ngii-dem-before-package-{time.time_ns()}.vrt';backup.write_bytes(original)
for row in staged:
 target=Path(row['target']);temp=target.with_suffix('.installing');shutil.copyfile(row['output'],temp);temp.replace(target)
 node=row['node'].find('SourceFilename');node.set('relativeToVRT','1');node.text='tiles/'+target.name
candidate.write_bytes(ET.tostring(tree))
if live.read_bytes()!=original:raise ValueError('Mosaic changed during file publication; leave valid added sources and retry')
candidate.replace(live)
spec=importlib.util.spec_from_file_location('sampler',str(sjp.EDITOR_ROOT / 'frontend/app/editor/tools/sample-building-dem.py'));sampler=importlib.util.module_from_spec(spec);spec.loader.exec_module(sampler)
keys=set(k for row in staged for k in row['verifiedKeys']);records=[r for r in json.loads((ROOT/'national-gap-exact-points.json').read_text(encoding='utf-8')) if r['key'] in keys]
heights=sampler.sample(str(live),[r['point'] for r in records])['heights'];fixed=[r for r,h in zip(records,heights) if h is not None]
installed=[{k:v for k,v in row.items() if k not in ['window','node']} for row in staged]
result={'at':time.time(),'backup':str(backup),'installed':previous['installed']+installed,'verifiedKeys':sorted(set(previous.get('verifiedKeys',[]))|{r['key'] for r in fixed}),'regions':sorted(set(previous.get('regions',[]))|{r['region'] for r in fixed}),'buildingRebakeComplete':False}
temp=receipt_path.with_suffix('.tmp');temp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(receipt_path)
print(json.dumps({'installedPatches':len(staged),'verifiedKeys':len(result['verifiedKeys']),'affectedRegions':len(result['regions'])}))
