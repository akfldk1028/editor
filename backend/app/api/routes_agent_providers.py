"""Bounded HTTP transport for the absorbed law and site calculation owners."""
import importlib
import json
import logging
import os
from io import BytesIO

from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool


OPERATIONS = {
    'law': frozenset({'review-design-state', 'review-program', 'review-facilities',
        'facility-criteria', 'building-uses', 'fire-requirements', 'use-research-routes',
        'ordinance-candidates', 'parking-design-rules', 'parking-count', 'parcel-limits', 'audit'}),
    'land': frozenset({'parcel-geometry', 'roads', 'datum', 'basement-storey'}),
    'design': frozenset({'research-bundle'}),
}
# A candidate mesh travels inside the research-bundle request; the other operations stay small.
BODY_LIMITS = {('design', 'research-bundle'): 20 * 1024 * 1024}
DEFAULT_BODY_LIMIT = 2 * 1024 * 1024
logger = logging.getLogger(__name__)


def _dispatch(domain, operation, body):
    if (domain, operation) == ('law', 'audit'):
        from backend.app.modules.massing.audit_service import audit_pool
        result, status = audit_pool(json.loads(body))
        return json.dumps(result, ensure_ascii=False).encode('utf-8'), status
    from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime
    ensure_design_runtime()
    from django.http import HttpRequest
    request = HttpRequest()
    request.method = 'POST'
    request._body = body
    request._stream = BytesIO(body)
    module = importlib.import_module('backend.app.api.agent_providers.' + domain)
    response = getattr(module, operation.replace('-', '_'))(request)
    try:
        return bytes(response.content), response.status_code
    finally:
        response.close()


def create_agent_provider_router(*, public_origin=None):
    router = APIRouter(prefix='/api/v1', tags=['agent-domain-providers'])
    origin = public_origin or os.environ.get('EDITOR_PUBLIC_URL', 'http://127.0.0.1:5173')

    @router.post('/{domain}/agent/{operation}')
    async def provider_operation(domain: str, operation: str, request: Request):
        if operation not in OPERATIONS.get(domain, ()):
            raise HTTPException(404, 'Unknown domain provider operation')
        if request.headers.get('sec-fetch-site') == 'cross-site' or (
                request.headers.get('origin') and request.headers['origin'] != origin):
            raise HTTPException(403, 'Cross-origin provider requests are not allowed')
        limit = BODY_LIMITS.get((domain, operation), DEFAULT_BODY_LIMIT)
        declared = request.headers.get('content-length')
        if declared and declared.isdecimal() and int(declared) > limit:
            raise HTTPException(413, 'Provider request is too large')
        body = await request.body()
        if len(body) > limit:
            raise HTTPException(413, 'Provider request is too large')
        try:
            value = json.loads(body)
            if not isinstance(value, dict):
                raise ValueError('Expected an object')
            json.dumps(value, allow_nan=False)
        except (ValueError, TypeError, UnicodeError):
            raise HTTPException(400, 'Expected a finite JSON object') from None
        try:
            content, status = await run_in_threadpool(_dispatch, domain, operation, body)
        except Exception:
            logger.exception('Domain provider operation failed: %s/%s', domain, operation)
            raise HTTPException(502, 'Domain provider failed; check the Editor backend log') from None
        return Response(content, status_code=status, media_type='application/json',
                        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    return router
