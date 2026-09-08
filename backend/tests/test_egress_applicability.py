from __future__ import annotations

from dataclasses import replace
import math

import pytest

from backend.app.cli import _mass_input_from_payload
from backend.app.core.serialization import to_jsonable
from backend.app.modules.generation_loop.service import run_building_generation
from backend.app.modules.validator.service import (
    _regulatory_exit_separation_threshold,
    screen_egress_requirements,
)
from backend.app.schemas.mass import (
    BuildingCodeContext,
    FloorCodeContext,
    MassInput,
)
from backend.app.schemas.regulatory import ExitSeparationEvidence

ARTICLE_34_URL = (
    "https://www.law.go.kr/lsLinkCommonInfo.do?lsJoLnkSeq=1025183067"
)
ARTICLE_8_URL = (
    "https://law.go.kr/lsLinkCommonInfo.do?"
    "chrClsCd=010202&lsJoLnkSeq=1025183885"
)
RULESET = "KR-egress-art34-20260227-art8-20251031"


def _fact(
    category: str | None,
    area: float | None,
    *,
    above_grade: bool | None = True,
    story: int | None = 1,
    occupancy: str | None = None,
    floor_index: int = 1,
    is_evacuation_floor: bool | None = False,
) -> FloorCodeContext:
    return FloorCodeContext(
        floor_index=floor_index,
        occupancy=occupancy,
        above_grade=above_grade,
        occupancy_category=category,
        story_number=story,
        habitable_area_m2=area,
        is_evacuation_floor=is_evacuation_floor,
    )


def _screen(
    fact: FloorCodeContext | None,
    *,
    generated_count: int | None = 2,
    verified_count: int | None = 2,
    measured_separation: float | None = 20.0,
    connected_passage_verified: bool | None = True,
    qualifying_sprinkler: bool | None = False,
    travel_class: str | None = "not_qualified",
    travel_limit: str | None = "general_30",
    jurisdiction: str | None = "KR",
    analysis_date: str | None = "2026-07-28",
):
    context = BuildingCodeContext(
        jurisdiction=jurisdiction,
        effective_date=analysis_date,
        qualifying_sprinkler_protection=qualifying_sprinkler,
        travel_construction_class=travel_class,
        travel_limit_classification=travel_limit,
        floor_facts=(() if fact is None else (fact,)),
    )
    return screen_egress_requirements(
        context=context,
        floor_index=1,
        generated_direct_stair_count=generated_count,
        floor_diagonal=30.0,
        verified_direct_stair_count=verified_count,
        exit_separation_evidence=ExitSeparationEvidence(
            nearest_doorway_segment_distance_m=measured_separation,
            connected_passage_verified=connected_passage_verified,
            exit_portal_ids=("exit-1", "exit-2"),
        ),
    )


def _check(screening, rule_id: str):
    return next(check for check in screening.checks if check.rule_id == rule_id)


@pytest.mark.parametrize(
    ("category", "above_grade", "story", "threshold"),
    [
        ("other_supported", False, None, 200.0),
        (
            "neighborhood_assembly_or_religious_meeting_300",
            True,
            None,
            300.0,
        ),
        ("assembly_religious_bar_funeral_200", True, None, 200.0),
        ("sales_and_similar", True, 3, 200.0),
        ("multi_unit_housing_over_4_units_per_floor", True, None, 300.0),
        ("officetel", True, None, 300.0),
        ("other_supported", True, 3, 400.0),
    ],
)
@pytest.mark.parametrize(
    ("offset", "expected_count"),
    [(-0.001, 1), (0.0, 2), (0.001, 2)],
)
def test_article_34_threshold_boundaries(
    category,
    above_grade,
    story,
    threshold,
    offset,
    expected_count,
) -> None:
    screening = _screen(
        _fact(
            category,
            threshold + offset,
            above_grade=above_grade,
            story=story,
        )
    )

    assert screening.screened_required_direct_stair_count == expected_count
    direct = _check(screening, "KR-EGRESS-DIRECT-STAIR-COUNT-ART34")
    assert direct.threshold == expected_count
    assert direct.status == "pass"


