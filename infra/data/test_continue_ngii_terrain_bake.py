from pathlib import Path
import pytest

from continue_ngii_terrain_bake import commands,refinement_gate,height_gate,validate_config,bake_gate

def test_fixed_command_sequence_has_full_verify_and_two_workers(tmp_path):
    cfg={k:str(tmp_path/k) for k in ['dataRoot','editorRoot','python','bun','refinerWork','base','baseReceipt','snapshot','plan','regions','queueInputs','dem','bakeOutput','verifyWork','work']}
    c=commands(cfg,25938,'a'*64)
    assert [Path(x[1]).name for x in c.values()]==['adaptive_terrain_refinement.py','verify-ngii-terrain-only.ts','queue_ngii_national_bake.py']
    assert '--region' not in c['verify'] and '--allow-sample' not in c['pack']
    assert c['bake'][c['bake'].index('--workers')+1]=='2'
    assert c['bake'][c['bake'].index('--limit')+1]=='25938'
    assert '--reuse-regions-pin' in c['bake']

def test_refinement_requires_final_complete_nonsample_and_matching_source():
    proof={'complete':True,'passed':True,'sampleOnly':False,'finalNeighbourCheck':True,'regions':2,'expectedRegions':2,'nativeFinite':10,'maximumAbsoluteErrorMetres':.5,'baseArchiveSHA256':'a'*64,'identitySHA256':'b'*64,'sourceFingerprint':{'sourceVrtSHA256':'c'*64,'sourceFilesSHA256':'d'*64}}
    receipt={'sha256':'a'*64,'vrt_sha256':'c'*64,'metadata':{'sourceFilesSHA256':'d'*64}}
    refinement_gate(proof,2,'b'*64,receipt)
    for key,value in [('complete',False),('sampleOnly',True),('finalNeighbourCheck',False),('nativeFinite',0),('maximumAbsoluteErrorMetres',.5001),('identitySHA256','e'*64)]:
        bad={**proof,key:value}
        with pytest.raises(ValueError):refinement_gate(bad,2,'b'*64,receipt)

def test_height_gate_rejects_samples_partial_old_archive_and_native_failure():
    p={'complete':True,'passed':True,'sampleOnly':False,'compared':12,'pendingRegions':0,'nativeFinite':12,'maximumAbsoluteErrorMetres':.2,'terrainArchiveSHA256':'a'*64,'sourceVrtSHA256':'b'*64,'sourceFilesSHA256':'c'*64}
    r={'sha256':'a'*64,'vrt_sha256':'b'*64,'metadata':{'sourceFilesSHA256':'c'*64}}
    height_gate(p,12,r)
    for key,value in [('sampleOnly',True),('compared',11),('nativeFinite',0),('terrainArchiveSHA256','d'*64),('maximumAbsoluteErrorMetres',1)]:
        with pytest.raises(ValueError):height_gate({**p,key:value},12,r)

def test_config_rejects_unknown_commands_and_escaping_output(tmp_path):
    cfg={k:str(tmp_path/k) for k in ['dataRoot','editorRoot','python','bun','refinerWork','base','baseReceipt','snapshot','plan','regions','queueInputs','dem','bakeOutput','verifyWork','work']}
    cfg['dataRoot']=str(tmp_path);cfg['work']=str(tmp_path/'management/supervisor');cfg['verifyWork']=str(tmp_path/'management/verify');cfg['bakeOutput']=str(tmp_path/'world-buildings/new');cfg['schema']='ngii-terrain-bake-continuation-v1'
    validate_config(cfg)
    with pytest.raises(ValueError):validate_config({**cfg,'command':['delete']})
    with pytest.raises(ValueError):validate_config({**cfg,'bakeOutput':str(tmp_path.parent/'escape')})

def test_bake_completion_requires_exact_regional_receipts_not_just_exit_zero(tmp_path):
    import json
    inventory={'regions':[{'region14':'14/1/2','buildings':3,'components':4}]}
    with pytest.raises(ValueError):bake_gate(tmp_path,inventory,'a'*64,'b'*64)
    folder=tmp_path/'14-1-2-example';folder.mkdir();p=folder/'candidate-receipt.json'
    value={'owner':'14/1/2','buildings':3,'components':4,'completeRegion':True,'sourcePlanSHA256':'a'*64,'terrainSHA256':'b'*64,'assetPacking':'gzip6-mesh-and-metadata-v1'}
    p.write_text(json.dumps(value));assert len(bake_gate(tmp_path,inventory,'a'*64,'b'*64))==1
    value['terrainSHA256']='c'*64;p.write_text(json.dumps(value))
    with pytest.raises(ValueError):bake_gate(tmp_path,inventory,'a'*64,'b'*64)

