import asyncio
import json

import pytest
from autogen_core import CancellationToken

from backend.app.adapters import workspace_tools
from backend.app.adapters.workspace_tool_policy import EDITOR_TOOL_PROVIDERS


class FakeServices:
    def __init__(self):
        self.calls = []

    async def analyze_land(self, pnu, address, zones):
        self.calls.append(('analyze_land', pnu, address, zones))
        return {'pnu': {'pnu': pnu}, 'regulations': {'bcr': 60}, 'setback_lines': [[0, 0]], 'law_articles': ['x']}

    async def search_laws(self, query, limit):
        self.calls.append(('search_laws', query, limit))
        return {'articles': [{'content': 'A' * 1000, 'hang_id': 'law::1'}] * 3, 'total_count': 3}


@pytest.fixture
def services():
    fake = FakeServices()
    workspace_tools.set_tool_services(fake)
    yield fake
    workspace_tools.set_tool_services(None)


def load(provider):
    from autogen_core.tools import BaseTool

    return BaseTool.load_component({'provider': provider, 'component_type': 'tool', 'config': {}})


def test_land_tool_loads_from_its_provider_string_and_trims_the_result(services):
    tool = load('backend.app.adapters.workspace_tools.LandAnalyzeTool')
    assert tool.dump_component().provider in EDITOR_TOOL_PROVIDERS
    text = asyncio.run(tool.run_json({'pnu': '1111010100100010000'}, CancellationToken()))
    result = json.loads(text)
    assert result['regulations'] == {'bcr': 60}
    assert 'setback_lines' not in result and 'law_articles' not in result
    assert services.calls == [('analyze_land', '1111010100100010000', '', [])]


def test_law_tool_caps_article_text(services):
    tool = load('backend.app.adapters.workspace_tools.LawSearchTool')
    text = asyncio.run(tool.run_json({'query': '건폐율', 'limit': 2}, CancellationToken()))
    result = json.loads(text)
    assert len(result['articles']) == 2
    assert len(result['articles'][0]['content']) == 600
    assert services.calls == [('search_laws', '건폐율', 2)]
