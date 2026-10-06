"""Read a pinned delivered mesh for MasterPlan; never regenerate it or run a planner."""
import copy
import math
import os
from pathlib import Path
import re

from backend.app.modules.design.generation.maas.delivered.mass_export import BACKEND, digest, file_hash, read


def _contained(path, root):
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError('delivered source escapes configured export root')
    return resolved


def resolve_delivered_source(handle, *, output_root=None):
    """Receipt, files and identity verification only; no export/reconstruction fallback."""
    if not isinstance(handle, dict) or handle.get('schema_version') != 'arr.delivered_mass_handle.v1':
        raise ValueError('versioned delivered mass handle required')
    export_id = handle.get('export_id')
    if not isinstance(export_id, str) or not re.fullmatch('[0-9a-f]{64}', export_id):
        raise ValueError('invalid delivered export id')
    # The same name the writer (delivered_mass_export.py) and MasterPlanagent read.
    root = Path(output_root or os.environ.get('EDITOR_DELIVERED_MASS_EXPORT_ROOT',
        str(BACKEND / 'runtime/delivered-mass-exports'))).resolve(strict=True)
    target = _contained(root / export_id, root)
    receipt_path = _contained(target / 'receipt.json', root)
    if file_hash(receipt_path) != handle.get('receipt_sha256'):
        raise ValueError('delivered receipt hash mismatch')
    receipt = read(receipt_path)
    if receipt.get('request_hash') != export_id:
        raise ValueError('delivered export identity mismatch')
    result = receipt['result']
    if result.get('status') != 'succeeded' or result.get('request_hash') != export_id:
        raise ValueError('delivered export not successful')
    for key in ('source_identity', 'source_versions', 'source_run_id'):
        if not handle.get(key) or handle[key] != result.get(key):
            raise ValueError('delivered source identity mismatch: ' + key)
    candidate_id = handle.get('candidate_id')
    if candidate_id != 'mass-' + export_id[:24]:
        raise ValueError('delivered candidate identity mismatch')
    relative = f'dataset/candidates/{candidate_id}/candidate.json'
    expected = receipt.get('files', {}).get(relative)
    if not expected or expected != handle.get('candidate_sha256'):
        raise ValueError('candidate not pinned by delivered receipt')
    # Validate every retained export file before using any of its geometry.
    for name, expected_hash in receipt['files'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('invalid delivered artifact path')
        artifact = _contained(target / name, target)
        if file_hash(artifact) != expected_hash:
            raise ValueError('delivered artifact hash mismatch')
    candidate = read(_contained(target / relative, target))
    certificate = candidate.get('numeric_certificate') or {}
    identity = result.get('identity') or {}
    if (candidate.get('candidate_id') != candidate_id
            or candidate.get('authority') != 'verified_delivered_source_mass'
            or candidate.get('source_identity') != handle['source_identity']
            or candidate.get('source_versions') != handle['source_versions']
            or candidate.get('delivered_shape_id') != identity.get('shape_id')
            or certificate.get('shape_id') != identity.get('shape_id')
            or certificate.get('certificate_id') != identity.get('certificate_id')
            or not identity.get('shape_id') or not identity.get('certificate_id')):
        raise ValueError('delivered candidate certificate mismatch')
    if (digest(candidate.get('mesh')) != candidate.get('geometry_hash')
            or candidate['geometry_hash'] != handle.get('geometry_hash')):
        raise ValueError('delivered mesh hash mismatch')
    return candidate, receipt


def bind_delivered_mass(request, source_handle, *, output_root=None):
    """Bind exact source-local geometry; missing source frame prohibits planning."""
    from shapely.geometry import Polygon, mapping, shape
    from shapely.ops import unary_union
    from backend.app.modules.design.generation.maas.geometry_language.source_bridge import mesh_section_solid, solid_section_polygon

    candidate, receipt = resolve_delivered_source(source_handle, output_root=output_root)
    if not isinstance(request, dict) or request.get('pnu') != source_handle['source_identity'].get('pnu'):
        raise ValueError('mass source parcel does not match MasterPlan request')
    mesh = candidate['mesh']
    vertices, triangles = mesh['vertices'], mesh['triangles']
    if (not vertices or not triangles or any(len(p) != 3 or any(type(v) not in (int, float)
            or not math.isfinite(v) for v in p) for p in vertices)
            or any(len(t) != 3 or any(type(i) is not int or not 0 <= i < len(vertices) for i in t) for t in triangles)):
        raise ValueError('finite complete triangle mesh required')
    certificate = candidate['numeric_certificate']
    datum = ((certificate.get('structure') or {}).get('mesh_support') or {}).get('datum_m')
    if type(datum) not in (int, float) or not math.isfinite(datum):
        raise ValueError('recorded source model datum required')
    solid = mesh_section_solid(vertices, triangles)
    ground = solid_section_polygon(solid, datum)
    projection = unary_union([p for t in triangles
        if not (p := Polygon([(vertices[i][0], vertices[i][1]) for i in t])).is_empty and p.area > 0])
    if (ground is None or ground.is_empty or not ground.is_valid or projection.is_empty
            or not projection.is_valid or not projection.buffer(1e-6).covers(ground)):
        raise ValueError('invalid delivered projection or model-ground section')
    # Only metadata actually pinned by the export may establish a source frame.
    frame = candidate.get('coordinate_frame')
    missing = ['mass_ground_vehicle_clearance_review', 'mass_structural_soffit_beams_services_review',
               'mass_semantic_core_geometry_missing', 'mass_structural_column_geometry_unverified']
    verified_frame = isinstance(frame, dict) and all(k in frame for k in ('crs', 'origin_utm', 'units', 'up_axis'))
    registration = ((certificate.get('storey_limit') or {}).get('policy_evidence') or {}).get('frontage_registration') or {}
    canonical_local_match = (not verified_frame
        and request.get('coordinate_frame') == 'site-local metres: crs minus origin_utm'
        and bool(registration.get('reference_parcel_ring_local_m')))
    if request.get('coordinate_frame') == 'delivered_source_local' or canonical_local_match:
        ring = registration.get('reference_parcel_ring_local_m')
        if registration.get('coordinate_frame') != 'parcel UTM translated by its minimum x,y; metres' or not ring:
            raise ValueError('recorded source-local parcel frame required')
        parcel = Polygon(ring)
        supplied = shape(request.get('site') or {})
        if (not parcel.is_valid or parcel.is_empty or not supplied.is_valid
                or not parcel.equals_exact(supplied, 1e-8)):
            raise ValueError('delivered source-local parcel frame mismatch')
        frame = {'scope':'source_local_only','definition':registration['coordinate_frame'],
                 'crs':None,'origin_utm':None,'units':'m','up_axis':'z',
                 'parcel_geometry_hash':digest(mapping(parcel))}
        if canonical_local_match:
            frame['alignment_basis'] = 'exact_certificate_local_parcel_equality_no_transform'
            frame['destination_frame'] = {'crs':request.get('crs'),
                'origin_utm':copy.deepcopy(request.get('origin_utm')),
                'authority':'request_only_not_source_world_frame'}
        verified_frame = True
        missing.append('source_world_crs_origin_linkage_unverified')
    elif verified_frame:
        origin = frame['origin_utm']
        if not isinstance(origin, list) or len(origin) != 2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in origin):
            raise ValueError('finite delivered source coordinate frame origin required')
        if frame['units'] != 'm' or frame['up_axis'] != 'z' or frame['crs'] != request.get('crs') or frame['origin_utm'] != request.get('origin_utm'):
            raise ValueError('delivered source coordinate frame mismatch')
    else:
        missing.append('delivered_source_coordinate_frame_missing')
    measured = ((certificate.get('storey_limit') or {}).get('policy_evidence') or {}).get('datum_measured') is True
    if not measured:
        missing.append('measured_terrain_datum_unverified')
    return {'schema_version': 'arr.masterplan.delivered_mass_binding.v1',
        'status': 'needs_evidence', 'planner_invoked': False, 'permit_ready': False,
        'candidate_id': candidate['candidate_id'], 'source_identity': copy.deepcopy(candidate['source_identity']),
        'source_versions': copy.deepcopy(candidate['source_versions']),
        'source_run_id': source_handle['source_run_id'], 'source_handle_hash': digest(source_handle),
        'source_shape_id': candidate['delivered_shape_id'], 'geometry_hash': candidate['geometry_hash'],
        'coordinate_frame': copy.deepcopy(frame), 'frame_verified': verified_frame,
        'model_datum_m': datum, 'terrain_datum_measured': measured,
        'model_geometry': {'projection': mapping(projection), 'ground_section': mapping(ground)},
        'missing_evidence': missing,
        'scope': 'Exact retained source-local mesh projection and model-datum section; no parking layout or legal approval'}


