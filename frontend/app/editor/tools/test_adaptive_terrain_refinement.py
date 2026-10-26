import sqlite3
import numpy as np
import pytest
from adaptive_terrain_refinement import native_grid,grid_key,open_overlay,append_grid,RESERVE


def test_native_grid_keeps_coordinates_and_explicit_nodata():
    seen=[]
    def sample(points):
        seen.extend(points);return [None if i==0 else p[0]+p[1] for i,p in enumerate(points)]
    key=grid_key(125.1,34.09,16);grid=native_grid(sample,*key)
    assert grid.shape==(33,33) and np.isnan(grid[0,0])
    assert len(seen)==1089 and grid[-1,-1]==np.float32(sum(seen[-1]))
    width=180/2**16
    assert seen[-1][0]-seen[0][0]==width and seen[0][1]-seen[-1][1]==width
    with pytest.raises(ValueError):native_grid(lambda points:[0],*key)


def test_overlay_rejects_source_alias_low_space_and_changed_identity(tmp_path):
    source=tmp_path/'source/base.pmtiles';source.parent.mkdir();source.write_bytes(b'preserve')
    with pytest.raises(ValueError):open_overlay(source.parent,tmp_path,[source],'pin')
    with pytest.raises(OSError):open_overlay(tmp_path/'candidate',tmp_path,[source],'pin',free=lambda _:RESERVE-1)
    with open_overlay(tmp_path/'candidate',tmp_path,[source],'pin',free=lambda _:RESERVE+1) as db:
        grid=np.ones((33,33),dtype='float32');key=grid_key(125.1,34.09,16)
        first=append_grid(db,key,grid);assert append_grid(db,key,grid)==first
        with pytest.raises(ValueError):append_grid(db,key,grid+1)
    with pytest.raises(ValueError):open_overlay(tmp_path/'candidate',tmp_path,[source],'other',free=lambda _:RESERVE+1)
    assert source.read_bytes()==b'preserve'


def test_merge_preserves_bytes_and_rejects_overwrite_or_unsorted():
    from adaptive_terrain_refinement import merge_payloads
    assert list(merge_payloads([(1,b'old1'),(5,b'old5')],[(2,b'new')]))==[(1,b'old1'),(2,b'new'),(5,b'old5')]
    with pytest.raises(ValueError):list(merge_payloads([(1,b'old')],[(1,b'new')]))
    with pytest.raises(ValueError):list(merge_payloads([(2,b'a'),(1,b'b')],[]))


def test_pack_stream_roundtrip_and_immutable_base(tmp_path,monkeypatch):
    import json,hashlib,gzip
    import adaptive_terrain_refinement as module
    import terrain_packing_space
    from pmtiles.writer import write
    from pmtiles.reader import Reader,all_tiles
    from pmtiles.tile import TileType,Compression,zxy_to_tileid
    monkeypatch.setattr(terrain_packing_space,'require_capacity',lambda *a,**k:None)
    monkeypatch.setattr(module.shutil,'disk_usage',lambda _:type('Usage',(),{'free':10**15})())
    work=tmp_path/'candidate';work.mkdir();base=tmp_path/'base.pmtiles'
    original=gzip.compress(b'base-preserved',mtime=0)
    with write(str(base)) as w:
        w.write_tile(zxy_to_tileid(1,0,0),original)
        w.finalize(dict(tile_type=TileType.UNKNOWN,tile_compression=Compression.GZIP,min_lon_e7=-1800000000,min_lat_e7=-900000000,max_lon_e7=1800000000,max_lat_e7=900000000),{'maxLevel':20})
    checksum=hashlib.sha256(base.read_bytes()).hexdigest()
    db=sqlite3.connect(work/'refinement-spool.sqlite')
    db.executescript('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE tiles(id INTEGER PRIMARY KEY,data BLOB);')
    db.executemany('INSERT INTO metadata VALUES(?,?)',[('identity',json.dumps({'sourcePins':{'terrainSHA256':checksum}})),('verification',json.dumps({'passed':True,'complete':False,'sampleOnly':True,'baseArchiveSHA256':checksum,'identitySHA256':'fixture'}))])
    extra=gzip.compress(b'new-detail',mtime=0);db.execute('INSERT INTO tiles VALUES(?,?)',(zxy_to_tileid(17,1,1),extra));db.commit();db.close()
    with pytest.raises(ValueError):module.pack_candidate(base,work,work/'reject.pmtiles')
    result=module.pack_candidate(base,work,work/'candidate.pmtiles',allow_sample=True)
    with (work/'candidate.pmtiles').open('rb') as f:
        def read(offset,length):f.seek(offset);return f.read(length)
        rows=list(all_tiles(read));assert rows==[((1,0,0),original),((17,1,1),extra)]
        assert Reader(read).metadata()['maxLevel']==20
    assert result['tiles']==2 and result['published'] is False
    assert hashlib.sha256(base.read_bytes()).hexdigest()==checksum
    with pytest.raises(ValueError):module.pack_candidate(base,work,base,allow_sample=True)

