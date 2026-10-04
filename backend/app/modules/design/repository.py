from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


JSON_FIELDS = {'jobs': ('site_polygon', 'job_spec', 'constraints'),
               'results': ('inputs', 'outputs', 'mass_geojson'),
               'revisions': ('graph_diff', 'validation', 'reference_evidence', 'revision_evaluation')}


class DesignRepository:
    def __init__(self, directory):
        root = Path(directory)
        if not root.is_absolute():
            raise ValueError('Design directory must be absolute')
        self.path = root / 'design.sqlite'

    @staticmethod
    def _ensure_schema(db):
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1):
            raise ValueError('Unsupported design schema version')
        if version == 0:
            db.execute('CREATE TABLE sources (source_id TEXT PRIMARY KEY,created_at TEXT NOT NULL)')
            db.execute('CREATE TABLE jobs (source_id TEXT,job_id TEXT,created_at TEXT,source_status TEXT,row_json TEXT,row_sha256 TEXT,PRIMARY KEY(source_id,job_id))')
            db.execute('CREATE TABLE results (source_id TEXT,result_pk INTEGER,job_id TEXT,generation INTEGER,design_id INTEGER,has_mass INTEGER,summary_json TEXT,row_json TEXT,row_sha256 TEXT,PRIMARY KEY(source_id,result_pk))')
            db.execute('CREATE INDEX results_job ON results(source_id,job_id,generation,design_id,result_pk)')
            db.execute('CREATE TABLE revisions (source_id TEXT,revision_id TEXT,job_id TEXT,row_json TEXT,row_sha256 TEXT,PRIMARY KEY(source_id,revision_id))')
            db.execute('CREATE TABLE imports (source_id TEXT,snapshot_sha256 TEXT,imported_at TEXT,counts_json TEXT,PRIMARY KEY(source_id,snapshot_sha256))')
            db.execute('CREATE TABLE attachments (actor TEXT,project_id TEXT,scene_id TEXT,scene_revision INTEGER,source_id TEXT,job_id TEXT,attached_at TEXT,PRIMARY KEY(actor,project_id,source_id,job_id))')
            db.execute('CREATE TABLE selections (actor TEXT,project_id TEXT,source_id TEXT,job_id TEXT,result_pk INTEGER,selected_at TEXT,PRIMARY KEY(actor,project_id))')
            db.execute('PRAGMA user_version=1')

    @contextmanager
    def _transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            self._ensure_schema(db)
            yield db

    @staticmethod
    def _page(limit, offset):
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise ValueError('Invalid design pagination')

    @staticmethod
    def _data(row, kind):
        data = json.loads(row['row_json'])
        for key in JSON_FIELDS[kind]:
            if data.get(key) is not None:
                data[key] = json.loads(data[key])
        return data

    @staticmethod
    def _job(row):
        return {'source_id':row['source_id'], 'job_id':row['job_id'],
                'created_at':row['created_at'], 'source_status':row['source_status'],
                'execution_state':'archived', 'result_count':row['result_count']}

    @staticmethod
    def _result(row):
        return {'source_id':row['source_id'], 'job_id':row['job_id'], 'result_pk':row['result_pk'],
                'generation':row['generation'], 'design_id':row['design_id'],
                'has_mass':bool(row['has_mass']), 'execution_state':'archived',
                **json.loads(row['summary_json'])}

    def list_jobs(self, source_id=None, limit=50, offset=0):
        self._page(limit,offset)
        where = ' WHERE source_id=?' if source_id is not None else ''
        params = [source_id] if source_id is not None else []
        with self._transaction() as db:
            rows = db.execute('SELECT source_id,job_id,created_at,source_status, '
                '(SELECT COUNT(*) FROM results r WHERE r.source_id=jobs.source_id AND r.job_id=jobs.job_id) AS result_count FROM jobs' + where +
                ' ORDER BY created_at DESC,source_id,job_id LIMIT ? OFFSET ?',params+[limit,offset]).fetchall()
        return [self._job(row) for row in rows]

    def get_job(self, source_id, job_id):
        with self._transaction() as db:
            row = db.execute('SELECT *, (SELECT COUNT(*) FROM results r WHERE r.source_id=jobs.source_id '
                'AND r.job_id=jobs.job_id) AS result_count FROM jobs WHERE source_id=? AND job_id=?',(source_id,job_id)).fetchone()
        return {**self._job(row),'row_sha256':row['row_sha256'],'data':self._data(row,'jobs')} if row else None

    def list_results(self, source_id, job_id, limit=50, offset=0):
        self._page(limit,offset)
        with self._transaction() as db:
            rows = db.execute('SELECT source_id,job_id,result_pk,generation,design_id,has_mass,summary_json FROM results '
                'WHERE source_id=? AND job_id=? ORDER BY generation,design_id,result_pk LIMIT ? OFFSET ?',
                (source_id,job_id,limit,offset)).fetchall()
        return [self._result(row) for row in rows]

    def get_result(self, source_id, job_id, result_pk):
        with self._transaction() as db:
            row = db.execute('SELECT * FROM results WHERE source_id=? AND job_id=? AND result_pk=?',
                             (source_id,job_id,result_pk)).fetchone()
        return {**self._result(row),'row_sha256':row['row_sha256'],'data':self._data(row,'results')} if row else None

    def attach_project(self, actor, project_id, scene_id, scene_revision, source_id, job_id):
        if (not all(isinstance(value,str) and value for value in (actor,project_id,scene_id,source_id,job_id))
                or type(scene_revision) is not int or scene_revision < 0):
            raise ValueError('Invalid project attachment')
        with self._transaction() as db:
            if not db.execute('SELECT 1 FROM jobs WHERE source_id=? AND job_id=?',(source_id,job_id)).fetchone():
                raise ValueError('Archived job not found')
            bindings = db.execute('SELECT scene_id,scene_revision FROM attachments WHERE actor=? AND project_id=?',
                                  (actor,project_id)).fetchall()
            if any(row['scene_id'] != scene_id or row['scene_revision'] != scene_revision for row in bindings):
                raise ValueError('Project scene binding conflicts')
            db.execute('INSERT OR IGNORE INTO attachments VALUES (?,?,?,?,?,?,?)',
                       (actor,project_id,scene_id,scene_revision,source_id,job_id,datetime.now(timezone.utc).isoformat()))
        return {'source_id':source_id,'job_id':job_id,'project_id':project_id,
                'scene_id':scene_id,'scene_revision':scene_revision,'execution_state':'archived'}

    def project_jobs(self, actor, project_id):
        with self._transaction() as db:
            rows = db.execute('SELECT j.source_id,j.job_id,j.created_at,j.source_status,a.scene_id,a.scene_revision, '
                '(SELECT COUNT(*) FROM results r WHERE r.source_id=j.source_id AND r.job_id=j.job_id) AS result_count '
                'FROM attachments a JOIN jobs j ON j.source_id=a.source_id AND j.job_id=a.job_id '
                'WHERE a.actor=? AND a.project_id=? ORDER BY j.created_at DESC,j.source_id,j.job_id',
                (actor,project_id)).fetchall()
        return [{**self._job(row),'scene_id':row['scene_id'],'scene_revision':row['scene_revision']} for row in rows]

    def select_result(self, actor, project_id, source_id, job_id, result_pk):
        with self._transaction() as db:
            attachment = db.execute('SELECT 1 FROM attachments WHERE actor=? AND project_id=? AND source_id=? AND job_id=?',
                                    (actor,project_id,source_id,job_id)).fetchone()
            result = db.execute('SELECT 1 FROM results WHERE source_id=? AND job_id=? AND result_pk=?',
                                (source_id,job_id,result_pk)).fetchone()
            if not attachment or not result:
                raise ValueError('Result does not belong to attached project job')
            db.execute('INSERT INTO selections VALUES (?,?,?,?,?,?) ON CONFLICT(actor,project_id) DO UPDATE SET '
                'source_id=excluded.source_id,job_id=excluded.job_id,result_pk=excluded.result_pk,selected_at=excluded.selected_at',
                (actor,project_id,source_id,job_id,result_pk,datetime.now(timezone.utc).isoformat()))
        return self.selected_result(actor,project_id)

    def selected_result(self, actor, project_id):
        with self._transaction() as db:
            row = db.execute('SELECT r.*,s.selected_at,a.scene_id,a.scene_revision FROM selections s '
                'JOIN results r ON r.source_id=s.source_id AND r.job_id=s.job_id AND r.result_pk=s.result_pk '
                'JOIN attachments a ON a.actor=s.actor AND a.project_id=s.project_id AND a.source_id=s.source_id AND a.job_id=s.job_id '
                'WHERE s.actor=? AND s.project_id=?',(actor,project_id)).fetchone()
        return ({**self._result(row),'data':self._data(row,'results'),'row_sha256':row['row_sha256'],
                 'selected_at':row['selected_at'],'scene_id':row['scene_id'],'scene_revision':row['scene_revision']}
                if row else None)
