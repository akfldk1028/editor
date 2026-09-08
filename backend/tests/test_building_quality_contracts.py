from __future__ import annotations

from dataclasses import replace
import json
import math

import pytest

from backend.app.modules.building_quality.contracts import (
    AlternativeDiversityReport,
    QualityIssue,
)
from backend.app.modules.building_quality.policy import DEFAULT_QUALITY_POLICY
from backend.tests.building_quality_fixtures import (
    floor_metrics,
    quality_issue,
    report as _report,
    vertical_metrics,
)


def test_default_policy_is_frozen_complete_and_normalized() -> None:
    policy = DEFAULT_QUALITY_POLICY

    assert policy.version == "building-quality/v1"
    assert policy.minimum_floor_coverage == 0.60
    assert policy.minimum_primary_daylight_ratio == 0.70
    assert policy.minimum_room_form_pass_ratio == 0.90
    assert policy.minimum_core_stack_ratio == 0.95
    assert policy.minimum_service_stack_ratio == 0.70
    assert policy.minimum_pairwise_diversity == 0.25
    assert sum(policy.weights.values()) == pytest.approx(1.0)
    with pytest.raises(TypeError):
        policy.weights["daylight"] = 0.0


@pytest.mark.parametrize("value", [True, math.nan, math.inf, -0.1, 1.1])
def test_policy_rejects_invalid_ratio(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        replace(DEFAULT_QUALITY_POLICY, minimum_floor_coverage=value)


def test_policy_copies_and_freezes_weights() -> None:
    weights = dict(DEFAULT_QUALITY_POLICY.weights)
    policy = replace(DEFAULT_QUALITY_POLICY, weights=weights)

    weights["daylight"] = 0.0

    assert policy.weights["daylight"] == 0.25
    assert json.dumps(policy.weights) == json.dumps(dict(policy.weights))


@pytest.mark.parametrize(
    "weights",
    (
        {
            "daylight": 0.25,
            "room_form": 0.20,
            "vertical_stacking": 0.20,
            "egress": 0.35,
        },
        {
            "daylight": 0.15,
            "room_form": 0.20,
            "vertical_stacking": 0.20,
            "egress": 0.20,
            "coverage_efficiency": 0.15,
            "unexpected": 0.10,
        },
    ),
    ids=("missing-component", "extra-component"),
)
def test_policy_requires_exact_evaluator_component_weights(
    weights: dict[str, float],
) -> None:
    with pytest.raises(ValueError, match="weights"):
        replace(DEFAULT_QUALITY_POLICY, weights=weights)


def test_quality_issue_rejects_invalid_members() -> None:
    with pytest.raises(ValueError, match="severity"):
        replace(quality_issue(), severity="warning")
    with pytest.raises(TypeError, match="floor_index"):
        replace(quality_issue(), floor_index=True)
    with pytest.raises(ValueError, match="measured_value"):
        replace(quality_issue(), measured_value=math.nan)
    with pytest.raises(ValueError, match="message"):
        replace(quality_issue(), message="")


def test_floor_quality_metrics_reject_invalid_values() -> None:
    with pytest.raises(ValueError, match="coverage"):
        replace(floor_metrics(), coverage=1.1)
    with pytest.raises(ValueError, match="worst_aspect_ratio"):
        replace(floor_metrics(), worst_aspect_ratio=math.inf)
    with pytest.raises(ValueError, match="egress_status"):
        replace(floor_metrics(), egress_status="unknown")


def test_vertical_quality_metrics_reject_invalid_values() -> None:
    with pytest.raises(ValueError, match="core_stack_ratio"):
        replace(vertical_metrics(), core_stack_ratio=-0.1)
    with pytest.raises(ValueError, match="maximum_service_centroid_shift_m"):
        replace(vertical_metrics(), maximum_service_centroid_shift_m=math.nan)


def test_report_rejects_hard_pass_when_a_hard_issue_exists() -> None:
    issue = QualityIssue(
        code="daylight_proxy",
        severity="hard",
        floor_index=1,
        subject_id="open_work",
        measured_value=0.4,
        threshold=0.7,
        message="primary daylight proxy is below policy",
    )

    with pytest.raises(ValueError, match="hard_pass"):
        _report(hard_pass=True, issues=(issue,))


def test_report_requires_ordered_floors_and_immutable_component_scores() -> None:
    with pytest.raises(ValueError, match="floors"):
        replace(_report(), floors=(floor_metrics(2), floor_metrics(1)))

    component_scores = {"daylight": 0.8}
    quality_report = replace(_report(), component_scores=component_scores)
    component_scores["daylight"] = 0.0

    assert quality_report.component_scores["daylight"] == 0.8
    with pytest.raises(TypeError):
        quality_report.component_scores["daylight"] = 0.0
    assert json.dumps(quality_report.component_scores) == '{"daylight": 0.8}'


def test_diversity_report_validates_distances_and_consistency() -> None:
    report = AlternativeDiversityReport(
        first_fingerprint="first",
        second_fingerprint="second",
        core_distance=1.0,
        circulation_distance=1.0,
        topology_distance=1.0,
        area_distribution_distance=1.0,
        total_distance=1.0,
        nonzero_component_count=4,
        quality_distinct=True,
    )

    assert report.total_distance == 1.0
    with pytest.raises(ValueError, match="total_distance"):
        replace(report, total_distance=math.nan)
    with pytest.raises(ValueError, match="core_distance"):
        replace(report, core_distance=1.1)
    with pytest.raises(ValueError, match="total_distance"):
        replace(report, total_distance=1.1)
    with pytest.raises(ValueError, match="nonzero_component_count"):
        replace(report, nonzero_component_count=2)


def test_diversity_report_uses_weighted_total_distance() -> None:
    report = AlternativeDiversityReport(
        first_fingerprint="first",
        second_fingerprint="second",
        core_distance=0.5,
        circulation_distance=0.5,
        topology_distance=0.0,
        area_distribution_distance=0.0,
        total_distance=0.275,
        nonzero_component_count=2,
        quality_distinct=True,
    )

    assert report.total_distance == 0.275


def test_diversity_report_allows_small_differences_without_quality_distinction() -> None:
    report = AlternativeDiversityReport(
        first_fingerprint="first",
        second_fingerprint="second",
        core_distance=0.1,
        circulation_distance=0.1,
        topology_distance=0.0,
        area_distribution_distance=0.0,
        total_distance=0.055,
        nonzero_component_count=2,
        quality_distinct=False,
    )

    assert not report.quality_distinct


def test_diversity_report_allows_policy_to_reject_a_distinct_candidate() -> None:
    report = AlternativeDiversityReport(
        first_fingerprint="first",
        second_fingerprint="second",
        core_distance=0.5,
        circulation_distance=0.6,
        topology_distance=0.0,
        area_distribution_distance=0.0,
        total_distance=0.3,
        nonzero_component_count=2,
        quality_distinct=False,
    )

    assert not report.quality_distinct


def test_diversity_report_requires_multiple_material_differences_for_distinction() -> None:
    report = AlternativeDiversityReport(
        first_fingerprint="first",
        second_fingerprint="second",
        core_distance=0.9,
        circulation_distance=0.0,
        topology_distance=0.0,
        area_distribution_distance=0.0,
        total_distance=0.27,
        nonzero_component_count=1,
        quality_distinct=False,
    )

    assert not report.quality_distinct
    with pytest.raises(ValueError, match="quality_distinct"):
        replace(report, quality_distinct=True)
