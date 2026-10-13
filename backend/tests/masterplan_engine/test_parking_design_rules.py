"""Behavioral contract for source-attributed parking design rules."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest




def rules(required_spaces: int, **context: object) -> dict:
    from backend.app.modules.design.generation.maas.masterplan.rules import parking_design_rules

    return parking_design_rules(required_spaces, **context)


def test_supported_attached_basement_returns_planner_dimensions_with_official_provenance():
    result = rules(24, assessment_date="2026-09-13")

    assert result["status"] == "rules_available"
    assert result["permit_compliance_verified"] is False
    assert result["applicability"]["status"] == "applicable_for_preliminary_design"
    assert result["source_snapshot"] == {
        "jurisdiction": "KR",
        "instrument": "주차장법 시행규칙",
        "edition_effective_from": "2026-07-27",
        "as_of": "2026-09-13",
        "official_url": "https://www.law.go.kr/법령/주차장법시행규칙",
        "provisions": ["제3조제1항제2호", "제5조제6호", "제6조제1항제2호ㆍ제3호ㆍ제4호ㆍ제5호ㆍ제7호ㆍ제13호ㆍ제14호", "제11조제1항ㆍ제4항ㆍ제5항", "별표 1"],
    }
    assert result["statutory"]["stalls"]["general"] == {
        "min_width_m": 2.5,
        "min_length_m": 5.0,
        "source": "제3조제1항제2호",
    }
    assert result["statutory"]["stalls"]["accessible"] == {
        "min_width_m": 3.3,
        "min_length_m": 5.0,
        "source": "제3조제1항제2호",
    }
    assert result["statutory"]["aisle"] == {
        "parking_angle": "perpendicular",
        "min_width_m": 6.0,
        "source": "제6조제1항제3호나목 및 제11조제1항",
    }
    ramp = result["statutory"]["ramp"]
    assert ramp["straight"] == {
        "one_lane_min_width_m": 3.3,
        "two_lane_min_width_m": 6.0,
        "max_longitudinal_slope_ratio": 0.17,
        "source": "제6조제1항제5호다목ㆍ라목 및 제11조제1항",
    }
    assert ramp["min_clear_height_m"] == 2.3
    assert ramp["road_interface"] == {
        "applies_to": "uphill_ramp_within_3m_of_road",
        "length_m": 3.0,
        "max_slope_ratio": 0.085,
        "source": "제6조제1항제5호바목 및 제11조제1항",
    }


@pytest.mark.parametrize(
    "count,convex_required,concave_required",
    [(49, False, False), (50, True, False), (99, True, False), (100, True, True)],
)
def test_transition_requirements_follow_statutory_space_thresholds(
    count: int, convex_required: bool, concave_required: bool
):
    ramp = rules(count)["statutory"]["ramp"]

    assert ramp["traffic_separation"]["required"] is (count >= 50)
    assert ramp["grade_transitions"]["convex"] == {
        "required": convex_required,
        "length_m": 1.7 if convex_required else None,
        "max_slope_ratio": 0.085 if convex_required else None,
        "source": "제6조제1항제5호사목 및 별표 1",
    }
    assert ramp["grade_transitions"]["concave"] == {
        "required": concave_required,
        "length_m": 2.0 if concave_required else None,
        "max_slope_ratio": 0.085 if concave_required else None,
        "source": "제6조제1항제5호사목 및 별표 1",
    }


def test_level_landing_is_explicitly_a_design_assumption_not_a_legal_threshold():
    result = rules(24)

    assert result["statutory"]["ramp"]["level_landing_length_m"] is None
    assert result["design_assumptions"]["ramp_level_landing"] == {
        "status": "design_assumption",
        "length_m": 6.0,
        "statutory_basis": None,
        "reason": "The cited provisions do not prescribe a general level-landing length; verify vehicle geometry and authority requirements.",
    }
    assert "ramp_level_landing_length_requires_project_review" in result["unresolved"]


@pytest.mark.parametrize(
    "context,gate",
    [
        ({"facility_type": "off_street"}, "facility_type"),
        ({"parking_method": "mechanical"}, "parking_method"),
        ({"parking_angle": "parallel"}, "parking_angle"),
        ({"ramp_shape": "curved"}, "ramp_shape"),
        ({"structure": "unknown"}, "structure"),
    ],
)
def test_unsupported_context_is_gated_without_applying_the_snapshot(context: dict, gate: str):
    result = rules(12, **context)

    assert result["status"] == "unsupported"
    assert result["applicability"]["status"] == "unsupported"
    assert gate in result["applicability"]["unsupported_fields"]
    assert result["statutory"] is None
    assert result["permit_compliance_verified"] is False


def test_date_outside_snapshot_is_needs_evidence_and_does_not_emit_thresholds():
    result = rules(12, assessment_date="2026-07-26")

    assert result["status"] == "needs_evidence"
    assert result["applicability"]["status"] == "needs_evidence"
    assert result["statutory"] is None
    assert "historical_edition_and_transitional_applicability" in result["unresolved"]


def test_eight_or_fewer_attached_spaces_are_gated_by_article_11_special_standard():
    result = rules(8)

    assert result["status"] == "needs_evidence"
    assert result["applicability"]["status"] == "needs_evidence"
    assert result["statutory"]["stalls"]["general"]["min_width_m"] == 2.5
    assert result["statutory"]["aisle"]["min_width_m"] == 6.0
    assert result["statutory"]["aisle"]["source"] == "제11조제5항제1호"
    assert result["statutory"]["ramp"] == {
        "status": "needs_evidence",
        "reason": "Article 11(5) replaces the paragraph (1) general structure standard for eight or fewer spaces.",
        "straight": None,
    }
    assumption = result["design_assumptions"]["small_attached_ramp_preliminary_envelope"]
    assert assumption["status"] == "design_assumption_needs_legal_applicability"
    assert assumption["legal_applicability_verified"] is False
    assert assumption["straight"]["one_lane_min_width_m"] == 3.3
    assert assumption["straight"]["two_lane_min_width_m"] == 6.0
    assert assumption["straight"]["max_longitudinal_slope_ratio"] == 0.17
    assert "article_11_5_small_attached_parking_special_standard" in result["unresolved"]


@pytest.mark.parametrize("required_spaces", [0, -1, True, 1.5, "12"])
def test_required_spaces_must_be_a_positive_exact_integer(required_spaces):
    with pytest.raises(ValueError, match="required_spaces"):
        rules(required_spaces)
