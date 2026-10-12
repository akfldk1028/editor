from shapely.geometry import box, LineString
from backend.app.modules.design.generation.maas.masterplan.joint import footprint_candidates
from backend.app.modules.design.generation.maas.masterplan.joint import select_joint_layout
from shapely.geometry import mapping


def test_candidates_keep_programme_area_and_leave_different_parking_strips():
    host = box(0, 0, 60, 45)
    candidates = footprint_candidates(host, 900, LineString([(0,45),(60,45)]), 16)
    assert 2 <= len(candidates) <= 32
    assert all(host.buffer(1e-6).covers(p) and abs(p.area-900) < .01 for p in candidates)
    # A frontage bar leaves a full parking module, unlike a deep narrow block.
    assert any(p.bounds[1] >= 16 for p in candidates)
    assert len({round(p.centroid.x, 2) for p in candidates}) > 1


def test_concave_boundary_does_not_silently_drop_floor_area():
    host = box(0,0,60,45).difference(box(20,20,40,45))
    candidates = footprint_candidates(host, 900, LineString([(0,0),(60,0)]), 16)
    assert candidates
    assert all(host.buffer(1e-6).covers(p) and abs(p.area-900)<.01 for p in candidates)


def test_authored_mass_is_never_moved_or_resolved_by_search():
    req = {'footprint': mapping(box(0,0,10,10)), 'options': {'target_surface_stalls':30}}
    calls=[]
    def solve(r):
        calls.append(r)
        return {'authored':r['footprint']}
    result=select_joint_layout(req,solve)
    assert len(calls)==1 and result['authored']==req['footprint']


def test_search_budget_keeps_multiple_plate_proportions():
    candidates=footprint_candidates(box(0,0,60,50),900,LineString([(0,50),(60,50)]),16)
    dimensions={(round(p.bounds[2]-p.bounds[0],2),round(p.bounds[3]-p.bounds[1],2)) for p in candidates}
    assert len(dimensions)>=4


def _placement_request():
    return {'site': mapping(box(0, 0, 60, 60)), 'buildable': mapping(box(0, 0, 60, 60)),
            'frontage': mapping(LineString([(0, 0), (60, 0)])), 'front_frontage': mapping(LineString([(0, 0), (60, 0)])),
            'rules': {'stall_width_m': 2.5, 'stall_length_m': 5.0, 'aisle_width_m': 6.0,
                      'accessible_width_m': 3.3, 'accessible_length_m': 5.0},
            'options': {'planning_stage': 'placement', 'target_parking_stalls': 50}}


def _fake_result(footprint, surface, aisle_m2=400):
    return {'features': [{'properties': {'layer': 'building_footprint'}, 'geometry': mapping(footprint)},
                         {'properties': {'layer': 'parking_aisle', 'level': 0}, 'geometry': mapping(box(0, 0, aisle_m2, 1))}],
            'metrics': {'building_footprint_m2': footprint.area, 'provided_parking_stalls': 50,
                        'planned_parking_stalls': 50, 'provided_accessible_stalls': 2,
                        'required_accessible_stalls': 2, 'excavation_m2': 0.0},
            'levels': [{'level': 0, 'provided_spaces': surface}, {'level': -1, 'provided_spaces': 50 - surface}],
            'validation': {'geometry_status': 'passed'}, 'blocking': [], 'status': 'resolved', 'handoff': {}}


def test_placement_stage_competes_the_generated_zone_against_its_piloti_variants():
    from shapely.geometry import shape
    generated = box(10, 40, 50, 60)          # against the north edge: the open ground is south
    calls = []
    def solve(r):
        calls.append(r)
        return _fake_result(generated, 22, 400) if r.get('ground_footprint') is None else _fake_result(generated, 30, 300)
    chosen = select_joint_layout(_placement_request(), solve)
    assert len(calls) == 3 and calls[0].get('ground_footprint') is None
    strips = []
    for r in calls[1:]:
        assert shape(r['footprint']).equals(generated)
        ground = shape(r['ground_footprint'])
        assert generated.covers(ground) and ground.bounds[1] > 40   # the strip is the south face
        strips.append(round(generated.area - ground.area, 6))
    assert strips == [40 * 5.0, 40 * 11.0]
    assert chosen.get('piloti_strip_m') in (5.0, 11.0)
    assert 'generated piloti ground occupancy requires MassAgent/architect acceptance' in chosen['blocking']
    assert chosen['joint_search']['complete_layouts'] == 3


def test_no_surface_target_outside_placement_stage_keeps_the_single_solve():
    req = _placement_request(); req['options'] = {'target_parking_stalls': 50}
    calls = []
    def solve(r):
        calls.append(r); return _fake_result(box(10, 40, 50, 60), 22)
    select_joint_layout(req, solve)
    assert len(calls) == 1
