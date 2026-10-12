"""Metric parcel intersection with supplied zoning features; no provider I/O.

The rule for what counts as a part of the parcel (zones overlapping each other, hair-thin strips at a
boundary drawn at another scale) is `land/reference/services/zone_split.py`, shared with the parcel-limits
path; this module only clips the features to the parcel and hands the pieces over.
"""
import logging
from typing import Any, Iterable
from shapely.geometry import Polygon, shape
from backend.app.modules.land.reference.services.zone_split import ZoneSplit, split_parcel
from .projection import wgs84_to_utm

logger = logging.getLogger(__name__)


def _small_part_threshold_m2() -> float | None:
    """시행령 제94조's small-part size from the overlap rules (the split never folds a part larger than it)."""
    try:
        from backend.app.modules.regulations.zoning_limits import _load_overlap
        value = (_load_overlap().get('small_part_threshold') or {}).get('default_m2')
        return float(value) if value is not None else None
    except Exception:
        return None


def zone_split(
    parcel_wgs84: Polygon,
    features: Iterable[dict[str, Any]],
    *,
    to_utm=wgs84_to_utm,
) -> ZoneSplit:
    """The parcel's exclusive division between the named 용도지역 of `features`, in square metres.

    It intersects (a zone that merely abuts the parcel arrives from the bounding-box query looking like
    one that covers it), it measures in metres (areas in degrees are not areas), and it leaves the
    decision of what is a part and what is a drawing artefact to `zone_split.split_parcel`.
    """

    parcel = to_utm(parcel_wgs84)
    if float(parcel.area) <= 0.0:
        return split_parcel(parcel, {})

    grouped: dict[str, list[Polygon]] = {}
    surroundings: dict[str, list[Polygon]] = {}
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
        surroundings.setdefault(name, []).append(piece)
        overlap = piece.intersection(parcel)
        if overlap.is_empty or float(overlap.area) <= 0.0:
            continue
        grouped.setdefault(name, []).append(overlap)
    return split_parcel(parcel, grouped, small_part_m2=_small_part_threshold_m2(), surroundings=surroundings)


def zone_areas(
    parcel_wgs84: Polygon,
    features: Iterable[dict[str, Any]],
    *,
    to_utm=wgs84_to_utm,
) -> dict[str, float]:
    """Square metres of the parcel lying in each named 용도지역 (`zone_split(...).areas`)."""

    return zone_split(parcel_wgs84, features, to_utm=to_utm).areas
