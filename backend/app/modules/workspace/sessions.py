import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class SessionRepository:
    def __init__(self, directory):
        self.path = Path(directory) / 'sessions.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, team_id INTEGER NOT NULL, team_snapshot TEXT NOT NULL, created_at TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL REFERENCES sessions(id), payload TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS runs_session ON runs(session_id)')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('PRAGMA foreign_keys=ON')
        db.row_factory = sqlite3.Row
        return db

    def record(self, row):
        return {'id': row['id'], 'name': row['name'], 'team_id': row['team_id'],
                'team_snapshot': json.loads(row['team_snapshot']), 'created_at': row['created_at'],
                'execution_status': 'recorded' if row['run_count'] else 'not_started'}

    def list(self):
        with self.connect() as db:
            rows = db.execute('SELECT s.*, (SELECT COUNT(*) FROM runs r WHERE r.session_id=s.id) AS run_count FROM sessions s WHERE archived=0 ORDER BY id DESC').fetchall()
        return [self.record(row) for row in rows]

    def create(self, name, team_id, snapshot):
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            identifier = db.execute('INSERT INTO sessions(name,team_id,team_snapshot,created_at) VALUES (?,?,?,?)',
                                    (name, team_id, json.dumps(snapshot, ensure_ascii=False, allow_nan=False), now)).lastrowid
        return {'id': identifier, 'name': name, 'team_id': team_id, 'team_snapshot': snapshot,
                'created_at': now, 'execution_status': 'not_started'}

    def runs(self, identifier):
        with self.connect() as db:
            if not db.execute('SELECT id FROM sessions WHERE id=? AND archived=0', (identifier,)).fetchone():
                raise LookupError('Session not found')
            rows = db.execute('SELECT payload FROM runs WHERE session_id=? ORDER BY id', (identifier,)).fetchall()
        return {'runs': [json.loads(row['payload']) for row in rows]}

    def archive(self, identifier):
        with self.connect() as db:
            if db.execute('UPDATE sessions SET archived=1 WHERE id=? AND archived=0', (identifier,)).rowcount != 1:
                raise LookupError('Session not found')
        return {'archived': True, 'id': identifier}
