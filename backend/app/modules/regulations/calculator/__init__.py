"""
Regulation Calculator - computes all 11 building regulations from zone data.

Given zone names, resolves BCR, FAR, height limit, sunlight setback,
road diagonal, corner cutoff, building line, adjacent setback, parking,
landscaping, and building designation regulations.
Multi-zone BCR/FAR uses the preserved area-allocation calculation.

Uses national references and dated municipal snapshots. LLM extractions remain proposals.
"""

import json
import logging
import os
import math
from copy import deepcopy
from pathlib import Path
from decimal import Decimal
from datetime import datetime

from ..legal_use import classify_building_use
from ..ordinance_evidence import assessment_day, source_eligibility

from .. import zoning_limits, overlays
from ..zoning_catalog import CatalogUnavailable
from .rules import (
    Extractor,
    _empty_result,
    _resolve_bcr_far,
    _resolve_height,
    _use_llm_extraction,
    _resolve_sunlight,
    _resolve_sunlight_from_json,
    _resolve_corner_cutoff,
    _resolve_road_diagonal,
    _resolve_building_line,
    _resolve_adjacent_setback,
    _resolve_landscaping,
    _resolve_building_designation,
)
from .parking import (
    _PARKING_AMBIGUOUS_UMBRELLA,
    _PARKING_CARVE_OUT,
    _parking_row,
    _parking_detached_house,
    _parking_first_decimal,
    _parking_round_note6,
    _parking_finalize,
    _accessible_row,
    _accessible_use_status,
)

ORDINANCE_DIR = Path(__file__).parent.with_name("data") / "ordinance_overrides"

logger = logging.getLogger(__name__)


