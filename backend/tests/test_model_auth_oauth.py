"""Local OAuth (Claude Code CLI login) for development, API keys for deployment."""
import asyncio
import json

import pytest
from autogen_core import FunctionCall
from autogen_core.models import (AssistantMessage, FunctionExecutionResult, FunctionExecutionResultMessage,
                                 SystemMessage, UserMessage)
from pydantic import BaseModel

from backend.app.adapters import cli_model_client
from backend.app.adapters.cli_model_client import PROVIDER, ClaudeCodeChatCompletionClient
from backend.app.adapters.workspace.credentials import apply_environment
from backend.app.core.model_auth import model_auth_mode

OPENAI = {'provider': 'autogen_ext.models.openai.OpenAIChatCompletionClient', 'component_type': 'model',
          'config': {'model': 'gpt-4o-mini'}}
ANTHROPIC = {'provider': 'autogen_ext.models.anthropic.AnthropicChatCompletionClient', 'component_type': 'model',
             'config': {'model': 'claude-sonnet-4-5'}}
KEYS = [{'name': 'OPENAI_API_KEY', 'value': 'sk-saved'}]


def test_mode_is_explicit_or_follows_the_cli_login():
    assert model_auth_mode({'EDITOR_MODEL_AUTH': 'api_key'}, which=lambda _: 'claude') == 'api_key'
    assert model_auth_mode({'EDITOR_MODEL_AUTH': 'OAUTH'}, which=lambda _: None) == 'oauth'
    assert model_auth_mode({}, which=lambda _: '/bin/claude') == 'oauth'
    assert model_auth_mode({}, which=lambda _: None) == 'api_key'
    with pytest.raises(ValueError):
        model_auth_mode({'EDITOR_MODEL_AUTH': 'both'})


def test_oauth_swaps_keyless_hosted_models_and_keeps_explicit_keys():
    keyed = {**OPENAI, 'config': {'model': 'gpt-4o', 'api_key': 'sk-template'}}
    team = {'provider': 'x', 'config': {'participants': [{'config': {'model_client': OPENAI}},
                                                         {'config': {'model_client': ANTHROPIC}},
                                                         {'config': {'model_client': keyed}}]}}
    out = apply_environment(team, KEYS, 'oauth')
    first, second, third = (p['config']['model_client'] for p in out['config']['participants'])
    assert first['provider'] == second['provider'] == PROVIDER
    assert first['config'] == {} and second['config'] == {'model': 'claude-sonnet-4-5'}
    assert third['config']['api_key'] == 'sk-template'            # a template's own key wins
    assert team['config']['participants'][0]['config']['model_client'] == OPENAI   # input untouched
    deployed = apply_environment(OPENAI, KEYS, 'api_key')
    assert deployed['provider'] == OPENAI['provider'] and deployed['config']['api_key'] == 'sk-saved'
    with pytest.raises(ValueError):
        apply_environment(OPENAI, KEYS, 'both')


def fake(reply, seen):
    async def run(command, system, transcript, timeout_s, token):
        seen.update(command=command, system=system, transcript=transcript)
        return reply
    return run


def ok(**fields):
    return {'type': 'result', 'subtype': 'success', 'is_error': False,
            'usage': {'input_tokens': 7, 'output_tokens': 2}, **fields}


def test_plain_turn_sends_system_and_transcript_and_reads_the_result():
    seen = {}
    client = ClaudeCodeChatCompletionClient(runner=fake(ok(result='4'), seen))
    result = asyncio.run(client.create([SystemMessage(content='terse'), UserMessage(content='2+2?', source='user')]))
    assert result.content == '4' and result.finish_reason == 'stop' and result.usage.prompt_tokens == 7
    assert seen['system'] == 'terse' and '[user]\n2+2?' in seen['transcript']
    command = seen['command']
    assert command[command.index('--tools') + 1] == ''
    assert '--setting-sources' in command and '--json-schema' not in command


