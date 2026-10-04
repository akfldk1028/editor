import math
from shapely.geometry import shape


def parcel_geometry(value: dict, *, largest: bool = False) -> dict:
    if not isinstance(value, dict) or value.get('type') not in ('Polygon', 'MultiPolygon'):
        raise ValueError('Expected parcel polygon')
    coordinates = value.get('coordinates')
    polygons = [coordinates] if value['type'] == 'Polygon' else coordinates
    if not isinstance(polygons, list) or not polygons:
        raise ValueError('Empty parcel')
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise ValueError('Empty polygon')
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4:
                raise ValueError('Invalid ring')
            for point in ring:
                if not isinstance(point, list) or len(point) != 2:
                    raise ValueError('Expected two-dimensional coordinate')
                if any(type(n) not in (float, int) or not math.isfinite(n) for n in point):
                    raise ValueError('Invalid coordinate')
                if not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90):
                    raise ValueError('Coordinate outside WGS84')
            if ring[0] != ring[-1]:
                raise ValueError('Unclosed ring')
    geometry = {'type':value['type'], 'coordinates':coordinates}
    if not shape(geometry).is_valid:
        raise ValueError('Invalid parcel topology')
    if largest and value['type'] == 'MultiPolygon':
        # Legacy PNU lookup ranks exterior area, not area after subtracting holes.
        selected = max(polygons, key=lambda polygon: shape({'type':'Polygon', 'coordinates':[polygon[0]]}).area)
        return {'type':'Polygon', 'coordinates':selected}
    return geometry
