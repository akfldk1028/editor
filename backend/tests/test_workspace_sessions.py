import json
import sqlite3

from fastapi.testclient import TestClient
from backend.app.main import create_app


def test_sessions_keep_their_team_snapshot_and_hide_without_deleting_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv('EDITOR_WORKSPACE_DATA_DIR', str(tmp_path))
    api = TestClient(create_app())
    team = api.post('/api/v1/workspace/teams', json={'component': {
        'provider': 'test.Team', 'component_type': 'team', 'label': 'Original', 'config': {}}}).json()
    created = api.post('/api/v1/workspace/sessions', json={'name': 'Saved session', 'team_id': team['id']})
    assert created.status_code == 201
    session = created.json()
    assert session['execution_status'] == 'not_started'
    assert api.get(f"/api/v1/workspace/sessions/{session['id']}/runs").json() == {'runs': []}
    api.delete(f"/api/v1/workspace/teams/{team['id']}")
    restored = TestClient(create_app())
    assert restored.get('/api/v1/workspace/sessions').json()[0]['team_snapshot']['label'] == 'Original'
    with sqlite3.connect(tmp_path / 'sessions.sqlite3') as db:
        db.execute('INSERT INTO runs(session_id,payload) VALUES (?,?)', (session['id'], json.dumps({
            'id': 17, 'status': 'error', 'messages': [], 'team_result': None, 'error_message': 'Recorded failure'})))
    assert restored.get(f"/api/v1/workspace/sessions/{session['id']}/runs").json()['runs'][0]['status'] == 'error'
    assert restored.delete(f"/api/v1/workspace/sessions/{session['id']}").status_code == 200
    assert restored.get('/api/v1/workspace/sessions').json() == []
    assert restored.get(f"/api/v1/workspace/sessions/{session['id']}/runs").status_code == 404
    with sqlite3.connect(tmp_path / 'sessions.sqlite3') as db:
        assert db.execute('SELECT COUNT(*) FROM runs').fetchone()[0] == 1


def test_sessions_reject_unknown_teams_client_run_evidence_and_cross_origin(tmp_path, monkeypatch):
    monkeypatch.setenv('EDITOR_WORKSPACE_DATA_DIR', str(tmp_path))
    api = TestClient(create_app(platform_public_origin='http://editor.test'))
    assert api.post('/api/v1/workspace/sessions', json={'name': 'Missing', 'team_id': 999}).status_code == 404
    assert api.post('/api/v1/workspace/sessions', json={'name': 'Fake', 'team_id': 1, 'runs': []}).status_code == 422
    assert api.get('/api/v1/workspace/sessions', headers={'Origin': 'http://other.test'}).status_code == 403
    assert api.get('/api/v1/workspace/sessions/999/runs').status_code == 404
