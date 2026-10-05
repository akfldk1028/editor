from shapely.geometry import LineString, Polygon, box, mapping
from shapely.affinity import rotate
import pytest
from backend.app.modules.design.generation.maas.masterplan.geometry import feature
from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
from backend.app.modules.design.generation.maas.masterplan.basement_layout import solve_basement_level


def stacked(wrong_departure=False, connected=True):
    request={'site':mapping(box(0,0,40,40)), 'basement_boundary':mapping(box(0,0,40,40)),
        'law':{'required_spaces':0,'required_accessible_spaces':0},
        'options':{'basement_floor_height_m':3,'slab_depth_m':.3},
        'rules':{'ramp_max_slope':.2,'min_headroom_m':2.3}}
    features=[]
    upper,lower=box(0,0,6,6),box(0,26,6,32)
    for depth in (1,2):
        level=-depth
        profile=[{'distance_m':d,'z_m':z+(level+1)*3} for d,z in ((0,0),(6,0),(26,-3),(32,-3))]
        features += [feature('basement_boundary',box(0,0,40,40),level),
            feature('ramp',box(0,0,6,32),level,from_level=level+1,to_level=level,width_m=6,profile=profile),
            feature('ramp_centerline',LineString([(3,p['distance_m'],p['z_m']) for p in profile]),level,from_level=level+1,to_level=level),
            feature('vehicular_access',lower if wrong_departure and depth==2 else upper,level+1,
                    role='ramp_departure',from_level=level+1,to_level=level),
            feature('vehicular_access',lower,level,role='ramp_arrival',from_level=level+1,to_level=level)]
    if connected:
        corridor=LineString([(3,3),(9,3),(9,29),(3,29)]).buffer(3,cap_style=2,join_style=2)
        features.append(feature('parking_aisle',corridor,-1))
    return request,features


def test_old_lower_landing_departure_is_not_centerline_start():
    request,features=stacked(wrong_departure=True)
    checks={c['id']:c['status'] for c in validate_plan(request,{'features':features})['checks']}
    assert checks['ramp_departure_profile_endpoint:-1:-2']=='failed'


def test_actual_return_lane_connects_intermediate_floor_and_respects_sloping_body():
    request,features=stacked()
    result=validate_plan(request,{'features':features})
    checks={c['id']:c['status'] for c in result['checks']}
    assert checks['ramp_departure_profile_endpoint:-1:-2']=='passed'
    assert checks['ramp_arrival_profile_endpoint:-1:-2']=='passed'
    assert checks['drive_obstructions:-1']=='passed'
    assert checks['drive_connected:-1']=='passed'
    assert result['geometry_status']=='passed', [c for c in result['checks'] if c['status']=='failed']


def test_disconnected_intermediate_floor_is_rejected():
    request,features=stacked(connected=False)
    checks={c['id']:c['status'] for c in validate_plan(request,{'features':features})['checks']}
    assert checks['drive_connected:-1']=='failed'


def test_return_lane_requires_real_stacked_headroom():
    request,features=stacked()
    request['options']['slab_depth_m']=1
    checks={c['id']:c['status'] for c in validate_plan(request,{'features':features})['checks']}
    assert checks['drive_obstructions:-1']=='failed'
    assert checks['ramp_stacking_headroom:-1:-2']=='failed'


@pytest.mark.parametrize('rotation',[0,37])
def test_basement_solver_builds_width_bearing_return_lane(monkeypatch,rotation):
    import backend.app.modules.design.generation.maas.masterplan.basement_layout as module
    monkeypatch.setattr(module,'row_candidates',lambda *a,**k:[])
    monkeypatch.setattr(module,'pack_level',lambda *a,**k:{'stalls':[],'drive':Polygon(),'provided':0,'accessible':0})
    ramp={'polygon':box(0,0,6,32),'upper_landing':box(0,0,6,6),'lower_landing':box(0,26,6,32)}
    turn=lambda g:rotate(g,rotation,origin=(0,0))
    ramp={k:turn(g) for k,g in ramp.items()}
    result=solve_basement_level(turn(box(0,0,40,40)),ramp,Polygon(),[],{'aisle_width_m':6},0,0,
        departure_landing=ramp['upper_landing'])
    drive=result['parking']['drive']
    assert drive.geom_type=='Polygon'
    assert drive.buffer(1e-6).covers(ramp['upper_landing']) and drive.buffer(1e-6).covers(ramp['lower_landing'])
    assert drive.intersection(turn(box(0,6,6,26))).area < 1e-6
    assert drive.intersection(turn(box(6,6,12,26))).area == pytest.approx(120)
    blocked=solve_basement_level(turn(box(0,0,6,32)),ramp,Polygon(),[],{'aisle_width_m':6},0,0,
        departure_landing=ramp['upper_landing'])
    assert blocked is None
