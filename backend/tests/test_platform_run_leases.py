"""A running run keeps the agents that are up leased (backend/app/modules/platform/run_leases.py)."""
import asyncio

from backend.app.modules.platform import host, run_leases


def keep(run, agents, *, last, clock, touched):
    async def status():
        return {'agents': agents}

    async def touch(ids):
        touched.append(ids)
        return {'agents': ids, 'lease_until': 'later'}

    return asyncio.run(run_leases.keep(run, status=status, touch=touch, now=lambda: clock[0], last=last))


AGENTS = {'masterplan': {'up': True, 'idle_in_s': 120}, 'mass': {'up': True, 'idle_in_s': 900},
          'law': {'up': True, 'idle_in_s': None}, 'program': {'up': False, 'idle_in_s': None}}


def test_a_running_run_touches_the_agents_up_with_an_idle_timeout_once_per_interval():
    touched, last, clock = [], {'at': None}, [1000.0]
    assert keep({'status': 'running'}, AGENTS, last=last, clock=clock, touched=touched) == ['mass', 'masterplan']
    assert touched == [['mass', 'masterplan']]
    clock[0] += run_leases.TOUCH_EVERY_S - 1
    assert keep({'status': 'running'}, AGENTS, last=last, clock=clock, touched=touched) is None
    clock[0] += 2
    assert keep({'status': 'reconciling'}, AGENTS, last=last, clock=clock, touched=touched) == ['mass', 'masterplan']
    assert len(touched) == 2


def test_a_finished_run_touches_nothing_and_a_missing_host_is_not_an_error():
    touched, last, clock = [], {'at': None}, [0.0]
    assert keep({'status': 'succeeded'}, AGENTS, last=last, clock=clock, touched=touched) is None
    assert touched == []

    async def unavailable():
        raise host.HostUnavailable('no node')

    assert asyncio.run(run_leases.keep({'status': 'running'}, status=unavailable, touch=None, now=lambda: 0.0,
                                       last={'at': None})) is None