def bind_delivered_request(request, source_handle, *, output_root=None):
    """Bind retained geometry into an already composed canonical request.

    Keep Site/Law/Program/district context intact. The whole projection stays
    excluded until under-wing clearance has independent evidence.
    """
    from shapely.geometry import shape
    binding = bind_delivered_mass(request, source_handle, output_root=output_root)
    result = {'source_binding': binding, 'planner_invoked': False}
    if not binding['frame_verified']:
        return {**result, 'status': 'needs_evidence'}
    projection = binding['model_geometry']['projection']
    if request.get('footprint') is not None and not shape(request['footprint']).equals_exact(shape(projection), 1e-8):
        raise ValueError('authored footprint conflicts with retained mass projection')
    if request.get('ground_footprint') is not None:
        raise ValueError('ground_footprint requires a separately verified clearance contract')
    prepared = copy.deepcopy(request)
    prepared['footprint'] = copy.deepcopy(projection)
    prepared.setdefault('options', {}).pop('planning_stage', None)
    prepared['mass_source_pending_reviews'] = list(dict.fromkeys([
        *(prepared.get('mass_source_pending_reviews') or []), *binding['missing_evidence']]))
    prepared.setdefault('evidence', {})['selected_mass'] = copy.deepcopy(binding)
    return {**result, 'status': 'prepared', 'request': prepared}


