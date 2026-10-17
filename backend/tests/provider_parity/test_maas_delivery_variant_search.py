import importlib


def search_type():
    return importlib.import_module(
        'backend.app.modules.design.generation.maas.book_language.delivery_search'
    ).DeliveryVariantSearch


def test_failed_delivery_regenerates_parameters_and_records_actual_refusals():
    search = search_type()(variant_count=3, baseline_variant=1, max_retries=8)
    calls = []
    def evaluate(variant):
        calls.append(variant)
        return (variant == 2, {'variant': variant}, 'ground_contact' if variant != 2 else '')
    result = search.find('source-slot', evaluate)
    assert result == {'variant': 2}
    assert calls[0] == 1 and len(set(calls)) == len(calls)
    assert search.evidence()['refusal_counts']['ground_contact'] == 2
    assert search.find('source-slot', evaluate) == result
    assert len(calls) == 3


def test_shared_budget_never_admits_an_unevaluated_variant():
    search = search_type()(variant_count=11, baseline_variant=5, max_retries=2)
    assert search.find('a', lambda v: (False, None, 'area')) is None
    calls = []
    assert search.find('b', lambda v: (calls.append(v) is not None, None, 'area')) is None
    assert calls == [5]
    assert search.evidence()['retry_count'] == 2
    assert search.evidence()['attempt_count'] == 4
    assert search.evidence()['budget_exhausted'] is True


def test_passing_baseline_is_unchanged_without_extra_search():
    search = search_type()(variant_count=11, baseline_variant=5, max_retries=20)
    calls = []
    result = search.find('a', lambda v: (calls.append(v) is None, v, ''))
    assert result == 5
    assert calls == [5]


def test_retry_budget_does_not_limit_supported_portfolio_size():
    search = search_type()(variant_count=11, baseline_variant=5, max_retries=0)
    for index in range(200):
        assert search.find(str(index), lambda v: (True, v, '')) == 5
    assert search.evidence()['attempt_count'] == 200
    assert search.evidence()['retry_count'] == 0


def test_probe_cache_rechecks_changed_facing_even_with_same_program_hash(monkeypatch, tmp_path):
    monkeypatch.setenv("MASSV2_WS", str(tmp_path))
    from types import SimpleNamespace
    from copy import deepcopy
    from shapely.geometry import box
    module = importlib.import_module('backend.app.modules.massing.workspace_tools.book_delivery_probe')
    calls = []
    def compile_record(record, host, site):
        facing = record['geometry_artifact']['authoredGeometryProgram']['metadata']['facing']
        calls.append(facing)
        return None, facing
    monkeypatch.setattr(module, '_compile_record', compile_record)
    probe = module.BookDeliveryProbe(SimpleNamespace(pnu='test', plan_at=lambda z: box(0, 0, 50, 50)), run_id='test')
    candidate = {'program_hash': 'same', 'geometry_program': {'metadata': {'facing': 'north'}},
                 'candidate_id': 'c', 'storey_evidence': {'actual_floor_areas_m2': [1]},
                 'mesh_evidence': {'bounds': [[0, 0, 0], [1, 1, 3]]}}
    assert probe(candidate)['reason'] == 'north'
    changed = deepcopy(candidate)
    changed['geometry_program']['metadata']['facing'] = 'south'
    assert probe(changed)['reason'] == 'south'
    assert probe(candidate)['reason'] == 'north'
    assert calls == ['north', 'south']


def test_explicit_variation_changes_executed_geometry_not_only_metadata():
    from backend.tests.provider_parity.test_maas_creative_floor_portfolio import CreativeFloorPortfolioReportTests
    from backend.app.modules.design.generation.maas.creative_book_supply import creative_book_schedule, project_creative_book_program
    from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program
    from backend.app.modules.design.generation.maas.creative_program_author import normalize_authored_programs
    authored = normalize_authored_programs((CreativeFloorPortfolioReportTests().valid_authored('first'),))[0]
    assignment = next(a for a in creative_book_schedule(59) if a.execution_verbs == ('taper',))
    original = project_creative_book_program(authored.program, assignment)
    middle = project_creative_book_program(authored.program, assignment, variation_index=5)
    other = project_creative_book_program(authored.program, assignment, variation_index=0)
    assert compile_geometry_program(original).geometry_hash == compile_geometry_program(middle).geometry_hash
    assert compile_geometry_program(other).geometry_hash != compile_geometry_program(middle).geometry_hash


def test_final_delivery_feedback_changes_geometry_and_preserves_authored_originals():
    from backend.tests.provider_parity.test_maas_creative_floor_portfolio import CreativeFloorPortfolioReportTests
    from backend.app.modules.design.generation.maas.creative_floor_portfolio import build_creative_floor_portfolio_report
    fixture = CreativeFloorPortfolioReportTests()
    inputs = (fixture.valid_authored('first'), fixture.valid_authored('second'))
    args = dict(target_count=2, capacity_ceiling_m2=332.322, authored_programs=inputs)
    baseline = build_creative_floor_portfolio_report(**args)
    blocked = {c['geometry_hash'] for c in baseline.candidates if c['candidate_origin'] == 'book_exploration'}
    checked = []
    def delivery(candidate):
        checked.append(candidate['geometry_hash'])
        ok = candidate['geometry_hash'] not in blocked
        return {'accepted': ok, 'reason': '' if ok else 'measured_delivery_refusal'}
    after = build_creative_floor_portfolio_report(**args, delivery_probe=delivery)
    assert after.exploration_count == 2
    assert after.schedule_evidence['delivery_search']['refusal_counts']['measured_delivery_refusal'] > 0
    children = [c for c in after.candidates if c['candidate_origin'] == 'book_exploration']
    assert all(c['geometry_hash'] not in blocked and c['geometry_hash'] in checked for c in children)
    assert {c['geometry_hash'] for c in baseline.candidates if c['candidate_origin'] == 'authored_original'} == {
        c['geometry_hash'] for c in after.candidates if c['candidate_origin'] == 'authored_original'}
