"""One deterministic additive search, independent of worker and HTTP ownership."""
from copy import deepcopy
import hashlib
from random import Random

from backend.app.modules.design.native_repository import canonical_json
from backend.app.modules.design.job_spec import _options, _outputs
from .evaluator import evaluate_candidate, validate_context
from .genome import EvaluationRejected
from .ssiea import SSIEAJob, resolve_options


ENGINE_VERSION = 'additive-ssiea-v1'


def compute(prepared, *, seed, limits=None, envelope=None, cancelled=None, on_event=None):
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError('Seed must be an unsigned 64-bit integer')
    frozen = deepcopy(prepared)
    if frozen.get('algorithm') != 'additive':
        raise ValueError('Only additive computation is enabled')
    spec = deepcopy(frozen['job_spec'])
    if spec.get('options', {}).get('algorithm', 'additive') != 'additive':
        raise ValueError('Stored algorithm does not match specification')
    spec['options'] = resolve_options(spec.get('options', {}))
    _options(spec['options'])
    _outputs(spec['outputs'])
    effective_hash = hashlib.sha256(canonical_json(spec).encode('utf-8')).hexdigest()
    frozen['job_spec'] = spec
    limits, envelope = deepcopy(limits), deepcopy(envelope)
    validate_context(frozen, limits=limits, envelope=envelope)
    job = SSIEAJob(spec, rng=Random(seed))
    events, evaluated = [], {}

    def emit(event):
        event = {'sequence': len(events) + 1, **event}
        canonical_json(event)
        if on_event is not None:
            on_event(deepcopy(event))
        events.append(event)

    def evaluate(designs):
        values = []
        for design in designs:
            result = evaluate_candidate(design.inputs, frozen, limits=limits, envelope=envelope)
            evaluated[design.id] = result
            if result['rejections']:
                values.append(EvaluationRejected(tuple(r['code'] for r in result['rejections'])))
            elif not result['geometry']:
                raise ValueError('Evaluator returned no geometry without a rejection')
            else:
                values.append(result['outputs'])
        return values

    emit({'type': 'started', 'engine_version': ENGINE_VERSION, 'seed': seed,
          'max_generations': spec['options']['Number of generations'],
          'population_size': spec['options']['num_islands'] * spec['options']['pop_per_island'],
          'effective_spec_sha256': effective_hash})
    job.init_designs()
    status = 'computed'
    while True:
        if cancelled is not None and cancelled():
            status = 'cancelled'
            break
        more, generation, population = job.step(evaluate)
        emit({'type': 'generation', 'generation': generation,
              'total_evaluated': len(job.all_designs),
              'feasible_count': sum(d.feasible for d in population),
              'pareto_count': len(job.get_pareto_front())})
        if not more:
            break
    candidates = []
    for design in job.get_pareto_front():
        result = evaluated[design.id]
        if result['rejections'] or not result['geometry']:
            raise ValueError('Rejected geometry entered the Pareto front')
        candidates.append({'candidate_id': f'additive:{design.id}', 'generation': design.genNum,
            'inputs': deepcopy(design.inputs), 'outputs': result['outputs'],
            'objectives': list(design.objectives), 'feasible': design.feasible,
            'metrics': result['metrics'], 'geometry': result['geometry'], 'repair': result['repair']})
    rejections = []
    for design in job.all_designs:
        result = evaluated[design.id]
        if not design.feasible:
            rejections.append({'candidate_id': f'additive:{design.id}',
                'reasons': result['rejections'] or [{'code': 'constraints_unsatisfied',
                    'message': 'Computed metrics do not satisfy the supplied search constraints'}],
                'outputs': result['outputs'], 'penalty': design.penalty})
    result = {'status': status, 'engine_version': ENGINE_VERSION, 'algorithm': 'additive',
        'seed': seed, 'effective_spec': spec, 'effective_spec_sha256': effective_hash,
        'legal_compliance_verified': False, 'evidence_mode': 'unverified_search',
        'total_evaluated': len(job.all_designs), 'candidates': candidates,
        'rejections': rejections, 'events': events}
    canonical_json(result, max_bytes=32 * 1024 * 1024, max_nodes=2000000)
    emit({'type': status, 'total_evaluated': len(job.all_designs),
          'candidate_count': len(candidates), 'rejected_count': len(rejections)})
    return result
