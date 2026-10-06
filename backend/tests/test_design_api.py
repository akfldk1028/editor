import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.modules.platform.routers.platform import create_platform_router
from backend.app.modules.platform.projects import ProjectService
from backend.app.modules.platform.repository import ProjectRepository
from backend.app.schemas.platform import ProjectCreate


class Sources:
    version = 2
    owner = 'local'
    async def list_projects(self):
        return [{'owner_project_id':'owner', 'branch_id':'main'}]
    async def get_scene(self, identifier):
        return {'id':identifier, 'projectId':'scene-project', 'version':self.version, 'ownerId':self.owner}


class Archive:
    def __init__(self):
        self.attached = []
        self.selection = None
    def list_jobs(self, **kwargs):
        return [{'source_id':'source', 'job_id':'job', 'execution_state':'archived', 'source_status':'running'}]
    def project_jobs(self, actor, project_id):
        return self.attached
    def attach_project(self, actor, project_id, scene_id, revision, source_id, job_id):
        value = dict(source_id=source_id, job_id=job_id, scene_id=scene_id, scene_revision=revision)
        self.attached.append(value)
        return value
    def select_result(self, actor, project_id, source_id, job_id, result_pk):
        if not any(j['job_id']==job_id and j['source_id']==source_id for j in self.attached):
            raise LookupError()
        self.selection = dict(source_id=source_id, job_id=job_id, result_pk=result_pk)
        return self.selection
    def selected_result(self, actor, project_id):
        return self.selection


@pytest.fixture
def api(tmp_path):
    sources = Sources()
    projects = ProjectRepository(tmp_path/'projects')
    project = projects.create('local', ProjectCreate(owner_project_id='owner', branch_id='main',
        scene_id='scene', scene_project_id='scene-project', scene_revision=2))
    archive = Archive()
    app = FastAPI()
    app.include_router(create_platform_router(project_service=ProjectService(projects,sources,sources),
        design_repository=archive))
    return TestClient(app), f'/api/v1/platform/projects/{project.project_id}/design', sources, archive


def test_attach_rechecks_live_scene_before_writing(api):
    client,url,sources,archive = api
    body={'source_id':'source','job_id':'job','scene_revision':2}
    assert client.post(url+'/jobs',json=body,headers={'origin':'https://other.invalid'}).status_code == 403
    sources.version=3
    assert client.post(url+'/jobs',json=body).status_code == 409
    sources.version=2; sources.owner='other'
    assert client.post(url+'/jobs',json=body).status_code == 409
    assert archive.attached == []
    sources.owner='local'
    assert client.post(url+'/jobs',json=body).status_code == 201
    assert client.get(url+'/jobs').json()['items'][0]['scene_revision'] == 2


def test_selection_requires_attachment_and_valid_revision(api):
    client,url,sources,archive = api
    body={'source_id':'source','job_id':'job','scene_revision':2,'result_pk':5}
    assert client.get(url+'/selection').json() is None
    assert client.post(url+'/selection',json=body).status_code == 404
    assert client.post(url+'/jobs',json={k:v for k,v in body.items() if k!='result_pk'}).status_code == 201
    assert client.post(url+'/selection',json=dict(body,scene_revision=1)).status_code == 409
    assert client.post(url+'/selection',json=dict(body,result_pk=True)).status_code == 422
    assert client.post(url+'/selection',json=body).json()['result_pk'] == 5
    assert client.get(url+'/selection').json()['result_pk'] == 5


def test_archive_requires_existing_project_and_bounds_pagination(api):
    client,url,_,archive = api
    assert client.get(url+'/archive/jobs?limit=101').status_code == 422
    assert client.get('/api/v1/platform/projects/missing/design/archive/jobs').status_code == 404
    value=client.get(url+'/archive/jobs').json()['items'][0]
    assert value['execution_state'] == 'archived'
    assert value['source_status'] == 'running'
    assert client.get(url+'/jobs/source/job/results').status_code == 404
