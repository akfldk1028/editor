import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.adapters.orchestrator import OrchestratorClient
from backend.app.modules.platform.repository import ProjectRepository
from backend.app.modules.platform.routers.platform import create_platform_router
from backend.app.schemas.platform import ProjectCreate


def snapshot(**changes):
    return dict(owner_project_id='owner-a', branch_id='main', conversation_id='main',
                revision=0, status='idle', messages=[], artifacts=[], error=None, **changes)


async def no_activation():
    pass


def setup(tmp_path, handler, activation=no_activation):
    repository = ProjectRepository(tmp_path)
    binding = repository.create('local', ProjectCreate(owner_project_id='owner-a', branch_id='main',
        scene_id='scene-a', scene_project_id='scene-p', scene_revision=1))
    owner = OrchestratorClient('http://owner', transport=httpx.MockTransport(handler))
    app = FastAPI()
    app.include_router(create_platform_router(owner, project_service=SimpleNamespace(repository=repository),
                                             conversation_activation=activation))
    return TestClient(app), f'/api/v1/platform/projects/{binding.project_id}/conversation'


def test_bound_read_and_duplicate_submission_are_authoritative(tmp_path, monkeypatch):
    monkeypatch.setenv('A2A_TOKEN', 'conversation-test-token')
    seen = []
    def handler(request):
        assert request.headers['authorization'] == 'Bearer conversation-test-token'
        assert request.headers.get('x-editor-client') == 'local'
        assert 'origin' not in request.headers
        assert request.url.path == '/editor/v1/conversation'
        if request.method == 'GET':
            assert dict(request.url.params) == dict(project='owner-a', branch='main', conversation_id='main')
            return httpx.Response(200, json=snapshot())
        body = json.loads(request.content)
        seen.append(body)
        assert body['project'] == 'owner-a' and body['branch'] == 'main'
        return httpx.Response(202, json={**snapshot(), 'revision': 1, 'status': 'working', 'messages': [
            dict(id=body['message_id'], role='user', agent=None, text=body['text'], at='2026-10-09T00:00:00Z')]})
    client, url = setup(tmp_path, handler)
    assert client.get(url).json() == snapshot()
    body = dict(conversation_id='main', message_id='m-1', text='hello', context={})
    first = client.post(url, json=body)
    second = client.post(url, json=body)
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert len(seen) == 2


@pytest.mark.parametrize('body', [
    dict(message_id='../bad', text='hi'), dict(message_id='m', text=' '),
    dict(message_id='m', text='a' * 8001), dict(message_id='m', text='hi', project='other'),
    dict(message_id='m', text='hi', context={'pnu':'123'}),
    dict(message_id='m', text='hi', context={'assessment_date':'2026-02-30'}),
])
def test_invalid_input_never_reaches_owner(tmp_path, body):
    client, url = setup(tmp_path, lambda request: pytest.fail('invalid input reached owner'))
    assert client.post(url, json=body).status_code == 422
    assert client.get(url, params={'conversation_id':'../bad'}).status_code == 422


def test_origin_and_unknown_binding(tmp_path):
    client, url = setup(tmp_path, lambda request: pytest.fail('invalid request reached owner'))
    assert client.post(url, json={'message_id':'m','text':'hi'}, headers={'origin':'https://other'}).status_code == 403
    assert client.get('/api/v1/platform/projects/unknown/conversation').status_code == 404


@pytest.mark.parametrize('status', [401, 403, 404, 409, 422, 429, 500, 503])
def test_owner_error_status_preserved(tmp_path, status):
    client, url = setup(tmp_path, lambda request: httpx.Response(status, json={'detail':'upstream'}))
    assert client.get(url).status_code == status


@pytest.mark.parametrize('changes', [
    {'owner_project_id':'other'}, {'branch_id':'other'}, {'conversation_id':'other'},
    {'revision':True}, {'status':'invented'}, {'messages':[{'id':'m'}]},
    {'messages':[dict(id='m', role='user', agent=None, text='hi', at='invalid')]},
    {'artifacts':[dict(id='a', owner='law', title='bad', data=[], status='ok')]},
])
def test_invalid_owner_snapshot_rejected(tmp_path, changes):
    client, url = setup(tmp_path, lambda request: httpx.Response(200, json={**snapshot(), **changes}))
    assert client.get(url).status_code == 502


def test_owner_oversized_response_and_request(tmp_path):
    client, url = setup(tmp_path, lambda request: httpx.Response(200, content=b' ' * (2 * 1024 * 1024 + 1)))
    assert client.get(url).status_code == 502
    assert client.post(url, content=b' ' * 65537, headers={'content-type':'application/json'}).status_code == 413


@pytest.mark.parametrize('payload', [b'not json', b'{}'])
def test_malformed_owner_json(tmp_path, payload):
    client, url = setup(tmp_path, lambda request: httpx.Response(200, content=payload))
    assert client.get(url).status_code == 502


