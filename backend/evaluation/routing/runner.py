import hashlib
import json
import time

from backend.app.modules.platform.routing import route, decide
from backend.app.modules.platform.routing import judge as judging
from .metrics import correct


async def run_case(case, policy, *, judge=None):
    if policy not in ('rules', 'hybrid', 'auto'):
        raise ValueError('unsupported routing policy: ' + policy)
    text = case['text']
    context = json.dumps(case.get('context', {}), ensure_ascii=False, sort_keys=True)
    model_input = json.dumps({'text': text, 'context': context}, ensure_ascii=False)
    prompts = []
    failures = []
    async def observed_judge(text, situation):
        return await judging.judge(text, situation, on_prompt=prompts.append, on_error=failures.append)
    start = time.perf_counter()
    result = route(text) if policy == 'rules' else await decide(text, situation=context, judge=judge or observed_judge,
                                                              enabled=True, policy='auto' if policy=='auto' else 'llm')
    prompt = prompts[-1] if prompts else None
    row = {'case_id': case['id'], 'policy': policy, 'status': 'measured',
           'acceptable_owners': case.get('acceptable_owners', []), 'required_owners': case.get('required_owners', []),
           'should_ask': case.get('should_ask', False), 'predicted_owners': [] if result.kind == 'ask' else [result.agent],
           'asked': result.kind == 'ask', 'decided_by': result.decided_by,
           'fallback': policy != 'rules' and bool(result.fallback_reason),
           'fallback_reason': failures[-1] if failures else result.fallback_reason,
           'elapsed_ms': (time.perf_counter()-start)*1000,
           'model_input': model_input, 'input_sha256': hashlib.sha256(model_input.encode()).hexdigest(),
           'model_prompt': prompt, 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest() if prompt is not None else None,
           'model_id': None, 'tokens': None}
    row['correct'] = correct(row)
    return row
