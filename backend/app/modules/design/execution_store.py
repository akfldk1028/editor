from contextlib import contextmanager, closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .artifacts import _linked
from .native_repository import NativeJobUnavailable, canonical_json


class ExecutionConflict(RuntimeError):
    pass


def encoded(value):
    return canonical_json(value, max_bytes=32*1024*1024, max_nodes=2000000)


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class ExecutionStore:
    def __init__(self, directory):
        self.path = Path(directory)/'executions.sqlite'
        if not self.path.is_absolute():
            raise NativeJobUnavailable('Absolute execution directory required')
        self.safe()

    def safe(self):
        paths = (self.path,*self.path.parents,*(Path(str(self.path)+suffix) for suffix in ('-wal','-shm','-journal')))
        if any(_linked(path) for path in paths):
            raise NativeJobUnavailable('Linked execution storage is unsupported')

    @contextmanager
    def connection(self, write=False):
        self.safe()
        if write:self.path.parent.mkdir(parents=True,exist_ok=True)
        try:
            with closing(sqlite3.connect(str(self.path) if write else self.path.as_uri()+'?mode=ro',
                                        uri=not write,timeout=20)) as db:
                db.row_factory=sqlite3.Row
                if write:db.execute('BEGIN IMMEDIATE')
                version=db.execute('PRAGMA user_version').fetchone()[0]
                if version==0 and write and not db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    db.execute('CREATE TABLE attempts (attempt_id TEXT PRIMARY KEY, actor TEXT, project_id TEXT, job_id TEXT, '
                        'request_id TEXT, seed TEXT, scene_revision INTEGER, status TEXT, token TEXT, cancel INTEGER, '
                        'created_at TEXT, prepared TEXT, prepared_sha TEXT, result TEXT, result_sha TEXT, '
                        'UNIQUE(actor,project_id,request_id))')
                    db.execute("CREATE UNIQUE INDEX active_job ON attempts(actor,project_id,job_id) WHERE status IN ('queued','running')")
                    db.execute('CREATE TABLE events (attempt_id TEXT, sequence INTEGER, data TEXT, PRIMARY KEY(attempt_id,sequence))')
                    db.execute('PRAGMA user_version=1')
                elif version!=1:
                    raise NativeJobUnavailable('Execution schema unavailable')
                try:
                    yield db
                    if write:db.commit()
                except BaseException:
                    if write:db.rollback()
                    raise
        except sqlite3.IntegrityError:
            raise ExecutionConflict('An active attempt already exists') from None
        except (sqlite3.Error,OSError):
            raise NativeJobUnavailable('Execution storage unavailable') from None

    @staticmethod
    def summary(row):
        return {key:row[key] for key in ('attempt_id','project_id','job_id','request_id','seed','scene_revision','status','created_at')}

    @staticmethod
    def append(db,attempt,event):
        seq=db.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE attempt_id=?',(attempt,)).fetchone()[0]
        db.execute('INSERT INTO events VALUES (?,?,?)',(attempt,seq,encoded({**event,'sequence':seq})))

    def enqueue(self,actor,project,job,request,seed,revision):
        prepared=encoded(job['prepared'])
        with self.connection(True) as db:
            existing=db.execute('SELECT * FROM attempts WHERE actor=? AND project_id=? AND request_id=?',(actor,project,request)).fetchone()
            if existing:
                if (existing['job_id'],existing['seed'],existing['scene_revision'],existing['prepared_sha'])!=(job['job_id'],str(seed),revision,digest(prepared)):
                    raise ExecutionConflict('Request identity has different execution inputs')
                return self.summary(existing)
            attempt=uuid4().hex
            db.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (attempt,actor,project,job['job_id'],request,str(seed),revision,'queued',None,0,
                 datetime.now(timezone.utc).isoformat(),prepared,digest(prepared),None,None))
            self.append(db,attempt,{'type':'queued'})
            return self.summary(db.execute('SELECT * FROM attempts WHERE attempt_id=?',(attempt,)).fetchone())

    def get(self,actor,project,attempt):
        self.safe()
        if not self.path.exists():return None
        with self.connection() as db:
            row=db.execute('SELECT * FROM attempts WHERE actor=? AND project_id=? AND attempt_id=?',(actor,project,attempt)).fetchone()
            return dict(row) if row else None

    def list(self,actor,project,job,limit=20,offset=0):
        if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or not 0<=offset<2**63:
            raise ValueError('Invalid attempt page')
        self.safe()
        if not self.path.exists():return []
        with self.connection() as db:
            return [self.summary(row) for row in db.execute('SELECT * FROM attempts WHERE actor=? AND project_id=? AND job_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?',(actor,project,job,limit,offset))]

    def events(self,attempt,after):
        with self.connection() as db:
            try:
                values=[]
                for row in db.execute('SELECT sequence,data FROM events WHERE attempt_id=? AND sequence>? ORDER BY sequence LIMIT 200',(attempt,after)):
                    value=json.loads(row['data'])
                    if not isinstance(value,dict) or value.get('sequence')!=row['sequence'] or not isinstance(value.get('type'),str):
                        raise ValueError('Invalid event')
                    values.append(value)
                return values
            except (ValueError,TypeError):
                raise NativeJobUnavailable('Execution event data unavailable') from None

    def cancel(self,actor,project,attempt):
        with self.connection(True) as db:
            row=db.execute('SELECT * FROM attempts WHERE actor=? AND project_id=? AND attempt_id=?',(actor,project,attempt)).fetchone()
            if not row:return None
            if row['status'] in ('queued','running') and not row['cancel']:
                status='cancelled' if row['status']=='queued' else 'running'
                db.execute('UPDATE attempts SET cancel=1,status=? WHERE attempt_id=?',(status,attempt))
                self.append(db,attempt,{'type':'cancelled' if status=='cancelled' else 'cancel_requested'})
            return self.summary(db.execute('SELECT * FROM attempts WHERE attempt_id=?',(attempt,)).fetchone())

    def recover(self):
        if not self.path.exists():return
        with self.connection(True) as db:
            for row in db.execute("SELECT attempt_id FROM attempts WHERE status='running'").fetchall():
                db.execute("UPDATE attempts SET status='interrupted',token=NULL WHERE attempt_id=?",(row[0],))
                self.append(db,row[0],{'type':'interrupted','reason':'worker_ownership_lost'})

    def claim(self):
        if not self.path.exists():return None
        with self.connection(True) as db:
            row=db.execute("SELECT * FROM attempts WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:return None
            token=uuid4().hex
            db.execute("UPDATE attempts SET status='running',token=? WHERE attempt_id=?",(token,row['attempt_id']))
            self.append(db,row['attempt_id'],{'type':'running'})
            return {**dict(row),'token':token,'status':'running'}

    @staticmethod
    def owned(db,attempt,token):
        row=db.execute("SELECT * FROM attempts WHERE attempt_id=? AND token=? AND status='running'",(attempt,token)).fetchone()
        if not row:raise ExecutionConflict('Worker no longer owns attempt')
        return row

    def event(self,attempt,token,event):
        with self.connection(True) as db:
            self.owned(db,attempt,token)
            self.append(db,attempt,event)

    def cancelled(self,attempt,token):
        with self.connection() as db:return bool(self.owned(db,attempt,token)['cancel'])

    def finish(self,attempt,token,result=None,error=None):
        with self.connection(True) as db:
            row=self.owned(db,attempt,token)
            if error:
                status='failed'; data=None; sha=None
            else:
                status='cancelled' if row['cancel'] else result['status']
                if status not in ('computed','cancelled'):raise ValueError('Invalid terminal computation status')
                result={**result,'status':status}
                if result['events']:
                    result['events'][-1]={**result['events'][-1],'type':status}
                data=encoded(result);sha=digest(data)
            db.execute('UPDATE attempts SET status=?,token=NULL,result=?,result_sha=? WHERE attempt_id=?',(status,data,sha,attempt))
            self.append(db,attempt,{'type':status,**({'error':error} if error else {'result_sha256':sha})})