@pytest.mark.parametrize(
    ("category", "threshold"),
    [
        ("neighborhood_assembly_or_religious_meeting_300", 300.0),
        ("assembly_religious_bar_funeral_200", 200.0),
        ("multi_unit_housing_over_4_units_per_floor", 300.0),
        ("officetel", 300.0),
    ],
)
@pytest.mark.parametrize("story", [1, 2, 3])
def test_story_independent_branches_apply_on_every_story(
    category,
    threshold,
    story,
) -> None:
    screening = _screen(_fact(category, threshold, story=story))

    assert screening.screened_required_direct_stair_count == 2


@pytest.mark.parametrize("category", ["sales_and_similar", "other_supported"])
def test_story_three_boundary_applies_only_to_story_limited_branches(category) -> None:
    threshold = 200.0 if category == "sales_and_similar" else 400.0

    story_two = _screen(_fact(category, threshold, story=2))
    story_three = _screen(_fact(category, threshold, story=3))

    assert story_two.screened_required_direct_stair_count == 1
    assert story_three.screened_required_direct_stair_count == 2


def test_basement_clause_can_make_below_category_threshold_ambiguous() -> None:
    screening = _screen(
        _fact(
            "neighborhood_assembly_or_religious_meeting_300",
            250.0,
            above_grade=None,
            story=None,
        )
    )

    assert screening.screened_required_direct_stair_count is None
    assert _check(
        screening,
        "KR-EGRESS-DIRECT-STAIR-COUNT-ART34",
    ).status == "not_checked"
    assert "above_grade" in screening.unresolved_facts


def test_basement_non_evacuation_floor_does_not_require_occupancy_category() -> None:
    screening = _screen(
        _fact(
            None,
            200.0,
            above_grade=False,
            story=None,
            is_evacuation_floor=False,
        )
    )

    assert screening.screened_required_direct_stair_count == 2
    assert "occupancy_category" not in screening.unresolved_facts


def test_unknown_evacuation_floor_status_blocks_direct_stair_screening() -> None:
    screening = _screen(
        _fact(
            "assembly_religious_bar_funeral_200",
            200.0,
            is_evacuation_floor=None,
        )
    )

    direct = _check(screening, "KR-EGRESS-DIRECT-STAIR-COUNT-ART34")
    assert direct.applicability is None
    assert direct.status == "not_checked"
    assert screening.screened_required_direct_stair_count is None
    assert "is_evacuation_floor" in screening.unresolved_facts


def test_evacuation_floor_marks_direct_stair_check_not_applicable() -> None:
    screening = _screen(
        _fact(
            "assembly_religious_bar_funeral_200",
            500.0,
            is_evacuation_floor=True,
        )
    )

    direct = _check(screening, "KR-EGRESS-DIRECT-STAIR-COUNT-ART34")
    assert direct.applicability is False
    assert direct.status == "not_checked"
    assert direct.threshold is None
    assert screening.screened_required_direct_stair_count is None
    assert "is_evacuation_floor" not in screening.unresolved_facts


@pytest.mark.parametrize(
    ("fact", "unresolved"),
    [
        (None, "floor_code_context"),
        (_fact(None, 200.0), "occupancy_category"),
        (_fact("sales_and_similar", None, story=3), "habitable_area_m2"),
        (
            _fact("sales_and_similar", 200.0, above_grade=None, story=None),
            "above_grade",
        ),
        (
            _fact("sales_and_similar", 200.0, above_grade=True, story=None),
            "story_number",
        ),
    ],
)
def test_missing_applicability_facts_are_not_checked(fact, unresolved) -> None:
    screening = _screen(fact)

    assert screening.screened_required_direct_stair_count is None
    assert unresolved in screening.unresolved_facts
    assert _check(
        screening,
        "KR-EGRESS-DIRECT-STAIR-COUNT-ART34",
    ).status == "not_checked"


def test_legacy_occupancy_does_not_classify_raw_multi_unit_housing() -> None:
    screening = _screen(
        _fact(None, 300.0, occupancy="multi_unit_housing")
    )

    assert screening.screened_required_direct_stair_count is None
    assert "occupancy_category" in screening.unresolved_facts


def test_generated_and_screened_stair_counts_remain_distinct() -> None:
    screening = _screen(
        _fact("assembly_religious_bar_funeral_200", 199.999, story=2)
    )

    assert screening.generated_direct_stair_count == 2
    assert screening.verified_direct_stair_count == 2
    assert screening.screened_required_direct_stair_count == 1
    direct = _check(screening, "KR-EGRESS-DIRECT-STAIR-COUNT-ART34")
    assert direct.measured_value == 2
    assert direct.threshold == 1
    assert direct.status == "pass"


