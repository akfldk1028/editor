import pytest
from shapely.affinity import rotate
from shapely.geometry import box
from backend.app.modules.design.generation.maas.masterplan.parking_modules import module_candidates
from backend.app.modules.design.generation.maas.masterplan.circulation import full_width_stall_access, closed_aisle_loop

RULES = dict(stall_width_m=2.5, stall_length_m=5, accessible_width_m=3.3,
             accessible_length_m=5, aisle_width_m=6)


@pytest.mark.parametrize('height',[27.6,40,60])
def test_larger_host_keeps_quota_compliant_widths(height):
    rules={**RULES,'expanded_width_m':2.6,'expanded_length_m':5.2,'expanded_min_share':.3}
    plans=module_candidates(box(0,0,50,height),[box(0,5.2,6,11.2)],rules,20,1,
        family='module27',angles=[0],field='comb',expanded_needed=6)
    assert any(p['provided']==20 and p['accessible']>=1 and
               sum(s['type']=='expanded' for s in p['stalls'])>=6 for p in plans)


@pytest.mark.parametrize('family,depth,rows', [('module16',16,2),('module27',27,3),('module32',32,4)])
def test_complete_recipes_and_access(family, depth, rows):
    host, anchor = box(0,0,36,depth), box(0,5,6,11)
    plans = module_candidates(host,[anchor],RULES,100,0,family=family,angles=[0],field='comb')
    assert plans
    p = plans[0]
    assert p['module_layout']['depth_m'] == depth
    assert p['module_layout']['parking_rows'] == rows
    assert host.buffer(1e-6).covers(p['drive'])
    assert full_width_stall_access(p['drive'],[s['polygon'] for s in p['stalls']],[anchor],6)
    assert all(host.covers(s['polygon']) and s['polygon'].intersection(p['drive']).area < 1e-6 for s in p['stalls'])


def test_ring_and_rotated_obstacle_host():
    host=box(0,0,48,32).difference(box(43,20,48,25))
    anchor=box(0,5,6,11)
    plans=module_candidates(rotate(host,31,origin=(0,0)),[rotate(anchor,31,origin=(0,0))],
        RULES,100,0,family='module32',angles=[31],field='ring')
    assert plans
    p=plans[0]
    assert closed_aisle_loop(p['drive'],6) is not None
    assert rotate(host,31,origin=(0,0)).buffer(1e-6).covers(p['drive'])
    assert all(rotate(host,31,origin=(0,0)).buffer(1e-6).covers(s['polygon']) for s in p['stalls'])


def test_disconnected_anchor_cannot_be_connected_through_wall():
    host=box(0,0,40,32).difference(box(6,0,8,32))
    assert not module_candidates(host,[box(0,5,6,11)],RULES,100,0,
        family='module32',angles=[0],field='comb')


def test_nominal_module_respects_expanded_and_accessible_dimensions():
    rules={**RULES,'expanded_width_m':2.6,'expanded_length_m':5.2,'expanded_min_share':.3}
    plans=module_candidates(box(0,0,40,33),[box(0,5.2,6,11.2)],rules,30,1,
        family='module32',angles=[0],field='comb',expanded_needed=9)
    assert plans
    p=plans[0]
    assert p['module_layout']['depth_m'] == pytest.approx(32.8)
    assert p['accessible'] >= 1
    assert sum(s['type']=='expanded' for s in p['stalls']) >= 9
    assert all(s['length_m']==5.2 for s in p['stalls'] if s['type']=='expanded')


def test_single_aisle_cannot_claim_ring():
    assert not module_candidates(box(0,0,40,16),[box(0,5,6,11)],RULES,30,0,
        family='module16',angles=[0],field='ring')


def test_invalid_host_is_normalized_before_boolean_operations():
    from shapely.geometry import Polygon
    host=Polygon([(0,0),(40,0),(40,32),(20,32),(20,31),(20,32),(0,32)])
    assert not host.is_valid
    plans=module_candidates(host,[box(0,5,6,11)],RULES,30,0,
        family='module16',angles=[0],field='comb')
    assert plans
    assert host.buffer(0).buffer(1e-6).covers(plans[0]['drive'])
