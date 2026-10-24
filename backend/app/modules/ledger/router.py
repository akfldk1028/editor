"""`/api/v1/platform/ledger`: agents and exporters post calls in, the 협업 view reads and tails them."""
from __future__ import annotations

import asyncio
import json
import re
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from backend.app.core.agent_network import token_accepted

from .service import Ledger

HEARTBEAT_S = 15.0
# A list or a stream sends each request and reply up to this many characters (a district review runs to hundreds of
# thousands); the whole call is GET /hops/{id}, which the transcript fetches when a clipped row is opened. At 32 KB a
# conversation's first read was 2.5 MB and took 7 s on 684-1 (2026-10-24); 2 KB is a readable preview.
LISTED_TEXT_CHARS = 2_048


def listed(row: dict, limit: int = LISTED_TEXT_CHARS) -> dict:
    """The row with each message text cut at `limit`, saying which side was cut (`texts_clipped`)."""
    clipped, out = {}, dict(row)
    for side, key in (('input', 'input_messages'), ('output', 'output_messages')):
        messages = row.get(key)
        if not isinstance(messages, list):
            continue
        kept = []
        for message in messages:
            if not isinstance(message, dict):
                kept.append(message)
                continue
            parts = []
            for part in message.get('parts') or []:
                text = part.get('content') if isinstance(part, dict) else None
                if isinstance(text, str) and len(text) > limit:
                    part = {**part, 'content': text[:limit]}
                    clipped[side] = True
                parts.append(part)
            kept.append({**message, 'parts': parts})
        out[key] = kept
    if clipped:
        out['texts_clipped'] = clipped
    return out
_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$')


def _scope(conversation_id, run_id, trace_id, project, branch) -> dict:
    for name, value in (('conversation_id', conversation_id), ('run_id', run_id), ('trace_id', trace_id), ('project', project), ('branch', branch)):
        if value is not None and not _ID.match(value):
            raise HTTPException(400, f'invalid {name}')
    if not any((conversation_id, run_id, trace_id, project)):
        raise HTTPException(400, 'name a conversation, run, trace or project')
    return {'conversation_id': conversation_id, 'run_id': run_id, 'trace_id': trace_id, 'project': project, 'branch': branch}


def sse(row: dict) -> str:
    return f'id: {row["id"]}\ndata: {json.dumps(listed(row), ensure_ascii=False, default=str)}\n\n'


async def stream_events(ledger: Ledger, scope: dict, since_id: int, *, heartbeat_s: float = HEARTBEAT_S, stop: asyncio.Event | None = None) -> AsyncIterator[str]:
    """Rows after `since_id` now, then every new row that matches the scope as it is recorded; a comment line keeps the
    connection alive while nothing happens. `stop` ends the stream (tests)."""
    last = since_id
    # A call is recorded twice on the same row (its start, then its end): a row the client holds is sent again when it
    # changes, so a running call turns finished without a reload.
    sent: dict[int, str] = {}
    queue = ledger.watch()
    try:
        if since_id:
            # The client already holds the rows up to `since_id` (from its first read, or before a reconnect): remember them
            # so their later changes reach it, and resend the ones that changed after its newest row was recorded.
            newest = ledger.store.get(since_id)
            mark = str(newest.get('recorded_at')) if newest else ''
            for row in ledger.rows(**scope, since_id=0, limit=500):
                if int(row['id']) > since_id:
                    break
                sent[int(row['id'])] = str(row.get('recorded_at'))
                if mark and str(row.get('recorded_at')) > mark:
                    yield sse(row)
        while not (stop and stop.is_set()):
            rows = ledger.rows(**scope, since_id=last, limit=200)
            for row in rows:
                last = max(last, int(row['id']))
                sent[int(row['id'])] = str(row.get('recorded_at'))
                yield sse(row)
            if rows:
                continue
            try:
                changed = await asyncio.wait_for(queue.get(), timeout=heartbeat_s)
            except asyncio.TimeoutError:
                yield ': keep-alive\n\n'
                continue
            if isinstance(changed, int) and changed in sent:
                row = ledger.store.get(changed)
                if row and str(row.get('recorded_at')) != sent[changed]:
                    sent[changed] = str(row.get('recorded_at'))
                    yield sse(row)
    finally:
        ledger.unwatch(queue)


