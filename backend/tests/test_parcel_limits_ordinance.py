"""parcel_limits cites what the caps came from: articles, ordinance edition, assessment date."""
import json
from types import SimpleNamespace

from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime
ensure_design_runtime()

from django.test import RequestFactory  # noqa: E402

from backend.app.api.agent_providers import law  # noqa: E402

REGULATION = {
    'assessment_date': '2026-10-06', 'bcr_pct': 60, 'bcr_article': '의정부시 도시계획 조례 제42조',
    'far_pct': 250, 'far_article': '의정부시 도시계획 조례 제46조', 'height_limit_m': None, 'height_article': '',
    'national_bcr_ceiling_pct': 60, 'national_far_ceiling_pct': 250, 'matched_zones': ['제2종일반주거지역'],
    'municipal_coverage': {'status': 'available_snapshot', 'caps_complete': True, 'missing_evidence': [],
                           'sources': [{'name': '의정부시 도시계획 조례', 'edition_id': '2072835',
                                        'effective_date': '20250925',
                                        'url': 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=2072835'}],
                           'excluded_sources': [], 'limitations': ['snapshot_does_not_certify_amendment_completeness']},
}


def test_the_receipt_names_articles_edition_and_date():
    got = law.ordinance_receipt(REGULATION)
    assert got['far_article'].endswith('제46조') and got['assessment_date'] == '2026-10-06'
    assert got['municipal_coverage']['sources'][0]['edition_id'] == '2072835'
    assert law.ordinance_receipt(None)['status'] == 'needs_evidence'


def test_parcel_limits_carries_the_receipt(monkeypatch):
    from backend.app.modules.design.generation.maas.massv2 import legal, parcel_policy
    site = SimpleNamespace(parcel_area_m2=1000.0, ground_capacity_m2=600.0, far_capacity_m2=2500.0,
                           max_storeys=None, regulation=REGULATION, evidence=lambda: {'schema_version': 'x'})
    monkeypatch.setattr(legal, 'load_legal_site', lambda pnu, building_type=None: site)
    monkeypatch.setattr(parcel_policy, 'policy_for', lambda pnu: {})
    request = RequestFactory().post('/law/agent/parcel-limits/', data=json.dumps({'pnu': '4115011300106840001'}),
                                    content_type='application/json')
    body = json.loads(law.parcel_limits(request).content)
    assert body['ordinance']['bcr_article'].endswith('제42조') and body['zones'] == ['제2종일반주거지역']
    assert body['far_pct'] == 250.0 and body['evidence'] == {'schema_version': 'x'}
