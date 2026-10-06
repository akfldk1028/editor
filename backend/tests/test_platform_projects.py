import pytest
from backend.app.modules.platform.repository import ProjectRepository
from backend.app.modules.platform.projects import ProjectService, BindingConflict
from backend.app.schemas.platform import ProjectCreate


class Sources:
    async def list_projects(self):
        return [{'owner_project_id': 'source-p', 'branch_id': 'main'}]

    async def get_scene(self, scene_id):
        return {'id': scene_id, 'projectId': 'pascal-p', 'version': 2, 'ownerId': None}


def binding(**changes):
    return ProjectCreate(**{'owner_project_id':'source-p', 'branch_id':'main',
        'scene_id':'scene-1', 'scene_revision':2, 'scene_project_id':'pascal-p', **changes})


def test_repository_persists_and_isolates_actor(tmp_path):
    repository = ProjectRepository(tmp_path)
    result = repository.create('local', binding())
    reopened = ProjectRepository(tmp_path)
    assert reopened.get('local', result.project_id) == result
    assert reopened.list('other') == []
    assert reopened.get('other', result.project_id) is None
    assert reopened.create('local', binding()).project_id == result.project_id


def test_repository_requires_absolute_storage():
    with pytest.raises(ValueError):
        ProjectRepository('relative-data')


def test_v1_binding_migrates_its_previously_verified_project_identity(tmp_path):
    import sqlite3
    with sqlite3.connect(tmp_path / 'platform.sqlite') as db:
        db.execute('CREATE TABLE projects (project_id TEXT PRIMARY KEY, actor TEXT, owner_project_id TEXT, branch_id TEXT, scene_id TEXT, scene_revision INTEGER, UNIQUE(actor,owner_project_id,branch_id,scene_id))')
        db.execute("INSERT INTO projects VALUES ('existing','local','old-project','main','scene',2)")
        db.execute('PRAGMA user_version=1')
    value = ProjectRepository(tmp_path).get('local', 'existing')
    assert value.scene_project_id == 'old-project'
    assert value.project_id == 'existing'
    assert ProjectRepository(tmp_path).get('local', 'existing') == value


def test_binding_checks_owner_and_scene(tmp_path):
    import asyncio
    service = ProjectService(ProjectRepository(tmp_path), Sources(), Sources())
    assert asyncio.run(service.create('local', binding())).scene_revision == 2
    for changes in [{'branch_id':'invented'}, {'scene_revision':1}, {'owner_project_id':'other'}]:
        with pytest.raises(BindingConflict):
            asyncio.run(service.create('local', binding(**changes)))
    assert len(service.repository.list('local')) == 1


def test_scene_project_mismatch_does_not_write(tmp_path):
    import asyncio
    class WrongScene(Sources):
        async def get_scene(self, scene_id):
            return {'id':scene_id, 'projectId':'other', 'version':2, 'ownerId':None}
    service = ProjectService(ProjectRepository(tmp_path), Sources(), WrongScene())
    with pytest.raises(BindingConflict):
        asyncio.run(service.create('local', binding()))
    assert service.repository.list('local') == []


def test_browser_identity_is_not_a_binding_field():
    with pytest.raises(ValueError):
        binding(user_id='someone-else')


def test_project_api_persistence_origin_and_unknown_id(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.modules.platform.routers.platform import create_platform_router
    service = ProjectService(ProjectRepository(tmp_path), Sources(), Sources())
    app = FastAPI()
    app.include_router(create_platform_router(project_service=service))
    client = TestClient(app)
    body = binding().model_dump()
    assert client.post('/api/v1/platform/projects', json=body,
        headers={'origin':'https://other.example'}).status_code == 403
    assert client.get('/api/v1/platform/projects').json() == []
    created = client.post('/api/v1/platform/projects', json=body)
    assert created.status_code == 201
    project_id = created.json()['project_id']
    assert client.get('/api/v1/platform/projects/' + project_id).json() == created.json()
    assert client.get('/api/v1/platform/projects/unknown').status_code == 404
    assert client.post('/api/v1/platform/projects', json={**body,'user_id':'other'}).status_code == 422
    assert client.post('/api/v1/platform/projects', json={**body,'scene_revision':1}).status_code == 409


@pytest.mark.parametrize('scene_status,scene_data,expected', [
    (200, {'id':'scene-1','projectId':'pascal-p','version':2,'ownerId':'other-user'}, 409),
    (404, {}, 409), (503, {}, 503),
    (200, {'id':'scene-1','projectId':'pascal-p','version':2}, 502),
    (200, {'id':'scene-1','version':2,'ownerId':None}, 502),
])
def test_actual_scene_adapter_ownership_and_missing_scene(tmp_path, scene_status, scene_data, expected):
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.adapters.platform_scenes import PlatformScenes
    from backend.app.modules.platform.routers.platform import create_platform_router
    scenes = PlatformScenes('http://scene', transport=httpx.MockTransport(
        lambda request: httpx.Response(scene_status,json=scene_data)))
    service = ProjectService(ProjectRepository(tmp_path), Sources(), scenes)
    app = FastAPI()
    app.include_router(create_platform_router(project_service=service, public_origin='http://127.0.0.1:5186'))
    response = TestClient(app).post('/api/v1/platform/projects', json=binding().model_dump(),
        headers={'origin':'http://127.0.0.1:5186'})
    assert response.status_code == expected
    assert service.repository.list('local') == []
