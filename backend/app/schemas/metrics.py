from __future__ import annotations

from dataclasses import dataclass, field


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
class RoomShapeMetric:
    room_id: str
    measured_min_width: float | None
    required_min_width: float | None
    measured_aspect_ratio: float | None
    maximum_aspect_ratio: float | None
    minimum_width_passed: bool
    aspect_ratio_passed: bool


@dataclass(frozen=True)
class BasicDesignMetric:
    policy_version: str
    stair_count: int
    elevator_count: int
    lobby_count: int
    shaft_count: int
    exit_count: int
    route_count: int
    grid_line_count: int
    column_count: int
    window_count: int
    entrance_count: int
    furniture_count: int
    fixture_count: int
    dimension_count: int
    min_exit_width: float | None
    exit_separation: float | None
    min_routes_per_room: int
    missing_required_kinds: tuple[str, ...]
    min_object_clearance: float | None = None
    object_clearance_violation_count: int = 0
    policy_checks: dict[str, dict[str, bool | float | int | str | None]] = field(
        default_factory=dict
    )


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
    openings_checked: bool = False
    corridor_width_checked: bool = False
    room_shapes: list[RoomShapeMetric] = field(default_factory=list)
    basic_design_checked: bool = False
    basic_design: BasicDesignMetric | None = None
