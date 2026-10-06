import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.modules.platform.routers.platform import create_platform_router
from backend.app.adapters.orchestrator import OrchestratorClient


@pytest.mark.parametrize('status,body,expected', [
    (200, [], 200), (503, {}, 503), (200, {'wrong': []}, 502),
    (200, [{'agent_id': 'bad'}], 502),
])
def test_agents_owner_contract(status, body, expected):
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body))
    app = FastAPI()
    app.include_router(create_platform_router(OrchestratorClient('http://owner', transport=transport)))
    response = TestClient(app).get('/api/v1/platform/agents')
    assert response.status_code == expected


def test_unconfigured_owner_is_unavailable():
    app = FastAPI()
    app.include_router(create_platform_router(OrchestratorClient(None)))
    assert TestClient(app).get('/api/v1/platform/agents').status_code == 503


def test_owner_timeout_is_not_empty_success():
    def fail(request):
        raise httpx.ReadTimeout('private internal details')
    app = FastAPI()
    app.include_router(create_platform_router(OrchestratorClient('http://owner', transport=httpx.MockTransport(fail))))
    response = TestClient(app).get('/api/v1/platform/agents')
    assert response.status_code == 503
    assert 'private internal' not in response.text
