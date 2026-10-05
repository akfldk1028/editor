import asyncio

import httpx
import pytest

from backend.app.adapters.law_workspace import LawWorkspaceClient, LawWorkspaceUnavailable


def test_search_preserves_original_stats_and_normalizes_article_cards():
    def respond(request):
        assert request.url.path == '/api/search'
        return httpx.Response(200, json={'results': [{'content': 'text', 'hang_id': 'article', 'stages': None}],
            'stats': {'total': 1, 'vector_count': 1}, 'domains_queried': ['building']})
    service = LawWorkspaceClient('http://primary', transport=httpx.MockTransport(respond))
    result = asyncio.run(service.search('height', 10))
    assert result['stats']['vector_count'] == 1
    assert result['domains_queried'] == ['building']
    assert result['results'][0]['stages'] == []


def test_domain_failure_never_returns_global_results():
    seen = []
    def respond(request):
        seen.append(request.url.host)
        raise httpx.ConnectError('unavailable')
    service = LawWorkspaceClient('http://primary', 'http://fallback', transport=httpx.MockTransport(respond))
    with pytest.raises(LawWorkspaceUnavailable):
        asyncio.run(service.search('height', 10, 'building'))
    assert seen == ['primary']


def test_light_provider_health_contract(monkeypatch):
    monkeypatch.delenv('LAW_BACKEND_URL', raising=False)
    service = LawWorkspaceClient(fallback_url='http://fallback', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={'status': True})))
    assert asyncio.run(service.health())['ready'] is True


def test_article_does_not_choose_an_ambiguous_law():
    service = LawWorkspaceClient(fallback_url='http://fallback', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={'results': [{'mst': 1}, {'mst': 2}]})))
    with pytest.raises(LawWorkspaceUnavailable):
        asyncio.run(service.article('건축법_제60조'))


def test_article_preserves_intro_and_paragraphs():
    def respond(request):
        if request.url.path == '/law/search':
            return httpx.Response(200, json={'results': [{'mst': 1, 'name': '건축법'}]})
        return httpx.Response(200, json={'text': '제60조 높이 제한\n① 첫째 항\n② 둘째 항'})
    service = LawWorkspaceClient(fallback_url='http://fallback', transport=httpx.MockTransport(respond))
    result = asyncio.run(service.article('건축법_제60조'))
    assert result['jo']['content'] == '제60조 높이 제한'
    assert [hang['number'] for hang in result['hangs']] == ['①', '②']
