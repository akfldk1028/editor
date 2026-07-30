from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from backend.app.modules.building_quality.contracts import (
    BuildingQualityReport,
    FloorQualityMetrics,
    QualityIssue,
    QualityPolicy,
    VerticalQualityMetrics,
)
from backend.app.modules.building_quality.daylight import measure_primary_daylight
from backend.app.modules.building_quality.egress import (
    EgressQualityMeasurement,
    aggregate_egress_quality,
)
from backend.app.modules.building_quality.policy import DEFAULT_QUALITY_POLICY
from backend.app.modules.building_quality.room_form import measure_room_form
from backend.app.modules.building_quality.vertical_stack import measure_vertical_quality
from backend.app.schemas.result import BuildingGenerationResult


def evaluate_building_quality(
    building: BuildingGenerationResult,
    policy: QualityPolicy = DEFAULT_QUALITY_POLICY,
) -> BuildingQualityReport:
    """Evaluate floor, vertical, and egress quality against one policy."""
    egress = aggregate_egress_quality(building)
    floors: list[FloorQualityMetrics] = []
    issues: list[QualityIssue] = []
    coverage_efficiency_scores: list[float] = []

    for floor in sorted(
        building.floor_results, key=lambda item: item.program.floor_index
    ):
        floor_index = floor.program.floor_index
        daylight = measure_primary_daylight(floor)
        room_form = measure_room_form(floor)
        coverage = float(floor.validation.coverage_score)
        efficiency = float(getattr(floor.validation, "efficiency_score", coverage))
        coverage_efficiency_scores.append((coverage + efficiency) / 2.0)
        egress_status = _floor_egress_status(floor_index, egress)
        metrics = FloorQualityMetrics(
            floor_index=floor_index,
            coverage=coverage,
            primary_daylight_ratio=daylight.ratio,
            room_form_pass_ratio=room_form.ratio,
            worst_aspect_ratio=room_form.worst_aspect_ratio,
            narrowest_room_width_m=room_form.narrowest_width_m,
            egress_status=egress_status,
        )
        floors.append(metrics)
        issues.extend(_floor_issues(metrics, policy))
        issues.extend(_room_form_geometry_issues(floor_index, room_form))

    vertical = measure_vertical_quality(building)
    issues.extend(_vertical_issues(vertical, policy))
    issues.extend(_vertical_geometry_issues(vertical))
    issues.extend(_egress_hard_failure_issues(egress.hard_failure_facts))
    issues.extend(_egress_unresolved_issues(egress.unresolved_facts))

    raw_component_scores = _component_scores(
        tuple(floors), vertical, egress.status, coverage_efficiency_scores
    )
    hard_pass = not any(issue.severity == "hard" for issue in issues)
    return BuildingQualityReport(
        policy_version=policy.version,
        hard_pass=hard_pass,
        score=round(
            sum(
                policy.weights[component] * score
                for component, score in raw_component_scores.items()
            ),
            4,
        ),
        component_scores={
            component: round(score, 4)
            for component, score in raw_component_scores.items()
        },
        floors=tuple(floors),
        vertical=vertical,
        issues=tuple(issues),
        unresolved_facts=tuple(sorted(set(egress.unresolved_facts))),
    )


def _floor_egress_status(
    floor_index: int, egress: EgressQualityMeasurement
) -> Literal["pass", "fail", "not_checked"]:
    if floor_index in egress.failed_floor_indexes:
        return "fail"
    if floor_index in egress.checked_floor_indexes:
        return "pass"
    return "not_checked"


def _floor_issues(
    metrics: FloorQualityMetrics, policy: QualityPolicy
) -> tuple[QualityIssue, ...]:
    issues: list[QualityIssue] = []
    thresholds = (
        (
            "floor_coverage",
            metrics.coverage,
            policy.minimum_floor_coverage,
            "floor coverage is below policy",
        ),
        (
            "primary_daylight_ratio",
            metrics.primary_daylight_ratio,
            policy.minimum_primary_daylight_ratio,
            "primary daylight ratio is below policy",
        ),
        (
            "room_form_pass_ratio",
            metrics.room_form_pass_ratio,
            policy.minimum_room_form_pass_ratio,
            "room form pass ratio is below policy",
        ),
    )
    for code, measured_value, threshold, message in thresholds:
        if measured_value < threshold:
            issues.append(
                QualityIssue(
                    code=code,
                    severity="hard",
                    floor_index=metrics.floor_index,
                    subject_id=f"floor-{metrics.floor_index}",
                    measured_value=measured_value,
                    threshold=threshold,
                    message=message,
                )
            )
    if metrics.egress_status == "fail":
        issues.append(
            QualityIssue(
                code="egress_checked_failure",
                severity="hard",
                floor_index=metrics.floor_index,
                subject_id=None,
                measured_value=0.0,
                threshold=1.0,
                message="checked egress requirement failed",
            )
        )
    return tuple(issues)


