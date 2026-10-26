"""One owned continuation: completed refinement -> pack -> independent terrain proof -> two mesh workers.

No activation, browser evidence, source acquisition, deletion or automatic failed-job retry.
STOP is forwarded only to owned verify/bake children, which finish their current region.
Packing finishes its current process; an unfinished pack is never killed automatically.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
from queue_ngii_national_bake import atomic,read,writer_lock,validate_reusable_inventory

RESERVE=20*1024**3
FIELDS={'schema','dataRoot','editorRoot','python','bun','refinerWork','base','baseReceipt','snapshot','plan','regions','queueInputs','dem','bakeOutput','verifyWork','work'}
def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def validate_config(c):
    if set(c)!=FIELDS or c['schema']!='ngii-terrain-bake-continuation-v1':raise ValueError('Unsupported continuation config')
    root=Path(c['dataRoot']).resolve()
    for key in FIELDS-{'schema','editorRoot','python','bun','dataRoot'}:
        p=Path(c[key]).resolve()
        if p==root or not p.is_relative_to(root):raise ValueError('Configured path escapes DATA_ROOT: '+key)
    if not Path(c['work']).resolve().is_relative_to(root/'management') or not Path(c['verifyWork']).resolve().is_relative_to(root/'management'):
        raise ValueError('Evidence directories must be below management')
    if not Path(c['bakeOutput']).resolve().is_relative_to(root/'world-buildings'):raise ValueError('Mesh output must be below world-buildings')
    directories=[Path(c[k]).resolve() for k in ['refinerWork','verifyWork','bakeOutput','work']]
    if any(a==b or a.is_relative_to(b) or b.is_relative_to(a) for i,a in enumerate(directories) for b in directories[i+1:]):raise ValueError('Work directories overlap')
    for key in ['base','baseReceipt','snapshot','plan','regions','queueInputs','dem']:
        if any(Path(c[key]).resolve().is_relative_to(d) for d in directories[1:]):raise ValueError('Output aliases protected input')
    return c

def commands(c,count,terrain_sha):
    tools=Path(c['editorRoot'])/'frontend/app/editor/tools';pack=Path(c['refinerWork'])/'terrain.packing.pmtiles'
    return {
      'pack':[c['python'],str(tools/'adaptive_terrain_refinement.py'),'--base',c['base'],'--work',c['refinerWork'],'--output',str(pack)],
      'verify':[c['bun'],str(tools/'verify-ngii-terrain-only.ts'),'--data-root',c['dataRoot'],'--work',c['verifyWork'],'--snapshot',c['snapshot'],'--plan',c['plan'],'--regions',c['regions'],'--queue-inputs',c['queueInputs'],'--terrain',str(pack),'--terrain-receipt',str(Path(c['refinerWork'])/'archive-receipt.json'),'--dem',c['dem'],'--python',c['python'],'--below-normal'],
      'bake':[c['python'],str(Path(c['editorRoot'])/'infra/data/queue_ngii_national_bake.py'),'--snapshot',c['snapshot'],'--plan',c['plan'],'--terrain',str(pack),'--terrain-sha',terrain_sha,'--output',c['bakeOutput'],'--regions',c['regions'],'--bun',c['bun'],'--python',c['python'],'--reuse-regions-pin',c['queueInputs'],'--limit',str(count),'--workers','2']}

def finite_max(p,key):return isinstance(p.get(key),(int,float)) and not isinstance(p[key],bool) and math.isfinite(p[key]) and 0<=p[key]<=.5
def fingerprint_gate(proof,receipt):
    for pkey,rvalue in [('sourceVrtSHA256',receipt['vrt_sha256']),('sourceFilesSHA256',receipt['metadata']['sourceFilesSHA256']),('recursiveSourceFilesSHA256',receipt['metadata'].get('recursiveSourceFilesSHA256'))]:
        if proof.get(pkey)!=rvalue:raise ValueError('Native source fingerprint mismatch')
def refinement_gate(p,count,identity,base):
    if p.get('complete') is not True or p.get('passed') is not True or p.get('sampleOnly') is not False or p.get('finalNeighbourCheck') is not True \
       or p.get('regions')!=count or p.get('expectedRegions')!=count or not p.get('nativeFinite',0)>0 or not finite_max(p,'maximumAbsoluteErrorMetres') \
       or p.get('identitySHA256')!=identity or p.get('baseArchiveSHA256')!=base['sha256']:raise ValueError('Full final refinement proof is not ready')
    fingerprint_gate(p.get('sourceFingerprint',{}),base)
def height_gate(p,count,receipt):
    if p.get('complete') is not True or p.get('passed') is not True or p.get('sampleOnly') is not False or p.get('compared')!=count or p.get('pendingRegions')!=0 \
       or not p.get('nativeFinite',0)>0 or not finite_max(p,'maximumAbsoluteErrorMetres') or p.get('terrainArchiveSHA256')!=receipt['sha256']:
        raise ValueError('Independent full terrain proof failed/incomplete')
    fingerprint_gate(p,receipt)
def bake_gate(folder,inventory,plan_sha,terrain_sha):
    expected={r['region14']:r for r in inventory['regions']};found={}
    for entry in Path(folder).iterdir():
        if not entry.is_dir() or not entry.name.startswith('14-'):continue
        receipt=entry/'candidate-receipt.json'
        if not receipt.exists():raise ValueError('Incomplete final candidate directory')
        r=read(receipt);owner=r.get('owner');target=expected.get(owner)
        if owner in found or target is None or r.get('completeRegion') is not True or r.get('buildings')!=target['buildings'] or r.get('components')!=target['components'] \
           or r.get('sourcePlanSHA256')!=plan_sha or r.get('terrainSHA256')!=terrain_sha or r.get('assetPacking')!='gzip6-mesh-and-metadata-v1':raise ValueError('Completed candidate coverage/identity mismatch')
        found[owner]={'receipt':str(receipt.resolve()),'sha256':sha(receipt),'buildings':r['buildings'],'components':r['components']}
    if set(found)!=set(expected):raise ValueError('Missing completed candidate regions')
    return dict(sorted(found.items()))
def alive(pid):
    if not isinstance(pid,int) or pid<1:return False
    if os.name=='nt':
        import ctypes
        handle=ctypes.windll.kernel32.OpenProcess(0x1000,False,pid)
        if not handle:return ctypes.windll.kernel32.GetLastError()==5
        code=ctypes.c_ulong();ok=ctypes.windll.kernel32.GetExitCodeProcess(handle,ctypes.byref(code));ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok and code.value==259)
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False

def run(config_path,*,resume_after_review=False,poll_seconds=30):
    config_path=Path(config_path).resolve();c=validate_config(read(config_path));root=Path(c['dataRoot']).resolve();work=Path(c['work']).resolve()
    if not config_path.is_relative_to(root/'management'):raise ValueError('Config must be inside management')
    work.mkdir(parents=True,exist_ok=True);status_path=work/'status.json';stages_path=work/'completed-stages.json'
    with writer_lock(work):
        previous=read(status_path) if status_path.exists() else {}
        if alive(previous.get('childPID')):raise ValueError('Recorded child is still alive; duplicate launch refused')
        if (previous.get('state') in ('failed','running') or previous.get('state')=='needs_storage' and previous.get('exitCode')) and not resume_after_review:raise ValueError('Prior failed/interrupted stage requires --resume-after-review')
        done=read(stages_path) if stages_path.exists() else {}
        state={}
        def record(phase,**details):
            nonlocal state
            state={'schema':'ngii-terrain-bake-continuation-status-v1','pid':os.getpid(),'state':phase,'at':time.time(),'candidateOnly':True,'published':False,**details};atomic(status_path,state);return state
        def stopped():return (work/'STOP').exists()
        def capacity(stage):
            while True:
                drives={Path(c[k]).anchor:Path(c[k]) for k in ['work','refinerWork','verifyWork','bakeOutput']};available={}
                for drive,p in drives.items():
                    while not p.exists():p=p.parent
                    available[drive]=shutil.disk_usage(p).free
                required={drive:RESERVE+512*1024**2 for drive in available}
                if stage=='pack':
                    refinement_proof=read(Path(c['refinerWork'])/'refinement-verification.json')
                    required[Path(c['refinerWork']).anchor]+=2*(Path(c['base']).stat().st_size+refinement_proof.get('added',{}).get('bytes',0))
                if all(v>=required[drive] for drive,v in available.items()):return True
                record('needs_storage',stage=stage,freeBytes=available,requiredBytes=required,reserveBytes=RESERVE,marginBytes=512*1024**2)
                if stopped():record('stopped',stage=stage);return False
                time.sleep(poll_seconds)
        def check_hashes(pins):
            if any(sha(p)!=digest for p,digest in pins.items()):raise ValueError('Pinned configuration/source/script changed')
        try:
            count=read(c['regions'])['regionCount'];inventory=read(c['regions']);plan=read(c['plan']);base_receipt=read(c['baseReceipt'])
            binding={'snapshotSHA256':sha(c['snapshot']),'planFileSHA256':sha(c['plan'])}
            validate_reusable_inventory(Path(c['regions']),c['queueInputs'],binding,plan)
            scripts=[cmd[1] for cmd in commands(c,count,'pending').values()]
            tools=Path(c['editorRoot'])/'frontend/app/editor/tools'
            scripts += [str(tools/n) for n in ['streaming_pmtiles_writer.py','verify-ngii-national-heights.ts','ngii-native-height-worker.py','bake-ngii-region.ts','ngii-canonical-source.ts','incremental_terrain_archive.py']]
            scripts += [str(tools.parent/'features/world/lib/terrain-height-contract.ts'),str(Path(__file__).resolve())]
            pins={p:sha(p) for p in [str(config_path),c['snapshot'],c['plan'],c['regions'],c['queueInputs'],c['baseReceipt'],str(Path(c['refinerWork'])/'inputs.json'),*scripts]}
            identity={'config':c,'pins':pins};ip=work/'inputs.json'
            if ip.exists() and read(ip)!=identity:raise ValueError('Supervisor immutable identity changed')
            if not ip.exists():atomic(ip,identity)
            def execute(stage,command):
                if stopped():return False
                check_hashes(pins)
                if not capacity(stage):return False
                log=work/(stage+'-'+str(time.time_ns())+'.log')
                flags=(subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name=='nt' else 0
                with log.open('xb') as stream:
                    child=subprocess.Popen(command,cwd=str(tools.parent),stdout=stream,stderr=subprocess.STDOUT,creationflags=flags,env={**os.environ,'NGII_PYTHON':c['python'],'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
                    record('running',stage=stage,childPID=child.pid,command=command,log=str(log))
                    try:
                        while child.poll() is None:
                            if stopped() and stage in ('verify','bake'):
                                folder=Path(c['verifyWork'] if stage=='verify' else c['bakeOutput']);folder.mkdir(parents=True,exist_ok=True)
                                marker=folder/'STOP'
                                if not marker.exists():marker.write_text('Supervisor STOP: finish current region; no activation',encoding='utf-8')
                            time.sleep(2)
                        code=child.wait()
                    except BaseException:
                        record('running',stage=stage,childPID=child.pid,log=str(log),error='Supervisor interrupted; child may still be alive, do not duplicate')
                        raise
                check_hashes(pins)
                if stopped():record('stopped',stage=stage,exitCode=code,log=str(log));return False
                if code:
                    with log.open('rb') as f:f.seek(max(0,log.stat().st_size-65536));tail=f.read().decode('utf-8',errors='replace')
                    if '20GiB' in tail or 'needs_storage' in tail or 'reserve' in tail:
                        record('needs_storage',stage=stage,exitCode=code,log=str(log),error='Child stopped for storage; preserve partial outputs and review before resume');return False
                    raise RuntimeError(f'{stage} exited {code}; review {log}; no automatic retry')
                return True
            refinement=Path(c['refinerWork']);proof_path=refinement/'refinement-verification.json'
            while not proof_path.exists() or (refinement/'refinement.lock').exists():
                if stopped():return record('stopped',stage='waiting-refinement')
                check_hashes(pins)
                if not capacity('waiting-refinement'):return state
                progress=read(refinement/'progress.json')
                if progress.get('state')=='needs_storage':record('needs_storage',stage='waiting-refinement',progress=progress);time.sleep(poll_seconds);continue
                if progress.get('state')=='failed' or str(progress.get('state','')).startswith('stopped'):raise ValueError('Refiner not progressing: '+str(progress.get('state')))
                lock=read(refinement/'refinement.lock') if (refinement/'refinement.lock').exists() else None
                owner=lock.get('pid') if isinstance(lock,dict) else lock
                if not alive(owner):
                    if proof_path.exists() and not (refinement/'refinement.lock').exists():break
                    raise ValueError('Refiner proof incomplete and live lock owner missing')
                record('waiting-refinement',refinerPID=owner,progress=progress);time.sleep(poll_seconds)
            original=read(refinement/'inputs.json');proof=read(proof_path)
            refinement_gate(proof,count,hashlib.sha256(canonical(original)).hexdigest(),base_receipt)
            with sqlite3.connect((refinement/'refinement-spool.sqlite').as_uri()+'?mode=ro',uri=True) as db:
                if json.loads(db.execute("SELECT value FROM metadata WHERE key='verification'").fetchone()[0])!=proof:raise ValueError('SQLite final proof differs')
            proof_pin={str(proof_path):sha(proof_path)};check_hashes(proof_pin)
            receipt_path=refinement/'archive-receipt.json';archive=refinement/'terrain.packing.pmtiles'
            if not receipt_path.exists():
                if archive.exists():raise ValueError('Unreceipted archive exists; manual review required')
                if not execute('pack',commands(c,count,'pending')['pack']):return state
            receipt=read(receipt_path)
            if Path(receipt['archive']).resolve()!=archive.resolve() or receipt['bytes']!=archive.stat().st_size or receipt['sha256']!=sha(archive):raise ValueError('Packed archive receipt/hash mismatch')
            fingerprint_gate({'sourceVrtSHA256':receipt.get('vrt_sha256'),'sourceFilesSHA256':receipt['metadata'].get('sourceFilesSHA256'),'recursiveSourceFilesSHA256':receipt['metadata'].get('recursiveSourceFilesSHA256')},base_receipt)
            adaptive=receipt['metadata'].get('adaptiveRefinement',{})
            if adaptive.get('identitySHA256')!=proof['identitySHA256'] or adaptive.get('baseArchiveSHA256')!=base_receipt['sha256'] or adaptive.get('sampleOnly') is not False:raise ValueError('Packed refinement identity mismatch')
            def completed(stage,files):
                current={str(p):sha(p) for p in files}
                if stage in done and done[stage]!=current:raise ValueError('Completed stage evidence changed: '+stage)
                done[stage]=current;atomic(stages_path,done);record('stage-complete',stage=stage,proofs=current)
            completed('pack',[receipt_path,archive]);check_hashes(proof_pin)
            hp=Path(c['verifyWork'])/'terrain-only-verification.json'
            if 'verify' not in done:
                if not execute('verify',commands(c,count,receipt['sha256'])['verify']):return state
            height_gate(read(hp),inventory['buildingCount'],receipt)
            vp=read(Path(c['verifyWork'])/'inputs.json')
            if vp['terrainSHA256']!=receipt['sha256'] or vp['sourceBindings']['snapshotSHA256']!=binding['snapshotSHA256'] or vp['sourceBindings']['planFileSHA256']!=binding['planFileSHA256'] or vp['sourceBindings']['regionsSHA256']!=sha(c['regions']):raise ValueError('Terrain verifier source binding mismatch')
            completed('verify',[hp,Path(c['verifyWork'])/'inputs.json']);check_hashes(proof_pin)
            if 'bake' not in done:
                if not execute('bake',commands(c,count,receipt['sha256'])['bake']):return state
            out=Path(c['bakeOutput']);status=read(out/'queue-status.json')
            if status.get('state')!='bounded-complete' or status.get('workers')!=2 or status.get('limit')!=count:raise ValueError('Two-worker bake incomplete')
            region_proofs=bake_gate(out,inventory,plan['planSHA256'],receipt['sha256']);region_manifest=work/'bake-receipts.json'
            if region_manifest.exists() and read(region_manifest)!=region_proofs:raise ValueError('Completed regional receipt identity changed')
            if not region_manifest.exists():atomic(region_manifest,region_proofs)
            completed('bake',[out/'queue-status.json',out/'queue-inputs.json',out/'candidate-inputs.json',region_manifest])
            return record('candidate-bake-complete',regions=count,terrainSHA256=receipt['sha256'],next='Independent final mesh datum verification, HLOD, geographic gate and reviewed browser publication remain required')
        except Exception as error:
            return record('failed',stage=state.get('stage'),error=str(error),childPID=state.get('childPID') if alive(state.get('childPID')) else None)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True);parser.add_argument('--resume-after-review',action='store_true');parser.add_argument('--poll-seconds',type=int,default=30)
    args=parser.parse_args()
    if not 1<=args.poll_seconds<=60:parser.error('poll-seconds must be1..60')
    result=run(args.config,resume_after_review=args.resume_after_review,poll_seconds=args.poll_seconds);print(json.dumps(result,ensure_ascii=False),flush=True)
    if result['state'] not in ('candidate-bake-complete','stopped'):raise SystemExit(1)
