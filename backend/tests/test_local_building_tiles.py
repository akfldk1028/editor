import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.modules.land.routers.map import create_land_map_router


def test_local_archive_is_served_without_agent_and_supports_ranges(tmp_path, monkeypatch):
    from backend.app.modules.platform import host
    from backend.app.adapters import scene_agent
    def forbidden(*args, **kwargs):
        raise AssertionError('local tile serving must not invoke an agent')
    monkeypatch.setattr(host, 'ensure', forbidden)
    monkeypatch.setattr(scene_agent, 'context_tiles', forbidden)
    monkeypatch.setenv('WORLD_BUILDING_TILES_DIR', str(tmp_path))
    version = '20261009-12345678'
    folder = tmp_path / version
    folder.mkdir()
    (tmp_path / 'latest').write_text(version)
    (folder / 'manifest.json').write_text(json.dumps({'version': version, 'layer': 'buildings'}))
    (folder / 'buildings.pmtiles').write_bytes(b'PMTiles' + bytes(range(100)))
    app = FastAPI()
    app.include_router(create_land_map_router())
    client = TestClient(app)
    manifest = client.get('/api/v1/land/context-tiles')
    assert manifest.status_code == 200
    reply = client.get(manifest.json()['href'], headers={'Range': 'bytes=0-6'})
    assert reply.status_code == 206 and reply.content == b'PMTiles'
    assert reply.headers['content-range'] == 'bytes 0-6/107'
    assert client.get('/api/v1/land/building-tiles/invalid/buildings.pmtiles').status_code == 404
