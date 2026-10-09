"""A question typed in the conversation, answered by the Law Agent.

`routing.route` picks the agent and skill — or a goal, or a question — for the text (role rule tables);
`normalize` turns the tool's own JSON into one UI shape without restating any legal value; `ask_law`
records the hop as a span (`invoke_agent law`, OTel GenAI names) so the conversation can show the trace.

Answer contract (every key present):
  question, route: {kind, agent, skill, goal, confidence, reason, choices[]}, agent, tool, trace_id, version,
  handoff: {goal, label, owners[], available} | null,
  answer: {kind: 'search', items: [{id, law, kind, article, text}], total, degraded, legal_evidence}
        | {kind: 'ordinance', ordinance: {name, ordinance_id, edition_id, effective_date, url},
           matches: [{article, title, text}], legal_evidence}
  legal_evidence: {assessment_date, currency_status, coverage_status, reason} | null
"""
import asyncio
import re

from backend.app.adapters import law_agent
from backend.app.core.tracing import Span, continue_or_start
from backend.app.modules.platform.goals import goal
from backend.app.modules.platform.routing import decide
from backend.app.modules.platform.run_results import law_from_response

EXCERPT = 400
LAW_GO_KR = 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq='


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
        # Whole articles with their 항 (law_article): one row per 항, under the search shape so the UI reads it the same way.
        rows = []
        for article in payload.get('articles') or []:
            if not isinstance(article, dict):
                continue
            head = str(article.get('jo_id') or '').split('::')[0]
            law, _, kind = head.partition('(')
            number = next((p for p in str(article.get('jo_id') or '').split('::') if re.fullmatch(r'제\d+조(의\d+)?', p)), None)
            label = f"{number}({article.get('title')})" if number and article.get('title') else number
            for hang in article.get('hangs') or [{'content': article.get('content'), 'hang_id': article.get('jo_id')}]:
                rows.append({'hang_id': hang.get('hang_id'), 'law_name': law or None, 'law_type': kind.rstrip(')') or '법률',
                             'article': label, 'content': hang.get('content')})
        payload = {'results': rows, 'stats': {'total': len(rows)}, 'legal_evidence': payload.get('legal_evidence')}
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
    caps = law_from_response(limits['payload']) if limits else None
    settle_caps(analysis.get('review'), caps)
    return {'pnu': pnu, 'agent': 'law', 'trace_id': parent.trace_id, 'version': land.get('version'),
            'analysis': analysis, 'findings': [f for f in payload.get('findings') or [] if isinstance(f, dict)],
            'limits': caps, 'limits_error': limits_error,
            'summary': _summary(analysis)}


def settle_caps(review, caps) -> None:
    """The Law Agent's two answers meet here: when `law_parcel_limits` set a cap, the review's cap item reads it
    (status applies, value, basis naming the policy/article) instead of 'needs_check'. No value is computed."""
    if not isinstance(review, dict) or not caps:
        return
    for item in review.get('items') or []:
        key = {'bcr-cap': 'bcr', 'far-cap': 'far'}.get(item.get('id'))
        value = caps.get(f'{key}_pct') if key else None
        if not isinstance(value, (int, float)):
            continue
        article = (caps.get('articles') or {}).get(key)
        policy = caps.get('policy_id')
        source = 'Law Agent 한도 산정: ' + ' · '.join(p for p in (article, f'지구단위 정책 {policy}' if policy else None) if p)
        # 지구단위계획·공공주택 지구계획 can set their own caps; while they are not in hand the ordinance cap is not final.
        pending = [i['title'] for i in review.get('items') or [] if i.get('group') == 'district' and i.get('status') == 'needs_source']
        if pending and not policy:
            item.update({'status': 'needs_check', 'value': f'{value:g}%',
                         'basis': f"{source} — {'·'.join(pending)} 확보 전이라 이 계획이 따로 정한 상한이 있으면 그 값이 우선해요"})
        else:
            item.update({'status': 'applies', 'value': f'{value:g}%', 'basis': source})


def article_id(hang_id: str) -> str:
    """'건축법(시행령)::제6장::제86조::1' → '건축법(시행령)::제6장::제86조' (law_article reads whole articles)."""
    parts = hang_id.split('::')
    for index, part in enumerate(parts):
        if re.fullmatch(r'제\d+조(의\d+)?', part):
            return '::'.join(parts[: index + 1])
    return hang_id


