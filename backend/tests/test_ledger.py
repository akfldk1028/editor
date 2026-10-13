"""협업 장부: the record shape, the sqlite store, the daily mirror, the service, and the door (post, read, tail)."""
import asyncio
import json
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.modules.ledger import HopRecord, Ledger, LedgerStore, from_hop_log, from_otlp_payload, message_text
from backend.app.modules.ledger.export import DailyMirror
from backend.app.modules.ledger.router import create_ledger_router, stream_events
from backend.app.modules.ledger.schema import to_otlp_span

HOP = {'ts': '2026-10-12T10:51:56.559Z', 'agent': 'site_context', 'version': '0.1.0+a455211', 'tool': 'site_resolve',
       'trace': {'caller': 'orchestrator', 'trace_id': 'a' * 32, 'span_id': 'b' * 16, 'hop': '1', 'run_id': 'run1', 'project': 'p', 'branch': 'main',
                 'from_agent': 'orchestrator', 'to_agent': 'site_context'},
       'a2a_task_id': 'c639', 'a2a_context_id': 'run1', 'args': {'pnu': '4115011300106840001'}, 'state': 'completed', 'elapsed_ms': 1200, 'reply_bytes': 184856}


def test_an_agents_hop_row_becomes_a_record_in_genai_terms_with_the_texts_and_the_a2a_facts():
    record = from_hop_log(HOP, response_text='{"status": "partial"}')
    assert (record.operation, record.from_agent, record.to_agent, record.tool, record.status, record.state) == ('invoke_agent', 'orchestrator', 'site_context', 'site_resolve', 'OK', 'completed')
    assert (record.conversation_id, record.run_id, record.task_id, record.project, record.branch, record.hop, record.source) == ('run1', 'run1', 'c639', 'p', 'main', 1, 'agent')
    assert record.ts_end == '2026-10-12T10:51:56.559Z' and record.ts_start == '2026-10-12T10:51:55.359Z' and record.elapsed_ms == 1200
    assert message_text(record.input_messages) == '{"pnu": "4115011300106840001"}' and message_text(record.output_messages) == '{"status": "partial"}'
    assert record.attrs == {'caller': 'orchestrator', 'version': '0.1.0+a455211', 'reply_bytes': 184856}
    assert from_hop_log({**HOP, 'state': 'failed'}).status == 'ERROR'
    assert from_hop_log(HOP, response_text='x', capture=False).output_messages is None
    # A row without usable ids still gets valid ones; a bad trace id is replaced, not rejected.
    loose = from_hop_log({'ts': 'bad', 'agent': 'law', 'tool': 'law_search', 'trace': {'trace_id': 'nope'}})
    assert len(loose.trace_id) == 32 and len(loose.span_id) == 16 and loose.from_agent == 'unknown'


def test_otlp_json_spans_that_name_an_agent_are_accepted_and_a_record_exports_back_to_otlp():
    payload = {'resourceSpans': [{'resource': {'attributes': [{'key': 'service.name', 'value': {'stringValue': 'law'}}]}, 'scopeSpans': [{'spans': [
        {'traceId': 'c' * 32, 'spanId': 'd' * 16, 'name': 'invoke_agent site_context', 'startTimeUnixNano': '1760266316000000000', 'endTimeUnixNano': '1760266317200000000',
         'attributes': [{'key': 'gen_ai.operation.name', 'value': {'stringValue': 'invoke_agent'}}, {'key': 'gen_ai.agent.name', 'value': {'stringValue': 'site_context'}},
                        {'key': 'gen_ai.conversation.id', 'value': {'stringValue': 'conv1'}}, {'key': 'unknown.thing', 'value': {'intValue': '3'}}], 'status': {'code': 1}},
        {'traceId': 'c' * 32, 'spanId': 'e' * 16, 'name': 'http GET', 'attributes': []},
    ]}]}]}
    records = from_otlp_payload(payload)
    assert len(records) == 1 and records[0].to_agent == 'site_context' and records[0].from_agent == 'law' and records[0].conversation_id == 'conv1'
    assert records[0].status == 'OK' and records[0].elapsed_ms == 1200
    span = to_otlp_span(records[0])
    assert span['traceId'] == 'c' * 32 and span['name'] == 'invoke_agent site_context' and {a['key'] for a in span['attributes']} >= {'gen_ai.operation.name', 'gen_ai.agent.name', 'gen_ai.conversation.id'}


