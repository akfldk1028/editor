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
