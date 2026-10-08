"""GET /api/v1/platform/status: registry rows, probes, host records and the Orchestrator merge."""
import json
import os

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.adapters.orchestrator import OrchestratorClient
from backend.app.modules.platform.routers.platform import create_platform_router
from backend.app.modules.platform.status.probes import Prober
from backend.app.modules.platform.status.registry import REGISTRY_PATH, Registry, health_url, host_record
from backend.app.modules.platform.status.service import StatusService


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def test_registry_reads_services_json_and_refreshes_on_mtime(tmp_path):
    live = Registry().entries()
    assert len(live) == 22
    assert {entry['kind'] for entry in live} == {'editor', 'orchestrator', 'agent', 'infra'}
    assert sum(entry['kind'] == 'agent' for entry in live) == 15
    assert REGISTRY_PATH.name == 'services.json'

    path = tmp_path / 'services.json'
    path.write_text(json.dumps({'services': [{'id': 'a', 'kind': 'agent', 'port': 1, 'host_env': None, 'health_url': '{base}/health'}]}))
    registry = Registry(path)
    assert [entry['id'] for entry in registry.entries()] == ['a']
    path.write_text(json.dumps({'services': []}))
    os.utime(path, (1, 1))
    assert registry.entries() == []


def test_health_url_prefers_the_env_override_and_handles_no_port():
    entry = {'id': 'law', 'port': 8301, 'host_env': 'LAW_A2A_URL', 'health_url': '{base}/health'}
    assert health_url(entry, {}) == 'http://127.0.0.1:8301/health'
    assert health_url(entry, {'LAW_A2A_URL': 'http://law.internal:9/'}) == 'http://law.internal:9/health'
    assert health_url({'id': 'neo4j', 'port': 7687, 'host_env': 'NEO4J_URI', 'health_url': None}, {}) is None
    assert health_url({'id': 'x', 'port': None, 'host_env': None, 'health_url': '{base}/h'}, {}) is None


def test_host_record_reads_the_supervisor_pid_file(tmp_path):
    (tmp_path / 'backend.json').write_text(json.dumps({'pid': 42, 'startedAt': '2026-10-08T02:30:54.607Z', 'cmd': [], 'adopted': False}))
    (tmp_path / 'broken.json').write_text('{')
    assert host_record('backend', tmp_path) == {'host': 'infra/host', 'pid': 42, 'started_at': '2026-10-08T02:30:54.607Z', 'adopted': False}
    assert host_record('broken', tmp_path) is None
    assert host_record('missing', tmp_path) is None


def fake_network(handler):
    """httpx MockTransport routed by host: 'up.test' answers JSON, 'down.test' refuses, others 500."""
    def respond(request):
        if request.url.host == 'up.test':
            return httpx.Response(200, json={'version': '1.2.3+abc', 'started_at': '2026-10-08T00:00:00Z'})
        if request.url.host == 'down.test':
            raise httpx.ConnectError('refused')
        return httpx.Response(500, text='boom')
    return httpx.MockTransport(handler or respond)


@pytest.mark.anyio
async def test_probes_report_up_down_and_unknown_without_raising_and_cache_for_20s():
    clock = [100.0]
    prober = Prober(transport=fake_network(None), clock=lambda: clock[0])
    urls = {'a': 'http://up.test/health', 'b': 'http://down.test/health', 'c': 'http://err.test/health', 'd': None}
    first = await prober.probe_all(urls)
    assert first['a'].state == 'up' and first['a'].version == '1.2.3+abc' and first['a'].started_at == '2026-10-08T00:00:00Z'
    assert first['b'].state == 'down' and first['b'].error == 'ConnectError' and first['b'].http_status is None
    assert first['c'].state == 'down' and first['c'].http_status == 500
    assert first['d'].state == 'unknown'
    clock[0] += 10
    assert (await prober.probe_all(urls))['a'] is first['a']
    assert (await prober.probe_all(urls, force=True))['a'] is not first['a']
    clock[0] += 21
    assert (await prober.probe_all(urls))['a'] is not first['a']


def registry_with(tmp_path, orchestrator_host):
    path = tmp_path / 'services.json'
    path.write_text(json.dumps({'services': [
        {'id': 'backend', 'kind': 'editor', 'port': 18449, 'host_env': None, 'health_url': '{base}/api/v1/platform/health',
         'lifecycle': 'persistent', 'management': 'editor-session', 'notes': 'n'},
        {'id': 'orchestrator', 'kind': 'orchestrator', 'port': 8791, 'host_env': 'HUB', 'health_url': '{base}/editor/v1/health',
         'lifecycle': 'persistent', 'management': 'agent-host', 'notes': ''},
        {'id': 'law', 'kind': 'agent', 'port': 8301, 'host_env': None, 'health_url': '{base}/health',
         'launcher': {'name': 'LawAgent', 'catalog': 'law_agent.json'}, 'lifecycle': 'persistent', 'management': 'agent-host', 'notes': ''},
        {'id': 'neo4j', 'kind': 'infra', 'port': 7687, 'host_env': None, 'health_url': None,
         'lifecycle': 'persistent', 'management': 'external', 'notes': ''},
    ]}))
    return Registry(path), {'HUB': f'http://{orchestrator_host}'}


