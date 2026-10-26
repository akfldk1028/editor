"""Exact polygon identity before projection, simplification, or tile clipping."""
import hashlib
import math
import shapely
from shapely.geometry import MultiPolygon


def polygon_identity(geometry):
    if geometry is None or geometry.is_empty:
        return None, {"reason": "empty-source"}
    if not all(math.isfinite(float(value)) for coordinate in shapely.get_coordinates(geometry) for value in coordinate):
        return None, {"reason": "nonfinite-source-coordinate"}
    repaired = shapely.make_valid(shapely.force_2d(geometry), method="structure", keep_collapsed=False)
    polygons = []

    def collect(item):
        if item.geom_type == "Polygon" and item.area > 0:
            polygons.append(item)
        elif hasattr(item, "geoms"):
            for part in item.geoms:
                collect(part)

    collect(repaired)
    if not polygons:
        return None, {"reason": "no-positive-area-after-repair"}
    result = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)
    if not result.is_valid:
        return None, {"reason": "invalid-polygon-after-repair"}
    result = shapely.normalize(result)
    digest = hashlib.sha256(shapely.to_wkb(result, byte_order=1, output_dimension=2)).hexdigest()
    return result, {"geometrySHA256": digest, "areaM2": result.area,
                    "repaired": not geometry.is_valid, "parts": len(polygons)}