def test_required_two_stairs_fails_with_one_generated_stair() -> None:
    screening = _screen(
        _fact("assembly_religious_bar_funeral_200", 200.0),
        generated_count=1,
        verified_count=1,
    )

    assert screening.status == "fail"
    assert _check(
        screening,
        "KR-EGRESS-DIRECT-STAIR-COUNT-ART34",
    ).status == "fail"


@pytest.mark.parametrize(
    ("qualifying", "denominator", "status"),
    [(True, 3.0, "pass"), (False, 2.0, "pass"), (None, 2.0, "not_checked")],
)
def test_article_8_uses_only_explicit_qualifying_sprinkler_fact(
    qualifying,
    denominator,
    status,
) -> None:
    screening = _screen(
        _fact("assembly_religious_bar_funeral_200", 200.0),
        measured_separation=30.0 / denominator,
        qualifying_sprinkler=qualifying,
    )

    separation = _check(screening, "KR-EGRESS-STAIR-SEPARATION-ART8")
    assert separation.threshold == pytest.approx(30.0 / denominator)
    assert separation.status == status
    assert separation.source_url == ARTICLE_8_URL
    assert separation.effective_date == "2025-10-31"
    assert separation.source_effective_date == "2025-10-31"


def test_article_8_recomputes_failure_from_measured_exit_separation() -> None:
    screening = _screen(
        _fact("assembly_religious_bar_funeral_200", 200.0),
        measured_separation=14.999,
        qualifying_sprinkler=False,
    )

    separation = _check(screening, "KR-EGRESS-STAIR-SEPARATION-ART8")
    assert separation.threshold == 15.0
    assert separation.status == "fail"
    assert screening.status == "fail"


def test_article_8_needs_explicit_connected_passage_evidence() -> None:
    screening = _screen(
        _fact("assembly_religious_bar_funeral_200", 200.0),
        measured_separation=15.0,
        connected_passage_verified=None,
        qualifying_sprinkler=False,
    )

    separation = _check(screening, "KR-EGRESS-STAIR-SEPARATION-ART8")
    assert separation.measured_value == 15.0
    assert separation.status == "not_checked"
    assert "connected_exit_passage" in screening.unresolved_facts


def test_article_8_is_not_applicable_when_screened_count_is_one() -> None:
    screening = _screen(
        _fact("assembly_religious_bar_funeral_200", 199.999)
    )

    separation = _check(screening, "KR-EGRESS-STAIR-SEPARATION-ART8")
    assert separation.applicability is False
    assert separation.threshold is None
    assert separation.status == "not_checked"
    assert "qualifying_sprinkler_protection" not in (
        screening.unresolved_facts
    )


@pytest.mark.parametrize(
    ("travel_limit", "threshold"),
    [
        ("qualified_50", 50.0),
        ("highrise_residential_40", 40.0),
        ("general_30", 30.0),
    ],
)
def test_task_two_travel_check_never_fabricates_measurement(
    travel_limit,
    threshold,
) -> None:
    screening = _screen(
        _fact("assembly_religious_bar_funeral_200", 200.0),
        travel_limit=travel_limit,
    )

    travel = _check(screening, "KR-EGRESS-TRAVEL-DISTANCE-ART34")
    assert travel.status == "not_checked"
    assert travel.applicability is True
    assert travel.measured_value is None
    assert travel.threshold == threshold
    assert travel.source_url == ARTICLE_34_URL
    assert travel.effective_date == "2026-02-27"
    assert travel.source_effective_date == "2026-02-27"
    assert "measured_travel_distance" in screening.unresolved_facts


def test_legacy_travel_construction_class_alone_never_claims_50_m() -> None:
    screening = _screen(
        _fact("assembly_religious_bar_funeral_200", 200.0),
        travel_class="fire_resistant_or_noncombustible",
        travel_limit=None,
    )

    travel = _check(screening, "KR-EGRESS-TRAVEL-DISTANCE-ART34")
    assert travel.threshold == 30.0
    assert travel.status == "not_checked"
    assert "travel_limit_classification" in screening.unresolved_facts


