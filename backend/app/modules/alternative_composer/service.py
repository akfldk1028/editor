from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations

from shapely.geometry import Polygon

from backend.app.modules.alternative_composer.contracts import (
    StructuralAlternative,
    StructuralAlternativeRejection,
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
from backend.app.modules.generation_loop.service import run_building_generation
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.schemas.llm import FloorAssignment, SUPPORTED_USE_TYPES
from backend.app.schemas.mass import MassInput
from backend.app.schemas.result import BuildingGenerationResult


@dataclass(frozen=True)
class StructuralComposition:
    alternatives: tuple[StructuralAlternative, ...]
    rejections: tuple[StructuralAlternativeRejection, ...]


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
    use_type: str = "office",
    limit: int = 3,
) -> StructuralComposition:
    if use_type not in SUPPORTED_USE_TYPES:
        raise ValueError(f"unsupported use_type: {use_type}")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("structural alternative limit must be a positive integer")

    analysis = analyze_mass(mass)
    boundaries = tuple(
        mass.footprint_for_floor(floor_index)
        for floor_index in range(1, mass.floors + 1)
    )
    assignments = tuple(
        FloorAssignment(floor_index, use_type)
        for floor_index in range(1, mass.floors + 1)
    )
    programs = {
        floor_index: generate_program_graph(
            analysis,
            floor_index=floor_index,
            use_type=use_type,
        )
        for floor_index in range(1, mass.floors + 1)
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
    for core in cores:
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
                circulation_fingerprint = _circulation_fingerprint(
                    circulation.items()
                )
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
                        core_fingerprint=core.fingerprint,
                        circulation_fingerprint=circulation_fingerprint,
                        room_fingerprint=room_fingerprint,
                        structural_fingerprint=structural_fingerprint,
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
        else:
            rejected.extend(core_rejections)

    alternatives = deduplicate_structural_alternatives(accepted)
    alternatives = tuple(sorted(alternatives, key=_rank_key)[:limit])
    return StructuralComposition(alternatives, tuple(rejected))


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
        if "edge_index" in record
        and record.get("kind") == "street"
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


def _rank_key(
    alternative: StructuralAlternative,
) -> tuple[int, float, float, str]:
    validations = [
        floor.validation for floor in alternative.building.floor_results
    ]
    return (
        sum(report.hard_violation_count for report in validations),
        sum(report.violation_score for report in validations),
        -sum(report.total_score for report in validations),
        alternative.strategy,
    )
