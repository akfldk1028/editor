from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import math

import pytest

from backend.app.cli import _mass_input_from_payload
from backend.app.modules.generation_loop.service import run_building_generation
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.validator.service import validate_layout
from backend.app.modules.visual_review import service as visual_review_service
from backend.app.modules.visual_review.service import (
    create_building_visual_review_artifacts,
    create_visual_review_artifacts,
)
from backend.app.schemas.mass import (
    BuildingCodeContext,
    FloorCodeContext,
    MassInput,
)
from backend.app.schemas.regulatory import RegulatoryCheck, RegulatoryScreening
from backend.tests.test_use_planning_policy import _office_candidate


def _legacy_payload() -> dict:
    return {
        "project_id": "legacy-mass",
        "floors": 2,
        "footprint_polygon": [[0, 0], [30, 0], [30, 12], [0, 12]],
        "site_edges": [{"edge_index": 0, "kind": "street"}],
        "access_candidates": [{"edge_index": 0, "position": 0.5}],
        "use_mix": {"office": 1.0},
    }


def test_old_manifest_remains_loadable_without_code_context() -> None:
    mass = _mass_input_from_payload(_legacy_payload())

    assert mass.building_code_context is None
    assert analyze_mass(mass).building_code_context is None


def test_cli_loads_immutable_building_code_context() -> None:
    payload = {
        **_legacy_payload(),
        "building_code_context": {
            "jurisdiction": "KR",
            "effective_date": "2025-10-31",
            "floor_to_floor_height_m": 3.6,
            "sprinklered": True,
            "fire_resistant": True,
            "floor_facts": [
                {
                    "floor_index": 1,
                    "occupancy": "office",
                    "occupant_load": 42,
                    "above_grade": True,
                }
            ],
        },
    }

    mass = _mass_input_from_payload(payload)
    context = mass.building_code_context

    assert context == BuildingCodeContext(
        jurisdiction="KR",
        effective_date="2025-10-31",
        floor_to_floor_height_m=3.6,
        sprinklered=True,
        fire_resistant=True,
        floor_facts=(
            FloorCodeContext(
                floor_index=1,
                occupancy="office",
                occupant_load=42,
                above_grade=True,
            ),
        ),
    )
    assert analyze_mass(mass).building_code_context is context
    with pytest.raises(FrozenInstanceError):
        context.sprinklered = False  # type: ignore[misc]


def test_regulatory_records_are_immutable_and_reject_unknown_status() -> None:
    check = RegulatoryCheck(
        rule_id="KR-EGRESS-STAIR-SEPARATION",
        status="not_checked",
        source_url="https://law.go.kr/example",
        effective_date="2025-10-31",
        measured_value=None,
        threshold=15.0,
        applicability=None,
        assumptions=("sprinkler protection is unknown",),
    )
    screening = RegulatoryScreening(
        ruleset_id="KR-egress-2025-10-31",
        status="not_checked",
        checks=(check,),
        unresolved_facts=("sprinklered",),
    )

    assert screening.checks == (check,)
    with pytest.raises(FrozenInstanceError):
        check.status = "pass"  # type: ignore[misc]
    with pytest.raises(ValueError, match="status"):
        RegulatoryCheck(
            rule_id="bad",
            status="unknown",  # type: ignore[arg-type]
            source_url="https://law.go.kr/example",
            effective_date="2025-10-31",
            measured_value=None,
            threshold=None,
            applicability=None,
            assumptions=(),
        )


def test_regulatory_screening_rejects_inconsistent_aggregate_status() -> None:
    passing_check = RegulatoryCheck(
        rule_id="pass",
        status="pass",
        source_url="https://law.go.kr/example",
        effective_date="2025-10-31",
        measured_value=12.0,
        threshold=10.0,
        applicability=True,
        assumptions=(),
    )
    failing_check = RegulatoryCheck(
        rule_id="fail",
        status="fail",
        source_url="https://law.go.kr/example",
        effective_date="2025-10-31",
        measured_value=8.0,
        threshold=10.0,
        applicability=True,
        assumptions=(),
    )

    with pytest.raises(ValueError, match="pass"):
        RegulatoryScreening(
            ruleset_id="rules",
            status="pass",
            checks=(passing_check,),
            unresolved_facts=("two_stair_applicability",),
        )
    with pytest.raises(ValueError, match="pass"):
        RegulatoryScreening(
            ruleset_id="rules",
            status="pass",
            checks=(failing_check,),
        )
    with pytest.raises(ValueError, match="fail"):
        RegulatoryScreening(
            ruleset_id="rules",
            status="fail",
            checks=(passing_check,),
        )