def owner_client(agents):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=agents))
    return OrchestratorClient('http://owner', transport=transport)


def catalog_agent(agent_id, label):
    return {'agent_id': agent_id, 'label': label, 'capabilities': [], 'implementation_status': 'unknown',
            'connection_status': 'available', 'checked_at': '2026-10-08T01:00:00Z', 'evidence_ref': None}


@pytest.mark.anyio
async def test_orchestrator_down_rows_still_come_from_direct_probes(tmp_path):
    registry, env = registry_with(tmp_path, 'down.test')

    def respond(request):
        if request.url.host == 'down.test':
            raise httpx.ConnectError('refused')
        return httpx.Response(200, json={'version': 'v'})
    owner = OrchestratorClient('http://owner', transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    service = StatusService(registry, Prober(transport=httpx.MockTransport(respond)), owner, env=env, runtime_dir=tmp_path)
    value = await service.status()
    by_id = {row['id']: row for row in value['services']}
    assert value['orchestrator']['state'] == 'down'
    assert by_id['orchestrator']['state'] == 'down'
    assert by_id['law']['state'] == 'up' and by_id['law']['orchestrator'] is None
    assert by_id['neo4j']['state'] == 'unknown'
    assert by_id['backend']['managed_by'] is None


@pytest.mark.anyio
async def test_orchestrator_up_merges_its_agent_view_and_host_records(tmp_path):
    registry, env = registry_with(tmp_path, 'up.test')
    (tmp_path / 'backend.json').write_text(json.dumps({'pid': 7, 'startedAt': '2026-10-08T02:30:54Z', 'cmd': [], 'adopted': True}))
    owner = owner_client([catalog_agent('LawAgent', 'LawAgent'), catalog_agent('Other', 'OtherAgent')])
    service = StatusService(registry, Prober(transport=fake_network(None)), owner, env=env, runtime_dir=tmp_path)
    value = await service.status()
    by_id = {row['id']: row for row in value['services']}
    assert value['orchestrator'] == {'state': 'up', 'error': None, 'agents': 2}
    assert by_id['law']['orchestrator'] == {'connection_status': 'available', 'checked_at': '2026-10-08T01:00:00Z', 'evidence_ref': None}
    assert by_id['backend']['managed_by']['pid'] == 7 and by_id['backend']['started_at'] == '2026-10-08T02:30:54Z'
    assert by_id['orchestrator']['version'] == '1.2.3+abc'


def test_status_route_shape(tmp_path):
    registry, env = registry_with(tmp_path, 'up.test')
    owner = owner_client([catalog_agent('LawAgent', 'LawAgent')])
    service = StatusService(registry, Prober(transport=fake_network(None)), owner, env=env, runtime_dir=tmp_path)
    app = FastAPI()
    app.include_router(create_platform_router(owner, status_service=service))
    response = TestClient(app).get('/api/v1/platform/status?refresh=1')
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {'checked_at', 'orchestrator', 'services'}
    assert len(body['services']) == 4
    row = body['services'][0]
    assert set(row) >= {'id', 'kind', 'port', 'state', 'http_status', 'version', 'started_at', 'latency_ms', 'managed_by', 'notes',
                        'label', 'management', 'checked_at', 'error', 'orchestrator'}
    assert {row['state'] for row in body['services']} <= {'up', 'down', 'unknown'}


def test_agents_without_the_orchestrator_is_a_structured_answer():
    def fail(request):
        raise httpx.ConnectError('refused')
    app = FastAPI()
    app.include_router(create_platform_router(OrchestratorClient('http://owner', transport=httpx.MockTransport(fail))))
    response = TestClient(app).get('/api/v1/platform/agents')
    assert response.status_code == 503
    assert response.json() == {'agents': [], 'orchestrator': {'state': 'down', 'error': 'Orchestrator catalog unavailable'}}
    bad = FastAPI()
    bad.include_router(create_platform_router(OrchestratorClient('http://owner',
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'wrong': []})))))
    response = TestClient(bad).get('/api/v1/platform/agents')
    assert response.status_code == 502
    assert response.json()['orchestrator']['state'] == 'invalid'
