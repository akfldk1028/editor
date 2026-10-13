"""`GET /runs/{id}/results` and `GET /projects/{id}/runs/latest` read recorded Orchestrator runs (fixtures/run_results,
copied verbatim from the live 고산 684-1 runs of 2026-10-08: public parcel facts, communications cut at 8000 chars)."""
import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.modules.platform.routers.platform import create_platform_router
from backend.app.modules.platform.run_results import loads_tolerant, parse_run_results, request_pnu
from backend.app.modules.platform.runs import RunService
from backend.tests.test_platform_runs import setup

FIXTURES = Path(__file__).parent / 'fixtures' / 'run_results'
PNU, PNU_2, PNU_FAR = '4115011300106840001', '4115011300106840003', '4115011200109450000'


def fixture(name):
    return json.loads((FIXTURES / f'{name}.json').read_text(encoding='utf-8'))


@pytest.fixture
def single():
    return fixture('limits-single-684-1')


def test_truncated_json_is_closed_at_its_last_complete_value():
    assert loads_tolerant('{"a": 1, "b": [1, 2, 3], "c": {"d": "x", "e": [1, 2') == {'a': 1, 'b': [1, 2, 3], 'c': {'d': 'x', 'e': [1]}}
    assert loads_tolerant('{"a": 1, "b": [1, 2, 3], "c": {"d": "x", "e": "cu') == {'a': 1, 'b': [1, 2, 3], 'c': {'d': 'x'}}
    assert loads_tolerant('{"a": "comma, inside", "b": {"c": 1, "d": "cut') == {'a': 'comma, inside', 'b': {'c': 1}}
    assert loads_tolerant('{"a": "esc \\" quote", "b"') == {'a': 'esc " quote'}
    assert loads_tolerant('{"a": 1}') == {'a': 1}
    assert loads_tolerant('not json') is None
    assert loads_tolerant('') is None
    assert loads_tolerant(None) is None


def test_single_parcel_run_reads_law_numbers_site_facts_and_review(single):
    results = parse_run_results(single)
    assert results['run_id'] == '8c7f6fb7602f4202ba9537bb94d833b9'
    assert (results['status'], results['goal'], results['truncated']) == ('blocked', 'limits', True)
    assert results['request'] == {'pnu': PNU, 'parcels': [PNU], 'building_type': '업무시설', 'assessment_date': None}
    assert [(s['agent'], s['tool'], s['state']) for s in results['steps']] == [
        ('site_context', 'site_resolve', 'needs_evidence'), ('law', 'law_parcel_limits', 'succeeded'), ('revision', 'revision_triage', 'failed')]
    assert results['steps'][0]['summary'] == '5/8 site facts established for 4115011300106840001'
    site = results['site']
    assert (site['status'], site['facts_known'], site['facts_total']) == ('partial', 5, 8)
    assert site['facts_missing'] == ['SITE-ACCESS', 'SITE-HAZARDS', 'SITE-UTILITIES']
    law = results['law']
    assert (law['site_area_m2'], law['bcr_pct'], law['far_pct'], law['max_floors']) == (2499.691, 59.92, 249.67, 5)
    assert law['policy_id'] == 'gosan-public1-molit-2026-334'
    assert law['parcel_label'] == '경기도 의정부시 산곡동 684-1 / 공공1'
    assert law['truncated'] is True and law['ordinance'] is None
    assert law['sources'][0]['date'] == '2026-06-29' and law['sources'][0]['title']
    assert law['findings'] == [{'finding': 'law.district_review.0333cbe75e022ebef2be',
        'recommended_action': 'Supply an explicit valid assessment date; Law cannot choose a date or legal edition on the user behalf.',
        'missing_evidence': ['assessment_date_required', 'district_effective_sources_unverified',
                             'district_applicability_unverified', 'district_complete_provisions_review_required'],
        'assessment_date': None}]
    review = results['review']
    assert (review['status'], review['code']) == ('needs_evidence', 'needs_user_input')
    assert [a['finding'] for a in review['actions']] == ['SITE-ACCESS', 'SITE-HAZARDS', 'SITE-UTILITIES', 'law.district_review.0333cbe75e022ebef2be']
    assert review['actions'][0]['recommended_agents'] == ['site_context']
    assert review['actions'][3]['recommended_agents'] == ['user']
    assert results['missing_evidence_all'] == ['SITE-ACCESS', 'SITE-HAZARDS', 'SITE-UTILITIES', 'assessment_date_required',
        'district_effective_sources_unverified', 'district_applicability_unverified',
        'district_complete_provisions_review_required', *review['missing_evidence']]
    assert results['notes'] == ['law_response_truncated: the ordinance receipt was cut off by the 8000-character communication cap']
    assert results['raw']['communications'] == 3 and results['raw']['keys']['law_parcel_limits'] >= 8


