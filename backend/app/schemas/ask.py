"""What the conversation sends when the user types a question for the Law Agent."""
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.schemas.site_run import ISO_DATE, PNU


class LawAnalysisCreate(BaseModel):
    """What the law artifact sends for the Law Agent's analysis of one parcel."""
    model_config = ConfigDict(strict=True, extra='forbid')
    pnu: str
    building_type: str | None = Field(default=None, max_length=64)
    floor_area_m2: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    assessment_date: str | None = None

    @field_validator('pnu')
    @classmethod
    def nineteen_digits(cls, value):
        if not PNU.fullmatch(value):
            raise ValueError('PNU requires 19 digits')
        return value

    @field_validator('building_type')
    @classmethod
    def nonblank_type(cls, value):
        if value is not None and not value.strip():
            raise ValueError('building_type must not be blank')
        return value.strip() if value else value

    @field_validator('assessment_date')
    @classmethod
    def real_date(cls, value):
        if value is None:
            return value
        if not ISO_DATE.fullmatch(value):
            raise ValueError('assessment_date must be YYYY-MM-DD')
        date.fromisoformat(value)
        return value


class AskCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    text: str = Field(min_length=1, max_length=500)
    pnu: str | None = None
    assessment_date: str | None = None
    # The agent the user picked when the router asked (a choice button); the router then skips its guess.
    role: str | None = Field(default=None, min_length=1, max_length=40, pattern=r'^[a-z_]+$')

    @field_validator('text')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('text must not be blank')
        return value.strip()

    @field_validator('pnu')
    @classmethod
    def nineteen_digits(cls, value):
        if value is not None and not PNU.fullmatch(value):
            raise ValueError('PNU requires 19 digits')
        return value

    @field_validator('assessment_date')
    @classmethod
    def real_date(cls, value):
        if value is None:
            return value
        if not ISO_DATE.fullmatch(value):
            raise ValueError('assessment_date must be YYYY-MM-DD')
        date.fromisoformat(value)
        return value
