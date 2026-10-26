import importlib.util
from pathlib import Path
import sqlite3
import numpy as np
from pmtiles.tile import zxy_to_tileid

MODULE = Path(__file__).with_name('incremental_terrain_archive.py')


def implementation():
    assert MODULE.exists(), 'incremental terrain builder is not implemented'
    spec = importlib.util.spec_from_file_location('incremental_terrain_archive', MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fine_patch_invalidates_ancestors_and_neighbor_support():
    m = implementation()
    # A tiny patch just east of an L15 tile border also influences its west
    # neighbor's shared grid sample and all coarse ancestors.
    x, y, level = 56000, 9600, 15
    width = 180 / 2**level
    lon, lat = -180 + x * width, 90 - y * width
    patch = (lon + 1e-7, lat - 1e-6, lon + 1e-6, lat - 1e-7)
    keys = [(level, x-1, y), (level, x, y), (11, x//16, y//16), (level, x+100, y)]
    got = m.affected_keys(keys, [patch])
    assert got == keys[:3]


def test_only_affected_tile_bytes_change_and_nodata_key_is_retained():
    m = implementation()
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE tiles(id INTEGER PRIMARY KEY,data BLOB NOT NULL)')
    before = [(1, b'unchanged-compressed-payload'), (2, b'old'), (3, b'explicit-nodata')]
    db.executemany('INSERT INTO tiles VALUES(?,?)', before)
    m.replace_existing_tiles(db, [(2, b'new')])
    assert db.execute('SELECT * FROM tiles ORDER BY id').fetchall() == [before[0], (2, b'new'), before[2]]
    try:
        m.replace_existing_tiles(db, [(4, b'new-key')])
    except ValueError:
        pass
    else:
        assert False, 'must reject unexpected tile keys'


def test_real_warp_patch_and_nodata_preservation(tmp_path):
    m = implementation()
    import rasterio
    from rasterio.transform import from_origin
    from terrain_archive import grid_view, read_grid
    level, x, y = 10, 1746, 300
    width = 180 / 2**level
    west, north = -180+x*width, 90-y*width
    transform = from_origin(west-width, north+width, width/128, width/128)
    profile = dict(driver='GTiff',width=384,height=384,count=1,dtype='float32',crs=4326,transform=transform,nodata=-9999)
    a=np.full((384,384),10,dtype='float32');a[128:256,128:256]=-9999
    b=a.copy();b[125:132,125:132]=30
    paths=[]
    for name,arr in [('base',a),('layered',b)]:
        p=tmp_path/(name+'.tif');paths.append(p)
        with rasterio.open(p,'w',**profile) as ds:ds.write(arr,1)
    keys=[(level,x-1,y-1),(level,x,y),(level-1,x//2,y//2),(level,x+10,y)]
    patch=(west-3*width/128,north-4*width/128,west+4*width/128,north+3*width/128)
    selected=m.affected_keys(keys,[patch])
    with rasterio.open(paths[0]) as old, rasterio.open(paths[1]) as new:
        changed=[]
        for lev,xx,yy in keys:
            with grid_view(old,lev) as ov,grid_view(new,lev) as nv:
                og,ng=read_grid(ov,xx,yy),read_grid(nv,xx,yy)
                if not np.array_equal(og,ng,equal_nan=True):changed.append((lev,xx,yy))
        assert changed
        assert set(changed)<=set(selected)
        with grid_view(new,level) as view:
            assert np.isnan(read_grid(view,x,y)[16,16])


def test_baseline_attachment_is_read_only(tmp_path):
    m = implementation()
    baseline = tmp_path/'baseline.sqlite'
    with sqlite3.connect(baseline) as db:
        db.execute('CREATE TABLE tiles(id INTEGER PRIMARY KEY,data BLOB)')
        db.execute('INSERT INTO tiles VALUES(1,?)',(b'original',))
    assert hasattr(m, 'open_checkpoint'), 'URI-enabled candidate connection is required'
    with m.open_checkpoint(tmp_path/'candidate.sqlite') as db:
        db.execute('ATTACH DATABASE ? AS original',(baseline.as_uri()+'?mode=ro',))
        assert db.execute('SELECT data FROM original.tiles').fetchone()[0] == b'original'
        try:
            db.execute('UPDATE original.tiles SET data=?',(b'changed',))
        except sqlite3.OperationalError as error:
            assert 'readonly' in str(error)
        else:
            assert False, 'baseline attachment must reject writes'


def test_extension_accepts_insertion_but_rejects_changed_or_reordered_layers():
    m=implementation()
    assert hasattr(m,'extension_sources'), 'validated layer extension is required'
    a={'path':'a.tif','sha256':'a','priority':0}
    b={'path':'b.tif','sha256':'b','priority':1}
    added={'path':'c.tif','sha256':'c','priority':0}
    assert m.extension_sources([a,b],[a,added,b]) == [added]
    import pytest
    for bad in [[b,a], [a], [dict(a,sha256='changed'),b]]:
        with pytest.raises(ValueError):m.extension_sources([a,b],bad)


def test_new_detail_keys_include_all_levels_and_neighbors():
    m=implementation()
    assert hasattr(m,'detail_keys'), 'explicit new detail key expansion is required'
    keys=m.detail_keys([{'point':[127.2,37.7]}],20)
    assert len(keys)==45
    for level in range(16,21):
        width=180/2**level
        import math
        x,y=math.floor((127.2+180)/width),math.floor((90-37.7)/width)
        assert {(level,x+dx,y+dy) for dx in (-1,0,1) for dy in (-1,0,1)} <= keys


def test_added_patch_outside_previous_footprint_invalidates_ancestors():
    m=implementation()
    old={'path':'old.tif','sha256':'a','bounds':(126,35,126.01,35.01)}
    new={'path':'new.tif','sha256':'b','bounds':(128,38,128.01,38.01)}
    added=m.extension_sources([old],[old,new])
    import math
    keys=[]
    for level in (11,15,20):
        width=180/2**level
        keys.append((level,math.floor((128.005+180)/width),math.floor((90-38.005)/width)))
    assert m.affected_keys(keys,[old['bounds']])==[]
    assert m.affected_keys(keys,[item['bounds'] for item in added])==keys


def test_explicit_replacement_tracks_removal_addition_and_source_order():
    m=implementation()
    assert hasattr(m,'replacement_sources'), 'explicit replacement mode is required'
    a={'path':'a.tif','sha256':'a'};b={'path':'b.tif','sha256':'b'};c={'path':'c.tif','sha256':'c'}
    sources,changes=m.replacement_sources([a,b],[b,c])
    assert {s['path'] for s in sources}=={'a.tif','b.tif','c.tif'}
    assert changes['removed']==['a.tif'] and changes['added']==['c.tif']
    sources,changes=m.replacement_sources([a,b],[b,a])
    assert changes['retainedOrderChanged'] is True
    assert len(sources)==2


def test_sequential_reuse_proof_rejects_removed_keys_and_changed_reused_bytes():
    m=implementation()
    assert hasattr(m,'verify_reuse_stream'), 'sequential preservation proof is required'
    before=[(1,b'a'),(3,b'old'),(5,b'no-data')]
    after=[(1,b'a'),(2,b'new'),(3,b'new-value'),(5,b'no-data')]
    assert m.verify_reuse_stream(iter(before),iter(after),{3},{2})=={'unchangedTileByteDifferences':0,'addedKeys':1,'removedKeys':0,'unexpectedAddedKeys':0,'missingRequestedKeys':0}
    import pytest
    with pytest.raises(ValueError):m.verify_reuse_stream(iter(before),iter(after[:-1]),{3},{2})
    with pytest.raises(ValueError):m.verify_reuse_stream(iter(before),iter([(1,b'corrupted')]+after[1:]),{3},{2})
    with pytest.raises(ValueError):m.verify_reuse_stream(iter(before),iter(after),{3},set())


def test_replacement_cli_resamples_changed_layer_and_preserves_keyset(tmp_path,monkeypatch):
    m=implementation()
    import json,gzip,math,sys,rasterio
    from rasterio.transform import from_origin
    from pyproj import Transformer
    from terrain_archive import grid_view,read_grid,encode_grid
    x,y=Transformer.from_crs(4326,5186,always_xy=True).transform(127,37)
    transform=from_origin(x-20,y+20,5,5)
    for name,value in [('base',10),('old',20),('new',30)]:
        with rasterio.open(tmp_path/(name+'.tif'),'w',driver='GTiff',width=8,height=8,count=1,
                           dtype='float32',crs=5186,transform=transform,nodata=-9999) as dst:
            dst.write(np.full((8,8),value,dtype='float32'),1)
    def vrt(name,sources):
        content=f'<VRTDataset rasterXSize="8" rasterYSize="8"><SRS>EPSG:5186</SRS><GeoTransform>{transform.c},5,0,{transform.f},0,-5</GeoTransform><VRTRasterBand dataType="Float32" band="1"><NoDataValue>-9999</NoDataValue>'
        for source in sources:
            content+=f'<ComplexSource><SourceFilename relativeToVRT="0">{source.as_posix()}</SourceFilename><SourceBand>1</SourceBand><SrcRect xOff="0" yOff="0" xSize="8" ySize="8"/><DstRect xOff="0" yOff="0" xSize="8" ySize="8"/><NODATA>-9999</NODATA></ComplexSource>'
        path=tmp_path/(name+'.vrt');path.write_text(content+'</VRTRasterBand></VRTDataset>');return path
    base=vrt('base',[tmp_path/'base.tif'])
    old=vrt('old',[base,tmp_path/'old.tif']);new=vrt('new',[base,tmp_path/'new.tif'])
    manifests=[]
    for name,layered in [('old',old),('new',new)]:
        patch=tmp_path/(name+'.tif');document={'base':str(base),'layered':str(layered),'sources':[{'path':str(patch),'sha256':m.sha(patch)}]}
        path=tmp_path/(name+'.json');path.write_text(json.dumps(document));manifests.append(path)
    width=180/2**20;xx,yy=math.floor(307/width),math.floor(53/width);tileid=zxy_to_tileid(21,xx,yy)
    with rasterio.open(old) as ds,grid_view(ds,20) as view:data=gzip.compress(encode_grid(read_grid(view,xx,yy)),mtime=0,compresslevel=1)
    metadata=dict(vrt_sha256=m.sha(old),sourceFilesSHA256=m.signature(m.source_stamps(old)),samplerSHA256=m.sampler_signature(),explicitNoData=True,
                  bounds=[126.9,36.9,127.1,37.1],minLevel=20,maxLevel=20,tiles=1)
    database=tmp_path/'old.sqlite'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE tiles(id INTEGER PRIMARY KEY,data BLOB)');db.execute('INSERT INTO tiles VALUES(?,?)',(tileid,data))
        db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)')
        db.executemany('INSERT INTO metadata VALUES(?,?)',[('sourceSignature',metadata['sourceFilesSHA256']),('samplerSignature',metadata['samplerSHA256'])])
    receipt=tmp_path/'receipt.json';receipt.write_text(json.dumps({'tiles':1,'metadata':metadata}))
    work=tmp_path/'work';output=tmp_path/'output'
    monkeypatch.setattr(sys,'argv',['builder','--manifest',str(manifests[1]),'--previous-manifest',str(manifests[0]),'--replace-precision-layers',
        '--old-dem',str(old),'--old-db',str(database),'--old-receipt',str(receipt),'--work',str(work),'--output',str(output),'--workers','1'])
    m.main()
    result=json.loads((work/'archive-receipt.json').read_text())
    assert result['tiles']==1 and result['verification']['removedKeys']==0
    with sqlite3.connect(next(work.glob('terrain-*.sqlite'))) as db:newdata=db.execute('SELECT data FROM tiles WHERE id=?',(tileid,)).fetchone()[0]
    values=np.frombuffer(gzip.decompress(newdata),dtype='<f4',offset=8)
    assert np.allclose(values[np.isfinite(values)],30)
    assert newdata!=data
