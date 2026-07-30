from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely import union_all
from shapely.geometry import Polygon

import backend.app.modules.alternative_composer.service as alternative_service
from backend.app.modules.alternative_composer.contracts import (
    GeneratorRepairAttempt,
    GeneratorRepairProvenance,
    StructuralAlternative,
    StructuralAlternativeRejection,
)
from backend.app.modules.alternative_composer.service import (
    StructuralComposition,
    compose_structural_alternatives,
    deduplicate_structural_alternatives,
    room_structural_fingerprint,
)
from backend.app.modules.building_quality.contracts import (
    AlternativeDiversityReport,
    BuildingQualityReport,
    FloorQualityMetrics,
    QualityIssue,
    VerticalQualityMetrics,
)
from backend.app.modules.building_quality import (
    PrimaryDaylightMeasurement,
    compare_building_diversity,
    measure_primary_daylight,
)
from backend.app.modules.circulation_planner.service import (
    circulation_geometry_fingerprint,
    generate_circulation_candidate,
)
from backend.app.modules.core_planner.service import (
    core_geometry_fingerprint,
    generate_shared_core_candidates,
)
from backend.app.modules.generation_loop.service import run_building_generation
from backend.app.modules.generation_loop.contracts import ExteriorAllocationRequest
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.schemas.mass import FloorFootprint, MassInput
from backend.app.schemas.result import BuildingGenerationResult


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "datasets"
    / "manifests"
    / "sample_mass_irregular_12v_setback_office.json"
)


def test_irregular_mass_produces_two_hard_pass_quality_distinct_families() -> None:
    composition = _composition()

    assert {item.strategy for item in composition.alternatives} == {
        "long_edge_adjacent",
        "notch_adjacent",
    }
    assert len(composition.alternatives) >= 2
    assert all(item.building.accepted for item in composition.alternatives)
    assert all(item.quality_report.hard_pass for item in composition.alternatives)
    long_edge = next(
        item
        for item in composition.alternatives
        if item.strategy == "long_edge_adjacent"
    )
    floor_3 = next(
        floor
        for floor in long_edge.quality_report.floors
        if floor.floor_index == 3
    )
    generated_floor_3 = long_edge.building.floor_results[2]
    daylight = measure_primary_daylight(generated_floor_3)
    repair, = long_edge.generator_repairs

    assert floor_3.primary_daylight_ratio >= 0.70
    assert floor_3.primary_daylight_ratio == pytest.approx(daylight.ratio)
    assert daylight.served_room_ids == ("meeting", "open_work")
    assert daylight.unserved_room_ids == ("focus",)
    assert repair.operator_id == "primary_daylight_exterior_allocation/v1"
    assert repair.issue_code == "primary_daylight_ratio"
    assert repair.floor_index == 3
    assert repair.subject_id == "floor-3"
    assert repair.room_ids == ("meeting",)
    assert repair.before_value == pytest.approx(0.6625309657157782)
    assert repair.threshold == pytest.approx(0.70)
    assert repair.after_value == pytest.approx(floor_3.primary_daylight_ratio)
    assert any(
        rejection.strategy == "long_edge_adjacent"
        and rejection.reason_type == "BuildingQualityRejected"
        and rejection.quality_report is not None
        and rejection.quality_report.floors[2].primary_daylight_ratio
        == pytest.approx(0.6625309657157782)
        for rejection in composition.rejections
    )
    first, second = composition.alternatives[:2]
    assert compare_building_diversity(
        first.building,
        second.building,
    ).quality_distinct
    mass = _mass()
    analysis = analyze_mass(mass)
    prior_by_floor = {
        floor_index: {
            node.node_id: node
            for node in generate_program_graph(
                analysis,
                floor_index=floor_index,
                use_type="office",
            ).nodes
        }
        for floor_index in range(1, mass.floors + 1)
    }
    for alternative in composition.alternatives:
        for floor in alternative.building.floor_results:
            boundary = Polygon(floor.floor_boundary)
            classified = union_all(
                [
                    Polygon(shape.polygon)
                    for shape in (*floor.layout.rooms, *floor.layout.circulation)
                ]
            ).intersection(boundary)
            unassigned_ratio = boundary.difference(classified).area / boundary.area
            assert floor.validation.coverage_score >= 0.60
            assert unassigned_ratio <= 0.40
            open_work = next(
                room for room in floor.layout.rooms if room.space_type == "open_work"
            )
            work_area = next(
                metric.actual_area
                for metric in floor.validation.room_areas
                if metric.room_id == open_work.room_id
            )
            program_areas = {
                metric.room_id: metric.actual_area
                for metric in floor.validation.room_areas
                if metric.room_id != "core"
            }
            assert work_area == max(program_areas.values())
            prior = prior_by_floor[floor.program.floor_index]
            learned_primary_share = float(prior["open_work"].target_area) / sum(
                float(node.target_area)
                for node in prior.values()
                if node.space_type != "core"
            )
            assert (
                work_area / sum(program_areas.values())
                >= learned_primary_share * 0.75
            )
            for room_id, actual_area in program_areas.items():
                if room_id == "open_work":
                    continue
                original_max = float(prior[room_id].max_area)
                cell_tolerance = max(10.0, original_max * 0.10)
                assert actual_area <= original_max + cell_tolerance
            features = floor.layout.basic_design
            assert features is not None
            workpoints = sum(
                element.kind == "workstation"
                and element.host_id == open_work.room_id
                for element in features.elements
            )
            assert math.ceil(work_area / 10.0) <= workpoints <= math.floor(
                work_area / 8.0
            )


