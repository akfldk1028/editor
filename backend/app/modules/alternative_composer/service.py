from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import combinations

from shapely.geometry import Polygon

from backend.app.modules.alternative_composer.contracts import (
    GeneratorRepairAttempt,
    GeneratorRepairProvenance,
    StructuralAlternative,
    StructuralAlternativeRejection,
)
from backend.app.modules.building_quality import (
    AlternativeDiversityReport,
    BuildingQualityReport,
    PrimaryDaylightMeasurement,
    compare_building_diversity,
    evaluate_building_quality,
    measure_primary_daylight,
)
from backend.app.modules.basic_design.stair import (
    required_stair_enclosure,
    resolve_floor_height,
)
from backend.app.modules.circulation_planner.service import (
    generate_circulation_candidate,
)
from backend.app.modules.circulation_planner.contracts import CirculationCandidate
from backend.app.modules.core_planner.service import generate_shared_core_candidates
from backend.app.modules.core_planner.contracts import CoreCandidate
from backend.app.modules.generation_loop.service import run_building_generation
from backend.app.modules.generation_loop.contracts import ExteriorAllocationRequest
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.schemas.llm import FloorAssignment, SUPPORTED_USE_TYPES
from backend.app.schemas.mass import MassInput
from backend.app.schemas.program import ProgramGraph
from backend.app.schemas.result import BuildingGenerationResult


@dataclass(frozen=True)
class StructuralComposition:
    alternatives: tuple[StructuralAlternative, ...]
    rejections: tuple[StructuralAlternativeRejection, ...]


@dataclass(frozen=True)
class _PrimaryDaylightRetryResult:
    building: BuildingGenerationResult | None
    quality_report: BuildingQualityReport | None
    generator_repairs: tuple[GeneratorRepairProvenance, ...]
    attempt: GeneratorRepairAttempt


def generate_structural_alternatives(
    mass: MassInput,
    *,
    use_type: str = "office",
    limit: int = 3,
) -> tuple[StructuralAlternative, ...]:
    """Compose bounded core/circulation families through building validation."""
    return compose_structural_alternatives(
        mass,
        use_type=use_type,
        limit=limit,
    ).alternatives


def compose_structural_alternatives(
    mass: MassInput,
    *,
    use_type: str | None = "office",
    floor_assignments: Iterable[FloorAssignment] | None = None,
    limit: int = 3,
) -> StructuralComposition:
    """Compose core and circulation families inside the actual floor polygon.

    Pass ``floor_assignments`` to plan a building whose floors differ, or
    ``use_type`` to give every floor the same one.
    """
    if floor_assignments is not None and use_type is not None:
        raise ValueError("supply either floor assignments or a single use type")
    if floor_assignments is None and use_type not in SUPPORTED_USE_TYPES:
        raise ValueError(f"unsupported use_type: {use_type}")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("structural alternative limit must be a positive integer")

    analysis = analyze_mass(mass)
    boundaries = tuple(
        mass.footprint_for_floor(floor_index)
        for floor_index in range(1, mass.floors + 1)
    )
    if floor_assignments is None:
        assignments = tuple(
            FloorAssignment(floor_index, use_type)
            for floor_index in range(1, mass.floors + 1)
        )
    else:
        assignments = tuple(floor_assignments)
        expected = tuple(range(1, mass.floors + 1))
        if tuple(item.floor_index for item in assignments) != expected:
            raise ValueError("floor assignments must cover every floor in order")
        unsupported = sorted(
            {item.use_type for item in assignments} - SUPPORTED_USE_TYPES
        )
        if unsupported:
            raise ValueError(f"unsupported use types: {', '.join(unsupported)}")
    programs = {
        assignment.floor_index: generate_program_graph(
            analysis,
            floor_index=assignment.floor_index,
            use_type=assignment.use_type,
        )
        for assignment in assignments
    }
    requested_core_area = min(
        72.0,
        max(
            float(
                next(
                    node.target_area
                    for node in program.nodes
                    if node.space_type == "core"
                )
            )
            for program in programs.values()
        ),
    )
    cores = generate_shared_core_candidates(
        boundaries,
        required_area=requested_core_area,
        minimum_width=7.6,
        minimum_depth=5.2,
    )
    stair_short_side, stair_long_side = required_stair_enclosure(
        resolve_floor_height(
            (
                mass.building_code_context.floor_to_floor_height_m
                if mass.building_code_context is not None
                else None
            )
        )[0]
    )
    stair_dimensions = (
        (stair_short_side, stair_long_side),
        (stair_long_side, stair_short_side),
    )

    accepted: list[StructuralAlternative] = []
    rejected: list[StructuralAlternativeRejection] = []
    circulation_boundary = min(
        boundaries,
        key=lambda boundary: (Polygon(boundary).area, boundary),
    )
    minimum_exit_separation = max(
        math.dist(first, second) / 2
        for boundary in boundaries
        for first, second in combinations(boundary, 2)
    )
    evaluated_cores: set[str] = set()

    def evaluate(core_candidates) -> None:
        for core in core_candidates:
            if core.fingerprint in evaluated_cores:
                continue
            evaluated_cores.add(core.fingerprint)
            _evaluate_core(
                core,
                mass=mass,
                assignments=assignments,
                programs=programs,
                circulation_boundary=circulation_boundary,
                minimum_exit_separation=minimum_exit_separation,
                stair_dimensions=stair_dimensions,
                accepted=accepted,
                rejected=rejected,
            )

    evaluate(cores)
    if len(deduplicate_structural_alternatives(accepted)) < 2:
        # This plate did not offer two workable cores among the strategy
        # leaders, so take the runners-up each strategy had already ranked
        # rather than leave the mass without a second alternative.
        evaluate(
            generate_shared_core_candidates(
                boundaries,
                required_area=requested_core_area,
                minimum_width=7.6,
                minimum_depth=5.2,
                widen=True,
            )
        )

    alternatives = deduplicate_structural_alternatives(accepted)
    alternatives, diversity_rejections = _select_quality_distinct_alternatives(
        alternatives,
        limit=limit,
    )
    rejected.extend(diversity_rejections)
    return StructuralComposition(
        alternatives,
        tuple(sorted(rejected, key=_rejection_key)),
    )


