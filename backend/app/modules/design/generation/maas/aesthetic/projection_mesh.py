"""Facade mesh and UV manifest builder for MAAS aesthetic projection."""

from __future__ import annotations

import math
from typing import Any


ATLAS_LAYOUT = {
    "front": [0.0, 0.0, 0.333333, 0.5],
    "right": [0.333333, 0.0, 0.333333, 0.5],
    "back": [0.666667, 0.0, 0.333333, 0.5],
    "left": [0.0, 0.5, 0.333333, 0.5],
    "axon": [0.333333, 0.5, 0.333333, 0.5],
    "top": [0.666667, 0.5, 0.333333, 0.5],
}


def build_projection_manifest(volumes: list[dict[str, Any]], bounds: dict[str, float]) -> dict[str, Any]:
    """Build a projection-ready facade mesh manifest.

    This is intentionally a JSON contract, not a renderer-specific mesh format.
    It gives the next UV bake worker stable facade surface IDs, 3D vertices in
    the same local-meter space as the condition pack, and normalized UVs inside
    the provider multi-view atlas panels.
    """

    surfaces: list[dict[str, Any]] = []
    origin = [float(bounds["origin_lng"]), float(bounds["origin_lat"])]

    for volume_index, volume in enumerate(volumes):
        ring = _open_ring(volume.get("ring") or [])
        if len(ring) < 3:
            continue
        local = [_to_local(point, origin) for point in ring]
        cx = sum(point[0] for point in local) / len(local)
        cy = sum(point[1] for point in local) / len(local)
        bottom = float(volume.get("bottom") or 0.0)
        top = float(volume.get("top") or bottom)
        if top <= bottom:
            continue

        for edge_index, (a, b) in enumerate(_edges(local)):
            edge_len = math.dist(a, b)
            if edge_len <= 0.01:
                continue
            view = _view_for_edge(a, b, cx, cy)
            panel = ATLAS_LAYOUT[view]

            vertices = [
                [round(a[0], 4), round(a[1], 4), round(bottom, 4)],
                [round(b[0], 4), round(b[1], 4), round(bottom, 4)],
                [round(b[0], 4), round(b[1], 4), round(top, 4)],
                [round(a[0], 4), round(a[1], 4), round(top, 4)],
            ]
            u0, v0, uw, vh = panel
            axis0, axis1, axis_min, axis_max = _projection_axis_for_view(view, a, b, bounds)
            left_u, right_u = sorted([
                _normalize(axis0, axis_min, axis_max),
                _normalize(axis1, axis_min, axis_max),
            ])
            bottom_v = 1.0 - _normalize(bottom, bounds["min_z"], bounds["max_z"])
            top_v = 1.0 - _normalize(top, bounds["min_z"], bounds["max_z"])
            uvs = [
                [round(u0 + left_u * uw, 6), round(v0 + bottom_v * vh, 6)],
                [round(u0 + right_u * uw, 6), round(v0 + bottom_v * vh, 6)],
                [round(u0 + right_u * uw, 6), round(v0 + top_v * vh, 6)],
                [round(u0 + left_u * uw, 6), round(v0 + top_v * vh, 6)],
            ]
            surfaces.append({
                "id": f"facade_surface_v{volume_index}_e{edge_index}",
                "volume_id": volume.get("id") or f"volume_{volume_index}",
                "view": view,
                "plane_id": f"facade_{view}",
                "source_panel_role": "facade_panel_image",
                "source_panel_view": view,
                "vertices_m": vertices,
                "uv": uvs,
                "triangles": [[0, 1, 2], [0, 2, 3]],
                "metrics": {
                    "edge_length_m": round(edge_len, 4),
                    "height_m": round(top - bottom, 4),
                    "area_m2": round(edge_len * (top - bottom), 4),
                },
            })

        roof_surface = _roof_surface(volume_index, volume, local, top, bounds)
        if roof_surface:
            surfaces.append(roof_surface)

    return {
        "schema_version": "arr.maas.projection_manifest.v0",
        "coordinate_space": "local_meter_from_first_mass_point",
        "origin": {"lng": origin[0], "lat": origin[1]},
        "atlas": {
            "layout": "multiview_3x2_normalized",
            "views": {
                view: {"uv_rect": rect}
                for view, rect in ATLAS_LAYOUT.items()
            },
        },
        "surfaces": surfaces,
        "notes": [
            "Derived from locked MAAS geometry; does not change legal evidence.",
            "UVs are first-pass per-facade atlas assignments for a later texture bake worker.",
        ],
    }


def _open_ring(ring: list[Any]) -> list[list[float]]:
    points = [[float(p[0]), float(p[1])] for p in ring if isinstance(p, (list, tuple)) and len(p) >= 2]
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    return points


def _edges(points: list[tuple[float, float]]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return [(points[i], points[(i + 1) % len(points)]) for i in range(len(points))]


def _view_for_edge(a: tuple[float, float], b: tuple[float, float], cx: float, cy: float) -> str:
    mx = (a[0] + b[0]) / 2
    my = (a[1] + b[1]) / 2
    dx = mx - cx
    dy = my - cy
    if abs(dx) > abs(dy):
        return "right" if dx >= 0 else "left"
    return "back" if dy >= 0 else "front"


def _projection_axis_for_view(
    view: str,
    a: tuple[float, float],
    b: tuple[float, float],
    bounds: dict[str, float],
) -> tuple[float, float, float, float]:
    if view in {"front", "back"}:
        return a[0], b[0], float(bounds["min_x"]), float(bounds["max_x"])
    return a[1], b[1], float(bounds["min_y"]), float(bounds["max_y"])


def _normalize(value: float, low: float, high: float) -> float:
    span = max(1e-9, high - low)
    return max(0.0, min(1.0, (value - low) / span))


def _roof_surface(
    volume_index: int,
    volume: dict[str, Any],
    local: list[tuple[float, float]],
    top: float,
    bounds: dict[str, float],
) -> dict[str, Any] | None:
    if len(local) < 3:
        return None
    panel = ATLAS_LAYOUT["top"]
    u0, v0, uw, vh = panel
    vertices = [[round(x, 4), round(y, 4), round(top, 4)] for x, y in local]
    uvs = [
        [
            round(u0 + _normalize(x, bounds["min_x"], bounds["max_x"]) * uw, 6),
            round(v0 + (1.0 - _normalize(y, bounds["min_y"], bounds["max_y"])) * vh, 6),
        ]
        for x, y in local
    ]
    triangles = [[0, i, i + 1] for i in range(1, len(local) - 1)]
    return {
        "id": f"roof_surface_v{volume_index}",
        "volume_id": volume.get("id") or f"volume_{volume_index}",
        "view": "top",
        "plane_id": "facade_top",
        "source_panel_role": "facade_panel_image",
        "source_panel_view": "top",
        "vertices_m": vertices,
        "uv": uvs,
        "triangles": triangles,
        "metrics": {
            "height_m": round(top, 4),
            "area_m2": round(_polygon_area(local), 4),
        },
    }


def _polygon_area(points: list[tuple[float, float]]) -> float:
    area = 0.0
    for a, b in _edges(points):
        area += a[0] * b[1] - b[0] * a[1]
    return abs(area) / 2


def _to_local(point: list[float], origin: list[float]) -> tuple[float, float]:
    lat = origin[1]
    meters_per_lng = max(1.0, 111_320.0 * math.cos(lat * math.pi / 180.0))
    return (point[0] - origin[0]) * meters_per_lng, (point[1] - origin[1]) * 110_540.0


__all__ = ["build_projection_manifest"]