def _repair_evidence(*, after_value: float = 0.75) -> GeneratorRepairProvenance:
    return GeneratorRepairProvenance(
        operator_id="primary_daylight_exterior_allocation/v1",
        issue_code="primary_daylight_ratio",
        policy_version="building-quality/v1",
        floor_index=3,
        subject_id="floor-3",
        room_ids=("meeting",),
        before_value=0.6625309657157782,
        threshold=0.7,
        after_value=after_value,
    )


def test_generator_repair_provenance_is_typed_and_immutable() -> None:
    evidence = _repair_evidence()

    assert evidence.room_ids == ("meeting",)
    with pytest.raises(ValueError, match="operator_id"):
        replace(evidence, operator_id="fixture-repair")
    with pytest.raises(ValueError, match="room_ids"):
        replace(evidence, room_ids=("meeting", "focus"))
    with pytest.raises(ValueError, match="before_value"):
        replace(evidence, before_value=math.nan)


@pytest.mark.parametrize("outcome", ["evaluated", "validation_rejected"])
@pytest.mark.parametrize(
    "after_primary_daylight",
    [
        ((1, 0.75),),
        ((1, 0.75), (2, 0.80), (3, 0.85)),
    ],
)
def test_generator_repair_attempt_requires_exact_requested_floor_evidence(
    outcome: str,
    after_primary_daylight: tuple[tuple[int, float], ...],
) -> None:
    requests = (
        ExteriorAllocationRequest(1, ("focus",)),
        ExteriorAllocationRequest(2, ("meeting",)),
    )

    with pytest.raises(
        ValueError,
        match="after evidence must cover requested floors",
    ):
        GeneratorRepairAttempt(
            operator_id="primary_daylight_exterior_allocation/v1",
            requests=requests,
            outcome=outcome,
            after_primary_daylight=after_primary_daylight,
            validation_codes=(
                ("coverage_below_minimum",)
                if outcome == "validation_rejected"
                else ()
            ),
            error_type=None,
            error_message=None,
        )


@pytest.mark.parametrize(
    "validation_codes",
    [
        (),
        ("z_code", "a_code"),
        ("coverage_below_minimum", "coverage_below_minimum"),
    ],
)
def test_validation_rejected_attempt_requires_deterministic_validation_codes(
    validation_codes: tuple[str, ...],
) -> None:
    request = ExteriorAllocationRequest(1, ("focus",))

    with pytest.raises(
        ValueError,
        match="validation codes",
    ):
        GeneratorRepairAttempt(
            operator_id="primary_daylight_exterior_allocation/v1",
            requests=(request,),
            outcome="validation_rejected",
            after_primary_daylight=((1, 0.75),),
            validation_codes=validation_codes,
            error_type=None,
            error_message=None,
        )


@pytest.mark.parametrize(
    ("outcome", "after_primary_daylight", "validation_codes"),
    [
        ("generation_failed", ((1, 0.75),), ()),
        ("generation_failed", (), ("coverage_below_minimum",)),
        ("evaluated", ((1, 0.75),), ("coverage_below_minimum",)),
    ],
)
def test_generator_repair_attempt_rejects_evidence_for_wrong_outcome(
    outcome: str,
    after_primary_daylight: tuple[tuple[int, float], ...],
    validation_codes: tuple[str, ...],
) -> None:
    request = ExteriorAllocationRequest(1, ("focus",))

    with pytest.raises(ValueError):
        GeneratorRepairAttempt(
            operator_id="primary_daylight_exterior_allocation/v1",
            requests=(request,),
            outcome=outcome,
            after_primary_daylight=after_primary_daylight,
            validation_codes=validation_codes,
            error_type="ValueError" if outcome == "generation_failed" else None,
            error_message=(
                "generation failed" if outcome == "generation_failed" else None
            ),
        )


def _rejection_repair(
    *,
    floor_index: int = 1,
    subject_id: str = "open_work",
    room_ids: tuple[str, ...] = ("meeting",),
    before_value: float = 0.69,
    threshold: float = 0.70,
    after_value: float = 0.75,
) -> GeneratorRepairProvenance:
    return GeneratorRepairProvenance(
        operator_id="primary_daylight_exterior_allocation/v1",
        issue_code="primary_daylight_ratio",
        policy_version="building-quality/v1",
        floor_index=floor_index,
        subject_id=subject_id,
        room_ids=room_ids,
        before_value=before_value,
        threshold=threshold,
        after_value=after_value,
    )


def _rejection_attempt(
    outcome: str,
    *,
    room_ids: tuple[str, ...] = ("meeting",),
    after_value: float = 0.75,
) -> GeneratorRepairAttempt:
    return GeneratorRepairAttempt(
        operator_id="primary_daylight_exterior_allocation/v1",
        requests=(ExteriorAllocationRequest(1, room_ids),),
        outcome=outcome,
        after_primary_daylight=(
            () if outcome == "generation_failed" else ((1, after_value),)
        ),
        validation_codes=(
            ("coverage_below_minimum",)
            if outcome == "validation_rejected"
            else ()
        ),
        error_type="ValueError" if outcome == "generation_failed" else None,
        error_message="generation failed" if outcome == "generation_failed" else None,
    )


@pytest.mark.parametrize(
    ("outcome", "reason_type"),
    [
        ("generation_failed", "BuildingQualityRejected"),
        ("validation_rejected", "BuildingQualityRejected"),
        ("evaluated", "GeneratorRepairFailed"),
        ("evaluated", "BuildingValidationRetryRejected"),
    ],
)
def test_repair_attempt_outcome_requires_matching_rejection_reason(
    outcome: str,
    reason_type: str,
) -> None:
    with pytest.raises(ValueError, match="outcome.*reason|reason.*outcome"):
        StructuralAlternativeRejection(
            strategy="test",
            reason_type=reason_type,
            reason="contradictory repair rejection",
            quality_report=_quality_report(hard_pass=False),
            generator_repairs=(
                (_rejection_repair(),) if outcome == "evaluated" else ()
            ),
            generator_repair_attempt=_rejection_attempt(outcome),
        )


