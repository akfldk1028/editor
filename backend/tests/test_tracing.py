"""core/tracing.py: W3C traceparent ids, parse/round-trip, and the JSONL span recorder."""
import json
import re
from datetime import date

import pytest

from backend.app.core.tracing import (
    JsonlTraceRecorder, Span, SpanContext, child_span, continue_or_start, new_span_id, new_trace_id,
    parse_traceparent, trace_dir, traceparent,
)


def test_ids_are_lowercase_hex_of_the_w3c_sizes_and_never_zero():
    for _ in range(50):
        assert re.fullmatch(r'[0-9a-f]{32}', new_trace_id())
        assert re.fullmatch(r'[0-9a-f]{16}', new_span_id())
    assert new_trace_id() != new_trace_id()
    assert new_trace_id().strip('0') and new_span_id().strip('0')


def test_traceparent_round_trips_and_rejects_malformed_values():
    context = SpanContext.new()
    header = context.header()
    assert header == traceparent(context.trace_id, context.span_id)
    assert re.fullmatch(r'00-[0-9a-f]{32}-[0-9a-f]{16}-01', header)
    assert parse_traceparent(header) == context
    assert parse_traceparent('00-' + 'a' * 32 + '-' + 'b' * 16 + '-00') == SpanContext('a' * 32, 'b' * 16, sampled=False)
    assert parse_traceparent(' 00-' + 'A' * 32 + '-' + 'B' * 16 + '-01 ').trace_id == 'a' * 32
    for bad in (None, '', 'garbage', '01-' + 'a' * 32 + '-' + 'b' * 16 + '-01', '00-' + '0' * 32 + '-' + 'b' * 16 + '-01',
                '00-' + 'a' * 32 + '-' + '0' * 16 + '-01', '00-' + 'a' * 31 + '-' + 'b' * 16 + '-01', '00-' + 'g' * 32 + '-' + 'b' * 16 + '-01'):
        assert parse_traceparent(bad) is None, bad


def test_child_keeps_the_trace_and_continue_or_start_prefers_the_incoming_header():
    parent = SpanContext.new()
    child = child_span(parent)
    assert child.trace_id == parent.trace_id and child.span_id != parent.span_id
    assert child_span(None).trace_id != parent.trace_id
    assert continue_or_start(parent.header()) == parent
    fresh = continue_or_start('not-a-header')
    assert fresh.trace_id != parent.trace_id


def test_trace_dir_prefers_env_then_platform_dir_then_runtime(tmp_path):
    assert trace_dir({'EDITOR_TRACE_DIR': str(tmp_path / 't')}) == tmp_path / 't'
    assert trace_dir({'EDITOR_PLATFORM_DATA_DIR': str(tmp_path)}) == tmp_path / 'trace'
    assert trace_dir({}).parts[-2:] == ('runtime', 'trace')


def test_recorder_writes_one_row_per_span_with_the_genai_names(tmp_path):
    today = [date(2026, 10, 8)]
    recorder = JsonlTraceRecorder(tmp_path, today=lambda: today[0])
    parent = SpanContext('a' * 32, 'b' * 16)
    span = Span.start(recorder, parent, agent='orchestrator', conversation_id='editor:p:k')
    row = span.end('error', error_type='OwnerUnavailable')
    path = tmp_path / '2026-10-08.jsonl'
    assert [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] == [row]
    assert set(row) == {'ts', 'trace_id', 'span_id', 'parent_span_id', 'name', 'gen_ai.operation.name', 'gen_ai.agent.name',
                        'gen_ai.conversation.id', 'run_id', 'status', 'duration_ms', 'error.type'}
    assert row['trace_id'] == 'a' * 32 and row['parent_span_id'] == 'b' * 16 and row['span_id'] != 'b' * 16
    assert row['name'] == 'invoke_agent orchestrator' and row['gen_ai.operation.name'] == 'invoke_agent'
    assert row['gen_ai.agent.name'] == 'orchestrator' and row['gen_ai.conversation.id'] == 'editor:p:k'
    assert row['status'] == 'error' and row['error.type'] == 'OwnerUnavailable' and row['run_id'] is None
    assert isinstance(row['duration_ms'], float) and row['duration_ms'] >= 0
    assert row['ts'].endswith('+00:00')


def test_spans_for_run_reads_today_plus_minus_one_day_and_caps(tmp_path):
    today = [date(2026, 10, 8)]
    recorder = JsonlTraceRecorder(tmp_path, today=lambda: today[0])
    today[0] = date(2026, 10, 7)
    Span.start(recorder, None, agent='orchestrator', conversation_id='editor:p:k').end('ok', run_id='r1')
    today[0] = date(2026, 10, 8)
    ok = Span.start(recorder, None, agent='orchestrator', conversation_id='editor:p:k').end('ok', run_id='r1')
    other = Span.start(recorder, None, agent='orchestrator', conversation_id='editor:p:z').end('ok', run_id='r2')
    today[0] = date(2026, 10, 10)
    Span.start(recorder, None, agent='orchestrator', conversation_id='editor:p:k').end('ok', run_id='r1')
    today[0] = date(2026, 10, 8)
    (tmp_path / '2026-10-09.jsonl').write_text('{broken\n', encoding='utf-8')
    found = recorder.spans_for_run('r1')
    assert [row['trace_id'] for row in found['spans']].count(ok['trace_id']) == 1
    assert len(found['spans']) == 2 and len(found['trace_ids']) == 2 and not found['truncated']
    assert other['trace_id'] not in found['trace_ids']
    assert recorder.spans_for_run('r1', limit=1) == {**found, 'spans': found['spans'][:1], 'truncated': True}
    assert recorder.spans_for_run('nobody') == {'run_id': 'nobody', 'trace_ids': [], 'spans': [], 'truncated': False}


@pytest.mark.parametrize('header', ['00-' + 'c' * 32 + '-' + 'd' * 16 + '-01', None])
def test_a_run_traced_under_the_conversation_id_is_found_too(tmp_path, header):
    recorder = JsonlTraceRecorder(tmp_path)
    Span.start(recorder, parse_traceparent(header), agent='orchestrator', conversation_id='r9').end('ok')
    assert recorder.spans_for_run('r9')['spans'][0]['parent_span_id'] == ('d' * 16 if header else None)
