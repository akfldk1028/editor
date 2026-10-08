"""The service registry (infra/config/services.json) as the backend reads it.

The file is the one owner of ids, ports and health URLs (infra/host/registry.mjs reads the same
file for the host). Nothing here validates the schema: `bun run host:check` does.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

EDITOR_ROOT = Path(__file__).resolve().parents[5]
REGISTRY_PATH = EDITOR_ROOT / 'infra/config/services.json'
HOST_RUNTIME_DIR = EDITOR_ROOT / 'runtime/host'
LOOPBACK = '127.0.0.1'


class Registry:
    """Registry entries, re-read whenever the file's mtime changes."""

    def __init__(self, path: Path = REGISTRY_PATH):
        self.path = Path(path)
        self._mtime: float | None = None
        self._entries: list[dict] = []

    def entries(self) -> list[dict]:
        mtime = self.path.stat().st_mtime
        if self._mtime != mtime:
            document = json.loads(self.path.read_text(encoding='utf-8'))
            self._entries = list(document['services'])
            self._mtime = mtime
        return [dict(entry) for entry in self._entries]


def base_url(entry: dict, env=os.environ) -> str | None:
    """The env override named by host_env wins; otherwise loopback on the registered port."""
    override = env.get(entry['host_env']) if entry.get('host_env') else None
    if override:
        return override.rstrip('/')
    if entry.get('port') is None:
        return None
    return f'http://{LOOPBACK}:{entry["port"]}'


def health_url(entry: dict, env=os.environ) -> str | None:
    template = entry.get('health_url')
    base = base_url(entry, env)
    if template is None or base is None:
        return None
    return template.replace('{base}', base)


def host_record(service_id: str, runtime_dir: Path = HOST_RUNTIME_DIR) -> dict | None:
    """The host supervisor's pid record (runtime/host/<id>.json) when it wrote one."""
    path = Path(runtime_dir) / f'{service_id}.json'
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return None
    if not isinstance(record, dict) or not isinstance(record.get('pid'), int):
        return None
    return {'host': 'infra/host', 'pid': record['pid'],
            'started_at': record.get('startedAt') if isinstance(record.get('startedAt'), str) else None,
            'adopted': bool(record.get('adopted'))}
