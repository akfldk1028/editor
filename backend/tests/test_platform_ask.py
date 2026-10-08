"""`POST /api/v1/platform/ask`: a typed question reaches the Law Agent over A2A and comes back in one shape.
Payloads below are the Law Agent's own answers of 2026-10-08 (law_search '자연녹지지역 건폐율', law_ordinance 의정부시 조례 제42조), trimmed."""
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.adapters import law_agent
from backend.app.modules.platform.ask import analyze_land, ask_law, normalize, plan
from backend.app.modules.platform.routing import RULES, route
from backend.app.modules.platform.routers.ask import create_ask_router
from backend.app.schemas.ask import AskCreate

ORIGIN = 'http://127.0.0.1:3003'

SEARCH = {'results': [
    {'hang_id': '국토의 계획 및 이용에 관한 법률(시행령)::제6장::제84조::8', 'content': '제1항에도 불구하고 법 제77조제4항제3호에 따라 생산녹지지역 또는 자연녹지지역에 건축할 수 있는',
     'law_name': '국토의 계획 및 이용에 관한 법률', 'law_type': '시행령', 'article': '제84조', 'similarity': 17.05, 'stages': ['fulltext_keyword']},
    {'hang_id': 'x::제84조의2::2', 'content': '제84조제1항에도 불구하고', 'law_name': '국토의 계획 및 이용에 관한 법률', 'law_type': '시행령', 'article': '제84조'},
    'not a row'],
    'stats': {'total': 5, 'degraded': False}, 'domain_id': 'all',
    'legal_evidence': {'assessment_date': '2026-10-08', 'currency_status': 'needs_evidence', 'coverage_status': 'needs_evidence',
                       'reason': 'Retrieved text does not establish complete dated coverage or transitional applicability.'}}

ORDINANCE = {'ordinance': {'name': '의정부시 도시계획 조례', 'id': '2149163', 'edition_id': '2072835', 'effective': '20250925', 'articles_total': 92},
             'query': '제42조',
             'matches': [{'article': '제42조', 'title': '용도지역안에서의 건폐율', 'content': '제42조(용도지역안에서의 건폐율) ' + '16. 자연녹지지역 : 20퍼센트 이하' * 30}],
             'source': 'law.go.kr lawService.do target=ordin MST=2072835',
             'legal_evidence': {'assessment_date': '2026-10-08', 'currency_status': 'needs_evidence', 'coverage_status': 'needs_evidence', 'reason': 'r'}}


def test_plan_routes_an_ordinance_article_to_law_ordinance_and_everything_else_to_law_search():
    assert plan('의정부시 도시계획 조례 제42조', '2026-10-08') == ('law_ordinance', {'name': '의정부시 도시계획 조례', 'article': '제42조', 'limit': 3, 'assessment_date': '2026-10-08'})
    assert plan('서울특별시 도시계획 조례 45조의3 보여줘') == ('law_ordinance', {'name': '서울특별시 도시계획 조례', 'article': '제45조의3', 'limit': 3})
    assert plan(' 자연녹지지역 건폐율 ') == ('law_search', {'query': '자연녹지지역 건폐율', 'limit': 8})
    assert plan('조례가 뭐야')[0] == 'law_search'
    assert plan('국토의 계획 및 이용에 관한 법률(시행령)::제6장::제84조::8') == ('law_article', {'full_id': '국토의 계획 및 이용에 관한 법률(시행령)::제6장::제84조::8'})


def test_route_explains_itself_and_ends_with_a_default():
    chosen = route('의정부시 도시계획 조례 제42조')
    assert (chosen.agent, chosen.skill, chosen.confidence) == ('law', 'law_ordinance', 0.95) and '조례' in chosen.reason
    assert route('아무 말').to_dict() == {'agent': 'law', 'skill': 'law_search', 'confidence': 0.6, 'reason': '법령 본문 검색 (기본)'}
    assert RULES[-1].build('x', {}) is not None


