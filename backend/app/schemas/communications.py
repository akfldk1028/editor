from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class RunCommunication(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    id: str
    task_id: str
    tool: str
    agent: str | None
    state: str
    # The door capped texts at 8,000 until 2026-10-09; it now sends whole answers (Site facts ~30 KB, Law ~31 KB).
    # The bound here only guards memory; a longer text is the door's `truncated` flag, never a refusal.
    request_text: str | None=Field(max_length=262_144)
    response_text: str | None=Field(max_length=262_144)
    transport: Literal['a2a','unknown']
    truncated: bool
    # Added by the Orchestrator door on 2026-10-09: secret-bearing fields were omitted from the texts (editor_dialogue).
    redacted: bool = False
    # Added by the door on 2026-10-12: the A2A task and context the call ran as, so a view can GetTask the agent's own record.
    a2a_task_id: str | None = None
    a2a_context_id: str | None = None


class RunCommunications(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    communications: list[RunCommunication]=Field(max_length=100)
    communications_available: bool
    communications_truncated: bool
