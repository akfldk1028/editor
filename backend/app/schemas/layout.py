from __future__ import annotations

from dataclasses import dataclass

Point = tuple[float, float]


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
