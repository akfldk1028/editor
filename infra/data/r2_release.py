"""Export a sealed v1/v2 map release. Upload is explicit; secrets never enter output."""
import argparse
import copy
import hashlib
import json
import mimetypes
import os
import posixpath
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from release_store import verify, encoded, digest, atomic_json, locked, local_file, runtime_validation

IMMUTABLE = 'public, max-age=31536000, immutable'
SHORT = 'public, max-age=60'
REQUIRED = ('R2_ACCOUNT_ID','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY','R2_BUCKET','R2_PUBLIC_BASE_URL')
V1, V2 = 'ace-map-release-v1', 'ace-map-release-v2'
# The local server's only absolute links: HLOD nodes pin regional tilesets as /api/map-data/...
ABSOLUTE_LINK = re.compile(rb'("uri"\s*:\s*")/api/map-data/(world-buildings/[^"\\]+)"')


class Failure(Exception):
    """Only fixed internal codes are safe to print."""


def safe_key(key):
    if not isinstance(key, str) or '\\' in key or key.startswith('/'):
        return False
    parts = key.split('/')
    if any(p in ('', '.', '..') or p.startswith('.') for p in parts): return False
    name = parts[-1].lower()
    return not any(word in name for word in ('secret','credential','upload-plan','state','receipt','key','env'))


def public_asset(key):
    if not safe_key(key): return False
    parts = key.split('/'); name = parts[-1].lower()
    if re.fullmatch(r'tiles/buildings/\d{8}-[a-f0-9]{8}/(?:buildings\.pmtiles|manifest\.json)',key): return True
    if parts[0]=='world-terrain': return len(parts)==2 and name.endswith('.pmtiles')
    return parts[0]=='world-buildings' and len(parts)>=3 and PurePosixPath(key).suffix in ('.json','.b3dm','.glb','.gltf','.bin')


def national_asset(key):
    """v2 serves only what Cesium fetches: tilesets, HLOD node tilesets, gzip b3dm, terrain.
    Summaries, footprints, ground sources, candidate inputs/receipts stay private evidence."""
    if not safe_key(key): return False
    parts = key.split('/'); name = parts[-1]
    if parts[0]=='world-terrain': return len(parts)==2 and name.endswith('.pmtiles')
    return parts[0]=='world-buildings' and len(parts)>=3 and (name=='tileset.json' or name.endswith('.b3dm.gz')
        or parts[-2]=='nodes' and name.endswith('.json'))


def relative_links(key, data):
    """Absolute /api/map-data links resolve against the R2 host root; relative ones work on both."""
    folder = posixpath.dirname(key)
    def local(match):
        target = match[2].decode()
        if not national_asset(target) or not target.endswith('/tileset.json'): raise Failure('INVALID_TILESET_LINK')
        return match[1]+posixpath.relpath(target,folder).encode()+b'"'
    data = ABSOLUTE_LINK.sub(local,data)
    try: nodes = [json.loads(data)['root']]
    except (ValueError, KeyError, TypeError): raise Failure('INVALID_TILESET') from None
    while nodes:
        node = nodes.pop(); nodes.extend(node.get('children',[]))
        uri = (node.get('content') or {}).get('uri')
        if uri is not None and (not isinstance(uri,str) or ':' in uri or uri.startswith(('/','\\'))): raise Failure('ABSOLUTE_TILESET_LINK')
    return data


def remote_bytes(root, row):
    """v2 tileset JSON as uploaded: sealed bytes with absolute links made relative. Local files never change."""
    path,_ = local_file(root,root/row['key']); data = path.read_bytes()
    source = row.get('sourceSHA256',row['sha256']); size = row.get('sourceBytes',row['bytes'])
    if len(data)!=size or hashlib.sha256(data).hexdigest()!=source: raise Failure('LOCAL_ASSET_CHANGED')
    result = relative_links(row['key'],data)
    if result==data: return {k:row[k] for k in ('key','bytes','sha256')}, None
    return {'key':row['key'],'bytes':len(result),'sha256':hashlib.sha256(result).hexdigest(),'sourceBytes':size,'sourceSHA256':source}, result


