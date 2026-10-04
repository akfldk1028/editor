"""Metric parcel intersection with supplied zoning features; no provider I/O."""
import logging
from typing import Any, Iterable
from shapely.geometry import Polygon, shape
from shapely.ops import unary_union
from .projection import wgs84_to_utm

logger = logging.getLogger(__name__)


def zone_areas(
    parcel_wgs84: Polygon,
    features: Iterable[dict[str, Any]],
    *,
    to_utm=wgs84_to_utm,
    minimum_share: float = 0.001,
) -> dict[str, float]:
    """Square metres of the parcel lying in each named 용도지역.

    Three things this does that a naive loop does not.

    It intersects. The layer is fetched by bounding box, so a zone that merely
    abuts the parcel arrives looking exactly like one that covers it, and only
    the intersection tells them apart - which is the same distinction
    `getLandUseAttr`'s 접함 makes, arrived at independently.

    It unions per name before measuring. The same 용도지역 comes back as several
    features, designated in different years; added up they would count the
    overlap twice and report more zone than there is parcel.

    It measures in metres. Areas in degrees are not areas, and they are wrong by
    a different factor at every latitude, which is exactly the kind of error that
    looks plausible on one parcel and is nonsense on the next.
    """

    parcel = to_utm(parcel_wgs84)
    total = float(parcel.area)
    if total <= 0.0:
        return {}

    grouped: dict[str, list[Polygon]] = {}
    for feature in features:
        name = ((feature.get("properties") or {}).get("uname") or "").strip()
        geometry = feature.get("geometry")
        if not name or not geometry:
            continue
        try:
            piece = to_utm(shape(geometry))
        except Exception:  # a malformed feature is not a reason to lose the rest
            logger.warning("zone_geometry: unreadable feature for %s", name)
            continue
        if piece.is_empty:
            continue
        overlap = piece.intersection(parcel)
        if overlap.is_empty or float(overlap.area) <= 0.0:
            continue
        grouped.setdefault(name, []).append(overlap)

    areas: dict[str, float] = {}
    for name, parts in grouped.items():
        merged = parts[0] if len(parts) == 1 else unary_union(parts)
        area = float(merged.area)
        # A hair of overlap is a boundary drawn at a different scale, not a part
        # of the parcel that carries its own building limits.
        if area / total >= minimum_share:
            areas[name] = area
    return areas
