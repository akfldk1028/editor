import importlib
import importlib.util


MODULE = 'backend.app.modules.design.generation.maas.book_language.compatible_search'


def solve(**kwargs):
    assert importlib.util.find_spec(MODULE) is not None, 'BOOK compatibility rollback search is missing'
    return importlib.import_module(MODULE).search_compatible_assignment(**kwargs)


def compatible(candidate, selected):
    return candidate not in selected


def test_rolls_back_earlier_choice_to_recover_full_portfolio():
    table = {(0, 0): 'x', (1, 1): 'x', (2, 2): 'z',
             (1, 0): 'y', (0, 1): 'x'}
    result = solve(source_count=3, slot_count=3, incumbent={0: 0, 1: 1, 2: 2},
                   candidate=lambda source, slot: table.get((source, slot)),
                   compatible=compatible)
    assert result.assignment == {0: 1, 1: 0, 2: 2}
    assert result.evidence['initial_compatible_count'] == 2
    assert result.evidence['status'] == 'complete'


def test_valid_incumbent_is_unchanged_and_no_alternatives_are_evaluated():
    calls = []
    def candidate(source, slot):
        calls.append((source, slot))
        return f'{source}:{slot}'
    result = solve(source_count=5, slot_count=2, incumbent={0: 3, 1: 1},
                   candidate=candidate, compatible=compatible)
    assert result.assignment == {0: 3, 1: 1}
    assert calls == [(3, 0), (1, 1)]
    assert result.evidence['status'] == 'incumbent_valid'


def test_budget_exhaustion_retains_valid_subset_and_does_not_claim_infeasibility():
    result = solve(source_count=3, slot_count=3, incumbent={0: 0, 1: 1, 2: 2},
                   candidate=lambda source, slot: 'same', compatible=compatible,
                   max_evaluations=0, max_states=10)
    assert len(result.assignment) == 1
    assert result.evidence['status'] == 'budget_exhausted'
    assert result.evidence['additional_evaluations'] == 0
    assert result.evidence['initial_rejection_count'] == 2
    assert result.evidence['compatibility_rejections'] >= 2


def test_search_memoizes_pairs_and_never_reuses_source():
    calls = []
    def candidate(source, slot):
        calls.append((source, slot))
        return 'same' if source == 0 else None
    result = solve(source_count=2, slot_count=3, incumbent={},
                   candidate=candidate, compatible=compatible)
    assert len(result.assignment) == 1
    assert len(calls) == len(set(calls))
    assert len(set(result.assignment.values())) == len(result.assignment)
    assert result.evidence['status'] == 'search_exhausted'


def test_canonical_portfolio_retries_rejected_matching_without_erasing_originals(monkeypatch):
    from dataclasses import replace
    from backend.tests.provider_parity.test_maas_creative_floor_portfolio import CreativeFloorPortfolioReportTests
    module = importlib.import_module('backend.app.modules.design.generation.maas.creative_floor_portfolio')
    fixture = CreativeFloorPortfolioReportTests()
    programs = (fixture.valid_authored('first'), fixture.valid_authored('second'))
    kwargs = dict(target_count=2, capacity_ceiling_m2=332.322, authored_programs=programs)
    before = module.build_creative_floor_portfolio_report(**kwargs)
    children = [c for c in before.candidates if c['candidate_origin'] == 'book_exploration']
    assert len(children) == 2
    blocked_pair = {c['geometry_hash'] for c in children}
    original_accept = module.accept_morphology

    def reject_this_pair(candidate, retained):
        decision = original_accept(candidate, retained)
        hashes = {candidate['geometry_hash'], *(r['geometry_hash'] for r in retained)}
        # Simulates a measured pairwise rejection at the admission boundary;
        # every alternative still uses real projection, compilation and gates.
        return replace(decision, accepted=False) if blocked_pair <= hashes else decision

    monkeypatch.setattr(module, 'accept_morphology', reject_this_pair)
    after = module.build_creative_floor_portfolio_report(**kwargs)
    assert after.exploration_count == 2
    assert after.rejection_counts['morphology_distance'] >= 1
    assert after.schedule_evidence['compatibility_search']['initial_compatible_count'] == 1
    assert after.schedule_evidence['compatibility_search']['additional_evaluations'] > 0
    assert {c['geometry_hash'] for c in after.candidates if c['candidate_origin'] == 'authored_original'} == {
        c['geometry_hash'] for c in before.candidates if c['candidate_origin'] == 'authored_original'}
