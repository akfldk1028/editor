import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.modules.land.routers.map import create_land_map_router
from backend.app.modules.land.routers.analysis import create_land_router
from backend.app.modules.land.vworld.map import VworldMapClient

PNG = b'\x89PNG\r\n\x1a\nimage-fixture'


@pytest.fixture(autouse=True)
def isolated_host(monkeypatch):
    from backend.app.modules.platform import host
    async def ensure(*args):
        return {}
    monkeypatch.setattr(host, 'ensure', ensure)


def test_live_scene_requests_do_not_wait_for_host_and_share_lease(monkeypatch):
    import asyncio
    from backend.app.adapters import scene_agent
    from backend.app.modules.land import building_tiles
    from backend.app.modules.platform import host

    async def run():
        release = asyncio.Event()
        calls = []
        async def ensure(*args):
            calls.append(args)
            await release.wait()
            return {}
        monkeypatch.setattr(host, 'ensure', ensure)
        monkeypatch.setattr(scene_agent, 'context_buildings', lambda *a: {'status': 'ok'})
        monkeypatch.setattr(building_tiles, 'latest', lambda prefix: {'regions': []})
        app = FastAPI()
        app.include_router(create_land_map_router())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            try:
                replies = await asyncio.wait_for(asyncio.gather(*[
                    client.get('/api/v1/land/context-buildings?lat=37.7&lon=127.1') for _ in range(8)
                ], client.get('/api/v1/land/context-tiles')), timeout=1)
                assert all(r.status_code == 200 for r in replies)
                assert len(calls) == 1
            finally:
                release.set()
                await asyncio.sleep(0)
    asyncio.run(run())


def test_stopped_scene_is_activated_and_retried(monkeypatch):
    from backend.app.adapters import scene_agent
    from backend.app.modules.platform import host
    ready = False
    async def ensure(*args):
        nonlocal ready
        ready = True
        return {}
    def ask(*args):
        if not ready:
            raise scene_agent.SceneAgentError('unreachable')
        return {'status': 'ok'}
    monkeypatch.setattr(host, 'ensure', ensure)
    monkeypatch.setattr(scene_agent, 'context_buildings', ask)
    app = FastAPI()
    app.include_router(create_land_map_router())
    with TestClient(app) as client:
        assert client.get('/api/v1/land/context-buildings?lat=37.7&lon=127.1').json() == {'status': 'ok'}


def test_terrain_grid_is_reused_but_failures_are_retryable(monkeypatch):
    from backend.app.modules.land import map_terrain
    from backend.app.adapters.elevation import ElevationFetchError
    monkeypatch.setattr(map_terrain, "identity", lambda: ("fixture", 1, 1))
    calls = []
    def sample(points):
        calls.append(points)
        if len(calls) == 1:
            raise ElevationFetchError('temporarily unavailable')
        return [12.34] * len(points), {'name': 'ngii'}
    monkeypatch.setattr(map_terrain, 'ground_heights', sample)
    app = FastAPI()
    app.include_router(create_land_map_router())
    path = '/api/v1/land/terrain-heights?west=127&south=37&east=127.01&north=37.01&size=3'
    with TestClient(app) as client:
        assert client.get(path).status_code == 502
        good = client.get(path)
        assert good.status_code == 200
        assert client.get(path).json() == good.json()
        assert len(calls) == 2


def test_terrain_coalesces_browsers_and_survives_one_disconnect(monkeypatch):
    import asyncio
    import threading
    from backend.app.modules.land import map_terrain
    from backend.app.adapters.elevation import ElevationFetchError
    monkeypatch.setattr(map_terrain, "identity", lambda: ("fixture", 1, 1))
    calls = []
    release = threading.Event()
    def sample(points):
        calls.append(points)
        assert release.wait(2)
        return [12.34] * len(points), {'name': 'ngii'}
    monkeypatch.setattr(map_terrain, 'ground_heights', sample)
    async def run():
        app = FastAPI()
        app.include_router(create_land_map_router())
        path = '/api/v1/land/terrain-heights?west=127&south=37&east=127.01&north=37.01&size=3'
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            first = asyncio.create_task(client.get(path))
            second = asyncio.create_task(client.get(path))
            try:
                for _ in range(100):
                    if calls:
                        break
                    await asyncio.sleep(.001)
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
            finally:
                release.set()
            assert (await second).status_code == 200
            assert len(calls) == 1
    asyncio.run(run())



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


def test_context_buildings_route_says_when_scene_agent_is_down(monkeypatch):
    from backend.app.adapters import scene_agent
    monkeypatch.setenv('SCENE_AGENT_URL', 'http://127.0.0.1:9')
    app = FastAPI()
    app.include_router(create_land_map_router())
    response = TestClient(app).get('/api/v1/land/context-buildings?lat=37.7&lon=127.1')
    assert response.status_code == 502 and 'SceneAgent unreachable' in response.json()['detail']


def test_terrain_heights_reads_local_north_to_south_grid(monkeypatch):
    from backend.app.modules.land import map_terrain
    from backend.app.adapters.elevation import ElevationFetchError
    monkeypatch.setattr(map_terrain, "identity", lambda: ("fixture", 1, 1))
    seen = {}

    def fake(points):
        seen['points'] = points
        return [float(i) for i in range(len(points))], {'name': 'ngii'}

    monkeypatch.setattr(map_terrain, 'ground_heights', fake)
    app = FastAPI()
    app.include_router(create_land_map_router())
    client = TestClient(app)
    got = client.get('/api/v1/land/terrain-heights?west=127.0&south=37.0&east=127.01&north=37.01&size=3').json()
    assert got['size'] == 3 and len(got['heights']) == 9
    assert seen['points'][0] == (37.01, 127.0) and seen['points'][-1] == (37.0, 127.01)   # NW first, SE last
    assert client.get('/api/v1/land/terrain-heights?west=127&south=37&east=128&north=38').status_code == 422

    def down(points):
        raise ElevationFetchError('no DEM here')
    monkeypatch.setattr(map_terrain, 'ground_heights', down)
    assert client.get('/api/v1/land/terrain-heights?west=127.0&south=37.0&east=127.01&north=37.01').status_code == 502


def test_default_ground_contract_and_invalid_detail_are_preserved(monkeypatch):
    from backend.app.modules.land import map_ground
    async def full(*args):
        return {'status': 'ok', 'detail': 'full'}
    monkeypatch.setattr(map_ground.GroundDisplay, 'get', full)
    app = FastAPI()
    app.include_router(create_land_map_router())
    client = TestClient(app)
    route = '/api/v1/land/context-ground?lat=37.7&lon=127.1'
    assert client.get(route).json()['detail'] == 'full'
    assert client.get(route + '&detail=anything').status_code == 422


def test_terrain_revision_is_uncached_metadata_and_missing_source_is_explicit(monkeypatch):
    from backend.app.modules.land import map_terrain
    from backend.app.adapters.elevation import ElevationFetchError
    monkeypatch.setattr(map_terrain, 'metadata', lambda: {'revision': 'new', 'vrt_sha256': 'digest'})
    app = FastAPI()
    app.include_router(create_land_map_router())
    client = TestClient(app)
    response = client.get('/api/v1/land/terrain-revision')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json() == {'revision': 'new', 'vrt_sha256': 'digest'}
    def missing():
        raise ElevationFetchError('Local map terrain is not installed')
    monkeypatch.setattr(map_terrain, 'metadata', missing)
    assert client.get('/api/v1/land/terrain-revision').status_code == 503
