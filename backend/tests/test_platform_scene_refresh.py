from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.modules.platform.routers.platform import create_platform_router
from backend.app.modules.platform.projects import ProjectService
from backend.app.modules.platform.repository import ProjectRepository
from backend.app.schemas.platform import ProjectCreate


class Sources:
    version = 3
    project = 'scene-project'
    actor = None

    async def list_projects(self):
        return [{'owner_project_id': 'owner', 'branch_id': 'main'}]

    async def get_scene(self, scene_id):
        return {'id': scene_id, 'projectId': self.project, 'version': self.version, 'ownerId': self.actor}


def setup(tmp_path):
    repository = ProjectRepository(tmp_path)
    binding = repository.create('local', ProjectCreate(owner_project_id='owner', branch_id='main',
        scene_id='scene', scene_project_id='scene-project', scene_revision=2))
    sources = Sources()
    app = FastAPI()
    app.include_router(create_platform_router(project_service=ProjectService(repository, sources, sources)))
    return TestClient(app), repository, binding, sources


def test_refresh_is_explicit_compare_and_swap_and_preserves_identity(tmp_path):
    client, repository, binding, sources = setup(tmp_path)
    path = f'/api/v1/platform/projects/{binding.project_id}/scene-revision'
    body = {'expected_scene_revision': 2, 'scene_revision': 3}
    assert client.post(path, json=body, headers={'origin': 'https://other.example'}).status_code == 403
    assert client.post(path, json={**body, 'scene_revision': 4}).status_code == 409
    assert repository.get('local', binding.project_id) == binding
    refreshed = client.post(path, json=body)
    assert refreshed.status_code == 200
    assert refreshed.json() == {**binding.model_dump(), 'scene_revision': 3}
    assert client.post(path, json=body).status_code == 409
    assert client.post(path, json={'expected_scene_revision': 3, 'scene_revision': 2}).status_code == 422
    assert repository.get('other', binding.project_id) is None


def test_refresh_rechecks_scene_identity_ownership_and_unknown_binding(tmp_path):
    client, repository, binding, sources = setup(tmp_path)
    path = f'/api/v1/platform/projects/{binding.project_id}/scene-revision'
    body = {'expected_scene_revision': 2, 'scene_revision': 3}
    sources.project = 'another-project'
    assert client.post(path, json=body).status_code == 409
    sources.project = 'scene-project'
    sources.actor = 'another-actor'
    assert client.post(path, json=body).status_code == 409
    assert client.post('/api/v1/platform/projects/missing/scene-revision', json=body).status_code == 404
    assert repository.get('local', binding.project_id) == binding
