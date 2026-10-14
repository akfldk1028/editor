import asyncio
import pytest

from backend.evaluation.routing.metrics import score_routes
from backend.evaluation.routing.runner import run_case


def row(expected, predicted, **extra):
    return {'acceptable_owners': expected, 'required_owners': [], 'should_ask': False,
            'predicted_owners': predicted, 'asked': False, 'status': 'measured',
            'fallback': False, 'elapsed_ms': 1, **extra}


def test_singletons_macro_f1_counts_missed_owner_and_confusion():
    result = score_routes([row(['law'], ['law']), row(['plan'], [], asked=True)])
    assert result['accuracy'] == .5
    assert result['macro_f1'] == .5
    assert result['per_owner']['plan']['recall'] == 0
    assert result['confusion']['plan']['<ask>'] == 1


def test_valid_alternatives_are_not_joint_requirements():
    result = score_routes([row(['law', 'mass'], ['law']),
                           row([], ['site'], required_owners=['site', 'law'])])
    assert result['accuracy'] == .5
    assert result['joint_owner_recall'] == .5
    assert result['joint_owner_precision'] == 1
    assert result['macro_f1'] is None


def test_unavailable_has_no_accuracy_and_fallback_cannot_be_model_success():
    result = score_routes([row(['law'], ['law'], fallback=True),
                           row(['plan'], [], status='unavailable')])
    assert result['n'] == 2 and result['measured_n'] == 1
    assert result['accuracy'] == 1
    assert result['model_only_accuracy'] is None
    assert result['availability'] == .5
    assert score_routes([])['accuracy'] is None


def test_runner_passes_only_text_context_not_labels_to_judge():
    from backend.app.modules.platform.routing.judge import Ledger
    seen = []
    async def judge(text, situation=''):
        seen.append((text, situation))
        return Ledger.model_validate({'is_request_satisfied': {'reason':'r','answer':False},
            'next_speaker': {'reason':'r','answer':'plan'},
            'instruction_or_question': {'reason':'r','answer':'draw'}})
    case = {'id':'x','text':'그려 줘','context':{'floor':3},'acceptable_owners':['plan'],
            'required_owners':[], 'should_ask':False, 'label_provenance':'SECRET_LABEL'}
    result = asyncio.run(run_case(case, 'hybrid', judge=judge))
    assert seen == [('그려 줘', '{"floor": 3}')]
    assert result['correct'] and result['decided_by'] == 'llm'
    assert 'SECRET_LABEL' not in result['model_input']


def test_runner_marks_fallback_and_rejects_unknown_policy():
    async def unavailable(*args): return None
    case={'id':'x','text':'매스 쌓아 봐','acceptable_owners':['mass']}
    result=asyncio.run(run_case(case,'hybrid',judge=unavailable))
    assert result['fallback'] and result['fallback_reason']=='model_unavailable'
    with pytest.raises(ValueError): asyncio.run(run_case(case,'debate'))


def test_production_route_exposes_safe_quota_reason(monkeypatch):
    from backend.app.modules.platform.routing import decide, judge as judging
    async def unavailable(text, situation='', **kwargs):
        kwargs['on_error']('model_usage_limit')
        return None
    monkeypatch.setattr(judging,'judge',unavailable)
    result=asyncio.run(decide('매스 쌓아 봐',enabled=True,extras=[]))
    assert result.to_dict()['fallback_reason']=='model_usage_limit'


def test_model_error_classification_distinguishes_auth_and_quota():
    from backend.app.modules.platform.routing.judge import error_code
    assert error_code(RuntimeError("You've hit your weekly limit"))=='model_usage_limit'
    assert error_code(RuntimeError('OAuth token expired'))=='model_authentication'
    assert error_code(TimeoutError())=='model_timeout'
    assert error_code(RuntimeError('sensitive arbitrary text'))=='model_unavailable'


def test_runner_routes_registered_agents_like_production(monkeypatch):
    from backend.app.modules.platform.routing import decide, judge as judging
    monkeypatch.setattr(judging, 'extras', lambda: ['new_specialist'])
    async def judge(text, situation=''):
        return judging.Ledger.model_validate({
            'is_request_satisfied': {'reason': 'r', 'answer': False},
            'next_speaker': {'reason': 'r', 'answer': 'new_specialist'},
            'instruction_or_question': {'reason': 'r', 'answer': 'draw'}})
    case = {'id': 'extra', 'text': 'please help', 'acceptable_owners': ['new_specialist']}
    production = asyncio.run(decide(case['text'], judge=judge, enabled=True))
    result = asyncio.run(run_case(case, 'hybrid', judge=judge))
    assert result['predicted_owners'] == [production.agent] == ['new_specialist']
    assert result['correct'] and not result['asked']


def test_runner_records_exact_prompt_and_roster_changes_even_on_fallback(monkeypatch):
    import hashlib
    import json
    from types import SimpleNamespace
    from backend.app.modules.platform.routing import judge as judging

    original_judge = judging.judge
    prompts = []
    description = 'first card snapshot'
    fail = False
    class Client:
        async def create(self, messages, **kwargs):
            prompts.append(messages[0].content)
            if fail:
                raise RuntimeError("You've hit your weekly limit")
            return SimpleNamespace(content=json.dumps({
                'is_request_satisfied': {'reason': 'r', 'answer': False},
                'next_speaker': {'reason': 'r', 'answer': 'plan'},
                'instruction_or_question': {'reason': 'r', 'answer': 'draw'}}))
    async def roster(agents):
        return {'plan': {'name': 'Plan', 'description': description, 'skills': []}}
    async def offline_judge(text, situation='', **kwargs):
        return await original_judge(text, situation, client=Client(), roster=roster, **kwargs)
    monkeypatch.setattr(judging, 'judge', offline_judge)
    case = {'id': 'prompt', 'text': 'please help', 'acceptable_owners': ['plan'],
            'label_provenance': 'SECRET_LABEL'}
    first = asyncio.run(run_case(case, 'hybrid'))
    description = 'second card snapshot'
    fail = True
    second = asyncio.run(run_case(case, 'hybrid'))
    assert first['input_sha256'] == second['input_sha256']
    assert first['prompt_sha256'] != second['prompt_sha256']
    for result, prompt in zip((first, second), prompts):
        assert result['model_prompt'] == prompt
        assert result['prompt_sha256'] == hashlib.sha256(prompt.encode()).hexdigest()
        assert 'SECRET_LABEL' not in prompt
    assert 'first card snapshot' in first['model_prompt']
    assert 'second card snapshot' in second['model_prompt']
    assert second['fallback_reason'] == 'model_usage_limit'
    assert second['fallback']


def test_rules_do_not_claim_model_prompt_provenance():
    result = asyncio.run(run_case({'id': 'rules', 'text': 'please help'}, 'rules'))
    assert result['model_prompt'] is None and result['prompt_sha256'] is None