class Plan:
    """Public rows streamed from the sealed receipt on every pass; never materialised in memory."""
    def __init__(self, root, identity, schema): self.root, self.identity, self.schema = root, identity, schema
    def __iter__(self):
        allowed = national_asset if self.schema==V2 else public_asset
        with (self.root/'management/releases'/self.identity/'files.jsonl').open(encoding='utf8') as f:
            for line in f:
                row = json.loads(line)
                if not allowed(row['key']): continue
                entry = {k:row[k] for k in ('key','bytes','sha256')}
                yield remote_bytes(self.root,entry)[0] if self.schema==V2 and entry['key'].endswith('.json') else entry


def public_base(value):
    url=urlsplit(value)
    if url.scheme not in ('http','https') or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise Failure('INVALID_PUBLIC_BASE')
    return value.rstrip('/')


def entry_keys(manifest):
    """v2 URLs stay /api/map-data/...; the editor maps them through assetBases (mapAssetUrl)."""
    keys=[]
    for value,namespace in (((manifest.get('terrain') or {}).get('url'),'world-terrain'),((manifest.get('nationalBuildings') or {}).get('url'),'world-buildings')):
        key=value.removeprefix('/api/map-data/') if isinstance(value,str) else ''
        if not key.startswith(namespace+'/') or not national_asset(key): raise Failure('INVALID_RELEASE_URL')
        keys.append(key)
    return keys


def transport_manifest(manifest, base, rows=(), required=()):
    schema=manifest.get('schema')
    if schema not in (V1,V2): raise Failure('UNSUPPORTED_RELEASE_SCHEMA')
    if schema==V2: entry_keys(manifest)
    base=public_base(base); result=copy.deepcopy(manifest)
    result.pop('releaseId',None)
    result['sourceReleaseId']=manifest['releaseId']
    result['sourceManifestSHA256']=hashlib.sha256(encoded(manifest)).hexdigest()
    result['assetBases']={'world-buildings':base+'/world-buildings','terrain':base+'/world-terrain'}
    if schema==V1: result['assetBases']['buildings']=base+'/tiles/buildings'
    receipt_hash=hashlib.sha256(); count=0; total=0; missing=set(required)
    for row in rows:
        entry={k:row[k] for k in ('key','bytes','sha256')}
        receipt_hash.update(encoded(entry)+b'\n'); count+=1; total+=entry['bytes']; missing.discard(entry['key'])
    if missing: raise Failure('RELEASE_ENTRY_NOT_PUBLIC')
    result['publicTransfer']={'fileCount':count,'totalBytes':total,'receiptSHA256':receipt_hash.hexdigest()}
    result['releaseId']=hashlib.sha256(encoded(result)).hexdigest()
    return result


def export_plan(root, identity):
    manifest=verify(root,identity)
    if manifest.get('schema') not in (V1,V2): raise Failure('UNSUPPORTED_RELEASE_SCHEMA')
    return manifest, Plan(root,identity,manifest['schema'])


def remote_digest(client,bucket,key):
    response=client.get_object(Bucket=bucket,Key=key)
    body=response['Body']; h=hashlib.sha256(); count=0
    try:
        while block:=body.read(1024*1024): h.update(block); count+=len(block)
    finally: body.close()
    return h.hexdigest(), count


def head(client,bucket,key):
    try: return client.head_object(Bucket=bucket,Key=key)
    except Exception as error:
        if getattr(error,'response',{}).get('Error',{}).get('Code') in ('404','NoSuchKey','NotFound'): return None
        raise Failure('REMOTE_HEAD_FAILED') from None


