"""Conservative body-envelope checks for an explicit, source-attributed path.

This does not generate a drivable trajectory or certify steering, tyre motion,
legal compliance, or a whole parking layout. No vehicle dimensions are defaulted.
"""
import hashlib
import json
import math

from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union
from .geometry import digest

FIELDS = ('wheelbase_m', 'body_width_m', 'front_overhang_m', 'rear_overhang_m', 'track_m')
SOURCE_FIELDS = ('vehicle_source_id', 'trajectory_source_id', 'coordinate_frame_id')
MAX_POSES = 256
MAX_INTERVALS = 2048


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_maneuver(*, vehicle, poses, drivable, obstacles, source_binding):
    """Check rear-axle-centre (x,y,yaw_degrees) poses in one metric XY frame.

    Between poses, translation is linear and yaw takes the shortest angular
    interval. This interpolation is explicit geometry, NOT a bicycle model.
    Wheel track is required/documented, but does not establish steering limits.
    """
    base = {'schema': 'arr.masterplan.body_envelope.v1', 'kinematics_verified': False,
            'legal_compliance_verified': False,
            'scope': 'conservative rectangular body envelope of declared interpolated poses only',
            'interpolation': 'linear rear-axle-centre translation; shortest yaw; metres/degrees',
            'pending_reviews': ['vehicle_swept_path_review', 'trajectory_kinematic_feasibility_review']}
    invalid = []
    if not isinstance(vehicle, dict):
        vehicle = {}
    for field in FIELDS:
        if not _finite(vehicle.get(field)) or vehicle[field] <= 0:
            invalid.append('vehicle.'+field)
    if not invalid and vehicle['track_m'] > vehicle['body_width_m']:
        invalid.append('vehicle.track_m_exceeds_body_width_m')
    source_binding = source_binding if isinstance(source_binding, dict) else {}
    for field in SOURCE_FIELDS:
        if not isinstance(source_binding.get(field), str) or not source_binding[field].strip():
            invalid.append('source_binding.'+field)
    if type(source_binding.get('level')) is not int:
        invalid.append('source_binding.level')
    if source_binding.get('pose_reference') != 'rear_axle_center':
        invalid.append('source_binding.pose_reference_requires_rear_axle_center')
    claimed_hash = source_binding.get('layout_features_sha256')
    if claimed_hash is not None and (not isinstance(claimed_hash, str) or len(claimed_hash) != 64
                                    or any(c not in '0123456789abcdef' for c in claimed_hash)):
        invalid.append('source_binding.layout_features_sha256')
    source_binding = {key: source_binding.get(key) for key in
                      (*SOURCE_FIELDS, 'level', 'pose_reference', 'layout_features_sha256')}
    if not isinstance(poses, (list, tuple)) or not 2 <= len(poses) <= MAX_POSES:
        invalid.append('poses_requires_2_to_256_entries')
    elif any(not isinstance(p, (list, tuple)) or len(p) != 3 or
             not all(_finite(v) for v in p) for p in poses):
        invalid.append('poses_require_finite_x_y_yaw_degrees')
    elif not any(tuple(p) != tuple(poses[0]) for p in poses[1:]):
        invalid.append('poses_require_nonconstant_path')
    if not isinstance(obstacles, (list, tuple)) or len(obstacles) > 256:
        invalid.append('obstacles_require_list_max_256')
    else:
        for g in [drivable, *obstacles]:
            if (getattr(g, 'geom_type', None) not in ('Polygon', 'MultiPolygon')
                    or g.is_empty or not g.is_valid):
                invalid.append('valid_nonempty_polygon_required')
                break
    if invalid:
        return {**base, 'status': 'refused', 'missing_or_invalid': invalid}
    deltas = [(((b[2] % 360)-(a[2] % 360)+180) % 360)-180 for a, b in zip(poses, poses[1:])]
    if not any(a[:2] != b[:2] or delta for a, b, delta in zip(poses, poses[1:], deltas)):
        return {**base, 'status': 'refused', 'missing_or_invalid': ['poses_require_nonconstant_path']}
    steps = [max(1, math.ceil(abs(delta)/5)) for delta in deltas]
    if sum(steps) > MAX_INTERVALS:
        return {**base, 'status': 'refused', 'missing_or_invalid': ['trajectory_operation_budget_exceeded']}
    front = vehicle['wheelbase_m'] + vehicle['front_overhang_m']
    rear, half = vehicle['rear_overhang_m'], vehicle['body_width_m']/2
    corners = [(-rear, -half), (front, -half), (front, half), (-rear, half)]
    radius = max(math.hypot(x, y) for x, y in corners)
    if (not math.isfinite(radius)
            or any(not math.isfinite(abs(p[i])+radius) for p in poses for i in (0, 1))
            or any(not math.isfinite(b[i]-a[i])
                   for a, b in zip(poses, poses[1:]) for i in (0, 1))):
        return {**base, 'status': 'refused', 'missing_or_invalid': ['numeric_range_exceeded']}

    def body(p):
        angle = math.radians(p[2] % 360)
        c, s = math.cos(angle), math.sin(angle)
        return Polygon([(p[0]+x*c-y*s, p[1]+x*s+y*c) for x, y in corners])

    pieces = []
    for a, b, delta, n in zip(poses, poses[1:], deltas, steps):
        def pose(t):
            # Reduce before adding the turn: at very large finite yaw, adding
            # a small delta first loses that delta to floating-point rounding.
            return (a[0]+t*(b[0]-a[0]), a[1]+t*(b[1]-a[1]), (a[2] % 360)+t*delta)
        for i in range(n):
            hull = body(pose(i/n)).union(body(pose((i+1)/n))).convex_hull
            # Linear interpolation error bound: max ||corner''|| / 8.
            # Translation has zero second derivative. The L-infinity square
            # expansion contains the Euclidean error ball without polygonal
            # circle-buffer undercoverage. This can conservatively overreject.
            error = radius * math.radians(delta/n)**2 / 8
            if error:
                hull = Polygon([(x+dx, y+dy) for x, y in hull.exterior.coords
                                for dx, dy in ((-error,-error),(-error,error),
                                               (error,-error),(error,error))]).convex_hull
            pieces.append(hull)
    envelope = unary_union(pieces)
    blocked = unary_union(obstacles)
    outside = envelope.difference(drivable).area
    overlap = envelope.intersection(blocked).area
    touches = not blocked.is_empty and envelope.intersects(blocked)
    clear = drivable.covers(envelope) and not touches
    clearances = [envelope.distance(drivable.boundary)]
    if not blocked.is_empty:
        clearances.append(envelope.distance(blocked))
    payload = {'vehicle': {key: vehicle[key] for key in FIELDS}, 'poses': poses,
               'drivable': mapping(drivable), 'obstacles': [mapping(g) for g in obstacles],
               'source_binding': source_binding, 'interpolation': base['interpolation']}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                      allow_nan=False).encode()).hexdigest()
    return {**base, 'status': ('clear_conservative_envelope' if clear
                              else 'collision_or_clearance_conflict'),
            'minimum_clearance_m': min(clearances) if clear else 0.0,
            'clearance_scope': 'Conservative interpolated body envelope to drawn drivable boundary/obstacles; not verified steering trajectory',
            'input_sha256': digest, 'source_binding': source_binding,
            'source_authentication': 'caller_attribution_not_independently_authenticated',
            'outside_drivable_m2': outside, 'obstacle_overlap_m2': overlap,
            'obstacle_contact': touches, 'envelope': mapping(envelope),
            'intervals_evaluated': sum(steps), 'conservative_overrejection_possible': True}


