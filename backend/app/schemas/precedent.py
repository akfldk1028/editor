from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrecedentCase:
    case_id: str
    use_type: str
    gross_area: float
    floors: int
    tags: list[str]
    metrics: dict[str, float]


@dataclass(frozen=True)
class RankedPrecedent:
    case: PrecedentCase
    score: float
