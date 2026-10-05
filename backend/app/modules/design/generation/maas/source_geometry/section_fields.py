"""Agent-authored, site-conditioned section-loft fields.

The graph owns a normalized section profile.  This module only projects that
profile through cross-sections of the current parcel/mass footprint.  It does
not contain named-building templates or parcel coordinates, and the legal
volume remains a separate conservative proxy.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, degrees, pi, radians, sin
from typing import Any

from shapely.affinity import rotate
from shapely.geometry import LineString, MultiLineString, Polygon

from backend.app.modules.design.generation.maas.source_geometry.parametric_curves import catmull_rom_path


@dataclass(frozen=True)
class SectionLoftField:
    rows: tuple[tuple[tuple[float, float, float], ...], ...]
    bottom_fraction: float
    evidence: dict[str, Any]


def build_section_loft_field(
    footprint: Polygon,
    params: dict[str, Any],
    *,
    bottom_fraction: float = 0.0,
    top_fraction: float = 1.0,
) -> SectionLoftField | None:
    """Loft an authored normalized section through the mass's local frame."""
    authored_controls = _control_points(params.get("control_points"))
    if len(authored_controls) < 4 or footprint.is_empty or footprint.area <= 0:
        return None
    interpolation = str(params.get("section_interpolation") or "smooth").strip().lower()
    interpolation = interpolation if interpolation in {"linear", "smooth"} else "smooth"
    controls = (
        _smooth_section_controls(authored_controls, count=7)
        if interpolation == "smooth"
        else authored_controls
    )
    bottom = max(0.0, min(0.90, float(bottom_fraction)))
    top = max(bottom + 0.08, min(1.0, float(top_fraction)))
    authored_station_count = _integer(params.get("field_samples"), default=5, low=5, high=9)
    # Early mass review has a hard clean-surface budget of 48. A 7x5 or 9x6
    # loft plus one retained connector crosses that budget without adding a
    # new architectural decision. Preserve the authored resolution as
    # provenance while compiling a five-station review LOD; a later detail
    # stage may resample the same genotype at the authored density.
    station_count = min(5, authored_station_count)
    wave = _number(params.get("longitudinal_wave"), 0.0, -0.24, 0.24)
    twist = _number(params.get("twist"), 0.0, -0.30, 0.30)
    axis = str(params.get("axis") or "x").strip().lower()
    axis = axis if axis in {"x", "y"} else "x"

    frame_angle = _dominant_axis_degrees(footprint)
    origin = (float(footprint.centroid.x), float(footprint.centroid.y))
    local = rotate(footprint, -frame_angle, origin=origin, use_radians=False)
    minx, miny, maxx, maxy = local.bounds
    length = (maxx - minx) if axis == "x" else (maxy - miny)
    if length <= 0:
        return None

    rows: list[tuple[tuple[float, float, float], ...]] = []
    for station_index in range(station_count):
        u = 0.03 + 0.94 * station_index / max(station_count - 1, 1)
        station = (minx + length * u) if axis == "x" else (miny + length * u)
        cross = _cross_section(local, station=station, axis=axis, padding=max(maxx - minx, maxy - miny) * 0.08)
        if cross is None:
            continue
        low, high = cross
        row: list[tuple[float, float, float]] = []
        for section_position, authored_height in controls:
            cross_value = low + (high - low) * section_position
            local_point = (station, cross_value) if axis == "x" else (cross_value, station)
            world_x, world_y = _rotate_point(local_point, frame_angle, origin)
            field_height = (
                authored_height
                + wave * sin(u * 2.0 * pi)
                + twist * (u - 0.5) * (section_position - 0.5) * 2.0
            )
            normalized_height = max(0.10, min(0.98, field_height))
            z = bottom + (top - bottom) * normalized_height
            row.append((world_x, world_y, z))
        if len(row) == len(controls):
            rows.append(tuple(row))
    if len(rows) < 3:
        return None
    heights = [height for _, height in authored_controls]
    segment_slopes = [
        abs(right[1] - left[1]) / max(right[0] - left[0], 1e-9)
        for left, right in zip(authored_controls, authored_controls[1:])
    ]
    return SectionLoftField(
        rows=tuple(rows),
        bottom_fraction=bottom,
        evidence={
            "schema_version": "arr.maas.site_section_loft.v1",
            "field_type": "agent_authored_section_loft",
            "coordinate_frame": "minimum_rotated_parcel_axis",
            "coordinate_template": False,
            "axis": axis,
            "dominant_axis_world_degrees": round(frame_angle, 4),
            "station_count": len(rows),
            "authored_station_count": authored_station_count,
            "review_lod_station_count": station_count,
            "section_control_point_count": len(authored_controls),
            "compiled_section_point_count": len(controls),
            "section_interpolation": interpolation,
            "control_points": [[round(u, 4), round(z, 4)] for u, z in authored_controls],
            "section_height_range": round(max(heights) - min(heights), 4),
            "profile_total_variation": round(sum(abs(right - left) for left, right in zip(heights, heights[1:])), 4),
            "max_normalized_segment_slope": round(max(segment_slopes, default=0.0), 4),
            "longitudinal_wave": round(wave, 4),
            "twist": round(twist, 4),
            "source": str(params.get("design_field_source") or "mass_graph_parameters"),
        },
    )


