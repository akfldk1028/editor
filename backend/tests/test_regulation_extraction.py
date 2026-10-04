import importlib
import json
import asyncio

import httpx
import pytest


@pytest.fixture
def anyio_backend():
    return 'asyncio'


class Search:
    def __init__(self):
        self.calls = []

    async def search_queries(self, queries, **kwargs):
        self.calls.append((queries, kwargs))
        return {'articles': [{'results': [
            {'hang_id': 'one', 'content': 'evidence text', 'law_name': 'Law', 'jo_name': 'Article 1'},
            {'hang_id': 'one', 'content': 'duplicate evidence'}]}], 'errors': []}


def client(search, **kwargs):
    return importlib.import_module('backend.app.adapters.regulation_extraction').RegulationExtractionClient(search, **kwargs)


@pytest.mark.anyio
@pytest.mark.parametrize('enabled,key', [(False, ''), (False, 'secret'), (True, '')])
async def test_disabled_or_unconfigured_extraction_performs_no_io(enabled, key):
    search = Search()
    async def completion(**kwargs):
        pytest.fail('disabled completion called')
    result = await client(search, enabled=enabled, api_key=key, completion=completion).extract(['zone'], 'sunlight')
    assert result is None
    assert search.calls == []


@pytest.mark.anyio
async def test_extraction_deduplicates_evidence_and_does_not_cache_mutable_results():
    search = Search()
    calls = []
    async def completion(**kwargs):
        calls.append(kwargs)
        return json.dumps({'sunlight_applies': True, 'sunlight_rules': [{'setback_m': 1.5}]})
    adapter = client(search, enabled=True, api_key='secret', model='configured-model', completion=completion)
    first = await adapter.extract(['zone'], 'sunlight')
    first['sunlight_rules'][0]['setback_m'] = 999
    second = await adapter.extract(['zone'], 'sunlight')
    assert second['sunlight_rules'][0]['setback_m'] == 1.5
    assert len(search.calls) == len(calls) == 2
    assert search.calls[0][1] == {'limit': 3, 'filter_results': False}
    assert calls[0]['model'] == 'configured-model'
    assert 'evidence text' in calls[0]['messages'][1]['content']
    assert 'duplicate evidence' not in calls[0]['messages'][1]['content']


@pytest.mark.anyio
@pytest.mark.parametrize('payload', ['[]', '42', 'null', '{"sunlight_applies":1}',
    '{"sunlight_rules":"bad"}', '{"sunlight_rules":[{"setback_m":NaN}]}',
    '{"sunlight_rules":[{"setback_m":-1}]}', '{"sunlight_rules":[{"setback_m":true}]}',
    '{"sunlight_rules":[1]}', '{"sunlight_applies":true,"exceptions":[{}]}'])
async def test_invalid_proposal_never_reaches_calculator(payload):
    async def completion(**kwargs):
        return payload
    assert await client(Search(), enabled=True, api_key='secret', completion=completion).extract(['zone'], 'sunlight') is None


@pytest.mark.anyio
async def test_transient_completion_failure_is_not_cached_or_exposed(caplog):
    calls = 0
    async def completion(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError('secret token and provider URL')
        return '{"adjacent_setback_m":2.0}'
    adapter = client(Search(), enabled=True, api_key='secret', completion=completion)
    assert await adapter.extract(['zone'], 'adjacent_setback') is None
    assert await adapter.extract(['zone'], 'adjacent_setback') == {'adjacent_setback_m': 2.0}
    assert 'secret token' not in caplog.text


@pytest.mark.anyio
async def test_unknown_kind_never_searches():
    search = Search()
    assert await client(search, enabled=True, api_key='secret').extract(['zone'], 'unknown') is None
    assert search.calls == []


@pytest.mark.anyio
async def test_completion_deadline_cancels_work():
    cancelled = False
    async def completion(**kwargs):
        nonlocal cancelled
        try:
            await asyncio.sleep(10)
        finally:
            cancelled = True
    adapter = client(Search(), enabled=True, api_key='secret', completion=completion, timeout=0.01)
    assert await adapter.extract(['zone'], 'sunlight') is None
    assert cancelled


@pytest.mark.anyio
async def test_real_search_adapter_keeps_unfiltered_evidence_for_advisory_only():
    from backend.app.adapters.law_search import LawSearchClient
    from backend.app.modules.regulations.calculator import calculate_all
    from backend.app.modules.regulations.zoning_catalog import get_zones

    async def handler(request):
        return httpx.Response(200, json={'results': [{'hang_id': 'low-score', 'content': 'law evidence',
            'law_name': 'Law', 'similarity': 0.01}]})
    async def completion(**kwargs):
        assert 'law evidence' in kwargs['messages'][1]['content']
        return '{"adjacent_setback_m":999}'
    search = LawSearchClient('https://law.example', transport=httpx.MockTransport(handler))
    adapter = client(search, enabled=True, api_key='secret', completion=completion)
    proposal = await adapter.extract(['zone'], 'adjacent_setback')
    assert proposal == {'adjacent_setback_m': 999}
    zone = get_zones()['zones'][0]['zone_name']
    baseline = calculate_all([zone], use_llm_extraction=False, assessment_date='2026-10-04')
    result = calculate_all([zone], use_llm_extraction=True, assessment_date='2026-10-04',
        extractor=lambda zones, kind: proposal if kind == 'adjacent_setback' else None)
    assert result['adjacent_setback_m'] == baseline['adjacent_setback_m']
    assert result['adjacent_setback_proposal'] == {'status': 'unverified_proposal', 'values': proposal}