def _evaluate_core(
    core,
    *,
    mass: MassInput,
    assignments,
    programs,
    circulation_boundary,
    minimum_exit_separation: float,
    stair_dimensions,
    accepted: list[StructuralAlternative],
    rejected: list[StructuralAlternativeRejection],
) -> None:
    core_alternatives: list[StructuralAlternative] = []
    core_rejections: list[StructuralAlternativeRejection] = []
    seen_circulation: set[str] = set()
    for variant, separation in (
        ("legacy", None),
        ("governing_separation", minimum_exit_separation),
    ):
        try:
            shared_circulation = generate_circulation_candidate(
                floor_boundary=circulation_boundary,
                core=core,
                street_segments=_access_segments(mass, circulation_boundary),
                minimum_width=1.2,
                stair_dimensions=stair_dimensions,
                minimum_exit_separation=separation,
            )
            if shared_circulation.fingerprint in seen_circulation:
                continue
            seen_circulation.add(shared_circulation.fingerprint)
            circulation = {
                floor_index: shared_circulation
                for floor_index in range(1, mass.floors + 1)
            }
            building = run_building_generation(
                mass,
                floor_assignments=assignments,
                program_overrides=programs,
                core_override=core,
                circulation_overrides=circulation,
            )
            if not building.accepted:
                core_rejections.append(
                    StructuralAlternativeRejection(
                        strategy=core.strategy,
                        reason_type="BuildingValidationRejected",
                        reason=f"{variant}: {_validation_reason(building)}",
                    )
                )
                continue
            quality_report = evaluate_building_quality(building)
            generator_repairs: tuple[GeneratorRepairProvenance, ...] = ()
            if not quality_report.hard_pass:
                core_rejections.append(
                    StructuralAlternativeRejection(
                        strategy=core.strategy,
                        reason_type="BuildingQualityRejected",
                        reason=(
                            f"{variant}: {_quality_rejection_reason(quality_report)}"
                        ),
                        quality_report=quality_report,
                    )
                )
                repaired = _evaluate_with_primary_daylight_retry(
                    mass,
                    assignments=assignments,
                    programs=programs,
                    core=core,
                    circulation=circulation,
                    building=building,
                    quality_report=quality_report,
                )
                if repaired is None:
                    continue
                retry_rejection = _primary_daylight_retry_rejection(
                    strategy=core.strategy,
                    variant=variant,
                    original_quality_report=quality_report,
                    retry=repaired,
                )
                if retry_rejection is not None:
                    core_rejections.append(retry_rejection)
                    continue
                if repaired.building is None or repaired.quality_report is None:
                    raise ValueError(
                        "successful primary daylight retry evidence is incomplete"
                    )
                building = repaired.building
                quality_report = repaired.quality_report
                generator_repairs = repaired.generator_repairs
            circulation_fingerprint = _circulation_fingerprint(circulation.items())
            room_fingerprint = room_structural_fingerprint(building)
            structural_fingerprint = hashlib.sha256(
                (
                    f"{core.fingerprint}:{circulation_fingerprint}:"
                    f"{room_fingerprint}"
                ).encode()
            ).hexdigest()
            core_alternatives.append(
                StructuralAlternative(
                    strategy=core.strategy,
                    building=building,
                    quality_report=quality_report,
                    core_fingerprint=core.fingerprint,
                    circulation_fingerprint=circulation_fingerprint,
                    room_fingerprint=room_fingerprint,
                    structural_fingerprint=structural_fingerprint,
                    generator_repairs=generator_repairs,
                )
            )
        except (TypeError, ValueError) as error:
            core_rejections.append(
                StructuralAlternativeRejection(
                    strategy=core.strategy,
                    reason_type=type(error).__name__,
                    reason=f"{variant}: {error}",
                )
            )
    if core_alternatives:
        accepted.append(min(core_alternatives, key=_rank_key))
    rejected.extend(core_rejections)


