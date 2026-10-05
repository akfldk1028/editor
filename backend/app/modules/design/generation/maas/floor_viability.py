"""Shared architectural viability rules for occupiable MASS floor plates."""

from __future__ import annotations

from typing import Any

from shapely.errors import GEOSException


DEFAULT_MINIMUM_CLEAR_DEPTH_M = 2.4


def minimum_usable_floor_area_m2(parcel_area_m2: float) -> float:
    """Return the common pre-authoring/shared-floor minimum occupied area."""

    return max(8.0, max(0.0, float(parcel_area_m2)) * 0.002)


def evaluate_floor_section_viability(
    section: Any,
    *,
    parcel_area_m2: float,
    minimum_clear_depth_m: float = DEFAULT_MINIMUM_CLEAR_DEPTH_M,
) -> dict[str, Any]:
    """Measure the same area/depth conditions before and after authoring."""

    minimum_area = minimum_usable_floor_area_m2(parcel_area_m2)
    area = (
        float(section.area)
        if section is not None and not section.is_empty
        else 0.0
    )
    try:
        clear_core = (
            section.buffer(-max(0.0, float(minimum_clear_depth_m)) / 2.0, join_style=2)
            if area > 0.0
            else None
        )
        clear_core_area = (
            float(clear_core.area)
            if clear_core is not None and not clear_core.is_empty
            else 0.0
        )
    except GEOSException:
        clear_core_area = 0.0
    failures: list[str] = []
    if area + 1e-9 < minimum_area:
        failures.append("insufficient_floor_area")
    if clear_core_area <= 1e-6:
        failures.append("insufficient_clear_floor_depth")
    return {
        "hard_pass": not failures,
        "failure_reasons": failures,
        "area_m2": round(area, 3),
        "minimum_usable_floor_area_m2": round(minimum_area, 3),
        "minimum_clear_depth_m": round(float(minimum_clear_depth_m), 3),
        "clear_depth_core_area_m2": round(clear_core_area, 3),
    }


__all__ = [
    "DEFAULT_MINIMUM_CLEAR_DEPTH_M",
    "evaluate_floor_section_viability",
    "minimum_usable_floor_area_m2",
]
