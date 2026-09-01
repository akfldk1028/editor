from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PlanmRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["planm-run-create/v1"]
    mass: dict[str, Any]


class PlanmApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["planm-approval/v1"]
    alternative_id: str = Field(min_length=1, max_length=128)