def deduplicate_structural_alternatives(
    alternatives: Iterable[StructuralAlternative],
) -> tuple[StructuralAlternative, ...]:
    unique: list[StructuralAlternative] = []
    seen: set[str] = set()
    for alternative in alternatives:
        if not isinstance(alternative, StructuralAlternative):
            raise TypeError("structural alternatives must be immutable records")
        fingerprint = hashlib.sha256(
            (
                f"{alternative.core_fingerprint}:"
                f"{alternative.circulation_fingerprint}:"
                f"{alternative.room_fingerprint}"
            ).encode()
        ).hexdigest()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(alternative)
    return tuple(unique)


def room_structural_fingerprint(building: BuildingGenerationResult) -> str:
    payload = [
        {
            "floor_index": floor.program.floor_index,
            "room_polygons": sorted(
                _canonical_ring(room.polygon) for room in floor.layout.rooms
            ),
        }
        for floor in building.floor_results
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _circulation_fingerprint(
    circulation: Iterable[tuple[int, CirculationCandidate]],
) -> str:
    payload = [
        [floor_index, candidate.fingerprint]
        for floor_index, candidate in sorted(circulation)
    ]
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":")).encode()
    ).hexdigest()


def _canonical_ring(points) -> tuple[tuple[str, str], ...]:
    ring = tuple((_coordinate(x), _coordinate(y)) for x, y in points)
    variants = []
    for oriented in (ring, tuple(reversed(ring))):
        variants.extend(
            oriented[index:] + oriented[:index] for index in range(len(oriented))
        )
    return min(variants)


def _coordinate(value: float) -> str:
    return format(float(value), ".12g")


def _access_segments(
    mass: MassInput,
    boundary: tuple[tuple[float, float], ...],
) -> tuple[tuple[tuple[float, float], tuple[float, float]], ...]:
    edge_indices = {
        int(record["edge_index"])
        for record in mass.site_edges
        if "edge_index" in record and record.get("kind") == "street"
    }
    edge_indices.update(
        int(record["edge_index"])
        for record in mass.access_candidates
        if "edge_index" in record
    )
    segments = tuple(
        (boundary[index], boundary[(index + 1) % len(boundary)])
        for index in sorted(edge_indices)
        if 0 <= index < len(boundary)
    )
    if not segments:
        raise ValueError("structural alternatives require a street or access edge")
    return segments


def _validation_reason(building: BuildingGenerationResult) -> str:
    reasons = sorted(
        {
            violation.code
            for floor in building.floor_results
            for violation in floor.validation.violations
        }
    )
    return ",".join(reasons) or "building acceptance gates failed"


def _quality_rejection_reason(report: BuildingQualityReport) -> str:
    evidence = tuple(
        sorted(
            (
                f"{issue.code}:{_quality_value(issue.measured_value)}/"
                f"{_quality_value(issue.threshold)}"
                for issue in report.issues
                if issue.severity == "hard"
            )
        )
    )
    return ", ".join(evidence) or "quality hard-pass gate failed"