def test_mass_rejects_mutable_or_invalid_code_context_values() -> None:
    with pytest.raises(ValueError, match="floor_to_floor_height_m"):
        BuildingCodeContext(floor_to_floor_height_m=0)
    with pytest.raises(TypeError, match="sprinklered"):
        BuildingCodeContext(sprinklered="yes")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="building_code_context"):
        MassInput(**_legacy_payload(), building_code_context={})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("qualifying_sprinkler", "denominator", "check_status"),
    [
        (None, 2.0, "not_checked"),
        (False, 2.0, "pass"),
        (True, 3.0, "pass"),
    ],
)
def test_qualifying_sprinkler_fact_controls_internal_separation_target_without_fabricating_status(
    qualifying_sprinkler,
    denominator,
    check_status,
) -> None:
    context = BuildingCodeContext(
        jurisdiction="KR",
        effective_date="2026-07-28",
        qualifying_sprinkler_protection=qualifying_sprinkler,
        travel_construction_class="not_qualified",
        floor_facts=(
            FloorCodeContext(
                floor_index=1,
                above_grade=True,
                is_evacuation_floor=False,
                occupancy_category="assembly_religious_bar_funeral_200",
                habitable_area_m2=200.0,
            ),
        ),
    )
    mass = MassInput(
        **_legacy_payload(),
        building_code_context=context,
    )

    result = run_building_generation(mass).floor_results[0]
    metric = result.validation.basic_design
    screening = result.validation.regulatory_screening

    assert metric is not None
    assert screening is not None
    expected = math.hypot(30.0, 12.0) / denominator
    assert metric.policy_checks["remote_exit_separation"]["threshold"] == pytest.approx(
        expected
    )
    assert screening.status == "not_checked"
    check = next(
        check
        for check in screening.checks
        if check.rule_id == "KR-EGRESS-STAIR-SEPARATION-ART8"
    )
    assert check.threshold == pytest.approx(expected)
    assert check.status == check_status
    assert check.source_url.startswith("https://law.go.kr/")
    assert check.effective_date == "2025-10-31"
    if qualifying_sprinkler is None:
        assert "qualifying_sprinkler_protection" in screening.unresolved_facts
        assert any(
            "half-diagonal" in assumption for assumption in check.assumptions
        )
    else:
        assert check.applicability is True
        assert check.measured_value is not None
        assert check.measured_value >= check.threshold
        assert (
            "qualifying_sprinkler_protection"
            not in screening.unresolved_facts
        )


def test_generated_exit_geometry_does_not_fabricate_regulatory_failure() -> None:
    layout, program = _office_candidate()
    context = BuildingCodeContext(
        jurisdiction="KR",
        effective_date="2026-07-28",
        qualifying_sprinkler_protection=False,
        travel_construction_class="not_qualified",
        floor_facts=(
            FloorCodeContext(
                floor_index=1,
                above_grade=True,
                is_evacuation_floor=False,
                occupancy_category="assembly_religious_bar_funeral_200",
                habitable_area_m2=200.0,
            ),
        ),
    )

    report = validate_layout(
        layout,
        program,
        [(0.0, 0.0), (18.0, 0.0), (18.0, 10.0), (0.0, 10.0)],
        require_basic_design=True,
        building_code_context=context,
    )

    assert report.regulatory_screening is not None
    assert report.regulatory_screening.status == "not_checked"
    separation = next(
        check
        for check in report.regulatory_screening.checks
        if check.rule_id == "KR-EGRESS-STAIR-SEPARATION-ART8"
    )
    assert separation.status == "not_checked"
    assert "connected_exit_passage" in report.regulatory_screening.unresolved_facts


def test_legacy_review_separates_internal_validation_from_unchecked_regulation(
    tmp_path,
) -> None:
    mass = _mass_input_from_payload(_legacy_payload())
    result = run_building_generation(mass).floor_results[0]

    artifacts = create_visual_review_artifacts(
        result,
        boundary=mass.footprint_polygon,
        output_dir=tmp_path,
    )
    report = json.loads(artifacts.report_path.read_text(encoding="utf-8"))
    page = artifacts.html_path.read_text(encoding="utf-8")

    assert report["internal_validation"]["status"] == "pass"
    assert report["regulatory_screening"]["status"] == "not_checked"
    assert "internal concept validation: pass" in page
    assert "regulatory screening: not checked" in page
    assert "passes hard validation" not in page


def test_render_failure_does_not_overwrite_internal_validation_status(
    tmp_path,
    monkeypatch,
) -> None:
    mass = _mass_input_from_payload(_legacy_payload())
    building = run_building_generation(mass)
    assert all(floor.validation.accepted for floor in building.floor_results)
    monkeypatch.setattr(
        visual_review_service,
        "_missing_basic_design_ids",
        lambda *_args: ("missing-rendered-object",),
    )

    artifacts = create_building_visual_review_artifacts(
        building,
        boundary=mass.footprint_polygon,
        output_dir=tmp_path,
    )
    building_report = json.loads(
        artifacts.report_path.read_text(encoding="utf-8")
    )
    floor_report = json.loads(
        artifacts.floor_artifacts[0].report_path.read_text(encoding="utf-8")
    )

    assert floor_report["internal_validation"]["status"] == "pass"
    assert floor_report["render_validation"]["status"] == "fail"
    assert building_report["internal_validation"]["status"] == "pass"
    assert building_report["render_validation"]["status"] == "fail"
    assert building_report["regulatory_screening"]["status"] == "not_checked"
    assert building_report["accepted"] is False
    assert artifacts.accepted is False
