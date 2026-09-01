from __future__ import annotations

from backend.app.modules.building_quality.contracts import (
    BuildingQualityReport,
    FloorQualityMetrics,
    QualityIssue,
    VerticalQualityMetrics,
)


def floor_metrics(floor_index: int = 1) -> FloorQualityMetrics:
    return FloorQualityMetrics(
        floor_index=floor_index,
        coverage=0.8,
        primary_daylight_ratio=0.8,
        room_form_pass_ratio=0.95,
        worst_aspect_ratio=2.0,
        narrowest_room_width_m=2.4,
        egress_status="pass",
    )


def vertical_metrics() -> VerticalQualityMetrics:
    return VerticalQualityMetrics(
        core_stack_ratio=1.0,
        shaft_stack_ratio=1.0,
        wet_service_stack_ratio=0.9,
        maximum_service_centroid_shift_m=0.2,
    )


def quality_issue(
    *, severity: str = "soft", floor_index: int | None = 1
) -> QualityIssue:
    return QualityIssue(
        code="daylight_proxy",
        severity=severity,  # type: ignore[arg-type]
        floor_index=floor_index,
        subject_id="open_work",
        measured_value=0.4,
        threshold=0.7,
        message="primary daylight proxy is below policy",
    )


def report(
    *, hard_pass: bool = True, issues: tuple[QualityIssue, ...] = ()
) -> BuildingQualityReport:
    return BuildingQualityReport(
        policy_version="building-quality/v1",
        hard_pass=hard_pass,
        score=0.8,
        component_scores={"daylight": 0.8},
        floors=(floor_metrics(),),
        vertical=vertical_metrics(),
        issues=issues,
        unresolved_facts=(),
    )
