import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from shapely.geometry import box, mapping

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram


def packet(domain=None):
    frame = {'crs': 'EPSG:32652', 'origin_utm': [100., 200.],
             'coordinate_frame': 'site-local metres: crs minus origin_utm'}
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    geometry = mapping(domain if domain is not None else box(10, 10, 30, 30))
    metric = {**frame, 'pnu': '123', 'buildable': mapping(box(0, 0, 100, 100))}
    features = [{'type': 'Feature', 'geometry': geometry,
                 'properties': {'layer': 'building_footprint', 'level': 0}}]
    layout = {'status': 'completed', 'metric_request': metric, 'metric_features': features,
              'validation': {'geometry_status': 'passed'},
              'handoff': {'pnu': '123', 'input_hash': digest(metric),
                          'metric_geometry_hash': digest(features), 'evaluated': True}}
    data = {'schema_version': 'masterplan.mass_development.v1',
            'source_identity': {'project': 'p', 'branch': 'b', 'pnu': '123', 'building_type': 'office'},
            'source_versions': {'law': 'l1', 'program': 'p1'}, 'run_id': 'r1',
            'layout': layout, 'law': {'owner': 'law'}, 'program': {'owner': 'program'},
            'binding': {'input_hash': digest(metric), 'metric_geometry_hash': digest(features), 'coordinate_frame': frame},
            'design_domain': {'geometry': geometry,
                              'coordinate_frame': frame}}
    data['package_hash'] = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return data


def program(x=15):
    return GeometryProgram(nodes=(
        GeometryNode('unit', 'primitive', 'box', parameters={'width': 1., 'depth': 1., 'height': 1.}),
        GeometryNode('placed', 'transform', 'matrix4', inputs=('unit',),
                     parameters={'matrix4': [[8., 0., 0., x], [0., 8., 0., 15.],
                                            [0., 0., 6., 0.], [0., 0., 0., 1.]]}),
    ), root_id='placed', name='placed',
    metadata={'dimensional_intent': {'schema_version': 'arr.maas.dimensional_intent.v1',
        'storey_count': 2, 'storey_height_m': 3., 'target_gfa_m2': 128.,
        'delivery_policy': 'preserve_physical_dimensions', 'programme_status': 'unknown'}})


def test_real_compiler_keeps_selected_position_and_refuses_outside_domain():
    from backend.app.modules.design.generation.maas.masterplan_development import bind_program, compile_bound_source
    p = bind_program(program(), packet())
    site = SimpleNamespace(pnu='123', building_type='office', site_origin_utm=(100., 200.),
                           plan_at=lambda z: box(0, 0, 100, 100))
    source = compile_bound_source(p, site.plan_at(0), site, floor_count=2)
    assert source is not None
    assert source.footprint.bounds == pytest.approx((15, 15, 23, 23))
    assert source.metadata['masterplan_development']['package_hash'] == packet()['package_hash']
    with pytest.raises(ValueError, match='domain'):
        compile_bound_source(bind_program(program(x=60), packet()), site.plan_at(0), site, floor_count=2)


def test_exact_payload_gets_owner_binding_and_rejects_wrong_frame():
    from backend.app.modules.design.generation.maas.creative_program_author import authored_programs_from_payload
    from backend.app.modules.design.generation.maas.masterplan_development import compile_bound_source
    result = authored_programs_from_payload({'geometry_programs': [program().to_dict()]}, expected_count=1,
                                           program_context={'masterplan_development': packet()})
    assert result[0].program.metadata['masterplan_development']['package_hash'] == packet()['package_hash']
    site = SimpleNamespace(pnu='123', building_type='office', site_origin_utm=(0., 0.),
                           plan_at=lambda z: box(0, 0, 100, 100))
    with pytest.raises(ValueError, match='frame'):
        compile_bound_source(result[0].program, site.plan_at(0), site, floor_count=2)


