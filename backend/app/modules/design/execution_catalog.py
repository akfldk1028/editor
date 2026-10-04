"""Pinned execution evidence index; reads never rebuild or render source artifacts."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import warnings

from PIL import Image

from .artifacts import ArtifactArchive, ArtifactArchiveError, _digest, _safe_path, _linked


class CatalogUnavailable(RuntimeError):
    pass


_PNG_ROLES={'preview','portfolio_board','proposal',
            *(f'elevation_{side}' for side in ('front','right','back','left','top','axon')),
            *(f'proposal_{side}' for side in ('front','right','back','left','critic_montage'))}
_JSON_ROLES={'execution_manifest','program','passport','run_state','geometry_archive',
             'portfolio_summary','proposal_evidence','critic_evidence'}


def _scalar(value):
    return value if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.: -]{1,200}',value) else None


def _decode(raw,artifact=False):
    try:
        value=json.loads(raw)
        if not isinstance(value,dict):raise ValueError()
        if artifact:
            _id(value['artifact_id']);_id(value['sha256'])
            role=value['role']
            if role not in _PNG_ROLES|_JSON_ROLES:raise ValueError()
            inline=role in _PNG_ROLES
            if (value['inline'] is not inline or value['media_type']!=('image/png' if inline else 'application/json')
                    or type(value['size']) is not int or value['size']<0):raise ValueError()
            keys=('artifact_id','role','media_type','size','sha256','inline')
        else:
            _id(value['catalog_id']);_id(value['snapshot_sha256'])
            if (value['source_namespace'] not in ('arr-maas-cache','arr-design-executions')
                    or value['execution_state']!='archived'
                    or any(type(value[key]) is not bool for key in ('has_preview','has_passport'))
                    or value['metadata_status'] not in ('available','missing','metadata_unavailable')):raise ValueError()
            if any(value.get(key) is not None and _scalar(value[key]) is None for key in ('execution_id','source_status')):raise ValueError()
            if 'geometry_ready' in value and type(value['geometry_ready']) is not bool:raise ValueError()
            if 'replay_reference' in value:
                ref=value['replay_reference']
                if not isinstance(ref,dict) or set(ref)!={'source_run_id','status'} or not _scalar(ref['source_run_id']) or ref['status']!='unresolved':raise ValueError()
            keys=('catalog_id','source_namespace','snapshot_sha256','execution_state','has_preview','has_passport',
                  'metadata_status','execution_id','source_status','geometry_ready','replay_reference')
        return {key:value[key] for key in keys if key in value}
    except (ValueError,TypeError,KeyError,LookupError):
        raise CatalogUnavailable('Registered catalog data is invalid') from None


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _id(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value):
        raise LookupError('Unknown execution artifact')
    return value


def _group(source,relative):
    parts=PurePosixPath(relative).parts
    if source=='arr-maas-cache':
        if len(parts)>=3 and parts[0] in ('single-executions','executed-masses'):
            return '/'.join(parts[:2]),'/'.join(parts[2:])
        if len(parts)>=2 and parts[0]=='geometry-language':
            return parts[0],'/'.join(parts[1:])
        return None
    if source=='arr-design-executions' and len(parts)>=2:
        return parts[0],'/'.join(parts[1:])
    return None


def _role(name):
    fixed={'mass.png':'preview','execution.json':'execution_manifest','program.json':'program',
           'mass.png.passport.json':'passport','maas-run-state.json':'run_state',
           'maas-book-exact-geometry-artifacts.json':'geometry_archive',
           'maas-book-programs-summary.json':'portfolio_summary',
           'maas-book-neighborhood-20.png':'portfolio_board',
           'elevation/proposals/alt-01/proposal.png':'proposal',
           'elevation/proposals/multi-view-alt-01/proposal.json':'proposal_evidence',
           'elevation/proposals/multi-view-alt-01/critic.json':'critic_evidence'}
    if name in fixed:return fixed[name]
    match=re.fullmatch(r'elevation/views/(front|right|back|left|top|axon)\.png',name)
    if match:return 'elevation_'+match[1]
    match=re.fullmatch(r'elevation/proposals/multi-view-alt-01/(front|right|back|left|critic-montage)\.png',name)
    if match:return 'proposal_'+match[1].replace('-','_')
    if re.fullmatch(r'mass-\d+-[a-f0-9]+\.png',name):return 'preview'
    if re.fullmatch(r'mass-\d+-[a-f0-9]+\.png\.passport\.json',name):return 'passport'
    return None


class ExecutionCatalog:
    def __init__(self,directory):
        root=Path(directory)
        if not root.is_absolute() or any(_linked(p) for p in (root,*root.parents)):
            raise CatalogUnavailable('Invalid execution catalog directory')
        self.directory=root
        try:
            self.path=_safe_path(root,'execution-catalog.sqlite')
            self.archive=ArtifactArchive(root/'artifacts')
        except (ArtifactArchiveError,OSError):
            raise CatalogUnavailable('Invalid execution catalog directory') from None

    @contextmanager
    def _db(self,write=False):
        try:
            _safe_path(self.directory,'execution-catalog.sqlite')
            if write:self.directory.mkdir(parents=True,exist_ok=True)
            connection=sqlite3.connect(self.path if write else self.path.as_uri()+'?mode=ro',uri=not write,timeout=10)
            with closing(connection) as db,db:
                db.row_factory=sqlite3.Row
                if write:db.execute('BEGIN IMMEDIATE')
                else:db.execute('PRAGMA query_only=ON')
                version=db.execute('PRAGMA user_version').fetchone()[0]
                if version==0 and write:
                    db.execute('CREATE TABLE snapshots (source_namespace TEXT,snapshot_sha256 TEXT,entries_json TEXT,PRIMARY KEY(source_namespace,snapshot_sha256))')
                    db.execute('CREATE TABLE executions (catalog_id TEXT PRIMARY KEY,summary_json TEXT)')
                    db.execute('CREATE TABLE artifacts (catalog_id TEXT,artifact_id TEXT,metadata_json TEXT,PRIMARY KEY(catalog_id,artifact_id))')
                    db.execute('CREATE TABLE attachments (actor TEXT,project_id TEXT,scene_id TEXT,scene_revision INTEGER,catalog_id TEXT,attached_at TEXT,PRIMARY KEY(actor,project_id,catalog_id))')
                    db.execute('PRAGMA user_version=1')
                elif version!=1:
                    raise CatalogUnavailable('Unsupported execution catalog schema')
                yield db
        except (sqlite3.Error,OSError,ArtifactArchiveError):
            raise CatalogUnavailable('Execution catalog unavailable') from None

    def _blob(self,entry):
        try:
            path=self.archive._blob(entry)
            if not path.is_file() or _digest(path)!={'sha256':entry['sha256'],'size':entry['size']}:
                raise CatalogUnavailable('Registered artifact missing or corrupt')
            return path
        except (OSError,ArtifactArchiveError):
            raise CatalogUnavailable('Registered artifact missing or corrupt') from None

    def _metadata(self,entries,group):
        identity=_scalar(PurePosixPath(group).name)
        missing={'metadata_status':'missing','execution_id':identity,'source_status':None}
        unavailable={**missing,'metadata_status':'metadata_unavailable'}
        entry=entries.get('execution.json') or entries.get('maas-run-state.json')
        if entry is None:return missing
        if entry['size']>1024*1024:return unavailable
        try:
            value=json.loads(self._blob(entry).read_text(encoding='utf-8'))
            if not isinstance(value,dict):raise ValueError()
            def scalar(key):
                item=value.get(key)
                return _scalar(item)
            declared=value.get('execution_id') or value.get('run_id')
            result={'metadata_status':'metadata_unavailable' if declared and declared!=identity else 'available','execution_id':identity,
                    'source_status':scalar('status')}
            for key in ('geometry_ready',):
                if type(value.get(key)) is bool:result[key]=value[key]
            reference=scalar('source_run_id')
            if reference:result['replay_reference']={'source_run_id':reference,'status':'unresolved'}
            return result
        except (ValueError,UnicodeError,OSError):
            return unavailable

    def register(self,source_id):
        if source_id not in ('arr-maas-cache','arr-design-executions'):
            raise ValueError('Unsupported execution source')
        try:entries=self.archive.entries(source_id)
        except (ArtifactArchiveError,OSError):raise CatalogUnavailable('Archive manifest unavailable') from None
        if not entries:raise CatalogUnavailable('Archive manifest unavailable')
        snapshot=_hash(entries)
        groups={}
        for relative,entry in entries.items():
            self._blob(entry)
            group=_group(source_id,relative)
            if group:groups.setdefault(group[0],{})[group[1]]=entry
        summaries=[];artifacts=[]
        for group,files in sorted(groups.items()):
            identifier=_hash([source_id,snapshot,group])
            roles=[]
            for name,entry in sorted(files.items()):
                role=_role(name)
                if not role:continue
                roles.append(role)
                metadata={'artifact_id':_hash([identifier,name,entry]),'role':role,
                          'media_type':'image/png' if name.endswith('.png') else 'application/json',
                          'size':entry['size'],'sha256':entry['sha256'],'inline':name.endswith('.png')}
                artifacts.append((identifier,metadata))
            summaries.append({'catalog_id':identifier,'source_namespace':source_id,'snapshot_sha256':snapshot,
                'execution_state':'archived','has_preview':any(r in ('preview','portfolio_board') for r in roles),
                'has_passport':'passport' in roles,**self._metadata(files,group)})
        with self._db(True) as db:
            db.execute('INSERT OR IGNORE INTO snapshots VALUES (?,?,?)',(source_id,snapshot,json.dumps(entries,sort_keys=True)))
            for summary in summaries:
                db.execute('INSERT OR IGNORE INTO executions VALUES (?,?)',(summary['catalog_id'],json.dumps(summary)))
            for identifier,metadata in artifacts:
                db.execute('INSERT OR IGNORE INTO artifacts VALUES (?,?,?)',(identifier,metadata['artifact_id'],json.dumps(metadata)))
        return {'source_namespace':source_id,'snapshot_sha256':snapshot,'executions':len(summaries),'artifacts':len(artifacts)}

    @staticmethod
    def _page(limit,offset):
        if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or offset<0:
            raise ValueError('Invalid execution pagination')

    def list_executions(self,limit=20,offset=0):
        self._page(limit,offset)
        if not self.path.exists():return []
        with self._db() as db:
            rows=db.execute('SELECT summary_json FROM executions ORDER BY catalog_id LIMIT ? OFFSET ?',(limit,offset)).fetchall()
        return [_decode(row[0]) for row in rows]

    def get_execution(self,catalog_id):
        _id(catalog_id)
        if not self.path.exists():return None
        with self._db() as db:
            row=db.execute('SELECT summary_json FROM executions WHERE catalog_id=?',(catalog_id,)).fetchone()
        return _decode(row[0]) if row else None

    def artifacts(self,catalog_id,limit=20,offset=0):
        self._page(limit,offset)
        if self.get_execution(catalog_id) is None:raise LookupError('Unknown execution')
        with self._db() as db:
            rows=db.execute('SELECT metadata_json FROM artifacts WHERE catalog_id=? ORDER BY artifact_id LIMIT ? OFFSET ?',
                            (catalog_id,limit,offset)).fetchall()
        return [_decode(row[0],artifact=True) for row in rows]

    def attach(self,actor,project_id,scene_id,scene_revision,catalog_id):
        if (not all(isinstance(v,str) and v for v in (actor,project_id,scene_id))
                or type(scene_revision) is not int or scene_revision<0):raise ValueError('Invalid attachment')
        summary=self.get_execution(catalog_id)
        if summary is None:raise LookupError('Unknown execution')
        with self._db(True) as db:
            bindings=db.execute('SELECT scene_id,scene_revision FROM attachments WHERE actor=? AND project_id=?',
                                (actor,project_id)).fetchall()
            if any(row['scene_id']!=scene_id or row['scene_revision']!=scene_revision for row in bindings):
                raise ValueError('Project scene binding conflict')
            db.execute('INSERT OR IGNORE INTO attachments VALUES (?,?,?,?,?,?)',
                (actor,project_id,scene_id,scene_revision,catalog_id,datetime.now(timezone.utc).isoformat()))
        return {**summary,'scene_id':scene_id,'scene_revision':scene_revision}

    def project_executions(self,actor,project_id,limit=20,offset=0):
        self._page(limit,offset)
        if not self.path.exists():return []
        with self._db() as db:
            rows=db.execute('SELECT e.summary_json,a.scene_id,a.scene_revision FROM attachments a JOIN executions e '
                'ON e.catalog_id=a.catalog_id WHERE a.actor=? AND a.project_id=? ORDER BY a.attached_at,e.catalog_id LIMIT ? OFFSET ?',
                (actor,project_id,limit,offset)).fetchall()
        return [{**_decode(row[0]),'scene_id':row[1],'scene_revision':row[2]} for row in rows]

    def is_attached(self,actor,project_id,catalog_id):
        _id(catalog_id)
        if not self.path.exists():return False
        with self._db() as db:
            return db.execute('SELECT 1 FROM attachments WHERE actor=? AND project_id=? AND catalog_id=?',
                              (actor,project_id,catalog_id)).fetchone() is not None

    def resolve_artifact(self,catalog_id,artifact_id):
        _id(catalog_id);_id(artifact_id)
        if not self.path.exists():raise LookupError('Unknown artifact')
        with self._db() as db:
            row=db.execute('SELECT metadata_json FROM artifacts WHERE catalog_id=? AND artifact_id=?',
                           (catalog_id,artifact_id)).fetchone()
        if row is None:raise LookupError('Unknown artifact')
        metadata=_decode(row[0],artifact=True)
        if metadata['artifact_id']!=artifact_id:raise CatalogUnavailable('Registered artifact identity is invalid')
        path=self._blob(metadata)
        if metadata['inline']:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error',Image.DecompressionBombWarning)
                    with Image.open(path) as image:
                        if image.format!='PNG' or image.width*image.height>40_000_000:raise ValueError()
                        image.verify()
                    with Image.open(path) as image:image.load()
            except (OSError,ValueError,SyntaxError,Image.DecompressionBombError,Image.DecompressionBombWarning):
                raise CatalogUnavailable('Registered PNG is invalid') from None
        return path,metadata
