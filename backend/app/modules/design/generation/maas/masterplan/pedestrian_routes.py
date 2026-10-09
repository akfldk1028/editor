"""Preliminary arrival-to-facade routes from explicit, source-attributed arrivals."""
from shapely.geometry import LineString, shape
from shapely.ops import nearest_points

from .geometry import EPS, feature, number, polygon, union_or_empty


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
    entrance = nearest_points(arrival, ground.exterior if ground.geom_type == 'Polygon' else ground.boundary)[1]
    spine = LineString([arrival, entrance])
    if spine.length <= EPS:
        raise ValueError('no external approach length; direct boundary entrances require separate design')
    corridor = spine.buffer(width / 2, cap_style=2)
    obstacles = union_or_empty([ground, *[polygon(g, 'column') for g in request.get('columns', [])],
                               *([polygon(request['core'], 'core')] if request.get('core') else [])])
    # Do not clip a too-wide route and then claim that its proposed width survived.
    if not site.buffer(EPS).covers(corridor) or corridor.intersection(obstacles).area > EPS:
        raise ValueError('full-width pedestrian approach is obstructed or outside the site')
    if corridor.buffer(EPS).intersection(front).length + EPS < width:
        raise ValueError('pedestrian arrival lacks the declared full-width opening')
    if corridor.buffer(EPS).intersection(ground.boundary).length + EPS < width:
        raise ValueError('proposed entrance lacks full-width facade contact')
    return {'corridor': corridor, 'centerline': spine, 'entrance': entrance,
            'arrival': arrival, 'width_m': width, 'approach': design['approach']}


def route_features(route):
    if route is None:
        return []
    props = {'source': 'AI preliminary design realized by engine', 'door_verified': False}
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
          door_verified=False, scope='plan geometry only; doors, slopes and full arrival network unverified')
