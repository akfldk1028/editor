"""An autogen model client backed by the logged-in Claude Code CLI (local OAuth, no API key).

Each `create` runs `claude -p` once in headless mode: the conversation goes in on stdin, system
messages become the session's system prompt, Claude Code's own tools, settings, hooks and MCP
servers are switched off, and the answer comes back as JSON. Agent tools are offered as a
schema and answered as structured output, so an AssistantAgent's function calls work as with
an API client. The child process gets the parent's environment minus any Anthropic API key or
token, so the CLI uses the developer's OAuth login, never a placeholder key.

Local development only: core.model_auth selects it; deployment uses API-key clients.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from typing import Any, AsyncGenerator, Literal, Mapping, Optional, Sequence, Union

from autogen_core import CancellationToken, Component, FunctionCall
from autogen_core.models import (
    AssistantMessage,
    ChatCompletionClient,
    CreateResult,
    FunctionExecutionResultMessage,
    LLMMessage,
    ModelFamily,
    ModelInfo,
    RequestUsage,
    SystemMessage,
    UserMessage,
)
from autogen_core.tools import Tool, ToolSchema
from pydantic import BaseModel
from typing_extensions import Self

PROVIDER = 'backend.app.adapters.cli_model_client.ClaudeCodeChatCompletionClient'
# The CLI must authenticate with the developer's login, not with whatever key the shell carries.
_STRIPPED_ENV = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX')
_TURN_SCHEMA = {
    'type': 'object',
    'properties': {
        'kind': {'type': 'string', 'enum': ['text', 'tool_calls']},
        'text': {'type': 'string'},
        'calls': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'name': {'type': 'string'}, 'arguments': {'type': 'object'}}, 'required': ['name', 'arguments']}},
    },
    'required': ['kind'],
}


class ClaudeCodeClientConfig(BaseModel):
    model: Optional[str] = None
    timeout_s: float = 300.0
    executable: str = 'claude'


class ClaudeCodeChatCompletionClient(ChatCompletionClient, Component[ClaudeCodeClientConfig]):
    component_type = 'model'
    component_provider_override = PROVIDER
    component_config_schema = ClaudeCodeClientConfig

    def __init__(self, model: Optional[str] = None, timeout_s: float = 300.0, executable: str = 'claude', runner=None):
        if not timeout_s > 0:
            raise ValueError('timeout_s must be positive')
        self._model, self._timeout_s, self._executable = model, float(timeout_s), executable
        self._runner = runner or _run_cli
        self._last = RequestUsage(prompt_tokens=0, completion_tokens=0)
        self._total = RequestUsage(prompt_tokens=0, completion_tokens=0)
        self._model_info = ModelInfo(vision=False, function_calling=True, json_output=True,
                                     family=ModelFamily.UNKNOWN, structured_output=True)

    async def create(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Tool | ToolSchema] = [],
        tool_choice: Tool | Literal['auto', 'required', 'none'] = 'auto',
        json_output: Optional[bool | type[BaseModel]] = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: Optional[CancellationToken] = None,
    ) -> CreateResult:
        system, transcript = _render(messages)
        schemas = [] if tool_choice == 'none' else [_schema(t) for t in tools]
        if isinstance(tool_choice, Tool):
            schemas = [_schema(tool_choice)]
        schema = None
        if schemas:
            transcript += '\n\n' + _tool_instructions(schemas, required=tool_choice != 'auto')
            schema = _TURN_SCHEMA
        elif isinstance(json_output, type) and issubclass(json_output, BaseModel):
            schema = json_output.model_json_schema()
        elif json_output:
            transcript += '\n\nAnswer with one JSON value only.'
        command = [self._executable, '-p', '--output-format', 'json', '--tools', '', '--no-session-persistence',
                   '--setting-sources', '', '--strict-mcp-config']
        if self._model:
            command += ['--model', self._model]
        if schema is not None:
            command += ['--json-schema', json.dumps(schema, ensure_ascii=False)]
        reply = await self._runner(command, system, transcript, self._timeout_s, cancellation_token)
        if reply.get('is_error') or reply.get('subtype') != 'success':
            raise RuntimeError('Claude Code CLI returned an error: ' + str(reply.get('result') or reply.get('subtype'))[:300])
        usage = reply.get('usage') or {}
        self._last = RequestUsage(
            prompt_tokens=int(usage.get('input_tokens') or 0) + int(usage.get('cache_read_input_tokens') or 0)
            + int(usage.get('cache_creation_input_tokens') or 0),
            completion_tokens=int(usage.get('output_tokens') or 0))
        self._total = RequestUsage(prompt_tokens=self._total.prompt_tokens + self._last.prompt_tokens,
                                   completion_tokens=self._total.completion_tokens + self._last.completion_tokens)
        structured = reply.get('structured_output')
        if schemas:
            if not isinstance(structured, dict):
                raise RuntimeError('Claude Code CLI returned no structured turn')
            calls = structured.get('calls') or []
            if structured.get('kind') == 'tool_calls' and calls:
                known = {s['name'] for s in schemas}
                unknown = [c.get('name') for c in calls if c.get('name') not in known]
                if unknown:
                    raise RuntimeError(f'Claude Code CLI called unknown tools: {unknown}')
                return CreateResult(finish_reason='function_calls', usage=self._last, cached=False, content=[
                    FunctionCall(id='call_' + uuid.uuid4().hex[:12], name=c['name'],
                                 arguments=json.dumps(c.get('arguments') or {}, ensure_ascii=False)) for c in calls])
            return CreateResult(finish_reason='stop', content=str(structured.get('text') or ''),
                                usage=self._last, cached=False)
        if schema is not None:
            return CreateResult(finish_reason='stop', content=json.dumps(structured, ensure_ascii=False),
                                usage=self._last, cached=False)
        return CreateResult(finish_reason='stop', content=str(reply.get('result') or ''), usage=self._last, cached=False)

    async def create_stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Tool | ToolSchema] = [],
        tool_choice: Tool | Literal['auto', 'required', 'none'] = 'auto',
        json_output: Optional[bool | type[BaseModel]] = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: Optional[CancellationToken] = None,
    ) -> AsyncGenerator[Union[str, CreateResult], None]:
        # One headless call is one answer; the stream carries it whole.
        result = await self.create(messages, tools=tools, tool_choice=tool_choice, json_output=json_output,
                                   extra_create_args=extra_create_args, cancellation_token=cancellation_token)
        if isinstance(result.content, str) and result.content:
            yield result.content
        yield result

    async def close(self) -> None:
        return None

    def actual_usage(self) -> RequestUsage:
        return self._last

    def total_usage(self) -> RequestUsage:
        return self._total

    def count_tokens(self, messages: Sequence[LLMMessage], *, tools: Sequence[Tool | ToolSchema] = []) -> int:
        system, transcript = _render(messages)
        return (len(system) + len(transcript)) // 4   # a rough estimate; the CLI reports real usage

    def remaining_tokens(self, messages: Sequence[LLMMessage], *, tools: Sequence[Tool | ToolSchema] = []) -> int:
        return max(0, 200_000 - self.count_tokens(messages, tools=tools))

    @property
    def capabilities(self):  # type: ignore[override]
        return self._model_info

    @property
    def model_info(self) -> ModelInfo:
        return self._model_info

    def _to_config(self) -> ClaudeCodeClientConfig:
        return ClaudeCodeClientConfig(model=self._model, timeout_s=self._timeout_s, executable=self._executable)

    @classmethod
    def _from_config(cls, config: ClaudeCodeClientConfig) -> Self:
        return cls(model=config.model, timeout_s=config.timeout_s, executable=config.executable)


def _render(messages):
    """System prompt and a plain transcript of the conversation, tool calls and results included."""
    system, lines = [], []
    for message in messages:
        if isinstance(message, SystemMessage):
            system.append(message.content)
        elif isinstance(message, UserMessage):
            if not isinstance(message.content, str):
                if any(not isinstance(part, str) for part in message.content):
                    raise ValueError('the Claude Code CLI client does not accept images')
                text = '\n'.join(message.content)
            else:
                text = message.content
            lines.append(f'[{message.source}]\n{text}')
        elif isinstance(message, AssistantMessage):
            if isinstance(message.content, str):
                lines.append(f'[assistant {message.source}]\n{message.content}')
            else:
                calls = '\n'.join(f'- {c.name}({c.arguments}) id={c.id}' for c in message.content)
                lines.append(f'[assistant {message.source} called tools]\n{calls}')
        elif isinstance(message, FunctionExecutionResultMessage):
            for item in message.content:
                state = 'error' if item.is_error else 'result'
                lines.append(f'[tool {state} {item.name} id={item.call_id}]\n{item.content}')
        else:
            raise ValueError(f'unsupported message type {type(message).__name__}')
    return '\n\n'.join(system), '\n\n'.join(lines)


def _schema(tool):
    if isinstance(tool, Tool):
        return dict(tool.schema)
    return dict(tool)


def _tool_instructions(schemas, *, required):
    listing = json.dumps([{'name': s['name'], 'description': s.get('description', ''),
                           'parameters': s.get('parameters', {})} for s in schemas], ensure_ascii=False)
    rule = 'You must call at least one tool.' if required else 'Call tools only when they are needed.'
    return ('Tools you may call (answer kind "tool_calls" with their name and JSON arguments; their results '
            'come back in the next turn), or answer kind "text" with your reply. ' + rule + '\n' + listing)


async def _run_cli(command, system, transcript, timeout_s, cancellation_token):
    executable = shutil.which(command[0])
    if executable is None:
        raise RuntimeError('Claude Code CLI not found on PATH; log in with `claude` or set EDITOR_MODEL_AUTH=api_key')
    env = {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV}
    with tempfile.TemporaryDirectory(prefix='editor-cli-model-') as folder:
        prompt_file = os.path.join(folder, 'system.txt')
        with open(prompt_file, 'w', encoding='utf-8') as handle:
            handle.write(system or 'You are a helpful assistant.')
        full = [executable, *command[1:], '--system-prompt-file', prompt_file]
        process = subprocess.Popen(full, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   cwd=folder, env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if cancellation_token is not None:
            cancellation_token.add_callback(process.kill)
        try:
            out, err = await asyncio.to_thread(process.communicate, transcript.encode('utf-8'), timeout_s)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise TimeoutError(f'Claude Code CLI did not answer within {timeout_s:.0f} s')
        except asyncio.CancelledError:
            # A caller's deadline (asyncio.timeout, a run's CancellationToken) must stop the model call too.
            process.kill()
            raise
    if process.returncode != 0 and not out:
        raise RuntimeError('Claude Code CLI failed: ' + err.decode('utf-8', 'replace')[-300:])
    return json.loads(out.decode('utf-8'))


__all__ = ['PROVIDER', 'ClaudeCodeChatCompletionClient', 'ClaudeCodeClientConfig']
