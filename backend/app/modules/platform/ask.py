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
        | {kind: 'site', query, pnu, address, coordinates: {x, y} | null, error}   (a typed address: the parcel it names)
  legal_evidence: {assessment_date, currency_status, coverage_status, reason} | null
"""
import asyncio
import json
import re

from backend.app.adapters import law_agent
from backend.app.core.tracing import Span, continue_or_start
from backend.app.modules.platform.goals import goal
from backend.app.modules.platform.routing import cards, decide
from backend.app.modules.platform.run_results import law_from_response

EXCERPT = 400
LAW_GO_KR = 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq='
PNU = re.compile(r'^\d{19}$')
_land = None


def _str(value):
    return value if isinstance(value, str) and value else None


def _addresses():
    """The editor's own address door (Vworld geocoding, the one the map's search box uses), built once."""
    global _land
    if _land is None:
        from backend.app.modules.land.services import LandServices
        _land = LandServices.from_environment()
    return _land.addresses


async def locate_site(query: str, *, addresses=None) -> dict:
    """`site_locate`: the parcel a typed address or PNU names — identity and point only; the map draws and selects
    it. `error` says why nothing was found (the conversation then asks the user to pick on the map)."""
    query = query.strip()
    body = {'kind': 'site', 'query': query, 'pnu': None, 'address': None, 'coordinates': None, 'error': None}
    if PNU.match(query):
        return {**body, 'pnu': query}
    found = await (addresses or _addresses()).resolve_address(query)
    if not isinstance(found, dict) or found.get('success') is not True:
        # Several parcels fit (or only a substitute does): the map's search lists them for the user to choose.
        ambiguous = {'ambiguous': True} if isinstance(found, dict) and found.get('status') == 'ambiguous' else {}
        return {**body, **ambiguous, 'error': _str((found or {}).get('error') if isinstance(found, dict) else None) or '주소에 해당하는 필지를 찾지 못했어요'}
    point = found.get('coordinates') if isinstance(found.get('coordinates'), dict) else None
    return {**body, 'pnu': _str(found.get('pnu')), 'address': _str(found.get('geocoded_address')) or query,
            'coordinates': {'x': point['x'], 'y': point['y']} if point and isinstance(point.get('x'), (int, float)) and isinstance(point.get('y'), (int, float)) else None}


def _legal_evidence(value):
    if not isinstance(value, dict):
        return None
    return {key: _str(value.get(key)) for key in ('assessment_date', 'currency_status', 'coverage_status', 'reason')}


def _iso(value):
    value = _str(value) or ''
    return f'{value[:4]}-{value[4:6]}-{value[6:]}' if re.fullmatch(r'\d{8}', value) else (value or None)


def normalize(tool: str, payload: dict, *, full_text: bool = False) -> dict:
    text_limit = None if full_text else EXCERPT
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
            'matches': [{'article': _str(m.get('article')), 'title': _str(m.get('title')), 'text': (_str(m.get('content')) or '')[:text_limit] or None}
                        for m in payload.get('matches') or [] if isinstance(m, dict)],
            'legal_evidence': _legal_evidence(payload.get('legal_evidence')),
        }
    stats = payload.get('stats') if isinstance(payload.get('stats'), dict) else {}
    items = []
    for row in payload.get('results') or []:
        if not isinstance(row, dict):
            continue
        items.append({'id': _str(row.get('hang_id')), 'law': _str(row.get('law_name')), 'kind': _str(row.get('law_type')),
                      'article': _str(row.get('article')), 'text': (_str(row.get('content')) or '')[:text_limit] or None})
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
            'zone_split': zone.get('zone_split') if isinstance(zone.get('zone_split'), dict) else None,
            'restrictions': [r for r in analysis.get('restrictions') or [] if isinstance(r, str)],
            'assessment_status': _str(assessment.get('status')),
            'permit_compliance_verified': assessment.get('permit_compliance_verified') is True,
            'missing_evidence': list(dict.fromkeys(missing))}


async def analyze_land(pnu: str, *, building_type: str | None, floor_area_m2: float | None, assessment_date: str | None, recorder,
                       traceparent: str | None = None, agent=law_agent.ask, site=None, ledger=None, conversation_id: str | None = None) -> dict:
    """The law artifact's analysis, from the Law Agent: `law_land_analyze` (the 42 regulations, lines, articles —
    the whole answer) and `law_parcel_limits` (the parcel's caps: district policy / ordinance, area-weighted),
    asked together; each hop is one span. `limits` is null when that call failed (the analysis still answers).

    With `site` (the Site Context Agent's A2A door), the review's road item is also settled from facts: Site's
    도시·군계획시설 polygons touching the parcel (`site_planned_facilities`) go to the Law Agent's `law_judge` with the
    item's own articles, and the item carries both — the facts and the judgement — as `evidence`. Without `site`
    (tests, a network without Site) the item stays as `law_land_analyze` wrote it."""
    parent = continue_or_start(traceparent)
    dated = {'assessment_date': assessment_date} if assessment_date else {}
    land_args = {'input': pnu, 'input_type': 'pnu', 'full': True, 'include_law': True, 'building_type': building_type or '',
                 'floor_area_m2': floor_area_m2, **dated}
    limits_args = {'pnu': pnu, **({'building_type': building_type} if building_type else {}), **dated}

    async def hop(tool, args, *, to='law', ask=agent):
        span = Span.start(recorder, parent, agent=to, conversation_id=f'editor:law-analysis:{pnu}')
        trace = {'caller': 'editor', 'trace_id': span.context.trace_id, 'span_id': span.context.span_id, 'hop': 1, 'tool': tool}
        hop = ledger.begin(from_agent='orchestrator', to_agent=to, tool=tool, conversation_id=conversation_id, input_text=json.dumps(args, ensure_ascii=False),
                           trace=span.context) if ledger else None
        try:
            raw = await ask(tool, args, trace=trace)
        except Exception as exc:
            span.end('error', error_type=type(exc).__name__)
            if hop is not None:
                ledger.finish(hop, status='ERROR', error_type=type(exc).__name__)
            raise
        span.end('ok')
        if hop is not None:
            ledger.finish(hop, output_text=json.dumps(raw.get('payload') or {}, ensure_ascii=False), status='OK', task_id=raw.get('task_id'))
        return raw

    calls = [hop('law_land_analyze', land_args), hop('law_parcel_limits', limits_args)]
    if site is not None:
        # Two Site facts: the planned facility polygons touching the outline, and the outline's own road frontage
        # (cadastral 도로 lots along each edge with the width across them, NGII centrelines) from `site_zoning`.
        calls += [hop('site_planned_facilities', {'pnu': pnu}, to='site_context', ask=site),
                  hop('site_zoning', {'pnu': pnu}, to='site_context', ask=site)]
    land, limits, *rest = await asyncio.gather(*calls, return_exceptions=True)
    if isinstance(land, BaseException):
        raise land
    payload = land.get('payload') or {}
    analysis = payload.get('raw') if isinstance(payload.get('raw'), dict) else payload
    limits_error = None
    if isinstance(limits, BaseException):
        limits_error = f'{type(limits).__name__}: {limits}'
        limits = None
    caps = law_from_response(limits['payload']) if limits else None
    from backend.app.modules.platform.law_sources import bind_ordinance_sources
    bind_ordinance_sources(analysis.get('review'), caps)
    settle_caps(analysis.get('review'), caps)
    if site is not None:
        facts = road_facts(rest[0], rest[1])
        judgement = None
        if facts['status'] == 'ok':
            try:
                # The judge reads the road item's own article and the definition article the question names
                # (건축법 제2조제1항제11호 — which article that is, Law's search says; no article path is written here).
                found = await hop('law_search', {'query': ROAD_DEFINITION_QUERY, 'limit': 5, **dated})
                judgement = (await hop('law_judge', road_question(facts, analysis.get('review'), assessment_date, found_ids(found)))).get('payload') or {}
            except Exception as exc:
                judgement = {'verdict': 'undecided', 'status': 'unavailable', 'reason': f'Law Agent 판단 실패: {type(exc).__name__}: {exc}'}
        settle_road(analysis.get('review'), facts, judgement)
    return {'pnu': pnu, 'agent': 'law', 'trace_id': parent.trace_id, 'version': land.get('version'),
            'analysis': analysis, 'findings': [f for f in payload.get('findings') or [] if isinstance(f, dict)],
            'limits': caps, 'limits_error': limits_error,
            'summary': _summary(analysis)}


ROAD_ITEM = 'road-frontage'
ROAD_FACT_KEYS = ('name', 'kind', 'ucode', 'decision', 'shared_edge_m', 'overlap_m2', 'width_m_rule', 'centrelines', 'jurisdiction')
ROAD_QUESTION = ('이 대지는 건축법 제44조(대지와 도로의 관계)에 따라 도로에 접하는가? 대지 경계에 닿는 도시·군계획시설 도로(국토의 계획 및 '
                 '이용에 관한 법률에 따른 결정)가 건축법 제2조제1항제11호의 도로에 해당하는지, 접한 길이와 결정 폭 범위가 제44조의 요건을 '
                 '채우는지 판단하라. 폭 범위는 도시·군계획시설의 결정·구조 및 설치기준에 관한 규칙 제9조의 등급별 범위이지 실측 폭이 아니다. '
                 'centrelines는 그 결정 도형 안을 지나는 NGII 도로중심선의 폭 속성(실측)이다. 답(reason·open_conditions)은 한국어로 쓴다.')


LOT_FACT_KEYS = ('bearing_deg', 'frontage_m', 'road_width_m', 'road_width_min_m', 'road_width_max_m', 'beyond_land_category', 'samples')


def road_facts(raw, zoning=None) -> dict:
    """Site's answers as the facts the judge reads: from `site_planned_facilities` each touching polygon's name, class,
    decision, shared edge, width band and centrelines — never its full property dump; from `site_zoning` the outline's
    road frontage (cadastral 도로 lots along each edge with the width across them, NGII centrelines nearby)."""
    if isinstance(raw, BaseException):
        return {'status': 'unavailable', 'reason': f'{type(raw).__name__}: {raw}'}
    payload = raw.get('payload') or {}
    if payload.get('status') != 'ok':
        return {'status': 'unavailable', 'reason': str(payload.get('reason') or payload.get('status') or 'no answer')}
    facts = {'status': 'ok', 'source': payload.get('source'), 'rule': payload.get('rule'), 'note': payload.get('note'),
             'touch_tolerance_m': payload.get('touch_tolerance_m'), 'centrelines_status': payload.get('centrelines_status'),
             'centrelines_source': payload.get('centrelines_source'),
             'planned_facilities_touching_parcel': [{key: item.get(key) for key in ROAD_FACT_KEYS} for item in payload.get('items') or [] if isinstance(item, dict)]}
    frontage = ((zoning.get('payload') or {}).get('road_frontage') if isinstance(zoning, dict) else None) or {}
    if isinstance(zoning, BaseException):
        facts['cadastre_status'] = f'unavailable: {type(zoning).__name__}: {zoning}'
    elif frontage:
        ngii = frontage.get('ngii_roads') or {}
        facts.update({'cadastre_status': frontage.get('cadastre_status'), 'cadastre_basis': frontage.get('basis'),
                      'cadastral_road_lots': [{key: lot.get(key) for key in LOT_FACT_KEYS} for lot in frontage.get('items') or [] if isinstance(lot, dict)],
                      'ngii_roads': {'status': ngii.get('status'), 'source': ngii.get('source'),
                                     'roads': [{key: road.get(key) for key in ('id', 'width_m', 'distance_to_parcel_m')} for road in (ngii.get('roads') or [])[:8] if isinstance(road, dict)]}})
    return facts


ROAD_DEFINITION_QUERY = '건축법 제2조 제1항 제11호 도로의 정의 고시된 도로 자동차만의 통행'


def found_ids(search) -> list[str]:
    """Whole-article ids from a `law_search` answer, in order, once each (the search names the unit; the judge reads the article)."""
    payload = (search or {}).get('payload') or {}
    rows = payload.get('results') if isinstance(payload.get('results'), list) else payload.get('items') if isinstance(payload.get('items'), list) else []
    return list(dict.fromkeys(article_id(row['hang_id']) for row in rows if isinstance(row, dict) and isinstance(row.get('hang_id'), str)))


def road_question(facts: dict, review, assessment_date: str | None, more_ids: list[str] | None = None) -> dict:
    """`law_judge` args: the question, Site's facts, and the articles to read — the road item's own (제44조) first, then
    the ones the search found for the definition the question names."""
    ids = []
    for item in (review or {}).get('items') or [] if isinstance(review, dict) else []:
        if item.get('id') == ROAD_ITEM:
            ids = list(dict.fromkeys(article_id(h) for ref in item.get('refs') or [] for h in ref.get('hang_ids') or []))
    ids = list(dict.fromkeys(ids + list(more_ids or [])))
    return {'question': ROAD_QUESTION, 'facts': facts, **({'article_ids': ids} if ids else {}),
            **({'assessment_date': assessment_date} if assessment_date else {})}


def settle_road(review, facts: dict, judgement: dict | None) -> None:
    """The road item meets the facts: what touches the parcel (Site) and what that means (Law). Status is the judge's
    verdict transcribed, never the editor's reading; both answers stay on the item as `evidence`."""
    if not isinstance(review, dict):
        return
    item = next((i for i in review.get('items') or [] if i.get('id') == ROAD_ITEM), None)
    if item is None:
        return
    item['evidence'] = {'site': facts, 'law': judgement}
    if facts['status'] != 'ok':
        item['basis'] = f"{item.get('basis') or ''} — Site 접도 사실을 받지 못했어요({facts['reason']}); 도시계획시설 도로 접촉은 확인하지 못함".strip(' —')
        return
    roads = facts['planned_facilities_touching_parcel']
    lots = facts.get('cadastral_road_lots') or []
    parts = [_road_line(r) for r in roads] or ['대지 경계에 닿는 도시·군계획시설 결정 도형 없음']
    if lots:
        parts.append(_lots_line(lots))
    elif facts.get('cadastre_status') == 'ok':
        parts.append('지목 도로 필지가 닿는 변 없음')
    nearest = next((r for r in (facts.get('ngii_roads') or {}).get('roads') or [] if isinstance(r.get('width_m'), (int, float))), None)
    if nearest:
        parts.append(f"NGII 중심선 폭 {nearest['width_m']:g} m(대지에서 {nearest.get('distance_to_parcel_m')} m)")
    said = ' · '.join(parts)
    verdict = (judgement or {}).get('verdict')
    status = {'applies': 'applies', 'conditional': 'conditional'}.get(verdict, 'needs_check')
    reason = (judgement or {}).get('reason') or ''
    conditions = (judgement or {}).get('open_conditions') or []
    law_said = ' · '.join(p for p in (reason, ('확인할 것: ' + '; '.join(map(str, conditions))) if conditions else '') if p)
    item.update({'status': status if (roads or lots) else 'needs_check', 'basis': f"Site: {said}" + (f" — Law: {law_said}" if law_said else '')})


def _lots_line(lots: list[dict]) -> str:
    """The cadastral 도로 lots along the outline: how many edges, the frontage they add up to, the width across them."""
    length = sum(float(l['frontage_m']) for l in lots if isinstance(l.get('frontage_m'), (int, float)))
    widths = [float(l[k]) for l in lots for k in ('road_width_min_m', 'road_width_max_m') if isinstance(l.get(k), (int, float))]
    span = f"지적 폭 {min(widths):g}~{max(widths):g} m" if widths and min(widths) != max(widths) else f"지적 폭 {widths[0]:g} m" if widths else '지적 폭 미측정'
    return f"지목 도로 필지 {len(lots)}변(접한 길이 합 {length:.1f} m, {span}; 설계·법정 폭 아님)"


def _road_line(road: dict) -> str:
    band = road.get('width_m_rule') or {}
    low, high = band.get('min_m'), band.get('max_m')
    width = f"결정 폭 {low:g}~{high:g} m" if isinstance(low, (int, float)) and isinstance(high, (int, float)) else (
        f"결정 폭 {high:g} m 미만" if isinstance(high, (int, float)) else f"결정 폭 {low:g} m 이상" if isinstance(low, (int, float)) else '폭 등급 없음')
    decision = road.get('decision') or {}
    # Vworld writes 2000-0000 where no decision record is kept: that is "none", not a decision.
    recorded = decision.get('year') and decision.get('no') and set(str(decision['no'])) != {'0'}
    when = f", 결정 {decision.get('year')}-{decision.get('no')}" if recorded else ''
    # The centrelines inside the polygon carry the measured widths (NGII): the only width where the class is missing.
    measured = ((road.get('centrelines') or {}).get('widths_m')) or []
    lines = f", 중심선 폭 {'·'.join(f'{w:g}' for w in measured)} m(NGII)" if measured else ''
    return f"{road.get('name') or '이름 없음'}({road.get('kind') or '등급 없음'}, {width}{lines}, 공유 변 {road.get('shared_edge_m')} m{when})"


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
        if caps.get('district_plan_review_needed') is True:
            # Law says so itself: the parcel is inside a 지구단위계획구역 and no lot rule was applied to these caps.
            item.update({'status': 'needs_check', 'value': f'{value:g}%',
                         'basis': f'{source} — 지구단위계획구역 안이라 이 값은 조례 상한이고, 획지 값은 지구단위 검토에서 정해져요'})
        elif pending and not policy:
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
    ordinance = next((r for r in refs if r.get('kind') == 'ordinance' and r.get('instrument')), None)
    statutes = [r for r in refs if r.get('kind') != 'ordinance' and r.get('article') and not str(r['article']).startswith('별표')]
    reason = f"선택한 조항({clause.get('title')})을 Law Agent에 물어요"
    # The binding text first: an ordinance article (law.go.kr), else the decree's, else the act's — by its exact id.
    if ordinance:
        return Route('skill', 'law', 'law_ordinance', None, {'name': ordinance['instrument'], 'article': ordinance.get('article') or '', 'limit': 3, **dated},
                     0.95, reason, decided_by='user', instruction=question)
    exact = sorted((r for r in statutes if r.get('hang_id')), key=lambda r: {'decree': 0, 'rule': 1, 'act': 2}.get(r.get('kind'), 3))
    if exact:
        full_id = article_id(exact[0]['hang_id'])
        return Route('skill', 'law', 'law_article', None, {'full_id': full_id, **dated}, 0.95, reason, decided_by='user', instruction=question)
    named = ' '.join(f"{r['instrument']} {r['article']}" for r in statutes[:3]) or clause.get('title')
    return Route('skill', 'law', 'law_search', None, {'query': f'{named} {question}'.strip(), 'limit': SEARCH_LIMIT, **dated},
                 0.95, reason, decided_by='user', instruction=question)


async def ask_law(question: str, *, pnu: str | None, assessment_date: str | None, recorder, traceparent: str | None = None,
                  role: str | None = None, agent=law_agent.ask, judge=None, situation: str = '', clause: dict | None = None,
                  addresses=None, roster=cards.roster, extras=None, ledger=None, conversation_id: str | None = None) -> dict:
    """One question → one route (the Orchestrator's judgment, `routing.decide`): a Law skill called now (one
    recorded span), a goal handed off to the catalog (no agent call; the conversation offers to start it), or a
    question back to the user with the roles as choices. A message that is an address goes to `locate_site`
    (the editor's own geocoder, no agent, no span). Every answer carries the same keys; `route.kind` says
    which part is filled and `route.decided_by` who decided (pattern · llm · rules · user)."""
    chosen = clause_route(question, clause, assessment_date) if clause else \
        await decide(question, assessment_date=assessment_date, role=role, judge=judge, situation=situation, extras=extras)
    # The 협업 장부: the person's question to the Orchestrator is one call; the skill it routes to is a second, under it.
    turn = ledger.begin(from_agent='user', to_agent='orchestrator', tool='ask', conversation_id=conversation_id, input_text=question) if ledger else None

    def done(result: dict, summary: str | None, status: str = 'OK', error_type: str | None = None) -> dict:
        if turn is not None:
            ledger.finish(turn, output_text=summary, status=status, error_type=error_type)
        return result
    base = {'question': question, 'route': chosen.to_dict(), 'agent': chosen.agent, 'tool': chosen.skill, 'trace_id': None,
            'version': None, 'answer': None, 'handoff': None, 'delegate': None,
            'clause': {'item_id': clause.get('item_id'), 'title': clause.get('title'), 'pnu': pnu, 'assessment_date': assessment_date} if clause else None}
    if chosen.kind in ('ask', 'answer'):
        # The Orchestrator speaks itself: a question back (choices in the route) or its own reply (route.instruction).
        return done(base, chosen.instruction or chosen.reason)
    if chosen.kind == 'agent':
        # A registered agent without a role module: hand the question to it in its own words (its A2A card) —
        # the skill call itself is the Orchestrator conversation's job, so no agent is called here.
        try:
            card = (await roster([chosen.agent])).get(chosen.agent)
        except Exception:
            card = None
        return done({**base, 'delegate': {'agent': chosen.agent, 'label': cards.display_name(chosen.agent, card),
                                     'description': (card or {}).get('description'), 'instruction': chosen.instruction,
                                     'skills': [{'id': s['id'], 'name': s.get('name') or s['id']} for s in (card or {}).get('skills') or []][:12],
                                     'available': card is not None}}, f'{cards.display_name(chosen.agent, card)}의 일로 넘김')
    if chosen.skill == 'site_locate':
        located = await locate_site(chosen.args['query'], addresses=addresses)
        return done({**base, 'answer': located}, located.get('address') or located.get('pnu') or '위치를 찾지 못함')
    if chosen.kind == 'goal':
        catalog = goal(chosen.goal) or {}
        return done({**base, 'handoff': {'goal': chosen.goal, 'label': catalog.get('label') or chosen.goal,
                                    'owners': catalog.get('owners') or [],
                                    # Offered to start only when the door takes it AND the conversation may offer it.
                                    'available': catalog.get('available') is True and catalog.get('offer') is True}}, f"{catalog.get('label') or chosen.goal} 목표로 넘김")
    tool, args = chosen.skill, chosen.args
    span = Span.start(recorder, continue_or_start(traceparent), agent=chosen.agent, conversation_id=f'editor:ask:{pnu or "-"}')
    trace = {'caller': 'editor', 'trace_id': span.context.trace_id, 'span_id': span.context.span_id, 'hop': 1, 'tool': tool}
    hop = ledger.begin(from_agent='orchestrator', to_agent=chosen.agent, tool=tool, conversation_id=conversation_id, input_text=json.dumps(args, ensure_ascii=False),
                       trace=span.context, parent_span_id=turn.span_id if turn else None) if ledger else None
    try:
        raw = await agent(tool, args, trace=trace)
    except Exception as exc:
        span.end('error', error_type=type(exc).__name__)
        if hop is not None:
            ledger.finish(hop, status='ERROR', error_type=type(exc).__name__)
        done(base, None, status='ERROR', error_type=type(exc).__name__)
        raise
    span.end('ok')
    if hop is not None:
        ledger.finish(hop, output_text=json.dumps(raw.get('payload') or {}, ensure_ascii=False), status='OK', task_id=raw.get('task_id'))
    return done({**base, 'trace_id': span.context.trace_id, 'version': raw.get('version'), 'answer': normalize(tool, raw.get('payload') or {}, full_text=bool(clause))},
                None)  # the skill's answer is on the hop; a tool name is not a reply to the person
