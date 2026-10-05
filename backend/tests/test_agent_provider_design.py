"""KMassAgent's research-bundle seam: the editor writes the bundle under its own root."""
from fastapi.testclient import TestClient
from backend.app.main import create_app


def test_research_bundle_validates_its_request_and_names_the_bundle_root(tmp_path, monkeypatch):
    monkeypatch.setenv('EDITOR_DESIGN_DATA_DIR', str(tmp_path))
    api = TestClient(create_app(platform_public_origin='http://editor.test'))
    assert api.post('/api/v1/design/agent/unknown-op', json={}).status_code == 404
    missing = api.post('/api/v1/design/agent/research-bundle', json={})
    assert missing.status_code == 400 and missing.json()['success'] is False
    bad_run = api.post('/api/v1/design/agent/research-bundle',
                       json={'candidate': {}, 'run_id': '../escape', 'pnu': '1'})
    assert bad_run.status_code == 400
    # An empty candidate is refused by the writer itself, inside the editor's root.
    refused = api.post('/api/v1/design/agent/research-bundle',
                       json={'candidate': {}, 'run_id': 'kmass-run-1', 'pnu': '4115011300106840001'})
    assert refused.status_code == 400, refused.text
    assert (tmp_path / 'runtime' / 'research-bundles').is_dir()
    assert not (tmp_path / 'runtime' / 'research-bundles' / 'kmass-run-1').exists()  # a refusal leaves nothing behind
    assert api.post('/api/v1/design/agent/research-bundle',
                    json={'candidate': {}, 'run_id': 'kmass-run-1\n', 'pnu': '1'}).status_code == 400
    assert api.post('/api/v1/design/agent/research-bundle', json={'candidate': {}, 'run_id': 'r', 'pnu': '1'},
                    headers={'Origin': 'http://other.test'}).status_code == 403
