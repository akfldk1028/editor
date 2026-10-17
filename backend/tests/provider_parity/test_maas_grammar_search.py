import importlib


def test_explicit_grammar_chain_changes_solid_and_reports_executed_verbs():
    from backend.tests.provider_parity.test_maas_creative_floor_portfolio import CreativeFloorPortfolioReportTests
    from backend.app.modules.design.generation.maas.creative_program_author import normalize_authored_programs
    from backend.app.modules.design.generation.maas.creative_book_supply import creative_book_schedule, project_creative_book_program, creative_book_evidence
    from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program
    source = normalize_authored_programs((CreativeFloorPortfolioReportTests().valid_authored('first'),))[0].program
    source_hash = source.program_hash()
    assignment = next(a for a in creative_book_schedule(59) if a.execution_verbs == ('taper',))
    baseline = project_creative_book_program(source, assignment)
    child = project_creative_book_program(source, assignment, execution_verbs=('split', 'taper', 'merge'))
    assert compile_geometry_program(child).geometry_hash != compile_geometry_program(baseline).geometry_hash
    assert creative_book_evidence(child)['execution_verbs'] == ['split', 'taper', 'merge']
    assert creative_book_evidence(child)['scheduled_execution_verbs'] == ['taper']
    assert creative_book_evidence(child)['principle_kind'] == 'grammar_composition'
    assert creative_book_evidence(child)['scheduled_principle_id'] == assignment.principle_id
    assert creative_book_evidence(child)['principle_id'] != assignment.principle_id
    assert compile_geometry_program(child).metrics['component_count'] == 1
    assert compile_geometry_program(child).metrics['watertight']
    executed = {node.provenance.get('book_verb') for node in child.topological_nodes()}
    assert {'split', 'taper', 'merge'} <= executed
    assert source.program_hash() == source_hash


def test_beam_descends_from_measured_best_branch_and_never_exceeds_shared_budget():
    module = importlib.import_module('backend.app.modules.design.generation.maas.book_language.grammar_search')
    search = module.GrammarBeamSearch(max_retries=18, max_depth=3, beam_width=1, branching_factor=3)
    seen = []
    def evaluate(proposal):
        seen.append(proposal)
        score = 4 if 'split' in proposal.verbs else 1
        return module.GrammarFeedback(False, None, 'constraint', score, 0.0)
    assert search.find('source', ('taper',), evaluate) is None
    trace = search.evidence()['trials']
    assert any(row['depth'] >= 2 for row in trace)
    for row in trace:
        if row['depth'] == 2:
            parent = next(p for p in trace if p['node_id'] == row['parent_id'])
            assert parent['score'] == max(p['score'] for p in trace if p['depth'] == 1)
    before = len(seen)
    assert search.find('source', ('taper',), evaluate) is None
    assert len(seen) == before
    search.find('other', ('bend',), evaluate)
    assert search.evidence()['retry_count'] <= 18
    assert search.evidence()['budget_exhausted']
    assert any(tuple(p.verbs) != ('taper',) for p in seen if p.depth and p.key == 'source')


def test_zero_budget_preserves_baseline_and_never_invents_success():
    module = importlib.import_module('backend.app.modules.design.generation.maas.book_language.grammar_search')
    search = module.GrammarBeamSearch(max_retries=0)
    for key in range(3):
        assert search.find(str(key), ('split',), lambda p: module.GrammarFeedback(False, None, 'ground', 0, 0)) is None
    assert search.evidence()['attempt_count'] == 3
    assert search.evidence()['retry_count'] == 0


def test_portfolio_delivery_search_explores_new_operation_sequences():
    from backend.tests.provider_parity.test_maas_creative_floor_portfolio import CreativeFloorPortfolioReportTests
    from backend.app.modules.design.generation.maas.creative_floor_portfolio import build_creative_floor_portfolio_report
    fixture = CreativeFloorPortfolioReportTests()
    sources = (fixture.valid_authored('first'), fixture.valid_authored('second'))
    args = dict(target_count=2, capacity_ceiling_m2=332.322, authored_programs=sources)
    baseline = build_creative_floor_portfolio_report(**args)
    def delivery(candidate):
        assignment = candidate['geometry_program']['metadata'].get('creative_book_assignment', {})
        accepted = assignment.get('derivation_kind') == 'grammar_composition'
        return {'accepted': accepted, 'reason': '' if accepted else 'requires_new_operation_chain'}
    report = build_creative_floor_portfolio_report(**args, delivery_probe=delivery, delivery_search_budget=24)
    children = [row for row in report.candidates if row['candidate_origin'] == 'book_exploration']
    assert children
    for row in children:
        evidence = row['book_language_evidence']
        assert len(evidence['execution_verbs']) > len(evidence['scheduled_execution_verbs'])
        assert row['grammar_search_evidence']['depth'] >= 1
        assert row['delivery_search_evidence']['accepted']
    assert {row['geometry_hash'] for row in baseline.candidates if row['candidate_origin'] == 'authored_original'} == {
        row['geometry_hash'] for row in report.candidates if row['candidate_origin'] == 'authored_original'}
    assert report.schedule_evidence['delivery_search']['retry_count'] <= 24


def test_beam_reaches_success_requiring_two_derivation_steps():
    module = importlib.import_module('backend.app.modules.design.generation.maas.book_language.grammar_search')
    search = module.GrammarBeamSearch(max_retries=30, beam_width=2)
    def evaluate(proposal):
        ok = len(proposal.verbs) >= 3
        return module.GrammarFeedback(ok, proposal if ok else None, '' if ok else 'depth', len(proposal.verbs), 0)
    selected = search.find('recursive', ('taper',), evaluate)
    assert selected is not None and selected.depth == 2
    assert len(selected.verbs) == 3
    assert any(row['node_id'] == selected.parent_id and not row['accepted'] for row in search.evidence()['trials'])


def test_grammar_preserves_parameter_only_repair_capability():
    module = importlib.import_module('backend.app.modules.design.generation.maas.book_language.grammar_search')
    search = module.GrammarBeamSearch(max_retries=20)
    original_variants = set()
    def evaluate(proposal):
        if proposal.verbs == ('taper',):
            original_variants.add(proposal.variation_index)
        ok = proposal.verbs == ('taper',) and proposal.variation_index == 1
        return module.GrammarFeedback(ok, proposal if ok else None, '' if ok else 'dimension', 1, 0)
    selected = search.find('numeric', ('taper',), evaluate)
    assert selected is not None
    assert selected.production == 'retune'
    assert original_variants == set(range(11))


def test_grammar_exposes_entire_executable_vocabulary_across_source_keys():
    module = importlib.import_module('backend.app.modules.design.generation.maas.book_language.grammar_search')
    offered = set()
    for index in range(100):
        search = module.GrammarBeamSearch(max_retries=16, max_depth=1)
        def evaluate(proposal):
            if proposal.depth:
                offered.update(proposal.verbs)
            return module.GrammarFeedback(False, None, 'closed', 0, 0)
        search.find(str(index), ('taper',), evaluate)
    assert offered == module.BOOK_EXECUTABLE_VERBS
