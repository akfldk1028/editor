"""Bounded asynchronous law search with connection-only provider fallback."""
import asyncio
from copy import deepcopy
import json
import math
import weakref

import httpx


_BASE_QUERIES = ['건폐율', '용적률', '건축제한', '높이제한', '일조권', '가각전제',
                 '건축물 높이제한 전면도로', '건축선', '인접대지', '주차장', '조경', '건축지정선']
_EXTENDED_QUERIES = ['용도제한', '접도의무', '대지분할', '인동간격', '공개공지',
                     '내화구조', '개발행위허가', '소방시설', '건축물 에너지절약설계']


class LawSearchClient:
    def __init__(self, base_url=None, fallback_url=None, *, transport=None,
                 fallback_transport=None, total_timeout=120):
        if not math.isfinite(total_timeout) or total_timeout <= 0:
            raise ValueError('Search timeout must be positive and finite')
        self.base_url = base_url.rstrip('/') if base_url else None
        self.fallback_url = fallback_url.rstrip('/') if fallback_url else None
        self.transport = transport
        self.fallback_transport = fallback_transport
        self.total_timeout = total_timeout
        self._loop_slots = weakref.WeakKeyDictionary()

    async def search_for_zones(self, zone_names, limit_per_query=5, include_extended=False):
        queries = list(_BASE_QUERIES)
        if include_extended:
            queries.extend(_EXTENDED_QUERIES)
        for zone in zone_names:
            queries.extend([f'{zone} 건폐율', f'{zone} 건축제한'])
        return await self.search_queries(queries, limit=limit_per_query)

    async def search_for_building_type(self, building_type, zone_names, limit_per_query=5):
        queries = [f'{building_type} {suffix}' for suffix in
                   ['건폐율', '용적률', '높이제한', '건축제한', '주차']]
        queries.extend(f'{zone} {building_type}' for zone in zone_names[:2])
        return await self.search_queries(queries, limit=limit_per_query, timeout=60)

    async def search_queries(self, queries, limit=5, timeout=None, *, filter_results=True):
        if type(limit) is not int or limit < 1:
            raise ValueError('Search limit must be positive')
        budget = self.total_timeout if timeout is None else min(timeout, self.total_timeout)
        if not math.isfinite(budget) or budget <= 0:
            raise ValueError('Search timeout must be positive and finite')
        queries = list(dict.fromkeys(queries))
        if not all(isinstance(query, str) and query.strip() for query in queries):
            raise ValueError('Search queries must be nonblank strings')
        if queries and not self.base_url and not self.fallback_url:
            return {'articles': [], 'total_count': 0, 'errors': ['Law search is not configured']}
        loop = asyncio.get_running_loop()
        reference = self._loop_slots.get(loop)
        slots = reference() if reference else None
        if slots is None:
            slots = asyncio.Semaphore(5)
            # Neither an idle semaphore nor its bound event loop must survive a request lifecycle.
            self._loop_slots[loop] = weakref.ref(slots)
        tasks = [asyncio.create_task(self._query(query, limit, filter_results, slots)) for query in queries]
        if not tasks:
            return {'articles': [], 'total_count': 0, 'errors': []}
        try:
            done, pending = await asyncio.wait(tasks, timeout=budget)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        articles, errors = [], []
        # Query order is stable even though requests finish concurrently.
        for task in tasks:
            if task not in done:
                continue
            try:
                article = task.result()
                if article['results']:
                    articles.append(article)
            except (httpx.HTTPError, ValueError, TypeError):
                errors.append('Law search query failed or returned an invalid response')
        if pending:
            errors.append('Law search deadline exceeded; unfinished queries cancelled')
        return {'articles': articles, 'total_count': sum(len(a['results']) for a in articles),
                'errors': list(dict.fromkeys(errors))}

    async def _query(self, query, limit, filter_results, slots):
        async with slots:
            fallback = False
            if self.base_url:
                try:
                    payload = await self._post(self.base_url + '/api/search',
                        {'query': query, 'limit': limit}, self.transport)
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    fallback = True
            else:
                fallback = True
            if fallback:
                if not self.fallback_url:
                    raise ValueError('Law search provider unavailable')
                payload = await self._post(self.fallback_url + '/search',
                    {'query': query, 'limit': limit, 'mode': 'hybrid'}, self.fallback_transport)
            return {'query': query, 'results': self._articles(payload, fallback, filter_results)}

    @staticmethod
    async def _post(url, body, transport):
        async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(30, connect=5),
                                     follow_redirects=False) as client:
            response = await client.post(url, json=body)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _articles(payload, fallback, filter_results):
        if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
            raise ValueError('Invalid law search response')
        articles = []
        for raw in payload['results']:
            if not isinstance(raw, dict):
                raise ValueError('Invalid law article')
            json.dumps(raw, allow_nan=False)
            score = raw.get('score', 0) if fallback else raw.get('similarity', 1.0)
            if type(score) not in (int, float) or not math.isfinite(score):
                raise ValueError('Invalid law similarity')
            article = deepcopy(raw)
            for key in ('content', 'law_name', 'law_type', 'jo_name'):
                article[key] = raw.get(key, '')
            article['article'] = raw.get('article', article['jo_name'])
            article['hang_id'] = raw.get('id', '') if fallback else raw.get('hang_id', raw.get('id', ''))
            if not all(isinstance(article[key], str) for key in
                       ('content', 'law_name', 'law_type', 'jo_name', 'article', 'hang_id')):
                raise ValueError('Invalid law article fields')
            article['similarity'] = score
            article['source'] = 'ag-light' if fallback else raw.get('source', '')
            if not isinstance(article['source'], str):
                raise ValueError('Invalid law article source')
            if filter_results and (score < .25 or article['law_name'] == '수도법'):
                continue
            articles.append(article)
        return articles
