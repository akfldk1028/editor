"""The review list for one lot: which provisions apply, why, and what is still missing — the Law Agent's answer.

The Law Agent's `law_land_analyze` returns this module's output inside `/land/analyze` (`analysis.review`); the
editor shows it and never re-judges. Every item is built from what the regulation calculators and the overlay
table already state about the lot (their rule, condition, status and article string); this module only sorts
them into the six groups people review by, says in a line why the lot meets the provision, and keeps the
calculators' own status as one of four:

  applies      적용 확인 — the lot meets the provision's trigger (a 용도지역 rule, a designation the lot is in)
  conditional  조건부 적용 — applies once the design (use, size, height, road corner) meets its stated condition
  needs_check  적용 여부 확인 필요 — the trigger cannot be decided from what is known (gazette, school position…)
  needs_source 자료 확보 필요 — the governing document itself is not in hand (지구단위계획, 공공주택 지구계획…)

Contract (`review`): {assessment_date, groups: [{id, label}], items: [{id, group, title, refs[], reason, status,
basis, value}], gaps: [{item, what}], search: {connected, errors[]}}; each ref
{instrument, kind, article, clause, text, text_status, hang_ids, url?, edition_id?, effective_date?}.
"""
from __future__ import annotations

from backend.app.modules.land.review.refs import parse
from backend.app.modules.land.review.texts import attach_texts
from backend.app.modules.regulations import zoning_limits

GROUPS = (
    {'id': 'use', 'label': '용도 제한'},
    {'id': 'bcr_far', 'label': '건폐율·용적률'},
    {'id': 'height_sunlight', 'label': '높이·일조'},
    {'id': 'road_setback', 'label': '도로·이격'},
    {'id': 'parking_landscape', 'label': '주차·조경'},
    {'id': 'district', 'label': '지역·지구·지구단위계획'},
)

# Overlay table categories → what reviewing it means for this lot.
_OVERLAY = {
    'planning': ('needs_source', '지구단위계획 결정도서·시행지침(용도·높이·건축선·배치 기준)을 확보해야 조항별로 판단할 수 있어요'),
    'housing_district': ('needs_source', '공공주택지구 지구계획(토지이용·건축 기준)을 확보해야 해요 — 지구단위계획과 함께 상위 기준이 될 수 있어요'),
    'education': ('needs_check', '학교·학교설립예정지와의 거리(절대 50m·상대 200m)와 계획 용도가 금지행위에 해당하는지 확인해야 해요'),
    'capital_region': ('conditional', '대규모 건축물·공장 신증설 같은 규모 기준에 걸릴 때만 제한돼요'),
    'livestock': ('conditional', '축사 등 가축 사육 시설을 둘 때만 해당돼요'),
    'military': ('needs_check', '보호구역 종류와 협의 대상 여부를 관할 부대·고시로 확인해야 해요'),
    'heritage': ('needs_check', '국가유산 외곽 거리와 허용기준을 고시로 확인해야 해요'),
    'landscape': ('conditional', '경관 기준(형태·색채·높이)이 설계에 적용돼요'),
}


def _item(id_, group, title, article, reason, status, basis, value=None, source=None):
    refs = parse(article)
    if source:
        for ref in refs:
            if ref['kind'] == 'ordinance' and _same_ordinance(ref['instrument'], source.get('name')):
                ref.update({key: source.get(key) for key in ('url', 'edition_id', 'effective_date') if source.get(key)})
    return {'id': id_, 'group': group, 'title': title, 'refs': refs, 'reason': reason, 'status': status,
            'basis': basis, 'value': value}


def _same_ordinance(a: str | None, b: str | None) -> bool:
    return bool(a and b) and a.replace(' ', '') == b.replace(' ', '')


def _ext_status(entry: dict) -> str:
    if entry.get('applies') is True:
        return 'applies'
    if entry.get('applies') is None and entry.get('result_kind') == 'provisional_applicability':
        return 'needs_check'
    return 'conditional'