@pytest.mark.parametrize('failure',[None,'verify','storage'])
@pytest.mark.parametrize('mode',['fresh-native','pack-equivalence'])
def test_owned_sequence_resume_hash_and_failure_stop(tmp_path,monkeypatch,failure,mode):
    import json,sqlite3,hashlib
    import continue_ngii_terrain_bake as m
    root=tmp_path/'data';repo=tmp_path/'repo';root.mkdir()
    cfg={k:str(root/k) for k in ['refinerWork','base','baseReceipt','snapshot','plan','regions','queueInputs','dem']}
    cfg.update(schema='ngii-terrain-bake-continuation-v1',dataRoot=str(root),editorRoot=str(repo),python='python',bun='bun',bakeOutput=str(root/'world-buildings/new'),verifyWork=str(root/'management/verify'),work=str(root/'management/supervisor'))
    if mode=='pack-equivalence':cfg['verificationMode']=mode
    work=Path(cfg['refinerWork']);work.mkdir();(root/'management').mkdir()
    def save(p,v):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v))
    Path(cfg['base']).write_bytes(b'base');Path(cfg['dem']).write_text('native')
    save(cfg['snapshot'],{});save(cfg['plan'],{'planSHA256':'f'*64})
    inventory={'regionCount':1,'buildingCount':1,'regions':[{'region14':'14/1/2','buildings':1,'components':1}]};save(cfg['regions'],inventory);save(cfg['queueInputs'],{})
    original={'immutable':'identity','sourcePins':{'snapshotSHA256':m.sha(cfg['snapshot'])}};save(work/'inputs.json',original)
    base={'sha256':m.sha(cfg['base']),'vrt_sha256':'c'*64,'metadata':{'sourceFilesSHA256':'d'*64}};save(cfg['baseReceipt'],base)
    proof={'complete':True,'passed':True,'sampleOnly':False,'finalNeighbourCheck':True,'regions':1,'expectedRegions':1,'nativeFinite':1,'maximumAbsoluteErrorMetres':.1,'baseArchiveSHA256':base['sha256'],'identitySHA256':hashlib.sha256(m.canonical(original)).hexdigest(),'sourceFingerprint':{'sourceVrtSHA256':'c'*64,'sourceFilesSHA256':'d'*64}}
    save(work/'refinement-verification.json',proof)
    with sqlite3.connect(work/'refinement-spool.sqlite') as db:db.execute('CREATE TABLE metadata(key,value)');db.execute('INSERT INTO metadata VALUES(?,?)',('verification',json.dumps(proof)))
    tools=repo/'frontend/app/editor/tools'
    for name in ['adaptive_terrain_refinement.py','verify-ngii-terrain-only.ts','verify_terrain_pack_equivalence.py','streaming_pmtiles_writer.py','verify-ngii-national-heights.ts','ngii-native-height-worker.py','bake-ngii-region.ts','ngii-canonical-source.ts','incremental_terrain_archive.py']:
        p=tools/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('pinned')
    for p in [repo/'infra/data/queue_ngii_national_bake.py',tools.parent/'features/world/lib/terrain-height-contract.ts']:p.parent.mkdir(parents=True,exist_ok=True);p.write_text('pinned')
    config=root/'management/config.json';save(config,cfg)
    monkeypatch.setattr(m,'validate_reusable_inventory',lambda *a:None)
    monkeypatch.setattr(m.shutil,'disk_usage',lambda p:type('Space',(),{'free':1 if failure=='storage' else 10**15})())
    states=[];real_atomic=m.atomic
    def observed_atomic(path,value):
        if path.name=='status.json':states.append(value['state'])
        real_atomic(path,value)
    monkeypatch.setattr(m,'atomic',observed_atomic)
    monkeypatch.setattr(m.time,'sleep',lambda _: (Path(cfg['work'])/'STOP').write_text('stop low-space fixture') if failure=='storage' else None)
    launches=[]
    class Child:
        pid=123456789
        def __init__(self,command,**kwargs):
            stage='pack' if 'adaptive_' in command[1] else 'verify' if 'verify' in Path(command[1]).name else 'bake';launches.append(stage)
            self.exit_code=1 if stage==failure else 0
            archive=work/'terrain.packing.pmtiles'
            if stage=='pack':
                archive.write_bytes(b'packed');save(work/'archive-receipt.json',{'archive':str(archive),'bytes':6,'sha256':m.sha(archive),'vrt_sha256':base['vrt_sha256'],'metadata':{**base['metadata'],'adaptiveRefinement':{'identitySHA256':proof['identitySHA256'],'baseArchiveSHA256':base['sha256'],'sampleOnly':False}}})
            elif stage=='verify':
                save(Path(cfg['verifyWork'])/'terrain-only-verification.json',{'complete':True,'passed':True,'sampleOnly':False,'compared':1,'pendingRegions':0,'nativeFinite':1,'maximumAbsoluteErrorMetres':.1,'terrainArchiveSHA256':m.sha(archive),'sourceVrtSHA256':'c'*64,'sourceFilesSHA256':'d'*64})
                save(Path(cfg['verifyWork'])/'inputs.json',{'terrainSHA256':m.sha(archive),'sourceBindings':{'snapshotSHA256':m.sha(cfg['snapshot']),'planFileSHA256':m.sha(cfg['plan']),'regionsSHA256':m.sha(cfg['regions'])}})
                if mode=='pack-equivalence':
                    save(Path(cfg['verifyWork'])/'pack-equivalence-verification.json',{'schema':'ngii-packed-exact-equivalence-proof-v1','method':'final-native-proof-transferred-by-exact-payload-equivalence','complete':True,'passed':True,'sampleOnly':False,'nativeFresh':False,'compared':1,'regions':1,'nativeFinite':1,'nativeNoData':0,'maximumAbsoluteErrorMetres':.1,'archiveSHA256':m.sha(archive),'sourceIdentitySHA256':proof['identitySHA256'],'sourceProofFileSHA256':m.sha(work/'refinement-verification.json'),'sourceInputsFileSHA256':m.sha(work/'inputs.json'),'regionsSHA256':m.sha(cfg['regions']),'queueInputsSHA256':m.sha(cfg['queueInputs']),'sourceFingerprint':proof['sourceFingerprint'],'allTileKeysAndEncodedBytesEqual':True,'allOverlayDecodedHashesChecked':True,'metadataEqual':True,'sourceProofSHA256':hashlib.sha256(json.dumps(proof).encode()).hexdigest(),'sourcePins':original['sourcePins'],'baseSHA256':base['sha256'],'overlaySHA256':m.sha(work/'refinement-spool.sqlite')})
            else:
                out=Path(cfg['bakeOutput']);save(out/'queue-status.json',{'state':'bounded-complete','workers':2,'limit':1});save(out/'queue-inputs.json',{});save(out/'candidate-inputs.json',{})
                save(out/'14-1-2-fixture/candidate-receipt.json',{'owner':'14/1/2','buildings':1,'components':1,'completeRegion':True,'sourcePlanSHA256':'f'*64,'terrainSHA256':m.sha(archive),'assetPacking':'gzip6-mesh-and-metadata-v1'})
        def poll(self):return self.exit_code
        def wait(self):return self.exit_code
    monkeypatch.setattr(m.subprocess,'Popen',Child)
    if failure=='storage':
        assert m.run(config)['state']=='stopped';assert 'needs_storage' in states;assert launches==[];return
    if failure=='verify':
        assert m.run(config)['state']=='failed';assert launches==['pack','verify']
        with pytest.raises(ValueError,match='review'):m.run(config)
        assert not Path(cfg['bakeOutput']).exists();return
    assert m.run(config)['state']=='candidate-bake-complete';assert launches==['pack','verify','bake']
    assert m.run(config)['state']=='candidate-bake-complete';assert len(launches)==3
    (work/'terrain.packing.pmtiles').write_bytes(b'broken')
    assert m.run(config)['state']=='failed';assert len(launches)==3
    with pytest.raises(ValueError,match='review'):m.run(config)
    assert Path(cfg['base']).read_bytes()==b'base'
