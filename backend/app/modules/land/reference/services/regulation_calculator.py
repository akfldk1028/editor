"""
Regulation Calculator - computes all 11 building regulations from zone data.

Given zone names, resolves BCR, FAR, height limit, sunlight setback,
road diagonal, corner cutoff, building line, adjacent setback, parking,
landscaping, and building designation regulations.
When multiple zones apply, the strictest values are used.

Uses national references and dated municipal snapshots. LLM extractions remain proposals.
"""

import json
import logging
import os
import math
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime

from backend.app.modules.land.reference.services.legal_use import classify_building_use
from backend.app.modules.land.reference.services.ordinance_evidence import assessment_day, source_eligibility

from backend.app.modules.land.reference import config
from backend.app.modules.land.reference.services import zoning_mapper, overlay_resolver

logger = logging.getLogger(__name__)


def calculate_all(zone_names: list[str], land_info: dict | None = None,
                   sigungu_code: str = "", use_llm_extraction: bool | None = None,
                   zone_areas: dict[str, float] | None = None,
                   building_type: str = "", floor_area_m2: float | None = None,
                   program_uses: list[dict] | None = None, assessment_date=None) -> dict:
    """
    Compute all 11 regulations from zone names.

    Args:
        zone_names: list of zone names including overlays (e.g. ["제1종일반주거지역", "지구단위계획구역"])
        land_info: optional dict with land_area_m2, etc.
        sigungu_code: 5-digit sigungu code for ordinance override (e.g. "11680" = 강남구)
        program_uses: Optional Program Agent schedule of {id, building_type,
            floor_area_m2}; takes precedence over the single-use fields for parking.
            Areas are parking facility areas, with their statutory exclusions
            still requiring verification before a final parking requirement.
        assessment_date: ISO date or date object; defaults to the server's date.
            A cached source is checked against this date on every call.
        zone_areas: m2 of the parcel in each 용도지역, from
            land.services.zone_geometry.parcel_zone_split. Required to be
            meaningful when the parcel spans more than one zone - 국토계획법
            제84조 makes BCR/FAR a function of the split. Without it a
            multi-zone parcel returns bcr_pct/far_pct of None rather than a
            guess; the guess it used to return (the strictest zone) understated
            의정부 4115011300106840001 by a factor of 2.5, because a 4.9 m2
            sliver of 자연녹지 on a 2499.7 m2 제2종일반주거지역 parcel was read as
            if the whole parcel were green.

    Returns dict with keys matching LandAnalysisResult fields.
    """
    zones_data = [
        zd for z in zone_names
        if (zd := zoning_mapper.lookup(z)) is not None
    ]

    day = assessment_day(assessment_date)
    if not zones_data:
        result = _empty_result()
        result.update(_resolve_parking([], building_type=building_type,
                                      floor_area_m2=floor_area_m2,
                                      program_uses=program_uses, assessment_date=day))
        result.update({'assessment_date': day.isoformat(),
                       'municipal_coverage': _municipal_coverage([], sigungu_code, day),
                       'unmatched_zones': list(zone_names)})
        return result
    national_limits = _resolve_bcr_far(zones_data, zone_areas)
    coverage = _municipal_coverage(zones_data, sigungu_code, day)
    known_zones = {z['zone_name'] for z in zones_data}
    recognized_overlays = overlay_resolver.get_all_matched_zones(zone_names)
    unresolved = [z for z in zone_names if z not in known_zones and z not in recognized_overlays]
    if unresolved:
        coverage['status'] = 'needs_evidence'
        coverage['missing_evidence'].extend('unresolved_zoning:' + z for z in unresolved)

    # Apply only eligible source snapshots.
    if sigungu_code:
        zones_data = _apply_ordinance_overrides(zones_data, sigungu_code, day)

    result = {}
    result.update(_resolve_bcr_far(zones_data, zone_areas))
    snapshot_complete = coverage['caps_complete'] and not unresolved
    result['municipal_bcr_snapshot_pct'] = result['bcr_pct'] if snapshot_complete else None
    result['municipal_far_snapshot_pct'] = result['far_pct'] if snapshot_complete else None
    result['national_bcr_ceiling_pct'] = national_limits['bcr_pct']
    result['national_far_ceiling_pct'] = national_limits['far_pct']
    result['municipal_coverage'] = coverage
    result['assessment_date'] = day.isoformat()
    if coverage['status'] != 'available_snapshot':
        result['bcr_pct'] = None
        result['far_pct'] = None
    result.update(_resolve_height(zones_data))
    result.update(_resolve_sunlight(zones_data, use_llm_extraction=use_llm_extraction))
    result.update(_resolve_corner_cutoff(zones_data))
    result.update(_resolve_road_diagonal(zones_data))
    result.update(_resolve_building_line(zones_data))
    result.update(_resolve_adjacent_setback(zones_data, use_llm_extraction=use_llm_extraction))
    result.update(_resolve_parking(zones_data, common=_ordinance_common(sigungu_code, day), sigungu_code=sigungu_code,
                                   zone_names=zone_names, building_type=building_type, floor_area_m2=floor_area_m2,
                                   program_uses=program_uses, assessment_date=day))
    result.update(_resolve_landscaping(zones_data, land_info, common=_ordinance_common(sigungu_code, day)))
    result.update(_resolve_building_designation(zone_names, use_llm_extraction=use_llm_extraction))
    result["zone_category"] = zones_data[0].get("category", "")
    result["matched_zones"] = [z["zone_name"] for z in zones_data]
    result["unmatched_zones"] = [
        z for z in zone_names if z not in result["matched_zones"]
    ]

    return result


