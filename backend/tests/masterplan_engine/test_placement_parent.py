from copy import deepcopy

import pytest
from shapely.geometry import box, mapping, shape

from backend.app.modules.design.generation.maas import masterplan_operations as ops


@pytest.fixture
def parent(tmp_path, monkeypatch):
    monkeypatch.setenv('EDITOR_PLACEMENT_SNAPSHOT_ROOT', str(tmp_path / 'snapshots'))
    from backend.app.modules.design.generation.maas.masterplan import planner
    request = {'pnu': 'parcel', 'site': mapping(box(0, 0, 60, 60)),
               'buildable': mapping(box(0, 0, 60, 60)),
               'rules': {'stall_length_m': 5., 'aisle_width_m': 6.},
               'options': {'target_footprint_m2': 1200., 'target_parking_stalls': 50}}
    upper, ground = box(20, 10, 50, 50), box(25, 10, 50, 50)
    result = {'features': [
        {'geometry': mapping(upper), 'properties': {'layer': 'building_footprint', 'level': 0}},
        {'geometry': mapping(ground), 'properties': {'layer': 'building_ground_footprint', 'level': 0}}],
        'metrics': {}, 'validation': {'geometry_status': 'passed'}}
    monkeypatch.setattr(planner, 'plan_site', lambda _: deepcopy(result))
    solved = ops.dispatch('plan_site', {'request': request})
    return request, solved, upper, ground


@pytest.mark.parametrize('choice', [None, 'keep'])
def test_piloti_alone_on_existing_parent_is_noop(parent, choice):
    request, solved, upper, ground = parent
    moves = {'piloti': 'piloti'}
    if choice is not None:
        moves['piloti_choice'] = choice
    applied = ops.dispatch('apply_placement_moves', {
        'request': request, 'moves': moves, 'parent_ref': solved['placement_snapshot']['ref']})
    assert applied['noop'] is True
    assert applied['realized_state']['upper_area_m2'] == pytest.approx(upper.area)
    assert applied['realized_state']['ground_area_m2'] == pytest.approx(ground.area)
    assert request.get('footprint') is None


def test_explicit_piloti_face_depth_preserves_parent_upper(parent):
    request, solved, upper, ground = parent
    choice = next(c for c in solved['placement_snapshot']['piloti_choices'] if c['depth_m'] == 11.)
    applied = ops.dispatch('apply_placement_moves', {
        'request': request, 'moves': {'piloti': 'piloti', 'piloti_choice': choice['id']},
        'parent_ref': solved['placement_snapshot']['ref']})
    from backend.app.modules.design.generation.maas.masterplan.placement_state import resolve_request
    resolved = resolve_request(applied['request'])
    assert shape(resolved['footprint']).equals(upper)
    assert not shape(resolved['ground_footprint']).equals(ground)
    assert applied['request'].get('footprint') is None


@pytest.mark.parametrize('field,value', [('pnu', 'other'), ('rules', {'aisle_width_m': 3.}),
                                        ('options', {'target_parking_stalls': 1})])
def test_parent_cannot_be_rebound_to_changed_source(parent, field, value):
    request, solved, *_ = parent
    bad = deepcopy(request)
    bad[field] = value
    with pytest.raises(ValueError, match='parent'):
        ops.dispatch('apply_placement_moves', {'request': bad, 'moves': {'piloti': 'piloti'},
                                               'parent_ref': solved['placement_snapshot']['ref']})


