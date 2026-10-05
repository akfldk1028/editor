"""Agent-authored oblique polygon-ring envelopes.

The graph supplies a normalized plan polygon and transformations for its base,
shoulder and top rings.  This module projects that genotype into the current
mass footprint.  It contains no named precedent outline, parcel coordinate or
fixed museum template; wedge, lean and undercut forms are consequences of the
authored ring relationship.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, degrees, radians, sin
from typing import Any

from shapely.affinity import rotate
from shapely.geometry import Polygon
from shapely.ops import unary_union


Point3 = tuple[float, float, float]


@dataclass(frozen=True)
class ObliqueEnvelopeField:
    rings: tuple[tuple[Point3, ...], ...]
    proxy_footprint: Polygon
    bottom_fraction: float
    evidence: dict[str, Any]


def build_oblique_envelope_field(
    footprint: Polygon,
    params: dict[str, Any],
    *,
    bottom_fraction: float = 0.0,
    top_fraction: float = 1.0,
) -> ObliqueEnvelopeField | None:
    """Project one authored polygon-ring genotype through a parcel frame."""
    controls = _plan_controls(params.get("plan_control_points"))
    if len(controls) < 3 or footprint.is_empty or footprint.area <= 0:
        return None
    plan = Polygon(controls)
    if not plan.is_valid or plan.area < 0.025:
        return None

    bottom = max(0.0, min(0.82, _number(bottom_fraction, 0.0, 0.0, 0.82)))
    top = max(bottom + 0.12, min(1.0, _number(top_fraction, 1.0, bottom + 0.12, 1.0)))
    shoulder_fraction = _number(params.get("shoulder_fraction"), 0.28, 0.12, 0.68)
    shoulder_z = bottom + (top - bottom) * shoulder_fraction
    base_scale_x = _number(params.get("base_scale_x_ratio"), 0.72, 0.28, 1.0)
    base_scale_y = _number(params.get("base_scale_y_ratio"), 0.72, 0.28, 1.0)
    base_shift_x = _number(params.get("base_shift_x_ratio"), 0.0, -0.28, 0.28)
    base_shift_y = _number(params.get("base_shift_y_ratio"), 0.0, -0.28, 0.28)
    top_scale_x = _number(params.get("top_scale_x_ratio"), 0.82, 0.08, 1.12)
    top_scale_y = _number(params.get("top_scale_y_ratio"), 0.82, 0.08, 1.12)
    top_shift_x = _number(params.get("top_shift_x_ratio"), 0.0, -0.30, 0.30)
    top_shift_y = _number(params.get("top_shift_y_ratio"), 0.0, -0.30, 0.30)
    top_heights = _height_controls(params.get("top_height_controls"), len(controls))

    frame_angle = _dominant_axis_degrees(footprint)
    origin = (float(footprint.centroid.x), float(footprint.centroid.y))
    local = rotate(footprint, -frame_angle, origin=origin, use_radians=False)
    minx, miny, maxx, maxy = local.bounds
    width, depth = maxx - minx, maxy - miny
    if width <= 0 or depth <= 0:
        return None

    def ring(
        *,
        scale_x: float,
        scale_y: float,
        shift_x: float,
        shift_y: float,
        heights: tuple[float, ...],
    ) -> tuple[Point3, ...]:
        points: list[Point3] = []
        for index, (u, v) in enumerate(controls):
            transformed_u = 0.5 + (u - 0.5) * scale_x + shift_x
            transformed_v = 0.5 + (v - 0.5) * scale_y + shift_y
            # Keep the authored envelope inside the conservative oriented
            # parcel frame. The later legal projection remains authoritative
            # for irregular/concave parcels.
            transformed_u = max(0.025, min(0.975, transformed_u))
            transformed_v = max(0.025, min(0.975, transformed_v))
            local_point = (minx + width * transformed_u, miny + depth * transformed_v)
            world_x, world_y = _rotate_point(local_point, frame_angle, origin)
            points.append((world_x, world_y, heights[index]))
        return tuple(points)

    bottom_ring = ring(
        scale_x=base_scale_x,
        scale_y=base_scale_y,
        shift_x=base_shift_x,
        shift_y=base_shift_y,
        heights=tuple(bottom for _ in controls),
    )
    shoulder_ring = ring(
        scale_x=1.0,
        scale_y=1.0,
        shift_x=0.0,
        shift_y=0.0,
        heights=tuple(shoulder_z for _ in controls),
    )
    top_ring = ring(
        scale_x=top_scale_x,
        scale_y=top_scale_y,
        shift_x=top_shift_x,
        shift_y=top_shift_y,
        heights=tuple(bottom + (top - bottom) * height for height in top_heights),
    )
    ring_polygons = [Polygon([(x, y) for x, y, _ in item]) for item in (bottom_ring, shoulder_ring, top_ring)]
    if any(not polygon.is_valid or polygon.area <= 0 for polygon in ring_polygons):
        return None
    proxy = unary_union(ring_polygons)
    if not isinstance(proxy, Polygon):
        proxy = proxy.convex_hull
    if proxy.is_empty or proxy.area <= 0:
        return None

    displacement = max(
        abs(base_shift_x), abs(base_shift_y), abs(top_shift_x), abs(top_shift_y),
        abs(1.0 - base_scale_x), abs(1.0 - base_scale_y),
        abs(1.0 - top_scale_x), abs(1.0 - top_scale_y),
    )
    return ObliqueEnvelopeField(
        rings=(bottom_ring, shoulder_ring, top_ring),
        proxy_footprint=proxy,
        bottom_fraction=bottom,
        evidence={
            "schema_version": "arr.maas.site_oblique_envelope.v1",
            "field_type": "agent_authored_oblique_polygon_rings",
            "coordinate_frame": "minimum_rotated_parcel_axis",
            "coordinate_template": False,
            "plan_control_point_count": len(controls),
            "plan_control_points": [[round(u, 4), round(v, 4)] for u, v in controls],
            "ring_count": 3,
            "shoulder_fraction": round(shoulder_fraction, 4),
            "base_scale": [round(base_scale_x, 4), round(base_scale_y, 4)],
            "base_shift": [round(base_shift_x, 4), round(base_shift_y, 4)],
            "top_scale": [round(top_scale_x, 4), round(top_scale_y, 4)],
            "top_shift": [round(top_shift_x, 4), round(top_shift_y, 4)],
            "top_height_controls": [round(value, 4) for value in top_heights],
            "top_height_range": round(max(top_heights) - min(top_heights), 4),
            "oblique_displacement": round(displacement, 4),
            "proxy_area_ratio": round(float(proxy.area) / max(float(footprint.area), 1e-9), 4),
            "dominant_axis_world_degrees": round(frame_angle, 4),
            "source": str(params.get("design_field_source") or "mass_graph_parameters"),
        },
    )


def _plan_controls(value: Any) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, list):
        return ()
    points: list[tuple[float, float]] = []
    for item in value[:8]:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        try:
            u, v = float(item[0]), float(item[1])
        except (TypeError, ValueError):
            continue
        points.append((max(0.02, min(0.98, u)), max(0.02, min(0.98, v))))
    return tuple(points)


def _height_controls(value: Any, count: int) -> tuple[float, ...]:
    if isinstance(value, list) and len(value) == count:
        try:
            return tuple(max(0.42, min(1.0, float(item))) for item in value)
        except (TypeError, ValueError):
            pass
    return tuple(1.0 for _ in range(count))


def _dominant_axis_degrees(footprint: Polygon) -> float:
    coordinates = list(footprint.minimum_rotated_rectangle.exterior.coords)[:4]
    edges = [
        (left, right, (right[0] - left[0]) ** 2 + (right[1] - left[1]) ** 2)
        for left, right in zip(coordinates, coordinates[1:] + coordinates[:1])
    ]
    if not edges:
        return 0.0
    left, right, _ = max(edges, key=lambda item: item[2])
    angle = degrees(atan2(right[1] - left[1], right[0] - left[0]))
    while angle >= 90.0:
        angle -= 180.0
    while angle < -90.0:
        angle += 180.0
    return angle


def _rotate_point(point: tuple[float, float], angle_degrees: float, origin: tuple[float, float]) -> tuple[float, float]:
    angle = radians(angle_degrees)
    cosine, sine = cos(angle), sin(angle)
    dx, dy = point[0] - origin[0], point[1] - origin[1]
    return origin[0] + dx * cosine - dy * sine, origin[1] + dx * sine + dy * cosine


def _number(value: Any, default: float, low: float, high: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


__all__ = ["ObliqueEnvelopeField", "build_oblique_envelope_field"]
