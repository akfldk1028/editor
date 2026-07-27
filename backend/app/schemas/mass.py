from __future__ import annotations

from dataclasses import dataclass

Point = tuple[float, float]


@dataclass(frozen=True)
class MassInput:
    project_id: str
    floors: int
    footprint_polygon: list[Point]
    site_edges: list[dict]
    access_candidates: list[dict]
    use_mix: dict[str, float]


@dataclass(frozen=True)
class MassAnalysis:
    project_id: str
    area: float
    floor_area: float
    floors: int
    edge_count: int
    street_edge_indices: list[int]
    access_edge_indices: list[int]
    bounds: tuple[float, float, float, float]
