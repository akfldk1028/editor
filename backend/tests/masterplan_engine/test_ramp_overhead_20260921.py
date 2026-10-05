from shapely.geometry import LineString,box
from backend.app.modules.design.generation.maas.masterplan.ramp_overhead import overhead_clearance


def test_lower_ramp_can_pass_under_slab_but_portal_cannot():
    ramp={'centerline':LineString([(0,0,0),(30,0,-3)]),'width_m':4}
    assert overhead_clearance(ramp,box(25,-3,35,3),-.4,2.1)['passed']
    assert not overhead_clearance(ramp,box(20,-3,35,3),-.4,2.1)['passed']
    assert not overhead_clearance(ramp,box(0,-3,5,3),-.4,2.1)['passed']


def test_empty_overlap_does_not_require_invented_headroom():
    ramp={'centerline':LineString([(0,0,0),(30,0,-3)]),'width_m':4}
    result=overhead_clearance(ramp,box(0,10,30,20),-.4,2.3)
    assert result['passed'] and result['minimum_clearance_m'] is None