def _control_points(value: Any) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, list):
        return ()
    points: list[tuple[float, float]] = []
    for item in value[:6]:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        try:
            position, height = float(item[0]), float(item[1])
        except (TypeError, ValueError):
            continue
        points.append((max(0.03, min(0.97, position)), max(0.12, min(0.88, height))))
    points.sort(key=lambda point: point[0])
    if any(right[0] - left[0] < 0.02 for left, right in zip(points, points[1:])):
        return ()
    return tuple(points)


def _smooth_section_controls(
    controls: tuple[tuple[float, float], ...],
    *,
    count: int,
) -> tuple[tuple[float, float], ...]:
    """Resample an authored profile as one bounded C1 section curve."""
    dense = catmull_rom_path(controls, samples_per_span=4)
    dense = tuple(sorted(
        (
            max(controls[0][0], min(controls[-1][0], float(position))),
            max(0.10, min(0.92, float(height))),
        )
        for position, height in dense
    ))
    if len(dense) < 2:
        return controls
    sample_count = max(len(controls), min(7, int(count)))
    low, high = controls[0][0], controls[-1][0]
    result: list[tuple[float, float]] = []
    for index in range(sample_count):
        position = low + (high - low) * index / max(sample_count - 1, 1)
        left, right = dense[0], dense[-1]
        for dense_left, dense_right in zip(dense, dense[1:]):
            if dense_left[0] <= position <= dense_right[0]:
                left, right = dense_left, dense_right
                break
        alpha = (position - left[0]) / max(right[0] - left[0], 1e-9)
        height = left[1] + (right[1] - left[1]) * alpha
        result.append((position, max(0.10, min(0.92, height))))
    return tuple(result)


def _cross_section(footprint: Polygon, *, station: float, axis: str, padding: float) -> tuple[float, float] | None:
    minx, miny, maxx, maxy = footprint.bounds
    line = (
        LineString(((station, miny - padding), (station, maxy + padding)))
        if axis == "x"
        else LineString(((minx - padding, station), (maxx + padding, station)))
    )
    intersection = footprint.intersection(line)
    lines = [intersection] if isinstance(intersection, LineString) else (
        list(intersection.geoms) if isinstance(intersection, MultiLineString) else
        [item for item in getattr(intersection, "geoms", ()) if isinstance(item, LineString)]
    )
    if not lines:
        return None
    longest = max(lines, key=lambda item: item.length)
    values = [float(point[1] if axis == "x" else point[0]) for point in longest.coords]
    return min(values), max(values)


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


def _integer(value: Any, *, default: int, low: int, high: int) -> int:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


__all__ = ["SectionLoftField", "build_section_loft_field"]
