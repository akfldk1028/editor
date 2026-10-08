"""GET /api/v1/platform/status: every registered service's state, for the shell's 시스템 artifact."""
from fastapi import APIRouter

from backend.app.adapters.orchestrator import OrchestratorClient
from backend.app.modules.platform.status.probes import Prober
from backend.app.modules.platform.status.registry import Registry
from backend.app.modules.platform.status.service import StatusService


def create_status_router(owner: OrchestratorClient, service: StatusService | None = None) -> APIRouter:
    router = APIRouter()
    status_service = service or StatusService(Registry(), Prober(), owner)

    @router.get('/status')
    async def status(refresh: bool = False):
        return await status_service.status(refresh=refresh)

    return router
