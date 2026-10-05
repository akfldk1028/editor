from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class UISettings(StrictModel):
    show_llm_call_events: bool = False
    expanded_messages_by_default: bool = False
    show_agent_flow_by_default: bool = False
    human_input_timeout_minutes: int = Field(default=3, ge=1, le=30)


class EnvironmentVariable(StrictModel):
    name: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z_][A-Za-z0-9_]*$')
    value: str = Field(max_length=16384)
    type: Literal['string', 'number', 'boolean', 'secret']
    description: str | None = Field(default=None, max_length=1000)
    required: bool = False


class SettingsConfig(StrictModel):
    ui: UISettings
    environment: list[EnvironmentVariable] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def unique_names(self):
        if len({item.name for item in self.environment}) != len(self.environment):
            raise ValueError('Environment variable names must be unique')
        return self


class SettingsUpdate(StrictModel):
    id: Literal[1] = 1
    version: int = Field(ge=0)
    config: SettingsConfig


