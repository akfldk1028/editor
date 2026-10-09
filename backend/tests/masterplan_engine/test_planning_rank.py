from shapely.geometry import box, mapping

from backend.app.modules.design.generation.maas.masterplan.planner_rank import planning_rank


def candidate(score=1):
    return {'validation': {'geometry_status': 'passed'}, 'provided': 50, 'accessible': 2,
            'levels': [{'level': 0, 'provided_spaces': 0}, {'level': -1, 'provided_spaces': 50}],
            'score': score, 'features': [], 'ramp_orientation': 'off_aisle'}


def rank(value):
    return planning_rank(value, placement_stage=False, accessible=2, planned=50, surface_target=None)


def test_construction_cost_and_loop_do_not_choose_planning_alternative():
    a, b = candidate(), candidate()
    a.update(excavation_cost_units=1, closed_loop=True)
    b.update(excavation_cost_units=1000, closed_loop=False)
    assert rank(a) == rank(b)


def test_feasibility_precedes_planning_score():
    a, b = candidate(1), candidate(100)
    b['validation']['geometry_status'] = 'failed'
    assert rank(a) > rank(b)
    b['validation']['geometry_status'] = 'passed'
    b['provided'] = 49
    assert rank(a) > rank(b)


def test_meeting_target_does_not_reward_extra_stalls():
    a, b = candidate(), candidate()
    b['provided'] = 100
    assert rank(a) == rank(b)


def test_all_levels_use_common_geometry_not_generator_score():
    a, b = candidate(0), candidate(1000)
    for value, area in [(a, 10), (b, 20)]:
        value['features'] = [{'properties': {'layer': 'parking_aisle', 'level': -1},
                              'geometry': mapping(box(0, 0, area, 1))}]
    assert rank(a) > rank(b)