def test_duplicate_owner_records_rejected(tmp_path):
    record = dict(id='m', role='user', agent=None, text='hi', at='2026-10-09T00:00:00Z')
    client, url = setup(tmp_path, lambda request: httpx.Response(200, json={**snapshot(), 'messages':[record, record]}))
    assert client.get(url).status_code == 502


def test_disconnected_owner(tmp_path):
    def disconnected(request):
        raise httpx.ConnectError('unavailable', request=request)
    client, url = setup(tmp_path, disconnected)
    assert client.get(url).status_code == 503


def test_two_local_projects_keep_distinct_owner_identity(tmp_path):
    seen = []
    def handler(request):
        owner_id = request.url.params['project']
        seen.append(owner_id)
        return httpx.Response(200, json={**snapshot(), 'owner_project_id':owner_id})
    client, first_url = setup(tmp_path, handler)
    second = ProjectRepository(tmp_path).create('local', ProjectCreate(owner_project_id='owner-b', branch_id='main',
        scene_id='scene-b', scene_project_id='scene-p', scene_revision=1))
    assert client.get(first_url).json()['owner_project_id'] == 'owner-a'
    assert client.get(f'/api/v1/platform/projects/{second.project_id}/conversation').json()['owner_project_id'] == 'owner-b'
    assert seen == ['owner-a', 'owner-b']


def test_version_bound_confirmation_forwarded_unchanged(tmp_path):
    confirmation = {'artifact_id':'proposal.abc', 'context_hash':'a' * 64}
    def handler(request):
        body = json.loads(request.content)
        assert body['confirmation'] == confirmation
        assert body['project'] == 'owner-a' and body['branch'] == 'main'
        return httpx.Response(202, json=snapshot())
    client, url = setup(tmp_path, handler)
    assert client.post(url, json={'message_id':'m', 'text':'Confirm', 'confirmation':confirmation}).status_code == 202


@pytest.mark.parametrize('confirmation', [
    {'artifact_id':'../bad', 'context_hash':'a' * 64},
    {'artifact_id':'proposal.abc', 'context_hash':'A' * 64},
    {'artifact_id':'proposal.abc', 'context_hash':'a' * 63},
    {'artifact_id':'proposal.abc', 'context_hash':'a' * 64, 'project':'other'},
    {'artifact_id':'proposal.abc'},
])
def test_invalid_confirmation_never_reaches_owner(tmp_path, confirmation):
    client, url = setup(tmp_path, lambda request: pytest.fail('invalid confirmation reached owner'))
    assert client.post(url, json={'message_id':'m', 'text':'Confirm', 'confirmation':confirmation}).status_code == 422


def test_activation_only_after_valid_submission(tmp_path):
    events = []
    async def activate():
        events.append('activate')
    def handler(request):
        events.append(request.method)
        return httpx.Response(202 if request.method == 'POST' else 200, json=snapshot())
    client, url = setup(tmp_path, handler, activate)
    assert client.get(url).status_code == 200
    assert events == ['GET']
    events.clear()
    body = {'message_id':'m','text':'Hello'}
    assert client.post(url, json=body, headers={'origin':'https://other'}).status_code == 403
    assert client.post(url, json=body, headers={'sec-fetch-site':'cross-site'}).status_code == 403
    assert client.post(url, json={'message_id':'m','text':''}).status_code == 422
    assert client.post('/api/v1/platform/projects/unknown/conversation', json=body).status_code == 404
    assert events == []
    assert client.post(url, json=body).status_code == 202
    assert events == ['activate', 'POST']


@pytest.mark.parametrize('failure', ['HostUnavailable', 'HostRefused'])
def test_activation_failure_refuses_submission(tmp_path, failure):
    from backend.app.modules.platform import host
    async def activate():
        raise getattr(host, failure)('private process detail')
    client, url = setup(tmp_path, lambda request: pytest.fail('unready providers reached owner'), activate)
    response = client.post(url, json={'message_id':'m','text':'Hello'})
    assert response.status_code == 503
    assert 'private process detail' not in response.text


def test_activation_selects_capability_from_registry(tmp_path, monkeypatch):
    import asyncio
    from backend.app.modules.platform import conversation_activation as module
    path = tmp_path / 'infra' / 'config'
    path.mkdir(parents=True)
    (path / 'services.json').write_text(json.dumps({'services':[
        {'id':'future-owner', 'capabilities':['design-conversation/v1']},
        {'id':'unrelated', 'capabilities':['other/v1']},
        {'id':'another'},
        {'id':'custom-orchestrator', 'capabilities':['design-conversation/v1'],
         'required_for_capabilities':['design-conversation/v1']},
    ]}), encoding='utf-8')
    monkeypatch.setattr(module, 'EDITOR_ROOT', tmp_path)
    calls = []
    async def ensure(agents, *, timeout_s):
        calls.append((agents, timeout_s))
        return {'up':agents, 'failed':[]}
    monkeypatch.setattr(module.host, 'ensure', ensure)
    asyncio.run(module.activate())
    assert calls == [(['future_owner', 'custom_orchestrator'], 30)]