@pytest.mark.parametrize(
    "reason_type",
    ["GeneratorRepairFailed"],
)
def test_generation_failed_attempt_cannot_carry_repair_provenance(
    reason_type: str,
) -> None:
    with pytest.raises(ValueError, match="cannot have generator repairs"):
        StructuralAlternativeRejection(
            strategy="test",
            reason_type=reason_type,
            reason="unevaluated repair rejection",
            quality_report=_quality_report(hard_pass=False),
            generator_repairs=(_rejection_repair(),),
            generator_repair_attempt=_rejection_attempt("generation_failed"),
        )


@pytest.mark.parametrize(
    "repairs",
    [
        (),
        (_rejection_repair(after_value=0.76),),
        (_rejection_repair(room_ids=("focus",)),),
        (_rejection_repair(floor_index=2),),
        (_rejection_repair(subject_id="floor-1"),),
        (_rejection_repair(before_value=0.68),),
        (_rejection_repair(threshold=0.71),),
    ],
)
def test_validation_rejection_requires_lossless_matching_provenance(
    repairs: tuple[GeneratorRepairProvenance, ...],
) -> None:
    original = _quality_report(
        hard_pass=False,
        hard_issue=("primary_daylight_ratio", 0.69, 0.70),
    )

    with pytest.raises(ValueError, match="validation.*repair|repair.*validation"):
        StructuralAlternativeRejection(
            strategy="test",
            reason_type="BuildingValidationRetryRejected",
            reason="inconsistent validation rejection",
            quality_report=original,
            generator_repairs=repairs,
            generator_repair_attempt=_rejection_attempt("validation_rejected"),
        )


def test_validation_rejection_requires_original_structured_hard_issue() -> None:
    with pytest.raises(ValueError, match="structured hard issue"):
        StructuralAlternativeRejection(
            strategy="test",
            reason_type="BuildingValidationRetryRejected",
            reason="missing original issue",
            quality_report=_quality_report(hard_pass=False),
            generator_repairs=(_rejection_repair(),),
            generator_repair_attempt=_rejection_attempt("validation_rejected"),
        )


@pytest.mark.parametrize(
    ("repairs", "attempt"),
    [
        ((), _rejection_attempt("evaluated")),
        (
            (_rejection_repair(after_value=0.76),),
            _rejection_attempt("evaluated", after_value=0.75),
        ),
        (
            (_rejection_repair(room_ids=("focus",)),),
            _rejection_attempt("evaluated", room_ids=("meeting",)),
        ),
        (
            (_rejection_repair(floor_index=2),),
            _rejection_attempt("evaluated"),
        ),
        ((_rejection_repair(),), None),
    ],
)
def test_evaluated_rejection_requires_exact_request_and_repair_evidence(
    repairs: tuple[GeneratorRepairProvenance, ...],
    attempt: GeneratorRepairAttempt | None,
) -> None:
    with pytest.raises(ValueError, match="repair.*attempt|attempt.*repair"):
        StructuralAlternativeRejection(
            strategy="test",
            reason_type="BuildingQualityRejected",
            reason="inconsistent evaluated rejection",
            quality_report=_quality_report(hard_pass=False),
            generator_repairs=repairs,
            generator_repair_attempt=attempt,
        )


def test_repair_rejection_truth_table_accepts_coherent_combinations() -> None:
    report = _quality_report(
        hard_pass=False,
        hard_issue=("primary_daylight_ratio", 0.69, 0.70),
    )
    evaluated = StructuralAlternativeRejection(
        strategy="evaluated",
        reason_type="BuildingQualityRejected",
        reason="post-evaluation quality rejection",
        quality_report=report,
        generator_repairs=(_rejection_repair(after_value=0.8),),
        generator_repair_attempt=_rejection_attempt("evaluated", after_value=0.8),
    )
    validation = StructuralAlternativeRejection(
        strategy="validation",
        reason_type="BuildingValidationRetryRejected",
        reason="validation rejection",
        quality_report=report,
        generator_repairs=(_rejection_repair(),),
        generator_repair_attempt=_rejection_attempt("validation_rejected"),
    )
    generation = StructuralAlternativeRejection(
        strategy="generation",
        reason_type="GeneratorRepairFailed",
        reason="generation failure",
        quality_report=report,
        generator_repair_attempt=_rejection_attempt("generation_failed"),
    )
    legacy = StructuralAlternativeRejection(
        strategy="legacy",
        reason_type="BuildingQualityRejected",
        reason="legacy quality rejection",
        quality_report=report,
    )

    assert evaluated.generator_repairs
    assert validation.generator_repairs
    assert generation.generator_repairs == ()
    assert legacy.generator_repair_attempt is None


def test_daylight_feedback_uses_issue_code_not_reason_or_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    building = SimpleNamespace(floor_results=())
    misleading = replace(
        _quality_report(
            hard_pass=False,
            hard_issue=("room_form_pass_ratio", 0.69, 0.70),
        ),
        issues=(
            QualityIssue(
                code="room_form_pass_ratio",
                severity="hard",
                floor_index=1,
                subject_id="floor-1",
                measured_value=0.69,
                threshold=0.70,
                message="primary_daylight_ratio should appear only as prose",
            ),
        ),
    )
    called = False

    def forbidden(_floor):
        nonlocal called
        called = True
        raise AssertionError("daylight measurement must not run")

    monkeypatch.setattr(alternative_service, "measure_primary_daylight", forbidden)

    assert alternative_service._primary_daylight_requests(
        building,
        misleading,
    ) == ()
    assert called is False


