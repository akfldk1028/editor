import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.modules.land.routers.map import create_land_map_router
from backend.app.modules.land.routers.analysis import create_land_router
from backend.app.modules.land.vworld.map import VworldMapClient

PNG = b'\x89PNG\r\n\x1a\nimage-fixture'


def test_map_config_exposes_only_explicit_browser_key_and_is_not_cached(monkeypatch):
    monkeypatch.setenv('VWORLD_API_KEY', 'server-only')
    monkeypatch.delenv('VWORLD_BROWSER_API_KEY', raising=False)
    app = FastAPI()
    app.include_router(create_land_map_router())
    client = TestClient(app)
    missing = client.get('/api/v1/land/map-config')
    assert missing.status_code == 503
    assert 'server-only' not in missing.text
    monkeypatch.setenv('VWORLD_BROWSER_API_KEY', 'browser-sdk-key')
    response = client.get('/api/v1/land/map-config')
    assert response.json() == {'api_key': 'browser-sdk-key'}
    assert response.headers['cache-control'] == 'no-store'


def test_map_routes_are_mounted_once_under_the_native_land_prefix(monkeypatch):
    monkeypatch.delenv('VWORLD_API_KEY', raising=False)
    app = FastAPI()
    app.include_router(create_land_router())
    client = TestClient(app)
    assert client.get('/api/v1/land/tiles/1/0/0.png').status_code == 503
    assert client.get('/api/v1/land/wms?BBOX=1,2,3,4').status_code == 503
    assert client.get('/api/v1/land/api/v1/land/tiles/1/0/0.png').status_code == 404

def test_map_tiles_and_wms_use_fixed_provider_with_server_key():
    seen = []
    def upstream(request):
        seen.append(request)
        return httpx.Response(200, content=PNG, headers={'Content-Type': 'image/png'})
    app = FastAPI()
    app.include_router(create_land_map_router(VworldMapClient('test-private-key', transport=httpx.MockTransport(upstream))))
    client = TestClient(app)
    tile = client.get('/api/v1/land/tiles/17/51101/111801.png')
    assert tile.status_code == 200 and tile.content == PNG
    assert 'test-private-key' in str(seen[0].url)
    assert 'test-private-key' not in str(tile.headers)
    wms = client.get('/api/v1/land/wms', params={'BBOX': '1,2,3,4', 'WIDTH': 256, 'HEIGHT': 256, 'LAYERS': 'lp_pa_cbnd_bonbun,lp_pa_cbnd_bubun', 'CRS': 'EPSG:3857'})
    assert wms.status_code == 200 and wms.content == PNG
    assert seen[1].url.params['key'] == 'test-private-key'

@pytest.mark.parametrize('path', ['/tiles/17/999999/0.png', '/tiles/25/0/0.png', '/wms?BBOX=nan,2,3,4', '/wms?BBOX=1,2,3,4&WIDTH=999999', '/wms?BBOX=1,2,3,4&LAYERS=arbitrary'])
def test_invalid_map_requests_do_not_reach_provider(path):
    def unexpected(request):
        pytest.fail('invalid request reached provider')
    app = FastAPI()
    app.include_router(create_land_map_router(VworldMapClient('key', transport=httpx.MockTransport(unexpected))))
    assert TestClient(app).get('/api/v1/land' + path).status_code == 422

def test_missing_key_and_provider_errors_are_explicit_and_redacted():
    app = FastAPI()
    app.include_router(create_land_map_router(VworldMapClient('')))
    assert TestClient(app).get('/api/v1/land/tiles/1/0/0.png').status_code == 503
    app = FastAPI()
    app.include_router(create_land_map_router(VworldMapClient('private-key', transport=httpx.MockTransport(lambda request: httpx.Response(200, text='<error>private-key</error>')))))
    response = TestClient(app).get('/api/v1/land/tiles/1/0/0.png')
    assert response.status_code == 502
    assert 'private-key' not in response.text


def test_context_buildings_route_asks_scene_agent_and_passes_its_reply(monkeypatch):
    from backend.app.adapters import scene_agent
    seen = []

    def upstream(request):
        seen.append(request)
        return httpx.Response(200, json={'status': 'ok', 'features': {'type': 'FeatureCollection', 'features': []},
                                         'counts': {'measured': 0, 'estimated': 0, 'unknown': 0}})

    real = scene_agent.context_buildings
    monkeypatch.setattr(scene_agent, 'context_buildings',
                        lambda lat, lon, r: real(lat, lon, r, base_url='http://scene', transport=httpx.MockTransport(upstream)))
    app = FastAPI()
    app.include_router(create_land_map_router())
    client = TestClient(app)
    ok = client.get('/api/v1/land/context-buildings?lat=37.7&lon=127.1&radius_m=200')
    assert ok.status_code == 200 and ok.json()['status'] == 'ok'
    assert str(seen[0].url) == 'http://scene/scene/context-buildings'
    assert client.get('/api/v1/land/context-buildings?lat=10&lon=127').status_code == 422
    monkeypatch.setattr(scene_agent, 'context_ground',
                        lambda lat, lon, r: real.__globals__['_ask']('/scene/context-ground', lat, lon, r, base_url='http://scene', transport=httpx.MockTransport(upstream)))
    assert client.get('/api/v1/land/context-ground?lat=37.7&lon=127.1').json()['status'] == 'ok'
    assert str(seen[-1].url) == 'http://scene/scene/context-ground'


def test_context_buildings_route_says_when_scene_agent_is_down(monkeypatch):
    from backend.app.adapters import scene_agent
    monkeypatch.setenv('SCENE_AGENT_URL', 'http://127.0.0.1:9')
    app = FastAPI()
    app.include_router(create_land_map_router())
    response = TestClient(app).get('/api/v1/land/context-buildings?lat=37.7&lon=127.1')
    assert response.status_code == 502 and 'SceneAgent unreachable' in response.json()['detail']
