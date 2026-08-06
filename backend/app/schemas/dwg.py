from pydantic import BaseModel, ConfigDict, Field


class DwgInspectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = Field(pattern=r"^planm-dwg-inspection-request/v1$")
    layer: str = Field(default="F001_ROOMS", min_length=1, max_length=64)
