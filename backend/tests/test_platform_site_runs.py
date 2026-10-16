"""A saved site reaches the Orchestrator as `{goal: limits, pnu, building_type?, assessment_date?, parcels?}`; nothing else widens the run contract."""
import pytest
from pydantic import ValidationError

from backend.app.schemas.platform import RunCreate
from backend.tests.test_platform_specialist_runs import client, specialist, without_trace

PNU = '4115011300106840001'
PNU_2 = '4115011300106840003'
FULL = {'goal': 'limits', 'pnu': PNU, 'parcels': [PNU, PNU_2], 'building_type': '업무시설', 'assessment_date': '2026-10-08'}


def run_create(request):
    return RunCreate(request=request, scene_revision=1, source_versions={})


def pnus(count):
    return [PNU[:-4] + f'{n:04d}' for n in range(1, count + 1)]


@pytest.mark.parametrize('request_', [
    {'goal': 'limits', 'pnu': PNU},
    {'goal': 'limits', 'pnu': PNU, 'building_type': '공공업무시설'},
    {'goal': 'limits', 'pnu': PNU, 'assessment_date': '2026-10-08'},
    {'goal': 'limits', 'pnu': PNU, 'assessment_date': '2024-02-29'},
    {'goal': 'limits', 'pnu': PNU, 'parcels': [PNU]},
    {'goal': 'limits', 'pnu': PNU, 'parcels': [PNU, PNU_2]},
    {'goal': 'limits', 'pnu': pnus(50)[0], 'parcels': pnus(50)},
    FULL,
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


@pytest.mark.parametrize('assessment_date', [
    '2026-13-01',       # no month 13
    '2026-02-30',       # not a real day
    '2025-02-29',       # not a leap year
    '2026/10/08',       # wrong separator
    '20261008',         # compact form
    '2026-10-08T00:00', # time attached
    '26-10-08',         # short year
    '',
    None,
    20261008,
])
def test_bad_assessment_dates_are_rejected(assessment_date):
    with pytest.raises(ValidationError):
        run_create({'goal': 'limits', 'pnu': PNU, 'assessment_date': assessment_date})


@pytest.mark.parametrize('parcels', [
    [PNU_2, PNU],             # parcels[0] != pnu
    [PNU_2],                  # pnu missing from the bundle
    [PNU, PNU],               # duplicate
    [PNU, PNU_2, PNU_2],      # duplicate further in
    pnus(51),                 # one over the cap
    [],                       # empty
    [PNU, PNU_2[:-1]],        # 18 digits
    [PNU, '4115011300-1-0684-0003'],
    [PNU, int(PNU_2)],
    PNU,                      # not a list
    None,
])
def test_bad_bundles_are_rejected(parcels):
    with pytest.raises(ValidationError):
        run_create({'goal': 'limits', 'pnu': PNU, 'parcels': parcels})


def test_site_run_reaches_owner_verbatim_and_retries_by_key(tmp_path):
    api, owner, path = client(tmp_path)
    payload = {'request': FULL, 'scene_revision': 1, 'source_versions': {}}
    first = api.post(path, json=payload, headers={'Idempotency-Key': 'site-1'})
    assert first.status_code == 202, first.text
    assert first.json()['goal'] == 'limits'
    assert without_trace(api.post(path, json=payload, headers={'Idempotency-Key': 'site-1'}).json()) == without_trace(first.json())
    assert len(owner.requests) == 1
    submitted = next(iter(owner.requests.values()))
    assert submitted['request'] == FULL
    assert (submitted['project'], submitted['branch']) == ('p', 'main')
    changed = {**payload, 'request': {**FULL, 'assessment_date': '2026-10-09'}}
    assert api.post(path, json=changed, headers={'Idempotency-Key': 'site-1'}).status_code == 409


@pytest.mark.parametrize('request_', [
    {'goal': 'limits', 'pnu': 'not-a-pnu'},
    {'goal': 'limits', 'pnu': PNU, 'parcels': [PNU_2, PNU]},
    {'goal': 'limits', 'pnu': PNU, 'assessment_date': '2026-02-30'},
])
def test_invalid_site_run_never_reaches_owner(tmp_path, request_):
    api, owner, path = client(tmp_path)
    payload = {'request': request_, 'scene_revision': 1, 'source_versions': {}}
    assert api.post(path, json=payload, headers={'Idempotency-Key': 'bad'}).status_code == 422
    assert owner.requests == {}


LAYOUT = {'goal': 'masterplan', 'pnu': PNU, 'building_type': '제2종근린생활시설', 'floor_area_m2': 3000}


@pytest.mark.parametrize('extra', [{}, {'footprint_m2': 600}, {'footprint_m2': 3000}, {'footprint_m2': 1},
                                   {'footprint_m2': 600, 'intent': '1층은 상가로 열고, 외장은 커튼월로'}])
def test_a_layout_run_may_carry_the_footprint_wanted(extra):
    assert run_create({**LAYOUT, **extra}).request == {**LAYOUT, **extra}


@pytest.mark.parametrize('footprint', [0, -1, 3001, True, '600', None, float('nan')])
def test_a_footprint_outside_one_to_the_floor_area_is_rejected(footprint):
    with pytest.raises(ValidationError):
        run_create({**LAYOUT, 'footprint_m2': footprint})