def publish(*,client,bucket,root,manifest,rows,base,work,workers=4,retries=2,transfer_config=None,validation=None):
    if not 1<=workers<=32 or not 0<=retries<=3: raise Failure('INVALID_LIMIT')
    root=root.resolve(); national=manifest.get('schema')==V2; scene=proof=None
    if national:
        # A public current.json is an activation: same measured browser PASS as release_store.activate.
        if validation is None: raise Failure('RUNTIME_VALIDATION_REQUIRED')
        try: proof=runtime_validation(manifest,validation)
        except Exception: raise Failure('RUNTIME_VALIDATION_FAILED') from None
        remote=transport_manifest(manifest,base,rows,entry_keys(manifest))
    else:
        remote=transport_manifest(manifest,base,rows)
        version=manifest['buildings']['version']
        if not re.fullmatch(r'\d{8}-[a-f0-9]{8}',version): raise Failure('INVALID_BUILDING_VERSION')
        scene_key=f'tiles/buildings/{version}/manifest.json'
        scene_row=next((r for r in rows if r['key']==scene_key),None)
        if scene_row is None: raise Failure('SEALED_SCENE_MANIFEST_REQUIRED')
        scene_path,_=local_file(root,root/scene_key)
        if digest(scene_path)!=scene_row['sha256']: raise Failure('LOCAL_SCENE_MANIFEST_CHANGED')
        scene=json.loads(scene_path.read_text(encoding='utf8'))
        if scene.get('version')!=version or scene.get('layer')!='buildings': raise Failure('INVALID_SCENE_MANIFEST')
    allowed=national_asset if national else public_asset
    work.mkdir(parents=True,exist_ok=True)
    with locked(work):
        binding={'sourceReleaseId':manifest['releaseId'], 'destinationSHA256':hashlib.sha256(encoded([bucket,public_base(base)])).hexdigest()}
        binding_path=work/'binding.json'
        if binding_path.exists() and json.loads(binding_path.read_text())!=binding: raise Failure('RESUME_DESTINATION_CHANGED')
        atomic_json(binding_path,binding)
        intents_path=work/'intents.jsonl'; intents=set(); intent_lock=threading.Lock()
        if intents_path.exists():
            for line in intents_path.read_text(encoding='utf8').splitlines():
                item=json.loads(line); intents.add((item['key'],item['sha256']))
        def own_write(key,sha):
            with intent_lock:
                if (key,sha) not in intents:
                    with intents_path.open('a',encoding='utf8') as log:
                        log.write(encoded({'key':key,'sha256':sha}).decode()+'\n'); log.flush(); os.fsync(log.fileno())
                    intents.add((key,sha))
        receipt=work/'objects.jsonl'
        def upload(row):
            key=row['key']
            if not allowed(key): raise Failure('NON_PUBLIC_ASSET')
            path,_=local_file(root,root/key); body=None
            if national and key.endswith('.json'):
                planned,body=remote_bytes(root,row)
                if planned!=row: raise Failure('LOCAL_ASSET_CHANGED')
            elif path.stat().st_size!=row['bytes'] or digest(path)!=row['sha256']: raise Failure('LOCAL_ASSET_CHANGED')
            metadata={'sha256':row['sha256'],'source-release':manifest['releaseId']}
            extra={'Metadata':metadata,'CacheControl':IMMUTABLE,
                'ContentType':'application/vnd.pmtiles' if key.endswith('.pmtiles') else mimetypes.guess_type(key)[0] or 'application/octet-stream'}
            # Same representation as prepared-map-files.ts: stored gzip, browser decodes for Cesium.
            if key.endswith('.gz'): extra['ContentEncoding']='gzip'
            existing=head(client,bucket,key)
            owned=(key,row['sha256']) in intents and existing and existing.get('Metadata',{}).get('source-release')==manifest['releaseId']
            if existing and (existing.get('Metadata',{}).get('sha256')!=row['sha256'] or existing['ContentLength']!=row['bytes'] and not owned):
                raise Failure('IMMUTABLE_OBJECT_COLLISION')
            if existing and existing.get('ContentEncoding')!=extra.get('ContentEncoding'): raise Failure('IMMUTABLE_OBJECT_HEADERS')
            created=False
            for attempt in range(retries+1):
                try:
                    if not existing or created:
                        own_write(key,row['sha256'])
                        opts={'Config':transfer_config} if transfer_config is not None else {}
                        if body is not None: client.put_object(Bucket=bucket,Key=key,Body=body,**extra)
                        else: client.upload_file(str(path),bucket,key,ExtraArgs=extra,**opts)
                        created=True
                    if remote_digest(client,bucket,key)!=(row['sha256'],row['bytes']):
                        if existing and not created and not owned: raise Failure('IMMUTABLE_OBJECT_CORRUPT')
                        created=True
                        raise Failure('GET_HASH_MISMATCH')
                    return {**row,'verified':True,'attempts':attempt+1}
                except Exception as error:
                    if isinstance(error,Failure) and str(error)=='IMMUTABLE_OBJECT_CORRUPT': raise
                    if attempt==retries: raise Failure('OBJECT_VERIFICATION_FAILED') from None
            raise Failure('OBJECT_VERIFICATION_FAILED')
        def checked_upload(row):
            try: return upload(row)
            except Failure as error: return {**row,'verified':False,'code':str(error)}
            except Exception: return {**row,'verified':False,'code':'OBJECT_OPERATION_FAILED'}
        with receipt.open('a',encoding='utf8') as out,ThreadPoolExecutor(max_workers=workers) as pool:
            iterator=iter(rows)
            for batch in iter(lambda:list(islice(iterator,workers)),[]):
                failed=False
                for result in pool.map(checked_upload,batch):
                    out.write(encoded(result).decode()+'\n'); out.flush(); os.fsync(out.fileno())
                    failed |= not result['verified']
                if failed: raise Failure('ASSET_BATCH_FAILED')

        def put_json(key,value,cache,immutable=False):
            data=encoded(value); expected=(hashlib.sha256(data).hexdigest(),len(data))
            existing=head(client,bucket,key) if immutable else None
            if existing:
                if remote_digest(client,bucket,key)!=expected: raise Failure('IMMUTABLE_MANIFEST_COLLISION')
                return
            for attempt in range(retries+1):
                try:
                    client.put_object(Bucket=bucket,Key=key,Body=data,ContentType='application/json',CacheControl=cache,
                        Metadata={'sha256':expected[0]})
                    if remote_digest(client,bucket,key)!=expected: raise Failure('POINTER_VERIFY_FAILED')
                    return
                except Exception:
                    if attempt==retries: raise Failure('POINTER_VERIFY_FAILED') from None
        # All immutable assets passed full GET verification before any pointer writes.
        put_json(f"releases/{remote['releaseId']}/manifest.json",remote,IMMUTABLE,immutable=True)
        # v2 has no Scene PMTiles; Scene's tiles/buildings/latest.json stays as previously published.
        if scene is not None: put_json('tiles/buildings/latest.json',scene,SHORT)
        # v2: the local browser PASS measured /api/map-data bytes, not the relinked R2 objects. The public pointer moves
        # only through promote(), after a browser PASS measured against R2 itself.
        if not national:
            # A v1 upload must not roll back a promoted v2 pointer.
            if head(client,bucket,'releases/current.json') is not None:
                body=client.get_object(Bucket=bucket,Key='releases/current.json')['Body']
                try: live=json.loads(body.read())
                finally: body.close()
                if live.get('schema')==V2: raise Failure('CURRENT_IS_V2')
            put_json('releases/current.json',remote,SHORT)
        summary={'state':'uploaded-unpromoted' if national else 'uploaded-verified','sourceReleaseId':manifest['releaseId'],
            'remoteReleaseId':remote['releaseId'],**remote['publicTransfer']}
        if proof: summary['runtimeValidationSHA256']=proof['receiptSHA256']
        atomic_json(work/'result.json',summary)
        return summary


