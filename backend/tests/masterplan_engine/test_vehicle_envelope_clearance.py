import pytest
from shapely.geometry import box
from backend.app.modules.design.generation.maas.masterplan.swept_path import validate_maneuver


def measure(obstacles):
    return validate_maneuver(vehicle={'wheelbase_m':2,'body_width_m':2,'front_overhang_m':1,
        'rear_overhang_m':1,'track_m':1.5}, poses=[[0,0,0],[2,0,0]], drivable=box(-3,-4,10,4),
        obstacles=obstacles, source_binding={'level':0,'vehicle_source_id':'vehicle',
        'trajectory_source_id':'path','coordinate_frame_id':'local','pose_reference':'rear_axle_center'})


def test_clearance_uses_both_boundary_and_obstacles_without_claiming_kinematics():
    boundary=measure([])
    obstacle=measure([box(-1,1.5,5,2)])
    assert boundary['minimum_clearance_m']==pytest.approx(2)
    assert obstacle['minimum_clearance_m']==pytest.approx(.5)
    assert obstacle['kinematics_verified'] is False


def test_conflicted_envelope_does_not_report_a_positive_clearance():
    result=measure([box(1,0,2,2)])
    assert result['status']=='collision_or_clearance_conflict'
    assert result['minimum_clearance_m']==0


def test_stale_claimed_geometry_hash_is_not_rewritten_as_fresh_evidence():
    from shapely.geometry import mapping
    from backend.app.modules.design.generation.maas.masterplan.swept_path import layout_maneuver_result
    request={'options':{'vehicle_maneuver':{'level':0,'source_binding':{'level':0,
        'layout_features_sha256':'0'*64,'vehicle_source_id':'vehicle','trajectory_source_id':'path',
        'coordinate_frame_id':'local','pose_reference':'rear_axle_center'},
        'vehicle':{'wheelbase_m':2,'body_width_m':2,'front_overhang_m':1,'rear_overhang_m':1,'track_m':1.5},
        'poses':[[3,3,0],[5,3,0]]}}}
    features=[{'geometry':mapping(box(0,0,20,20)),'properties':{'layer':'parking_aisle','level':0}}]
    result=layout_maneuver_result(request,features)
    assert result['status']=='refused'
    assert 'source_binding.layout_features_sha256_mismatch' in result['missing_or_invalid']
    from backend.app.modules.design.generation.maas.masterplan.geometry import digest
    features[0]['properties']['source'] = '검증 도면'
    request['options']['vehicle_maneuver']['source_binding']['layout_features_sha256'] = digest(features)
    assert layout_maneuver_result(request,features)['status']=='clear_conservative_envelope'
