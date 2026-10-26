import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import box, mapping, shape

from backend.app.modules.land.routers.map import create_land_map_router


def test_full_ground_never_calls_agents_when_sources_missing(monkeypatch, tmp_path):
    from backend.app.adapters import scene_agent
    from backend.app.modules.platform import host
    from backend.app.modules.land import map_roads
    def forbidden(*args, **kw):
        raise AssertionError('full map ground must not call agents')
    async def roads(*args):
        return {'status': 'ok', 'features': {'type': 'FeatureCollection', 'features': []},
                'counts': {'carriageways': 0}, 'record': {'roads': {}}, 'gaps': []}
    monkeypatch.setattr(host, 'ensure', forbidden)
    monkeypatch.setattr(scene_agent, 'context_ground', forbidden)
    monkeypatch.setattr(map_roads.RoadDisplay, 'get', roads)
    monkeypatch.delenv('VWORLD_API_KEY', raising=False)
    monkeypatch.setenv('MAP_GROUND_CACHE_DIR', str(tmp_path))
    async def unavailable(*args, **kw):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(httpx.AsyncClient, 'send', unavailable)
    app = FastAPI()
    app.include_router(create_land_map_router())
    result = TestClient(app).get('/api/v1/land/context-ground?lat=37&lon=127').json()
    assert result['detail'] == 'full'
    assert result['counts']['parcels'] == 0
    assert any('cadastre' in gap for gap in result['gaps'])
    assert any('cover' in gap for gap in result['gaps'])


def polygon(identifier, bounds=(127, 37, 127.001, 37.001), **properties):
    return {'type': 'Feature', 'id': identifier, 'geometry': mapping(box(*bounds)), 'properties': properties}


def test_provider_splits_full_cadastral_page_and_pages_cover_without_truncation(monkeypatch):
    from backend.app.modules.land.map_ground import sources
    monkeypatch.setattr(sources, 'CADASTRE_PAGE', 2)
    monkeypatch.setattr(sources, 'COVER_PAGE', 2)
    a, b, c = [polygon(str(i), pnu=str(i), jibun='1도', l3_code='411') for i in range(3)]
    calls = []
    def upstream(request):
        q = request.url.params
        calls.append(dict(q))
        if 'startIndex' in q:
            rows = [a, b] if q['startIndex'] == '0' else [c]
            return httpx.Response(200, json={'type': 'FeatureCollection', 'numberMatched': 3, 'features': rows})
        full = q['BBOX'] == '37,127,37.002,127.002,EPSG:4326'
        south, west = map(float, q['BBOX'].split(',')[:2])
        rows = [a, b] if full else [c] if south > 37 and west > 127 else [a, b]
        return httpx.Response(200, json={'type': 'FeatureCollection', 'numberMatched': 3 if full else len(rows), 'features': rows})
    async def run():
        transport = httpx.MockTransport(upstream)
        cadastre = await sources.fetch('cadastre', (127, 37, 127.002, 37.002), 'private', transport=transport)
        assert {r['id'] for r in cadastre['rows']} == {'0', '1', '2'}
        cover = await sources.fetch('cover', (127, 37, 127.002, 37.002), '', transport=transport)
        assert [r['id'] for r in cover['rows']] == ['0', '1', '2']
        assert [p['startIndex'] for p in calls if 'startIndex' in p] == ['0', '2']
        assert 'private' not in json.dumps(cadastre)
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['cadastre', 'cover'])
def test_provider_rejects_incomplete_sources(kind, monkeypatch):
    from backend.app.modules.land.map_ground import sources
    monkeypatch.setattr(sources, 'COVER_PAGE', 1)
    def upstream(request):
        return httpx.Response(200, json={'features': [polygon('same')], 'numberMatched': 2})
    async def run():
        with pytest.raises(sources.SourceUnavailable):
            await sources.fetch(kind, (127, 37, 127.002, 37.002), 'private', transport=httpx.MockTransport(upstream))
    asyncio.run(run())