def promote(*,client,bucket,base,remote_release_id,validation,expected_current,source=None):
    """Point releases/current.json at an uploaded v2 release.

    Requires a browser PASS measured against this R2 base (receipt fields remoteReleaseId and baseUrl, bound to the
    sealed source release) and a conditional write on the current pointer (If-Match its ETag, or If-None-Match when
    absent): a stale or concurrent run cannot silently roll it back, even between our read and write.
    """
    if not re.fullmatch('[a-f0-9]{64}',remote_release_id): raise Failure('INVALID_RELEASE_ID')
    if expected_current!='none' and not re.fullmatch('[a-f0-9]{64}',expected_current): raise Failure('INVALID_EXPECTED_CURRENT')
    def read(key):
        body=client.get_object(Bucket=bucket,Key=key)['Body']
        try: return json.loads(body.read())
        finally: body.close()
    key=f'releases/{remote_release_id}/manifest.json'
    if head(client,bucket,key) is None: raise Failure('REMOTE_RELEASE_MISSING')
    remote=read(key)
    if remote.get('schema')!=V2 or remote.get('releaseId')!=remote_release_id: raise Failure('REMOTE_RELEASE_INVALID')
    if source is not None and (remote.get('sourceReleaseId')!=source.get('releaseId')): raise Failure('REMOTE_SOURCE_MISMATCH')
    try: proof=json.loads(Path(validation).read_bytes())
    except Exception: raise Failure('RUNTIME_VALIDATION_FAILED') from None
    if not isinstance(proof,dict) or proof.get('schema')!='ngii-national-browser-validation-v1'        or proof.get('releaseId')!=remote.get('sourceReleaseId') or proof.get('remoteReleaseId')!=remote_release_id        or (source is not None and proof.get('filesReceiptSHA256')!=source.get('filesReceiptSHA256'))        or proof.get('baseUrl')!=public_base(base) or proof.get('status')!='PASS' or proof.get('isolatedCandidate') is not True        or proof.get('renderer')!='national'        or any(type(proof.get(k)) is not int or proof[k]!=v for k,v in [('buildingSourceCount',1),('legacyBuildingRequests',0),('errors',0)])        or type(proof.get('terrainRequests')) is not int or proof['terrainRequests']<1        or proof.get('distances')!={'near':'PASS','mid':'PASS','far':'PASS'}:
        raise Failure('RUNTIME_VALIDATION_FAILED')
    pointer='releases/current.json'; existing=head(client,bucket,pointer)
    current=read(pointer).get('releaseId') if existing is not None else None
    # A rerun after a write that succeeded but failed verification finds itself already current.
    if current==remote_release_id: return {'state':'already-current','remoteReleaseId':remote_release_id}
    if current!=(None if expected_current=='none' else expected_current): raise Failure('CURRENT_POINTER_CHANGED')
    data=encoded(remote); expected=(hashlib.sha256(data).hexdigest(),len(data))
    condition={'IfMatch':existing['ETag']} if existing is not None else {'IfNoneMatch':'*'}
    try:
        client.put_object(Bucket=bucket,Key=pointer,Body=data,ContentType='application/json',CacheControl=SHORT,
            Metadata={'sha256':expected[0]},**condition)
    except Exception as error:
        if getattr(error,'response',{}).get('Error',{}).get('Code') in ('PreconditionFailed','412','ConditionalRequestConflict','409'): raise Failure('CURRENT_POINTER_CHANGED') from None
        raise Failure('POINTER_WRITE_FAILED') from None
    # Never blindly re-PUT: a mismatch is judged by re-reading who owns the pointer now.
    if remote_digest(client,bucket,pointer)!=expected and read(pointer).get('releaseId')!=remote_release_id: raise Failure('CURRENT_POINTER_CHANGED')
    return {'state':'promoted','remoteReleaseId':remote_release_id,'previousReleaseId':current,
        'runtimeValidationSHA256':hashlib.sha256(Path(validation).read_bytes()).hexdigest()}


