"""Building/site observations and explicitly bound Programme relations."""
import math
import hashlib
import json
from collections import defaultdict
from shapely.geometry import shape
from shapely.ops import unary_union
from .geometry import digest
from .declared_route_measurement import measure_declared_route

TOL = 1e-6


def brief_digest(brief):
    value = {k: v for k, v in brief.items() if k != 'brief_id'}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _parts(g):
    if g.is_empty:
        return []
    parts = [g] if g.geom_type == 'Polygon' else getattr(g, 'geoms', [])
    # Boolean operations on rotated edges leave sub-tolerance islands; these are not spatial fragmentation.
    return [p for p in parts if p.geom_type == 'Polygon' and p.area > TOL * TOL]


def measure_siting(request, features, occupied):
    """No target dimensions, public-space programme or door locations are invented."""
    grouped = defaultdict(list)
    invalid = []
    area_layers = {'building_footprint', 'building_ground_footprint', 'parking_stall', 'parking_aisle',
                   'vehicular_access', 'ramp', 'column', 'building_core', 'pedestrian_route'}
    for index, feature in enumerate(features):
        p = feature.get('properties') or {}
        if p.get('level', 0) != 0 and not (p.get('layer') == 'ramp' and 0 in (p.get('from_level'), p.get('to_level'))):
            continue
        if p.get('layer') not in area_layers:
            continue
        try:
            g = shape(feature['geometry'])
            if not g.is_valid or g.is_empty or g.geom_type not in ('Polygon', 'MultiPolygon'):
                raise ValueError('invalid area geometry')
            grouped[p['layer']].append(g)
        except (KeyError, TypeError, ValueError):
            invalid.append({'index': index, 'layer': p.get('layer')})
    upper = unary_union(grouped['building_footprint'])
    vehicle = unary_union([g for key in ('parking_aisle', 'vehicular_access', 'ramp', 'parking_stall') for g in grouped[key]])
    free = shape(request['site']).difference(unary_union([upper, occupied, vehicle, *grouped['column'], *grouped['building_core']]))
    parts = _parts(free)
    routes = unary_union(grouped['pedestrian_route']).buffer(0)
    approach = shape(request['pedestrian_frontage']) if request.get('pedestrian_frontage') else None
    route_parts = _parts(routes.buffer(TOL))
    connected = None
    if approach is not None and not upper.is_empty and not routes.is_empty:
        connected = any(p.distance(approach) <= TOL and p.distance(occupied if not occupied.is_empty else upper) <= TOL
                        for p in route_parts)
    frontage = request.get('front_frontage') or request.get('frontage')
    building = {'upper_m2': round(upper.area, 3), 'ground_m2': round(occupied.area, 3),
                'frontage_distance_m': round(upper.distance(shape(frontage)), 3) if frontage and not upper.is_empty else None,
                'inside_declared_buildable': shape(request['buildable']).buffer(TOL).covers(upper)
                    if request.get('buildable') and not upper.is_empty else None,
                'mass_owner_acceptance': 'unknown', 'programme_fit': 'unknown'}
    if not upper.is_empty:
        coordinates = list(upper.minimum_rotated_rectangle.exterior.coords)
        a, b = max(zip(coordinates, coordinates[1:]), key=lambda pair: math.dist(*pair))
        building['long_axis_deg'] = round(math.degrees(math.atan2(b[1]-a[1], b[0]-a[0])) % 180, 3)
    from .configuration_signature import configuration_signature
    return {'schema_version': 'masterplan.siting-evidence.v1', 'geometry_hash': digest(features),
            'configuration_signature': configuration_signature(features, occupied) if not invalid else {'status':'unknown','reason':'invalid_area_features'},
            'invalid_area_features': invalid,
            'building': building,
            'outdoor': {'unoccupied_m2': round(free.area, 3) if not invalid else None, 'components': len(parts) if not invalid else None,
                        'largest_component_m2': round(max((p.area for p in parts), default=0), 3) if not invalid else None,
                        'usable_public_space_status': 'unknown'},
            'pedestrian': {'facade_connected': connected, 'route_components': len(route_parts),
                           'vehicle_overlap_m2': round(routes.intersection(vehicle).area, 3) if not routes.is_empty else None,
                           **measure_declared_route(request, features)},
            'scope': 'Building disposition, outdoor remainder and declared approach; no universal preferred direction or public-space approval'}


def evaluate_relations(brief, owner_artifacts):
    """Hashes bind a validated owner handoff, not independently authenticate its author."""
    owner = owner_artifacts or {}
    expected = (brief.get('source_versions', {}).get('programme') or {}).get('snapshot_hash')
    features = owner.get('features') or []
    bound = (bool(expected) and brief.get('brief_id') == brief_digest(brief)
             and owner.get('programme_snapshot_hash') == expected
             and owner.get('brief_id') == brief.get('brief_id')
             and owner.get('coordinate_frame') == 'metric_local_m'
             and owner.get('geometry_hash') == digest(features))
    by_id = defaultdict(list)
    if bound:
        for f in features:
            p = f.get('properties') or {}
            if p.get('space_id') and f.get('geometry'):
                g = shape(f['geometry'])
                if g.is_valid and not g.is_empty:
                    by_id[p['space_id']].append((g, p.get('level')))
    results = []
    for relation in brief.get('relations') or []:
        req = relation['requirement']
        row = {'relation_id': relation['id'], 'status': 'unknown', 'measured': None, 'unit': None,
               'source_hashes': {'brief': brief.get('brief_id'), 'programme': expected, 'geometry': owner.get('geometry_hash')},
               'evidence_ids': [req.get('from'), req.get('to')],
               'reason': 'missing, stale or unsupported owner evidence'}
        left, right = by_id.get(req.get('from'), []), by_id.get(req.get('to'), [])
        if len(left) == len(right) == 1 and req.get('kind') in ('shares_wall', 'near', 'separated'):
            (a, al), (b, bl) = left[0], right[0]
            if al is None or bl is None or any(req.get(k) for k in ('condition', 'constraints', 'direction', 'distance')):
                row['reason'] = 'unresolved floor association or unsupported requirement condition'
            elif al != bl:
                if req['kind'] == 'shares_wall':
                    row.update(status='failed', measured=0, unit='m', reason='different floor levels')
            elif req['kind'] == 'shares_wall':
                length = a.boundary.intersection(b.boundary).length
                row.update(status='passed' if length > TOL and a.intersection(b).area <= TOL else 'failed',
                           measured=round(length, 6), unit='m', reason='shared boundary only; not a door')
            else:
                threshold = req.get('max_distance_m' if req['kind'] == 'near' else 'min_distance_m')
                if type(threshold) in (int, float) and math.isfinite(threshold) and threshold >= 0:
                    distance = a.distance(b)
                    ok = distance <= threshold + TOL if req['kind'] == 'near' else distance + TOL >= threshold
                    other = req.get('min_distance_m' if req['kind'] == 'near' else 'max_distance_m')
                    if other is not None:
                        if type(other) not in (int, float) or not math.isfinite(other) or other < 0:
                            results.append(row)
                            continue
                        ok = ok and (distance + TOL >= other if req['kind'] == 'near' else distance <= other + TOL)
                    row.update(status='passed' if ok else 'failed', measured=round(distance, 6), unit='m',
                               reason='same-floor straight-line polygon distance, not walking distance')
        results.append(row)
    return results
