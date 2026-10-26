import numpy as np
import rasterio
from rasterio.transform import from_origin
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.modules.land.routers.map import create_land_map_router


def test_map_samples_local_dem_without_agent_and_invalidates_new_source(tmp_path, monkeypatch):
    from backend.app.adapters import site_context
    def forbidden(*a, **kw):
        raise AssertionError('terrain display must not call agents')
    monkeypatch.setattr(site_context, 'ground_heights', forbidden)
    path = tmp_path / 'terrain.tif'
    monkeypatch.setenv('NGII_DEM_LOCAL_PATH', str(path))
    def write(height):
        with rasterio.open(path, 'w', driver='GTiff', height=10, width=10, count=1,
                           dtype='float32', crs=4326, nodata=-9999,
                           transform=from_origin(126.9,37.1,.02,.02)) as dst:
            dst.write(np.full((10,10),height,dtype='float32'),1)
    write(12)
    app = FastAPI()
    app.include_router(create_land_map_router())
    query = '/api/v1/land/terrain-heights?west=127&south=37&east=127.01&north=37.01&size=3'
    client = TestClient(app)
    assert client.get(query).json()['heights'] == [12]*9
    write(27)
    assert client.get(query).json()['heights'] == [27]*9
    write(-9999)
    assert client.get(query).status_code == 404
    path.unlink()
    assert client.get(query).status_code == 502


def test_metadata_changes_with_installed_source(tmp_path, monkeypatch):
    import hashlib
    from backend.app.modules.land import map_terrain
    path = tmp_path / 'terrain.vrt'
    monkeypatch.setenv('NGII_DEM_LOCAL_PATH', str(path))
    path.write_text('first')
    first = map_terrain.metadata()
    assert first['vrt_sha256'] == hashlib.sha256(b'first').hexdigest()
    path.write_text('second')
    second = map_terrain.metadata()
    assert first['revision'] != second['revision']
    assert second['vrt_sha256'] == hashlib.sha256(b'second').hexdigest()
