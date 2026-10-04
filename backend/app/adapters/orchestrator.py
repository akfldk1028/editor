import httpx
from pydantic import TypeAdapter, ValidationError

from backend.app.schemas.platform import AgentSummary


class OwnerUnavailable(Exception):
    pass


class OwnerContractError(Exception):
    pass


class OrchestratorClient:
    def __init__(self, base_url: str | None, *, transport=None):
        self.base_url = base_url
        self.transport = transport

    async def list_agents(self) -> list[AgentSummary]:
        if not self.base_url:
            raise OwnerUnavailable()
        try:
            async with httpx.AsyncClient(timeout=8, transport=self.transport, follow_redirects=False) as client:
                response = await client.get(self.base_url.rstrip('/') + '/editor/v1/agents')
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OwnerUnavailable() from exc
        try:
            return TypeAdapter(list[AgentSummary]).validate_json(response.content)
        except (ValidationError, ValueError) as exc:
            raise OwnerContractError() from exc
