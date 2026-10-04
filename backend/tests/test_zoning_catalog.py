import json
from pathlib import Path
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes_land import create_land_router


def test_zones_are_owned_by_editor_without_legacy_server(monkeypatch):
    monkeypatch.delenv('EDITOR_ARR_URL', raising=False)
    app = FastAPI()
    app.include_router(create_land_router())
    with TestClient(app) as client:
        response = client.get('/api/v1/land/zones')
    assert response.status_code == 200
    data = Path(__file__).parents[1] / 'app/modules/regulations/data/zoning_limits.json'
    expected = json.loads(data.read_text(encoding='utf-8'))['zones']
    assert expected
    assert response.json() == {'zones': expected, 'count': len(expected)}


def test_catalog_results_do_not_mutate_later_requests():
    from backend.app.modules.regulations.zoning_catalog import get_zones
    first = get_zones()
    original = first['zones'][0]['sunlight_setback']['applies']
    first['zones'][0]['sunlight_setback']['applies'] = not original
    assert get_zones()['zones'][0]['sunlight_setback']['applies'] is original


def test_missing_catalog_is_unavailable_not_empty_success(monkeypatch, tmp_path):
    from backend.app.modules.regulations import zoning_catalog
    monkeypatch.setattr(zoning_catalog, 'DATA_PATH', tmp_path / 'missing.json')
    app = FastAPI()
    app.include_router(create_land_router())
    with TestClient(app) as client:
        response = client.get('/api/v1/land/zones')
    assert response.status_code == 503
    assert 'zones' not in response.json()


@pytest.mark.parametrize('contents', ['{', '{}', '{"zones": []}', '{"zones": [null]}'])
def test_invalid_catalog_is_unavailable(monkeypatch, tmp_path, contents):
    from backend.app.modules.regulations import zoning_catalog
    path = tmp_path / 'invalid.json'
    path.write_text(contents, encoding='utf-8')
    monkeypatch.setattr(zoning_catalog, 'DATA_PATH', path)
    with pytest.raises(zoning_catalog.CatalogUnavailable):
        zoning_catalog.get_zones()
