"""The one module that knows where the Law Agent is and how to ask it one question over A2A.

The Law Agent (agents/Lawagent, a2a-sdk 1.0) answers one JSON-RPC `SendMessage` per question: the
text part is `{"tool": ..., "args": ...}` and the completed task's status message carries the tool's
JSON verbatim (its reply metadata names the code version that answered). The editor sends the
network token (A2A_TOKEN) like every other caller and puts its trace record on the message so the
agent logs the hop. Nothing here restates a legal value: the tool's dict comes back as it is.
"""
from __future__ import annotations

import json
import os
from uuid import uuid4

import httpx

from backend.app.core.agent_network import network_headers

LAW_AGENT_URL_ENV = 'LAW_A2A_URL'
DEFAULT_URL = 'http://127.0.0.1:8301'
COMPLETED = 'TASK_STATE_COMPLETED'


class LawAgentUnavailable(RuntimeError):
    """The Law Agent could not be reached or did not speak A2A."""


class LawAgentError(RuntimeError):
    """The Law Agent answered, but with a refusal, a failed task or an error payload."""


def law_agent_url(env=os.environ) -> str:
    return (env.get(LAW_AGENT_URL_ENV) or DEFAULT_URL).rstrip('/')


async def ask(tool: str, args: dict, *, trace: dict | None = None, base_url: str | None = None,
              transport: httpx.AsyncBaseTransport | None = None, timeout: float = 180.0) -> dict:
    """`{tool, payload, task_id, version}` for one tool call; raises LawAgentUnavailable / LawAgentError."""
    base = (base_url or law_agent_url())
    message = {'messageId': uuid4().hex, 'role': 'ROLE_USER',
               'parts': [{'text': json.dumps({'tool': tool, 'args': args}, ensure_ascii=False)}]}
    if trace:
        message['metadata'] = {'trace': {key: str(value) for key, value in trace.items()}}
    body = {'jsonrpc': '2.0', 'id': uuid4().hex, 'method': 'SendMessage', 'params': {'message': message}}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5), transport=transport,
                                     headers={**network_headers(), 'Content-Type': 'application/json'},
                                     follow_redirects=False) as client:
            response = await client.post(base + '/', content=json.dumps(body, ensure_ascii=False).encode('utf-8'))
        reply = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise LawAgentUnavailable(f'Law Agent unreachable at {base}: {error}') from None
    if not isinstance(reply, dict):
        raise LawAgentUnavailable(f'Law Agent at {base} did not answer JSON-RPC')
    if isinstance(reply.get('error'), dict):
        raise LawAgentError(f'{tool}: {reply["error"].get("message") or reply["error"]}')
    task = _dict(_dict(reply.get('result')).get('task'))
    status = _dict(task.get('status'))
    state = status.get('state')
    text = ''.join(part.get('text', '') for part in _dict(status.get('message')).get('parts') or [] if isinstance(part, dict))
    if state != COMPLETED:
        raise LawAgentError(f'{tool}: {state or "no task"}: {text[:200]}')
    try:
        payload = json.loads(text) if text.strip() else {}
    except ValueError:
        raise LawAgentError(f'{tool}: non-JSON reply: {text[:200]}') from None
    if not isinstance(payload, dict):
        payload = {'value': payload}
    if payload.get('error'):
        raise LawAgentError(f'{tool}: {payload["error"]}')
    version = _dict(_dict(status.get('message')).get('metadata')).get('version')
    return {'tool': tool, 'payload': payload, 'task_id': task.get('id'), 'version': version if isinstance(version, str) else None}


def _dict(value):
    return value if isinstance(value, dict) else {}