def create_ledger_router(ledger: Ledger, allowed_origin: str) -> APIRouter:
    router = APIRouter(prefix='/ledger', tags=['ledger'])

    def network_only(request: Request) -> None:
        if not token_accepted(request.headers.get('authorization')):
            raise HTTPException(401, 'network token required')

    async def body_of(request: Request, cap: int = 4 * 1024 * 1024) -> dict:
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > cap:
                raise HTTPException(413, 'record too large')
            chunks.append(chunk)
        try:
            value = json.loads(b''.join(chunks))
        except ValueError:
            raise HTTPException(400, 'invalid JSON') from None
        if not isinstance(value, dict):
            raise HTTPException(400, 'expected a JSON object')
        return value

    @router.post('/hops', status_code=201)
    async def post_hop(request: Request):
        """One hop as agents/a2a_common records it (plus request_text/response_text); bearer = the network token."""
        network_only(request)
        try:
            # A hop carries its request and reply texts whole (up to 8 MiB each, a2a_common HOP_TEXT_LIMIT).
            row = ledger.ingest_hop(await body_of(request, cap=24 * 1024 * 1024))
        except (ValidationError, ValueError, TypeError) as exc:
            raise HTTPException(422, f'invalid hop record: {type(exc).__name__}') from None
        return {'id': row['id']}

    @router.post('/v1/traces')
    async def post_traces(request: Request):
        """OTLP/HTTP JSON traces; spans that name an agent or tool (gen_ai.*) are recorded, the rest ignored."""
        network_only(request)
        try:
            count = ledger.ingest_otlp(await body_of(request, cap=16 * 1024 * 1024))
        except (ValidationError, ValueError, TypeError) as exc:
            raise HTTPException(422, f'invalid trace export: {type(exc).__name__}') from None
        return {'partialSuccess': {}, 'accepted': count}

    # A plain def: FastAPI runs it in its thread pool. Reading and listing a conversation's hops (2 MB, 2 s) on the
    # event loop held every other request of the page - the map's tiles and parcel waited behind it (2026-10-17).
    @router.get('/hops')
    def get_hops(conversation_id: str | None = None, run_id: str | None = None, trace_id: str | None = None, project: str | None = None,
                       branch: str | None = None, since_id: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=500)):
        scope = _scope(conversation_id, run_id, trace_id, project, branch)
        return {'hops': [listed(row) for row in ledger.rows(**scope, since_id=since_id, limit=limit)], 'latest_id': ledger.latest_id()}

    @router.get('/hops/stream')
    async def stream_hops(request: Request, conversation_id: str | None = None, run_id: str | None = None, trace_id: str | None = None,
                          project: str | None = None, branch: str | None = None, since_id: int = Query(default=0, ge=0)):
        origin = request.headers.get('origin')
        if origin and origin != allowed_origin:
            raise HTTPException(403, 'Cross-origin stream is not allowed')
        scope = _scope(conversation_id, run_id, trace_id, project, branch)
        last_event = request.headers.get('last-event-id')
        start = int(last_event) if last_event and last_event.isdigit() else since_id
        return StreamingResponse(stream_events(ledger, scope, start), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

    # After /hops/stream: a path segment that is not a number is never read as a call id.
    @router.get('/hops/{hop_id}')
    async def get_hop(hop_id: int):
        """One call whole: the request and reply the list and the stream cut at LISTED_TEXT_CHARS."""
        row = ledger.store.get(hop_id)
        if row is None:
            raise HTTPException(404, 'call not found')
        return row

    return router
