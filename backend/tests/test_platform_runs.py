import asyncio
import pytest
from backend.app.core.tracing import JsonlTraceRecorder
from backend.app.modules.platform.runs import RunService
from backend.app.modules.platform.projects import ProjectService, BindingConflict
from backend.app.modules.platform.repository import ProjectRepository
from backend.app.schemas.platform import ProjectCreate, RunCreate


class Owner:
    def __init__(self): self.requests = {}
    async def list_projects(self): return [{'owner_project_id':'p','branch_id':'main'}]
    async def get_scene(self, scene_id): return {'id':scene_id,'projectId':None,'version':1,'ownerId':None}
    async def context(self, project, branch): return {}
    async def list_runs(self, project, branch, prefix, trace=None):
        return [await self.submit_run(body) for key,body in list(self.requests.items()) if key.startswith(prefix)]
    async def submit_run(self, body, trace=None):
        key = body['request_id']
        if key in self.requests and self.requests[key] != body: raise BindingConflict('changed')
        self.requests[key] = body
        return {'run_id':'r1','owner_project_id':'p','branch_id':'main','request_id':key,
            'goal':'health','status':'queued','receipt_task_ids':[], 'pending_input':False}


def setup(tmp_path):
    owner = Owner()
    projects = ProjectService(ProjectRepository(tmp_path), owner, owner)
    binding = asyncio.run(projects.create('local', ProjectCreate(owner_project_id='p',branch_id='main',scene_id='s',scene_revision=1)))
    return owner, projects, binding, RunService(projects, owner, JsonlTraceRecorder(tmp_path / 'trace'))


def test_submission_binds_project_and_preserves_retry_identity(tmp_path):
    owner, projects, binding, runs = setup(tmp_path)
    request = RunCreate(request={'goal':'health'}, scene_revision=1,source_versions={})
    first = asyncio.run(runs.submit('local', binding.project_id,'key',request))
    second = asyncio.run(runs.submit('local', binding.project_id,'key',request))
    # Each submission is its own trace; the run underneath is the same.
    assert first.pop('trace_id') != second.pop('trace_id')
    assert first == second
    assert len(owner.requests) == 1
    assert next(iter(owner.requests)).startswith('editor:' + binding.project_id + ':')
    with pytest.raises(BindingConflict):
        asyncio.run(runs.submit('local',binding.project_id,'key',request.model_copy(update={'scene_revision':0})))
    with pytest.raises(LookupError):
        asyncio.run(runs.submit('other',binding.project_id,'key',request))


def test_run_api_requires_key_and_rejects_cross_origin(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.modules.platform.routers.platform import create_platform_router
    owner, projects, binding, runs = setup(tmp_path)
    app = FastAPI()
    app.include_router(create_platform_router(owner,project_service=projects,trace_recorder=runs.recorder))
    client=TestClient(app)
    path='/api/v1/platform/projects/'+binding.project_id+'/runs'
    payload={'request':{'goal':'health'},'scene_revision':1,'source_versions':{}}
    assert client.post(path,json=payload).status_code==422
    assert client.post(path,json=payload,headers={'Idempotency-Key':'k','Origin':'https://other.example'}).status_code==403
    assert owner.requests=={}
    first=client.post(path,json=payload,headers={'Idempotency-Key':'k'})
    assert first.status_code==202
    second=client.post(path,json=payload,headers={'Idempotency-Key':'k'}).json()
    assert {**second,'trace_id':None}=={**first.json(),'trace_id':None}


def test_owner_adapter_invalid_json_and_missing_run():
    import httpx
    from backend.app.adapters.orchestrator import OrchestratorClient, OwnerContractError
    client = OrchestratorClient('http://owner', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text='not json')))
    with pytest.raises(OwnerContractError):
        asyncio.run(client.context('p', 'main'))
    client = OrchestratorClient('http://owner', transport=httpx.MockTransport(
        lambda request: httpx.Response(404)))
    with pytest.raises(LookupError):
        asyncio.run(client.get_run('missing', 'p', 'main'))


def test_accepted_retry_survives_scene_outage_but_new_request_does_not(tmp_path):
    from backend.app.adapters.orchestrator import OwnerUnavailable
    owner, projects, binding, runs = setup(tmp_path)
    body = RunCreate(request={'goal':'health'},scene_revision=1,source_versions={})
    first = asyncio.run(runs.submit('local',binding.project_id,'key',body))
    async def unavailable(scene_id): raise OwnerUnavailable()
    owner.get_scene = unavailable
    assert {**asyncio.run(runs.submit('local',binding.project_id,'key',body)),'trace_id':None} == {**first,'trace_id':None}
    with pytest.raises(OwnerUnavailable):
        asyncio.run(runs.submit('local',binding.project_id,'new-key',body))
    with pytest.raises(BindingConflict):
        asyncio.run(runs.submit('local',binding.project_id,'key',body.model_copy(update={'source_versions':{'x':1}})))


def test_owner_adapter_rejects_run_from_other_project():
    import httpx
    from backend.app.adapters.orchestrator import OrchestratorClient, OwnerContractError
    value = {'run_id':'r','owner_project_id':'other','branch_id':'main','request_id':'k',
        'goal':'health','status':'queued','receipt_task_ids':[], 'pending_input':False}
    client = OrchestratorClient('http://owner', transport=httpx.MockTransport(
        lambda request: httpx.Response(200,json=value)))
    with pytest.raises(OwnerContractError):
        asyncio.run(client.get_run('r','p','main'))