def _empty_result() -> dict:
    return {
        "bcr_pct": None, "bcr_article": "",
        "far_pct": None, "far_article": "",
        "national_bcr_ceiling_pct": None, "national_far_ceiling_pct": None,
        "municipal_bcr_snapshot_pct": None, "municipal_far_snapshot_pct": None,
        "municipal_coverage": {"status": "needs_evidence", "sources": [],
                               "missing_evidence": ["recognized_zoning_and_jurisdiction"]},
        "sunlight_status": "needs_evidence",
        "parking_status": "needs_evidence",
        "height_limit_m": None, "height_article": "",
        "sunlight_applies": False, "sunlight_rules": [], "sunlight_article": "",
        "corner_cutoff_required": False, "corner_cutoff_m": None, "corner_cutoff_article": "",
        "road_diagonal_multiplier": None, "road_diagonal_rule": "",
        "road_diagonal_article": "",
        "building_line_setback_m": None, "building_line_article": "",
        "adjacent_setback_m": None, "adjacent_setback_article": "",
        "parking_rule": "", "parking_article": "",
        "landscaping_threshold_m2": None, "landscaping_min_pct": None,
        "landscaping_article": "",
        "sunlight_source": "",
        "adjacent_setback_source": "",
        "building_designation_applies": False,
        "building_designation_setback_m": None,
        "building_designation_article": "",
        "building_designation_source": "",
        "zone_category": "",
        "matched_zones": [],
        "unmatched_zones": [],
    }


def _resolve_bcr_far(zones_data: list[dict], zone_areas: dict[str, float] | None = None) -> dict:
    """BCR/FAR per 국토계획법 제84조. One implementation, in zoning_mapper.

    This used to take the strictest limit across zones independently of
    `zoning_mapper`, so the same wrong rule existed twice and fixing either one
    alone changed nothing for callers of the other.
    """

    combined = zoning_mapper.combine_limits(zones_data, zone_areas)
    bcr = combined["bcr_limit"]
    far = combined["far_limit"]

    bcr_articles = list(dict.fromkeys(z["bcr_article"] for z in zones_data))
    far_articles = list(dict.fromkeys(z["far_article"] for z in zones_data))

    overlap = combined.get("overlap")
    if overlap:
        # The article that actually decided the number, not only the ones that
        # set each zone's own default.
        bcr_articles.append(overlap["article"])
        far_articles.append(overlap["article"])

    return {
        "bcr_pct": bcr,
        "bcr_article": "; ".join(dict.fromkeys(bcr_articles)),
        "far_pct": far,
        "far_article": "; ".join(dict.fromkeys(far_articles)),
        "zone_overlap": overlap,
    }


def _resolve_height(zones_data: list[dict]) -> dict:
    """Height limit: use strictest (lowest non-null)."""
    heights = [z["height_limit_m"] for z in zones_data if z.get("height_limit_m") is not None]
    articles = list(dict.fromkeys(z.get("height_limit_article", "") for z in zones_data if z.get("height_limit_article")))

    return {
        "height_limit_m": min(heights) if heights else None,
        "height_article": "; ".join(articles) if articles else "",
    }


def _use_llm_extraction(override: bool | None) -> bool:
    return config.LLM_EXTRACTION_ENABLED if override is None else bool(override)


def _resolve_sunlight(zones_data: list[dict], use_llm_extraction: bool | None = None) -> dict:
    """Resolve static rules and keep any unverified extraction advisory."""
    # Base: static JSON
    base = _resolve_sunlight_from_json(zones_data)
    base["sunlight_source"] = "static_json"

    # Advisory extraction only; source identity/applicability are not verified.
    if _use_llm_extraction(use_llm_extraction):
        try:
            from backend.app.modules.land.reference.services import law_enricher
            zone_names = [z["zone_name"] for z in zones_data]
            extracted = law_enricher.extract_regulation_values(zone_names, "sunlight")
            if extracted:
                base['sunlight_proposal'] = {'status': 'unverified_proposal', 'values': extracted}
        except Exception as e:
            logger.warning(f"LLM sunlight extraction failed, using JSON fallback: {e}")

    return base


def _resolve_sunlight_from_json(zones_data: list[dict]) -> dict:
    """Sunlight from static JSON (fallback)."""
    applies = any(
        z.get("sunlight_setback", {}).get("applies", False)
        for z in zones_data
    )

    if not applies:
        articles = list(dict.fromkeys(
            z.get("sunlight_setback", {}).get("article", "")
            for z in zones_data
            if z.get("sunlight_setback", {}).get("article")
        ))
        return {
            "sunlight_applies": False,
            "sunlight_rules": [],
            "sunlight_article": "; ".join(articles) if articles else "",
        }

    for z in zones_data:
        ss = z.get("sunlight_setback", {})
        if ss.get("applies"):
            return {
                "sunlight_applies": True,
                "sunlight_rules": ss.get("rules", []),
                "sunlight_article": ss.get("article", ""),
            }

    return {"sunlight_applies": False, "sunlight_rules": [], "sunlight_article": ""}