def test_primary_daylight_request_uses_typed_unserved_room_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    building = SimpleNamespace(
        floor_results=(
            SimpleNamespace(
                program=SimpleNamespace(floor_index=1),
                validation=SimpleNamespace(
                    room_areas=(
                        SimpleNamespace(room_id="open_work", actual_area=69.0),
                        SimpleNamespace(room_id="focus", actual_area=10.0),
                        SimpleNamespace(room_id="meeting", actual_area=21.0),
                    ),
                ),
            ),
        ),
    )
    report = _quality_report(
        hard_pass=False,
        hard_issue=("primary_daylight_ratio", 0.69, 0.70),
    )
    report = replace(
        report,
        issues=(
            replace(
                report.issues[0],
                floor_index=1,
                subject_id="floor-1",
            ),
        ),
    )
    monkeypatch.setattr(
        alternative_service,
        "measure_primary_daylight",
        lambda _floor: PrimaryDaylightMeasurement(
            total_primary_area=100.0,
            served_primary_area=69.0,
            ratio=0.69,
            served_room_ids=("open_work",),
            unserved_room_ids=("focus", "meeting"),
        ),
    )

    request, = alternative_service._primary_daylight_requests(building, report)

    assert request == ExteriorAllocationRequest(
        floor_index=1,
        room_ids=("meeting",),
    )


@pytest.mark.parametrize(
    (
        "served_area",
        "threshold",
        "unserved_areas",
        "expected_room_ids",
    ),
    [
        (
            50.0,
            0.70,
            (("alpha", 15.0), ("beta", 16.0), ("gamma", 19.0)),
            ("beta", "gamma"),
        ),
        (
            80.0,
            0.90,
            (("focus", 10.0), ("meeting", 10.0)),
            ("focus",),
        ),
    ],
    ids=("three-room-minimum-prefix", "equal-area-room-id-tie"),
)
def test_primary_daylight_request_uses_minimum_area_ranked_prefix(
    monkeypatch: pytest.MonkeyPatch,
    served_area: float,
    threshold: float,
    unserved_areas: tuple[tuple[str, float], ...],
    expected_room_ids: tuple[str, ...],
) -> None:
    floor = SimpleNamespace(
        program=SimpleNamespace(floor_index=1),
        validation=SimpleNamespace(
            room_areas=(
                SimpleNamespace(room_id="open_work", actual_area=served_area),
                *(
                    SimpleNamespace(room_id=room_id, actual_area=area)
                    for room_id, area in unserved_areas
                ),
            ),
        ),
    )
    report = _quality_report(
        hard_pass=False,
        hard_issue=(
            "primary_daylight_ratio",
            served_area / 100.0,
            threshold,
        ),
    )
    report = replace(
        report,
        issues=(
            replace(
                report.issues[0],
                floor_index=1,
                subject_id="floor-1",
            ),
        ),
    )
    monkeypatch.setattr(
        alternative_service,
        "measure_primary_daylight",
        lambda _floor: PrimaryDaylightMeasurement(
            total_primary_area=100.0,
            served_primary_area=served_area,
            ratio=served_area / 100.0,
            served_room_ids=("open_work",),
            unserved_room_ids=tuple(
                sorted(room_id for room_id, _ in unserved_areas)
            ),
        ),
    )

    request, = alternative_service._primary_daylight_requests(
        SimpleNamespace(floor_results=(floor,)),
        report,
    )

    assert request == ExteriorAllocationRequest(
        floor_index=1,
        room_ids=expected_room_ids,
    )


def test_primary_daylight_retry_is_one_shot_and_re_evaluated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _quality_report(
        hard_pass=False,
        hard_issue=("primary_daylight_ratio", 0.69, 0.70),
    )
    after = _quality_report(hard_pass=True, score=0.81)
    building = SimpleNamespace(accepted=True)
    calls = []

    monkeypatch.setattr(
        alternative_service,
        "_primary_daylight_requests",
        lambda _building, _report: (
            ExteriorAllocationRequest(1, ("meeting",)),
        ),
    )
    monkeypatch.setattr(
        alternative_service,
        "run_building_generation",
        lambda *_args, **kwargs: calls.append(kwargs) or building,
    )
    monkeypatch.setattr(
        alternative_service,
        "evaluate_building_quality",
        lambda _building: after,
    )

    repaired = alternative_service._evaluate_with_primary_daylight_retry(
        _mass(),
        assignments=(),
        programs={},
        core=object(),
        circulation={},
        building=building,
        quality_report=before,
    )

    assert repaired is not None
    assert len(calls) == 1
    assert calls[0]["exterior_allocation_requests"] == (
        ExteriorAllocationRequest(1, ("meeting",)),
    )


