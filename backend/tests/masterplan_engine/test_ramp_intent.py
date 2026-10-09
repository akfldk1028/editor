from shapely.geometry import LineString
from backend.app.modules.design.generation.maas.masterplan.ramp_intent import matches_turn
from backend.app.modules.design.generation.maas.masterplan.placement_moves import apply_placement_moves


def test_quarter_turn_checks_geometry_not_declared_label():
    assert matches_turn({'centerline':LineString([(0,0,0),(10,0,-1),(10,10,-3)])},90)
    assert not matches_turn({'turn_deg':90,'centerline':LineString([(0,0),(10,0),(20,0)])},90)
    assert not matches_turn({'centerline':LineString([(0,0),(10,0),(10,10),(0,10)])},90)


def test_ramp_move_can_set_and_clear_turn_without_changing_rules():
    original={'options':{},'rules':{'ramp_width_m':6}}
    changed=apply_placement_moves(original,{'ramp':'quarter_turn'})['request']
    assert changed['options']=={'ramp_shape':'curved','ramp_turn_deg':90}
    assert changed['rules']==original['rules'] and original['options']=={}
    reset=apply_placement_moves(changed,{'ramp':'straight'})['request']
    assert reset['options']=={'ramp_shape':'straight'}
