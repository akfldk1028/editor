"""Bounded-directory PMTiles v3 writer; compressed tile bytes remain unchanged.

The SQLite journal and payload live in an explicitly owned work directory.
Resume restores only committed payload/entry checkpoints and requires identical
caller identity. The caller must replay only IDs greater than last_tile.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from pmtiles.tile import Entry,serialize_directory,serialize_header,tileid_to_zxy,Compression

RESERVE=20*1024**3
CHUNK=4096
ROOT_LIMIT=16384-127


def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


class StreamingWriter:
    def __init__(self,work,identity,*,resume=False,reserve=RESERVE,free=None):
        self.work=Path(work).resolve();self.reserve=reserve
        self.free=free or (lambda:shutil.disk_usage(self.work).free)
        self.work.mkdir(parents=True,exist_ok=True)
        for name in ('directory.sqlite','payload.spool','leaves.spool'):
            path=self.work/name
            if path.exists() and (path.is_symlink() or path.stat().st_nlink>1):raise ValueError('Spool file aliases another path')
        self._capacity(0)
        encoded=json.dumps(identity,sort_keys=True,separators=(',',':'))
        self.db_path=self.work/'directory.sqlite';exists=self.db_path.exists()
        if exists:
            if not resume:raise ValueError('Existing writer checkpoint requires explicit resume')
            with sqlite3.connect(f'{self.db_path.as_uri()}?mode=ro',uri=True) as check:
                row=check.execute("SELECT value FROM state WHERE key='identity'").fetchone()
                if row!=(encoded,):raise ValueError('Writer input identity changed')
        elif resume:raise ValueError('No checkpoint to resume')
        elif any(self.work.iterdir()):raise ValueError('Unowned nonempty spool directory')
        self.db=sqlite3.connect(self.db_path)
        self.db.executescript('PRAGMA journal_mode=DELETE; PRAGMA cache_size=-4096; CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE IF NOT EXISTS contents(sha BLOB PRIMARY KEY,offset INTEGER,length INTEGER); CREATE TABLE IF NOT EXISTS entries(tile_id INTEGER PRIMARY KEY,offset INTEGER,length INTEGER,run_length INTEGER);')
        self.db.execute('PRAGMA locking_mode=EXCLUSIVE')
        self.db.execute('BEGIN EXCLUSIVE')
        self.db.execute("INSERT OR IGNORE INTO state VALUES('identity',?)",(encoded,))
        self.db.commit()
        row=self.db.execute("SELECT value FROM state WHERE key='checkpoint'").fetchone()
        state=json.loads(row[0]) if row else dict(offset=0,addressed=0,last_tile=-1,first_tile=None)
        self.offset=state['offset'];self.addressed=state['addressed'];self.last_tile=state['last_tile'];self.first_tile=state['first_tile']
        self.payload_path=self.work/'payload.spool'
        if exists and not self.payload_path.exists():raise ValueError('Missing checkpoint payload')
        self.payload=open(self.payload_path,'r+b' if exists else 'w+b')
        if self.payload.seek(0,2)<self.offset:raise ValueError('Checkpoint payload truncated')
        self.payload.truncate(self.offset);self.payload.seek(self.offset)
        row=self.db.execute('SELECT tile_id,offset,length,run_length FROM entries ORDER BY tile_id DESC LIMIT 1').fetchone()
        self.last_entry=list(row) if row else None
        self.pending=0;self.max_directory_entries=0

    def _capacity(self,extra):
        if self.free()<self.reserve+extra:raise OSError('needs_storage: streaming writer reserve')

    def checkpoint(self):
        self.payload.flush();os.fsync(self.payload.fileno())
        self.db.execute("INSERT OR REPLACE INTO state VALUES('checkpoint',?)",(json.dumps(dict(offset=self.offset,addressed=self.addressed,last_tile=self.last_tile,first_tile=self.first_tile)),))
        self.db.commit();self.pending=0

    def write_tile(self,tileid,data):
        if not isinstance(tileid,int) or tileid<=self.last_tile:raise ValueError('Sorted unique tile IDs required')
        tileid_to_zxy(tileid)
        self._capacity(len(data)+65536)
        checksum=hashlib.sha256(data).digest()
        found=self.db.execute('SELECT offset,length FROM contents WHERE sha=?',(checksum,)).fetchone()
        if found:
            offset,length=found
            self.payload.seek(offset)
            if length!=len(data) or self.payload.read(length)!=data:raise ValueError('Payload SHA collision or corrupted spool')
        else:
            offset=self.offset;length=len(data);self.payload.seek(offset);self.payload.write(data)
            self.db.execute('INSERT INTO contents VALUES(?,?,?)',(checksum,offset,length));self.offset+=length
        last=self.last_entry
        if last and tileid==last[0]+last[3] and offset==last[1] and length==last[2]:
            last[3]+=1;self.db.execute('UPDATE entries SET run_length=? WHERE tile_id=?',(last[3],last[0]))
        else:
            self.last_entry=[tileid,offset,length,1]
            self.db.execute('INSERT INTO entries VALUES(?,?,?,?)',tuple(self.last_entry))
        if self.first_tile is None:self.first_tile=tileid
        self.last_tile=tileid;self.addressed+=1;self.pending+=1
        if self.pending>=1000:self.checkpoint()

    def _directories(self,leaves):
        self.db.execute('DROP TABLE IF EXISTS directory_levels')
        self.db.execute('CREATE TABLE directory_levels(level INTEGER,seq INTEGER,tile_id INTEGER,offset INTEGER,length INTEGER,run_length INTEGER,PRIMARY KEY(level,seq))')
        level=0
        while True:
            query=('SELECT tile_id,offset,length,run_length FROM entries ORDER BY tile_id' if level==0 else 'SELECT tile_id,offset,length,run_length FROM directory_levels WHERE level=? ORDER BY seq')
            params=() if level==0 else (level,)
            cursor=self.db.execute(query,params);first=cursor.fetchmany(CHUNK);second=cursor.fetchmany(CHUNK)
            self.max_directory_entries=max(self.max_directory_entries,len(first))
            if not second:
                root=serialize_directory([Entry(*r) for r in first])
                if len(root)<=ROOT_LIMIT:return root,level
            if level>=3:raise ValueError('PMTiles maximum lookup depth exceeded')
            seq=0
            def write_group(rows):
                nonlocal seq
                self.max_directory_entries=max(self.max_directory_entries,len(rows))
                encoded=serialize_directory([Entry(*r) for r in rows]);offset=leaves.tell()
                self._capacity(len(encoded)+65536);leaves.write(encoded)
                self.db.execute('INSERT INTO directory_levels VALUES(?,?,?,?,?,?)',(level+1,seq,rows[0][0],offset,len(encoded),0));seq+=1
            write_group(first)
            if second:write_group(second)
            for rows in iter(lambda:cursor.fetchmany(CHUNK),[]):write_group(rows)
            level+=1

    def finalize(self,output,header,metadata):
        output=Path(output).resolve()
        if output.parent!=self.work or output.exists() or output in (self.db_path,self.payload_path):raise ValueError('Output must be a fresh owned path')
        if not self.addressed:raise ValueError('Cannot publish empty archive')
        self.checkpoint()
        with open(self.work/'leaves.spool','w+b') as leaves:
            root,depth=self._directories(leaves)
            leaves_size=leaves.tell();meta=gzip.compress(json.dumps(metadata).encode(),mtime=0)
            entries=self.db.execute('SELECT count(*) FROM entries').fetchone()[0]
            contents=self.db.execute('SELECT count(*) FROM contents').fetchone()[0]
            total_runs=self.db.execute('SELECT sum(run_length) FROM entries').fetchone()[0]
            if total_runs!=self.addressed:raise ValueError('Directory addressed count mismatch')
            h={**header,'addressed_tiles_count':self.addressed,'tile_entries_count':entries,'tile_contents_count':contents,'min_zoom':tileid_to_zxy(self.first_tile)[0],'max_zoom':tileid_to_zxy(self.last_tile)[0],'clustered':True,'internal_compression':Compression.GZIP,'root_offset':127,'root_length':len(root),'metadata_offset':127+len(root),'metadata_length':len(meta),'leaf_directory_offset':127+len(root)+len(meta),'leaf_directory_length':leaves_size,'tile_data_offset':127+len(root)+len(meta)+leaves_size,'tile_data_length':self.offset}
            self._capacity(h['tile_data_offset']+self.offset+128*1024**2)
            part=output.with_name(output.name+'.part')
            if part.exists() and (part.is_symlink() or part.stat().st_nlink>1):raise ValueError('Partial output aliases another path')
            running=hashlib.sha256()
            with open(part,'wb') as destination:
                def emit(b):destination.write(b);running.update(b)
                emit(serialize_header(h));emit(root);emit(meta)
                for source in (leaves,self.payload):
                    source.seek(0)
                    for chunk in iter(lambda:source.read(1024*1024),b''):emit(chunk)
                destination.flush();os.fsync(destination.fileno())
            checksum=digest(part)
            if checksum!=running.hexdigest():raise ValueError('Final archive readback SHA mismatch')
            part.rename(output)
            self.db.commit()
            return {'sha256':checksum,'bytes':output.stat().st_size,'addressedTiles':self.addressed,'tileEntries':entries,'tileContents':contents,'directoryDepth':depth,'maxDirectoryEntries':self.max_directory_entries}

    def close(self):
        # Only explicit checkpointed input is resumable after cancellation.
        self.db.rollback();self.payload.close();self.db.close()
