"""Read-only native road mask → area-coverage pyramid. Never activates imagery."""
import argparse
from collections import defaultdict
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil

import numpy as np
from PIL import Image
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import write

spec=importlib.util.spec_from_file_location('road_repack_base',Path(__file__).with_name('bake-ngii-national-roads.py'))
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
common=base.common
REVISION='native-pixel-area-average-alpha-v1'


class ReadMask:
    def __init__(self,path,grid):
        self.path=Path(path);self.grid=grid
        if self.path.stat().st_size!=grid['width']*grid['height']:raise ValueError('Mask size mismatch')
        self.file=self.path.open('rb')
    def read(self,key):
        x,y=key;g=self.grid
        if not(g['x0']<=x<g['x0']+g['nx'] and g['y0']<=y<g['y0']+g['ny']):raise ValueError('Mask bounds')
        self.file.seek(((y-g['y0'])*g['nx']+x-g['x0'])*65536)
        raw=self.file.read(65536)
        if len(raw)!=65536:raise ValueError('Truncated mask')
        a=np.frombuffer(raw,dtype=np.uint8).reshape(256,256)
        if not np.isin(a,[0,255]).all():raise ValueError('Nonbinary native mask')
        return a


def coverage(mask,z,x,y,children):
    factor=2**(mask.grid['z']-z)
    counts=np.zeros(65536,dtype=np.uint32)
    for cx,cy in children:
        rows,cols=np.nonzero(mask.read((cx,cy)))
        px=(cx*256+cols-x*256*factor)//factor
        py=(cy*256+rows-y*256*factor)//factor
        counts+=np.bincount(py*256+px,minlength=65536).astype(np.uint32)
    # Round once from native counts: no repeated 8-bit quantization between levels.
    return np.floor(counts.reshape(256,256).astype(np.float64)*255/(factor*factor)+0.5).astype(np.uint8)


def png(alpha):
    rgba=np.zeros((256,256,4),dtype=np.uint8)
    rgba[alpha!=0,:3]=[206,205,199];rgba[:,:,3]=alpha
    # PNG stores straight alpha; constant RGB is equivalent to filtering
    # premultiplied road color, then unpremultiplying for PNG storage.
    out=io.BytesIO();Image.fromarray(rgba).save(out,format='PNG',compress_level=6)
    return out.getvalue()


