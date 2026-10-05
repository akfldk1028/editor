"""Graph-native relative starting volume for BOOK program projection.

BOOK p.3 defines relative volumes, not parcel coordinates.  A scope is derived
from the dominant program component's principal frame and clipped back to the
host, so concave or oblique hosts remain safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees

from shapely.affinity import rotate, scale
from shapely.geometry import Polygon

from backend.app.modules.design.generation.maas.book_language.semantics import BASE_VOLUME_FRACTIONS
from backend.app.modules.design.generation.maas.source_geometry.polygon_quality import repair_source_polygon


BOOK_SCOPE_VERB = "select_book_scope"
BOOK_SCOPE_ORIENTATIONS = ("long_axis", "short_axis", "vertical")
_ALLOWED_FRACTIONS = {round(value, 6) for _label, value in BASE_VOLUME_FRACTIONS}


@dataclass(frozen=True)
class BookProjectionScope:
    label: str
    requested_fraction: float
    orientation: str


@dataclass(frozen=True)
class MaterializedBookScope:
    footprint: Polygon
    requested_fraction: float
    measured_plan_fraction: float
    height_fraction: float
    orientation: str


def projection_scope(label: str = "1/1", orientation: str = "long_axis") -> BookProjectionScope:
    fractions = dict(BASE_VOLUME_FRACTIONS)
    if label not in fractions:
        raise ValueError(f"unknown BOOK p.3 base volume: {label!r}")
    if orientation not in BOOK_SCOPE_ORIENTATIONS:
        raise ValueError(f"unknown BOOK orientation: {orientation!r}")
    return BookProjectionScope(label, fractions[label], orientation)


def materialize_book_scope(host: Polygon, scope: BookProjectionScope) -> MaterializedBookScope:
    host = repair_source_polygon(host, minimum_area=1.0)
    if host is None:
        raise ValueError("BOOK scope requires a valid host polygon")
    fraction = max(1.0 / 16.0, min(1.0, float(scope.requested_fraction)))
    if round(fraction, 6) not in _ALLOWED_FRACTIONS:
        raise ValueError("BOOK scope fraction must come from p.3")
    if scope.orientation == "vertical" or fraction >= 1.0 - 1e-9:
        footprint = host
        height_fraction = fraction if scope.orientation == "vertical" else 1.0
    else:
        angle = _major_axis_angle(host)
        aligned = rotate(host, -angle, origin="centroid", use_radians=False)
        xfactor = fraction if scope.orientation == "short_axis" else 1.0
        yfactor = fraction if scope.orientation == "long_axis" else 1.0
        selected = scale(aligned, xfact=xfactor, yfact=yfactor, origin="centroid")
        selected = rotate(selected, angle, origin=host.centroid, use_radians=False)
        repaired = repair_source_polygon(selected.intersection(host), minimum_area=1.0)
        footprint = repaired if repaired is not None else host
        height_fraction = 1.0
    return MaterializedBookScope(
        footprint=footprint,
        requested_fraction=fraction,
        measured_plan_fraction=round(float(footprint.area) / max(float(host.area), 1e-9), 6),
        height_fraction=height_fraction,
        orientation=scope.orientation,
    )


def _major_axis_angle(poly: Polygon) -> float:
    coordinates = list(poly.minimum_rotated_rectangle.exterior.coords)
    edges = [
        (((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5, degrees(atan2(y2 - y1, x2 - x1)))
        for (x1, y1), (x2, y2) in zip(coordinates, coordinates[1:])
    ]
    return max(edges, key=lambda item: item[0])[1] if edges else 0.0


__all__ = [
    "BOOK_SCOPE_ORIENTATIONS",
    "BOOK_SCOPE_VERB",
    "BookProjectionScope",
    "MaterializedBookScope",
    "materialize_book_scope",
    "projection_scope",
]
