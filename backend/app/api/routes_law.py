import json
import os
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.adapters.law_workspace import LawWorkspaceClient, LawWorkspaceUnavailable


class SearchRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    q: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=10, ge=1, le=100)

    @field_validator('q')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Search query is required')
        return value.strip()


def create_law_router(*, provider=None, public_origin=None):
    service = provider or LawWorkspaceClient()
    origin = public_origin or os.environ.get('EDITOR_PUBLIC_URL', 'http://127.0.0.1:5173')
    router = APIRouter(prefix='/api/v1/law', tags=['law'])

    def check_origin(request):
        if request.headers.get('sec-fetch-site') == 'cross-site' or (request.headers.get('origin') and request.headers['origin'] != origin):
            raise HTTPException(403, 'Cross-origin search is not allowed')

    async def search_result(query, limit, domain=None):
        started = time.monotonic()
        try:
            result = await service.search(query, limit, domain)
            if not isinstance(result.get('results'), list):
                raise LawWorkspaceUnavailable('검색 결과 형식이 올바르지 않습니다.')
            return {**result, 'query': query, 'total_count': len(result['results']),
                    'response_time': round((time.monotonic() - started) * 1000, 2)}
        except LawWorkspaceUnavailable as error:
            raise HTTPException(503, str(error)) from None

    @router.post('/search')
    async def search(body: SearchRequest, request: Request):
        check_origin(request)
        return await search_result(body.q, body.limit)

    @router.post('/domain/{domain}/search')
    async def domain_search(domain: str, body: SearchRequest, request: Request):
        check_origin(request)
        return await search_result(body.q, body.limit, domain)

    @router.get('/search/stream')
    async def stream(request: Request, query: str = Query(min_length=1, max_length=2000),
                     limit: int = Query(default=10, ge=1, le=100), domain_id: str | None = None):
        check_origin(request)
        if not query.strip():
            raise HTTPException(422, 'Search query is required')

        async def events():
            yield 'data: ' + json.dumps({'status': 'started', 'progress': 0}) + '\n\n'
            try:
                result = await search_result(query.strip(), limit, domain_id)
                event = {**result, 'status': 'complete', 'result_count': result['total_count']}
            except HTTPException as error:
                event = {'status': 'error', 'message': error.detail}
            yield 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'

        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

    async def provider_result(operation):
        try:
            return await operation
        except LawWorkspaceUnavailable as error:
            raise HTTPException(503, str(error)) from None

    @router.get('/domains')
    async def domains():
        return await provider_result(service.domains())

    @router.get('/health')
    async def health():
        return await provider_result(service.health())

    @router.get('/article')
    async def article(full_id: str = Query(min_length=1, max_length=1000)):
        return await provider_result(service.article(full_id))

    return router
