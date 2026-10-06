from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.modules.platform.routers.platform import create_platform_router


def test_health_reports_configuration_without_claiming_owner_or_storage_is_reachable(monkeypatch):
    for key in ('EDITOR_PLATFORM_DATA_DIR', 'EDITOR_LAND_DATA_DIR', 'EDITOR_DESIGN_DATA_DIR', 'EDITOR_ORCHESTRATOR_URL'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('EDITOR_SCENE_URL', 'http://127.0.0.1:3002')
    app = FastAPI()
    app.include_router(create_platform_router(public_origin='http://127.0.0.1:3002'))
    client = TestClient(app)
    response = client.get('/api/v1/platform/health')
    assert response.status_code == 200
    assert response.json() == {'service': 'editor-platform', 'public_origin': 'http://127.0.0.1:3002',
        'scene_url': 'http://127.0.0.1:3002', 'storage_configured': False, 'owner_configured': False}
    for key in ('EDITOR_PLATFORM_DATA_DIR', 'EDITOR_LAND_DATA_DIR', 'EDITOR_DESIGN_DATA_DIR'):
        monkeypatch.setenv(key, '/private/storage')
    monkeypatch.setenv('EDITOR_ORCHESTRATOR_URL', 'http://127.0.0.1:8791')
    assert client.get('/api/v1/platform/health').json()['storage_configured'] is True
    assert client.get('/api/v1/platform/health').json()['owner_configured'] is True
    assert '/private/storage' not in client.get('/api/v1/platform/health').text
