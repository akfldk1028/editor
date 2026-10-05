"""Site-conditioned geometric fields consumed by procedural mass graphs.

The field builder does not choose an architectural style.  A graph/agent
chooses a lane count, width, curvature and vertical overlap; this module maps
those editable parameters onto the actual parcel cross-sections.  Compilers
therefore never carry parcel-specific coordinate templates.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, degrees, pi, radians, sin
from typing import Any

from shapely.affinity import rotate
from shapely.geometry import LineString, MultiLineString, Polygon


@dataclass(frozen=True)
class RibbonDesignField:
    paths: tuple[tuple[tuple[float, float], ...], ...]
    half_widths: tuple[float, ...]
    half_width_profiles: tuple[tuple[float, ...], ...]
    vertical_bands: tuple[tuple[float, float], ...]
    evidence: dict[str, Any]


def build_ribbon_design_field(footprint: Polygon, params: dict[str, Any]) -> RibbonDesignField | None:
    """Project an editable ribbon graph onto the parcel's local cross-sections."""
    if footprint.is_empty or footprint.area <= 0:
        return None
    # Work in the parcel's minimum-rotated long-axis frame. Axis-aligned world
    # sections kept geometry inside a rotated parcel but made its architectural
    # flow ignore the site. The local-frame transform is derived from geometry,
    # not from a parcel-specific coordinate recipe.
    frame_angle = _dominant_axis_degrees(footprint)
    origin = (float(footprint.centroid.x), float(footprint.centroid.y))
    local_footprint = rotate(footprint, -frame_angle, origin=origin, use_radians=False)
    minx, miny, maxx, maxy = local_footprint.bounds
    length, depth = maxx - minx, maxy - miny
    if length <= 0 or depth <= 0:
        return None

    lane_count = _integer(params.get("lane_count"), default=3, low=2, high=3)
    # Five authored control sections are enough for an early massing ribbon.
    # A default of seven made the compiler emit more than the clean-mass
    # surface budget, so agent-authored bend graphs were systematically
    # rejected while box graphs survived. Higher resolution remains an
    # explicit graph parameter for later design stages.
    sample_count = _integer(params.get("field_samples"), default=5, low=5, high=9)
    # Ratios are half-widths. A 0.04 default produced 3--4 m deep graphic
    # strips on a 40 m parcel: attractive as lines, but incapable of carrying
    # neighborhood floor area. Keep the parameter authored while enforcing an
    # occupiable early-massing range for this building-scale operator.
    # Keep this boundary identical to grammar.parameter_schema.  Search can
    # then thicken an authored field to meet a program's coverage/FAR target
    # instead of every candidate silently saturating at the old 0.11 cap.
    width_ratio = _number(params, ("lane_width_ratio", "bar_ratio", "width_ratio"), 0.10, 0.075, 0.22)
    explicit_curvature = any(key in params for key in ("curvature", "distance_ratio", "shift_ratio"))
    curvature = _number(params, ("curvature", "distance_ratio", "shift_ratio"), 0.08, -0.18, 0.18)
    if not explicit_curvature:
        angle = abs(_number(params, ("angle",), 24.0, 0.0, 45.0))
        curvature = max(0.07, min(0.17, angle / 190.0))
    phase = _number(params, ("field_phase", "phase"), 0.0, -1.0, 1.0)
    overlap = _number(params, ("vertical_overlap",), 0.22, 0.0, 0.38)
    width_gradient = _number(params, ("width_gradient",), 0.40, -0.48, 0.48)
    width_start_ratio = _number(params, ("width_start_ratio",), 0.72, 0.45, 1.35)
    width_mid_ratio = _number(params, ("width_mid_ratio",), 1.20, 0.65, 1.55)
    width_end_ratio = _number(params, ("width_end_ratio",), 0.78, 0.45, 1.35)
    width_wave = _number(params, ("width_wave",), 0.10, -0.28, 0.28)
    field_topology = str(params.get("field_topology") or "parallel").strip().lower()
    if field_topology not in {"parallel", "branched"}:
        field_topology = "parallel"
    branch_point_ratio = _number(params, ("branch_point_ratio",), 0.36, 0.22, 0.58)
    height_start_ratio = _number(params, ("height_start_ratio",), 0.64, 0.40, 1.00)
    height_mid_ratio = _number(params, ("height_mid_ratio",), 0.96, 0.50, 1.00)
    height_end_ratio = _number(params, ("height_end_ratio",), 0.70, 0.40, 1.00)
    height_wave = _number(params, ("height_wave",), 0.10, -0.24, 0.24)
    vertical_mode = str(params.get("vertical_mode") or "terraced").strip().lower()
    authored_controls = _control_points(params.get("control_points"))

    paths: list[tuple[tuple[float, float], ...]] = []
    widths: list[float] = []
    width_profiles: list[tuple[float, ...]] = []
    for lane_index in range(lane_count):
        lane_position = (lane_index + 1.0) / (lane_count + 1.0)
        points: list[tuple[float, float]] = []
        local_depths: list[float] = []
        control_samples = authored_controls or tuple(
            (sample_index / max(sample_count - 1, 1), lane_position)
            for sample_index in range(sample_count)
        )
        for sample_index, (t, authored_position) in enumerate(control_samples):
            x = minx + length * (0.03 + t * 0.94)
            cross_section = _longest_cross_section(local_footprint, x=x, padding=max(depth, length) * 0.05)
            if cross_section is None:
                continue
            low, high = cross_section
            available = high - low
            if available <= 0:
                continue
            # The same continuous field displaces every lane, preserving their
            # ordering and preventing the crossing-ribbon failure.
            wave = sin((t + phase * 0.12) * 2.0 * pi)
            margin = min(0.42, width_ratio * 1.35)
            if authored_controls:
                lane_offset = (lane_position - 0.5) * 0.42
                position = authored_position + lane_offset + curvature * wave * 0.28
            else:
                position = lane_position + curvature * wave
            if field_topology == "branched":
                # Paths share a trunk until the authored branch point, then
                # progressively diverge. This is normalized graph logic, not
                # a parcel-coordinate template.
                branch_progress = max(0.0, (t - branch_point_ratio) / max(1.0 - branch_point_ratio, 1e-9))
                trunk_spread = 0.06 + branch_progress * 0.94
                position = 0.5 + (position - 0.5) * trunk_spread
            position = max(margin, min(1.0 - margin, position))
            points.append(_rotate_point((x, low + available * position), frame_angle, origin))
            local_depths.append(available)
        if len(points) < 3:
            return None
        paths.append(tuple(points))
        hierarchy = 1.0 + (0.5 - lane_index / max(lane_count - 1, 1)) * width_gradient
        base_width = min(local_depths) * width_ratio * hierarchy
        profile = []
        for point_index in range(len(points)):
            t = point_index / max(len(points) - 1, 1)
            if t <= 0.5:
                local_ratio = width_start_ratio + (width_mid_ratio - width_start_ratio) * t * 2.0
            else:
                local_ratio = width_mid_ratio + (width_end_ratio - width_mid_ratio) * (t - 0.5) * 2.0
            local_ratio += width_wave * sin((t + phase * 0.08) * 2.0 * pi)
            profile.append(base_width * max(0.48, min(1.55, local_ratio)))
        width_profiles.append(tuple(profile))
        widths.append(sum(profile) / len(profile))

    if vertical_mode == "grounded":
        bands = tuple((0.0, max(0.72, 1.0 - index * 0.10)) for index in range(lane_count))
    else:
        # ``vertical_overlap`` now controls actual occupiable section depth.
        # The former fixed 0.56 bands left only one lane active at the lowest
        # and highest floors, forcing every authored ribbon below the same FAR
        # gate that bars passed. Overlapping thick bands model inhabitable
        # layered buildings while preserving three distinct plan lanes.
        band_height = max(0.84, min(0.96, 0.70 + overlap * 0.95))
        step = (1.0 - band_height) / max(lane_count - 1, 1)
        bands = tuple(
            (max(0.0, index * step), min(1.0, index * step + band_height))
            for index in range(lane_count)
        )
    return RibbonDesignField(
        paths=tuple(paths),
        half_widths=tuple(widths),
        half_width_profiles=tuple(width_profiles),
        vertical_bands=bands,
        evidence={
            "schema_version": "arr.maas.site_design_field.v1",
            "field_type": "parcel_cross_section_ribbon",
            "field_topology": field_topology,
            "coordinate_frame": "minimum_rotated_long_axis",
            "dominant_axis_world_degrees": round(frame_angle, 4),
            "source": str(params.get("design_field_source") or "mass_graph_parameters"),
            "coordinate_template": False,
            "lane_count": lane_count,
            "sample_count": sample_count,
            "curvature": round(curvature, 4),
            "phase": round(phase, 4),
            "width_ratio": round(width_ratio, 4),
            "vertical_overlap": round(overlap, 4),
            "vertical_band_height": round(band_height if vertical_mode != "grounded" else 1.0, 4),
            "vertical_mode": vertical_mode,
            "width_gradient": round(width_gradient, 4),
            "variable_width": True,
            "width_profile_source": (
                "agent_authored"
                if any(key in params for key in (
                    "width_start_ratio", "width_mid_ratio", "width_end_ratio", "width_wave"
                ))
                else "formal_rule_prior"
            ),
            "width_profile_ratios": [
                round(width_start_ratio, 4),
                round(width_mid_ratio, 4),
                round(width_end_ratio, 4),
            ],
            "width_wave": round(width_wave, 4),
            "branch_point_ratio": round(branch_point_ratio, 4),
            "height_profile_source": (
                "agent_authored"
                if any(key in params for key in (
                    "height_start_ratio", "height_mid_ratio", "height_end_ratio", "height_wave"
                ))
                else "formal_rule_prior"
            ),
            "height_profile_ratios": [
                round(height_start_ratio, 4),
                round(height_mid_ratio, 4),
                round(height_end_ratio, 4),
            ],
            "height_wave": round(height_wave, 4),
            "authored_control_point_count": len(authored_controls),
            "parcel_area_m2": round(float(footprint.area), 2),
        },
    )