def test_bundle_run_keeps_both_parcels_and_the_failed_bundle_names_its_code():
    bundle = parse_run_results(fixture('limits-bundle-684-1-684-3'))
    assert bundle['request']['parcels'] == [PNU, PNU_2]
    assert bundle['law']['bcr_pct'] == 59.92
    apart = parse_run_results(fixture('limits-failed-not-contiguous'))
    assert apart['status'] == 'failed'
    assert apart['request']['parcels'] == [PNU, PNU_FAR]
    assert (apart['site']['status'], apart['site']['code']) == ('failed', 'parcels_not_contiguous')
    assert apart['steps'][0]['summary'].startswith('the parcels do not form one contiguous site')
    assert apart['site']['facts_known'] is None


def test_ordinance_receipt_is_read_when_the_law_answer_is_whole(single):
    law = next(row for row in single['communications'] if row['tool'] == 'law_parcel_limits')
    law['truncated'] = False
    law['response_text'] = json.dumps({'pnu': PNU, 'parcel_area_m2': 2499.691, 'bcr_pct': 59.92, 'far_pct': 249.67, 'max_storeys': 5,
        'policy': {'policy_id': 'p'}, 'ordinance': {'status': 'complete', 'assessment_date': '2026-10-08',
        'bcr_article': '의정부시 도시계획 조례 제55조', 'far_article': '의정부시 도시계획 조례 제56조', 'height_article': None,
        'municipal_coverage': {'sources': [{'name': '의정부시 도시계획 조례', 'effective_date': '20250101'}]}}})
    results = parse_run_results(single)
    assert results['law']['ordinance'] == {'articles': ['의정부시 도시계획 조례 제55조', '의정부시 도시계획 조례 제56조'],
        'edition_id': '의정부시 도시계획 조례', 'effective_date': '20250101', 'assessment_date': '2026-10-08',
        'sources': [{'name': '의정부시 도시계획 조례', 'ordinance_id': None, 'edition_id': None, 'effective_date': '20250101', 'url': None}],
        'limitations': []}
    assert results['request']['assessment_date'] == '2026-10-08'
    assert results['notes'] == []


