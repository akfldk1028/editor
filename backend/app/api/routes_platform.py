import os

from fastapi import APIRouter, HTTPException

from backend.app.adapters.orchestrator import OrchestratorClient, OwnerContractError, OwnerUnavailable
from backend.app.schemas.platform import AgentSummary


def create_platform_router(client: OrchestratorClient | None = None) -> APIRouter:
    owner = client or OrchestratorClient(os.environ.get('EDITOR_ORCHESTRATOR_URL'))
    router = APIRouter(prefix='/api/v1/platform', tags=['platform'])

    @router.get('/agents', response_model=list[AgentSummary])
    async def agents():
        try:
            return await owner.list_agents()
        except OwnerUnavailable:
            raise HTTPException(503, 'Orchestrator catalog unavailable') from None
        except OwnerContractError:
            raise HTTPException(502, 'Orchestrator catalog contract invalid') from None

    return router
