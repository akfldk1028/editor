from types import SimpleNamespace

import manifold3d as m3d
import pytest
from shapely.geometry import box


def test_explicit_impose_finds_continuous_scale_between_legacy_steps():
    from backend.app.modules.design.generation.maas.geometry_language.source_bridge import _pose_metric_vertices_to_host
    mesh = m3d.Manifold.cube((10, 10, 4), center=True).to_mesh64()
    compiled = SimpleNamespace(vertices=tuple(tuple(p[:3]) for p in mesh.vert_properties),
                               triangles=tuple(tuple(f) for f in mesh.tri_verts))
    fitted = _pose_metric_vertices_to_host(compiled, box(-4.85, -4.85, 4.85, 4.85),
        clip_to_host=True, impose_fit=True, facing_angle_deg=0)
    assert fitted is not None
    assert fitted.matrix4[0][0] == pytest.approx(.97, abs=2e-4)
    assert fitted.matrix4[1][1] == fitted.matrix4[0][0]
    assert fitted.matrix4[2][2] == pytest.approx(.25)
    assert fitted.constraint_evidence['accepted']


def test_constraint_solver_observes_budget_and_reports_rank_deficiency():
    from backend.app.modules.design.generation.maas.geometry_language.constraint_fit import solve_imposed_pose
    occupied = box(-5, -1, 5, 1)
    host = box(-4.85, -100, 4.85, 100)
    fit = solve_imposed_pose([(occupied, host, 1), (occupied, host, 1)], max_evaluations=120)
    assert fit.evidence['accepted']
    assert fit.scale == pytest.approx(.97, abs=2e-4)
    assert any(row.get('rank', 3) < row.get('editable_count', 0) for row in fit.evidence['iterations'])
    assert fit.evidence['evaluation_count'] <= 120
    exhausted = solve_imposed_pose([(occupied, host, 1)], max_evaluations=1)
    assert not exhausted.evidence['accepted']
    assert exhausted.evidence['evaluation_count'] == 1


def test_constraint_solver_does_not_accept_vertices_around_host_hole():
    from backend.app.modules.design.generation.maas.geometry_language.constraint_fit import solve_imposed_pose
    occupied = box(-4, -4, 4, 4)
    host = box(-5, -5, 5, 5).difference(box(-1, -1, 1, 1))
    fit = solve_imposed_pose([(occupied, host, 1)], minimum_scale=1, max_evaluations=60)
    assert not fit.evidence['accepted']
    assert fit.evidence['initial_outside_area_m2'] == pytest.approx(4)


def test_host_hole_does_not_force_shrink_when_offcenter_metric_pose_exists():
    from backend.app.modules.design.generation.maas.geometry_language.constraint_fit import solve_imposed_pose
    occupied = box(-2, -2, 2, 2)
    host = box(-5, -5, 5, 5).difference(box(-1, -1, 1, 1))
    fit = solve_imposed_pose([(occupied, host, 1)])
    assert fit.evidence['initial_outside_area_m2'] == pytest.approx(4)
    assert fit.evidence['accepted']
    assert fit.scale == 1


def test_rank_zero_center_does_not_hide_feasible_offcenter_shrink():
    from shapely.affinity import affine_transform
    from backend.app.modules.design.generation.maas.geometry_language.constraint_fit import solve_imposed_pose
    occupied = box(-4,-4,4,4)
    host = box(-5,-5,5,5).difference(box(-1,-1,1,1))
    fit = solve_imposed_pose([(occupied,host,1)])
    assert fit.evidence['accepted']
    assert fit.evidence['evaluation_count'] <= 192
    assert .45 < fit.scale <= .50001
    assert host.buffer(1e-7).covers(affine_transform(occupied,[fit.scale,0,0,fit.scale,fit.x,fit.y]))


