"""Single-writer B021 road-area mask and immutable imagery candidate; never activates a release."""
import argparse
from collections import OrderedDict, defaultdict
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import time

import numpy as np
import pyogrio
from PIL import Image
from pmtiles.tile import Compression, TileType, zxy_to_tileid, deserialize_header, deserialize_directory
from pmtiles.writer import write
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from shapely import from_wkb, make_valid, is_valid_reason, get_coordinates
import shapely
from shapely.geometry import box, MultiPolygon
from shapely.ops import transform

spec=importlib.util.spec_from_file_location('road_sample',Path(__file__).with_name('bake-ngii-road-archive.py'))
common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)
REVISION='ngii-national-road-mask-v1'
AREAS={'11','12','26','27','28','30','31','36','41','43','44','45','47','48','50','51'}
NATIONAL=[124.,33.,132.,39.]


def atomic_json(path,value):
    path=Path(path);part=path.with_suffix(path.suffix+'.part')
    with part.open('wb') as stream:
        stream.write(common.encoded(value));stream.flush();os.fsync(stream.fileno())
    os.replace(part,path)


def plan_sources(root):
    root=Path(root).resolve();unique={};areas=set()
    inventory_path=root/'national-continuous-source-inventory.json'
    inventory_manifest=json.loads(inventory_path.read_text(encoding='utf8'))
    if (inventory_manifest.get('productCode'),inventory_manifest.get('scale'),inventory_manifest.get('year'),inventory_manifest.get('format'),inventory_manifest.get('crs'))!=('B021',5000,2024,'SHP','EPSG:5179') or 'N3A_A0010000' not in inventory_manifest.get('canonicalLayers',[]):
        raise ValueError('Official nationwide inventory product mismatch')
    inventory_sha=common.sha(inventory_path)
    for inventory in sorted(root.glob('[0-9][0-9]-source-inventory.json')):
        for row in json.loads(inventory.read_text(encoding='utf8')):
            if row.get('shp')!='N3A_A0010000.shp':continue
            area=inventory.name[:2];areas.add(area)
            path=root/row['path'] if 'path' in row else root/(area+'-files')/row['zip']
            receipt_path=Path(str(path)+'.receipt.json');receipt=json.loads(receipt_path.read_text(encoding='utf8'))
            common.validate_receipt_product(receipt)
            key=hashlib.sha256(common.encoded({'layer':'N3A_A0010000','edition':2024,'orderedPartSHA256':[receipt['sha256']]})).hexdigest()
            stamp=path.stat()
            item=dict(path=str(path),receipt=str(receipt_path),receiptSHA256=common.sha(receipt_path),sha256=receipt['sha256'],
                      bytes=stamp.st_size,mtimeNs=str(stamp.st_mtime_ns),sourceId=key,features=row['features'],aliases=[area],
                      officialInventorySHA256=inventory_sha,sourceInventorySHA256=common.sha(inventory),
                      receiptProduct={k:receipt[k] for k in ['scale','year','requestedScale','requestedYear'] if k in receipt})
            if key in unique:unique[key]['aliases']=sorted(set(unique[key]['aliases']+[area]))
            else:unique[key]=item
    if areas!=AREAS or len(unique)!=17:raise ValueError('Incomplete official A001 inventory: expected 16 provider areas / 17 distinct sources')
    return sorted(unique.values(),key=lambda row:row['sourceId'])


