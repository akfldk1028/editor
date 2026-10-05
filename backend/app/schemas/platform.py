from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .specialist_review import specialist_items, validate_specialist_review


class AgentSummary(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    agent_id: str
    label: str
    capabilities: list[str]
    implementation_status: str
    connection_status: str
    checked_at: str | None
    evidence_ref: str | None


class ProjectCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    owner_project_id: str = Field(min_length=1, max_length=200)
    branch_id: str = Field(min_length=1, max_length=200)
    scene_id: str = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    scene_revision: int = Field(ge=0)
    scene_project_id: str | None = Field(default=None, max_length=200)


class ProjectBinding(ProjectCreate):
    project_id: str


class RunCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    request: dict
    scene_revision: int = Field(ge=0)
    source_versions: dict[str, Annotated[int, Field(ge=0)]]

    @field_validator('request')
    @classmethod
    def supported_request(cls, value):
        if value != {'goal':'health'}:
            validate_specialist_review(value)
        return value

    @model_validator(mode='after')
    def bound_specialist_sources(self):
        for item in specialist_items(self.request):
            if any(self.source_versions.get(key) != version for key, version in item['source_versions'].items()):
                raise ValueError('Specialist sources must match submitted context')
        return self