@pytest.mark.parametrize('width,facing', [(9.73,0), (8.41,31), (6.37,-18)])
def test_continuous_fit_preserves_facing_and_actual_upper_band(width, facing):
    from math import atan2, degrees, hypot
    from shapely.affinity import rotate, translate
    from backend.app.modules.design.generation.maas.geometry_language.source_bridge import (
        _pose_metric_vertices_to_host, mesh_section_solid, solid_section_polygon)
    mesh = m3d.Manifold.cube((10, 10, 4), center=True).to_mesh64()
    compiled = SimpleNamespace(vertices=tuple(tuple(p[:3]) for p in mesh.vert_properties),
                               triangles=tuple(tuple(f) for f in mesh.tri_verts))
    def located(polygon):
        return translate(rotate(polygon, facing, origin=(0,0)), 33, -17)
    host, upper = located(box(-10,-10,10,10)), located(box(-width/2,-6,width/2,6))
    fitted = _pose_metric_vertices_to_host(compiled, host, clip_to_host=True, impose_fit=True,
        facing_angle_deg=facing, clip_sections=((0,.5,host),(.5,1,upper)))
    assert fitted is not None
    assert hypot(fitted.matrix4[0][0], fitted.matrix4[1][0]) == pytest.approx(width/10, abs=2e-4)
    assert degrees(atan2(fitted.matrix4[1][0], fitted.matrix4[0][0])) == pytest.approx(facing)
    posed = mesh_section_solid(fitted.world_vertices, compiled.triangles)
    assert upper.buffer(1e-7).covers(solid_section_polygon(posed, .75))
    assert host.buffer(1e-7).covers(solid_section_polygon(posed, .25))


def test_final_import_executes_numeric_fit_and_exact_development_cannot_resize(monkeypatch, tmp_path):
    monkeypatch.setenv('MASSV2_WS', str(tmp_path))
    from copy import deepcopy
    from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram
    from backend.app.modules.design.generation.maas.dimensional_intent import SCHEMA, POLICY
    from backend.app.modules.design.generation.maas.book_development import MODE, MARKER, contract_hash
    from backend.app.modules.massing.workspace_tools.book_import import candidate_record, _compile_record, _refused
    program = GeometryProgram((GeometryNode('body', 'primitive', 'box',
        parameters={'width':10., 'depth':10., 'height':9.9}),), 'body', name='numeric-import',
        metadata={'site_fit':'impose', 'dimensional_intent': {
            'schema_version':SCHEMA, 'storey_count':3, 'storey_height_m':3.3,
            'target_gfa_m2':300., 'delivery_policy':POLICY, 'programme_status':'unknown'}})
    candidate = {'candidate_id':'numeric', 'geometry_program':program.to_dict(),
        'mesh_evidence':{'bounds':[[0,0,0],[10,10,9.9]]},
        'storey_evidence':{'storey_count':3, 'typical_storey_height_m':3.3,
                           'actual_floor_areas_m2':[100.,100.,100.]}}
    host = box(-4.85,-4.85,4.85,4.85)
    site = SimpleNamespace(pnu='numeric-test', plan_at=lambda height:host,
        parcel_area_m2=200., ground_capacity_m2=100., far_capacity_m2=400., floor_height_m=3.3)
    record = candidate_record(candidate, run_id='numeric-test')
    source, entry = _compile_record(record, host, site)
    assert source is not None, entry
    assert not _refused(source, site)
    assert entry['floor_area_m2'] == pytest.approx(282.27, abs=.01)
    evidence = source.metadata['geometry_program_bridge_evidence']['numeric_constraint_fit']
    assert evidence['accepted'] and evidence['evaluation_count'] <= 192
    assert candidate['geometry_program'] == program.to_dict()
    exact_record = deepcopy(record)
    metadata = exact_record['geometry_artifact']['authoredGeometryProgram']['metadata']
    metadata.pop('dimensional_intent')
    parent = dict(parent='parent',parent_shape_id='shape',parent_program_hash='program',
                  parent_certificate_id='certificate',site_pnu=site.pnu,
                  storey_count=3,storey_height_m=3.3,height_m=9.9,target_gfa_m2=300.)
    metadata[MARKER] = {'mode':MODE, 'parent_contract':parent, 'parent_contract_hash':contract_hash(parent),
                        'authored_program':program.to_dict(), 'authored_program_hash':program.program_hash()}
    refused, reason = _compile_record(exact_record, host, site)
    assert refused is None
    assert 'exact development' in reason
    assert 'without resizing or clipping' in reason


def test_disconnected_host_tries_component_with_feasible_scale():
    from shapely.affinity import affine_transform
    from shapely.ops import unary_union
    from backend.app.modules.design.generation.maas.geometry_language.constraint_fit import solve_imposed_pose
    occupied = box(-10, -10, 10, 10)
    host = unary_union([box(0, 0, 50, 3), box(100, 0, 110, 10)])
    fit = solve_imposed_pose([(occupied, host, 1)])
    assert fit.evidence['accepted']
    assert fit.evidence['evaluation_count'] <= 192
    assert .46 < fit.scale <= .50001
    assert host.buffer(1e-7).covers(affine_transform(occupied, [fit.scale, 0, 0, fit.scale, fit.x, fit.y]))


