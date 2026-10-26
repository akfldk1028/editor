"""Candidate-only native 33x33 refinement primitives; never modify a base archive."""
import gzip
import hashlib
import math
from pathlib import Path
import shutil
import sqlite3

import numpy as np
from pmtiles.tile import zxy_to_tileid
from terrain_archive import encode_grid

RESERVE = 20 * 1024**3
RECIPE = 'native-anchor-adaptive-grid-v1'


def grid_key(lon, lat, level):
    if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon < 180 and -90 < lat <= 90 and 16 <= level <= 20):
        raise ValueError('Invalid adaptive detail point/level')
    width = 180 / 2**level
    return level, math.floor((lon + 180) / width), math.floor((90 - lat) / width)


def native_grid(sample, level, x, y):
    if not (16 <= level <= 20 and 0 <= x < 2**(level+1) and 0 <= y < 2**level):
        raise ValueError('Invalid native detail tile')
    width = 180 / 2**level
    points = [[-180 + (x + col/32)*width, 90 - (y + row/32)*width] for row in range(33) for col in range(33)]
    values = sample(points)
    if len(values) != 1089 or any(v is not None and (not math.isfinite(v) or not -500 <= v <= 9000) for v in values):
        raise ValueError('Invalid native grid response')
    # Unsupported vertices stay NaN. The shared display resolver, not this writer,
    # decides which existing ancestor supports them; never synthesize zero here.
    return np.asarray([np.nan if v is None else v for v in values], dtype='<f4').reshape(33,33)


