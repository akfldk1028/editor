import importlib.util
import hashlib
import json
import sys
from pathlib import Path

import pytest

MODULE = Path(__file__).with_name('unified_inventory.py')


def load_module():
    assert MODULE.exists(), 'Missing unified inventory implementation'
    spec = importlib.util.spec_from_file_location('unified_inventory', MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_only_mounted_django_routes_are_active(tmp_path):
    module = load_module()
    (tmp_path / 'backend').mkdir()
    (tmp_path / 'law').mkdir()
    (tmp_path / 'unused').mkdir()
    (tmp_path / 'backend/urls.py').write_text("urlpatterns=[path('law/', include('law.urls'))]\n# path('unused/', include('unused.urls'))\n", encoding='utf-8')
    (tmp_path / 'law/urls.py').write_text("urlpatterns=[path('health/', views.health)]\n", encoding='utf-8')
    (tmp_path / 'unused/urls.py').write_text("urlpatterns=[path('run/', views.run)]\n", encoding='utf-8')
    rows = module.django_routes(tmp_path)
    assert [(row['route'], row['mounted']) for row in rows] == [('law/health/', True), ('unused/run/', False)]


def test_every_active_operation_has_a_target():
    module = load_module()
    operations = [{'id': 'arr:law/health/', 'mounted': True}]
    with pytest.raises(ValueError, match='missing'):
        module.validate_coverage(operations, [])
    with pytest.raises(ValueError, match='target'):
        module.validate_coverage(operations, [{'id': 'arr:law/health/', 'target': '', 'disposition': 'migrate'}])
    module.validate_coverage(operations, [{'id': 'arr:law/health/', 'target': 'backend/arr/law', 'disposition': 'migrate'}])


def test_duplicate_rows_and_silent_exclusions_are_rejected():
    module = load_module()
    row = {'id': 'x', 'target': 'backend/arr', 'disposition': 'migrate'}
    with pytest.raises(ValueError, match='duplicate'):
        module.validate_coverage([], [row, row])
    with pytest.raises(ValueError, match='reason'):
        module.validate_coverage([{'id': 'x', 'mounted': True}], [{**row, 'disposition': 'exclude'}])


def test_root_handlers_are_not_lost(tmp_path):
    module = load_module()
    (tmp_path / 'backend').mkdir()
    (tmp_path / 'backend/urls.py').write_text("urlpatterns=[path('admin/', admin.site.urls)]", encoding='utf-8')
    rows = module.django_routes(tmp_path)
    assert len(rows) == 1
    assert rows[0]['route'] == 'admin/'
    assert rows[0]['mounted'] is True


def test_fastapi_inventory_preserves_methods_and_websocket_prefixes(tmp_path):
    module = load_module()
    assert hasattr(module, 'fastapi_routes'), 'Missing mounted FastAPI inventory'
    (tmp_path / 'routes').mkdir()
    (tmp_path / 'app.py').write_text("from .routes import runs\napi.include_router(runs.router,prefix='/runs')\n@api.get('/health')\ndef health(): pass\n", encoding='utf-8')
    (tmp_path / 'routes/runs.py').write_text("@router.post('/')\ndef create(): pass\n@router.websocket('/{id}')\nasync def stream(): pass\n", encoding='utf-8')
    rows = module.fastapi_routes(tmp_path)
    assert {row['id'] for row in rows} == {'ag:GET /api/health', 'ag:POST /api/runs/', 'ag:WEBSOCKET /api/runs/{id}'}


def test_source_drift_invalidates_migration_evidence(tmp_path):
    module = load_module()
    assert hasattr(module, 'validate_sources'), 'Missing source drift check'
    file = tmp_path / 'views.py'
    file.write_bytes(b'original')
    rows = [{'source': str(file), 'sha256': hashlib.sha256(b'original').hexdigest()}]
    module.validate_sources(rows)
    file.write_bytes(b'changed')
    with pytest.raises(ValueError, match='source changed'):
        module.validate_sources(rows)


def test_new_inventory_does_not_plan_a_legacy_named_backend_tree(tmp_path, monkeypatch):
    module = load_module()
    root = tmp_path / 'source'
    (root / 'backend/backend').mkdir(parents=True)
    (root / 'backend/land').mkdir()
    (root / 'backend/backend/urls.py').write_text("urlpatterns=[path('land/', include('land.urls'))]", encoding='utf-8')
    (root / 'backend/land/urls.py').write_text("urlpatterns=[path('zones/', views.zones)]", encoding='utf-8')
    matrix, sources = tmp_path / 'matrix.json', tmp_path / 'sources.json'
    monkeypatch.setattr(module, 'source_record', lambda root, file, target: {'source': str(file), 'target': target})
    monkeypatch.setattr(sys, 'argv', ['inventory', '--arr', str(root), '--matrix', str(matrix), '--source-map', str(sources)])
    module.main()
    assert json.loads(matrix.read_text())['features'][0]['target'] == 'backend/app/api/routes_land.py'
    assert all(row['target'].startswith('reference-only:') for row in json.loads(sources.read_text())['files'])
