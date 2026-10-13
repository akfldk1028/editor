from uuid import uuid4

from backend.app.schemas.platform import ProjectCreate, SceneRevisionRefresh
from backend.app.adapters.platform_scenes import SceneNotFound


class BindingConflict(ValueError):
    pass


class BindingNotFound(LookupError):
    pass


class ProjectService:
    def __init__(self, repository, owner, scenes):
        self.repository, self.owner, self.scenes = repository, owner, scenes

    async def create(self, actor: str, request: ProjectCreate):
        projects = await self.owner.list_projects()
        # A conversation's own branch exists in the Orchestrator only after its first record: the workspace the
        # editor made for it stands for the branch until then. Everything else is checked as for any binding.
        held = self.repository.find(actor, request)
        if not (held is not None and held.conversation) and not any(
                item['owner_project_id'] == request.owner_project_id and item['branch_id'] == request.branch_id
                for item in projects):
            raise BindingConflict('owner project or branch does not exist')
        try:
            scene = await self.scenes.get_scene(request.scene_id)
        except SceneNotFound as exc:
            raise BindingConflict('scene does not exist') from exc
        # Legacy unowned scenes are shared only in this explicit local single-user profile.
        if 'ownerId' not in scene or scene['ownerId'] not in (None, actor):
            raise BindingConflict('scene is not accessible to this actor')
        if (scene.get('id') != request.scene_id or scene.get('projectId') != request.scene_project_id
                or scene.get('version') != request.scene_revision):
            raise BindingConflict('scene project or revision does not match')
        try:
            return self.repository.create(actor, request)
        except ValueError as exc:
            raise BindingConflict(str(exc)) from exc

    def start_conversation(self, actor: str, project_id: str):
        """A new conversation's own workspace: the same owner project and scene on a branch of its own, so what one
        conversation records (its parcel, assessment date, brief) never binds another. The Orchestrator makes the
        branch with the conversation's first record, so it is not looked up here."""
        binding = self.repository.get(actor, project_id)
        if binding is None:
            raise BindingNotFound()
        request = ProjectCreate(owner_project_id=binding.owner_project_id, branch_id=f'c-{uuid4().hex[:12]}',
                                scene_id=binding.scene_id, scene_revision=binding.scene_revision,
                                scene_project_id=binding.scene_project_id)
        try:
            return self.repository.create(actor, request, conversation=True)
        except ValueError as exc:
            raise BindingConflict(str(exc)) from exc

    async def refresh_scene_revision(self, actor: str, project_id: str, request: SceneRevisionRefresh):
        binding = self.repository.get(actor, project_id)
        if binding is None:
            raise BindingNotFound()
        if binding.scene_revision != request.expected_scene_revision:
            raise BindingConflict('binding revision changed')
        projects = await self.owner.list_projects()
        if not any(item['owner_project_id'] == binding.owner_project_id and
                   item['branch_id'] == binding.branch_id for item in projects):
            raise BindingConflict('owner project or branch no longer exists')
        try:
            scene = await self.scenes.get_scene(binding.scene_id)
        except SceneNotFound as exc:
            raise BindingConflict('scene does not exist') from exc
        if ('ownerId' not in scene or scene['ownerId'] not in (None, actor)
                or scene.get('id') != binding.scene_id or scene.get('projectId') != binding.scene_project_id
                or scene.get('version') != request.scene_revision):
            raise BindingConflict('scene identity, access or revision changed')
        try:
            return self.repository.refresh_scene_revision(actor, project_id,
                request.expected_scene_revision, request.scene_revision)
        except ValueError as exc:
            raise BindingConflict(str(exc)) from exc
