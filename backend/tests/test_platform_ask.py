"""`POST /api/v1/platform/ask`: a typed question reaches the Law Agent over A2A and comes back in one shape.
Payloads below are the Law Agent's own answers of 2026-10-08 (law_search '자연녹지지역 건폐율', law_ordinance 의정부시 조례 제42조), trimmed."""
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.adapters import law_agent
from backend.app.modules.platform.ask import analyze_land, ask_law, normalize, ROAD_DEFINITION_QUERY, found_ids, _road_line, road_facts
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
    assert set(answer) == {'question', 'route', 'agent', 'tool', 'trace_id', 'version', 'answer', 'handoff', 'delegate', 'clause'} and answer['clause'] is None
    assert answer['handoff'] is None
    assert answer['agent'] == 'law' and answer['trace_id'] == '4bf92f3577b34da6a3ce929d0e0e4736' and answer['answer']['kind'] == 'search'
    assert answer['route'] == {'kind': 'skill', 'agent': 'law', 'skill': 'law_search', 'goal': None, 'confidence': 0.7, 'reason': '법령·조례 검색 (Law Agent)의 말이 1개 보여요', 'choices': [], 'decided_by': 'rules', 'instruction': None, 'fallback_reason': None}
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

    # A text the router sends to the Law Agent (keyword 건폐율); an unroutable text never reaches the agent.
    assert app_with(down).post('/api/v1/platform/ask', json={'text': '건폐율'}, headers={'Origin': ORIGIN}).status_code == 503
    response = app_with(refused).post('/api/v1/platform/ask', json={'text': '건폐율'}, headers={'Origin': ORIGIN})
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
    assert tools['law_parcel_limits'] == {'pnu': '4115011300106840001', 'building_type': '업무시설', 'assessment_date': '2026-10-08'}
    assert {trace['tool'] for _, _, trace in calls} == {'law_land_analyze', 'law_parcel_limits'}
    assert len({trace['trace_id'] for _, _, trace in calls}) == 1
    assert answer['analysis'] is LAND['raw'] or answer['analysis'] == LAND['raw']
    assert answer['findings'] == LAND['findings'] and answer['version'] == 'v1' and answer['limits_error'] is None
    limits = answer['limits']
    assert (limits['bcr_pct'], limits['far_pct'], limits['max_floors'], limits['policy_id']) == (59.92, 249.67, 5, 'gosan-public1-molit-2026-334')
    assert limits['articles']['bcr'] == '의정부시 도시계획 조례 제42조' and limits['ordinance']['edition_id'] == '2072835'
    assert answer['summary'] == {'zones': ['제2종일반주거지역', '자연녹지지역'], 'unmatched_zones': ['과밀억제권역', '공공청사'],
                                 'zone_areas_m2': {'자연녹지지역': 4.85, '제2종일반주거지역': 2499.69}, 'zone_split': None,
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


ROAD_REVIEW = {'items': [{'id': 'road-frontage', 'group': 'road_setback', 'title': '대지와 도로의 관계', 'status': 'applies', 'basis': '폭 4m 이상 도로에 2m 이상',
                          'refs': [{'kind': 'act', 'instrument': '건축법', 'article': '제44조', 'hang_ids': ['건축법::제5장::제44조::1', '건축법::제5장::제44조::2']}]}]}
SITE_ROADS = {'status': 'ok', 'source': 'Vworld WFS lt_c_uq161', 'rule': '규칙 제9조', 'note': 'n', 'touch_tolerance_m': 0.3,
              'items': [{'name': '중로2-5호선', 'kind': '중로2류', 'ucode': 'x', 'decision': {'year': '2018', 'no': '0816'}, 'shared_edge_m': 50.72,
                         'overlap_m2': 1.2, 'width_m_rule': {'min_m': 15, 'max_m': 20}, 'jurisdiction': '의정부시', 'properties': {'big': 'dump'}}]}


def _land_with_review():
    return {**LAND, 'raw': {**LAND['raw'], 'review': {'items': [dict(ROAD_REVIEW['items'][0])]}}}


def test_analyze_land_settles_the_road_item_from_site_facts_and_the_law_judge():
    calls = []
    land = _land_with_review()

    async def agent(tool, args, *, trace=None):
        calls.append((tool, args))
        if tool == 'law_judge':
            return {'tool': tool, 'payload': {'verdict': 'applies', 'status': 'judged', 'reason': '국토계획법 결정 도로라 제2조제1항제11호 도로이고 50.72 m 접함',
                                              'open_conditions': [], 'findings': [{'unit': 'u', 'claim': 'c', 'quote': 'q'}]}, 'task_id': 'j', 'version': 'v1'}
        if tool == 'law_search':
            return {'tool': tool, 'payload': {'results': [{'hang_id': '건축법(법률)::제1장::제2조::1::제11호', 'content': '도로란…'}, {'hang_id': '건축법(법률)::제1장::제2조::1'},
                                                          {'hang_id': '건축법(법률)::제4장::제44조::1'}]}, 'task_id': 'q', 'version': 'v1'}
        return {'tool': tool, 'payload': land if tool == 'law_land_analyze' else LIMITS, 'task_id': 't', 'version': 'v1'}

    async def site(tool, args, *, trace=None):
        calls.append((tool, args))
        return {'tool': tool, 'payload': SITE_ROADS, 'task_id': 's', 'version': 'v1'}

    recorder = Recorder()
    answer = run(analyze_land('4115011300106840001', building_type=None, floor_area_m2=None, assessment_date='2026-10-16', recorder=recorder, agent=agent, site=site))
    tools = dict(calls)
    assert tools['site_planned_facilities'] == {'pnu': '4115011300106840001'}
    judge = tools['law_judge']
    # The judge reads the item's own article first, then the definition article Law's search found for the question
    # (whole article ids, once each), the facts without Site's property dump, and the date.
    assert tools['law_search'] == {'query': ROAD_DEFINITION_QUERY, 'limit': 5, 'assessment_date': '2026-10-16'}
    assert judge['article_ids'] == ['건축법::제5장::제44조', '건축법(법률)::제1장::제2조', '건축법(법률)::제4장::제44조']
    assert judge['assessment_date'] == '2026-10-16' and '제44조' in judge['question']
    assert judge['facts']['planned_facilities_touching_parcel'] == [{'name': '중로2-5호선', 'kind': '중로2류', 'ucode': 'x', 'decision': {'year': '2018', 'no': '0816'},
                                                                     'shared_edge_m': 50.72, 'overlap_m2': 1.2, 'width_m_rule': {'min_m': 15, 'max_m': 20}, 'centrelines': None, 'jurisdiction': '의정부시'}]
    item = answer['analysis']['review']['items'][0]
    assert item['status'] == 'applies'
    assert item['basis'] == 'Site: 중로2-5호선(중로2류, 결정 폭 15~20 m, 공유 변 50.72 m, 결정 2018-0816) — Law: 국토계획법 결정 도로라 제2조제1항제11호 도로이고 50.72 m 접함'
    assert item['evidence']['law']['verdict'] == 'applies' and item['evidence']['site']['status'] == 'ok'
    assert [row['name'] for row in recorder.rows] == ['invoke_agent law', 'invoke_agent law', 'invoke_agent site_context', 'invoke_agent law', 'invoke_agent law']


def test_analyze_land_says_when_site_facts_are_missing_and_transcribes_an_undecided_judge():
    calls = []

    async def agent(tool, args, *, trace=None):
        calls.append(tool)
        if tool == 'law_judge':
            return {'tool': tool, 'payload': {'verdict': 'undecided', 'status': 'needs_evidence', 'reason': '지적 도로 자료 없음', 'open_conditions': ['현황 도로 폭']}, 'task_id': 'j', 'version': 'v1'}
        return {'tool': tool, 'payload': _land_with_review() if tool == 'law_land_analyze' else LIMITS, 'task_id': 't', 'version': 'v1'}

    async def down(tool, args, *, trace=None):
        raise RuntimeError('site off')

    item = run(analyze_land('4115011300106840001', building_type=None, floor_area_m2=None, assessment_date=None, recorder=Recorder(), agent=agent, site=down))['analysis']['review']['items'][0]
    assert item['status'] == 'applies' and 'Site 접도 사실을 받지 못했어요(RuntimeError: site off)' in item['basis'] and 'law_judge' not in calls
    assert item['evidence'] == {'site': {'status': 'unavailable', 'reason': 'RuntimeError: site off'}, 'law': None}

    async def nothing_touches(tool, args, *, trace=None):
        return {'tool': tool, 'payload': {**SITE_ROADS, 'items': []}, 'task_id': 's', 'version': 'v1'}

    item = run(analyze_land('4115011300106840001', building_type=None, floor_area_m2=None, assessment_date=None, recorder=Recorder(), agent=agent, site=nothing_touches))['analysis']['review']['items'][0]
    assert item['status'] == 'needs_check' and 'law_judge' in calls
    assert item['basis'] == 'Site: 대지 경계에 닿는 도시·군계획시설 결정 도형 없음(지적 도로·현황 도로 확인 필요) — Law: 지적 도로 자료 없음 · 확인할 것: 현황 도로 폭'
    # A classless polygon (서울's '도로') has no band; the centrelines inside it carry the measured widths.
    classless = {**SITE_ROADS['items'][0], 'name': '도로', 'kind': None, 'width_m_rule': None,
                 'centrelines': {'widths_m': [25.0, 8.0], 'nearest_width_m': 25.0, 'segments': [{'width_m': 25.0}], 'source': 'NGII'}}
    assert _road_line(classless) == '도로(등급 없음, 폭 등급 없음, 중심선 폭 25·8 m(NGII), 공유 변 50.72 m, 결정 2018-0816)'
    assert road_facts({'payload': {**SITE_ROADS, 'items': [classless]}})['planned_facilities_touching_parcel'][0]['centrelines']['widths_m'] == [25.0, 8.0]
    # A search answer without usable ids leaves the judge with the item's own article only.
    assert found_ids({'payload': LIMITS}) == [] and found_ids(None) == []
    # Without `site` (the default) nothing about roads is asked: the item stays as the Law Agent wrote it.
    calls.clear()
    item = run(analyze_land('4115011300106840001', building_type=None, floor_area_m2=None, assessment_date=None, recorder=Recorder(), agent=agent))['analysis']['review']['items'][0]
    assert 'evidence' not in item and calls == ['law_land_analyze', 'law_parcel_limits']


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


def test_ask_law_hands_off_another_roles_question_and_asks_when_unsure_without_calling_any_agent():
    calls = []

    async def agent(tool, args, *, trace=None):
        calls.append(tool)
        return {'tool': tool, 'payload': SEARCH, 'task_id': 't', 'version': 'v'}

    mass = run(ask_law('매스 쌓아 봐', pnu=None, assessment_date=None, recorder=Recorder(), agent=agent))
    assert mass['route']['kind'] == 'goal' and mass['agent'] == 'mass' and mass['answer'] is None and mass['trace_id'] is None
    assert mass['handoff'] == {'goal': 'mass', 'label': '매스 생성', 'owners': ['program', 'masterplan', 'mass', 'revision'], 'available': False}
    unsure = run(ask_law('뭐 할 수 있어?', pnu=None, assessment_date=None, recorder=Recorder(), agent=agent))
    assert unsure['route']['kind'] == 'ask' and unsure['agent'] is None and unsure['handoff'] is None
    assert [c['agent'] for c in unsure['route']['choices']][:2] == ['law', 'site_context']
    picked = run(ask_law('뭐 할 수 있어?', pnu=None, assessment_date=None, recorder=Recorder(), role='law', agent=agent))
    assert picked['route']['kind'] == 'skill' and picked['answer']['kind'] == 'search'
    assert calls == ['law_search']


def test_route_accepts_a_picked_role_and_rejects_a_malformed_one():
    client = app_with(lambda tool, args, trace=None: None)
    assert client.post('/api/v1/platform/ask', json={'text': '뭐 할 수 있어?', 'role': 'Mass Agent'}, headers={'Origin': ORIGIN}).status_code == 422
    response = client.post('/api/v1/platform/ask', json={'text': '뭐 할 수 있어?'}, headers={'Origin': ORIGIN})
    assert response.status_code == 200 and response.json()['route']['kind'] == 'ask'


def test_a_question_about_a_review_item_goes_to_the_law_agent_about_exactly_that_provision():
    from backend.app.modules.platform.ask import clause_route, settle_caps

    ordinance = {'item_id': 'landscaping', 'title': '대지의 조경', 'refs': [{'instrument': '의정부시 건축 조례', 'kind': 'ordinance', 'article': '제29조', 'clause': None}]}
    route = clause_route('연면적 900㎡면 몇 %?', ordinance, '2026-10-09')
    assert (route.kind, route.agent, route.skill, route.decided_by) == ('skill', 'law', 'law_ordinance', 'user')
    assert route.args == {'name': '의정부시 건축 조례', 'article': '제29조', 'limit': 3, 'assessment_date': '2026-10-09'}
    statute = {'item_id': 'sunlight', 'title': '일조 등의 확보를 위한 높이 제한', 'refs': [
        {'instrument': '건축법', 'kind': 'act', 'article': '제61조', 'clause': '제1항'},
        {'instrument': '건축법 시행령', 'kind': 'decree', 'article': '제86조', 'clause': None}]}
    route = clause_route('10m 넘으면?', statute, None)
    assert route.skill == 'law_search' and route.args['query'] == '건축법 제61조 건축법 시행령 제86조 10m 넘으면?'
    exact = {**statute, 'refs': [{**statute['refs'][0], 'hang_id': '건축법::제5장::제61조::1'}, {**statute['refs'][1], 'hang_id': '건축법(시행령)::제6장::제86조::1'}]}
    route = clause_route('10m 넘으면?', exact, '2026-10-09')
    assert (route.skill, route.args) == ('law_article', {'full_id': '건축법(시행령)::제6장::제86조', 'assessment_date': '2026-10-09'}), 'the decree by its exact id'
    normalized = normalize('law_article', {'articles': [{'jo_id': '건축법(시행령)::제6장::제86조', 'title': '일조 등의 확보를 위한 건축물의 높이 제한',
        'hangs': [{'content': '정북 방향 이격', 'hang_id': '건축법(시행령)::제6장::제86조::1'}]}]})
    assert normalized['items'] == [{'id': '건축법(시행령)::제6장::제86조::1', 'law': '건축법', 'kind': '시행령',
                                    'article': '제86조(일조 등의 확보를 위한 건축물의 높이 제한)', 'text': '정북 방향 이격'}]

    calls = []

    async def agent(tool, args, *, trace=None):
        calls.append((tool, args))
        return {'tool': tool, 'payload': {'results': [], 'stats': {'total': 0}}, 'task_id': 't', 'version': None}

    answer = run(ask_law('10m 넘으면?', pnu='4115011200109610003', assessment_date='2026-10-09', recorder=Recorder(), agent=agent, clause=statute))
    assert calls[0][0] == 'law_search'
    assert answer['clause'] == {'item_id': 'sunlight', 'title': '일조 등의 확보를 위한 높이 제한', 'pnu': '4115011200109610003', 'assessment_date': '2026-10-09'}

    review = {'items': [{'id': 'bcr-cap', 'status': 'needs_check', 'value': None, 'basis': 'x'}, {'id': 'far-cap', 'status': 'needs_check', 'value': None, 'basis': 'x'}]}
    settle_caps(review, {'bcr_pct': 60.0, 'far_pct': None, 'articles': {'bcr': '의정부시 도시계획 조례 제42조'}, 'policy_id': None})
    assert review['items'][0] == {'id': 'bcr-cap', 'status': 'applies', 'value': '60%', 'basis': 'Law Agent 한도 산정: 의정부시 도시계획 조례 제42조'}
    assert review['items'][1]['status'] == 'needs_check'
    # A district plan not in hand may set its own cap: the value is shown, the status stays needs_check.
    pending = {'items': [{'id': 'bcr-cap', 'status': 'needs_check', 'value': None, 'basis': 'x'},
                         {'id': 'district-지구단위계획구역', 'group': 'district', 'title': '지구단위계획구역', 'status': 'needs_source'}]}
    settle_caps(pending, {'bcr_pct': 60.0, 'articles': {}, 'policy_id': None})
    assert pending['items'][0]['status'] == 'needs_check' and pending['items'][0]['value'] == '60%' and '지구단위계획구역 확보 전' in pending['items'][0]['basis']
    # Law itself says the parcel is inside a 지구단위계획구역 and applied no lot rule: the ordinance value is shown as a ceiling.
    inside = {'items': [{'id': 'far-cap', 'status': 'needs_check', 'value': None, 'basis': 'x'}]}
    settle_caps(inside, {'far_pct': 250.0, 'articles': {'far': '의정부시 도시계획 조례 제46조'}, 'policy_id': None, 'district_plan_review_needed': True})
    assert inside['items'][0]['status'] == 'needs_check' and inside['items'][0]['value'] == '250%'
    assert inside['items'][0]['basis'] == 'Law Agent 한도 산정: 의정부시 도시계획 조례 제46조 — 지구단위계획구역 안이라 이 값은 조례 상한이고, 획지 값은 지구단위 검토에서 정해져요'
    ordinance = {'item_id': 'x', 'title': 't', 'refs': [{'instrument': '의정부시 도시계획 조례', 'kind': 'ordinance', 'article': '제42조', 'clause': None, 'edition_id': '2072835'}]}
    assert 'edition_id' not in clause_route('q', ordinance, None).args


def test_an_address_is_located_through_the_editors_own_geocoder_without_any_agent_call():
    from backend.app.modules.platform.ask import locate_site
    calls = []

    class Addresses:
        async def resolve_address(self, address):
            calls.append(address)
            if address.startswith('없는'):
                return {'success': False, 'address': address, 'pnu': None, 'error': 'Address lookup returned no usable result'}
            return {'success': True, 'address': address, 'pnu': '4115011300106840001', 'coordinates': {'x': 127.108, 'y': 37.730}, 'geocoded_address': '경기도 의정부시 산곡동 684-1'}

    async def agent(tool, args, *, trace=None):
        raise AssertionError('no agent should be asked')

    recorder = Recorder()
    found = run(ask_law('의정부시 산곡동 684-1', pnu=None, assessment_date=None, recorder=recorder, agent=agent, addresses=Addresses()))
    assert found['route']['kind'] == 'skill' and found['agent'] == 'site_context' and found['tool'] == 'site_locate' and found['trace_id'] is None
    assert found['answer'] == {'kind': 'site', 'query': '의정부시 산곡동 684-1', 'pnu': '4115011300106840001', 'address': '경기도 의정부시 산곡동 684-1',
                               'coordinates': {'x': 127.108, 'y': 37.730}, 'error': None}
    assert calls == ['의정부시 산곡동 684-1'] and recorder.rows == []
    missing = run(ask_law('없는시 없는동 1', pnu=None, assessment_date=None, recorder=recorder, agent=agent, addresses=Addresses()))
    assert missing['answer']['pnu'] is None and missing['answer']['error'] == 'Address lookup returned no usable result'
    by_pnu = run(locate_site('4115011300106840001', addresses=Addresses()))
    assert by_pnu['pnu'] == '4115011300106840001' and calls == ['의정부시 산곡동 684-1', '없는시 없는동 1']


def test_ask_hands_a_question_to_a_registered_agent_in_its_own_card_words_without_calling_it(monkeypatch):
    import asyncio

    monkeypatch.setenv('EDITOR_ROUTING_JUDGE', 'llm')

    from backend.app.core.tracing import JsonlTraceRecorder
    from backend.app.modules.platform.ask import ask_law
    from backend.app.modules.platform.routing.judge import Ledger

    async def judge(text, situation=''):
        return Ledger.model_validate({'is_request_satisfied': {'reason': 'r', 'answer': False},
                                      'next_speaker': {'reason': '구조 질문이에요', 'answer': 'structure'},
                                      'instruction_or_question': {'reason': 'r', 'answer': '이 매스의 골조 안을 내 주세요'}})

    async def roster(agents):
        assert agents == ['structure']
        return {'structure': {'name': 'StructureAgent', 'description': 'Frames and walls for a mass.',
                              'skills': [{'id': 'structure_frame', 'name': 'frame', 'description': ''}, {'id': 'structure_health', 'name': 'health', 'description': ''}]}}

    async def never(tool, args, trace=None):
        raise AssertionError('no agent is called for a delegation')
    answer = asyncio.run(ask_law('기둥 간격 어떻게?', pnu=None, assessment_date=None, recorder=JsonlTraceRecorder(), agent=never, judge=judge,
                                 roster=roster, extras=['structure']))
    assert answer['route']['kind'] == 'agent' and answer['agent'] == 'structure' and answer['answer'] is None and answer['handoff'] is None
    assert answer['delegate'] == {'agent': 'structure', 'label': 'StructureAgent', 'description': 'Frames and walls for a mass.',
                                  'instruction': '이 매스의 골조 안을 내 주세요', 'skills': [{'id': 'structure_frame', 'name': 'frame'}, {'id': 'structure_health', 'name': 'health'}],
                                  'available': True}
