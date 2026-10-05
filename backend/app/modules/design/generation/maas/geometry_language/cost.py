"""Canonical program cost and solid equivalence for candidate selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult


@dataclass(frozen=True)
class ProgramCost:
    node_count: float
    tree_depth_penalty: float
    boolean_penalty: float
    deformation_penalty: float
    topology_complexity: float
    unstable_operation_penalty: float
    invalid_geometry_penalty: float

    @property
    def total(self) -> float:
        return round(
            self.node_count
            + self.tree_depth_penalty
            + self.boolean_penalty
            + self.deformation_penalty
            + self.topology_complexity
            + self.unstable_operation_penalty
            + self.invalid_geometry_penalty,
            6,
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "node_count": self.node_count,
            "tree_depth_penalty": self.tree_depth_penalty,
            "boolean_penalty": self.boolean_penalty,
            "deformation_penalty": self.deformation_penalty,
            "topology_complexity": self.topology_complexity,
            "unstable_operation_penalty": self.unstable_operation_penalty,
            "invalid_geometry_penalty": self.invalid_geometry_penalty,
            "total": self.total,
        }


def program_cost(program: GeometryProgram, compilation: CompilationResult | None = None) -> ProgramCost:
    """Prefer short, robust programs without suppressing meaningful form edits."""
    nodes = program.topological_nodes()
    boolean_count = sum(node.kind == "boolean" for node in nodes)
    deformation_count = sum(node.operator in {"bend", "taper", "twist", "shear"} for node in nodes)
    unstable_count = sum(
        node.operator in {"difference", "intersection", "bend", "twist", "loft"}
        for node in nodes
    )
    triangle_count = int((compilation.metrics if compilation else {}).get("triangle_count") or 0)
    component_count = int((compilation.metrics if compilation else {}).get("component_count") or 1)
    invalid = compilation is not None and compilation.status != "compiled"
    node_map = program.node_map
    depth_cache: dict[str, int] = {}

    def depth(node_id: str) -> int:
        if node_id not in depth_cache:
            inputs = node_map[node_id].inputs
            depth_cache[node_id] = 1 + max((depth(value) for value in inputs), default=0)
        return depth_cache[node_id]

    tree_depth = depth(program.root_id)
    return ProgramCost(
        node_count=float(len(nodes)),
        tree_depth_penalty=round(max(0, tree_depth - 3) * 0.35, 6),
        boolean_penalty=1.75 * boolean_count,
        deformation_penalty=0.8 * deformation_count,
        topology_complexity=round(triangle_count / 4000.0 + max(0, component_count - 1) * 2.0, 6),
        unstable_operation_penalty=0.55 * unstable_count,
        invalid_geometry_penalty=1_000_000.0 if invalid else 0.0,
    )


def geometry_equivalent(
    left: CompilationResult,
    right: CompilationResult,
    *,
    absolute_volume_tolerance: float = 1e-6,
    relative_volume_tolerance: float = 1e-7,
) -> bool:
    """Test solid equivalence, independent of triangulation and AST spelling."""
    if left.status != "compiled" or right.status != "compiled":
        return False
    if left.geometry_hash == right.geometry_hash:
        return True
    if left._solid is None or right._solid is None:
        return False
    scale = max(float(left.metrics.get("volume") or 0.0), float(right.metrics.get("volume") or 0.0), 1.0)
    tolerance = max(absolute_volume_tolerance, relative_volume_tolerance * scale)
    try:
        residual = float((left._solid - right._solid).volume()) + float((right._solid - left._solid).volume())
    except Exception:
        return False
    return residual <= tolerance


def candidate_sort_key(program: GeometryProgram, compilation: CompilationResult) -> tuple[Any, ...]:
    cost = program_cost(program, compilation)
    return (cost.total, program.canonical_structure_hash(), compilation.geometry_hash)


__all__ = ["ProgramCost", "candidate_sort_key", "geometry_equivalent", "program_cost"]
