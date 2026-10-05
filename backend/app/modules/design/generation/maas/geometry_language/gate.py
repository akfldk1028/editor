"""Hard validation policy for compiled architectural solid programs."""

from __future__ import annotations

from dataclasses import dataclass
from math import dist
from typing import Any

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryIssue


@dataclass(frozen=True)
class GeometryGatePolicy:
    maximum_nodes: int = 96
    maximum_depth: int = 32
    maximum_triangles: int = 12_000
    maximum_components: int = 5
    maximum_extent: float = 1_000.0
    minimum_volume: float = 1e-4
    minimum_edge_length: float = 1e-5
    minimum_triangle_area: float = 1e-10


def compilation_gate(result: Any, policy: GeometryGatePolicy | None = None) -> tuple[GeometryIssue, ...]:
    policy = policy or GeometryGatePolicy()
    issues: list[GeometryIssue] = []
    if getattr(result, "status", "failed") != "compiled":
        return tuple(getattr(result, "issues", ()) or (GeometryIssue("compile_failed", "solid did not compile"),))
    metrics = getattr(result, "metrics", {}) or {}
    for key, code, message in (
        ("watertight", "non_watertight_mesh", "compiled mesh is not watertight"),
        ("manifold", "non_manifold_mesh", "compiled mesh is not manifold"),
        ("closed_solid", "open_solid", "compiled geometry is not a closed solid"),
        ("self_intersection_checked_by_kernel", "self_intersection_unchecked", "self-intersection was not checked by the kernel"),
        ("outward_normals", "inverted_normals", "mesh winding does not produce outward normals"),
    ):
        if metrics.get(key) is not True:
            issues.append(GeometryIssue(code, message))
    if float(metrics.get("volume") or 0.0) < policy.minimum_volume:
        issues.append(GeometryIssue("empty_or_tiny_solid", "compiled volume is below the hard minimum"))
    if int(metrics.get("triangle_count") or 0) > policy.maximum_triangles:
        issues.append(GeometryIssue("mesh_complexity_exceeded", "triangle budget exceeded"))
    if int(metrics.get("component_count") or 0) > policy.maximum_components:
        issues.append(GeometryIssue("disconnected_component_budget_exceeded", "too many disconnected solid components"))
    bounds = metrics.get("bounds") or []
    if isinstance(bounds, list) and len(bounds) == 2:
        try:
            extents = [abs(float(bounds[1][axis]) - float(bounds[0][axis])) for axis in range(3)]
            if max(extents) > policy.maximum_extent:
                issues.append(GeometryIssue("bounding_box_exceeded", "solid exceeds permitted compiler extent"))
        except (TypeError, ValueError, IndexError):
            issues.append(GeometryIssue("invalid_bounding_box", "compiler returned an invalid bounding box"))
    vertices = getattr(result, "vertices", ()) or ()
    triangles = getattr(result, "triangles", ()) or ()
    for triangle in triangles:
        try:
            a, b, c = (vertices[int(index)] for index in triangle)
            lengths = (dist(a, b), dist(b, c), dist(c, a))
            if min(lengths) < policy.minimum_edge_length:
                issues.append(GeometryIssue("tiny_edge", "mesh contains an edge below tolerance"))
                break
            ux, uy, uz = (b[i] - a[i] for i in range(3))
            vx, vy, vz = (c[i] - a[i] for i in range(3))
            cross = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
            area2 = sum(value * value for value in cross) ** 0.5
            if area2 * 0.5 < policy.minimum_triangle_area:
                issues.append(GeometryIssue("tiny_face", "mesh contains a face below tolerance"))
                break
        except (TypeError, ValueError, IndexError):
            issues.append(GeometryIssue("invalid_mesh_index", "triangle references an invalid vertex"))
            break
    return tuple(issues)


__all__ = ["GeometryGatePolicy", "compilation_gate"]
