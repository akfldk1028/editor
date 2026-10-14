"""Exact principal-layout identity independent of stall counts and candidate names."""
import hashlib
import math
from shapely import normalize, set_precision
from shapely.errors import ShapelyError
from shapely.geometry import shape
from shapely.ops import unary_union
from .geometry import digest


def _key(geometries):
    merged = normalize(set_precision(unary_union(geometries), 1e-6).simplify(0))
    return hashlib.sha256(merged.wkb).hexdigest()


def configuration_signature(features, occupied):
    try:
        return _configuration_signature(features, occupied)
    except (KeyError, TypeError, ValueError, AttributeError, ShapelyError):
        return {'status': 'unknown', 'reason': 'invalid_configuration_geometry'}


def _configuration_signature(features, occupied):
    buildings, levels = [], {}
    for feature in features:
        props = feature.get('properties') or {}
        layer, level = props.get('layer'), props.get('level', 0) or 0
        if layer not in ('building_footprint', 'parking_aisle', 'vehicular_access', 'ramp', 'parking_stall'):
            continue
        if not isinstance(level, (int, float)) or isinstance(level, bool) or not math.isfinite(level):
            return {'status': 'unknown', 'reason': 'invalid_configuration_level'}
        geometry = shape(feature['geometry'])
        if geometry.geom_type not in ('Polygon', 'MultiPolygon') or not geometry.is_valid or geometry.is_empty:
            return {'status': 'unknown', 'reason': 'invalid_configuration_geometry'}
        if layer == 'building_footprint' and level == 0:
            buildings.append(geometry)
        if level < 0:
            bucket = levels.setdefault(str(float(level)), {'aisles': [], 'ramps': [], 'orientations': set()})
            if layer in ('parking_aisle','vehicular_access'): bucket['aisles'].append(geometry)
            elif layer == 'ramp': bucket['ramps'].append(geometry)
            elif layer == 'parking_stall':
                rectangle = geometry.minimum_rotated_rectangle
                if rectangle.geom_type != 'Polygon':
                    return {'status':'unknown','reason':'invalid_stall_geometry'}
                coords=list(rectangle.exterior.coords)
                a,b=max(zip(coords,coords[1:]),key=lambda pair: math.dist(*pair))
                bucket['orientations'].add(round(math.degrees(math.atan2(b[1]-a[1],b[0]-a[0]))%180,6)%180)
    if not buildings:
        return {'status':'unknown','reason':'building_geometry_missing'}
    building_key=digest({'upper':_key(buildings),'ground':_key([occupied])})
    basement={level:{'aisles':_key(b['aisles']),'ramps':_key(b['ramps']),
                     'stall_axis_deg':sorted(b['orientations'])} for level,b in sorted(levels.items())}
    basement_key=digest(basement)
    return {'status':'measured','key':digest({'building':building_key,'basement':basement_key}),
            'building_key':building_key,'basement_key':basement_key,'basement_levels':basement,
            'scope':'Exact principal geometry at 1e-6m precision; counts, labels and excavation excluded. '
                    'Distinct keys do not prove perceptual diversity, circulation quality or useful alternatives.'}
