from fastapi import HTTPException

from backend.app.adapters.orchestrator import OwnerContractError, OwnerUnavailable
from backend.app.modules.platform.projects import BindingConflict


class DesignAccess:
    def __init__(self, projects_service, allowed_origin):
        self.projects_service = projects_service
        self.allowed_origin = allowed_origin

    def binding(self, project_id):
        value = self.projects_service().repository.get('local', project_id)
        if value is None:
            raise HTTPException(404, 'Project not found')
        return value

    async def mutate(self, project_id, body, request):
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != self.allowed_origin):
            raise HTTPException(403, 'Cross-origin design changes are not allowed')
        value = self.binding(project_id)
        if value.scene_revision != body.scene_revision:
            raise HTTPException(409, 'Scene revision changed')
        try:
            await self.projects_service().create('local', value.creation())
        except BindingConflict:
            raise HTTPException(409, 'Project or scene revision changed') from None
        except OwnerUnavailable:
            raise HTTPException(503, 'Project source unavailable') from None
        except OwnerContractError:
            raise HTTPException(502, 'Project source contract invalid') from None
        return value