def _room_form_geometry_issues(
    floor_index: int,
    room_form,
) -> tuple[QualityIssue, ...]:
    return tuple(
        QualityIssue(
            code="geometry_unmeasurable",
            severity="hard",
            floor_index=floor_index,
            subject_id=room_id,
            measured_value=None,
            threshold=None,
            message="room form geometry cannot be measured",
        )
        for room_id in sorted(set(getattr(room_form, "unmeasurable_room_ids", ())))
    )


def _vertical_issues(
    vertical: VerticalQualityMetrics, policy: QualityPolicy
) -> tuple[QualityIssue, ...]:
    issues: list[QualityIssue] = []
    thresholds = (
        (
            "core_stack_ratio",
            vertical.core_stack_ratio,
            policy.minimum_core_stack_ratio,
            "core stack ratio is below policy",
            "hard",
        ),
        (
            "shaft_stack_ratio",
            vertical.shaft_stack_ratio,
            policy.minimum_shaft_stack_ratio,
            "shaft stack ratio is below policy",
            "hard",
        ),
        (
            "wet_service_stack_ratio",
            vertical.wet_service_stack_ratio,
            policy.minimum_service_stack_ratio,
            "wet service stack ratio is below policy",
            "soft",
        ),
    )
    for code, measured_value, threshold, message, severity in thresholds:
        if measured_value < threshold:
            issues.append(
                QualityIssue(
                    code=code,
                    severity=severity,
                    floor_index=None,
                    subject_id=None,
                    measured_value=measured_value,
                    threshold=threshold,
                    message=message,
                )
            )
    return tuple(issues)


def _vertical_geometry_issues(
    vertical: VerticalQualityMetrics,
) -> tuple[QualityIssue, ...]:
    return tuple(
        QualityIssue(
            code="geometry_unmeasurable",
            severity="hard",
            floor_index=floor_index,
            subject_id=subject_id,
            measured_value=None,
            threshold=None,
            message="vertical stack geometry cannot be measured",
        )
        for floor_index, subject_id in vertical.unmeasurable_geometry
    )


def _egress_hard_failure_issues(
    hard_failure_facts: tuple[tuple[int, str], ...],
) -> tuple[QualityIssue, ...]:
    return tuple(
        QualityIssue(
            code="egress_graph_failure",
            severity="hard",
            floor_index=floor_index,
            subject_id=fact,
            measured_value=0.0,
            threshold=1.0,
            message="egress graph contains an internal failure",
        )
        for floor_index, fact in sorted(set(hard_failure_facts))
    )


def _egress_unresolved_issues(
    unresolved_facts: tuple[str, ...],
) -> tuple[QualityIssue, ...]:
    return tuple(
        QualityIssue(
            code="egress_unresolved",
            severity="unresolved",
            floor_index=None,
            subject_id=fact,
            measured_value=None,
            threshold=None,
            message=f"egress fact remains unresolved: {fact}",
        )
        for fact in sorted(set(unresolved_facts))
    )


def _component_scores(
    floors: tuple[FloorQualityMetrics, ...],
    vertical: VerticalQualityMetrics,
    egress_status: Literal["pass", "fail", "not_checked"],
    coverage_efficiency_scores: Iterable[float],
) -> dict[str, float]:
    scores = {
        "daylight": _mean(floor.primary_daylight_ratio for floor in floors),
        "room_form": _mean(floor.room_form_pass_ratio for floor in floors),
        "vertical_stacking": (
            vertical.core_stack_ratio
            + vertical.shaft_stack_ratio
            + vertical.wet_service_stack_ratio
        )
        / 3,
        "egress": {"pass": 1.0, "fail": 0.0, "not_checked": 0.5}[egress_status],
        "coverage_efficiency": _mean(coverage_efficiency_scores),
    }
    return scores


def _mean(values: Iterable[float]) -> float:
    values = tuple(values)
    return sum(values) / len(values)