def pack_owned(mask,path,metadata):
    g=mask.grid;occupied=[]
    for y in range(g['y0'],g['y0']+g['ny']):
        for x in range(g['x0'],g['x0']+g['nx']):
            if mask.read((x,y)).any():occupied.append((x,y))
    tiles=0
    with write(str(path)) as writer:
        for z in range(g['z']+1):
            factor=2**(g['z']-z);groups=defaultdict(list)
            for x,y in occupied:groups[x//factor,y//factor].append((x,y))
            for (x,y),children in sorted(groups.items(),key=lambda entry:zxy_to_tileid(z,*entry[0])):
                common.space(path.parent);alpha=coverage(mask,z,x,y,children)
                if not alpha.any():continue
                payload=png(alpha)
                writer.write_tile(zxy_to_tileid(z,x,y),payload);tiles+=1
        if shutil.disk_usage(path.parent).free<common.RESERVE+writer.offset+64*1024**2:raise OSError('needs_storage: archive packing plus reserve')
        writer.finalize(dict(tile_type=TileType.PNG,tile_compression=Compression.NONE,min_zoom=0,max_zoom=g['z'],
            min_lon_e7=round(metadata['bounds'][0]*1e7),min_lat_e7=round(metadata['bounds'][1]*1e7),
            max_lon_e7=round(metadata['bounds'][2]*1e7),max_lat_e7=round(metadata['bounds'][3]*1e7)),metadata)
    return tiles


def pin_source(folder):
    folder=Path(folder).resolve();receipt_path=folder/'receipt.json'
    receipt=json.loads(receipt_path.read_text(encoding='utf8'))
    inputs=json.loads((folder/'inputs.json').read_text(encoding='utf8'))
    if not receipt.get('completeCoverage') or receipt.get('sampleOnly') or receipt.get('completedSources')!=17 or receipt.get('rejectedFeatures')!=0:raise ValueError('Incomplete source receipt')
    items=inputs['sourceItems'];audits=receipt['sourceAudits']
    if hashlib.sha256(common.encoded(inputs)).hexdigest()!=folder.name or hashlib.sha256(common.encoded(items)).hexdigest()!=receipt['sourcePlanSHA256']:raise ValueError('Source identity mismatch')
    if not inputs.get('completeCoverage') or inputs['grid']!=base.layout(base.NATIONAL) or receipt['bounds']!=base.NATIONAL:raise ValueError('Native grid contract mismatch')
    base.assert_sources(items)
    if len(items)!=17 or len({r['sourceId'] for r in items})!=17 or {a for r in items for a in r['aliases']}!=base.AREAS:raise ValueError('Incomplete source pins')
    if {r['sourceId'] for r in items}!={r['sourceId'] for r in audits}:raise ValueError('Source audit set mismatch')
    source_counts={r['sourceId']:r['features'] for r in items}
    for row in audits:
        if row['acceptedFeatures']!=row['inventoryFeatures'] or row['inventoryFeatures']!=source_counts[row['sourceId']] or row['rejectedFeatures'] or common.sha(row['audit'])!=row['auditSHA256']:raise ValueError('Source audit mismatch')
    if sum(r['acceptedFeatures'] for r in audits)!=receipt['acceptedFeatures']:raise ValueError('Source count mismatch')
    if sum(r['repairedFeatures'] for r in audits)!=receipt['repairedFeatures']:raise ValueError('Repair count mismatch')
    archive=folder/'roads.pmtiles'
    if archive.stat().st_size!=receipt['bytes'] or common.sha(archive)!=receipt['sha256']:raise ValueError('Archive pin mismatch')
    mask=folder/'mask.uint8';stamp=mask.stat()
    if stamp.st_size!=receipt['maskBytes']:raise ValueError('Mask receipt mismatch')
    return receipt,inputs['grid'],dict(receiptSHA256=common.sha(receipt_path),inputsSHA256=common.sha(folder/'inputs.json'),
        maskSHA256=common.sha(mask),maskBytes=stamp.st_size,maskMtimeNs=str(stamp.st_mtime_ns))


def run_owned(source,output):
    source=Path(source).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True);common.space(output)
    receipt,grid,pin=pin_source(source)
    identity=dict(recipe=REVISION,source=str(source),pin=pin,implementationSHA256=common.sha(__file__),packingHelperSHA256=common.sha(base.__file__))
    version=hashlib.sha256(common.encoded(identity)).hexdigest();folder=output/version
    folder.mkdir(exist_ok=True)
    if (folder/'receipt.json').exists():
        done=json.loads((folder/'receipt.json').read_text(encoding='utf8'))
        if done['identity']!=identity or common.sha(folder/'roads.pmtiles')!=done['sha256']:raise ValueError('Existing output mismatch')
        return done
    final=folder/'roads.pmtiles'
    metadata={k:v for k,v in receipt.items() if k not in ('archive','bytes','sha256','seconds','tiles','maskBytes','sourceItems','sourceAudits')}
    metadata.update(algorithm=REVISION,hierarchy='native-area-average-coverage',alphaQuantization='round-nearest-8bit-once-per-level',sourceArchiveSHA256=receipt['sha256'])
    mask=ReadMask(source/'mask.uint8',grid);part=folder/'roads.pmtiles.part'
    try:
        # Private imported module only: reuse deterministic directory gzip and same-volume spool.
        base.pack_owned=pack_owned
        tiles=base.pack(mask,part,metadata)
    finally:mask.file.close()
    stamp=(source/'mask.uint8').stat()
    if (stamp.st_size,str(stamp.st_mtime_ns),common.sha(source/'mask.uint8'))!=(pin['maskBytes'],pin['maskMtimeNs'],pin['maskSHA256']):raise ValueError('Native mask changed')
    if common.sha(source/'receipt.json')!=pin['receiptSHA256'] or common.sha(source/'inputs.json')!=pin['inputsSHA256']:raise ValueError('Source metadata changed')
    done=dict(metadata,identity=identity,archive=str(final),tiles=tiles,bytes=part.stat().st_size,sha256=common.sha(part),sourceAudits=receipt['sourceAudits'],activated=False)
    if final.exists():
        if final.stat().st_size!=done['bytes'] or common.sha(final)!=done['sha256']:raise ValueError('Immutable archive mismatch')
    else:os.rename(part,final)
    base.atomic_json(folder/'receipt.json',done)
    return done


def run(source,output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    with (output/'road-repack.lock').open('a+b') as lock:
        lock.seek(0,2)
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return run_owned(source,output)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();print(json.dumps(run(a.source,a.output),ensure_ascii=False))
