"""Independent validation of constructed slabs, rooms and drives without stalls."""
from shapely.geometry import box, mapping, LineString
from backend.app.modules.design.generation.maas.masterplan.geometry import feature
from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan


def request():
    return {"site":mapping(box(0,0,40,40)),"basement_boundary":mapping(box(0,0,30,30)),
        "law":{"required_spaces":0,"required_accessible_spaces":0},"rules":{},
        "options":{"basement_floor_height_m":3}}


def checks(data,features):
    return {c['id']:c['status'] for c in validate_plan(data,{'features':features})['checks']}


def test_ordinary_slab_cannot_extend_beyond_excavation_permission():
    c=checks(request(),[feature('basement_boundary',box(0,0,35,35),-1)])
    assert c['basement_boundary_envelope:-1']=='failed'


def test_rooms_cannot_sit_outside_drawn_slab_even_inside_permission():
    f=[feature('basement_boundary',box(0,0,10,10),-1),feature('basement_room',box(12,12,17,17),-1)]
    assert checks(request(),f)['basement_boundary_preserves_programme:-1']=='failed'


def test_zero_stall_drive_cannot_cross_core_or_plant():
    f=[feature('basement_boundary',box(0,0,30,30),-1),
       feature('parking_aisle',box(0,5,25,11),-1),feature('building_core',box(5,5,10,10),-1),
       feature('basement_plant_zone',box(15,5,20,10),-1,declared_area_m2=25)]
    c=checks(request(),f)
    assert c['drive_obstructions:-1']=='failed'


def test_declared_programme_cannot_disappear():
    data=request();data['options']['basement_program']=[{'name':'plant','area_m2':25}]
    c=checks(data,[feature('basement_boundary',box(0,0,30,30),-1)])
    assert c['basement_programme_present:-1']=='failed'


def test_programme_cannot_overlap_core_or_duplicate_room_area():
    data=request();data['core']=mapping(box(5,5,10,10))
    data['options']['basement_program']=[{'name':'A','area_m2':25},{'name':'B','area_m2':25}]
    f=[feature('basement_boundary',box(0,0,30,30),-1),
       feature('basement_plant_zone',box(5,5,15,10),-1,declared_area_m2=50),
       feature('basement_room',box(5,5,10,10),-1,name='A',declared_area_m2=25),
       feature('basement_room',box(5,5,10,10),-1,name='B',declared_area_m2=25)]
    c=checks(data,f)
    assert c['plant_zone_obstructions:-1']=='failed'
    assert c['basement_room_overlap:-1:0']=='failed'


def test_flat_arrival_can_be_drive_but_sloping_run_cannot():
    data=request();data['rules']['ramp_max_slope']=.2
    ramp=feature('ramp',box(0,0,6,26),-1,from_level=0,to_level=-1,width_m=6,
        profile=[{'distance_m':0,'z_m':0},{'distance_m':3,'z_m':0},
                 {'distance_m':23,'z_m':-3},{'distance_m':26,'z_m':-3}])
    base=[feature('basement_boundary',box(0,0,30,30),-1),ramp,
          feature('ramp_centerline',LineString([(3,0),(3,26)]),-1,from_level=0,to_level=-1),
          feature('vehicular_access',box(0,23,6,26),-1,role='ramp_arrival',z_m=-3)]
    c=checks(data,base+[feature('parking_aisle',box(0,23,20,29),-1)])
    assert c['drive_obstructions:-1']=='passed'
    c=checks(data,base+[feature('parking_aisle',box(0,10,20,26),-1)])
    assert c['drive_obstructions:-1']=='failed'


def overhead_features(occupied):
    profile=[{'distance_m':0,'z_m':0},{'distance_m':3,'z_m':0},
             {'distance_m':23,'z_m':-3},{'distance_m':26,'z_m':-3}]
    return [feature('building_footprint',occupied),feature('basement_boundary',box(0,0,30,30),-1),
        feature('ramp',box(0,0,6,26),-1,from_level=0,to_level=-1,width_m=6,
                overhead_soffit_z_m=-.3,profile=profile),
        feature('ramp_centerline',LineString([(3,p['distance_m'],p['z_m']) for p in profile]),
                -1,from_level=0,to_level=-1)]


def test_under_building_ramp_needs_real_profile_clearance_and_source_soffit():
    data=request();data['options']['slab_depth_m']=.3;data['rules']['min_headroom_m']=2.3
    f=overhead_features(box(0,23,6,26))
    c=checks(data,f)
    assert c['ramp_overhead_soffit_source:0:-1']=='passed'
    assert c['ramp_overhead_clearance:0:-1']=='passed'
    assert 'structural_soffit_beams_services_review' in validate_plan(data,{'features':f})['pending_reviews']
    c=checks(data,overhead_features(box(0,15,6,26)))
    assert c['ramp_overhead_clearance:0:-1']=='failed'


def test_overhead_clearance_cannot_use_xyz_lower_than_declared_profile():
    data=request();data['options']['slab_depth_m']=.3;data['rules']['min_headroom_m']=2.3
    f=overhead_features(box(0,15,6,26))
    f[3]['geometry']=mapping(LineString([(3,0,-10),(3,3,-10),(3,23,-13),(3,26,-13)]))
    c=checks(data,f)
    assert c['ramp_overhead_xyz_profile:0:-1']=='failed'
    assert c['ramp_overhead_clearance:0:-1']=='failed'
    f[2]['properties']['overhead_soffit_z_m']=20
    assert checks(data,f)['ramp_overhead_soffit_source:0:-1']=='failed'


def test_under_building_ramp_rejects_missing_xyz_and_soffit_source():
    data=request();data['rules']['min_headroom_m']=2.3
    f=overhead_features(box(0,23,6,26))
    f[3]['geometry']=mapping(LineString([(3,0),(3,26)]))
    c=checks(data,f)
    assert c['ramp_overhead_soffit_source:0:-1']=='failed'
    assert c['ramp_overhead_clearance:0:-1']=='failed'
