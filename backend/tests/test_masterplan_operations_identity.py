"""The planning-operations envelope MasterPlanagent verifies must leave the editor untouched."""
import hashlib
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes_design_runtime import create_design_runtime_router


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def test_catch_all_does_not_rewrite_urls_inside_the_identity_hashed_envelope(monkeypatch):
    from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime
    ensure_design_runtime()
    from backend.app.api.design_runtime import masterplan_operations_views as views
    from django.http import JsonResponse

    result = {'preview_url': '/design/maas/executed-masses/1', 'features': []}
    envelope = {'schema_version': 'arr.masterplan.operations.v1', 'operation': 'plan_site', 'status': 'succeeded',
                'request_hash': 'x' * 64, 'result': result, 'result_hash': digest(result)}
    monkeypatch.setattr(views, 'masterplan_operations', lambda request: JsonResponse(envelope))
    from backend.app.api.design_runtime import urls
    monkeypatch.setattr(urls.urlpatterns[0], 'callback', views.masterplan_operations)

    app = FastAPI()
    app.include_router(create_design_runtime_router(public_origin='http://editor.test'))
    response = TestClient(app).post('/api/v1/design/masterplan/operations/', json={'operation': 'plan_site', 'arguments': {}},
                                    headers={'Origin': 'http://editor.test'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['result'] == result
    assert body['result_hash'] == digest(body['result'])


def test_delivered_export_root_has_one_name(tmp_path, monkeypatch):
    # Writer (delivered_mass_export) and reader (delivered_source) read EDITOR_DELIVERED_MASS_EXPORT_ROOT.
    import inspect
    from backend.app.modules.design.generation.maas.delivered import mass_export as delivered_mass_export
    from backend.app.modules.design.generation.maas.masterplan import delivered_source

    assert 'EDITOR_DELIVERED_MASS_EXPORT_ROOT' in inspect.getsource(delivered_mass_export)
    assert 'EDITOR_DELIVERED_MASS_EXPORT_ROOT' in inspect.getsource(delivered_source)
    assert 'ARR_DELIVERED_MASS_EXPORT_ROOT' not in inspect.getsource(delivered_source)
