"""
Road frontage detection from Vworld cadastral polygons.

Used to avoid the old fallback where setback_geometry guessed the road side as
the longest parcel edge. For building-line and corner-cutoff visualisation,
actual neighboring road parcels are a better source than edge length alone.
"""

from __future__ import annotations

import logging
import math

from pyproj import Transformer
from shapely.geometry import LineString, Polygon, shape
from shapely.ops import transform

from backend.app.modules.land.reference import config

logger = logging.getLogger(__name__)

_to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32652", always_xy=True)
_to_wgs = Transformer.from_crs("EPSG:32652", "EPSG:4326", always_xy=True)


def fetch_neighbor_roads(parcel_geojson: dict) -> dict:
    """Return road frontages touching a parcel polygon."""
    if not config.VWORLD_API_KEY:
        return {"success": False, "roads": [], "error": "VWORLD_API_KEY not configured"}

    coords = _extract_ring(parcel_geojson)
    if not coords:
        return {"success": False, "roads": [], "error": "invalid parcel geometry"}

    min_x = min(p[0] for p in coords) - 0.0002
    min_y = min(p[1] for p in coords) - 0.0002
    max_x = max(p[0] for p in coords) + 0.0002
    max_y = max(p[1] for p in coords) + 0.0002

    params = {
        "key": config.VWORLD_API_KEY,
        "service": "data",
        "request": "GetFeature",
        "data": "LP_PA_CBND_BUBUN",
        "geomFilter": f"BOX({min_x},{min_y},{max_x},{max_y})",
        "format": "json",
        "crs": "EPSG:4326",
        "size": "100",
    }

    try:
        resp = config.vworld_client.get(config.VWORLD_DATA_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("Vworld neighbor road lookup failed: %s", e)
        return {"success": False, "roads": [], "error": f"RoadFrontage: {e}"}

    features = (
        data.get("response", {})
        .get("result", {})
        .get("featureCollection", {})
        .get("features", [])
    )
    if not features:
        return {"success": True, "roads": []}

    roads = []
    for feat in features:
        props = feat.get("properties", {}) or {}
        if not _is_road_props(props):
            continue

        road_ring = _extract_ring(feat.get("geometry") or {})
        if not road_ring:
            continue

        shared = _shared_edges_metric(coords, feat.get("geometry") or {})
        if not shared:
            continue

        road_width_m = _estimate_road_width_m(road_ring, shared)
        for seg in shared:
            roads.append({
                "geometry": feat.get("geometry"),
                "sharedEdge": seg,
                "roadWidthM": max(2.0, min(road_width_m, 40.0)),
                "roadCenterline": _estimate_road_centerline(seg, road_ring, road_width_m),
                "landCategory": _land_category_name(props) or "도",
            })

    return {"success": True, "roads": roads}


def fetch_neighbor_parcels(parcel_geojson: dict) -> dict:
    """Return non-road neighboring parcels touching a parcel polygon."""
    if not config.VWORLD_API_KEY:
        return {"success": False, "neighbors": [], "error": "VWORLD_API_KEY not configured"}

    coords = _extract_ring(parcel_geojson)
    if not coords:
        return {"success": False, "neighbors": [], "error": "invalid parcel geometry"}

    min_x = min(p[0] for p in coords) - 0.0002
    min_y = min(p[1] for p in coords) - 0.0002
    max_x = max(p[0] for p in coords) + 0.0002
    max_y = max(p[1] for p in coords) + 0.0002

    params = {
        "key": config.VWORLD_API_KEY,
        "service": "data",
        "request": "GetFeature",
        "data": "LP_PA_CBND_BUBUN",
        "geomFilter": f"BOX({min_x},{min_y},{max_x},{max_y})",
        "format": "json",
        "crs": "EPSG:4326",
        "size": "100",
    }

    try:
        resp = config.vworld_client.get(config.VWORLD_DATA_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("Vworld neighbor parcel lookup failed: %s", e)
        return {"success": False, "neighbors": [], "error": f"NeighborParcels: {e}"}

    features = (
        data.get("response", {})
        .get("result", {})
        .get("featureCollection", {})
        .get("features", [])
    )
    neighbors = []
    for feat in features:
        props = feat.get("properties", {}) or {}
        name = _land_category_name(props)
        if _is_road_props(props):
            continue

        geom = feat.get("geometry") or {}
        ring = _extract_ring(geom)
        if not ring:
            continue
        shared = _shared_edges_metric(coords, geom)
        if not shared:
            continue
        if _same_ring(coords, ring):
            continue
        neighbors.append({
            "geometry": geom,
            "sharedEdge": shared[0],
            "landCategory": name,
            "pnu": props.get("pnu"),
        })

    return {"success": True, "neighbors": neighbors}


def _land_category_name(props: dict) -> str:
    name = str(props.get("lndcgrCodeNm", "") or "")
    if name:
        return name
    # Vworld writes the 지목 as the trailing Hangul of `jibun`, and it is NOT always separated by a
    # space: "894-151 전" and "894-38구" both occur in one response. Splitting on the space dropped
    # the category for every unspaced entry, so an unspaced "...도" was never recognised as a road.
    jibun = str(props.get("jibun", "") or "").strip()
    trailing = ""
    for ch in reversed(jibun):
        if "가" <= ch <= "힣":
            trailing = ch + trailing
        elif ch == " " and trailing:
            break
        elif trailing:
            break
        elif ch == " ":
            continue
        else:
            break
    return trailing


def _is_road_props(props: dict) -> bool:
    code = str(props.get("lndcgrCode", "") or "")
    name = _land_category_name(props)
    return code == "07" or name == "도" or "도로" in name


def _extract_ring(geojson: dict) -> list[list[float]] | None:
    try:
        if geojson.get("type") == "Polygon":
            return geojson.get("coordinates", [None])[0]
        if geojson.get("type") == "MultiPolygon":
            return geojson.get("coordinates", [[None]])[0][0]
    except (IndexError, TypeError):
        return None
    return None


def _shared_edges_metric(parcel: list[list[float]], neighbour_geojson: dict,
                         tol_m: float = 1.0) -> list[list[list[float]]]:
    """Subject-parcel edges that run along a neighbour's boundary, measured in metres.

    The vertex test this replaces compared the subject against ONE ring - `_extract_ring` returns
    only the first ring of the first part - and a 도로 parcel almost always arrives as a
    MultiPolygon because it is long and split at every junction. So the comparison was made against
    a part that does not touch us and every real frontage was dropped. Measured on 수원 고색동
    894-27: Vworld returns 23 neighbours, 2 of them roads and 8 genuinely touching, and the vertex
    test found 0. Testing the whole boundary, at both ends and the middle of each edge, finds them.
    """
    try:
        geom = shape(neighbour_geojson)
    except Exception:
        return []
    if geom.is_empty:
        return []
    boundary = transform(_to_utm.transform, geom).boundary
    out = []
    for a, b in zip(parcel, parcel[1:]):
        seg = transform(_to_utm.transform, LineString([a[:2], b[:2]]))
        if seg.length < 0.5:
            continue
        probes = [seg.interpolate(t, normalized=True) for t in (0.0, 0.5, 1.0)]
        if max(boundary.distance(pt) for pt in probes) <= tol_m:
            out.append([[a[0], a[1]], [b[0], b[1]]])
    return out


def _find_shared_edges(parcel: list[list[float]], road: list[list[float]]) -> list[list[list[float]]]:
    """Find parcel edge segments whose endpoints sit on a neighboring road ring."""
    tol_deg = 0.00001  # roughly 1m in Seoul
    shared = []
    for i in range(len(parcel) - 1):
        p1 = parcel[i]
        p2 = parcel[i + 1]
        if _point_near_polyline(p1, road, tol_deg) and _point_near_polyline(p2, road, tol_deg):
            shared.append([[p1[0], p1[1]], [p2[0], p2[1]]])
    return shared


def _point_near_polyline(pt: list[float], ring: list[list[float]], tol: float) -> bool:
    for i in range(len(ring) - 1):
        if _point_to_segment_distance(pt, ring[i], ring[i + 1]) < tol:
            return True
    return False


def _point_to_segment_distance(p: list[float], a: list[float], b: list[float]) -> float:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-20:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def _estimate_road_width_m(road_ring: list[list[float]], shared_edges: list[list[list[float]]]) -> float:
    try:
        road_poly = shape({"type": "Polygon", "coordinates": [road_ring]})
        road_area_m2 = _polygon_area_utm(road_poly)
        shared_len_m = sum(_line_length_utm(LineString(seg)) for seg in shared_edges)
        return road_area_m2 / shared_len_m if shared_len_m > 0.1 else 6.0
    except Exception:
        return 6.0


def _estimate_road_centerline(
    shared_edge: list[list[float]],
    road_ring: list[list[float]],
    road_width_m: float,
) -> list[list[float]] | None:
    """Approximate road centerline by offsetting frontage halfway into the road parcel."""
    try:
        edge = transform(_to_utm.transform, LineString(shared_edge))
        road_poly = transform(_to_utm.transform, shape({"type": "Polygon", "coordinates": [road_ring]}))
        midpoint = edge.interpolate(0.5, normalized=True)
        centroid = road_poly.centroid
        coords = list(edge.coords)
        dx = coords[-1][0] - coords[0][0]
        dy = coords[-1][1] - coords[0][1]
        length = math.hypot(dx, dy)
        if length < 0.1:
            return None
        nx = -dy / length
        ny = dx / length
        to_road_x = centroid.x - midpoint.x
        to_road_y = centroid.y - midpoint.y
        if nx * to_road_x + ny * to_road_y < 0:
            nx, ny = -nx, -ny
        offset = max(1.0, min(road_width_m / 2.0, 20.0))
        shifted = LineString([(x + nx * offset, y + ny * offset) for x, y in coords])
        wgs = transform(_to_wgs.transform, shifted)
        return [[round(x, 8), round(y, 8)] for x, y in wgs.coords]
    except Exception as e:
        logger.warning("road centerline estimate failed: %s", e)
        return None


def _same_ring(a: list[list[float]], b: list[list[float]]) -> bool:
    if len(a) != len(b):
        return False
    if not a or not b:
        return False
    return all(math.hypot(pa[0] - pb[0], pa[1] - pb[1]) < 1e-8 for pa, pb in zip(a, b))


def _polygon_area_utm(poly: Polygon) -> float:
    coords = [_to_utm.transform(x, y) for x, y in poly.exterior.coords]
    area = 0.0
    for i in range(len(coords) - 1):
        area += coords[i][0] * coords[i + 1][1] - coords[i + 1][0] * coords[i][1]
    return abs(area) / 2.0


def _line_length_utm(line: LineString) -> float:
    pts = [_to_utm.transform(x, y) for x, y in line.coords]
    return sum(
        math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        for i in range(len(pts) - 1)
    )
