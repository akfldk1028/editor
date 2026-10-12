from shapely.geometry import LineString, Polygon, box, mapping
import pytest

from backend.app.modules.design.generation.maas.masterplan.ramps import curved_ramp_candidates
from backend.app.modules.design.generation.maas.masterplan.placement_moves import apply_placement_moves
from test_ramp_fitting_20260920 import rules


def test_small_curve_budget_preserves_distinct_turn_families():
    rows = curved_ramp_candidates(box(0, 0, 80, 80), LineString([(0, 0), (80, 0)]),
                                  Polygon(), rules(), 3.3, turns=(90., 180.), limit=2)
    assert {r['turn_deg'] for r in rows} == {90., 180.}
    assert all(r['inner_radius_m'] >= 5 for r in rows)


def test_unused_family_budget_can_find_more_accepted_landings():
    rows = curved_ramp_candidates(box(0, 0, 80, 80), LineString([(0, 0), (80, 0)]),
        Polygon(), rules(), 3.3, turns=(90., 180.), limit=4,
        accept=lambda ramp: ramp['turn_deg'] == 90.)
    assert len(rows) == 4


def test_half_turn_move_is_a_geometric_constraint_and_can_be_cleared():
    source = {'options': {}, 'rules': rules()}
    result = apply_placement_moves(source, {'ramp': 'half_turn'})['request']
    assert result['options'] == {'ramp_shape': 'curved', 'ramp_turn_deg': 180.}
    assert apply_placement_moves(result, {'ramp': 'any'})['request']['options'] == {'ramp_shape': 'any'}
    assert source['options'] == {}


def test_internal_aisle_can_generate_half_turn_without_covering_stalls():
    from test_aisle_ramps import row
    from backend.app.modules.design.generation.maas.masterplan.aisle_ramps import aisle_ramp_candidates
    from backend.app.modules.design.generation.maas.masterplan.ramp_intent import matches_turn
    source = row()
    source['provided'] = len(source['stalls'])
    rows = aisle_ramp_candidates(box(-25, -30, 90, 80), [source], Polygon(),
                                LineString([(0, 0), (0, 6)]), rules(), 3.3,
                                limit=2, accept_ramp=lambda ramp: matches_turn(ramp, 180))
    assert rows
    for proposal in rows:
        assert matches_turn(proposal['ramp'], 180)
        assert all(s['polygon'].intersection(proposal['ramp']['polygon']).area < 1e-6
                   for s in proposal['stalls'])


def test_scores_do_not_reward_unknown_or_forged_radius_labels():
    from backend.app.modules.design.generation.maas.masterplan.planning_scores import score_relationships
    result = score_relationships([], [])
    assert result['groups']['ramp_geometry']['score'] is None
    assert result['groups']['vehicle_maneuver']['score'] is None
    assert result['overall_score'] is None
    ramp = {'geometry': mapping(box(0, 0, 8, 20)), 'properties': {
        'layer': 'ramp', 'level': -1, 'from_level': 0, 'to_level': -1,
        'radius_m': 100, 'layout_type': 'curved_arc_with_grade_transitions'}}
    result = score_relationships([ramp], [{'id': 'ramp_curve_radius:0:-1', 'status': 'failed'}])
    assert result['groups']['ramp_geometry']['score'] == 0
    assert result['groups']['ramp_geometry']['coverage_pct'] < 100


def test_disconnected_drive_is_not_perfect_despite_passed_legacy_check():
    from backend.app.modules.design.generation.maas.masterplan.planning_scores import score_relationships
    def feat(g):
        return {'geometry': mapping(g), 'properties': {'layer': 'parking_aisle', 'level': 0}}
    disconnected = score_relationships([feat(box(0, 0, 10, 6)), feat(box(20, 0, 30, 6))],
                                       [{'id': 'drive_connected:0', 'status': 'passed', 'components': 2}])
    joined = score_relationships([feat(box(0, 0, 30, 6))], [])
    assert disconnected['groups']['drive_continuity']['score'] == 0
    assert joined['groups']['drive_continuity']['score'] == 100
    assert disconnected['groups']['vehicle_maneuver']['score'] is None