def test_invalid_daylight_retry_keeps_lossless_after_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _quality_report(
        hard_pass=False,
        hard_issue=("primary_daylight_ratio", 0.69, 0.70),
    )
    before = replace(
        before,
        issues=(
            replace(
                before.issues[0],
                subject_id="floor-1",
            ),
        ),
    )
    floor = SimpleNamespace(
        program=SimpleNamespace(floor_index=1),
        layout=SimpleNamespace(rooms=()),
        validation=SimpleNamespace(
            violations=(SimpleNamespace(code="coverage_below_minimum"),),
        ),
    )
    invalid = SimpleNamespace(
        accepted=False,
        floor_results=(floor,),
    )
    request = ExteriorAllocationRequest(1, ("meeting",))
    monkeypatch.setattr(
        alternative_service,
        "_primary_daylight_requests",
        lambda _building, _report: (request,),
    )
    monkeypatch.setattr(
        alternative_service,
        "run_building_generation",
        lambda *_args, **_kwargs: invalid,
    )
    monkeypatch.setattr(
        alternative_service,
        "measure_primary_daylight",
        lambda _floor: PrimaryDaylightMeasurement(
            total_primary_area=100.0,
            served_primary_area=75.0,
            ratio=0.75,
            served_room_ids=("focus", "open_work"),
            unserved_room_ids=("meeting",),
        ),
    )

    retry = alternative_service._evaluate_with_primary_daylight_retry(
        _mass(),
        assignments=(),
        programs={},
        core=object(),
        circulation={},
        building=SimpleNamespace(),
        quality_report=before,
    )
    rejection = alternative_service._primary_daylight_retry_rejection(
        strategy="long_edge_adjacent",
        variant="legacy",
        original_quality_report=before,
        retry=retry,
    )

    assert rejection.reason_type == "BuildingValidationRetryRejected"
    assert rejection.reason == (
        "legacy primary_daylight_retry: coverage_below_minimum"
    )
    repair, = rejection.generator_repairs
    assert repair.issue_code == "primary_daylight_ratio"
    assert repair.policy_version == before.policy_version
    assert repair.floor_index == 1
    assert repair.subject_id == "floor-1"
    assert repair.room_ids == ("meeting",)
    assert repair.before_value == pytest.approx(0.69)
    assert repair.threshold == pytest.approx(0.70)
    assert repair.after_value == pytest.approx(0.75)
    assert rejection.generator_repair_attempt == GeneratorRepairAttempt(
        operator_id="primary_daylight_exterior_allocation/v1",
        requests=(request,),
        outcome="validation_rejected",
        after_primary_daylight=((1, 0.75),),
        validation_codes=("coverage_below_minimum",),
        error_type=None,
        error_message=None,
    )


def test_daylight_generation_error_keeps_structured_attempt_without_fake_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _quality_report(
        hard_pass=False,
        hard_issue=("primary_daylight_ratio", 0.69, 0.70),
    )
    request = ExteriorAllocationRequest(1, ("meeting",))
    monkeypatch.setattr(
        alternative_service,
        "_primary_daylight_requests",
        lambda _building, _report: (request,),
    )

    def fail_generation(*_args, **_kwargs):
        raise ValueError("cannot split requested exterior seed")

    monkeypatch.setattr(
        alternative_service,
        "run_building_generation",
        fail_generation,
    )

    retry = alternative_service._evaluate_with_primary_daylight_retry(
        _mass(),
        assignments=(),
        programs={},
        core=object(),
        circulation={},
        building=SimpleNamespace(),
        quality_report=before,
    )
    rejection = alternative_service._primary_daylight_retry_rejection(
        strategy="long_edge_adjacent",
        variant="legacy",
        original_quality_report=before,
        retry=retry,
    )

    assert rejection.reason_type == "GeneratorRepairFailed"
    assert rejection.reason == (
        "legacy primary_daylight_retry: ValueError: "
        "cannot split requested exterior seed"
    )
    assert rejection.generator_repairs == ()
    assert rejection.generator_repair_attempt == GeneratorRepairAttempt(
        operator_id="primary_daylight_exterior_allocation/v1",
        requests=(request,),
        outcome="generation_failed",
        after_primary_daylight=(),
        validation_codes=(),
        error_type="ValueError",
        error_message="cannot split requested exterior seed",
    )


def test_composition_keeps_one_result_per_core_and_typed_rejections() -> None:
    composition = _composition()

    assert {item.strategy for item in composition.alternatives} == {
        "long_edge_adjacent",
        "notch_adjacent",
    }
    assert len({item.strategy for item in composition.alternatives}) == len(
        composition.alternatives
    )
    assert composition.rejections
    assert all(
        isinstance(item, StructuralAlternativeRejection) and item.reason_type and item.reason
        for item in composition.rejections
    )
    assert any(item.strategy == "central" for item in composition.rejections)
    assert any(
        item.strategy == "long_edge_adjacent"
        and item.reason_type == "BuildingQualityRejected"
        and "primary_daylight_ratio" in item.reason
        for item in composition.rejections
    )


def test_composer_rejects_building_quality_hard_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing = _quality_report(
        hard_pass=False,
        hard_issue=("primary_daylight_ratio", 0.69, 0.70),
    )
    monkeypatch.setattr(
        alternative_service,
        "evaluate_building_quality",
        lambda building: failing,
    )

    composition = compose_structural_alternatives(_mass(), limit=3)

    assert not composition.alternatives
    assert any(
        rejection.reason_type == "BuildingQualityRejected"
        and "primary_daylight_ratio" in rejection.reason
        for rejection in composition.rejections
    )


def test_composer_ranks_quality_before_structural_tie_breaker() -> None:
    original = _lightweight_alternative("rank")
    lower = replace(original, quality_report=_quality_report(score=0.71))
    higher = replace(original, quality_report=_quality_report(score=0.88))

    assert sorted((lower, higher), key=alternative_service._rank_key) == [
        higher,
        lower,
    ]


def test_composer_keeps_only_pairwise_quality_distinct_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        alternative_service,
        "evaluate_building_quality",
        lambda building: _quality_report(),
    )
    monkeypatch.setattr(
        alternative_service,
        "compare_building_diversity",
        _controlled_diversity,
    )

    composition = compose_structural_alternatives(_mass(), limit=3)

    assert len(composition.alternatives) == 2
    assert all(item.quality_report.hard_pass for item in composition.alternatives)