def layout_maneuver_result(request, features):
    """Bind optional owner poses to drawn level geometry, never a supplied clear-area override."""
    proposal = (request.get('options') or {}).get('vehicle_maneuver')
    if proposal is None:
        return None
    refusal = {'schema': 'arr.masterplan.body_envelope.v1', 'status': 'refused',
               'kinematics_verified': False, 'legal_compliance_verified': False,
               'pending_reviews': ['vehicle_swept_path_review']}
    if not isinstance(proposal, dict) or type(proposal.get('level')) is not int:
        return {**refusal, 'missing_or_invalid': ['vehicle_maneuver.level']}
    level = proposal['level']
    binding = proposal.get('source_binding') or {}
    if not isinstance(binding, dict) or binding.get('level') != level:
        return {**refusal, 'missing_or_invalid': ['source_binding.level_mismatch']}
    target = proposal.get('target_stall_id')
    local = [f for f in features if (f.get('properties') or {}).get('level', 0) == level]
    selected = [f for f in local if f['properties'].get('layer') == 'parking_stall'
                and target is not None and f['properties'].get('stall_id') == target]
    if target is not None and len(selected) != 1:
        return {**refusal, 'missing_or_invalid': ['unique_drawn_target_stall_required']}
    try:
        drive = unary_union([shape(f['geometry']) for f in local if f['properties'].get('layer')
                             in ('parking_aisle', 'vehicular_access')] +
                            [shape(f['geometry']) for f in selected])
        layers = {'building_core', 'column', 'basement_room', 'basement_plant_zone', 'parked_vehicle'}
        if level == 0:
            ground_layer = ('building_ground_footprint' if any(f['properties'].get('layer') ==
                             'building_ground_footprint' for f in local) else 'building_footprint')
            layers.add(ground_layer)
        obstacles = [shape(f['geometry']) for f in local if f['properties'].get('layer') in layers]
        # Authored source obstacles also participate even if omitted from drawing.
        obstacles += [shape(g) for g in request.get('columns', [])]
        if request.get('core'):
            obstacles.append(shape(request['core']))
        geometry_hash = digest(features)
        if binding.get('layout_features_sha256') is not None and binding['layout_features_sha256'] != geometry_hash:
            return {**refusal, 'missing_or_invalid': ['source_binding.layout_features_sha256_mismatch']}
        return validate_maneuver(vehicle=proposal.get('vehicle'), poses=proposal.get('poses'),
                                 drivable=drive, obstacles=obstacles,
                                 source_binding={**binding, 'layout_features_sha256': geometry_hash})
    except (ValueError, TypeError, KeyError):
        return {**refusal, 'missing_or_invalid': ['invalid_serialized_maneuver_geometry']}
