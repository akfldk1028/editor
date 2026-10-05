import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class CatalogConflict(Exception):
    pass


class CatalogRepository:
    def __init__(self, directory):
        self.path = Path(directory) / 'catalog.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS records (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def encode(self, payload):
        value = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        if len(value.encode('utf-8')) > 2_000_000:
            raise ValueError('Template exceeds 2 MB')
        return value

    def record(self, row):
        return {'id': row[0], 'version': row[1], **json.loads(row[2]), 'created_at': row[3],
                'updated_at': row[4], 'execution_status': 'not_executed'}

    def list(self, kind):
        with self.connect() as db:
            rows = db.execute('SELECT id,version,payload,created_at,updated_at FROM records WHERE kind=? ORDER BY id DESC', (kind,)).fetchall()
        return [self.record(row) for row in rows]

    def get(self, kind, identifier):
        with self.connect() as db:
            row = db.execute('SELECT id,version,payload,created_at,updated_at FROM records WHERE kind=? AND id=?', (kind, identifier)).fetchone()
        if row is None:
            raise LookupError('Template not found')
        return self.record(row)

    def create(self, kind, payload):
        encoded = self.encode(payload)
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            identifier = db.execute('INSERT INTO records(kind,version,payload,created_at,updated_at) VALUES (?,0,?,?,?)', (kind, encoded, now, now)).lastrowid
        return self.get(kind, identifier)

    def update(self, kind, identifier, version, payload):
        encoded = self.encode(payload)
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            changed = db.execute('UPDATE records SET version=version+1,payload=?,updated_at=? WHERE kind=? AND id=? AND version=?', (encoded, now, kind, identifier, version))
            if changed.rowcount != 1:
                raise CatalogConflict('Template changed or was removed. Reload before saving.')
        return self.get(kind, identifier)

    def delete(self, kind, identifier):
        with self.connect() as db:
            if db.execute('DELETE FROM records WHERE kind=? AND id=?', (kind, identifier)).rowcount != 1:
                raise LookupError('Template not found')
        return {'deleted': True, 'id': identifier}


def validate_component(component):
    errors = []
    for field in ('provider', 'component_type'):
        if not isinstance(component.get(field), str) or not component[field].strip():
            errors.append({'field': field, 'error': 'A nonempty string is required'})
    if component.get('component_type') not in ('team', 'agent', 'model', 'tool', 'termination', 'workbench'):
        errors.append({'field': 'component_type', 'error': 'Unknown component type'})
    if not isinstance(component.get('config'), dict):
        errors.append({'field': 'config', 'error': 'An object is required'})
    elif component.get('component_type') == 'team':
        participants = component['config'].get('participants')
        if not isinstance(participants, list) or not participants:
            errors.append({'field': 'config.participants', 'error': 'At least one participant is required to run a team'})
        else:
            for index, participant in enumerate(participants):
                if not isinstance(participant, dict):
                    errors.append({'field': f'config.participants.{index}', 'error': 'A component object is required'})
                else:
                    for error in validate_component(participant)['errors']:
                        errors.append({**error, 'field': f'config.participants.{index}.{error["field"]}'})
    return {'is_valid': not errors, 'errors': errors, 'scope': 'configuration_structure_only',
            'warnings': [{'field': 'execution', 'error': 'Provider loading, credentials and agent execution have not been verified.'}]}