def test_the_store_keeps_one_row_per_span_updates_it_when_the_call_ends_and_answers_by_conversation_run_and_trace(tmp_path):
    store = LedgerStore(tmp_path / 'ledger.sqlite')
    first = from_hop_log({**HOP, 'state': 'working'})
    row_id = store.append(first)
    assert store.append(from_hop_log(HOP, response_text='done')) == row_id, 'the end of the same span updates the row'
    other = store.append(HopRecord(trace_id='f' * 32, span_id='1' * 16, ts_start='2026-10-12T10:00:00.000Z', from_agent='user', to_agent='orchestrator',
                                   operation='start_run', status='OK', conversation_id='conv9', run_id='run1', source='editor'))
    assert store.latest_id() == other
    assert [r['id'] for r in store.query(run_id='run1')] == [row_id, other]
    assert [r['id'] for r in store.query(conversation_id='conv9', run_ids=store.runs_of('conv9'))] == [row_id, other], 'a conversation sees the runs it started'
    assert [r['id'] for r in store.query(trace_id='a' * 32)] == [row_id]
    assert store.query(conversation_id='conv9', since_id=other) == []
    got = store.get(row_id)
    assert got['state'] == 'completed' and got['output_messages'][0]['parts'][0]['content'] == 'done' and got['attrs']['reply_bytes'] == 184856
    assert LedgerStore(tmp_path / 'ledger.sqlite').latest_id() == other, 'reopening keeps the data'


def test_the_mirror_writes_one_line_per_record_to_the_days_file_and_prunes_old_days(tmp_path):
    today = date(2026, 10, 12)
    mirror = DailyMirror(tmp_path, keep_days=2, today=lambda: today)
    mirror.write({'id': 1, 'to_agent': 'law', 'input_messages': [{'role': 'user', 'parts': [{'type': 'text', 'content': 'x'}]}]})
    mirror.write({'id': 2, 'to_agent': 'site_context', 'output_messages': [{'role': 'assistant', 'parts': [{'type': 'text', 'content': 'y' * 1_100_000}]}]})
    lines = (tmp_path / '2026-10-12.jsonl').read_text(encoding='utf-8').splitlines()
    assert json.loads(lines[0])['to_agent'] == 'law' and json.loads(lines[1])['mirror_note'].startswith('texts over 1 MiB')
    assert (tmp_path / 'README.md').is_file()
    (tmp_path / '2026-10-01.jsonl').write_text('{}\n', encoding='utf-8')
    (tmp_path / '2026-10-11.jsonl').write_text('{}\n', encoding='utf-8')
    removed = mirror.prune()
    assert [p.name for p in removed] == ['2026-10-01.jsonl'] and (tmp_path / '2026-10-11.jsonl').is_file()


def test_the_service_records_editor_calls_as_running_then_finished_links_runs_and_tells_watchers(tmp_path):
    ledger = Ledger(tmp_path)
    queue = ledger.watch()
    started = ledger.begin(from_agent='orchestrator', to_agent='law', tool='law_search', conversation_id='conv1', input_text='조경 의무 면적?')
    rows = ledger.rows(conversation_id='conv1')
    assert rows[0]['state'] == 'working' and rows[0]['status'] == 'UNSET' and rows[0]['source'] == 'editor'
    done = ledger.finish(started, output_text='제42조', status='OK')
    assert done['id'] == rows[0]['id'] and done['state'] == 'completed' and done['elapsed_ms'] >= 0 and message_text(done['output_messages']) == '제42조'
    link = ledger.link_run(conversation_id='conv1', run_id='run7', project='p', branch='main', text='법규 검토')
    ledger.ingest_hop({**HOP, 'trace': {**HOP['trace'], 'run_id': 'run7', 'trace_id': '9' * 32}, 'a2a_context_id': 'run7'})
    ids = [r['id'] for r in ledger.rows(conversation_id='conv1')]
    assert ids == [done['id'], link['id'], link['id'] + 1], "the run's agent hops belong to the conversation that started it"
    assert ledger.rows(conversation_id='other') == []
    assert [queue.get_nowait() for _ in range(4)] == [done['id'], done['id'], link['id'], link['id'] + 1]
    assert (tmp_path / 'ledger.sqlite').is_file() and any(p.suffix == '.jsonl' for p in tmp_path.iterdir()) and (tmp_path / 'README.md').is_file()


