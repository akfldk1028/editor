"""The whole text of one dated ordinance edition from law.go.kr (DRF lawService.do, target=ordin, MST=edition).

The body is accepted only when the record says it is the edition asked for: same name, same edition serial,
in force on or before the assessment date. Articles keep the official order (chapter headings included,
marked), annexes (별표) carry their title, kind and official attachment link, the supplementary provisions
(부칙) come as the record gives them. Nothing is summarised or interpreted.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

from backend.app.modules.law.ordinances.search import _safe
from backend.app.modules.law.reference.ordinance_discovery import public_record

SOURCE = 'law.go.kr DRF lawService.do target=ordin'
ORDINANCE_URL = 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq='
CACHE_TTL_S = 600
_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def fetch_service(edition_id: str, *, oc: str, timeout: float = 60.0) -> dict:
    url = 'https://www.law.go.kr/DRF/lawService.do?' + urllib.parse.urlencode({'OC': oc, 'target': 'ordin', 'type': 'JSON', 'MST': edition_id})
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def _norm(value) -> str:
    return re.sub(r'\s+', '', str(value or ''))


def _iso(value) -> str | None:
    raw = _norm(value).replace('-', '').replace('.', '')
    if not re.fullmatch(r'\d{8}', raw):
        return None
    try:
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:])).isoformat()
    except ValueError:
        return None


def _rows(value) -> list[dict]:
    rows = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _text(value) -> str:
    """The record gives text as a string or nested lists of strings; one string, lines kept."""
    if isinstance(value, list):
        return '\n'.join(part for part in (_text(item) for item in value) if part)
    return str(value or '')


def article_number(unit: dict) -> str:
    """'004200' → 제42조, '000302' → 제3조의2 (the DRF article key)."""
    raw = unit.get('조문번호')
    raw = raw[0] if isinstance(raw, list) and raw else raw
    raw = str(raw or '').strip()
    if raw.isdigit() and len(raw) == 6:
        main, branch = int(raw[:4]), int(raw[4:])
        return f'제{main}조' + (f'의{branch}' if branch else '')
    return f'제{raw}조' if raw else ''


def ordinance_body(name: str, edition_id: str, assessment_date: str, *, fetch_service, now=None) -> dict:
    """The verified edition's whole text, or {error, reason} when the record is not the edition asked for."""
    when = date.fromisoformat(assessment_date)
    with _lock:
        cached = _cache.get(edition_id)
    if cached and time.time() - cached[0] < CACHE_TTL_S:
        payload = cached[1]
    else:
        try:
            payload = fetch_service(edition_id)
        except Exception as exc:
            return {'error': 'external_failure', 'reason': _safe(f'{type(exc).__name__}: {exc}'), 'edition_id': edition_id}
        if isinstance(payload, dict):
            with _lock:
                _cache[edition_id] = (time.time(), payload)
    law = payload.get('LawService') if isinstance(payload, dict) and isinstance(payload.get('LawService'), dict) else payload
    info = law.get('자치법규기본정보') if isinstance(law, dict) and isinstance(law.get('자치법규기본정보'), dict) else None
    if info is None:
        return {'error': 'invalid_record', 'reason': 'no 자치법규기본정보 in the official record', 'edition_id': edition_id}
    effective = _iso(info.get('시행일자'))
    checks = {'name': _norm(info.get('자치법규명')) == _norm(name), 'edition': _norm(info.get('자치법규일련번호')) == _norm(edition_id),
              'date': effective is not None and effective <= when.isoformat()}
    if not all(checks.values()):
        failed = [key for key, ok in checks.items() if not ok]
        return {'error': 'identity_mismatch', 'reason': f"record differs in {', '.join(failed)}", 'edition_id': edition_id,
                'record': {'name': info.get('자치법규명'), 'edition_id': info.get('자치법규일련번호'), 'effective_date': effective}}
    articles = []
    for unit in _rows((law.get('조문') or {}).get('조') if isinstance(law.get('조문'), dict) else law.get('조문')):
        content = str(unit.get('조내용') or '').replace('\r', '').strip()
        heading = str(unit.get('조문여부', '')).upper() == 'N'
        if not content:
            continue
        articles.append({'article': '' if heading else article_number(unit), 'title': str(unit.get('조제목') or '').strip(), 'content': content, 'heading': heading})
    annexes = []
    for row in _rows((law.get('별표') or {}).get('별표단위') if isinstance(law.get('별표'), dict) else law.get('별표')):
        row = public_record(row)
        annexes.append({'number': str(row.get('별표번호') or '').lstrip('0') or None, 'title': str(row.get('별표제목') or '').strip(),
                        'kind': str(row.get('별표구분') or '').strip() or None, 'file_kind': str(row.get('별표첨부파일구분') or '').strip() or None,
                        'file_url': row.get('별표첨부파일명') if isinstance(row.get('별표첨부파일명'), str) and row.get('별표첨부파일명', '').startswith('http') else None,
                        'content': str(row.get('별표내용') or '').replace('\r', '').strip() or None})
    supplement = law.get('부칙') if isinstance(law.get('부칙'), dict) else {}
    body = _text(supplement.get('부칙내용'))
    clock = now or (lambda: datetime.now(timezone.utc))
    return {'ordinance': {'name': str(info.get('자치법규명') or '').strip(), 'ordinance_id': _norm(info.get('자치법규ID')) or None, 'edition_id': edition_id,
                          'effective_date': effective, 'promulgated': _iso(info.get('공포일자')), 'promulgation_no': str(info.get('공포번호') or '').strip() or None,
                          'issuer': str(info.get('지자체기관명') or '').strip() or None, 'url': ORDINANCE_URL + edition_id},
            'assessment_date': assessment_date, 'articles': articles, 'annexes': annexes,
            'supplement': {'promulgated': _iso(supplement.get('부칙공포일자')), 'no': str(supplement.get('부칙공포번호') or '').strip() or None, 'content': body.replace('\r', '').strip() or None},
            'status': {'identity': 'body_verified', 'applicability': 'unknown'}, 'source': f'{SOURCE} MST={edition_id}', 'retrieved_at': clock().isoformat()}


def clear_cache() -> None:
    with _lock:
        _cache.clear()
