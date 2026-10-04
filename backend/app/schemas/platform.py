from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, field_validator


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
            raise ValueError('Only the health template is currently supported')
        return value
