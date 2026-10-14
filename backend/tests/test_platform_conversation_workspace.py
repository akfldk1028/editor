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


def test_a_conversation_workspace_is_named_once_by_its_first_message_and_a_project_binding_never(tmp_path):
    from backend.app.modules.platform.routers.conversation import conversation_title
    client, repository, binding, _ = setup(tmp_path)
    made = client.post(f'/api/v1/platform/projects/{binding.project_id}/conversations').json()
    assert made['conversation'] is True and made['title'] is None and made['created_at']
    assert repository.name_conversation('local', made['project_id'], '684-1 어린이집')
    assert not repository.name_conversation('local', made['project_id'], '두 번째 메시지')
    assert repository.get('local', made['project_id']).title == '684-1 어린이집'
    assert not repository.name_conversation('local', binding.project_id, '프로젝트 자체')
    assert repository.get('local', binding.project_id).title is None and repository.get('local', binding.project_id).conversation is False
    assert conversation_title('의정부시 산곡동 684-1에 어린이집을 설계하고 싶어요.\n정원 49명') == '의정부시 산곡동 684-1에 어린이집을 설계하고 싶어요.'
    assert conversation_title('아주 ' * 30).endswith('…') and len(conversation_title('아주 ' * 30)) <= 41


def test_a_version_2_database_gains_the_conversation_columns(tmp_path):
    import sqlite3
    from backend.app.modules.platform.repository import ProjectRepository
    db = sqlite3.connect(tmp_path / 'platform.sqlite')
    db.execute('CREATE TABLE projects (project_id TEXT PRIMARY KEY, actor TEXT NOT NULL, owner_project_id TEXT NOT NULL, branch_id TEXT NOT NULL, '
               'scene_id TEXT NOT NULL, scene_revision INTEGER NOT NULL, scene_project_id TEXT, UNIQUE(actor, owner_project_id, branch_id, scene_id))')
    db.execute("INSERT INTO projects VALUES ('p', 'local', 'o', 'main', 's', 1, 'sp')")
    db.execute('PRAGMA user_version=2')
    db.commit(); db.close()
    old = ProjectRepository(tmp_path).get('local', 'p')
    assert (old.branch_id, old.conversation, old.title) == ('main', False, None)


def test_a_new_conversation_workspace_is_usable_before_its_branch_has_a_record(tmp_path):
    import asyncio
    from backend.app.modules.platform.projects import BindingConflict, ProjectService
    client, repository, binding, sources = setup(tmp_path)
    made = repository.get('local', client.post(f'/api/v1/platform/projects/{binding.project_id}/conversations').json()['project_id'])
    sources.version = made.scene_revision  # the scene is unchanged since the workspace was made
    service = ProjectService(repository, sources, sources)
    # The Orchestrator lists only `main` here; the conversation's branch is the editor's own until its first record.
    assert asyncio.run(service.create('local', made.creation())).project_id == made.project_id
    stranger = made.creation().model_copy(update={'branch_id': 'never-made'})
    try:
        asyncio.run(service.create('local', stranger))
        raise AssertionError('an unknown branch must still be refused')
    except BindingConflict:
        pass


def test_a_conversation_workspace_takes_a_scene_refresh_before_its_branch_has_a_record(tmp_path):
    client, repository, binding, sources = setup(tmp_path)
    made = client.post(f'/api/v1/platform/projects/{binding.project_id}/conversations').json()
    sources.version = 3  # the Orchestrator lists only `main`; the scene moved on
    refreshed = client.post(f"/api/v1/platform/projects/{made['project_id']}/scene-revision",
                            json={'expected_scene_revision': 2, 'scene_revision': 3})
    assert refreshed.status_code == 200 and refreshed.json()['scene_revision'] == 3
