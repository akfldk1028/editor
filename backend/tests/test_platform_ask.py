"""`POST /api/v1/platform/ask`: a typed question reaches the Law Agent over A2A and comes back in one shape.
Payloads below are the Law Agent's own answers of 2026-10-08 (law_search '자연녹지지역 건폐율', law_ordinance 의정부시 조례 제42조), trimmed."""
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.adapters import law_agent
from backend.app.modules.platform.ask import ask_law, normalize, plan
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
    assert set(answer) == {'question', 'tool', 'agent', 'trace_id', 'version', 'answer'}
    assert answer['agent'] == 'law' and answer['trace_id'] == '4bf92f3577b34da6a3ce929d0e0e4736' and answer['answer']['kind'] == 'search'
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


def test_ask_schema_is_strict():
    assert AskCreate(text=' 건폐율 ').text == '건폐율'
    with pytest.raises(ValueError):
        AskCreate(text='x', pnu=4115011300106830000)
