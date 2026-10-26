"""Offline candidate-only EGIS WMS tiles. Never edits a serving pointer or raw source.

plan pins provider metadata and the built-excluding diagram style; fetch resumes
only verified PNG receipts. pack refuses any pending/failed tile. A completed
archive is not permission to redistribute: provider terms require separate review.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import xml.etree.ElementTree as ET

import httpx
from PIL import Image
from pmtiles.reader import Reader
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

ENDPOINT = 'https://api.mcee.go.kr/geoserver/wms'
LAYER = 'EGIS:lv3_2025y'
RESERVE = 20 * 1024**3
MARGIN = 64 * 1024**2
MAX_RESPONSE = 2 * 1024**2
WORLD = 20037508.342789244
PYRAMID = 'z12-wms-child4-premultiplied-alpha-box-v1'
GROUPS = [('forest', '#cfdcc0', [311,321,331]),
          ('green', '#dfe8d1', [411,421,422,423,511,521,522]),
          ('farm', '#ece9da', [211,212,221,222,231,241,251,252]),
          ('bare', '#efe9de', [611,612,613,621,623]),
          ('water', '#d3e2ec', [711,712,721]),
          ('paved', '#e2e1dc', [154,155,622]), ('rail', '#d0d0cc', [153])]


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def style():
    rules=[]
    for name,color,codes in GROUPS:
        terms=['<ogc:PropertyIsEqualTo><ogc:PropertyName>l3_code</ogc:PropertyName><ogc:Literal>'+str(c)+
               '</ogc:Literal></ogc:PropertyIsEqualTo>' for c in codes]
        condition='<ogc:Or>'+''.join(terms)+'</ogc:Or>' if len(terms)>1 else terms[0]
        rules.append('<Rule><Name>'+name+'</Name><ogc:Filter>'+condition+'</ogc:Filter><PolygonSymbolizer><Fill>'+
                     '<CssParameter name="fill">'+color+'</CssParameter></Fill></PolygonSymbolizer></Rule>')
    return ('<StyledLayerDescriptor version="1.0.0" xmlns="http://www.opengis.net/sld" xmlns:ogc="http://www.opengis.net/ogc">'
            '<NamedLayer><Name>'+LAYER+'</Name><UserStyle><FeatureTypeStyle>'+''.join(rules)+
            '</FeatureTypeStyle></UserStyle></NamedLayer></StyledLayerDescriptor>')


def source_metadata(raw):
    root=ET.fromstring(raw);ns={'w':'http://www.opengis.net/wms'}
    layer=next((node for node in root.findall('.//w:Layer',ns) if node.findtext('w:Name',namespaces=ns)==LAYER),None)
    if layer is None:raise ValueError('Required official landcover layer is missing')
    geo=layer.find('w:EX_GeographicBoundingBox',ns)
    bounds=[float(geo.findtext('w:'+name,namespaces=ns)) for name in
            ('westBoundLongitude','southBoundLatitude','eastBoundLongitude','northBoundLatitude')]
    if not all(math.isfinite(x) for x in bounds) or not (-180<=bounds[0]<bounds[2]<=180 and -85<bounds[1]<bounds[3]<85):
        raise ValueError('Invalid provider coverage')
    if 'EPSG:3857' not in [x.text for x in layer.findall('w:CRS',ns)]:raise ValueError('Provider CRS unsupported')
    # Global updateSequence differs across provider replicas even when this
    # layer's metadata is identical; only this layer belongs to our source pin.
    return {'endpoint':ENDPOINT,'layer':LAYER,'title':layer.findtext('w:Title',namespaces=ns),
            'bounds':bounds,
            'layerMetadataSHA256':sha(ET.tostring(layer))}


def xy(lon,lat,z):
    n=2**z
    return (lon+180)/360*n,(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n


def keys_for(bounds):
    w,s,e,n=bounds;keys=[]
    for z in range(13):
        left,top=xy(w,n,z);right,bottom=xy(e,s,z)
        for x in range(math.floor(left),min(2**z,math.ceil(right))):
            for y in range(math.floor(top),min(2**z,math.ceil(bottom))):keys.append((z,x,y))
    return sorted(keys,key=lambda k:zxy_to_tileid(*k))


def tile_bbox(key):
    z,x,y=key;step=2*WORLD/2**z
    return [-WORLD+x*step,WORLD-(y+1)*step,-WORLD+(x+1)*step,WORLD-y*step]


def params(key):
    if key[0]!=12:raise ValueError('Only finest z12 tiles may request WMS')
    return {'service':'WMS','version':'1.3.0','request':'GetMap','layers':LAYER,'styles':'',
            'crs':'EPSG:3857','bbox':','.join(map(str,tile_bbox(key))), 'width':256,'height':256,
            'format':'image/png','transparent':'true','SLD_BODY':style()}


def check_space(folder,needed=0):
    if shutil.disk_usage(folder).free < RESERVE+MARGIN+needed:raise RuntimeError('20 GiB storage reserve')


def atomic(path,raw,immutable=False):
    check_space(path.parent,len(raw))
    if path.exists():
        if path.is_symlink():raise ValueError('Symlink output rejected')
        if immutable:
            if path.read_bytes()!=raw:raise ValueError('Immutable candidate collision: '+str(path))
            return
    temporary=path.with_name(path.name+'.part')
    with temporary.open('wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    temporary.replace(path)


@contextmanager
def locked(root):
    with (root/'writer.lock').open('a+b') as stream:
        if stream.seek(0,2)==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


class Fetcher:
    def __init__(self,client,interval=1.0,attempts=3):
        if interval<.5 or not 1<=attempts<=3:raise ValueError('Unsafe request rate/retry budget')
        self.client,self.interval,self.attempts=client,interval,attempts
        self.lock=threading.Lock();self.next=0.0

    def delay(self,seconds):
        with self.lock:self.next=max(self.next,time.monotonic()+seconds)

    def get(self,query):
        for attempt in range(self.attempts):
            with self.lock:
                wait=max(0,self.next-time.monotonic())
                if wait:time.sleep(wait)
                self.next=time.monotonic()+self.interval
            try:
                with self.client.stream('GET',ENDPOINT,params=query) as response:
                    if response.status_code in (429,502,503,504):
                        delay=2**(attempt+1)
                        retry=response.headers.get('retry-after')
                        if retry:
                            try:delay=max(delay,float(retry))
                            except ValueError:delay=max(delay,(parsedate_to_datetime(retry)-datetime.now(timezone.utc)).total_seconds())
                        if delay>60:raise ValueError('Provider Retry-After exceeds bounded retry window; resume later')
                        self.delay(max(0,delay))
                        raise httpx.HTTPStatusError('Retryable provider status',request=response.request,response=response)
                    response.raise_for_status()
                    chunks=[];total=0
                    for chunk in response.iter_bytes():
                        total+=len(chunk)
                        if total>MAX_RESPONSE:raise ValueError('WMS response exceeds byte limit')
                        chunks.append(chunk)
                    return b''.join(chunks)
            except (httpx.TransportError,httpx.HTTPStatusError) as error:
                if isinstance(error,httpx.HTTPStatusError) and error.response.status_code not in (429,502,503,504):raise
                if attempt+1==self.attempts:raise
                self.delay(2**(attempt+1))
        raise AssertionError('Unreachable')

    def metadata(self):
        return source_metadata(self.get({'service':'WMS','version':'1.3.0','request':'GetCapabilities'}))


def validate_png(raw):
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Provider did not return PNG')
    with Image.open(io.BytesIO(raw)) as image:
        if image.size!=(256,256) or image.mode!='RGBA':raise ValueError('Expected transparent 256 RGBA PNG')
        image.load()
        return image.getchannel('A').getextrema()[1]==0


def plan(work_root,metadata):
    work_root=Path(work_root).resolve();work_root.mkdir(parents=True,exist_ok=True);check_space(work_root)
    identity={'schema':'egis-landcover-archive-plan-v1','source':metadata,'sourceSHA256':sha(encoded(metadata)),
              'styleSHA256':sha(style().encode()),'zooms':[0,12],'tileSize':256,'crs':'EPSG:3857',
              'pyramid':PYRAMID,'networkZoom':12,'pillowVersion':Image.__version__,
              'classification':'diagram landcover; built classes excluded; no labels/strokes/building footprints',
              'builderSHA256':sha(Path(__file__).read_bytes())}
    identity['version']=sha(encoded(identity))
    root=work_root/identity['version'];root.mkdir(exist_ok=True)
    if root.is_symlink() or not root.resolve().is_relative_to(work_root):raise ValueError('Unsafe version directory')
    atomic(root/'plan.json',encoded(identity),True);atomic(root/'style.sld',style().encode(),True)
    (root/'tiles').mkdir(exist_ok=True)
    return root,identity


def load_plan(root):
    root=Path(root).resolve();document=json.loads((root/'plan.json').read_bytes())
    body={k:v for k,v in document.items() if k!='version'}
    if document['version']!=sha(encoded(body)) or root.name!=document['version'] \
       or document['styleSHA256']!=sha(style().encode()) or document['builderSHA256']!=sha(Path(__file__).read_bytes()) \
       or document['sourceSHA256']!=sha(encoded(document['source'])) or document['source']['endpoint']!=ENDPOINT \
       or document['source']['layer']!=LAYER or document['zooms']!=[0,12] \
       or document.get('pyramid')!=PYRAMID or document.get('pillowVersion')!=Image.__version__ \
       or (root/'style.sld').read_bytes()!=style().encode():raise ValueError('Candidate pins changed')
    if (root/'tiles').is_symlink():raise ValueError('Unsafe tile directory')
    return document


def tile_paths(root,key):
    name='-'.join(map(str,key));return root/'tiles'/(name+'.png'),root/'tiles'/(name+'.json')


def verified_receipts(root,document,keys):
    ready={}
    for key in keys:
        png,receipt=tile_paths(root,key)
        if not receipt.exists():continue
        value=json.loads(receipt.read_bytes())
        if receipt.is_symlink() or png.is_symlink():raise ValueError('Symlink tile rejected')
        raw=png.read_bytes()
        if value.get('version')!=document['version'] or value.get('key')!=list(key) \
           or value.get('sha256')!=sha(raw) or value.get('bytes')!=len(raw):raise ValueError('Tile receipt changed')
        empty=validate_png(raw)
        if value.get('alphaEmpty') is not empty or value.get('kind')!=('wms' if key[0]==12 else 'derived'):
            raise ValueError('Tile sample/derivation status changed')
        ready[key]=value
    keyset=set(keys)
    for key,value in ready.items():
        if key[0]<12:
            if value.get('pyramid')!=PYRAMID or value.get('children')!=child_evidence(key,keyset,ready):
                raise ValueError('Derived parent child receipt mismatch')
    return ready


def child_evidence(key,keyset,ready):
    z,x,y=key;evidence=[]
    for dy in (0,1):
        for dx in (0,1):
            child=(z+1,x*2+dx,y*2+dy)
            if child in keyset and child not in ready:raise ValueError('Parent requires every covered child')
            evidence.append({'key':list(child),'sha256':ready[child]['sha256'] if child in keyset else None,
                             'status':'received' if child in keyset else 'outside-provider-coverage-transparent'})
    return evidence


def parent_png(children):
    mosaic=Image.new('RGBA',(512,512),(0,0,0,0))
    for index,raw in enumerate(children):
        if raw is not None:
            validate_png(raw)
            with Image.open(io.BytesIO(raw)) as child:mosaic.paste(child,(index%2*256,index//2*256))
    # Premultiplication prevents RGB in transparent pixels creating pale/dark fringes.
    image=mosaic.convert('RGBa').resize((256,256),Image.Resampling.BOX).convert('RGBA')
    stream=io.BytesIO();image.save(stream,format='PNG',compress_level=6)
    return stream.getvalue()


def derive_parents(root,document,keys,ready):
    keyset=set(keys)
    for key in sorted(keys,reverse=True):
        if key[0]==12 or key in ready:continue
        try:evidence=child_evidence(key,keyset,ready)
        except ValueError:continue
        raw=parent_png([tile_paths(root,tuple(child['key']))[0].read_bytes() if child['sha256'] else None for child in evidence])
        value={'key':list(key),'version':document['version'],'bytes':len(raw),'sha256':sha(raw),
               'sourceSHA256':document['sourceSHA256'],'styleSHA256':document['styleSHA256'],
               'kind':'derived','pyramid':PYRAMID,'children':evidence,'alphaEmpty':validate_png(raw)}
        png,receipt=tile_paths(root,key);atomic(png,raw,True);atomic(receipt,encoded(value),True);ready[key]=value


def check_source(fetcher,document):
    if fetcher.metadata()!=document['source']:raise ValueError('Official source metadata changed; use a new candidate')


def sentinel(fetcher,root,ready):
    key=next((k for k in ready if k[0]==12),None)
    if key is None:return
    raw=fetcher.get(params(key));validate_png(raw)
    if sha(raw)!=ready[key]['sha256']:raise ValueError('Provider rendered source changed at sentinel')


def progress(root,document,ready,keys,errors,state):
    value={'schema':'egis-landcover-archive-progress-v1','version':document['version'],'pid':os.getpid(),
           'at':datetime.now(timezone.utc).isoformat(),'state':state,'completedTiles':len(ready),'totalTiles':len(keys),
           'pendingTiles':len(keys)-len(ready),'failedTiles':len(errors),'errors':errors,
           'finestReceived':sum(k[0]==12 for k in ready),'finestTotal':sum(k[0]==12 for k in keys),
           'derivedParents':sum(k[0]<12 for k in ready),'alphaEmptyTiles':sum(v['alphaEmpty'] for v in ready.values()),
           'bytes':sum(v['bytes'] for v in ready.values()),'complete':state=='packed','published':False,
           'freeBytes':shutil.disk_usage(root).free,'reserveBytes':RESERVE}
    atomic(root/'progress.json',encoded(value));return value


def fetch_tiles(root,fetcher,*,limit=0,workers=1,sample_point=None):
    if workers not in (1,2) or limit<0:raise ValueError('Workers must be 1..2 and limit nonnegative')
    root=Path(root).resolve()
    with locked(root):
        document=load_plan(root);keys=keys_for(document['source']['bounds'])
        ready=verified_receipts(root,document,keys);errors=[]
        progress(root,document,ready,keys,errors,'checking-source')
        check_source(fetcher,document);sentinel(fetcher,root,ready)
        pending=[k for k in keys if k[0]==12 and k not in ready]
        if sample_point:
            if not limit:raise ValueError('Sample ordering requires explicit bounded limit')
            x,y=xy(*sample_point,12)
            pending.sort(key=lambda k:(12-k[0],(k[1]+.5-x)**2+(k[2]+.5-y)**2))
        if limit:pending=pending[:limit]
        checked=time.monotonic()
        def get(key):
            try:
                check_space(root,MAX_RESPONSE*workers);raw=fetcher.get(params(key));validate_png(raw)
                return key,raw,None
            except Exception as error:return key,None,str(error)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for offset in range(0,len(pending),workers):
                if time.monotonic()-checked>=300:
                    check_source(fetcher,document);checked=time.monotonic()
                for key,raw,error in pool.map(get,pending[offset:offset+workers]):
                    if error:errors.append({'key':key,'error':error});continue
                    png,receipt=tile_paths(root,key)
                    value={'key':list(key),'version':document['version'],'bytes':len(raw),'sha256':sha(raw),
                           'sourceSHA256':document['sourceSHA256'],'styleSHA256':document['styleSHA256'],
                           'kind':'wms','alphaEmpty':validate_png(raw)}
                    atomic(png,raw,True);atomic(receipt,encoded(value),True);ready[key]=value
                progress(root,document,ready,keys,errors,'fetching')
                if errors:break
        check_source(fetcher,document);sentinel(fetcher,root,ready)
        derive_parents(root,document,keys,ready)
        return progress(root,document,ready,keys,errors,'failed' if errors else 'downloaded' if len(ready)==len(keys) else 'partial')


def pack(root,fetcher):
    root=Path(root).resolve()
    with locked(root):
        document=load_plan(root);keys=keys_for(document['source']['bounds']);ready=verified_receipts(root,document,keys)
        if len(ready)!=len(keys):raise ValueError('Pending/failed tiles cannot be published or packed as complete')
        check_source(fetcher,document);sentinel(fetcher,root,ready)
        total=sum(r['bytes'] for r in ready.values());check_space(root,3*total+MARGIN)
        receipt_path=root/'archive-receipt.json'
        if receipt_path.exists():
            prior=json.loads(receipt_path.read_bytes());file=root/prior['file']
            if prior['version']!=document['version'] or file_sha(file)!=prior['sha256']:raise ValueError('Immutable archive changed')
            return prior
        target=root/'landcover.pmtiles'
        if target.exists():raise ValueError('Unreceipted archive exists; preserve for review')
        # Temporary spool stays on the checked output volume, never system TEMP.
        with tempfile.TemporaryFile(dir=root) as spool, (root/'landcover.pmtiles.part').open('wb') as output:
            writer=Writer(output);writer.tile_f.close();writer.tile_f=spool
            for key in keys:
                check_space(root,ready[key]['bytes']+MARGIN)
                writer.write_tile(zxy_to_tileid(*key),tile_paths(root,key)[0].read_bytes())
            check_space(root,total+MARGIN)
            w,s,e,n=document['source']['bounds']
            writer.finalize({'tile_type':TileType.PNG,'tile_compression':Compression.NONE,
                             'min_lon_e7':round(w*1e7),'min_lat_e7':round(s*1e7),'max_lon_e7':round(e*1e7),'max_lat_e7':round(n*1e7)},
                            {'name':'EGIS 2025 diagram landcover','attribution':'기후에너지환경부 환경공간정보서비스, 토지피복 세분류 [2025]',
                             'source':document['source'],'sourceSHA256':document['sourceSHA256'],'styleSHA256':document['styleSHA256'],
                             'pyramid':PYRAMID,'networkZoom':12,'pillowVersion':Image.__version__,
                             'bounds':','.join(map(str,document['source']['bounds'])),'minzoom':0,'maxzoom':12,
                             'format':'png','type':'baselayer','candidateOnly':True})
        part=root/'landcover.pmtiles.part'
        with part.open('rb') as stream:
            def read(offset,length):stream.seek(offset);return stream.read(length)
            reader=Reader(read)
            for key in keys:
                if sha(reader.get(*key))!=ready[key]['sha256']:raise ValueError('Packed tile mismatch')
        check_source(fetcher,document);sentinel(fetcher,root,ready)
        checksum=file_sha(part);part.replace(target)
        result={'schema':'egis-landcover-archive-receipt-v1','version':document['version'],'file':target.name,
                'sha256':checksum,'bytes':target.stat().st_size,'tiles':len(keys),'bounds':document['source']['bounds'],
                'sourceSHA256':document['sourceSHA256'],'styleSHA256':document['styleSHA256'],
                'pyramid':PYRAMID,'networkZoom':12,'alphaEmptyTiles':sum(v['alphaEmpty'] for v in ready.values()),
                'complete':True,'published':False,'redistributionAuthorization':'not established by this receipt',
                'sourceConsistency':'layer capabilities metadata and repeated sentinel; not a transactional provider snapshot'}
        atomic(receipt_path,encoded(result),True)
        progress(root,document,ready,keys,[],'packed')
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['plan','fetch','pack'])
    parser.add_argument('--work-root',type=Path);parser.add_argument('--work',type=Path)
    parser.add_argument('--capabilities-file',type=Path)
    parser.add_argument('--limit',type=int,default=0);parser.add_argument('--workers',type=int,default=1)
    parser.add_argument('--interval',type=float,default=1.0)
    parser.add_argument('--sample-point',type=float,nargs=2,metavar=('LON','LAT'))
    args=parser.parse_args()
    if args.operation=='plan' and not args.work_root:parser.error('plan requires --work-root')
    if args.operation!='plan' and not args.work:parser.error('fetch/pack requires --work')
    with httpx.Client(timeout=httpx.Timeout(25,connect=8),follow_redirects=False,trust_env=False) as client:
        fetcher=Fetcher(client,args.interval)
        if args.operation=='plan':
            metadata=source_metadata(args.capabilities_file.read_bytes()) if args.capabilities_file else fetcher.metadata()
            root,document=plan(args.work_root,metadata)
            result={'work':str(root),'version':document['version'],'totalTiles':len(keys_for(metadata['bounds'])),'complete':False}
        elif args.operation=='fetch':result=fetch_tiles(args.work,fetcher,limit=args.limit,workers=args.workers,sample_point=args.sample_point)
        else:result=pack(args.work,fetcher)
        print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
