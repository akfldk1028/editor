"""Independently reconstruct the declared-door segment and compare serialized geometry."""
from copy import deepcopy
from shapely.geometry import shape
from .pedestrian_routes import realize_route


def measure_declared_route(request, features):
    result = {'distance_to_declared_entrance_m': None, 'actual_door_status': 'unknown',
              'scope': 'Selected frontage arrival to source-declared door; physical door, indoor network and accessibility unverified'}
    if not request.get('building_entrance'):
        return result
    try:
        route = realize_route(request)
        if route is None or route['door_status'] != 'declared':
            return result
        for layer, key in [('pedestrian_route', 'corridor'), ('pedestrian_route_centerline', 'centerline'),
                           ('pedestrian_entrance_proposal', 'entrance')]:
            drawn = [f for f in features if (f.get('properties') or {}).get('layer') == layer
                     and (f.get('properties') or {}).get('level', 0) == 0]
            if len(drawn) != 1 or not shape(drawn[0]['geometry']).equals_exact(route[key], 1e-6):
                return result
        result.update(distance_to_declared_entrance_m=route['centerline'].length,
                      actual_door_status='declared', entrance_source=deepcopy(route['entrance_source']),
                      arrival_xy=list(route['arrival'].coords[0]), destination_xy=list(route['entrance'].coords[0]),
                      source_refs=['request/evidence/building_entrance', 'features/pedestrian_route_centerline'])
    except (KeyError, TypeError, ValueError):
        pass
    return result
