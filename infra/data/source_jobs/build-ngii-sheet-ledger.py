"""Reconcile observed NGII sheet catalogues with actual files, layers and processing."""
import source_job_paths as sjp
import collections,json,re,time,zipfile
from pathlib import Path
ROOT=Path(str(sjp.NGII_ORIGINAL_ROOT))
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
sheets={};file_to_sheet={}
for path in ROOT.glob('*-catalogue.json'):
 region='41480' if path.stem=='paju-catalogue' else path.stem.split('-')[0]
 for row in read(path):
  key=str(row.get('scale'))+'/'+row['sheet']
  item=sheets.setdefault(key,{'sheet':row['sheet'],'scale':row.get('scale'),'years':set(),'regions':set(),'bboxEPSG5179':[row[k] for k in ['minx','miny','maxx','maxy']],'files':{},'layerCodes':set()})
  item['years'].add(str(row.get('year','')));item['regions'].add(region)
  file_to_sheet.setdefault(row['sheet'],set()).add(key)
for path in ROOT.glob('*-manifest.json'):
 for row in read(path)['files']:
  match=re.search(r'_([A-Z0-9-]+)_(\d{4})_',row['name'])
  if not match:continue
  for key in file_to_sheet.get(match[1],[]):
   sheets[key]['files'][row['name']]={'name':row['name'],'expectedBytes':row['bytes'],'downloaded':False,'sha256Recorded':False,'stageState':None,'verifiedNewGroundRecords':0,'published':False}
stage_path=ROOT/'terrain-stage-status.json';stage=read(stage_path).get('results',{}) if stage_path.exists() else {}
install_path=ROOT/'terrain-install-receipt.json'
installed={r['sourceSHA256'] for r in read(install_path).get('installed',[])} if install_path.exists() else set()
for item in sheets.values():
 for name,file in item['files'].items():
  path=ROOT/'files'/name;receipt=path.with_suffix(path.suffix+'.receipt.json')
  if path.exists() and receipt.exists():
   record=read(receipt);file['downloaded']=path.stat().st_size==file['expectedBytes']==record['bytes'];file['sha256Recorded']=bool(record.get('sha256'))
   if path.suffix=='.xml' and record.get('state')=='xml_verified_manifest_size_mismatch' and record.get('manifestBytes')==file['expectedBytes'] and path.stat().st_size==record['bytes']:
    file['downloaded']=True;file['metadataSizeException']=True
   if file['downloaded'] and path.suffix=='.zip':
    try:
     with zipfile.ZipFile(path) as archive:item['layerCodes'].update(Path(n).stem for n in archive.namelist() if n.endswith('.shp'))
    except zipfile.BadZipFile:file['archiveInvalid']=True
  result=stage.get(name,{})
  file.pop('published',None)
  file['stageState']=result.get('state');file['verifiedNewGroundRecords']=len(result.get('verifiedKeys',[]));file['groundPatchPublished']=result.get('sourceSHA256') in installed
 item['files']=list(item['files'].values());item['years']=sorted(item['years']);item['regions']=sorted(item['regions']);item['layerCodes']=sorted(item['layerCodes'])
 item['downloadedFiles']=sum(f['downloaded'] for f in item['files']);item['providedFiles']=len(item['files'])
 item['state']='catalogued_no_file_provided' if not item['files'] else 'download_complete' if item['downloadedFiles']==len(item['files']) else 'download_partial' if item['downloadedFiles'] else 'download_pending'
report={'at':time.time(),'scope':'Observed original B010 package sheets, not an authoritative complete national sheet inventory. Existing nationwide B020 sources remain separate. Download completion is not geometry validation or service publication.','summary':dict(collections.Counter(s['state'] for s in sheets.values())),'sheets':list(sheets.values())}
path=ROOT/'sheet-ledger.json';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8');tmp.replace(path)
print(json.dumps({'sheets':len(sheets),'summary':report['summary']}))
