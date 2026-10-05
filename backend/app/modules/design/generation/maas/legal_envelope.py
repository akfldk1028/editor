"""Legal envelope primitives for MAAS mass generation.

This module is the boundary between ARR law/constraint data and MAAS geometry
search. MAAS should generate inside this envelope first; legacy mass algorithms
can still be used later as seed/operator sources, but they are not the source of
truth for legal capacity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from shapely.affinity import scale as shapely_scale
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, box, mapping, shape

from backend.app.modules.design.generation.maas.morphology_operators import largest_polygon
from backend.app.modules.design.generation.services.constraint_bridge import build_default_job_spec
from backend.app.modules.design.generation.services.mass_evaluator import _build_repair_limits_from_outputs, get_floor_height
from backend.app.modules.design.generation.services.repair_operator import _sunlight_height_cap_m, clip_to_sunlight_envelope
from backend.app.modules.design.generation.services.site_geometry import wgs84_to_utm


@dataclass(frozen=True)
class LegalEnvelope:
    site_utm: Any
    site_area_m2: float
    outputs_def: list[dict[str, Any]]
    limits: Any
    floor_height: float
    max_seed_floors: int
    bcr_limit: float
    far_limit: float
    height_limit: float
    constraint_values: dict[str, tuple[str, float]]
    buildable_footprint: Any | None


@dataclass(frozen=True)
class FloorPlateStack:
    operator: str
    footprint: Any
    floor_plates: list[dict[str, Any]]
    total_floor_area_m2: float
    num_floors: int
    height_m: float
    notes: tuple[str, ...] = ()


def _constraint_value(outputs_def: list[dict[str, Any]], name: str, default: float) -> float:
    for item in outputs_def:
        if item.get("type") == "Constraint" and item.get("name") == name:
            try:
                return float(item.get("val"))
            except (TypeError, ValueError):
                return default
    return default


def _constraint_values(outputs_def: list[dict[str, Any]]) -> dict[str, tuple[str, float]]:
    values: dict[str, tuple[str, float]] = {}
    for item in outputs_def:
        if item.get("type") != "Constraint":
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        try:
            values[name] = (str(item.get("Requirement", "")), float(item.get("val")))
        except (TypeError, ValueError):
            continue
    return values


def max_legal_seed_floors(limits: Any, floor_height: float, sunlight_envelope: dict[str, Any] | None) -> int:
    """Highest plausible legal floor count before footprint-specific repair."""
    caps = [limits.height_limit_m]
    sunlight_cap = _sunlight_height_cap_m(sunlight_envelope)
    if sunlight_cap is not None:
        caps.append(sunlight_cap)
    return max(1, int(min(caps) / max(floor_height, 0.1)))


def buildable_max_footprint(
    site_utm: Any,
    limits: Any,
    sunlight_envelope: dict[str, Any] | None,
    *,
    clip_sunlight_plan: bool = True,
):
    """Best-effort legal footprint anchor inside the current ARR constraints."""
    effective_setback = max(limits.adjacent_setback_m, limits.road_setback_m)
    buildable = site_utm.buffer(-effective_setback) if effective_setback > 0 else site_utm
    if buildable.is_empty or buildable.area < 1.0:
        buildable = site_utm

    # Match the conservative north-base rule used by repair_footprint.
    if limits.north_setback_m > 0:
        minx, miny, maxx, maxy = site_utm.bounds
        north_clip_y = maxy - limits.north_setback_m
        if north_clip_y > miny:
            buildable = buildable.intersection(box(minx - 1, miny - 1, maxx + 1, north_clip_y))

    if buildable.is_empty or buildable.area < 1.0:
        return None
    # The sunlight slope is a height field, not a permanent vertical footprint
    # cut. Legacy repaired seed shapes may still request this conservative
    # 2D clip, but the MAAS layered generator must keep the full ground
    # buildable area and clip each floor by height instead.
    if clip_sunlight_plan:
        buildable, _ = clip_to_sunlight_envelope(buildable, sunlight_envelope)
    if isinstance(buildable, MultiPolygon):
        buildable = largest_polygon(buildable)
    if buildable.is_empty or buildable.area < 1.0:
        return None
    return buildable


def _setback_geometry_value(setback_geometries: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    if not isinstance(setback_geometries, dict):
        return None
    value = setback_geometries.get(key)
    if not isinstance(value, dict):
        return None
    geom = value.get("geometry") if isinstance(value.get("geometry"), dict) else value
    return geom if isinstance(geom, dict) and "type" in geom else None


def _geojson_to_utm_geometry(geom: dict[str, Any]):
    parsed = shape(geom)
    if parsed.is_empty:
        return None
    return wgs84_to_utm(parsed)


def _half_plane_for_line(line: LineString, keep_point: Point, extent: float) -> Polygon | None:
    coords = list(line.coords)
    if len(coords) < 2:
        return None
    a = Point(coords[0])
    b = Point(coords[-1])
    dx = b.x - a.x
    dy = b.y - a.y
    length = math.hypot(dx, dy)
    if length < 0.01:
        return None
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    ax, ay = a.x - ux * extent, a.y - uy * extent
    bx, by = b.x + ux * extent, b.y + uy * extent
    side_a = Polygon([(ax, ay), (bx, by), (bx + nx * extent, by + ny * extent), (ax + nx * extent, ay + ny * extent)])
    side_b = Polygon([(ax, ay), (bx, by), (bx - nx * extent, by - ny * extent), (ax - nx * extent, ay - ny * extent)])
    return side_a if side_a.covers(keep_point) else side_b


def _clip_to_offset_lines(buildable, line_geom, site_utm):
    if buildable is None or buildable.is_empty or line_geom is None or line_geom.is_empty:
        return buildable
    lines = list(line_geom.geoms) if isinstance(line_geom, MultiLineString) else [line_geom]
    if not lines:
        return buildable
    minx, miny, maxx, maxy = site_utm.bounds
    extent = max(maxx - minx, maxy - miny, 1.0) * 8.0
    keep_point = site_utm.representative_point()
    clipped = buildable
    for line in lines:
        if not isinstance(line, LineString):
            continue
        half_plane = _half_plane_for_line(line, keep_point, extent)
        if half_plane is None:
            continue
        next_geom = clipped.intersection(half_plane)
        if next_geom.is_empty or next_geom.area < 1.0:
            continue
        if isinstance(next_geom, MultiPolygon):
            next_geom = largest_polygon(next_geom)
        clipped = next_geom
    return clipped


def buildable_footprint_from_setback_geometries(
    site_utm: Any,
    setback_geometries: dict[str, Any] | None,
):
    """Build an edge-specific footprint from actual setback geometries."""
    if not isinstance(setback_geometries, dict):
        return None
    buildable = None
    buildable_geom = _setback_geometry_value(setback_geometries, "buildable_area")
    if buildable_geom is not None:
        try:
            buildable = _geojson_to_utm_geometry(buildable_geom)
            if isinstance(buildable, MultiPolygon):
                buildable = largest_polygon(buildable)
        except Exception:
            buildable = None
    if buildable is None or buildable.is_empty or buildable.area < 1.0:
        buildable = site_utm
    else:
        buildable = buildable.intersection(site_utm)

    for key in ("adjacent_setback", "road_setback", "building_designation_line"):
        geom = _setback_geometry_value(setback_geometries, key)
        if geom is None:
            continue
        try:
            line_geom = _geojson_to_utm_geometry(geom)
            buildable = _clip_to_offset_lines(buildable, line_geom, site_utm)
        except Exception:
            continue

    if buildable.is_empty or buildable.area < 1.0:
        return None
    if isinstance(buildable, MultiPolygon):
        buildable = largest_polygon(buildable)
    return buildable


def _cap_footprint_to_bcr(footprint: Any, site_area_m2: float, bcr_limit_pct: float):
    if footprint is None or footprint.is_empty or site_area_m2 <= 0 or bcr_limit_pct <= 0:
        return footprint
    max_area = site_area_m2 * bcr_limit_pct / 100.0
    if footprint.area <= max_area + 0.1:
        return footprint
    capped = footprint
    for _ in range(8):
        if capped.area <= max_area + 0.1:
            break
        factor = math.sqrt(max_area / capped.area) * 0.995
        next_poly = shapely_scale(capped, xfact=factor, yfact=factor, origin="centroid")
        next_poly = next_poly.intersection(footprint)
        if next_poly.is_empty or next_poly.area < 1.0:
            break
        if isinstance(next_poly, MultiPolygon):
            next_poly = largest_polygon(next_poly)
        capped = next_poly
    return capped


def _minimum_floor_plate_area(ground_area_m2: float) -> float:
    """Small FAR remainders should not become standalone architectural floors."""
    return max(1.0, min(24.0, ground_area_m2 * 0.25))


def _envelope_ring_utm_h(sunlight_envelope: dict[str, Any] | None) -> list[tuple[float, float, float]]:
    if not sunlight_envelope:
        return []
    slanted = sunlight_envelope.get("slanted_polygons") or []
    if not slanted:
        return []
    corners = slanted[0].get("corners") or []
    if len(corners) < 3:
        return []
    from backend.app.modules.design.generation.services.site_geometry import wgs84_to_utm

    ring = []
    for corner in corners:
        if not isinstance(corner, (list, tuple)) or len(corner) < 3:
            continue
        try:
            lng, lat, h = float(corner[0]), float(corner[1]), float(corner[2])
        except (TypeError, ValueError):
            continue
        pt_utm = wgs84_to_utm(Point(lng, lat))
        ring.append((pt_utm.x, pt_utm.y, h))
    if len(ring) >= 2 and ring[0][:2] == ring[-1][:2]:
        ring.pop()
    return ring


def _clip_ring_by_min_height(ring: list[tuple[float, float, float]], min_height_m: float) -> Polygon | None:
    """Clip a 3D envelope ring to the 2D area where envelope height >= min_height."""
    if len(ring) < 3:
        return None
    output = list(ring)

    def inside(p: tuple[float, float, float]) -> bool:
        return p[2] >= min_height_m - 1e-6

    def intersect(a: tuple[float, float, float], b: tuple[float, float, float]):
        denom = b[2] - a[2]
        if abs(denom) < 1e-9:
            return b
        t = (min_height_m - a[2]) / denom
        t = max(0.0, min(1.0, t))
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, min_height_m)

    clipped: list[tuple[float, float, float]] = []
    prev = output[-1]
    prev_inside = inside(prev)
    for curr in output:
        curr_inside = inside(curr)
        if curr_inside:
            if not prev_inside:
                clipped.append(intersect(prev, curr))
            clipped.append(curr)
        elif prev_inside:
            clipped.append(intersect(prev, curr))
        prev, prev_inside = curr, curr_inside

    coords = [(p[0], p[1]) for p in clipped]
    if len(coords) < 3:
        return None
    poly = Polygon(coords)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if isinstance(poly, MultiPolygon):
        poly = largest_polygon(poly)
    if poly.is_empty or poly.area < 1.0:
        return None
    return poly


def allowed_footprint_at_height(
    envelope: LegalEnvelope,
    height_m: float,
    sunlight_envelope: dict[str, Any] | None,
):
    """Allowed floor footprint whose top is at ``height_m``."""
    base = envelope.buildable_footprint
    if base is None or base.is_empty:
        return None
    ring = _envelope_ring_utm_h(sunlight_envelope)
    if ring:
        sunlight_poly = _clip_ring_by_min_height(ring, height_m)
        if sunlight_poly is None:
            return None
        base = base.intersection(sunlight_poly)
    if base.is_empty or base.area < 1.0:
        return None
    if isinstance(base, MultiPolygon):
        base = largest_polygon(base)
    return base


def build_floor_plate_stack(
    envelope: LegalEnvelope,
    sunlight_envelope: dict[str, Any] | None,
    *,
    operator: str = "legal_layered_max",
    ground_footprint: Any | None = None,
    upper_footprint: Any | None = None,
    lower_floor_fraction: float | None = None,
) -> FloorPlateStack | None:
    """Generate floor-by-floor legal plates, filling FAR until the cap is reached."""
    if envelope.buildable_footprint is None:
        return None
    max_far_area = envelope.site_area_m2 * envelope.far_limit / 100.0
    # Layered generation must not use the conservative global sunlight cap.
    # Each floor plate is clipped by the envelope at its own top height instead.
    max_height = envelope.height_limit
    max_floors = max(1, int(max_height / max(envelope.floor_height, 0.1)))
    ground_base = envelope.buildable_footprint
    if ground_footprint is not None and not ground_footprint.is_empty:
        ground_base = ground_base.intersection(ground_footprint)
        if isinstance(ground_base, MultiPolygon):
            ground_base = largest_polygon(ground_base)
    ground_cap = _cap_footprint_to_bcr(ground_base, envelope.site_area_m2, envelope.bcr_limit)
    if ground_cap is None or ground_cap.is_empty:
        return None
    upper_cap = None
    if upper_footprint is not None and not upper_footprint.is_empty:
        upper_cap = upper_footprint.intersection(ground_cap)
        if isinstance(upper_cap, MultiPolygon):
            upper_cap = largest_polygon(upper_cap)
        if upper_cap.is_empty or upper_cap.area < 1.0:
            upper_cap = None
    candidate_floor_count = 0
    for floor in range(1, max_floors + 1):
        if allowed_footprint_at_height(envelope, floor * envelope.floor_height, sunlight_envelope) is None:
            break
        candidate_floor_count += 1
    if candidate_floor_count <= 0:
        return None

    lower_floors = max(1, int(round(candidate_floor_count * (lower_floor_fraction or 1.0))))
    if upper_cap is None:
        lower_floors = candidate_floor_count

    plates: list[dict[str, Any]] = []
    total_area = 0.0
    min_plate_area = _minimum_floor_plate_area(float(ground_cap.area))
    for floor in range(1, candidate_floor_count + 1):
        top_h = floor * envelope.floor_height
        allowed = allowed_footprint_at_height(envelope, top_h, sunlight_envelope)
        if allowed is None:
            break
        plate_cap = ground_cap if floor <= lower_floors else upper_cap
        if plate_cap is None:
            break
        allowed = allowed.intersection(plate_cap)
        if allowed.is_empty or allowed.area < 1.0:
            break
        if isinstance(allowed, MultiPolygon):
            allowed = largest_polygon(allowed)
        if allowed.area < min_plate_area:
            break
        remaining = max_far_area - total_area
        if remaining < min_plate_area:
            break
        if allowed.area > remaining:
            allowed = _cap_footprint_to_bcr(allowed, allowed.area, remaining / allowed.area * 100.0)
            if allowed is None or allowed.is_empty or allowed.area < min_plate_area:
                break
        total_area += allowed.area
        from backend.app.modules.design.generation.services.site_geometry import utm_to_wgs84

        plates.append({
            "floor": floor,
            "top_height": round(top_h, 2),
            "area": round(allowed.area, 2),
            "geometry": mapping(utm_to_wgs84(allowed)),
        })
        if total_area >= max_far_area - 1.0:
            break

    if not plates:
        return None
    return FloorPlateStack(
        operator=operator,
        footprint=ground_cap,
        floor_plates=plates,
        total_floor_area_m2=total_area,
        num_floors=len(plates),
        height_m=plates[-1]["top_height"],
        notes=("층별 legal envelope로 각 floor plate를 직접 clip",),
    )


def build_legal_envelope(
    *,
    site_utm: Any,
    constraints: list[dict[str, Any]] | None,
    building_type: str,
    sunlight_envelope: dict[str, Any] | None,
    setback_geometries: dict[str, Any] | None = None,
) -> LegalEnvelope:
    site_area_m2 = site_utm.area
    job_spec = build_default_job_spec(site_area_m2, constraints or [], building_type, "additive")
    outputs_def = job_spec.get("outputs", [])
    limits = _build_repair_limits_from_outputs(outputs_def, building_type)
    floor_height = get_floor_height(building_type)

    edge_specific_buildable = buildable_footprint_from_setback_geometries(site_utm, setback_geometries)
    fallback_buildable = buildable_max_footprint(
        site_utm,
        limits,
        sunlight_envelope,
        clip_sunlight_plan=False,
    )

    return LegalEnvelope(
        site_utm=site_utm,
        site_area_m2=site_area_m2,
        outputs_def=outputs_def,
        limits=limits,
        floor_height=floor_height,
        max_seed_floors=max_legal_seed_floors(limits, floor_height, sunlight_envelope),
        bcr_limit=_constraint_value(outputs_def, "bcr", limits.bcr_limit_pct),
        far_limit=_constraint_value(outputs_def, "far", limits.far_limit_pct),
        height_limit=_constraint_value(outputs_def, "height", limits.height_limit_m),
        constraint_values=_constraint_values(outputs_def),
        buildable_footprint=edge_specific_buildable or fallback_buildable,
    )


def failed_constraint_metrics(props: dict[str, Any], envelope: LegalEnvelope) -> dict[str, float]:
    failed: dict[str, float] = {}
    for name, (requirement, limit_value) in envelope.constraint_values.items():
        metric_name = {
            "building_line_setback": "min_setback",
            "landscaping_pct": "open_pct",
            "setback": "min_setback",
        }.get(name, name)
        actual = props.get(metric_name)
        if not isinstance(actual, (int, float)):
            continue
        if requirement == "Less than" and actual > limit_value + 0.1:
            failed[name] = float(actual)
        if requirement == "Greater than" and actual < limit_value - 0.1:
            failed[name] = float(actual)
    return failed


__all__ = [
    "LegalEnvelope",
    "FloorPlateStack",
    "allowed_footprint_at_height",
    "build_legal_envelope",
    "build_floor_plate_stack",
    "buildable_max_footprint",
    "buildable_footprint_from_setback_geometries",
    "failed_constraint_metrics",
    "max_legal_seed_floors",
]