def test_normalize_keeps_the_tools_values_and_shapes_them_for_the_ui():
    search = normalize('law_search', SEARCH)
    assert search['kind'] == 'search' and search['total'] == 5 and search['degraded'] is False
    assert search['items'][0] == {'id': '국토의 계획 및 이용에 관한 법률(시행령)::제6장::제84조::8', 'law': '국토의 계획 및 이용에 관한 법률', 'kind': '시행령',
                                  'article': '제84조', 'text': '제1항에도 불구하고 법 제77조제4항제3호에 따라 생산녹지지역 또는 자연녹지지역에 건축할 수 있는'}
    assert len(search['items']) == 2
    assert search['legal_evidence']['currency_status'] == 'needs_evidence'
    ordinance = normalize('law_ordinance', ORDINANCE)
    assert ordinance['ordinance'] == {'name': '의정부시 도시계획 조례', 'ordinance_id': '2149163', 'edition_id': '2072835', 'effective_date': '2025-09-25',
                                      'url': 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=2072835'}
    assert ordinance['matches'][0]['article'] == '제42조' and ordinance['matches'][0]['title'] == '용도지역안에서의 건폐율'
    assert len(ordinance['matches'][0]['text']) == 400
    assert normalize('law_search', {}) == {'kind': 'search', 'items': [], 'total': 0, 'degraded': False, 'legal_evidence': None}


def a2a_reply(payload, state='TASK_STATE_COMPLETED', version='0.1.0+eaba337'):
    return {'jsonrpc': '2.0', 'id': 'x', 'result': {'task': {'id': 't1', 'contextId': 'c1', 'status': {'state': state, 'message': {
        'messageId': 'm', 'role': 'ROLE_AGENT', 'parts': [{'text': json.dumps(payload, ensure_ascii=False)}], 'metadata': {'version': version, 'tool': 'law_search'}}}}}}


def run(coroutine):
    return asyncio.run(coroutine)


def test_adapter_sends_one_a2a_message_with_the_trace_and_reads_the_tools_json():
    seen = {}

    def handler(request: httpx.Request):
        seen['url'] = str(request.url)
        seen['body'] = json.loads(request.content)
        return httpx.Response(200, json=a2a_reply(SEARCH))

    answer = run(law_agent.ask('law_search', {'query': '건폐율', 'limit': 8}, trace={'caller': 'editor', 'trace_id': 'abc', 'hop': 1},
                               base_url='http://law.test', transport=httpx.MockTransport(handler)))
    assert seen['url'] == 'http://law.test/'
    message = seen['body']['params']['message']
    assert seen['body']['method'] == 'SendMessage' and message['role'] == 'ROLE_USER'
    assert json.loads(message['parts'][0]['text']) == {'tool': 'law_search', 'args': {'query': '건폐율', 'limit': 8}}
    assert message['metadata'] == {'trace': {'caller': 'editor', 'trace_id': 'abc', 'hop': '1'}}
    assert answer == {'tool': 'law_search', 'payload': SEARCH, 'task_id': 't1', 'version': '0.1.0+eaba337'}


def test_adapter_names_a_down_agent_a_failed_task_and_an_error_payload():
    def down(request):
        raise httpx.ConnectError('refused')
    ask = lambda transport: run(law_agent.ask('law_search', {'query': 'x'}, base_url='http://law.test', transport=httpx.MockTransport(transport)))
    with pytest.raises(law_agent.LawAgentUnavailable):
        ask(down)
    with pytest.raises(law_agent.LawAgentError, match='TASK_STATE_FAILED'):
        ask(lambda r: httpx.Response(200, json=a2a_reply({}, state='TASK_STATE_FAILED')))
    with pytest.raises(law_agent.LawAgentError, match='nope'):
        ask(lambda r: httpx.Response(200, json=a2a_reply({'error': 'nope'})))
    with pytest.raises(law_agent.LawAgentError, match='Method not found'):
        ask(lambda r: httpx.Response(200, json={'jsonrpc': '2.0', 'id': 'x', 'error': {'code': -32601, 'message': 'Method not found'}}))


class Recorder:
    def __init__(self):
        self.rows = []

    def record(self, row):
        self.rows.append(row)


def test_ask_law_records_one_law_span_and_answers_in_the_contract_shape():
    recorder = Recorder()
    calls = []

    async def agent(tool, args, *, trace=None):
        calls.append((tool, args, trace))
        return {'tool': tool, 'payload': SEARCH, 'task_id': 't1', 'version': 'v'}

    answer = run(ask_law('자연녹지지역 건폐율', pnu='4115011300106830000', assessment_date='2026-10-08', recorder=recorder,
                         traceparent='00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01', agent=agent))
    assert calls[0][0] == 'law_search' and calls[0][1]['query'] == '자연녹지지역 건폐율'
    assert calls[0][2]['caller'] == 'editor' and calls[0][2]['trace_id'] == '4bf92f3577b34da6a3ce929d0e0e4736'
    assert set(answer) == {'question', 'tool', 'agent', 'trace_id', 'version', 'route', 'answer'}
    assert answer['agent'] == 'law' and answer['trace_id'] == '4bf92f3577b34da6a3ce929d0e0e4736' and answer['answer']['kind'] == 'search'
    assert answer['route'] == {'agent': 'law', 'skill': 'law_search', 'confidence': 0.6, 'reason': '법령 본문 검색 (기본)'}
    row = recorder.rows[0]
    assert (row['name'], row['gen_ai.agent.name'], row['gen_ai.conversation.id'], row['status']) == ('invoke_agent law', 'law', 'editor:ask:4115011300106830000', 'ok')


def app_with(agent):
    app = FastAPI()
    app.include_router(create_ask_router(ORIGIN, Recorder(), agent), prefix='/api/v1/platform')
    return TestClient(app)


def test_route_answers_same_origin_and_refuses_cross_origin_and_bad_bodies():
    async def agent(tool, args, *, trace=None):
        return {'tool': tool, 'payload': ORDINANCE, 'task_id': 't', 'version': None}

    client = app_with(agent)
    ok = client.post('/api/v1/platform/ask', json={'text': '의정부시 도시계획 조례 제42조', 'pnu': '4115011300106830000'}, headers={'Origin': ORIGIN})
    assert ok.status_code == 200 and ok.json()['tool'] == 'law_ordinance' and ok.json()['answer']['ordinance']['edition_id'] == '2072835'
    assert client.post('/api/v1/platform/ask', json={'text': 'x'}, headers={'Origin': 'http://evil.test'}).status_code == 403
    assert client.post('/api/v1/platform/ask', json={'text': '   '}, headers={'Origin': ORIGIN}).status_code == 422
    assert client.post('/api/v1/platform/ask', json={'text': 'x', 'pnu': '12'}, headers={'Origin': ORIGIN}).status_code == 422
    assert client.post('/api/v1/platform/ask', json={'text': 'x', 'assessment_date': '2026-02-30'}, headers={'Origin': ORIGIN}).status_code == 422
    assert client.post('/api/v1/platform/ask', json={'text': 'x', 'extra': 1}, headers={'Origin': ORIGIN}).status_code == 422


def test_route_maps_an_unreachable_agent_to_503_and_a_refusal_to_502():
    async def down(tool, args, *, trace=None):
        raise law_agent.LawAgentUnavailable('off')

    async def refused(tool, args, *, trace=None):
        raise law_agent.LawAgentError('law_search: TASK_STATE_FAILED')

    assert app_with(down).post('/api/v1/platform/ask', json={'text': 'x'}, headers={'Origin': ORIGIN}).status_code == 503
    response = app_with(refused).post('/api/v1/platform/ask', json={'text': 'x'}, headers={'Origin': ORIGIN})
    assert response.status_code == 502 and 'TASK_STATE_FAILED' in response.json()['detail']


LAND = {'status': 200, 'findings': [{'id': 'law-parking-x', 'severity': 'major', 'raised_by': 'law'}],
        'raw': {'pnu': '4115011300106840001',
                'regulations': {'bcr': {'limit_pct': None, 'article': '의정부시 도시계획 조례 제42조', 'national_ceiling_pct': 59.9225, 'status': 'needs_evidence'}},
                'zone_info': {'bcr_limit': None, 'far_limit': None, 'zones': ['제2종일반주거지역', '자연녹지지역'], 'unmatched': ['과밀억제권역', '공공청사'],
                              'zone_areas_m2': {'자연녹지지역': 4.85, '제2종일반주거지역': 2499.69}},
                'land_info': {'land_area_m2': 2500.0}, 'law_articles': None,
                'restrictions': ['건폐율·용적률: 적용 조례·판본·용도지역 증거 부족 — 상한 미확정', '일조사선: 정북방향 H/2 이격'],
                'assessment': {'status': 'needs_evidence', 'permit_compliance_verified': False,
                               'municipal_coverage': {'missing_evidence': ['unresolved_zoning:공공청사']}, 'missing_evidence': ['complete_design_applicability_and_permit_checks']}}}
LIMITS = {'pnu': '4115011300106840001', 'building_type': '업무시설', 'parcel_area_m2': 2499.691, 'ground_capacity_m2': 1497.877, 'far_capacity_m2': 6240.995,
          'max_storeys': 5, 'bcr_pct': 59.92, 'far_pct': 249.67, 'zones': ['제2종일반주거지역', '자연녹지지역'],
          'policy': {'policy_id': 'gosan-public1-molit-2026-334', 'parcel_label': '경기도 의정부시 산곡동 684-1 / 공공1', 'max_storeys': 5, 'max_bcr_pct': 60.0, 'max_far_pct': 250.0,
                     'sources': [{'title': '의정부고산 토지이용계획도', 'date': '2026-06-29'}]},
          'ordinance': {'assessment_date': '2026-10-08', 'bcr_article': '의정부시 도시계획 조례 제42조', 'far_article': '의정부시 도시계획 조례 제46조',
                        'municipal_coverage': {'sources': [{'name': '의정부시 도시계획 조례', 'edition_id': '2072835', 'effective_date': '20250925'}]}}}


def test_analyze_land_asks_both_law_tools_and_answers_the_analysis_with_its_limits_and_summary():
    recorder = Recorder()
    calls = []

    async def agent(tool, args, *, trace=None):
        calls.append((tool, args, trace))
        return {'tool': tool, 'payload': LAND if tool == 'law_land_analyze' else LIMITS, 'task_id': 't', 'version': 'v1'}

    answer = run(analyze_land('4115011300106840001', building_type='업무시설', floor_area_m2=None, assessment_date='2026-10-08', recorder=recorder, agent=agent))
    tools = {tool: args for tool, args, _ in calls}
    assert tools['law_land_analyze'] == {'input': '4115011300106840001', 'input_type': 'pnu', 'full': True, 'include_law': True, 'building_type': '업무시설',
                                        'floor_area_m2': None, 'assessment_date': '2026-10-08'}
    assert tools['law_parcel_limits'] == {'pnu': '4115011300106840001', 'building_type': '업무시설'}
    assert {trace['tool'] for _, _, trace in calls} == {'law_land_analyze', 'law_parcel_limits'}
    assert len({trace['trace_id'] for _, _, trace in calls}) == 1
    assert answer['analysis'] is LAND['raw'] or answer['analysis'] == LAND['raw']
    assert answer['findings'] == LAND['findings'] and answer['version'] == 'v1' and answer['limits_error'] is None
    limits = answer['limits']
    assert (limits['bcr_pct'], limits['far_pct'], limits['max_floors'], limits['policy_id']) == (59.92, 249.67, 5, 'gosan-public1-molit-2026-334')
    assert limits['articles']['bcr'] == '의정부시 도시계획 조례 제42조' and limits['ordinance']['edition_id'] == '2072835'
    assert answer['summary'] == {'zones': ['제2종일반주거지역', '자연녹지지역'], 'unmatched_zones': ['과밀억제권역', '공공청사'],
                                 'zone_areas_m2': {'자연녹지지역': 4.85, '제2종일반주거지역': 2499.69},
                                 'restrictions': LAND['raw']['restrictions'], 'assessment_status': 'needs_evidence', 'permit_compliance_verified': False,
                                 'missing_evidence': ['complete_design_applicability_and_permit_checks', 'unresolved_zoning:공공청사']}
    assert [(row['name'], row['status']) for row in recorder.rows] == [('invoke_agent law', 'ok'), ('invoke_agent law', 'ok')]


def test_analyze_land_keeps_the_analysis_when_only_the_limits_call_fails_and_fails_when_the_analysis_does():
    async def limits_down(tool, args, *, trace=None):
        if tool == 'law_parcel_limits':
            raise law_agent.LawAgentError('law_parcel_limits: TASK_STATE_FAILED')
        return {'tool': tool, 'payload': LAND, 'task_id': 't', 'version': None}

    answer = run(analyze_land('4115011300106840001', building_type=None, floor_area_m2=None, assessment_date=None, recorder=Recorder(), agent=limits_down))
    assert answer['limits'] is None and 'TASK_STATE_FAILED' in answer['limits_error'] and answer['summary']['zones'] == ['제2종일반주거지역', '자연녹지지역']

    async def land_down(tool, args, *, trace=None):
        raise law_agent.LawAgentUnavailable('off')

    with pytest.raises(law_agent.LawAgentUnavailable):
        run(analyze_land('4115011300106840001', building_type=None, floor_area_m2=None, assessment_date=None, recorder=Recorder(), agent=land_down))


def test_law_analysis_route_validates_and_answers():
    async def agent(tool, args, *, trace=None):
        return {'tool': tool, 'payload': LAND if tool == 'law_land_analyze' else LIMITS, 'task_id': 't', 'version': 'v1'}

    client = app_with(agent)
    ok = client.post('/api/v1/platform/law-analysis', json={'pnu': '4115011300106840001', 'building_type': '업무시설', 'assessment_date': '2026-10-08'}, headers={'Origin': ORIGIN})
    assert ok.status_code == 200 and ok.json()['limits']['bcr_pct'] == 59.92 and ok.json()['analysis']['land_info']['land_area_m2'] == 2500.0
    assert client.post('/api/v1/platform/law-analysis', json={'pnu': '12'}, headers={'Origin': ORIGIN}).status_code == 422
    assert client.post('/api/v1/platform/law-analysis', json={'pnu': '4115011300106840001', 'floor_area_m2': 0}, headers={'Origin': ORIGIN}).status_code == 422
    assert client.post('/api/v1/platform/law-analysis', json={'pnu': '4115011300106840001'}, headers={'Origin': 'http://evil.test'}).status_code == 403


def test_ask_schema_is_strict():
    assert AskCreate(text=' 건폐율 ').text == '건폐율'
    with pytest.raises(ValueError):
        AskCreate(text='x', pnu=4115011300106830000)
