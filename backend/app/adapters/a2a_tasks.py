"""The tasks an agent still holds, read with the official A2A `ListTasks` (a2a-sdk 1.0, JSON-RPC).

Every agent server keeps its tasks in an `InMemoryTaskStore` for as long as the process lives: the request the
Orchestrator sent (the task's first user message) and the full reply (`status.message`), uncut. The Orchestrator's
own record of a run cuts each message at 8,000 characters, so this is where the 협업 view fetches the whole text
of a reply when the record was cut. An agent that restarted holds nothing — the view says so.
"""
from __future__ import annotations

import json
import os
from uuid import uuid4

import httpx

from backend.app.core.agent_network import network_headers
from backend.app.modules.platform.routing.cards import host_id
from backend.app.modules.platform.status.registry import Registry, base_url

_registry = Registry()
TIMEOUT_S = 10.0
MAX_PAGE = 50


class AgentTasksUnavailable(Exception):
    """The agent is not registered, not reachable, or did not answer the A2A call."""


class AgentTaskNotFound(Exception):
    """The agent answered but holds no such task (it restarted since, or the id is another's)."""


def rpc_url(agent: str, *, registry: Registry = _registry, env=os.environ) -> str | None:
    entry = next((e for e in registry.entries() if e.get('id') == host_id(agent) and e.get('kind') == 'agent'), None)
    base = base_url(entry, env) if entry else None
    return f'{base}/' if base else None


def _text(message: dict | None) -> str:
    return ''.join(part.get('text', '') for part in (message or {}).get('parts') or [] if isinstance(part, dict))


def _dict(value):
    return value if isinstance(value, dict) else {}


def task_record(task: dict) -> dict:
    """One task as the view reads it: its state, when it ended, the tool it ran, the request it got and the full reply."""
    status = _dict(task.get('status'))
    reply = _dict(status.get('message'))
    history = [m for m in task.get('history') or [] if isinstance(m, dict)]
    asked = next((m for m in history if m.get('role') == 'ROLE_USER'), None)
    state = str(status.get('state') or '')
    return {
        'id': str(task.get('id') or ''), 'context_id': task.get('contextId') if isinstance(task.get('contextId'), str) else None,
        'state': state.removeprefix('TASK_STATE_').lower() or 'unknown', 'at': status.get('timestamp') if isinstance(status.get('timestamp'), str) else None,
        'tool': _dict(reply.get('metadata')).get('tool') if isinstance(_dict(reply.get('metadata')).get('tool'), str) else None,
        'request_text': _text(asked), 'response_text': _text(reply),
    }


async def _rpc(agent: str, method: str, params: dict, *, registry: Registry, transport, env) -> dict:
    url = rpc_url(agent, registry=registry, env=env)
    if not url:
        raise AgentTasksUnavailable(f'{agent} is not a registered agent')
    body = {'jsonrpc': '2.0', 'id': uuid4().hex, 'method': method, 'params': params}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_S, connect=3), transport=transport,
                                     headers={**network_headers(env), 'Content-Type': 'application/json'}, follow_redirects=False) as client:
            response = await client.post(url, content=json.dumps(body).encode('utf-8'))
        reply = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise AgentTasksUnavailable(f'{agent} unreachable: {type(error).__name__}') from None
    if not isinstance(reply, dict):
        raise AgentTasksUnavailable(f'{agent} did not answer JSON-RPC')
    return reply


async def list_tasks(agent: str, *, page_size: int = 20, history_length: int = 2, registry: Registry = _registry,
                     transport: httpx.AsyncBaseTransport | None = None, env=os.environ) -> list[dict]:
    """The agent's tasks, newest first as the agent lists them; raises AgentTasksUnavailable when it cannot answer."""
    reply = await _rpc(agent, 'ListTasks', {'pageSize': max(1, min(page_size, MAX_PAGE)), 'historyLength': max(0, history_length)},
                       registry=registry, transport=transport, env=env)
    if isinstance(reply.get('error'), dict):
        raise AgentTasksUnavailable(f'{agent} refused ListTasks')
    tasks = _dict(reply.get('result')).get('tasks')
    return [task_record(task) for task in tasks or [] if isinstance(task, dict)]


async def get_task(agent: str, task_id: str, *, history_length: int = 2, registry: Registry = _registry,
                   transport: httpx.AsyncBaseTransport | None = None, env=os.environ) -> dict:
    """One task by its A2A id (the id the Orchestrator recorded for the call); AgentTaskNotFound when the agent no longer holds it."""
    reply = await _rpc(agent, 'GetTask', {'id': task_id, 'historyLength': max(0, history_length)}, registry=registry, transport=transport, env=env)
    error = reply.get('error')
    if isinstance(error, dict):
        if error.get('code') == -32001 or 'not found' in str(error.get('message', '')).lower():
            raise AgentTaskNotFound(f'{agent} holds no task {task_id}')
        raise AgentTasksUnavailable(f'{agent} refused GetTask')
    result = _dict(reply.get('result'))
    task = result.get('task') if isinstance(result.get('task'), dict) else result
    if not isinstance(task, dict) or not task.get('id'):
        raise AgentTaskNotFound(f'{agent} holds no task {task_id}')
    return task_record(task)
