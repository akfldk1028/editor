"""Single-writer local map release store. Preparation never changes the active release."""
import argparse,contextlib,hashlib,json,os,re,time,uuid
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
from pathlib import Path

def read_json(path):return json.loads(path.read_text(encoding='utf-8'))
def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def digest(path):
    with path.open('rb') as file:return hashlib.file_digest(file,'sha256').hexdigest()

def atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temporary.open('wb') as file:file.write(encoded(value));file.flush();os.fsync(file.fileno())
    for attempt in range(50):
        try:temporary.replace(path);return
        except PermissionError:
            if attempt==49:raise
            time.sleep(.1)

@contextlib.contextmanager
def locked(root):
    folder=root/'management';folder.mkdir(parents=True,exist_ok=True)
    with (folder/'publication.lock').open('a+b') as file:
        if file.seek(0,2)==0:file.write(b'0');file.flush()
        file.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:
            file.seek(0)
            if os.name=='nt':msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(file,fcntl.LOCK_UN)

def local_file(root,path,parents=None):
    parents={} if parents is None else parents
    path=Path(os.path.abspath(path))
    parent=parents.get(path.parent)
    if parent is None:parent=path.parent.resolve();parents[path.parent]=parent
    path=path.resolve() if path.is_symlink() else parent/path.name
    if not path.is_relative_to(root):raise ValueError('Release file escapes DATA_ROOT')
    return path,path.relative_to(root).as_posix()

def seal(root,payload,files,*,reuse=True):
    root=root.resolve()
    with locked(root):
        cache={}
        # A stopped run has already hashed these bytes. Reuse only unchanged
        # size/mtime identities; --deep verification remains available for bit rot.
        prior_receipts=list((root/'management/staging').glob('*/files.jsonl')) if reuse else []
        current_path=root/'releases/current.json'
        if reuse and current_path.exists():
            current=read_json(current_path);active_id=current['releaseId']
            if not re.fullmatch('[a-f0-9]{64}',active_id):raise ValueError('Invalid active release id')
            active_receipt=root/'management/releases'/active_id/'files.jsonl'
            if digest(active_receipt)!=current['filesReceiptSHA256']:raise ValueError('Active hash receipt changed')
            prior_receipts.append(active_receipt)
        for prior in prior_receipts:
            with prior.open(encoding='utf-8') as stream:
                for line in stream:
                    try:
                        row=json.loads(line)
                        if re.fullmatch('[a-f0-9]{64}',row.get('sha256','')):cache[row['key']]=row
                    except json.JSONDecodeError:continue
        staging=root/'management/staging'/uuid.uuid4().hex;staging.mkdir(parents=True)
        receipt=staging/'files.jsonl';count=0;total=0;seen=set();parents={};started=time.time()
        try:
            def hash_file(item):
                file,key=item;before=file.stat();cached=cache.get(key)
                sha=cached['sha256'] if cached and cached['bytes']==before.st_size and cached['mtimeNs']==before.st_mtime_ns else digest(file)
                after=file.stat()
                if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError(f'File changed during verification: {key}')
                return {'key':key,'bytes':after.st_size,'mtimeNs':after.st_mtime_ns,'sha256':sha}
            with receipt.open('wb') as output,ThreadPoolExecutor(max_workers=4) as workers:
                iterator=iter(files)
                for batch in iter(lambda:list(islice(iterator,256)),[]):
                    jobs=[]
                    for file in batch:
                        file,key=local_file(root,file,parents)
                        if key not in seen:seen.add(key);jobs.append((file,key))
                    for row in workers.map(hash_file,jobs):
                        output.write(encoded(row)+b'\n');count+=1;total+=row['bytes']
                        if count%2000==0:
                            output.flush();atomic_json(root/'management/activity.json',{'state':'hashing','pid':os.getpid(),'files':count,'bytes':total,'startedAt':started})
                            print(json.dumps({'state':'hashing','files':count,'bytes':total}),flush=True)
                output.flush();os.fsync(output.fileno())
            receipt_sha=digest(receipt)
            body={**payload,'filesReceiptSHA256':receipt_sha,'fileCount':count,'totalBytes':total}
            identity=hashlib.sha256(encoded(body)).hexdigest();manifest={**body,'releaseId':identity}
            private=root/'management/releases'/identity
            if private.exists():
                if digest(private/'files.jsonl')!=receipt_sha:raise ValueError('Immutable receipt collision')
            else:private.parent.mkdir(parents=True,exist_ok=True);staging.rename(private)
            destination=root/'releases'/identity/'manifest.json'
            if destination.exists() and read_json(destination)!=manifest:raise ValueError('Immutable release collision')
            if not destination.exists():atomic_json(destination,manifest)
            atomic_json(root/'management/activity.json',{'state':'prepared','releaseId':identity,'files':count,'bytes':total})
            return manifest
        except Exception as error:
            atomic_json(root/'management/activity.json',{'state':'failed','files':count,'errorType':type(error).__name__})
            raise

