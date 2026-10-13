import pytest
from backend.app.modules.design.generation.maas.masterplan.rules import parking_design_rules


@pytest.mark.parametrize('count', [1, 5, 8])
def test_small_surface_has_own_entrance_without_basement_assumption(count):
    out = parking_design_rules(count, structure='surface')
    assert out['status'] == 'rules_available'
    assert out['statutory']['entrance']['min_width_m'] == 3
    assert out['statutory']['aisle']['min_width_m'] == 6
    assert out['statutory']['ramp']['status'] == 'not_applicable'
    assert out['applicability']['installed_spaces_range']['maximum'] == 8


def test_ninth_surface_space_switches_to_general_standard():
    out = parking_design_rules(9, structure='surface')
    assert out['status'] == 'rules_available'
    assert out['statutory']['entrance']['min_width_m'] == 3.5
    assert out['statutory']['ramp']['status'] == 'not_applicable'


def test_road_requirements_use_programme_and_unknown_is_not_exemption():
    from backend.app.modules.law.reference.siting_rules import siting_requirements
    assert siting_requirements('1'*19, '업무시설', 1999)['criteria']['min_frontage_m'] == 2
    large = siting_requirements('1'*19, '업무시설', 2000)
    assert large['criteria']['min_frontage_m'] == 4
    assert large['criteria']['min_road_width_m'] == 6
    assert siting_requirements('1'*19, '공장', 2999)['criteria']['min_frontage_m'] == 2
    assert siting_requirements('1'*19, '공장', 3000)['criteria']['min_frontage_m'] == 4
    assert siting_requirements('1'*19, '', None)['status'] == 'needs_evidence'
    assert large['permit_compliance_verified'] is False