def test_the_door_takes_hops_with_the_network_token_reads_by_scope_and_tails_live(tmp_path, monkeypatch):
    monkeypatch.setenv('A2A_TOKEN', 'secret')
    ledger = Ledger(tmp_path)
    app = FastAPI()
    app.include_router(create_ledger_router(ledger, 'http://127.0.0.1:3003'), prefix='/api/v1/platform')
    client = TestClient(app)
    assert client.post('/api/v1/platform/ledger/hops', json=HOP).status_code == 401
    posted = client.post('/api/v1/platform/ledger/hops', json={**HOP, 'response_text': '{"status": "partial"}'}, headers={'Authorization': 'Bearer secret'})
    assert posted.status_code == 201 and posted.json() == {'id': 1}
    assert client.post('/api/v1/platform/ledger/hops', json={'trace': 5}, headers={'Authorization': 'Bearer secret'}).status_code == 422
    assert client.post('/api/v1/platform/ledger/v1/traces', json={'resourceSpans': []}, headers={'Authorization': 'Bearer secret'}).json() == {'partialSuccess': {}, 'accepted': 0}
    assert client.get('/api/v1/platform/ledger/hops').status_code == 400
    got = client.get('/api/v1/platform/ledger/hops', params={'run_id': 'run1'}).json()
    assert [h['id'] for h in got['hops']] == [1] and got['latest_id'] == 1 and got['hops'][0]['output_messages'][0]['parts'][0]['content'] == '{"status": "partial"}'
    assert client.get('/api/v1/platform/ledger/hops', params={'run_id': 'bad id'}).status_code == 400

    async def tail():
        stop = asyncio.Event()
        events = []
        agen = stream_events(ledger, {'conversation_id': None, 'run_id': 'run1', 'trace_id': None, 'project': None, 'branch': None}, 0, heartbeat_s=0.05, stop=stop)
        events.append(await agen.__anext__())            # the existing row
        events.append(await agen.__anext__())            # a heartbeat while nothing happens
        ledger.ingest_hop({**HOP, 'trace': {**HOP['trace'], 'span_id': '2' * 16}})
        events.append(await agen.__anext__())            # the new row, pushed by the watcher
        started = ledger.begin(from_agent='user', to_agent='orchestrator', tool='conversation', conversation_id=None, run_id='run1')
        events.append(await agen.__anext__())            # a call that started (running)
        ledger.finish(started, status='OK')
        events.append(await agen.__anext__())            # the same row again, now finished
        stop.set()
        await agen.aclose()
        return events
    events = asyncio.run(tail())
    assert events[0].startswith('id: 1\ndata: ') and events[1] == ': keep-alive\n\n' and events[2].startswith('id: 2\ndata: ')
    assert events[3].startswith('id: 3\ndata: ') and '"ts_end": null' in events[3]
    assert events[4].startswith('id: 3\ndata: ') and '"status": "OK"' in events[4] and '"ts_end": null' not in events[4]


