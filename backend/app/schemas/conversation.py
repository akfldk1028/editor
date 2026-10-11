from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ConversationId = Annotated[str, Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')]


class ConversationModel(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')


class ConversationContext(ConversationModel):
    pnu: str | None = Field(default=None, pattern=r'^[0-9]{19}$')
    address: str | None = Field(default=None, min_length=1, max_length=500)
    assessment_date: str | None = None
    law_run_id: ConversationId | None = None

    @field_validator('assessment_date')
    @classmethod
    def valid_date(cls, value):
        if value is not None and date.fromisoformat(value).isoformat() != value:
            raise ValueError('Expected ISO calendar date')
        return value


class ConversationConfirmation(ConversationModel):
    artifact_id: ConversationId
    context_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


class ConversationSubmit(ConversationModel):
    conversation_id: ConversationId = 'main'
    message_id: ConversationId
    text: str = Field(min_length=1, max_length=8000)
    context: ConversationContext = Field(default_factory=ConversationContext)
    confirmation: ConversationConfirmation | None = None

    @field_validator('text')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Message is blank')
        return value


class ConversationMessage(ConversationModel):
    id: ConversationId
    role: Literal['user', 'assistant']
    agent: str | None = Field(max_length=200)
    text: str = Field(max_length=100000)
    at: str = Field(max_length=64)

    @field_validator('at')
    @classmethod
    def timestamp(cls, value):
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('Timestamp requires timezone')
        return value


class ConversationArtifact(ConversationModel):
    id: ConversationId
    owner: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    data: dict
    status: str = Field(min_length=1, max_length=100)


class ConversationSnapshot(ConversationModel):
    owner_project_id: str = Field(min_length=1, max_length=200)
    branch_id: str = Field(min_length=1, max_length=200)
    conversation_id: ConversationId
    revision: int = Field(ge=0)
    status: Literal['idle', 'working', 'failed']
    messages: list[ConversationMessage] = Field(max_length=2000)
    artifacts: list[ConversationArtifact] = Field(max_length=1000)
    error: str | None = Field(max_length=8000)

    @model_validator(mode='after')
    def unique_records(self):
        for records in (self.messages, self.artifacts):
            if len({record.id for record in records}) != len(records):
                raise ValueError('Duplicate record identity')
        return self
