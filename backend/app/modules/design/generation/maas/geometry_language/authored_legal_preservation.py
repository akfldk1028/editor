"""Certify a site-placed authored solid without rewriting its geometry DAG."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

from shapely.geometry import Polygon

from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import Matrix4, identity_matrix4
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult, compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.floorwise_legal_program import _compiled_manifold, _measure_floor_evidence, _valid_legal_context
from backend.app.modules.design.generation.maas.geometry_language.gate import GeometryGatePolicy, compilation_gate


@dataclass(frozen=True)
class AuthoredLegalPreservationResult:
    """Evidence for an unchanged authored program accepted as the final solid."""

    program: GeometryProgram
    floor_matrices: tuple[Matrix4, ...]
    achieved_floor_areas_m2: tuple[float, ...]
    certificate: dict[str, Any]
    final_compilation: CompilationResult


def _valid_authored_request(
    program: GeometryProgram,
    *,
    legal_sections: tuple[Polygon, ...],
    target_floor_areas_m2: tuple[float, ...],
    floor_capacity_plan_hash: str,
) -> bool:
    """Require canonical UnitBox lineage while permitting typed cutters.

    Additional authored primitives are operands in the typed geometry DAG;
    rejecting them would silently reduce the advertised language to unary
    UnitBox modifiers.  Exactly one canonical UnitBox remains mandatory.
    """

    canonical_unitboxes = tuple(
        node
        for node in program.nodes
        if node.kind == "primitive"
        and node.operator == "box"
        and node.parameters
        == {"width": 1.0, "depth": 1.0, "height": 1.0}
    )
    return bool(
        len(canonical_unitboxes) == 1
        and _valid_legal_context(
            program,
            legal_sections=legal_sections,
            target_floor_areas_m2=target_floor_areas_m2,
            floor_capacity_plan_hash=floor_capacity_plan_hash,
        )
    )


def certify_authored_affine_program(
    program: GeometryProgram,
    *,
    legal_sections: tuple[Polygon, ...],
    target_floor_areas_m2: tuple[float, ...],
    floor_capacity_plan_hash: str,
    minimum_aggregate_target_ratio: float = 0.995,
) -> AuthoredLegalPreservationResult | None:
    """Return unchanged ``program`` only when its measured final mesh passes."""

    if not _valid_authored_request(
        program,
        legal_sections=legal_sections,
        target_floor_areas_m2=target_floor_areas_m2,
        floor_capacity_plan_hash=floor_capacity_plan_hash,
    ):
        return None

    compilation = compile_geometry_program(program)
    if (
        not _compiled_manifold(compilation)
        or compilation_gate(
            compilation,
            GeometryGatePolicy(maximum_components=1),
        )
    ):
        return None

    bounds = (compilation.metrics or {}).get("bounds") or ()
    if len(bounds) != 2 or len(bounds[0]) != 3 or len(bounds[1]) != 3:
        return None
    min_z = float(bounds[0][2])
    max_z = float(bounds[1][2])
    floor_count = len(legal_sections)
    floor_height = (max_z - min_z) / floor_count
    if (
        not all(isfinite(value) for value in (min_z, max_z, floor_height))
        or floor_height <= 1e-9
    ):
        return None

    floor_ranges = tuple(
        (
            min_z + floor_height * floor_index,
            (
                max_z
                if floor_index == floor_count - 1
                else min_z + floor_height * (floor_index + 1)
            ),
        )
        for floor_index in range(floor_count)
    )
    floor_matrices = tuple(
        identity_matrix4()
        for _floor_index in range(floor_count)
    )
    measured = _measure_floor_evidence(
        compilation,
        legal_sections=legal_sections,
        floor_ranges=floor_ranges,
        floor_matrices=floor_matrices,
        target_floor_areas_m2=target_floor_areas_m2,
        matrix_mode="authored_affine_preserved",
    )
    if measured is None:
        return None
    achieved, floor_evidence = measured
    aggregate_target = sum(float(value) for value in target_floor_areas_m2)
    achieved_total = sum(achieved)
    capacity_threshold_ratio = max(
        0.05,
        min(0.995, float(minimum_aggregate_target_ratio)),
    )
    if achieved_total + 1e-7 < aggregate_target * capacity_threshold_ratio:
        return None

    program_hash = program.program_hash()
    certificate = {
        "schema_version": "arr.maas.authored_legal_preservation.v1",
        "status": "certified",
        "hard_pass": True,
        "projection_mode": "authored_affine_preserved",
        "authored_program_hash": program_hash,
        "final_program_hash": program_hash,
        "final_geometry_hash": compilation.geometry_hash,
        "floor_capacity_plan_hash": floor_capacity_plan_hash,
        "floor_count": floor_count,
        "finite_coordinates": True,
        "manifold": bool(compilation.metrics.get("manifold")),
        "watertight": bool(compilation.metrics.get("watertight")),
        "all_sections_contained": all(
            evidence["contained"] for evidence in floor_evidence
        ),
        "capacity_threshold_ratio": capacity_threshold_ratio,
        "aggregate_target_area_m2": round(aggregate_target, 8),
        "achieved_aggregate_area_m2": round(achieved_total, 8),
        "achieved_floor_areas_m2": [
            round(value, 8) for value in achieved
        ],
        "target_floor_areas_m2": [
            round(float(value), 8)
            for value in target_floor_areas_m2
        ],
        "floor_evidence": list(floor_evidence),
    }
    return AuthoredLegalPreservationResult(
        program=program,
        floor_matrices=floor_matrices,
        achieved_floor_areas_m2=achieved,
        certificate=certificate,
        final_compilation=compilation,
    )


__all__ = [
    "AuthoredLegalPreservationResult",
    "certify_authored_affine_program",
]
