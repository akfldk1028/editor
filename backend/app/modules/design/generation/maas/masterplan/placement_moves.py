"""Realise bounded AI proposals as request inputs; plan gates remain authoritative."""
from __future__ import annotations

import copy
import math

from shapely.geometry import Point, Polygon, mapping, shape

from backend.app.modules.design.generation.maas.masterplan.joint import footprint_candidates
from backend.app.modules.design.generation.maas.masterplan.layout_axis import layout_axis_angle


SHARES = {'all_basement': 0, 'mostly_basement': .25, 'half': .5,
          'mostly_surface': .6, 'all_surface': 1}
MOVES = {'building_side': {'keep', 'center', 'N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'},
         'piloti': {'keep', 'piloti'}, 'surface_share': {'keep', *SHARES},
         'ramp': {'keep', 'any', 'straight', 'curved'}}
MOVES['pedestrian_route'] = {'keep', 'front_start', 'front_middle', 'front_end'}
MOVES['circulation'] = {'keep', 'ring'}
MOVES['parking_mix'] = {'keep', 'parallel_infill'}


def _number(value, name, *, count=False):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or value < 0 or (count and int(value) != value)):
        raise ValueError(f'{name} requires a finite nonnegative {"count" if count else "number"}')
    return value


def _side(site, footprint):
    dx = footprint.centroid.x - site.centroid.x
    dy = footprint.centroid.y - site.centroid.y
    x0, y0, x1, y1 = site.bounds
    if math.hypot(dx, dy) < .05 * max(x1 - x0, y1 - y0):
        return 'center'
    return ('E', 'NE', 'N', 'NW', 'W', 'SW', 'S', 'SE')[round(math.degrees(math.atan2(dy, dx)) / 45) % 8]


def _piloti_ground(site, footprint, depth):
    coords = list(footprint.minimum_rotated_rectangle.exterior.coords)
    best = None
    for a, b in zip(coords, coords[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        nx, ny = dy / length, -dx / length
        if footprint.buffer(1e-6).contains(Point((a[0] + b[0]) / 2 + nx, (a[1] + b[1]) / 2 + ny)):
            nx, ny = -nx, -ny
        outside = Polygon([a, b, (b[0] + nx * depth, b[1] + ny * depth),
                           (a[0] + nx * depth, a[1] + ny * depth)])
        inside = Polygon([a, b, (b[0] - nx * depth, b[1] - ny * depth),
                          (a[0] - nx * depth, a[1] - ny * depth)])
        free = outside.intersection(site).difference(footprint).area
        if best is None or free > best[0]:
            best = (free, inside)
    ground = footprint.difference(best[1])
    if ground.is_empty or ground.area <= 1e-6 or ground.geom_type != 'Polygon':
        return None
    return ground


def apply_placement_moves(request, moves):
    if not isinstance(request, dict) or not isinstance(moves, dict):
        raise ValueError('placement moves require request and moves objects')
    for key, value in moves.items():
        if key == 'pedestrian_width_m':
            if _number(value, key) <= 0 or moves.get('pedestrian_route', 'keep') == 'keep':
                raise ValueError('pedestrian width requires a positive width and route proposal')
            continue
        if key not in MOVES or not isinstance(value, str) or value not in MOVES[key]:
            raise ValueError(f'unsupported placement move: {key}')
    result = copy.deepcopy(request)
    applied = {key: value for key, value in moves.items() if value != 'keep'}
    unresolved = []
    if not applied:
        return {'request': result, 'applied': {}, 'unresolved': []}
    options = result.setdefault('options', {})
    if not isinstance(options, dict):
        raise ValueError('request options must be an object')
    if 'building_side' in applied or 'piloti' in applied:
        if any(request.get(key) for key in ('footprint', 'ground_footprint', 'core', 'columns')):
            raise ValueError('placement moves cannot modify authored footprint, ground footprint, core or columns')
        target = _number(options.get('target_footprint_m2'), 'target_footprint_m2')
        if target <= 0:
            raise ValueError('target_footprint_m2 must be positive')
        rules = request.get('rules', {})
        module = (2 * _number(rules.get('stall_length_m'), 'stall_length_m')
                  + _number(rules.get('aisle_width_m'), 'aisle_width_m'))
        if module <= 0:
            raise ValueError('parking module depth must be positive')
        site = shape(request['site'])
        buildable = shape(request.get('buildable') or request['site'])
        front = shape(request['front_frontage']) if request.get('front_frontage') else None
        wanted = applied.get('building_side')
        chosen = ground = None
        for candidate in footprint_candidates(buildable, target, front, module,
                                               angle_deg=layout_axis_angle(request)):
            if wanted is not None and _side(site, candidate) != wanted:
                continue
            if not math.isclose(candidate.area, target, rel_tol=1e-9, abs_tol=1e-6):
                continue
            if 'piloti' in applied:
                ground = _piloti_ground(site, candidate, module)
                if ground is None:
                    continue
            chosen = candidate
            break
        if chosen is None:
            raise ValueError('no matching equal-area placement candidate with the requested side/piloti ground')
        result['footprint'] = mapping(chosen)
        unresolved.append('generated footprint requires MassAgent/architect acceptance and engine validation')
        if ground is not None:
            result['ground_footprint'] = mapping(ground)
            unresolved.append('preliminary piloti: clear height and structural support are unverified')
    if 'surface_share' in applied:
        total = options.get('target_parking_stalls')
        if total is None:
            total = request.get('law', {}).get('required_spaces')
        total = _number(total, 'confirmed parking count', count=True)
        proposed = int(round(SHARES[applied['surface_share']] * total))
        existing = options.get('target_surface_stalls')
        cap = options.get('max_surface_stalls')
        if existing is not None and proposed < _number(existing, 'target_surface_stalls', count=True):
            raise ValueError('surface share would reduce the existing target_surface_stalls promise')
        if cap is not None and proposed > _number(cap, 'max_surface_stalls', count=True):
            raise ValueError('surface share would violate max_surface_stalls')
        options['target_surface_stalls'] = proposed
        if cap is None:
            options['max_surface_stalls'] = proposed
    if 'ramp' in applied:
        options['ramp_shape'] = applied['ramp']
    if 'circulation' in applied:
        options['basement_parking_field'] = 'ring'
        unresolved.append('closed aisle geometry does not certify steering or swept paths')
    if 'parking_mix' in applied:
        options['parking_mix'] = applied['parking_mix']
        unresolved.append('parallel infill: general bay dimensions; manoeuvres and project applicability require review')
    if 'pedestrian_route' in applied:
        from .pedestrian_routes import realize_route
        if request.get('pedestrian_route_design') is not None:
            raise ValueError('placement moves cannot replace an authored pedestrian route')
        result['pedestrian_route_design'] = {'approach': applied['pedestrian_route'],
                                            'width_m': moves.get('pedestrian_width_m')}
        realize_route(result)
        unresolved.extend(['preliminary facade entrance: door and internal connection require Mass/Plan acceptance',
                           'pedestrian width is a design proposal, not a verified legal minimum'])
    return {'request': result, 'applied': applied, 'unresolved': unresolved}
