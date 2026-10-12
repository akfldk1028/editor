from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .site_run import is_site_run, validate_site_run
from .specialist_review import specialist_items, validate_specialist_review


class AgentSkill(BaseModel):
    """A skill as the agent's A2A card declares it (id, name, description)."""
    model_config = ConfigDict(strict=True, extra='forbid')
    id: str
    name: str
    description: str


class AgentSummary(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    agent_id: str
    label: str
    capabilities: list[str]
    implementation_status: str
    connection_status: str
    checked_at: str | None
    evidence_ref: str | None
    # The agent's own words from its live A2A card (`/.well-known/agent-card.json`); None when the card is unreachable.
    description: str | None = None
    skills: list[AgentSkill] | None = None


class ProjectCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    owner_project_id: str = Field(min_length=1, max_length=200)
    branch_id: str = Field(min_length=1, max_length=200)
    scene_id: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    scene_revision: int = Field(ge=0)
    scene_project_id: str | None = Field(default=None, max_length=200)


class ProjectBinding(ProjectCreate):
    project_id: str


class SceneRevisionRefresh(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    expected_scene_revision: int = Field(ge=0)
    scene_revision: int = Field(ge=0)

    @model_validator(mode='after')
    def advances_revision(self):
        if self.scene_revision <= self.expected_scene_revision:
            raise ValueError('scene revision must advance')
        return self


class RunCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    request: dict
    # The conversation this request belongs to (the editor's conversation id), so the ledger scopes the call to it.
    conversation_id: str | None = Field(default=None, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')
    scene_revision: int = Field(ge=0)
    source_versions: dict[str, Annotated[int, Field(ge=0)]]

    @field_validator('request')
    @classmethod
    def supported_request(cls, value):
        if value == {'goal':'health'}:
            return value
        if is_site_run(value):
            validate_site_run(value)
        else:
            validate_specialist_review(value)
        return value

    @model_validator(mode='after')
    def bound_specialist_sources(self):
        for item in specialist_items(self.request):
            if any(self.source_versions.get(key) != version for key, version in item['source_versions'].items()):
                raise ValueError('Specialist sources must match submitted context')
        return self