@pytest.fixture
def composition_inputs():
    parcels = [polygon('road', (127, 37, 127.001, 37.001), pnu='road', jimok='도', ground='road'),
               polygon('lot', (127.001, 37, 127.003, 37.002), pnu='lot', jimok='대', ground='lot')]
    cover = [polygon('grass', (127, 37, 127.0005, 37.001), cover='green', l3_code='411', l3_name='grass'),
             polygon('paved', (127.001, 37, 127.002, 37.001), cover='paved', l3_code='154', l3_name='road'),
             polygon('trees', (127.001, 37.001, 127.003, 37.002), cover='forest', l3_code='311', l3_name='trees')]
    roads = {'status': 'ok', 'features': {'type': 'FeatureCollection', 'features': []}, 'counts': {'carriageways': 0}}
    return parcels, cover, roads


def test_ground_composition_preserves_road_cover_and_lot_remainders(composition_inputs):
    from backend.app.modules.land.map_ground.compose import compose
    parcels, covers, roads = composition_inputs
    features, counts = compose(parcels, covers, roads)
    assert counts == {'parcels': 2, 'cover': 1, 'carriageways': 0, 'parcels_split_by_cover': 2}
    rows = features['features']
    ground = {r['properties']['id']: r for r in rows if r['properties']['layer'] == 'ground'}
    assert set(ground) == {'road', 'road:green', 'lot', 'lot:road'}
    expected = {
        'road': box(127.0005, 37, 127.001, 37.001),
        'road:green': box(127, 37, 127.0005, 37.001),
        'lot:road': box(127.001, 37, 127.002, 37.001),
        'lot': box(127.001, 37, 127.003, 37.002).difference(box(127.001, 37, 127.002, 37.001)),
    }
    for key, geometry in expected.items():
        assert shape(ground[key]['geometry']).equals(geometry)
    assert ground['road:green']['properties']['ground'] == 'green'
    assert ground['lot:road']['properties']['ground'] == 'road'
    cover = [r for r in rows if r['properties']['layer'] == 'cover']
    assert len(cover) == 1
    assert cover[0]['properties']['cover'] == 'forest'
    assert shape(cover[0]['geometry']).equals(box(127.001, 37.001, 127.003, 37.002))


def test_ground_composition_matches_existing_scene_surface_rules(composition_inputs):
    import ast
    from pathlib import Path
    from backend.app.modules.land.map_ground.compose import compose
    parcels, cover, roads = composition_inputs
    # Load only the old pure compositor as an independent migration oracle, never agent runtime imports.
    path = Path(__file__).resolve().parents[3] / 'agents/SceneAgent/sceneagent/context.py'
    if not path.is_file():
        pytest.skip('Optional cross-repository comparison requires the SceneAgent checkout')
    names = {'_Index', '_by_cover', 'context_ground', 'NATURAL_COVER', 'MIN_PIECE_M2', 'ROAD_COVER', 'MIN_ROAD_PIECE_M2'}
    tree = ast.parse(path.read_text(encoding='utf-8'))
    tree.body = [n for n in tree.body if getattr(n, 'name', None) in names or
                 isinstance(n, ast.Assign) and any(getattr(t, 'id', None) in names for t in n.targets)]
    namespace = {'context_roads': lambda reply: reply}
    exec(compile(tree, str(path), 'exec'), namespace)
    expected = namespace['context_ground']({'status': 'ok', 'parcels': parcels}, roads, {'status': 'ok', 'cover': cover})
    features, counts = compose(parcels, cover, roads)
    assert counts == expected['counts'] == {'parcels': 2, 'cover': 1, 'carriageways': 0, 'parcels_split_by_cover': 2}
    assert len(features['features']) == len(expected['features']['features'])
    for new, old in zip(features['features'], expected['features']['features']):
        if 'method' in old['properties']:
            old['properties']['method'] = old['properties']['method'].replace('2024 land cover', 'EGIS:lv3_2025y land cover')
        assert new['properties'] == old['properties']
        assert shape(new['geometry']).equals(shape(old['geometry']))