def clause_route(question: str, clause: dict, assessment_date: str | None):
    """A question about one review item goes to the Law Agent at once (the user chose the provision): its ordinance
    article through `law_ordinance` (law.go.kr text), else a statute search narrowed to the item's articles."""
    from backend.app.modules.platform.routing.roles.law import SEARCH_LIMIT
    from backend.app.modules.platform.routing.rules import Route
    dated = {'assessment_date': assessment_date} if assessment_date else {}
    refs = clause.get('refs') or []
    ordinance = next((r for r in refs if r.get('kind') == 'ordinance' and r.get('article')), None)
    statutes = [r for r in refs if r.get('kind') != 'ordinance' and r.get('article') and not str(r['article']).startswith('별표')]
    reason = f"선택한 조항({clause.get('title')})을 Law Agent에 물어요"
    # The binding text first: an ordinance article (law.go.kr), else the decree's, else the act's — by its exact id.
    if ordinance:
        edition = {'edition_id': ordinance['edition_id']} if ordinance.get('edition_id') else {}
        return Route('skill', 'law', 'law_ordinance', None, {'name': ordinance['instrument'], 'article': ordinance['article'], 'limit': 3, **dated, **edition},
                     0.95, reason, decided_by='user', instruction=question)
    exact = sorted((r for r in statutes if r.get('hang_id')), key=lambda r: {'decree': 0, 'rule': 1, 'act': 2}.get(r.get('kind'), 3))
    if exact:
        full_id = article_id(exact[0]['hang_id'])
        return Route('skill', 'law', 'law_article', None, {'full_id': full_id, **dated}, 0.95, reason, decided_by='user', instruction=question)
    named = ' '.join(f"{r['instrument']} {r['article']}" for r in statutes[:3]) or clause.get('title')
    return Route('skill', 'law', 'law_search', None, {'query': f'{named} {question}'.strip(), 'limit': SEARCH_LIMIT, **dated},
                 0.95, reason, decided_by='user', instruction=question)


async def ask_law(question: str, *, pnu: str | None, assessment_date: str | None, recorder, traceparent: str | None = None,
                  role: str | None = None, agent=law_agent.ask, judge=None, situation: str = '', clause: dict | None = None) -> dict:
    """One question → one route (the Orchestrator's judgment, `routing.decide`): a Law skill called now (one
    recorded span), a goal handed off to the catalog (no agent call; the conversation offers to start it), or a
    question back to the user with the roles as choices. Every answer carries the same keys; `route.kind` says
    which part is filled and `route.decided_by` who decided (pattern · llm · rules · user)."""
    chosen = clause_route(question, clause, assessment_date) if clause else \
        await decide(question, assessment_date=assessment_date, role=role, judge=judge, situation=situation)
    base = {'question': question, 'route': chosen.to_dict(), 'agent': chosen.agent, 'tool': chosen.skill, 'trace_id': None,
            'version': None, 'answer': None, 'handoff': None,
            'clause': {'item_id': clause.get('item_id'), 'title': clause.get('title'), 'pnu': pnu, 'assessment_date': assessment_date} if clause else None}
    if chosen.kind in ('ask', 'answer'):
        # The Orchestrator speaks itself: a question back (choices in the route) or its own reply (route.instruction).
        return base
    if chosen.kind == 'goal':
        catalog = goal(chosen.goal) or {}
        return {**base, 'handoff': {'goal': chosen.goal, 'label': catalog.get('label') or chosen.goal,
                                    'owners': catalog.get('owners') or [],
                                    # Offered to start only when the door takes it AND the conversation may offer it.
                                    'available': catalog.get('available') is True and catalog.get('offer') is True}}
    tool, args = chosen.skill, chosen.args
    span = Span.start(recorder, continue_or_start(traceparent), agent=chosen.agent, conversation_id=f'editor:ask:{pnu or "-"}')
    trace = {'caller': 'editor', 'trace_id': span.context.trace_id, 'span_id': span.context.span_id, 'hop': 1, 'tool': tool}
    try:
        raw = await agent(tool, args, trace=trace)
    except Exception as exc:
        span.end('error', error_type=type(exc).__name__)
        raise
    span.end('ok')
    return {**base, 'trace_id': span.context.trace_id, 'version': raw.get('version'), 'answer': normalize(tool, raw.get('payload') or {})}