def _dominant_axis_degrees(footprint: Polygon) -> float:
    rectangle = footprint.minimum_rotated_rectangle
    coordinates = list(rectangle.exterior.coords)[:4]
    if len(coordinates) < 2:
        return 0.0
    edges = [
        (left, right, (right[0] - left[0]) ** 2 + (right[1] - left[1]) ** 2)
        for left, right in zip(coordinates, coordinates[1:] + coordinates[:1])
    ]
    left, right, _ = max(edges, key=lambda item: item[2])
    angle = degrees(atan2(right[1] - left[1], right[0] - left[0]))
    # An undirected parcel axis is equivalent modulo 180 degrees.
    while angle >= 90.0:
        angle -= 180.0
    while angle < -90.0:
        angle += 180.0
    return angle


def _rotate_point(
    point: tuple[float, float],
    angle_degrees: float,
    origin: tuple[float, float],
) -> tuple[float, float]:
    angle = radians(angle_degrees)
    cosine, sine = cos(angle), sin(angle)
    dx, dy = point[0] - origin[0], point[1] - origin[1]
    return (
        origin[0] + dx * cosine - dy * sine,
        origin[1] + dx * sine + dy * cosine,
    )


def _longest_cross_section(footprint: Polygon, *, x: float, padding: float) -> tuple[float, float] | None:
    minx, miny, maxx, maxy = footprint.bounds
    section = footprint.intersection(LineString(((x, miny - padding), (x, maxy + padding))))
    lines = []
    if isinstance(section, LineString):
        lines = [section]
    elif isinstance(section, MultiLineString):
        lines = list(section.geoms)
    elif hasattr(section, "geoms"):
        lines = [item for item in section.geoms if isinstance(item, LineString)]
    if not lines:
        return None
    longest = max(lines, key=lambda item: item.length)
    ys = [float(point[1]) for point in longest.coords]
    return min(ys), max(ys)


def _number(params: dict[str, Any], keys: tuple[str, ...], default: float, low: float, high: float) -> float:
    for key in keys:
        try:
            return max(low, min(high, float(params[key])))
        except (KeyError, TypeError, ValueError):
            continue
    return max(low, min(high, default))


def _integer(value: Any, *, default: int, low: int, high: int) -> int:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def _control_points(value: Any) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, list):
        return ()
    controls: list[tuple[float, float]] = []
    for item in value[:6]:
        if not isinstance(item, list | tuple) or len(item) != 2:
            continue
        try:
            u, v = float(item[0]), float(item[1])
        except (TypeError, ValueError):
            continue
        controls.append((max(0.03, min(0.97, u)), max(0.12, min(0.88, v))))
    controls.sort(key=lambda point: point[0])
    return tuple(controls) if len(controls) >= 4 else ()


__all__ = ["RibbonDesignField", "build_ribbon_design_field"]