@pytest.mark.parametrize('answer', [
    {'up':['future_owner'], 'failed':[]},
    {'up':['gateway'], 'failed':[{'agent':'gateway'}]},
])
def test_activation_requires_registered_gateway(tmp_path, monkeypatch, answer):
    import asyncio
    from backend.app.modules.platform import conversation_activation as module
    path = tmp_path / 'infra' / 'config'
    path.mkdir(parents=True)
    (path / 'services.json').write_text(json.dumps({'services':[
        {'id':'future-owner', 'capabilities':['design-conversation/v1']},
        {'id':'gateway', 'capabilities':['design-conversation/v1'],
         'required_for_capabilities':['design-conversation/v1']},
    ]}), encoding='utf-8')
    monkeypatch.setattr(module, 'EDITOR_ROOT', tmp_path)
    async def ensure(agents, *, timeout_s):
        return answer
    monkeypatch.setattr(module.host, 'ensure', ensure)
    with pytest.raises(module.host.HostUnavailable):
        asyncio.run(module.activate())


def test_optional_owner_failure_still_forwards_conversation(tmp_path, monkeypatch):
    from backend.app.modules.platform import conversation_activation as module
    path = tmp_path / 'infra' / 'config'
    path.mkdir(parents=True)
    (path / 'services.json').write_text(json.dumps({'services':[
        {'id':'optional-owner', 'capabilities':['design-conversation/v1']},
        {'id':'gateway', 'capabilities':['design-conversation/v1'],
         'required_for_capabilities':['design-conversation/v1']},
    ]}), encoding='utf-8')
    monkeypatch.setattr(module, 'EDITOR_ROOT', tmp_path)
    events = []
    async def ensure(agents, *, timeout_s):
        assert agents == ['optional_owner', 'gateway']
        events.append('activation')
        return {'up':['gateway'], 'failed':[{'agent':'optional_owner', 'error':'unavailable'}]}
    monkeypatch.setattr(module.host, 'ensure', ensure)
    def handler(request):
        events.append('forwarded')
        return httpx.Response(202, json=snapshot())
    client, url = setup(tmp_path, handler, module.activate)
    assert client.post(url, json={'message_id':'hello', 'text':'Hello'}).status_code == 202
    assert events == ['activation', 'forwarded']


def test_activation_without_required_gateway_registration_refuses(tmp_path, monkeypatch):
    import asyncio
    from backend.app.modules.platform import conversation_activation as module
    path = tmp_path / 'infra' / 'config'
    path.mkdir(parents=True)
    (path / 'services.json').write_text(json.dumps({'services':[
        {'id':'optional-owner', 'capabilities':['design-conversation/v1']},
    ]}), encoding='utf-8')
    monkeypatch.setattr(module, 'EDITOR_ROOT', tmp_path)
    async def ensure(agents, *, timeout_s):
        pytest.fail('registry lacks a required gateway')
    monkeypatch.setattr(module.host, 'ensure', ensure)
    with pytest.raises(module.host.HostUnavailable):
        asyncio.run(module.activate())


def test_address_message_is_located_by_the_editor_and_never_reaches_owner(tmp_path, monkeypatch):
    from backend.app.modules.platform.routers import conversation as module
    located = []
    async def locate(query):
        located.append(query)
        return {'kind': 'site', 'query': query, 'pnu': '4115011300106840001', 'address': '경기도 의정부시 산곡동 684-1',
                'coordinates': {'x': 127.1, 'y': 37.7}, 'error': None}
    monkeypatch.setattr(module, 'locate_site', locate)
    async def no_providers():
        pytest.fail('an address needs no owner, so no activation')
    client, url = setup(tmp_path, lambda request: pytest.fail('an address reached the owner'), no_providers)
    response = client.post(url, json={'message_id': 'm-1', 'text': ' 경기도  의정부시 산곡동 684-1 '})
    assert response.status_code == 200
    assert response.json() == {'located': {'kind': 'site', 'query': '경기도 의정부시 산곡동 684-1', 'pnu': '4115011300106840001',
                                           'address': '경기도 의정부시 산곡동 684-1', 'coordinates': {'x': 127.1, 'y': 37.7}, 'error': None}}
    assert located == ['경기도 의정부시 산곡동 684-1']
    assert client.post('/api/v1/platform/projects/unknown/conversation', json={'message_id': 'm-2', 'text': '산곡동 684-1'}).status_code == 404


def test_a_sentence_with_an_address_in_it_still_goes_to_the_owner(tmp_path, monkeypatch):
    from backend.app.modules.platform.routers import conversation as module
    async def locate(query):
        pytest.fail('only a whole-message address is the editor\'s')
    monkeypatch.setattr(module, 'locate_site', locate)
    forwarded = []
    def handler(request):
        forwarded.append(json.loads(request.content)['text'])
        return httpx.Response(202, json=snapshot())
    client, url = setup(tmp_path, handler)
    assert client.post(url, json={'message_id': 'm-1', 'text': '산곡동 684-1에 어린이집을 지으려고 해요'}).status_code == 202
    assert forwarded == ['산곡동 684-1에 어린이집을 지으려고 해요']
