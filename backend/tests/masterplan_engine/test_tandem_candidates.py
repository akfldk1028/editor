from shapely.geometry import box, mapping
from backend.app.modules.design.generation.maas.masterplan.rules import parking_design_rules


def case():
    def feature(layer, geom, **props):
        return {'type':'Feature', 'geometry':mapping(geom), 'properties':{'layer':layer,'level':0,**props}}
    request = {'site':mapping(box(0,0,8,16)), 'rules':{'owner_snapshot':parking_design_rules(2,structure='surface')},
               'options':{}, 'law':{'required_spaces':2}}
    candidate = {'features':[feature('parking_aisle',box(0,0,8,6)),
        feature('parking_stall',box(0,6,2.5,11),stall_id='G-P001',type='standard_90deg',width_m=2.5,length_m=5)],
        'provided':1,'accessible':0,'levels':[{'level':0,'provided_spaces':1}],'search_count':1}
    return request,candidate


def test_adds_a_rear_bay_only_with_law_scope_and_preserves_original():
    from backend.app.modules.design.generation.maas.masterplan.tandem import expand, certified_rears
    request, original = case()
    result = expand(request, original, 2)
    assert original['provided'] == 1
    assert result['provided'] == 2
    rears, checks = certified_rears(request, result['features'])
    assert len(rears) == 1 and all(c['status']=='passed' for c in checks)
    request['rules'] = {}
    assert expand(request,original,2) is None


def test_forged_rear_far_from_front_is_not_exempt_from_access_check():
    from backend.app.modules.design.generation.maas.masterplan.tandem import expand, certified_rears
    request, original = case()
    result = expand(request,original,2)
    result['features'][-1]['geometry'] = mapping(box(5,11,7.5,16))
    rears, checks = certified_rears(request,result['features'])
    assert not rears and any(c['status']=='failed' for c in checks)


def test_independent_validation_keeps_pair_dependency_and_rejects_forgery():
    from backend.app.modules.design.generation.maas.masterplan.tandem import expand
    from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
    request, original = case()
    request['frontage'] = {'type':'LineString','coordinates':[[0,0],[8,0]]}
    request['rules'].update(stall_width_m=2.5,stall_length_m=5,aisle_width_m=6)
    request['law']['required_accessible_spaces'] = 0
    result = expand(request,original,2)
    report = validate_plan(request,result)
    assert report['geometry_status'] == 'passed'
    assert 'tandem_front_vehicle_relocation_and_operation_review' in report['pending_reviews']
    result['features'][-1]['geometry'] = mapping(box(5,11,7.5,16))
    assert validate_plan(request,result)['geometry_status']=='failed'


def test_tandem_never_exceeds_explicit_surface_cap():
    from backend.app.modules.design.generation.maas.masterplan.tandem import expand
    request, original = case()
    request['options']['max_surface_stalls'] = 1
    assert expand(request, original, 2) is None


def test_full_planner_fills_deep_pocket_without_moving_authored_building():
    from backend.app.modules.design.generation.maas.masterplan.planner import plan_site
    request, _ = case()
    request.update(pnu='test', footprint=mapping(box(3,6,8,16)),
                   frontage={'type':'LineString','coordinates':[[0,0],[8,0]]})
    request['law'].update(bcr_pct=60, required_accessible_spaces=0)
    request['rules'].update(stall_width_m=2.5,stall_length_m=5,accessible_width_m=3.3,
                            accessible_length_m=5,aisle_width_m=6,entrance_width_m=3)
    request['options'].update(parking_strategy='ground_surface',max_basement_levels=0)
    result = plan_site(request)
    assert result['metrics']['provided_parking_stalls'] == 2
    assert result['metrics']['layout_pattern'] == 'tandem'
    assert result['metrics']['building_footprint_m2'] == 50
    assert result['validation']['geometry_status'] == 'passed'
    request['options']['corner_clearance_m'] = 1
    constrained = plan_site(request)
    assert not (constrained['metrics']['provided_parking_stalls']==2 and constrained['validation']['geometry_status']=='passed')
    assert any(c['id']=='authored_footprint_preserved' and c['status']=='passed'
               for c in result['validation']['checks'])


def test_absent_geometry_on_non_tandem_drive_does_not_crash_pair_validation():
    from backend.app.modules.design.generation.maas.masterplan.tandem import certified_rears
    request, candidate = case()
    candidate['features'][0]['geometry'] = None
    assert certified_rears(request,candidate['features']) == (set(), [])
