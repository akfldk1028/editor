from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.modules.land.routers.analysis import create_land_router
from backend.app.modules.regulations.zoning_catalog import get_zones


def client_for(monkeypatch, tmp_path):
    monkeypatch.delenv('EDITOR_ARR_URL', raising=False)
    monkeypatch.setenv('EDITOR_LAND_DATA_DIR', str(tmp_path / 'land'))
    app = FastAPI()
    app.include_router(create_land_router())
    return TestClient(app)


def raw_body():
    return {'input': '', 'input_type': 'raw',
            'zones': [get_zones()['zones'][0]['zone_name']], 'include_law': False}


def test_raw_analysis_runs_and_persists_without_arr(monkeypatch, tmp_path):
    client = client_for(monkeypatch, tmp_path)
    response = client.post('/api/v1/land/analyze', json=raw_body())
    assert response.status_code == 200
    result = response.json()
    assert result['assessment']['permit_compliance_verified'] is False
    assert result['assessment']['status'] == 'needs_evidence'
    assert result['regulations']['bcr']['limit_pct'] is None
    assert result['regulations']['bcr']['national_ceiling_pct'] == get_zones()['zones'][0]['bcr_default']
    assert result['law_articles'] is None
    assert result['storage']['saved'] is True
    from backend.app.modules.land.repository import LandRepository
    repo = LandRepository(tmp_path / 'land')
    saved = repo.get(result['storage']['analysis_id'])
    assert saved['result']['regulations'] == result['regulations']
    stats = client.get('/api/v1/land/stats?scope=editor').json()
    assert stats['total_queries'] == 1
    assert stats['by_input_type'] == [{'input_type': 'raw', 'count': 1}]
    assert stats['scope'] == 'editor_local'


def test_law_analysis_with_no_provider_is_explicit_partial(monkeypatch, tmp_path):
    monkeypatch.delenv('LAW_BACKEND_URL', raising=False)
    monkeypatch.delenv('AG_LIGHT_URL', raising=False)
    client = client_for(monkeypatch, tmp_path)
    for body in [dict(raw_body(), include_law=True),
                 {'input': '1168011200101280003', 'input_type': 'pnu', 'include_law': True}]:
        response = client.post('/api/v1/land/analyze', json=body)
        assert response.status_code == 200
        assert response.json()['execution_owner'] == 'editor'
        assert response.json().get('errors') or response.json().get('warning')
    assert client.get('/api/v1/land/stats?scope=editor').json()['total_queries'] == 2


def test_missing_storage_does_not_claim_saved(monkeypatch, tmp_path):
    client = client_for(monkeypatch, tmp_path)
    monkeypatch.delenv('EDITOR_LAND_DATA_DIR')
    response = client.post('/api/v1/land/analyze', json=raw_body())
    assert response.status_code == 200
    assert response.json()['storage'] == {'saved': False, 'error': 'Analysis storage unavailable'}


def test_multiple_zones_remain_unresolved_without_areas(monkeypatch, tmp_path):
    client = client_for(monkeypatch, tmp_path)
    body = dict(raw_body(), zones=[z['zone_name'] for z in get_zones()['zones'][:2]])
    value = client.post('/api/v1/land/analyze', json=body).json()
    assert value['zone_info']['bcr_limit'] is None
    assert value['zone_info']['far_limit'] is None
    assert value['assessment']['permit_compliance_verified'] is False


def test_local_analysis_checks_origin_before_storage(monkeypatch, tmp_path):
    client = client_for(monkeypatch, tmp_path)
    response = client.post('/api/v1/land/analyze', json=raw_body(), headers={'Origin': 'https://other.example'})
    assert response.status_code == 403
    assert not (tmp_path / 'land').exists()


def test_database_failure_is_explicit_and_keeps_calculation(monkeypatch, tmp_path):
    import sqlite3
    from backend.app.modules.land.repository import LandRepository
    client = client_for(monkeypatch, tmp_path)
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError('private internal path')
    monkeypatch.setattr(LandRepository, 'save', fail)
    response = client.post('/api/v1/land/analyze', json=raw_body())
    assert response.status_code == 200
    assert response.json()['storage']['saved'] is False
    assert response.json()['regulations'] is not None
    assert 'private internal' not in response.text


def test_local_stats_do_not_call_legacy_or_claim_historical_migration(monkeypatch, tmp_path):
    client = client_for(monkeypatch, tmp_path)
    assert client.get('/api/v1/land/stats').json()['scope'] == 'editor_all'
    response = client.get('/api/v1/land/stats?scope=editor')
    assert response.status_code == 200
    assert response.json()['legacy_history_included'] is False
    assert client.get('/api/v1/land/stats?scope=all').status_code == 200
    imported = client.get('/api/v1/land/stats?scope=imported').json()
    assert imported['scope'] == 'editor_imported'
    assert imported['total_queries'] == 0
    assert client.get('/api/v1/land/stats?scope=legacy').status_code == 422
