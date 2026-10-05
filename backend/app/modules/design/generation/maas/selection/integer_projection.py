"""Exact 0-1 projection for the final MAAS review set."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from backend.app.modules.design.generation.maas.selection.visual_similarity import duplicate_conflict_pairs


Feature = dict[str, Any]


@dataclass(frozen=True)
class ProjectionDescriptor:
    feature: Feature
    cost: float
    family: str
    language: str
    formal_principle: str
    role_pattern: str
    island: str
    height_band: str
    direct_llm: bool
    vlm_scored: bool
    weak_llm: bool
    reference_ids: tuple[str, ...] = ()
    concept_vector: tuple[float, ...] = ()
    visual_vector: tuple[float, ...] = ()


def solve_final_integer_projection(
    descriptors: list[ProjectionDescriptor],
    *,
    final_count: int = 20,
    min_family_count: int = 15,
    min_direct_llm: int = 16,
    min_vlm_scored: int = 14,
    max_language_repeat: int = 2,
    max_role_repeat: int = 2,
    max_formal_repeat: int = 4,
    max_height_repeat: int = 12,
    max_weak_llm: int = 1,
    max_pairwise_similarity: float = 0.82,
    island_minimums: dict[str, int] | None = None,
) -> tuple[list[Feature], dict[str, Any]]:
    if len(descriptors) < final_count:
        return [], {"status": "insufficient_pool", "pool_count": len(descriptors)}
    island_minimums = island_minimums or {"additive": 4, "subtractive": 4, "hybrid": 4, "sectional": 4}
    families = sorted({item.family for item in descriptors if item.family})
    family_index = {family: len(descriptors) + index for index, family in enumerate(families)}
    variable_count = len(descriptors) + len(families)
    rows: list[tuple[dict[int, float], float, float]] = []

    def add(coefficients: dict[int, float], lower: float = -np.inf, upper: float = np.inf) -> None:
        rows.append((coefficients, lower, upper))

    add({i: 1.0 for i in range(len(descriptors))}, final_count, final_count)
    add({i: 1.0 for i, item in enumerate(descriptors) if item.direct_llm}, min_direct_llm, np.inf)
    add({i: 1.0 for i, item in enumerate(descriptors) if item.vlm_scored}, min_vlm_scored, np.inf)
    add({i: 1.0 for i, item in enumerate(descriptors) if item.weak_llm}, -np.inf, max_weak_llm)

    def cap_by(attribute: str, maximum: int) -> None:
        values = sorted({getattr(item, attribute) for item in descriptors if getattr(item, attribute)})
        for value in values:
            add({i: 1.0 for i, item in enumerate(descriptors) if getattr(item, attribute) == value}, -np.inf, maximum)

    cap_by("language", max_language_repeat)
    cap_by("role_pattern", max_role_repeat)
    cap_by("formal_principle", max_formal_repeat)
    cap_by("height_band", max_height_repeat)
    for island, minimum in island_minimums.items():
        add({i: 1.0 for i, item in enumerate(descriptors) if item.island == island}, minimum, np.inf)
    conflict_pairs = duplicate_conflict_pairs(descriptors, threshold=max_pairwise_similarity)
    for left_index, right_index, _ in conflict_pairs:
        add({left_index: 1.0, right_index: 1.0}, -np.inf, 1.0)

    for family, y_index in family_index.items():
        member_indexes = [i for i, item in enumerate(descriptors) if item.family == family]
        add({y_index: 1.0, **{i: -1.0 for i in member_indexes}}, -np.inf, 0.0)
        for index in member_indexes:
            add({index: 1.0, y_index: -1.0}, -np.inf, 0.0)
    add({index: 1.0 for index in family_index.values()}, min_family_count, np.inf)

    matrix = lil_matrix((len(rows), variable_count), dtype=float)
    lower = np.empty(len(rows), dtype=float)
    upper = np.empty(len(rows), dtype=float)
    for row_index, (coefficients, row_lower, row_upper) in enumerate(rows):
        for column, value in coefficients.items():
            matrix[row_index, column] = value
        lower[row_index] = row_lower
        upper[row_index] = row_upper
    objective = np.zeros(variable_count, dtype=float)
    objective[: len(descriptors)] = [item.cost for item in descriptors]
    # Diversity is primarily an optimization objective, not a reason to make
    # an otherwise legal/clean/VLM-scored review set mathematically impossible.
    # Reward each represented family while hard duplicate constraints retain
    # the actual anti-collapse guarantee.
    for y_index in family_index.values():
        objective[y_index] = -0.12
    result = milp(
        c=objective,
        integrality=np.ones(variable_count, dtype=int),
        bounds=Bounds(np.zeros(variable_count), np.ones(variable_count)),
        constraints=LinearConstraint(matrix.tocsr(), lower, upper),
        options={"time_limit": 30.0, "mip_rel_gap": 0.0},
    )
    if not result.success or result.x is None:
        return [], {
            "status": "infeasible_or_timeout",
            "solver_status": int(result.status),
            "message": str(result.message),
            "pool_count": len(descriptors),
        }
    selected = [item.feature for index, item in enumerate(descriptors) if result.x[index] >= 0.5]
    return selected, {
        "schema_version": "arr.maas.final_integer_projection.v1",
        "status": "optimal" if result.status == 0 else "feasible",
        "pool_count": len(descriptors),
        "selected_count": len(selected),
        "objective": round(float(result.fun), 6),
        "max_formal_repeat": max_formal_repeat,
        "pairwise_duplicate_conflict_count": len(conflict_pairs),
        "max_pairwise_similarity": max_pairwise_similarity,
        "solver": "scipy.optimize.milp_highs",
    }


__all__ = ["ProjectionDescriptor", "solve_final_integer_projection"]