def load_settings(path):
    values=dict(os.environ)
    if path and path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k,v=line.split('=',1); values[k.strip()]=v.strip().strip('"').strip("'")
    if any(not values.get(key,'').strip() for key in REQUIRED): raise Failure('R2_SETTINGS_INCOMPLETE')
    public_base(values['R2_PUBLIC_BASE_URL'])
    return values


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',type=Path,required=True); p.add_argument('--release-id',required=True)
    mode=p.add_mutually_exclusive_group(required=True); mode.add_argument('--dry-run',action='store_true'); mode.add_argument('--upload',action='store_true'); mode.add_argument('--promote',metavar='REMOTE_RELEASE_ID')
    p.add_argument('--expected-current',help='--promote: remote current releaseId this promotion replaces, or none')
    p.add_argument('--env-file',type=Path); p.add_argument('--workers',type=int,default=4); p.add_argument('--retries',type=int,default=2)
    p.add_argument('--configure-cors',action='store_true'); p.add_argument('--origin',action='append',default=[])
    p.add_argument('--runtime-validation',type=Path,help='v2 upload: measured browser PASS receipt (same as release_store activate)')
    args=p.parse_args()
    try:
        if not re.fullmatch('[a-f0-9]{64}',args.release_id): raise Failure('INVALID_RELEASE_ID')
        if not 1<=args.workers<=32 or not 0<=args.retries<=3: raise Failure('INVALID_LIMIT')
        root=args.data_root.resolve(); manifest,rows=export_plan(root,args.release_id)
        if args.dry_run:
            count=total=rewritten=0; missing=set(entry_keys(manifest)) if manifest.get('schema')==V2 else set()
            for row in rows: count+=1; total+=row['bytes']; rewritten+='sourceSHA256' in row; missing.discard(row['key'])
            if missing: raise Failure('RELEASE_ENTRY_NOT_PUBLIC')
            print(json.dumps({'state':'dry-run','schema':manifest.get('schema'),'sourceReleaseId':args.release_id,'publicFiles':count,'publicBytes':total,
                'rewrittenLinkFiles':rewritten,'networkWrites':False})); return 0
        if manifest.get('schema')==V2 and args.runtime_validation is None: raise Failure('RUNTIME_VALIDATION_REQUIRED')
        if args.promote and not args.expected_current: raise Failure('EXPECTED_CURRENT_REQUIRED')
        settings=load_settings(args.env_file)
        import boto3
        from boto3.s3.transfer import TransferConfig
        from botocore.config import Config
        client=boto3.client('s3',endpoint_url='https://'+settings['R2_ACCOUNT_ID']+'.r2.cloudflarestorage.com',
            aws_access_key_id=settings['R2_ACCESS_KEY_ID'],aws_secret_access_key=settings['R2_SECRET_ACCESS_KEY'],region_name='auto',
            config=Config(connect_timeout=15,read_timeout=120,retries={'max_attempts':2},max_pool_connections=args.workers+4))
        # Verification hashes the stored gzip bytes; never ask for a decoded representation. Everything else asks for
        # identity: R2 gzips JSON on the fly for 'gzip', and botocore's stored checksum then fails on the encoded body.
        client.meta.events.register('before-sign.s3.GetObject',lambda request,**_: request.headers.__setitem__('Accept-Encoding',
            'gzip' if urlsplit(request.url).path.endswith('.gz') else 'identity'))
        if args.configure_cors:
            if not args.origin: raise Failure('CORS_ORIGIN_REQUIRED')
            origins=[public_base(v) for v in args.origin]
            if any(urlsplit(v).path for v in origins): raise Failure('INVALID_CORS_ORIGIN')
            client.put_bucket_cors(Bucket=settings['R2_BUCKET'],CORSConfiguration={'CORSRules':[{
                'AllowedOrigins':origins,'AllowedMethods':['GET','HEAD'],
                'AllowedHeaders':['Range','If-Match','If-None-Match','If-Range'],
                'ExposeHeaders':['Content-Range','ETag','Content-Length','Accept-Ranges'],'MaxAgeSeconds':3600}]})
        if args.promote:
            print(json.dumps(promote(client=client,bucket=settings['R2_BUCKET'],base=settings['R2_PUBLIC_BASE_URL'],remote_release_id=args.promote,
                validation=args.runtime_validation,expected_current=args.expected_current,source=manifest))); return 0
        result=publish(client=client,bucket=settings['R2_BUCKET'],root=root,manifest=manifest,rows=rows,
            base=settings['R2_PUBLIC_BASE_URL'],work=root/'management/r2'/args.release_id,workers=args.workers,retries=args.retries,
            transfer_config=TransferConfig(max_concurrency=1,use_threads=False),validation=args.runtime_validation)
        print(json.dumps(result)); return 0
    except Failure as error:
        print(json.dumps({'state':'failed','code':str(error)})); return 1
    except Exception:
        print(json.dumps({'state':'failed','code':'R2_OPERATION_FAILED'})); return 1


if __name__=='__main__': raise SystemExit(main())
