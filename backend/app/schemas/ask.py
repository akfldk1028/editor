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


class ClauseRef(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    instrument: str = Field(min_length=1, max_length=120)
    kind: str = Field(pattern=r'^(act|decree|rule|ordinance)$')
    article: str | None = Field(default=None, max_length=40)
    clause: str | None = Field(default=None, max_length=40)


class ClauseContext(BaseModel):
    """The review item a question is about (law artifact → 이 조항 질문하기): Law Agent answers about exactly it."""
    model_config = ConfigDict(strict=True, extra='forbid')
    item_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=120)
    refs: list[ClauseRef] = Field(min_length=1, max_length=12)
    reason: str | None = Field(default=None, max_length=400)
    status: str | None = Field(default=None, max_length=20)
    basis: str | None = Field(default=None, max_length=400)


class AskCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    text: str = Field(min_length=1, max_length=500)
    pnu: str | None = None
    # The site's address as the conversation shows it; only read into the Orchestrator's situation text.
    address: str | None = Field(default=None, max_length=200)
    assessment_date: str | None = None
    # The agent the user picked when the router asked (a choice button); the router then skips its guess.
    role: str | None = Field(default=None, min_length=1, max_length=40, pattern=r'^[a-z_]+$')
    # The review item the question is about (law artifact); the Law Agent is asked about it directly.
    clause: ClauseContext | None = None

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
