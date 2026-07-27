from __future__ import annotations

from dataclasses import dataclass


SUPPORTED_USE_TYPES = frozenset({"neighborhood_commercial", "office"})


@dataclass(frozen=True)
class FloorAssignment:
    floor_index: int
    use_type: str


@dataclass(frozen=True)
class BuildingFloorAssignments:
    project_id: str
    assignments: tuple[FloorAssignment, ...]


@dataclass(frozen=True)
class ProgramNodeProposal:
    node_id: str
    space_type: str
    target_area: float
    min_area: float | None = None
    max_area: float | None = None
    frontage_required: bool = False


@dataclass(frozen=True)
class ProgramEdgeProposal:
    source: str
    target: str
    relation: str
    weight: float = 1.0


@dataclass(frozen=True)
class ProgramGraphProposal:
    project_id: str
    floor_index: int
    use_type: str
    nodes: tuple[ProgramNodeProposal, ...]
    edges: tuple[ProgramEdgeProposal, ...]