def _resolve_corner_cutoff(zones_data: list[dict]) -> dict:
    """Corner cutoff: required if ANY zone requires it. Cutoff distance from zone or ordinance."""
    required = any(
        z.get("corner_cutoff", {}).get("required", False)
        for z in zones_data
    )
    articles = list(dict.fromkeys(
        z.get("corner_cutoff", {}).get("article", "")
        for z in zones_data
        if z.get("corner_cutoff", {}).get("article")
    ))
    # Cutoff distance: ordinance/zone override or None (→ setback_geometry calculates dynamically)
    cutoff_values = [
        z.get("corner_cutoff", {}).get("default_cutoff_m")
        for z in zones_data
        if z.get("corner_cutoff", {}).get("default_cutoff_m") is not None
    ]

    return {
        "corner_cutoff_required": required,
        "corner_cutoff_m": max(cutoff_values) if cutoff_values else None,
        "corner_cutoff_article": "; ".join(articles) if articles else "",
    }


def _resolve_road_diagonal(zones_data: list[dict]) -> dict:
    """Road diagonal: use strictest (lowest multiplier)."""
    multipliers = [
        z.get("road_diagonal", {}).get("multiplier")
        for z in zones_data
        if z.get("road_diagonal", {}).get("multiplier") is not None
    ]
    notes = [
        z.get("road_diagonal", {}).get("note", "")
        for z in zones_data
        if z.get("road_diagonal", {}).get("note")
    ]
    articles = list(dict.fromkeys(
        z.get("road_diagonal", {}).get("article", "")
        for z in zones_data
        if z.get("road_diagonal", {}).get("article")
    ))

    return {
        "road_diagonal_multiplier": min(multipliers) if multipliers else None,
        "road_diagonal_rule": notes[0] if notes else "",
        "road_diagonal_article": "; ".join(articles) if articles else "",
    }


def _resolve_building_line(zones_data: list[dict]) -> dict:
    """Building line: rule text only (site-specific calculation in Phase 3+)."""
    articles = list(dict.fromkeys(
        z.get("building_line_article", "")
        for z in zones_data
        if z.get("building_line_article")
    ))

    return {
        "building_line_setback_m": None,
        "building_line_article": "; ".join(articles) if articles else "",
    }


def _resolve_adjacent_setback(zones_data: list[dict], use_llm_extraction: bool | None = None) -> dict:
    """Use the largest sourced setback; extractions never replace numeric rules."""
    # Base: static JSON
    setbacks = [
        z.get("adjacent_setback_m")
        for z in zones_data
        if z.get("adjacent_setback_m") is not None
    ]
    articles = list(dict.fromkeys(
        z.get("adjacent_setback_article", "")
        for z in zones_data
        if z.get("adjacent_setback_article")
    ))
    base = {
        "adjacent_setback_m": max(setbacks) if setbacks else None,
        "adjacent_setback_article": "; ".join(articles) if articles else "",
        "adjacent_setback_source": "static_json",
    }

    # Advisory extraction only; source identity/applicability are not verified.
    if _use_llm_extraction(use_llm_extraction):
        try:
            from backend.app.modules.land.reference.services import law_enricher
            zone_names = [z["zone_name"] for z in zones_data]
            extracted = law_enricher.extract_regulation_values(zone_names, "adjacent_setback")
            if extracted:
                base['adjacent_setback_proposal'] = {'status': 'unverified_proposal', 'values': extracted}
        except Exception as e:
            logger.warning(f"LLM adjacent_setback extraction failed: {e}")

    return base


_parking_national_cache: dict | None = None


def _parking_national() -> dict:
    global _parking_national_cache
    if _parking_national_cache is None:
        path = os.path.join(os.path.dirname(os.path.normpath(config.ORDINANCE_DIR)), "parking_national.json")
        try:
            with open(path, encoding="utf-8") as f:
                _parking_national_cache = json.load(f)
        except Exception as e:
            logger.warning(f"parking_national.json unavailable: {e}")
            _parking_national_cache = {}
    return _parking_national_cache


# 별표 1 umbrellas whose statutory carve-out is a structural cross-reference, not a
# declarable use label, so the umbrella itself can never be resolved:
#   제1종 근린생활시설[건축법 시행령 별표1 제3호 바목·사목 … 은 제외한다]
#   방송통신시설 중 방송국 (the row covers one subtype, not the umbrella)
# 의료시설/운동시설/문화 및 집회시설/공장 stay here as a deliberate conservatism:
# their carve-outs are declarable, but nothing in this pipeline needs the umbrella.
_PARKING_AMBIGUOUS_UMBRELLA = {'방송통신시설', '제1종 근린생활시설', '의료시설',
                               '운동시설', '문화 및 집회시설', '공장'}

# Uses named in a 별표 1 parenthetical carve-out. Such a use never inherits its
# category's row; it matches only a row that lists it explicitly.
#   문화 및 집회시설(관람장은 제외한다)
#   의료시설(정신병원·요양병원 및 격리병원은 제외한다)
#   운동시설(골프장·골프연습장 및 옥외수영장은 제외한다)
#   업무시설(외국공관 및 오피스텔은 제외한다)
_PARKING_CARVE_OUT = {'관람장', '정신병원', '요양병원', '격리병원',
                      '골프장', '골프연습장', '옥외수영장', '외국공관', '오피스텔'}


