import asyncio
import json

import httpx
import pytest

from backend.app.adapters.law_search import LawSearchClient


def test_unconfigured_has_explicit_errors_without_network():
    result = asyncio.run(LawSearchClient().search_queries(['one']))
    assert result['total_count'] == 0
    assert result['errors'] == ['Law search is not configured']


def test_filtering_dedup_order_and_extraction_unfiltered():
    seen = []
    async def respond(request):
        seen.append(json.loads(request.content)['query'])
        return httpx.Response(200, json={'results': [
            {'content': 'keep', 'similarity': .25, 'jo_name': 'article'},
            {'content': 'low', 'similarity': .24},
            {'content': 'noise', 'law_name': '수도법'},
        ]})
    client = LawSearchClient('http://law', transport=httpx.MockTransport(respond))
    result = asyncio.run(client.search_queries(['a', 'b', 'a']))
    assert seen == ['a', 'b']
    assert result['total_count'] == 2
    assert result['articles'][0]['results'][0]['jo_name'] == 'article'
    assert asyncio.run(client.search_queries(['a'], filter_results=False))['total_count'] == 3


@pytest.mark.parametrize('failure', ['connect', 'connect_timeout', 'read', 'status', 'json'])
def test_fallback_only_connection_failures(failure):
    calls = []
    async def primary(request):
        if failure == 'connect': raise httpx.ConnectError('secret URL')
        if failure == 'connect_timeout': raise httpx.ConnectTimeout('secret URL')
        if failure == 'read': raise httpx.ReadTimeout('secret URL')
        if failure == 'status': return httpx.Response(500)
        return httpx.Response(200, text='invalid')
    async def fallback(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'results': [
            {'id': 'id', 'content': 'text', 'score': .9, 'jo_name': 'article'}]})
    result = asyncio.run(LawSearchClient('http://law', 'http://fallback',
        transport=httpx.MockTransport(primary), fallback_transport=httpx.MockTransport(fallback)
    ).search_queries(['q']))
    assert bool(calls) == (failure in ('connect', 'connect_timeout'))
    assert 'secret' not in json.dumps(result)
    if calls:
        article = result['articles'][0]['results'][0]
        assert article['hang_id'] == 'id'
        assert article['jo_name'] == 'article'
        assert article['article'] == 'article'
        assert calls[0]['mode'] == 'hybrid'


@pytest.mark.parametrize('payload', [[], {}, {'results': {}}, {'results': [None]},
    {'results': [{'content': 1}]}, {'results': [{'content': 'x', 'similarity': 'bad'}]},
    {'results': [{'content': 'x', 'similarity': float('inf')}]},
    {'results': [{'content': 'x', 'citation': {'value': float('nan')}}]}])
def test_malformed_safe_error(payload):
    async def respond(request):
        return httpx.Response(200, content=json.dumps(payload))
    result = asyncio.run(LawSearchClient('http://law', transport=httpx.MockTransport(respond))
                         .search_queries(['q']))
    assert result['errors'] and not result['articles']


def test_deadline_retains_completed_results_and_cancels_pending():
    active = peak = cancelled = 0
    async def respond(request):
        nonlocal active, peak, cancelled
        active += 1
        peak = max(peak, active)
        try:
            if json.loads(request.content)['query'] != 'fast':
                await asyncio.sleep(10)
            return httpx.Response(200, json={'results': [{'content': 'done'}]})
        except asyncio.CancelledError:
            cancelled += 1
            raise
        finally:
            active -= 1
    async def run():
        client = LawSearchClient('http://law', transport=httpx.MockTransport(respond), total_timeout=.04)
        return await asyncio.wait_for(client.search_queries(['fast'] + [str(i) for i in range(20)]), 1)
    result = asyncio.run(run())
    assert result['total_count'] == 1 and result['errors']
    assert peak <= 5 and active == 0 and cancelled > 0


def test_caller_cancellation_cleans_children():
    active = 0
    async def respond(request):
        nonlocal active
        active += 1
        try: await asyncio.sleep(10)
        finally: active -= 1
    async def run():
        client = LawSearchClient('http://law', transport=httpx.MockTransport(respond))
        task = asyncio.create_task(client.search_queries(['a', 'b']))
        await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(run())
    assert active == 0


def test_shared_client_caps_concurrency_across_batches_and_keeps_partial_results():
    active = peak = 0
    async def respond(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(.001)
            query = json.loads(request.content)['query']
            if query == 'fail': return httpx.Response(503)
            return httpx.Response(200, json={'results': [{'content': query}]})
        finally: active -= 1
    async def run():
        client = LawSearchClient('http://law', transport=httpx.MockTransport(respond))
        return await asyncio.gather(client.search_queries(['fail', 'a', 'b', 'c']),
                                    client.search_queries(['d', 'e', 'f', 'g']))
    first, second = asyncio.run(run())
    assert first['total_count'] == 3 and first['errors']
    assert second['total_count'] == 4 and not second['errors']
    assert peak <= 5 and active == 0


def test_source_query_composition_and_fallback_only_configuration():
    queries = []
    async def respond(request):
        queries.append(json.loads(request.content)['query'])
        return httpx.Response(200, json={'results': []})
    async def run():
        client = LawSearchClient(fallback_url='http://fallback',
                                fallback_transport=httpx.MockTransport(respond))
        await client.search_for_zones(['zone', 'zone'], include_extended=True)
        assert len(queries) == 23
        assert queries[-2:] == ['zone 건폐율', 'zone 건축제한']
        queries.clear()
        await client.search_for_building_type('building', ['one', 'two', 'three'])
        assert len(queries) == 7
        assert queries[-2:] == ['one building', 'two building']
    asyncio.run(run())


def test_reused_client_across_event_loops():
    async def respond(request):
        await asyncio.sleep(.001)
        return httpx.Response(200, json={'results': []})
    client = LawSearchClient('http://law', transport=httpx.MockTransport(respond))
    for _ in range(2):
        assert not asyncio.run(client.search_queries([str(i) for i in range(8)]))['errors']


@pytest.mark.parametrize('bad', [False, True])
def test_preserves_primary_citation_metadata_but_rejects_invalid_article(bad):
    record = {'content': 'text', 'article': 3 if bad else 'Article 3',
              'effective_date': '2026-10-04', 'source_id': 'source',
              'citation': {'title': 'reference', 'pages': [1, 2]}}
    async def respond(request):
        return httpx.Response(200, json={'results': [record]})
    result = asyncio.run(LawSearchClient('http://law', transport=httpx.MockTransport(respond))
                         .search_queries(['q']))
    if bad:
        assert result['errors'] and not result['articles']
    else:
        assert record.items() <= result['articles'][0]['results'][0].items()