def _quality_value(value: float | None) -> str:
    return "unknown" if value is None else format(value, ".12g")


def _primary_daylight_requests(
    building: BuildingGenerationResult,
    report: BuildingQualityReport,
) -> tuple[ExteriorAllocationRequest, ...]:
    issues = tuple(
        issue
        for issue in report.issues
        if issue.code == "primary_daylight_ratio" and issue.severity == "hard"
    )
    if not issues:
        return ()

    floors_by_index = {
        floor.program.floor_index: floor for floor in building.floor_results
    }
    issue_floor_indexes = tuple(issue.floor_index for issue in issues)
    if len(set(issue_floor_indexes)) != len(issue_floor_indexes):
        raise ValueError("one primary daylight issue per floor is required")
    requests: list[ExteriorAllocationRequest] = []
    for issue in sorted(issues, key=lambda item: item.floor_index or 0):
        if (
            issue.floor_index is None
            or issue.subject_id is None
            or issue.measured_value is None
            or issue.threshold is None
        ):
            raise ValueError("primary daylight issue requires structured evidence")
        floor = floors_by_index.get(issue.floor_index)
        if floor is None:
            raise ValueError("primary daylight issue floor_index does not match building")
        if issue.subject_id != f"floor-{issue.floor_index}":
            raise ValueError("primary daylight issue subject_id does not match floor")
        measurement: PrimaryDaylightMeasurement = measure_primary_daylight(floor)
        if not math.isclose(
            measurement.ratio,
            issue.measured_value,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "primary daylight issue measured_value does not match measurement"
            )
        room_ids = _minimum_primary_daylight_room_ids(
            floor,
            measurement,
            threshold=issue.threshold,
        )
        requests.append(
            ExteriorAllocationRequest(
                floor_index=issue.floor_index,
                room_ids=room_ids,
            )
        )
    return tuple(requests)


def _minimum_primary_daylight_room_ids(
    floor,
    measurement: PrimaryDaylightMeasurement,
    *,
    threshold: float,
) -> tuple[str, ...]:
    areas_by_room_id = {
        metric.room_id: float(metric.actual_area)
        for metric in floor.validation.room_areas
    }
    missing = sorted(set(measurement.unserved_room_ids) - areas_by_room_id.keys())
    if missing:
        raise ValueError(
            "primary daylight request room area is unavailable: "
            + ", ".join(missing)
        )
    ranked = sorted(
        measurement.unserved_room_ids,
        key=lambda room_id: (-areas_by_room_id[room_id], room_id),
    )
    selected = []
    projected_served_area = measurement.served_primary_area
    required_served_area = measurement.total_primary_area * threshold
    for room_id in ranked:
        selected.append(room_id)
        projected_served_area += areas_by_room_id[room_id]
        if projected_served_area + 1e-12 >= required_served_area:
            break
    if projected_served_area + 1e-12 < required_served_area:
        raise ValueError("primary daylight request cannot reach issue threshold")
    return tuple(sorted(selected))


