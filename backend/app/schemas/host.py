"""What the conversation sends to bring agents up before a goal."""
from pydantic import BaseModel, ConfigDict, Field


class HostEnsure(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    # Agent ids as the network names them (site_context, design_intent, …); at most the whole network.
    agents: list[str] = Field(min_length=1, max_length=20)
    timeout_s: int = Field(default=90, ge=5, le=300)
    # How long the caller will use them; the host stops an agent idle_timeout_s after its last lease ended.
    lease_s: int = Field(default=1800, ge=60, le=86400)

    def ids(self) -> list[str]:
        seen = []
        for agent in self.agents:
            if not agent or not agent.replace('_', '').replace('-', '').isalnum() or agent in seen:
                continue
            seen.append(agent)
        if not seen:
            raise ValueError('agents must name at least one agent')
        return seen


class HostTouch(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    agents: list[str] = Field(min_length=1, max_length=20)
    lease_s: int = Field(default=1800, ge=60, le=86400)

    def ids(self) -> list[str]:
        return HostEnsure(agents=self.agents).ids()