def test_select_quality_distinct_alternatives_rejects_non_distinct_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _lightweight_alternative("first", score=0.9)
    second = _lightweight_alternative("second", score=0.8)
    monkeypatch.setattr(
        alternative_service,
        "compare_building_diversity",
        lambda first, second: _diversity_report(total_distance=0.0, quality_distinct=False),
    )

    selected, rejections = alternative_service._select_quality_distinct_alternatives(
        (second, first),
        limit=3,
    )

    assert selected == (first,)
    assert len(rejections) == 1
    assert rejections[0].strategy == "second"
    assert rejections[0].reason_type == "AlternativeDiversityRejected"
    assert first.structural_fingerprint in rejections[0].reason


def test_select_quality_distinct_alternatives_uses_max_min_and_fingerprint_tie_breaker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _lightweight_alternative("first", score=0.9)
    second = _lightweight_alternative("second", score=0.8)
    third = _lightweight_alternative("third", score=0.7)
    fourth = _lightweight_alternative("fourth", score=0.6)
    distances = {
        frozenset(("first", "second")): 0.4,
        frozenset(("first", "third")): 0.8,
        frozenset(("first", "fourth")): 0.8,
        frozenset(("second", "third")): 0.4,
        frozenset(("second", "fourth")): 0.4,
        frozenset(("third", "fourth")): 0.9,
    }
    calls: list[frozenset[str]] = []

    def compare(
        first: BuildingGenerationResult,
        second: BuildingGenerationResult,
    ) -> AlternativeDiversityReport:
        pair = frozenset((first.marker, second.marker))
        calls.append(pair)
        return _diversity_report(total_distance=distances[pair], quality_distinct=True)

    monkeypatch.setattr(alternative_service, "compare_building_diversity", compare)

    selected, rejections = alternative_service._select_quality_distinct_alternatives(
        (fourth, second, third, first),
        limit=3,
    )

    tie_winner, remaining = sorted(
        (third, fourth),
        key=lambda alternative: alternative.structural_fingerprint,
    )
    assert selected == (first, tie_winner, remaining)
    assert not rejections
    assert set(calls) == {
        frozenset(("first", "second")),
        frozenset(("first", "third")),
        frozenset(("first", "fourth")),
        frozenset(("second", tie_winner.strategy)),
        frozenset((tie_winner.strategy, remaining.strategy)),
    }


def test_cached_diversity_comparison_reuses_symmetric_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _lightweight_alternative("first")
    second = _lightweight_alternative("second")
    calls = 0

    def compare(
        first: BuildingGenerationResult,
        second: BuildingGenerationResult,
    ) -> AlternativeDiversityReport:
        nonlocal calls
        calls += 1
        return _diversity_report(total_distance=0.5, quality_distinct=True)

    monkeypatch.setattr(alternative_service, "compare_building_diversity", compare)
    cache = {}

    assert alternative_service._cached_diversity_comparison(first, second, cache) is (
        alternative_service._cached_diversity_comparison(second, first, cache)
    )
    assert calls == 1


def test_quality_rejection_reason_sorts_hard_issue_evidence() -> None:
    report = _quality_report(
        hard_pass=False,
        hard_issues=(
            ("zoning_ratio", 0.9, 1.0),
            ("daylight_ratio", 0.1, 0.2),
        ),
    )

    assert alternative_service._quality_rejection_reason(report) == (
        "daylight_ratio:0.1/0.2, zoning_ratio:0.9/1"
    )


def test_structural_alternative_requires_hard_passing_quality_report() -> None:
    alternative = _lightweight_alternative("contract")

    with pytest.raises(TypeError, match="quality report"):
        replace(alternative, quality_report=object())
    with pytest.raises(ValueError, match="hard-pass"):
        replace(alternative, quality_report=_quality_report(hard_pass=False))


def test_room_label_swap_does_not_create_structural_family() -> None:
    original = _alternatives()[0]
    first_floor = original.building.floor_results[0]
    first, second, *remaining = first_floor.layout.rooms
    swapped_layout = replace(
        first_floor.layout,
        rooms=(
            replace(first, room_id=second.room_id),
            replace(second, room_id=first.room_id),
            *remaining,
        ),
    )
    label_swap_building = replace(
        original.building,
        floor_results=(
            replace(first_floor, layout=swapped_layout),
            *original.building.floor_results[1:],
        ),
    )
    label_swap = replace(
        original,
        building=label_swap_building,
        room_fingerprint=room_structural_fingerprint(label_swap_building),
    )

    assert label_swap.room_fingerprint == original.room_fingerprint
    assert deduplicate_structural_alternatives((original, label_swap)) == (original,)


def test_building_generation_uses_exact_floor_circulation_overrides() -> None:
    mass = _mass()
    core, circulation = _first_override_family()

    building = run_building_generation(
        mass,
        core_override=core,
        circulation_overrides=circulation,
    )

    assert building.vertical_core_aligned
    for floor in building.floor_results:
        expected = circulation[floor.program.floor_index]
        core_room = next(
            room for room in floor.layout.rooms if room.space_type == "core"
        )
        assert core_room.polygon == core.polygon
        assert tuple(tuple(path.polygon) for path in floor.layout.circulation) == (
            expected.polygons
        )
        assert floor.layout.remote_stair_footprint == expected.remote_stair_polygon
        assert floor.floor_boundary == mass.footprint_for_floor(
            floor.program.floor_index
        )