def test_the_ask_door_records_the_persons_question_and_the_skill_it_routed_to_under_the_conversation(tmp_path):
    from backend.app.core.tracing import JsonlTraceRecorder
    from backend.app.modules.platform.ask import ask_law

    ledger = Ledger(tmp_path)

    async def agent(tool, args, trace=None):
        return {'tool': tool, 'payload': {'items': [{'law': '건축법', 'article': '제42조'}], 'total': 1}, 'task_id': 'task-9', 'version': 'v'}
    answer = asyncio.run(ask_law('조경 의무 면적', pnu=None, assessment_date=None, recorder=JsonlTraceRecorder(tmp_path / 'trace'), agent=agent,
                                 role='law', ledger=ledger, conversation_id='conv-1'))
    assert answer['route']['kind'] == 'skill'
    rows = ledger.rows(conversation_id='conv-1')
    assert [(r['from_agent'], r['to_agent'], r['tool'], r['status'], r['state']) for r in rows] == [
        ('user', 'orchestrator', 'ask', 'OK', 'completed'), ('orchestrator', 'law', 'law_search', 'OK', 'completed')]
    assert rows[1]['parent_span_id'] == rows[0]['span_id'] and rows[1]['task_id'] == 'task-9'
    assert message_text(rows[0]['input_messages']) == '조경 의무 면적' and '제42조' in message_text(rows[1]['output_messages'])
    assert ledger.rows(conversation_id='conv-2') == []


def test_a_persons_message_runs_until_its_reply_is_in_the_conversation_then_ends_with_that_reply(tmp_path):
    from backend.app.modules.platform.routers.conversation import settle_turns
    from backend.app.schemas.conversation import ConversationSnapshot

    ledger = Ledger(tmp_path)
    ledger.begin(from_agent='user', to_agent='orchestrator', tool='conversation', conversation_id='c1', input_text='건폐율은?', attrs={'message_id': 'm1'})
    ledger.begin(from_agent='user', to_agent='orchestrator', tool='conversation', conversation_id='c1', input_text='높이는?', attrs={'message_id': 'm2'})

    def snapshot(status, messages, error=None):
        return ConversationSnapshot(owner_project_id='p', branch_id='main', conversation_id='c1', revision=1, status=status, artifacts=[], error=error,
                                    messages=[{'id': i, 'role': role, 'agent': agent, 'text': text, 'at': '2026-10-12T00:00:00Z'} for i, role, agent, text in messages])

    settle_turns(ledger, snapshot('working', [('m1', 'user', None, '건폐율은?'), ('a1', 'assistant', 'law', '60%')]))
    assert all(row['ts_end'] is None for row in ledger.rows(conversation_id='c1')), 'a reply still being written leaves the call running'
    settle_turns(ledger, snapshot('working', [('m1', 'user', None, '건폐율은?'), ('a1', 'assistant', 'law', '60%'), ('m2', 'user', None, '높이는?')]))
    first, second = ledger.rows(conversation_id='c1')
    assert first['state'] == 'completed' and message_text(first['output_messages']) == '60%' and second['ts_end'] is None
    settle_turns(ledger, snapshot('failed', [('m1', 'user', None, '건폐율은?'), ('a1', 'assistant', 'law', '60%'), ('m2', 'user', None, '높이는?')], error='owner_failed'))
    assert ledger.rows(conversation_id='c1')[1]['status'] == 'ERROR' and ledger.open_calls(conversation_id='c1', tool='conversation') == []


def test_a_callers_start_row_runs_until_the_agents_row_for_the_same_span_ends_it(tmp_path):
    ledger = Ledger(tmp_path)
    start = {**HOP, 'state': 'working', 'elapsed_ms': None, 'ts': '2026-10-12T10:51:55.000Z'}
    first = ledger.ingest_hop(start)
    assert first['ts_end'] is None and first['state'] == 'working'
    done = ledger.ingest_hop({**HOP, 'response_text': '{"status": "partial"}'})
    assert done['id'] == first['id'] and done['ts_end'] == '2026-10-12T10:51:56.559Z' and done['state'] == 'completed'


def test_a_start_row_that_arrives_after_the_end_does_not_reopen_the_call(tmp_path):
    ledger = Ledger(tmp_path)
    done = ledger.ingest_hop({**HOP, 'response_text': '{"status": "partial"}'})
    late = ledger.ingest_hop({**HOP, 'state': 'working', 'elapsed_ms': None, 'ts': '2026-10-12T10:51:55.000Z'})
    assert late['id'] == done['id'] and late['ts_end'] == '2026-10-12T10:51:56.559Z' and late['state'] == 'completed'
