from copy import deepcopy
import json
from pathlib import Path
from random import Random
import random
import math

import pytest

from backend.app.modules.design.optimization.genome import Design, OptimizationError, EvaluationRejected
from backend.app.modules.design.optimization.ssiea import SSIEAJob, resolve_options
from backend.app.modules.design.optimization.ranking import rank

FIXTURE=json.loads((Path(__file__).parent/'fixtures/ssiea_source.json').read_text())


def evaluate(designs):
    return [[sum(v[0] for v in d.inputs),sum(v[0]**2 for v in d.inputs),50+d.inputs[0][0]*4] for d in designs]


def source_data(design):
    return {key:value for key,value in design.get_data().items() if key not in ('outputs','rejections')}


@pytest.mark.parametrize('case',FIXTURE['cases'],ids=lambda case:str(case['seed']))
def test_original_fixed_seed_trace_including_migration_history_and_pareto(case):
    global_state=random.getstate()
    job=SSIEAJob(case['spec'],rng=Random(case['seed']))
    assert [source_data(d) for d in job.init_designs()]==case['initial']
    for expected in case['trace']:
        cont,generation,pop=job.step(evaluate)
        actual={'continue':cont,'generation':generation,'population':[source_data(d) for d in pop],
                'all_designs':[source_data(d) for d in job.all_designs],
                'pareto_ids':[d.id for d in job.get_pareto_front()],
                'best_id':job.get_best().id,'des_count':job.des_count}
        assert actual==expected
    assert random.getstate()==global_state


def test_29_gene_draws_blx_de_and_gaussian_mutation_match_original():
    case=FIXTURE['genome'];rng=Random(case['seed'])
    first=Design(0,0,0,rng=rng);second=Design(1,1,0,rng=rng)
    for item in (first,second):item.generate_random(case['inputs'])
    assert [source_data(first),source_data(second)]==case['initial']
    for expected in case['children']:
        child=first.crossover(second,case['inputs'],1,0,2,strategy=expected['strategy'])
        assert source_data(child)==expected['before']
        child.mutate(case['inputs'],.7)
        assert source_data(child)==expected['after']


@pytest.mark.parametrize('bad', ['short_batch','long_batch','short_vector','nonfinite','boolean'])
def test_invalid_evaluation_batch_is_rejected_before_state_application(bad):
    job=SSIEAJob(FIXTURE['cases'][0]['spec'],rng=Random(17));job.init_designs()
    def invalid(designs):
        values=evaluate(designs)
        if bad=='short_batch':return values[:-1]
        if bad=='long_batch':return values+values[:1]
        if bad=='short_vector':values[-1]=values[-1][:-1]
        if bad=='nonfinite':values[-1][0]=float('nan')
        if bad=='boolean':values[-1][0]=True
        return values
    with pytest.raises(OptimizationError):job.step(invalid)
    assert job.all_designs==[] and not job._initialized
    assert all(not d.objectives for island in job.islands for d in island)


def test_engine_options_pin_real_omitted_defaults_and_strategy_count():
    options=resolve_options({})
    assert options['num_islands']==5 and options['pop_per_island']==15
    assert options['Number of generations']==50 and options['migration_interval']==10
    assert options['island_strategies']==['blx']*5
    with pytest.raises(OptimizationError):resolve_options({'num_islands':2,'island_strategies':['blx']})


def test_interleaved_runs_have_independent_random_streams():
    first=SSIEAJob(FIXTURE['cases'][0]['spec'],rng=Random(17))
    second=SSIEAJob(FIXTURE['cases'][1]['spec'],rng=Random(23))
    first.init_designs();second.init_designs()
    for expected in FIXTURE['cases'][0]['trace']:
        first.step(evaluate);second.step(evaluate)
        assert [source_data(d) for d in first.all_designs]==expected['all_designs']


def test_geometry_rejections_survive_migration_without_becoming_pareto_or_metrics():
    job=SSIEAJob(FIXTURE['cases'][0]['spec'],rng=Random(17));job.init_designs()
    while True:
        cont,_,population=job.step(lambda designs:[EvaluationRejected(('empty_geometry',)) for _ in designs])
        assert job.get_pareto_front()==[] and job.get_best() is None
        for design in population:
            data=design.get_data()
            assert data['outputs']==[] and data['objectives']==[] and data['feasible'] is False
            assert data['rejections']==['empty_geometry']
            json.dumps(data,allow_nan=False)
        if not cont:break


@pytest.mark.parametrize('case',FIXTURE['ranking'])
def test_source_ranking_preserves_direction_ties_and_internal_crowding(case):
    designs=[]
    for index,values in enumerate(case['scores']):
        design=Design(index,index,0,rng=Random(0));design.set_outputs(values,case['definitions']);designs.append(design)
    ranks,distances,penalties=rank(designs,case['definitions'])
    assert ranks==case['ranks'] and penalties==case['penalties']
    assert [None if math.isinf(value) else value for value in distances]==case['distances']


@pytest.mark.parametrize('case',FIXTURE['penalties'])
def test_source_penalty_equality_and_both_directions(case):
    design=Design(0,0,0,rng=Random(0));design.set_outputs(case['outputs'],case['definitions'],case['mode'])
    assert source_data(design)==case['expected']
    assert design.get_data()['outputs']==case['outputs']


def test_ranking_rejects_missing_or_nonfinite_objective_evidence():
    design=Design(0,0,0,rng=Random(0))
    for values in ([],[float('inf')],[True]):
        design.objectives=values
        with pytest.raises(OptimizationError):rank([design],[{'type':'Objective','Goal':'Maximize'}])


def test_completed_run_and_repeated_initialization_do_not_expand_work():
    job=SSIEAJob(FIXTURE['cases'][0]['spec'],rng=Random(17))
    assert job.get_pareto_front()==[] and job.get_best() is None
    with pytest.raises(OptimizationError):job.step(evaluate)
    job.init_designs()
    with pytest.raises(OptimizationError):job.init_designs()
    while job.step(evaluate)[0]:pass
    count=len(job.all_designs)
    with pytest.raises(OptimizationError):job.step(evaluate)
    assert len(job.all_designs)==count
