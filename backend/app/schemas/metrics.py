from __future__ import annotations

from dataclasses import dataclass, field
import math

from backend.app.schemas.regulatory import RegulatoryScreening

PolicyValue = bool | float | int | str | None
_UNSET = object()


class _ImmutableJsonDict(dict):
    def _immutable(self, *args, **kwargs):
        raise TypeError(f"{type(self).__name__} is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


class PolicyCheck(_ImmutableJsonDict):
    def __init__(
        self,
        value=_UNSET,
        threshold=_UNSET,
        passed=_UNSET,
        reason=_UNSET,
    ) -> None:
        if (
            threshold is _UNSET
            and passed is _UNSET
            and reason is _UNSET
            and value is not _UNSET
        ):
            values = dict(value)
            if set(values) != {"value", "threshold", "pass", "reason"}:
                raise TypeError("PolicyCheck requires the exact policy-check fields")
        else:
            values = {
                "value": value,
                "threshold": threshold,
                "pass": passed,
                "reason": reason,
            }
        if not _is_json_policy_value(values["value"]) or not _is_json_policy_value(
            values["threshold"]
        ):
            raise TypeError("PolicyCheck values must be finite JSON scalar values")
        if not isinstance(values["pass"], bool):
            raise TypeError("PolicyCheck passed value must be bool")
        if not isinstance(values["reason"], str) or not values["reason"]:
            raise TypeError("PolicyCheck reason must be a non-empty string")
        dict.__init__(self, values)


class UsePlanningMetrics(_ImmutableJsonDict):
    def __init__(self, checks=None) -> None:
        values = dict(() if checks is None else checks)
        if any(
            not isinstance(name, str)
            or not name
            or not isinstance(check, PolicyCheck)
            for name, check in values.items()
        ):
            raise TypeError(
                "UsePlanningMetrics requires named immutable PolicyCheck values"
            )
        dict.__init__(self, values)


def _is_json_policy_value(value) -> bool:
    return (
        value is None
        or isinstance(value, (bool, int, str))
        or isinstance(value, float)
        and math.isfinite(value)
    )


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
    modeled_stair_count: int = 0
    min_riser_height: float | None = None
    max_riser_height: float | None = None
    min_tread_depth: float | None = None
    min_stair_clear_width: float | None = None
    min_landing_depth: float | None = None
    stair_height_sources: tuple[str, ...] = ()
    stair_headroom_statuses: tuple[str, ...] = ()
    min_object_clearance: float | None = None
    object_clearance_violation_count: int = 0
    policy_checks: UsePlanningMetrics = field(
        default_factory=UsePlanningMetrics
    )

    def __post_init__(self) -> None:
        if not isinstance(self.policy_checks, UsePlanningMetrics):
            raise TypeError("policy_checks must be immutable UsePlanningMetrics")


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
    regulatory_screening: RegulatoryScreening | None = None
