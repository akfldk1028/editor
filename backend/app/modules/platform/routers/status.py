"""GET /api/v1/platform/status: every registered service's state, for the shell's 시스템 artifact.
GET /api/v1/platform/capabilities: the goals the product can ask for, for the conversation's choices."""
from fastapi import APIRouter

from backend.app.adapters.orchestrator import OrchestratorClient
from backend.app.modules.platform.goals import capabilities
from backend.app.modules.platform.status.probes import Prober
from backend.app.modules.platform.status.registry import Registry
from backend.app.modules.platform.status.service import StatusService


def create_status_router(owner: OrchestratorClient, service: StatusService | None = None) -> APIRouter:
    router = APIRouter()
    status_service = service or StatusService(Registry(), Prober(), owner)

    @router.get('/status')
    async def status(refresh: bool = False):
        return await status_service.status(refresh=refresh)

    @router.get('/capabilities')
    async def goals():
        return capabilities()

    return router
