from copy import deepcopy
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes_platform import create_platform_router
from backend.app.modules.platform.projects import ProjectService
from backend.app.modules.platform.repository import ProjectRepository
from backend.app.schemas.platform import ProjectCreate


class Sources:
    version = 2
    owner = 'local'

    async def list_projects(self):
        return [{'owner_project_id': 'native-owner', 'branch_id': 'main'}]

    async def get_scene(self, identifier):
        return {'id': identifier, 'projectId': 'native-scene-project', 'version': self.version, 'ownerId': self.owner}


@pytest.fixture
def api(tmp_path):
    from backend.app.modules.design.native_service import NativeDesignService
    sources = Sources()
    projects = ProjectRepository(tmp_path / 'projects')
    body = ProjectCreate(owner_project_id='native-owner', branch_id='main', scene_id='scene',
                         scene_project_id='native-scene-project', scene_revision=2)
    project = projects.create('local', body)
    foreign = projects.create('other', body)
    app = FastAPI()
    app.include_router(create_platform_router(project_service=ProjectService(projects, sources, sources),
        native_design_service=NativeDesignService(tmp_path / 'design')))
    payload = {'site_polygon': {'type': 'Polygon', 'coordinates': [[[127, 37.5], [127.0005, 37.5],
        [127.0005, 37.5005], [127, 37.5005], [127, 37.5]]]},
        'job_spec': {'options': {'algorithm': 'additive', 'building_type': '업무시설'}}}
    return TestClient(app), f'/api/v1/platform/projects/{project.project_id}/design/native-jobs', sources, payload, foreign.project_id


def test_native_creation_persists_exact_input_and_never_starts_execution(api):
    client, url, _, payload, _ = api
    body = {'request_id': 'request-one', 'scene_revision': 2, 'payload': payload}
    assert client.get(url).json()['items'] == []
    response = client.post(url, json=body)
    assert response.status_code == 201, response.text
    job = response.json()
    assert job['status'] == 'created' and job['execution_supported'] is False
    assert job['input'] == payload and job['prepared']['site_polygon'] == payload['site_polygon']
    assert client.post(url, json=body).json()['job_id'] == job['job_id']
    assert len(client.get(url).json()['items']) == 1
    assert client.get(url + '/' + job['job_id']).json() == job
    changed = deepcopy(body); changed['payload']['address'] = 'changed'
    assert client.post(url, json=changed).status_code == 409


def test_native_mutation_requires_live_binding_and_origin(api):
    client, url, sources, payload, _ = api
    body = {'request_id': 'request-one', 'scene_revision': 2, 'payload': payload}
    assert client.post(url, json=body, headers={'origin': 'https://other.invalid'}).status_code == 403
    sources.version = 3
    assert client.post(url, json=body).status_code == 409
    sources.version = 2; sources.owner = 'other'
    assert client.post(url, json=body).status_code == 409
    sources.owner = 'local'
    assert client.post(url, json={**body, 'scene_revision': True}).status_code == 422
    assert client.get(url).json()['items'] == []


def test_native_scope_and_validation_errors_are_explicit(api):
    client, url, _, payload, foreign = api
    body = {'request_id': 'request-one', 'scene_revision': 2, 'payload': payload}
    invalid = deepcopy(body); invalid['payload']['job_spec']['options']['algorithm'] = 'typo'
    response = client.post(url, json=invalid)
    assert response.status_code == 422 and response.json()['detail']['code']
    assert client.get(url + '?limit=101').status_code == 422
    assert client.get(url + '/bad-id').status_code == 422
    assert client.get(f'/api/v1/platform/projects/{foreign}/design/native-jobs').status_code == 404
    job = client.post(url, json=body).json()
    assert client.get(f'/api/v1/platform/projects/{foreign}/design/native-jobs/{job["job_id"]}').status_code == 404
    assert client.get(url + '/' + 'f' * 32).status_code == 404


def test_native_nonfinite_json_is_validation_error_without_creation(api):
    client, url, _, payload, _ = api
    payload['address'] = float('nan')
    response = client.post(url, content=json.dumps({'request_id': 'invalid-json',
        'scene_revision': 2, 'payload': payload}), headers={'content-type': 'application/json'})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'invalid_input'
    assert client.get(url).json()['items'] == []
