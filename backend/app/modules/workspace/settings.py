import json
import sqlite3
from pathlib import Path


class SettingsConflict(Exception):
    pass


class SettingsRepository:
    def __init__(self, directory):
        self.path = Path(directory) / 'workspace.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL, config TEXT NOT NULL)')
            connection.execute('INSERT OR IGNORE INTO settings VALUES (1, 0, ?)', (json.dumps({
                'ui': {'show_llm_call_events': False, 'expanded_messages_by_default': False,
                       'show_agent_flow_by_default': False, 'human_input_timeout_minutes': 3},
                'environment': [],
            }),))

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def get(self):
        with self.connect() as connection:
            version, config = connection.execute('SELECT version, config FROM settings WHERE id=1').fetchone()
        return {'id': 1, 'version': version, 'config': json.loads(config)}

    def update(self, version, config):
        encoded = json.dumps(config, ensure_ascii=False, allow_nan=False)
        with self.connect() as connection:
            changed = connection.execute('UPDATE settings SET version=version+1, config=? WHERE id=1 AND version=?', (encoded, version))
            if changed.rowcount != 1:
                raise SettingsConflict('Settings changed. Reload before saving again.')
        return {'id': 1, 'version': version + 1, 'config': config}