def open_overlay(work, data_root, protected, identity, *, free=None):
    work, root = Path(work).resolve(), Path(data_root).resolve()
    if not work.is_relative_to(root) or work == root:
        raise ValueError('Candidate work must be below DATA_ROOT')
    protected = [Path(p).resolve() for p in protected]
    destination = work/'refinement-spool.sqlite'
    for source in protected:
        if destination == source or work == source or work == source.parent:
            raise ValueError('Candidate aliases a protected source directory/file')
        if destination.exists() and source.exists() and destination.samefile(source):
            raise ValueError('Candidate hardlink aliases protected source')
    work.mkdir(parents=True, exist_ok=True)
    available = (free or (lambda p: shutil.disk_usage(p).free))(work)
    if available < RESERVE:
        raise OSError('needs_storage: 20GiB reserve')
    if destination.exists():
        with sqlite3.connect(destination.as_uri()+'?mode=ro',uri=True) as prior:
            try: row=prior.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
            except sqlite3.DatabaseError as exc: raise ValueError('Not an owned refinement overlay') from exc
            if row != (identity,): raise ValueError('Overlay identity changed')
    db = sqlite3.connect(destination)
    db.execute('CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    existing = db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
    if existing and existing[0] != identity:
        db.close();raise ValueError('Overlay identity changed')
    db.execute("INSERT OR IGNORE INTO metadata VALUES('identity',?)",(identity,))
    db.execute('CREATE TABLE IF NOT EXISTS tiles(id INTEGER PRIMARY KEY,level INTEGER NOT NULL,x INTEGER NOT NULL,y INTEGER NOT NULL,data BLOB NOT NULL,decoded_sha256 TEXT NOT NULL)')
    db.commit()
    return db


def append_grid(db, key, grid):
    decoded = encode_grid(grid); data = gzip.compress(decoded, compresslevel=1, mtime=0)
    tileid = zxy_to_tileid(key[0]+1,key[1],key[2]); checksum = hashlib.sha256(decoded).hexdigest()
    old = db.execute('SELECT data,decoded_sha256 FROM tiles WHERE id=?',(tileid,)).fetchone()
    if old is not None and old != (data,checksum):
        raise ValueError('Immutable overlay tile differs')
    db.execute('INSERT OR IGNORE INTO tiles VALUES(?,?,?,?,?,?)',(tileid,*key,data,checksum))
    return len(data), checksum

def merge_payloads(base, additions):
    """Sorted streaming union. Existing native payloads may never be overwritten."""
    base=iter(base); additions=iter(additions)
    a=next(base,None); b=next(additions,None); previous=-1
    while a is not None or b is not None:
        if a is not None and b is not None and a[0]==b[0]:
            raise ValueError('Overlay attempts to replace immutable base tile')
        if b is None or (a is not None and a[0]<b[0]):
            row=a;a=next(base,None)
        else:row=b;b=next(additions,None)
        if row[0]<=previous:raise ValueError('Tile stream is not strictly ordered')
        previous=row[0]
        yield row


def pack_candidate(base, work, output, *, allow_sample=False):
    """Reuse base compressed payload bytes; only the small overlay is SQLite-backed."""
    import json,tempfile
    from pmtiles.reader import Reader,all_tiles
    from streaming_pmtiles_writer import StreamingWriter
    from pmtiles.tile import TileType,Compression
    from terrain_packing_space import require_capacity
    from incremental_terrain_archive import sha,atomic_json
    base=Path(base).resolve();work=Path(work).resolve();output=Path(output).resolve()
    if output.parent!=work or output.exists() or output==base:raise ValueError('Fresh candidate output must be inside owned work')
    overlay=work/'refinement-spool.sqlite'
    if (work/'refinement.lock').exists():raise ValueError('Refinement worker still owns candidate')
    wal=Path(str(overlay)+'-wal')
    if wal.exists() and wal.stat().st_size:raise ValueError('Overlay has pending WAL')
    before=[(p,p.stat().st_size,p.stat().st_mtime_ns) for p in (base,overlay)]
    with sqlite3.connect(f'{overlay.as_uri()}?mode=ro',uri=True) as db:
        identity=json.loads(db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()[0])
        proof=json.loads(db.execute("SELECT value FROM metadata WHERE key='verification'").fetchone()[0])
        if not proof['passed'] or (not proof['complete'] and not allow_sample):raise ValueError('Incomplete refinement proof')
        if sha(base)!=proof['baseArchiveSHA256']:raise ValueError('Base archive changed')
        if identity['sourcePins']['terrainSHA256']!=proof['baseArchiveSHA256']:raise ValueError('Base pin mismatch')
        extra=db.execute('SELECT coalesce(sum(length(data)),0) FROM tiles').fetchone()[0]
        bound=base.stat().st_size+extra;volume=work.anchor
        require_capacity({volume:shutil.disk_usage(work).free},volume,volume,bound)
        with base.open('rb') as source:
            def get_bytes(offset,length):source.seek(offset);return source.read(length)
            reader=Reader(get_bytes);meta=reader.metadata();header=reader.header()
            metadata={**meta,'maxLevel':20,'adaptiveRefinement':{'recipe':RECIPE,'baseArchiveSHA256':proof['baseArchiveSHA256'],'identitySHA256':proof['identitySHA256'],'sampleOnly':proof['sampleOnly']},'explicitNoData':True}
            old=((zxy_to_tileid(*key),data) for key,data in all_tiles(get_bytes))
            added=db.execute('SELECT id,data FROM tiles ORDER BY id')
            spool=work/'packing-spool'
            if spool.resolve().parent!=work:raise ValueError('Spool directory aliases another root')
            writer_identity={'baseSHA256':proof['baseArchiveSHA256'],'overlaySHA256':sha(overlay),'proof':proof,'writerSHA256':sha(Path(__file__).with_name('streaming_pmtiles_writer.py'))}
            writer=StreamingWriter(spool,writer_identity,resume=(spool/'directory.sqlite').exists())
            try:
                count=0
                for tileid,data in merge_payloads(old,added):
                    if tileid>writer.last_tile:writer.write_tile(tileid,data)
                    count+=1
                if count!=writer.addressed:raise ValueError('Resumed payload count mismatch')
                metadata['tiles']=count
                writer.finalize(spool/output.name,dict(tile_type=TileType.UNKNOWN,tile_compression=Compression.GZIP,**{k:header[k] for k in ['min_lon_e7','min_lat_e7','max_lon_e7','max_lat_e7']}),metadata)
                (spool/output.name).rename(output)
            finally:writer.close()
    if any(p.stat().st_size!=size or p.stat().st_mtime_ns!=mtime for p,size,mtime in before):raise ValueError('Packing input changed; output unverified')
    checksum=sha(output)
    receipt={'archive':str(output),'sha256':checksum,'bytes':output.stat().st_size,'tiles':count,'metadata':metadata,'published':False,'independentPackedArchiveVerificationRequired':True}
    atomic_json(work/'archive-receipt.json',receipt)
    return receipt


if __name__=='__main__':
    import argparse,json
    p=argparse.ArgumentParser();p.add_argument('--base',required=True);p.add_argument('--work',required=True);p.add_argument('--output',required=True);p.add_argument('--allow-sample',action='store_true')
    a=p.parse_args();print(json.dumps(pack_candidate(a.base,a.work,a.output,allow_sample=a.allow_sample)))

