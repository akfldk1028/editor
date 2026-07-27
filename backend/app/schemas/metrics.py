from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationReport:
    is_valid: bool
    area_score: float
    overlap_score: float
    boundary_score: float
    circulation_score: float
    efficiency_score: float
    total_score: float
    messages: list[str]
