"""
Extended regulation references and provisional applicability (31 items).

Group A (5): Zone-dependent, loaded from zoning_limits_extended.json
Group B (10): Scale-dependent, fixed thresholds
Group C (16): Text-only, law article references
"""

import json
import os
from copy import deepcopy

from .legal_use import classify_building_use
from .zoning_use_evidence import evaluate_use_evidence
from .zoning_catalog import CatalogUnavailable

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _load_extended_data() -> dict:
    path = os.path.join(_DATA_DIR, "zoning_limits_extended.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if (not isinstance(data, dict) or not isinstance(data.get('zones'), dict)
                or not data['zones'] or not all(isinstance(zone, dict) for zone in data['zones'].values())
                or not isinstance(data.get('common'), dict)
                or any(not isinstance(data['common'].get(key), dict)
                       for key in ('site_road_requirement', 'split_zoning_rule'))):
            raise ValueError('Invalid extended reference')
        return data
    except (OSError, ValueError, TypeError) as exc:
        raise CatalogUnavailable('Extended regulation reference unavailable') from exc


# ──────────────────────────────────────────────────────
# Group B: Scale-dependent regulations (10)
# ──────────────────────────────────────────────────────
_SCALE_REGULATIONS = {
    "site_safety": {
        "name": "대지의 안전",
        "rule": "성토·절토 시 옹벽 설치, 배수 확보 등 대지 안전 조치 의무",
        "applies_when": "모든 건축물",
        "article": "건축법 §40",
    },
    "public_open_space": {
        "name": "공개공지",
        "rule": "일반인이 이용할 수 있는 공개 공간 확보 의무",
        "applies_when": "연면적 합계 5,000m² 이상 (문화·집회·판매·업무·숙박시설 등)",
        "article": "건축법 §43, 시행령 §27의2",
    },
    "on_site_open_space": {
        "name": "대지 안의 공지",
        "rule": "건축선 및 인접 대지경계선으로부터 건축물까지 일정 거리 이격",
        "applies_when": "용도·규모별 조례 기준 적용",
        "article": "건축법 §58, 시행령 §80의2",
    },
    "structural_safety": {
        "name": "구조안전 확인/내진설계",
        "rule": "구조안전 확인과 확인 서류 제출은 별도 요건으로 검토",
        "applies_when": "허가 대상 건축·대수선 여부, 구조·용도·규모 및 예외에 따라 확인",
        "structural_check": "제32조제1항: 법 제11조제1항에 따른 건축물의 건축·대수선 시 설계자가 구조 안전 확인",
        "document_submission": (
            "제32조제2항: 구조안전을 확인한 건축물 중 2층 이상(목구조 3층), "
            "연면적 200m² 이상(목구조 500m²; 이 면적 요건에서 창고·축사·작물재배사 제외), "
            "높이 13m·처마높이 9m·기둥 간 거리 10m 이상 등 어느 하나 해당 시 착공신고 때 제출. "
            "중요도 높은 건축물, 보존가치 있는 국가적 문화유산, 제2조제18호가·다·라목, "
            "단독주택·공동주택도 검토. 표준설계도서 예외 및 제3·4항의 특례 별도 확인"
        ),
        "missing_inputs": ["permit_scope", "construction_scope", "structural_material", "floors",
                           "total_floor_area_m2", "height_m", "eave_height_m", "column_span_m",
                           "legal_use_classification", "importance", "heritage_status",
                           "special_structure", "standard_design", "alteration_exceptions"],
        "source": {"url": "https://www.law.go.kr/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1026114885",
                   "effective_date": "2026-07-28", "verified_on": "2026-09-13"},
        "article": "건축법 §48, 시행령 §32",
    },
    "fire_resistant": {
        "name": "내화구조",
        "rule": "주요 구조부를 내화구조로 설계",
        "applies_when": "3층 이상 또는 연면적 200m² 이상 (용도별 차이)",
        "article": "건축법 §50, 시행령 §56",
    },
    "fire_compartment": {
        "name": "방화구획",
        "rule": "바닥면적 일정 규모 이상 시 방화구획 설치",
        "applies_when": "내화구조 건축물로서 연면적 기준 초과 시",
        "article": "건축법 §49, 시행령 §46",
    },
    "fire_district": {
        "name": "방화지구 건축제한",
        "rule": "방화지구 내 건축물은 내화구조, 불연재료 사용 의무",
        "applies_when": "방화지구 내 위치 시",
        "article": "건축법 §51, 시행령 §58",
    },
    "elevator": {
        "name": "승강기 설치",
        "rule": "승용 승강기 설치 의무",
        # 건축법 제64조제1항: "6층 이상으로서 연면적이 2천제곱미터 이상인 건축물" - both,
        # not either. 시행령 제89조 exempts a 6-storey building with a 직통계단 per 300m2.
        "applies_when": "6층 이상이면서 연면적 2,000m² 이상 (시행령 §89: 6층·각 층 거실 300m²마다 직통계단이면 제외)",
        "article": "건축법 §64①, 시행령 §89",
    },
    "development_permit": {
        "name": "개발행위허가",
        "rule": "건축물 건축, 토지 형질변경 등 시 허가 필요",
        "applies_when": "용도지역별 면적 기준 초과 시",
        "article": "국토계획법 §56, 시행령 §51",
    },
    "infrastructure_fee": {
        # 기반시설부담금법 was repealed in 2008; the current instrument is the
        # 기반시설설치비용 of 국토계획법 §67 (부담구역의 지정) and §68 (부과대상: 200m² 초과).
        "name": "기반시설설치비용",
        "rule": "기반시설부담구역 안에서 기반시설 설치비용을 부담",
        "applies_when": "기반시설부담구역 내, 연면적 200m²(기존 건축물 포함) 초과 건축행위",
        "article": "국토계획법 §67, §68, 시행령 §64-§70",
    },
}

