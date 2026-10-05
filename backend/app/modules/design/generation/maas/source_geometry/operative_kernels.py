"""Coordinate-free plan/section kernels for architect BOOK operations.

These kernels derive every dimension from the current mass and legal clip.
They contain no named precedent footprint and no parcel coordinate recipe.
The compiler remains responsible for provenance, graph relations, surface
materialization and hard-gate evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import tan, radians
from typing import Any

from shapely.affinity import affine_transform, rotate, scale, translate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.source_geometry.polygon_quality import repair_source_polygon


BOOK_KERNEL_VERBS = frozenset({
    "inflate", "merge", "skew", "twist", "intersect", "lodge", "rotate",
    "carve", "compress", "fracture", "shear", "extract", "inscribe",
    "puncture", "pack", "join",
})


@dataclass(frozen=True)
class OperativeKernelResult:
    footprint: Polygon
    upper: Polygon | None = None
    layout_units: tuple[Polygon, ...] = ()
    family: str = ""
    note: str = "book_typed_kernel"


def _clean(value: Any, clip: Polygon) -> Polygon | None:
    try:
        return repair_source_polygon(value.intersection(clip), minimum_area=1.0)
    except (AttributeError, TypeError, ValueError):
        return None


def _number(params: dict[str, Any], key: str, default: float, low: float, high: float) -> float:
    try:
        value = float(params.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _integer(params: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    return int(round(_number(params, key, float(default), float(low), float(high))))


def _axis(params: dict[str, Any]) -> str:
    return "y" if str(params.get("axis") or "x").lower() in {"y", "north", "south"} else "x"


def _scaled(poly: Polygon, x: float, y: float, clip: Polygon) -> Polygon | None:
    return _clean(scale(poly, xfact=x, yfact=y, origin="centroid"), clip)


def _shifted(poly: Polygon, axis: str, amount: float, clip: Polygon) -> Polygon | None:
    minx, miny, maxx, maxy = clip.bounds
    return _clean(translate(
        poly,
        xoff=(maxx - minx) * amount if axis == "x" else 0.0,
        yoff=(maxy - miny) * amount if axis == "y" else 0.0,
    ), clip)


def _packed_units(poly: Polygon, params: dict[str, Any], clip: Polygon) -> tuple[Polygon, ...]:
    axis = _axis(params)
    count = _integer(params, "n", 3, 2, 4)
    spacing = _number(params, "spacing_ratio", 0.10, 0.04, 0.22)
    unit_scale = _number(params, "unit_scale", 0.48, 0.24, 0.68)
    minx, miny, maxx, maxy = poly.bounds
    width, depth = maxx - minx, maxy - miny
    cx, cy = poly.centroid.x, poly.centroid.y
    span = width if axis == "x" else depth
    positions = [((index + 0.5) / count - 0.5) * span * (1.0 - spacing) for index in range(count)]
    units: list[Polygon] = []
    for index, position in enumerate(positions):
        hierarchy = 1.0 - 0.10 * index
        if axis == "x":
            raw = box(
                cx + position - span * 0.42 / count,
                cy - depth * unit_scale * hierarchy / 2,
                cx + position + span * 0.42 / count,
                cy + depth * unit_scale * hierarchy / 2,
            )
        else:
            raw = box(
                cx - width * unit_scale * hierarchy / 2,
                cy + position - span * 0.42 / count,
                cx + width * unit_scale * hierarchy / 2,
                cy + position + span * 0.42 / count,
            )
        unit = _clean(raw, clip)
        if unit is not None and unit.area >= max(1.0, poly.area * 0.04):
            units.append(unit)
    return tuple(units)


def apply_book_plan_kernel(
    verb: str,
    current: Polygon,
    legal_clip: Polygon,
    params: dict[str, Any],
) -> OperativeKernelResult | None:
    """Apply one typed BOOK operator; return ``None`` for non-BOOK kernels."""
    if verb not in BOOK_KERNEL_VERBS:
        return None
    axis = _axis(params)
    angle = _number(params, "angle", 18.0, -48.0, 48.0)
    factor = _number(params, "factor", 0.72, 0.28, 0.92)
    ratio = _number(params, "ratio", 0.25, 0.10, 0.48)
    minx, miny, maxx, maxy = current.bounds
    width, depth = maxx - minx, maxy - miny
    cx, cy = current.centroid.x, current.centroid.y

    if verb == "inflate":
        # A 2.5D inflation is represented by a broad lower plate and a smaller
        # crown; profiled surfaces remain a separate compiler responsibility.
        ground = _scaled(current, 0.94, 0.94, legal_clip)
        crown = _scaled(current, factor, factor, legal_clip)
        return OperativeKernelResult(ground or current, crown, family="inflate")
    if verb == "merge":
        units = _packed_units(current, {**params, "n": 2}, legal_clip)
        if len(units) < 2:
            return None
        connector_width = min(width, depth) * 0.16
        connector = LineString((units[0].centroid, units[-1].centroid)).buffer(connector_width / 2, cap_style=2)
        merged = _clean(unary_union((*units, connector)), legal_clip)
        # MERGE produces one fused body.  Keeping the two input units as
        # additional review solids duplicates the same geometry and reads as
        # a Lego assembly rather than a resolved mass.
        return OperativeKernelResult(merged or current, family="merge")
    if verb in {"skew", "shear"}:
        shear = tan(radians(angle)) * (0.55 if verb == "skew" else 0.82)
        matrix = (1.0, shear if axis == "y" else 0.0, shear if axis == "x" else 0.0, 1.0, 0.0, 0.0)
        shaped = _clean(affine_transform(_scaled(current, 0.82, 0.82, legal_clip) or current, matrix), legal_clip)
        return OperativeKernelResult(shaped or current, family="oblique_transform")
    if verb in {"twist", "rotate"}:
        ground = _scaled(current, 0.88, 0.88, legal_clip) or current
        upper = _clean(rotate(_scaled(current, factor, factor, legal_clip) or current, angle, origin=(cx, cy)), ground)
        return OperativeKernelResult(ground, upper, family="oblique_transform")
    if verb == "intersect":
        a = rotate(_scaled(current, factor, 0.92, legal_clip) or current, angle, origin=(cx, cy))
        b = rotate(_scaled(current, 0.92, factor, legal_clip) or current, -angle, origin=(cx, cy))
        shaped = _clean(a.intersection(b), legal_clip)
        return OperativeKernelResult(shaped or current, family="interlock")
    if verb == "lodge":
        host = _scaled(current, 0.88, 0.88, legal_clip) or current
        guest = _scaled(current, _number(params, "guest_scale", 0.42, 0.20, 0.66), 0.42, legal_clip)
        guest = _shifted(guest or current, axis, _number(params, "distance_ratio", 0.16, -0.28, 0.28), legal_clip)
        return OperativeKernelResult(host, guest, family="nest")
    if verb == "carve":
        cut_width = width * _number(params, "width_ratio", 0.42, 0.18, 0.68)
        cut_depth = depth * _number(params, "depth_ratio", 0.28, 0.10, 0.48)
        side = str(params.get("side") or "south").lower()
        cutter = {
            "north": box(cx - cut_width / 2, maxy - cut_depth, cx + cut_width / 2, maxy),
            "east": box(maxx - width * 0.28, cy - depth * 0.24, maxx, cy + depth * 0.24),
            "west": box(minx, cy - depth * 0.24, minx + width * 0.28, cy + depth * 0.24),
        }.get(side, box(cx - cut_width / 2, miny, cx + cut_width / 2, miny + cut_depth))
        shaped = _clean(current.difference(cutter), legal_clip)
        return OperativeKernelResult(shaped or current, family="void_notch")
    if verb == "compress":
        shaped = _scaled(current, factor if axis == "x" else 1.0, factor if axis == "y" else 1.0, legal_clip)
        return OperativeKernelResult(shaped or current, family="slender_bar")
    if verb == "fracture":
        gap = min(width, depth) * _number(params, "gap_ratio", 0.10, 0.04, 0.20)
        cutter = rotate(box(cx - width, cy - gap / 2, cx + width, cy + gap / 2), angle or 18.0, origin=(cx, cy))
        shaped = _clean(current.difference(cutter), legal_clip)
        return OperativeKernelResult(shaped or current, family="split")
    if verb == "extract":
        hole = Point(cx, cy).buffer(min(width, depth) * ratio, resolution=3)
        mouth = box(cx - width * ratio * 0.45, miny, cx + width * ratio * 0.45, cy)
        shaped = _clean(current.difference(unary_union((hole, mouth))), legal_clip)
        return OperativeKernelResult(shaped or current, family="void_notch")
    if verb == "inscribe":
        inner = _scaled(current, max(0.18, 1.0 - ratio * 2.0), max(0.18, 1.0 - ratio * 2.0), legal_clip)
        shaped = _clean(current.difference(inner), legal_clip) if inner is not None else None
        return OperativeKernelResult(shaped or current, family="courtyard")
    if verb == "puncture":
        count = _integer(params, "n", 2, 2, 4)
        spacing = _number(params, "spacing_ratio", 0.20, 0.10, 0.34)
        radius = min(width, depth) * _number(params, "ratio", 0.11, 0.06, 0.18)
        centers = [index - (count - 1) / 2 for index in range(count)]
        cutters = [
            Point(cx + (width * spacing * offset if axis == "x" else 0.0), cy + (depth * spacing * offset if axis == "y" else 0.0)).buffer(radius, resolution=3)
            for offset in centers
        ]
        shaped = _clean(current.difference(unary_union(cutters)), legal_clip)
        return OperativeKernelResult(shaped or current, family="courtyard")
    if verb == "pack":
        units = _packed_units(current, params, legal_clip)
        shaped = _clean(unary_union(units), legal_clip) if units else None
        return OperativeKernelResult(shaped or current, layout_units=units, family="array_cluster")
    if verb == "join":
        units = _packed_units(current, {**params, "n": 2}, legal_clip)
        if len(units) < 2:
            return None
        bridge = LineString((units[0].centroid, units[-1].centroid)).buffer(
            min(width, depth) * _number(params, "bridge_ratio", 0.12, 0.06, 0.24) / 2,
            cap_style=2,
        )
        shaped = _clean(unary_union((*units, bridge)), legal_clip)
        return OperativeKernelResult(shaped or current, layout_units=units, family="diagonal_connect")
    return None


__all__ = ["BOOK_KERNEL_VERBS", "OperativeKernelResult", "apply_book_plan_kernel"]
