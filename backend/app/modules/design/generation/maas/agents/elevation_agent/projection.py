"""Deterministic orthographic projection of indexed MASS triangle meshes."""

from __future__ import annotations

import hashlib
from math import cos, radians, sqrt
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageDraw

from backend.app.modules.design.generation.maas.agents.elevation_agent.contract import ElevationViewArtifact


CAMERA_CONTRACTS: dict[str, dict[str, tuple[float, float, float]]] = {
    "front": {"direction": (0, -1, 0), "up": (0, 0, 1)},
    "right": {"direction": (1, 0, 0), "up": (0, 0, 1)},
    "back": {"direction": (0, 1, 0), "up": (0, 0, 1)},
    "left": {"direction": (-1, 0, 0), "up": (0, 0, 1)},
    "top": {"direction": (0, 0, 1), "up": (0, 1, 0)},
    "axon": {"direction": (1, -1, 0.9), "up": (0, 0, 1)},
}


def render_mesh_views(
    vertices: Sequence[Sequence[float]],
    triangles: Sequence[Sequence[int]],
    output_directory: Path,
    *,
    execution_id: str,
    size: int = 720,
) -> tuple[ElevationViewArtifact, ...]:
    output_directory.mkdir(parents=True, exist_ok=True)
    return tuple(
        _render_view(
            view,
            vertices,
            triangles,
            output_directory / f"{view}.png",
            execution_id=execution_id,
            size=size,
        )
        for view in ("front", "right", "back", "left", "top", "axon")
    )


def triangle_normals(
    vertices: Sequence[Sequence[float]],
    triangles: Sequence[Sequence[int]],
) -> list[list[float]]:
    result: list[list[float]] = []
    for triangle in triangles:
        a, b, c = (vertices[int(index)] for index in triangle)
        ab = tuple(float(b[i]) - float(a[i]) for i in range(3))
        ac = tuple(float(c[i]) - float(a[i]) for i in range(3))
        normal = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        result.append([round(value, 8) for value in _unit(normal)])
    return result


