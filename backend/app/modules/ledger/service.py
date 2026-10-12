"""The ledger as the rest of the backend uses it: record a call (store + mirror + live notification), ingest what
agents and OTLP exporters post, link a run to the conversation that started it, and hand a live cursor to the SSE route."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from backend.app.core.tracing import SpanContext, new_span_id, new_trace_id

from .export import DailyMirror
from .schema import HopRecord, from_hop_log, from_otlp_payload, now_iso, text_message
from .store import LedgerStore

EDITOR_ROOT = Path(__file__).resolve().parents[4]  # backend/app/modules/ledger/service.py → editor
USER = 'user'
ORCHESTRATOR = 'orchestrator'


def ledger_dir(env=os.environ) -> Path:
    """`EDITOR_LEDGER_DIR`, else `<EDITOR_PLATFORM_DATA_DIR>/ledger`, else `<editor>/runtime/ledger`."""
    explicit = env.get('EDITOR_LEDGER_DIR')
    if explicit:
        return Path(explicit)
    data_dir = env.get('EDITOR_PLATFORM_DATA_DIR')
    if data_dir:
        return Path(data_dir) / 'ledger'
    return EDITOR_ROOT / 'runtime' / 'ledger'


class Ledger:
    def __init__(self, directory: Path | str, *, capture: bool = True, keep_days: int = 30):
        self.directory = Path(directory)
        self.capture = capture
        self.store = LedgerStore(self.directory / 'ledger.sqlite')
        self.mirror = DailyMirror(self.directory, keep_days=keep_days)
        self.mirror.ensure_readme()
        self.mirror.prune()
        self._watchers: set[asyncio.Queue] = set()

    @classmethod
    def from_env(cls, env=os.environ) -> 'Ledger':
        capture = (env.get('LEDGER_CAPTURE_CONTENT') or 'on').strip().lower() not in ('off', 'false', '0', 'no')
        keep = int(env.get('LEDGER_KEEP_DAYS') or 30)
        return cls(ledger_dir(env), capture=capture, keep_days=keep)

    # --- recording -------------------------------------------------------------------------------------------
    def record(self, record: HopRecord) -> dict:
        row_id = self.store.append(record)
        row = self.store.get(row_id) or {'id': row_id}
        self.mirror.write(row)
        self._notify(row_id)
        return row

    def ingest_hop(self, payload: dict) -> dict:
        """An agent's hop-log row (agents/a2a_common `_record`) with the optional `request_text`/`response_text` a sink adds."""
        return self.record(from_hop_log(payload, request_text=payload.get('request_text') if isinstance(payload.get('request_text'), str) else None,
                                        response_text=payload.get('response_text') if isinstance(payload.get('response_text'), str) else None,
                                        capture=self.capture))

    def ingest_otlp(self, payload: dict) -> int:
        count = 0
        for record in from_otlp_payload(payload, capture=self.capture):
            self.record(record)
            count += 1
        return count

    def link_run(self, *, conversation_id: str, run_id: str, project: str | None, branch: str | None, text: str | None = None,
                 requested_by: str = USER) -> dict:
        """The conversation asked the Orchestrator for a run: from now on that run's calls belong to the conversation."""
        context = SpanContext.new()
        return self.record(HopRecord(
            trace_id=context.trace_id, span_id=context.span_id, ts_start=now_iso(), ts_end=now_iso(), operation='start_run',
            from_agent=requested_by, to_agent=ORCHESTRATOR, status='OK', conversation_id=conversation_id, run_id=run_id,
            project=project, branch=branch, hop=0, source='editor',
            input_messages=[text_message('user', text)] if self.capture and text else None, attrs={}))

    def begin(self, *, from_agent: str, to_agent: str, tool: str | None, conversation_id: str | None, run_id: str | None = None,
              project: str | None = None, branch: str | None = None, input_text: str | None = None, trace: SpanContext | None = None,
              parent_span_id: str | None = None, source: str = 'editor') -> HopRecord:
        """A call the editor is about to make, recorded as running; `finish` records how it ended on the same span."""
        context = trace or SpanContext.new()
        record = HopRecord(
            trace_id=context.trace_id, span_id=context.span_id, parent_span_id=parent_span_id, ts_start=now_iso(), operation='invoke_agent',
            from_agent=from_agent, to_agent=to_agent, tool=tool, status='UNSET', state='working', conversation_id=conversation_id, run_id=run_id,
            project=project, branch=branch, hop=1, source=source,  # type: ignore[arg-type]
            input_messages=[text_message('user', input_text)] if self.capture and input_text else None, attrs={})
        self.record(record)
        return record

    def finish(self, record: HopRecord, *, output_text: str | None = None, status: str = 'OK', error_type: str | None = None,
               state: str | None = None, task_id: str | None = None) -> dict:
        started = datetime.fromisoformat(record.ts_start.replace('Z', '+00:00'))
        ended = datetime.now(timezone.utc)
        done = record.model_copy(update={
            'ts_end': now_iso(), 'status': status, 'error_type': error_type, 'state': state or ('completed' if status == 'OK' else 'failed'),
            'elapsed_ms': int((ended - started).total_seconds() * 1000), 'task_id': task_id or record.task_id,
            'output_messages': [text_message('assistant', output_text)] if self.capture and output_text else None})
        return self.record(done)

    # --- reading ---------------------------------------------------------------------------------------------
    def rows(self, *, conversation_id: str | None = None, run_id: str | None = None, trace_id: str | None = None, project: str | None = None,
             branch: str | None = None, since_id: int = 0, limit: int = 200) -> list[dict]:
        """The conversation's own calls and the calls of the runs it started; or one run's; or one trace's."""
        run_ids = self.store.runs_of(conversation_id) if conversation_id else None
        return self.store.query(conversation_id=conversation_id, run_ids=run_ids, run_id=run_id, trace_id=trace_id, project=project, branch=branch,
                                since_id=since_id, limit=limit)

    def latest_id(self) -> int:
        return self.store.latest_id()

    # --- live ------------------------------------------------------------------------------------------------
    def watch(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._watchers.add(queue)
        return queue

    def unwatch(self, queue: asyncio.Queue) -> None:
        self._watchers.discard(queue)

    def _notify(self, row_id: int) -> None:
        for queue in list(self._watchers):
            try:
                queue.put_nowait(row_id)
            except asyncio.QueueFull:
                pass


__all__ = ['Ledger', 'ledger_dir', 'new_span_id', 'new_trace_id']