def test_domain_hole_is_not_filled():
    from backend.app.modules.design.generation.maas.masterplan_development import bind_program, compile_bound_source
    domain = box(10, 10, 30, 30).difference(box(14, 14, 16, 16))
    site = SimpleNamespace(pnu='123', building_type='office', site_origin_utm=(100., 200.),
                           plan_at=lambda z: box(0, 0, 100, 100))
    with pytest.raises(ValueError, match='domain'):
        compile_bound_source(bind_program(program(), packet(domain)), site.plan_at(0), site, floor_count=2)


def test_rehashed_enlarged_domain_is_refused():
    from backend.app.modules.design.generation.maas.masterplan_development import validate_packet
    value = packet()
    value['design_domain']['geometry'] = mapping(box(0, 0, 100, 100))
    value['package_hash'] = hashlib.sha256(json.dumps({k: v for k, v in value.items() if k != 'package_hash'},
        sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    with pytest.raises(ValueError, match='domain'):
        validate_packet(value)


@pytest.mark.parametrize('selection_mode', [None, 'user_selected', 'jury_recommended'])
def test_export_owner_issues_receipt_bound_handle(tmp_path, selection_mode):
    from backend.app.modules.design.generation.maas.delivered.mass_export import with_hrefs, digest
    from backend.app.modules.design.generation.maas.masterplan.delivered_source import resolve_delivered_source
    export_id = 'a' * 64
    target = tmp_path / export_id
    candidate_id = 'mass-' + export_id[:24]
    path = target / 'dataset/candidates' / candidate_id / 'candidate.json'
    path.parent.mkdir(parents=True)
    identity, versions = packet()['source_identity'], packet()['source_versions']
    mesh = {'vertices': [[0, 0, 0]], 'triangles': []}
    candidate = {'candidate_id': candidate_id, 'source_identity': identity, 'source_versions': versions,
        'authority': 'verified_delivered_source_mass', 'mesh': mesh, 'geometry_hash': digest(mesh),
        'delivered_shape_id': 'shape', 'numeric_certificate': {'shape_id': 'shape', 'certificate_id': 'cert'},
        'masterplan_development_hash': packet()['package_hash']}
    if selection_mode:
        candidate.update(selected_mass_id='book:choice', selection_mode=selection_mode)
        candidate['numeric_certificate']['name'] = 'book:choice'
    path.write_text(json.dumps(candidate))
    result = {'status': 'succeeded', 'request_hash': export_id, 'source_identity': identity,
        'source_versions': versions, 'source_run_id': 'r1', 'identity': {'shape_id': 'shape', 'certificate_id': 'cert'},
        'elevation_handoff': {'request': {'dataset_root': str(target / 'dataset'), 'candidate': candidate_id,
                                         'selected_glb': str(path.parent / 'selected.glb')}},
        'artifacts': []}
    if selection_mode:
        result.update(selected_mass_id='book:choice', selection_mode=selection_mode)
        result['identity']['name'] = 'book:choice'
    receipt = {'request_hash': export_id, 'result': result,
        'files': {path.relative_to(target).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()}}
    (target / 'receipt.json').write_text(json.dumps(receipt))
    response = with_hrefs(result)
    resolved, _ = resolve_delivered_source(response['source_handle'], output_root=tmp_path)
    assert resolved == candidate
    if selection_mode:
        assert response['source_handle']['selected_mass_id'] == 'book:choice'
        assert response['source_handle']['selection_mode'] == selection_mode
        for field, changed in [('selected_mass_id', 'book:foreign'), ('selection_mode', 'jury_recommended' if selection_mode == 'user_selected' else 'user_selected')]:
            bad = {**response['source_handle'], field: changed}
            with pytest.raises(ValueError, match='selection identity'):
                resolve_delivered_source(bad, output_root=tmp_path)
        bad = {k: v for k, v in response['source_handle'].items() if k != 'selection_mode'}
        with pytest.raises(ValueError, match='selection identity'):
            resolve_delivered_source(bad, output_root=tmp_path)
    assert response['source_handle']['masterplan_development_hash'] == packet()['package_hash']


def test_portfolio_and_tracked_rebuild_preserve_bound_metric_geometry():
    from backend.app.modules.design.generation.maas.creative_program_author import authored_programs_from_payload, authored_program_result
    from backend.app.modules.design.generation.maas.creative_floor_portfolio import _compile_candidate
    from backend.app.modules.design.generation.maas.delivered.book_rebuild import _compile_record
    authored = authored_programs_from_payload({'geometry_programs': [program().to_dict()]}, expected_count=1,
        program_context={'masterplan_development': packet()})[0]
    candidate = _compile_candidate(authored_program_result(authored), family='test', source_family='test',
        family_index=0, variation_index=0, candidate_index=0, capacity_band='maximum_target',
        capacity_ceiling_m2=9000)
    assert candidate is not None
    assert candidate['mesh_evidence']['bounds'][0][:2] == pytest.approx([15, 15])
    assert candidate['mesh_evidence']['bounds'][1][:2] == pytest.approx([23, 23])
    rec = {'trace_sequence_name': 'test', 'geometry_artifact': {
        'authoredGeometryProgram': candidate['geometry_program'],
        'storeyEvidence': candidate['storey_evidence']}}
    site = SimpleNamespace(pnu='123', building_type='office', site_origin_utm=(100., 200.),
        ground_capacity_m2=1000, far_capacity_m2=1000, plan_at=lambda z: box(0, 0, 100, 100))
    source, entry = _compile_record(rec, site.plan_at(0), site)
    assert source is not None, entry
    assert source.footprint.bounds == pytest.approx((15, 15, 23, 23))
    assert entry['floor_area_m2'] == pytest.approx(128.)
    assert entry['masterplan_development']['package_hash'] == packet()['package_hash']


def test_legal_owner_crs_cannot_be_overridden_by_packet():
    from backend.app.modules.design.generation.maas.masterplan_development import bind_program, compile_bound_source
    site = SimpleNamespace(pnu='123', building_type='office', site_origin_utm=(100., 200.), crs='EPSG:32651',
                           plan_at=lambda z: box(0, 0, 100, 100))
    with pytest.raises(ValueError, match='CRS'):
        compile_bound_source(bind_program(program(), packet()), site.plan_at(0), site, floor_count=2)


def test_explicit_snapshot_versions_must_match_packet():
    from backend.app.modules.design.generation.maas.masterplan_development import validate_packet
    value = packet()
    value['law']['source_versions'] = {'law': 'wrong'}
    value['package_hash'] = hashlib.sha256(json.dumps({k: v for k, v in value.items() if k != 'package_hash'},
        sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    with pytest.raises(ValueError, match='snapshot'):
        validate_packet(value)


def test_exact_development_inherits_bound_parent_frame_and_floor_schedule():
    from backend.app.modules.design.generation.maas.book_development import build_exact_development_portfolio
    from backend.app.modules.design.generation.maas.masterplan_development import compile_bound_source
    from backend.app.modules.design.generation.maas.creative_program_author import authored_programs_from_payload, authored_program_result
    from backend.app.modules.design.generation.maas.creative_floor_portfolio import _compile_candidate
    from backend.app.modules.design.generation.maas.delivered.book_rebuild import _compile_record
    from backend.app.modules.design.generation.maas.delivered.book_identity import seat_certificate
    authored = authored_programs_from_payload({'geometry_programs': [program().to_dict()]}, expected_count=1,
        program_context={'masterplan_development': packet()})[0]
    first = _compile_candidate(authored_program_result(authored), family='test', source_family='test',
        family_index=0, variation_index=0, candidate_index=0, capacity_band='maximum_target',
        capacity_ceiling_m2=9000)
    site = SimpleNamespace(pnu='123', building_type='office', site_origin_utm=(100., 200.),
        ground_capacity_m2=1000, far_capacity_m2=1000, parcel_area_m2=10000,
        plan_at=lambda z: box(0, 0, 100, 100))
    rec = {'trace_sequence_name': 'parent', 'geometry_artifact': {
        'authoredGeometryProgram': first['geometry_program'], 'storeyEvidence': first['storey_evidence']}}
    parent, entry = _compile_record(rec, site.plan_at(0), site)
    assert parent is not None, entry
    cert = seat_certificate('book:parent', parent, {}, site, book_entry=entry)
    context = {'parent': 'book:parent', 'parent_shape_id': cert['shape_id'],
        'parent_program_hash': GeometryProgram.from_dict(first['geometry_program']).program_hash(),
        'parent_certificate_id': cert['certificate_id'], 'site_pnu': '123', 'storey_count': 2,
        'storey_height_m': cert['storey_m'], 'height_m': cert['height_m'], 'target_gfa_m2': cert['gross_m2'],
        'masterplan_development': parent.metadata['masterplan_development']}
    payload = {'mode': 'exact-authored-development', 'inherit_parent_dimensions': True,
        **{key: context[key] for key in ('parent', 'parent_shape_id', 'parent_program_hash')},
        'geometry_programs': [program().to_dict()]}
    portfolio = build_exact_development_portfolio(payload, context, expected_count=1)
    child = GeometryProgram.from_dict(portfolio['candidates'][0]['geometry_program'])
    assert child.metadata['masterplan_development']['package_hash'] == packet()['package_hash']
    source = compile_bound_source(child, site.plan_at(0), site, floor_count=2)
    assert source.footprint.bounds == pytest.approx((15, 15, 23, 23))
    child_record = {'trace_sequence_name': 'child', 'geometry_artifact': {
        'authoredGeometryProgram': child.to_dict(), 'storeyEvidence': portfolio['candidates'][0]['storey_evidence']}}
    rebuilt, child_entry = _compile_record(child_record, site.plan_at(0), site)
    assert rebuilt is not None, child_entry
    child_cert = seat_certificate('book:child', rebuilt, {}, site, book_entry=child_entry)
    assert child_cert['gross_m2'] == pytest.approx(cert['gross_m2'])
    assert child_entry['masterplan_development']['package_hash'] == packet()['package_hash']


def _rehash(value):
    value['package_hash'] = hashlib.sha256(json.dumps({k: v for k, v in value.items() if k != 'package_hash'},
        sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return value


@pytest.mark.parametrize('status,ok', [('needs_revision', True), ('failed', False)])
def test_a_confirmed_needs_revision_card_binds_and_a_failed_one_does_not(status, ok):
    """684-1 (2026-11-03): the confirmed 4-storey card was needs_revision with every geometry check passed."""
    from backend.app.modules.design.generation.maas.masterplan_development import validate_packet
    value = packet()
    value['layout']['status'] = status
    _rehash(value)
    if ok:
        validate_packet(value)
    else:
        with pytest.raises(ValueError, match='binding'):
            validate_packet(value)


@pytest.mark.parametrize('key,marker,ok', [
    ('program', 'large_review_sections_are_receipts; snapshot_hash_identifies_stored_original', True),
    ('program', True, False), ('law', 'large_review_sections_are_receipts; snapshot_hash_identifies_stored_original', False)])
def test_only_programs_transport_projection_skips_its_hash(key, marker, ok):
    from backend.app.modules.design.generation.maas.masterplan_development import validate_packet
    value = packet()
    value[key] = {'owner': key, 'transport_projection': marker, 'snapshot_hash': 'of-the-stored-original'}
    _rehash(value)
    if ok:
        validate_packet(value)
    else:
        with pytest.raises(ValueError, match='snapshot'):
            validate_packet(value)
