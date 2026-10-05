import json
from pathlib import Path
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes_design_workspace import create_design_workspace_router
from backend.app.modules.design.artifacts import ArtifactArchive, import_artifacts


def local_run(directory):
    root = directory / 'single-executions' / 'mass-local'
    root.mkdir(parents=True)
    (root / 'execution.json').write_text(json.dumps({'execution_id': 'mass-local', 'geometry_ready': True, 'created_at': '2026-10-05T00:00:00Z', 'geometry_hash': 'local-geometry', 'program_hash': 'local-program'}))
    (root / 'mass.png.passport.json').write_text(json.dumps({'geometry_hash': 'local-geometry', 'program_hash': 'local-program', 'stages': []}))
    (root / 'program.json').write_text(json.dumps({'schema_version': 'arr.geometry_program.v1', 'program_id': 'local', 'name': 'Local mass', 'nodes': [{'id': 'mass', 'kind': 'primitive', 'operator': 'box', 'parameters': {'width': 10, 'depth': 10, 'height': 10}}], 'root_id': 'mass', 'metadata': {}}))
    (root / 'mass.png').write_bytes(b'local-render')


def old_run(tmp_path, directory):
    source = tmp_path / 'source' / 'executed-masses' / 'old-run'
    source.mkdir(parents=True)
    (source / 'mass-01-abcdef.png').write_bytes(b'old-render')
    (source / 'mass-01-abcdef.png.passport.json').write_text(json.dumps({'geometry_hash': 'abcdef123', 'program_hash': 'old-program', 'activation_graph': {'nodes': []}, 'stages': []}))
    import_artifacts(ArtifactArchive(directory / 'artifacts'), tmp_path / 'source', 'arr-maas-cache', dry_run=False)


def client(directory, monkeypatch):
    monkeypatch.setenv('EDITOR_DESIGN_DATA_DIR', str(directory))
    app = FastAPI()
    app.include_router(create_design_workspace_router())
    return TestClient(app)


def test_archive_routes_merge_local_and_imported_runs_and_read_both(tmp_path, monkeypatch):
    directory = tmp_path / 'design'
    local_run(directory)
    old_run(tmp_path, directory)
    api = client(directory, monkeypatch)
    base = '/api/v1/design/maas/executed-masses'
    listing = api.get(base)
    assert listing.status_code == 200
    assert {row['run_id'] for row in listing.json()['runs']} == {'old-run', 'single-execution:mass-local'}
    selected = api.get(base, params={'run_id': 'single-execution:mass-local'})
    assert selected.status_code == 200, selected.text
    assert selected.json()['selected_run_id'] == 'single-execution:mass-local'
    assert selected.json()['masses'][0]['preview_url'].startswith('/api/v1/design/')
    assert api.get(base + '/1', params={'run_id': 'single-execution:mass-local'}).content == b'local-render'
    assert api.get(base + '/1/passport', params={'run_id': 'single-execution:mass-local'}).json()['geometry_hash'] == 'local-geometry'
    assert api.get(base + '/2', params={'run_id': 'single-execution:mass-local'}).status_code == 404
    assert api.get(base + '/1', params={'run_id': 'old-run'}).content == b'old-render'
    archive = ArtifactArchive(directory / 'artifacts')
    archive.file('arr-maas-cache', 'executed-masses/old-run/mass-01-abcdef.png').write_bytes(b'tampered')
    assert api.get(base + '/1', params={'run_id': 'old-run'}).status_code == 503


def test_first_local_execution_is_readable_without_imported_archive(tmp_path, monkeypatch):
    local_run(tmp_path)
    api = client(tmp_path, monkeypatch)
    result = api.get('/api/v1/design/maas/executed-masses')
    assert result.status_code == 200, result.text
    assert result.json()['selected_run_id'] == 'single-execution:mass-local'
    assert result.json()['run_count'] == 1
    assert api.get('/api/v1/design/maas/executed-masses', params={'run_id': 'single-execution:missing'}).status_code == 404


@pytest.mark.parametrize('configured', [None, 'relative-design'])
def test_archive_uses_generation_default_and_relative_data_roots(tmp_path, monkeypatch, configured):
    from backend.app.modules.design.generation import paths
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paths, 'editor_root', lambda: tmp_path)
    if configured is None:
        monkeypatch.delenv('EDITOR_DESIGN_DATA_DIR', raising=False)
    else:
        monkeypatch.setenv('EDITOR_DESIGN_DATA_DIR', configured)
    local_run(paths.data_root())
    app = FastAPI()
    app.include_router(create_design_workspace_router())
    result = TestClient(app).get('/api/v1/design/maas/executed-masses')
    assert result.status_code == 200, result.text
    assert result.json()['selected_run_id'] == 'single-execution:mass-local'


def test_imported_passport_links_are_adapted_without_changing_original_evidence(tmp_path, monkeypatch):
    directory = tmp_path / 'design'
    source = tmp_path / 'source' / 'executed-masses' / 'old-run'
    source.mkdir(parents=True)
    (source / 'mass-01-abcdef.png').write_bytes(b'archived-image-fixture')
    raw = {'geometry_hash': 'abcdef123', 'program_hash': 'original-program',
           'request_hash': 'original-request', 'stages': [],
           'activation_graph': {'nodes': [{'evidence': {
               'preview_url': '/design/maas/reference-assets/example.png',
               'source_url': 'https://example.org/original.png',
               'identity': '/design/must-not-change'}}]}}
    original_bytes = json.dumps(raw, indent=2).encode('utf-8')
    (source / 'mass-01-abcdef.png.passport.json').write_bytes(original_bytes)
    archive = ArtifactArchive(directory / 'artifacts')
    import_artifacts(archive, tmp_path / 'source', 'arr-maas-cache', dry_run=False)
    response = client(directory, monkeypatch).get('/api/v1/design/maas/executed-masses/1/passport', params={'run_id': 'old-run'})
    assert response.status_code == 200, response.text
    adapted = response.json()
    evidence = adapted['activation_graph']['nodes'][0]['evidence']
    assert evidence['preview_url'] == '/api/v1/design/maas/reference-assets/example.png'
    assert evidence['source_url'] == raw['activation_graph']['nodes'][0]['evidence']['source_url']
    assert evidence['identity'] == '/design/must-not-change'
    for key in ('geometry_hash', 'program_hash', 'request_hash'):
        assert adapted[key] == raw[key]
    stored = archive.file('arr-maas-cache', 'executed-masses/old-run/mass-01-abcdef.png.passport.json')
    assert stored.read_bytes() == original_bytes