def test_unknown_snapshot_is_refused(parent):
    request, solved, *_ = parent
    ref = deepcopy(solved['placement_snapshot']['ref'])
    ref['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='snapshot'):
        ops.dispatch('apply_placement_moves', {'request': request, 'moves': {'piloti': 'piloti'}, 'parent_ref': ref})


def test_parent_reference_does_not_allow_authored_mass_edit(parent):
    request, _, upper, _ = parent
    authored = {**request, 'footprint': mapping(upper)}
    solved = ops.dispatch('plan_site', {'request': authored})
    with pytest.raises(ValueError, match='authored'):
        ops.dispatch('apply_placement_moves', {'request': authored, 'moves': {'piloti': 'piloti'},
                                               'parent_ref': solved['placement_snapshot']['ref']})


def test_non_mass_move_preserves_parent_ground_and_upper(parent):
    request, solved, upper, ground = parent
    applied = ops.dispatch('apply_placement_moves', {'request': request, 'moves': {'ramp': 'straight'},
                                                   'parent_ref': solved['placement_snapshot']['ref']})
    from backend.app.modules.design.generation.maas.masterplan.placement_state import resolve_request
    resolved = resolve_request(applied['request'])
    assert shape(resolved['footprint']).equals(upper)
    assert shape(resolved['ground_footprint']).equals(ground)
    assert resolved['options']['ramp_shape'] == 'straight'


def test_moved_upper_cannot_pass_preservation_contract(parent):
    request, solved, *_ = parent
    applied = ops.dispatch('apply_placement_moves', {'request': request, 'moves': {'ramp': 'straight'},
                                                   'parent_ref': solved['placement_snapshot']['ref']})
    from backend.app.modules.design.generation.maas.masterplan.placement_state import preservation_checks
    tampered = deepcopy(solved)
    tampered['features'][0]['geometry'] = mapping(box(0, 0, 30, 40))
    checks = preservation_checks(applied['request'], tampered)
    assert next(c for c in checks if c['id'] == 'placement_upper_preserved')['status'] == 'failed'


def test_two_revisions_inherit_options_without_reselecting_mass(parent):
    request, solved, upper, ground = parent
    first = ops.dispatch('apply_placement_moves', {'request': request, 'moves': {'ramp': 'straight'},
                                                 'parent_ref': solved['placement_snapshot']['ref']})
    child = ops.dispatch('plan_site', {'request': first['request']})
    second = ops.dispatch('apply_placement_moves', {'request': request, 'moves': {'entry_approach': 'straight_10m'},
                                                  'parent_ref': child['placement_snapshot']['ref']})
    from backend.app.modules.design.generation.maas.masterplan.placement_state import resolve_request
    resolved = resolve_request(second['request'])
    assert resolved['options']['ramp_shape'] == 'straight'
    assert resolved['options']['entry_approach'] == 'straight_10m'
    assert shape(resolved['footprint']).equals(upper)
    assert shape(resolved['ground_footprint']).equals(ground)


def test_reference_cannot_authorize_mutated_option_after_application(parent):
    request, solved, *_ = parent
    applied = ops.dispatch('apply_placement_moves', {'request': request, 'moves': {'ramp': 'straight'},
                                                   'parent_ref': solved['placement_snapshot']['ref']})
    from backend.app.modules.design.generation.maas.masterplan.placement_state import resolve_request
    bad = deepcopy(applied['request'])
    bad['options']['target_parking_stalls'] = 1
    with pytest.raises(ValueError, match='parent'):
        resolve_request(bad)


def test_reference_run_identity_is_pinned(parent):
    request, solved, *_ = parent
    ref = {**solved['placement_snapshot']['ref'], 'run_id': 'other-run'}
    with pytest.raises(ValueError, match='snapshot'):
        ops.dispatch('apply_placement_moves', {'request': request, 'moves': {'piloti': 'piloti'}, 'parent_ref': ref})


def test_new_building_with_default_piloti_is_allowed(parent):
    request, solved, *_ = parent
    applied = ops.dispatch('apply_placement_moves', {
        'request': request, 'moves': {'building_side': 'E', 'piloti': 'piloti'},
        'parent_ref': solved['placement_snapshot']['ref']})
    assert applied['realized_state']['covered_footprint_m2'] > 0


def test_parent_face_id_cannot_be_remapped_onto_replacement_mass(parent):
    request, solved, *_ = parent
    with pytest.raises(ValueError, match='parent.*choice'):
        ops.dispatch('apply_placement_moves', {
            'request': request, 'moves': {'building_side': 'E', 'piloti': 'piloti', 'piloti_choice': 'e0_stall'},
            'parent_ref': solved['placement_snapshot']['ref']})


def test_local_revision_retains_generated_mass_acceptance_requirement(parent, monkeypatch):
    request, solved, *_ = parent
    from backend.app.modules.design.generation.maas.masterplan import planner
    result = {**deepcopy(solved), 'status': 'resolved', 'blocking': [],
              'handoff': {'hard_pass': True, 'status': 'passed'}}
    monkeypatch.setattr(planner, 'plan_site', lambda _: deepcopy(result))
    applied = ops.dispatch('apply_placement_moves', {'request': request, 'moves': {'ramp': 'straight'},
                                                   'parent_ref': solved['placement_snapshot']['ref']})
    child = ops.dispatch('plan_site', {'request': applied['request']})
    assert child['status'] == 'needs_evidence'
    assert 'generated_mass_acceptance' in child['validation']['pending_reviews']
    assert child['handoff']['hard_pass'] is False


def test_mass_feedback_keeps_original_authorship_when_parent_is_generated(parent, monkeypatch):
    request, solved, *_ = parent
    from backend.app.modules.design.generation.maas.masterplan import planner
    from backend.app.modules.design.generation.maas.masterplan.feedback import build_mass_feedback
    def plan(internal_request):
        result = deepcopy(solved)
        result['mass_feedback'] = build_mass_feedback(internal_request, result)
        return result
    monkeypatch.setattr(planner, 'plan_site', plan)
    applied = ops.dispatch('apply_placement_moves', {'request': request, 'moves': {'ramp': 'straight'},
                                                   'parent_ref': solved['placement_snapshot']['ref']})
    child = ops.dispatch('plan_site', {'request': applied['request']})
    assert child['mass_feedback']['mass_context']['authored_footprint'] is False
