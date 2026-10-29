"""While a run of this project is running, the agents that are up stay leased.

The host stops an agent idle_timeout_s after its last lease ended, and a run's hops take no lease of
their own: MasterPlan was idle-stopped in the middle of the brief it was answering, and the run ended
`reconciling outcome_unknown` (run 5dc5476f, 2026-10-29). The editor polls a running run every few
seconds; once per TOUCH_EVERY_S that poll extends the lease of every agent the host reports up with an
idle timeout. No agent is named here; the host says which are up.
"""
from __future__ import annotations

import time

from backend.app.modules.platform import host

RUNNING = ('queued', 'running', 'reconciling')
TOUCH_EVERY_S = 300.0
_last: dict = {'at': None}


async def keep(run: dict, *, status=host.status, touch=host.touch, now=time.monotonic, last=_last) -> list[str] | None:
    """Extends the leases of the agents up with an idle timeout while `run` is running; the ids touched, or None."""
    if run.get('status') not in RUNNING:
        return None
    if last['at'] is not None and now() - last['at'] < TOUCH_EVERY_S:
        return None
    try:
        agents = (await status())['agents']
        up = sorted(agent for agent, row in agents.items() if row.get('up') and row.get('idle_in_s') is not None)
        if up:
            await touch(up)
    except (host.HostUnavailable, host.HostRefused):
        return None
    last['at'] = now()
    return up
