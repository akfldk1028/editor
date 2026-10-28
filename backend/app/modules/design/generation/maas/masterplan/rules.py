"""Source-attributed numeric rules for preliminary attached parking design.

The function in this module selects only the narrow statutory snapshot its
arguments establish.  It does not decide the required parking count, the
accessible-space count, parcel-specific ordinance applicability, or permit
compliance.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from backend.app.modules.design.generation.maas.parking.layout import DEFAULT_ACCESSIBLE_LENGTH_M, DEFAULT_ACCESSIBLE_WIDTH_M, DEFAULT_AISLE_WIDTH_M, DEFAULT_STALL_LENGTH_M, DEFAULT_STALL_WIDTH_M


SCHEMA_VERSION = "arr.maas.parking_design_rules.v1"
SNAPSHOT_EFFECTIVE_FROM = date(2026, 7, 27)
SNAPSHOT_AS_OF = date(2026, 10, 28)  # re-read from 법제처 DRF (lawService target=law, 법령ID 008238) on 2026-09-17;
# 2026-10-28: law.go.kr 법령 본문(lsInfoP lsId=008238) still shows 국토교통부령 제1604호, 시행 2026-07-27 — no later edition.
OFFICIAL_URL = "https://www.law.go.kr/법령/주차장법시행규칙"

# Ramp values have no earlier numeric owner in ARR.  They are defined here and
# exposed by Lawagent; consumers must read this function rather than restating
# them in prompts or wrappers.
STRAIGHT_RAMP_ONE_LANE_MIN_WIDTH_M = 3.3
STRAIGHT_RAMP_TWO_LANE_MIN_WIDTH_M = 6.0
STRAIGHT_RAMP_MAX_SLOPE_RATIO = 0.17
RAMP_MIN_CLEAR_HEIGHT_M = 2.3
ROAD_INTERFACE_LENGTH_M = 3.0
ROAD_INTERFACE_MAX_SLOPE_RATIO = 0.085
CONVEX_TRANSITION_LENGTH_M = 1.7
CONCAVE_TRANSITION_LENGTH_M = 2.0
TRANSITION_MAX_SLOPE_RATIO = STRAIGHT_RAMP_MAX_SLOPE_RATIO / 2

# Curved ramps, entrances and stall mix - 제6조제1항 as applied to 부설주차장 by 제11조제1항·제4항.
CURVED_RAMP_ONE_LANE_MIN_WIDTH_M = 3.6          # 제6조제1항제5호다목
CURVED_RAMP_TWO_LANE_MIN_WIDTH_M = 6.5          # 제6조제1항제5호다목
CURVED_RAMP_MAX_SLOPE_RATIO = 0.14              # 제6조제1항제5호라목
CURVED_ROAD_INTERFACE_MAX_SLOPE_RATIO = 0.07    # 제6조제1항제5호바목
CURVE_MIN_INNER_RADIUS_M = 6.0                  # 제6조제1항제5호나목 (주차대수 50대 이하: 5 m)
CURVE_MIN_INNER_RADIUS_SMALL_M = 5.0
ENTRANCE_MIN_WIDTH_M = 3.5                      # 제6조제1항제4호
ENTRANCE_LARGE_FROM_SPACES = 50                 # 50대 이상: 출구·입구 분리 또는 5.5 m
ENTRANCE_LARGE_MIN_WIDTH_M = 5.5
EXPANDED_STALL_WIDTH_M = 2.6                    # 제3조제1항제2호 확장형
EXPANDED_STALL_LENGTH_M = 5.2
EXPANDED_SHARE_FROM_SPACES = 50                 # 제11조제4항 -> 제6조제1항제14호: 확장형 30 % 이상 (평행주차 제외)
EXPANDED_MIN_SHARE = 0.30
EV_MIN_SHARE = 0.05                             # 제6조제1항제14호: 환경친화적 자동차 전용구획 5 % 이상
STALL_SURFACE_MAX_GRADE_RATIO = 0.07            # 제6조제1항제13호 (평평한 장소; 7 % 이하는 인정 시)
EXIT_SIGHT_SETBACK_M = 2.0                      # 제6조제1항제2호: 출구 2 m 후퇴, 1.4 m 높이, 좌우 60도
EXIT_SIGHT_EYE_HEIGHT_M = 1.4
EXIT_SIGHT_ANGLE_DEG = 60.0
# This is deliberately outside the statutory object.  The cited provisions do
# not specify a general flat landing length at each level.
DEFAULT_LEVEL_LANDING_LENGTH_M = 6.0

_SUPPORTED = {
    "facility_type": {"attached"},
    "parking_method": {"self_parking"},
    "structure": {"underground_or_building", "underground", "building", "surface"},
    "parking_angle": {"perpendicular"},
    "ramp_shape": {"straight"},
}


def _source_snapshot(assessment: date) -> dict[str, Any]:
    return {
        "jurisdiction": "KR",
        "instrument": "주차장법 시행규칙",
        "edition_effective_from": SNAPSHOT_EFFECTIVE_FROM.isoformat(),
        "as_of": assessment.isoformat(),
        "official_url": OFFICIAL_URL,
        "provisions": [
            "제3조제1항제2호",
            "제5조제6호",
            "제6조제1항제2호ㆍ제3호ㆍ제4호ㆍ제5호ㆍ제7호ㆍ제13호ㆍ제14호",
            "제11조제1항ㆍ제4항ㆍ제5항",
            "별표 1",
        ],
    }


def _assessment_date(value: str | None) -> date:
    if value is None:
        return SNAPSHOT_AS_OF
    if not isinstance(value, str):
        raise ValueError("assessment_date must be an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("assessment_date must be an ISO date (YYYY-MM-DD)") from exc


def _base_result(*, status: str, assessment: date, applicability: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "permit_compliance_verified": False,
        "applicability": applicability,
        "source_snapshot": _source_snapshot(assessment),
        "statutory": None,
        "design_assumptions": {},
        "unresolved": [],
    }


def parking_design_rules(
    required_spaces: int,
    *,
    facility_type: str = "attached",
    parking_method: str = "self_parking",
    structure: str = "underground_or_building",
    parking_angle: str = "perpendicular",
    ramp_shape: str = "straight",
    entrance_count: int = 1,
    assessment_date: str | None = None,
) -> dict[str, Any]:
    """Return the applicable Art. 3/6/11 + Annex 1 design-rule snapshot.

    ``required_spaces`` is the proposed total installed count for structural
    applicability. The statutory minimum demand is calculated separately.
    """
    if isinstance(required_spaces, bool) or not isinstance(required_spaces, int) or required_spaces <= 0:
        raise ValueError("required_spaces must be a positive exact integer")
    if isinstance(entrance_count, bool) or not isinstance(entrance_count, int) or entrance_count <= 0:
        raise ValueError("entrance_count must be a positive exact integer")

    assessment = _assessment_date(assessment_date)
    requested = {
        "required_spaces": required_spaces,
        "facility_type": facility_type,
        "parking_method": parking_method,
        "structure": structure,
        "parking_angle": parking_angle,
        "ramp_shape": ramp_shape,
        "entrance_count": entrance_count,
    }
    unsupported_fields = [
        field for field, allowed in _SUPPORTED.items() if requested[field] not in allowed
    ]
    if unsupported_fields:
        result = _base_result(
            status="unsupported",
            assessment=assessment,
            applicability={
                "status": "unsupported",
                "requested": requested,
                "unsupported_fields": unsupported_fields,
                "supported": {key: sorted(values) for key, values in _SUPPORTED.items()},
                "reason": "No statutory selection is emitted for an unsupported parking context.",
            },
        )
        result["unresolved"] = [f"unsupported_{field}" for field in unsupported_fields]
        return result

    if assessment < SNAPSHOT_EFFECTIVE_FROM or assessment > SNAPSHOT_AS_OF:
        result = _base_result(
            status="needs_evidence",
            assessment=assessment,
            applicability={
                "status": "needs_evidence",
                "requested": requested,
                "unsupported_fields": [],
                "reason": "The requested date is outside the verified edition window.",
            },
        )
        result["unresolved"] = ["historical_edition_and_transitional_applicability"]
        return result

    from backend.app.modules.law.reference.siting_rules import catalog
    small = catalog()['small_attached_parking']
    if required_spaces <= small['max_total_spaces']:
        result = _base_result(
            status="needs_evidence",
            assessment=assessment,
            applicability={
                "status": "needs_evidence",
                "requested": requested,
                "unsupported_fields": [],
                "reason": (
                    "Article 11(5) supplies a special standard for attached self-parking "
                    "with eight or fewer total spaces; this general ramp snapshot does not "
                    "silently apply Article 6 ramp values across that exception."
                ),
            },
        )
        result["statutory"] = {
            "stalls": {
                "general": {
                    "min_width_m": DEFAULT_STALL_WIDTH_M,
                    "min_length_m": DEFAULT_STALL_LENGTH_M,
                    "source": "제3조제1항제2호",
                },
                "accessible": {
                    "min_width_m": DEFAULT_ACCESSIBLE_WIDTH_M,
                    "min_length_m": DEFAULT_ACCESSIBLE_LENGTH_M,
                    "source": "제3조제1항제2호",
                },
            },
            "aisle": {
                "parking_angle": "perpendicular",
                "min_width_m": DEFAULT_AISLE_WIDTH_M,
                "source": "제11조제5항제1호",
            },
            "ramp": {
                "status": "needs_evidence",
                "reason": "Article 11(5) replaces the paragraph (1) general structure standard for eight or fewer spaces.",
                "straight": None,
            },
        }
        result["design_assumptions"] = {
            "small_attached_ramp_preliminary_envelope": {
                "status": "design_assumption_needs_legal_applicability",
                "legal_applicability_verified": False,
                "candidate_basis": "제6조제1항제5호 general attached-parking envelope; not selected as the applicable small-parking rule",
                "straight": {
                    "one_lane_min_width_m": STRAIGHT_RAMP_ONE_LANE_MIN_WIDTH_M,
                    "two_lane_min_width_m": STRAIGHT_RAMP_TWO_LANE_MIN_WIDTH_M,
                    "max_longitudinal_slope_ratio": STRAIGHT_RAMP_MAX_SLOPE_RATIO,
                    "min_clear_height_m": RAMP_MIN_CLEAR_HEIGHT_M,
                },
                "road_interface": {
                    "length_m": ROAD_INTERFACE_LENGTH_M,
                    "max_slope_ratio": ROAD_INTERFACE_MAX_SLOPE_RATIO,
                },
                "level_landing_length_m": DEFAULT_LEVEL_LANDING_LENGTH_M,
            }
        }
        result["unresolved"] = [
            "article_11_5_small_attached_parking_special_standard",
            "accessible_space_count_requires_facility_and_local_ordinance_evidence",
            "ramp_level_landing_length_requires_project_review",
        ]
        result['statutory']['entrance'] = {'min_width_m': small['entrance_min_width_m'],
                                          'large_lot': False, 'source': small['source']}
        result['statutory']['aisle']['min_width_m'] = small['adjacent_aisle_widths_m'][parking_angle]
        result['statutory']['through_aisle'] = {'min_width_m': small['through_aisle_min_width_m'], 'source': small['source']}
        result['conditional_options'] = small
        result['applicability']['installed_spaces_range'] = {'minimum': 1, 'maximum': small['max_total_spaces']}
        if structure == 'surface':
            result['status'] = 'rules_available'
            result['applicability']['status'] = 'applicable_for_preliminary_design'
            result['applicability']['reason'] = 'Small attached surface self-parking; conditional relaxations are not applied.'
            result['statutory']['ramp'] = {'status': 'not_applicable'}
            result['design_assumptions'] = {}
            result['unresolved'] = ['accessible_space_count_requires_facility_and_local_ordinance_evidence',
                                    'conditional_parking_options_require_evidence', 'parcel_specific_ordinance_and_permit_review']
        return result

    transition_required = required_spaces >= 50
    concave_required = required_spaces >= 100
    large_lot = required_spaces >= ENTRANCE_LARGE_FROM_SPACES
    statutory = {
        "stalls": {
            "general": {
                "min_width_m": DEFAULT_STALL_WIDTH_M,
                "min_length_m": DEFAULT_STALL_LENGTH_M,
                "source": "제3조제1항제2호",
            },
            "accessible": {
                "min_width_m": DEFAULT_ACCESSIBLE_WIDTH_M,
                "min_length_m": DEFAULT_ACCESSIBLE_LENGTH_M,
                "source": "제3조제1항제2호",
            },
            "expanded": {
                "min_width_m": EXPANDED_STALL_WIDTH_M,
                "min_length_m": EXPANDED_STALL_LENGTH_M,
                "min_share": EXPANDED_MIN_SHARE if required_spaces >= EXPANDED_SHARE_FROM_SPACES else None,
                "applies_from_spaces": EXPANDED_SHARE_FROM_SPACES,
                "share_basis": "주차단위구획 총수 (평행주차형식 제외)",
                "source": "제3조제1항제2호; 제11조제4항 -> 제6조제1항제14호",
            },
            "ev": {
                "min_share": EV_MIN_SHARE if required_spaces >= EXPANDED_SHARE_FROM_SPACES else None,
                "applies_from_spaces": EXPANDED_SHARE_FROM_SPACES,
                "source": "제11조제4항 -> 제6조제1항제14호 (조례로 상향 가능)",
            },
            "surface": {
                "max_grade_ratio": STALL_SURFACE_MAX_GRADE_RATIO,
                "source": "제6조제1항제13호 및 제11조제1항",
            },
        },
        "entrance": {
            "min_width_m": ENTRANCE_LARGE_MIN_WIDTH_M if large_lot else ENTRANCE_MIN_WIDTH_M,
            "large_lot": large_lot,
            "large_lot_alternative": "separate_entry_and_exit" if large_lot else None,
            "road_choice": "둘 이상의 도로에 접하면 자동차교통에 미치는 지장이 적은 도로에 출입구",
            "road_choice_source": "제5조제6호 및 제11조제1항",
            "sight": {"setback_m": EXIT_SIGHT_SETBACK_M, "eye_height_m": EXIT_SIGHT_EYE_HEIGHT_M, "angle_deg": EXIT_SIGHT_ANGLE_DEG,
                      "source": "제6조제1항제2호 및 제11조제1항"},
            "source": "제6조제1항제4호 및 제11조제1항",
        },
        "aisle": {
            "parking_angle": "perpendicular",
            "min_width_m": DEFAULT_AISLE_WIDTH_M,
            "source": "제6조제1항제3호나목 및 제11조제1항",
        },
        "ramp": {
            "straight": {
                "one_lane_min_width_m": STRAIGHT_RAMP_ONE_LANE_MIN_WIDTH_M,
                "two_lane_min_width_m": STRAIGHT_RAMP_TWO_LANE_MIN_WIDTH_M,
                "max_longitudinal_slope_ratio": STRAIGHT_RAMP_MAX_SLOPE_RATIO,
                "source": "제6조제1항제5호다목ㆍ라목 및 제11조제1항",
            },
            "curved": {
                "one_lane_min_width_m": CURVED_RAMP_ONE_LANE_MIN_WIDTH_M,
                "two_lane_min_width_m": CURVED_RAMP_TWO_LANE_MIN_WIDTH_M,
                "max_longitudinal_slope_ratio": CURVED_RAMP_MAX_SLOPE_RATIO,
                "min_inner_radius_m": CURVE_MIN_INNER_RADIUS_M if required_spaces > 50 else CURVE_MIN_INNER_RADIUS_SMALL_M,
                "road_interface_max_slope_ratio": CURVED_ROAD_INTERFACE_MAX_SLOPE_RATIO,
                "kerb": "양쪽 벽면에서 30 cm 지점에 높이 10~15 cm 연석 (차로 너비에 포함)",
                "source": "제6조제1항제5호나목ㆍ다목ㆍ라목ㆍ바목 및 제11조제1항",
            },
            "min_clear_height_m": RAMP_MIN_CLEAR_HEIGHT_M,
            "min_clear_height_source": "제6조제1항제5호가목 및 제11조제1항",
            "parking_area_min_clear_height_m": 2.1,
            "parking_area_min_clear_height_source": "제6조제1항제7호 및 제11조제1항",
            "road_interface": {
                "applies_to": "uphill_ramp_within_3m_of_road",
                "length_m": ROAD_INTERFACE_LENGTH_M,
                "max_slope_ratio": ROAD_INTERFACE_MAX_SLOPE_RATIO,
                "source": "제6조제1항제5호바목 및 제11조제1항",
            },
            "traffic_separation": {
                "required": transition_required,
                "applies_from_spaces": 50,
                "requirement": (
                    "two_lane_width_at_least_6m_or_separate_entry_and_exit_ramps"
                    if transition_required
                    else None
                ),
                "source": "제6조제1항제5호사목1) 및 제11조제1항",
            },
            "grade_transitions": {
                "convex": {
                    "required": transition_required,
                    "length_m": CONVEX_TRANSITION_LENGTH_M if transition_required else None,
                    "max_slope_ratio": TRANSITION_MAX_SLOPE_RATIO if transition_required else None,
                    "source": "제6조제1항제5호사목 및 별표 1",
                },
                "concave": {
                    "required": concave_required,
                    "length_m": CONCAVE_TRANSITION_LENGTH_M if concave_required else None,
                    "max_slope_ratio": TRANSITION_MAX_SLOPE_RATIO if concave_required else None,
                    "source": "제6조제1항제5호사목 및 별표 1",
                },
            },
            "level_landing_length_m": None,
        },
    }
    if structure == 'surface':
        statutory['ramp'] = {'status': 'not_applicable'}
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "rules_available",
        "permit_compliance_verified": False,
        "applicability": {
            "status": "applicable_for_preliminary_design",
            "requested": requested,
            "unsupported_fields": [],
            "installed_spaces_range": {'minimum': (small['max_total_spaces'] + 1 if required_spaces < 50 else 50 if required_spaces == 50 else 51 if required_spaces < 100 else 100), 'maximum': (49 if required_spaces < 50 else 50 if required_spaces == 50 else 99 if required_spaces < 100 else None)},
            "scope": f"attached {structure} self-parking; perpendicular stalls; conditional exceptions not applied",
        },
        "source_snapshot": _source_snapshot(assessment),
        "statutory": statutory,
        "design_assumptions": {} if structure == 'surface' else {
            "ramp_level_landing": {
                "status": "design_assumption",
                "length_m": DEFAULT_LEVEL_LANDING_LENGTH_M,
                "statutory_basis": None,
                "reason": "The cited provisions do not prescribe a general level-landing length; verify vehicle geometry and authority requirements.",
            }
        },
        "unresolved": [
            "accessible_space_count_requires_facility_and_local_ordinance_evidence",
            *([] if structure == 'surface' else ["ramp_level_landing_length_requires_project_review"]),
            "vehicle_swept_path_requires_project_review",
            "parcel_specific_ordinance_and_permit_review",
        ],
    }


__all__ = ["parking_design_rules"]
