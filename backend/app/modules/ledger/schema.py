"""The record shape (OpenTelemetry GenAI names where they exist, `ace.*` facts where they do not) and the
converters from what the network already emits: an agent's hop-log row (agents/a2a_common/protocol.py `_record`)
and an OTLP/HTTP JSON trace export."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.core.tracing import new_span_id, new_trace_id

Operation = Literal['invoke_agent', 'execute_tool', 'start_run']
Status = Literal['OK', 'ERROR', 'UNSET']
Source = Literal['agent', 'orchestrator', 'editor']

_HEX32 = re.compile(r'^[0-9a-f]{32}$')
_HEX16 = re.compile(r'^[0-9a-f]{16}$')
TEXT_CAP = 262_144


def text_message(role: str, text: str) -> dict:
    """One GenAI message (`gen_ai.input.messages` / `gen_ai.output.messages` item) carrying one text part."""
    return {'role': role, 'parts': [{'type': 'text', 'content': text[:TEXT_CAP]}]}


def message_text(messages: list[dict] | None) -> str:
    """The text of a GenAI message list, parts joined."""
    return ''.join(str(part.get('content', '')) for message in messages or [] if isinstance(message, dict)
                   for part in message.get('parts') or [] if isinstance(part, dict) and part.get('type') == 'text')


class HopRecord(BaseModel):
    """One call between two parties of the network. `from_agent`/`to_agent` are network ids (`gen_ai.agent.name`);
    `conversation_id` is a real identifier (the A2A context id or the editor's conversation id), never synthesized."""
    model_config = ConfigDict(strict=True, extra='forbid')
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    ts_start: str
    ts_end: str | None = None
    operation: Operation = 'invoke_agent'
    from_agent: str
    to_agent: str
    tool: str | None = None
    status: Status = 'UNSET'
    error_type: str | None = None
    # The A2A task state word (completed · failed · rejected · canceled · input_required · working) — not the status.
    state: str | None = None
    elapsed_ms: int | None = None
    conversation_id: str | None = None
    run_id: str | None = None
    task_id: str | None = None
    project: str | None = None
    branch: str | None = None
    hop: int | None = None
    source: Source = 'agent'
    input_messages: list[dict] | None = None
    output_messages: list[dict] | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)

    @field_validator('trace_id')
    @classmethod
    def _trace(cls, value: str) -> str:
        if not _HEX32.match(value):
            raise ValueError('trace_id must be 32 lowercase hex characters')
        return value

    @field_validator('span_id', 'parent_span_id')
    @classmethod
    def _span(cls, value: str | None) -> str | None:
        if value is not None and not _HEX16.match(value):
            raise ValueError('span ids must be 16 lowercase hex characters')
        return value


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def now_iso() -> str:
    return _iso(datetime.now(timezone.utc))


def _parse(ts: Any) -> datetime | None:
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00'))
    except ValueError:
        return None


def _hex(value: Any, pattern: re.Pattern[str], make) -> str:
    text = str(value).lower() if value is not None else ''
    return text if pattern.match(text) else make()


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != '' else None
    except (TypeError, ValueError):
        return None


STATE_STATUS = {'completed': 'OK', 'failed': 'ERROR', 'rejected': 'ERROR', 'canceled': 'ERROR'}


def from_hop_log(row: dict, *, request_text: str | None = None, response_text: str | None = None, capture: bool = True) -> HopRecord:
    """A row as agents/a2a_common/protocol.py `_record` writes it (plus the texts a network sink adds), as a HopRecord.
    The row is written when the call ends, so `ts` is the end and the start is `elapsed_ms` earlier."""
    if not isinstance(row.get('agent'), str) or not row['agent']:
        raise ValueError('a hop record names the agent that answered')
    trace = row.get('trace') if isinstance(row.get('trace'), dict) else {}
    ended = _parse(row.get('ts')) or datetime.now(timezone.utc)
    elapsed = _int(row.get('elapsed_ms'))
    started = ended - timedelta(milliseconds=elapsed) if elapsed is not None else ended
    state = str(row.get('state') or '') or None
    args = row.get('args')
    request = request_text if isinstance(request_text, str) else (json.dumps(args, ensure_ascii=False, default=str) if isinstance(args, dict) else None)
    to_agent = str(row.get('agent') or trace.get('to_agent') or 'unknown')
    attrs = {key: trace[key] for key in ('caller', 'parent_task_id', 'request_id', 'round') if key in trace}
    for key in ('version', 'reply_bytes'):
        if key in row:
            attrs[key] = row[key]
    return HopRecord(
        trace_id=_hex(trace.get('trace_id'), _HEX32, new_trace_id), span_id=_hex(trace.get('span_id'), _HEX16, new_span_id),
        parent_span_id=_hex(trace.get('parent_span_id'), _HEX16, lambda: None) if trace.get('parent_span_id') else None,
        ts_start=_iso(started), ts_end=_iso(ended), operation='invoke_agent',
        from_agent=str(trace.get('from_agent') or trace.get('caller') or 'unknown'), to_agent=to_agent,
        tool=str(row['tool']) if row.get('tool') else None, status=STATE_STATUS.get(state or '', 'UNSET'),
        error_type=None, state=state, elapsed_ms=elapsed,
        conversation_id=(str(trace['conversation_id']) if trace.get('conversation_id') else None) or (str(row['a2a_context_id']) if row.get('a2a_context_id') else None),
        run_id=str(trace['run_id']) if trace.get('run_id') else None, task_id=str(row['a2a_task_id']) if row.get('a2a_task_id') else None,
        project=str(trace['project']) if trace.get('project') else None, branch=str(trace['branch']) if trace.get('branch') else None,
        hop=_int(trace.get('hop')), source='orchestrator' if to_agent == 'orchestrator' else 'agent',
        input_messages=[text_message('user', request)] if capture and request else None,
        output_messages=[text_message('assistant', response_text)] if capture and isinstance(response_text, str) and response_text else None,
        attrs=attrs,
    )


