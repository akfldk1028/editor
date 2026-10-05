"""
Site polygon processing utilities.

WGS84↔UTM coordinate conversion, Vworld WFS parcel boundary fetch,
and site validation.
"""

from backend.app.modules.design.generation import paths as _design_paths

import json
import logging
import pathlib
from datetime import datetime, timezone

from shapely.geometry import MultiPolygon, Polygon, box, shape, mapping
from shapely.ops import transform
from pyproj import Transformer

from backend.app.modules.design.generation import config
from backend.app.modules.design.generation.exceptions import SiteGeometryError

logger = logging.getLogger(__name__)

# Korea is in UTM zone 52N (126°E–132°E)
_to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)
_to_wgs = Transformer.from_crs("EPSG:32652", "EPSG:4326", always_xy=True)


def wgs84_to_utm(polygon: Polygon) -> Polygon:
    """Convert WGS84 (lon/lat) polygon to UTM52N (meters)."""
    return transform(_to_utm.transform, polygon)


def utm_to_wgs84(polygon: Polygon) -> Polygon:
    """Convert UTM52N (meters) polygon to WGS84 (lon/lat)."""
    return transform(_to_wgs.transform, polygon)


def geojson_to_polygon(geojson: dict) -> Polygon:
    """Convert GeoJSON geometry dict to Shapely Polygon."""
    geom = shape(geojson)
    if isinstance(geom, MultiPolygon):
        return max(geom.geoms, key=lambda polygon: polygon.area)
    return geom


def polygon_to_geojson(polygon: Polygon) -> dict:
    """Convert Shapely Polygon to GeoJSON geometry dict."""
    return mapping(polygon)


PARCEL_BOUNDARY_CACHE_DIR = (
    _design_paths.backend_root()
    / "runtime"
    / "vworld_parcel_boundaries"
)


def _cached_parcel_boundary_path(pnu: str) -> pathlib.Path:
    return PARCEL_BOUNDARY_CACHE_DIR / f"{pnu}.json"


def _store_parcel_boundary(pnu: str, geometry: dict) -> None:
    """Keep the real response so an outage does not block a rerun."""

    try:
        PARCEL_BOUNDARY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cached_parcel_boundary_path(pnu).write_text(
            json.dumps(
                {
                    "source": "vworld_data_api_LP_PA_CBND_BUBUN",
                    "pnu": pnu,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "geometry": geometry,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError as error:
        logger.warning("Could not cache parcel boundary for PNU %s: %s", pnu, error)


def _load_parcel_boundary(pnu: str) -> dict | None:
    path = _cached_parcel_boundary_path(pnu)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        logger.warning("Unreadable parcel boundary cache for PNU %s: %s", pnu, error)
        return None
    if not isinstance(payload, dict) or payload.get("pnu") != pnu or payload.get("source") != "vworld_data_api_LP_PA_CBND_BUBUN":
        logger.warning("Parcel boundary cache identity mismatch for PNU %s", pnu)
        return None
    geometry = payload.get("geometry")
    if not isinstance(geometry, dict):
        return None
    logger.warning(
        "Vworld unavailable; using the cached real boundary for PNU %s "
        "fetched at %s",
        pnu,
        payload.get("fetched_at"),
    )
    return geometry


def fetch_parcel_boundary(pnu: str) -> dict | None:
    """
    Fetch parcel boundary polygon from Vworld Data API (LP_PA_CBND_BUBUN).

    A successful response is cached on disk. A parcel boundary is static, and
    Vworld goes down for hours at a time - three consecutive verification runs
    were lost to it in one session. The cache holds the real response, never a
    synthesized one, and is read only when the live call fails, so live data
    stays authoritative and the failure is logged rather than hidden.

    Args:
        pnu: 19-digit PNU code

    Returns:
        GeoJSON geometry dict or None if not found
    """
    if not config.VWORLD_API_KEY:
        logger.warning("VWORLD_API_KEY not set, cannot fetch parcel boundary")
        return _load_parcel_boundary(pnu)

    try:
        resp = config.vworld_client.get(
            "https://api.vworld.kr/req/data",
            params={
                "service": "data",
                "request": "GetFeature",
                "data": "LP_PA_CBND_BUBUN",
                "attrFilter": f"pnu:=:{pnu}",
                "format": "json",
                "crs": "EPSG:4326",
                "key": config.VWORLD_API_KEY,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        response = data.get("response", {})
        if response.get("status") != "OK":
            # An error status is a failed live call like any other, and this
            # was the one path that did not consult the cache the docstring
            # above exists for. An expired key answers HTTP 200 with
            # status ERROR / EXPIRE_KEY, so the whole massing pipeline stopped
            # on a parcel whose real boundary was already on disk.
            error = (response.get("error") or {}).get("code") or response.get("status")
            logger.warning("Vworld Data API error for PNU %s: %s", pnu, error)
            return _load_parcel_boundary(pnu)

        features = (
            response
            .get("result", {})
            .get("featureCollection", {})
            .get("features", [])
        )
        if not features:
            logger.warning("No parcel boundary found for PNU %s", pnu)
            return _load_parcel_boundary(pnu)

        geometry = polygon_to_geojson(
            geojson_to_polygon(features[0].get("geometry"))
        )
        _store_parcel_boundary(pnu, geometry)
        return geometry

    except Exception as e:
        logger.error("Vworld Data API fetch failed for PNU %s: %s", pnu, e)
        return _load_parcel_boundary(pnu)


def validate_site(polygon: Polygon) -> dict:
    """
    Validate site polygon for optimization.

    Returns:
        {"valid": bool, "area_m2": float, "errors": [str]}
    """
    errors = []

    if not polygon.is_valid:
        errors.append("Polygon geometry is invalid")

    utm_poly = wgs84_to_utm(polygon)
    area = utm_poly.area

    if area < 10:
        errors.append(f"Site too small: {area:.1f} m² (minimum 10 m²)")

    if area > 100000:
        errors.append(f"Site too large: {area:.1f} m² (maximum 100,000 m²)")

    bounds = utm_poly.bounds
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    if width < 3 or height < 3:
        errors.append(f"Site too narrow: {width:.1f}m × {height:.1f}m (minimum 3m each)")

    return {
        "valid": len(errors) == 0,
        "area_m2": round(area, 2),
        "bounds_m": {
            "width": round(width, 2),
            "height": round(height, 2),
        },
        "errors": errors,
    }
