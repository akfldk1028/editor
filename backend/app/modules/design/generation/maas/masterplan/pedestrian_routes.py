"""Arrival routes to source-declared entrances, or explicitly unknown-door facades."""
import math
from shapely.geometry import shape
from shapely.ops import nearest_points

from .geometry import EPS, feature, number, polygon, union_or_empty
from .pedestrian_path_search import corridor_for, route_spine


APPROACHES = {'front_start': .25, 'front_middle': .5, 'front_end': .75}
PENDING = ['pedestrian_entrance_door_and_internal_connection_review',
           'pedestrian_slope_surface_accessibility_review',
           'pedestrian_arrival_network_completeness_review']


def realize_route(request):
    design = request.get('pedestrian_route_design')
    if design is None:
        return None
    if not isinstance(design, dict) or design.get('approach') not in APPROACHES:
        raise ValueError('pedestrian route requires a supported approach')
    width = number(design.get('width_m'), 'declared pedestrian route width')
    if width <= 0:
        raise ValueError('pedestrian width must be positive; no legal default is inferred')
    if not request.get('pedestrian_frontage') or not (request.get('evidence') or {}).get('pedestrian_frontage'):
        raise ValueError('source-attributed pedestrian_frontage is required; vehicle frontage is not a substitute')
    front = shape(request['pedestrian_frontage'])
    site = polygon(request['site'], 'site')
    if (front.geom_type != 'LineString' or front.is_empty or not front.is_valid
            or front.length <= EPS or not site.boundary.buffer(EPS).covers(front)):
        raise ValueError('pedestrian frontage must be one confirmed boundary line')
    mass = request.get('ground_footprint') or request.get('footprint')
    if not mass:
        raise ValueError('pedestrian route needs a fixed ground building zone')
    ground = polygon(mass, 'ground building zone')
    arrival = front.interpolate(APPROACHES[design['approach']], normalized=True)
    declared = request.get('building_entrance')
    if declared is not None:
        source = (request.get('evidence') or {}).get('building_entrance')
        if not source or (isinstance(source, dict) and source.get('authored_source_missing')):
            raise ValueError('building entrance requires source-attributed evidence')
        entrance = shape(declared)
        if (entrance.geom_type != 'Point' or entrance.is_empty or not entrance.is_valid
                or entrance.has_z or not all(math.isfinite(v) for v in entrance.coords[0])
                or ground.boundary.distance(entrance) > EPS):
            raise ValueError('building entrance must be a finite 2D point on the ground facade in site metric XY')
    else:
        entrance = nearest_points(arrival, ground.boundary)[1]
    obstacles = union_or_empty([ground, *[polygon(g, 'column') for g in request.get('columns', [])],
                               *([polygon(request['core'], 'core')] if request.get('core') else [])])
    spine, search_nodes = route_spine(arrival, entrance, front, ground, site, obstacles, width)
    corridor = corridor_for(spine, width)
    # Do not clip a too-wide route and then claim that its proposed width survived.
    if not site.buffer(EPS).covers(corridor) or corridor.intersection(obstacles).area > EPS:
        raise ValueError('full-width pedestrian approach is obstructed or outside the site')
    if corridor.buffer(EPS).intersection(front).length + EPS < width:
        raise ValueError('pedestrian arrival lacks the declared full-width opening')
    if corridor.buffer(EPS).intersection(ground.boundary).length + EPS < width:
        raise ValueError('proposed entrance lacks full-width facade contact')
    return {'corridor': corridor, 'centerline': spine, 'entrance': entrance,
            'arrival': arrival, 'width_m': width, 'approach': design['approach'],
            'destination_kind': 'declared_entrance' if declared is not None else 'facade_proposal',
            'door_status': 'declared' if declared is not None else 'unknown',
            'door_verified': False, 'clearance_verified': True, 'search_nodes': search_nodes,
            'entrance_source': (request.get('evidence') or {}).get('building_entrance') if declared is not None else None,
            'distance_to_declared_entrance_m': spine.length if declared is not None else None}


def route_features(route):
    if route is None:
        return []
    props = {'source': 'AI preliminary design realized by engine', 'door_verified': False,
             'door_status': route['door_status'], 'destination_kind': route['destination_kind'],
             'clearance_verified': route['clearance_verified'], 'entrance_source': route['entrance_source'],
             'arrival_xy': list(route['arrival'].coords[0]), 'destination_xy': list(route['entrance'].coords[0]),
             'distance_to_declared_entrance_m': route['distance_to_declared_entrance_m']}
    return [feature('pedestrian_route', route['corridor'], width_m=route['width_m'], **props),
            feature('pedestrian_route_centerline', route['centerline'], **props),
            feature('pedestrian_entrance_proposal', route['entrance'], **props)]


def check_route_features(check, request, features):
    route = realize_route(request)
    if route is None:
        return
    expected = {'pedestrian_route': route['corridor'],
                'pedestrian_route_centerline': route['centerline'],
                'pedestrian_entrance_proposal': route['entrance']}
    for layer, geometry in expected.items():
        drawn = [shape(f['geometry']) for f in features
                 if (f.get('properties') or {}).get('layer') == layer
                 and (f.get('properties') or {}).get('level', 0) == 0]
        check('pedestrian_route_preserved:' + layer,
              len(drawn) == 1 and drawn[0].equals_exact(geometry, EPS))
    check('pedestrian_arrival_to_facade_connection', True,
          width_m=route['width_m'], length_m=route['centerline'].length,
          door_verified=False, door_status=route['door_status'],
          distance_to_declared_entrance_m=route['distance_to_declared_entrance_m'],
          clearance_verified=route['clearance_verified'], scope='plan geometry only; doors, slopes and full arrival network unverified')
