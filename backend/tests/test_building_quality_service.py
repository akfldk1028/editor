from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.app.modules.building_quality import service
from backend.app.modules.building_quality.contracts import VerticalQualityMetrics
from backend.app.modules.building_quality.egress import EgressQualityMeasurement
from backend.app.modules.building_quality.policy import DEFAULT_QUALITY_POLICY
from backend.app.modules.building_quality.service import evaluate_building_quality


def test_evaluator_returns_versioned_component_scores_and_hard_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_measurements(monkeypatch)

    report = evaluate_building_quality(_building())

    assert report.policy_version == "building-quality/v1"
    assert report.hard_pass is True
    assert 0.0 <= report.score <= 1.0
    assert set(report.component_scores) == {
        "daylight",
        "room_form",
        "vertical_stacking",
        "egress",
        "coverage_efficiency",
    }
    assert not [issue for issue in report.issues if issue.severity == "hard"]


def test_hard_daylight_failure_cannot_be_offset_by_other_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_measurements(monkeypatch, daylight_ratio=0.69)

    report = evaluate_building_quality(_building())

    assert report.hard_pass is False
    assert any(
        issue.code == "primary_daylight_ratio"
        and issue.severity == "hard"
        and issue.measured_value == pytest.approx(0.69)
        and issue.threshold == pytest.approx(0.70)
        for issue in report.issues
    )


def test_unresolved_legal_context_does_not_become_pass_or_hard_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_measurements(
        monkeypatch,
        egress=EgressQualityMeasurement(
            status="not_checked",
            checked_floor_indexes=(),
            failed_floor_indexes=(),
            unresolved_facts=("jurisdiction",),
        ),
    )

    report = evaluate_building_quality(_building())

    assert "jurisdiction" in report.unresolved_facts
    assert any(issue.severity == "unresolved" for issue in report.issues)
    assert report.floors[0].egress_status == "not_checked"
    assert report.hard_pass is True


def test_custom_policy_controls_thresholds_and_rounds_public_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_measurements(monkeypatch, daylight_ratio=0.87654)
    policy = replace(
        DEFAULT_QUALITY_POLICY,
        version="test/v1",
        minimum_primary_daylight_ratio=0.88,
    )

    report = evaluate_building_quality(_building(), policy=policy)

    assert report.policy_version == "test/v1"
    assert report.component_scores["daylight"] == 0.8765
    assert report.hard_pass is False
    assert any(
        issue.code == "primary_daylight_ratio" and issue.threshold == 0.88
        for issue in report.issues
    )


def test_issues_are_deterministically_ordered_by_floor_then_policy_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_measurements(
        monkeypatch,
        daylight_ratio=0.0,
        room_form_ratio=0.0,
        egress=EgressQualityMeasurement(
            status="fail",
            checked_floor_indexes=(),
            failed_floor_indexes=(1, 2),
            unresolved_facts=("jurisdiction",),
        ),
        vertical=VerticalQualityMetrics(0.0, 0.0, 0.0, None),
    )

    report = evaluate_building_quality(_building(floor_indexes=(2, 1), coverage=0.0))

    assert [(issue.floor_index, issue.code) for issue in report.issues] == [
        (1, "floor_coverage"),
        (1, "primary_daylight_ratio"),
        (1, "room_form_pass_ratio"),
        (1, "egress_checked_failure"),
        (2, "floor_coverage"),
        (2, "primary_daylight_ratio"),
        (2, "room_form_pass_ratio"),
        (2, "egress_checked_failure"),
        (None, "core_stack_ratio"),
        (None, "shaft_stack_ratio"),
        (None, "wet_service_stack_ratio"),
        (None, "egress_unresolved"),
    ]


def _building(
    *, floor_indexes: tuple[int, ...] = (1,), coverage: float = 0.8
) -> SimpleNamespace:
    return SimpleNamespace(
        floor_results=tuple(
            SimpleNamespace(
                program=SimpleNamespace(floor_index=floor_index),
                validation=SimpleNamespace(coverage_score=coverage),
            )
            for floor_index in floor_indexes
        )
    )


def _stub_measurements(
    monkeypatch: pytest.MonkeyPatch,
    *,
    daylight_ratio: float = 0.8,
    room_form_ratio: float = 0.95,
    egress: EgressQualityMeasurement | None = None,
    vertical: VerticalQualityMetrics | None = None,
) -> None:
    monkeypatch.setattr(
        service,
        "measure_primary_daylight",
        lambda floor: SimpleNamespace(ratio=daylight_ratio),
    )
    monkeypatch.setattr(
        service,
        "measure_room_form",
        lambda floor: SimpleNamespace(
            ratio=room_form_ratio,
            worst_aspect_ratio=2.0,
            narrowest_width_m=2.4,
        ),
    )
    monkeypatch.setattr(
        service,
        "aggregate_egress_quality",
        lambda building: egress
        or EgressQualityMeasurement("pass", (1,), (), ()),
    )
    monkeypatch.setattr(
        service,
        "measure_vertical_quality",
        lambda building: vertical
        or VerticalQualityMetrics(1.0, 1.0, 0.9, 0.2),
    )