def prepare_delivered_surface(request, source_handle, *, output_root=None):
    """Prepare a conservative fixed-source surface request, without running it."""
    binding = bind_delivered_mass(request, source_handle, output_root=output_root)
    if not binding['frame_verified']:
        raise ValueError('verified source frame required before surface planning')
    access = bind_retained_access(request, source_handle, output_root=output_root)
    request = access['request']
    binding['district_access'] = access['evidence']
    if any(request.get(k) is not None for k in ('footprint','ground_footprint','core','basement_boundary')) or request.get('columns'):
        raise ValueError('surface source binding does not accept replacement mass or basement geometry')
    options = request.setdefault('options', {})
    target = options.get('target_parking_stalls')
    if type(target) is not int or not 0 < target <= 1000:
        raise ValueError('explicit positive integer surface design target required')
    options.update(parking_strategy='ground_surface',max_basement_levels=0,
                   joint_placement_search=False,compact_basement_search=False)
    options.pop('planning_stage',None)
    # The entire projection is excluded. The measured ground section remains
    # evidence only, never permission to park below an unverified raised wing.
    request['footprint'] = copy.deepcopy(binding['model_geometry']['projection'])
    law = request.setdefault('law', {})
    law['status'] = 'needs_evidence'
    law.setdefault('blocking', []).append('unapproved surface concept; legal applicability and access require review')
    request['mass_source_pending_reviews'] = list(binding['missing_evidence'])
    request.setdefault('evidence', {})['selected_mass'] = binding
    return {'request':request,'source_binding':binding,'planner_invoked':False}


def bind_retained_access(request, source_handle, *, output_root=None):
    """Apply the same source certificate's registered exclusion, not entrance approval."""
    from shapely.geometry import LineString, mapping, shape
    from shapely.ops import unary_union
    from backend.app.modules.design.generation.maas.massv2.parcel_policy import frontage_shapes_from_registration
    candidate, _ = resolve_delivered_source(source_handle, output_root=output_root)
    reg = ((candidate['numeric_certificate'].get('storey_limit') or {}).get('policy_evidence') or {}).get('frontage_registration')
    if (not reg or not reg.get('road_frontage') or not reg.get('vehicle_access_prohibited')
            or not reg.get('source_pdf_sha256') or not reg.get('source_pdf_page_1_based')):
        raise ValueError('retained district access registration required; unanchored parking refused')
    parcel, buildable, prohibited = frontage_shapes_from_registration(reg)
    if request.get('pnu') != candidate['source_identity'].get('pnu') or not parcel.equals_exact(shape(request['site']),1e-8):
        raise ValueError('retained district access parcel/frame mismatch')
    ring=reg['reference_parcel_ring_local_m']
    indices=reg[reg['road_frontage']['registered_edge_group']]['edge_indices_0_based']
    road=unary_union([LineString([ring[i],ring[(i+1)%len(ring)]]) for i in indices])
    # Registered transformed endpoints can differ from the road by floating
    # point noise. Exact line subtraction may retain a whole prohibited edge.
    # This is numeric equality tolerance, not a survey/legal setback.
    available=road.difference(prohibited.buffer(1e-6))
    if request.get('frontage') is not None:
        authored=shape(request['frontage'])
        if authored.difference(available.buffer(1e-6)).length > 1e-6 or authored.intersection(prohibited).length > 1e-6:
            raise ValueError('authored vehicle frontage crosses prohibited or unregistered interval')
        available=authored.intersection(available)
    if available.is_empty or available.length <= 1e-6:
        raise ValueError('no nonprohibited registered vehicle approach remains')
    evidence={'registration_id':reg['registration_id'],'source_pdf_sha256':reg['source_pdf_sha256'],
        'source_pdf_page_1_based':reg['source_pdf_page_1_based'],
        'coordinate_frame':reg['coordinate_frame'],'vehicle_prohibited':mapping(prohibited),
        'registered_road_frontage':mapping(road),'nonprohibited_approach':mapping(available),
        'vehicle_access_verified':False,'survey_verified':False,'legal_applicability':'unverified',
        'numeric_frame_tolerance_m':1e-6,
        'scope':'retained source registration geometry applied; actual entrance/egress and pedestrian design pending'}
    out=copy.deepcopy(request)
    out['frontage']=mapping(available)
    out['buildable']=mapping(buildable if out.get('buildable') is None else buildable.intersection(shape(out['buildable'])))
    out.setdefault('evidence',{}).update(frontage=evidence,buildable=evidence,district_access=evidence)
    return {'request':out,'evidence':evidence}
