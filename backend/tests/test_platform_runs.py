import asyncio
import pytest
from backend.app.modules.platform.runs import RunService
from backend.app.modules.platform.projects import ProjectService, BindingConflict
from backend.app.modules.platform.repository import ProjectRepository
from backend.app.schemas.platform import ProjectCreate, RunCreate


class Owner:
    def __init__(self): self.requests = {}
    async def list_projects(self): return [{'owner_project_id':'p','branch_id':'main'}]
    async def get_scene(self, scene_id): return {'id':scene_id,'projectId':None,'version':1,'ownerId':None}
    async def context(self, project, branch): return {}
    async def list_runs(self, project, branch, prefix):
        return [await self.submit_run(body) for key,body in list(self.requests.items()) if key.startswith(prefix)]
    async def submit_run(self, body):
        key = body['request_id']
        if key in self.requests and self.requests[key] != body: raise BindingConflict('changed')
        self.requests[key] = body
        return {'run_id':'r1','owner_project_id':'p','branch_id':'main','request_id':key,
            'goal':'health','status':'queued','receipt_task_ids':[], 'pending_input':False}


def setup(tmp_path):
    owner = Owner()
    projects = ProjectService(ProjectRepository(tmp_path), owner, owner)
    binding = asyncio.run(projects.create('local', ProjectCreate(owner_project_id='p',branch_id='main',scene_id='s',scene_revision=1)))
    return owner, projects, binding, RunService(projects, owner)


def test_submission_binds_project_and_preserves_retry_identity(tmp_path):
    owner, projects, binding, runs = setup(tmp_path)
    request = RunCreate(request={'goal':'health'}, scene_revision=1,source_versions={})
    first = asyncio.run(runs.submit('local', binding.project_id,'key',request))
    second = asyncio.run(runs.submit('local', binding.project_id,'key',request))
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
    app.include_router(create_platform_router(owner,project_service=projects))
    client=TestClient(app)
    path='/api/v1/platform/projects/'+binding.project_id+'/runs'
    payload={'request':{'goal':'health'},'scene_revision':1,'source_versions':{}}
    assert client.post(path,json=payload).status_code==422
    assert client.post(path,json=payload,headers={'Idempotency-Key':'k','Origin':'https://other.example'}).status_code==403
    assert owner.requests=={}
    first=client.post(path,json=payload,headers={'Idempotency-Key':'k'})
    assert first.status_code==202
    assert client.post(path,json=payload,headers={'Idempotency-Key':'k'}).json()==first.json()


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
    assert asyncio.run(runs.submit('local',binding.project_id,'key',body)) == first
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