def test_rule_sources_and_floor_identity_are_serialized() -> None:
    screening = _screen(
        _fact("assembly_religious_bar_funeral_200", 200.0)
    )
    payload = to_jsonable(screening)

    assert payload["ruleset_id"] == RULESET
    assert payload["floor_index"] == 1
    assert payload["analysis_as_of_date"] == "2026-07-28"
    assert {
        check["rule_id"]: (
            check["source_url"],
            check["source_effective_date"],
        )
        for check in payload["checks"]
    } == {
        "KR-EGRESS-DIRECT-STAIR-COUNT-ART34": (
            ARTICLE_34_URL,
            "2026-02-27",
        ),
        "KR-EGRESS-STAIR-SEPARATION-ART8": (
            ARTICLE_8_URL,
            "2025-10-31",
        ),
        "KR-EGRESS-TRAVEL-DISTANCE-ART34": (
            ARTICLE_34_URL,
            "2026-02-27",
        ),
    }


def test_legacy_sprinkler_and_fire_resistance_do_not_enable_exceptions() -> None:
    context = BuildingCodeContext(
        jurisdiction="KR",
        effective_date="2026-07-28",
        sprinklered=True,
        fire_resistant=True,
        floor_facts=(
            _fact("assembly_religious_bar_funeral_200", 200.0),
        ),
    )

    screening = screen_egress_requirements(
        context=context,
        floor_index=1,
        generated_direct_stair_count=2,
        floor_diagonal=30.0,
        verified_direct_stair_count=2,
        exit_separation_evidence=ExitSeparationEvidence(
            nearest_doorway_segment_distance_m=15.0,
            connected_passage_verified=True,
            exit_portal_ids=("exit-1", "exit-2"),
        ),
    )

    separation = _check(screening, "KR-EGRESS-STAIR-SEPARATION-ART8")
    travel = _check(screening, "KR-EGRESS-TRAVEL-DISTANCE-ART34")
    assert separation.threshold == 15.0
    assert separation.status == "not_checked"
    assert travel.threshold == 30.0
    assert "qualifying_sprinkler_protection" in screening.unresolved_facts
    assert "travel_limit_classification" in screening.unresolved_facts


@pytest.mark.parametrize(
    "kwargs",
    [
        {"occupancy_category": "unknown"},
        {"habitable_area_m2": -1},
        {"habitable_area_m2": math.inf},
        {"habitable_area_m2": math.nan},
        {"habitable_area_m2": True},
        {"story_number": 0},
    ],
)
def test_floor_code_context_rejects_invalid_typed_facts(kwargs) -> None:
    values = {
        "floor_index": 1,
        "above_grade": True,
        "occupancy_category": "other_supported",
        "story_number": 3,
        "habitable_area_m2": 400.0,
        **kwargs,
    }

    with pytest.raises((TypeError, ValueError)):
        FloorCodeContext(**values)


def test_basement_rejects_above_grade_story_number() -> None:
    with pytest.raises(ValueError, match="story_number"):
        _fact(
            "other_supported",
            200.0,
            above_grade=False,
            story=1,
        )


def test_new_qualification_facts_are_independent_from_legacy_booleans() -> None:
    context = BuildingCodeContext(
        sprinklered=False,
        qualifying_sprinkler_protection=True,
        fire_resistant=False,
        travel_construction_class="fire_resistant_or_noncombustible",
        travel_limit_classification="qualified_50",
    )

    assert context.sprinklered is False
    assert context.qualifying_sprinkler_protection is True
    assert context.fire_resistant is False
    assert context.travel_construction_class == (
        "fire_resistant_or_noncombustible"
    )
    assert context.travel_limit_classification == "qualified_50"


def test_generic_sprinkler_can_be_explicitly_nonqualifying() -> None:
    context = BuildingCodeContext(
        sprinklered=True,
        qualifying_sprinkler_protection=False,
    )

    assert context.sprinklered is True
    assert context.qualifying_sprinkler_protection is False


def test_mass_rejects_floor_facts_outside_supplied_floors() -> None:
    context = BuildingCodeContext(
        floor_facts=(_fact("other_supported", 100.0, floor_index=3),)
    )

    with pytest.raises(ValueError, match="outside"):
        MassInput(
            project_id="bounds",
            floors=2,
            footprint_polygon=[(0, 0), (20, 0), (20, 12), (0, 12)],
            site_edges=[],
            access_candidates=[],
            use_mix={"office": 1.0},
            building_code_context=context,
        )


