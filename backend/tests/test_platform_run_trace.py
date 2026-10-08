"""W3C trace context on the editor → Orchestrator submission: header sent, span recorded, trace read back."""
import asyncio
import json
import re

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.adapters.orchestrator import OrchestratorClient, OwnerUnavailable
from backend.app.core.tracing import JsonlTraceRecorder
from backend.app.modules.platform.projects import ProjectService
from backend.app.modules.platform.repository import ProjectRepository
from backend.app.modules.platform.routers.platform import create_platform_router
from backend.app.schemas.platform import ProjectCreate

TRACEPARENT = re.compile(r'^00-([0-9a-f]{32})-([0-9a-f]{16})-01$')


class Scenes:
    async def get_scene(self, scene_id):
        return {'id': scene_id, 'projectId': None, 'version': 1, 'ownerId': None}


def owner_run(request_id):
    return {'run_id': 'run-1', 'owner_project_id': 'p', 'branch_id': 'main', 'request_id': request_id,
            'goal': 'limits', 'status': 'queued', 'receipt_task_ids': [], 'pending_input': False}


class Seen(list):
    down = False


def orchestrator(tmp_path):
    """A real adapter over a mock Orchestrator that remembers every request it saw.
    `seen.down = True` makes it refuse connections from then on."""
    seen = Seen()

    def respond(request):
        seen.append(request)
        if seen.down:
            raise httpx.ConnectError('refused')
        if request.method == 'POST':
            return httpx.Response(202, json=owner_run(json.loads(request.content)['request_id']))
        if request.url.path == '/editor/v1/projects':
            return httpx.Response(200, json=[{'owner_project_id': 'p', 'branch_id': 'main'}])
        return httpx.Response(200, json=[])  # list_runs: nothing queued yet

    recorder = JsonlTraceRecorder(tmp_path / 'trace')
    return OrchestratorClient('http://owner', transport=httpx.MockTransport(respond)), seen, recorder


def client_for(tmp_path, owner, recorder):
    projects = ProjectService(ProjectRepository(tmp_path), owner, Scenes())
    binding = asyncio.run(projects.create('local', ProjectCreate(owner_project_id='p', branch_id='main', scene_id='s', scene_revision=1)))
    app = FastAPI()
    app.include_router(create_platform_router(owner, project_service=projects, trace_recorder=recorder))
    return TestClient(app), binding


PAYLOAD = {'request': {'goal': 'limits', 'pnu': '4115011300106840001'}, 'scene_revision': 1, 'source_versions': {}}


def test_submission_sends_traceparent_records_the_span_and_answers_with_the_trace_id(tmp_path):
    owner, seen, recorder = orchestrator(tmp_path)
    client, binding = client_for(tmp_path, owner, recorder)
    response = client.post(f'/api/v1/platform/projects/{binding.project_id}/runs', json=PAYLOAD, headers={'Idempotency-Key': 'k1'})
    assert response.status_code == 202
    body = response.json()
    assert re.fullmatch(r'[0-9a-f]{32}', body['trace_id'])
    assert body['run_id'] == 'run-1' and body['request_id'] == f'editor:{binding.project_id}:k1'

    post = next(request for request in seen if request.method == 'POST')
    assert post.headers['x-editor-client'] == 'local'
    match = TRACEPARENT.match(post.headers['traceparent'])
    assert match and match.group(1) == body['trace_id']
    # The retry probe (GET list) belongs to the same span; reads outside a submission carry their own trace.
    assert all(TRACEPARENT.match(request.headers.get('traceparent', '')) for request in seen)
    probe = next(request for request in seen if request.url.path == '/editor/v1/runs' and request.method == 'GET')
    assert probe.headers['traceparent'] == post.headers['traceparent']

    rows = recorder.rows()
    assert len(rows) == 1
    row = rows[0]
    assert row['trace_id'] == body['trace_id'] and row['span_id'] == match.group(2)
    assert row['name'] == 'invoke_agent orchestrator' and row['gen_ai.operation.name'] == 'invoke_agent'
    assert row['gen_ai.agent.name'] == 'orchestrator' and row['gen_ai.conversation.id'] == body['request_id']
    assert row['status'] == 'ok' and row['error.type'] is None and row['run_id'] == 'run-1'
    assert row['parent_span_id'] is not None and row['parent_span_id'] != row['span_id']

    trace = client.get(f'/api/v1/platform/runs/run-1/trace?project_id={binding.project_id}')
    assert trace.status_code == 200
    assert trace.json() == {'run_id': 'run-1', 'trace_ids': [body['trace_id']], 'spans': [row], 'truncated': False}
    assert client.get('/api/v1/platform/runs/run-1/trace?project_id=nope').status_code == 404


def test_an_incoming_traceparent_is_continued_not_replaced(tmp_path):
    owner, seen, recorder = orchestrator(tmp_path)
    client, binding = client_for(tmp_path, owner, recorder)
    incoming = '00-' + 'a1' * 16 + '-' + 'b2' * 8 + '-01'
    response = client.post(f'/api/v1/platform/projects/{binding.project_id}/runs', json=PAYLOAD,
                           headers={'Idempotency-Key': 'k2', 'traceparent': incoming})
    assert response.json()['trace_id'] == 'a1' * 16
    post = next(request for request in seen if request.method == 'POST')
    assert post.headers['traceparent'].startswith('00-' + 'a1' * 16 + '-') and post.headers['traceparent'] != incoming
    row = recorder.rows()[0]
    assert row['trace_id'] == 'a1' * 16 and row['parent_span_id'] == 'b2' * 8


def test_orchestrator_down_is_503_and_an_error_span(tmp_path):
    owner, seen, recorder = orchestrator(tmp_path)
    client, binding = client_for(tmp_path, owner, recorder)
    seen.down = True
    response = client.post(f'/api/v1/platform/projects/{binding.project_id}/runs', json=PAYLOAD, headers={'Idempotency-Key': 'k3'})
    assert response.status_code == 503 and response.json()['detail'] == 'external_outcome_unknown'
    # The failure happens at the retry probe, before any POST: the span still records it.
    assert seen[-1].method == 'GET' and seen[-1].url.path == '/editor/v1/runs'
    [row] = recorder.rows()
    assert row['status'] == 'error' and row['error.type'] == 'OwnerUnavailable' and row['run_id'] is None
    assert row['gen_ai.conversation.id'] == f'editor:{binding.project_id}:k3'
    match = TRACEPARENT.match(seen[-1].headers['traceparent'])
    assert (match.group(1), match.group(2)) == (row['trace_id'], row['span_id'])
    assert client.get(f'/api/v1/platform/runs/none/trace?project_id={binding.project_id}').json()['spans'] == []

    with pytest.raises(OwnerUnavailable):  # the adapter alone propagates; it records nothing
        asyncio.run(owner.submit_run({'project': 'p', 'branch': 'main', 'request_id': 'x', 'request': {}, 'source_versions': {}}))
    assert len(recorder.rows()) == 1
