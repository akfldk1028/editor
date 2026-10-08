"""A saved site reaches the Orchestrator as `{goal: limits, pnu}`; nothing else widens the run contract."""
import pytest
from pydantic import ValidationError

from backend.app.schemas.platform import RunCreate
from backend.tests.test_platform_specialist_runs import client, specialist

PNU = '4115011300106840001'


def run_create(request):
    return RunCreate(request=request, scene_revision=1, source_versions={})


@pytest.mark.parametrize('request_', [
    {'goal': 'limits', 'pnu': PNU},
    {'goal': 'limits', 'pnu': PNU, 'building_type': '공공업무시설'},
    {'goal': 'health'},
    specialist()['request'],
])
def test_site_health_and_specialist_requests_are_accepted(request_):
    body = RunCreate(request=request_, scene_revision=1, source_versions={'program': 2})
    assert body.request == request_


@pytest.mark.parametrize('request_', [
    {'goal': 'site_brief', 'pnu': PNU},
    {'goal': 'site_layout', 'pnu': PNU},
    {'goal': 'limits'},
    {'goal': 'limits', 'pnu': PNU, 'parcels': [PNU]},
    {'goal': 'limits', 'pnu': PNU, 'profile': {}},
    {'goal': 'limits', 'pnu': PNU[:-1]},
    {'goal': 'limits', 'pnu': '4115011300-1-0684-0001'},
    {'goal': 'limits', 'pnu': int(PNU)},
    {'goal': 'limits', 'pnu': PNU, 'building_type': ''},
    {'goal': 'limits', 'pnu': PNU, 'building_type': 'x' * 65},
    {'goal': 'limits', 'pnu': PNU, 'building_type': 3},
])
def test_other_goals_keys_and_bad_pnus_are_rejected(request_):
    with pytest.raises(ValidationError):
        run_create(request_)


def test_site_run_reaches_owner_verbatim_and_retries_by_key(tmp_path):
    api, owner, path = client(tmp_path)
    payload = {'request': {'goal': 'limits', 'pnu': PNU}, 'scene_revision': 1, 'source_versions': {}}
    first = api.post(path, json=payload, headers={'Idempotency-Key': 'site-1'})
    assert first.status_code == 202, first.text
    assert first.json()['goal'] == 'limits'
    assert api.post(path, json=payload, headers={'Idempotency-Key': 'site-1'}).json() == first.json()
    assert len(owner.requests) == 1
    submitted = next(iter(owner.requests.values()))
    assert submitted['request'] == {'goal': 'limits', 'pnu': PNU}
    assert (submitted['project'], submitted['branch']) == ('p', 'main')
    changed = {**payload, 'request': {'goal': 'limits', 'pnu': PNU[:-1] + '2'}}
    assert api.post(path, json=changed, headers={'Idempotency-Key': 'site-1'}).status_code == 409


def test_invalid_site_run_never_reaches_owner(tmp_path):
    api, owner, path = client(tmp_path)
    payload = {'request': {'goal': 'limits', 'pnu': 'not-a-pnu'}, 'scene_revision': 1, 'source_versions': {}}
    assert api.post(path, json=payload, headers={'Idempotency-Key': 'bad'}).status_code == 422
    assert owner.requests == {}
