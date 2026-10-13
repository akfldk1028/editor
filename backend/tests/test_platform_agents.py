import json
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.modules.platform.routers.platform import create_platform_router
from backend.app.adapters.orchestrator import OrchestratorClient


@pytest.mark.parametrize('status,body,expected', [
    (200, [], 200), (503, {}, 503), (200, {'wrong': []}, 502),
    (200, [{'agent_id': 'bad'}], 502),
])
def test_agents_owner_contract(status, body, expected):
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body))
    app = FastAPI()
    app.include_router(create_platform_router(OrchestratorClient('http://owner', transport=transport)))
    response = TestClient(app).get('/api/v1/platform/agents')
    assert response.status_code == expected


def test_unconfigured_owner_is_unavailable():
    app = FastAPI()
    app.include_router(create_platform_router(OrchestratorClient(None)))
    assert TestClient(app).get('/api/v1/platform/agents').status_code == 503


def test_owner_timeout_is_not_empty_success():
    def fail(request):
        raise httpx.ReadTimeout('private internal details')
    app = FastAPI()
    app.include_router(create_platform_router(OrchestratorClient('http://owner', transport=httpx.MockTransport(fail))))
    response = TestClient(app).get('/api/v1/platform/agents')
    assert response.status_code == 503
    assert 'private internal' not in response.text


def test_agents_carry_their_own_card_words():
    """The Orchestrator's catalog gives the ids; each agent's live A2A card adds its description and skills by name."""
    catalog = [{'agent_id': 'site_context', 'label': 'SiteContextAgent', 'capabilities': ['site_resolve', 'site_health'],
                'implementation_status': 'unknown', 'connection_status': 'available', 'checked_at': None, 'evidence_ref': None},
               {'agent_id': 'structure', 'label': 'structure', 'capabilities': [], 'implementation_status': 'unknown',
                'connection_status': 'not_declared', 'checked_at': None, 'evidence_ref': None}]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=catalog))

    async def roster(agents):
        assert agents == ['site_context', 'structure']
        return {'site_context': {'name': 'SiteContextAgent', 'description': 'Establishes the facts a parcel has.',
                                 'skills': [{'id': 'site_resolve', 'name': 'resolve', 'description': 'Resolve the site facts for a parcel.'}]},
                'structure': None}
    app = FastAPI()
    app.include_router(create_platform_router(OrchestratorClient('http://owner', transport=transport), roster=roster))
    rows = TestClient(app).get('/api/v1/platform/agents').json()
    assert rows[0]['description'] == 'Establishes the facts a parcel has.'
    assert rows[0]['skills'] == [{'id': 'site_resolve', 'name': 'resolve', 'description': 'Resolve the site facts for a parcel.'}]
    assert rows[1]['description'] is None and rows[1]['skills'] is None


def test_a_failing_card_lookup_leaves_the_catalog_as_it_is():
    catalog = [{'agent_id': 'law', 'label': 'LawAgent', 'capabilities': ['law_search'], 'implementation_status': 'unknown',
                'connection_status': 'available', 'checked_at': None, 'evidence_ref': None}]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=catalog))

    async def roster(agents):
        raise RuntimeError('registry unreadable')
    app = FastAPI()
    app.include_router(create_platform_router(OrchestratorClient('http://owner', transport=transport), roster=roster))
    rows = TestClient(app).get('/api/v1/platform/agents').json()
    assert rows[0]['agent_id'] == 'law' and rows[0]['description'] is None and rows[0]['skills'] is None


def test_a_card_with_a_non_string_skill_name_does_not_break_the_catalog():
    from backend.app.modules.platform.routing import cards
    card = cards._card({'name': 'X', 'description': 'd', 'skills': [{'id': 'x_a', 'name': None, 'description': 7}, {'id': 'x_b', 'name': 'b'}]})
    assert card['skills'] == [{'id': 'x_a', 'name': 'x_a', 'description': ''}, {'id': 'x_b', 'name': 'b', 'description': 'b'}]


