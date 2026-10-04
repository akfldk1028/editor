from backend.app.schemas.platform import ProjectCreate
from backend.app.adapters.platform_scenes import SceneNotFound


class BindingConflict(ValueError):
    pass


class ProjectService:
    def __init__(self, repository, owner, scenes):
        self.repository, self.owner, self.scenes = repository, owner, scenes

    async def create(self, actor: str, request: ProjectCreate):
        projects = await self.owner.list_projects()
        if not any(item['owner_project_id'] == request.owner_project_id and
                   item['branch_id'] == request.branch_id for item in projects):
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