# ──────────────────────────────────────────────────────
# Group C: Text-only regulations (16)
# ──────────────────────────────────────────────────────
_TEXT_REGULATIONS = {
    "fire_protection": {
        "name": "소방시설",
        "rule": "용도·규모별 소방시설 설치 의무 (소화기, 스프링클러, 자동화재탐지설비 등)",
        "article": "소방시설법 §7, §12",
    },
    "accessibility": {
        "name": "장애인 편의시설",
        "rule": "장애인등이 이용 가능한 편의시설 설치 의무 (경사로, 승강기, 점자블록 등)",
        "article": "장애인등편의법 §8, 시행령 §4",
    },
    "energy_saving": {
        "name": "에너지절약설계",
        "rule": "에너지절약계획서 제출 및 건축물 에너지효율등급 인증 (단열, 기밀, 설비효율)",
        "article": "녹색건축물법 §14, §15, 시행령 §10",
    },
    "evacuation": {
        "name": "피난시설",
        "rule": "피난계단, 특별피난계단, 비상구, 피난안전구역 설치 의무",
        "article": "건축법 §49, 시행령 §34-46",
    },
    "finishing_materials": {
        "name": "마감재료",
        "rule": "내부 마감재료의 불연·준불연·난연 등급 적용 (방화, 유독가스 방지)",
        "article": "건축법 §52, 시행령 §61",
    },
    "room_daylighting": {
        "name": "거실 채광·환기",
        "rule": "거실에 채광 및 환기를 위한 창문 면적 확보 (바닥면적의 1/10 이상 등)",
        "article": "건축법 시행령 §51, §51의2",
    },
    "sewage_treatment": {
        "name": "오수처리",
        "rule": "오수를 공공하수도로 유입시키거나 개인하수처리시설 설치",
        "article": "하수도법 §34, 하수도법 시행령",
    },
    "school_buffer_zone": {
        # 학교보건법 제6조 was deleted (2016); the zone is now the 교육환경보호구역 of
        # 교육환경 보호에 관한 법률 §8 (절대보호구역 50m / 상대보호구역 200m) and §9 (금지행위).
        "name": "교육환경보호구역",
        "rule": "절대보호구역은 기존 학교 출입문에서 직선 50m, 학교설립예정지는 경계에서 직선 50m. 상대보호구역은 학교·예정지 경계에서 직선 200m 이내 중 절대보호구역 제외. 교육감 설정·고시와 금지행위 별도 확인",
        "reference_geometry": {"existing_school_absolute": "entrance",
                               "planned_school_absolute": "boundary",
                               "absolute_distance_m": 50, "relative_origin": "boundary",
                               "relative_distance_m": 200, "relative_excludes_absolute": True},
        "missing_inputs": ["school_status", "school_entrances", "school_boundary",
                           "designated_protection_zone", "proposed_activity"],
        "source": {"url": "https://www.law.go.kr/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1029599041",
                   "effective_date": "2026-06-03", "verified_on": "2026-09-13"},
        "article": "교육환경 보호에 관한 법률 §8, §9, 시행령 §3",
    },
    "cultural_heritage_zone": {
        # 문화재보호법 became 문화유산의 보존 및 활용에 관한 법률 (2024.5.17): the 500m
        # 역사문화환경 보존지역 is §13, the permit for 현상변경 is §35.
        "name": "역사문화환경 보존지역",
        "rule": "지정문화유산 외곽 500m 이내(역사문화환경 보존지역) 건축행위는 국가유산청 사전 검토·허가",
        "article": "문화유산의 보존 및 활용에 관한 법률 §13, §35, 시행령 §14",
    },
    "military_zone": {
        "name": "군사시설 보호구역",
        "rule": "군사시설 보호구역 내 건축 시 국방부 협의 필요 (높이 제한 등)",
        "article": "군사기지법 §13, 시행령",
    },
    "use_district_restriction": {
        "name": "용도지구 건축제한",
        "rule": "경관지구·미관지구·고도지구 등 용도지구별 추가 건축제한",
        "article": "국토계획법 §76②, 시행령 §72-82",
    },
    "party_wall": {
        "name": "맞벽건축",
        "rule": "상업지역 등에서 맞벽건축 허용·의무 (건축선 일치, 방화벽 공유)",
        "article": "건축법 §59, 시행령 §81",
    },
    "cpted": {
        "name": "범죄예방 CPTED",
        "rule": "범죄예방 환경설계 기준 적용 (사각지대 제거, 조명, 감시카메라 등)",
        "article": "건축법 §53의2, 시행령 §61의3",
    },
    "combined_development": {
        "name": "결합건축",
        "rule": "2개 이상 대지(최단거리 100m 이내)를 결합하여 용적률 통합 적용 허용",
        "article": "건축법 §77의15-§77의17, 시행령 §111-§111의3",
    },
    "basement_restriction": {
        "name": "지하층 제한",
        "rule": "지하층 설치 시 방수·환기·채광·비상탈출구 기준 적용",
        "article": "건축법 §53, 시행령 §25",
    },
    "building_systems": {
        "name": "건축설비",
        "rule": "급·배수, 냉난방, 환기, 전기설비 등 건축설비 기준 적용",
        "article": "건축법 §62, 시행령 §87",
    },
}


