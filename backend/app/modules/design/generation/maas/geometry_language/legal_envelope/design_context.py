"""Normalized, coordinate-free description of the lawful buildable field.

The legal floor sections are the one place where the parcel's real shape,
setbacks and sunlight cut become geometry.  Everything that authors or
schedules candidate form needs to know *that* shape, but nothing upstream of
compilation may ever see parcel coordinates or a finished mesh.

This module is the single shared translation between the two: it turns the
capacity contract's legal floor sections into normalized band relations in the
generation host's principal frame.  It is deliberately relational — area
ratios, normalized axis extents and centroid drift — so a consumer can reason
about how the lawful volume narrows with height without being handed a form to
copy.
"""

from __future__ import annotations

from math import atan2, degrees, hypot
from typing import Any

from shapely.affinity import rotate as rotate_geometry
from shapely.geometry import Polygon, shape


SCHEMA_VERSION = "arr.maas.normalized_legal_field_design_context.v1"

AUTHORSHIP_INSTRUCTION = (
    "Author one continuous architectural section that can survive these "
    "relations; never replay band boundaries or copy a per-floor profile."
)


def normalized_legal_field_design_context(
    capacity_contract: dict[str, Any],
) -> dict[str, Any]:
    """Expose legal shape relations without parcel coordinates or form recipes.

    Returns an empty dict whenever the contract carries no usable legal floor
    sections, so every caller can treat "no lawful context" and "malformed
    lawful context" identically instead of guessing.
    """

    sections = _legal_floor_sections(capacity_contract)
    if not sections:
        return {}
    rotated = _principal_frame_sections(sections)
    if rotated is None:
        return {}
    min_x, min_y, max_x, max_y = rotated[0].bounds
    span_x = max_x - min_x
    span_y = max_y - min_y
    if span_x <= 1e-9 or span_y <= 1e-9:
        return {}
    ground_area = float(rotated[0].area)
    bands = [
        _band_relation(
            section,
            band_index=index,
            ground_area=ground_area,
            min_x=min_x,
            min_y=min_y,
            span_x=span_x,
            span_y=span_y,
        )
        for index, section in enumerate(rotated)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "authority": "constraint_context_only_not_morphology_recipe",
        "coordinate_frame": "generation_host_principal_frame_normalized",
        "absolute_parcel_coordinates_included": False,
        "floor_band_count": len(bands),
        "ground_long_to_short_aspect": round(span_x / span_y, 6),
        "bands": bands,
        "authorship_instruction": AUTHORSHIP_INSTRUCTION,
    }


def _legal_floor_sections(
    capacity_contract: dict[str, Any],
) -> tuple[Polygon, ...]:
    raw_sections = capacity_contract.get("candidate_legal_floor_sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        legal_field = capacity_contract.get("legal_floor_field")
        raw_sections = (
            legal_field.get("legal_floor_sections")
            if isinstance(legal_field, dict)
            else None
        )
    if not isinstance(raw_sections, list) or not raw_sections:
        return ()
    sections: list[Polygon] = []
    try:
        for raw in raw_sections:
            # `shape()` raises AttributeError, not ValueError, when handed a
            # non-mapping. This is a shared entry point now, so every malformed
            # payload has to fail closed rather than escape as a crash.
            polygon = shape(raw)
            if (
                not isinstance(polygon, Polygon)
                or polygon.is_empty
                or not polygon.is_valid
                or float(polygon.area) <= 1e-9
            ):
                return ()
            sections.append(polygon)
    except (AttributeError, KeyError, TypeError, ValueError):
        return ()
    return tuple(sections)


def _principal_frame_sections(
    sections: tuple[Polygon, ...],
) -> tuple[Polygon, ...] | None:
    """Rotate every section so the ground long axis lies along +x."""

    ground = sections[0]
    rectangle = list(ground.minimum_rotated_rectangle.exterior.coords)[:4]
    if len(rectangle) != 4:
        return None
    edges = []
    for index, left in enumerate(rectangle):
        right = rectangle[(index + 1) % 4]
        dx = float(right[0]) - float(left[0])
        dy = float(right[1]) - float(left[1])
        edges.append((hypot(dx, dy), degrees(atan2(dy, dx))))
    _length, principal_angle = max(edges)
    return tuple(
        rotate_geometry(section, -principal_angle, origin=ground.centroid)
        for section in sections
    )


def _band_relation(
    section: Polygon,
    *,
    band_index: int,
    ground_area: float,
    min_x: float,
    min_y: float,
    span_x: float,
    span_y: float,
) -> dict[str, Any]:
    low_x, low_y, high_x, high_y = section.bounds
    return {
        "band_index": band_index,
        "area_ratio_to_ground": round(float(section.area) / ground_area, 6),
        "long_axis_min": round((low_x - min_x) / span_x, 6),
        "long_axis_max": round((high_x - min_x) / span_x, 6),
        "short_axis_min": round((low_y - min_y) / span_y, 6),
        "short_axis_max": round((high_y - min_y) / span_y, 6),
        "centroid_long_axis": round(
            (float(section.centroid.x) - min_x) / span_x,
            6,
        ),
        "centroid_short_axis": round(
            (float(section.centroid.y) - min_y) / span_y,
            6,
        ),
    }


__all__ = [
    "AUTHORSHIP_INSTRUCTION",
    "SCHEMA_VERSION",
    "normalized_legal_field_design_context",
]
