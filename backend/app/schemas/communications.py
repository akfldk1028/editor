from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class RunCommunication(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    id: str
    task_id: str
    tool: str
    agent: str | None
    state: str
    request_text: str | None=Field(max_length=8000)
    response_text: str | None=Field(max_length=8000)
    transport: Literal['a2a','unknown']
    truncated: bool


class RunCommunications(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    communications: list[RunCommunication]=Field(max_length=100)
    communications_available: bool
    communications_truncated: bool
