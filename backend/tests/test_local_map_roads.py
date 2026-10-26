import asyncio
import json
import shutil
from pathlib import Path

import geopandas as gpd
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import LineString

from backend.app.modules.land.routers.map import create_land_map_router


@pytest.fixture
def source(tmp_path, monkeypatch):
    root = tmp_path / 'data'
    (root / 'index').mkdir(parents=True)
    jobs = Path(__file__).resolve().parents[2] / 'infra/data/source_jobs'
    monkeypatch.syspath_prepend(str(jobs))
    import source_job_paths
    monkeypatch.setattr(source_job_paths, 'SOURCE_DATA_ROOT', root)
    monkeypatch.setattr(source_job_paths, 'INDEX_STATE_ROOT', root / 'index')
    monkeypatch.setattr(source_job_paths, 'DATA_ROOT', tmp_path)
    shutil.copyfile(jobs / 'ngii_index_resolver.py',
                    root / 'index/ngii_index_resolver.py')
    folder = root / 'raw/(B020)fixture'
    folder.mkdir(parents=True)
    (root / 'index/registry.json').write_text(json.dumps({'sheets': [
        {'folder': 'raw/(B020)fixture', 'bounds_wgs84': [126.9, 36.9, 127.1, 37.1]}]}))
    monkeypatch.setenv('NGII_MAP_DATA_ROOT', str(root))
    def write(lanes=2):
        gpd.GeoDataFrame({'ufid': ['wide', 'alley', 'unknown'], 'rdln': [lanes, 2, 0],
                          'rvwd': [46., 3., 25.]}, geometry=[
            LineString([(127, 37), (127.001, 37)]),
            LineString([(127, 37.0002), (127.001, 37.0002)]),
            LineString([(127, 37.0004), (127.001, 37.0004)])], crs=4326).to_file(
                folder / 'N3L_A0020000_001.shp', engine='pyogrio', encoding='UTF-8',
                layer_options={'SPATIAL_INDEX': 'YES'})
    write()
    return root, folder, write


def test_local_roads_without_agents_preserve_lane_width_and_refresh_source(source, monkeypatch):
    from backend.app.adapters import scene_agent
    from backend.app.modules.platform import host
    def forbidden(*a, **kw):
        raise AssertionError('map roads must not start or call an agent')
    monkeypatch.setattr(host, 'ensure', forbidden)
    monkeypatch.setattr(scene_agent, 'context_ground', forbidden)
    app = FastAPI()
    app.include_router(create_land_map_router())
    with TestClient(app) as client:
        url = '/api/v1/land/context-ground?lat=37&lon=127&radius_m=300&detail=roads'
        first = client.get(url)
        assert first.status_code == 200
        payload = first.json()
        assert payload['status'] == 'ok'
        props = {f['properties']['id']: f['properties'] for f in payload['features']['features']}
        assert props['wide']['width_m'] == 6.5
        assert props['wide']['width_status'] == 'estimated'
        assert props['alley']['width_m'] == 3
        assert props['alley']['width_status'] == 'measured'
        polygon = gpd.GeoDataFrame.from_features(payload['features'], crs=4326).to_crs(5186).geometry.iloc[0]
        assert 6.4 < polygon.bounds[3] - polygon.bounds[1] < 6.7
        assert 'unknown' not in props
        assert any('without lanes' in gap for gap in payload['gaps'])
        assert client.get(url).json() == payload
        source[2](4)
        refreshed = client.get(url).json()
        assert refreshed['record']['roads']['revision'] != payload['record']['roads']['revision']
        assert refreshed['features']['features'][0]['properties']['width_m'] == 13
        assert client.get(url.replace('radius_m=300', 'radius_m=1001')).status_code == 422


def test_missing_or_incomplete_local_source_does_not_claim_empty_roads(source):
    app = FastAPI()
    app.include_router(create_land_map_router())
    with TestClient(app) as client:
        response = client.get('/api/v1/land/context-ground?lat=38&lon=128&detail=roads')
        assert response.json()['status'] == 'needs_evidence'
        (source[1] / '.sitecontext-install-incomplete.json').write_text('{}')
        response = client.get('/api/v1/land/context-ground?lat=37&lon=127&detail=roads')
        assert response.status_code == 503


def test_roads_coalesce_disconnects_and_bound_distinct_pending_requests(source, monkeypatch):
    import threading
    from backend.app.modules.land import map_roads
    started, release = threading.Event(), threading.Event()
    original = map_roads._read
    calls = []
    def read(prepared, radius):
        calls.append(prepared[4])
        started.set()
        assert release.wait(5)
        return original(prepared, radius)
    monkeypatch.setattr(map_roads, '_read', read)
    async def run():
        service = map_roads.RoadDisplay()
        first = asyncio.create_task(service.get(37, 127, 300))
        await asyncio.to_thread(started.wait, 3)
        second = asyncio.create_task(service.get(37, 127, 300))
        await asyncio.sleep(.05)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        others = [asyncio.create_task(service.get(37, 127, radius)) for radius in range(301, 320)]
        await asyncio.sleep(.2)
        assert len(service.pending) <= 16
        assert len(calls) <= 2
        release.set()
        result = await second
        assert result['counts']['carriageways'] == 2
        outcomes = await asyncio.gather(*others, return_exceptions=True)
        assert any(isinstance(r, map_roads.RoadsUnavailable) for r in outcomes)
        assert len(calls) == 16
        assert (await service.get(37, 127, 300)) == result
        assert len(calls) == 16
    try:
        asyncio.run(run())
    finally:
        release.set()


def test_changed_source_during_read_is_not_cached(source, monkeypatch):
    from backend.app.modules.land import map_roads
    prepared = map_roads._prepare(37, 127, 300)
    original = prepared[1].read_layer
    def read(*args, **kwargs):
        assert kwargs.get('bbox') is not None
        result = original(*args, **kwargs)
        (source[0] / 'index/registry.json').write_text('{}')
        return result
    monkeypatch.setattr(prepared[1], 'read_layer', read)
    with pytest.raises(map_roads.RoadsUnavailable, match='changed'):
        map_roads._read(prepared, 300)
