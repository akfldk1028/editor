from pyproj import Transformer
from shapely.geometry import MultiPolygon, shape
from shapely.ops import transform


_to_utm = Transformer.from_crs('EPSG:4326', 'EPSG:32652', always_xy=True)
_to_wgs = Transformer.from_crs('EPSG:32652', 'EPSG:4326', always_xy=True)


def wgs84_to_utm(geometry):
    return transform(_to_utm.transform, geometry)


def utm_to_wgs84(geometry):
    return transform(_to_wgs.transform, geometry)


def geojson_to_polygon(geojson: dict):
    geometry = shape(geojson)
    if isinstance(geometry, MultiPolygon):
        return max(geometry.geoms, key=lambda polygon: polygon.area)
    return geometry
