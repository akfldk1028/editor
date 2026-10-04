from pydantic import BaseModel, ConfigDict


class AgentSummary(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    agent_id: str
    label: str
    capabilities: list[str]
    implementation_status: str
    connection_status: str
    checked_at: str | None
    evidence_ref: str | None
