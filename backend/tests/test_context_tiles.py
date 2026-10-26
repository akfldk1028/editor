import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.adapters import scene_agent
from backend.app.modules.land.routers.map import create_land_map_router
from backend.app.modules.platform import host


@pytest.mark.parametrize('status', [200, 404, 500])
def test_agent_adapter_preserves_manifest_contract(monkeypatch, status):
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
    if status == 200:
        assert real(transport=httpx.MockTransport(upstream)) == manifest
    else:
        with pytest.raises(scene_agent.SceneAgentError, match='no tiles'):
            real(transport=httpx.MockTransport(upstream))
    assert calls == [('GET', 'http://scene/scene/tiles/buildings/latest')]


def test_missing_local_tiles_refuse_without_starting_agents(monkeypatch, tmp_path):
    async def ensure(ids):
        raise AssertionError('map reads must not start agents')
    monkeypatch.setattr(host, 'ensure', ensure)
    monkeypatch.setenv('WORLD_BUILDING_TILES_DIR', str(tmp_path))
    app = FastAPI()
    app.include_router(create_land_map_router())
    response = TestClient(app).get('/api/v1/land/context-tiles')
    assert response.status_code == 503
    assert 'unavailable' in response.json()['detail']
