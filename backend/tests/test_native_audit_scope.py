from backend.app.modules.massing.audit_service import audit_pool
import json
from pathlib import Path


def test_audit_refuses_arbitrary_host_paths_and_missing_pools(tmp_path, monkeypatch):
    root = tmp_path / 'owned'
    root.mkdir()
    monkeypatch.setenv('EDITOR_MASS_OUTPUT_ROOT', str(root))
    assert audit_pool({'candidates_root': str(tmp_path)})[1] == 400
    assert audit_pool({'candidates_root': '../outside'})[1] == 400
    assert audit_pool({'candidates_root': 'missing'})[1] == 404
    assert audit_pool({'candidates_root': '.', 'pnu': 'invalid'})[1] == 400
    assert audit_pool({'candidates_root': '.', 'limit': True})[1] == 400


def test_archived_geometry_runs_original_collaboration_with_unknown_sources(tmp_path, monkeypatch):
    from backend.app.modules.massing.commands import audit_maas_agent_collaboration as owner
    from backend.app.adapters.design_storage import bootstrap
    fixture = next((Path(__file__).parent / 'provider_parity/fixtures/geometry-author-cache').glob('*.json'))
    program = json.loads(fixture.read_text(encoding='utf-8'))['compiled_programs'][0]
    pool = tmp_path / 'pool' / 'candidates'
    pool.mkdir(parents=True)
    (pool / 'candidate.json').write_text(json.dumps({'geometry_program': program}), encoding='utf-8')
    monkeypatch.setenv('EDITOR_MASS_OUTPUT_ROOT', str(tmp_path))
    monkeypatch.setenv('EDITOR_DESIGN_DATA_DIR', str(tmp_path / 'design'))
    monkeypatch.setattr(bootstrap, 'ensure_design_runtime', lambda: None)
    monkeypatch.setattr(owner, 'collect_law_source_snapshot', lambda context: {})
    response, status = audit_pool({'candidates_root': 'pool', 'pnu': '4115011300106840001',
                                  'legal_check': False, 'limit': 1})
    assert status == 200
    assert response['exit'] == 0
    assert response['law_source']['graph_available'] is False
    assert 'gates_on_parking_absent' in response['conditions']
    assert Path(response['report']).is_file()