def build(analysis: dict, *, assessment_date: str | None = None) -> dict:
    """The review items of one analysis (pure; texts are attached by `attach_texts`)."""
    reg = analysis.get('regulations') or {}
    ext = reg.get('extended') or {}
    zone_info = analysis.get('zone_info') or {}
    land = analysis.get('land_info') or {}
    area = next((land.get(key) for key in ('land_area_m2', 'area_m2', 'area') if isinstance(land.get(key), (int, float))), None)
    zones = [z for z in zone_info.get('zones') or [] if zoning_limits.lookup(z) is not None]
    zone_text = ' · '.join(zones) or '용도지역 미확인'
    coverage = (analysis.get('assessment') or {}).get('municipal_coverage') or {}
    source = (coverage.get('sources') or [None])[0]
    # The lot's own ordinance as the calculators named it; never a city written here.
    jurisdiction = (source or {}).get('name') or '관할 지방자치단체 조례'
    items: list[dict] = []

    use = (analysis.get('assessment') or {}).get('use_permission') or ext.get('building_use_restriction') or {}
    items.append(_item('use-zone', 'use', '용도지역 안에서의 건축 제한', (use.get('article') or '국토계획법 §76, 시행령 §71') + ', 시행령 별표',
        f'대지가 {zone_text}이라 지을 수 있는 건축물·없는 건축물이 시행령 별표로 정해져 있어요', 'conditional',
        use.get('note') or '계획 용도가 정해지면 별표의 허용·불허·조례 위임 여부로 판정해요'))

    for key, title, national_article in (('bcr', '건폐율', '국토계획법 §77, 시행령 §84'), ('far', '용적률', '국토계획법 §78, 시행령 §85')):
        entry = reg.get(key) or {}
        ceiling = entry.get('national_ceiling_pct')
        limit = entry.get('limit_pct')
        items.append(_item(f'{key}-cap', 'bcr_far', f'{title} 상한', f"{national_article}, {entry.get('article') or ''}",
            f"{zone_text}의 {title} 상한은 법이 정한 범위({ceiling:g}% 이내)에서 {jurisdiction}로 정해요" if isinstance(ceiling, (int, float)) else f'{zone_text}의 {title} 상한은 {jurisdiction}로 정해요',
            'applies' if isinstance(limit, (int, float)) else 'needs_check',
            f'조례 상한 {limit:g}%' if isinstance(limit, (int, float)) else '조례 수치는 Law Agent 한도 산정(law_parcel_limits)으로 확정해요',
            value=f'{limit:g}%' if isinstance(limit, (int, float)) else None, source=source))
    if len(zones) > 1:
        split = ext.get('split_zoning_rule') or {}
        items.append(_item('split-zoning', 'bcr_far', '둘 이상 용도지역에 걸친 대지', split.get('article') or '건축법 §54, 국토계획법 §84',
            f'대지가 {len(zones)}개 용도지역({zone_text})에 걸쳐 있어요', 'applies', split.get('rule') or ''))

    height = reg.get('height') or {}
    if height:
        items.append(_item('height', 'height_sunlight', '건축물의 높이 제한', height.get('article'),
            '가로구역별 최고높이가 지정·고시됐는지에 따라 높이 상한이 정해져요', 'needs_check',
            height.get('rule') or '가로구역 높이 지정 고시 확인 필요', value=f"{height['limit_m']} m" if height.get('limit_m') else None))
    sun = reg.get('sunlight_setback') or {}
    if sun:
        items.append(_item('sunlight', 'height_sunlight', '일조 등의 확보를 위한 높이 제한', sun.get('article'),
            f"{zone_text}(전용·일반주거지역)이라 정북방향 인접대지 경계에서 높이별로 띄워야 해요" if sun.get('applies') else '해당 용도지역이면 정북방향 이격이 적용돼요',
            'applies' if sun.get('applies') else 'needs_check',
            '; '.join(f"{r.get('condition')}: {r.get('setback_m', r.get('formula'))}" for r in sun.get('rules') or [])))
    day = ext.get('daylighting_spacing') or {}
    if day:
        items.append(_item('daylighting', 'height_sunlight', day.get('name') or '채광 인동간격', day.get('article') or '건축법 §61②',
            '공동주택을 짓거나 한 대지에 두 동 이상이면 채광 방향 이격이 생겨요', _ext_status(day), day.get('reason') or day.get('rule') or ''))

    road = ext.get('site_road_requirement') or {}
    if road:
        items.append(_item('road-frontage', 'road_setback', road.get('name') or '대지와 도로의 관계', road.get('article'),
            '모든 건축물의 대지는 정해진 폭 이상 도로에 접해야 해요', 'applies', road.get('rule') or ''))
    corner = reg.get('corner_cutoff') or {}
    if corner:
        items.append(_item('corner', 'road_setback', '도로 모퉁이의 건축선(가각전제)', corner.get('article'),
            '대지가 너비 8m 미만 도로의 모퉁이에 있으면 교차각에 따라 건축선이 물러나요', 'conditional', corner.get('rule') or ''))
    line = reg.get('building_line') or {}
    if line:
        items.append(_item('building-line', 'road_setback', '건축선', line.get('article'),
            '도로 너비가 4m 미만이거나 지정 건축선이 있으면 도로경계선에서 물러난 선이 건축선이 돼요', 'conditional', line.get('rule') or ''))
    adjacent = reg.get('adjacent_setback') or {}
    if adjacent:
        items.append(_item('adjacent', 'road_setback', '대지 안의 공지·인접대지 이격', adjacent.get('article'),
            '인접대지 경계에서 띄우는 거리가 민법과 조례(용도·규모별)로 정해져요', 'applies',
            f"최소 {adjacent.get('min_m')} m (조례 별표로 상향 가능)" if adjacent.get('min_m') else ''))

    parking = reg.get('parking') or {}
    if parking:
        items.append(_item('parking', 'parking_landscape', '부설주차장 설치기준', parking.get('article'),
            '용도별 시설면적에 따라 필요한 주차 대수가 조례 별표로 정해져요', 'conditional', parking.get('rule') or ''))
    landscape = reg.get('landscaping') or {}
    if landscape:
        threshold = landscape.get('threshold_m2')
        over = isinstance(area, (int, float)) and isinstance(threshold, (int, float)) and area >= threshold
        tiers = ' / '.join(f"연면적 {t.get('min_floor_area_m2', 0):g}㎡ 이상 {t.get('min_pct')}%" for t in landscape.get('tiers') or [])
        items.append(_item('landscaping', 'parking_landscape', '대지의 조경', landscape.get('article'),
            f'대지면적 {area:g}㎡가 조경 의무 기준 {threshold:g}㎡ 이상이라 연면적에 따라 조경 면적을 둬야 해요' if over
            else f'대지면적이 {threshold}㎡ 이상이면 조경 의무가 생겨요', 'applies' if over else 'needs_check', tiers, source=source))

    gaps: list[dict] = []
    for overlay in analysis.get('overlay_regulations') or []:
        status, basis = _OVERLAY.get(overlay.get('category'), ('needs_check', overlay.get('description') or ''))
        item = _item(f"district-{overlay.get('raw_zone') or overlay.get('name')}", 'district', overlay.get('name') or overlay.get('raw_zone'),
            overlay.get('article'), f"대지가 {overlay.get('name')}에 들어 있어요 — {overlay.get('description') or ''}".rstrip(' —'), status, basis)
        items.append(item)
        if status == 'needs_source':
            gaps.append({'item': item['id'], 'what': basis})
    known = {overlay.get('raw_zone') for overlay in analysis.get('overlay_regulations') or []}
    for name in zone_info.get('unmatched') or []:
        if name in known:
            continue
        item = _item(f'district-{name}', 'district', name, None, f'대지가 {name}에 들어 있어요',
            'needs_source', 'Law Agent의 규제표에 없는 지정이에요 — 근거 법령과 고시를 확보해야 해요')
        items.append(item)
        gaps.append({'item': item['id'], 'what': item['basis']})
    for code in coverage.get('missing_evidence') or []:
        kind, _, value = code.partition(':')
        if kind == 'unresolved_zoning' and value in known:
            continue  # the designation has its own item above
        gaps.append({'item': None, 'what': f'조례 상한표에 없는 지정: {value}' if kind == 'unresolved_zoning' else f'조례 근거 미확보: {code}'})
    return {'assessment_date': assessment_date or coverage.get('assessment_date'), 'groups': list(GROUPS), 'items': items,
            'gaps': gaps, 'search': {'connected': None, 'errors': []}}


async def build_review(analysis: dict, law_client, *, assessment_date: str | None = None) -> dict:
    """`build` plus the article texts; an article the search does not hold becomes a gap, not an absence."""
    review = build(analysis, assessment_date=assessment_date)
    errors = await attach_texts(review['items'], law_client)
    review['search'] = {'connected': not errors, 'errors': errors}
    for item in review['items']:
        missing = [ref for ref in item['refs'] if ref.get('text_status') == 'needs_source' and ref['kind'] != 'ordinance']
        for ref in missing:
            review['gaps'].append({'item': item['id'], 'what': f"조문 원문 미확보: {ref['instrument']} {ref.get('article') or ''} — {ref.get('text_gap')}".strip()})
    return review
