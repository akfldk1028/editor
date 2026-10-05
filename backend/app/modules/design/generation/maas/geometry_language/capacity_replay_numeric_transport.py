"""Proof-bounded numeric transport for floorwise capacity replay meshes."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from math import dist, isfinite
from typing import Any

import manifold3d as m3d
import numpy as np
from shapely.geometry import Polygon

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram


CAPACITY_REPLAY_TRANSPORT_SCHEMA = (
    "arr.maas.capacity_replay_numeric_transport.v1"
)
COLLAPSE_THRESHOLD_M = 1e-5
SECTION_BASE_EPSILON_M = 1e-6
SECTION_ROUNDING_BUDGET_M = 2e-8


@dataclass(frozen=True)
class CapacityReplayNumericTransport:
    vertices: tuple[tuple[float, float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]
    evidence: dict[str, Any]


def repair_capacity_replay_mesh(
    program: GeometryProgram,
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
) -> CapacityReplayNumericTransport | None:
    """Collapse only sub-gate-tolerance edges and prove every floor section."""

    expected_sections = _expected_floor_sections(program)
    if not expected_sections:
        return None
    collapsed = _collapse_edges(
        vertices,
        triangles,
        maximum_length=COLLAPSE_THRESHOLD_M,
    )
    if collapsed is None:
        return None
    clean_vertices, clean_triangles, displacement = collapsed
    kernel_simplification_applied = False
    if not _numeric_triangle_gate_passes(
        clean_vertices,
        clean_triangles,
    ):
        simplified = _kernel_simplified_mesh(
            clean_vertices,
            clean_triangles,
            tolerance_m=COLLAPSE_THRESHOLD_M,
        )
        if simplified is None:
            return None
        simplified_vertices, simplified_triangles, simplification_displacement = (
            simplified
        )
        displacement = max(displacement, simplification_displacement)
        if displacement > COLLAPSE_THRESHOLD_M + 1e-15:
            return None
        clean_vertices = simplified_vertices
        clean_triangles = simplified_triangles
        kernel_simplification_applied = True
    epsilon = (
        SECTION_BASE_EPSILON_M
        + displacement
        + SECTION_ROUNDING_BUDGET_M
    )
    rows: list[dict[str, Any]] = []
    for floor_index, (z, expected) in enumerate(
        expected_sections,
        start=1,
    ):
        measured = _indexed_mesh_section_polygon(
            clean_vertices,
            clean_triangles,
            z,
        )
        proof = _section_equivalence(
            measured,
            expected,
            epsilon_m=epsilon,
        )
        if proof is None:
            return None
        rows.append({
            "floor_index": floor_index,
            "section_z_m": round(z, 8),
            **proof,
        })
    raw_hash = indexed_mesh_hash(vertices, triangles)
    clean_hash = indexed_mesh_hash(clean_vertices, clean_triangles)
    return CapacityReplayNumericTransport(
        vertices=clean_vertices,
        triangles=clean_triangles,
        evidence={
            "schema_version": CAPACITY_REPLAY_TRANSPORT_SCHEMA,
            "hard_pass": True,
            "raw_indexed_mesh_hash": raw_hash,
            "clean_indexed_mesh_hash": clean_hash,
            "collapse_threshold_m": COLLAPSE_THRESHOLD_M,
            "max_3d_displacement_m": displacement,
            "kernel_simplification_applied": (
                kernel_simplification_applied
            ),
            "section_numeric_epsilon_m": epsilon,
            "floor_center_section_count": len(rows),
            "floor_center_sections": rows,
        },
    )


def indexed_mesh_hash(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
) -> str:
    payload = {
        "vertices": [list(vertex) for vertex in vertices],
        "triangles": [list(triangle) for triangle in triangles],
    }
    return sha256(json.dumps(
        payload,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")).hexdigest()


def _expected_floor_sections(
    program: GeometryProgram,
) -> tuple[tuple[float, Polygon], ...]:
    node_map = program.node_map
    sections: list[tuple[float, Polygon]] = []
    for node in program.topological_nodes():
        if node.kind != "transform" or node.operator != "translate":
            continue
        if len(node.inputs) != 1:
            return ()
        primitive = node_map.get(node.inputs[0])
        if (
            primitive is None
            or primitive.kind != "primitive"
            or primitive.operator != "extruded_polygon"
        ):
            return ()
        try:
            vector = node.parameters["vector"]
            bottom = float(vector[2])
            height = float(primitive.parameters["height"])
            points = primitive.parameters["points"]
            holes = primitive.parameters.get("holes") or ()
            polygon = Polygon(points, holes)
        except (KeyError, TypeError, ValueError, IndexError):
            return ()
        if (
            not isfinite(bottom)
            or not isfinite(height)
            or height <= 0.0
            or not _single_polygon(polygon)
        ):
            return ()
        sections.append((bottom + height * 0.5, polygon))
    sections.sort(key=lambda row: row[0])
    return tuple(sections)


def _collapse_edges(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
    *,
    maximum_length: float,
) -> tuple[
    tuple[tuple[float, float, float], ...],
    tuple[tuple[int, int, int], ...],
    float,
] | None:
    parent = list(range(len(vertices)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    edges = {
        tuple(sorted((int(triangle[left]), int(triangle[right]))))
        for triangle in triangles
        for left, right in ((0, 1), (1, 2), (2, 0))
    }
    collapsed_count = 0
    for left, right in sorted(
        edges,
        key=lambda edge: (
            dist(vertices[edge[0]], vertices[edge[1]]),
            vertices[edge[0]],
            vertices[edge[1]],
        ),
    ):
        if abs(vertices[left][2] - vertices[right][2]) > 1e-12:
            continue
        if dist(vertices[left], vertices[right]) >= maximum_length:
            continue
        left_root, right_root = root(left), root(right)
        if left_root == right_root:
            continue
        retained, removed = sorted(
            (left_root, right_root),
            key=lambda index: (vertices[index], index),
        )
        parent[removed] = retained
        collapsed_count += 1
    if not collapsed_count:
        return None

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
    clean_vertices = tuple(vertices[index] for index in used)
    clean_triangles = tuple(sorted(
        (
            _rotate_triangle(tuple(compact[index] for index in triangle))
            for triangle in surviving
        ),
        key=lambda triangle: tuple(
            clean_vertices[index] for index in triangle
        ),
    ))
    displacement = max(
        dist(vertices[index], vertices[root(index)])
        for index in range(len(vertices))
    )
    if displacement > maximum_length + 1e-15:
        return None
    return clean_vertices, clean_triangles, displacement


def _numeric_triangle_gate_passes(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
) -> bool:
    for triangle in triangles:
        try:
            a, b, c = (vertices[int(index)] for index in triangle)
        except (IndexError, TypeError, ValueError):
            return False
        if min(dist(a, b), dist(b, c), dist(c, a)) < COLLAPSE_THRESHOLD_M:
            return False
        u = tuple(b[index] - a[index] for index in range(3))
        v = tuple(c[index] - a[index] for index in range(3))
        cross = (
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        )
        if 0.5 * sum(value * value for value in cross) ** 0.5 < 1e-10:
            return False
    return bool(vertices and triangles)


def _kernel_simplified_mesh(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
    *,
    tolerance_m: float,
) -> tuple[
    tuple[tuple[float, float, float], ...],
    tuple[tuple[int, int, int], ...],
    float,
] | None:
    """Remove only kernel-proven collinear sliver faces after edge collapse."""

    try:
        mesh = m3d.Mesh(
            np.asarray(vertices, dtype=np.float64),
            np.asarray(triangles, dtype=np.uint32),
        )
        mesh.merge()
        solid = m3d.Manifold(mesh)
        simplified = solid.simplify(float(tolerance_m))
        exported = simplified.to_mesh64()
        simplified_vertices = tuple(
            tuple(float(value) for value in row[:3])
            for row in np.asarray(
                exported.vert_properties,
                dtype=float,
            )
        )
        simplified_triangles = tuple(
            tuple(int(value) for value in row)
            for row in np.asarray(
                exported.tri_verts,
                dtype=np.int64,
            )
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None
    if (
        simplified.is_empty()
        or "NoError" not in str(simplified.status())
        or len(simplified.decompose()) != 1
        or not _numeric_triangle_gate_passes(
            simplified_vertices,
            simplified_triangles,
        )
    ):
        return None
    displacement = max(
        (
            min(
                dist(vertex, original)
                for original in vertices
            )
            for vertex in simplified_vertices
        ),
        default=0.0,
    )
    return (
        simplified_vertices,
        simplified_triangles,
        displacement,
    )


def _indexed_mesh_section_polygon(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
    z: float,
) -> Polygon | None:
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
        or len(solid.decompose()) != 1
        or section.is_empty()
        or not contours
    ):
        return None
    polygon = None
    for contour in contours:
        ring = Polygon([
            (float(point[0]), float(point[1]))
            for point in contour
        ])
        if (
            ring.is_empty
            or not ring.is_valid
            or float(ring.area) <= 1e-10
        ):
            continue
        polygon = (
            ring
            if polygon is None
            else polygon.symmetric_difference(ring)
        )
    return polygon if _single_polygon(polygon) else None


def _section_equivalence(
    measured: Polygon | None,
    expected: Polygon,
    *,
    epsilon_m: float,
) -> dict[str, float] | None:
    if not _single_polygon(measured) or not _single_polygon(expected):
        return None
    assert measured is not None
    area_delta = abs(float(measured.area) - float(expected.area))
    symdiff = float(measured.symmetric_difference(expected).area)
    hausdorff = float(
        measured.boundary.hausdorff_distance(expected.boundary)
    )
    area_bound = (
        SECTION_BASE_EPSILON_M
        + float(expected.length) * epsilon_m
    )
    if (
        not all(isfinite(value) for value in (
            area_delta,
            symdiff,
            hausdorff,
            area_bound,
        ))
        or area_delta > area_bound
        or symdiff > area_bound
        or hausdorff > epsilon_m
    ):
        return None
    return {
        "area_delta_m2": area_delta,
        "symdiff_m2": symdiff,
        "hausdorff_m": hausdorff,
        "area_bound_m2": area_bound,
    }


def _single_polygon(value: Any) -> bool:
    return bool(
        isinstance(value, Polygon)
        and not value.is_empty
        and value.is_valid
        and float(value.area) > 1e-8
    )


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
    "CAPACITY_REPLAY_TRANSPORT_SCHEMA",
    "COLLAPSE_THRESHOLD_M",
    "CapacityReplayNumericTransport",
    "indexed_mesh_hash",
    "repair_capacity_replay_mesh",
]
