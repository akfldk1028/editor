"""Compatibility wrapper for interactive MAAS mass operations."""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.interactive import apply_interactive_mass_operation


def apply_mass_operation(
    *,
    mass_geojson: dict[str, Any],
    site_polygon_geojson: dict[str, Any],
    operation: dict[str, Any],
    constraints: list[dict[str, Any]] | None = None,
    building_type: str = "공동주택",
    sunlight_envelope: dict[str, Any] | None = None,
    setback_geometries: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return apply_interactive_mass_operation(
        mass_geojson=mass_geojson,
        site_polygon_geojson=site_polygon_geojson,
        operation=operation,
        constraints=constraints or [],
        building_type=building_type,
        sunlight_envelope=sunlight_envelope,
        setback_geometries=setback_geometries,
    )


__all__ = ["apply_mass_operation"]
