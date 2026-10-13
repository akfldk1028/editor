"""The human-readable mirror: one NDJSON line per recorded call in `<ledger dir>/YYYY-MM-DD.jsonl` (the day it was
recorded, UTC), like the OpenTelemetry Collector's file exporter. Append only; a line longer than 1 MiB keeps its
head and says so; files older than `keep_days` are deleted, never truncated in place. The SQLite file is the record;
this is for eyes and `tail -f`."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

MAX_LINE_BYTES = 1_048_576
README = """# 협업 장부 (ledger)

- `ledger.sqlite` — the record: table `agent_calls`, one row per agent-to-agent call (W3C trace/span ids, GenAI operation,
  from/to agent, tool, status, A2A state, conversation/run/task ids, request and reply as GenAI message JSON).
- `YYYY-MM-DD.jsonl` — the same rows as they were recorded that day (UTC), one JSON object per line, for people and tails.
  Written by the editor backend only; agents post their hops to `POST /api/v1/platform/ledger/hops` (bearer A2A_TOKEN),
  OTLP/HTTP JSON exporters to `POST /api/v1/platform/ledger/v1/traces`.
- `conversations/YYYY-MM-DD/HHMMSS-<question>-<id>/` — one folder per conversation, rewritten when a question is
  answered: `transcript.md` (each question, every call in order with its request, reply and outcome, the answer; calls
  that failed or answered without settling listed first) and `calls.jsonl` (those calls in full).
- Field names follow the OpenTelemetry GenAI semantic conventions where they exist (`invoke_agent`, `execute_tool`,
  `gen_ai.conversation.id` = `conversation_id`, GenAI message JSON); A2A-only facts keep their own names (`task_id`, `run_id`, `hop`).
"""


class DailyMirror:
    def __init__(self, directory: Path | str, *, keep_days: int = 30, today=None):
        self.directory = Path(directory)
        self.keep_days = max(1, int(keep_days))
        self._today = today or (lambda: datetime.now(timezone.utc).date())

    def path(self, day: date) -> Path:
        return self.directory / f'{day.isoformat()}.jsonl'

    def ensure_readme(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        readme = self.directory / 'README.md'
        if not readme.is_file() or readme.read_text(encoding='utf-8') != README:
            readme.write_text(README, encoding='utf-8')

    def write(self, row: dict) -> None:
        """Appends the row to today's file; a row that cannot be written is dropped, never raised into the call it describes."""
        try:
            self.ensure_readme()
            line = json.dumps(row, ensure_ascii=False, default=str)
            if len(line.encode('utf-8')) > MAX_LINE_BYTES:
                head = {key: row[key] for key in row if key not in ('input_messages', 'output_messages')}
                line = json.dumps({**head, 'input_messages': None, 'output_messages': None, 'mirror_note': 'texts over 1 MiB left to the sqlite record'}, ensure_ascii=False, default=str)
            with self.path(self._today()).open('a', encoding='utf-8') as handle:
                handle.write(line + '\n')
        except OSError:
            pass

    def prune(self) -> list[Path]:
        """Deletes daily files older than `keep_days`; returns what it deleted."""
        cutoff = self._today() - timedelta(days=self.keep_days)
        removed = []
        for path in self.directory.glob('????-??-??.jsonl'):
            try:
                day = date.fromisoformat(path.stem)
            except ValueError:
                continue
            if day < cutoff:
                try:
                    path.unlink()
                    removed.append(path)
                except OSError:
                    pass
        return removed
