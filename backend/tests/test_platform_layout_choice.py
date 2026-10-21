"""A 배치 설계 ends as a selection set: the editor serves MasterPlan's candidates, records the person's pick through the
Orchestrator, and draws the chosen layout for the continuation run (which has no synthesis call of its own)."""
import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.adapters.orchestrator import OwnerRejected
from backend.app.modules.platform.routers.platform import create_platform_router
from backend.tests.test_platform_runs import setup

PNU = '4115011300106840001'
RING = [[127.108, 37.730], [127.109, 37.730], [127.109, 37.731], [127.108, 37.731], [127.108, 37.730]]
LAYOUT = {'schema_version': 'masterplan.layout.v1', 'pnu': PNU, 'coordinate_crs': 'EPSG:4326', 'status': 'needs_evidence',
          'features': [{'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [RING]},
                        'properties': {'layer': 'building_footprint', 'level': 0, 'area_m2': 800}}],
          'metrics': {'building_footprint_m2': 800, 'coverage_ratio_pct': 32}}


class ChoosingOwner:
    """The Orchestrator door with one selection set: run r1 (the 배치 설계) and, after a pick, run r2 (its continuation)."""
    def __init__(self):
        self.chosen = None
        self.project = 'proj'
        self.selections = []
        self.alternatives_state = 'completed'   # what the alternatives row of r1 says happened

    async def list_projects(self): return [{'owner_project_id': 'p', 'branch_id': 'main'}]
    async def get_scene(self, scene_id): return {'id': scene_id, 'projectId': None, 'version': 1, 'ownerId': None}
    async def context(self, project, branch): return {}

    def run(self, run_id):
        if run_id == 'r1':
            return {'run_id': 'r1', 'owner_project_id': 'p', 'branch_id': 'main', 'request_id': f'editor:{self.project}:site-1', 'goal': 'masterplan',
                    'status': 'blocked', 'receipt_task_ids': [], 'pending_input': False, 'pnu': PNU,
                    'communications': [{'id': '1', 'task_id': 'masterplan_layout_alternatives', 'tool': 'masterplan_layout_alternatives', 'agent': 'masterplan',
                                        'state': self.alternatives_state, 'request_text': '{"pnu": "%s", "floor_area_m2": 3000}' % PNU,
                                        'response_text': '{"status": "succeeded"}', 'truncated': False}],
                    'communications_available': True, 'communications_truncated': False}
        if run_id == 'r2' and self.chosen:
            return {'run_id': 'r2', 'owner_project_id': 'p', 'branch_id': 'main', 'request_id': f'editor:{self.project}:selection-editor-1', 'goal': 'masterplan',
                    'status': 'succeeded', 'receipt_task_ids': [], 'pending_input': False, 'pnu': PNU,
                    'communications': [{'id': '1', 'task_id': 'masterplan_layout_validate', 'tool': 'masterplan_layout_validate', 'agent': 'masterplan',
                                        'state': 'completed', 'request_text': '{}', 'response_text': '{"status": "succeeded"}', 'truncated': False}],
                    'communications_available': True, 'communications_truncated': False}
        raise LookupError('run not found')

    async def list_runs(self, project, branch, prefix, trace=None):
        runs = [self.run('r2'), self.run('r1')] if self.chosen else [self.run('r1')]
        return [{k: v for k, v in run.items() if k not in ('communications', 'pnu')} for run in runs if run['request_id'].startswith(prefix)]

    async def get_run(self, run_id, project, branch):
        return self.run(run_id)

    async def alternatives(self, run_id, project, branch):
        if run_id != 'r1':
            raise LookupError('run not found')
        return {'run_id': 'r1', 'index_revision': 1, 'selection_revision': 1 if self.chosen else 0, 'chosen_candidate_id': self.chosen,
                'candidates': [{'candidate_id': 'a', 'label': '도로 쪽 배치', 'status': 'needs_evidence', 'layout': LAYOUT, 'preview_svg': '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'},
                               {'candidate_id': 'b', 'label': '안쪽 배치', 'status': 'needs_evidence', 'layout': LAYOUT, 'preview_svg': None}]}

    async def select_alternative(self, run_id, project, branch, candidate_id):
        if run_id != 'r1':
            raise LookupError('run not found')
        if candidate_id not in ('a', 'b'):
            raise OwnerRejected('candidate_id is not a selectable candidate of this run')
        self.chosen = candidate_id
        self.selections.append((project, branch, candidate_id))
        return {'dispatch_run_id': 'd1', 'candidate_id': candidate_id, 'status': 'queued', 'queued': True,
                'decision_id': 'editor-1', 'continuation_request_id': f'editor:{self.project}:selection-editor-1'}

    async def layout(self, run_id, project, branch):
        if not self.chosen:
            raise LookupError('no layout')
        return {'run_id': run_id, 'revision': 3, 'quality': 'valid', 'dirty': False, 'candidate_id': self.chosen, 'layout': LAYOUT}