def calculate_extended(zone_names: list[str], land_info: dict | None = None, *,
                       building_type: str = '', program_uses: list | None = None,
                       assessment_date: str | None = None) -> dict:
    """
    Return 31 references, not 31 completed compliance checks.

    Program Agent supplies intended uses/areas; LawAgent owns their legal
    classification and the evidence needed to establish permission.

    Returns dict keyed by regulation key with name/rule/article/etc per item.
    """
    result = {}
    result.update(_resolve_group_a(zone_names, land_info, building_type, program_uses, assessment_date))
    result.update(_resolve_group_b(zone_names, land_info))
    result.update(_resolve_group_c())
    for item in result.values():
        item.setdefault('evaluated', False)
        item.setdefault('status', 'needs_evidence')
        item.setdefault('result_kind', 'reference_only')
        item.setdefault('missing_inputs', ['applicable_use_scale_and_site_conditions'])
        item.setdefault('missing_evidence', ['applicable_legal_edition', 'site_applicability'])
        item['assessment_date'] = assessment_date
        if not assessment_date and 'assessment_date' not in item['missing_inputs']:
            item['missing_inputs'].append('assessment_date')
    return result


def _resolve_group_a(zone_names: list[str], land_info=None, building_type='', program_uses=None,
                     assessment_date=None) -> dict:
    """Group A: Zone-dependent (5 items). Uses strictest values for multiple zones."""
    data = _load_extended_data()
    zones_db = data["zones"]
    common = data["common"]

    # Collect zone-specific data
    zone_names = sorted(set(zone_names))
    matched = [zones_db[z] for z in zone_names if z in zones_db]

    result = {}

    requested_uses = deepcopy(program_uses) if program_uses else ([
        {'id': 'primary', 'building_type': building_type, 'floor_area_m2': None}
    ] if building_type else [])
    per_use = []
    for use in requested_uses:
        classification = classify_building_use(use.get('building_type', ''))
        missing = []
        if classification['status'] != 'classified':
            missing.append('legal_use_classification')
        if use.get('floor_area_m2') is None:
            missing.append('floor_area_m2')
        evidence = (land_info or {}).get('zoning_use_evidence')
        partial = evaluate_use_evidence(use, classification, zone_names, evidence, assessment_date)
        per_use.append({**use, **partial, 'classification': classification, 'permitted': None,
                        'status': 'needs_evidence', 'evaluated': False,
                        'missing_inputs': missing,
                        'missing_evidence': ['national_use_rule', 'municipal_ordinance',
                                             'district_plan', 'applicable_legal_edition']})
    result['building_use_restriction'] = {
        'name': '건축물 용도 제한', 'allowed_summary': '', 'prohibited_summary': '',
        'reference_table': '', 'article': '국토계획법 §76, 시행령 §71',
        'note': '지역별 요약은 참고자료이며 요청 용도의 허용 판정이 아닙니다',
        'per_zone_summaries': [
            {'zone_name': z, **deepcopy(zones_db.get(z, {}).get('building_use_restriction', {})),
             'evaluated': False, 'status': 'needs_evidence', 'result_kind': 'reference_only'}
            for z in zone_names],
        'per_use': per_use, 'permitted': None, 'status': 'needs_evidence', 'evaluated': False,
        'program_owner': 'ProgramAgent', 'legal_owner': 'LawAgent',
        'missing_inputs': ([] if requested_uses else ['building_type_or_program_uses'])
                          + ([] if zone_names else ['zone_names']),
        'missing_evidence': ['national_use_rule', 'municipal_ordinance', 'district_plan',
                             'applicable_legal_edition', 'zone_boundary_allocation'],
    }

    # 12. site_road_requirement (common, zone-independent)
    road = common.get("site_road_requirement", {})
    result["site_road_requirement"] = {
        "name": "접도의무",
        "min_frontage_m": road.get("min_frontage_m", 2),
        # 시행령 §28②: the 2,000 m² (공장 3,000 m²) size is statute; the ordinance only sets the size of 축사·작물재배사
        # and similar buildings that are exempt (`exempt_similar_buildings_below_m2`, read from the ordinance text).
        "rule": road.get("rule", ""),
        "article": road.get("article", "건축법 §44"),
    }

    # 13. site_subdivision_limit - strictest (largest min_area)
    sub_areas = [
        m.get("site_subdivision_limit", {}).get("min_area_m2")
        for m in matched if m.get("site_subdivision_limit", {}).get("min_area_m2") is not None
    ]
    sub_articles = list(dict.fromkeys(
        m.get("site_subdivision_limit", {}).get("article", "")
        for m in matched if m.get("site_subdivision_limit", {}).get("article")
    ))
    result["site_subdivision_limit"] = {
        "name": "대지 분할 제한",
        # The 시행령 §80 floor for the zone(s); 건축법 §57 makes the ordinance's figure (at or above it) the rule.
        "min_area_m2": max(sub_areas) if sub_areas else None,
        "basis": "시행령 §80 하한 — 조례가 정한 면적이 적용 기준(미확인)",
        "article": "; ".join(sub_articles) if sub_articles else "건축법 §57, 시행령 §80",
    }

    # 14. Zone summaries cannot establish article 61(2) applicability.
    result['daylighting_spacing'] = _daylighting_applicability(zone_names, per_use, land_info)

    # 15. split_zoning_rule (common)
    split = common.get("split_zoning_rule", {})
    result["split_zoning_rule"] = {
        "name": "2개 용도지역 걸침 규정",
        "rule": split.get("rule", ""),
        "article": split.get("article", "건축법 §54, 국토계획법 §84"),
    }

    return result


