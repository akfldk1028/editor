"""Verified MasterPlan placement boundary for authored BOOK geometry."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path

from shapely.geometry import shape

KEY = 'masterplan_development'
PROGRAM_PROJECTION = 'large_review_sections_are_receipts; snapshot_hash_identifies_stored_original'

def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def validate_packet(packet):
    if not isinstance(packet, dict) or packet.get('schema_version') != 'masterplan.mass_development.v1':
        raise ValueError('unsupported MasterPlan development packet')
    raw = {k: v for k, v in packet.items() if k != 'package_hash'}
    digest = _digest(raw)
    if digest != packet.get('package_hash'):
        raise ValueError('MasterPlan package hash mismatch')
    for key in ('source_identity', 'source_versions', 'layout', 'law', 'program', 'binding', 'design_domain'):
        if not isinstance(packet.get(key), dict) or not packet[key]:
            raise ValueError('MasterPlan packet missing ' + key)
    frame = packet['binding'].get('coordinate_frame')
    if not isinstance(frame, dict) or frame != packet['design_domain'].get('coordinate_frame'):
        raise ValueError('MasterPlan coordinate frame mismatch')
    origin = frame.get('origin_utm')
    if (not frame.get('crs') or not frame.get('coordinate_frame') or not isinstance(origin, (list, tuple))
            or len(origin) != 2 or any(type(n) not in (int, float) or not math.isfinite(n) for n in origin)):
        raise ValueError('MasterPlan requires an explicit metric coordinate frame')
    domain = shape(packet['design_domain']['geometry'])
    if domain.geom_type not in ('Polygon', 'MultiPolygon') or domain.is_empty or not domain.is_valid or domain.area <= 0:
        raise ValueError('MasterPlan design domain must be a valid Polygon or MultiPolygon')
    from shapely.ops import unary_union
    layout, binding = packet['layout'], packet['binding']
    metric, features = layout.get('metric_request') or {}, layout.get('metric_features')
    handoff = layout.get('handoff') or {}
    if (binding.get('input_hash') != _digest(metric)
            or binding.get('metric_geometry_hash') != _digest(features)
            or frame != {k: metric.get(k) for k in ('crs', 'origin_utm', 'coordinate_frame')}
            or frame['coordinate_frame'] != 'site-local metres: crs minus origin_utm'
            or metric.get('pnu') != packet['source_identity'].get('pnu')
            or handoff.get('input_hash') != binding['input_hash']
            or handoff.get('metric_geometry_hash') != binding['metric_geometry_hash']
            or handoff.get('pnu') != metric['pnu'] or handoff.get('evaluated') is not True
            or (layout.get('validation') or {}).get('geometry_status') != 'passed'
            # needs_revision is a confirmed card with reviews still open, not a failed geometry; MasterPlan hands it on
            # with those reviews (684-1 2026-11-03, the 4-storey card that passed every geometry check).
            or layout.get('status') == 'failed'):
        raise ValueError('MasterPlan source layout binding mismatch')
    parts = [shape(f['geometry']) for f in features
             if (f.get('properties') or {}).get('layer') == 'building_footprint'
             and f['properties'].get('level', 0) == 0]
    # `metric_request.buildable` is only set when a caller supplied one; otherwise the engine derived the buildable
    # area itself and froze it among the hashed metric features (MasterPlan mass_development.py; the first editor
    # selection's book step crashed on None here, Mass cycle editor-2adfa67bd8 on 684-1, 2026-10-29).
    buildable = metric.get('buildable') or next(
        (f['geometry'] for f in features if (f.get('properties') or {}).get('layer') == 'buildable_boundary'), None)
    if buildable is None:
        raise ValueError('MasterPlan selected layout carries no buildable domain')
    if (not parts or not unary_union(parts).equals(domain)
            or not shape(buildable).buffer(1e-6).covers(domain)):
        raise ValueError('MasterPlan design domain differs from selected layout')
    for key in ('law', 'program'):
        snapshot = packet[key]
        if (snapshot.get('pnu', metric['pnu']) != metric['pnu']
                or snapshot.get('source_identity', packet['source_identity']) != packet['source_identity']
                or snapshot.get('source_versions', packet['source_versions']) != packet['source_versions']
                # Program's transport projection (ProgramAgent service.py) names the stored original by its
                # snapshot_hash, so that hash cannot be recomputed from the projection; only Program's, only that marker.
                or ('snapshot_hash' in snapshot and not (key == 'program' and snapshot.get('transport_projection') == PROGRAM_PROJECTION)
                    and snapshot['snapshot_hash'] != _digest({k: v for k, v in snapshot.items() if k != 'snapshot_hash'}))):
            raise ValueError('MasterPlan ' + key + ' snapshot binding mismatch')
    return packet


def environment_packet():
    path = os.environ.get('MASS_MASTERPLAN_DEVELOPMENT')
    return validate_packet(json.loads(Path(path).read_text(encoding='utf-8'))) if path else None


def bind_program(program, packet):
    from .dimensional_intent import program_intent
    validate_packet(packet)
    existing = program.metadata.get(KEY)
    if existing is not None and existing != packet:
        raise ValueError('authored MasterPlan binding differs from frozen owner packet')
    if program_intent(program) is None:
        raise ValueError('MasterPlan-bound BOOK requires an authored dimensional_intent floor schedule')
    return replace(program, metadata={**program.metadata, KEY: deepcopy(packet)})


def bound_dimensions(program):
    from .dimensional_intent import program_intent
    from .book_development import exact_dimensions
    exact = exact_dimensions(program.to_dict())
    if exact is not None:
        packet = validate_packet(program.metadata[KEY])
        if (exact.get(KEY) != packet or exact['site_pnu'] != packet['source_identity']['pnu']):
            raise ValueError('MasterPlan development differs from verified parent binding')
        return exact
    return program_intent(program)


def compile_bound_source(program, legal_host, site, *, floor_count):
    from .geometry_language.compiler import compile_geometry_program
    from .geometry_language.source_bridge import compile_site_bound_geometry_program_to_source_mass
    from .dimensional_intent import program_intent
    packet = validate_packet(program.metadata[KEY])
    identity = packet['source_identity']
    if site is None or str(site.pnu) != str(identity.get('pnu')) or site.building_type != identity.get('building_type'):
        raise ValueError('MasterPlan source identity differs from legal site')
    frame = packet['binding']['coordinate_frame']
    from backend.app.modules.design.generation.services.site_geometry import _to_utm
    legal_crs = getattr(site, 'crs', None) or _to_utm.target_crs.to_string()
    if frame['crs'] != legal_crs:
        raise ValueError('MasterPlan CRS differs from legal site geometry owner')
    if tuple(frame['origin_utm']) != tuple(site.site_origin_utm):
        raise ValueError('MasterPlan coordinate frame differs from legal site')
    intent = bound_dimensions(program)
    if intent is None or floor_count != intent['storey_count']:
        raise ValueError('MasterPlan-bound BOOK floor schedule missing or changed')
    compilation = compile_geometry_program(program)
    bounds = compilation.metrics.get('bounds') or []
    height = intent['storey_count'] * intent['storey_height_m']
    if (len(bounds) != 2 or abs(bounds[0][2]) > 1e-7 or abs(bounds[1][2] - height) > 1e-6):
        raise ValueError('MasterPlan-bound authored metric height differs from floor schedule')
    domain = shape(packet['design_domain']['geometry'])
    host = domain.intersection(legal_host)
    # The existing exact exporter accepts one connected host. A disconnected
    # domain is supported by selecting its component that covers the whole mesh.
    hosts = list(host.geoms) if host.geom_type == 'MultiPolygon' else [host]
    source = None
    for part in hosts:
        if part.is_empty or part.geom_type != 'Polygon' or part.area < 1.:
            continue
        source = compile_site_bound_geometry_program_to_source_mass(program, part,
            name=program.name, floor_count=floor_count)
        if source is not None:
            break
    if source is None:
        raise ValueError('authored geometry lies outside MasterPlan design domain or legal host')
    from .massv2.parcel_policy import source_plan_projection
    projection, _ = source_plan_projection(source)
    if not domain.buffer(1e-7).covers(projection):
        raise ValueError('delivered geometry lies outside MasterPlan design domain')
    # Conservative whole-mass containment at every authored storey top avoids
    # silently clipping upper floors or treating ground containment as legal proof.
    for index in range(floor_count):
        if not site.plan_at((index + 1) * intent['storey_height_m']).buffer(1e-7).covers(projection):
            raise ValueError('authored geometry exceeds a legal height section')
    return replace(source, metadata={**source.metadata, KEY: deepcopy(packet),
        'masterplan_package_hash': packet['package_hash'], 'source_identity': deepcopy(identity),
        'source_versions': deepcopy(packet['source_versions']), 'coordinate_frame': deepcopy(frame),
        'datum_m': 0., 'authored_height_m': height})


def compile_bound_record(rec, legal_host, site):
    """Shared by stage and tracked rebuild; never refit a selected placement."""
    from .geometry_language.ast import GeometryProgram
    from .dimensional_intent import program_intent
    from .delivered.book_floors import delivered_floor_evidence
    from .massv2.parcel_policy import area_limit_evidence, storey_limit_evidence
    art = rec.get('geometry_artifact') or {}
    payload = art.get('authoredGeometryProgram') or art.get('geometryProgram')
    try:
        program = GeometryProgram.from_dict(payload)
        intent = bound_dimensions(program)
        count, storey_m = intent['storey_count'], intent['storey_height_m']
        source = compile_bound_source(program, legal_host, site, floor_count=count)
        storeys = art.get('storeyEvidence') or {}
        source = replace(source, metadata={**source.metadata, 'book_floor_count': count,
            'book_storey_height_m': storey_m, 'book_original_storey_evidence': storeys})
        floors = delivered_floor_evidence(source, storeys, floor_count=count, storey_m=storey_m)
        if not floors['measurement_consistent']:
            raise ValueError('MasterPlan-bound delivered floor measurement inconsistent')
        source = replace(source, metadata={**source.metadata, 'book_floor_area_m2': floors['actual_gfa_m2'],
            'book_delivered_floor_evidence': floors,
            # The importer uses this owner-issued marker to retain BOOK's
            # measured floor ruler through storey, area and plausibility gates.
            'book_height_certificate': 'verified_masterplan_bound_floor_schedule'})
        storey_gate = storey_limit_evidence(source, site, storey_m=storey_m,
                                           book_floor_count=count, source_kind='book')
        area_gate = area_limit_evidence(source, site, floors['actual_gfa_m2'])
        if not storey_gate['satisfied'] or not area_gate['satisfied']:
            raise ValueError('MasterPlan-bound geometry failed legal area/storey gate')
        return source, {'trace': rec.get('trace_sequence_name'), 'thesis': rec.get('thesis', ''),
            'verbs': [], 'height_m': count * storey_m, 'footprint_m2': floors['mesh_projection_m2'],
            'requested_footprint_m2': floors['mesh_projection_m2'], 'floor_area_m2': floors['actual_gfa_m2'],
            'delivered_floor_evidence': floors, 'book_floor_count': count,
            'book_storey_height_m': storey_m, 'original_book_storey_height_m': storey_m,
            'original_storey_evidence': storeys, 'storey_limit': storey_gate,
            KEY: deepcopy(program.metadata[KEY])}
    except (ValueError, TypeError, KeyError) as exc:
        return None, 'MasterPlan-bound BOOK: ' + str(exc)
