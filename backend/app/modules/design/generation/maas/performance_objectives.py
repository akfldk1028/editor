"""Early-stage MAAS performance objectives.

These are fast massing proxies for population ranking. They are not a daylight,
solar-radiation, glare, or energy simulation backend.
"""

from __future__ import annotations

from typing import Any

from shapely.geometry import Polygon, MultiPolygon

from backend.app.modules.design.generation.services.site_geometry import geojson_to_polygon, wgs84_to_utm


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _largest_polygon_or_none(geometry: Any) -> Polygon | None:
    if isinstance(geometry, Polygon):
        return geometry
    if isinstance(geometry, MultiPolygon):
        polygons = list(geometry.geoms)
        if polygons:
            return max(polygons, key=lambda polygon: polygon.area)
    return None


def early_massing_performance_proxy(feature: dict[str, Any]) -> dict[str, Any]:
    """Compute EvoMass-style early massing performance proxies."""
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    volumes = props.get("mass_volumes") if isinstance(props.get("mass_volumes"), list) else model.get("volumes")
    volumes = volumes if isinstance(volumes, list) else []
    parsed: list[dict[str, float]] = []
    for volume in volumes:
        if not isinstance(volume, dict):
            continue
        try:
            geom = _largest_polygon_or_none(wgs84_to_utm(geojson_to_polygon(volume.get("geometry"))))
        except Exception:
            geom = None
        if geom is None or geom.is_empty or geom.area <= 0:
            continue
        minx, miny, maxx, maxy = geom.bounds
        width = max(maxx - minx, 0.0)
        depth = max(maxy - miny, 0.0)
        bottom = float(volume.get("bottom_height") or volume.get("bottom_fraction") or 0.0)
        top = float(volume.get("top_height") or volume.get("top_fraction") or bottom)
        height = max(0.1, top - bottom)
        parsed.append({
            "area": float(geom.area),
            "perimeter": float(geom.length),
            "width": width,
            "depth": depth,
            "height": height,
            "top": top,
        })
    if not parsed:
        return {
            "schema_version": "arr.maas.performance_proxy.v1",
            "status": "missing_geometry",
            "method": "early_massing_proxy_not_simulation",
            "daylight_perimeter_proxy": 0.0,
            "south_solar_access_proxy": 0.0,
            "view_openness_proxy": 0.0,
            "mass_distribution_balance": 0.0,
            "aggregate_performance_proxy": 0.0,
        }
    weighted_area = sum(item["area"] * item["height"] for item in parsed)
    weighted_perimeter = sum(item["perimeter"] * item["height"] for item in parsed)
    weighted_south_width = sum(item["width"] * item["height"] for item in parsed)
    weighted_facade_span = sum((2.0 * item["width"] + 2.0 * item["depth"]) * item["height"] for item in parsed)
    daylight_perimeter_proxy = clamp01(
        weighted_perimeter / max(4.0 * (weighted_area ** 0.5) * sum(item["height"] for item in parsed), 1e-6)
    )
    south_solar_access_proxy = clamp01(weighted_south_width / max(weighted_facade_span, 1e-6) * 4.0)
    top_area = sum(item["area"] for item in parsed if item["top"] >= max(v["top"] for v in parsed) - 0.5)
    base_area = max(max(item["area"] for item in parsed), 1e-6)
    mass_distribution_balance = clamp01(1.0 - abs((top_area / base_area) - 0.55) / 0.55)
    compactness_values = [
        (item["perimeter"] ** 2) / max(item["area"], 1e-6)
        for item in parsed
    ]
    avg_compactness = sum(compactness_values) / max(len(compactness_values), 1)
    view_openness_proxy = clamp01((avg_compactness - 16.0) / 52.0)
    aggregate = (
        0.34 * daylight_perimeter_proxy
        + 0.30 * south_solar_access_proxy
        + 0.20 * view_openness_proxy
        + 0.16 * mass_distribution_balance
    )
    return {
        "schema_version": "arr.maas.performance_proxy.v1",
        "status": "measured",
        "method": "early_massing_proxy_not_simulation",
        "basis": [
            "volume_area",
            "volume_perimeter",
            "south_width_ratio",
            "vertical_area_distribution",
        ],
        "daylight_perimeter_proxy": round(daylight_perimeter_proxy, 4),
        "south_solar_access_proxy": round(south_solar_access_proxy, 4),
        "view_openness_proxy": round(view_openness_proxy, 4),
        "mass_distribution_balance": round(mass_distribution_balance, 4),
        "aggregate_performance_proxy": round(clamp01(aggregate), 4),
        "limitations": [
            "Proxy objective only; not Radiance, UDI, solar-radiation, glare, or energy simulation.",
            "Use for early population ranking/audit until real environmental simulation is attached.",
        ],
    }


__all__ = ["clamp01", "early_massing_performance_proxy"]
