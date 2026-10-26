"""Read-only completed B021 road index to bounded high-resolution imagery."""
import asyncio
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid
import zlib

import numpy as np
from PIL import Image
from rasterio.features import rasterize
from rasterio.transform import from_bounds
import shapely

from .map_ground_imagery import validate_png, ImageryUnavailable

STYLE = 'native-road-area-rgba206-205-199-coverage4x-box-colorbleed-v3'
STYLE_SHA = hashlib.sha256(STYLE.encode()).hexdigest()
FIELDS = {'schema','version','file','sha256','complete','sourceCount','rows','repairs','rejected'}
MAX_ROWS = 20000


def stamp(path):
    value=path.stat()
    return value.st_size,value.st_mtime_ns


def query_png(path,z,x,y):
    world=math.pi*6378137;span=2*world/2**z
    bounds=(-world+x*span,world-(y+1)*span,-world+(x+1)*span,world-y*span)
    w,s,e,n=bounds;mask=np.zeros((1024,1024),dtype=np.uint8);count=0
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)
    try:
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA cache_size=-8192');db.execute('PRAGMA threads=1')
        deadline=time.monotonic()+15
        db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
        cursor=db.execute('SELECT r.wkb FROM bounds b JOIN roads r ON r.id=b.id WHERE b.minx<=? AND b.maxx>=? AND b.miny<=? AND b.maxy>=?',(e,w,n,s))
        while rows:=cursor.fetchmany(64):
            count+=len(rows)
            if count>MAX_ROWS or time.monotonic()>deadline:raise ImageryUnavailable('Road imagery query budget exceeded')
            geometries=[];batch_bytes=0
            for row in rows:
                decoder=zlib.decompressobj();raw=decoder.decompress(row[0],16*1024**2)
                batch_bytes+=len(raw)
                if not decoder.eof or decoder.unused_data or batch_bytes>32*1024**2:raise ImageryUnavailable('Road geometry exceeds memory budget')
                geometries.append(shapely.from_wkb(raw))
            rasterize([(g,255) for g in geometries],out=mask,transform=from_bounds(*bounds,1024,1024))
    finally:db.close()
    alpha=np.asarray(Image.fromarray(mask).resize((256,256),Image.Resampling.BOX))
    rgba=np.empty((256,256,4),dtype=np.uint8);rgba[:,:,:3]=[206,205,199];rgba[:,:,3]=alpha
    output=io.BytesIO();Image.fromarray(rgba).save(output,format='PNG',compress_level=6)
    return output.getvalue()


class RoadImagery:
    def __init__(self,*,data_root=None):
        data=Path(data_root or os.environ.get('DATA_ROOT') or Path(__file__).resolve().parents[4]/'data').resolve()
        self.root=data/'world-ground/road-index';self.cache=data/'cache/world-ground/road-imagery'
        self.pending={};self.slots=asyncio.Semaphore(2);self.binding=None;self.lock=threading.Lock()

    def select(self):
        pointer=self.root/'latest.json'
        if pointer.is_symlink() or pointer.stat().st_size>4096:raise ImageryUnavailable('Road index unavailable')
        raw=pointer.read_bytes();value=json.loads(raw)
        if (set(value)!=FIELDS or value['schema']!='ngii-native-road-index-pointer-v1' or value['complete'] is not True
            or any(type(value[k]) is not int or value[k]!=v for k,v in [('sourceCount',17),('rows',8976641),('repairs',37),('rejected',0)])
            or value['file']!='roads.sqlite' or any(not isinstance(value[k],str) or not re.fullmatch('[a-f0-9]{64}',value[k]) for k in ('version','sha256'))):
            raise ImageryUnavailable('Completed national road index required')
        folder=self.root/value['version'];path=folder/value['file']
        if folder.is_symlink() or path.is_symlink() or path.resolve()!=self.root.resolve()/value['version']/'roads.sqlite':raise ImageryUnavailable('Road index path rejected')
        if any(Path(str(path)+suffix).exists() and Path(str(path)+suffix).stat().st_size for suffix in ('-wal','-journal')):raise ImageryUnavailable('Road index is writable')
        identity=(raw,stamp(path))
        with self.lock:
            if self.binding and self.binding[0]['version']==value['version']:
                if self.binding[2]!=identity:raise ImageryUnavailable('Road index changed')
                return self.binding
            before=stamp(path)
            with path.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
            if checksum!=value['sha256'] or before!=stamp(path):raise ImageryUnavailable('Road index fingerprint mismatch')
            db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)
            try:
                sources=list(db.execute('SELECT sourceId,ordinal,expected,next_row FROM sources'))
                meta=json.loads(db.execute('SELECT identity FROM metadata').fetchone()[0])
                if (len(sources)!=17 or {s[1] for s in sources}!=set(range(1,18)) or sum(s[2] for s in sources)!=8976641
                    or any(s[2]!=s[3] for s in sources) or db.execute('SELECT count(*) FROM repairs').fetchone()[0]!=37
                    or meta['schema']!='ngii-native-road-index-v2' or meta['nationalSelection'] is not True):
                    raise ImageryUnavailable('Road index completion mismatch')
            finally:db.close()
            if before!=stamp(path) or raw!=pointer.read_bytes():raise ImageryUnavailable('Road index changed')
            self.binding=(value,path,identity)
            return self.binding

    def image(self,key):
        selection=self.select();value,path,identity=selection
        epoch=hashlib.sha256((value['sha256']+STYLE_SHA).encode()).hexdigest()
        png=self.cache/epoch/('-'.join(map(str,key))+'.png');receipt=png.with_suffix('.json');raw=None
        try:
            if png.stat().st_size<=1024**2 and receipt.stat().st_size<=4096 and not png.is_symlink() and not receipt.is_symlink():
                record=json.loads(receipt.read_bytes())
                candidate=png.read_bytes()
                if (record['epoch']==epoch and 0<=time.time()-record['at']<86400
                    and record['sha256']==hashlib.sha256(candidate).hexdigest()):validate_png(candidate);raw=candidate
        except (OSError,KeyError,TypeError,ValueError,ImageryUnavailable):pass
        if raw is None:
            raw=query_png(path,*key);empty=validate_png(raw)
            if self.select()!=selection:raise ImageryUnavailable('Road index changed')
            png.parent.mkdir(parents=True,exist_ok=True)
            record={'epoch':epoch,'sourceIndexSHA256':value['sha256'],'styleSHA256':STYLE_SHA,'at':time.time(),
                    'sha256':hashlib.sha256(raw).hexdigest(),'alphaEmpty':empty}
            for target,content in ((png,raw),(receipt,json.dumps(record).encode())):
                part=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
                try:part.write_bytes(content);part.replace(target)
                finally:part.unlink(missing_ok=True)
        if self.select()!=selection:raise ImageryUnavailable('Road index changed')
        return raw

    async def get(self,z,x,y):
        if not 13<=z<=17 or not 0<=x<2**z or not 0<=y<2**z:raise ValueError('Invalid road tile')
        key=z,x,y
        if key not in self.pending:
            if len(self.pending)>=64:raise ImageryUnavailable('Road imagery busy')
            task=asyncio.create_task(self.load(key));self.pending[key]=task
            task.add_done_callback(lambda t:t.exception() if not t.cancelled() else None)
        return await asyncio.shield(self.pending[key])

    async def load(self,key):
        try:
            async with self.slots:return await asyncio.to_thread(self.image,key)
        except (OSError,ValueError,KeyError,TypeError,sqlite3.Error,shapely.errors.GEOSException):
            raise ImageryUnavailable('Road imagery unavailable') from None
        finally:self.pending.pop(key,None)
