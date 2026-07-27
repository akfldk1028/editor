from __future__ import annotations

from dataclasses import dataclass, field

Point = tuple[float, float]


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
