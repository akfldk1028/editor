"""The ledger's SQLite file: one table of calls, WAL, one writer (this backend), `PRAGMA user_version` migrations."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .schema import HopRecord

SCHEMA_VERSION = 1
MAX_LIMIT = 500
JSON_COLUMNS = ('input_messages', 'output_messages', 'attrs')
COLUMNS = ('trace_id', 'span_id', 'parent_span_id', 'ts_start', 'ts_end', 'operation', 'from_agent', 'to_agent', 'tool', 'status',
           'error_type', 'state', 'elapsed_ms', 'conversation_id', 'run_id', 'task_id', 'project', 'branch', 'hop', 'source',
           'input_messages', 'output_messages', 'attrs')


class LedgerStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError('ledger path must be absolute')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db:
            db.execute('PRAGMA journal_mode=WAL')
            with db:
                db.execute('BEGIN IMMEDIATE')
                version = db.execute('PRAGMA user_version').fetchone()[0]
                if version not in (0, SCHEMA_VERSION):
                    raise ValueError('unsupported ledger database version')
                db.execute('''CREATE TABLE IF NOT EXISTS agent_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL, span_id TEXT NOT NULL, parent_span_id TEXT,
                    ts_start TEXT NOT NULL, ts_end TEXT,
                    operation TEXT NOT NULL, from_agent TEXT NOT NULL, to_agent TEXT NOT NULL, tool TEXT,
                    status TEXT NOT NULL, error_type TEXT, state TEXT, elapsed_ms INTEGER,
                    conversation_id TEXT, run_id TEXT, task_id TEXT, project TEXT, branch TEXT, hop INTEGER,
                    source TEXT NOT NULL, input_messages TEXT, output_messages TEXT, attrs TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    UNIQUE(trace_id, span_id))''')
                db.execute('CREATE INDEX IF NOT EXISTS agent_calls_trace ON agent_calls(trace_id)')
                db.execute('CREATE INDEX IF NOT EXISTS agent_calls_conversation ON agent_calls(conversation_id, ts_start)')
                db.execute('CREATE INDEX IF NOT EXISTS agent_calls_run ON agent_calls(run_id, ts_start)')
                db.execute('CREATE INDEX IF NOT EXISTS agent_calls_time ON agent_calls(ts_start)')
                db.execute('CREATE INDEX IF NOT EXISTS agent_calls_scope ON agent_calls(project, branch)')
                db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=5000')
        return db

    def conversation_for(self, project: str, branch: str) -> str | None:
        with closing(self.connect()) as db:
            rows = db.execute('SELECT DISTINCT conversation_id FROM agent_calls '
                              'WHERE project=? AND branch=? AND conversation_id IS NOT NULL LIMIT 2',
                              (project, branch)).fetchall()
        return rows[0]['conversation_id'] if len(rows) == 1 else None

    @staticmethod
    def _values(record: HopRecord) -> list:
        data = record.model_dump()
        return [json.dumps(data[column], ensure_ascii=False) if column in JSON_COLUMNS and data[column] is not None else data[column] for column in COLUMNS]

    def append(self, record: HopRecord) -> int:
        """Inserts the call; the same span recorded again (its end after its start) updates the row. Returns the row id."""
        placeholders = ', '.join('?' for _ in COLUMNS)
        # The end of a call updates its start's row and stamps when: readers that already have the row see it changed.
        updates = ', '.join([*(f'{column}=excluded.{column}' for column in COLUMNS if column not in ('trace_id', 'span_id')),
                             "recorded_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"])
        with closing(self.connect()) as db, db:
            # A caller's start row and the agent's end row are posted from different processes, so the end can arrive
            # first; a late start must not reopen a call that has already ended.
            row = db.execute(f'INSERT INTO agent_calls ({", ".join(COLUMNS)}) VALUES ({placeholders}) '
                             f'ON CONFLICT(trace_id, span_id) DO UPDATE SET {updates} '
                             'WHERE excluded.ts_end IS NOT NULL OR agent_calls.ts_end IS NULL RETURNING id', self._values(record)).fetchone()
            if row is None:
                row = db.execute('SELECT id FROM agent_calls WHERE trace_id=? AND span_id=?', (record.trace_id, record.span_id)).fetchone()
            return int(row['id'])

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        out = dict(row)
        for column in JSON_COLUMNS:
            out[column] = json.loads(out[column]) if out.get(column) else ({} if column == 'attrs' else None)
        return out

    def get(self, row_id: int) -> dict | None:
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM agent_calls WHERE id=?', (row_id,)).fetchone()
            return self._row(row) if row else None

    def query(self, *, conversation_id: str | None = None, run_id: str | None = None, run_ids: list[str] | None = None, trace_id: str | None = None,
              project: str | None = None, branch: str | None = None, since_id: int = 0, limit: int = 200) -> list[dict]:
        """Rows after `since_id` (by id, i.e. in the order they were recorded) that match every given filter; a
        conversation filter also takes the runs it started (`run_ids`)."""
        clauses, params = ['id > ?'], [int(since_id)]
        scope = []
        if conversation_id:
            scope.append('conversation_id = ?')
            params.append(conversation_id)
        if run_ids:
            scope.append(f'run_id IN ({", ".join("?" for _ in run_ids)})')
            params.extend(run_ids)
        if scope:
            clauses.append(f'({" OR ".join(scope)})')
        if run_id:
            clauses.append('run_id = ?')
            params.append(run_id)
        if trace_id:
            clauses.append('trace_id = ?')
            params.append(trace_id)
        if project:
            clauses.append('project = ?')
            params.append(project)
        if branch:
            clauses.append('branch = ?')
            params.append(branch)
        params.append(max(1, min(int(limit), MAX_LIMIT)))
        with closing(self.connect()) as db:
            rows = db.execute(f'SELECT * FROM agent_calls WHERE {" AND ".join(clauses)} ORDER BY id LIMIT ?', params).fetchall()
            return [self._row(row) for row in rows]

    def runs_of(self, conversation_id: str) -> list[str]:
        """The runs a conversation started (`start_run` records), oldest first."""
        with closing(self.connect()) as db:
            rows = db.execute("SELECT run_id FROM agent_calls WHERE operation='start_run' AND conversation_id=? AND run_id IS NOT NULL ORDER BY id",
                              (conversation_id,)).fetchall()
            return list(dict.fromkeys(row['run_id'] for row in rows))

    def latest_id(self) -> int:
        with closing(self.connect()) as db:
            row = db.execute('SELECT MAX(id) AS id FROM agent_calls').fetchone()
            return int(row['id'] or 0)
