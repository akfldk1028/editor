from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.modules.alternative_composer.contracts import (
    StructuralAlternativeRejection,
)
from backend.app.modules.alternative_composer.service import _rank_key
from backend.app.cli import _serialize_rejected_strategy
from backend.app.modules.building_quality import service
from backend.app.modules.building_quality.contracts import (
    BuildingQualityReport,
    FloorQualityMetrics,
    QualityIssue,
    VerticalQualityMetrics,
)
from backend.app.modules.building_quality.egress import aggregate_egress_quality
from backend.app.modules.building_quality.service import evaluate_building_quality
from backend.app.core.serialization import to_jsonable


def test_internal_egress_graph_failure_is_hard_while_legal_fact_remains_unresolved():
    floor = SimpleNamespace(
        program=SimpleNamespace(floor_index=2),
        validation=SimpleNamespace(
            regulatory_screening=SimpleNamespace(
                checks=(SimpleNamespace(status="pass"),),
                unresolved_facts=("jurisdiction",),
            )
        ),
        egress_graph=SimpleNamespace(
            status="not_checked",
            unresolved_facts=(
                "unreachable_occupied_room:open-work",
                "jurisdiction",
            ),
        ),
    )

    measured = aggregate_egress_quality(SimpleNamespace(floor_results=(floor,)))

    assert measured.status == "fail"
    assert measured.failed_floor_indexes == (2,)
    assert measured.hard_failure_facts == ((2, "unreachable_occupied_room:open-work"),)
    assert measured.unresolved_facts == (
        "jurisdiction",
        "unreachable_occupied_room:open-work",
    )
    assert measured.checked_floor_indexes == ()


@pytest.mark.parametrize("screening", (None, SimpleNamespace(checks=(), unresolved_facts=())))
def test_internal_egress_failure_survives_missing_or_empty_regulatory_screening(
    screening,
) -> None:
    floor = SimpleNamespace(
        program=SimpleNamespace(floor_index=4),
        validation=SimpleNamespace(regulatory_screening=screening),
        egress_graph=SimpleNamespace(
            status="not_checked",
            unresolved_facts=("protected_exit_portal_missing",),
        ),
    )

    measured = aggregate_egress_quality(SimpleNamespace(floor_results=(floor,)))

    assert measured.status == "fail"
    assert measured.failed_floor_indexes == (4,)
    assert measured.hard_failure_facts == ((4, "protected_exit_portal_missing"),)
    assert measured.unresolved_facts == ("protected_exit_portal_missing",)


def test_quality_evaluator_hard_fails_unmeasurable_geometry_with_floor_and_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_measurements(monkeypatch)
    monkeypatch.setattr(
        service,
        "measure_room_form",
        lambda floor: SimpleNamespace(
            ratio=1.0,
            worst_aspect_ratio=2.0,
            narrowest_width_m=2.0,
            unmeasurable_room_ids=("meeting",),
        ),
    )
    monkeypatch.setattr(
        service,
        "measure_vertical_quality_evidence",
        lambda building: SimpleNamespace(
            metrics=VerticalQualityMetrics(1.0, 1.0, 1.0, None),
            unmeasurable_geometry=((1, "shaft:shaft-west"),),
        ),
    )

    report = evaluate_building_quality(_building())

    assert report.hard_pass is False
    assert [
        (issue.floor_index, issue.subject_id)
        for issue in report.issues
        if issue.code == "geometry_unmeasurable"
    ] == [
        (1, "meeting"),
        (1, "shaft:shaft-west"),
    ]


def test_coverage_efficiency_combines_public_coverage_and_efficiency_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_measurements(monkeypatch)

    efficient = evaluate_building_quality(_building(efficiency=1.0))
    inefficient = evaluate_building_quality(_building(efficiency=0.4))

    assert efficient.component_scores["coverage_efficiency"] == pytest.approx(0.9)
    assert inefficient.component_scores["coverage_efficiency"] == pytest.approx(0.6)
    assert efficient.score > inefficient.score
    assert _rank_key(_rankable(efficient, "efficient")) < _rank_key(
        _rankable(inefficient, "inefficient")
    )