def test_rectangular_building_uses_exact_structural_overrides() -> None:
    mass = _rectangular_mass()
    boundary = mass.footprint_for_floor(1)
    core = generate_shared_core_candidates(
        (boundary,),
        required_area=72.0,
        minimum_width=7.6,
        minimum_depth=5.2,
    )[0]
    circulation = generate_circulation_candidate(
        floor_boundary=boundary,
        core=core,
        street_segments=((boundary[0], boundary[1]),),
        minimum_width=1.2,
        stair_dimensions=((2.8, 4.92), (4.92, 2.8)),
    )

    building = run_building_generation(
        mass,
        core_override=core,
        circulation_overrides={1: circulation},
    )

    layout = building.floor_results[0].layout
    assert next(room.polygon for room in layout.rooms if room.space_type == "core") == (
        core.polygon
    )
    assert tuple(tuple(path.polygon) for path in layout.circulation) == (
        circulation.polygons
    )
    assert layout.remote_stair_footprint == circulation.remote_stair_polygon


def test_rectangular_omitted_structural_overrides_preserve_default() -> None:
    mass = _rectangular_mass()

    default = run_building_generation(mass)
    explicit_none = run_building_generation(
        mass,
        core_override=None,
        circulation_overrides=None,
    )

    assert explicit_none == default


def test_empty_circulation_override_mapping_is_rejected() -> None:
    with pytest.raises(ValueError, match="circulation overrides must not be empty"):
        run_building_generation(
            _rectangular_mass(),
            circulation_overrides={},
        )


def test_structural_override_rejects_missing_core_fingerprint_binding() -> None:
    mass = _mass()
    core, circulation = _first_override_family()
    missing_binding = replace(circulation[1], core_fingerprint=None)

    with pytest.raises(ValueError, match="requires a core fingerprint binding"):
        run_building_generation(
            mass,
            core_override=core,
            circulation_overrides={**circulation, 1: missing_binding},
        )


def test_structural_override_rejects_stale_core_geometry_fingerprint() -> None:
    mass = _mass()
    core, circulation = _first_override_family()
    stale = replace(
        core,
        polygon=tuple((x + 0.01, y) for x, y in core.polygon),
    )

    with pytest.raises(ValueError, match="core override fingerprint"):
        run_building_generation(
            mass,
            core_override=stale,
            circulation_overrides=circulation,
        )


def test_structural_override_rejects_same_strategy_different_core_binding() -> None:
    mass = _mass()
    boundaries = tuple(
        mass.footprint_for_floor(index) for index in range(1, mass.floors + 1)
    )
    first, second, *_ = generate_shared_core_candidates(
        boundaries,
        required_area=72.0,
        minimum_width=7.6,
        minimum_depth=5.2,
    )
    circulation = {
        floor_index: generate_circulation_candidate(
            floor_boundary=boundary,
            core=first,
            street_segments=((boundary[0], boundary[1]),),
            minimum_width=1.2,
            stair_dimensions=((2.8, 4.92), (4.92, 2.8)),
        )
        for floor_index, boundary in enumerate(boundaries, start=1)
    }
    same_strategy_other_core = replace(second, strategy=first.strategy)

    assert core_geometry_fingerprint(same_strategy_other_core.polygon) == (
        same_strategy_other_core.fingerprint
    )
    with pytest.raises(ValueError, match="core fingerprint"):
        run_building_generation(
            mass,
            core_override=same_strategy_other_core,
            circulation_overrides=circulation,
        )


def test_structural_override_rejects_stale_circulation_fingerprint() -> None:
    mass = _mass()
    core, circulation = _first_override_family()
    first = circulation[1]
    polygon = first.polygons[0]
    stale = replace(
        first,
        polygons=(
            (
                (polygon[0][0] + 0.01, polygon[0][1]),
                *polygon[1:],
            ),
            *first.polygons[1:],
        ),
        entrance_connected=True,
        core_connected=True,
        stair_connected=True,
    )

    with pytest.raises(ValueError, match="circulation override fingerprint"):
        run_building_generation(
            mass,
            core_override=core,
            circulation_overrides={**circulation, 1: stale},
        )


def test_structural_override_rejects_resigned_disconnected_geometry() -> None:
    mass = _mass()
    core, circulation = _first_override_family()
    first = circulation[1]
    invalid_stair = core.polygon
    resigned = replace(
        first,
        remote_stair_polygon=invalid_stair,
        fingerprint=circulation_geometry_fingerprint(
            strategy=first.strategy,
            core_fingerprint=first.core_fingerprint,
            polygons=first.polygons,
            remote_stair=invalid_stair,
        ),
        entrance_connected=True,
        core_connected=True,
        stair_connected=True,
    )

    with pytest.raises(ValueError, match="actual connected topology"):
        run_building_generation(
            mass,
            core_override=core,
            circulation_overrides={**circulation, 1: resigned},
        )


@pytest.mark.parametrize(
    ("core_transform", "circulation_transform", "match"),
    [
        (lambda core: object(), lambda values: values, "core override"),
        (
            lambda core: replace(
                core,
                polygon=tuple((x + 100.0, y) for x, y in core.polygon),
            ),
            lambda values: values,
            "fingerprint",
        ),
        (
            lambda core: core,
            lambda values: {1: values[1], 2: values[2]},
            "every floor",
        ),
        (
            lambda core: core,
            lambda values: {
                **values,
                1: replace(values[1], strategy="different-core"),
            },
            "fingerprint",
        ),
        (
            lambda core: core,
            lambda values: {
                **values,
                1: replace(
                    values[1],
                    polygons=(
                        tuple((x + 100.0, y) for x, y in values[1].polygons[0]),
                    ),
                ),
            },
            "fingerprint",
        ),
    ],
)
def test_building_generation_rejects_invalid_structural_overrides(
    core_transform,
    circulation_transform,
    match,
) -> None:
    mass = _mass()
    core, circulation = _first_override_family()

    with pytest.raises((TypeError, ValueError), match=match):
        run_building_generation(
            mass,
            core_override=core_transform(core),
            circulation_overrides=circulation_transform(circulation),
        )


