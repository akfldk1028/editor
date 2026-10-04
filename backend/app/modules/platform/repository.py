import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from backend.app.schemas.platform import ProjectBinding, ProjectCreate


class ProjectRepository:
    def __init__(self, directory: Path | str):
        root = Path(directory)
        if not root.is_absolute():
            raise ValueError('platform data directory must be absolute')
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / 'platform.sqlite'
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1, 2):
                raise ValueError('unsupported platform database version')
            db.execute('''CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY, actor TEXT NOT NULL,
                owner_project_id TEXT NOT NULL, branch_id TEXT NOT NULL,
                scene_id TEXT NOT NULL, scene_revision INTEGER NOT NULL,
                UNIQUE(actor, owner_project_id, branch_id, scene_id))''')
            if version < 2:
                db.execute('ALTER TABLE projects ADD COLUMN scene_project_id TEXT')
                if version == 1:
                    db.execute('UPDATE projects SET scene_project_id=owner_project_id')
            db.execute('PRAGMA user_version=2')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def binding(row):
        if row is None:
            return None
        return ProjectBinding(**{key: row[key] for key in row.keys() if key != 'actor'})

    def list(self, actor: str) -> list[ProjectBinding]:
        db = self.connect()
        try:
            return [self.binding(row) for row in db.execute(
                'SELECT * FROM projects WHERE actor=? ORDER BY project_id', (actor,))]
        finally:
            db.close()

    def get(self, actor: str, project_id: str) -> ProjectBinding | None:
        db = self.connect()
        try:
            return self.binding(db.execute('SELECT * FROM projects WHERE actor=? AND project_id=?',
                (actor, project_id)).fetchone())
        finally:
            db.close()

    def create(self, actor: str, request: ProjectCreate) -> ProjectBinding:
        db = self.connect()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT * FROM projects WHERE actor=? AND owner_project_id=? AND branch_id=? AND scene_id=?',
                    (actor, request.owner_project_id, request.branch_id, request.scene_id)).fetchone()
                if row:
                    if row['scene_revision'] != request.scene_revision or row['scene_project_id'] != request.scene_project_id:
                        raise ValueError('binding already exists at another scene revision')
                    return self.binding(row)
                result = ProjectBinding(project_id=uuid4().hex, **request.model_dump())
                db.execute('INSERT INTO projects VALUES (?,?,?,?,?,?,?)', (result.project_id, actor,
                    result.owner_project_id, result.branch_id, result.scene_id, result.scene_revision, result.scene_project_id))
                return result
        finally:
            db.close()
