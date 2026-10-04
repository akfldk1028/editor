"""Preserved primary-road and north-neighbor selection for datum context."""
from pyproj import Transformer
from math import isfinite
from shapely.geometry import LineString, Polygon, MultiPolygon, shape
from ..projection import wgs84_to_utm as _wgs_to_utm

_to_utm = Transformer.from_crs('EPSG:4326', 'EPSG:32652', always_xy=True)


def road_centerline(road_frontages: list[dict] | None) -> LineString | None:
    if not road_frontages:
        return None
    candidates = []
    for idx, frontage in enumerate(road_frontages):
        coords = frontage.get("roadCenterline") or frontage.get("road_centerline")
        if coords and len(coords) >= 2:
            try:
                line = LineString(coords)
                if line.is_empty or not line.is_valid or line.length == 0:
                    continue
                width = float(frontage.get("roadWidthM") or frontage.get("road_width_m") or 0.0)
                if not isfinite(width):
                    continue
                shared = frontage.get("sharedEdge") or frontage.get("shared_edge")
                shared_len = 0.0
                if shared and len(shared) >= 2:
                    try:
                        shared_len = LineString([
                            _to_utm.transform(float(x), float(y)) for x, y in shared
                        ]).length
                    except Exception:
                        shared_len = 0.0
                candidates.append((width, shared_len, -idx, line))
            except Exception:
                continue
    if candidates:
        # Multiple road frontages are possible on corner lots. Use the primary
        # frontage for §119 road datum: widest road first, then longer shared
        # frontage. Per-edge building-line setbacks still use every road edge.
        candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return candidates[0][3]
    return None


def neighbor_polygon(
    neighbor_parcels: list[dict] | None,
    north_edges_utm: list[LineString] | None = None,
) -> Polygon | None:
    if not neighbor_parcels:
        return None
    candidates = []
    for idx, neighbor in enumerate(neighbor_parcels):
        geom = neighbor.get("geometry")
        if not geom:
            continue
        try:
            poly = shape(geom)
            if isinstance(poly, MultiPolygon):
                poly = max(poly.geoms, key=lambda g: g.area)
            if isinstance(poly, Polygon) and not poly.is_empty and poly.is_valid:
                shared = neighbor.get("sharedEdge") or neighbor.get("shared_edge")
                shared_utm = None
                if shared and len(shared) >= 2:
                    try:
                        shared_utm = LineString([_to_utm.transform(float(x), float(y)) for x, y in shared])
                    except Exception:
                        shared_utm = None
                if shared_utm is not None:
                    midpoint_y = shared_utm.interpolate(0.5, normalized=True).y
                    north_distance = min((shared_utm.distance(edge) for edge in (north_edges_utm or [])), default=0.0)
                else:
                    poly_utm = _wgs_to_utm(poly)
                    midpoint_y = poly_utm.representative_point().y
                    north_distance = 999999.0 if north_edges_utm else 0.0
                candidates.append((north_distance, -midpoint_y, idx, poly))
        except Exception:
            continue
    if not candidates:
        return None
    # §86 uses the north-side neighboring lot. Prefer neighbors whose shared edge
    # coincides with the north-facing parcel edge, then the northernmost edge.
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[0][3]
