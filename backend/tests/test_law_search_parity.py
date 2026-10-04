"""Fixtures captured from the original source AST with offline provider stubs."""
import asyncio
import json
from pathlib import Path

import httpx

from backend.app.adapters.law_search import LawSearchClient


FIXTURE = json.loads((Path(__file__).with_name('fixtures') / 'law_search_parity.json')
                    .read_text(encoding='utf-8'))


def test_primary_filter_and_original_metadata_match_source():
    async def handler(request):
        return httpx.Response(200, json={'results': FIXTURE['records']})
    result = asyncio.run(LawSearchClient('http://law', transport=httpx.MockTransport(handler))
                         .search_queries(['query']))
    actual = result['articles'][0]
    expected = FIXTURE['primary_expected']
    assert actual['query'] == expected['query']
    assert len(actual['results']) == len(expected['results'])
    for original, migrated in zip(expected['results'], actual['results']):
        assert all(migrated[key] == value for key, value in original.items())


def test_zone_and_building_query_order_and_limits_match_original():
    calls = []
    async def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'results': []})
    async def run():
        client = LawSearchClient('http://law', transport=httpx.MockTransport(handler))
        await client.search_for_zones(['zone', 'zone'], include_extended=True)
        assert [call['query'] for call in calls] == FIXTURE['zone_queries']['queries']
        assert all(call['limit'] == FIXTURE['zone_queries']['limit'] for call in calls)
        calls.clear()
        await client.search_for_building_type('building', ['one', 'two', 'three'])
        assert [call['query'] for call in calls] == FIXTURE['building_queries']['queries']
    asyncio.run(run())
