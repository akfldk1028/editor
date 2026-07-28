from __future__ import annotations

from dataclasses import dataclass, field
import math

Point = tuple[float, float]


def _require_finite_points(points: tuple[Point, ...], *, label: str, minimum: int) -> None:
    if len(points) < minimum:
        raise ValueError(f"{label} needs at least {minimum} points")
    if not all(math.isfinite(value) for point in points for value in point):
        raise ValueError(f"{label} coordinates must be finite")


@dataclass(frozen=True)
class UsePlanningMetadata:
    reception_to_lobby_route_line_id: str | None = None
    support_room_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        route_id = self.reception_to_lobby_route_line_id
        if route_id is not None and (
            not isinstance(route_id, str) or not route_id.strip()
        ):
            raise TypeError(
                "reception_to_lobby_route_line_id must be a non-empty string or None"
            )
        if not isinstance(self.support_room_ids, tuple):
            raise TypeError("support_room_ids must be an immutable tuple")
        if any(
            not isinstance(room_id, str) or not room_id.strip()
            for room_id in self.support_room_ids
        ):
            raise TypeError("support_room_ids must contain non-empty strings")
        if len(set(self.support_room_ids)) != len(self.support_room_ids):
            raise ValueError("support_room_ids must be unique")


@dataclass(frozen=True)
class PlanElement:
    element_id: str
    category: str
    kind: str
    host_id: str
    label: str
    footprint: tuple[Point, ...]

    def __post_init__(self) -> None:
        _require_finite_points(self.footprint, label="element footprint", minimum=3)


@dataclass(frozen=True)
class PlanLine:
    line_id: str
    category: str
    kind: str
    points: tuple[Point, ...]
    host_id: str | None = None
    target_id: str | None = None
    label: str = ""
    measured_value: float | None = None
    clear_width: float | None = None

    def __post_init__(self) -> None:
        _require_finite_points(self.points, label="line", minimum=2)
        for name, value in (
            ("measured_value", self.measured_value),
            ("clear_width", self.clear_width),
        ):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} must be finite")


@dataclass(frozen=True)
class BasicDesignFeatures:
    elements: tuple[PlanElement, ...]
    lines: tuple[PlanLine, ...]
    policy_version: str = "concept-basic-v1"
    planning: UsePlanningMetadata | None = None

    def __post_init__(self) -> None:
        if self.planning is not None and not isinstance(
            self.planning,
            UsePlanningMetadata,
        ):
            raise TypeError("planning must be frozen UsePlanningMetadata or None")


@dataclass(frozen=True)
class OpeningSegment:
    opening_id: str
    kind: str
    connects: tuple[str, str]
    start: Point
    end: Point
    clear_width: float


@dataclass(frozen=True)
class RoomPolygon:
    room_id: str
    space_type: str
    polygon: list[Point]


@dataclass(frozen=True)
class LayoutCandidate:
    candidate_id: str
    project_id: str
    floor_index: int
    rooms: list[RoomPolygon]
    circulation: list[RoomPolygon]
    score: float
    openings: list[OpeningSegment] = field(default_factory=list)
    basic_design: BasicDesignFeatures | None = None
