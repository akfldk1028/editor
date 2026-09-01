from __future__ import annotations

from dataclasses import dataclass


Point = tuple[float, float]


@dataclass(frozen=True)
class CirculationCandidate:
    strategy: str
    polygons: tuple[tuple[Point, ...], ...]
    remote_stair_polygon: tuple[Point, ...]
    fingerprint: str
    entrance_connected: bool
    core_connected: bool
    stair_connected: bool
    core_fingerprint: str | None = None


class CirculationPlanningError(ValueError):
    """Raised when no connected circulation topology can be constructed."""
