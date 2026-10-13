import random
import pytest
from shapely.geometry import box

from backend.app.modules.design.generation.maas.masterplan.joint import screen_placements


def test_two_full_demand_enclosed_options_skip_inferior_piloti_screens():
    proposals = [(box(i, 0, i+10, 10), box(i, 0, i+10, h), {'id': f'{i}-{h}'})
                 for i in range(3) for h in (10, 5, 2)]
    calls = []
    def evaluate(p, ground, choice):
        calls.append(choice['id'])
        return 8
    selected, skipped = screen_placements(proposals, evaluate, 8)
    assert calls == ['0-10', '1-10']
    assert skipped == 7
    assert [v[3]['id'] for v in selected[:2]] == calls


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
