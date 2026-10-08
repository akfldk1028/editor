"""The host supervisor's door for the product: make sure the agents a goal needs are up — lazily, at the call.

Research (memory `agent-activation-research`): virtual-actor activation (Dapr, AutoGen's factory-on-first-message)
and KEDA's interceptor — the caller holds its request while the platform brings the service up. Here the platform is
`infra/host` (registry, depends_on, health, restart); this module only asks it, through its CLI
(`node infra/host/cli.mjs ensure <ids> --json`), and reads the JSON answer. Agent ids are the network's
(`site_context`, `design_intent`); registry ids use dashes.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time

from backend.app.core.tracing import EDITOR_ROOT

CLI = EDITOR_ROOT / 'infra' / 'host' / 'cli.mjs'
DEFAULT_TIMEOUT_S = 90
DEFAULT_LEASE_S = 1800   # "in use until": the host stops an agent idle_timeout_s after its last lease ended


class HostUnavailable(Exception):
    """Node or the host CLI is missing, or the CLI did not answer in its contract."""


class HostRefused(Exception):
    """The CLI refused the request (an unknown id, nothing to start)."""


def host_id(agent: str) -> str:
    return agent.replace('_', '-')


def agent_id(host: str) -> str:
    return host.replace('-', '_')


async def _run(args: list[str], timeout_s: float) -> tuple[int, str, str]:
    node = shutil.which('node')
    if not node or not CLI.exists():
        raise HostUnavailable('node or infra/host/cli.mjs is missing')
    process = await asyncio.create_subprocess_exec(node, str(CLI), *args, cwd=str(EDITOR_ROOT), env=os.environ.copy(),
                                                   stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout_s)
    except asyncio.TimeoutError:
        process.kill()
        raise HostUnavailable('host CLI did not answer in time') from None
    return process.returncode, out.decode('utf-8', 'replace'), err.decode('utf-8', 'replace')


def _json_line(out: str, code: int, err: str) -> dict:
    line = next((row for row in reversed(out.splitlines()) if row.startswith('{')), None)
    if line is None:
        if code != 0 and err.strip():
            raise HostRefused(err.strip().splitlines()[-1])
        raise HostUnavailable('host CLI returned no JSON')
    try:
        return json.loads(line)
    except ValueError as exc:
        raise HostUnavailable(f'host CLI answer out of contract: {exc}') from None


STATUS_CACHE_S = 5.0
_status_cache: dict = {'at': 0.0, 'value': None}


async def status(*, runner=_run, now=time.monotonic, cache=_status_cache) -> dict:
    """Every agent's state from the daemon's last tick (no probes): {at, daemon: {pid, stale}, agents: {agent: {state, up,
    lease_until, idle_in_s}}} in agent ids; the same answer is served for STATUS_CACHE_S so a conversation turn costs
    one CLI call at most."""
    if cache['value'] is not None and now() - cache['at'] < STATUS_CACHE_S:
        return cache['value']
    code, out, err = await runner(['status', '--json', '--snapshot'], 20)
    result = _json_line(out, code, err)
    try:
        agents = {agent_id(row['id']): {'state': row['state'], 'up': row['up'], 'lease_until': row.get('leaseUntil'),
                                        'idle_in_s': row.get('idleInS')} for row in result['services'] if row.get('kind') in ('agent', 'orchestrator')}
        value = {'at': result.get('snapshotAt'), 'daemon': {'pid': result['daemon'].get('pid'), 'stale': bool(result['daemon'].get('stale'))}, 'agents': agents}
    except (KeyError, TypeError) as exc:
        raise HostUnavailable(f'host CLI answer out of contract: {exc}') from None
    cache['at'], cache['value'] = now(), value
    return value


async def touch(agents: list[str], *, lease_s: int = DEFAULT_LEASE_S, runner=_run) -> dict:
    """Extends the agents' leases (a run's hop, a conversation turn) so the idle stop waits. {agents[], lease_until}."""
    ids = [host_id(agent) for agent in agents]
    code, out, err = await runner(['touch', *ids, '--json', f'--lease={int(lease_s)}'], 20)
    result = _json_line(out, code, err)
    return {'agents': list(agents), 'lease_until': result.get('leaseUntil')}


async def ensure(agents: list[str], *, timeout_s: int = DEFAULT_TIMEOUT_S, lease_s: int = DEFAULT_LEASE_S, runner=_run) -> dict:
    """Brings the agents up (parallel, dependency-ordered by the host), leases them for `lease_s` and waits for their
    health. Answer: {requested[], up[], failed: [{agent, error}], waited_s, lease_until} in agent ids."""
    ids = [host_id(agent) for agent in agents]
    code, out, err = await runner(['ensure', *ids, '--json', f'--timeout={int(timeout_s)}', f'--lease={int(lease_s)}'], timeout_s + 15)
    result = _json_line(out, code, err)
    try:
        up = [agent_id(i) for i in result['up']]
        failed = [{'agent': agent_id(f['id']), 'error': str(f.get('error') or 'no answer')} for f in result['failed']]
        waited = round(int(result['waitedMs']) / 1000, 1)
    except (ValueError, KeyError, TypeError) as exc:
        raise HostUnavailable(f'host CLI answer out of contract: {exc}') from None
    return {'requested': list(agents), 'up': up, 'failed': failed, 'waited_s': waited, 'lease_until': result.get('leaseUntil')}
