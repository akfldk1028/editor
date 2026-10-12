"""Composition gates for a placement shortlist, separate from permit approval."""
import math
from shapely.geometry import shape
from .parking_targets import target_mode, target_observation


def axis(geometry):
    pts = list(geometry.minimum_rotated_rectangle.exterior.coords)
    a, b = max(zip(pts, pts[1:]), key=lambda p: math.dist(*p))
    return math.degrees(math.atan2(b[1]-a[1], b[0]-a[0])) % 90


def review_placement(request, result):
    features = result.get('metric_features') or result.get('features', [])
    failures, review_findings = [], []
    m = result.get('metrics', {})
    target = max(m.get('planned_parking_stalls') or 0, m.get('required_parking_stalls') or 0)
    stalls = [f for f in features if f['properties']['layer']=='parking_stall']
    from backend.app.modules.design.generation.maas.masterplan.stall_banks import banks
    if target>1:
        for level in {f['properties'].get('level',0) for f in stalls}:
            level_stalls=[f for f in stalls if f['properties'].get('level',0)==level]
            if any(len(bank)==1 for bank in banks(level_stalls)):
                review_findings.append('isolated_single_bay')
    required_target = max(m.get('required_parking_stalls') or 0,
                          (m.get('planned_parking_stalls') or 0) if target_mode(request) == 'required' else 0)
    if len(stalls) < required_target:
        failures.append('parking_target')
    surface_target = request.get('options', {}).get('target_surface_stalls')
    if surface_target is not None and sum(f['properties'].get('level',0)==0 for f in stalls) != surface_target:
        failures.append('surface_allocation_target')
    if result.get('validation', {}).get('geometry_status') != 'passed':
        failures.append('independent_geometry')
    passed = {c['id'] for c in result.get('validation', {}).get('checks', []) if c.get('status')=='passed'}
    for level in {f['properties'].get('level', 0) for f in stalls}:
        if level < 0 and f'placement_full_width_drive:{level}' not in passed:
            failures.append('full_width_certificate_missing')
    buildings = [shape(f['geometry']) for f in features if f['properties']['layer']=='building_footprint']
    if not buildings:
        failures.append('building_zone_missing')
    else:
        reference = axis(buildings[0])
        if not request.get('buildable'):
            failures.append('buildable_boundary_unconfirmed')
        elif not shape(request['buildable']).buffer(1e-5).covers(buildings[0]):
            failures.append('building_zone_outside_buildable')
        for f in features:
            layer = f['properties']['layer']
            if layer not in ('parking_stall', 'basement_room'):
                continue
            g = shape(f['geometry'])
            rectangle = g.minimum_rotated_rectangle
            if g.area <= 0 or g.symmetric_difference(rectangle).area > max(1e-5, g.area*1e-6):
                failures.append('clipped_or_tapered_' + layer)
                continue
            delta = abs(axis(g)-reference)
            if min(delta, 90-delta) > 1:
                review_findings.append('inconsistent_module_axis')
    return {'schema_version':'masterplan.placement-quality.v1',
            'policy_version':4, 'review_findings':sorted(set(review_findings)),
            'parking_target': target_observation(request, m.get('planned_parking_stalls'), len(stalls)),
            'eligible':not failures, 'failures':sorted(set(failures)),
            **({'status':'needs_evidence'} if 'buildable_boundary_unconfirmed' in failures else {}),
            'scope':'shortlist composition and independently checked capacity; not Mass/Plan or permit approval'}
