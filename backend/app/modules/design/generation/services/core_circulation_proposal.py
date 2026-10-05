"""Explicitly unselected dimensional core/circulation proposal, not approval."""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
import math
from pathlib import Path

from shapely.affinity import rotate, translate
from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union

from backend.app.modules.design.generation.services.core_proposal_geometry import placements, farthest_pair, maximum_diagonal, route


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                            allow_nan=False).encode()).hexdigest()


def _artifact(ref):
    path = Path(ref['path'])
    if not path.is_absolute():
        raise ValueError('Core design artifact must have absolute path')
    content = path.read_bytes()
    if sha256(content).hexdigest() != ref['sha256']:
        raise ValueError('Core design artifact byte hash mismatch')
    return json.loads(content)


def stair_dimensions(height, assumed, law):
    values = [height, *[assumed[key] for key in ('max_riser_m', 'tread_m', 'wall_m', 'flight_gap_m')],
              *[law[key] for key in ('stairs_clear_width_m', 'landing_clear_width_m', 'max_vertical_landing_interval_m')]]
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError('Positive finite stair proposal dimensions required')
    risers = math.ceil(height / assumed['max_riser_m'])
    flights = [risers // 2, risers - risers // 2]
    rise = height / risers
    if max(flights) * rise > law['max_vertical_landing_interval_m']:
        raise ValueError('Two-flight proposal exceeds vertical landing interval; additional landing design required')
    return {'riser_count': risers, 'flight_risers': flights, 'riser_height_m': rise,
        'tread_depth_m': assumed['tread_m'], 'flight_clear_width_m': law['stairs_clear_width_m'],
        'landing_clear_width_m': law['landing_clear_width_m'],
        'width_m': 2 * law['stairs_clear_width_m'] + assumed['flight_gap_m'] + 2 * assumed['wall_m'],
        'depth_m': (max(flights) - 1) * assumed['tread_m'] + 2 * law['landing_clear_width_m'] + 2 * assumed['wall_m'],
        'wall_m': assumed['wall_m'], 'flight_gap_m': assumed['flight_gap_m'],
        'storey_height_m': height, 'headroom_verified': False,
        'scope': 'Dimensioned two-flight proposal; stair opening and3D headroom not verified.'}


def generate(envelope, output_root):
    floors = envelope['floor_requests']
    options = floors[0]['body']['options']
    if 'core_design_basis' not in options and 'core_design_profile' not in options:
        return None
    basis_ref, profile_ref = options['core_design_basis'], options['core_design_profile']
    for floor in floors:
        other = floor['body']['options']
        if _digest([other.get('core_design_basis'), other.get('core_design_profile')]) != _digest([basis_ref, profile_ref]):
            raise ValueError('Core profile must be identical across the bound floor batch')
    basis, profile = _artifact(basis_ref), _artifact(profile_ref)
    if (basis.get('schema_version') != 'law.core-design-basis/1'
            or basis.get('permit_ready') is not False
            or basis.get('status') != 'design_assumptions_not_qualified_legal_requirements'
            or profile.get('schema_version') != 'arr.core-design-profile/1'
            or profile.get('status') != 'unselected_owner_design_assumptions'
            or profile.get('program_identity') != envelope['program_identity']
            or profile.get('mass_geometry_hash') != envelope['mass_identity']['geometry_hash']
            or basis.get('project_id') != envelope['program_identity']['project_id']
            or basis.get('program_revision') != envelope['program_identity']['revision']):
        raise ValueError('Core design basis/profile must bind current Program and occupied geometry')
    height_source = _artifact(profile['floor_height_source'])
    elevations = height_source['storey_evidence']['floor_elevations_m']
    centers = height_source['storey_evidence']['floor_center_elevations_m']
    if (len(elevations) != len(floors) + 1 or centers != [f['section_elevation_m'] for f in floors]
            or height_source['delivered_shape_id'] != envelope['mass_identity']['identity']['shape_id']
            or height_source['geometry_hash'] != envelope['mass_identity']['source_mesh_hash']
            or height_source['numeric_certificate']['certificate_id'] != envelope['mass_identity']['identity']['certificate_id']):
        raise ValueError('Core height source does not match bound floor schedule and Mass identity')
    heights = [float(Decimal(str(b)) - Decimal(str(a))) for a, b in zip(elevations, elevations[1:])]
    law, assumed = basis['proposal_profile'], profile['dimensional_assumptions']
    if law['stairs_count'] != 2:
        raise ValueError('Core prototype currently requires an explicit two-stair proposal basis')
    dimensions = [stair_dimensions(height, assumed, law) for height in heights]
    width = max(d['width_m'] for d in dimensions); depth = max(d['depth_m'] for d in dimensions)
    polygons = [shape(f['body']['footprint_geojson']) for f in floors]
    common = polygons[0]
    for polygon in polygons[1:]: common = common.intersection(polygon)
    if common.is_empty:
        raise ValueError('No full-height occupied core placement envelope')
    corridor_width = law['corridor_clear_width_m']
    step, angles = assumed['placement_step_m'], assumed['placement_angles_deg']
    if (type(step) not in (int, float) or not math.isfinite(step) or step <= 0
            or not isinstance(angles, list) or not 1 <= len(angles) <= 8
            or any(type(a) not in (int, float) or not math.isfinite(a) for a in angles)):
        raise ValueError('Bounded explicit core placement resolution/angles required')
    candidates = placements(common, width, depth, assumed['wall_m'] + law['landing_clear_width_m'] / 2,
                            corridor_width, step, angles)
    pair = farthest_pair(candidates)
    if pair is None:
        raise ValueError('Explicit stair dimensions do not fit two full-height core placements')
    stairs = [dict(pair[1], core_id='stair-A', through_floor=len(floors)),
              dict(pair[2], core_id='stair-B', through_floor=len(floors))]
    lower_search = {'status': 'not_needed', 'candidate_count': 0}
    if len(floors) >= 3:
        lower = polygons[0].intersection(polygons[1]).intersection(polygons[2])
        lower_candidates = placements(lower, width, depth, assumed['wall_m'] + law['landing_clear_width_m'] / 2,
                                      corridor_width, step, angles)
        best = None
        for candidate in lower_candidates:
            if candidate['geometry'].difference(common).area <= 0:
                continue
            if any(candidate['geometry'].intersects(s['geometry']) for s in stairs):
                continue
            distance = max(math.dist(candidate['entry'], s['entry']) for s in stairs)
            if best is None or distance > best[0]: best = distance, candidate
        lower_search = {'status': 'candidate_found' if best else 'no_additional_sampled_placement',
            'candidate_count': len(lower_candidates), 'step_m': step, 'angles_deg': angles,
            'global_infeasibility_proved': False}
        if best:
            lower_search['best_entry_separation_m'] = best[0]
            lower_search['improves_existing_entry_separation'] = best[0] > pair[0]
            if best[0] > pair[0]:
                stairs.append(dict(best[1], core_id='stair-C', through_floor=3))
            else:
                lower_search['status'] = 'sampled_candidate_rejected_no_separation_improvement'
    shaft_width, shaft_depth = assumed['lift_shaft_m']
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in (shaft_width, shaft_depth)):
        raise ValueError('Positive explicit lift shaft dimensions required')
    lift_candidates = placements(common, shaft_width, shaft_depth, shaft_depth / 2,
                                 corridor_width, step, [0])
    from shapely.geometry import Point
    lift_candidates = [c for c in lift_candidates if not any(
        c['geometry'].intersects(s['geometry'])
        or c['geometry'].distance(Point(s['port'])) < corridor_width / 2
        or s['geometry'].distance(Point(c['port'])) < corridor_width / 2 for s in stairs)]
    if not lift_candidates:
        raise ValueError('Explicit lift shaft reservation does not fit beside stairs')
    lift_candidates.sort(key=lambda c: math.dist(c['entry'], stairs[0]['entry']))
    scored = []
    for candidate in lift_candidates[:16]:
        trial = route(common, [s['geometry'] for s in stairs] + [candidate['geometry']],
                      stairs[0], candidate, corridor_width)
        if trial is not None and trial['outside_m2'] <= 1e-8:
            scored.append((trial['length_m'], candidate))
    lift = min(scored, key=lambda pair: pair[0])[1] if scored else lift_candidates[0]
    return _floor_proposals(envelope, output_root, basis_ref, profile_ref, profile, law, dimensions,
                            polygons, stairs, lift, lower_search, common, elevations)