def test_archived_impose_bands_do_not_exhaust_budget_on_translation():
    import json
    from pathlib import Path
    from shapely import wkt
    from backend.app.modules.design.generation.maas.geometry_language.constraint_fit import solve_imposed_pose
    fixture = json.loads((Path(__file__).parent / 'fixtures/maas_numeric_impose_archived_constraints.json').read_text(encoding='utf8'))
    fit = solve_imposed_pose([(wkt.loads(p), wkt.loads(h), weight) for p, h, weight in fixture['constraints']])
    assert fit.evidence['accepted']
    assert fit.evidence['evaluation_count'] <= 192
    assert any(row['phase'] == 'scale' and row['accepted'] for row in fit.evidence['iterations'])
    assert fit.scale > .82  # Archived legacy delivery scale.
    assert fit.evidence['translation_domain_refinement']['host_intersections'] <= 4096


def test_unspecified_facing_retains_best_pose_across_angle_budget(monkeypatch):
    from math import hypot
    from shapely.ops import unary_union
    from backend.app.modules.design.generation.maas.geometry_language.source_bridge import _pose_metric_vertices_to_host
    mesh = m3d.Manifold.cube((20, 4, 4), center=True).to_mesh64()
    compiled = SimpleNamespace(vertices=tuple(tuple(p[:3]) for p in mesh.vert_properties),
                               triangles=tuple(tuple(f) for f in mesh.tri_verts))
    from backend.app.modules.design.generation.maas.geometry_language import source_bridge
    # Control the heuristic's ordering; actual geometric solve and gates run.
    monkeypatch.setattr(source_bridge, '_principal_frame', lambda polygon: (0., 20., 5.))
    host = box(-2.5, -10, 2.5, 10)
    fitted = _pose_metric_vertices_to_host(compiled, host, clip_to_host=True, impose_fit=True)
    assert fitted is not None
    assert hypot(fitted.matrix4[0][0], fitted.matrix4[1][0]) > .95
    evidence = fitted.constraint_evidence
    assert len(evidence['pose_attempts']) >= 2
    assert evidence['total_evaluation_count'] <= 192
    assert evidence['solution']['uniform_xy_scale'] == max(
        row['solution']['uniform_xy_scale'] for row in evidence['pose_attempts'] if row['accepted'])


def test_affine_repair_topology_error_refuses_pose(monkeypatch):
    from shapely.geometry import MultiPolygon, Polygon
    from backend.app.modules.design.generation.maas.geometry_language import source_bridge
    mesh = m3d.Manifold.cube((10, 10, 4), center=True).to_mesh64()
    compiled = SimpleNamespace(vertices=tuple(tuple(p[:3]) for p in mesh.vert_properties),
                               triangles=tuple(tuple(f) for f in mesh.tri_verts))
    invalid = MultiPolygon([box(0, 0, 10, 10), Polygon([
        (20, 0), (20.000001, .000001), (20, .000001), (20.000001, 0)])])
    monkeypatch.setattr(source_bridge, '_solid_plan_projection', lambda solid: invalid)
    assert source_bridge._pose_metric_vertices_to_host(compiled, box(-30, -30, 30, 30),
        clip_to_host=True, impose_fit=True, facing_angle_deg=0) is None


def test_real_reflected_l_uses_second_angle_after_first_budget():
    from shapely.affinity import scale
    from shapely.geometry.polygon import orient
    from shapely.ops import unary_union
    from backend.app.modules.design.generation.maas.geometry_language.source_bridge import _pose_metric_vertices_to_host
    plan = orient(unary_union([box(0, 0, 20, 3), box(0, 0, 3, 20)]), sign=1)
    mesh = m3d.CrossSection([list(plan.exterior.coords)]).extrude(4).to_mesh64()
    compiled = SimpleNamespace(vertices=tuple(tuple(p[:3]) for p in mesh.vert_properties),
                               triangles=tuple(tuple(f) for f in mesh.tri_verts))
    fitted = _pose_metric_vertices_to_host(compiled, scale(plan, xfact=-1, origin=(0, 0)),
                                          clip_to_host=True, impose_fit=True)
    assert fitted is not None
    assert fitted.achieved_plan_area_m2 == pytest.approx(111)
    evidence = fitted.constraint_evidence
    assert not evidence['pose_attempts'][0]['accepted']
    assert evidence['pose_attempts'][0]['max_evaluations'] == 64
    assert evidence['total_evaluation_count'] <= 192
