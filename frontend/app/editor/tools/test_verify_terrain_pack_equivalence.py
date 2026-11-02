import gzip
import hashlib
import json
import sqlite3
import struct
import time
import pytest
from pmtiles.writer import write
from pmtiles.tile import TileType,Compression,zxy_to_tileid
from verify_terrain_pack_equivalence import verify,digest


def sample(tmp_path,count=3):
 base=tmp_path/'base.pmtiles';overlay=tmp_path/'overlay.sqlite';packed=tmp_path/'packed.pmtiles'
 bm={'maxLevel':20,'vrt_sha256':'a'*64,'sourceFilesSHA256':'b'*64,'recursiveSourceFilesSHA256':'c'*64,'schema':'ngii-heightmap-v1','size':33,'archiveZoomOffset':1}
 header=dict(tile_type=TileType.UNKNOWN,tile_compression=Compression.GZIP,min_lon_e7=-1800000000,min_lat_e7=-900000000,max_lon_e7=1800000000,max_lat_e7=900000000)
 rows=[(i,gzip.compress(b'HTM1!\0\0\0'+struct.pack('<1089f',*[float(j+i) for j in range(1089)]),mtime=0)) for i in range(count)]
 def archive(path,entries,metadata):
  with write(str(path)) as w:
   for k,v in entries:w.write_tile(k,v)
   w.finalize(header,metadata)
 archive(base,rows,bm);pins={'terrainSHA256':hashlib.sha256(base.read_bytes()).hexdigest(),'snapshotSHA256':'d'*64,'planFileSHA256':'e'*64,'regionsSHA256':'f'*64}
 identity=json.dumps({'sourcePins':pins,'contract':'resolved-ancestor-grid-v1','sampleOnly':True,'selected':['14/1/1'],'recipe':'native-anchor-adaptive-grid-v1'},sort_keys=True,separators=(',',':'));ih=digest(identity.encode())
 tileid=zxy_to_tileid(17,100,100);payload=rows[0][1]
 proof={'sampleOnly':True,'complete':False,'passed':True,'finalNeighbourCheck':True,'independentPackedArchiveVerificationRequired':True,'identitySHA256':ih,'baseArchiveSHA256':pins['terrainSHA256'],'regions':1,'expectedRegions':25938,'nativeFinite':5,'nativeNoData':2,'maximumAbsoluteErrorMetres':.4,'added':{'tiles':1,'bytes':len(payload)},'sourceFingerprint':{'sourceVrtSHA256':'a'*64,'sourceFilesSHA256':'b'*64,'recursiveSourceFilesSHA256':'c'*64}}
 proofraw=json.dumps(proof);db=sqlite3.connect(overlay);db.executescript('CREATE TABLE metadata(key,value);CREATE TABLE regions(owner,receipt);CREATE TABLE final_checks(owner,receipt);CREATE TABLE tiles(id INTEGER PRIMARY KEY,level,x,y,data,decoded_sha256);');db.executemany('INSERT INTO metadata VALUES(?,?)',[('identity',identity),('verification',proofraw),('finalGeneration',json.dumps({'n':1,'last':tileid}))]);db.execute('INSERT INTO regions VALUES(?,?)',('14/1/1','{"passed":true}'));db.execute('INSERT INTO final_checks VALUES(?,?)',('14/1/1',json.dumps({'nativeFinite':5,'nativeNoData':2,'maximum':.4})));db.execute('INSERT INTO tiles VALUES(?,?,?,?,?,?)',(tileid,16,100,100,payload,digest(gzip.decompress(payload))));db.commit();db.close()
 pm={**bm,'maxLevel':20,'adaptiveRefinement':{'recipe':'native-anchor-adaptive-grid-v1','baseArchiveSHA256':pins['terrainSHA256'],'identitySHA256':ih,'sampleOnly':True},'explicitNoData':True,'tiles':count+1};archive(packed,rows+[(tileid,payload)],pm)
 return (base,overlay,packed),dict(proof_sha=digest(proofraw.encode()),identity_sha=ih,source_pins=pins,allow_sample=True),archive,rows+[(tileid,payload)],pm


def test_exact_sample_is_not_national_or_fresh_native(tmp_path):
 args,kw,*_=sample(tmp_path)
 result=verify(*args,**kw);assert result['passed'] and not result['complete'] and not result['nativeFresh'];assert result['tiles']==4 and result['nativeNoData']==2
 with pytest.raises(ValueError,match='Sample'):verify(*args,**{**kw,'allow_sample':False})


@pytest.mark.parametrize('change',['payload','missing','extra','metadata','decoded','owners','native','identity','active'])
def test_rejects_invalid_transfer(tmp_path,change):
 args,kw,archive,rows,metadata=sample(tmp_path);base,overlay,packed=args
 if change=='payload':archive(packed,[(k,v+b'X') if i==0 else(k,v) for i,(k,v) in enumerate(rows)],metadata)
 elif change=='missing':archive(packed,rows[:-1],metadata)
 elif change=='extra':archive(packed,rows+[(rows[-1][0]+1,rows[-1][1])],metadata)
 elif change=='metadata':archive(packed,rows,{**metadata,'size':65})
 elif change=='identity':kw['identity_sha']='0'*64
 elif change=='active':(tmp_path/'refinement.lock').write_text('active')
 else:
  with sqlite3.connect(overlay) as db:
   if change=='decoded':db.execute("UPDATE tiles SET decoded_sha256='bad'")
   if change=='owners':db.execute('DELETE FROM final_checks')
   if change=='native':db.execute('UPDATE final_checks SET receipt=?',(json.dumps({'nativeFinite':5,'nativeNoData':2,'maximum':.7}),))
 with pytest.raises(ValueError):verify(*args,**kw)