def client(tmp_path):
    owner, projects, binding, runs = setup(tmp_path)
    choosing = ChoosingOwner()
    choosing.project = binding.project_id
    projects.owner = choosing
    from backend.app.modules.platform.runs import RunService
    service = RunService(projects, choosing, runs.recorder)
    app = FastAPI()
    app.include_router(create_platform_router(choosing, project_service=projects, trace_recorder=runs.recorder))
    return TestClient(app), choosing, binding.project_id, service


def test_the_selection_set_is_served_and_a_pick_continues_as_the_projects_run(tmp_path):
    api, owner, project, service = client(tmp_path)
    found = api.get('/api/v1/platform/runs/r1/alternatives', params={'project_id': project})
    assert found.status_code == 200, found.text
    assert found.json()['chosen_candidate_id'] is None
    assert [c['candidate_id'] for c in found.json()['candidates']] == ['a', 'b']
    assert found.json()['candidates'][0]['preview_svg'].startswith('<svg')
    first = found.json()['candidates'][0]
    assert 'layout' not in first and first['masterplan']['layout']['footprint_m2'] == 800
    assert first['masterplan']['layout']['storeys'] == 4          # 3000 ㎡ asked / 800 ㎡ footprint
    assert api.get('/api/v1/platform/runs/zzz/alternatives', params={'project_id': project}).status_code == 404

    base = f'/api/v1/platform/projects/{project}/runs/r1/select'
    assert api.post(base, json={'candidate_id': 'a'}, headers={'origin': 'http://evil.example'}).status_code == 403
    assert api.post(base, json={'candidate_id': 'zzz'}).status_code == 409
    assert api.post(base, json={'candidate_id': 'a', 'approve': True}).status_code == 422
    picked = api.post(base, json={'candidate_id': 'a'})
    assert picked.status_code == 202, picked.text
    assert picked.json()['continuation_request_id'] == f'editor:{project}:selection-editor-1'
    assert owner.selections == [('p', 'main', 'a')]
    assert api.get('/api/v1/platform/runs/r1/alternatives', params={'project_id': project}).json()['chosen_candidate_id'] == 'a'


def test_the_continuation_run_draws_the_chosen_layout(tmp_path):
    api, owner, project, service = client(tmp_path)
    owner.chosen = 'a'
    # The run itself has no synthesis call; its results carry the branch's layout from the Orchestrator's layout door.
    results = api.get('/api/v1/platform/runs/r2/results', params={'project_id': project})
    assert results.status_code == 200, results.text
    plan = results.json()['masterplan']
    assert plan['candidate_id'] == 'a' and plan['code'] == 'chosen_candidate'
    assert plan['layout']['footprint_m2'] == 800 and plan['layout']['layers'] == ['building_footprint']
    # The newest 배치 설계 of the parcel is that continuation (the door names its parcel).
    latest = asyncio.run(service.latest('local', project, 'masterplan', PNU))
    assert latest['run_id'] == 'r2' and latest['results']['masterplan']['candidate_id'] == 'a'
    shown = api.get('/api/v1/platform/runs/r2/layout', params={'project_id': project})
    assert shown.status_code == 200 and shown.json()['masterplan']['layout']['footprint_m2'] == 800
    # The 배치 설계 that produced the set draws nothing itself: it says a pick is wanted (nothing is guessed across runs).
    parent = api.get('/api/v1/platform/runs/r1/results', params={'project_id': project}).json()['masterplan']
    assert parent['layout'] is None and parent['code'] == 'masterplan_alternative_selection_required'


def test_a_lost_or_failed_alternatives_answer_is_not_announced_as_a_set_to_pick_from(tmp_path):
    api, owner, project, service = client(tmp_path)
    told = api.get('/api/v1/platform/runs/r1/results', params={'project_id': project}).json()
    assert told['masterplan']['code'] == 'masterplan_alternative_selection_required'
    for state in ('reconciling', 'failed', 'running'):
        owner.alternatives_state = state
        told = api.get('/api/v1/platform/runs/r1/results', params={'project_id': project}).json()
        assert not told.get('masterplan'), state
