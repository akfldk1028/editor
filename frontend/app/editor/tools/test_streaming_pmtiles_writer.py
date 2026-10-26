import gzip
import tracemalloc
import pytest
from pmtiles.reader import Reader,all_tiles
from pmtiles.tile import TileType,Compression,zxy_to_tileid
from streaming_pmtiles_writer import StreamingWriter,ROOT_LIMIT

HEADER=dict(tile_type=TileType.UNKNOWN,tile_compression=Compression.GZIP,min_lon_e7=1200000000,min_lat_e7=300000000,max_lon_e7=1350000000,max_lat_e7=400000000)


def inspect(path):
    f=path.open('rb')
    def read(offset,length):f.seek(offset);return f.read(length)
    return f,Reader(read),read


def test_roundtrip_dedup_runs_and_header(tmp_path):
    writer=StreamingWriter(tmp_path/'work',{'source':'pinned'},reserve=0)
    data=[gzip.compress(b'A',mtime=0),gzip.compress(b'B',mtime=0)]
    rows=[(1,data[0]),(2,data[0]),(4,data[1]),(5,data[0])]
    try:
        for key,payload in rows:writer.write_tile(key,payload)
        output=writer.work/'result.pmtiles';proof=writer.finalize(output,HEADER,{'schema':'fixture'})
        with pytest.raises(ValueError):writer.finalize(output,HEADER,{})
    finally:writer.close()
    f,reader,read=inspect(output)
    try:
        actual=[(zxy_to_tileid(*key),payload) for key,payload in all_tiles(read)]
        assert actual==rows
        h=reader.header();assert h['addressed_tiles_count']==4 and h['tile_entries_count']==3 and h['tile_contents_count']==2
        assert h['clustered'] and h['root_length']<=ROOT_LIMIT
        assert reader.metadata()=={'schema':'fixture'}
        assert proof['bytes']==output.stat().st_size
    finally:f.close()


def test_resume_discards_uncommitted_input_and_rejects_alias(tmp_path):
    work=tmp_path/'work';writer=StreamingWriter(work,{'source':'same'},reserve=0)
    writer.write_tile(1,b'a');writer.checkpoint();writer.write_tile(2,b'uncommitted');writer.close()
    with pytest.raises(ValueError):StreamingWriter(work,{'source':'other'},resume=True,reserve=0)
    with pytest.raises(ValueError):StreamingWriter(work,{'source':'same'},reserve=0)
    writer=StreamingWriter(work,{'source':'same'},resume=True,reserve=0)
    try:
        assert writer.last_tile==1 and writer.offset==1
        with pytest.raises(ValueError):writer.write_tile(1,b'a')
        writer.write_tile(2,b'b')
        with pytest.raises(ValueError):writer.finalize(tmp_path/'outside.pmtiles',HEADER,{})
        writer.finalize(work/'valid.pmtiles',HEADER,{})
    finally:writer.close()
    f,_,read=inspect(work/'valid.pmtiles')
    try:assert [payload for _,payload in all_tiles(read)]==[b'a',b'b']
    finally:f.close()


def test_100k_unique_entries_have_bounded_python_memory(tmp_path):
    tracemalloc.start();writer=StreamingWriter(tmp_path/'work',{'source':'100k'},reserve=0)
    try:
        for i in range(100000):writer.write_tile(i,(i.to_bytes(8,'little')))
        output=writer.work/'large.pmtiles';proof=writer.finalize(output,{**HEADER,'tile_compression':Compression.NONE},{'count':100000})
        peak=tracemalloc.get_traced_memory()[1]
    finally:writer.close();tracemalloc.stop()
    assert peak<20*1024**2
    assert proof['maxDirectoryEntries']<=4096 and proof['directoryDepth']>=1
    f,reader,read=inspect(output)
    try:
        count=0
        for key,payload in all_tiles(read):
            assert zxy_to_tileid(*key)==count and payload==count.to_bytes(8,'little');count+=1
        assert count==100000 and reader.header()['tile_entries_count']==100000
    finally:f.close()
    import psutil
    memory=psutil.Process().memory_info()
    print({'entries':100000,'pythonPeakBytes':peak,'processPeakWorkingSetBytes':getattr(memory,'peak_wset',memory.rss),**proof})


def test_capacity_guard(tmp_path):
    with pytest.raises(OSError):StreamingWriter(tmp_path/'work',{},free=lambda:0)


def test_multiple_directory_tiers_are_standard_reader_compatible(tmp_path,monkeypatch):
    import streaming_pmtiles_writer as module
    monkeypatch.setattr(module,'CHUNK',8);monkeypatch.setattr(module,'ROOT_LIMIT',64)
    writer=StreamingWriter(tmp_path/'work',{},reserve=0)
    try:
        for i in range(1000):writer.write_tile(i,i.to_bytes(8,'little'))
        proof=writer.finalize(writer.work/'nested.pmtiles',{**HEADER,'tile_compression':Compression.NONE},{})
    finally:writer.close()
    assert proof['directoryDepth']>=2
    f,_,read=inspect(tmp_path/'work/nested.pmtiles')
    try:assert [(zxy_to_tileid(*k),v) for k,v in all_tiles(read)]==[(i,i.to_bytes(8,'little')) for i in range(1000)]
    finally:f.close()


def test_unowned_payload_or_hardlink_is_never_overwritten(tmp_path):
    import os
    work=tmp_path/'work';work.mkdir();source=tmp_path/'source';source.write_bytes(b'original')
    os.link(source,work/'payload.spool')
    with pytest.raises(ValueError):StreamingWriter(work,{},reserve=0)
    assert source.read_bytes()==b'original'
