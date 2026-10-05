import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.adapters.orchestrator import OrchestratorClient
from backend.app.api.routes_design_collaboration import create_design_collaboration_router
from backend.app.modules.platform.projects import ProjectService
from backend.app.modules.platform.repository import ProjectRepository
from backend.app.schemas.platform import ProjectCreate


BASE = '/api/v1/design/collaboration'


def setup(tmp_path, *, communications=None, owner_status=200, run_changes=None):
    requests = []
    repo = ProjectRepository(tmp_path)
    binding = repo.create('local', ProjectCreate(owner_project_id='owner-project', branch_id='main', scene_id='scene', scene_revision=1))
    run = dict(run_id='run-1', owner_project_id='owner-project', branch_id='main',
               request_id=f'editor:{binding.project_id}:request-1', goal='health', status='succeeded',
               receipt_task_ids=['task-1'], pending_input=False,
               communications=communications if communications is not None else [dict(
                   id='row-1', task_id='task-1', tool='health', agent='law_agent', state='finished',
                   request_text='recorded request', response_text='recorded response', transport='a2a', truncated=False)],
               communications_available=True, communications_truncated=False)
    run.update(run_changes or {})

    def handle(request):
        requests.append(request)
        if owner_status != 200:
            return httpx.Response(owner_status, json={})
        if request.url.path == '/editor/v1/agents':
            return httpx.Response(200, json=[dict(agent_id=name, label=name, capabilities=[],
                implementation_status='unknown', connection_status=status, checked_at=None, evidence_ref=None)
                for name, status in [('law_agent', 'available'), ('offline', 'unavailable'), ('local', 'local')]])
        assert request.method == 'GET'
        assert request.url.params['project'] == 'owner-project'
        assert request.url.params['branch'] == 'main'
        return httpx.Response(200, json=run)

    owner = OrchestratorClient('http://owner', transport=httpx.MockTransport(handle))
    projects = ProjectService(repo, owner, None)
    app = FastAPI()
    app.include_router(create_design_collaboration_router(owner, project_service=projects))
    return TestClient(app), binding.project_id, requests


def test_health_reports_only_observed_connected_agents(tmp_path):
    client, _, requests = setup(tmp_path)
    result = client.get(BASE + '/health')
    assert result.status_code == 200
    assert result.json()['service'] == 'editor-design-collaboration'
    assert result.json()['components']['bus']['connected_agents'] == ['law_agent']
    assert result.json()['direct_message_supported'] is False
    assert requests[0].url.path == '/editor/v1/agents'


def test_transcript_and_log_use_project_bound_recorded_text(tmp_path):
    client, project, _ = setup(tmp_path)
    query = dict(project_id=project, run_id='run-1')
    result = client.get(BASE + '/transcript', params=query)
    assert result.status_code == 200
    value = result.json()
    assert value['session_id'] == 'run-1'
    assert [m['message'] for m in value['messages']] == ['recorded request', 'recorded response']
    assert [m['from_agent'] for m in value['messages']] == ['orchestrator', 'law_agent']
    assert all(m['timestamp'] == '' for m in value['messages'])
    assert value['available'] is True
    log = client.get(BASE + '/bus/log', params={**query, 'limit': 1})
    assert log.status_code == 200
    assert len(log.json()) == 1
    assert log.json()[0]['message'] == 'recorded response'
    assert log.json()[0]['metadata']['source'] == 'orchestrator_run_receipt'


@pytest.mark.parametrize('endpoint', ['/bus/log', '/transcript'])
def test_unbound_reads_require_context_without_fetching_latest_run(tmp_path, endpoint):
    client, _, requests = setup(tmp_path)
    result = client.get(BASE + endpoint)
    assert result.status_code == 400
    assert result.json()['detail']['code'] == 'collaboration_context_required'
    assert requests == []


def test_unknown_project_is_not_forwarded(tmp_path):
    client, _, requests = setup(tmp_path)
    result = client.get(BASE + '/transcript', params=dict(project_id='wrong', run_id='run-1'))
    assert result.status_code == 404
    assert requests == []


@pytest.mark.parametrize('changes,expected', [
    ({'owner_project_id': 'other'}, 502),
    ({'request_id': 'editor:other:request-1'}, 404),
    ({'run_id': 'other'}, 502),
])
def test_cross_project_and_run_records_are_rejected(tmp_path, changes, expected):
    client, project, _ = setup(tmp_path, run_changes=changes)
    assert client.get(BASE + '/transcript', params=dict(project_id=project, run_id='run-1')).status_code == expected


def test_old_owner_explicitly_reports_unavailable_communications(tmp_path):
    client, project, _ = setup(tmp_path, communications=[], run_changes={'communications_available': False})
    result = client.get(BASE + '/transcript', params=dict(project_id=project, run_id='run-1')).json()
    assert result['available'] is False
    assert result['messages'] == []
    assert result['participants'] == []


def test_owner_outage_is_not_success_or_fake_dialogue(tmp_path):
    client, project, _ = setup(tmp_path, owner_status=503)
    assert client.get(BASE + '/health').status_code == 503
    assert client.get(BASE + '/transcript', params=dict(project_id=project, run_id='run-1')).status_code == 503


def test_send_requires_context_and_does_not_claim_unsupported_dispatch(tmp_path):
    client, project, requests = setup(tmp_path)
    body = dict(from_agent='user', to_agent='law_agent', message='review the design')
    unbound = client.post(BASE + '/bus/send', json=body)
    assert unbound.status_code == 400
    assert requests == []
    bound = client.post(BASE + '/bus/send', json={**body, 'metadata': {'project_id': project, 'run_id': 'run-1'}})
    assert bound.status_code == 409
    assert bound.json()['detail']['code'] == 'direct_agent_message_unsupported'
    assert all(request.method == 'GET' for request in requests)


def test_send_rejects_cross_origin_before_owner_request(tmp_path):
    client, _, requests = setup(tmp_path)
    result = client.post(BASE + '/bus/send', json=dict(from_agent='user', to_agent='law_agent', message='review'),
                         headers={'Origin': 'https://other.example'})
    assert result.status_code == 403
    assert requests == []


def test_unavailable_bus_log_is_not_presented_as_empty_history(tmp_path):
    client, project, _ = setup(tmp_path, communications=[], run_changes={'communications_available': False})
    response = client.get(BASE + '/bus/log', params=dict(project_id=project, run_id='run-1'))
    assert response.status_code == 503


def test_malformed_owner_receipt_is_a_contract_error(tmp_path):
    client, project, _ = setup(tmp_path, communications=[{'id': 'invalid'}])
    assert client.get(BASE + '/transcript', params=dict(project_id=project, run_id='run-1')).status_code == 502


@pytest.mark.parametrize('metadata', [{'project_id': [], 'run_id': 'run-1'}, {'project_id': 'x', 'run_id': ' '}])
def test_invalid_send_context_is_not_passed_to_storage(tmp_path, metadata):
    client, _, requests = setup(tmp_path)
    result = client.post(BASE + '/bus/send', json=dict(from_agent='user', to_agent='law_agent', message='review', metadata=metadata))
    assert result.status_code == 400
    assert requests == []