def _parking_row(rows: list[dict], building_type: str) -> tuple[dict | None, str | None]:
    """Resolve a use to its 별표 1 row. Returns (row, precision).

    Exact legal identity wins. A use that is not itself listed may inherit its
    statutory category's row ("category"), because 별표 1 writes those rows at
    umbrella level - but never when the use is a named carve-out of that row.
    Never broadens an excluded subtype and never falls back to 그 밖의 건축물.
    """
    classification = classify_building_use(building_type)
    canonical = classification['canonical_use']
    if canonical is None or canonical in _PARKING_AMBIGUOUS_UMBRELLA:
        return None, None
    if canonical in {'아파트', '연립주택', '다세대주택'}:
        canonical = '공동주택'
    for row in rows:
        if any(canonical == classify_building_use(use)['canonical_use']
               for use in row.get('uses', [])):
            return row, 'exact'
    category = classification['category']
    if (category is None or category == canonical or canonical in _PARKING_CARVE_OUT
            or category in _PARKING_AMBIGUOUS_UMBRELLA):
        return None, None
    for row in rows:
        if any(category == classify_building_use(use)['canonical_use']
               for use in row.get('uses', [])):
            return row, 'category'
    return None, None


def _resolve_parking(zones_data: list[dict], common: dict | None = None, sigungu_code: str = "",
                     zone_names: list[str] | None = None, building_type: str = "",
                     floor_area_m2: float | None = None, program_uses=None, assessment_date=None) -> dict:
    """부설주차장 (주차장법 §19 -> 시행령 §6 별표1 -> 지자체 조례). The ratio belongs to
    the building's use and 시설면적, never to the zone: the national table is the
    floor, the city's ordinance usually tightens it, and in Seoul's
    주차장설치제한지역 (상업·준주거 inside named districts) a second table is the cap."""
    national = _parking_national()
    ordinance = (common or {}).get("parking") if common else None
    out: dict = {
        "parking_rule": "주차장법 시행령 별표 1 및 적용 조례: 용도별 시설면적/기준면적으로 산정 후 별표 1 비고 4(복합용도 소수점 첫째자리 합산)·비고 6(0.5 이상 1대, 총 1대 미만 0대) 단수처리. 비고 1 면제 대상 여부와 주차장설치제한지역 경계는 별도 확인",
        "parking_article": "주차장법 제19조, 시행령 제6조 별표 1",
        "parking_national_rows": national.get("rows"),
        "parking_ordinance_rows": None,
        "parking_restricted": None,
        "parking_restricted_candidate": None,
        "parking_ratio_m2_per_car": None,
        "parking_required": None,
        "parking_cap": None,
        "parking_needs_review": None,
    }
    if isinstance(ordinance, dict):
        if ordinance.get("rows"):
            out["parking_ordinance_rows"] = ordinance["rows"]
            out["parking_article"] += (f"; {ordinance['ordinance']['name']} {ordinance.get('article', '')}"
                                       f" (시행 {ordinance['ordinance'].get('effective')})")
        if ordinance.get("needs_review"):
            out["parking_needs_review"] = ordinance["needs_review"]
        restricted = ordinance.get("restricted")
        if isinstance(restricted, dict):
            out["parking_restricted"] = {k: v for k, v in restricted.items() if k != "districts"}
            zones = set(zone_names or [])
            commercial = any(z.endswith("상업지역") or z == "준주거지역" for z in zones)
            for dist in restricted.get("districts", []):
                if sigungu_code and sigungu_code in dist.get("sigungu", []) and commercial:
                    out["parking_restricted_candidate"] = {
                        "district": dist["name"], "boundary": dist.get("boundary"),
                        "note": "상업·준주거 대지가 이 구역의 경계도로 안(경계도로에 접한 대지 포함)이면 별표 3 최고한도 적용. 경계 판정은 지도 확인 필요",
                    }
                    break
    day = assessment_day(assessment_date)
    try:
        national_effective = datetime.strptime(national.get('effective', ''), '%Y%m%d').date()
        national_eligible = national_effective <= day
    except (TypeError, ValueError):
        national_eligible = False
    rows = out['parking_ordinance_rows'] or (national.get('rows') if national_eligible else []) or []
    out['parking_basis'] = 'municipal_snapshot' if out['parking_ordinance_rows'] else 'national_reference'
    out['parking_source'] = {
        'national_edition_id': national.get('mst'),
        'national_effective_date': national.get('effective'),
        'national_fetched_date': national.get('fetched'),
        'national_edition_status': 'available_snapshot' if national_eligible else 'needs_evidence',
        'assessment_date': day.isoformat(),
        'municipal_ordinance': ordinance.get('ordinance') if isinstance(ordinance, dict) else None,
    }
    out['parking_status'] = 'needs_evidence'
    out['parking_calculated_intermediate'] = None
    out['parking_missing_evidence'] = []
    if not out['parking_ordinance_rows']:
        out['parking_missing_evidence'].append('applicable_municipal_ordinance')
    entries = program_uses if program_uses is not None else [
        {'id': 'single_use', 'building_type': building_type, 'floor_area_m2': floor_area_m2}]
    evaluated = []
    single_row = None
    for entry in entries:
        label = entry.get('building_type', '')
        row, precision = _parking_row(rows, label)
        if program_uses is None:
            single_row = row
        item = {'id': entry.get('id'), 'building_type': label,
                'classification': classify_building_use(label),
                'floor_area_m2': entry.get('floor_area_m2'),
                'status': 'needs_evidence', 'calculated_intermediate': None,
                'cars_first_decimal': None, 'use_precision': precision,
                'required': None, 'ratio_m2_per_car': None}
        if row:
            item['rule'] = row.get('rule')
            item['ratio_m2_per_car'] = row.get('m2_per_car')
            item['row_note'] = row.get('note')
            area = entry.get('floor_area_m2')
            ratio = row.get('m2_per_car')
            area_ok = (isinstance(area, (int, float)) and not isinstance(area, bool)
                       and math.isfinite(area) and area > 0)
            cars = None
            if area_ok and ratio:
                cars = area / ratio
            elif area_ok and any('단독주택' in use for use in row.get('uses', [])):
                cars = _parking_detached_house(float(area), row.get('tier') or {})
            if cars is not None:
                item['calculated_intermediate'] = cars
                # 별표 1 비고 4: each use's count to the first decimal place.
                item['cars_first_decimal'] = _parking_first_decimal(cars)
                item['status'] = 'calculated_intermediate'
            else:
                item['missing_evidence'] = ['facility_area_or_use_specific_manual_rule']
        else:
            item['missing_evidence'] = ['specific_legal_use_and_applicable_parking_row']
        evaluated.append(item)
    out['parking_program_uses'] = evaluated
    if evaluated and all(item['calculated_intermediate'] is not None for item in evaluated):
        out['parking_calculated_intermediate'] = sum(item['calculated_intermediate'] for item in evaluated)
    if program_uses is None and evaluated:
        item = evaluated[0]
        out['parking_ratio_m2_per_car'] = item['ratio_m2_per_car']
        if item.get('rule'):
            out['parking_ratio_rule'] = item['rule']
        if single_row:
            out['parking_ratio_uses'] = single_row.get('uses')
    if out['parking_restricted_candidate']:
        out['parking_missing_evidence'].append('restricted_district_parcel_boundary')
    # A candidate boundary and a ratio cannot establish a final legal cap.
    out['parking_cap'] = None
    _parking_finalize(out, evaluated)
    _parking_accessible(out, evaluated, ordinance if isinstance(ordinance, dict) else None)

    return out