def _evaluate_with_primary_daylight_retry(
    mass: MassInput,
    *,
    assignments: tuple[FloorAssignment, ...],
    programs: Mapping[int, ProgramGraph],
    core: CoreCandidate,
    circulation: Mapping[int, CirculationCandidate],
    building: BuildingGenerationResult,
    quality_report: BuildingQualityReport,
) -> (
    _PrimaryDaylightRetryResult | None
):
    requests = _primary_daylight_requests(building, quality_report)
    if not requests:
        return None

    try:
        repaired_building = run_building_generation(
            mass,
            floor_assignments=assignments,
            program_overrides=programs,
            core_override=core,
            circulation_overrides=circulation,
            exterior_allocation_requests=requests,
        )
    except Exception as error:
        return _PrimaryDaylightRetryResult(
            building=None,
            quality_report=None,
            generator_repairs=(),
            attempt=GeneratorRepairAttempt(
                operator_id="primary_daylight_exterior_allocation/v1",
                requests=requests,
                outcome="generation_failed",
                after_primary_daylight=(),
                validation_codes=(),
                error_type=type(error).__name__,
                error_message=str(error) or "generation failed without a message",
            ),
        )
    if not repaired_building.accepted:
        after_values = _measure_primary_daylight_after_values(
            repaired_building,
            requests,
        )
        repairs = _generator_repair_provenance(
            quality_report,
            requests,
            after_values=after_values,
            policy_version=quality_report.policy_version,
        )
        return _PrimaryDaylightRetryResult(
            building=repaired_building,
            quality_report=None,
            generator_repairs=repairs,
            attempt=GeneratorRepairAttempt(
                operator_id="primary_daylight_exterior_allocation/v1",
                requests=requests,
                outcome="validation_rejected",
                after_primary_daylight=after_values,
                validation_codes=_validation_codes(repaired_building),
                error_type=None,
                error_message=None,
            ),
        )
    repaired_report = evaluate_building_quality(repaired_building)
    after_values = tuple(
        (
            request.floor_index,
            next(
                floor.primary_daylight_ratio
                for floor in repaired_report.floors
                if floor.floor_index == request.floor_index
            ),
        )
        for request in requests
    )
    repairs = _generator_repair_provenance(
        quality_report,
        requests,
        after_values=after_values,
        policy_version=repaired_report.policy_version,
    )
    if quality_report.policy_version != repaired_report.policy_version:
        raise ValueError("primary daylight repair policy version changed")
    return _PrimaryDaylightRetryResult(
        building=repaired_building,
        quality_report=repaired_report,
        generator_repairs=repairs,
        attempt=GeneratorRepairAttempt(
            operator_id="primary_daylight_exterior_allocation/v1",
            requests=requests,
            outcome="evaluated",
            after_primary_daylight=after_values,
            validation_codes=(),
            error_type=None,
            error_message=None,
        ),
    )


def _measure_primary_daylight_after_values(
    building: BuildingGenerationResult,
    requests: tuple[ExteriorAllocationRequest, ...],
) -> tuple[tuple[int, float], ...]:
    floors_by_index = {
        floor.program.floor_index: floor for floor in building.floor_results
    }
    values = []
    for request in requests:
        floor = floors_by_index.get(request.floor_index)
        if floor is None or getattr(floor, "layout", None) is None:
            raise ValueError(
                "primary daylight retry floor layout evidence is unavailable"
            )
        values.append(
            (
                request.floor_index,
                measure_primary_daylight(floor).ratio,
            )
        )
    return tuple(values)


def _generator_repair_provenance(
    quality_report: BuildingQualityReport,
    requests: tuple[ExteriorAllocationRequest, ...],
    *,
    after_values: tuple[tuple[int, float], ...],
    policy_version: str,
) -> tuple[GeneratorRepairProvenance, ...]:
    issues_by_floor = {
        issue.floor_index: issue
        for issue in quality_report.issues
        if issue.code == "primary_daylight_ratio" and issue.severity == "hard"
    }
    after_by_floor = dict(after_values)
    repairs = []
    for request in requests:
        issue = issues_by_floor.get(request.floor_index)
        after_value = after_by_floor.get(request.floor_index)
        if issue is None or after_value is None:
            raise ValueError("primary daylight repair evidence is inconsistent")
        if (
            issue.subject_id is None
            or issue.measured_value is None
            or issue.threshold is None
        ):
            raise ValueError("primary daylight repair requires structured evidence")
        repairs.append(
            GeneratorRepairProvenance(
                operator_id="primary_daylight_exterior_allocation/v1",
                issue_code=issue.code,
                policy_version=policy_version,
                floor_index=request.floor_index,
                subject_id=issue.subject_id,
                room_ids=request.room_ids,
                before_value=issue.measured_value,
                threshold=issue.threshold,
                after_value=after_value,
            )
        )
    return tuple(repairs)


def _validation_codes(building: BuildingGenerationResult) -> tuple[str, ...]:
    codes = {
        violation.code
        for floor in building.floor_results
        for violation in floor.validation.violations
    }
    for field_name, code in (
        ("vertical_core_aligned", "vertical_core_alignment_failed"),
        ("vertical_basic_design_aligned", "vertical_basic_design_alignment_failed"),
        ("vertical_structure_aligned", "vertical_structure_alignment_failed"),
    ):
        if getattr(building, field_name, True) is False:
            codes.add(code)
    return tuple(sorted(codes)) or ("building_acceptance_gate_failed",)