def test_missing_parcels_keep_available_landcover_and_correct_cadastral_classes():
    from backend.app.modules.land.map_ground.compose import normalize, compose
    rows = [polygon(str(i), jibun='1' + jimok) for i, jimok in enumerate(('원', '제', '유'))]
    assert [p['properties']['ground'] for p in normalize({'rows': rows}, 'cadastre', 37, 127, 300)] == ['green', 'green', 'water']
    cover = [polygon('grass', cover='green', l3_code='411', l3_name='grass')]
    features, counts = compose([], cover, {}, parcels_available=False)
    assert counts['cover'] == 1
    assert features['features'][0]['properties']['layer'] == 'cover'


def test_successful_sources_survive_restart_and_corrupt_cache_is_refetched(tmp_path, monkeypatch):
    from backend.app.modules.land.map_ground.cache import SourceCache
    monkeypatch.setenv('MAP_GROUND_CACHE_DIR', str(tmp_path))
    calls = []
    def upstream(request):
        calls.append(request)
        return httpx.Response(200, json={'features': [polygon('grass', l3_code='411')], 'numberMatched': 1})
    async def run():
        transport = httpx.MockTransport(upstream)
        first = await SourceCache(transport=transport).get('cover', (127, 37, 127.002, 37.002))
        second = await SourceCache(transport=transport).get('cover', (127, 37, 127.002, 37.002))
        assert second == first
        assert len(calls) == 1
        path = next(tmp_path.glob('*.json'))
        value = json.loads(path.read_text())
        value['payload']['rows'] = []
        path.write_text(json.dumps(value))
        third = await SourceCache(transport=transport).get('cover', (127, 37, 127.002, 37.002))
        assert len(third['rows']) == 1
        assert len(calls) == 2
    asyncio.run(run())


def test_full_ground_reuses_composition_until_source_revision_changes(monkeypatch):
    from backend.app.modules.land import map_ground
    revision = ['one']
    class Roads:
        async def get(self, *args):
            return {'status': 'ok', 'record': {'roads': {'revision': 'roads'}}}
    async def source(kind, bounds):
        return {'rows': [], 'record': {'revision': revision[0], 'retrieved': 'now'}}
    original = map_ground.compose
    calls = []
    def compose(*args, **kw):
        calls.append(True)
        return original(*args, **kw)
    monkeypatch.setattr(map_ground, 'compose', compose)
    async def run():
        service = map_ground.GroundDisplay(Roads())
        monkeypatch.setattr(service.sources, 'get', source)
        first = await service.get(37, 127, 300)
        assert (await service.get(37, 127, 300)) == first
        assert len(calls) == 1
        revision[0] = 'two'
        assert (await service.get(37, 127, 300))['record']['ground']['revision'] == 'two'
        assert len(calls) == 2
    asyncio.run(run())


def test_display_clips_regional_polygons_to_requested_viewport():
    from backend.app.modules.land.map_ground.compose import normalize
    row = polygon('regional', (126, 36, 128, 38), l3_code='411')
    result = normalize({'rows': [row]}, 'cover', 37, 127, 300)
    geometry = shape(result[0]['geometry'])
    assert geometry.contains(shape(mapping(box(126.9999, 36.9999, 127.0001, 37.0001))))
    west, south, east, north = geometry.bounds
    assert 126.99 < west < east < 127.01
    assert 36.99 < south < north < 37.01


def test_viewport_clipping_preserves_multipart_holes_and_ground_class():
    from shapely.geometry import MultiPolygon, Point, Polygon
    from backend.app.modules.land.map_ground.compose import normalize
    outer = box(126.999, 36.999, 127.0005, 37.0005)
    hole = box(126.9999, 36.9999, 127.0001, 37.0001)
    multipart = MultiPolygon([Polygon(outer.exterior.coords, [hole.exterior.coords]),
                              box(127.001, 37, 127.002, 37.001)])
    row = {'type': 'Feature', 'geometry': mapping(multipart), 'properties': {'pnu': 'water', 'jibun': '1유'}}
    normalized = normalize({'rows': [row]}, 'cadastre', 37, 127, 300)[0]
    geometry = shape(normalized['geometry'])
    assert normalized['properties']['ground'] == 'water'
    assert geometry.geom_type == 'MultiPolygon' and len(geometry.geoms) == 2
    assert not geometry.contains(Point(127, 37))
    assert geometry.contains(Point(127.0015, 37.0005))
