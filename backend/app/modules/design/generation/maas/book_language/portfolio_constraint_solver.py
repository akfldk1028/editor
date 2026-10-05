"""Small exact solver for the final, already hard-gated BOOK portfolio.

Generation and VLM review can produce at most a few dozen final candidates.
At that scale an exact branch-and-bound search is preferable to letting an
early greedy pick block several mutually compatible later candidates.  The
caller supplies typed cap keys and a measured pairwise compatibility matrix;
this module has no geometry, program or VLM authority of its own.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from backend.app.modules.design.generation.maas.book_language.competition_portfolio_contract import CompetitionPortfolioContract


@dataclass(frozen=True)
class ConstraintCandidateFacts:
    score: float
    cap_keys: tuple[str, ...]
    coverage_tags: tuple[str, ...] = ()
    visible_stepped: bool = False
    body_phenotype: str = ""
    roof_archetype: str = ""
    chassis_family: str = ""
    plan_family: str = ""
    base_scope: str = ""
    capacity_band: str = ""
    body_roof_signature: str = ""
    # Transitional aliases retained for callers that predate the unified
    # measured-field contract.
    scope: str = ""
    stepped: bool = False
    solid_phenotype: str = ""


def solve_maximum_compatible_subset(
    facts: list[ConstraintCandidateFacts],
    compatibility: list[list[bool]],
    *,
    target_count: int,
    maximum_key_counts: dict[str, int],
    required_coverage_tags: tuple[str, ...] = (),
) -> tuple[int, ...]:
    """Return a maximum-cardinality subset without relaxing any supplied cap."""
    count = len(facts)
    if count == 0 or target_count <= 0 or len(compatibility) != count:
        return ()
    if any(len(row) != count for row in compatibility):
        return ()

    order = sorted(
        range(count),
        key=lambda index: (
            -sum(not compatibility[index][other] for other in range(count) if other != index),
            facts[index].score,
        ),
        reverse=True,
    )
    required = set(required_coverage_tags)
    best_feasible: tuple[int, ...] = ()
    best_any: tuple[int, ...] = ()

    def quality(indices: tuple[int, ...]) -> tuple[int, int, float]:
        covered = {
            tag for index in indices for tag in facts[index].coverage_tags
        }
        return (
            len(indices),
            len(covered & required),
            sum(facts[index].score for index in indices),
        )

    def visit(
        position: int,
        chosen: tuple[int, ...],
        usage: Counter[str],
        covered: set[str],
    ) -> None:
        nonlocal best_any, best_feasible
        if quality(chosen) > quality(best_any):
            best_any = chosen
        if required.issubset(covered) and quality(chosen) > quality(best_feasible):
            best_feasible = chosen
        if position >= len(order) or len(chosen) >= target_count:
            return
        remaining = len(order) - position
        incumbent_count = max(len(best_feasible), len(best_any))
        if len(chosen) + remaining < incumbent_count:
            return

        candidate_index = order[position]
        candidate = facts[candidate_index]
        allowed = all(
            usage[key] < max(0, int(maximum_key_counts.get(key, target_count)))
            for key in candidate.cap_keys
        ) and all(compatibility[candidate_index][other] for other in chosen)
        if allowed:
            for key in candidate.cap_keys:
                usage[key] += 1
            visit(
                position + 1,
                (*chosen, candidate_index),
                usage,
                covered | set(candidate.coverage_tags),
            )
            for key in candidate.cap_keys:
                usage[key] -= 1
        visit(position + 1, chosen, usage, covered)

    visit(0, (), Counter(), set())
    # Cardinality is the hard objective promised by this solver. Coverage is
    # the next tie-breaker, not permission for a one-card coverage witness to
    # replace a larger legal compatible portfolio.
    winner = max((best_feasible, best_any), key=quality)
    return tuple(sorted(winner))


def solve_bounded_compatible_subset(
    facts: list[ConstraintCandidateFacts],
    compatibility: list[list[bool]],
    *,
    target_count: int,
    maximum_key_counts: dict[str, int],
    required_coverage_tags: tuple[str, ...] = (),
    beam_width: int = 512,
) -> tuple[int, ...]:
    """Beam-search a large hard-gated pool without exponential backtracking.

    Cardinality is ranked before required coverage and score. Low-conflict
    candidates with rare required coverage are visited first. Every retained
    state still satisfies the caller's exact pairwise compatibility matrix and
    typed cap counts.
    """

    count = len(facts)
    if count == 0 or target_count <= 0 or len(compatibility) != count:
        return ()
    if any(len(row) != count for row in compatibility):
        return ()
    required = set(required_coverage_tags)
    coverage_supply = Counter(
        tag for fact in facts for tag in fact.coverage_tags if tag in required
    )
    order = sorted(
        range(count),
        key=lambda index: (
            sum(
                not compatibility[index][other]
                for other in range(count)
                if other != index
            ),
            min(
                (coverage_supply[tag] for tag in facts[index].coverage_tags if tag in required),
                default=count + 1,
            ),
            -len(set(facts[index].coverage_tags) & required),
            -facts[index].score,
        ),
    )
    # chosen, usage, covered, score
    states: list[tuple[tuple[int, ...], Counter[str], frozenset[str], float]] = [
        ((), Counter(), frozenset(), 0.0)
    ]

    def rank(state: tuple[tuple[int, ...], Counter[str], frozenset[str], float]) -> tuple[int, int, float]:
        chosen, _usage, covered, score = state
        return len(chosen), len(covered & required), score

    for candidate_index in order:
        candidate = facts[candidate_index]
        expanded = list(states)
        for chosen, usage, covered, score in states:
            if len(chosen) >= target_count:
                continue
            if not all(
                usage[key] < max(0, int(maximum_key_counts.get(key, target_count)))
                for key in candidate.cap_keys
            ):
                continue
            if not all(compatibility[candidate_index][other] for other in chosen):
                continue
            next_usage = usage.copy()
            next_usage.update(candidate.cap_keys)
            expanded.append((
                (*chosen, candidate_index),
                next_usage,
                covered | frozenset(candidate.coverage_tags),
                score + float(candidate.score),
            ))
        states = sorted(expanded, key=rank, reverse=True)[:max(8, int(beam_width))]
        complete = [
            state for state in states
            if len(state[0]) >= target_count and required.issubset(state[2])
        ]
        if complete:
            return tuple(sorted(max(complete, key=rank)[0]))

    winner = max(states, key=rank)
    return tuple(sorted(winner[0]))


def solve_milp_compatible_subset(
    facts: list[ConstraintCandidateFacts],
    compatibility: list[list[bool]],
    *,
    target_count: int,
    maximum_key_counts: dict[str, int],
    required_coverage_tags: tuple[str, ...] = (),
    required_scopes: tuple[str, ...] = (),
    capacity_band_minimum_counts: dict[str, int] | None = None,
    capacity_band_maximum_counts: dict[str, int] | None = None,
    required_classified_capacity_count: int | None = None,
    minimum_stepped_count: int = 0,
    maximum_stepped_count: int | None = None,
    upper_band_stepped_bands: tuple[str, ...] = (),
    minimum_upper_band_stepped_count: int = 0,
    maximum_roof_archetype_count: int | None = None,
    maximum_solid_phenotype_count: int | None = None,
    portfolio_contract: CompetitionPortfolioContract | None = None,
    infeasibility_certificate: dict[str, object] | None = None,
    time_limit_seconds: float = 45.0,
) -> tuple[int, ...]:
    """Solve every supplied final-portfolio requirement in one MILP.

    Each candidate is one binary variable. Incompatible silhouettes become
    pair constraints; scopes, achieved-capacity bands, stepped morphology and
    repetition caps are rows in the same model. A completed result always has
    exactly ``target_count`` members. Infeasibility returns an empty tuple and
    populates ``infeasibility_certificate``; it never substitutes a
    cardinality-only portfolio.
    """

    if infeasibility_certificate is not None:
        infeasibility_certificate.clear()
    count = len(facts)
    if count == 0 or target_count <= 0 or len(compatibility) != count:
        if infeasibility_certificate is not None:
            infeasibility_certificate.update({
                "status": "infeasible",
                "maximum_achievable_cardinality": 0,
                "unsatisfied_constraints": [
                    f"selection_count:exact_{max(0, int(target_count))}",
                ],
            })
        return ()
    if any(len(row) != count for row in compatibility):
        if infeasibility_certificate is not None:
            infeasibility_certificate.update({
                "status": "invalid_compatibility_matrix",
                "maximum_achievable_cardinality": 0,
                "unsatisfied_constraints": ["compatibility_matrix:square"],
            })
        return ()
    try:
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import lil_matrix
    except ImportError:
        if infeasibility_certificate is not None:
            infeasibility_certificate.update({
                "status": "solver_unavailable",
                "maximum_achievable_cardinality": 0,
                "unsatisfied_constraints": ["scipy_milp:available"],
            })
        return ()

    capacity_band_exact_counts: dict[str, int] = {}
    base_scope_minimum_each = 0
    base_scope_maximum_each: int | None = None
    body_phenotype_minimum_distinct = 0
    roof_archetype_minimum_distinct = 0
    chassis_family_minimum_distinct = 0
    plan_family_minimum_distinct = 0
    body_roof_signature_minimum_distinct = 0
    maximum_chassis_family_count: int | None = None
    maximum_plan_family_count: int | None = None
    maximum_body_roof_signature_count: int | None = None
    if portfolio_contract is not None:
        if int(portfolio_contract.target_count) != int(target_count):
            if infeasibility_certificate is not None:
                infeasibility_certificate.update({
                    "status": "invalid_contract_target",
                    "target_count": int(target_count),
                    "unsatisfied_constraints": [
                        "portfolio_contract:target_count_match",
                    ],
                })
            return ()
        capacity_band_exact_counts = dict(
            portfolio_contract.capacity_band_exact_counts
        )
        capacity_band_minimum_counts = dict(
            portfolio_contract.capacity_band_minimum_counts
        )
        capacity_band_maximum_counts = dict(
            portfolio_contract.capacity_band_maximum_counts
        )
        if (
            capacity_band_exact_counts
            or capacity_band_minimum_counts
            or capacity_band_maximum_counts
        ):
            required_classified_capacity_count = int(target_count)
        required_scopes = portfolio_contract.base_scopes
        base_scope_minimum_each = (
            portfolio_contract.base_scope_minimum_each
        )
        base_scope_maximum_each = (
            portfolio_contract.base_scope_maximum_each
        )
        minimum_stepped_count = (
            portfolio_contract.visible_stepped_minimum
        )
        maximum_stepped_count = (
            portfolio_contract.visible_stepped_maximum
        )
        upper_band_stepped_bands = (
            portfolio_contract.upper_band_stepped_bands
        )
        minimum_upper_band_stepped_count = (
            portfolio_contract.upper_band_stepped_minimum
        )
        body_phenotype_minimum_distinct = (
            portfolio_contract.body_phenotype_minimum_distinct
        )
        maximum_solid_phenotype_count = (
            portfolio_contract.body_phenotype_maximum_each
        )
        roof_archetype_minimum_distinct = (
            portfolio_contract.roof_archetype_minimum_distinct
        )
        maximum_roof_archetype_count = (
            portfolio_contract.roof_archetype_maximum_each
        )
        chassis_family_minimum_distinct = (
            portfolio_contract.chassis_family_minimum_distinct
        )
        maximum_chassis_family_count = (
            portfolio_contract.chassis_family_maximum_each
        )
        plan_family_minimum_distinct = (
            portfolio_contract.plan_family_minimum_distinct
        )
        maximum_plan_family_count = (
            portfolio_contract.plan_family_maximum_each
        )
        body_roof_signature_minimum_distinct = (
            portfolio_contract.body_roof_signature_minimum_distinct
        )
        maximum_body_roof_signature_count = (
            portfolio_contract.body_roof_signature_maximum_each
        )

    # name, coefficients, lower, upper. Names are stable evidence keys used by
    # the selector and benchmark when no completed board exists.
    rows: list[tuple[str, dict[int, float], float, float]] = []
    variable_count = count
    exact_count_name = f"selection_count:exact_{int(target_count)}"
    rows.append((
        exact_count_name,
        {index: 1.0 for index in range(count)},
        float(target_count),
        float(target_count),
    ))
    for left in range(count):
        for right in range(left + 1, count):
            if not compatibility[left][right]:
                rows.append((
                    f"silhouette_incompatibility:{left}:{right}",
                    {left: 1.0, right: 1.0},
                    0.0,
                    1.0,
                ))
    candidates_by_key: dict[str, list[int]] = {}
    for index, fact in enumerate(facts):
        for key in fact.cap_keys:
            candidates_by_key.setdefault(key, []).append(index)
    for key, indices in sorted(candidates_by_key.items()):
        rows.append((
            f"typed_cap:{key}:max_{max(0, int(maximum_key_counts.get(key, target_count)))}",
            {index: 1.0 for index in indices},
            0.0,
            float(max(0, int(maximum_key_counts.get(key, target_count)))),
        ))

    for tag in dict.fromkeys(required_coverage_tags):
        indices = [
            index for index, fact in enumerate(facts)
            if tag in fact.coverage_tags
        ]
        rows.append((
            f"coverage:{tag}:min_1",
            {index: 1.0 for index in indices},
            1.0,
            np.inf,
        ))
    for scope in dict.fromkeys(required_scopes):
        indices = [
            index for index, fact in enumerate(facts)
            if (fact.base_scope or fact.scope) == scope
        ]
        minimum = max(1, int(base_scope_minimum_each))
        rows.append((
            f"scope:{scope}:min_{minimum}",
            {index: 1.0 for index in indices},
            float(minimum),
            np.inf,
        ))
        if base_scope_maximum_each is not None:
            maximum = max(0, int(base_scope_maximum_each))
            rows.append((
                f"scope:{scope}:max_{maximum}",
                {index: 1.0 for index in indices},
                0.0,
                float(maximum),
            ))

    minimum_band_counts = capacity_band_minimum_counts or {}
    maximum_band_counts = capacity_band_maximum_counts or {}
    exact_band_counts = capacity_band_exact_counts
    for band in sorted(
        set(exact_band_counts)
        | set(minimum_band_counts)
        | set(maximum_band_counts)
    ):
        indices = [
            index for index, fact in enumerate(facts)
            if fact.capacity_band == band
        ]
        if band in exact_band_counts:
            exact = max(0, int(exact_band_counts[band]))
            rows.append((
                f"capacity_band:{band}:exact_{exact}",
                {index: 1.0 for index in indices},
                float(exact),
                float(exact),
            ))
        if band in minimum_band_counts:
            minimum = max(0, int(minimum_band_counts[band]))
            rows.append((
                f"capacity_band:{band}:min_{minimum}",
                {index: 1.0 for index in indices},
                float(minimum),
                np.inf,
            ))
        if band in maximum_band_counts:
            maximum = max(0, int(maximum_band_counts[band]))
            rows.append((
                f"capacity_band:{band}:max_{maximum}",
                {index: 1.0 for index in indices},
                0.0,
                float(maximum),
            ))
    if required_classified_capacity_count is not None:
        required_classified = max(
            0,
            int(required_classified_capacity_count),
        )
        classified_bands = (
            set(exact_band_counts)
            | set(minimum_band_counts)
            | set(maximum_band_counts)
        )
        classified_indices = [
            index for index, fact in enumerate(facts)
            if fact.capacity_band in classified_bands
        ]
        rows.append((
            f"capacity_band:classified_exact_{required_classified}",
            {index: 1.0 for index in classified_indices},
            float(required_classified),
            float(required_classified),
        ))

    stepped_indices = [
        index
        for index, fact in enumerate(facts)
        if fact.visible_stepped or fact.stepped
    ]
    stepped_row_name = (
        "visible_stepped"
        if portfolio_contract is not None
        else "stepped"
    )
    if minimum_stepped_count > 0:
        minimum = max(0, int(minimum_stepped_count))
        rows.append((
            f"{stepped_row_name}:min_{minimum}",
            {index: 1.0 for index in stepped_indices},
            float(minimum),
            np.inf,
        ))
    if maximum_stepped_count is not None:
        maximum = max(0, int(maximum_stepped_count))
        rows.append((
            f"{stepped_row_name}:max_{maximum}",
            {index: 1.0 for index in stepped_indices},
            0.0,
            float(maximum),
        ))

    if minimum_upper_band_stepped_count > 0:
        upper_bands = set(upper_band_stepped_bands)
        upper_stepped_indices = [
            index for index, fact in enumerate(facts)
            if (
                fact.visible_stepped or fact.stepped
            ) and fact.capacity_band in upper_bands
        ]
        minimum = max(0, int(minimum_upper_band_stepped_count))
        rows.append((
            f"upper_band_stepped:min_{minimum}",
            {index: 1.0 for index in upper_stepped_indices},
            float(minimum),
            np.inf,
        ))

    def add_distinct_category_rows(
        name: str,
        values: list[str],
        *,
        minimum_distinct: int,
        maximum_each: int | None,
    ) -> None:
        nonlocal variable_count
        categories = sorted({value for value in values if value})
        if maximum_each is not None:
            maximum = max(0, int(maximum_each))
            for category in categories:
                indices = [
                    index for index, value in enumerate(values)
                    if value == category
                ]
                rows.append((
                    f"{name}:{category}:max_{maximum}",
                    {index: 1.0 for index in indices},
                    0.0,
                    float(maximum),
                ))
        minimum = max(0, int(minimum_distinct))
        if minimum == 0:
            return
        indicator_indices: list[int] = []
        for category in categories:
            indices = [
                index for index, value in enumerate(values)
                if value == category
            ]
            indicator = variable_count
            variable_count += 1
            indicator_indices.append(indicator)
            rows.append((
                f"{name}:{category}:indicator_upper",
                {
                    **{index: 1.0 for index in indices},
                    indicator: -float(len(indices)),
                },
                -np.inf,
                0.0,
            ))
            rows.append((
                f"{name}:{category}:indicator_lower",
                {
                    indicator: 1.0,
                    **{index: -1.0 for index in indices},
                },
                -np.inf,
                0.0,
            ))
        rows.append((
            f"{name}:distinct_min_{minimum}",
            {index: 1.0 for index in indicator_indices},
            float(minimum),
            np.inf,
        ))

    add_distinct_category_rows(
        (
            "body_phenotype"
            if portfolio_contract is not None
            else "solid_phenotype"
        ),
        [fact.body_phenotype or fact.solid_phenotype for fact in facts],
        minimum_distinct=body_phenotype_minimum_distinct,
        maximum_each=maximum_solid_phenotype_count,
    )
    add_distinct_category_rows(
        (
            "roof_archetype"
            if portfolio_contract is not None
            else "roof"
        ),
        [fact.roof_archetype for fact in facts],
        minimum_distinct=roof_archetype_minimum_distinct,
        maximum_each=maximum_roof_archetype_count,
    )
    add_distinct_category_rows(
        "chassis_family",
        [fact.chassis_family for fact in facts],
        minimum_distinct=chassis_family_minimum_distinct,
        maximum_each=maximum_chassis_family_count,
    )
    add_distinct_category_rows(
        "plan_family",
        [fact.plan_family for fact in facts],
        minimum_distinct=plan_family_minimum_distinct,
        maximum_each=maximum_plan_family_count,
    )
    add_distinct_category_rows(
        "body_roof_signature",
        [fact.body_roof_signature for fact in facts],
        minimum_distinct=body_roof_signature_minimum_distinct,
        maximum_each=maximum_body_roof_signature_count,
    )

    scores = np.asarray([float(fact.score) for fact in facts], dtype=float)
    if scores.size and float(np.max(scores) - np.min(scores)) > 1e-12:
        scores = (scores - np.min(scores)) / (np.max(scores) - np.min(scores))
    objective = np.zeros(variable_count, dtype=float)
    objective[:count] = -(
        np.ones(count, dtype=float) + scores * 1e-4
    )

    def run_solver(
        active_rows: list[tuple[str, dict[int, float], float, float]],
    ):
        matrix = lil_matrix(
            (len(active_rows), variable_count),
            dtype=float,
        )
        lower = np.empty(len(active_rows), dtype=float)
        upper = np.empty(len(active_rows), dtype=float)
        for row_index, (_name, coefficients, low, high) in enumerate(active_rows):
            for candidate_index, value in coefficients.items():
                matrix[row_index, candidate_index] = value
            lower[row_index] = low
            upper[row_index] = high
        return milp(
            c=objective,
            integrality=np.ones(variable_count, dtype=int),
            bounds=Bounds(
                np.zeros(variable_count),
                np.ones(variable_count),
            ),
            constraints=LinearConstraint(matrix.tocsr(), lower, upper),
            options={
                "time_limit": max(1.0, float(time_limit_seconds)),
                "presolve": True,
            },
        )

    def solver_status_name(result: object) -> str:
        return {
            0: "optimal",
            1: "limit_reached",
            2: "infeasible",
            3: "unbounded",
            4: "solver_error",
        }.get(int(getattr(result, "status", -1)), "unknown")

    def selected_indices(result: object) -> tuple[int, ...]:
        values = getattr(result, "x", None)
        if values is None:
            return ()
        return tuple(
            index
            for index, value in enumerate(values[:count])
            if value >= 0.5
        )

    def satisfies(
        result: object,
        active_rows: list[
            tuple[str, dict[int, float], float, float]
        ],
    ) -> bool:
        values = getattr(result, "x", None)
        if values is None:
            return False
        return all(
            low - 1e-7
            <= sum(
                coefficient * float(values[index])
                for index, coefficient in coefficients.items()
            )
            <= high + 1e-7
            for _name, coefficients, low, high in active_rows
        )

    result = run_solver(rows)
    selected = selected_indices(result)
    # A time-limited incumbent that satisfies every row is already a valid
    # completed board; optimal score proof is not required for feasibility.
    if len(selected) == target_count and satisfies(result, rows):
        return selected
    exact_status = solver_status_name(result)
    if exact_status != "infeasible":
        if infeasibility_certificate is not None:
            infeasibility_certificate.update({
                "schema_version": (
                    "arr.maas.portfolio_infeasibility.v1"
                ),
                "status": "solver_not_proven",
                "target_count": int(target_count),
                "solver_status": exact_status,
                "solver_message": str(
                    getattr(result, "message", "")
                ),
            })
        return ()

    # Diagnose, but do not complete, an infeasible portfolio. Keep all hard
    # upper bounds and incompatibility edges, relax exact/lower bounds, and
    # maximize cardinality to state how close the candidate universe can get.
    diagnostic_rows = [
        row for row in rows
        if (
            row[0] != exact_count_name
            and row[2] <= 0.0
        )
    ]
    diagnostic_rows.append((
        f"selection_count:max_{int(target_count)}",
        {index: 1.0 for index in range(count)},
        0.0,
        float(target_count),
    ))
    diagnostic_result = run_solver(diagnostic_rows)
    diagnostic_selected = selected_indices(diagnostic_result)
    diagnostic_status = solver_status_name(diagnostic_result)
    unsatisfied: list[str] = []
    diagnostic_values = getattr(diagnostic_result, "x", None)
    for name, coefficients, low, high in rows:
        value = sum(
            coefficient * (
                float(diagnostic_values[index])
                if diagnostic_values is not None
                else 0.0
            )
            for index, coefficient in coefficients.items()
        )
        if value + 1e-7 < low or value - 1e-7 > high:
            unsatisfied.append(name)
            continue
        # If an upper row excludes supplied candidates and prevents reaching
        # exact cardinality, retain its name in the diagnosis even though the
        # relaxed incumbent necessarily obeys it.
        if (
            len(diagnostic_selected) < target_count
            and high < np.inf
            and sum(coefficients.values()) > high + 1e-7
            and name != exact_count_name
        ):
            unsatisfied.append(name)
    if exact_count_name not in unsatisfied:
        unsatisfied.insert(0, exact_count_name)
    if infeasibility_certificate is not None:
        certificate: dict[str, object] = {
            "schema_version": "arr.maas.portfolio_infeasibility.v1",
            "status": "infeasible",
            "target_count": int(target_count),
            "unsatisfied_constraints": list(dict.fromkeys(unsatisfied)),
            "diagnostic_solver_status": diagnostic_status,
            "solver_message": str(
                getattr(result, "message", "joint MILP infeasible")
            ),
        }
        if (
            diagnostic_status == "optimal"
            and bool(getattr(diagnostic_result, "success", False))
        ):
            certificate["maximum_achievable_cardinality"] = len(
                diagnostic_selected
            )
            certificate["maximum_cardinality_proven"] = True
        else:
            certificate["diagnostic_incumbent_cardinality"] = len(
                diagnostic_selected
            )
            certificate["maximum_cardinality_proven"] = False
        infeasibility_certificate.update(certificate)
    return ()


__all__ = [
    "ConstraintCandidateFacts",
    "solve_bounded_compatible_subset",
    "solve_milp_compatible_subset",
    "solve_maximum_compatible_subset",
]