def test_cli_loads_new_context_fields_without_changing_legacy_fields() -> None:
    mass = _mass_input_from_payload(
        {
            "project_id": "typed",
            "floors": 1,
            "footprint_polygon": [[0, 0], [20, 0], [20, 12], [0, 12]],
            "site_edges": [],
            "access_candidates": [],
            "use_mix": {"office": 1.0},
            "building_code_context": {
                "jurisdiction": "KR",
                "effective_date": "2026-07-28",
                "sprinklered": True,
                "fire_resistant": True,
                "qualifying_sprinkler_protection": True,
                "travel_construction_class": (
                    "fire_resistant_or_noncombustible"
                ),
                "travel_limit_classification": "qualified_50",
                "floor_facts": [
                    {
                        "floor_index": 1,
                        "occupancy": "legacy-display",
                        "above_grade": True,
                        "occupancy_category": (
                            "assembly_religious_bar_funeral_200"
                        ),
                        "habitable_area_m2": 200.0,
                        "is_evacuation_floor": False,
                    }
                ],
            },
        }
    )

    context = mass.building_code_context
    assert context is not None
    assert context.sprinklered is True
    assert context.qualifying_sprinkler_protection is True
    assert context.travel_construction_class == (
        "fire_resistant_or_noncombustible"
    )
    assert context.travel_limit_classification == "qualified_50"
    assert context.floor_facts[0].occupancy == "legacy-display"
    assert context.floor_facts[0].occupancy_category == (
        "assembly_religious_bar_funeral_200"
    )


def test_building_generation_preserves_distinct_floor_screening_results() -> None:
    mass = MassInput(
        project_id="floor-specific",
        floors=2,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
        building_code_context=BuildingCodeContext(
            jurisdiction="KR",
            effective_date="2026-07-28",
            qualifying_sprinkler_protection=False,
            travel_construction_class="not_qualified",
            floor_facts=(
                _fact(
                    "assembly_religious_bar_funeral_200",
                    200.0,
                    floor_index=1,
                ),
                _fact(
                    "assembly_religious_bar_funeral_200",
                    199.999,
                    floor_index=2,
                ),
            ),
        ),
    )

    building = run_building_generation(mass)
    screenings = tuple(
        floor.validation.regulatory_screening
        for floor in building.floor_results
    )

    assert all(screening is not None for screening in screenings)
    assert [screening.floor_index for screening in screenings] == [1, 2]
    assert [
        screening.screened_required_direct_stair_count
        for screening in screenings
    ] == [2, 1]
    assert all(len(screening.checks) == 3 for screening in screenings)


def test_unknown_context_keeps_three_checks_separate() -> None:
    screening = screen_egress_requirements(
        context=None,
        floor_index=1,
        generated_direct_stair_count=2,
        floor_diagonal=30.0,
        verified_direct_stair_count=None,
        exit_separation_evidence=None,
    )

    assert screening.status == "not_checked"
    assert tuple(check.rule_id for check in screening.checks) == (
        "KR-EGRESS-DIRECT-STAIR-COUNT-ART34",
        "KR-EGRESS-STAIR-SEPARATION-ART8",
        "KR-EGRESS-TRAVEL-DISTANCE-ART34",
    )
    assert all(check.status == "not_checked" for check in screening.checks)
    assert _check(
        screening,
        "KR-EGRESS-TRAVEL-DISTANCE-ART34",
    ).applicability is None
    assert screening.generated_direct_stair_count == 2
    assert screening.verified_direct_stair_count is None
    assert screening.screened_required_direct_stair_count is None
    assert "floor_code_context" in screening.unresolved_facts


@pytest.mark.parametrize(
    "analysis_date",
    ["2026-02-27", "2026-04-15", "2026-07-28"],
)
def test_supported_analysis_as_of_date_range_is_checked(
    analysis_date,
) -> None:
    screening = _screen(
        _fact("assembly_religious_bar_funeral_200", 200.0),
        analysis_date=analysis_date,
    )

    assert screening.analysis_as_of_date == analysis_date
    assert screening.screened_required_direct_stair_count == 2
    assert "effective_date" not in screening.unresolved_facts


