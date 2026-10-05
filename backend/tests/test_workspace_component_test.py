import asyncio

from backend.app.modules.workspace.component_test import test_component as run_test


REPLAY = {'provider': 'autogen_ext.models.replay.ReplayChatCompletionClient', 'component_type': 'model',
          'config': {'chat_completions': ['4']}}


def test_replay_model_answers_the_probe():
    result = asyncio.run(run_test(REPLAY, [], 10))
    assert result['status'] is True
    assert result['data']['content'] == '4'


def test_structural_and_policy_failures_are_reported_without_loading():
    bad = asyncio.run(run_test({'provider': 'x', 'config': {}}, [], 10))
    assert bad['status'] is False and bad['message'] == 'Component validation failed' and bad['logs']
    unsafe = asyncio.run(run_test({'provider': 'autogen_core.tools.FunctionTool', 'component_type': 'tool',
                                   'config': {'source_code': 'def f(): pass', 'name': 'f'}}, [], 10))
    assert unsafe['status'] is False and 'FunctionTool' in unsafe['message']


def test_agent_is_loaded_but_not_executed():
    agent = {'provider': 'autogen_agentchat.agents.AssistantAgent', 'component_type': 'agent',
             'config': {'name': 'a', 'description': 'd', 'reflect_on_tool_use': False,
                        'tool_call_summary_format': '{result}', 'model_client': REPLAY}}
    result = asyncio.run(run_test(agent, [], 10))
    assert result == {'status': True, 'message': 'Loaded; not executed', 'data': None, 'logs': ['Component loaded']}


def test_provider_failure_hides_the_secret():
    openai = {'provider': 'autogen_ext.models.openai.OpenAIChatCompletionClient', 'component_type': 'model',
              'config': {'model': 'gpt-4o-mini', 'base_url': 'http://127.0.0.1:9/v1'}}
    result = asyncio.run(run_test(openai, [{'name': 'OPENAI_API_KEY', 'value': 'sk-secret-value'}], 5))
    assert result['status'] is False
    assert 'sk-secret-value' not in result['message'] and 'api_key' not in result['message']
