from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProgramNode:
    node_id: str
    space_type: str
    target_area: float
    min_area: float | None = None
    max_area: float | None = None
    frontage_required: bool = False


@dataclass(frozen=True)
class ProgramEdge:
    source: str
    target: str
    relation: str
    weight: float = 1.0


@dataclass(frozen=True)
class ProgramGraph:
    project_id: str
    floor_index: int
    use_type: str
    nodes: list[ProgramNode]
    edges: list[ProgramEdge]
    source: str
