"""Bounded numeric repair and section evidence for profiled legal meshes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Sequence

import manifold3d as m3d
import numpy as np
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult, revalidate_compilation_mesh
from backend.app.modules.design.generation.maas.geometry_language.gate import GeometryGatePolicy, compilation_gate


FLOOR_CENTER_NUMERIC_EQUIVALENCE_SCHEMA = (
    "arr.maas.floor_center_numeric_equivalence.v1"
)
FLOOR_CENTER_NUMERIC_EQUIVALENCE_REPAIR_SCHEMA = (
    "arr.maas.floor_center_numeric_equivalence.v2"
)
MESH_NUMERIC_REPAIR_SCHEMA = "arr.maas.profiled_mesh_numeric_repair.v1"
SECTION_EXTRACTOR_EPSILON_M = 1e-6
SECTION_ROUNDING_BUDGET_M = 2e-8
MAXIMUM_CLEANUP_DISPLACEMENT_M = 1e-5
_COLLAPSE_THRESHOLDS_M = (
    1e-8, 3e-8, 1e-7, 3e-7, 1e-5,
)
_NUMERIC_REPAIRABLE_GATE_CODES = frozenset(("tiny_edge", "tiny_face"))


@dataclass(frozen=True)
class ProfiledMeshNumericRepair:
    vertices: tuple[tuple[float, float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]
    collapse_threshold_m: float
    max_physical_displacement_m: float
    raw_indexed_mesh_hash: str
    raw_gate_failure_codes: tuple[str, ...]
    clean_indexed_mesh_hash: str
    clean_gate_hard_pass: bool = True


@dataclass(frozen=True)
class ProfiledMeshCollapseAttempt:
    threshold_m: float
    collapse_count: int
    termination_reason: str
    max_chain_displacement_m: float
    minimum_surviving_edge_physical_m: float
    minimum_surviving_edge_coordinate: float
    minimum_edge_endpoint_indices: tuple[int, ...]
    minimum_edge_delta_xyz: tuple[float, float, float]
    post_gate_codes: tuple[str, ...] = ()
    raw_component_count: int = 0
    post_component_count: int = 0
    structural_evidence: tuple[tuple[str, bool], ...] = ()
    selected_as_final: bool = False
    vertices: tuple[tuple[float, float, float], ...] | None = None
    triangles: tuple[tuple[int, int, int], ...] | None = None

    def evidence(self) -> dict[str, Any]:
        return {
            "threshold_m": self.threshold_m,
            "collapse_count": self.collapse_count,
            "termination_reason": self.termination_reason,
            "max_chain_displacement_m": self.max_chain_displacement_m,
            "minimum_surviving_edge_physical_m": (
                self.minimum_surviving_edge_physical_m
            ),
            "minimum_surviving_edge_coordinate": (
                self.minimum_surviving_edge_coordinate
            ),
            "minimum_edge_endpoint_indices": list(
                self.minimum_edge_endpoint_indices[:2]
            ),
            "minimum_edge_delta_xyz": list(
                self.minimum_edge_delta_xyz
            ),
            "post_gate_codes": list(self.post_gate_codes),
            "raw_component_count": self.raw_component_count,
            "post_component_count": self.post_component_count,
            "structural_evidence": dict(self.structural_evidence),
            "selected_as_final": self.selected_as_final,
        }


@dataclass(frozen=True)
class ProfiledMeshRevalidationResult:
    hard_pass: bool
    raw_gate_codes: tuple[str, ...]
    numeric_measurements: tuple[tuple[str, float], ...]
    repair_attempted: bool
    max_physical_displacement_m: float
    post_repair_gate_codes: tuple[str, ...]
    raw_component_count: int = 0
    post_repair_component_count: int = 0
    compilation: CompilationResult | Any | None = None
    certified_vertices: tuple[tuple[float, float, float], ...] | None = None
    certified_triangles: tuple[tuple[int, int, int], ...] | None = None
    collapse_threshold_m: float = 0.0
    raw_indexed_mesh_hash: str = ""
    clean_indexed_mesh_hash: str = ""
    attempt_records: tuple[ProfiledMeshCollapseAttempt, ...] = ()

    def evidence(self) -> dict[str, Any]:
        return {
            "raw_gate_codes": list(self.raw_gate_codes),
            "numeric_measurements": {
                key: value for key, value in self.numeric_measurements
            },
            "repair_attempted": self.repair_attempted,
            "max_physical_displacement_m": (
                self.max_physical_displacement_m
            ),
            "post_repair_gate_codes": list(self.post_repair_gate_codes),
            "raw_component_count": self.raw_component_count,
            "post_repair_component_count": (
                self.post_repair_component_count
            ),
            "attempt_records": [
                attempt.evidence() for attempt in self.attempt_records
            ],
        }


def revalidated_profiled_mesh(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
) -> CompilationResult | None:
    """Compatibility validator for consumers that must never repair."""

    result, failures = _revalidated_result(vertices, triangles)
    return result if not failures else None


def revalidate_or_repair_profiled_mesh(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
    *,
    effective_height_m: float,
) -> ProfiledMeshRevalidationResult:
    raw_result, raw_failures = _revalidated_result(vertices, triangles)
    raw_component_count = int(
        getattr(raw_result, "metrics", {}).get("component_count") or 0
    )
    measurements = _allowlisted_numeric_measurements(vertices, triangles)
    raw_hash = indexed_mesh_hash(vertices, triangles)
    if not raw_failures:
        return ProfiledMeshRevalidationResult(
            hard_pass=True,
            raw_gate_codes=(),
            numeric_measurements=measurements,
            repair_attempted=False,
            max_physical_displacement_m=0.0,
            post_repair_gate_codes=(),
            raw_component_count=raw_component_count,
            post_repair_component_count=raw_component_count,
            compilation=raw_result,
            certified_vertices=vertices,
            certified_triangles=triangles,
            raw_indexed_mesh_hash=raw_hash,
            clean_indexed_mesh_hash=raw_hash,
        )
    if raw_failures == ("tiny_edge",):
        minimum_physical_edge = _minimum_physical_edge_length(
            vertices,
            triangles,
            effective_height_m=effective_height_m,
        )
        if minimum_physical_edge >= GeometryGatePolicy().minimum_edge_length:
            return ProfiledMeshRevalidationResult(
                hard_pass=True,
                raw_gate_codes=(),
                numeric_measurements=tuple((*measurements, (
                    "minimum_edge_length_physical_m",
                    minimum_physical_edge,
                ))),
                repair_attempted=False,
                max_physical_displacement_m=0.0,
                post_repair_gate_codes=(),
                raw_component_count=raw_component_count,
                post_repair_component_count=raw_component_count,
                compilation=raw_result,
                certified_vertices=vertices,
                certified_triangles=triangles,
                raw_indexed_mesh_hash=raw_hash,
                clean_indexed_mesh_hash=raw_hash,
            )
    if not set(raw_failures).issubset(_NUMERIC_REPAIRABLE_GATE_CODES):
        return ProfiledMeshRevalidationResult(
            hard_pass=False,
            raw_gate_codes=raw_failures,
            numeric_measurements=measurements,
            repair_attempted=False,
            max_physical_displacement_m=0.0,
            post_repair_gate_codes=(),
            raw_component_count=raw_component_count,
            compilation=raw_result,
            raw_indexed_mesh_hash=raw_hash,
        )

    post_failures: tuple[str, ...] = ("numeric_repair_not_produced",)
    maximum_displacement = 0.0
    attempt_records: list[ProfiledMeshCollapseAttempt] = []
    selected_result: ProfiledMeshRevalidationResult | None = None
    decisive_failure: ProfiledMeshRevalidationResult | None = None
    for threshold in _COLLAPSE_THRESHOLDS_M:
        attempt = _collapse_edges_attempt(
            vertices,
            triangles,
            maximum_length=threshold,
            effective_height_m=effective_height_m,
            fixed_point="tiny_edge" in raw_failures,
        )
        attempt = replace(
            attempt,
            raw_component_count=raw_component_count,
        )
        maximum_displacement = max(
            maximum_displacement,
            float(attempt.max_chain_displacement_m),
        )
        if attempt.vertices is None or attempt.triangles is None:
            if attempt.termination_reason == "chain_displacement_exceeded":
                post_failures = ("numeric_repair_displacement_exceeded",)
            attempt_records.append(attempt)
            continue
        clean_vertices = attempt.vertices
        clean_triangles = attempt.triangles
        displacement = attempt.max_chain_displacement_m
        clean_result, clean_failures = _revalidated_result(
            clean_vertices,
            clean_triangles,
        )
        if (
            clean_failures == ("tiny_edge",)
            and _minimum_physical_edge_length(
                clean_vertices,
                clean_triangles,
                effective_height_m=effective_height_m,
            ) >= GeometryGatePolicy().minimum_edge_length
        ):
            clean_failures = ()
        clean_component_count = int(
            getattr(clean_result, "metrics", {}).get("component_count") or 0
        )
        clean_metrics = getattr(clean_result, "metrics", {})
        structural_evidence = tuple(
            (key, bool(clean_metrics.get(key) is True))
            for key in (
                "watertight",
                "closed_solid",
                "manifold",
                "self_intersection_checked_by_kernel",
                "outward_normals",
            )
        )
        attempt = replace(
            attempt,
            post_gate_codes=clean_failures,
            post_component_count=clean_component_count,
            structural_evidence=structural_evidence,
        )
        if (
            not isfinite(displacement)
            or displacement > MAXIMUM_CLEANUP_DISPLACEMENT_M
        ):
            attempt = replace(
                attempt,
                termination_reason="chain_displacement_exceeded",
                post_gate_codes=("numeric_repair_displacement_exceeded",),
            )
            attempt_records.append(attempt)
            if selected_result is None and decisive_failure is None:
                decisive_failure = ProfiledMeshRevalidationResult(
                hard_pass=False,
                raw_gate_codes=raw_failures,
                numeric_measurements=measurements,
                repair_attempted=True,
                max_physical_displacement_m=float(displacement),
                post_repair_gate_codes=(
                    "numeric_repair_displacement_exceeded",
                ),
                raw_component_count=raw_component_count,
                post_repair_component_count=clean_component_count,
                compilation=raw_result,
                raw_indexed_mesh_hash=raw_hash,
                )
            continue
        post_failures = clean_failures
        if clean_failures:
            attempt_records.append(attempt)
            continue
        if raw_component_count <= 0:
            attempt = replace(
                attempt,
                post_gate_codes=(
                    "numeric_repair_raw_component_count_unavailable",
                ),
            )
            attempt_records.append(attempt)
            if selected_result is None and decisive_failure is None:
                decisive_failure = ProfiledMeshRevalidationResult(
                hard_pass=False,
                raw_gate_codes=raw_failures,
                numeric_measurements=measurements,
                repair_attempted=True,
                max_physical_displacement_m=float(displacement),
                post_repair_gate_codes=(
                    "numeric_repair_raw_component_count_unavailable",
                ),
                raw_component_count=raw_component_count,
                post_repair_component_count=clean_component_count,
                compilation=raw_result,
                raw_indexed_mesh_hash=raw_hash,
                )
            continue
        if clean_component_count != raw_component_count:
            attempt = replace(
                attempt,
                post_gate_codes=("numeric_repair_component_count_mismatch",),
            )
            attempt_records.append(attempt)
            if selected_result is None and decisive_failure is None:
                decisive_failure = ProfiledMeshRevalidationResult(
                hard_pass=False,
                raw_gate_codes=raw_failures,
                numeric_measurements=measurements,
                repair_attempted=True,
                max_physical_displacement_m=float(displacement),
                post_repair_gate_codes=(
                    "numeric_repair_component_count_mismatch",
                ),
                raw_component_count=raw_component_count,
                post_repair_component_count=clean_component_count,
                compilation=raw_result,
                raw_indexed_mesh_hash=raw_hash,
                )
            continue
        if selected_result is None and decisive_failure is None:
            attempt = replace(attempt, selected_as_final=True)
            selected_result = ProfiledMeshRevalidationResult(
                hard_pass=True,
                raw_gate_codes=raw_failures,
                numeric_measurements=measurements,
                repair_attempted=True,
                max_physical_displacement_m=float(displacement),
                post_repair_gate_codes=(),
                raw_component_count=raw_component_count,
                post_repair_component_count=clean_component_count,
                compilation=clean_result,
                certified_vertices=clean_vertices,
                certified_triangles=clean_triangles,
                collapse_threshold_m=threshold,
                raw_indexed_mesh_hash=raw_hash,
                clean_indexed_mesh_hash=indexed_mesh_hash(
                    clean_vertices,
                    clean_triangles,
                ),
            )
        attempt_records.append(attempt)
    if selected_result is not None:
        return replace(
            selected_result,
            attempt_records=tuple(attempt_records),
        )
    if decisive_failure is not None:
        return replace(
            decisive_failure,
            attempt_records=tuple(attempt_records),
        )
    return ProfiledMeshRevalidationResult(
        hard_pass=False,
        raw_gate_codes=raw_failures,
        numeric_measurements=measurements,
        repair_attempted=True,
        max_physical_displacement_m=maximum_displacement,
        post_repair_gate_codes=post_failures,
        raw_component_count=raw_component_count,
        compilation=raw_result,
        raw_indexed_mesh_hash=raw_hash,
        attempt_records=tuple(attempt_records),
    )


def repair_profiled_indexed_mesh(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
    *,
    effective_height_m: float,
) -> ProfiledMeshNumericRepair | None:
    """Compatibility view over the typed revalidation/repair boundary."""

    result = revalidate_or_repair_profiled_mesh(
        vertices,
        triangles,
        effective_height_m=effective_height_m,
    )
    if not result.hard_pass or not result.repair_attempted:
        return None
    assert result.certified_vertices is not None
    assert result.certified_triangles is not None
    return ProfiledMeshNumericRepair(
        vertices=result.certified_vertices,
        triangles=result.certified_triangles,
        collapse_threshold_m=result.collapse_threshold_m,
        max_physical_displacement_m=result.max_physical_displacement_m,
        raw_indexed_mesh_hash=result.raw_indexed_mesh_hash,
        raw_gate_failure_codes=result.raw_gate_codes,
        clean_indexed_mesh_hash=result.clean_indexed_mesh_hash,
    )


def _allowlisted_numeric_measurements(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
) -> tuple[tuple[str, float], ...]:
    edge_lengths: list[float] = []
    triangle_areas: list[float] = []
    for triangle in triangles:
        try:
            points = tuple(np.asarray(vertices[index], dtype=float) for index in triangle)
        except (IndexError, TypeError, ValueError):
            continue
        if len(points) != 3 or any(point.shape != (3,) for point in points):
            continue
        edge_lengths.extend(
            float(np.linalg.norm(points[left] - points[right]))
            for left, right in ((0, 1), (1, 2), (2, 0))
        )
        triangle_areas.append(float(
            np.linalg.norm(np.cross(points[1] - points[0], points[2] - points[0]))
            * 0.5
        ))
    return (
        ("vertex_count", float(len(vertices))),
        ("triangle_count", float(len(triangles))),
        (
            "minimum_edge_length_coordinate",
            min(edge_lengths) if edge_lengths else 0.0,
        ),
        (
            "minimum_triangle_area_coordinate2",
            min(triangle_areas) if triangle_areas else 0.0,
        ),
    )


def section_numeric_epsilon_m(cleanup_displacement_m: float) -> float:
    displacement = float(cleanup_displacement_m)
    if displacement <= 0.0:
        return SECTION_EXTRACTOR_EPSILON_M
    if (
        not isfinite(displacement)
        or displacement > MAXIMUM_CLEANUP_DISPLACEMENT_M
    ):
        raise ValueError("mesh cleanup displacement exceeds numeric contract")
    return (
        SECTION_EXTRACTOR_EPSILON_M
        + displacement
        + SECTION_ROUNDING_BUDGET_M
    )


def floor_center_numeric_equivalence(
    measured: Any,
    expected: Any,
    *,
    epsilon_m: float = SECTION_EXTRACTOR_EPSILON_M,
    contour_count: int | None = None,
) -> dict[str, Any] | None:
    """Certify one reconstructed section without hiding topology changes."""

    if not _valid_polygonal(measured) or not _valid_polygonal(expected):
        return None
    measured_components = _components(measured)
    expected_components = _components(expected)
    measured_holes = sum(len(component.interiors) for component in measured_components)
    expected_holes = sum(len(component.interiors) for component in expected_components)
    area_delta = abs(float(measured.area) - float(expected.area))
    symdiff = float(measured.symmetric_difference(expected).area)
    hausdorff = float(
        measured.boundary.hausdorff_distance(expected.boundary)
    )
    area_bound = (
        SECTION_EXTRACTOR_EPSILON_M
        + float(expected.length) * float(epsilon_m)
    )
    hausdorff_bound = max(
        float(epsilon_m),
        SECTION_EXTRACTOR_EPSILON_M
        + MAXIMUM_CLEANUP_DISPLACEMENT_M
        + SECTION_ROUNDING_BUDGET_M,
    )
    values = (
        area_delta,
        symdiff,
        hausdorff,
        area_bound,
        hausdorff_bound,
    )
    if not all(isfinite(value) for value in values):
        return None
    failed_predicates = []
    if len(measured_components) != len(expected_components):
        failed_predicates.append("component_count_mismatch")
    if measured_holes != expected_holes:
        failed_predicates.append("hole_count_mismatch")
    if area_delta > area_bound:
        failed_predicates.append("area_delta_exceeds_bound")
    if symdiff > area_bound:
        failed_predicates.append("symmetric_difference_exceeds_bound")
    if hausdorff > hausdorff_bound:
        failed_predicates.append("hausdorff_distance_exceeds_bound")
    return {
        "hard_pass": not failed_predicates,
        "area_delta_m2": area_delta,
        "symdiff_m2": symdiff,
        "hausdorff_m": hausdorff,
        "area_bound_m2": area_bound,
        "hausdorff_bound_m": hausdorff_bound,
        "failed_predicates": failed_predicates,
        "component_count": len(measured_components),
        "hole_count": measured_holes,
        "expected_component_count": len(expected_components),
        "expected_hole_count": expected_holes,
        "contour_count": int(
            contour_count
            if contour_count is not None
            else len(measured_components) + measured_holes
        ),
    }


def indexed_mesh_section_polygon(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
    z: float,
) -> Polygon | MultiPolygon | None:
    """Kernel-slice the final indexed payload without flattening topology."""

    measured = indexed_mesh_section_topology(vertices, triangles, z)
    return measured[0] if measured is not None else None


def indexed_mesh_section_topology(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
    z: float,
) -> tuple[Polygon | MultiPolygon, int, int] | None:
    """Return complete polygonal section, contour count, and solid count."""

    try:
        mesh = m3d.Mesh(
            np.asarray(vertices, dtype=np.float64),
            np.asarray(triangles, dtype=np.uint32),
        )
        mesh.merge()
        solid = m3d.Manifold(mesh)
        section = solid.slice(float(z))
        contours = section.to_polygons()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None
    if (
        solid.is_empty()
        or "NoError" not in str(solid.status())
        or section.is_empty()
        or int(section.num_contour()) <= 0
        or len(contours) != int(section.num_contour())
    ):
        return None
    polygonal = _polygonal_from_contours(contours)
    if polygonal is None:
        return None
    return polygonal, int(section.num_contour()), len(solid.decompose())


def profiled_surface_section_polygon(
    surfaces: Sequence[Any],
    *,
    origin_xy: tuple[float, float],
    z: float,
) -> Polygon | MultiPolygon | None:
    """Kernel-slice a complete triangle-surface transport payload."""

    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    for surface in surfaces:
        triangle = tuple(getattr(surface, "vertices_m", ()) or ())
        if len(triangle) != 3:
            return None
        offset = len(vertices)
        vertices.extend(
            (
                float(point[0]) + float(origin_xy[0]),
                float(point[1]) + float(origin_xy[1]),
                float(point[2]),
            )
            for point in triangle
        )
        triangles.append((offset, offset + 1, offset + 2))
    return indexed_mesh_section_polygon(
        tuple(vertices),
        tuple(triangles),
        z,
    )


def indexed_mesh_hash(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
) -> str:
    payload = {
        "vertices": [[float(value) for value in vertex] for vertex in vertices],
        "triangles": [[int(value) for value in triangle] for triangle in triangles],
    }
    return sha256(json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")).hexdigest()


def indexed_mesh_component_volumes(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
) -> tuple[float, ...] | None:
    """Measure component volumes from the exact emitted indexed payload."""

    try:
        mesh = m3d.Mesh(
            np.asarray(vertices, dtype=np.float64),
            np.asarray(triangles, dtype=np.uint32),
        )
        mesh.merge()
        solid = m3d.Manifold(mesh)
        components = solid.decompose()
        volumes = tuple(sorted(float(component.volume()) for component in components))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None
    if (
        solid.is_empty()
        or "NoError" not in str(solid.status())
        or not volumes
        or not all(isfinite(volume) and volume > 0.0 for volume in volumes)
    ):
        return None
    return volumes


def _revalidated_result(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
) -> tuple[CompilationResult, tuple[str, ...]]:
    result = revalidate_compilation_mesh(CompilationResult(
        program=None,  # type: ignore[arg-type]
        status="compiled",
        vertices=vertices,
        triangles=triangles,
    ))
    structural = (
        result.status == "compiled"
        and result.metrics.get("watertight") is True
        and result.metrics.get("closed_solid") is True
        and result.metrics.get("manifold") is True
        and result.metrics.get("self_intersection_checked_by_kernel") is True
        and result.metrics.get("outward_normals") is True
        and float(result.metrics.get("volume") or 0.0) > 0.0
        and int(result.metrics.get("component_count") or 0) >= 1
    )
    failures = tuple(
        issue.code
        for issue in compilation_gate(
            result,
            GeometryGatePolicy(),
        )
    )
    if not structural and not failures:
        failures = ("mesh_structural_revalidation_failed",)
    return result, failures


def _minimum_physical_edge_length(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
    *,
    effective_height_m: float,
) -> float:
    if not vertices or not triangles or effective_height_m <= 0.0:
        return 0.0
    edges = {
        tuple(sorted((triangle[left], triangle[right])))
        for triangle in triangles
        for left, right in ((0, 1), (1, 2), (2, 0))
        if triangle[left] != triangle[right]
    }
    if not edges:
        return 0.0
    return min((
        (vertices[left][0] - vertices[right][0]) ** 2
        + (vertices[left][1] - vertices[right][1]) ** 2
        + (
            (vertices[left][2] - vertices[right][2])
            * effective_height_m
        ) ** 2
    ) ** 0.5 for left, right in edges)


def _collapse_edges_attempt(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
    *,
    maximum_length: float,
    effective_height_m: float,
    fixed_point: bool = True,
) -> ProfiledMeshCollapseAttempt:
    parent = list(range(len(vertices)))
    if not isfinite(effective_height_m) or effective_height_m <= 0.0:
        return ProfiledMeshCollapseAttempt(
            threshold_m=maximum_length,
            collapse_count=0,
            termination_reason="invalid_effective_height",
            max_chain_displacement_m=0.0,
            minimum_surviving_edge_physical_m=0.0,
            minimum_surviving_edge_coordinate=0.0,
            minimum_edge_endpoint_indices=(),
            minimum_edge_delta_xyz=(0.0, 0.0, 0.0),
        )

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    pending_original_edges = None if fixed_point else {
        tuple(sorted((int(triangle[left]), int(triangle[right]))))
        for triangle in triangles
        for left, right in ((0, 1), (1, 2), (2, 0))
    }
    collapsed_count = 0
    while True:
        if fixed_point:
            representative_triangles = tuple(
                tuple(root(int(index)) for index in triangle)
                for triangle in triangles
            )
            edges = {
                tuple(sorted((triangle[left], triangle[right])))
                for triangle in representative_triangles
                if len(set(triangle)) == 3
                for left, right in ((0, 1), (1, 2), (2, 0))
                if triangle[left] != triangle[right]
            }
        else:
            edges = pending_original_edges or set()

        def physical_distance_squared(edge: tuple[int, int]) -> float:
            left, right = edge
            return (
            sum(
                (vertices[left][axis] - vertices[right][axis]) ** 2
                for axis in range(2)
            )
            + (
                (vertices[left][2] - vertices[right][2])
                * effective_height_m
            ) ** 2
            )

        eligible = tuple(sorted(
            (
                edge for edge in edges
                if physical_distance_squared(edge)
                < maximum_length * maximum_length
            ),
            key=lambda edge: (
                physical_distance_squared(edge),
                vertices[edge[0]],
                vertices[edge[1]],
                edge,
            ),
        ))
        if not eligible:
            break
        selected_edge = eligible[0]
        if pending_original_edges is not None:
            pending_original_edges.discard(selected_edge)
        left_root, right_root = (
            root(selected_edge[0]),
            root(selected_edge[1]),
        )
        if left_root == right_root:
            continue
        retained, removed = sorted(
            (left_root, right_root),
            key=lambda index: (vertices[index], index),
        )
        parent[removed] = retained
        collapsed_count += 1
    if not collapsed_count:
        if edges:
            minimum_edge = min(
                edges,
                key=lambda edge: (physical_distance_squared(edge), edge),
            )
            delta = tuple(
                float(
                    vertices[minimum_edge[1]][axis]
                    - vertices[minimum_edge[0]][axis]
                )
                for axis in range(3)
            )
            minimum_physical = physical_distance_squared(minimum_edge) ** 0.5
            minimum_coordinate = sum(value ** 2 for value in delta) ** 0.5
        else:
            minimum_edge = ()
            delta = (0.0, 0.0, 0.0)
            minimum_physical = 0.0
            minimum_coordinate = 0.0
        return ProfiledMeshCollapseAttempt(
            threshold_m=maximum_length,
            collapse_count=0,
            termination_reason="no_eligible_edge",
            max_chain_displacement_m=0.0,
            minimum_surviving_edge_physical_m=minimum_physical,
            minimum_surviving_edge_coordinate=minimum_coordinate,
            minimum_edge_endpoint_indices=minimum_edge,
            minimum_edge_delta_xyz=delta,
        )

    remapped = tuple(
        tuple(root(index) for index in triangle)
        for triangle in triangles
    )
    surviving = tuple(
        triangle for triangle in remapped
        if len(set(triangle)) == 3
    )
    used = tuple(sorted(
        {index for triangle in surviving for index in triangle},
        key=lambda index: (vertices[index], index),
    ))
    compact = {old: new for new, old in enumerate(used)}
    compact_vertices = tuple(vertices[index] for index in used)
    compact_triangles = tuple(sorted(
        (
            _rotate_triangle(tuple(compact[index] for index in triangle))
            for triangle in surviving
        ),
        key=lambda triangle: tuple(
            compact_vertices[index]
            for index in triangle
        ),
    ))
    max_displacement = max(
        (
            sum(
            (
                vertices[index][axis]
                - vertices[root(index)][axis]
            ) ** 2
            for axis in range(2)
            )
            + (
                (
                    vertices[index][2]
                    - vertices[root(index)][2]
                )
                * effective_height_m
            ) ** 2
        ) ** 0.5
        for index in range(len(vertices))
    )
    compact_edges = tuple(sorted({
        tuple(sorted((triangle[left], triangle[right])))
        for triangle in compact_triangles
        for left, right in ((0, 1), (1, 2), (2, 0))
    }))
    if compact_edges:
        minimum_edge = min(compact_edges, key=lambda edge: (
            sum(
                (
                    compact_vertices[edge[0]][axis]
                    - compact_vertices[edge[1]][axis]
                ) ** 2
                for axis in range(2)
            ) + (
                (
                    compact_vertices[edge[0]][2]
                    - compact_vertices[edge[1]][2]
                ) * effective_height_m
            ) ** 2,
            edge,
        ))
        delta = tuple(
            float(
                compact_vertices[minimum_edge[1]][axis]
                - compact_vertices[minimum_edge[0]][axis]
            )
            for axis in range(3)
        )
        minimum_physical = (
            delta[0] ** 2
            + delta[1] ** 2
            + (delta[2] * effective_height_m) ** 2
        ) ** 0.5
        minimum_coordinate = sum(value ** 2 for value in delta) ** 0.5
    else:
        minimum_edge = ()
        delta = (0.0, 0.0, 0.0)
        minimum_physical = 0.0
        minimum_coordinate = 0.0
    if max_displacement > min(
        maximum_length,
        MAXIMUM_CLEANUP_DISPLACEMENT_M,
    ) + 1e-12:
        return ProfiledMeshCollapseAttempt(
            threshold_m=maximum_length,
            collapse_count=collapsed_count,
            termination_reason="chain_displacement_exceeded",
            max_chain_displacement_m=max_displacement,
            minimum_surviving_edge_physical_m=minimum_physical,
            minimum_surviving_edge_coordinate=minimum_coordinate,
            minimum_edge_endpoint_indices=minimum_edge,
            minimum_edge_delta_xyz=delta,
        )
    return ProfiledMeshCollapseAttempt(
        threshold_m=maximum_length,
        collapse_count=collapsed_count,
        termination_reason="completed",
        max_chain_displacement_m=max_displacement,
        minimum_surviving_edge_physical_m=minimum_physical,
        minimum_surviving_edge_coordinate=minimum_coordinate,
        minimum_edge_endpoint_indices=minimum_edge,
        minimum_edge_delta_xyz=delta,
        vertices=compact_vertices,
        triangles=compact_triangles,
    )


def _collapse_edges(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
    *,
    maximum_length: float,
    effective_height_m: float,
    fixed_point: bool = True,
) -> tuple[
    tuple[tuple[float, float, float], ...],
    tuple[tuple[int, int, int], ...],
    float,
] | None:
    """Compatibility view preserving the prior tuple-or-None contract."""

    attempt = _collapse_edges_attempt(
        vertices,
        triangles,
        maximum_length=maximum_length,
        effective_height_m=effective_height_m,
        fixed_point=fixed_point,
    )
    if attempt.vertices is None or attempt.triangles is None:
        return None
    return (
        attempt.vertices,
        attempt.triangles,
        attempt.max_chain_displacement_m,
    )


def _components(value: Any) -> tuple[Polygon, ...]:
    if isinstance(value, Polygon):
        return (value,)
    if isinstance(value, MultiPolygon):
        return tuple(sorted(
            value.geoms,
            key=lambda component: component.normalize().wkb_hex,
        ))
    return ()


def _valid_polygonal(value: Any) -> bool:
    return bool(
        isinstance(value, (Polygon, MultiPolygon))
        and not value.is_empty
        and value.is_valid
        and isfinite(float(value.area))
        and float(value.area) > 1e-8
    )


def _polygonal_from_contours(contours: Sequence[Any]) -> Polygon | MultiPolygon | None:
    rings = []
    for contour in contours:
        coordinates = tuple(
            (float(point[0]), float(point[1]))
            for point in contour
        )
        ring = Polygon(coordinates)
        if ring.is_empty or not ring.is_valid or float(ring.area) <= 1e-8:
            return None
        rings.append(ring)
    parents: list[int | None] = []
    for index, ring in enumerate(rings):
        point = ring.representative_point()
        containers = [
            candidate
            for candidate, outer in enumerate(rings)
            if candidate != index
            and float(outer.area) > float(ring.area)
            and outer.covers(point)
        ]
        parents.append(
            min(containers, key=lambda item: rings[item].area)
            if containers else None
        )
    depths = []
    for index in range(len(rings)):
        depth = 0
        parent = parents[index]
        seen = {index}
        while parent is not None:
            if parent in seen:
                return None
            seen.add(parent)
            depth += 1
            parent = parents[parent]
        depths.append(depth)
    polygons = []
    for index, ring in enumerate(rings):
        if depths[index] % 2:
            continue
        holes = [
            tuple(rings[child].exterior.coords)
            for child, parent in enumerate(parents)
            if parent == index and depths[child] == depths[index] + 1
        ]
        polygons.append(Polygon(tuple(ring.exterior.coords), holes=holes))
    result = unary_union(polygons).normalize()
    return result if _valid_polygonal(result) else None


def _rotate_triangle(
    triangle: tuple[int, int, int],
) -> tuple[int, int, int]:
    rotations = (
        triangle,
        (triangle[1], triangle[2], triangle[0]),
        (triangle[2], triangle[0], triangle[1]),
    )
    return min(rotations)


__all__ = [
    "FLOOR_CENTER_NUMERIC_EQUIVALENCE_SCHEMA",
    "FLOOR_CENTER_NUMERIC_EQUIVALENCE_REPAIR_SCHEMA",
    "MAXIMUM_CLEANUP_DISPLACEMENT_M",
    "MESH_NUMERIC_REPAIR_SCHEMA",
    "ProfiledMeshCollapseAttempt",
    "ProfiledMeshNumericRepair",
    "ProfiledMeshRevalidationResult",
    "floor_center_numeric_equivalence",
    "indexed_mesh_section_polygon",
    "indexed_mesh_section_topology",
    "indexed_mesh_component_volumes",
    "profiled_surface_section_polygon",
    "repair_profiled_indexed_mesh",
    "revalidate_or_repair_profiled_mesh",
    "revalidated_profiled_mesh",
    "_collapse_edges_attempt",
    "section_numeric_epsilon_m",
]
