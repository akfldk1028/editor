from shapely.geometry import box, mapping, MultiLineString


def test_disconnected_contacts_not_added_and_gis_not_legal_pass():
    from backend.app.modules.design.generation.maas.masterplan.legal_siting import measure
    request = {'pnu':'1'*19, 'site':mapping(box(0, 0, 10, 10)),
        'law':{'siting_requirements':{'pnu':'1'*19, 'status':'criteria_available',
            'criteria':{'min_frontage_m':4, 'min_road_width_m':6}}},
        'evidence':{'road_context':{'edges':[{'geometry':mapping(MultiLineString([[(0,0),(2,0)],[(4,0),(6,0)]])), 'width_m':6}]}}}
    out = measure(request)
    assert out['observations'][0]['continuous_contact_m'] == 2
    assert out['observations'][0]['dimension_status'] == 'shortfall'
    assert out['status'] == 'needs_evidence'


def test_small_profile_rejected_after_actual_count_crosses_boundary():
    from backend.app.modules.design.generation.maas.masterplan.legal_siting import parking_applicability
    rules = {'owner_snapshot':{'applicability':{'requested':{'structure':'surface'},
        'installed_spaces_range':{'minimum':1, 'maximum':8}}}}
    assert parking_applicability(rules, 8, False)['status'] == 'matched'
    assert parking_applicability(rules, 9, False)['status'] == 'needs_evidence'
    assert parking_applicability(rules, 8, True)['status'] == 'needs_evidence'


def test_general_snapshot_cannot_be_reused_below_its_threshold():
    from backend.app.modules.design.generation.maas.masterplan.rules import parking_design_rules
    from backend.app.modules.design.generation.maas.masterplan.legal_siting import parking_applicability
    for count in (50, 51, 100):
        rules = {'owner_snapshot':parking_design_rules(count)}
        assert parking_applicability(rules, count, True)['status'] == 'matched'
        assert parking_applicability(rules, 9, True)['status'] == 'needs_evidence'


def test_elevated_and_piloti_stalls_are_not_open_surface_parking():
    from backend.app.modules.design.generation.maas.masterplan.legal_siting import building_parking
    stall = {'geometry':mapping(box(0,0,2.5,5)), 'properties':{'layer':'parking_stall', 'level':1}}
    assert building_parking([stall])
    stall['properties']['level'] = 0
    assert not building_parking([stall])
    roof = {'geometry':mapping(box(0,0,10,10)), 'properties':{'layer':'building_footprint'}}
    assert building_parking([stall,roof])