@pytest.mark.parametrize("analysis_date", ["2026-02-26", "2026-07-29"])
def test_unverified_analysis_as_of_date_is_not_checked(
    analysis_date,
) -> None:
    screening = _screen(
        _fact("assembly_religious_bar_funeral_200", 200.0),
        analysis_date=analysis_date,
    )

    assert screening.status == "not_checked"
    assert screening.screened_required_direct_stair_count is None
    assert "effective_date" in screening.unresolved_facts


def test_wrong_jurisdiction_is_not_checked() -> None:
    fact = _fact("assembly_religious_bar_funeral_200", 200.0)
    wrong_jurisdiction = _screen(fact, jurisdiction="US")

    assert wrong_jurisdiction.status == "not_checked"
    assert "jurisdiction" in wrong_jurisdiction.unresolved_facts


def test_floor_screening_selects_only_matching_floor_fact() -> None:
    first = _fact(
        "assembly_religious_bar_funeral_200",
        200.0,
        floor_index=1,
    )
    second = replace(first, floor_index=2, habitable_area_m2=199.999)
    context = BuildingCodeContext(
        jurisdiction="KR",
        effective_date="2026-07-28",
        qualifying_sprinkler_protection=False,
        travel_construction_class="not_qualified",
        floor_facts=(first, second),
    )

    result = screen_egress_requirements(
        context=context,
        floor_index=2,
        generated_direct_stair_count=2,
        floor_diagonal=30.0,
        verified_direct_stair_count=2,
        exit_separation_evidence=ExitSeparationEvidence(
            nearest_doorway_segment_distance_m=20.0,
            connected_passage_verified=True,
            exit_portal_ids=("exit-1", "exit-2"),
        ),
    )

    assert result.floor_index == 2
    assert result.screened_required_direct_stair_count == 1


def test_validate_layout_does_not_treat_stair_elements_as_verified_direct_stairs() -> None:
    mass = MassInput(
        project_id="unverified-direct-stairs",
        floors=1,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
        building_code_context=BuildingCodeContext(
            jurisdiction="KR",
            effective_date="2026-04-15",
            qualifying_sprinkler_protection=False,
            travel_limit_classification="general_30",
            floor_facts=(
                _fact("assembly_religious_bar_funeral_200", 200.0),
            ),
        ),
    )

    result = run_building_generation(mass).floor_results[0]
    screening = result.validation.regulatory_screening
    assert screening is not None
    direct = _check(screening, "KR-EGRESS-DIRECT-STAIR-COUNT-ART34")
    assert screening.generated_direct_stair_count == 2
    assert screening.verified_direct_stair_count is None
    assert direct.measured_value is None
    assert direct.status == "not_checked"
    assert "all_floor_stair_continuity" in screening.unresolved_facts
    assert "ground_termination" in screening.unresolved_facts


def test_validate_layout_records_graph_proven_connected_passage() -> None:
    mass = MassInput(
        project_id="portal-distance",
        floors=1,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
        building_code_context=BuildingCodeContext(
            jurisdiction="KR",
            effective_date="2026-04-15",
            qualifying_sprinkler_protection=False,
            travel_limit_classification="general_30",
            floor_facts=(
                _fact("assembly_religious_bar_funeral_200", 200.0),
            ),
        ),
    )

    result = run_building_generation(mass).floor_results[0]
    screening = result.validation.regulatory_screening
    assert screening is not None
    evidence = screening.exit_separation_evidence
    assert evidence is not None
    assert evidence.nearest_doorway_segment_distance_m is not None
    assert result.egress_graph is not None
    assert result.egress_graph.status == "checked"
    assert evidence.connected_passage_verified is True
    separation = _check(screening, "KR-EGRESS-STAIR-SEPARATION-ART8")
    assert separation.status == "pass"
    assert "connected_exit_passage" not in screening.unresolved_facts


def test_irregular_boundary_uses_maximum_pairwise_vertex_distance() -> None:
    boundary = [
        (0.0, 1.0),
        (2.0, 0.0),
        (4.0, 1.0),
        (3.0, 3.0),
        (1.0, 3.0),
    ]
    context = BuildingCodeContext(
        qualifying_sprinkler_protection=False,
    )

    threshold = _regulatory_exit_separation_threshold(boundary, context)

    assert threshold == pytest.approx(2.0)
    assert threshold != pytest.approx(5.0 / 2.0)
