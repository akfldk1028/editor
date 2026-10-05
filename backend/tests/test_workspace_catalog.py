from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.app.modules.workspace.seeds import DEFAULT_GALLERY, DEFAULT_TEAMS, LAND_TEAM_LABEL


SEED_LABELS = [team['label'] for team in reversed(DEFAULT_TEAMS)]


def test_team_template_and_gallery_survive_restart_without_running_agents(tmp_path, monkeypatch):
    monkeypatch.setenv('EDITOR_WORKSPACE_DATA_DIR', str(tmp_path))
    api = TestClient(create_app())
    component = {'provider': 'autogen_agentchat.teams.RoundRobinGroupChat', 'component_type': 'team', 'config': {'participants': []}, 'label': 'Saved template'}
    response = api.post('/api/v1/workspace/teams', json={'component': component})
    assert response.status_code == 201
    team = response.json()
    assert team['component'] == component
    assert team['execution_status'] == 'not_executed'
    component['label'] = 'Edited template'
    changed = api.put(f"/api/v1/workspace/teams/{team['id']}", json={'component': component, 'version': team['version']})
    assert changed.status_code == 200
    assert api.put(f"/api/v1/workspace/teams/{team['id']}", json={'component': component, 'version': team['version']}).status_code == 409
    gallery = {'name': 'Saved gallery', 'components': {'teams': [component], 'agents': [], 'models': [], 'tools': [], 'terminations': []}, 'metadata': {'description': 'Test'}}
    response = api.post('/api/v1/workspace/galleries', json={'config': gallery})
    assert response.status_code == 201
    restored = TestClient(create_app())
    assert restored.get('/api/v1/workspace/galleries').json()[0]['config'] == gallery
    assert restored.get('/api/v1/workspace/teams').json()[0]['component']['label'] == 'Edited template'
    assert restored.delete(f"/api/v1/workspace/teams/{team['id']}").status_code == 200
    assert restored.get(f"/api/v1/workspace/teams/{team['id']}").status_code == 404


def test_template_validation_is_structural_and_rejects_bad_requests(tmp_path, monkeypatch):
    monkeypatch.setenv('EDITOR_WORKSPACE_DATA_DIR', str(tmp_path))
    api = TestClient(create_app(platform_public_origin='http://editor.test'))
    bad = api.post('/api/v1/workspace/validate', json={'component': {'provider': 'x', 'config': {}}})
    assert bad.status_code == 200
    assert bad.json()['is_valid'] is False
    good = api.post('/api/v1/workspace/validate', json={'component': {'provider': 'x', 'component_type': 'agent', 'config': {'name': 'agent'}}})
    assert good.status_code == 200
    assert good.json()['scope'] == 'configuration_structure_only'
    assert good.json()['warnings']
    assert api.post('/api/v1/workspace/teams', json={'component': {}}, headers={'Origin': 'http://other.test'}).status_code == 403
    assert api.post('/api/v1/workspace/teams', json={'component': {}, 'user_id': 'other'}).status_code == 422


def test_gallery_rejects_malformed_components_before_they_can_break_cards(tmp_path, monkeypatch):
    monkeypatch.setenv('EDITOR_WORKSPACE_DATA_DIR', str(tmp_path))
    api = TestClient(create_app())
    response = api.post('/api/v1/workspace/galleries', json={'config': {'name': 'Bad', 'components': {'agents': [{}]}}})
    assert response.status_code == 422
    assert [g['config']['name'] for g in api.get('/api/v1/workspace/galleries').json()] == [DEFAULT_GALLERY['name']]


def test_team_storage_rejects_shapes_that_crash_the_builder(tmp_path, monkeypatch):
    monkeypatch.setenv('EDITOR_WORKSPACE_DATA_DIR', str(tmp_path))
    api = TestClient(create_app())
    base = {'provider': 'test.Team', 'component_type': 'team', 'config': {}}
    for patch in ({'config': {'participants': 'broken'}}, {'config': {'participants': [None]}}, {'label': {}}, {'provider': ' '}):
        response = api.post('/api/v1/workspace/teams', json={'component': {**base, **patch}})
        assert response.status_code == 422, patch
    assert [t['component']['label'] for t in api.get('/api/v1/workspace/teams').json()] == SEED_LABELS


def test_default_seed_validates_against_execution_policy():
    from backend.app.adapters.workspace_team import validate_components
    from backend.app.modules.workspace.validation import validate_template_shape

    for team in DEFAULT_TEAMS:
        validate_template_shape(team, ('team',))
        validate_components(team)
    for kind, items in DEFAULT_GALLERY['components'].items():
        for item in items:
            validate_template_shape(item)


def test_seed_is_idempotent_and_respects_user_deletion(tmp_path):
    from backend.app.modules.workspace.catalog import CatalogRepository

    repo = CatalogRepository(tmp_path)
    repo.seed_defaults(DEFAULT_TEAMS, DEFAULT_GALLERY)
    repo.seed_defaults(DEFAULT_TEAMS, DEFAULT_GALLERY)
    teams = repo.list('teams')
    assert [t['component']['label'] for t in teams] == SEED_LABELS
    assert len(repo.list('galleries')) == 1
    roundrobin = next(t for t in teams if t['component']['label'] == 'RoundRobin Team')
    repo.delete('teams', roundrobin['id'])
    repo.seed_defaults(DEFAULT_TEAMS, DEFAULT_GALLERY)
    assert [t['component']['label'] for t in repo.list('teams')] == [LAND_TEAM_LABEL]
    assert repo.find_team(LAND_TEAM_LABEL)['label'] == LAND_TEAM_LABEL
    assert repo.find_team('RoundRobin Team') is None


def test_validate_test_runs_replay_model_and_reports_loaded_only_for_agents(tmp_path, monkeypatch):
    monkeypatch.setenv('EDITOR_WORKSPACE_DATA_DIR', str(tmp_path))
    api = TestClient(create_app(platform_public_origin='http://editor.test'))
    replay = {'provider': 'autogen_ext.models.replay.ReplayChatCompletionClient', 'component_type': 'model',
              'config': {'chat_completions': ['4']}}
    model = api.post('/api/v1/workspace/validate/test', json={'component': replay, 'timeout': 10})
    assert model.status_code == 200, model.text
    assert model.json()['status'] is True and model.json()['data']['content'] == '4'
    agent = {'provider': 'autogen_agentchat.agents.AssistantAgent', 'component_type': 'agent',
             'config': {'name': 'a', 'description': 'd', 'reflect_on_tool_use': False, 'tool_call_summary_format': '{result}',
                        'model_client': replay, 'workbench': [{'provider': 'autogen_core.tools.StaticStreamWorkbench',
                                                               'component_type': 'workbench', 'config': {'tools': []}}]}}
    loaded = api.post('/api/v1/workspace/validate/test', json={'component': agent}).json()
    assert loaded['status'] is True and loaded['message'] == 'Loaded; not executed'
    unsafe = api.post('/api/v1/workspace/validate/test', json={'component': {
        'provider': 'autogen_core.tools.FunctionTool', 'component_type': 'tool', 'config': {'source_code': 'x', 'name': 'x'}}}).json()
    assert unsafe['status'] is False
    assert api.post('/api/v1/workspace/validate/test', json={'component': replay},
                    headers={'Origin': 'http://other.test'}).status_code == 403
