import asyncio
import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.adapters.orchestrator import OrchestratorClient, OwnerContractError
from backend.app.api.routes_platform import create_platform_router
from backend.app.modules.platform.projects import ProjectService
from backend.app.modules.platform.repository import ProjectRepository
from backend.app.schemas.platform import ProjectCreate


def value(binding='binding'):
    return {'run_id': 'run', 'request_id': f'editor:{binding}:key', 'owner_project_id': 'owner', 'branch_id': 'main',
        'source_versions': {'program.spaces': 3}, 'reviews': [],
        'request': {'goal': 'specialist_review', 'specialist_reviews': [{'agent': 'domain_expert', 'tool': 'domain_review',
            'source_versions': {'program.spaces': 3}, 'args': {'request': {'sources': [{'content': 'x' * 12000}]}}}]}}


def test_followup_adapter_rejects_identity_and_version_mismatch():
    for change in [{'owner_project_id': 'foreign'}, {'run_id': 'other'}, {'source_versions': {'program.spaces': 4}}, {'reviews': [{'needs': 'bad'}]}]:
        client = OrchestratorClient('http://owner', transport=httpx.MockTransport(lambda request: httpx.Response(200, json={**value(), **change})))
        with pytest.raises(OwnerContractError): asyncio.run(client.review_request('run', 'owner', 'main'))


def test_full_request_route_enforces_native_binding_and_keeps_long_sources(tmp_path):
    repo = ProjectRepository(tmp_path)
    binding = repo.create('local', ProjectCreate(owner_project_id='owner', branch_id='main', scene_id='scene', scene_revision=1))
    response = value(binding.project_id)
    owner = OrchestratorClient('http://owner', transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response)))
    app = FastAPI()
    app.include_router(create_platform_router(owner, project_service=ProjectService(repo, owner, None)))
    client = TestClient(app)
    url = f'/api/v1/platform/runs/run/request?project_id={binding.project_id}'
    assert client.get(url).json()['request'] == response['request']
    response['request_id'] = 'editor:foreign:key'
    assert client.get(url).status_code == 404
