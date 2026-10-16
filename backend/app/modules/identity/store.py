"""The people who signed in: one row per provider account, and the owner id the rest of the editor keys data by.

SQLite with WAL and `PRAGMA user_version` migrations, the same shape as the ledger's store.
"""
from __future__ import annotations

import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class User:
    id: str
    provider: str
    subject: str
    email: str | None
    name: str | None

    @property
    def owner(self) -> str:
        """The owner id this person's projects, conversations and runs are stored under."""
        return f'u_{self.id}'


class UserStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute('PRAGMA journal_mode=WAL')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise ValueError('unsupported identity database version')
            db.execute('''CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, provider TEXT NOT NULL, subject TEXT NOT NULL, email TEXT, name TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                last_login_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                UNIQUE (provider, subject))''')
            db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=5000')
        return db

    def sign_in(self, provider: str, subject: str, email: str | None, name: str | None) -> User:
        """The account behind a provider identity, made on its first sign-in; its profile is refreshed each time."""
        with closing(self.connect()) as db, db:
            db.execute('INSERT INTO users (id, provider, subject, email, name) VALUES (?,?,?,?,?) '
                       'ON CONFLICT(provider, subject) DO UPDATE SET email=excluded.email, name=excluded.name, '
                       "last_login_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                       (secrets.token_hex(8), provider, subject, email, name))
            row = db.execute('SELECT * FROM users WHERE provider=? AND subject=?', (provider, subject)).fetchone()
        return _user(row)

    def get(self, user_id: str) -> User | None:
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        return _user(row) if row else None


def _user(row: sqlite3.Row) -> User:
    return User(id=row['id'], provider=row['provider'], subject=row['subject'], email=row['email'], name=row['name'])