def calculate_all(zone_names: list[str], land_info: dict | None = None,
                   sigungu_code: str = "", use_llm_extraction: bool | None = None,
                   zone_areas: dict[str, float] | None = None,
                   building_type: str = "", floor_area_m2: float | None = None,
                   program_uses: list[dict] | None = None, assessment_date=None,
                   *, extractor: Extractor | None = None) -> dict:
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
    if use_llm_extraction and extractor is None:
        raise ValueError("Advisory extraction requires an explicit extractor")
    zones_data = [
        zd for z in zone_names
        if (zd := zoning_limits.lookup(z)) is not None
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
    recognized_overlays = overlays.get_all_matched_zones(zone_names)
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
    result.update(_resolve_sunlight(zones_data, use_llm_extraction=use_llm_extraction, extractor=extractor))
    result.update(_resolve_corner_cutoff(zones_data))
    result.update(_resolve_road_diagonal(zones_data))
    result.update(_resolve_building_line(zones_data))
    result.update(_resolve_adjacent_setback(zones_data, use_llm_extraction=use_llm_extraction, extractor=extractor))
    result.update(_resolve_parking(zones_data, common=_ordinance_common(sigungu_code, day), sigungu_code=sigungu_code,
                                   zone_names=zone_names, building_type=building_type, floor_area_m2=floor_area_m2,
                                   program_uses=program_uses, assessment_date=day))
    result.update(_resolve_landscaping(zones_data, land_info, common=_ordinance_common(sigungu_code, day)))
    result.update(_resolve_building_designation(zone_names, use_llm_extraction=use_llm_extraction, extractor=extractor))
    result["zone_category"] = zones_data[0].get("category", "")
    result["matched_zones"] = [z["zone_name"] for z in zones_data]
    result["unmatched_zones"] = [
        z for z in zone_names if z not in result["matched_zones"]
    ]

    return result


_parking_national_cache: dict | None = None


def _parking_national() -> dict:
    global _parking_national_cache
    if _parking_national_cache is None:
        path = os.path.join(os.path.dirname(os.path.normpath(ORDINANCE_DIR)), "parking_national.json")
        try:
            with open(path, encoding="utf-8") as f:
                _parking_national_cache = json.load(f)
            if (not isinstance(_parking_national_cache, dict)
                    or not isinstance(_parking_national_cache.get('rows'), list)
                    or not _parking_national_cache['rows']
                    or not all(isinstance(row, dict) for row in _parking_national_cache['rows'])):
                raise ValueError('Invalid parking reference')
        except (OSError, ValueError, TypeError) as exc:
            _parking_national_cache = None
            raise CatalogUnavailable('Parking reference unavailable') from exc
    return deepcopy(_parking_national_cache)


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


_accessible_applicability_cache: dict | None = None


def _accessible_applicability() -> dict:
    """장애인등편의법 시행령 별표 1 (대상시설) + 별표 2 제2호(2)(가) (count rule), one data file."""
    global _accessible_applicability_cache
    if _accessible_applicability_cache is None:
        path = os.path.join(os.path.dirname(os.path.normpath(ORDINANCE_DIR)),
                            'accessible_parking_applicability.json')
        try:
            with open(path, encoding='utf-8') as f:
                _accessible_applicability_cache = json.load(f)
            if (not isinstance(_accessible_applicability_cache, dict)
                    or not isinstance(_accessible_applicability_cache.get('rows'), list)
                    or not _accessible_applicability_cache['rows']
                    or not all(isinstance(row, dict) for row in _accessible_applicability_cache['rows'])
                    or not isinstance(_accessible_applicability_cache.get('count_rule'), dict)):
                raise ValueError('Invalid accessible parking reference')
        except (OSError, ValueError, TypeError) as exc:
            _accessible_applicability_cache = None
            raise CatalogUnavailable('Accessible parking reference unavailable') from exc
    return deepcopy(_accessible_applicability_cache)


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
    for code in dict.fromkeys(ordinance_codes(sigungu_code)):
        doc = _load_ordinance(code, assessment_date)
        if doc and isinstance(doc.get("common"), dict):
            for name, rule in doc['common'].items():
                if not isinstance(rule, dict):
                    continue
                rule_doc = {**doc, 'ordinance': rule.get('ordinance')}
                if source_eligibility(rule_doc, code, assessment_date)[0]:
                    common[name] = rule
    return common


# ──────────────────────────────────────────────────────
# Ordinance Override (지자체 조례)
# ──────────────────────────────────────────────────────

_ordinance_cache: dict[str, dict | None] = {}



def ordinance_codes(sigungu_code: str) -> list[str]:
    """Jurisdictions whose 도시계획 조례 may bind, outermost first: 시도, then the 시 of an
    일반구 (수원시 권선구 41113 -> 수원시 41110), then the 시군구 itself."""
    code = sigungu_code or ""
    return [c for c in (code[:2], code[:4] + "0" if len(code) == 5 else "", code) if c]


def _load_ordinance(sigungu_code: str, assessment_date=None) -> dict | None:
    """Load ordinance override JSON for a sigungu. Cached."""
    if sigungu_code in _ordinance_cache:
        cached = _ordinance_cache[sigungu_code]
        return deepcopy(cached) if source_eligibility(cached, sigungu_code, assessment_date)[0] else None

    path = os.path.join(ORDINANCE_DIR, f"{sigungu_code}.json")
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
        return deepcopy(data) if eligible else None
    except Exception as e:
        logger.warning(f"Failed to load ordinance {sigungu_code}: {e}")
        _ordinance_cache[sigungu_code] = None
        return None


def _apply_ordinance_overrides(zones_data: list[dict], sigungu_code: str, assessment_date=None) -> list[dict]:
    """Merge ordinance overrides into zones_data, 시도 file first (a 특별시/광역시
    도시계획 조례 binds every 구, e.g. 11.json for Seoul), then the 5-digit 시군구
    file. 1-level merge; returns a new list (no mutation)."""
    layers = []
    for code in dict.fromkeys(ordinance_codes(sigungu_code)):
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


def _municipal_coverage(zones_data, sigungu_code, assessment_date=None):
    sources = []
    covered = {}
    rejected = []
    edition_missing = []
    for code in dict.fromkeys(ordinance_codes(sigungu_code)):
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
