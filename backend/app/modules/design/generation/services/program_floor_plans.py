"""Generate an explicitly bound Program gross-floor batch in the Plan owner."""
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path

from shapely.geometry import shape

from backend.app.modules.design.generation.services.floor_plan_contract import _validate
from backend.app.modules.design.generation.services.gross_zone_subdivision import subdivide_gross_zones
from backend.app.modules.design.generation.services.program_plan_artifacts import publish
from backend.app.modules.design.generation.services.plan_connectivity import measure as measure_connectivity
from backend.app.modules.design.generation.services.connected_reservations import reject_fragmented

BASIS = 'gross_functional_reservations'
CHECKS = ('net_room_geometry', 'program_allocation', 'egress', 'core_coordination',
          'accessibility', 'statutory_use_area_aggregation', 'parking_requirement')


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def _positive(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        return False


def validate(envelope):
    digest(envelope)
    if (not isinstance(envelope, dict) or envelope.get('schema_version') != 'program-plan/1'
            or envelope.get('prepared') is not True or envelope.get('planning_basis') != BASIS
            or envelope.get('permit_ready') is not False or not envelope.get('floor_bindings_hash')):
        raise ValueError('Prepared Program gross-floor proposal required')
    program, mass = envelope.get('program_identity'), envelope.get('mass_identity')
    if (not isinstance(program, dict) or not isinstance(mass, dict)
            or type(program.get('revision')) is not int or program['revision'] < 1
            or not all(program.get(key) for key in ('project_id', 'program_id', 'input_hash', 'snapshot_hash'))
            or not mass.get('geometry_hash') or not mass.get('identity')
            or (mass.get('source_identity') or {}).get('project') != program['project_id']):
        raise ValueError('Exact Program and Mass identities required')
    floors = envelope.get('floor_requests')
    if not isinstance(floors, list) or not 1 <= len(floors) <= 64:
        raise ValueError('Batch requires 1..64 explicit floor requests')
    seen_floors, seen_samples, seen_spaces = set(), set(), set()
    for floor in floors:
        if not isinstance(floor, dict):
            raise ValueError('Floor request must be an object')
        number, sample = floor.get('program_floor'), floor.get('mass_floor')
        if (type(number) is not int or number in seen_floors or not isinstance(sample, str)
                or not sample or sample in seen_samples):
            raise ValueError('Distinct explicit Program/Mass floors required')
        seen_floors.add(number); seen_samples.add(sample)
        elevation = floor.get('section_elevation_m')
        if type(elevation) not in (int, float) or not math.isfinite(elevation):
            raise ValueError('Finite source section elevation required')
        body = floor.get('body')
        if (not isinstance(body, dict) or body.get('planning_basis') != BASIS
                or body.get('algorithm') != 'subdivision' or not isinstance(body.get('options'), dict)
                or digest(body.get('program_binding')) != digest(program)):
            raise ValueError('Gross subdivision body must retain Program identity')
        binding = body.get('mass_binding') or {}
        if (not isinstance(binding, dict) or binding.get('floor') != sample
                or binding.get('footprint_hash') != digest(body.get('footprint_geojson'))
                or any(digest(binding.get(key)) != digest(value) for key, value in mass.items())):
            raise ValueError('Floor footprint must retain exact Mass binding')
        _validate(body)
        rooms = body.get('rooms')
        if not isinstance(rooms, list) or not 1 <= len(rooms) <= 256:
            raise ValueError('Floor needs 1..256 gross reservations')
        ids = []
        for room in rooms:
            if (not isinstance(room, dict) or not isinstance(room.get('space_id'), str)
                    or not room['space_id'] or room['space_id'] in seen_spaces
                    or not isinstance(room.get('name'), str) or not room['name'].strip()
                    or room.get('area_basis') != 'gross' or not _positive(room.get('area'))):
                raise ValueError('Distinct identified named gross reservations required')
            ids.append(room['space_id']); seen_spaces.add(room['space_id'])
        if ids != floor.get('space_ids'):
            raise ValueError('Floor space list differs from Program rooms')
        total = sum(room['area'] for room in rooms)
        if (not _positive(floor.get('gross_reserved_m2'))
                or not math.isclose(total, floor['gross_reserved_m2'], rel_tol=1e-9, abs_tol=1e-6)):
            raise ValueError('Floor gross total differs from Program rooms')
        if not math.isclose(total, shape(body['footprint_geojson']).area, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError('Gross floor reservations differ from footprint; no automatic rescaling')
    return floors


def generate(envelope, artifact_root):
    floors = validate(envelope)
    from backend.app.modules.design.generation.services.core_circulation_proposal import generate as generate_core_proposal
    core_proposal = generate_core_proposal(envelope, artifact_root)
    packet_hash = digest(envelope)
    acceptance = {'status': 'not_verified', 'checks': {key: 'not_verified' for key in CHECKS}}
    output, artifacts, rejected_artifacts = [], [], []
    for floor in floors:
        body = floor['body']
        result = reject_fragmented(subdivide_gross_zones(shape(body['footprint_geojson']), body['rooms'], body['options']))
        for variant in result['results'] + result['rejected_candidates']:
            refs = publish(Path(artifact_root) / packet_hash, floor, variant)
            variant['artifacts'] = refs
            (rejected_artifacts if variant['candidate_status'] == 'rejected' else artifacts).extend(refs)
        output.append({key: deepcopy(floor[key]) for key in ('program_floor', 'mass_floor',
            'section_elevation_m', 'space_ids', 'gross_reserved_m2')} | result | {
            'footprint_hash': digest(body['footprint_geojson']), 'design_acceptance': deepcopy(acceptance)})
    connectivity, issues = measure_connectivity(floors, output)
    empty = [floor['program_floor'] for floor in output if not floor['results']]
    generation = {'status': ('rejected' if len(empty) == len(output) else 'partial') if empty else 'candidates_available',
        'accepted_variants': sum(len(f['results']) for f in output),
        'rejected_variants': sum(len(f['rejected_candidates']) for f in output),
        'floors_without_connected_candidate': empty}
    findings = [{'id': 'plan-connectivity-' + digest(issue)[:20], 'severity': 'major',
        'category': 'geometry_source_qualification' if issue['code'] == 'disconnected_floor_footprint' else 'plan_geometry',
        'affected_nodes': (['geometry.mass', 'program.spaces', 'geometry.plan']
            if issue['code'] in ('disconnected_floor_footprint', 'no_common_core_stacking_envelope') else ['geometry.plan']),
        'evidence': deepcopy(issue), 'recommended_action': issue['requested_correction'],
        'raised_by': 'plan', 'recommended_agents': issue['recommended_agents']} for issue in issues]
    if core_proposal:
        for issue in core_proposal['geometric_failures']:
            findings.append({'id': 'plan-core-proposal-' + digest([packet_hash, issue])[:20],
                'severity': 'major', 'category': 'core_proposal_geometry',
                'affected_nodes': ['geometry.mass', 'program.spaces', 'geometry.plan'],
                'evidence': {'measurement': issue, 'basis_ref': core_proposal['basis_ref'],
                    'profile_ref': core_proposal['profile_ref'], 'unselected_proposal': True},
                'recommended_action': 'Revise the unselected core/discharge proposal or Mass envelope; measured conditional separation/path constraints are unmet. Do not treat this as a qualified legal violation.',
                'raised_by': 'plan', 'recommended_agents': ['mass', 'program', 'plan']})
        for change in core_proposal['program_revision_proposal']['common_area_changes']:
            if change['additional_gross_m2'] > 0:
                findings.append({'id': 'plan-core-area-' + digest([packet_hash, change])[:20],
                    'severity': 'major', 'category': 'program_core_allocation',
                    'affected_nodes': ['program.spaces', 'geometry.plan'],
                    'evidence': {'measurement': change, 'basis_ref': core_proposal['basis_ref'],
                        'profile_ref': core_proposal['profile_ref'], 'unselected_proposal': True},
                    'recommended_action': 'Author an explicit unselected Program allocation revision for measured core/circulation area; preserve source IDs and do not silently change functional targets.',
                    'raised_by': 'plan', 'recommended_agents': ['program', 'plan']})
    return {'schema_version': 'arr.program-floor-plans/1', 'status': 'needs_revision' if empty else 'needs_evidence',
        'planning_basis': BASIS, 'program_identity': deepcopy(envelope['program_identity']),
        'mass_identity': deepcopy(envelope['mass_identity']), 'program_plan_hash': packet_hash,
        'floor_bindings_hash': envelope.get('floor_bindings_hash'), 'floor_results': output,
        'artifacts': artifacts, 'design_acceptance': acceptance, 'permit_ready': False,
        'physical_connectivity': connectivity, 'revision_issues': issues,
        'generation_acceptance': generation, 'rejected_artifacts': rejected_artifacts,
        'findings': findings,
        **({'core_proposal': core_proposal, 'core_artifacts': core_proposal['artifacts']} if core_proposal else {}),
        'scope': 'Gross functional-zone proposals, not net room plans or legal acceptance'}
