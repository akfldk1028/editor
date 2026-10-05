"""Convert ARR mass GeoJSON into MAAS-style OpenSCAD code."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from shapely.geometry import MultiPolygon, Polygon

from backend.app.modules.design.generation.services.site_geometry import geojson_to_polygon, wgs84_to_utm


SCAD_HEADER = """// ARR MAAS adapter - generated OpenSCAD
// Source of truth: ARR mass_geojson + validator metrics
// Export is derived geometry, not the legal/original design state.
$fn = 32;
"""


@dataclass(frozen=True)
class ScadExport:
    name: str
    scad_text: str
    metadata: dict[str, Any]
    warnings: list[str]


def _safe_name(name: str | None) -> str:
    raw = name or "arr_mass"
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_")
    return cleaned or "arr_mass"


def _largest_polygon(geometry: Polygon | MultiPolygon) -> Polygon:
    if isinstance(geometry, Polygon):
        return geometry
    if isinstance(geometry, MultiPolygon):
        polygons = [p for p in geometry.geoms if not p.is_empty]
        if polygons:
            return max(polygons, key=lambda p: p.area)
    raise ValueError("mass geometry must be Polygon or MultiPolygon")


def _polygon_to_local_points(polygon_wgs: Polygon, cx: float, cy: float) -> list[tuple[float, float]]:
    polygon_utm = wgs84_to_utm(polygon_wgs)
    exterior = list(polygon_utm.exterior.coords)
    if len(exterior) > 3 and exterior[0] == exterior[-1]:
        exterior = exterior[:-1]
    if len(exterior) < 3:
        raise ValueError("polygon exterior needs at least 3 points")
    return [(float(x - cx), float(y - cy)) for x, y in exterior]


def _points_to_scad(points: list[tuple[float, float]]) -> str:
    return "[" + ", ".join(f"[{x:.4f},{y:.4f}]" for x, y in points) + "]"


def _extrude_scad(
    *,
    points: list[tuple[float, float]],
    bottom: float,
    height: float,
    label: str,
) -> str:
    height = max(float(height), 0.01)
    bottom = float(bottom)
    return (
        f"  // {label}\n"
        f"  translate([0,0,{bottom:.4f}])\n"
        f"    linear_extrude(height={height:.4f})\n"
        f"      polygon(points={_points_to_scad(points)});\n"
    )


def _canonical_bands(props: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    volume_field = None
    volumes = None
    if "mass_volumes" in props:
        volume_field = "mass_volumes"
        volumes = props["mass_volumes"]
    elif "volumes" in model:
        volume_field = "maas_model.volumes"
        volumes = model["volumes"]
    if volume_field is not None:
        if not isinstance(volumes, list) or not volumes:
            raise ValueError(f"{volume_field} must be a non-empty list")
        bands: list[dict[str, Any]] = []
        for index, volume in enumerate(volumes):
            if not isinstance(volume, dict) or not isinstance(volume.get("geometry"), dict):
                raise ValueError(f"{volume_field}[{index}].geometry is required")
            try:
                bottom = float(volume.get("bottom_height"))
                top = float(volume.get("top_height"))
            except (TypeError, ValueError):
                raise ValueError(f"{volume_field}[{index}] requires numeric heights") from None
            if top <= bottom:
                raise ValueError(f"{volume_field}[{index}] top_height must exceed bottom_height")
            bands.append({
                "index": index,
                "bottom": bottom,
                "top": top,
                "geometry": volume["geometry"],
            })
        bands.sort(key=lambda band: (band["bottom"], band["top"], band["index"]))
        return bands, "mass_volumes"

    plate_field = None
    plates = None
    if "floor_plates" in props:
        plate_field = "floor_plates"
        plates = props["floor_plates"]
    elif "floor_plates" in model:
        plate_field = "maas_model.floor_plates"
        plates = model["floor_plates"]
    if plate_field is not None:
        if not isinstance(plates, list) or not plates:
            raise ValueError(f"{plate_field} must be a non-empty list")
        bands = []
        previous_top = 0.0
        if any(not isinstance(plate, dict) for plate in plates):
            raise ValueError(f"{plate_field} entries must be objects")
        ordered = sorted(plates, key=lambda plate: int(plate.get("floor") or 0))
        for index, plate in enumerate(ordered):
            if not isinstance(plate.get("geometry"), dict):
                raise ValueError(f"{plate_field}[{index}].geometry is required")
            try:
                top = float(plate.get("top_height"))
            except (TypeError, ValueError):
                raise ValueError(f"{plate_field}[{index}].top_height must be numeric") from None
            if top <= previous_top:
                raise ValueError(f"{plate_field}[{index}] top_height must increase")
            bands.append({
                "index": index,
                "bottom": previous_top,
                "top": top,
                "geometry": plate["geometry"],
            })
            previous_top = top
        return bands, "floor_plates"
    return [], None


def mass_geojson_to_scad(mass_geojson: dict[str, Any], *, name: str | None = None) -> ScadExport:
    """Convert a mass GeoJSON Feature into OpenSCAD text.

    Canonical floorwise mass bands are exported first. Legacy two-tier
    compatibility geometry is used only when canonical bands are absent.
    """
    if mass_geojson.get("type") != "Feature":
        raise ValueError("mass_geojson must be a GeoJSON Feature")

    geometry = mass_geojson.get("geometry")
    if not isinstance(geometry, dict):
        raise ValueError("mass_geojson.geometry is required")

    props = mass_geojson.get("properties") or {}
    canonical_bands, geometry_source = _canonical_bands(props)
    origin_geometry = canonical_bands[0]["geometry"] if canonical_bands else geometry
    base_wgs = _largest_polygon(geojson_to_polygon(origin_geometry))
    base_utm = wgs84_to_utm(base_wgs)
    cx, cy = base_utm.centroid.x, base_utm.centroid.y
    base_points = _polygon_to_local_points(base_wgs, cx, cy)

    total_height = (
        max(float(band["top"]) for band in canonical_bands)
        if canonical_bands
        else float(props.get("height") or 0)
    )
    if total_height <= 0:
        floor_height = float(props.get("floor_height") or 3.0)
        num_floors = float(props.get("num_floors") or 1)
        total_height = max(floor_height * num_floors, 0.01)

    safe_name = _safe_name(name or props.get("design_id") or props.get("interactive_candidate_id"))
    warnings: list[str] = []
    body_parts: list[str] = []

    upper_geometry = props.get("upper_geometry")
    lower_height = float(props.get("lower_height") or 0)
    if canonical_bands:
        for band_number, band in enumerate(canonical_bands, start=1):
            band_wgs = _largest_polygon(geojson_to_polygon(band["geometry"]))
            band_points = _polygon_to_local_points(band_wgs, cx, cy)
            body_parts.append(
                _extrude_scad(
                    points=band_points,
                    bottom=float(band["bottom"]),
                    height=float(band["top"]) - float(band["bottom"]),
                    label=f"canonical floorwise band {band_number}",
                )
            )
    elif isinstance(upper_geometry, dict) and 0 < lower_height < total_height:
        upper_wgs = _largest_polygon(geojson_to_polygon(upper_geometry))
        upper_points = _polygon_to_local_points(upper_wgs, cx, cy)
        body_parts.append(
            _extrude_scad(
                points=base_points,
                bottom=0,
                height=lower_height,
                label="lower mass / podium",
            )
        )
        body_parts.append(
            _extrude_scad(
                points=upper_points,
                bottom=lower_height,
                height=total_height - lower_height,
                label="upper mass / stepback",
            )
        )
    else:
        if upper_geometry:
            warnings.append("upper_geometry ignored because lower_height is missing or invalid")
        body_parts.append(
            _extrude_scad(
                points=base_points,
                bottom=0,
                height=total_height,
                label="single mass",
            )
        )

    metadata = {
        "height": round(total_height, 4),
        "far": props.get("far"),
        "bcr": props.get("bcr"),
        "floor_area": props.get("floor_area"),
        "footprint_area": props.get("footprint_area"),
        "num_floors": props.get("num_floors"),
        "mass_shape": props.get("mass_shape"),
        "origin_utm": {"x": round(cx, 4), "y": round(cy, 4)},
        "has_stepback": len(body_parts) > 1,
        "canonical_band_count": len(canonical_bands),
        "geometry_source": geometry_source or "legacy_compatibility",
    }

    metric_lines = "\n".join(
        f"// {key}: {value}" for key, value in metadata.items() if value is not None
    )
    scad_text = (
        SCAD_HEADER
        + f"// name: {safe_name}\n"
        + metric_lines
        + "\n\n"
        + "union() {\n"
        + "\n".join(body_parts)
        + "}\n"
    )
    return ScadExport(name=safe_name, scad_text=scad_text, metadata=metadata, warnings=warnings)


def export_mass_geojson_to_scad(mass_geojson: dict[str, Any], *, name: str | None = None) -> dict[str, Any]:
    """JSON-serializable wrapper for API responses."""
    export = mass_geojson_to_scad(mass_geojson, name=name)
    return {
        "mode": "maas_scad_export",
        "name": export.name,
        "scad_text": export.scad_text,
        "metadata": export.metadata,
        "warnings": export.warnings,
        "notes": [
            "SCAD is derived from ARR mass_geojson.",
            "Use ARR validator metrics as legal truth; OpenSCAD is an export/mesh layer.",
        ],
    }


__all__ = ["ScadExport", "export_mass_geojson_to_scad", "mass_geojson_to_scad"]