def _daylighting_applicability(zone_names, per_use, land_info):
    """Provisional article 61(2) scope from explicit facts, never compliance.

    The implementing decree, exceptions, geometry and local spacing remain
    evidence requirements even when the parent article's scope can be inferred.
    """
    context = (land_info or {}).get('daylighting_context') or {}
    fields = ('windows_facing_boundary', 'multiple_buildings_on_site')
    missing = []
    classifications = [u['classification'] for u in per_use]
    known_uses = bool(classifications) and all(c['status'] == 'classified' for c in classifications)
    housing = any(c.get('category') == '공동주택' for c in classifications)
    applies = None
    reason = '용도·용도지역·제61조제2항 조건 확인 필요'
    if not known_uses:
        missing.append('legal_use_classification')
    if not zone_names:
        missing.append('zone_names')
    if known_uses and not housing:
        applies, reason = False, '입력 용도 분류상 공동주택에 해당하지 않음; 분류 근거 확인 필요'
    elif known_uses and zone_names:
        exempt = {'일반상업지역', '중심상업지역'}
        if set(zone_names).issubset(exempt):
            applies, reason = False, '제61조제2항의 일반상업·중심상업지역 예외 후보; 대지와 용도 증빙 필요'
        elif set(zone_names) & exempt or any(z not in _load_extended_data()['zones'] for z in zone_names):
            missing.append('zone_boundary_allocation')
        elif any(context.get(key) is True for key in fields):
            applies, reason = True, '공동주택이며 제61조제2항의 조건 중 하나가 입력됨; 세부 기준 확인 필요'
        elif all(context.get(key) is False for key in fields):
            applies, reason = False, '입력상 제61조제2항 각 호 조건에 해당하지 않음; 배치·채광 증빙 필요'
        else:
            missing.extend(key for key in fields if type(context.get(key)) is not bool)
    return {
        'name': '채광 인동간격', 'applies': applies, 'status': 'needs_evidence',
        'evaluated': False, 'result_kind': 'provisional_applicability', 'reason': reason,
        'rule': '공동주택의 경계 방향 채광창 또는 한 대지 두 동 이상 조건 검토. 일반·중심상업지역 예외 및 시행령 세부 기준 별도 확인',
        'article': '건축법 §61②, 시행령 §86③',
        'source': {'url': 'https://law.go.kr/LSW/lsInfoP.do?chrClsCd=010202&lsId=001823&lsiSeq=273437&urlMode=lsEfInfoR&viewCls=thdCmpNewScP',
                   'effective_date': '2026-02-27', 'verified_on': '2026-09-13'},
        'missing_inputs': missing,
        'missing_evidence': ['legal_use_classification', 'site_geometry', 'applicable_legal_edition',
                             'article_86_conditions_and_exceptions', 'municipal_spacing_rule'],
    }


def _resolve_group_b(zone_names: list[str], land_info: dict | None = None) -> dict:
    """Group B: Scale-dependent (10 items). Returns threshold info."""
    data = _load_extended_data()
    zones_db = data["zones"]
    matched = [zones_db[z] for z in zone_names if z in zones_db]

    result = {}
    for key, reg in _SCALE_REGULATIONS.items():
        item = deepcopy(reg)

        # Enrich development_permit with zone-specific max_area if available
        if key == "development_permit" and matched:
            dev_areas = [
                m.get("development_permit", {}).get("max_area_m2")
                for m in matched
                if m.get("development_permit", {}).get("max_area_m2") is not None
            ]
            if dev_areas:
                item["max_area_m2"] = min(dev_areas)  # strictest = smallest

        result[key] = item

    return result


def _resolve_group_c() -> dict:
    """Group C: Text-only (16 items). Static law references."""
    return {key: deepcopy(reg) for key, reg in _TEXT_REGULATIONS.items()}