def layout(bounds,z=12):
    w,s,e,n=bounds
    if not (124<=w<e<=132 and 33<=s<n<=39):raise ValueError('Invalid Korea bounds')
    count=2**z
    tx=lambda lon:math.floor((lon+180)/360*count)
    ty=lambda lat:math.floor((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*count)
    x0,x1,y0,y1=tx(w),tx(e),ty(n),ty(s)
    return dict(z=z,x0=x0,y0=y0,nx=x1-x0+1,ny=y1-y0+1,width=(x1-x0+1)*256,height=(y1-y0+1)*256)


class Mask:
    def __init__(self,path,grid,cache_bytes=32*1024**2):
        self.path=Path(path);self.grid=grid;self.cache=OrderedDict();self.limit=max(1,cache_bytes//65536)
        size=grid['width']*grid['height']
        if not self.path.exists():
            common.space(self.path.parent)
            if shutil.disk_usage(self.path.parent).free < common.RESERVE+size:raise OSError('needs_storage: mask plus reserve')
            with self.path.open('wb') as stream:stream.truncate(size)
        if self.path.stat().st_size!=size:raise ValueError('Scratch mask size mismatch')
        self.file=self.path.open('r+b')
    def offset(self,key):
        x,y=key;g=self.grid
        return ((y-g['y0'])*g['nx']+x-g['x0'])*65536
    def read(self,key):
        self.file.seek(self.offset(key));raw=self.file.read(65536)
        if len(raw)!=65536:raise ValueError('Truncated scratch block')
        return np.frombuffer(raw,dtype=np.uint8).reshape(256,256)
    def save(self,key,value):
        self.file.seek(self.offset(key));self.file.write(value.tobytes())
    def block(self,key):
        if key not in self.cache:
            if len(self.cache)>=self.limit:
                old,value=self.cache.popitem(last=False);self.save(old,value)
            self.cache[key]=self.read(key).copy()
        self.cache.move_to_end(key);return self.cache[key]
    def burn(self,geometry):
        g=self.grid;step=2*common.HALF_WORLD/(2**g['z']);w,s,e,n=geometry.bounds
        x0=max(g['x0'],math.floor((w+common.HALF_WORLD)/step));x1=min(g['x0']+g['nx']-1,math.floor((e+common.HALF_WORLD)/step))
        y0=max(g['y0'],math.floor((common.HALF_WORLD-n)/step));y1=min(g['y0']+g['ny']-1,math.floor((common.HALF_WORLD-s)/step))
        for x in range(x0,x1+1):
            for y in range(y0,y1+1):
                bounds=common.tile_bounds(g['z'],x,y);clipped=geometry.intersection(box(*bounds))
                if not clipped.is_empty:rasterize([(clipped,255)],out=self.block((x,y)),transform=from_bounds(*bounds,256,256))
    def burn_batch(self,geometries):
        g=self.grid;step=2*common.HALF_WORLD/(2**g['z']);groups={};references=0
        def flush():
            for key,rows in groups.items():
                bounds=common.tile_bounds(g['z'],*key)
                clipped=shapely.intersection(np.asarray(rows,dtype=object),box(*bounds))
                shapes=[(shape,255) for shape in clipped if not shape.is_empty]
                if shapes:rasterize(shapes,out=self.block(key),transform=from_bounds(*bounds,256,256))
            groups.clear()
        for geometry in geometries:
            if geometry.is_empty:continue
            w,s,e,n=geometry.bounds
            x0=max(g['x0'],math.floor((w+common.HALF_WORLD)/step));x1=min(g['x0']+g['nx']-1,math.floor((e+common.HALF_WORLD)/step))
            y0=max(g['y0'],math.floor((common.HALF_WORLD-n)/step));y1=min(g['y0']+g['ny']-1,math.floor((common.HALF_WORLD-s)/step))
            for x in range(x0,x1+1):
                for y in range(y0,y1+1):
                    key=(x,y)
                    if (key not in groups and len(groups)>=64) or references>=4096:flush();references=0
                    groups.setdefault(key,[]).append(geometry);references+=1
        flush()
    def flush(self):
        for key,value in self.cache.items():self.save(key,value)
        self.cache.clear();self.file.flush();os.fsync(self.file.fileno())
    def close(self):
        self.flush();self.file.close()


class RoadGeometryError(ValueError):
    def __init__(self,record):
        self.record=record
        super().__init__('Rejected road geometry: '+str(record))


def repair_road_geometry(geometry):
    holes=lambda g: len(g.interiors) if g.geom_type=='Polygon' else sum(len(p.interiors) for p in g.geoms if p.geom_type=='Polygon') if hasattr(g,'geoms') else 0
    if geometry is None or geometry.is_empty or geometry.geom_type not in ('Polygon','MultiPolygon'):
        raise RoadGeometryError(dict(reason='empty-or-nonpolygon-source'))
    if geometry.is_valid and geometry.area>0:return geometry,None
    record=dict(reason=is_valid_reason(geometry),originalType=geometry.geom_type,originalAreaM2=geometry.area,originalHoles=holes(geometry))
    if not np.isfinite(get_coordinates(geometry)).all():raise RoadGeometryError({**record,'rejection':'nonfinite-coordinate'})
    repaired=make_valid(geometry,method='structure',keep_collapsed=True)
    polygons=[];residue=[]
    def collect(g):
        if g.geom_type=='Polygon' and g.area>0:polygons.append(g)
        elif hasattr(g,'geoms'):
            for part in g.geoms:collect(part)
        elif not g.is_empty:residue.append(g.geom_type)
    collect(repaired)
    if residue or not polygons:raise RoadGeometryError({**record,'rejection':'nonpolygon-residue-or-zero-area','residue':residue})
    result=polygons[0] if len(polygons)==1 else MultiPolygon(polygons)
    if not result.is_valid or result.area<=0:raise RoadGeometryError({**record,'rejection':'invalid-repair'})
    return result,{**record,'method':'make_valid-structure-keep-collapsed-audited','repairedType':result.geom_type,
                   'repairedAreaM2':result.area,'areaDeltaM2':result.area-geometry.area,'repairedHoles':holes(result),'parts':len(polygons)}


def project_road_batch(rows,geometry_name,fid_column,item,coverage,project,audit=lambda record:None):
    values=[row[geometry_name] for row in rows]
    try:geometries=shapely.from_wkb(values)
    except Exception:
        for row,value in zip(rows,values):
            try:from_wkb(value)
            except Exception as error:
                audit(dict(sourceId=item['sourceId'],FID=row[fid_column],UFID=row.get('UFID'),status='rejected',reason=str(error)));raise
        raise
    valid=shapely.is_valid(geometries)&(shapely.area(geometries)>0)&np.isin(shapely.get_type_id(geometries),[3,6])
    for index in np.flatnonzero(~valid):
        row=rows[int(index)];identity=dict(sourceId=item['sourceId'],FID=row[fid_column],UFID=row.get('UFID'))
        try:geometries[index],repair=repair_road_geometry(geometries[index])
        except RoadGeometryError as error:
            audit({**identity,'status':'rejected',**error.record});raise
        if repair:audit({**identity,'status':'repaired',**repair})
    return shapely.intersection(shapely.transform(geometries,project,interleaved=False),coverage)


def stream_source_batches(item,coverage,audit=lambda record:None):
    uri='/vsizip/'+Path(item['path']).as_posix()+'/N3A_A0010000.shp'
    project=Transformer.from_crs(5179,3857,always_xy=True).transform
    bbox=Transformer.from_crs(3857,5179,always_xy=True).transform_bounds(*coverage.bounds,densify_pts=21)
    with pyogrio.open_arrow(uri,bbox=bbox,columns=['UFID'],return_fids=True,batch_size=256,use_pyarrow=True) as (meta,reader):
        for batch in reader:
            yield project_road_batch(batch.to_pylist(),meta['geometry_name'] or 'wkb_geometry',meta['fid_column'],item,coverage,project,audit)


def stream_source(item,coverage,audit=lambda record:None):
    for batch in stream_source_batches(item,coverage,audit):yield from batch


def assert_sources(items):
    for item in items:
        stamp=Path(item['path']).stat()
        if stamp.st_size!=item['bytes'] or str(stamp.st_mtime_ns)!=item['mtimeNs'] or common.sha(item['receipt'])!=item['receiptSHA256']:
            raise ValueError('Pinned road source changed')


def pack_owned(mask,path,metadata):
    g=mask.grid;occupied=[]
    for y in range(g['y0'],g['y0']+g['ny']):
        for x in range(g['x0'],g['x0']+g['nx']):
            if mask.read((x,y)).any():occupied.append((x,y))
    if not occupied:raise ValueError('No road pixels')
    tiles=0
    with write(str(path)) as writer:
        for z in range(g['z']+1):
            factor=2**(g['z']-z);groups=defaultdict(list)
            for x,y in occupied:groups[x//factor,y//factor].append((x,y))
            for (x,y),children in sorted(groups.items(),key=lambda entry:zxy_to_tileid(z,*entry[0])):
                common.space(path.parent);alpha=np.zeros((256,256),dtype=np.uint8)
                for cx,cy in children:
                    rows,cols=np.nonzero(mask.read((cx,cy)))
                    px=(cx*256+cols-x*256*factor)//factor;py=(cy*256+rows-y*256*factor)//factor
                    alpha[py,px]=255
                rgba=np.zeros((256,256,4),dtype=np.uint8);rgba[alpha!=0]=[206,205,199,255]
                stream=io.BytesIO();Image.fromarray(rgba).save(stream,format='PNG',compress_level=6)
                payload=stream.getvalue()
                if shutil.disk_usage(path.parent).free<common.RESERVE+len(payload):raise OSError('needs_storage: PNG plus reserve')
                writer.write_tile(zxy_to_tileid(z,x,y),payload);tiles+=1
        # PMTiles finalization copies the payload spool into the immutable archive.
        if shutil.disk_usage(path.parent).free<common.RESERVE+writer.offset+64*1024**2:raise OSError('needs_storage: archive packing plus reserve')
        writer.finalize(dict(tile_type=TileType.PNG,tile_compression=Compression.NONE,min_zoom=0,max_zoom=g['z'],
            min_lon_e7=round(metadata['bounds'][0]*1e7),min_lat_e7=round(metadata['bounds'][1]*1e7),
            max_lon_e7=round(metadata['bounds'][2]*1e7),max_lat_e7=round(metadata['bounds'][3]*1e7)),metadata)
    return tiles


def pack(mask,path,metadata):
    previous=tempfile.tempdir
    try:
        tempfile.tempdir=str(path.parent)
        count=pack_owned(mask,path,metadata)
        # Installed pmtiles uses wall-clock gzip timestamps for directories/metadata.
        # Zero only those header timestamps so interrupted finalization reproduces identical bytes.
        with path.open('r+b') as stream:
            header=deserialize_header(stream.read(127))
            stream.seek(header['root_offset']);entries=deserialize_directory(stream.read(header['root_length']))
            offsets=[header['root_offset'],header['metadata_offset']]
            offsets.extend(header['leaf_directory_offset']+entry.offset for entry in entries if entry.run_length==0)
            for offset in offsets:
                stream.seek(offset)
                if stream.read(3)!=b'\x1f\x8b\x08':raise ValueError('Unexpected internal PMTiles compression')
                stream.seek(offset+4);stream.write(b'\0'*4)
        return count
    finally:tempfile.tempdir=previous


def run_owned(items,output,bounds=NATIONAL,complete=False,iterator=stream_source):
    if complete and (bounds!=NATIONAL or len(items)!=17 or len({i['sourceId'] for i in items})!=17 or set(a for item in items for a in item['aliases'])!=AREAS):
        raise ValueError('Incomplete national source set')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True);common.space(output)
    identity=dict(schema=REVISION,sourceItems=items,bounds=bounds,grid=layout(bounds),buildingLayers=False,
                  algorithm='pixel-center-native-max-pyramid',storageOrder='row-major-256px-blocks',palette=[206,205,199,255],
                  implementationSHA256=common.sha(__file__),validatorSHA256=common.sha(common.__file__),completeCoverage=complete)
    folder=output/hashlib.sha256(common.encoded(identity)).hexdigest();folder.mkdir(exist_ok=True)
    pin=folder/'inputs.json';checkpoint=folder/'checkpoint.json';receipt_file=folder/'receipt.json'
    if pin.exists():
        if pin.read_bytes()!=common.encoded(identity):raise ValueError('Road run identity mismatch')
    else:
        if any(folder.iterdir()):raise ValueError('Unbound road work directory')
        atomic_json(pin,identity)
    assert_sources(items)
    if receipt_file.exists():
        receipt=json.loads(receipt_file.read_bytes());archive=Path(receipt['archive'])
        if common.sha(archive)!=receipt['sha256'] or archive.stat().st_size!=receipt['bytes']:raise ValueError('Road archive changed')
        return receipt
    progress=json.loads(checkpoint.read_bytes()) if checkpoint.exists() else dict(completedSources=[],observedFeatures=0,repairedFeatures=0,sourceAudits=[])
    expected=[item['sourceId'] for item in items]
    if progress['completedSources']!=expected[:len(progress['completedSources'])]:raise ValueError('Invalid completed-source prefix')
    if not progress.get('validated'):
        for item in items:common.source(item['path'],item['receipt'])
        assert_sources(items);progress['validated']=True;atomic_json(checkpoint,progress)
    mask=Mask(folder/'mask.uint8',identity['grid']);started=time.monotonic()
    coverage=box(*Transformer.from_crs(4326,3857,always_xy=True).transform_bounds(*bounds))
    try:
        for item in items[len(progress['completedSources']):]:
            count=0;repairs=0;rejections=0
            audits=folder/'source-audits';audits.mkdir(exist_ok=True)
            audit_path=audits/(item['sourceId']+'.jsonl.part')
            with audit_path.open('wb') as audit_file:
                def audit(record):
                    nonlocal repairs,rejections
                    repairs+=int(record['status']=='repaired');rejections+=int(record['status']=='rejected')
                    audit_file.write(common.encoded(record)+b'\n');audit_file.flush()
                try:
                    batches=stream_source_batches(item,coverage,audit) if iterator is stream_source else ([geometry] for geometry in iterator(item,coverage))
                    for batch in batches:
                        mask.burn_batch(batch)
                        count+=len(batch)
                        if count%4096==0:
                            common.space(folder)
                            print(json.dumps(dict(phase='road-source',sourceId=item['sourceId'],acceptedFeatures=count,repairedFeatures=repairs,rejectedFeatures=rejections)),flush=True)
                except Exception as error:
                    atomic_json(folder/'failure.json',dict(sourceId=item['sourceId'],acceptedFeatures=count,repairedFeatures=repairs,rejectedFeatures=rejections,error=str(error),audit=str(audit_path)))
                    raise
                audit_file.flush();os.fsync(audit_file.fileno())
            if complete and count!=item['features']:raise ValueError('National source feature count differs from inventory')
            assert_sources(items);mask.flush()
            final_audit=audit_path.with_suffix('');os.replace(audit_path,final_audit)
            progress['sourceAudits'].append(dict(sourceId=item['sourceId'],inventoryFeatures=item['features'],acceptedFeatures=count,repairedFeatures=repairs,rejectedFeatures=rejections,auditSHA256=common.sha(final_audit),audit=str(final_audit)))
            progress['repairedFeatures']+=repairs
            progress['completedSources'].append(item['sourceId']);progress['observedFeatures']+=count
            atomic_json(checkpoint,progress)
        mask.flush();assert_sources(items)
        metadata=dict(schema=REVISION,bounds=bounds,sourcePlanSHA256=hashlib.sha256(common.encoded(items)).hexdigest(),
            sourceCount=len(items),completedSources=len(progress['completedSources']),observedFeatures=progress['observedFeatures'],
            acceptedFeatures=progress['observedFeatures'],repairedFeatures=progress['repairedFeatures'],rejectedFeatures=0,
            sourceCRS='EPSG:5179',targetCRS='EPSG:3857',buildingLayers=False,missingTile='transparent',
            completeCoverage=complete,sampleOnly=not complete,activated=False,algorithm=identity['algorithm'],usage='Display imagery only; not statutory road boundaries')
        target=folder/'roads.pmtiles';part=folder/'roads.pmtiles.part'
        tiles=pack(mask,part,metadata);assert_sources(items);checksum=common.sha(part)
        receipt={**metadata,'archive':str(target),'bytes':part.stat().st_size,'sha256':checksum,'tiles':tiles,
                 'maskBytes':mask.path.stat().st_size,'seconds':round(time.monotonic()-started,3),'sourceAudits':progress['sourceAudits']}
        common.space(folder)
        if target.exists():
            if common.sha(target)!=checksum:raise ValueError('Immutable road archive mismatch')
        else:part.rename(target)
        atomic_json(receipt_file,receipt);return receipt
    finally:mask.close()


def run(items,output,bounds=NATIONAL,complete=False,iterator=stream_source):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    # OS locks release on crashes, unlike PID sentinel files that obstruct safe resume.
    with (output/'road-bake.lock').open('a+b') as lock:
        lock.seek(0,2)
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return run_owned(items,output,bounds,complete,iterator)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--inventory-root',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--bounds',nargs=4,type=float,default=NATIONAL);parser.add_argument('--sample-province')
    args=parser.parse_args();items=plan_sources(args.inventory_root)
    complete=args.sample_province is None and args.bounds==NATIONAL
    if args.sample_province:items=[item for item in items if args.sample_province in item['aliases']]
    if not items:parser.error('No selected A001 sources')
    print(json.dumps(run(items,args.output,args.bounds,complete)))
