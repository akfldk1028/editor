import random
import pytest
from shapely.geometry import box

from backend.app.modules.design.generation.maas.masterplan.joint import screen_placements


def test_demand_hits_do_not_hide_other_positions_or_piloti():
    proposals = [(box(i, 0, i+10, 10), box(i, 0, i+10, h), {'id': f'{i}-{h}'})
                 for i in range(3) for h in (10, 5, 2)]
    calls = []
    def evaluate(p, ground, choice):
        calls.append(choice['id'])
        return 8
    selected, skipped = screen_placements(proposals, evaluate, 8)
    assert len(calls) == 9
    assert skipped == 0
    assert {v[3]['id'] for v in selected} == {f'{i}-{h}' for i in range(3) for h in (10, 5, 2)}


@pytest.mark.parametrize('seed', range(12))
def test_bounded_screen_preserves_exhaustive_top_two_with_ties(seed):
    rng = random.Random(seed)
    proposals = [(box(0, 0, 10, 10), box(0, 0, 10, rng.choice([3, 5, 10])),
                  {'id': str(i), 'count': rng.randint(0, 8)}) for i in range(30)]
    exhaustive = sorted([(c['count'], p, g, c) for p, g, c in proposals], key=lambda v: (-v[0], -round(v[2].area, 6)))
    bounded, skipped = screen_placements(proposals, lambda p, g, c: c['count'], 8)
    assert [v[3]['id'] for v in bounded[:2]] == [v[3]['id'] for v in exhaustive[:2]]
    assert len(bounded)+skipped == len(proposals)


def test_no_pruning_without_a_positive_demand_bound():
    proposals = [(box(0, 0, 10, 10), box(0, 0, 10, 10), {'count': c}) for c in [8, 8, 9]]
    selected, skipped = screen_placements(proposals, lambda p, g, c: c['count'], 0)
    assert skipped == 0
    assert selected[0][0] == 9


def test_complete_solve_shortlist_reaches_distant_equal_count_placement(monkeypatch):
    from backend.app.modules.design.generation.maas.masterplan import joint, rows
    from backend.tests.masterplan_engine.test_joint_placement import _placement_request, _fake_result
    from shapely.geometry import shape
    candidates = [box(x, 20, x+10, 30) for x in (0, 1, 40)]
    monkeypatch.setattr(joint, 'footprint_candidates', lambda *a, **k: candidates)
    monkeypatch.setattr(joint, 'piloti_ground_variants', lambda *a: [])
    monkeypatch.setattr(rows, 'row_candidates', lambda *a, **k: [])
    request = _placement_request()
    request['options'].update(max_joint_layouts=2, max_joint_screenings=64)
    def solve(candidate):
        p = shape(candidate['footprint']) if candidate.get('footprint') else box(20, 40, 30, 50)
        result = _fake_result(p, 10)
        result['validation']['geometry_status'] = 'passed' if p.bounds[0] == 40 else 'failed'
        return result
    chosen = joint.select_joint_layout(request, solve)
    assert chosen['validation']['geometry_status'] == 'passed'
    assert chosen['joint_search']['complete_layouts'] == 3


def test_screen_budget_spans_positions_before_repeating_ground_variants():
    proposals = [(box(x, 0, x+10, 10), box(x, 0, x+10, h), {'id': f'{x}-{h}'})
                 for x in (0, 1, 40) for h in (10, 5, 2)]
    selected, skipped = screen_placements(proposals, lambda *a: 8, 8, budget=3)
    assert {item[1].bounds[0] for item in selected} == {0, 1, 40}
    assert len(selected) == 3 and skipped == 6


@pytest.mark.parametrize('key,value', [('max_joint_screenings', 0), ('max_joint_screenings', 513),
    ('max_joint_screenings', True), ('max_joint_layouts', 0), ('max_joint_layouts', 17)])
def test_invalid_search_budgets_fail_before_solving(key, value):
    from backend.app.modules.design.generation.maas.masterplan.joint import select_joint_layout
    with pytest.raises(ValueError, match=key):
        select_joint_layout({'options': {key: value}}, lambda _: pytest.fail('must validate before solving'))