def _primary_daylight_retry_rejection(
    *,
    strategy: str,
    variant: str,
    original_quality_report: BuildingQualityReport,
    retry: _PrimaryDaylightRetryResult | None,
) -> StructuralAlternativeRejection | None:
    if retry is None:
        return None
    if retry.attempt.outcome == "generation_failed":
        return StructuralAlternativeRejection(
            strategy=strategy,
            reason_type="GeneratorRepairFailed",
            reason=(
                f"{variant} primary_daylight_retry: "
                f"{retry.attempt.error_type}: {retry.attempt.error_message}"
            ),
            quality_report=original_quality_report,
            generator_repair_attempt=retry.attempt,
        )
    if retry.attempt.outcome == "validation_rejected":
        return StructuralAlternativeRejection(
            strategy=strategy,
            reason_type="BuildingValidationRetryRejected",
            reason=(
                f"{variant} primary_daylight_retry: "
                f"{','.join(retry.attempt.validation_codes)}"
            ),
            quality_report=original_quality_report,
            generator_repairs=retry.generator_repairs,
            generator_repair_attempt=retry.attempt,
        )
    if retry.quality_report is None:
        raise ValueError("evaluated primary daylight retry requires a quality report")
    if retry.quality_report.hard_pass:
        return None
    return StructuralAlternativeRejection(
        strategy=strategy,
        reason_type="BuildingQualityRejected",
        reason=(
            f"{variant} primary_daylight_retry: "
            f"{_quality_rejection_reason(retry.quality_report)}"
        ),
        quality_report=retry.quality_report,
        generator_repairs=retry.generator_repairs,
        generator_repair_attempt=retry.attempt,
    )


def _select_quality_distinct_alternatives(
    alternatives: Iterable[StructuralAlternative],
    *,
    limit: int,
) -> tuple[
    tuple[StructuralAlternative, ...],
    tuple[StructuralAlternativeRejection, ...],
]:
    pending = list(sorted(alternatives, key=_rank_key))
    if not pending:
        return (), ()

    selected = [pending.pop(0)]
    rejections: list[StructuralAlternativeRejection] = []
    diversity_cache = {}
    while pending and len(selected) < limit:
        distinct: list[tuple[StructuralAlternative, float]] = []
        for candidate in pending:
            comparisons = tuple(
                _cached_diversity_comparison(
                    candidate,
                    prior,
                    diversity_cache,
                )
                for prior in selected
            )
            if all(comparison.quality_distinct for comparison in comparisons):
                distinct.append(
                    (
                        candidate,
                        min(comparison.total_distance for comparison in comparisons),
                    )
                )
                continue
            rejections.append(
                StructuralAlternativeRejection(
                    strategy=candidate.strategy,
                    reason_type="AlternativeDiversityRejected",
                    reason=_diversity_rejection_reason(
                        candidate, selected, comparisons
                    ),
                )
            )
        pending = [candidate for candidate, _ in distinct]
        if not distinct:
            break
        next_candidate, _ = min(
            distinct,
            key=lambda item: (-item[1], item[0].structural_fingerprint),
        )
        selected.append(next_candidate)
        pending.remove(next_candidate)

    return tuple(selected), tuple(rejections)


def _cached_diversity_comparison(
    first: StructuralAlternative,
    second: StructuralAlternative,
    cache: dict[tuple[str, str], AlternativeDiversityReport],
) -> AlternativeDiversityReport:
    key = tuple(sorted((first.structural_fingerprint, second.structural_fingerprint)))
    if key not in cache:
        cache[key] = compare_building_diversity(first.building, second.building)
    return cache[key]


def _diversity_rejection_reason(
    candidate: StructuralAlternative,
    selected: Iterable[StructuralAlternative],
    comparisons,
) -> str:
    evidence = tuple(
        sorted(
            (
                f"{prior.structural_fingerprint}:{comparison.total_distance:.12g}"
                for prior, comparison in zip(selected, comparisons, strict=True)
                if not comparison.quality_distinct
            )
        )
    )
    return (
        f"{candidate.structural_fingerprint} is not quality-distinct from "
        f"{', '.join(evidence)}"
    )


def _rejection_key(
    rejection: StructuralAlternativeRejection,
) -> tuple[str, str, str]:
    return rejection.strategy, rejection.reason_type, rejection.reason


def _rank_key(
    alternative: StructuralAlternative,
) -> tuple[float, float, str]:
    validations = [floor.validation for floor in alternative.building.floor_results]
    return (
        -alternative.quality_report.score,
        -sum(report.total_score for report in validations),
        alternative.structural_fingerprint,
    )
