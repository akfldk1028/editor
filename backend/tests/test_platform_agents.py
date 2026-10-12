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


def test_agents_carry_their_own_card_words():
    """The Orchestrator's catalog gives the ids; each agent's live A2A card adds its description and skills by name."""
    catalog = [{'agent_id': 'site_context', 'label': 'SiteContextAgent', 'capabilities': ['site_resolve', 'site_health'],
                'implementation_status': 'unknown', 'connection_status': 'available', 'checked_at': None, 'evidence_ref': None},
               {'agent_id': 'structure', 'label': 'structure', 'capabilities': [], 'implementation_status': 'unknown',
                'connection_status': 'not_declared', 'checked_at': None, 'evidence_ref': None}]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=catalog))

    async def roster(agents):
        assert agents == ['site_context', 'structure']
        return {'site_context': {'name': 'SiteContextAgent', 'description': 'Establishes the facts a parcel has.',
                                 'skills': [{'id': 'site_resolve', 'name': 'resolve', 'description': 'Resolve the site facts for a parcel.'}]},
                'structure': None}
    app = FastAPI()
    app.include_router(create_platform_router(OrchestratorClient('http://owner', transport=transport), roster=roster))
    rows = TestClient(app).get('/api/v1/platform/agents').json()
    assert rows[0]['description'] == 'Establishes the facts a parcel has.'
    assert rows[0]['skills'] == [{'id': 'site_resolve', 'name': 'resolve', 'description': 'Resolve the site facts for a parcel.'}]
    assert rows[1]['description'] is None and rows[1]['skills'] is None
