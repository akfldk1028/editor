from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ProgramNode:
    node_id: str
    space_type: str
    target_area: float
    min_area: float | None = None
    max_area: float | None = None
    frontage_required: bool = False
    min_width: float | None = None
    max_aspect_ratio: float | None = None
    zone: str | None = None
    tenant_id: str | None = None


@dataclass(frozen=True)
class ProgramEdge:
    source: str
    target: str
    relation: str
    weight: float = 1.0


@dataclass(frozen=True)
class ProgramAdjustment:
    reason: str
    original_targets: tuple[tuple[str, float], ...]
    adjusted_targets: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("program adjustment reason must not be empty")
        original_ids = self._validated_ids("original", self.original_targets)
        adjusted_ids = self._validated_ids("adjusted", self.adjusted_targets)
        if original_ids != adjusted_ids:
            raise ValueError(
                "program adjustment original and adjusted node ids must match"
            )

    @staticmethod
    def _validated_ids(
        label: str,
        targets: tuple[tuple[str, float], ...],
    ) -> set[str]:
        ids: set[str] = set()
        for node_id, area in targets:
            if not node_id.strip():
                raise ValueError(
                    f"program adjustment {label} node id must not be empty"
                )
            if node_id in ids:
                raise ValueError(
                    f"program adjustment {label} node ids must be unique"
                )
            if not math.isfinite(area) or area < 0:
                raise ValueError(
                    f"program adjustment {label} areas must be finite and nonnegative"
                )
            ids.add(node_id)
        return ids


@dataclass(frozen=True)
class ProgramGraph:
    project_id: str
    floor_index: int
    use_type: str
    nodes: list[ProgramNode]
    edges: list[ProgramEdge]
    source: str
    adjustments: tuple[ProgramAdjustment, ...] = ()
