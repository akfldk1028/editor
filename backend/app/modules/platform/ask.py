"""A question typed in the conversation, answered by the Law Agent.

`plan` picks the Law Agent tool from the text (an ordinance name with an article → `law_ordinance`,
anything else → `law_search`, the 7-stage statute-graph search); `normalize` turns the tool's own
JSON into one UI shape without restating any legal value; `ask_law` records the hop as a span
(`invoke_agent law`, OTel GenAI names) so the conversation can show the trace.

Answer contract (every key present):
  question, tool, agent: 'law', trace_id, version,
  answer: {kind: 'search', items: [{id, law, kind, article, text}], total, degraded, legal_evidence}
        | {kind: 'ordinance', ordinance: {name, ordinance_id, edition_id, effective_date, url},
           matches: [{article, title, text}], legal_evidence}
  legal_evidence: {assessment_date, currency_status, coverage_status, reason} | null
"""
import re

from backend.app.adapters import law_agent
from backend.app.core.tracing import Span, continue_or_start

ORDINANCE = re.compile(r'(?P<name>[가-힣]+(?:\s+[가-힣]+)*?\s*조례)\s*(?P<article>제?\s*\d+\s*조(?:\s*의\s*\d+)?)')
SEARCH_LIMIT = 8
EXCERPT = 400
LAW_GO_KR = 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq='


def plan(text: str, assessment_date: str | None = None) -> tuple[str, dict]:
    """Which Law Agent tool answers this text, with its arguments."""
    dated = {'assessment_date': assessment_date} if assessment_date else {}
    match = ORDINANCE.search(text)
    if match:
        article = re.sub(r'\s+', '', match.group('article'))
        if not article.startswith('제'):
            article = '제' + article
        return 'law_ordinance', {'name': re.sub(r'\s+', ' ', match.group('name')).strip(), 'article': article, 'limit': 3, **dated}
    return 'law_search', {'query': text.strip(), 'limit': SEARCH_LIMIT, **dated}


def _str(value):
    return value if isinstance(value, str) and value else None


def _legal_evidence(value):
    if not isinstance(value, dict):
        return None
    return {key: _str(value.get(key)) for key in ('assessment_date', 'currency_status', 'coverage_status', 'reason')}


def _iso(value):
    value = _str(value) or ''
    return f'{value[:4]}-{value[4:6]}-{value[6:]}' if re.fullmatch(r'\d{8}', value) else (value or None)


def normalize(tool: str, payload: dict) -> dict:
    if tool == 'law_ordinance':
        ordinance = payload.get('ordinance') if isinstance(payload.get('ordinance'), dict) else {}
        edition = _str(ordinance.get('edition_id'))
        return {
            'kind': 'ordinance',
            'ordinance': {'name': _str(ordinance.get('name')), 'ordinance_id': _str(ordinance.get('id')), 'edition_id': edition,
                          'effective_date': _iso(ordinance.get('effective')), 'url': LAW_GO_KR + edition if edition else None},
            'matches': [{'article': _str(m.get('article')), 'title': _str(m.get('title')), 'text': (_str(m.get('content')) or '')[:EXCERPT] or None}
                        for m in payload.get('matches') or [] if isinstance(m, dict)],
            'legal_evidence': _legal_evidence(payload.get('legal_evidence')),
        }
    stats = payload.get('stats') if isinstance(payload.get('stats'), dict) else {}
    items = []
    for row in payload.get('results') or []:
        if not isinstance(row, dict):
            continue
        items.append({'id': _str(row.get('hang_id')), 'law': _str(row.get('law_name')), 'kind': _str(row.get('law_type')),
                      'article': _str(row.get('article')), 'text': (_str(row.get('content')) or '')[:EXCERPT] or None})
    return {'kind': 'search', 'items': items,
            'total': stats.get('total') if isinstance(stats.get('total'), int) else len(items),
            'degraded': stats.get('degraded') is True,
            'legal_evidence': _legal_evidence(payload.get('legal_evidence'))}


async def ask_law(question: str, *, pnu: str | None, assessment_date: str | None, recorder, traceparent: str | None = None,
                  agent=law_agent.ask) -> dict:
    """One question → one Law Agent tool call → the answer; the hop is one recorded span."""
    tool, args = plan(question, assessment_date)
    span = Span.start(recorder, continue_or_start(traceparent), agent='law', conversation_id=f'editor:ask:{pnu or "-"}')
    trace = {'caller': 'editor', 'trace_id': span.context.trace_id, 'span_id': span.context.span_id, 'hop': 1}
    try:
        raw = await agent(tool, args, trace=trace)
    except Exception as exc:
        span.end('error', error_type=type(exc).__name__)
        raise
    span.end('ok')
    return {'question': question, 'tool': tool, 'agent': 'law', 'trace_id': span.context.trace_id, 'version': raw.get('version'),
            'answer': normalize(tool, raw.get('payload') or {})}
