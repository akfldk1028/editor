"""W3C Trace Context for the editor's calls to the Orchestrator, and a local span recorder.

Header: `traceparent: 00-<32 hex trace-id>-<16 hex parent-id>-<2 hex flags>` (W3C Trace
Context level 1; `tracestate` is passed through untouched when a caller has one). Spans we
record ourselves use the OpenTelemetry GenAI semantic-convention names (`gen_ai.operation.name`
= invoke_agent, span name `invoke_agent <agent>`). There is no OTLP exporter yet: the recorder
appends one JSON row per span to `<trace dir>/<yyyy-mm-dd>.jsonl`.

The trace directory is `EDITOR_TRACE_DIR`, else `<EDITOR_PLATFORM_DATA_DIR>/trace` (the same
rule workspace storage uses), else `<editor>/runtime/trace`.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

EDITOR_ROOT = Path(__file__).resolve().parents[3]
TRACE_ENV = 'EDITOR_TRACE_DIR'
INVOKE_AGENT = 'invoke_agent'
_TRACEPARENT = re.compile(r'^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$')


def new_trace_id() -> str:
    return _nonzero_hex(16)


def new_span_id() -> str:
    return _nonzero_hex(8)


def _nonzero_hex(size: int) -> str:
    while True:
        value = secrets.token_hex(size)
        if value.strip('0'):
            return value


def traceparent(trace_id: str, span_id: str, *, sampled: bool = True) -> str:
    return f'00-{trace_id}-{span_id}-{"01" if sampled else "00"}'


@dataclass(frozen=True)
class SpanContext:
    trace_id: str
    span_id: str
    sampled: bool = True

    @classmethod
    def new(cls) -> 'SpanContext':
        return cls(new_trace_id(), new_span_id())

    def header(self) -> str:
        return traceparent(self.trace_id, self.span_id, sampled=self.sampled)


def parse_traceparent(value: str | None) -> SpanContext | None:
    """The context a `traceparent` header names, or None when it is absent or malformed."""
    match = _TRACEPARENT.match((value or '').strip().lower())
    if not match:
        return None
    trace_id, span_id, flags = match.groups()
    if not trace_id.strip('0') or not span_id.strip('0'):
        return None
    return SpanContext(trace_id, span_id, sampled=bool(int(flags, 16) & 1))


def child_span(parent: SpanContext | None) -> SpanContext:
    """A new span in the parent's trace; a new trace when there is no parent."""
    if parent is None:
        return SpanContext.new()
    return SpanContext(parent.trace_id, new_span_id(), parent.sampled)


def continue_or_start(header: str | None) -> SpanContext:
    """The incoming request's context when it carries a valid traceparent, else a new root."""
    return parse_traceparent(header) or SpanContext.new()


class TraceRecorder(Protocol):
    def record(self, row: dict) -> None: ...


class Span:
    """One recorded span: `start()` returns it, `end()` writes the row."""

    def __init__(self, recorder: TraceRecorder, context: SpanContext, parent: SpanContext | None, *,
                 agent: str, conversation_id: str, operation: str = INVOKE_AGENT):
        self.recorder, self.context, self.parent = recorder, context, parent
        self.agent, self.conversation_id, self.operation = agent, conversation_id, operation
        self.started = time.monotonic()
        self.ts = datetime.now(timezone.utc)

    @classmethod
    def start(cls, recorder: TraceRecorder, parent: SpanContext | None, **fields) -> 'Span':
        return cls(recorder, child_span(parent), parent, **fields)

    def end(self, status: str, *, error_type: str | None = None, run_id: str | None = None) -> dict:
        row = {
            'ts': self.ts.isoformat(timespec='milliseconds'),
            'trace_id': self.context.trace_id,
            'span_id': self.context.span_id,
            'parent_span_id': self.parent.span_id if self.parent else None,
            'name': f'{self.operation} {self.agent}',
            'gen_ai.operation.name': self.operation,
            'gen_ai.agent.name': self.agent,
            'gen_ai.conversation.id': self.conversation_id,
            'run_id': run_id,
            'status': status,
            'duration_ms': round((time.monotonic() - self.started) * 1000, 1),
            'error.type': error_type,
        }
        self.recorder.record(row)
        return row


def trace_dir(env=os.environ) -> Path:
    if env.get(TRACE_ENV):
        return Path(env[TRACE_ENV])
    platform = env.get('EDITOR_PLATFORM_DATA_DIR')
    return Path(platform) / 'trace' if platform else EDITOR_ROOT / 'runtime/trace'


class JsonlTraceRecorder:
    """Appends rows to `<directory>/<yyyy-mm-dd>.jsonl`; reads today ± 1 day back."""

    def __init__(self, directory: Path | None = None, *, today=None):
        self.directory = Path(directory) if directory else trace_dir()
        self._today = today or (lambda: datetime.now(timezone.utc).date())

    def path(self, day: date) -> Path:
        return self.directory / f'{day.isoformat()}.jsonl'

    def record(self, row: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.path(self._today()).open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')

    def rows(self, *, days: int = 1) -> list[dict]:
        today = self._today()
        found = []
        for offset in range(-days, days + 1):
            path = self.path(today + timedelta(days=offset))
            if not path.is_file():
                continue
            for line in path.read_text(encoding='utf-8').splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    found.append(row)
        return found

    def spans_for_run(self, run_id: str, *, limit: int = 500) -> dict:
        """Every span of every trace that mentions this run: by `run_id` or as conversation id."""
        rows = self.rows()
        trace_ids = sorted({row['trace_id'] for row in rows
                            if run_id in (row.get('run_id'), row.get('gen_ai.conversation.id'))})
        spans = [row for row in rows if row.get('trace_id') in trace_ids]
        return {'run_id': run_id, 'trace_ids': trace_ids, 'spans': spans[:limit], 'truncated': len(spans) > limit}