def test_tools_come_back_as_function_calls_and_results_go_into_the_next_turn():
    seen = {}
    tool = {'name': 'analyze_land', 'description': 'parcel facts', 'parameters': {'type': 'object', 'properties': {}}}
    reply = ok(structured_output={'kind': 'tool_calls', 'calls': [{'name': 'analyze_land', 'arguments': {'pnu': '1'}}]})
    client = ClaudeCodeChatCompletionClient(runner=fake(reply, seen))
    result = asyncio.run(client.create([UserMessage(content='analyse', source='user')], tools=[tool]))
    assert result.finish_reason == 'function_calls'
    assert result.content[0].name == 'analyze_land' and json.loads(result.content[0].arguments) == {'pnu': '1'}
    assert '--json-schema' in seen['command'] and 'analyze_land' in seen['transcript']
    history = [UserMessage(content='analyse', source='user'),
               AssistantMessage(content=[FunctionCall(id='c1', name='analyze_land', arguments='{}')], source='a'),
               FunctionExecutionResultMessage(content=[FunctionExecutionResult(
                   content='zone: 2종', name='analyze_land', call_id='c1', is_error=False)])]
    second = ClaudeCodeChatCompletionClient(runner=fake(ok(structured_output={'kind': 'text', 'text': 'done'}), seen))
    assert asyncio.run(second.create(history, tools=[tool])).content == 'done'
    assert 'analyze_land({}) id=c1' in seen['transcript']
    assert '[tool result analyze_land id=c1]\nzone: 2종' in seen['transcript']
    bad = ok(structured_output={'kind': 'tool_calls', 'calls': [{'name': 'rm_rf', 'arguments': {}}]})
    with pytest.raises(RuntimeError):
        asyncio.run(ClaudeCodeChatCompletionClient(runner=fake(bad, {})).create(
            [UserMessage(content='x', source='u')], tools=[tool]))


def test_structured_output_and_cli_errors():
    class Answer(BaseModel):
        value: int
    seen = {}
    client = ClaudeCodeChatCompletionClient(runner=fake(ok(structured_output={'value': 4}), seen))
    result = asyncio.run(client.create([UserMessage(content='2+2', source='u')], json_output=Answer))
    assert json.loads(result.content) == {'value': 4} and '--json-schema' in seen['command']
    failing = ClaudeCodeChatCompletionClient(runner=fake({'is_error': True, 'subtype': 'error', 'result': 'login'}, {}))
    with pytest.raises(RuntimeError):
        asyncio.run(failing.create([UserMessage(content='x', source='u')]))


def test_child_process_never_sees_an_anthropic_key(monkeypatch):
    captured = {}

    class Done:
        returncode = 0

        def __init__(self, args, **kwargs):
            captured.update(args=args, env=kwargs['env'])

        def communicate(self, data=None, timeout=None):
            return json.dumps(ok(result='hi')).encode(), b''

    monkeypatch.setenv('ANTHROPIC_API_KEY', 'abc')
    monkeypatch.setattr(cli_model_client.shutil, 'which', lambda name: 'C:/bin/claude.exe')
    monkeypatch.setattr(cli_model_client.subprocess, 'Popen', Done)
    reply = asyncio.run(cli_model_client._run_cli(['claude', '-p'], 'sys', 'hello', 5, None))
    assert reply['result'] == 'hi'
    assert 'ANTHROPIC_API_KEY' not in captured['env'] and '--system-prompt-file' in captured['args']


def test_component_round_trip_and_registered_provider():
    from autogen_core.models import ChatCompletionClient
    from backend.app.adapters.workspace.team import SUPPORTED_PROVIDERS
    dumped = ClaudeCodeChatCompletionClient(model='claude-sonnet-4-5', timeout_s=60).dump_component()
    assert dumped.provider == PROVIDER and PROVIDER in SUPPORTED_PROVIDERS
    loaded = ChatCompletionClient.load_component(dumped)
    assert isinstance(loaded, ClaudeCodeChatCompletionClient) and loaded.model_info['function_calling']