def _render_view(
    view: str,
    vertices: Sequence[Sequence[float]],
    triangles: Sequence[Sequence[int]],
    output: Path,
    *,
    execution_id: str,
    size: int,
) -> ElevationViewArtifact:
    horizontal, vertical, depth_axis = camera_axes(view)
    projected = [
        (_dot(vertex, horizontal), _dot(vertex, vertical), _dot(vertex, depth_axis))
        for vertex in vertices
    ]
    min_u, max_u = min(row[0] for row in projected), max(row[0] for row in projected)
    min_v, max_v = min(row[1] for row in projected), max(row[1] for row in projected)
    min_d, max_d = min(row[2] for row in projected), max(row[2] for row in projected)
    margin = 64
    usable = size - margin * 2
    scale = min(
        usable / max(max_u - min_u, 1e-9),
        usable / max(max_v - min_v, 1e-9),
    )
    offset_u = (size - (max_u - min_u) * scale) / 2.0
    offset_v = (size - (max_v - min_v) * scale) / 2.0

    def pixel(index: int) -> tuple[float, float]:
        u, v, _depth = projected[index]
        return (
            offset_u + (u - min_u) * scale,
            size - offset_v - (v - min_v) * scale,
        )

    image = Image.new("RGB", (size, size), (248, 248, 246))
    draw = ImageDraw.Draw(image)
    normals = [
        _triangle_normal(vertices, triangle)
        for triangle in triangles
    ]
    ordered_indices = sorted(
        range(len(triangles)),
        key=lambda triangle_index: sum(
            projected[int(index)][2]
            for index in triangles[triangle_index]
        ) / 3.0,
    )
    light = _unit((0.35, -0.45, 1.0))
    feature_edges = set(
        _visible_feature_edges(vertices, triangles, normals, depth_axis)
    )
    for triangle_index in ordered_indices:
        triangle = triangles[triangle_index]
        illumination = abs(_dot(normals[triangle_index], light))
        shade = int(220 - illumination * 42)
        draw.polygon(
            [pixel(int(index)) for index in triangle],
            fill=(shade, shade, max(0, shade - 3)),
        )
        for start, end in (
            (int(triangle[0]), int(triangle[1])),
            (int(triangle[1]), int(triangle[2])),
            (int(triangle[2]), int(triangle[0])),
        ):
            if _geometry_edge_key(vertices, start, end) in feature_edges:
                draw.line(
                    (pixel(start), pixel(end)),
                    fill=(43, 43, 41),
                    width=2,
                )
    draw.line((margin // 2, size - margin // 2, size - margin // 2, size - margin // 2), fill=(20, 20, 20), width=2)
    draw.text((24, 20), f"{view.upper()} / {execution_id}", fill=(18, 18, 18))
    image.save(output, format="PNG", optimize=True)
    return ElevationViewArtifact(
        view=view,
        path=str(output.resolve()),
        preview_url=f"/design/maas/single-executions/{execution_id}/elevation/{view}/",
        sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        width_px=size,
        height_px=size,
        projection_axes={
            "horizontal": list(horizontal),
            "vertical": list(vertical),
            "depth": list(depth_axis),
        },
        view_matrix4=[
            [*horizontal, 0.0],
            [*vertical, 0.0],
            [*depth_axis, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        projected_bounds=[
            [round(min_u, 8), round(min_v, 8)],
            [round(max_u, 8), round(max_v, 8)],
        ],
        depth_range=[round(min_d, 8), round(max_d, 8)],
    )


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(float(left[index]) * float(right[index]) for index in range(3))


def camera_axes(
    view: str,
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    contract = CAMERA_CONTRACTS[view]
    depth = _unit(contract["direction"])
    horizontal = _unit(_cross(contract["up"], depth))
    vertical = _unit(_cross(depth, horizontal))
    if horizontal == (0.0, 0.0, 0.0) or vertical == (0.0, 0.0, 0.0):
        raise ValueError(f"camera direction and up vector are parallel: {view}")
    return horizontal, vertical, depth


def _cross(
    left: Sequence[float],
    right: Sequence[float],
) -> tuple[float, float, float]:
    return (
        float(left[1]) * float(right[2]) - float(left[2]) * float(right[1]),
        float(left[2]) * float(right[0]) - float(left[0]) * float(right[2]),
        float(left[0]) * float(right[1]) - float(left[1]) * float(right[0]),
    )


def _triangle_normal(
    vertices: Sequence[Sequence[float]],
    triangle: Sequence[int],
) -> tuple[float, float, float]:
    a, b, c = (vertices[int(index)] for index in triangle)
    ab = tuple(float(b[i]) - float(a[i]) for i in range(3))
    ac = tuple(float(c[i]) - float(a[i]) for i in range(3))
    return _unit(_cross(ab, ac))


def _visible_feature_edges(
    vertices: Sequence[Sequence[float]],
    triangles: Sequence[Sequence[int]],
    normals: Sequence[Sequence[float]],
    camera_depth: Sequence[float],
    *,
    crease_degrees: float = 28.0,
) -> list[
    tuple[
        tuple[float, float, float],
        tuple[float, float, float],
    ]
]:
    adjacency: dict[
        tuple[
            tuple[float, float, float],
            tuple[float, float, float],
        ],
        list[int],
    ] = {}
    for triangle_index, triangle in enumerate(triangles):
        for start, end in (
            (int(triangle[0]), int(triangle[1])),
            (int(triangle[1]), int(triangle[2])),
            (int(triangle[2]), int(triangle[0])),
        ):
            edge = _geometry_edge_key(vertices, start, end)
            adjacency.setdefault(edge, []).append(triangle_index)
    threshold = cos(radians(crease_degrees))
    result: list[
        tuple[
            tuple[float, float, float],
            tuple[float, float, float],
        ]
    ] = []
    for edge, adjacent in adjacency.items():
        facing = [_dot(normals[index], camera_depth) for index in adjacent]
        if len(adjacent) == 1:
            if facing[0] >= 0.0:
                result.append(edge)
            continue
        normal_dot = _dot(normals[adjacent[0]], normals[adjacent[1]])
        silhouette = facing[0] * facing[1] <= 0.0
        crease = normal_dot < threshold
        if (silhouette or crease) and max(facing) >= 0.0:
            result.append(edge)
    return result


def _geometry_edge_key(
    vertices: Sequence[Sequence[float]],
    start: int,
    end: int,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
]:
    points = tuple(
        tuple(round(float(value), 8) for value in vertices[index])
        for index in (start, end)
    )
    return tuple(sorted(points))  # type: ignore[return-value]


def _unit(vector: Iterable[float]) -> tuple[float, float, float]:
    values = tuple(float(value) for value in vector)
    length = sqrt(sum(value * value for value in values))
    if length <= 1e-12:
        return (0.0, 0.0, 0.0)
    return tuple(value / length for value in values)  # type: ignore[return-value]


__all__ = ["CAMERA_CONTRACTS", "camera_axes", "render_mesh_views", "triangle_normals"]
