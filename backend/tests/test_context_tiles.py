import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.adapters import scene_agent
from backend.app.modules.land.routers.map import create_land_map_router
from backend.app.modules.platform import host


@pytest.mark.parametrize('status', [200, 404, 500])
def test_tiles_manifest_wakes_scene_and_preserves_contract(monkeypatch, status):
    calls = []
    manifest = {'version': '20261009-12345678', 'href': 'http://scene/buildings.pmtiles',
                'path': '/buildings.pmtiles', 'zoom': [13, 16], 'layer': 'buildings'}

    async def ensure(ids):
        calls.append(ids)
        return {'up': ids, 'failed': []}

    def upstream(request):
        calls.append((request.method, str(request.url)))
        return httpx.Response(status, json=manifest if status == 200 else {'detail': 'no tiles'})

    monkeypatch.setattr(host, 'ensure', ensure)
    monkeypatch.setenv('SCENE_AGENT_URL', 'http://scene')
    real = scene_agent.context_tiles
    monkeypatch.setattr(scene_agent, 'context_tiles', lambda: real(transport=httpx.MockTransport(upstream)))
    app = FastAPI()
    app.include_router(create_land_map_router())
    response = TestClient(app).get('/api/v1/land/context-tiles')
    assert calls[0] == ['scene']
    assert calls[1] == ('GET', 'http://scene/scene/tiles/buildings/latest')
    if status == 200:
        assert response.status_code == 200
        assert response.json() == manifest
    else:
        assert response.status_code == 502
        assert 'no tiles' in response.json()['detail']


def test_tiles_host_failure_is_502(monkeypatch):
    async def ensure(ids):
        raise host.HostUnavailable('host offline')
    monkeypatch.setattr(host, 'ensure', ensure)
    app = FastAPI()
    app.include_router(create_land_map_router())
    response = TestClient(app).get('/api/v1/land/context-tiles')
    assert response.status_code == 502
    assert 'host offline' in response.json()['detail']
