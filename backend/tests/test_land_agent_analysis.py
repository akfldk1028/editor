import asyncio
import copy
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.adapters.workspace import tools as workspace_tools
from backend.app.modules.land.routers.analysis import create_land_router
from backend.app.modules.land.agent_analysis import agent_analysis_events
from backend.app.modules.workspace.seeds import LAND_TEAM


REPLAY_INFO = {'vision': False, 'function_calling': True, 'json_output': False, 'family': 'unknown',
               'structured_output': False}


def replay_land_team():
    """LAND_TEAM with every model replaced by scripted replies, so no key or network is needed."""
    team = copy.deepcopy(LAND_TEAM)
    for participant, replies in zip(team['config']['participants'],
                                    (['규제 요약'] * 3, ['법조항 정리'] * 3, ['보고서\nTERMINATE'] * 3)):
        participant['config']['model_client'] = {
            'provider': 'autogen_ext.models.replay.ReplayChatCompletionClient', 'component_type': 'model',
            'config': {'chat_completions': replies, 'model_info': REPLAY_INFO}}
    return team


class FakeServices:
    addresses = None  # the router reads it for resolve/reverse, which this test does not call

    def __init__(self, fail=False):
        self.fail = fail

    async def analyze_land(self, pnu, address, zones):
        if self.fail:
            raise OSError('vworld down')
        return {'pnu': {'pnu': pnu}, 'regulations': {'bcr': 60}, 'zones': zones}

    async def search_laws(self, query, limit):
        return {'articles': [], 'total_count': 0}


def collect(**kwargs):
    async def run():
        return [event async for event in agent_analysis_events(**kwargs)]

    return asyncio.run(run())


def test_quick_result_then_agent_turns_then_report():
    workspace_tools.set_tool_services(FakeServices())
    try:
        events = collect(pnu='1111010100100010000', address='', zones=['제2종일반주거지역'], services=FakeServices(),
                         team=replay_land_team(), environment=[])
    finally:
        workspace_tools.set_tool_services(None)
    statuses = [event['status'] for event in events]
    assert statuses[:5] == ['analyzing'] * 3 + ['analyzing', 'quick_done']
    assert statuses[5] == 'analyzing' and events[5]['phase'] == 'agent_connect'
    assert events[4]['regulations']['zones'] == ['제2종일반주거지역']
    agents = [event for event in events if event['status'] == 'agent']
    assert [event['agent'] for event in agents] == ['land_analyst', 'legal_interpreter', 'report_writer']
    assert events[-1]['status'] == 'complete'
    assert events[-1]['report'].endswith('TERMINATE')
    assert events[-1]['run_summary']['turn_count'] == 3


def test_quick_failure_stops_without_a_fallback():
    events = collect(pnu='1111010100100010000', address='', zones=[], services=FakeServices(fail=True),
                     team=replay_land_team(), environment=[])
    assert events[-1] == {'status': 'error', 'message': '빠른 분석 중 오류가 발생했습니다.', 'fallback_to_quick': False}
    assert len(events) == 4


def test_stream_route_emits_the_contract_and_guards_input():
    app = FastAPI()
    app.include_router(create_land_router(public_origin='http://editor', services=FakeServices(),
                                          agent_team=replay_land_team(), agent_environment=[]))
    api = TestClient(app)
    response = api.get('/api/v1/land/agent-analyze/stream', params={'pnu': '1111010100100010000'})
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    statuses = [event['status'] for event in events]
    assert statuses[0] == 'analyzing' and 'quick_done' in statuses and statuses[-1] == 'complete'
    assert api.get('/api/v1/land/agent-analyze/stream').status_code == 422
    assert api.get('/api/v1/land/agent-analyze/stream', params={'pnu': 'x'},
                   headers={'Origin': 'http://other'}).status_code == 403
