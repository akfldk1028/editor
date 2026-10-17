import importlib
import pytest


def module():
    return importlib.import_module('backend.app.modules.design.generation.maas.book_language.grammar_mcts')


def test_mcts_rollout_backpropagates_delayed_reward_and_uses_ucb():
    m = module()
    search = m.GrammarMCTSSearch(max_retries=96, pair_budget=96, seed=7)
    def evaluate(p):
        # No accepted result: the complete budget must reveal repeated tree selection.
        return m.GrammarFeedback(False, None, 'probe_refused', 5 if len(p.verbs) >= 3 else 0, .1)
    assert search.find('delayed', ('taper',), evaluate) is None
    ev = search.evidence()
    assert ev['ucb_selection_count'] > 0
    assert ev['simulation_count'] > 2
    assert any(r['phase'] == 'rollout' and r['depth'] >= 2 for r in ev['trials'])
    root = next(n for n in ev['nodes'] if n['parent_id'] is None)
    assert root['visits'] == ev['simulation_count']
    assert root['reward_sum'] > 0
    assert any(n['visits'] > 1 for n in ev['nodes'] if n['parent_id'])
    ids = {r['node_id'] for r in ev['trials']}
    assert all(r['parent_id'] in ids for r in ev['trials'] if r['parent_id'])


def test_all_parameter_variants_remain_available_and_budget_is_shared_fairly():
    m = module()
    search = m.GrammarMCTSSearch(max_retries=96, pair_budget=16, seed=3)
    for key in range(6):
        search.find(str(key), ('taper',), lambda p: m.GrammarFeedback(False, None, 'no', 0, 0))
    ev = search.evidence()
    assert ev['retry_count'] == 96
    assert all(p['retry_count'] == 16 for p in ev['pairs'])
    assert all(p['ucb_selection_count'] > 0 for p in ev['pairs'])
    assert {r['node_id'] for r in ev['trials'] if r['phase'] == 'rollout'} <= {n['node_id'] for n in ev['nodes']}
    for key in range(6):
        assert {r['variation_index'] for r in ev['trials'] if r['key'] == str(key) and r['verbs'] == ['taper']} == set(range(11))
    before = len(ev['trials'])
    search.find('0', ('taper',), lambda p: (_ for _ in ()).throw(AssertionError('cached')))
    assert len(search.evidence()['trials']) == before


def test_repeatable_seed_actual_recursive_success_and_hard_acceptance():
    m = module()
    def run():
        s = m.GrammarMCTSSearch(max_retries=40, pair_budget=40, seed=42)
        def evaluate(p):
            ok = len(p.verbs) >= 3
            return m.GrammarFeedback(ok, p if ok else None, '' if ok else 'requires_composition', 6 if ok else 5, .2, p.node_id, p.node_id)
        result = s.find('recursive', ('taper',), evaluate)
        assert result is not None and len(result.verbs) >= 3
        return s.evidence()
    assert run() == run()
    s = m.GrammarMCTSSearch(max_retries=0)
    assert s.find('closed', ('taper',), lambda p: m.GrammarFeedback(False, None, 'hard_failure', 100, 100)) is None
    assert s.evidence()['retry_count'] == 0


def test_delayed_high_reward_branch_receives_more_visits_than_zero_reward_sibling():
    m = module()
    search = m.GrammarMCTSSearch(max_retries=160, pair_budget=160, seed=7)
    search.find('delayed', ('taper',), lambda p: m.GrammarFeedback(False, None, 'not_delivered',
        6 if len(p.verbs) >= 3 and p.verbs[0] == 'pinch' else 0, 0))
    ev = search.evidence()
    root = ev['nodes'][0]
    children = [n for n in ev['nodes'] if n['parent_id'] == root['node_id']]
    productive = next(n for n in children if n['verbs'] == ['pinch', 'taper'])
    unproductive = next(n for n in children if n['verbs'] == ['taper', 'pinch'])
    assert productive['reward_sum'] > 0 == unproductive['reward_sum']
    assert productive['visits'] > unproductive['visits']
    assert not any(r['accepted'] for r in ev['trials'])


def test_mcts_portfolio_runs_real_compiler_and_preserves_originals():
    from backend.tests.provider_parity.test_maas_creative_floor_portfolio import CreativeFloorPortfolioReportTests
    from backend.app.modules.design.generation.maas.creative_floor_portfolio import build_creative_floor_portfolio_report
    fixture = CreativeFloorPortfolioReportTests()
    args = dict(target_count=2, capacity_ceiling_m2=332.322,
                authored_programs=(fixture.valid_authored('first'), fixture.valid_authored('second')))
    baseline = build_creative_floor_portfolio_report(**args)
    def probe(c):
        ok = c['geometry_program']['metadata'].get('creative_book_assignment', {}).get('derivation_kind') == 'grammar_composition'
        return {'accepted': ok, 'reason': '' if ok else 'needs_operations'}
    report = build_creative_floor_portfolio_report(**args, delivery_probe=probe,
                 delivery_search_budget=48, delivery_search_algorithm='mcts')
    children = [c for c in report.candidates if c['candidate_origin'] == 'book_exploration']
    assert children
    assert all(c['delivery_search_evidence']['algorithm'] == 'delivery_guided_grammar_mcts.v1' for c in children)
    assert all(c['grammar_search_evidence']['depth'] > 0 for c in children)
    assert {c['geometry_hash'] for c in baseline.candidates if c['candidate_origin'] == 'authored_original'} == {c['geometry_hash'] for c in report.candidates if c['candidate_origin'] == 'authored_original'}
    ev = report.schedule_evidence['delivery_search']
    assert ev['retry_count'] <= 48
    assert any(r['program_hash'] and r['geometry_hash'] for r in ev['trials'])


@pytest.mark.parametrize('budget,per_source', [(32, 16), (8, 4)])
def test_portfolio_reserves_initial_search_for_different_authored_sources(budget, per_source):
    from backend.tests.provider_parity.test_maas_creative_floor_portfolio import CreativeFloorPortfolioReportTests
    from backend.app.modules.design.generation.maas.creative_floor_portfolio import build_creative_floor_portfolio_report
    fixture = CreativeFloorPortfolioReportTests()
    report = build_creative_floor_portfolio_report(target_count=2, capacity_ceiling_m2=332.322,
        authored_programs=(fixture.valid_authored('first'), fixture.valid_authored('second')),
        delivery_probe=lambda c: {'accepted': False, 'reason': 'impossible_site'},
        delivery_search_budget=budget, delivery_search_algorithm='mcts')
    pairs = report.schedule_evidence['delivery_search']['pairs']
    assert len({p['key'].split(':')[0] for p in pairs[:2]}) == 2
    assert [p['retry_count'] for p in pairs[:2]] == [per_source, per_source]
