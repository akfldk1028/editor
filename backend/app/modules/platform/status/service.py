"""Status rows: registry entry + probe + host pid record, with the Orchestrator's agent view merged
in when the Orchestrator itself answers."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from backend.app.adapters.orchestrator import OrchestratorClient, OwnerContractError, OwnerUnavailable
from backend.app.modules.platform.status.probes import Prober
from backend.app.modules.platform.status.registry import HOST_RUNTIME_DIR, Registry, health_url, host_record

ROW_KEYS = ('id', 'kind', 'port', 'lifecycle', 'management', 'notes')


class StatusService:
    def __init__(self, registry: Registry, prober: Prober, owner: OrchestratorClient, *,
                 env=os.environ, runtime_dir: Path = HOST_RUNTIME_DIR):
        self.registry = registry
        self.prober = prober
        self.owner = owner
        self.env = env
        self.runtime_dir = runtime_dir

    async def status(self, *, refresh: bool = False) -> dict:
        entries = self.registry.entries()
        probes = await self.prober.probe_all({entry['id']: health_url(entry, self.env) for entry in entries},
                                             force=refresh)
        rows = [self.row(entry, probes[entry['id']]) for entry in entries]
        orchestrator = await self.orchestrator_view(entries, rows)
        return {'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'orchestrator': orchestrator, 'services': rows}

    def row(self, entry: dict, probe) -> dict:
        record = host_record(entry['id'], self.runtime_dir)
        launcher = entry.get('launcher') or {}
        return {
            **{key: entry.get(key) for key in ROW_KEYS},
            'label': launcher.get('name') or entry['id'],
            'state': probe.state,
            'http_status': probe.http_status,
            'version': probe.version,
            'started_at': (record or {}).get('started_at') or probe.started_at,
            'latency_ms': probe.latency_ms,
            'checked_at': probe.checked_at,
            'error': probe.error,
            'managed_by': record,
            'orchestrator': None,
        }

    async def orchestrator_view(self, entries: list[dict], rows: list[dict]) -> dict:
        """The Orchestrator's catalog merged into agent rows; `state` says whether it answered."""
        hub = next((row for row in rows if row['kind'] == 'orchestrator'), None)
        if hub is None or hub['state'] != 'up':
            return {'state': 'down', 'error': None if hub is None else hub['error'] or 'health probe failed'}
        try:
            agents = await self.owner.list_agents()
        except OwnerUnavailable:
            return {'state': 'down', 'error': 'Orchestrator catalog unavailable'}
        except OwnerContractError:
            return {'state': 'invalid', 'error': 'Orchestrator catalog contract invalid'}
        by_name = {}
        for agent in agents:
            view = {'connection_status': agent.connection_status, 'checked_at': agent.checked_at,
                    'evidence_ref': agent.evidence_ref}
            by_name.setdefault(agent.agent_id, view)
            by_name.setdefault(agent.label, view)
        for entry, row in zip(entries, rows):
            if row['kind'] != 'agent':
                continue
            for name in self.agent_names(entry):
                if name in by_name:
                    row['orchestrator'] = by_name[name]
                    break
        return {'state': 'up', 'error': None, 'agents': len(agents)}

    @staticmethod
    def agent_names(entry: dict) -> list[str]:
        """Names the Orchestrator may call this agent: catalog name, catalog file stem, registry id."""
        launcher = entry.get('launcher') or {}
        catalog = str(launcher.get('catalog') or '')
        return [name for name in (launcher.get('name'), catalog.removesuffix('.json') or None, entry['id']) if name]