def _parking_detached_house(area: float, tier: dict) -> float:
    """별표 1 제4호 단독주택(다가구주택 제외): 50㎡ 초과 first_max 이하 1대, 초과분은
    step㎡당 1대 (시행령 150/100; 의정부 별표 3은 134/85). 50㎡ 이하는 표에 값이 없고
    비고 4 단서가 면적을 100㎡로 나눈 대수로 정한다 (서울 별표 2 비고 4도 100㎡,
    의정부 별표 3 비고 1은 85㎡) - the divisor is read from the ordinance snapshot."""
    first_max = float(tier.get('first_max_m2', 150))
    step = float(tier.get('step_m2', 100))
    if area <= 50:
        return area / float(tier.get('under_50_divisor_m2', 100))
    if area <= first_max:
        return 1.0
    return 1 + (area - first_max) / step


def _parking_first_decimal(cars: float) -> float:
    """별표 1 비고 4's "소수점 이하 첫째자리까지의 주차대수".

    별표 1 states the precision, not how to reach it; neither the 시행령, 서울 별표 2
    비고 4 (same sentence), 의정부 별표 3 비고 1 (restates it with an 85㎡ divisor for
    단독주택 50㎡ 이하) nor 법제처 법령해석 15-0777 says 반올림 or 절사. Round-half-up
    is used, consistent with 비고 6's own treatment of 0.5, and the exact quotient
    is preserved alongside so an ordinance that decides otherwise can override.
    """
    return float(Decimal(repr(cars)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


def _parking_round_note6(subtotal: float) -> int:
    """별표 1 비고 6: 0.5 이상은 1로, 총주차대수 1대 미만은 0대. 반올림이지 올림이 아니다."""
    if subtotal < 1:
        return 0
    whole = math.floor(subtotal)
    return whole + (1 if Decimal(repr(subtotal)) - whole >= Decimal('0.5') else 0)


def _parking_finalize(out: dict, evaluated: list) -> None:
    """별표 1 비고 6 단수처리 -> the binding 부설주차장 주차대수.

    "소수점 이하의 수…가 0.5 이상인 경우에는 이를 1로 본다. 다만, 해당 시설물
    전체에 대하여 설치기준을 적용하여 산정한 총주차대수가 1대 미만인 경우에는
    주차대수를 0으로 본다." 서울 조례 별표 2 비고 6 and 별표 3 비고 7 repeat this
    verbatim; 의정부 별표 3 carries no rounding note of its own, so the 시행령 sentence
    governs there too. An ordinance may tighten the ratio (비고 11) without changing
    this step. 법제처 법령해석 15-0777 (2015-12-31): the 단서's "해당 시설물 전체" is
    the whole mixed-use building, so the 1대 미만 test runs on the summed total.

    The number is emitted only when it binds: an ordinance snapshot is present
    (시행령 별표 1 is the national floor, the ordinance is what binds the parcel),
    every declared use resolved, and no unresolved 주차장설치제한지역 candidate -
    there the 별표 3 cap is lower than the requirement, so an uncapped number
    would overstate parking.
    """
    distinct = {(item.get('classification') or {}).get('canonical_use') for item in evaluated}
    # 별표 1 비고 4 governs "용도가 다른 시설물이 복합된 시설물" only. A single use -
    # or several entries of the same use - is summed at full precision, so a
    # 0.95-car facility stays below 비고 6's 1대 threshold instead of being lifted
    # to 1.0 by a rounding step the statute does not apply to it.
    mixed_use = len(distinct - {None}) > 1
    calculation = {
        'notes_applied': (['별표1 비고4'] if mixed_use else []) + ['별표1 비고6'],
        'mixed_use': mixed_use,
        'rounding_policy': 'first_decimal_round_half_up' if mixed_use else 'exact_quotient',
        'final_rule': '소수점 이하 0.5 이상은 1로 본다; 총주차대수 1대 미만은 0대',
        'basis': out.get('parking_basis'),
        'subtotal_first_decimal': None,
        'uses': [{k: item.get(k) for k in
                  ('id', 'building_type', 'ratio_m2_per_car', 'rule', 'use_precision',
                   'calculated_intermediate', 'cars_first_decimal', 'status')}
                 for item in evaluated],
        # 비고 1 lists uses that need no 부설주차장 (변전소·수도원·동물 및 식물 관련
        # 시설·송수신 중계시설·도시철도 역사·전통한옥 등). None of them is a
        # declarable label in legal_use, so no exemption is evaluated here.
        'note1_exemptions_evaluated': False,
    }
    out['parking_calculation'] = calculation
    if not evaluated or any(item['cars_first_decimal'] is None for item in evaluated):
        for item in evaluated:
            for reason in item.get('missing_evidence', []):
                if reason not in out['parking_missing_evidence']:
                    out['parking_missing_evidence'].append(reason)
        return
    key = 'cars_first_decimal' if mixed_use else 'calculated_intermediate'
    subtotal = float(sum(Decimal(repr(item[key])) for item in evaluated))
    calculation['subtotal'] = subtotal
    calculation['subtotal_first_decimal'] = subtotal if mixed_use else None
    if out['parking_basis'] != 'municipal_snapshot':
        # The national table is a floor; the ordinance is the binding number.
        calculation['national_floor_cars'] = _parking_round_note6(subtotal)
        return
    if out['parking_restricted_candidate']:
        return
    out['parking_required'] = _parking_round_note6(subtotal)
    out['parking_status'] = 'calculated'


_accessible_applicability_cache: dict | None = None


def _accessible_applicability() -> dict:
    """장애인등편의법 시행령 별표 1 (대상시설) + 별표 2 제2호(2)(가) (count rule), one data file."""
    global _accessible_applicability_cache
    if _accessible_applicability_cache is None:
        path = os.path.join(os.path.dirname(os.path.normpath(config.ORDINANCE_DIR)),
                            'accessible_parking_applicability.json')
        try:
            with open(path, encoding='utf-8') as f:
                _accessible_applicability_cache = json.load(f)
        except Exception as e:
            logger.warning(f'accessible_parking_applicability.json unavailable: {e}')
            _accessible_applicability_cache = {}
    return _accessible_applicability_cache


def _accessible_row(rows: list[dict], classification: dict) -> dict | None:
    canonical = classification.get('canonical_use')
    if canonical is None:
        return None
    for row in rows:
        if canonical in row.get('uses', []):
            return row
    category = classification.get('category')
    for row in rows:
        if category in row.get('uses', []):
            return row
    return None


def _accessible_use_status(row: dict | None, area) -> tuple[str, str]:
    """One use against 별표 1: applies / not_applicable / needs_evidence, with its clause."""
    if row is None:
        return 'needs_evidence', 'accessibility_act_applicability_unknown_use'
    if row.get('status'):
        return row['status'], row.get('reason') or row.get('clause', '')
    condition = row.get('applies_when') or {}
    if condition.get('always'):
        return 'applies', row.get('clause', '')
    minimum = condition.get('min_floor_area_m2')
    if minimum is not None:
        if not (isinstance(area, (int, float)) and not isinstance(area, bool) and math.isfinite(area)):
            return 'needs_evidence', 'floor_area_for_accessibility_threshold'
        if area >= minimum:
            return 'applies', row.get('clause', '')
        return row.get('below', 'needs_evidence'), f"{row.get('clause', '')} 문턱 {minimum}㎡ 미달"
    return 'needs_evidence', row.get('clause', '')


def _parking_accessible(out: dict, evaluated: list, ordinance: dict | None) -> None:
    """장애인전용 주차구획 count, emitted next to the binding 부설주차장 count.

    Chain: 주차장법 시행령 별표 1 비고 10 (2~4 % 범위에서 조례로 정하는 비율 이상, 10대 미만
    제외) -> the city's ratio (서울 조례 제25조제1항 3 %, 의정부 별표 3 비고 2 3 %) ->
    장애인등편의법 시행령 별표 2 제2호(2)(가): 10대 미만 제외, "산정된 장애인전용주차구역의
    주차대수 중 소수점이하의 끝수는 이를 1대로 본다" (올림 - a different quantity from the
    반올림 of the 부설주차장 total). Whether the facility must provide any at all is 별표 1 of
    that decree (대상시설, by use and 바닥면적 합계); the ratio applies to the whole
    부설주차장 of the facility once any of its uses is a 대상시설 (서울 조례 제25조제1항).
    """
    table = _accessible_applicability()
    count_rule = table.get('count_rule') or {}
    acc = (ordinance or {}).get('accessible') if ordinance else None
    block = {
        'required_accessible_cars': None,
        'status': 'needs_evidence',
        'article': '주차장법 시행령 별표 1 비고 10; 장애인등편의법 제17조, 시행령 제4조 별표 2 제2호(2)(가); 대상시설은 같은 시행령 별표 1',
        'ratio_pct': acc.get('ratio_pct') if acc else None,
        'ratio_article': (f"{ordinance['ordinance']['name']} {acc.get('article', '')}".strip()
                          if acc and ordinance.get('ordinance') else None),
        'ratio_basis': 'municipal_snapshot' if acc else None,
        'national_band_pct': count_rule.get('national_band_pct'),
        'min_cars': count_rule.get('min_cars', 10),
        'rounding': 'ceil - 장애인등편의법 시행령 별표 2: 산정된 주차대수의 소수점 이하 끝수는 1대',
        'applicability': {'status': None, 'source': table.get('source'), 'uses': []},
        'missing_evidence': [],
    }
    out['parking_accessible'] = block
    out['parking_required_accessible'] = None
    statuses = []
    for item in evaluated:
        row = _accessible_row(table.get('rows') or [], item.get('classification') or {})
        status, basis = _accessible_use_status(row, item.get('floor_area_m2'))
        block['applicability']['uses'].append({'id': item.get('id'), 'building_type': item.get('building_type'),
                                               'status': status, 'basis': basis})
        statuses.append(status)
    if 'applies' in statuses:
        applicability = 'applies'
    elif 'needs_evidence' in statuses or not statuses:
        applicability = 'needs_evidence'
    else:
        applicability = 'not_applicable'
    block['applicability']['status'] = applicability
    required = out.get('parking_required')
    if required is None:
        block['missing_evidence'].append('binding_parking_count')
        return
    if required < block['min_cars']:
        block.update(status='not_required', required_accessible_cars=0,
                     reason=f"부설주차장 주차대수 {required}대 < {block['min_cars']}대 (별표 2 제2호(2)(가) 단서)")
        out['parking_required_accessible'] = 0
        return
    if applicability == 'not_applicable':
        block.update(status='not_applicable', required_accessible_cars=0)
        out['parking_required_accessible'] = 0
        return
    if applicability != 'applies':
        block['missing_evidence'].append('accessibility_act_target_facility')
        return
    if not acc or acc.get('ratio_pct') is None:
        block['missing_evidence'].append('municipal_accessible_parking_ratio')
        return
    exact = Decimal(required) * Decimal(str(acc['ratio_pct'])) / Decimal(100)
    cars = math.ceil(exact)
    block.update(status='calculated', required_accessible_cars=cars, exact=float(exact))
    out['parking_required_accessible'] = cars


def _ordinance_common(sigungu_code: str, assessment_date=None) -> dict:
    """City-wide rules that are not per zone (조경 tiers …), 시도 then 시군구 file."""
    common: dict = {}
    if not sigungu_code:
        return common
    for code in dict.fromkeys([sigungu_code[:2], sigungu_code]):
        doc = _load_ordinance(code, assessment_date)
        if doc and isinstance(doc.get("common"), dict):
            for name, rule in doc['common'].items():
                if not isinstance(rule, dict):
                    continue
                rule_doc = {**doc, 'ordinance': rule.get('ordinance')}
                if source_eligibility(rule_doc, code, assessment_date)[0]:
                    common[name] = rule
    return common


def _resolve_landscaping(zones_data: list[dict], land_info: dict | None = None,
                         common: dict | None = None) -> dict:
    """Landscaping (건축법 §42 -> 건축조례). Every 건축 조례 seen so far tiers the
    minimum by the building's 연면적 (2,000 m2+ 15 %, 1,000-2,000 10 %, under
    1,000 5 %), not by zone, so when the city's ordinance is on file the tiers are
    returned and min_pct is left to the caller who knows the floor area. The
    zone-keyed static value is only the fallback for cities without a file."""
    ls_common = (common or {}).get("landscaping") if common else None
    if isinstance(ls_common, dict) and ls_common.get("tiers"):
        return {
            "landscaping_threshold_m2": ls_common.get("threshold_m2", 200),
            "landscaping_min_pct": None,
            "landscaping_tiers": ls_common["tiers"],
            "landscaping_article": ls_common.get("article", ""),
        }
    thresholds = []
    pcts = []
    articles_set = set()

    for z in zones_data:
        ls = z.get("landscaping", {})
        if ls.get("threshold_m2") is not None:
            thresholds.append(ls["threshold_m2"])
        if ls.get("min_pct") is not None:
            pcts.append(ls["min_pct"])
        if ls.get("article"):
            articles_set.add(ls["article"])

    return {
        "landscaping_threshold_m2": min(thresholds) if thresholds else None,
        "landscaping_min_pct": max(pcts) if pcts else None,
        "landscaping_article": "; ".join(articles_set) if articles_set else "",
    }


# ──────────────────────────────────────────────────────
# Ordinance Override (지자체 조례)
# ──────────────────────────────────────────────────────

_ordinance_cache: dict[str, dict | None] = {}


def _load_ordinance(sigungu_code: str, assessment_date=None) -> dict | None:
    """Load ordinance override JSON for a sigungu. Cached."""
    if sigungu_code in _ordinance_cache:
        cached = _ordinance_cache[sigungu_code]
        return cached if source_eligibility(cached, sigungu_code, assessment_date)[0] else None

    path = os.path.join(config.ORDINANCE_DIR, f"{sigungu_code}.json")
    if not os.path.exists(path):
        _ordinance_cache[sigungu_code] = None
        return None

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        _ordinance_cache[sigungu_code] = data
        logger.info(f"Loaded ordinance override: {sigungu_code} ({data.get('sigungu_name', '')})")
        eligible, reason = source_eligibility(data, sigungu_code, assessment_date)
        if not eligible:
            logger.warning('Ordinance %s excluded: %s', sigungu_code, reason)
        return data if eligible else None
    except Exception as e:
        logger.warning(f"Failed to load ordinance {sigungu_code}: {e}")
        _ordinance_cache[sigungu_code] = None
        return None


def _apply_ordinance_overrides(zones_data: list[dict], sigungu_code: str, assessment_date=None) -> list[dict]:
    """Merge ordinance overrides into zones_data, 시도 file first (a 특별시/광역시
    도시계획 조례 binds every 구, e.g. 11.json for Seoul), then the 5-digit 시군구
    file. 1-level merge; returns a new list (no mutation)."""
    layers = []
    for code in dict.fromkeys([sigungu_code[:2], sigungu_code]):
        ordinance = _load_ordinance(code, assessment_date)
        if ordinance and ordinance.get("overrides"):
            layers.append(ordinance["overrides"])
    if not layers:
        return zones_data

    overrides: dict[str, dict] = {}
    for layer in layers:
        for zone_name, row in layer.items():
            overrides[zone_name] = {**overrides.get(zone_name, {}), **row}

    result = []
    for z in zones_data:
        zone_name = z.get("zone_name", "")
        if zone_name in overrides:
            merged = {**z}
            for key, val in overrides[zone_name].items():
                if isinstance(val, dict) and isinstance(merged.get(key), dict):
                    merged[key] = {**merged[key], **val}
                else:
                    merged[key] = val
            result.append(merged)
        else:
            result.append(z)
    return result


def _resolve_building_designation(
    all_zone_names: list[str], use_llm_extraction: bool | None = None,
) -> dict:
    """A district-plan designation requires the parcel's actual plan evidence."""
    is_district_plan = any("지구단위계획" in z for z in all_zone_names)

    base = {
        "building_designation_applies": is_district_plan,
        "building_designation_setback_m": None,
        "building_designation_article": (
            "국토계획법 §49-52, 건축법 §46-47" if is_district_plan else ""
        ),
        "building_designation_source": "needs_district_plan_evidence" if is_district_plan else "",
    }

    if not is_district_plan:
        return base

    # Advisory extraction only; source identity/applicability are not verified.
    if _use_llm_extraction(use_llm_extraction):
        try:
            from backend.app.modules.land.reference.services import law_enricher
            standard_zones = [
                z for z in all_zone_names
                if zoning_mapper.lookup(z) is not None
            ]
            if standard_zones:
                extracted = law_enricher.extract_regulation_values(
                    standard_zones, "building_designation",
                )
                if extracted:
                    base['building_designation_proposal'] = {'status': 'unverified_proposal', 'values': extracted}
        except Exception as e:
            logger.warning(f"LLM building_designation extraction failed: {e}")

    return base


def _municipal_coverage(zones_data, sigungu_code, assessment_date=None):
    sources = []
    covered = {}
    rejected = []
    edition_missing = []
    for code in dict.fromkeys([sigungu_code[:2], sigungu_code]):
        if not code:
            continue
        doc = _load_ordinance(code, assessment_date)
        if doc:
            source = doc['ordinance']
            edition_id = source.get('mst') or source.get('ordinSeq') or source.get('edition_id')
            if not edition_id:
                edition_missing.append('ordinance_edition_identity:' + code)
            sources.append({'jurisdiction_code': code, 'name': source['name'],
                            'ordinance_id': source['id'], 'edition_id': edition_id,
                            'effective_date': source['effective'],
                            'fetched_at': doc['fetched_at'],
                            'url': source.get('url') or doc.get('source_url'),
                            'source_request': {'provider': 'law.go.kr DRF', 'target': 'ordin', 'ID': source['id']}})
            for name, row in doc.get('overrides', {}).items():
                covered[name] = {**covered.get(name, {}), **row}
        else:
            rejected.append({'code': code, 'reason': source_eligibility(
                _ordinance_cache.get(code), code, assessment_date)[1]})
    missing = [z['zone_name'] for z in zones_data
               if not all(covered.get(z['zone_name'], {}).get(key) is not None
                          for key in ('bcr_default', 'far_default'))]
    if not zones_data:
        missing.append('recognized_zoning')
    return {'status': 'needs_evidence' if missing or edition_missing else 'available_snapshot',
            'caps_complete': not missing,
            'assessment_date': assessment_day(assessment_date).isoformat(),
            'sources': sources, 'excluded_sources': rejected,
            'missing_evidence': ['applicable_municipal_caps:' + name for name in missing] + edition_missing,
            'limitations': ['snapshot_does_not_certify_amendment_completeness',
                           'parcel_plan_conditions_and_transitional_rules_require_review']}
