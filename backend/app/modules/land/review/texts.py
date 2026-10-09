"""Article texts for the review items, from the statute graph search (:8011, `LAW_BACKEND_URL`).

One query per distinct statute article ("건축법 제61조"); a result counts only when its law name and article
match the reference — a near miss is not shown as the article. What the search does not hold (민법, 조례,
별표, laws outside the 20-law graph) is marked `needs_source`, never "관련 법규 없음".
"""
from __future__ import annotations

import re

EXCERPT = 700


def _norm(name: str | None) -> str:
    return re.sub(r'[\s·ㆍ()]', '', name or '')


def _matches(row: dict, ref: dict) -> bool:
    instrument = ref['instrument']
    base = instrument
    kind = None
    for suffix in ('시행령', '시행규칙'):
        if instrument.endswith(suffix):
            base, kind = instrument[: -len(suffix)].strip(), suffix
    if _norm(row.get('law_name')) != _norm(base):
        return False
    row_kind = row.get('law_type') or ''
    if kind is None and row_kind in ('시행령', '시행규칙'):
        return False
    if kind is not None and row_kind != kind:
        return False
    return (row.get('article') or '') == ref['article']


def _query(ref: dict) -> str | None:
    if ref['kind'] == 'ordinance' or not ref.get('article') or ref['article'].startswith('별표'):
        return None
    return f"{ref['instrument']} {ref['article']}"


async def attach_texts(items: list[dict], law_client) -> list[str]:
    """Fills `text`/`text_status`/`hang_ids` on every ref in place; returns search errors (empty when it answered)."""
    refs = [ref for item in items for ref in item['refs']]
    queries = list(dict.fromkeys(q for q in (_query(ref) for ref in refs) if q))
    rows: dict[str, list[dict]] = {}
    errors: list[str] = []
    if queries and law_client is not None:
        try:
            answer = await law_client.search_queries(queries, limit=8, timeout=60, filter_results=False)
            for article in answer.get('articles') or []:
                rows[article['query']] = article['results']
            errors = list(answer.get('errors') or [])
        except Exception as exc:  # the review stands without texts; the gap says why
            errors = [f'Law search failed: {type(exc).__name__}']
    elif queries:
        errors = ['Law search is not configured']
    for ref in refs:
        query = _query(ref)
        hits = [row for row in rows.get(query, []) if _matches(row, ref)] if query else []
        if ref.get('clause'):
            narrowed = [row for row in hits if ref['clause'].replace('제', '').replace('항', '') in (row.get('hang_id') or '')]
            hits = narrowed or hits
        if hits:
            ref['text'] = '\n'.join(dict.fromkeys(row.get('content') or '' for row in hits))[:EXCERPT]
            ref['hang_ids'] = [row.get('hang_id') for row in hits if row.get('hang_id')]
            ref['text_status'] = 'found'
        else:
            ref['text'] = None
            ref['hang_ids'] = []
            ref['text_status'] = 'needs_source'
            ref['text_gap'] = ('조례 원문은 law.go.kr에서 Law Agent가 조문별로 가져와요' if ref['kind'] == 'ordinance'
                               else '별표는 원문 별도 확인' if (ref.get('article') or '').startswith('별표')
                               else '법령 그래프 검색에 이 조문이 없어요' if query and not errors
                               else '조문 검색이 응답하지 않았어요')
    return errors
