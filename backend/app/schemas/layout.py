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
class StairFlight:
    flight_index: int
    footprint: tuple[Point, ...]
    direction: str
    riser_count: int
    tread_count: int
    start_elevation_m: float
    end_elevation_m: float

    def __post_init__(self) -> None:
        _require_finite_points(self.footprint, label="stair flight", minimum=3)
        if self.direction not in {"+x", "-x", "+y", "-y"}:
            raise ValueError("stair flight direction must be an axis direction")
        if self.riser_count < 1 or self.tread_count < 0:
            raise ValueError("stair flight counts must be non-negative")
        if not all(
            math.isfinite(value)
            for value in (self.start_elevation_m, self.end_elevation_m)
        ):
            raise ValueError("stair flight elevations must be finite")


@dataclass(frozen=True)
class StairLanding:
    landing_index: int
    role: str
    footprint: tuple[Point, ...]
    elevation_m: float

    def __post_init__(self) -> None:
        _require_finite_points(self.footprint, label="stair landing", minimum=3)
        if self.role not in {"floor_lower", "intermediate", "floor_upper"}:
            raise ValueError("stair landing role is invalid")
        if not math.isfinite(self.elevation_m):
            raise ValueError("stair landing elevation must be finite")


@dataclass(frozen=True)
class StairGeometry:
    floor_to_floor_height_m: float
    height_source: str
    clear_width_m: float
    riser_count: int
    riser_height_m: float
    tread_depth_m: float
    required_enclosure_width_m: float
    required_enclosure_length_m: float
    enclosure_footprint: tuple[Point, ...]
    flights: tuple[StairFlight, ...]
    landings: tuple[StairLanding, ...]
    headroom_m: float | None = None
    headroom_status: str = "not_checked"

    def __post_init__(self) -> None:
        _require_finite_points(
            self.enclosure_footprint,
            label="stair enclosure",
            minimum=3,
        )
        if self.height_source not in {"project-fact", "concept-default"}:
            raise ValueError("stair height source is invalid")
        if not isinstance(self.flights, tuple) or not all(
            isinstance(flight, StairFlight) for flight in self.flights
        ):
            raise TypeError("stair flights must be an immutable typed tuple")
        if not isinstance(self.landings, tuple) or not all(
            isinstance(landing, StairLanding) for landing in self.landings
        ):
            raise TypeError("stair landings must be an immutable typed tuple")
        values = (
            self.floor_to_floor_height_m,
            self.clear_width_m,
            self.riser_height_m,
            self.tread_depth_m,
            self.required_enclosure_width_m,
            self.required_enclosure_length_m,
        )
        if not all(math.isfinite(value) and value > 0 for value in values):
            raise ValueError("stair dimensions must be finite and positive")
        if self.riser_count < 1:
            raise ValueError("stair riser count must be positive")
        if self.headroom_m is not None and (
            not math.isfinite(self.headroom_m) or self.headroom_m <= 0
        ):
            raise ValueError("stair headroom must be finite and positive or None")
        if self.headroom_status not in {"checked", "not_checked"}:
            raise ValueError("stair headroom_status must be checked or not_checked")
        if (self.headroom_status == "checked") != (self.headroom_m is not None):
            raise ValueError("checked stair headroom requires a measured value")


@dataclass(frozen=True)
class DoorSwing:
    hinge: Point
    leaf_end: Point
    angle_degrees: float
    direction: str
    target_landing_role: str

    def __post_init__(self) -> None:
        _require_finite_points((self.hinge, self.leaf_end), label="door swing", minimum=2)
        if not math.isfinite(self.angle_degrees) or self.angle_degrees == 0:
            raise ValueError("door swing angle must be finite and non-zero")
        if self.direction not in {"clockwise", "counterclockwise"}:
            raise ValueError("door swing direction is invalid")
        if self.target_landing_role not in {"floor_lower", "floor_upper"}:
            raise ValueError("door swing must target a floor landing")


@dataclass(frozen=True)
class PlanElement:
    element_id: str
    category: str
    kind: str
    host_id: str
    label: str
    footprint: tuple[Point, ...]
    stair_geometry: StairGeometry | None = None

    def __post_init__(self) -> None:
        _require_finite_points(self.footprint, label="element footprint", minimum=3)
        if self.stair_geometry is not None and not isinstance(
            self.stair_geometry,
            StairGeometry,
        ):
            raise TypeError("stair_geometry must be StairGeometry or None")


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
    door_swing: DoorSwing | None = None

    def __post_init__(self) -> None:
        _require_finite_points(self.points, label="line", minimum=2)
        for name, value in (
            ("measured_value", self.measured_value),
            ("clear_width", self.clear_width),
        ):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.door_swing is not None and not isinstance(self.door_swing, DoorSwing):
            raise TypeError("door_swing must be DoorSwing or None")


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
    remote_stair_footprint: tuple[Point, ...] | None = None

    def __post_init__(self) -> None:
        if self.remote_stair_footprint is not None:
            _require_finite_points(
                self.remote_stair_footprint,
                label="remote stair footprint",
                minimum=3,
            )
