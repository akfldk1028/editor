import pytest
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


@pytest.mark.parametrize('authored_key', ['footprint', 'ground_footprint', 'core', 'columns'])
def test_authored_mass_is_never_moved_or_resolved_by_search(authored_key):
    authored = mapping(box(0,0,10,10))
    req = {authored_key: [authored] if authored_key == 'columns' else authored,
           'options': {'planning_stage': 'placement', 'target_surface_stalls':30}}
    calls=[]
    def solve(r):
        calls.append(r)
        return {'authored':r[authored_key]}
    result=select_joint_layout(req,solve)
    assert len(calls)==1 and result['authored']==req[authored_key]


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
    assert len(calls) == 5 and calls[0].get('ground_footprint') is None
    strips = []
    for r in calls[1:3]:
        assert shape(r['footprint']).equals(generated)
        ground = shape(r['ground_footprint'])
        assert generated.covers(ground) and ground.bounds[1] > 40   # the strip is the south face
        strips.append(round(generated.area - ground.area, 6))
    assert strips == [40 * 5.0, 40 * 11.0]
    assert chosen.get('piloti_strip_m') in (5.0, 11.0)
    assert 'generated piloti ground occupancy requires MassAgent/architect acceptance' in chosen['blocking']
    assert chosen['joint_search']['complete_layouts'] == 5


def test_no_surface_target_outside_placement_stage_keeps_the_single_solve():
    req = _placement_request(); req['options'] = {'target_parking_stalls': 50}
    calls = []
    def solve(r):
        calls.append(r); return _fake_result(box(10, 40, 50, 60), 22)
    select_joint_layout(req, solve)
    assert len(calls) == 1


@pytest.mark.parametrize('extra_stall', [False, True])
def test_final_choice_preserves_ground_before_optimizing_drive(monkeypatch, extra_stall):
    from backend.app.modules.design.generation.maas.masterplan import joint
    generated = box(10, 40, 50, 60)
    monkeypatch.setattr(joint, 'footprint_candidates', lambda *a, **k: [])
    def solve(request):
        piloti = request.get('ground_footprint') is not None
        result = _fake_result(generated, 22, 10 if piloti else 400)
        result['metrics']['provided_parking_stalls'] = 50 if piloti or not extra_stall else 49
        if piloti:
            result['features'].append({'properties': {'layer':'building_ground_footprint','level':0},
                                       'geometry':request['ground_footprint']})
        return result
    chosen = select_joint_layout(_placement_request(), solve)
    assert (chosen.get('piloti_strip_m') is not None) == extra_stall


@pytest.mark.parametrize('surface_cap', [5, 7])
def test_equal_area_placement_and_owner_piloti_can_jointly_reach_surface_target(surface_cap):
    import copy
    from shapely.geometry import Polygon, MultiLineString, shape
    from backend.app.modules.design.generation.maas.masterplan.planner import _plan_site_fixed

    site = Polygon([(17.1839901253, 21.4382114881), (23.0478998980, 4.6205000607),
                    (9.8472777951, 0), (4.4413813417, 2.5953054512), (0, 15.2820265698)])
    front = LineString([(4.4413813417, 2.5953054512), (0, 15.2820265698)])
    request = {'site': mapping(site), 'front_frontage': mapping(front),
               'frontage': mapping(MultiLineString([
                   [(23.0478998980, 4.6205000607), (9.8472777951, 0)], list(front.coords)])),
               'law': {'required_spaces': 7, 'bcr_pct': 60},
               'rules': _placement_request()['rules'],
               'options': {'planning_stage': 'placement', 'target_footprint_m2': 135.3,
                           'target_surface_stalls': surface_cap, 'max_surface_stalls': surface_cap,
                           'layout_axis': {'frame': 'site_local', 'vector': [-4.4413813417, 12.6867211186],
                                           'source': 'test front_frontage direction'},
                           'parking_strategy': 'ground_surface', 'max_basement_levels': 0}}
    original = copy.deepcopy(request)
    calls = []

    def solve(candidate):
        calls.append(copy.deepcopy(candidate))
        return _plan_site_fixed(candidate)

    chosen = select_joint_layout(request, solve)
    assert chosen['metrics']['provided_parking_stalls'] == surface_cap
    if surface_cap == 7:
        assert chosen['validation']['geometry_status'] == 'passed'
    assert request == original
    assert len(calls) <= 5
    assert all(c['options'] == original['options'] and c['rules'] == original['rules'] for c in calls)
    assert abs(chosen['metrics']['building_footprint_m2'] - 135.3) < 1e-6
    if surface_cap == 7:
        ground = next(shape(f['geometry']) for f in chosen['features']
                      if f['properties']['layer'] == 'building_ground_footprint')
        assert ground.area > 60, 'Equal successful screens should preserve more enclosed ground'
        assert 'generated piloti ground occupancy requires MassAgent/architect acceptance' in chosen['blocking']
    else:
        assert any(c['id'] == 'parking_count' and c['status'] == 'failed'
                   for c in chosen['validation']['checks'])


@pytest.mark.parametrize('constraint', ['corner', 'corner_approach', 'prohibited', 'straight'])
def test_shortlist_entries_honor_the_same_constraints_as_complete_solve(monkeypatch, constraint):
    from shapely.geometry import Point, shape
    from backend.app.modules.design.generation.maas.masterplan import joint, rows

    request = _placement_request()
    request['options'].update(target_surface_stalls=12, max_surface_stalls=12)
    request['frontage'] = mapping(LineString([(0, 0), (0, 60)]))
    request['front_frontage'] = request['frontage']
    request['options']['layout_axis'] = {'frame': 'site_local', 'vector': [1, 0],
                                         'source': 'test declared design axis'}
    if constraint == 'corner':
        request['options']['corner_clearance_m'] = 4
    elif constraint == 'corner_approach':
        request['options']['entry_approach'] = 'corner_clear'
    elif constraint == 'prohibited':
        request['vehicle_prohibited'] = mapping(LineString([(0, 0), (0, 20)]))
    else:
        request['options']['entry_alignment'] = 'straight'
    proposed = box(25, 20, 45, 40)
    monkeypatch.setattr(joint, 'footprint_candidates', lambda *a, **k: [proposed])
    real_rows = rows.row_candidates
    examined = []

    def inspect_rows(*args, **kwargs):
        results = real_rows(*args, **kwargs)
        examined.append(results)
        for result in results:
            entrance = result['entrance']
            if constraint in ('corner', 'corner_approach'):
                assert min(entrance.distance(Point(c)) for c in [(0, 0), (0, 60)]) >= 4 - 1e-6
            elif constraint == 'prohibited':
                assert entrance.distance(shape(request['vehicle_prohibited'])) > 0.05
        if constraint == 'straight':
            assert kwargs.get('straight_entry') is True
            assert kwargs['allowed_angles'] == [0]
        assert kwargs['preserve_banks'] is True
        return results

    monkeypatch.setattr(rows, 'row_candidates', inspect_rows)
    select_joint_layout(request, lambda candidate: _fake_result(proposed, 12))
    assert examined and any(examined)