def test_small_streaming_benchmark(tmp_path):
 args,kw,*_=sample(tmp_path,1000);r=verify(*args,**kw);print('\nPACK_EQ_SAMPLE',json.dumps({k:r[k] for k in ['tiles','payloadBytes','elapsedSeconds','sampleOnly']}));assert r['tiles']==1001


def external_fixture(tmp_path):
 from verify_terrain_pack_equivalence import file_sha
 args,kw,archive,rows,pm=sample(tmp_path);base,overlay,packed=args
 def put(name,value):
  p=tmp_path/name;p.write_text(json.dumps(value,indent=2));return p
 snapshot=put('snapshot.json',{'complete':True});plan=put('plan.json',{'planSHA256':'e'*64,'expectedRows':7})
 regions=put('regions.json',{'schema':'ngii-canonical-regions-v1','sourceComplete':True,'planSHA256':'e'*64,'sourceRows':7,'regionCount':1,'buildingCount':7,'regions':[{'region14':'14/1/1','buildings':7,'components':8}]})
 with sqlite3.connect(overlay) as db:
  meta=dict(db.execute('SELECT key,value FROM metadata'));identity=json.loads(meta['identity']);proof=json.loads(meta['verification'])
  pins={**identity['sourcePins'],'snapshotSHA256':file_sha(snapshot),'planFileSHA256':file_sha(plan),'regionsSHA256':file_sha(regions),'terrainPath':str(base),'regionsPath':str(regions)}
  identity.update(sourcePins=pins,sourcePlanSHA256='e'*64,sampleOnly=False);raw=json.dumps(identity,sort_keys=True,separators=(',',':'));ih=digest(raw.encode())
  proof.update(sampleOnly=False,complete=True,expectedRegions=1,identitySHA256=ih)
  db.execute("UPDATE metadata SET value=? WHERE key='identity'",(raw,));db.execute("UPDATE metadata SET value=? WHERE key='verification'",(json.dumps(proof,separators=(',',':')),));db.execute('UPDATE regions SET receipt=?',(json.dumps({'passed':True,'buildings':7}),))
 pm['adaptiveRefinement'].update(identitySHA256=ih,sampleOnly=False);archive(packed,rows,pm)
 inputs=put('inputs.json',identity);proof_file=put('proof.json',proof);queue=put('queue.json',pins)
 return dict(base=base,overlay=overlay,packed=packed,inputs=inputs,proof=proof_file,inputs_file_sha=file_sha(inputs),proof_file_sha=file_sha(proof_file),regions=regions,snapshot=snapshot,plan=plan,queue_inputs=queue,output=tmp_path/'result.json')


def test_cli_proof_pins_pretty_file_and_sqlite_separately_and_resumes(tmp_path,monkeypatch):
 import verify_terrain_pack_equivalence as m
 monkeypatch.setattr(m.shutil,'disk_usage',lambda _:type('Space',(),{'free':10**15})())
 kw=external_fixture(tmp_path);result=m.verify_files(**kw)
 assert result['complete'] and result['compared']==7 and result['nativeNoData']==2 and not result['nativeFresh']
 assert result['sourceProofFileSHA256']!=result['sourceProofSHA256']
 assert m.verify_files(**kw)==result
 result['nativeFresh']=True;kw['output'].write_text(json.dumps(result))
 with pytest.raises(ValueError,match='Existing proof'):m.verify_files(**kw)


@pytest.mark.parametrize('failure',['file_sha','semantic','count','source','stop','storage'])
def test_cli_rejects_unbound_incomplete_or_stopped_evidence(tmp_path,monkeypatch,failure):
 import verify_terrain_pack_equivalence as m
 monkeypatch.setattr(m.shutil,'disk_usage',lambda _:type('Space',(),{'free':0 if failure=='storage' else 10**15})())
 kw=external_fixture(tmp_path)
 if failure=='file_sha':kw['proof_file_sha']='0'*64
 elif failure=='semantic':
  value=json.loads(kw['proof'].read_text());value['nativeNoData']=1;kw['proof'].write_text(json.dumps(value));kw['proof_file_sha']=m.file_sha(kw['proof'])
 elif failure=='count':
  with sqlite3.connect(kw['overlay']) as db:db.execute('UPDATE regions SET receipt=?',(json.dumps({'passed':True,'buildings':6}),))
 elif failure=='source':kw['snapshot'].write_text('{}')
 elif failure=='stop':kw['stop_file']=tmp_path/'STOP';kw['stop_file'].write_text('stop')
 with pytest.raises((ValueError,InterruptedError)):m.verify_files(**kw)
 assert not kw['output'].exists()


def test_stop_during_tile_scan_never_returns_pass(tmp_path):
 args,kw,*_=sample(tmp_path,1000);calls=0
 def stop():
  nonlocal calls
  calls+=1;return calls>=2
 with pytest.raises(InterruptedError):verify(*args,**kw,stop=stop)
