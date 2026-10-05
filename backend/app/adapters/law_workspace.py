import os
import re
from urllib.parse import quote

import httpx

from backend.app.adapters.law_search import LawSearchClient


class LawWorkspaceUnavailable(Exception):
    pass


class LawWorkspaceClient:
    def __init__(self, base_url=None, fallback_url=None, *, transport=None):
        self.base_url = base_url or os.environ.get('LAW_BACKEND_URL')
        self.fallback_url = fallback_url or os.environ.get('AG_LIGHT_URL')
        self.transport = transport

    async def request(self, base, path, body=None):
        if not base:
            raise LawWorkspaceUnavailable('법규 서비스가 설정되지 않았습니다.')
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=5), transport=self.transport,
                                         follow_redirects=False) as client:
                response = await client.request('GET' if body is None else 'POST', base.rstrip('/') + path, json=body)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError()
                return data
        except (httpx.HTTPError, ValueError):
            raise LawWorkspaceUnavailable('법규 서비스 응답을 확인하지 못했습니다.') from None

    async def search(self, query, limit, domain=None):
        fallback = not self.base_url
        try:
            if domain:
                # A global fallback would silently discard the user's selected domain.
                data = await self.request(self.base_url, '/api/domain/' + quote(domain, safe='') + '/search',
                                          {'query': query, 'limit': limit})
                fallback = False
            else:
                if self.base_url:
                    try:
                        data = await LawSearchClient._post(self.base_url.rstrip('/') + '/api/search',
                            {'query': query, 'limit': limit}, self.transport)
                    except (httpx.ConnectError, httpx.ConnectTimeout):
                        fallback = True
                if fallback:
                    if not self.fallback_url:
                        raise LawWorkspaceUnavailable('법규 검색 서비스가 설정되지 않았습니다.')
                    data = await LawSearchClient._post(self.fallback_url.rstrip('/') + '/search',
                        {'query': query, 'limit': limit, 'mode': 'hybrid'}, self.transport)
            articles = LawSearchClient._articles(data, fallback, False)
            for article in articles:
                stages = article.get('stages')
                article['stages'] = stages if isinstance(stages, list) and all(isinstance(stage, str) for stage in stages) else []
            return {**data, 'results': articles}
        except (httpx.HTTPError, ValueError, TypeError):
            raise LawWorkspaceUnavailable('법규 검색 서비스를 사용할 수 없습니다.') from None

    async def domains(self):
        if not self.base_url:
            return {'domains': []}
        return await self.request(self.base_url, '/api/domains')

    async def health(self):
        base = self.base_url or self.fallback_url
        data = await self.request(base, '/api/health' if self.base_url else '/health')
        if data.get('ready') is False or data.get('error') or data.get('status') not in ('ok', 'healthy', True):
            raise LawWorkspaceUnavailable('법규 검색 서비스가 준비되지 않았습니다.')
        return {'ready': True, 'status': 'ok'}

    async def article(self, full_id):
        parts = full_id.split('::') if '::' in full_id else full_id.split('_', 1)
        law = parts[0]
        number = next((part for part in parts[1:] if re.fullmatch(r'제\d+조(?:의\d+)?', part)), None)
        if not number:
            raise LawWorkspaceUnavailable('조문 식별자를 확인하지 못했습니다.')
        found = await self.request(self.fallback_url, '/law/search', {'query': law, 'display': 5})
        matches = found.get('results', [])
        if not isinstance(matches, list) or not all(isinstance(item, dict) for item in matches):
            raise LawWorkspaceUnavailable('법령 검색 결과 형식이 올바르지 않습니다.')
        # Never choose an arbitrary first law when the provider returns ambiguous results.
        exact = [item for item in matches if (item.get('name') or item.get('law_name') or item.get('법령명한글')) == law]
        if exact:
            matches = exact
        if len(matches) != 1 or not matches[0].get('mst'):
            raise LawWorkspaceUnavailable('법령을 하나로 식별하지 못했습니다.')
        returned_name = matches[0].get('name') or matches[0].get('law_name') or matches[0].get('법령명한글')
        if returned_name and returned_name != law:
            raise LawWorkspaceUnavailable('요청한 법령과 검색 결과가 일치하지 않습니다.')
        body = await self.request(self.fallback_url, '/law/text', {'mst': matches[0]['mst'], 'jo': number})
        content = body.get('text')
        if not isinstance(content, str) or not content.strip():
            raise LawWorkspaceUnavailable('조문 원문이 없습니다.')
        prefix = f'{law}::{number}'
        chunks = re.split(r'(?m)^([①-⑳])\s*', content.strip())
        hangs = []
        for index in range(1, len(chunks), 2):
            hangs.append({'full_id': f'{prefix}::{chunks[index]}', 'number': chunks[index],
                          'content': chunks[index + 1].strip(), 'unit_path': None, 'hos': []})
        if not hangs:
            hangs = [{'full_id': prefix, 'number': '', 'content': content, 'unit_path': None, 'hos': []}]
        return {'jo_prefix': prefix, 'law_name': law, 'law_type': '',
                'jo': {'full_id': prefix, 'number': number, 'title': None, 'content': chunks[0].strip() or None,
                       'law_name': law, 'unit_path': None},
                'hangs': hangs, 'hang_count': len(hangs), 'ho_count': 0, 'source': 'worker_api'}
