"""Shared defensive boundary for serialized source-volume polygons."""

from __future__ import annotations

from typing import Any, Iterable

from shapely.errors import GEOSException
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, shape
from shapely.ops import unary_union
from shapely.validation import make_valid


def _repair_polygon(geometry) -> Polygon | None:
    if geometry is None or geometry.is_empty:
        return None
    try:
        repaired = geometry if geometry.is_valid else make_valid(geometry)
    except GEOSException:
        try:
            repaired = geometry.buffer(0)
        except GEOSException:
            return None
    if isinstance(repaired, Polygon):
        return repaired
    if isinstance(repaired, (MultiPolygon, GeometryCollection)):
        polygons = [item for item in repaired.geoms if isinstance(item, Polygon) and not item.is_empty]
        return max(polygons, key=lambda item: item.area) if polygons else None
    return None


def repaired_volume_records(feature: dict[str, Any]) -> list[tuple[dict[str, Any], Any]]:
    """Parse and repair each serialized volume without aborting the population."""
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    repaired: list[tuple[dict[str, Any], Any]] = []
    for record in props.get("mass_volumes") or []:
        if not isinstance(record, dict) or not record.get("geometry"):
            continue
        try:
            polygon = _repair_polygon(shape(record["geometry"]))
        except (GEOSException, TypeError, ValueError):
            polygon = None
        if polygon is not None and not polygon.is_empty:
            repaired.append((record, polygon))
    return repaired


def safe_unary_union(geometries: Iterable[Any]):
    """Union repaired polygons; return ``None`` for one irreparable candidate."""
    items = [
        repaired
        for geometry in geometries
        if geometry is not None and not geometry.is_empty
        for repaired in [_repair_polygon(geometry)]
        if repaired is not None and not repaired.is_empty
    ]
    if not items:
        return None
    try:
        return unary_union(items)
    except GEOSException:
        retry = [_repair_polygon(item.buffer(0)) for item in items]
        retry = [item for item in retry if item is not None and not item.is_empty]
        try:
            return unary_union(retry) if retry else None
        except GEOSException:
            return None


def safe_symmetric_difference_ratio(left: Any, right: Any) -> float:
    """Return a conservative Jaccard distance without leaking GEOS failures.

    Projection and precision operations can occasionally leave an invalid hole
    ring even when every source footprint passed its own validity check.  This
    boundary repairs the two derived silhouettes immediately before the overlay
    operation.  If GEOS still cannot compare them, return ``0`` so an invalid
    candidate is treated as a duplicate instead of gaining artificial novelty.
    """
    repaired_left = _repair_polygon(left)
    repaired_right = _repair_polygon(right)
    if repaired_left is None and repaired_right is None:
        return 0.0
    if repaired_left is None or repaired_right is None:
        return 1.0
    try:
        difference_area = float(repaired_left.symmetric_difference(repaired_right).area)
        union_area = float(repaired_left.union(repaired_right).area)
    except GEOSException:
        try:
            clean_left = repaired_left.buffer(0)
            clean_right = repaired_right.buffer(0)
            difference_area = float(clean_left.symmetric_difference(clean_right).area)
            union_area = float(clean_left.union(clean_right).area)
        except GEOSException:
            return 0.0
    return max(0.0, min(1.0, difference_area / max(union_area, 1e-9)))


__all__ = [
    "repaired_volume_records",
    "safe_symmetric_difference_ratio",
    "safe_unary_union",
]
