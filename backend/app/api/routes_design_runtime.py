"""Serve the absorbed design engine through the Editor HTTP boundary."""
from __future__ import annotations

import logging
import json
import os
from io import BytesIO

from anyio import CancelScope
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from starlette.concurrency import run_in_threadpool
from backend.app.modules.design.public_urls import normalize_design_urls
from backend.app.core.agent_network import token_accepted

logger = logging.getLogger(__name__)
DELIVERED_EXPORT = 'maas/delivered-mass-export'
BUNDLE_LIMIT = 512 * 1024 * 1024


def _agent_only(path):
    # Agents on other servers carry A2A_TOKEN: planning operations, and the delivered
    # Mass bundle/files/package doors (the bare export door keeps its same-host contract).
    path = path.rstrip('/')
    return path == 'masterplan/operations' or path.startswith(DELIVERED_EXPORT + '/')


async def _capped_body(request, limit):
    declared = request.headers.get('content-length', '')
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, 'Design request is too large')
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, 'Design request is too large')
        chunks.append(chunk)
    return b''.join(chunks)


def _dispatch(method, path, query, headers, body):
    from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime
    ensure_design_runtime()
    from django.db import close_old_connections
    from django.http import HttpRequest, Http404, QueryDict
    from django.urls import Resolver404, resolve

    close_old_connections()
    request = HttpRequest()
    request.method = method
    request.path = '/api/v1/design/' + path
    request.path_info = '/' + path
    request.GET = QueryDict(query)
    request._body = body
    request._stream = BytesIO(body)
    request.META = {'HTTP_' + key.upper().replace('-', '_'): value for key, value in headers.items()}
    request.META['CONTENT_TYPE'] = headers.get('content-type', 'application/json')
    request.META['SERVER_NAME'] = 'localhost'
    request.META['SERVER_PORT'] = '80'
    try:
        target = '/' + path.rstrip('/')
        if not target.endswith('/stream'):
            target += '/'
        match = resolve(target, urlconf='backend.app.api.design_runtime.urls')
        response = match.func(request, *match.args, **match.kwargs)
    except (Resolver404, Http404):
        raise HTTPException(404, 'Design operation or artifact not found') from None
    finally:
        close_old_connections()
    return response


def _next_chunk(iterator):
    from django.db import close_old_connections
    try:
        return next(iterator), False
    except StopIteration:
        return None, True
    finally:
        close_old_connections()


async def _stream_response(response):
    iterator = iter(response.streaming_content)
    try:
        while True:
            chunk, exhausted = await run_in_threadpool(_next_chunk, iterator)
            if exhausted:
                break
            yield chunk
    finally:
        # A disconnected subscriber must release its journal/file iterator even
        # when ASGI cancels the response task; it does not own the background job.
        with CancelScope(shield=True):
            await run_in_threadpool(response.close)


def create_design_runtime_router(*, public_origin=None):
    router = APIRouter(prefix='/api/v1/design', tags=['design-generation'])
    origin = public_origin or os.environ.get('EDITOR_PUBLIC_URL', 'http://127.0.0.1:5173')

    @router.api_route('/{path:path}', methods=['GET', 'POST'])
    async def design_operation(path: str, request: Request):
        if _agent_only(path) and not token_accepted(request.headers.get('authorization')):
            raise HTTPException(401, 'Agent network token required')
        if request.method != 'GET' and (request.headers.get('sec-fetch-site') == 'cross-site' or (
            request.headers.get('origin') and request.headers['origin'] != origin
        )):
            raise HTTPException(403, 'Cross-origin changes are not allowed')
        # A delivered Mass bundle is a zip of the cycle's files, not a JSON object.
        bundle = path.rstrip('/') == DELIVERED_EXPORT + '/bundle'
        if bundle:
            body = await _capped_body(request, BUNDLE_LIMIT)
        else:
            body = await request.body()
            if len(body) > 20 * 1024 * 1024:
                raise HTTPException(413, 'Design request is too large')
        if request.method == 'POST' and body and not bundle:
            try:
                value = json.loads(body)
                if not isinstance(value, dict):
                    raise ValueError('Expected an object')
                json.dumps(value, allow_nan=False)
            except (ValueError, TypeError, UnicodeError):
                raise HTTPException(400, 'Expected a finite JSON object') from None
        try:
            response = await run_in_threadpool(_dispatch, request.method, path,
                request.url.query, dict(request.headers), body)
        except HTTPException:
            raise
        except Exception:
            logger.exception('Design operation failed: %s', path)
            raise HTTPException(500, 'Design operation failed; check the Editor backend log') from None
        headers = dict(response.items())
        headers['X-Content-Type-Options'] = 'nosniff'
        headers.setdefault('Cache-Control', 'no-store')
        if response.streaming:
            return StreamingResponse(_stream_response(response), status_code=response.status_code, headers=headers)
        content = bytes(response.content)
        response.close()
        # Planning operations are an identity-hashed envelope (result_hash over
        # result); rewriting URLs inside it would break the caller's check.
        identity_envelope = path.rstrip('/') == 'masterplan/operations'
        if headers.get('Content-Type', '').split(';', 1)[0] == 'application/json' and not identity_envelope:
            content = json.dumps(normalize_design_urls(json.loads(content)), ensure_ascii=False).encode('utf-8')
            headers.pop('Content-Length', None)
        return Response(content, status_code=response.status_code, headers=headers)

    return router
