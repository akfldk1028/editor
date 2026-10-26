"""Bounded, road-only B021 imagery candidate. Not a nationwide source-completeness gate."""
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import shutil
import zipfile

import numpy as np
import pyogrio
from PIL import Image
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import write
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from shapely import from_wkb
from shapely.geometry import box
from shapely.ops import transform

REVISION = 'ngii-road-imagery-sample-v1'
RESERVE = 20 * 1024**3
HALF_WORLD = math.pi * 6378137


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def space(path):
    if shutil.disk_usage(path).free < RESERVE:
        raise OSError('needs_storage: 20GiB reserve')


def validate_receipt_product(receipt):
    for direct, requested, expected in [('scale','requestedScale',5000),('year','requestedYear',2024)]:
        values=[receipt[key] for key in (direct,requested) if key in receipt]
        if not values or any(type(value) not in (int,str) or str(value)!=str(expected) for value in values):
            raise ValueError('Expected official B021 5000/2024 SHP receipt')
    if receipt.get('provider')!='NGII' or receipt.get('format')!='SHP':
        raise ValueError('Expected official B021 5000/2024 SHP receipt')


def source(zip_path, receipt_path, centerlines=False):
    zip_path = Path(zip_path).resolve()
    receipt = json.loads(Path(receipt_path).read_text(encoding='utf8'))
    validate_receipt_product(receipt)
    if '(B021)' not in zip_path.name:
        raise ValueError('Expected official B021 5000/2024 SHP receipt')
    if zip_path.stat().st_size != receipt.get('bytes') or sha(zip_path) != receipt.get('sha256'):
        raise ValueError('Source receipt SHA/size mismatch')
    # Multidisk input needs separately bounded member staging, never silent partial ZIP reads.
    with zip_path.open('rb') as stream:
        stream.seek(max(0, zip_path.stat().st_size - 65557)); tail = stream.read()
    eocd = tail.rfind(b'PK\x05\x06')
    if eocd < 0 or int.from_bytes(tail[eocd+4:eocd+6], 'little') or int.from_bytes(tail[eocd+6:eocd+8], 'little'):
        raise ValueError('Split ZIP requires bounded member staging')
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    members = [name for name in names if name.lower().endswith('.shp')]
    if len(members) != 1:
        raise ValueError('Expected exactly one road SHP')
    member = members[0]
    area = Path(member).stem == 'N3A_A0010000'
    if not area and not (centerlines and Path(member).stem == 'N3L_A0020000'):
        raise ValueError('Only road area A001, or explicit one-pixel A002, is allowed')
    uri = '/vsizip/' + zip_path.as_posix() + '/' + member
    info = pyogrio.read_info(uri)
    if info['crs'] != 'EPSG:5179' or info['geometry_type'] not in (('Polygon', 'MultiPolygon') if area else ('LineString', 'MultiLineString')):
        raise ValueError('Road CRS or geometry mismatch')
    stamp = zip_path.stat()
    return dict(uri=uri, path=str(zip_path), stamp=(stamp.st_size, stamp.st_mtime_ns), area=area,
                provenance={key: receipt[key] for key in ('provider', 'province', 'scale', 'year', 'requestedScale', 'requestedYear', 'format', 'sha256', 'bytes') if key in receipt},
                member=member, receiptSHA256=sha(receipt_path))


def tile_bounds(z, x, y):
    width = 2 * HALF_WORLD / 2**z
    return (-HALF_WORLD+x*width, HALF_WORLD-(y+1)*width, -HALF_WORLD+(x+1)*width, HALF_WORLD-y*width)