def test_an_agents_own_task_records_are_read_with_the_official_list_tasks_call():
    """ListTasks (a2a-sdk 1.0) answers the request the agent got and its full reply; the route maps them for the view."""
    import asyncio

    from backend.app.adapters import a2a_tasks

    listing = {'jsonrpc': '2.0', 'id': 'x', 'result': {'tasks': [{
        'id': 'f2d2', 'contextId': 'ctx', 'status': {'state': 'TASK_STATE_COMPLETED', 'timestamp': '2026-10-12T10:47:03Z',
        'message': {'role': 'ROLE_AGENT', 'parts': [{'text': '{"status": "partial", "summary": "6/9"}'}], 'metadata': {'tool': 'site_resolve'}}},
        'history': [{'role': 'ROLE_USER', 'parts': [{'text': '{"tool": "site_resolve", "args": {"pnu": "1"}}'}]}], 'artifacts': []}]}}
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=listing)
    records = asyncio.run(a2a_tasks.list_tasks('site_context', transport=httpx.MockTransport(handler), env={'SITE_CONTEXT_A2A_URL': 'http://site'}))
    assert seen[0]['method'] == 'ListTasks' and seen[0]['params'] == {'pageSize': 20, 'historyLength': 2, 'includeArtifacts': True}
    assert records == [{'id': 'f2d2', 'context_id': 'ctx', 'state': 'completed', 'at': '2026-10-12T10:47:03Z', 'tool': 'site_resolve',
                        'request_text': '{"tool": "site_resolve", "args": {"pnu": "1"}}', 'response_text': '{"status": "partial", "summary": "6/9"}'}]

    async def tasks(agent):
        assert agent == 'site_context'
        return records

    async def down(agent):
        raise a2a_tasks.AgentTasksUnavailable('site_context unreachable')
    app = FastAPI()
    app.include_router(create_platform_router(OrchestratorClient(None), tasks=tasks))
    assert TestClient(app).get('/api/v1/platform/agents/site_context/tasks').json() == {'agent': 'site_context', 'tasks': records}
    assert TestClient(app).get('/api/v1/platform/agents/bad id/tasks').status_code == 400
    gone = FastAPI()
    gone.include_router(create_platform_router(OrchestratorClient(None), tasks=down))
    assert TestClient(gone).get('/api/v1/platform/agents/site_context/tasks').status_code == 503


def test_one_task_is_read_by_its_a2a_id_and_a_missing_one_is_404():
    import asyncio

    from backend.app.adapters import a2a_tasks

    def handler(request):
        body = json.loads(request.content)
        assert body['method'] == 'GetTask'
        if body['params']['id'] == 'gone':
            return httpx.Response(200, json={'jsonrpc': '2.0', 'id': 'x', 'error': {'code': -32001, 'message': 'Task not found'}})
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': 'x', 'result': {'task': {
            'id': body['params']['id'], 'contextId': 'ctx', 'status': {'state': 'TASK_STATE_COMPLETED', 'timestamp': None,
            'message': {'role': 'ROLE_AGENT', 'parts': [{'text': '{"status": "ok"}'}], 'metadata': {'tool': 'law_search'}}},
            'history': [{'role': 'ROLE_USER', 'parts': [{'text': '{"tool": "law_search"}'}]}]}}})
    env = {'LAW_A2A_URL': 'http://law'}
    record = asyncio.run(a2a_tasks.get_task('law', 'abc', transport=httpx.MockTransport(handler), env=env))
    assert record['id'] == 'abc' and record['tool'] == 'law_search' and record['response_text'] == '{"status": "ok"}'
    import pytest as _pytest
    with _pytest.raises(a2a_tasks.AgentTaskNotFound):
        asyncio.run(a2a_tasks.get_task('law', 'gone', transport=httpx.MockTransport(handler), env=env))

    async def task(agent, task_id):
        if task_id == 'gone':
            raise a2a_tasks.AgentTaskNotFound('gone')
        return record
    app = FastAPI()
    app.include_router(create_platform_router(OrchestratorClient(None), task=task))
    assert TestClient(app).get('/api/v1/platform/agents/law/tasks/abc').json() == {'agent': 'law', 'task': record}
    assert TestClient(app).get('/api/v1/platform/agents/law/tasks/gone').status_code == 404
    assert TestClient(app).get('/api/v1/platform/agents/law/tasks/bad%20id').status_code == 400


def test_the_door_may_name_the_a2a_task_of_a_communication():
    from backend.app.schemas.communications import RunCommunication
    row = RunCommunication.model_validate({'id': '1', 'task_id': 'site_resolve', 'tool': 'site_resolve', 'agent': 'site_context', 'state': 'failed',
                                           'request_text': '{}', 'response_text': '{}', 'transport': 'a2a', 'truncated': True, 'redacted': False,
                                           'a2a_task_id': 'c639', 'a2a_context_id': 'run1'})
    assert (row.a2a_task_id, row.a2a_context_id) == ('c639', 'run1')



def test_a_task_answered_the_a2a_way_reads_its_artifact():
    """A data-part caller (the Orchestrator) gets its result as an artifact; the full view reads it from there."""
    from backend.app.adapters.a2a_tasks import task_record
    task = {'id': 't1', 'status': {'state': 'TASK_STATE_COMPLETED', 'message': {'parts': [{'text': ''}], 'metadata': {'tool': 'law_parcel_limits'}}},
            'artifacts': [{'artifactId': 'a', 'name': 'law_parcel_limits', 'parts': [{'data': {'bcr_pct': 60.0, 'far_pct': 250.5}}]}],
            'history': [{'role': 'ROLE_USER', 'parts': [{'text': '{"tool": "law_parcel_limits", "args": {}}'}]}]}
    record = task_record(task)
    assert record['tool'] == 'law_parcel_limits' and record['state'] == 'completed'
    assert record['response_text'] == '{"bcr_pct": 60, "far_pct": 250.5}'
