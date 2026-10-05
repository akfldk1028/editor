"""Floor-plate grouping for MAAS massing.

The optimizer may generate a legal plate for every floor. Rendering and agent
operations need a maintainable middle layer: grouped floors with shared
footprint, area contribution, and height bands.
"""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.program_packing import attach_program_packing
from backend.app.modules.design.generation.services.site_geometry import geojson_to_polygon, wgs84_to_utm


def _plate_area(plate: dict[str, Any]) -> float:
    try:
        return float(plate.get("area") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _geometry_area(plate: dict[str, Any]) -> float:
    try:
        return float(wgs84_to_utm(geojson_to_polygon(plate.get("geometry"))).area)
    except Exception:
        return _plate_area(plate)


def _iou(a: dict[str, Any], b: dict[str, Any]) -> float:
    try:
        pa = wgs84_to_utm(geojson_to_polygon(a.get("geometry")))
        pb = wgs84_to_utm(geojson_to_polygon(b.get("geometry")))
        union = pa.union(pb).area
        return float(pa.intersection(pb).area / union) if union > 0 else 0.0
    except Exception:
        aa = _plate_area(a)
        ba = _plate_area(b)
        return min(aa, ba) / max(aa, ba, 1.0)


def _same_group(a: dict[str, Any], b: dict[str, Any]) -> bool:
    aa = max(_geometry_area(a), 1.0)
    ba = max(_geometry_area(b), 1.0)
    area_ratio = min(aa, ba) / max(aa, ba)
    return area_ratio >= 0.93 and _iou(a, b) >= 0.90


def build_floor_groups(
    floor_plates: list[dict[str, Any]],
    *,
    site_area_m2: float,
    building_type: str = "",
    include_program_packing: bool = True,
) -> list[dict[str, Any]]:
    """Return contiguous floor groups from floor plates.

    Groups split when the legal footprint meaningfully changes. This exposes
    real floor-by-floor massing without forcing the frontend to infer geometry
    similarity itself.
    """
    if not floor_plates:
        return []

    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for plate in floor_plates:
        if not current or _same_group(current[-1], plate):
            current.append(plate)
        else:
            groups.append(current)
            current = [plate]
    if current:
        groups.append(current)

    result: list[dict[str, Any]] = []
    previous_top = 0.0
    cumulative_area = 0.0
    for index, group in enumerate(groups):
        first = group[0]
        last = group[-1]
        area = sum(_plate_area(plate) for plate in group)
        cumulative_area += area
        top = float(last.get("top_height") or previous_top)
        result.append({
            "group": index,
            "start_floor": int(first.get("floor") or index + 1),
            "end_floor": int(last.get("floor") or first.get("floor") or index + 1),
            "floor_count": len(group),
            "bottom_height": round(previous_top, 2),
            "top_height": round(top, 2),
            "area": round(area, 2),
            "far_contribution": round(area / site_area_m2 * 100.0, 2) if site_area_m2 > 0 else 0.0,
            "cumulative_far": round(cumulative_area / site_area_m2 * 100.0, 2) if site_area_m2 > 0 else 0.0,
            "geometry": last.get("geometry"),
            "source_floor_plates": [int(p.get("floor") or 0) for p in group],
        })
        previous_top = top
    if include_program_packing:
        return attach_program_packing(result, building_type=building_type)
    return result


__all__ = ["build_floor_groups"]