def test_structural_alternative_contract_rejects_mismatched_hash() -> None:
    original = _alternatives()[0]

    with pytest.raises(ValueError, match="structural fingerprint"):
        StructuralAlternative(
            strategy=original.strategy,
            building=original.building,
            quality_report=original.quality_report,
            core_fingerprint=original.core_fingerprint,
            circulation_fingerprint=original.circulation_fingerprint,
            room_fingerprint=original.room_fingerprint,
            structural_fingerprint="0" * 64,
        )


@lru_cache(maxsize=1)
def _first_override_family():
    mass = _mass()
    boundaries = tuple(
        mass.footprint_for_floor(index) for index in range(1, mass.floors + 1)
    )
    core = generate_shared_core_candidates(
        boundaries,
        required_area=72.0,
        minimum_width=7.6,
        minimum_depth=5.2,
    )[0]
    circulation = {
        floor_index: generate_circulation_candidate(
            floor_boundary=boundary,
            core=core,
            street_segments=((boundary[0], boundary[1]),),
            minimum_width=1.2,
            stair_dimensions=((2.8, 4.92), (4.92, 2.8)),
        )
        for floor_index, boundary in enumerate(boundaries, start=1)
    }
    return core, circulation


@lru_cache(maxsize=1)
def _alternatives() -> tuple[StructuralAlternative, ...]:
    return _composition().alternatives


@lru_cache(maxsize=1)
def _composition() -> StructuralComposition:
    return compose_structural_alternatives(_mass(), use_type="office", limit=3)


@lru_cache(maxsize=1)
def _mass() -> MassInput:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return MassInput(
        project_id=manifest["project_id"],
        floors=manifest["floors"],
        footprint_polygon=manifest["footprint_polygon"],
        floor_footprints=tuple(
            FloorFootprint(
                floor_index=floor["floor_index"],
                footprint_polygon=tuple(
                    (float(x), float(y)) for x, y in floor["footprint_polygon"]
                ),
            )
            for floor in manifest["floor_footprints"]
        ),
        site_edges=manifest["site_edges"],
        access_candidates=manifest["access_candidates"],
        use_mix=manifest["use_mix"],
    )


@lru_cache(maxsize=1)
def _rectangular_mass() -> MassInput:
    return MassInput(
        project_id="rectangular-structural-override",
        floors=1,
        footprint_polygon=[
            (0.0, 0.0),
            (40.0, 0.0),
            (40.0, 20.0),
            (0.0, 20.0),
        ],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
    )


def _quality_report(
    *,
    hard_pass: bool = True,
    score: float = 0.8,
    hard_issue: tuple[str, float, float] | None = None,
    hard_issues: tuple[tuple[str, float, float], ...] = (),
) -> BuildingQualityReport:
    issue_values = (
        *hard_issues,
        *((hard_issue,) if hard_issue is not None else ()),
    )
    issues = tuple(
        QualityIssue(
            code=code,
            severity="hard",
            floor_index=1,
            subject_id="open_work",
            measured_value=measured_value,
            threshold=threshold,
            message="quality policy failure",
        )
        for code, measured_value, threshold in issue_values
    )
    return BuildingQualityReport(
        policy_version="building-quality/v1",
        hard_pass=hard_pass,
        score=score,
        component_scores={"daylight": score},
        floors=(
            FloorQualityMetrics(
                floor_index=1,
                coverage=0.8,
                primary_daylight_ratio=0.8,
                room_form_pass_ratio=0.9,
                worst_aspect_ratio=2.0,
                narrowest_room_width_m=2.4,
                egress_status="pass",
            ),
        ),
        vertical=VerticalQualityMetrics(
            core_stack_ratio=1.0,
            shaft_stack_ratio=1.0,
            wet_service_stack_ratio=0.9,
            maximum_service_centroid_shift_m=0.2,
        ),
        issues=issues,
        unresolved_facts=(),
    )


def _lightweight_alternative(
    strategy: str,
    *,
    score: float = 0.8,
) -> StructuralAlternative:
    building = object.__new__(BuildingGenerationResult)
    object.__setattr__(building, "floor_results", ())
    object.__setattr__(building, "marker", strategy)
    components = tuple(
        hashlib.sha256(f"{strategy}:{label}".encode()).hexdigest()
        for label in ("core", "circulation", "rooms")
    )
    structural_fingerprint = hashlib.sha256(":".join(components).encode()).hexdigest()
    return StructuralAlternative(
        strategy=strategy,
        building=building,
        quality_report=_quality_report(score=score),
        core_fingerprint=components[0],
        circulation_fingerprint=components[1],
        room_fingerprint=components[2],
        structural_fingerprint=structural_fingerprint,
    )


def _diversity_report(
    *,
    total_distance: float,
    quality_distinct: bool,
) -> AlternativeDiversityReport:
    return AlternativeDiversityReport(
        first_fingerprint="first",
        second_fingerprint="second",
        core_distance=total_distance,
        circulation_distance=total_distance,
        topology_distance=total_distance,
        area_distribution_distance=total_distance,
        total_distance=total_distance,
        nonzero_component_count=4 if total_distance else 0,
        quality_distinct=quality_distinct,
    )


def _controlled_diversity(
    first,
    second,
) -> AlternativeDiversityReport:
    return AlternativeDiversityReport(
        first_fingerprint="first",
        second_fingerprint="second",
        core_distance=0.5,
        circulation_distance=0.5,
        topology_distance=0.5,
        area_distribution_distance=0.5,
        total_distance=0.5,
        nonzero_component_count=4,
        quality_distinct=True,
    )
