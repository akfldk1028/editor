from fastapi.testclient import TestClient
from backend.app.main import create_app


def test_team_template_and_gallery_survive_restart_without_running_agents(tmp_path, monkeypatch):
    monkeypatch.setenv('EDITOR_WORKSPACE_DATA_DIR', str(tmp_path))
    api = TestClient(create_app())
    component = {'provider': 'autogen_agentchat.teams.RoundRobinGroupChat', 'component_type': 'team', 'config': {'participants': []}, 'label': 'Saved template'}
    response = api.post('/api/v1/workspace/teams', json={'component': component})
    assert response.status_code == 201
    team = response.json()
    assert team['component'] == component
    assert team['execution_status'] == 'not_executed'
    component['label'] = 'Edited template'
    changed = api.put(f"/api/v1/workspace/teams/{team['id']}", json={'component': component, 'version': team['version']})
    assert changed.status_code == 200
    assert api.put(f"/api/v1/workspace/teams/{team['id']}", json={'component': component, 'version': team['version']}).status_code == 409
    gallery = {'name': 'Saved gallery', 'components': {'teams': [component], 'agents': [], 'models': [], 'tools': [], 'terminations': []}, 'metadata': {'description': 'Test'}}
    response = api.post('/api/v1/workspace/galleries', json={'config': gallery})
    assert response.status_code == 201
    restored = TestClient(create_app())
    assert restored.get('/api/v1/workspace/galleries').json()[0]['config'] == gallery
    assert restored.get('/api/v1/workspace/teams').json()[0]['component']['label'] == 'Edited template'
    assert restored.delete(f"/api/v1/workspace/teams/{team['id']}").status_code == 200
    assert restored.get(f"/api/v1/workspace/teams/{team['id']}").status_code == 404


def test_template_validation_is_structural_and_rejects_bad_requests(tmp_path, monkeypatch):
    monkeypatch.setenv('EDITOR_WORKSPACE_DATA_DIR', str(tmp_path))
    api = TestClient(create_app(platform_public_origin='http://editor.test'))
    bad = api.post('/api/v1/workspace/validate', json={'component': {'provider': 'x', 'config': {}}})
    assert bad.status_code == 200
    assert bad.json()['is_valid'] is False
    good = api.post('/api/v1/workspace/validate', json={'component': {'provider': 'x', 'component_type': 'agent', 'config': {'name': 'agent'}}})
    assert good.status_code == 200
    assert good.json()['scope'] == 'configuration_structure_only'
    assert good.json()['warnings']
    assert api.post('/api/v1/workspace/teams', json={'component': {}}, headers={'Origin': 'http://other.test'}).status_code == 403
    assert api.post('/api/v1/workspace/teams', json={'component': {}, 'user_id': 'other'}).status_code == 422


def test_gallery_rejects_malformed_components_before_they_can_break_cards(tmp_path, monkeypatch):
    monkeypatch.setenv('EDITOR_WORKSPACE_DATA_DIR', str(tmp_path))
    api = TestClient(create_app())
    response = api.post('/api/v1/workspace/galleries', json={'config': {'name': 'Bad', 'components': {'agents': [{}]}}})
    assert response.status_code == 422
    assert api.get('/api/v1/workspace/galleries').json() == []
