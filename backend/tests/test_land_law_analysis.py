from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes_land import create_land_router
from backend.app.modules.land.repository import LandRepository

ZONE = '제2종일반주거지역'
BODY = {'input':'', 'input_type':'raw', 'zones':[ZONE], 'include_law':True}


class Search:
    def __init__(self):
        self.calls = []
    async def search_for_zones(self, names, **kwargs):
        self.calls.append(names)
        article = {'hang_id':'law-1','law_name':'fixture law','article':'1','content':'fixture text'}
        return {'articles':[{'query':'one','results':[article]}, {'query':'two','results':[article]}],
                'total_count':2,'errors':['one search unavailable']}


def client_for(tmp_path, monkeypatch, search=None, extraction=None):
    monkeypatch.delenv('EDITOR_ARR_URL', raising=False)
    monkeypatch.delenv('ENABLE_DATUM_ELEVATION', raising=False)
    monkeypatch.setenv('LLM_EXTRACTION_ENABLED', 'false')
    app = FastAPI()
    app.include_router(create_land_router(repository=LandRepository(tmp_path),
        law_client=search, extraction_client=extraction))
    return TestClient(app)


def test_default_law_analysis_is_local_deduplicated_and_saved(tmp_path, monkeypatch):
    search = Search()
    client = client_for(tmp_path, monkeypatch, search)
    response = client.post('/api/v1/land/analyze', json=BODY)
    assert response.status_code == 200
    result = response.json()
    assert result['execution_owner'] == 'editor'
    assert result['law_articles']['total_count'] == 1
    assert result['law_articles']['errors'] == ['one search unavailable']
    assert result['assessment']['permit_compliance_verified'] is False
    assert result['storage']['saved'] is True
    assert search.calls == [[ZONE]]
    saved = LandRepository(tmp_path).get(result['storage']['analysis_id'])
    assert saved['result']['law_articles'] == result['law_articles']
    assert LandRepository(tmp_path).stats()['error_count'] == 1


def test_law_disabled_makes_no_search_calls(tmp_path, monkeypatch):
    search = Search()
    client = client_for(tmp_path, monkeypatch, search)
    value = client.post('/api/v1/land/analyze', json={**BODY,'include_law':False}).json()
    assert value['law_articles'] is None
    assert search.calls == []


def test_missing_search_configuration_keeps_explicit_partial_calculation(tmp_path, monkeypatch):
    monkeypatch.delenv('LAW_BACKEND_URL', raising=False)
    monkeypatch.delenv('AG_LIGHT_URL', raising=False)
    client = client_for(tmp_path, monkeypatch)
    value = client.post('/api/v1/land/analyze', json=BODY).json()
    assert value['execution_owner'] == 'editor'
    assert value['regulations'] is not None
    assert value['law_articles']['articles'] == []
    assert value['law_articles']['errors']


def test_advisory_never_changes_numeric_rules_and_is_explicit(tmp_path, monkeypatch):
    class Extraction:
        enabled = True
        async def extract(self, names, kind):
            return {'adjacent_setback_m':0, 'sunlight_rules':[{'setback_m':0}]}
    baseline = client_for(tmp_path, monkeypatch, Search())
    expected = baseline.post('/api/v1/land/analyze',json=BODY).json()
    client = client_for(tmp_path, monkeypatch, Search(), Extraction())
    value = client.post('/api/v1/land/analyze',json=BODY).json()
    assert value['regulations'] == expected['regulations']
    assert value['advisory']['status'] == 'unverified_proposal'
    assert value['advisory']['proposals']
    assert value['assessment']['permit_compliance_verified'] is False


def test_evidence_failure_cancels_sibling_search(monkeypatch):
    import asyncio
    import pytest
    from backend.app.modules.land import evidence
    from backend.app.modules.regulations.zoning_catalog import CatalogUnavailable
    cancelled = []
    class SearchForever:
        async def search_for_zones(self, *args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)
    class Extraction:
        enabled = True
    def unavailable(name):
        raise CatalogUnavailable('fixture failure')
    monkeypatch.setattr(evidence, 'lookup', unavailable)
    with pytest.raises(CatalogUnavailable):
        asyncio.run(evidence.collect_evidence([ZONE], include_law=True,
            law_client=SearchForever(), extraction_client=Extraction()))
    assert cancelled == [True]