def jobs(bounds, min_zoom, max_zoom):
    w,s,e,n = bounds
    if not (124 <= w < e <= 132 and 33 <= s < n <= 39 and 0 <= min_zoom <= max_zoom <= 12):
        raise ValueError('Expected Korea bounds and zooms 0..12')
    rows = []
    for z in range(min_zoom, max_zoom+1):
        size = 2**z
        x = lambda lon: math.floor((lon+180)/360*size)
        y = lambda lat: math.floor((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*size)
        rows.extend((z,a,b) for a in range(x(w),x(e)+1) for b in range(y(n),y(s)+1))
    if len(rows) > 512:
        raise ValueError('Sample limited to 512 tiles; national spatial staging is not implemented')
    return sorted(rows, key=lambda row: zxy_to_tileid(*row))


def geometries(item, clip):
    project = Transformer.from_crs(5179,3857,always_xy=True).transform
    query = Transformer.from_crs(3857,5179,always_xy=True).transform_bounds(*clip.bounds, densify_pts=21)
    with pyogrio.open_arrow(item['uri'], bbox=query, columns=[], batch_size=256, use_pyarrow=True) as (meta, reader):
        for batch in reader:
            name = meta['geometry_name'] or 'wkb_geometry'
            for value in batch.column(name):
                if value.as_py() is None:
                    continue
                geometry = from_wkb(value.as_py())
                if not geometry.is_valid:
                    raise ValueError('Invalid source road geometry; explicit repair audit required')
                geometry = transform(project, geometry).intersection(clip)
                if not geometry.is_empty:
                    yield geometry


def raster_tile(items, tile, coverage, iterator=geometries):
    bounds = tile_bounds(*tile)
    clip = box(*bounds).intersection(coverage)
    mask = np.zeros((256,256), dtype=np.uint8)
    if not clip.is_empty:
        for item in items:
            batch = []
            for geometry in iterator(item, clip):
                batch.append((geometry,255))
                if len(batch) == 256:
                    rasterize(batch,out=mask,transform=from_bounds(*bounds,256,256));batch=[]
            if batch:
                rasterize(batch,out=mask,transform=from_bounds(*bounds,256,256))
    rgba = np.zeros((256,256,4),dtype=np.uint8)
    rgba[mask != 0] = [206,205,199,255]
    stream = io.BytesIO();Image.fromarray(rgba).save(stream,format='PNG',compress_level=6)
    return stream.getvalue(), bool(mask.any())


def bake(inputs, output, bounds, min_zoom=0, max_zoom=12):
    selected = jobs(bounds,min_zoom,max_zoom)
    public_sources = [{k:item[k] for k in ('provenance','member','receiptSHA256','area')} for item in inputs]
    identity = dict(schema=REVISION,sources=public_sources,bounds=bounds,minZoom=min_zoom,maxZoom=max_zoom,
                    implementationSHA256=sha(__file__),buildingLayers=False,centerlineStyle='one-pixel-display-only' if any(not i['area'] for i in inputs) else None)
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True);space(output)
    folder=output/hashlib.sha256(encoded(identity)).hexdigest();folder.mkdir(exist_ok=True)
    pin=folder/'inputs.json'
    if pin.exists() and pin.read_bytes()!=encoded(identity):raise ValueError('Output identity mismatch')
    if not pin.exists():pin.write_bytes(encoded(identity))
    target=folder/'roads.pmtiles';receipt_path=folder/'receipt.json'
    if receipt_path.exists():
        receipt=json.loads(receipt_path.read_bytes())
        if target.stat().st_size!=receipt['bytes'] or sha(target)!=receipt['sha256']:raise ValueError('Existing archive mismatch')
        return receipt
    if target.exists():raise ValueError('Unreceipted immutable archive; manual validation required')
    projected=Transformer.from_crs(4326,3857,always_xy=True).transform_bounds(*bounds)
    coverage=box(*projected);nonempty=0;part=folder/'roads.pmtiles.part'
    with write(str(part)) as writer:
        for tile in selected:
            space(output)
            png,filled=raster_tile(inputs,tile,coverage)
            if filled:writer.write_tile(zxy_to_tileid(*tile),png);nonempty+=1
        if not nonempty:raise ValueError('No road pixels at selected zooms')
        writer.finalize(dict(tile_type=TileType.PNG,tile_compression=Compression.NONE,
            min_zoom=min_zoom,max_zoom=max_zoom,min_lon_e7=round(bounds[0]*1e7),min_lat_e7=round(bounds[1]*1e7),
            max_lon_e7=round(bounds[2]*1e7),max_lat_e7=round(bounds[3]*1e7)),
            {**identity,'missingTile':'transparent','sampleOnly':True,'publishable':False})
    for item in inputs:
        stamp=Path(item['path']).stat()
        if (stamp.st_size,stamp.st_mtime_ns)!=item['stamp']:raise ValueError('Road source changed during bake')
    space(output)
    receipt={**identity,'archive':str(target),'sha256':sha(part),'bytes':part.stat().st_size,
             'tilesConsidered':len(selected),'tilesWritten':nonempty,'sampleOnly':True,'publishable':False}
    part.rename(target)
    temporary=folder/'receipt.json.part';temporary.write_bytes(encoded(receipt));temporary.rename(receipt_path)
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',action='append',required=True)
    parser.add_argument('--receipt',action='append',required=True)
    parser.add_argument('--centerline-one-pixel',action='store_true')
    parser.add_argument('--bounds',nargs=4,type=float,required=True)
    parser.add_argument('--min-zoom',type=int,default=0);parser.add_argument('--max-zoom',type=int,default=12)
    parser.add_argument('--output',required=True);args=parser.parse_args()
    if len(args.source)!=len(args.receipt):parser.error('Every source needs its receipt')
    items=[source(p,r,args.centerline_one_pixel) for p,r in zip(args.source,args.receipt)]
    print(json.dumps(bake(items,args.output,args.bounds,args.min_zoom,args.max_zoom)))
