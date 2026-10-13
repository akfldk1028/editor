"""One conversation = one workspace: a new conversation binds the same owner project and scene on a branch of its own."""
from test_platform_scene_refresh import setup


def test_a_new_conversation_gets_its_own_branch_of_the_same_project_and_scene(tmp_path):
    client, repository, binding, _ = setup(tmp_path)
    path = f'/api/v1/platform/projects/{binding.project_id}/conversations'
    assert client.post(path, headers={'origin': 'https://other.example'}).status_code == 403
    first, second = client.post(path), client.post(path)
    assert first.status_code == second.status_code == 201
    a, b = first.json(), second.json()
    for made in (a, b):
        assert made['branch_id'].startswith('c-') and made['branch_id'] != binding.branch_id
        assert (made['owner_project_id'], made['scene_id'], made['scene_revision']) == ('owner', 'scene', 2)
    assert a['branch_id'] != b['branch_id'] and a['project_id'] != b['project_id']
    assert {p.project_id for p in repository.list('local')} == {binding.project_id, a['project_id'], b['project_id']}
    assert client.post('/api/v1/platform/projects/missing/conversations').status_code == 404
