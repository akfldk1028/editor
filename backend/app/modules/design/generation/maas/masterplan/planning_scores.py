"""Transparent geometric relationship scores; no weighted architectural verdict."""
from collections import defaultdict
from shapely.geometry import shape
from shapely.ops import unary_union


def _group(items, scope):
    known = [x for x in items if x['status'] in ('passed', 'failed')]
    passed = sum(x['status'] == 'passed' for x in known)
    return {'score': round(100 * passed / len(known), 2) if known else None,
            'passed': passed, 'evaluated': len(known), 'expected': len(items),
            'coverage_pct': round(100 * len(known) / len(items), 2) if items else 0,
            'items': items, 'scope': scope}


def score_relationships(features, checks):
    by_id = defaultdict(list)
    for check in checks:
        by_id[check['id']].append(check)

    def evidence(ident):
        matches = by_id.get(ident, [])
        # Repeated checks must not let a later pass hide an earlier failure.
        states = {c.get('status') for c in matches}
        status = 'failed' if 'failed' in states else ('passed' if states == {'passed'} else 'unknown')
        return {'id': ident, 'status': status,
                'measurements': [{k: v for k, v in c.items() if k not in ('id', 'status')} for c in matches]}

    drive, stalls, ramps = defaultdict(list), [], []
    for f in features:
        props = f.get('properties', {})
        layer = props.get('layer')
        if layer in ('parking_aisle', 'vehicular_access') and f.get('geometry'):
            g = shape(f['geometry'])
            if g.is_valid and not g.is_empty:
                drive[props.get('level', 0)].append(g)
        if layer == 'parking_stall':
            stalls.append(props)
        if layer == 'ramp':
            ramps.append(props)
    cohesion = []
    for level, geometries in sorted(drive.items()):
        union = unary_union(geometries).buffer(1e-6)
        components = len(union.geoms) if hasattr(union, 'geoms') else 1
        cohesion.append({'id': f'single_drive_component:{level}',
                         'status': 'passed' if components == 1 else 'failed', 'components': components})
    ramp_items, joints, kerbs = [], [], []
    for p in ramps:
        rid = f"{p.get('from_level')}:{p.get('to_level')}"
        names = ['ramp_containment', 'ramp_profile_length', 'ramp_width', 'ramp_grade',
                 'ramp_departure_profile_endpoint', 'ramp_arrival_profile_endpoint']
        if str(p.get('layout_type', '')).startswith('curved'):
            names.append('ramp_curve_radius')
            kerbs.append(evidence(f'ramp_grade_kerbs:{rid}'))
        ramp_items.extend(evidence(f'{name}:{rid}') for name in names)
        joints.append(evidence(f"ramp_to_aisle_connection:{p.get('to_level')}"))
    stall_items = [evidence('stall_aisle_frontage:' + str(p['stall_id'])) if 'stall_id' in p
                   else {'id': f'stall_without_id:{i}', 'status': 'unknown'} for i, p in enumerate(stalls)]
    pedestrian = [evidence('pedestrian_arrival_to_facade_connection')]
    return {'schema_version': 'masterplan.relationship-scores.v2', 'overall_score': None,
            'purpose': 'validation_coverage_diagnostics_not_design_quality',
            'formula': '100 * passed / evaluated; coverage = evaluated / expected; unknown excluded, never passed',
            'groups': {
                'drive_continuity': _group(cohesion, 'Single polygon component per floor; diagnostic for shared-drive intent, not a universal preference or steering proof'),
                'drive_width': _group([evidence('entry_approach_width'),
                    *[evidence(f'placement_full_width_drive:{level}') for level in sorted(drive) if level < 0]],
                    'Entry width and basement full-width routes; ground full-width routes reported separately'),
                'ground_drive_width': _group([evidence('placement_full_width_drive:0')] if 0 in drive else [],
                    'Conservative road-to-ground-stall width certificate; incomplete certificates stay unknown, not steering proof'),
                'ramp_kerb_grade': _group(kerbs, 'Kerb grade measurements do not certify applicability or compliance'),
                'stall_frontage': _group(stall_items, 'Validator boundary contact length with aisle; not confirmed front-edge orientation or bay entry/exit maneuver'),
                'ramp_geometry': _group(ramp_items, 'Independent containment, width, radius and centreline grade checks against supplied rules'),
                'ramp_connections': _group(joints, 'Lower landing contact with aisle; not trajectory continuity'),
                'pedestrian_approach': _group(pedestrian, 'Declared approach to facade only; not an actual door'),
                'vehicle_maneuver': _group([{'id': 'vehicle_trajectory', 'status': 'unknown'}], 'No verified kinematic vehicle trajectories supplied'),
                'building_programme': _group([{'id': 'owner_programme_and_doors', 'status': 'unknown'}], 'Requires Programme/Mass/Plan evidence')},
            'scope': 'Geometric diagnostic scores, not overall design quality, legal approval or calibrated Jev scores'}
