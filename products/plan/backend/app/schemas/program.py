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
    original_nodes: tuple[ProgramNode, ...]
    adjusted_nodes: tuple[ProgramNode, ...]
    original_targets: tuple[tuple[str, float], ...]
    adjusted_targets: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("program adjustment reason must not be empty")
        original_ids = self._validated_nodes("original", self.original_nodes)
        adjusted_ids = self._validated_nodes("adjusted", self.adjusted_nodes)
        if original_ids != adjusted_ids:
            raise ValueError(
                "program adjustment original and adjusted node ids must match"
            )
        if self.original_nodes == self.adjusted_nodes:
            raise ValueError("program adjustment must change at least one field")
        original_targets = self._validated_targets(
            "original",
            self.original_targets,
        )
        adjusted_targets = self._validated_targets(
            "adjusted",
            self.adjusted_targets,
        )
        if original_targets != {
            node.node_id: float(node.target_area)
            for node in self.original_nodes
        }:
            raise ValueError(
                "program adjustment original targets must match original nodes"
            )
        if adjusted_targets != {
            node.node_id: float(node.target_area)
            for node in self.adjusted_nodes
        }:
            raise ValueError(
                "program adjustment adjusted targets must match adjusted nodes"
            )

    @staticmethod
    def _validated_nodes(
        label: str,
        nodes: tuple[ProgramNode, ...],
    ) -> set[str]:
        if not isinstance(nodes, tuple):
            raise TypeError(f"program adjustment {label} nodes must be a tuple")
        ids: set[str] = set()
        for node in nodes:
            if not isinstance(node, ProgramNode):
                raise TypeError(
                    f"program adjustment {label} nodes must be ProgramNode records"
                )
            if not node.node_id.strip():
                raise ValueError(
                    f"program adjustment {label} node id must not be empty"
                )
            if node.node_id in ids:
                raise ValueError(
                    f"program adjustment {label} node ids must be unique"
                )
            for field_name in (
                "target_area",
                "min_area",
                "max_area",
                "min_width",
                "max_aspect_ratio",
            ):
                value = getattr(node, field_name)
                if value is not None and (
                    not math.isfinite(float(value)) or float(value) < 0
                ):
                    raise ValueError(
                        f"program adjustment {label} {field_name} "
                        "must be finite and nonnegative"
                    )
            ids.add(node.node_id)
        return ids

    @staticmethod
    def _validated_targets(
        label: str,
        targets: tuple[tuple[str, float], ...],
    ) -> dict[str, float]:
        if not isinstance(targets, tuple):
            raise TypeError(f"program adjustment {label} targets must be a tuple")
        values: dict[str, float] = {}
        for node_id, area in targets:
            if not node_id.strip() or node_id in values:
                raise ValueError(
                    f"program adjustment {label} target ids must be non-empty and unique"
                )
            if not math.isfinite(area) or area < 0:
                raise ValueError(
                    f"program adjustment {label} areas must be finite and nonnegative"
                )
            values[node_id] = float(area)
        return values


@dataclass(frozen=True)
class ProgramGraph:
    project_id: str
    floor_index: int
    use_type: str
    nodes: list[ProgramNode]
    edges: list[ProgramEdge]
    source: str
    adjustments: tuple[ProgramAdjustment, ...] = ()