def verify(root,identity,*,deep=False):
    if not re.fullmatch('[a-f0-9]{64}',identity):raise ValueError('Invalid release id')
    root=root.resolve();manifest=read_json(root/'releases'/identity/'manifest.json')
    body={k:v for k,v in manifest.items() if k!='releaseId'}
    if manifest.get('releaseId')!=identity or hashlib.sha256(encoded(body)).hexdigest()!=identity:raise ValueError('Release manifest changed')
    receipt=root/'management/releases'/identity/'files.jsonl'
    if digest(receipt)!=manifest['filesReceiptSHA256']:raise ValueError('Release receipt changed')
    count=0;total=0;parents={}
    def check_row(line):
            row=json.loads(line);file,key=local_file(root,root/row['key'],parents);info=file.stat()
            if info.st_size!=row['bytes']:raise ValueError(f'Release file size changed: {key}')
            if (deep or info.st_mtime_ns!=row['mtimeNs']) and digest(file)!=row['sha256']:raise ValueError(f'Release file hash changed: {key}')
            return info.st_size
    with receipt.open(encoding='utf-8') as stream,ThreadPoolExecutor(max_workers=8) as workers:
        for batch in iter(lambda:list(islice(stream,256)),[]):
            for size in workers.map(check_row,batch):count+=1;total+=size
            if count and count%8192==0:print(json.dumps({'state':'verifying','files':count,'total':manifest['fileCount']}),flush=True)
    if count!=manifest['fileCount'] or total!=manifest['totalBytes']:raise ValueError('Incomplete release receipt')
    return manifest

def runtime_validation(manifest,path):
    """Require actual isolated-factory browser evidence for every v2 activation.

    JSON schema ngii-national-browser-validation-v1 binds releaseId and
    filesReceiptSHA256. Required evidence: status PASS, isolatedCandidate true,
    renderer national, buildingSourceCount 1, legacyBuildingRequests 0,
    terrainRequests > 0, errors 0, and distances near/mid/far each PASS.
    This validates an explicit measured receipt, not a substitute browser run.
    Rollbacks to v2 require the same evidence; v1 retains its existing contract.
    """
    if manifest.get('schema')!='ace-map-release-v2':return None
    if path is None:raise ValueError('v2 requires runtime validation receipt')
    raw=Path(path).read_bytes();proof=json.loads(raw)
    if not isinstance(proof,dict) or proof.get('schema')!='ngii-national-browser-validation-v1' \
       or proof.get('releaseId')!=manifest['releaseId'] \
       or proof.get('filesReceiptSHA256')!=manifest['filesReceiptSHA256']:
        raise ValueError('Runtime validation receipt binding mismatch')
    if proof.get('status')!='PASS' or proof.get('isolatedCandidate') is not True \
       or proof.get('renderer')!='national' \
       or any(type(proof.get(key)) is not int or proof[key]!=value for key,value in
              [('buildingSourceCount',1),('legacyBuildingRequests',0),('errors',0)]) \
       or type(proof.get('terrainRequests')) is not int or proof['terrainRequests']<1 \
       or proof.get('distances')!={'near':'PASS','mid':'PASS','far':'PASS'}:
        raise ValueError('Runtime validation receipt is not a complete browser PASS')
    return {'receiptSHA256':hashlib.sha256(raw).hexdigest(),'evidence':proof}


def activate(root,identity,*,reason='activate',deep=False,expected_current=None,runtime_validation_path=None):
    with locked(root):
        manifest=verify(root,identity,deep=deep)
        browser_proof=runtime_validation(manifest,runtime_validation_path)
        current=root/'releases/current.json';previous=read_json(current) if current.exists() else None
        previous_id=previous['releaseId'] if previous else None
        if expected_current is not None and previous_id!=expected_current:raise ValueError('Active release differs from expected current release')
        if reason!='rollback' and 'predecessorRelease' in manifest and previous_id not in (manifest['predecessorRelease'],identity):raise ValueError('Active release changed since preparation; prepare again or explicitly roll back')
        event={'at':time.time(),'reason':reason,'previous':previous,'next':manifest}
        if browser_proof is not None:event['runtimeValidation']=browser_proof
        # The recovery record is durable before the single public pointer changes.
        atomic_json(root/'management/history'/f'{time.time_ns()}-{uuid.uuid4().hex}.json',event)
        atomic_json(current,manifest)
        return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('operation',choices=['verify','activate','rollback']);p.add_argument('release_id');p.add_argument('--deep',action='store_true')
    p.add_argument('--runtime-validation',type=Path,help='Measured isolated browser PASS receipt required for v2 activate/rollback')
    a=p.parse_args()
    result=verify(a.data_root,a.release_id,deep=a.deep) if a.operation=='verify' else activate(a.data_root,a.release_id,reason=a.operation,deep=a.deep,runtime_validation_path=a.runtime_validation)
    print(json.dumps({'state':a.operation,'releaseId':result['releaseId'],'files':result['fileCount']}))
