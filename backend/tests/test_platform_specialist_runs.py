from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.modules.platform.routers.platform import create_platform_router
from backend.tests.test_platform_runs import setup


def specialist():
    return {'request': {'goal': 'specialist_review', 'specialist_reviews': [{
        'agent': 'systems', 'tool': 'systems_requirements',
        'args': {'request': {'project_id': 'p', 'branch_id': 'main', 'spaces': []}},
        'source_versions': {'program': 2},
    }]}, 'scene_revision': 1, 'source_versions': {'program': 2}}


def client(tmp_path):
    owner, projects, binding, _ = setup(tmp_path)
    original_submit = owner.submit_run
    async def submit(body):
        return {**await original_submit(body), 'goal': body['request']['goal']}
    owner.submit_run = submit
    app = FastAPI()
    app.include_router(create_platform_router(owner, project_service=projects))
    return TestClient(app), owner, '/api/v1/platform/projects/' + binding.project_id + '/runs'


@pytest.mark.parametrize('tool', ['systems_requirements', 'systems_analyze'])
def test_specialist_submission_preserves_exact_owner_payload_and_retry(tmp_path, tool):
    api, owner, path = client(tmp_path)
    payload = specialist()
    payload['request']['specialist_reviews'][0]['tool'] = tool
    first = api.post(path, json=payload, headers={'Idempotency-Key': 'review'})
    assert first.status_code == 202, first.text
    assert first.json()['goal'] == 'specialist_review'
    assert api.post(path, json=payload, headers={'Idempotency-Key': 'review'}).json() == first.json()
    assert len(owner.requests) == 1
    submitted = next(iter(owner.requests.values()))
    assert submitted['request'] == payload['request']
    assert submitted['source_versions'] == {'program': 2}
    assert (submitted['project'], submitted['branch']) == ('p', 'main')
    changed = deepcopy(payload)
    changed['request']['specialist_reviews'][0]['args']['request']['spaces'] = [{'name': 'changed'}]
    assert api.post(path, json=changed, headers={'Idempotency-Key': 'review'}).status_code == 409


@pytest.mark.parametrize('change', ['wrong_tool', 'empty_sources', 'stale_sources', 'duplicate_tool', 'authoring', 'extra_field', 'boolean_revision'])
def test_invalid_specialist_contract_never_reaches_owner(tmp_path, change):
    api, owner, path = client(tmp_path)
    payload = specialist()
    item = payload['request']['specialist_reviews'][0]
    if change == 'wrong_tool': item['tool'] = 'interior_review'
    elif change == 'empty_sources': item['source_versions'] = {}
    elif change == 'stale_sources': item['source_versions']['program'] = 1
    elif change == 'duplicate_tool': payload['request']['specialist_reviews'].append(deepcopy(item))
    elif change == 'authoring': payload['request'] = {'goal': 'interior_concept', 'interior_tasks': [item]}
    elif change == 'extra_field': item['accept_design'] = True
    elif change == 'boolean_revision': item['source_versions']['program'] = True
    assert api.post(path, json=payload, headers={'Idempotency-Key': 'bad'}).status_code == 422
    assert owner.requests == {}


@pytest.mark.parametrize('field,value', [('project_id', 'other'), ('branch_id', 'other')])
@pytest.mark.parametrize('location', ['request', 'args'])
def test_specialist_payload_cannot_override_bound_project(tmp_path, field, value, location):
    api, owner, path = client(tmp_path)
    payload = specialist()
    args = payload['request']['specialist_reviews'][0]['args']
    (args['request'] if location == 'request' else args)[field] = value
    assert api.post(path, json=payload, headers={'Idempotency-Key': 'wrong-project'}).status_code == 409
    assert owner.requests == {}


def test_specialist_submission_keeps_origin_and_scene_guards(tmp_path):
    api, owner, path = client(tmp_path)
    payload = specialist()
    assert api.post(path, json=payload, headers={'Idempotency-Key': 'origin', 'Origin': 'https://other.example'}).status_code == 403
    payload['scene_revision'] = 0
    assert api.post(path, json=payload, headers={'Idempotency-Key': 'stale-scene'}).status_code == 409
    assert owner.requests == {}