def test_quality_rejection_preserves_lossless_report_and_structured_issues() -> None:
    issue = QualityIssue(
        code="floor_coverage",
        severity="hard",
        floor_index=3,
        subject_id="floor-3",
        measured_value=0.5,
        threshold=0.6,
        message="floor coverage is below policy",
    )
    report = _quality_report(issue)

    rejection = StructuralAlternativeRejection(
        strategy="central",
        reason_type="BuildingQualityRejected",
        reason="legacy: floor_coverage:0.5/0.6",
        quality_report=report,
    )

    assert rejection.quality_report is report
    assert rejection.quality_report.issues[0].subject_id == "floor-3"
    serialized = _serialize_rejected_strategy(rejection)
    assert serialized["quality_report"]["issues"] == [
        {
            "code": "floor_coverage",
            "severity": "hard",
            "floor_index": 3,
            "subject_id": "floor-3",
            "measured_value": 0.5,
            "threshold": 0.6,
            "message": "floor coverage is below policy",
        }
    ]


def test_legal_unresolved_fact_forces_floor_not_checked_without_hard_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_measurements(monkeypatch, unresolved_facts=("jurisdiction",))

    report = evaluate_building_quality(_building())

    assert report.floors[0].egress_status == "not_checked"
    assert report.hard_pass is True


def test_vertical_metrics_v1_serialization_has_no_geometry_evidence_field() -> None:
    serialized = to_jsonable(VerticalQualityMetrics(1.0, 1.0, 1.0, None))

    assert serialized == {
        "core_stack_ratio": 1.0,
        "shaft_stack_ratio": 1.0,
        "wet_service_stack_ratio": 1.0,
        "maximum_service_centroid_shift_m": None,
    }


def _building(*, efficiency: float = 0.8) -> SimpleNamespace:
    return SimpleNamespace(
        floor_results=(
            SimpleNamespace(
                program=SimpleNamespace(floor_index=1),
                validation=SimpleNamespace(
                    coverage_score=0.8, efficiency_score=efficiency
                ),
            ),
        )
    )


def _stub_measurements(
    monkeypatch: pytest.MonkeyPatch,
    *,
    unresolved_facts: tuple[str, ...] = (),
) -> None:
    monkeypatch.setattr(
        service,
        "measure_primary_daylight",
        lambda floor: SimpleNamespace(ratio=1.0),
    )
    monkeypatch.setattr(
        service,
        "measure_room_form",
        lambda floor: SimpleNamespace(
            ratio=1.0,
            worst_aspect_ratio=2.0,
            narrowest_width_m=2.0,
            unmeasurable_room_ids=(),
        ),
    )
    monkeypatch.setattr(
        service,
        "aggregate_egress_quality",
        lambda building: SimpleNamespace(
            status="not_checked" if unresolved_facts else "pass",
            checked_floor_indexes=() if unresolved_facts else (1,),
            failed_floor_indexes=(),
            unresolved_facts=unresolved_facts,
            hard_failure_facts=(),
        ),
    )
    monkeypatch.setattr(
        service,
        "measure_vertical_quality_evidence",
        lambda building: SimpleNamespace(
            metrics=VerticalQualityMetrics(1.0, 1.0, 1.0, None),
            unmeasurable_geometry=(),
        ),
    )


def _quality_report(issue: QualityIssue) -> BuildingQualityReport:
    return BuildingQualityReport(
        policy_version="test/v1",
        hard_pass=False,
        score=0.8,
        component_scores={
            "daylight": 1.0,
            "room_form": 1.0,
            "vertical_stacking": 1.0,
            "egress": 1.0,
            "coverage_efficiency": 0.8,
        },
        floors=(FloorQualityMetrics(3, 0.5, 1.0, 1.0, None, None, "pass"),),
        vertical=VerticalQualityMetrics(1.0, 1.0, 1.0, None),
        issues=(issue,),
        unresolved_facts=(),
    )


def _rankable(report: BuildingQualityReport, fingerprint: str) -> SimpleNamespace:
    return SimpleNamespace(
        quality_report=report,
        building=SimpleNamespace(
            floor_results=(
                SimpleNamespace(validation=SimpleNamespace(total_score=1.0)),
            )
        ),
        structural_fingerprint=fingerprint,
    )
