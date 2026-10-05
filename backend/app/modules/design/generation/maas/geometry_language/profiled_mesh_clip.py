"""Closed half-space clipping for renderer-authoritative profiled triangle meshes."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Sequence

from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, triangulate, unary_union

from backend.app.modules.design.generation.maas.source_geometry.ir import SourceSurface


_EPSILON = 1e-9
_ROUND_DIGITS = 8


@dataclass(frozen=True)
class ProfiledMeshClipResult:
    surfaces: tuple[SourceSurface, ...]
    boundary_loop_count: int
    removed_degenerate_count: int
    removed_duplicate_count: int
    closed_mesh_hard_pass: bool


def clip_profiled_mesh_above_z(
    surfaces: Sequence[SourceSurface],
    *,
    minimum_z: float,
) -> ProfiledMeshClipResult:
    """Intersect a closed profiled triangle mesh with ``z >= minimum_z``.

    Crossing triangles are geometrically clipped. The resulting plane boundary
    is polygonized and capped with downward-facing profiled underside triangles.
    A result is returned only when the complete output is a closed directed
    two-manifold.
    """

    plane_z = float(minimum_z)
    if not isfinite(plane_z):
        raise ValueError("piloti half-space plane must be finite")
    source = tuple(surfaces)
    if not source:
        raise ValueError("piloti half-space clip requires profiled triangles")

    clipped: list[SourceSurface] = []
    removed_degenerate = 0

    for surface in source:
        if (
            not surface.surface_type.startswith("profiled_")
            or len(surface.vertices_m) != 3
        ):
            raise ValueError("piloti half-space clip requires profiled triangles")
        triangle = tuple(_finite_vertex(vertex) for vertex in surface.vertices_m)
        polygon = _clip_triangle_above_z(triangle, minimum_z=plane_z)
        if len(polygon) < 3:
            continue
        pieces = _triangulate_convex_polygon(polygon)
        kept_piece_index = 0
        for piece in pieces:
            if _triangle_area_squared(piece) <= 0.0:
                removed_degenerate += 1
                continue
            kept_piece_index += 1
            clipped.append(SourceSurface(
                role=(
                    surface.role
                    if len(pieces) == 1
                    else f"{surface.role}:piloti_clip_{kept_piece_index:02d}"
                ),
                volume_role=surface.volume_role,
                verb=surface.verb,
                surface_type=surface.surface_type,
                vertices_m=piece,
                operator=surface.operator,
                semantic_patch_id=surface.semantic_patch_id,
            ))

    if not clipped:
        raise ValueError("piloti half-space clip removed the complete visual mesh")

    boundary_segments = _plane_boundary_segments(
        clipped,
        minimum_z=plane_z,
    )
    caps, boundary_loop_count = _underside_caps(
        boundary_segments,
        minimum_z=plane_z,
        template=source[0],
    )
    combined, removed_duplicates, extra_degenerate = _deduplicate_surfaces(
        (*clipped, *caps)
    )
    removed_degenerate += extra_degenerate
    if not combined or not _closed_directed_two_manifold(combined):
        raise ValueError("piloti half-space result is not a closed two-manifold")
    return ProfiledMeshClipResult(
        surfaces=combined,
        boundary_loop_count=boundary_loop_count,
        removed_degenerate_count=removed_degenerate,
        removed_duplicate_count=removed_duplicates,
        closed_mesh_hard_pass=True,
    )


def _finite_vertex(vertex: Iterable[float]) -> tuple[float, float, float]:
    values = tuple(float(value) for value in vertex)
    if len(values) != 3 or not all(isfinite(value) for value in values):
        raise ValueError("piloti visual triangle contains an invalid vertex")
    return values


def _clip_triangle_above_z(
    triangle: tuple[tuple[float, float, float], ...],
    *,
    minimum_z: float,
) -> tuple[tuple[float, float, float], ...]:
    output: list[tuple[float, float, float]] = []
    previous = triangle[-1]
    previous_inside = previous[2] >= minimum_z
    for current in triangle:
        current_inside = current[2] >= minimum_z
        if current_inside != previous_inside:
            output.append(_edge_plane_intersection(
                previous,
                current,
                minimum_z=minimum_z,
            ))
        if current_inside:
            output.append(current)
        previous = current
        previous_inside = current_inside
    return _deduplicate_ring_vertices(output)


def _edge_plane_intersection(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
    *,
    minimum_z: float,
) -> tuple[float, float, float]:
    left, right = sorted((left, right))
    if left[2] == minimum_z:
        return left
    if right[2] == minimum_z:
        return right
    delta = right[2] - left[2]
    if delta == 0.0:
        raise ValueError("piloti half-space edge is parallel to its clip plane")
    amount = (minimum_z - left[2]) / delta
    return (
        left[0] + (right[0] - left[0]) * amount,
        left[1] + (right[1] - left[1]) * amount,
        minimum_z,
    )


def _deduplicate_ring_vertices(
    vertices: Sequence[tuple[float, float, float]],
) -> tuple[tuple[float, float, float], ...]:
    result: list[tuple[float, float, float]] = []
    for vertex in vertices:
        if not result or _vertex_key(result[-1]) != _vertex_key(vertex):
            result.append(vertex)
    if len(result) > 1 and _vertex_key(result[0]) == _vertex_key(result[-1]):
        result.pop()
    return tuple(result)


def _plane_boundary_segments(
    surfaces: Sequence[SourceSurface],
    *,
    minimum_z: float,
) -> tuple[
    tuple[tuple[float, float, float], tuple[float, float, float]],
    ...,
]:
    counts: dict[
        tuple[tuple[float, float, float], tuple[float, float, float]],
        int,
    ] = {}
    representatives: dict[
        tuple[tuple[float, float, float], tuple[float, float, float]],
        tuple[tuple[float, float, float], tuple[float, float, float]],
    ] = {}
    for surface in surfaces:
        vertices = surface.vertices_m
        for left, right in zip(vertices, (*vertices[1:], vertices[0])):
            if (
                left[2] != minimum_z
                or right[2] != minimum_z
            ):
                continue
            key = tuple(sorted((_vertex_key(left), _vertex_key(right))))
            if key[0] == key[1]:
                continue
            counts[key] = counts.get(key, 0) + 1
            representatives.setdefault(key, (left, right))
    if any(count > 2 for count in counts.values()):
        raise ValueError("piloti half-space plane boundary is non-manifold")
    return tuple(
        representatives[key]
        for key, count in counts.items()
        if count == 1
    )


def _triangulate_convex_polygon(
    polygon: Sequence[tuple[float, float, float]],
) -> tuple[tuple[tuple[float, float, float], ...], ...]:
    if len(polygon) < 3:
        return ()
    return tuple(
        (polygon[0], polygon[index], polygon[index + 1])
        for index in range(1, len(polygon) - 1)
    )


def _underside_caps(
    segments: Sequence[
        tuple[tuple[float, float, float], tuple[float, float, float]]
    ],
    *,
    minimum_z: float,
    template: SourceSurface,
) -> tuple[tuple[SourceSurface, ...], int]:
    unique_segments = {
        tuple(sorted((_vertex_key(left), _vertex_key(right)))): (left, right)
        for left, right in segments
        if _vertex_key(left) != _vertex_key(right)
    }
    if not unique_segments:
        raise ValueError("piloti half-space plane does not intersect the mesh")
    lines = [
        LineString(((left[0], left[1]), (right[0], right[1])))
        for left, right in unique_segments.values()
    ]
    polygonized = [
        polygon
        for polygon in polygonize(unary_union(lines))
        if isinstance(polygon, Polygon)
        and not polygon.is_empty
        and float(polygon.area) > _EPSILON
    ]
    interior_ring_keys = {
        _plan_ring_edge_key(interior.coords)
        for polygon in polygonized
        for interior in polygon.interiors
    }
    loops = [
        polygon
        for polygon in polygonized
        if _plan_ring_edge_key(polygon.exterior.coords) not in interior_ring_keys
    ]
    loops.sort(key=lambda polygon: tuple(round(value, 8) for value in polygon.bounds))
    if not loops:
        raise ValueError("piloti half-space boundary does not form a loop")

    caps: list[SourceSurface] = []
    for loop_index, polygon in enumerate(loops, start=1):
        candidates = [
            triangle
            for triangle in triangulate(polygon)
            if (
                not triangle.is_empty
                and float(triangle.area) > _EPSILON
                and polygon.buffer(_EPSILON).covers(triangle)
            )
        ]
        candidates.sort(key=lambda triangle: (
            round(float(triangle.centroid.x), 8),
            round(float(triangle.centroid.y), 8),
            round(float(triangle.area), 8),
        ))
        for triangle_index, triangle in enumerate(candidates, start=1):
            coordinates = list(triangle.exterior.coords)[:3]
            vertices = tuple(
                (float(x), float(y), minimum_z)
                for x, y in coordinates
            )
            if _signed_plan_area_twice(vertices) > 0.0:
                vertices = (vertices[0], vertices[2], vertices[1])
            caps.append(SourceSurface(
                role=(
                    f"piloti:underside:{loop_index:02d}:"
                    f"{triangle_index:03d}"
                ),
                volume_role=template.volume_role,
                verb="piloti_void",
                surface_type="profiled_piloti_underside",
                vertices_m=vertices,
                operator="half_space_intersection",
                semantic_patch_id=f"piloti:underside:{loop_index:02d}",
            ))
    if not caps:
        raise ValueError("piloti half-space underside cannot be triangulated")
    boundary_loop_count = sum(
        1 + len(polygon.interiors)
        for polygon in loops
    )
    return tuple(caps), boundary_loop_count


def _deduplicate_surfaces(
    surfaces: Sequence[SourceSurface],
) -> tuple[tuple[SourceSurface, ...], int, int]:
    result: list[SourceSurface] = []
    seen: set[tuple[tuple[float, float, float], ...]] = set()
    duplicate_count = 0
    degenerate_count = 0
    for surface in surfaces:
        if _triangle_area_squared(surface.vertices_m) <= 0.0:
            degenerate_count += 1
            continue
        key = tuple(sorted(_vertex_key(vertex) for vertex in surface.vertices_m))
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        result.append(surface)
    return tuple(result), duplicate_count, degenerate_count


def _closed_directed_two_manifold(
    surfaces: Sequence[SourceSurface],
) -> bool:
    directed: dict[
        tuple[
            tuple[float, float, float],
            tuple[float, float, float],
        ],
        int,
    ] = {}
    for surface in surfaces:
        vertices = tuple(_vertex_key(vertex) for vertex in surface.vertices_m)
        if len(set(vertices)) != 3:
            return False
        for left, right in zip(vertices, (*vertices[1:], vertices[0])):
            directed[(left, right)] = directed.get((left, right), 0) + 1
    return bool(directed) and all(
        count == 1 and directed.get((right, left), 0) == 1
        for (left, right), count in directed.items()
    )


def _triangle_area_squared(
    vertices: Sequence[tuple[float, float, float]],
) -> float:
    if len(vertices) != 3:
        return 0.0
    left = tuple(vertices[1][index] - vertices[0][index] for index in range(3))
    right = tuple(vertices[2][index] - vertices[0][index] for index in range(3))
    cross = (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )
    return sum(value * value for value in cross)


def _signed_plan_area_twice(
    vertices: Sequence[tuple[float, float, float]],
) -> float:
    return sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(vertices, (*vertices[1:], vertices[0]))
    )


def _vertex_key(vertex: Iterable[float]) -> tuple[float, float, float]:
    return tuple(float(value) for value in vertex)


def _plan_ring_edge_key(coordinates: Iterable[Iterable[float]]) -> frozenset[
    tuple[tuple[float, float], tuple[float, float]]
]:
    vertices = [
        tuple(round(float(value), _ROUND_DIGITS) for value in coordinate[:2])
        for coordinate in coordinates
    ]
    if len(vertices) > 1 and vertices[0] == vertices[-1]:
        vertices.pop()
    return frozenset(
        tuple(sorted((left, right)))
        for left, right in zip(vertices, (*vertices[1:], vertices[0]))
    )


__all__ = ["ProfiledMeshClipResult", "clip_profiled_mesh_above_z"]
