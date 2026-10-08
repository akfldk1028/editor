"""A question typed in the conversation, answered by the Law Agent.

`routing.route` picks the agent and skill for the text (one rule table; `plan` keeps the old name);
`normalize` turns the tool's own JSON into one UI shape without restating any legal value; `ask_law`
records the hop as a span (`invoke_agent law`, OTel GenAI names) so the conversation can show the trace.

Answer contract (every key present):
  question, tool, agent: 'law', trace_id, version, route: {agent, skill, confidence, reason},
  answer: {kind: 'search', items: [{id, law, kind, article, text}], total, degraded, legal_evidence}
        | {kind: 'ordinance', ordinance: {name, ordinance_id, edition_id, effective_date, url},
           matches: [{article, title, text}], legal_evidence}
  legal_evidence: {assessment_date, currency_status, coverage_status, reason} | null
"""
import asyncio
import re

from backend.app.adapters import law_agent
from backend.app.core.tracing import Span, continue_or_start
from backend.app.modules.platform.routing import route
from backend.app.modules.platform.run_results import law_from_response

EXCERPT = 400
LAW_GO_KR = 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq='


def plan(text: str, assessment_date: str | None = None) -> tuple[str, dict]:
    """Which Law Agent tool answers this text, with its arguments (the routing table decides)."""
    chosen = route(text, assessment_date=assessment_date)
    return chosen.skill, chosen.args


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
    if tool == 'law_article':
        # One article: the agent's dict as it is, under the search shape so the UI reads it the same way.
        payload = {'results': [payload] if payload else [], 'stats': {'total': 1 if payload else 0}, 'legal_evidence': payload.get('legal_evidence')}
        tool = 'law_search'
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


def _summary(analysis: dict) -> dict:
    """The few numbers the conversation says about a land analysis (the artifact shows the rest)."""
    zone = analysis.get('zone_info') if isinstance(analysis.get('zone_info'), dict) else {}
    assessment = analysis.get('assessment') if isinstance(analysis.get('assessment'), dict) else {}
    coverage = assessment.get('municipal_coverage') if isinstance(assessment.get('municipal_coverage'), dict) else {}
    missing = [code for code in [*(assessment.get('missing_evidence') or []), *(coverage.get('missing_evidence') or [])] if isinstance(code, str)]
    return {'zones': [z for z in zone.get('zones') or [] if isinstance(z, str)],
            'unmatched_zones': [z for z in zone.get('unmatched') or [] if isinstance(z, str)],
            'zone_areas_m2': {k: v for k, v in (zone.get('zone_areas_m2') or {}).items() if isinstance(k, str) and isinstance(v, (int, float))},
            'restrictions': [r for r in analysis.get('restrictions') or [] if isinstance(r, str)],
            'assessment_status': _str(assessment.get('status')),
            'permit_compliance_verified': assessment.get('permit_compliance_verified') is True,
            'missing_evidence': list(dict.fromkeys(missing))}


async def analyze_land(pnu: str, *, building_type: str | None, floor_area_m2: float | None, assessment_date: str | None, recorder,
                       traceparent: str | None = None, agent=law_agent.ask) -> dict:
    """The law artifact's analysis, from the Law Agent: `law_land_analyze` (the 42 regulations, lines, articles —
    the whole answer) and `law_parcel_limits` (the parcel's caps: district policy / ordinance, area-weighted),
    asked together; each hop is one span. `limits` is null when that call failed (the analysis still answers)."""
    parent = continue_or_start(traceparent)
    dated = {'assessment_date': assessment_date} if assessment_date else {}
    land_args = {'input': pnu, 'input_type': 'pnu', 'full': True, 'include_law': True, 'building_type': building_type or '',
                 'floor_area_m2': floor_area_m2, **dated}
    limits_args = {'pnu': pnu, **({'building_type': building_type} if building_type else {})}

    async def hop(tool, args):
        span = Span.start(recorder, parent, agent='law', conversation_id=f'editor:law-analysis:{pnu}')
        trace = {'caller': 'editor', 'trace_id': span.context.trace_id, 'span_id': span.context.span_id, 'hop': 1, 'tool': tool}
        try:
            raw = await agent(tool, args, trace=trace)
        except Exception as exc:
            span.end('error', error_type=type(exc).__name__)
            raise
        span.end('ok')
        return raw

    land, limits = await asyncio.gather(hop('law_land_analyze', land_args), hop('law_parcel_limits', limits_args), return_exceptions=True)
    if isinstance(land, BaseException):
        raise land
    payload = land.get('payload') or {}
    analysis = payload.get('raw') if isinstance(payload.get('raw'), dict) else payload
    limits_error = None
    if isinstance(limits, BaseException):
        limits_error = f'{type(limits).__name__}: {limits}'
        limits = None
    return {'pnu': pnu, 'agent': 'law', 'trace_id': parent.trace_id, 'version': land.get('version'),
            'analysis': analysis, 'findings': [f for f in payload.get('findings') or [] if isinstance(f, dict)],
            'limits': law_from_response(limits['payload']) if limits else None, 'limits_error': limits_error,
            'summary': _summary(analysis)}


async def ask_law(question: str, *, pnu: str | None, assessment_date: str | None, recorder, traceparent: str | None = None,
                  agent=law_agent.ask) -> dict:
    """One question → one Law Agent tool call → the answer; the hop is one recorded span."""
    chosen = route(question, assessment_date=assessment_date)
    tool, args = chosen.skill, chosen.args
    span = Span.start(recorder, continue_or_start(traceparent), agent=chosen.agent, conversation_id=f'editor:ask:{pnu or "-"}')
    trace = {'caller': 'editor', 'trace_id': span.context.trace_id, 'span_id': span.context.span_id, 'hop': 1, 'tool': tool}
    try:
        raw = await agent(tool, args, trace=trace)
    except Exception as exc:
        span.end('error', error_type=type(exc).__name__)
        raise
    span.end('ok')
    return {'question': question, 'tool': tool, 'agent': chosen.agent, 'trace_id': span.context.trace_id, 'version': raw.get('version'),
            'route': chosen.to_dict(), 'answer': normalize(tool, raw.get('payload') or {})}