def test_whole_law_answer_reads_capacities_ceilings_articles_sources_and_site_facts():
    """산곡동 683 (2026-10-08): Law's answer fits the cap, so the receipt and its law.go.kr source are whole."""
    results = parse_run_results(fixture('limits-single-683'))
    law = results['law']
    assert (law['site_area_m2'], law['bcr_pct'], law['far_pct'], law['max_floors']) == (1006.531, 20.0, 80.0, None)
    assert (law['ground_capacity_m2'], law['far_capacity_m2']) == (201.306, 805.225)
    assert law['zones'] == ['자연녹지지역']
    assert (law['national_bcr_ceiling_pct'], law['national_far_ceiling_pct']) == (20.0, 100.0)
    assert law['articles'] == {'bcr': '의정부시 도시계획 조례 제42조', 'far': '의정부시 도시계획 조례 제46조', 'height': '건축법 제60조, 국토계획법 시행령 제80조'}
    assert law['height'] == {'status': 'no_height_overlay', 'limit_m': None}
    assert law['ordinance']['sources'] == [{'name': '의정부시 도시계획 조례', 'ordinance_id': '2149163', 'edition_id': '2072835',
        'effective_date': '20250925', 'url': 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=2072835'}]
    assert law['ordinance']['limitations'] == ['snapshot_does_not_certify_amendment_completeness', 'parcel_plan_conditions_and_transitional_rules_require_review']
    assert law['evidence'] == {'floor_height_m': 3.8, 'datum_measured': False, 'frontage_grade': 'inferred_not_road_verified', 'legal_floor_section_count': 13}
    assert law['truncated'] is False and results['notes'] == []
    site = results['site']
    assert (site['facts_known'], site['facts_total'], site['facts_missing']) == (5, 8, ['SITE-ACCESS', 'SITE-HAZARDS', 'SITE-UTILITIES'])
    # The Site answer is cut at 8000 chars: the first facts are readable, with their provenance and a one-line summary.
    keys = [fact['key'] for fact in site['facts']]
    assert keys[:2] == ['site.boundary', 'site.roads'] and all(key.startswith('site.') for key in keys)
    boundary = site['facts'][0]
    assert (boundary['confidence'], boundary['as_of'], boundary['summary']) == ('measured', '2026-10-08', '면적 1,006.65㎡')
    assert boundary['source'].startswith('Vworld')
    assert site['facts'][1]['summary'].startswith('접도 ') and '폭 ' in site['facts'][1]['summary']


@pytest.mark.parametrize('run', [None, 'text', {}, {'communications': 'no'}, {'communications': [{'tool': 7, 'response_text': 3}]},
    {'run_id': 'r', 'status': 'running', 'communications': [{'tool': 'law_parcel_limits', 'state': 'running', 'response_text': None}]}])
def test_parsing_never_raises(run):
    results = parse_run_results(run)
    assert set(results) == {'run_id', 'status', 'goal', 'pending_input', 'pending_fields', 'pending_note', 'pending_request', 'truncated', 'request', 'steps', 'site', 'law',
                            'review', 'missing_evidence_all', 'notes', 'raw'}
    assert request_pnu(run) is None


class RecordedOwner:
    """Serves the recorded runs: the list (no communications, newest first) and each run whole."""
    def __init__(self):
        self.runs = {name: fixture(name) for name in ('limits-single-684-1', 'limits-bundle-684-1-684-3', 'limits-failed-not-contiguous')}
        self.fetched = []
    async def list_projects(self): return [{'owner_project_id': 'p', 'branch_id': 'main'}]
    async def get_scene(self, scene_id): return {'id': scene_id, 'projectId': None, 'version': 1, 'ownerId': None}
    async def context(self, project, branch): return {}
    async def list_runs(self, project, branch, prefix, trace=None):
        return [{**{k: v for k, v in run.items() if k != 'communications'}, 'communications': [],
                 'communications_available': False, 'communications_truncated': False, 'request_id': prefix + 'k'}
                for run in self.runs.values()]
    async def get_run(self, run_id, project, branch):
        self.fetched.append(run_id)
        run = next((run for run in self.runs.values() if run['run_id'] == run_id), None)
        if run is None:
            raise LookupError('run not found')
        return {**run, 'request_id': 'editor:' + self._project + ':k'}
    async def review_request(self, run_id, project, branch): raise LookupError('no')


def recorded_client(tmp_path):
    from backend.app.core.tracing import JsonlTraceRecorder
    from backend.app.modules.platform.projects import ProjectService
    from backend.app.modules.platform.repository import ProjectRepository
    from backend.app.schemas.platform import ProjectCreate
    owner = RecordedOwner()
    projects = ProjectService(ProjectRepository(tmp_path), owner, owner)
    binding = asyncio.run(projects.create('local', ProjectCreate(owner_project_id='p', branch_id='main', scene_id='s', scene_revision=1)))
    owner._project = binding.project_id
    app = FastAPI()
    app.include_router(create_platform_router(owner, project_service=projects, trace_recorder=JsonlTraceRecorder(tmp_path / 'trace')))
    return TestClient(app), owner, binding.project_id


def test_results_route_answers_for_a_bound_run_only(tmp_path):
    api, owner, project_id = recorded_client(tmp_path)
    response = api.get(f'/api/v1/platform/runs/8c7f6fb7602f4202ba9537bb94d833b9/results?project_id={project_id}')
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body['law']['bcr_pct'], body['law']['far_pct'], body['law']['max_floors']) == (59.92, 249.67, 5)
    assert api.get(f'/api/v1/platform/runs/missing/results?project_id={project_id}').status_code == 404
    assert api.get('/api/v1/platform/runs/8c7f6fb7602f4202ba9537bb94d833b9/results?project_id=other').status_code == 404


def test_latest_route_matches_the_parcel_from_fetched_runs_and_caps_the_search(tmp_path):
    api, owner, project_id = recorded_client(tmp_path)
    base = f'/api/v1/platform/projects/{project_id}/runs/latest'
    newest = api.get(base).json()
    assert newest['run_id'] == '8c7f6fb7602f4202ba9537bb94d833b9' and newest['results']['law']['bcr_pct'] == 59.92
    # Every recorded run asks about 684-1 first; the single-parcel run is listed first, so it wins.
    by_pnu = api.get(f'{base}?goal=limits&pnu={PNU}').json()
    assert by_pnu['run_id'] == '8c7f6fb7602f4202ba9537bb94d833b9'
    assert by_pnu['results']['request']['parcels'] == [PNU]
    assert owner.fetched[-1] == '8c7f6fb7602f4202ba9537bb94d833b9'
    assert api.get(f'{base}?pnu={PNU_2}').status_code == 404
    assert len(owner.fetched) <= 1 + 1 + 3
    assert api.get(f'{base}?goal=health').status_code == 404
    assert api.get(f'{base}?pnu=12').status_code == 422
    assert api.get('/api/v1/platform/projects/other/runs/latest').status_code == 404


def test_latest_service_caps_candidates(tmp_path):
    owner, projects, binding, runs = setup(tmp_path)
    many = [{'run_id': f'r{n}', 'goal': 'limits', 'owner_project_id': 'p', 'branch_id': 'main', 'request_id': 'editor:x:k',
             'status': 'blocked', 'receipt_task_ids': [], 'pending_input': False} for n in range(15)]
    fetched = []
    async def list_runs(project, branch, prefix, trace=None): return many
    async def get_run(run_id, project, branch):
        fetched.append(run_id)
        return {**next(r for r in many if r['run_id'] == run_id), 'communications': [], 'communications_available': False, 'communications_truncated': False}
    owner.list_runs, owner.get_run = list_runs, get_run
    service = RunService(projects, owner, runs.recorder)
    with pytest.raises(LookupError):
        asyncio.run(service.latest('local', binding.project_id, 'limits', PNU))
    assert fetched == [f'r{n}' for n in range(10)]
