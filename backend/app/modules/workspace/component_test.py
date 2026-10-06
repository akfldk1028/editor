"""POST /validate/test: load a component, and for a model send one prompt.

Only a model is executed. Agents, teams, terminations, tools and workbenches are
loaded and reported as such; a workbench load does not connect (MCP connects on
first use).
"""
import asyncio

from backend.app.adapters.workspace.credentials import apply_environment
from backend.app.adapters.workspace.team import close_team, validate_components
from backend.app.core.model_auth import model_auth_mode
from backend.app.modules.workspace.catalog import validate_component


TEST_PROMPT = 'What is 2+2? Give me only the answer.'


def result(status, message, data=None, logs=()):
    return {'status': status, 'message': message, 'data': data, 'logs': list(logs)}


async def test_component(component, environment, timeout):
    structure = validate_component(component)
    if not structure['is_valid']:
        return result(False, 'Component validation failed', logs=[error['error'] for error in structure['errors']])
    try:
        validate_components(component)
    except ValueError as error:
        return result(False, str(error))
    component = apply_environment(component, environment, model_auth_mode())
    loader = LOADERS[component['component_type']]
    try:
        async with asyncio.timeout(timeout):
            return await loader(component)
    except TimeoutError:
        return result(False, f'Component test exceeded the {timeout}s timeout')
    except Exception as error:
        # Provider errors can embed credentials/request bodies; expose the type only.
        return result(False, f'Component test failed ({type(error).__name__})')


async def test_model(component):
    from autogen_core.models import ChatCompletionClient, UserMessage

    client = ChatCompletionClient.load_component(component)
    try:
        response = await client.create([UserMessage(content=TEST_PROMPT, source='user')])
    finally:
        await client.close()
    usage = response.usage
    return result(True, 'Model responded',
                  {'content': response.content if isinstance(response.content, str) else None,
                   'usage': {'prompt_tokens': usage.prompt_tokens, 'completion_tokens': usage.completion_tokens}},
                  ['Model component loaded', 'Model responded'])


def loaded_only(base):
    async def load(component):
        from importlib import import_module

        module, name = base.rsplit('.', 1)
        instance = getattr(import_module(module), name).load_component(component)
        await close_team(instance)
        return result(True, 'Loaded; not executed', logs=['Component loaded'])

    return load


LOADERS = {
    'model': test_model,
    'agent': loaded_only('autogen_agentchat.base.ChatAgent'),
    'team': loaded_only('autogen_agentchat.base.Team'),
    'termination': loaded_only('autogen_agentchat.base.TerminationCondition'),
    'tool': loaded_only('autogen_core.tools.BaseTool'),
    'workbench': loaded_only('autogen_core.tools.Workbench'),
}
