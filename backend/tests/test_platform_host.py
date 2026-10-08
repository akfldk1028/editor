"""`POST /api/v1/platform/host/ensure`: the conversation asks the host supervisor to bring agents up before a goal."""
import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.modules.platform import host
from backend.app.modules.platform.routers.host import create_host_router

ORIGIN = 'http://127.0.0.1:3003'


def test_ensure_maps_agent_ids_to_registry_ids_and_reads_the_cli_json():
    calls = []

    async def runner(args, timeout_s):
        calls.append((args, timeout_s))
        return 2, 'daemon pid 1 already runs\n{"up":["masterplan","site-context"],"failed":[{"id":"mass","error":"status 503"}],"waitedMs":41200}\n', ''

    answer = asyncio.run(host.ensure(['masterplan', 'site_context', 'mass'], timeout_s=60, runner=runner))
    assert calls == [(['ensure', 'masterplan', 'site-context', 'mass', '--json', '--timeout=60'], 75)]
    assert answer == {'requested': ['masterplan', 'site_context', 'mass'], 'up': ['masterplan', 'site_context'],
                      'failed': [{'agent': 'mass', 'error': 'status 503'}], 'waited_s': 41.2}


def test_ensure_names_a_refusal_and_a_silent_cli():
    async def refused(args, timeout_s):
        return 1, '', 'Unknown service "nobody" (not in infra/config/services.json)\n'

    async def silent(args, timeout_s):
        return 0, 'nothing\n', ''

    try:
        asyncio.run(host.ensure(['nobody'], runner=refused))
        raise AssertionError('expected HostRefused')
    except host.HostRefused as exc:
        assert 'Unknown service' in str(exc)
    try:
        asyncio.run(host.ensure(['law'], runner=silent))
        raise AssertionError('expected HostUnavailable')
    except host.HostUnavailable:
        pass


def test_route_is_same_origin_and_maps_errors():
    async def ensure(agents, *, timeout_s):
        if agents == ['nobody']:
            raise host.HostRefused('Unknown service "nobody"')
        if agents == ['law']:
            raise host.HostUnavailable('node missing')
        return {'requested': agents, 'up': agents, 'failed': [], 'waited_s': 0.3}

    app = FastAPI()
    app.include_router(create_host_router(ORIGIN, ensure), prefix='/api/v1/platform')
    client = TestClient(app)
    ok = client.post('/api/v1/platform/host/ensure', json={'agents': ['mass', 'mass', 'program']}, headers={'Origin': ORIGIN})
    assert ok.status_code == 200 and ok.json()['up'] == ['mass', 'program']
    assert client.post('/api/v1/platform/host/ensure', json={'agents': ['mass']}, headers={'Origin': 'http://evil.test'}).status_code == 403
    assert client.post('/api/v1/platform/host/ensure', json={'agents': []}, headers={'Origin': ORIGIN}).status_code == 422
    assert client.post('/api/v1/platform/host/ensure', json={'agents': ['../x']}, headers={'Origin': ORIGIN}).status_code == 422
    assert client.post('/api/v1/platform/host/ensure', json={'agents': ['nobody']}, headers={'Origin': ORIGIN}).status_code == 422
    assert client.post('/api/v1/platform/host/ensure', json={'agents': ['law']}, headers={'Origin': ORIGIN}).status_code == 503
    assert client.post('/api/v1/platform/host/ensure', json={'agents': ['law'], 'timeout_s': 1}, headers={'Origin': ORIGIN}).status_code == 422
