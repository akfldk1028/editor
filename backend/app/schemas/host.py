"""What the conversation sends to bring agents up before a goal."""
from pydantic import BaseModel, ConfigDict, Field


class HostEnsure(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    # Agent ids as the network names them (site_context, design_intent, …); at most the whole network.
    agents: list[str] = Field(min_length=1, max_length=20)
    timeout_s: int = Field(default=90, ge=5, le=300)

    def ids(self) -> list[str]:
        seen = []
        for agent in self.agents:
            if not agent or not agent.replace('_', '').replace('-', '').isalnum() or agent in seen:
                continue
            seen.append(agent)
        if not seen:
            raise ValueError('agents must name at least one agent')
        return seen
