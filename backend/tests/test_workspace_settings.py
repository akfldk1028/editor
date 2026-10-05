from fastapi.testclient import TestClient
from backend.app.main import create_app


def client(tmp_path, monkeypatch):
    monkeypatch.setenv('EDITOR_WORKSPACE_DATA_DIR', str(tmp_path))
    return TestClient(create_app(platform_public_origin='http://editor.test'))


def test_settings_persist_and_reject_stale_revisions(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    response = api.get('/api/v1/workspace/settings')
    assert response.status_code == 200
    value = response.json()
    value['config']['ui']['human_input_timeout_minutes'] = 9
    saved = api.put('/api/v1/workspace/settings', json=value)
    assert saved.status_code == 200
    assert saved.json()['version'] > value['version']
    assert client(tmp_path, monkeypatch).get('/api/v1/workspace/settings').json()['config']['ui']['human_input_timeout_minutes'] == 9
    assert api.put('/api/v1/workspace/settings', json=value).status_code == 409


def test_settings_origin_and_validation(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    value = api.get('/api/v1/workspace/settings').json()
    assert api.put('/api/v1/workspace/settings', json=value, headers={'Origin': 'http://other.test'}).status_code == 403
    value['config']['ui']['human_input_timeout_minutes'] = 99
    assert api.put('/api/v1/workspace/settings', json=value).status_code == 422


def test_environment_roundtrip_does_not_mutate_process_environment(tmp_path, monkeypatch):
    import os
    api = client(tmp_path, monkeypatch)
    value = api.get('/api/v1/workspace/settings').json()
    assert 'config' in value
    value['config']['environment'] = [{'name': 'EDITOR_TEST_SAVED_ONLY', 'type': 'secret', 'value': 'test-placeholder', 'required': False}]
    assert api.put('/api/v1/workspace/settings', json=value).status_code == 200
    saved = client(tmp_path, monkeypatch).get('/api/v1/workspace/settings').json()
    assert saved['config']['environment'][0]['value'] == 'test-placeholder'
    assert 'EDITOR_TEST_SAVED_ONLY' not in os.environ


def test_apply_environment_fills_only_missing_model_fields_and_leaves_input_untouched():
    import copy
    import os
    from backend.app.adapters.workspace_credentials import apply_environment

    openai = 'autogen_ext.models.openai.OpenAIChatCompletionClient'
    team = {'provider': 'autogen_agentchat.teams.RoundRobinGroupChat', 'component_type': 'team', 'config': {'participants': [
        {'provider': 'autogen_agentchat.agents.AssistantAgent', 'component_type': 'agent', 'config': {'name': 'a',
         'model_client': {'provider': openai, 'component_type': 'model', 'config': {'model': 'gpt-4o-mini'}}}},
        {'provider': 'autogen_agentchat.agents.AssistantAgent', 'component_type': 'agent', 'config': {'name': 'b',
         'model_client': {'provider': openai, 'component_type': 'model', 'config': {'model': 'gpt-4o-mini', 'api_key': 'explicit'}}}},
    ]}}
    before = copy.deepcopy(team)
    filled = apply_environment(team, [{'name': 'OPENAI_API_KEY', 'value': 'saved-key', 'type': 'secret', 'required': False},
                                      {'name': 'OPENAI_BASE_URL', 'value': '', 'type': 'string', 'required': False}])
    first, second = (p['config']['model_client']['config'] for p in filled['config']['participants'])
    assert first['api_key'] == 'saved-key' and 'base_url' not in first
    assert second['api_key'] == 'explicit'
    assert team == before
    assert 'OPENAI_API_KEY' not in os.environ or os.environ['OPENAI_API_KEY'] != 'saved-key'