def _stair_parts(item, dimensions, level):
    d = dimensions
    wall, clear, landing = d['wall_m'], d['flight_clear_width_m'], d['landing_clear_width_m']
    going, width, depth = d['tread_depth_m'], d['width_m'], d['depth_m']
    parts = [('floor_landing', box(wall, wall, width-wall, wall+landing), level),
             ('intermediate_landing', box(wall, depth-wall-landing, width-wall, depth-wall),
              level + d['flight_risers'][0] * d['riser_height_m'])]
    for flight, count in enumerate(d['flight_risers']):
        x = wall if flight == 0 else wall + clear + d['flight_gap_m']
        for tread in range(count - 1):
            y = wall + landing + (tread if flight == 0 else count - 2 - tread) * going
            z = level + (tread + 1 + (d['flight_risers'][0] if flight else 0)) * d['riser_height_m']
            parts.append((f'flight_{flight+1}_tread_{tread+1}', box(x, y, x+clear, y+going), z))
    return [{'component': name, 'geometry': mapping(translate(rotate(geom, item['angle_deg'], origin=(0,0)),
                xoff=item['origin'][0], yoff=item['origin'][1])), 'finished_elevation_m': z,
             'headroom_verified': False} for name, geom, z in parts]


def _floor_proposals(envelope, output_root, basis_ref, profile_ref, profile, law, dimensions,
                     polygons, stairs, lift, lower_search, common, elevations):
    from backend.app.modules.design.generation.services.program_plan_artifacts import publish
    rows, artifacts, revision_rows, failures = [], [], [], []
    source_hash = _digest(envelope)
    for index, (floor, polygon, dim) in enumerate(zip(envelope['floor_requests'], polygons, dimensions)):
        # The top plan depicts the incoming flight, not a flight to an assumed roof.
        if index == len(polygons) - 1 and index > 0:
            dim = dimensions[index - 1]
        active = [s for s in stairs if s['through_floor'] >= index + 1]
        obstacles = [s['geometry'] for s in active] + [lift['geometry']]
        routes = [route(polygon, obstacles, active[0], end, law['corridor_clear_width_m'])
                  for end in [*active[1:], lift]]
        route_ok = all(r is not None and r['outside_m2'] <= 1e-8 for r in routes)
        geometries = obstacles + [r['geometry'] for r in routes if r is not None]
        reservation = unary_union(geometries)
        sid = profile['common_space_ids'][str(floor['program_floor'])]
        source_room = next((r for r in floor['body']['rooms'] if r['space_id'] == sid), None)
        if source_room is None:
            raise ValueError('Explicit core/common reservation ID missing from Program floor')
        separation = max(math.dist(a['entry'], b['entry']) for i, a in enumerate(active) for b in active[i+1:])
        required = maximum_diagonal(polygon) * law['stair_separation']['plan_diagonal_ratio']
        separated = separation >= required
        if not route_ok or not separated:
            failures.append({'program_floor': floor['program_floor'], 'mass_floor': floor['mass_floor'],
                'corridor_connected': route_ok, 'entry_separation_m': separation, 'proposal_required_separation_m': required})
        features = []
        for item, name, color in [(s, s['core_id'], '#c2410c') for s in active] + [(lift, 'Lift shaft reservation', '#7c3aed')]:
            features.append({'type': 'Feature', 'geometry': mapping(item['geometry']), 'properties': {
                'space_id': sid, 'room_name': name, 'area_m2': item['geometry'].area, 'color': color,
                'source_space_id': sid, 'entry': list(item['entry']), 'proposal_only': True}})
            if 'core_id' in item:
                level = elevations[index if index < len(polygons)-1 else max(0, index-1)]
                for part in _stair_parts(item, dim, level):
                    features.append({'type': 'Feature', 'geometry': part['geometry'], 'properties': {
                        'space_id': sid, 'source_space_id': sid, 'room_name': part['component'],
                        'area_m2': shape(part['geometry']).area, 'color': '#ffedd5',
                        'render_as_detail': True, 'stair_id': item['core_id'],
                        'finished_elevation_m': part['finished_elevation_m'], 'headroom_verified': False}})
                door_width = law['stair_entry_clear_width_m']
                x = 0 if item['entry_side'] == -1 else item['width_m'] - dim['wall_m']
                y = item['entry_offset_m']
                door = translate(rotate(box(x, y-door_width/2, x+dim['wall_m'], y+door_width/2),
                    item['angle_deg'], origin=(0,0)), xoff=item['origin'][0], yoff=item['origin'][1])
                features.append({'type': 'Feature', 'geometry': mapping(door), 'properties': {
                    'space_id': sid, 'source_space_id': sid, 'room_name': 'Proposed stair entry opening',
                    'area_m2': door.area, 'clear_width_m': door_width, 'color': '#ffffff',
                    'render_as_detail': True, 'stair_id': item['core_id'],
                    'fire_rating_verified': False, 'door_swing_verified': False}})
        for i, r in enumerate(routes):
            if r:
                features.append({'type': 'Feature', 'geometry': mapping(r['geometry']), 'properties': {
                    'space_id': sid, 'source_space_id': sid, 'room_name': f'Clear corridor {i+1}',
                    'area_m2': r['geometry'].area, 'color': '#fbbf24', 'clear_width_m': r['clear_width_m'],
                    'centerline': mapping(r['centerline']), 'walking_length_m': r['length_m'], 'proposal_only': True}})
        drawing = {'design_id': 0, 'proposal_kind': 'core_circulation',
                   'floor_plan': {'type': 'FeatureCollection', 'features': features}}
        refs = publish(Path(output_root) / source_hash / 'core-proposal', floor, drawing)
        for ref in refs: ref['role'] = 'core_proposal_' + ('svg' if ref['media_type'] == 'image/svg+xml' else 'geojson')
        artifacts.extend(refs)
        rows.append({'program_floor': floor['program_floor'], 'mass_floor': floor['mass_floor'],
            'footprint_hash': floor['body']['mass_binding']['footprint_hash'],
            'source_space_ids': floor['space_ids'], 'common_space_id': sid,
            'geometry': drawing['floor_plan'], 'common_reservation_geometry': mapping(reservation),
            'common_gross_m2': reservation.area, 'source_common_gross_m2': source_room['area'],
            'stair_dimensions': dim, 'stair_count': len(active),
            'stair_flight_projection': 'toward_next_floor' if index < len(polygons)-1 else 'incoming_from_floor_below_no_roof_access_assumed',
            'entry_separation_m': separation, 'proposal_required_separation_m': required,
            'separation_satisfied_under_proposal': separated, 'corridor_connected': route_ok,
            'corridor_width_m': law['corridor_clear_width_m'],
            'corridor_outside_areas_m2': [r['outside_m2'] if r else None for r in routes],
            'common_outside_m2': reservation.difference(polygon).area,
            'route_lengths_m': [r['length_m'] if r else None for r in routes],
            'room_to_stair_walking_verified': False, 'headroom_verified': False,
            'lift_equipment_accessibility_verified': False, 'artifacts': refs})
        revision_rows.append({'program_floor': floor['program_floor'], 'space_id': sid,
            'prior_gross_m2': source_room['area'], 'measured_core_circulation_gross_m2': reservation.area,
            'additional_gross_m2': max(0, reservation.area - source_room['area']),
            'named_functional_areas_changed': False,
            'status': 'owner_allocation_revision_required' if reservation.area > source_room['area'] else 'fits_existing_common_allowance'})
    return {'schema_version': 'arr.core-circulation-proposal/1', 'status': 'needs_revision' if failures else 'needs_evidence',
        'selected': False, 'permit_ready': False, 'program_identity': deepcopy(envelope['program_identity']),
        'mass_identity': deepcopy(envelope['mass_identity']), 'basis_ref': basis_ref, 'profile_ref': profile_ref,
        'profile_status': profile['status'], 'source_plan_hash': source_hash,
        'full_height_stacking_envelope': mapping(common), 'lower_stair_search': lower_search,
        'floor_results': rows, 'artifacts': artifacts, 'geometric_failures': failures,
        'program_revision_proposal': {'status': 'not_applied', 'preserve_space_ids': True, 'common_area_changes': revision_rows},
        'pending_checks': ['actual_room_doors_and_paths', 'stair_openings_and_3d_headroom',
            'lift_equipment_and_accessibility', 'fire_enclosures_and_discharge', 'Law_applicability'],
        'scope': 'Unselected dimensioned owner prototype under conditional Law basis and explicit assumptions; no legal or room-plan acceptance.'}
