from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationViolation:
    code: str
    subject: str
    message: str


@dataclass(frozen=True)
class RoomAreaMetric:
    room_id: str
    target_area: float
    actual_area: float
    min_area: float
    max_area: float
    within_range: bool


@dataclass(frozen=True)
class ValidationReport:
    is_valid: bool
    accepted: bool
    hard_violation_count: int
    violation_score: float
    violations: list[ValidationViolation]
    room_areas: list[RoomAreaMetric]
    area_score: float
    overlap_score: float
    boundary_score: float
    circulation_score: float
    efficiency_score: float
    adjacency_score: float
    frontage_score: float
    coverage_score: float
    compactness_score: float
    total_score: float
    messages: list[str]
    policy_version: str