def _otlp_attrs(items: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items or []:
        if not isinstance(item, dict) or not isinstance(item.get('key'), str):
            continue
        value = item.get('value')
        if isinstance(value, dict):
            value = next(iter(value.values()), None)
        out[item['key']] = value
    return out


def _nanos(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value) / 1e9, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def from_otlp_payload(payload: dict, *, capture: bool = True) -> list[HopRecord]:
    """OTLP/HTTP JSON (`resourceSpans[].scopeSpans[].spans[]`) as HopRecords, one per span that names an agent or a
    tool (`gen_ai.*` attributes); other spans are ignored. Unknown fields are ignored as the OTLP spec asks."""
    records: list[HopRecord] = []
    for resource in payload.get('resourceSpans') or []:
        if not isinstance(resource, dict):
            continue
        resource_attrs = _otlp_attrs((resource.get('resource') or {}).get('attributes'))
        for scope in resource.get('scopeSpans') or []:
            for span in (scope or {}).get('spans') or []:
                if not isinstance(span, dict):
                    continue
                attrs = {**resource_attrs, **_otlp_attrs(span.get('attributes'))}
                operation = attrs.get('gen_ai.operation.name')
                if operation not in ('invoke_agent', 'execute_tool'):
                    continue
                started, ended = _nanos(span.get('startTimeUnixNano')), _nanos(span.get('endTimeUnixNano'))
                status = (span.get('status') or {}).get('code')
                input_text = attrs.get('gen_ai.input.messages')
                output_text = attrs.get('gen_ai.output.messages')
                records.append(HopRecord(
                    trace_id=_hex(span.get('traceId'), _HEX32, new_trace_id), span_id=_hex(span.get('spanId'), _HEX16, new_span_id),
                    parent_span_id=str(span['parentSpanId']).lower() if _HEX16.match(str(span.get('parentSpanId') or '').lower()) else None,
                    ts_start=_iso(started or datetime.now(timezone.utc)), ts_end=_iso(ended) if ended else None, operation=operation,
                    from_agent=str(attrs.get('ace.from_agent') or resource_attrs.get('service.name') or 'unknown'),
                    to_agent=str(attrs.get('gen_ai.agent.name') or attrs.get('gen_ai.tool.name') or 'unknown'),
                    tool=str(attrs['gen_ai.tool.name']) if attrs.get('gen_ai.tool.name') else None,
                    status='OK' if status in (1, 'STATUS_CODE_OK') else 'ERROR' if status in (2, 'STATUS_CODE_ERROR') else 'UNSET',
                    error_type=str(attrs['error.type']) if attrs.get('error.type') else None, state=str(attrs['ace.state']) if attrs.get('ace.state') else None,
                    elapsed_ms=int((ended - started).total_seconds() * 1000) if started and ended else None,
                    conversation_id=str(attrs['gen_ai.conversation.id']) if attrs.get('gen_ai.conversation.id') else None,
                    run_id=str(attrs['ace.run_id']) if attrs.get('ace.run_id') else None, task_id=str(attrs['ace.a2a.task_id']) if attrs.get('ace.a2a.task_id') else None,
                    project=str(attrs['ace.project']) if attrs.get('ace.project') else None, branch=str(attrs['ace.branch']) if attrs.get('ace.branch') else None,
                    hop=_int(attrs.get('ace.hop')), source='agent',
                    input_messages=[text_message('user', str(input_text))] if capture and input_text else None,
                    output_messages=[text_message('assistant', str(output_text))] if capture and output_text else None,
                    attrs={key: value for key, value in attrs.items() if not key.startswith(('gen_ai.input', 'gen_ai.output'))},
                ))
    return records


def to_otlp_span(record: HopRecord) -> dict:
    """The record as one OTLP JSON span, for export to any OTLP backend unchanged."""
    def attr(key, value):
        return {'key': key, 'value': {'stringValue': str(value)}}
    started, ended = _parse(record.ts_start), _parse(record.ts_end)
    attributes = [attr('gen_ai.operation.name', record.operation), attr('gen_ai.agent.name', record.to_agent), attr('ace.from_agent', record.from_agent)]
    for key, value in (('gen_ai.tool.name', record.tool), ('gen_ai.conversation.id', record.conversation_id), ('ace.run_id', record.run_id),
                       ('ace.a2a.task_id', record.task_id), ('ace.project', record.project), ('ace.branch', record.branch), ('ace.hop', record.hop),
                       ('ace.state', record.state), ('error.type', record.error_type)):
        if value is not None:
            attributes.append(attr(key, value))
    if record.input_messages:
        attributes.append(attr('gen_ai.input.messages', json.dumps(record.input_messages, ensure_ascii=False)))
    if record.output_messages:
        attributes.append(attr('gen_ai.output.messages', json.dumps(record.output_messages, ensure_ascii=False)))
    return {'traceId': record.trace_id, 'spanId': record.span_id, **({'parentSpanId': record.parent_span_id} if record.parent_span_id else {}),
            'name': f'{record.operation} {record.to_agent}', 'kind': 3,
            'startTimeUnixNano': str(int(started.timestamp() * 1e9)) if started else '0', 'endTimeUnixNano': str(int(ended.timestamp() * 1e9)) if ended else '0',
            'attributes': attributes, 'status': {'code': {'OK': 1, 'ERROR': 2}.get(record.status, 0)}}
