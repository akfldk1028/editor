"""One folder per conversation, for people to read what happened when a test goes wrong.

    <ledger dir>/conversations/YYYY-MM-DD/HHMMSS-<first question>-<conversation id>/   (this machine's local time)
        transcript.md   each turn: the question, every call in the order it started (who asked whom, which tool,
                        how it ended, how long, what was sent, what came back), then the answer
        calls.jsonl     the same calls as the ledger holds them, texts in full

The folder is rewritten when a user turn ends, so it always matches the ledger. `render` is pure; a call's status
is read from its own reply (`status`, `code`, `error`, `missing_evidence`), never judged here.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from .schema import message_text

REQUEST_CHARS = 2_000
REPLY_CHARS = 4_000
_UNSAFE = re.compile(r'[^\w가-힣-]+')
# Reply statuses that mean the tool answered but did not settle the question.
_UNSETTLED = {'needs_evidence', 'failed', 'error', 'rejected', 'blocked', 'unavailable'}


def is_turn(row: dict, user: str) -> bool:
    """A user's question to the network: the root of one turn."""
    return row.get('from_agent') == user and row.get('operation') == 'invoke_agent'


def reply_facts(text: str) -> dict:
    """What a JSON reply says about itself: its status, code, error and missing evidence, when it says any."""
    try:
        body = json.loads(text)
    except (TypeError, ValueError):
        return {}
    if not isinstance(body, dict):
        return {}
    return {key: body.get(key) for key in ('status', 'code', 'error', 'missing_evidence') if body.get(key)}


def outcome(row: dict) -> tuple[str, bool]:
    """(a short word for how the call ended, whether it needs a look)."""
    if not row.get('ts_end'):
        return '끝나지 않음', True
    if row.get('status') == 'ERROR' or row.get('state') in ('failed', 'rejected', 'canceled'):
        return f"실패 ({row.get('error_type') or row.get('state')})", True
    facts = reply_facts(message_text(row.get('output_messages')))
    status = str(facts.get('status') or '')
    if facts.get('error') or status in _UNSETTLED:
        detail = ', '.join(str(value) for value in (status, facts.get('code'), facts.get('error')) if value)
        missing = facts.get('missing_evidence')
        if missing:
            detail += f" · 빠진 근거: {', '.join(map(str, missing)) if isinstance(missing, list) else missing}"
        return f'답은 왔지만 미해결 ({detail})', True
    return '완료', False


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f'\n… ({len(text) - limit:,}자 더, calls.jsonl에 전체)'


def _fence(text: str) -> str:
    try:
        text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        lang = 'json'
    except (TypeError, ValueError):
        lang = ''
    return f'```{lang}\n{text}\n```'


def _local(iso: str | None) -> datetime | None:
    """The ledger's UTC time on this machine's clock, the one the chat shows."""
    try:
        return datetime.fromisoformat(str(iso).replace('Z', '+00:00')).astimezone()
    except ValueError:
        return None


def _time(iso: str | None) -> str:
    moment = _local(iso)
    return moment.strftime('%H:%M:%S') if moment else ''


def _seconds(row: dict) -> str:
    ms = row.get('elapsed_ms')
    return f'{ms / 1000:.1f} s' if isinstance(ms, (int, float)) else '-'


def turns(rows: list[dict], user: str) -> list[tuple[dict | None, list[dict]]]:
    """Calls grouped by the user turn they started under (by start time); calls before any turn come first."""
    ordered = sorted(rows, key=lambda row: (row.get('ts_start') or '', row.get('id') or 0))
    groups: list[tuple[dict | None, list[dict]]] = [(None, [])]
    for row in ordered:
        if is_turn(row, user):
            groups.append((row, []))
        else:
            groups[-1][1].append(row)
    return [group for group in groups if group[0] is not None or group[1]]


def render(conversation_id: str, rows: list[dict], user: str) -> str:
    grouped = turns(rows, user)
    calls = [row for _turn, group in grouped for row in group]
    flagged = [row for row in calls if outcome(row)[1]]
    first = next((turn for turn, _group in grouped if turn), None)
    lines = [f"# {message_text((first or {}).get('input_messages')) or conversation_id}", '',
             f'- 대화 id: `{conversation_id}`',
             f"- 프로젝트: {(first or {}).get('project') or '-'} · {(first or {}).get('branch') or '-'}",
             f'- 질문 {sum(1 for turn, _ in grouped if turn)}번 · 에이전트 호출 {len(calls)}번 · 살펴볼 호출 {len(flagged)}번', '']
    if flagged:
        lines += ['## 살펴볼 호출', '']
        lines += [f"- {_time(row.get('ts_start'))} {row.get('to_agent')} · `{row.get('tool')}` — {outcome(row)[0]}" for row in flagged]
        lines.append('')
    number = 0
    for turn, group in grouped:
        if turn is None:
            lines += ['## 질문 전 호출', '']
        else:
            number += 1
            lines += [f"## 질문 {number} ({_time(turn.get('ts_start'))}, {_seconds(turn)})", '',
                      '> ' + message_text(turn.get('input_messages')).replace('\n', '\n> '), '']
        if group:
            lines += ['| # | 시작 | 누가 → 누구 | 도구 | 결과 | 걸린 시간 |', '|---|---|---|---|---|---|']
            for index, row in enumerate(group, 1):
                lines.append(f"| {index} | {_time(row.get('ts_start'))} | {row.get('from_agent')} → {row.get('to_agent')} | "
                             f"`{row.get('tool') or '-'}` | {outcome(row)[0].replace('|', '/')} | {_seconds(row)} |")
            lines.append('')
            for index, row in enumerate(group, 1):
                lines += [f"### {index}. {row.get('to_agent')} · `{row.get('tool') or '-'}` — {outcome(row)[0]}", '']
                request = message_text(row.get('input_messages'))
                reply = message_text(row.get('output_messages'))
                if request:
                    lines += ['요청', '', _fence(_clip(request, REQUEST_CHARS)), '']
                if reply:
                    lines += ['답', '', _fence(_clip(reply, REPLY_CHARS)), '']
        if turn is not None:
            answer = message_text(turn.get('output_messages'))
            lines += ['### 최종 답', '', answer or f'(답 없음 — {outcome(turn)[0]})', '']
    return '\n'.join(lines)


def folder_name(conversation_id: str, rows: list[dict], user: str) -> str:
    first = next((row for row in sorted(rows, key=lambda r: r.get('ts_start') or '') if is_turn(row, user)), None)
    started = _local((first or (rows[0] if rows else {})).get('ts_start'))
    question = _UNSAFE.sub('-', message_text((first or {}).get('input_messages')))[:40].strip('-') or 'conversation'
    day, clock = (started.strftime('%Y-%m-%d'), started.strftime('%H%M%S')) if started else ('undated', '000000')
    return f"{day}/{clock}-{question}-{_UNSAFE.sub('-', conversation_id)[:12]}"


class ConversationLogs:
    """Writes a conversation's folder from the ledger's rows; a write that fails is skipped, never raised."""

    def __init__(self, directory: Path | str, rows: Callable[[str], Iterable[dict]], *, user: str):
        self.directory = Path(directory)
        self._rows = rows
        self.user = user

    def write(self, conversation_id: str) -> Path | None:
        try:
            rows = list(self._rows(conversation_id))
            if not rows:
                return None
            folder = self.directory / folder_name(conversation_id, rows, self.user)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'transcript.md').write_text(render(conversation_id, rows, self.user), encoding='utf-8')
            with (folder / 'calls.jsonl').open('w', encoding='utf-8') as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
            return folder
        except OSError:
            return None