@pytest.mark.parametrize('changes', [
    {'request':{'goal':'limits'}}, {'request':{'goal':'health','unexpected':1}},
    {'source_versions':{'mass':-1}}, {'source_versions':{'mass':True}},
])
def test_run_contract_rejects_unsupported_work_and_invalid_versions(changes):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RunCreate(**{'request':{'goal':'health'},'scene_revision':1,'source_versions':{},**changes})


def test_run_contract_accepts_the_doors_redacted_flag_on_communications():
    """2026-10-09: the Orchestrator door marks rows whose texts had secret fields omitted; older doors send no flag."""
    from backend.app.adapters.orchestrator import OrchestratorClient

    row = {'id': '1', 'task_id': 'site_resolve', 'tool': 'site_resolve', 'agent': 'site_context', 'state': 'running',
           'request_text': '{}', 'response_text': None, 'transport': 'a2a', 'truncated': False, 'redacted': True}
    run = {'run_id': 'r', 'owner_project_id': 'p', 'branch_id': 'b', 'request_id': 'editor:x:y', 'goal': 'limits', 'status': 'running',
           'receipt_task_ids': ['site_resolve'], 'pending_input': False, 'pending_fields': [], 'pending_note': None,
           'communications': [row], 'communications_available': True, 'communications_truncated': False}
    parsed = OrchestratorClient.parse_run(run)
    assert parsed['communications'][0]['redacted'] is True
    assert OrchestratorClient.parse_run({**run, 'communications': [{k: v for k, v in row.items() if k != 'redacted'}]})['communications'][0]['redacted'] is False


QUESTION = {'kind': 'request_input', 'code': 'district_lot_required', 'fields': ['district_lot'], 'pnu': '4115011300106840001',
            'candidates': {'status': 'parcel_not_tied_to_a_lot_choose_one', 'lots': [
                {'lot': '공공1', 'bcr_pct_max': [{'value': 60, 'quote': '건폐율 ∙ 60퍼센트 이하', 'article': '제23조'}]}]}}


def test_a_waiting_runs_question_reaches_the_editor_whole_and_the_answer_goes_back_to_the_owner(tmp_path):
    from backend.app.adapters.orchestrator import OrchestratorClient
    from backend.app.modules.platform.run_results.parse import parse_run_results
    from backend.app.schemas.platform import RunResume
    owner, projects, binding, runs = setup(tmp_path)
    request_id = f'editor:{binding.project_id}:k'
    waiting = OrchestratorClient.parse_run({'run_id': 'r1', 'owner_project_id': 'p', 'branch_id': 'main', 'request_id': request_id,
        'goal': 'limits', 'status': 'waiting_input', 'receipt_task_ids': [], 'pending_input': True,
        'pending_fields': ['district_lot'], 'pending_note': 'choose a lot', 'pending_request': QUESTION})
    assert (waiting['pending_fields'], waiting['pending_note'], waiting['pending_request']) == (['district_lot'], 'choose a lot', QUESTION)
    assert parse_run_results(waiting)['pending_request'] == QUESTION and parse_run_results(waiting)['pending_note'] == 'choose a lot'
    answered = []

    async def get_run(run_id, project, branch):
        return waiting

    async def resume_run(run_id, project, branch, answer):
        answered.append((run_id, project, branch, answer))
        return {**waiting, 'status': 'queued', 'pending_input': False, 'pending_request': None}
    owner.get_run, owner.resume_run = get_run, resume_run
    resumed = asyncio.run(runs.resume('local', binding.project_id, 'r1', RunResume(input={'district_lot': '공공1'}).input))
    assert answered == [('r1', 'p', 'main', {'district_lot': '공공1'})] and resumed['status'] == 'queued'
    # A run of another project is not answered from here.
    async def foreign(run_id, project, branch):
        return {**waiting, 'request_id': 'editor:other:k'}
    owner.get_run = foreign
    with pytest.raises(LookupError):
        asyncio.run(runs.resume('local', binding.project_id, 'r1', {'district_lot': '공공1'}))


def test_a_run_started_from_a_conversation_is_linked_to_it_in_the_ledger(tmp_path):
    from backend.app.modules.ledger import Ledger
    owner, projects, binding, _ = setup(tmp_path)
    ledger = Ledger(tmp_path / 'ledger')
    runs = RunService(projects, owner, JsonlTraceRecorder(tmp_path / 'trace'), ledger)
    run = asyncio.run(runs.submit('local', binding.project_id, 'key',
                                  RunCreate(request={'goal': 'health'}, scene_revision=1, source_versions={}, conversation_id='conv-1')))
    assert ledger.store.runs_of('conv-1') == [run['run_id']]


def test_a_refused_answer_says_why_through_the_door(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.adapters.orchestrator import OwnerRejected
    from backend.app.modules.platform.routers.platform import create_platform_router
    owner, projects, binding, runs = setup(tmp_path)

    async def get_run(run_id, project, branch):
        return {'run_id': run_id, 'request_id': f'editor:{binding.project_id}:k'}

    async def resume_run(run_id, project, branch, answer):
        raise OwnerRejected('후보로 나온 획지 중에서 골라 주세요.', 'district_lot must be one of the lots Law offered: A11, A12')
    owner.get_run, owner.resume_run = get_run, resume_run
    app = FastAPI()
    app.include_router(create_platform_router(owner, project_service=projects, trace_recorder=runs.recorder))
    answer = TestClient(app).post(f'/api/v1/platform/projects/{binding.project_id}/runs/r1/resume', json={'input': {'district_lot': 'Z9'}})
    assert answer.status_code == 409 and answer.json()['detail'] == 'answer_rejected: 후보로 나온 획지 중에서 골라 주세요.'
