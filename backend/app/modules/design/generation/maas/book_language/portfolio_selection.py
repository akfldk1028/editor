"""Constraint-aware selection for measured BOOK candidates."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Any

from backend.app.modules.design.generation.maas.book_language.candidate_analysis import _Candidate, _chassis_family, _capacity_alternative_key, _requested_capacity_alternative_key, _capacity_target_gate, _design_concept_descriptor, _distance, _fingerprint, _geometry_program_family, _plan_family, _roof_archetype, _portfolio_diversity_key, _scope_key, _section_family, _seed_family, _silhouette_distance, _solid_morphology_metrics
from backend.app.modules.design.generation.maas.book_language.compatibility_analysis import CompatibilityAnalysis
from backend.app.modules.design.generation.maas.book_language.competition_portfolio_contract import competition_portfolio_contract
from backend.app.modules.design.generation.maas.book_language.semantics import BASE_VOLUME_FRACTIONS
from backend.app.modules.design.generation.maas.book_language.portfolio_constraint_solver import ConstraintCandidateFacts, solve_bounded_compatible_subset, solve_milp_compatible_subset, solve_maximum_compatible_subset
from backend.app.modules.design.generation.maas.book_language.quality_diversity_archive import map_elites_archive, qd_archive_policy
from backend.app.modules.design.generation.maas.book_language.diversity_contract import certified_mesh_cluster_key
from backend.app.modules.design.generation.maas.book_language.run_budget import progressive_mass_run_budget
from backend.app.modules.design.generation.maas.program_massing.morphology import DEFAULT_NOVELTY_POLICY


def _solve_cardinality_fallback(
    facts: list[ConstraintCandidateFacts],
    compatibility: list[list[bool]],
    *,
    target_count: int,
    maximum_key_counts: dict[str, int],
    required_coverage_tags: tuple[str, ...] = (),
) -> tuple[int, ...]:
    """Keep diagnostic cardinality recovery bounded for large pools."""

    solver = (
        solve_maximum_compatible_subset
        if len(facts) <= 24
        else solve_bounded_compatible_subset
    )
    return solver(
        facts,
        compatibility,
        target_count=target_count,
        maximum_key_counts=maximum_key_counts,
        required_coverage_tags=required_coverage_tags,
    )


PORTFOLIO_SILHOUETTE_DISTANCE = (
    DEFAULT_NOVELTY_POLICY.visual_silhouette_repeat
)
ANCHOR_BRANCH_LIMIT = 8
ANCHOR_SEARCH_STATE_LIMIT = 20_000


def build_compatibility_analysis(
    candidates: list[Any],
    *,
    threshold: float | None = None,
    target_count: int | None = None,
    distance_evaluator: Any | None = None,
) -> CompatibilityAnalysis:
    if threshold is not None and target_count is not None:
        raise ValueError("threshold and target_count are mutually exclusive")
    resolved_threshold = (
        competition_portfolio_contract(target_count).minimum_pair_distance
        if target_count is not None
        else (
            PORTFOLIO_SILHOUETTE_DISTANCE
            if threshold is None
            else float(threshold)
        )
    )
    return CompatibilityAnalysis(
        candidates,
        threshold=resolved_threshold,
        distance_evaluator=distance_evaluator or _silhouette_distance,
    )


def build_gestalt_compatibility_analysis(
    candidates: list[Any],
    *,
    target_count: int,
) -> CompatibilityAnalysis:
    """Build the selector graph with the final gestalt distance formula."""

    return build_compatibility_analysis(
        candidates,
        target_count=target_count,
        distance_evaluator=_distance,
    )


def _chassis_caps(
    chassis_families: set[str],
    *,
    target: int,
    directive: dict[str, Any],
) -> dict[str, int]:
    """Resolve portfolio caps per measured chassis family.

    Board feedback is family-specific. A repeated courtyard must not reduce
    the available count for split-wing, lifted-spine, or any other unrelated
    chassis. ``max_chassis_family_count`` remains an explicit legacy/global
    fallback; typed ``max_chassis_family_counts`` entries take precedence.
    """
    default = max(
        1,
        min(
            target,
            int(directive.get("max_chassis_family_count") or (
                target
                if len(chassis_families) <= 1
                else max(4, target // max(1, len(chassis_families)) + 2)
            )),
        ),
    )
    caps = {family: default for family in chassis_families}
    for family, value in (directive.get("max_chassis_family_counts") or {}).items():
        family = str(family)
        if family in caps:
            caps[family] = max(1, min(target, int(value)))
    return caps


def _capacity_portfolio_quotas(
    candidates: list[_Candidate],
    *,
    target: int,
) -> dict[str, int]:
    """Distribute board slots across measured capacity bands.

    Supply-limited bands keep every valid candidate; the remaining slots are
    divided deterministically across the other bands with the higher-yield
    alternatives receiving the remainder first.  This prevents an easy
    spatial-reserve target from filling most of a board while still allowing
    the selector to reach its requested size when one band is genuinely rare.
    """
    priority = (
        "maximum_feasible", "brief_target", "balanced_yield", "spatial_reserve",
    )
    supply = Counter(
        _capacity_alternative_key(candidate)
        for candidate in candidates
        if _capacity_alternative_key(candidate)
    )
    active = [alternative for alternative in priority if supply.get(alternative, 0)]
    if not active or target <= 0:
        return {}
    quotas: dict[str, int] = {}
    remaining = min(int(target), sum(supply[alternative] for alternative in active))
    unresolved = list(active)
    while unresolved:
        even_share = (remaining + len(unresolved) - 1) // len(unresolved)
        supply_limited = [
            alternative for alternative in unresolved
            if supply[alternative] <= even_share
        ]
        if not supply_limited:
            base, extra = divmod(remaining, len(unresolved))
            for index, alternative in enumerate(unresolved):
                quotas[alternative] = min(
                    supply[alternative],
                    base + (1 if index < extra else 0),
                )
            break
        for alternative in supply_limited:
            quotas[alternative] = supply[alternative]
            remaining -= supply[alternative]
            unresolved.remove(alternative)
        if remaining <= 0:
            for alternative in unresolved:
                quotas[alternative] = 0
            break
    return quotas


def _scope_coverage_anchors(
    candidates: list[_Candidate],
    *,
    seed_family_cap: int,
    section_family_cap: int,
    roof_archetype_caps: dict[str, int],
    chassis_family_caps: dict[str, int],
    phenotype_cap: int,
    wedge_like_cap: int,
    pyramidal_like_cap: int,
    required_phenotypes: tuple[str, ...] = (),
    required_principle_kinds: tuple[str, ...] = (),
    required_capacity_alternatives: tuple[str, ...] = (),
    required_plan_families: tuple[str, ...] = (),
    compatibility_analysis: CompatibilityAnalysis | None = None,
) -> list[_Candidate]:
    """Find joint scope/phenotype/BOOK-language anchors before greedy filling.

    A portfolio used to anchor the six p.3 scopes and then greedily optimize
    silhouette novelty.  That could discard every valid aggregation even when
    aggregation candidates had passed program, legal and parking gates.  BOOK
    sentence depth is part of the authored geometry language, so solve it in
    the same bounded joint coverage problem instead of adding a post-hoc
    counter or weakening any geometry threshold.
    """
    # The coverage dimension is the delivered ground take, not the BOOK base
    # volume scope. The scope is an authoring abstraction that does not survive
    # into the form - all six scopes delivered the same silhouette envelope - so
    # anchoring it spent the portfolio's diversity budget on something invisible
    # in the result.
    #
    # Requiring all six scopes also made this solver give up before it started:
    # a run that reaches three of them returned [] on the first line and every
    # joint anchor was lost (joint_anchor_count 0 on PNU 4115011300106840001).
    # The ground take is built from the positions actually present, the same way
    # phenotypes, principle kinds and capacity alternatives already are, so the
    # solver covers what exists instead of demanding what does not.
    available_ground_takes = tuple(
        dict.fromkeys(_portfolio_diversity_key(candidate) for candidate in candidates)
    )
    by_scope = {
        label: sorted(
            (
                candidate
                for candidate in candidates
                if _portfolio_diversity_key(candidate) == label
            ),
            key=lambda candidate: candidate.score,
            reverse=True,
        )
        for label in available_ground_takes
    }
    if not by_scope:
        return []
    available_phenotypes = {_solid_morphology_metrics(candidate)["phenotype"] for candidate in candidates}
    required_phenotypes = tuple(
        value for value in dict.fromkeys(required_phenotypes)
        if value in available_phenotypes
    )
    available_principle_kinds = {candidate.principle_kind for candidate in candidates}
    required_principle_kinds = tuple(
        value for value in dict.fromkeys(required_principle_kinds)
        if value in available_principle_kinds
    )
    available_capacity_alternatives = {
        _capacity_alternative_key(candidate) for candidate in candidates
    }
    required_capacity_alternatives = tuple(
        value for value in dict.fromkeys(required_capacity_alternatives)
        if value in available_capacity_alternatives
    )
    available_plan_families = {_plan_family(candidate) for candidate in candidates}
    required_plan_families = tuple(
        value for value in dict.fromkeys(required_plan_families)
        if value in available_plan_families
    )

    def solve(
        phenotype_requirements: tuple[str, ...],
        principle_kind_requirements: tuple[str, ...],
    ) -> list[_Candidate] | None:
        search_state_count = 0
        requirements = tuple(
            [("scope", label) for label in available_ground_takes]
            + [("phenotype", value) for value in phenotype_requirements]
            + [("principle_kind", value) for value in principle_kind_requirements]
            + [("capacity", value) for value in required_capacity_alternatives]
            + [("plan_family", value) for value in required_plan_families]
        )

        def visit(
            picked: list[_Candidate],
            operation_usage: Counter,
            seed_usage: Counter,
            section_usage: Counter,
            roof_usage: Counter,
            chassis_usage: Counter,
            phenotype_usage: Counter,
            capacity_usage: Counter,
            wedge_count: int,
            pyramidal_count: int,
        ) -> list[_Candidate] | None:
            nonlocal search_state_count
            search_state_count += 1
            if search_state_count > ANCHOR_SEARCH_STATE_LIMIT:
                return None
            covered_scopes = {
                _portfolio_diversity_key(candidate) for candidate in picked
            }
            covered_phenotypes = {_solid_morphology_metrics(candidate)["phenotype"] for candidate in picked}
            covered_principle_kinds = {candidate.principle_kind for candidate in picked}
            covered_capacity_alternatives = {
                _capacity_alternative_key(candidate) for candidate in picked
            }
            covered_requirements = {
                *({("scope", value) for value in covered_scopes}),
                *({("phenotype", value) for value in covered_phenotypes}),
                *({("principle_kind", value) for value in covered_principle_kinds}),
                *({("capacity", value) for value in covered_capacity_alternatives}),
                *({("plan_family", _plan_family(candidate)) for candidate in picked}),
            }
            missing = [requirement for requirement in requirements if requirement not in covered_requirements]
            if not missing:
                return list(picked)

            def eligible(requirement: tuple[str, str]) -> list[_Candidate]:
                result = []
                for candidate in candidates:
                    if any(candidate is item for item in picked):
                        continue
                    if requirement[0] == "scope" and _portfolio_diversity_key(candidate) != requirement[1]:
                        continue
                    if requirement[0] == "phenotype" and _solid_morphology_metrics(candidate)["phenotype"] != requirement[1]:
                        continue
                    if requirement[0] == "principle_kind" and candidate.principle_kind != requirement[1]:
                        continue
                    if requirement[0] == "capacity" and _capacity_alternative_key(candidate) != requirement[1]:
                        continue
                    if requirement[0] == "plan_family" and _plan_family(candidate) != requirement[1]:
                        continue
                    seed = _seed_family(candidate)
                    section = _section_family(candidate)
                    roof = _roof_archetype(candidate)
                    chassis = _chassis_family(candidate)
                    morphology = _solid_morphology_metrics(candidate)
                    if operation_usage[candidate.operation] >= 2:
                        continue
                    if phenotype_usage[str(morphology["phenotype"])] >= phenotype_cap:
                        continue
                    if bool(morphology.get("wedge_like")) and wedge_count >= wedge_like_cap:
                        continue
                    if bool(morphology.get("pyramidal_like")) and pyramidal_count >= pyramidal_like_cap:
                        continue
                    if (
                        seed_usage[seed] >= seed_family_cap
                        or section_usage[section] >= section_family_cap
                        or roof_usage[roof] >= roof_archetype_caps.get(roof, 999)
                        or chassis_usage[chassis] >= chassis_family_caps.get(chassis, 999)
                    ):
                        continue
                    if any(
                        (
                            compatibility_analysis.distance(candidate, other)
                            if compatibility_analysis is not None
                            else _silhouette_distance(candidate, other)
                        ) < PORTFOLIO_SILHOUETTE_DISTANCE
                        for other in picked
                    ):
                        continue
                    result.append(candidate)
                def coverage_gain(candidate: _Candidate) -> int:
                    morphology = _solid_morphology_metrics(candidate)
                    values = {
                        ("scope", _portfolio_diversity_key(candidate)),
                        ("phenotype", str(morphology["phenotype"])),
                        ("principle_kind", candidate.principle_kind),
                        ("capacity", _capacity_alternative_key(candidate)),
                        ("plan_family", _plan_family(candidate)),
                    }
                    return sum(requirement in values for requirement in missing)

                result.sort(key=lambda candidate: (
                    -coverage_gain(candidate),
                    -float(candidate.score),
                ))
                return result[:ANCHOR_BRANCH_LIMIT]

            requirement_options = [(requirement, eligible(requirement)) for requirement in missing]
            requirement, options = min(
                requirement_options,
                key=lambda item: (len(item[1]), item[0][0], item[0][1]),
            )
            if not options:
                return None
            options.sort(key=lambda candidate: (
                capacity_usage[_capacity_alternative_key(candidate)],
                seed_usage[_seed_family(candidate)],
                section_usage[_section_family(candidate)],
                roof_usage[_roof_archetype(candidate)],
                chassis_usage[_chassis_family(candidate)],
                -candidate.score,
            ))
            for candidate in options:
                seed = _seed_family(candidate)
                section = _section_family(candidate)
                roof = _roof_archetype(candidate)
                chassis = _chassis_family(candidate)
                morphology = _solid_morphology_metrics(candidate)
                operation_usage[candidate.operation] += 1
                seed_usage[seed] += 1
                section_usage[section] += 1
                roof_usage[roof] += 1
                chassis_usage[chassis] += 1
                phenotype_usage[str(morphology["phenotype"])] += 1
                capacity_usage[_capacity_alternative_key(candidate)] += 1
                picked.append(candidate)
                result = visit(
                    picked, operation_usage, seed_usage, section_usage,
                    roof_usage, chassis_usage, phenotype_usage,
                    capacity_usage,
                    wedge_count + int(bool(morphology.get("wedge_like"))),
                    pyramidal_count + int(bool(morphology.get("pyramidal_like"))),
                )
                if result is not None:
                    return result
                picked.pop()
                operation_usage[candidate.operation] -= 1
                seed_usage[seed] -= 1
                section_usage[section] -= 1
                roof_usage[roof] -= 1
                chassis_usage[chassis] -= 1
                phenotype_usage[str(morphology["phenotype"])] -= 1
                capacity_usage[_capacity_alternative_key(candidate)] -= 1
            return None

        return visit(
            [], Counter(), Counter(), Counter(), Counter(), Counter(), Counter(),
            Counter(), 0, 0,
        )

    # If all requested phenotypes cannot coexist under hard silhouette/family
    # constraints, preserve the six BOOK scopes and let the explicit failure
    # remain visible. Never fabricate or relax a geometry threshold.
    return (
        solve(required_phenotypes, required_principle_kinds)
        or solve((), required_principle_kinds)
        or solve(required_phenotypes, ())
        or solve((), ())
        or []
    )


def _target_hard_pass_universe(
    pool: list[_Candidate],
) -> tuple[list[_Candidate], list[_Candidate]]:
    """Deduplicate candidates and retain capacity measurements as diagnostics."""

    unique: dict[tuple[Any, ...], _Candidate] = {}
    for candidate in pool:
        fingerprint = _fingerprint(candidate)
        current = unique.get(fingerprint)
        if current is None or candidate.score > current.score:
            unique[fingerprint] = candidate
    deduplicated = list(unique.values())
    measured = [
        candidate for candidate in deduplicated
        if _capacity_target_gate(candidate) is not None
    ]
    return deduplicated, measured


def _select(
    pool: list[_Candidate],
    target: int = 20,
    *,
    visual_directive: dict[str, Any] | None = None,
    selection_trace: dict[str, Any] | None = None,
    compatibility_analysis: CompatibilityAnalysis | None = None,
    allow_diagnostic_fallback: bool = False,
) -> list[_Candidate]:
    trace = selection_trace if isinstance(selection_trace, dict) else {}
    trace.clear()
    trace["raw_pool_count"] = len(pool)
    candidates, measured_capacity_candidates = _target_hard_pass_universe(pool)
    trace["capacity_target_gate_measured_count"] = len(measured_capacity_candidates)
    trace["capacity_target_gate_pass_count"] = sum(
        _capacity_target_gate(candidate) is True
        for candidate in measured_capacity_candidates
    )
    trace["capacity_target_gate_advisory_miss_count"] = sum(
        _capacity_target_gate(candidate) is False
        for candidate in measured_capacity_candidates
    )
    trace["capacity_target_gate_rejected_count"] = 0
    trace["capacity_target_gate_authority"] = "diagnostic_only"
    diagnostic_capacity_pass_candidates = [
        candidate for candidate in candidates
        if _capacity_target_gate(candidate) is True
    ]
    diagnostic_capacity_filter_applied = bool(
        allow_diagnostic_fallback
        and target >= 20
        and len(diagnostic_capacity_pass_candidates) >= target
    )
    if diagnostic_capacity_filter_applied:
        candidates = diagnostic_capacity_pass_candidates
    trace["diagnostic_capacity_hard_pass_filter_applied"] = (
        diagnostic_capacity_filter_applied
    )
    trace["diagnostic_capacity_hard_pass_filter_count"] = len(candidates)
    uncapped_candidates = list(candidates)
    diagnostic_preview_threshold = 0.0 if (
        allow_diagnostic_fallback and target >= 20
    ) else None
    compatibility_analysis = compatibility_analysis or (
        build_compatibility_analysis(
            uncapped_candidates,
            threshold=diagnostic_preview_threshold,
        )
        if diagnostic_preview_threshold is not None
        else build_compatibility_analysis(
            uncapped_candidates,
            target_count=target,
        )
    )
    silhouette_distance = compatibility_analysis.distance
    trace["unique_candidate_count"] = len(candidates)
    directive = visual_directive or {}
    geometry_family_caps = {
        str(family): max(1, min(target, int(cap)))
        for family, cap in (directive.get("max_geometry_family_counts") or {}).items()
        if str(family)
    }
    if geometry_family_caps:
        family_usage: Counter[str] = Counter()
        capped_candidates: list[_Candidate] = []
        for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
            family = _geometry_program_family(candidate)
            cap = geometry_family_caps.get(family, target)
            if family_usage[family] >= cap:
                continue
            family_usage[family] += 1
            capped_candidates.append(candidate)
        candidates = capped_candidates
    trace["after_memory_geometry_family_cap_count"] = len(candidates)
    trace["memory_geometry_family_caps"] = dict(sorted(geometry_family_caps.items()))
    candidate_universe = list(candidates)
    advisory_capacity_priority = (
        "spatial_reserve", "balanced_yield", "brief_target", "maximum_feasible",
    )
    available_capacity_alternatives = {
        _capacity_alternative_key(candidate)
        for candidate in candidate_universe
        if _capacity_alternative_key(candidate)
    }
    advisory_capacity_alternative_quotas = _capacity_portfolio_quotas(
        candidate_universe,
        target=target,
    )
    capacity_priority: tuple[str, ...] = ()
    capacity_alternative_quotas: dict[str, int] = {}
    trace["capacity_alternative_supply_counts"] = dict(sorted(Counter(
        _capacity_alternative_key(candidate)
        for candidate in candidate_universe
        if _capacity_alternative_key(candidate)
    ).items()))
    trace["capacity_alternative_quotas"] = {}
    trace["advisory_capacity_priority"] = list(advisory_capacity_priority)
    trace["advisory_capacity_alternative_quotas"] = dict(
        sorted(advisory_capacity_alternative_quotas.items())
    )
    trace["capacity_alternative_quota_authority"] = "diagnostic_only"
    selected: list[_Candidate] = []
    operation_usage: dict[str, int] = {}
    scope_usage: dict[str, int] = {}
    seed_usage: dict[str, int] = {}
    section_usage: dict[str, int] = {}
    roof_usage: dict[str, int] = {}
    chassis_usage: dict[str, int] = {}
    ground_strategy_usage: dict[str, int] = {}
    concept_usage: dict[str, int] = {}
    principle_kind_usage: dict[str, int] = {}
    capacity_alternative_usage: dict[str, int] = {}
    # The delivered ground take is the axis the portfolio spreads over; the
    # BOOK scope it used to steer by is invisible in the finished mass.
    available_scopes = {
        _portfolio_diversity_key(candidate) for candidate in candidates
    }
    seed_families = {_seed_family(candidate) for candidate in candidates}
    roof_archetypes = {_roof_archetype(candidate) for candidate in candidates}
    chassis_families = {_chassis_family(candidate) for candidate in candidates}
    seed_family_cap = max(2, (target + max(1, len(seed_families)) - 1) // max(1, len(seed_families)) + 1)
    section_family_cap = max(3, target // 2)
    default_roof_cap = min(target, 3)
    roof_archetype_caps = {archetype: default_roof_cap for archetype in roof_archetypes}
    for archetype, cap in (directive.get("max_roof_archetype_counts") or {}).items():
        if str(archetype) in roof_archetypes:
            roof_archetype_caps[str(archetype)] = max(1, min(target, int(cap)))
    chassis_family_caps = _chassis_caps(
        chassis_families,
        target=target,
        directive=directive,
    )
    wedge_like_cap = max(0, min(
        target,
        int(directive.get("max_wedge_like_count", max(3, target // 5))),
    ))
    pyramidal_like_cap = max(0, min(
        target,
        int(directive.get("max_pyramidal_like_count", 2)),
    ))
    phenotype_cap = max(2, min(
        target,
        int(directive.get("max_solid_phenotype_count", 3)),
    ))

    def morphology_caps_allow(candidate: _Candidate) -> bool:
        metrics = _solid_morphology_metrics(candidate)
        phenotype = str(metrics["phenotype"])
        if sum(
            _solid_morphology_metrics(item)["phenotype"] == phenotype
            for item in selected
        ) >= phenotype_cap:
            return False
        if metrics["wedge_like"] and sum(
            bool(_solid_morphology_metrics(item)["wedge_like"])
            for item in selected
        ) >= wedge_like_cap:
            return False
        if metrics["pyramidal_like"] and sum(
            bool(_solid_morphology_metrics(item)["pyramidal_like"])
            for item in selected
        ) >= pyramidal_like_cap:
            return False
        return True

    def capacity_quota_allows(candidate: _Candidate) -> bool:
        alternative = _capacity_alternative_key(candidate)
        quota = capacity_alternative_quotas.get(alternative)
        return quota is None or capacity_alternative_usage.get(alternative, 0) < quota

    def register(winner: _Candidate) -> None:
        selected.append(winner)
        operation_usage[winner.operation] = operation_usage.get(winner.operation, 0) + 1
        scope_usage[_portfolio_diversity_key(winner)] = (
            scope_usage.get(_portfolio_diversity_key(winner), 0) + 1
        )
        seed_usage[_seed_family(winner)] = seed_usage.get(_seed_family(winner), 0) + 1
        section_usage[_section_family(winner)] = section_usage.get(_section_family(winner), 0) + 1
        roof_usage[_roof_archetype(winner)] = roof_usage.get(_roof_archetype(winner), 0) + 1
        chassis_usage[_chassis_family(winner)] = chassis_usage.get(_chassis_family(winner), 0) + 1
        concept = _design_concept_descriptor(winner)
        ground = str(concept["ground_strategy"])
        key = str(concept["concept_key"])
        ground_strategy_usage[ground] = ground_strategy_usage.get(ground, 0) + 1
        concept_usage[key] = concept_usage.get(key, 0) + 1
        principle_kind_usage[winner.principle_kind] = principle_kind_usage.get(winner.principle_kind, 0) + 1
        capacity_key = _capacity_alternative_key(winner)
        capacity_alternative_usage[capacity_key] = capacity_alternative_usage.get(capacity_key, 0) + 1
    anchors = _scope_coverage_anchors(
        candidates,
        seed_family_cap=seed_family_cap,
        section_family_cap=section_family_cap,
        roof_archetype_caps=roof_archetype_caps,
        chassis_family_caps=chassis_family_caps,
        phenotype_cap=phenotype_cap,
        wedge_like_cap=wedge_like_cap,
        pyramidal_like_cap=pyramidal_like_cap,
        required_phenotypes=tuple(
            str(value) for value in directive.get("required_solid_phenotypes") or ()
        ),
        required_principle_kinds=tuple(
            kind for kind in ("base_operative", "combination", "aggregation")
            if any(candidate.principle_kind == kind for candidate in candidates)
        ),
        required_capacity_alternatives=tuple(
            alternative for alternative in capacity_priority
            if alternative in available_capacity_alternatives
        ),
        required_plan_families=tuple(
            str(value) for value in directive.get("required_plan_families") or ()
        ),
        compatibility_analysis=compatibility_analysis,
    )
    anchor_ids = {id(candidate) for candidate in anchors}
    candidates = [candidate for candidate in candidates if id(candidate) not in anchor_ids]
    for winner in anchors:
        register(winner)
    trace["joint_anchor_count"] = len(selected)
    # Where a ground take is lost is not guessable from counts alone: a trim
    # of one candidate cannot explain a drop of two positions.
    trace["joint_anchor_ground_takes"] = sorted(
        {_portfolio_diversity_key(candidate) for candidate in selected}
    )
    trace["joint_anchor_principle_kind_counts"] = dict(Counter(
        candidate.principle_kind for candidate in selected
    ))

    # Capacity alternatives are site-derived projections of valid typed forms.
    # Keep one strict candidate from every available target band so a board is
    # not allowed to hide the spatial-reserve or maximum-feasible comparison.
    for required_capacity in capacity_priority:
        if (
            required_capacity not in available_capacity_alternatives
            or len(selected) >= target
            or capacity_alternative_usage.get(required_capacity, 0)
        ):
            continue
        options = [
            candidate for candidate in candidates
            if _capacity_alternative_key(candidate) == required_capacity
            and capacity_quota_allows(candidate)
            and operation_usage.get(candidate.operation, 0) < 2
            and seed_usage.get(_seed_family(candidate), 0) < seed_family_cap
            and section_usage.get(_section_family(candidate), 0) < section_family_cap
            and roof_usage.get(_roof_archetype(candidate), 0) < roof_archetype_caps.get(_roof_archetype(candidate), target)
            and chassis_usage.get(_chassis_family(candidate), 0) < chassis_family_caps.get(_chassis_family(candidate), target)
            and morphology_caps_allow(candidate)
            and concept_usage.get(_design_concept_descriptor(candidate)["concept_key"], 0) < 2
            and all(silhouette_distance(candidate, other) >= PORTFOLIO_SILHOUETTE_DISTANCE for other in selected)
        ]
        if not options:
            continue
        winner = max(options, key=lambda candidate: candidate.score)
        register(winner)
        candidates.remove(winner)
    trace["after_capacity_alternative_anchor_count"] = len(selected)
    trace["capacity_alternative_anchor_counts"] = dict(sorted(capacity_alternative_usage.items()))

    # Keep one valid example from every available BOOK language depth.  This
    # is normally satisfied by the joint anchor solver above; the bounded
    # recovery handles a cap conflict without inventing geometry or accepting
    # a candidate that failed a hard gate.
    available_principle_kinds = tuple(
        kind for kind in ("base_operative", "combination", "aggregation")
        if any(candidate.principle_kind == kind for candidate in candidate_universe)
    )
    for required_kind in available_principle_kinds:
        if len(selected) >= target or principle_kind_usage.get(required_kind, 0):
            continue
        options = [
            candidate for candidate in candidates
            if candidate.principle_kind == required_kind
            and capacity_quota_allows(candidate)
            and operation_usage.get(candidate.operation, 0) < 2
            and seed_usage.get(_seed_family(candidate), 0) < seed_family_cap
            and section_usage.get(_section_family(candidate), 0) < section_family_cap
            and roof_usage.get(_roof_archetype(candidate), 0) < roof_archetype_caps.get(_roof_archetype(candidate), target)
            and chassis_usage.get(_chassis_family(candidate), 0) < chassis_family_caps.get(_chassis_family(candidate), target)
            and morphology_caps_allow(candidate)
            and concept_usage.get(_design_concept_descriptor(candidate)["concept_key"], 0) < 2
            and all(silhouette_distance(candidate, other) >= PORTFOLIO_SILHOUETTE_DISTANCE for other in selected)
        ]
        if not options:
            continue
        winner = max(options, key=lambda candidate: candidate.score)
        register(winner)
        candidates.remove(winner)
    trace["after_principle_kind_recovery_count"] = len(selected)

    # A design portfolio must vary the relationship to the public edge, not
    # only its roof label.  Anchor up to three ground strategies that already
    # exist as valid final ASTs; this never fabricates a form or weakens a gate.
    available_ground_strategies = {
        str(_design_concept_descriptor(candidate)["ground_strategy"])
        for candidate in candidate_universe
        if str(_design_concept_descriptor(candidate)["ground_strategy"]) != "misaligned_open_court"
    }
    ground_priority = (
        "frontage_open_court", "frontage_court_threshold",
        "frontage_split_threshold", "frontage_entry_notch",
        "frontage_lifted_threshold",
        "lifted_threshold", "split_threshold",
        "carved_notch", "internal_court", "direct_edge",
    )
    required_ground_strategies = tuple(
        strategy for strategy in ground_priority if strategy in available_ground_strategies
    )[:min(3, len(available_ground_strategies))]
    for required_ground in required_ground_strategies:
        if len(selected) >= target or ground_strategy_usage.get(required_ground, 0):
            continue
        options = [
            candidate for candidate in candidates
            if _design_concept_descriptor(candidate)["ground_strategy"] == required_ground
            and capacity_quota_allows(candidate)
            and operation_usage.get(candidate.operation, 0) < 2
            and seed_usage.get(_seed_family(candidate), 0) < seed_family_cap
            and section_usage.get(_section_family(candidate), 0) < section_family_cap
            and roof_usage.get(_roof_archetype(candidate), 0) < roof_archetype_caps.get(_roof_archetype(candidate), target)
            and chassis_usage.get(_chassis_family(candidate), 0) < chassis_family_caps.get(_chassis_family(candidate), target)
            and morphology_caps_allow(candidate)
            and concept_usage.get(_design_concept_descriptor(candidate)["concept_key"], 0) < 2
            and all(silhouette_distance(candidate, other) >= PORTFOLIO_SILHOUETTE_DISTANCE for other in selected)
        ]
        if not options:
            continue
        winner = max(options, key=lambda candidate: candidate.score)
        register(winner)
        candidates.remove(winner)
    trace["after_ground_anchor_count"] = len(selected)

    # A VLM critic may require missing visual genotypes, but it can only select
    # candidates that were produced by typed graph mutations and passed all
    # geometry/program/legal gates.  It never injects a finished mesh.
    required_roofs = tuple(dict.fromkeys(
        str(value) for value in (directive.get("required_roof_archetypes") or ())
        if str(value) in roof_archetypes
    ))
    for required_roof in required_roofs:
        if len(selected) >= target or roof_usage.get(required_roof, 0):
            continue
        options = [
            candidate for candidate in candidates
            if _roof_archetype(candidate) == required_roof
            and capacity_quota_allows(candidate)
            and operation_usage.get(candidate.operation, 0) < 2
            and seed_usage.get(_seed_family(candidate), 0) < seed_family_cap
            and section_usage.get(_section_family(candidate), 0) < section_family_cap
            and roof_usage.get(required_roof, 0) < roof_archetype_caps.get(required_roof, target)
            and chassis_usage.get(_chassis_family(candidate), 0) < chassis_family_caps.get(_chassis_family(candidate), target)
            and morphology_caps_allow(candidate)
            and all(silhouette_distance(candidate, other) >= PORTFOLIO_SILHOUETTE_DISTANCE for other in selected)
        ]
        if not options:
            continue
        winner = max(options, key=lambda candidate: candidate.score)
        register(winner)
        candidates.remove(winner)
    trace["after_roof_anchor_count"] = len(selected)
    available_geometry_families = {
        _geometry_program_family(candidate)
        for candidate in candidates
        if _geometry_program_family(candidate)
    }
    required_geometry_families = tuple(dict.fromkeys(
        str(value) for value in (directive.get("required_geometry_program_families") or ())
        if str(value) in available_geometry_families
    ))
    for required_family in required_geometry_families:
        if len(selected) >= target or any(
            _geometry_program_family(candidate) == required_family
            for candidate in selected
        ):
            continue
        options = [
            candidate for candidate in candidates
            if _geometry_program_family(candidate) == required_family
            and capacity_quota_allows(candidate)
            and operation_usage.get(candidate.operation, 0) < 2
            and seed_usage.get(_seed_family(candidate), 0) < seed_family_cap
            and section_usage.get(_section_family(candidate), 0) < section_family_cap
            and roof_usage.get(_roof_archetype(candidate), 0) < roof_archetype_caps.get(_roof_archetype(candidate), target)
            and chassis_usage.get(_chassis_family(candidate), 0) < chassis_family_caps.get(_chassis_family(candidate), target)
            and morphology_caps_allow(candidate)
            and all(silhouette_distance(candidate, other) >= PORTFOLIO_SILHOUETTE_DISTANCE for other in selected)
        ]
        if not options:
            continue
        winner = max(options, key=lambda candidate: candidate.score)
        register(winner)
        candidates.remove(winner)
    trace["after_geometry_family_anchor_count"] = len(selected)
    # Board memory also records executable chassis that received no slot at
    # all.  If a missing chassis later produces a strict final-VLM hard pass,
    # reserve one portfolio slot for it before greedy score filling.  This is a
    # representation anchor only: every ordinary cap and silhouette test still
    # applies, and absent/rejected chassis cannot be synthesized here.
    available_chassis = {_chassis_family(candidate) for candidate in candidates}
    required_chassis = tuple(dict.fromkeys(
        str(value) for value in (directive.get("required_chassis_families") or ())
        if str(value) in available_chassis
    ))
    for chassis in required_chassis:
        if len(selected) >= target or chassis_usage.get(chassis, 0):
            continue
        options = [
            candidate for candidate in candidates
            if _chassis_family(candidate) == chassis
            and capacity_quota_allows(candidate)
            and operation_usage.get(candidate.operation, 0) < 2
            and seed_usage.get(_seed_family(candidate), 0) < seed_family_cap
            and section_usage.get(_section_family(candidate), 0) < section_family_cap
            and roof_usage.get(_roof_archetype(candidate), 0) < roof_archetype_caps.get(_roof_archetype(candidate), target)
            and chassis_usage.get(chassis, 0) < chassis_family_caps.get(chassis, target)
            and morphology_caps_allow(candidate)
            and concept_usage.get(_design_concept_descriptor(candidate)["concept_key"], 0) < 2
            and all(silhouette_distance(candidate, other) >= PORTFOLIO_SILHOUETTE_DISTANCE for other in selected)
        ]
        if not options:
            continue
        winner = max(options, key=lambda candidate: candidate.score)
        register(winner)
        candidates.remove(winner)
    trace["after_chassis_anchor_count"] = len(selected)
    greedy_iterations = 0
    while candidates and len(selected) < target:
        def eligible_with_operation_cap(operation_cap: int) -> list[_Candidate]:
            return [
                candidate for candidate in candidates
                if capacity_quota_allows(candidate)
                and operation_usage.get(candidate.operation, 0) < operation_cap
                and seed_usage.get(_seed_family(candidate), 0) < seed_family_cap
                and section_usage.get(_section_family(candidate), 0) < section_family_cap
                and roof_usage.get(_roof_archetype(candidate), 0) < roof_archetype_caps.get(_roof_archetype(candidate), target)
                and chassis_usage.get(_chassis_family(candidate), 0) < chassis_family_caps.get(_chassis_family(candidate), target)
                and morphology_caps_allow(candidate)
                and concept_usage.get(_design_concept_descriptor(candidate)["concept_key"], 0) < 2
                and all(silhouette_distance(candidate, other) >= PORTFOLIO_SILHOUETTE_DISTANCE for other in selected)
            ]

        eligible_at_two = eligible_with_operation_cap(2)
        eligible = eligible_at_two
        if not eligible:
            # Only after the two-use diversity cap is exhausted may the same
            # BOOK sentence appear once more on another program/section
            # family. Silhouette and family caps remain unchanged.
            eligible = eligible_with_operation_cap(3)
        if not eligible:
            trace["greedy_break"] = {
                "reason": "no_candidate_satisfies_all_selection_caps",
                "selected_count": len(selected),
                "remaining_candidate_count": len(candidates),
                "eligible_at_operation_cap_2": len(eligible_at_two),
                "eligible_at_operation_cap_3": len(eligible),
            }
            break
        uncovered_scopes = available_scopes - set(scope_usage)
        if uncovered_scopes:
            # BOOK p.3 scope coverage is a portfolio constraint. Start with
            # the rarest surviving scope so a high-scoring 1/1 family cannot
            # crowd a valid 1/16 or 1/8 candidate out of the final archive.
            target_scope = min(
                uncovered_scopes,
                key=lambda scope: (
                    sum(
                        _portfolio_diversity_key(candidate) == scope
                        for candidate in eligible
                    ),
                    scope,
                ),
            )
            scoped = [
                candidate
                for candidate in eligible
                if _portfolio_diversity_key(candidate) == target_scope
            ]
            if scoped:
                eligible = scoped

        def selection_key(candidate: _Candidate) -> tuple[float, float]:
            novelty = 1.0 if not selected else min(
                _distance(candidate, other) * 0.55 + silhouette_distance(candidate, other) * 0.45
                for other in selected
            )
            new_language_bonus = 0.08 if operation_usage.get(candidate.operation, 0) == 0 else 0.0
            new_scope_bonus = (
                0.05
                if scope_usage.get(_portfolio_diversity_key(candidate), 0) == 0
                else 0.0
            )
            new_seed_bonus = 0.06 if seed_usage.get(_seed_family(candidate), 0) == 0 else 0.0
            new_section_bonus = 0.05 if section_usage.get(_section_family(candidate), 0) == 0 else 0.0
            new_roof_bonus = 0.09 if roof_usage.get(_roof_archetype(candidate), 0) == 0 else 0.0
            new_chassis_bonus = 0.06 if chassis_usage.get(_chassis_family(candidate), 0) == 0 else 0.0
            concept = _design_concept_descriptor(candidate)
            new_ground_bonus = 0.10 if ground_strategy_usage.get(concept["ground_strategy"], 0) == 0 else 0.0
            new_concept_bonus = 0.08 if concept_usage.get(concept["concept_key"], 0) == 0 else 0.0
            new_principle_kind_bonus = 0.10 if principle_kind_usage.get(candidate.principle_kind, 0) == 0 else 0.0
            capacity_balance_bonus = 0.0
            return (
                candidate.score * 0.44
                + novelty * 0.56
                + new_language_bonus
                + new_scope_bonus
                + new_seed_bonus
                + new_section_bonus
                + new_roof_bonus
                + new_chassis_bonus
                + new_ground_bonus
                + new_concept_bonus
                + new_principle_kind_bonus
                + capacity_balance_bonus,
                candidate.score,
            )

        winner = max(eligible, key=selection_key)
        register(winner)
        candidates.remove(winner)
        greedy_iterations += 1
    trace["greedy_iteration_count"] = greedy_iterations
    trace["pre_rebalance_count"] = len(selected)
    trace["pre_rebalance_ground_takes"] = sorted(
        {_portfolio_diversity_key(candidate) for candidate in selected}
    )
    # Greedy novelty is useful for ordering but can paint itself into a
    # corner.  Solve the final <=20 candidate compatibility graph globally,
    # with the exact same caps, and only replace the greedy set when the
    # solver proves a larger valid portfolio exists.
    # This exact search is intentionally a final-pool tool. The same `_select`
    # function also helps stratify hundreds of pre-VLM candidates; applying an
    # exponential exact search there is both unnecessary and unbounded.
    if len(candidate_universe) <= 24:
        cap_limits: dict[str, int] = {}
        solver_facts: list[ConstraintCandidateFacts] = []
        for candidate in candidate_universe:
            morphology = _solid_morphology_metrics(candidate)
            concept = _design_concept_descriptor(candidate)
            keys = (
                f"operation:{candidate.operation}",
                f"seed:{_seed_family(candidate)}",
                f"section:{_section_family(candidate)}",
                f"roof:{_roof_archetype(candidate)}",
                f"chassis:{_chassis_family(candidate)}",
                f"capacity_alt:{_capacity_alternative_key(candidate)}",
                f"concept:{concept['concept_key']}",
                f"phenotype:{morphology['phenotype']}",
                *(("wedge_like",) if morphology["wedge_like"] else ()),
                *(("pyramidal_like",) if morphology["pyramidal_like"] else ()),
            )
            cap_limits.update({
                f"operation:{candidate.operation}": 3,
                f"seed:{_seed_family(candidate)}": seed_family_cap,
                f"section:{_section_family(candidate)}": section_family_cap,
                f"roof:{_roof_archetype(candidate)}": roof_archetype_caps.get(
                    _roof_archetype(candidate), target
                ),
                f"chassis:{_chassis_family(candidate)}": chassis_family_caps.get(
                    _chassis_family(candidate), target
                ),
                # Capacity bands are diagnostic design alternatives. Keeping
                # this non-binding key in solver evidence must not impose a
                # quota, coverage requirement, or per-candidate hard gate.
                f"capacity_alt:{_capacity_alternative_key(candidate)}": target,
                f"concept:{concept['concept_key']}": 2,
                f"phenotype:{morphology['phenotype']}": phenotype_cap,
                "wedge_like": wedge_like_cap,
                "pyramidal_like": pyramidal_like_cap,
            })
            solver_facts.append(ConstraintCandidateFacts(
                score=float(candidate.score),
                cap_keys=tuple(keys),
                coverage_tags=(
                    f"scope:{_portfolio_diversity_key(candidate)}",
                    f"capacity_alt:{_capacity_alternative_key(candidate)}",
                ),
            ))
        compatibility = compatibility_analysis.compatibility_matrix(candidate_universe)
        required_scope_tags = tuple(
            f"scope:{label}" for label in sorted(available_scopes)
        )
        required_capacity_tags = tuple(
            f"capacity_alt:{alternative_id}"
            for alternative_id in capacity_priority
            if alternative_id in available_capacity_alternatives
        )
        solver_indices = solve_maximum_compatible_subset(
            solver_facts,
            compatibility,
            target_count=target,
            maximum_key_counts=cap_limits,
            required_coverage_tags=(*required_scope_tags, *required_capacity_tags),
        )
        solver_selected = [candidate_universe[index] for index in solver_indices]
        trace["global_constraint_solver_count"] = len(solver_selected)
        trace["global_constraint_solver_replaced_greedy"] = len(solver_selected) > len(selected)
        trace["global_constraint_solver_preserved_caps"] = True
        if len(solver_selected) > len(selected):
            selected = solver_selected
    else:
        trace["global_constraint_solver_count"] = None
        trace["global_constraint_solver_replaced_greedy"] = False
        trace["global_constraint_solver_preserved_caps"] = True
        trace["global_constraint_solver_skipped_reason"] = "exact_solver_pool_above_24"
        # Large post-gate pools need set search too: a high-scoring greedy
        # member can be the sole silhouette conflict for many later forms.
        # Use the uncapped hard-pass universe and ordinary typed caps; prior
        # VLM repetition caps remain a first-pass preference, never authority
        # to leave eight portfolio slots empty.
        beam_universe = list(uncapped_candidates)
        ordinary_chassis_caps = _chassis_caps(
            {_chassis_family(candidate) for candidate in beam_universe},
            target=target,
            directive={},
        )
        beam_cap_limits: dict[str, int] = {}
        beam_facts: list[ConstraintCandidateFacts] = []
        for candidate in beam_universe:
            morphology = _solid_morphology_metrics(candidate)
            concept = _design_concept_descriptor(candidate)
            capacity_key = _capacity_alternative_key(candidate)
            cap_keys = (
                f"operation:{candidate.operation}",
                f"seed:{_seed_family(candidate)}",
                f"section:{_section_family(candidate)}",
                f"roof:{_roof_archetype(candidate)}",
                f"chassis:{_chassis_family(candidate)}",
                f"capacity_alt:{capacity_key}",
                f"concept:{concept['concept_key']}",
                f"phenotype:{morphology['phenotype']}",
                *(("wedge_like",) if morphology["wedge_like"] else ()),
                *(("pyramidal_like",) if morphology["pyramidal_like"] else ()),
            )
            beam_cap_limits.update({
                f"operation:{candidate.operation}": 3,
                f"seed:{_seed_family(candidate)}": seed_family_cap,
                f"section:{_section_family(candidate)}": section_family_cap,
                f"roof:{_roof_archetype(candidate)}": roof_archetype_caps.get(
                    _roof_archetype(candidate), target
                ),
                f"chassis:{_chassis_family(candidate)}": ordinary_chassis_caps.get(
                    _chassis_family(candidate), target
                ),
                # The site-derived target is already a per-candidate hard
                # pass. Portfolio distribution is coverage + preference, not
                # a hard maximum whose empty rare-band slots block valid MASS.
                f"capacity_alt:{capacity_key}": target,
                f"concept:{concept['concept_key']}": 2,
                f"phenotype:{morphology['phenotype']}": phenotype_cap,
                "wedge_like": wedge_like_cap,
                "pyramidal_like": pyramidal_like_cap,
            })
            coverage_tags = [
                f"scope:{_portfolio_diversity_key(candidate)}",
                f"capacity_alt:{capacity_key}",
                f"principle_kind:{candidate.principle_kind}",
                f"ground:{concept['ground_strategy']}",
                f"plan:{_plan_family(candidate)}",
            ]
            if concept["frontage_aligned"]:
                coverage_tags.append("frontage_aligned")
            if str(morphology["phenotype"]) in set(
                str(value) for value in directive.get("required_solid_phenotypes") or ()
            ):
                coverage_tags.append(f"required_phenotype:{morphology['phenotype']}")
            beam_facts.append(ConstraintCandidateFacts(
                score=float(candidate.score),
                cap_keys=tuple(cap_keys),
                coverage_tags=tuple(coverage_tags),
            ))
        beam_compatibility = compatibility_analysis.compatibility_matrix(beam_universe)
        beam_required_tags = (
            *(f"scope:{scope}" for scope in sorted({_portfolio_diversity_key(item) for item in beam_universe})),
            *(f"capacity_alt:{alternative}" for alternative in capacity_priority if alternative in available_capacity_alternatives),
            *(f"principle_kind:{kind}" for kind in available_principle_kinds),
            *(f"ground:{ground}" for ground in required_ground_strategies),
            *(f"plan:{plan_family}" for plan_family in dict.fromkeys(
                str(value) for value in directive.get("required_plan_families") or ()
            ) if any(
                _plan_family(item) == plan_family for item in beam_universe
            )),
            *(('frontage_aligned',) if any(
                _design_concept_descriptor(item)["frontage_aligned"] for item in beam_universe
            ) else ()),
            *(f"required_phenotype:{phenotype}" for phenotype in dict.fromkeys(
                str(value) for value in directive.get("required_solid_phenotypes") or ()
            ) if any(
                _solid_morphology_metrics(item)["phenotype"] == phenotype
                for item in beam_universe
            )),
        )
        milp_indices = solve_milp_compatible_subset(
            beam_facts,
            beam_compatibility,
            target_count=target,
            maximum_key_counts=beam_cap_limits,
            required_coverage_tags=tuple(beam_required_tags),
        )
        beam_indices = milp_indices
        beam_selected = [beam_universe[index] for index in beam_indices]
        trace["milp_global_solver_count"] = len(milp_indices)
        trace["milp_global_solver_used"] = bool(milp_indices)
        trace["milp_global_solver_target_reached"] = len(milp_indices) >= target
        trace["milp_capacity_band_policy"] = "diagnostic_only"
        trace["bounded_global_solver_count"] = len(beam_selected)
        trace["bounded_global_solver_replaced_greedy"] = len(beam_selected) > len(selected)
        trace["bounded_global_solver_preserved_caps"] = True
        if len(beam_selected) > len(selected):
            selected = beam_selected
    trace["memory_cap_primary_selection_count"] = len(selected)
    trace["memory_cap_fallback_added_count"] = 0
    trace["memory_cap_fallback_preserved_all_quality_gates"] = True
    contract = competition_portfolio_contract(target)
    trace["portfolio_contract_target_count"] = target
    required_joint_tags: list[str] = []
    requested_chassis = {
        str(value)
        for value in directive.get("required_chassis_families") or ()
    }
    requested_geometry = {
        str(value)
        for value in directive.get(
            "required_geometry_program_families"
        ) or ()
    }
    available_joint_chassis = {
        _chassis_family(candidate) for candidate in candidate_universe
    }
    available_joint_geometry = {
        _geometry_program_family(candidate)
        for candidate in candidate_universe
    }
    required_joint_tags.extend(
        f"required_chassis:{family}"
        for family in sorted(
            requested_chassis & available_joint_chassis
        )
    )
    required_joint_tags.extend(
        f"required_geometry:{family}"
        for family in sorted(
            requested_geometry & available_joint_geometry
        )
    )
    # The final authority over what ships is this joint solver, and the ground
    # take was not among the positions it had to cover - only chassis and
    # geometry family were. So the anchors covered four ground takes, the solver
    # re-picked three under other constraints, and two shipped
    # (held + worked on PNU 4115011300106840001, from a pool holding all four).
    #
    # Ask for as many distinct positions as the portfolio requires and the pool
    # can actually supply; requiring more than exists is what made the earlier
    # anchor solver give up before it started.
    available_joint_ground_takes = sorted(
        {_portfolio_diversity_key(candidate) for candidate in candidate_universe}
    )
    required_joint_tags.extend(
        f"required_ground_take:{value}"
        for value in available_joint_ground_takes[
            : max(0, min(int(target), len(available_joint_ground_takes)))
        ]
    )
    def build_joint_payload(
        active_contract: object,
        *,
        enforce_typed_caps: bool = True,
    ) -> tuple[list[ConstraintCandidateFacts], dict[str, int]]:
        facts: list[ConstraintCandidateFacts] = []
        maximum_key_counts: dict[str, int] = {}
        try:
            certified_cluster_maximum = (
                progressive_mass_run_budget(target).cluster_maximum
            )
        except ValueError:
            certified_cluster_maximum = max(1, int(target))
        active_body_phenotype_cap = (
            max(1, min(
                target,
                int(directive["max_solid_phenotype_count"]),
            ))
            if "max_solid_phenotype_count" in directive
            else (
                active_contract.body_phenotype_maximum_each
                if active_contract.body_phenotype_maximum_each is not None
                else phenotype_cap
            )
        )
        for candidate in candidate_universe:
            morphology = _solid_morphology_metrics(candidate)
            body_phenotype = str(
                morphology.get("body_phenotype")
                or morphology.get("phenotype")
                or ""
            )
            section_phenotype = str(
                morphology.get("section_phenotype") or ""
            )
            roof_archetype = _roof_archetype(candidate)
            chassis_family = _chassis_family(candidate)
            geometry_family = _geometry_program_family(candidate)
            seed_family = _seed_family(candidate)
            section_family = _section_family(candidate)
            concept_key = str(
                _design_concept_descriptor(candidate)["concept_key"]
            )
            cap_keys: list[str] = []
            if enforce_typed_caps:
                try:
                    certified_cluster = certified_mesh_cluster_key(
                        candidate.source
                    )
                except (AttributeError, TypeError, ValueError, RuntimeError):
                    program_hash_resolver = getattr(candidate, "program_hash", None)
                    program_hash = (
                        program_hash_resolver()
                        if callable(program_hash_resolver)
                        else str(getattr(candidate, "key", id(candidate)))
                    )
                    certified_cluster = f"uncertified:{program_hash}"
                certified_cluster_cap_key = (
                    f"certified_mesh_cluster:{certified_cluster}"
                )
                cap_keys = [
                    certified_cluster_cap_key,
                    f"operation:{candidate.operation}",
                    f"seed:{seed_family}",
                    f"section:{section_family}",
                    f"roof:{roof_archetype}",
                    f"chassis:{chassis_family}",
                    f"concept:{concept_key}",
                    f"phenotype:{body_phenotype}",
                ]
                maximum_key_counts.update({
                    certified_cluster_cap_key: certified_cluster_maximum,
                    f"operation:{candidate.operation}": 3,
                    f"seed:{seed_family}": seed_family_cap,
                    f"section:{section_family}": section_family_cap,
                    f"roof:{roof_archetype}": roof_archetype_caps.get(
                        roof_archetype, target
                    ),
                    f"chassis:{chassis_family}": chassis_family_caps.get(
                        chassis_family, target
                    ),
                    f"concept:{concept_key}": 2,
                    f"phenotype:{body_phenotype}": int(active_body_phenotype_cap),
                })
                if bool(morphology.get("wedge_like")):
                    cap_keys.append("wedge_like")
                    maximum_key_counts["wedge_like"] = wedge_like_cap
                if bool(morphology.get("pyramidal_like")):
                    cap_keys.append("pyramidal_like")
                    maximum_key_counts["pyramidal_like"] = pyramidal_like_cap
                if geometry_family in geometry_family_caps:
                    cap_key = f"memory_geometry_family:{geometry_family}"
                    cap_keys.append(cap_key)
                    maximum_key_counts[cap_key] = (
                        geometry_family_caps[geometry_family]
                    )
            facts.append(ConstraintCandidateFacts(
                score=float(candidate.score),
                cap_keys=tuple(cap_keys),
                coverage_tags=(
                    f"required_chassis:{chassis_family}",
                    f"required_geometry:{geometry_family}",
                    f"required_ground_take:{_portfolio_diversity_key(candidate)}",
                ),
                visible_stepped=(
                    bool(morphology["visible_stepped"])
                    if "visible_stepped" in morphology
                    else (
                        body_phenotype == "stepped"
                        or section_phenotype == "stepped"
                    )
                ),
                body_phenotype=body_phenotype,
                roof_archetype=roof_archetype,
                chassis_family=chassis_family,
                plan_family=_plan_family(candidate),
                # The BOOK scope, deliberately. The publishable contract
                # counts base_scope from the archive descriptor and requires its
                # six labels, so pointing this fact at the ground take made the
                # solver optimise one axis while the contract checked another -
                # quota.base_scope_outside_range on the first target-20 that
                # reached the contract at all. The ground take reaches this
                # solver as its own coverage tag instead, so it serves both.
                base_scope=_scope_key(candidate),
                capacity_band=_capacity_alternative_key(candidate),
                body_roof_signature=(
                    f"{body_phenotype}|{roof_archetype}"
                ),
            ))
        return facts, maximum_key_counts

    def build_joint_compatibility(
        active_contract: object,
        facts: list[ConstraintCandidateFacts],
    ) -> list[list[bool]]:
        return [
            [
                True
                if left == right
                else bool(
                    compatibility_analysis.distance(
                        candidate_universe[left],
                        candidate_universe[right],
                    )
                    >= active_contract.minimum_pair_distance
                    and (
                        active_contract.shared_language_minimum_composite_distance
                        <= 0.0
                        or not (
                            facts[left].body_phenotype
                            == facts[right].body_phenotype
                            or facts[left].roof_archetype
                            == facts[right].roof_archetype
                        )
                        or _distance(
                            candidate_universe[left],
                            candidate_universe[right],
                        )
                        >= active_contract.shared_language_minimum_composite_distance
                    )
                )
                for right in range(len(candidate_universe))
            ]
            for left in range(len(candidate_universe))
        ]

    joint_facts, joint_maximum_key_counts = build_joint_payload(contract)
    joint_compatibility = build_joint_compatibility(contract, joint_facts)
    joint_certificate: dict[str, object] = {}
    joint_solver_time_limit = 16.0 if allow_diagnostic_fallback else 45.0
    joint_indices = solve_milp_compatible_subset(
        joint_facts,
        joint_compatibility,
        target_count=target,
        maximum_key_counts=joint_maximum_key_counts,
        required_coverage_tags=tuple(required_joint_tags),
        portfolio_contract=contract,
        infeasibility_certificate=joint_certificate,
        time_limit_seconds=joint_solver_time_limit,
    )
    available_body_phenotypes = {
        str(
            _solid_morphology_metrics(candidate).get("body_phenotype")
            or _solid_morphology_metrics(candidate).get("phenotype")
            or ""
        )
        for candidate in candidate_universe
        if candidate
    }
    available_roof_archetypes = {
        _roof_archetype(candidate) for candidate in candidate_universe
    }
    available_chassis_families = {
        _chassis_family(candidate) for candidate in candidate_universe
    }
    available_plan_families = {
        _plan_family(candidate) for candidate in candidate_universe
    }
    available_body_phenotype_count = len(available_body_phenotypes)
    available_roof_archetype_count = len(available_roof_archetypes)
    available_chassis_family_count = len(available_chassis_families)
    available_plan_family_count = len(available_plan_families)
    relaxed_body_diversity_min = max(
        1,
        min(4, max(1, available_body_phenotype_count)),
    )
    relaxed_roof_diversity_min = max(
        1,
        min(4, max(1, available_roof_archetype_count)),
    )
    relaxed_chassis_diversity_min = max(
        1,
        min(3, max(1, available_chassis_family_count)),
    )
    relaxed_plan_diversity_min = max(
        1,
        min(4, max(1, available_plan_family_count)),
    )
    relaxed_body_roof_distinct_min = max(
        1,
        min(3, max(1, available_body_phenotype_count)),
    )
    relaxed_body_diversity_max_each = max(
        2,
        target // max(1, relaxed_body_diversity_min),
    )
    relaxed_roof_diversity_max_each = max(
        1,
        min(target, max(2, target // max(1, relaxed_roof_diversity_min))),
    )
    relaxed_chassis_diversity_max_each = max(
        1,
        min(target, max(2, target // max(1, relaxed_chassis_diversity_min))),
    )
    relaxed_plan_diversity_max_each = max(
        1,
        min(target, max(2, target // max(1, relaxed_plan_diversity_min))),
    )
    if (
        not joint_indices
        and allow_diagnostic_fallback
    ):
        relaxed_contract = replace(
            contract,
            capacity_band_exact_counts={},
            capacity_band_minimum_counts={},
            capacity_band_maximum_counts={},
            base_scope_maximum_each=target if target >= 20 else None,
            visible_stepped_minimum=0 if target >= 20 else contract.visible_stepped_minimum,
            upper_band_stepped_bands=(),
            upper_band_stepped_minimum=0,
            base_scope_minimum_each=1 if target >= 20 else (
                contract.base_scope_minimum_each
            ),
            body_phenotype_minimum_distinct=relaxed_body_diversity_min
            if target >= 20 else contract.body_phenotype_minimum_distinct,
            body_phenotype_maximum_each=relaxed_body_diversity_max_each
            if target >= 20 else contract.body_phenotype_maximum_each,
            roof_archetype_minimum_distinct=relaxed_roof_diversity_min
            if target >= 20 else contract.roof_archetype_minimum_distinct,
            roof_archetype_maximum_each=relaxed_roof_diversity_max_each
            if target >= 20 else contract.roof_archetype_maximum_each,
            chassis_family_minimum_distinct=relaxed_chassis_diversity_min
            if target >= 20 else contract.chassis_family_minimum_distinct,
            chassis_family_maximum_each=relaxed_chassis_diversity_max_each
            if target >= 20 else contract.chassis_family_maximum_each,
            plan_family_minimum_distinct=relaxed_plan_diversity_min
            if target >= 20 else contract.plan_family_minimum_distinct,
            plan_family_maximum_each=relaxed_plan_diversity_max_each
            if target >= 20 else contract.plan_family_maximum_each,
            body_roof_signature_minimum_distinct=relaxed_body_roof_distinct_min
            if target >= 20 else contract.body_roof_signature_minimum_distinct,
            body_roof_signature_maximum_each=target if target >= 20 else (
                contract.body_roof_signature_maximum_each
            ),
            minimum_pair_distance=(
                contract.minimum_pair_distance if target == 5 else 0.0
            ),
            shared_language_minimum_composite_distance=(
                contract.shared_language_minimum_composite_distance
                if target == 5
                else 0.0
            ),
        )
        relaxed_joint_facts, relaxed_joint_maximum_key_counts = build_joint_payload(
            relaxed_contract,
        )
        relaxed_joint_compatibility = build_joint_compatibility(
            relaxed_contract,
            relaxed_joint_facts,
        )
        relaxed_joint_certificate: dict[str, object] = {}
        relaxed_joint_indices = solve_milp_compatible_subset(
            relaxed_joint_facts,
            relaxed_joint_compatibility,
            target_count=target,
            maximum_key_counts=relaxed_joint_maximum_key_counts,
            required_coverage_tags=tuple(required_joint_tags),
            portfolio_contract=relaxed_contract,
            infeasibility_certificate=relaxed_joint_certificate,
            time_limit_seconds=20.0,
        )
        if relaxed_joint_indices:
            joint_indices = relaxed_joint_indices
            joint_facts = relaxed_joint_facts
            joint_maximum_key_counts = relaxed_joint_maximum_key_counts
            joint_compatibility = relaxed_joint_compatibility
            contract = relaxed_contract
            joint_certificate = {
                "fallback_contract": (
                    "diagnostic_relaxed_target20_contract"
                    if target == 20
                    else "diagnostic_relaxed_phenotype_roof_signature_contract"
                ),
                "status": "relaxed_contract_success",
                "diagnostic_certificate": list(
                    relaxed_joint_certificate.get("unsatisfied_constraints") or ()
                ),
            }
        elif target == 20:
            preview_contract = replace(
                relaxed_contract,
                base_scopes=(),
                base_scope_minimum_each=0,
                base_scope_maximum_each=None,
                visible_stepped_minimum=0,
                visible_stepped_maximum=None,
                upper_band_stepped_bands=(),
                upper_band_stepped_minimum=0,
                body_phenotype_minimum_distinct=1,
                body_phenotype_maximum_each=target,
                roof_archetype_minimum_distinct=1,
                roof_archetype_maximum_each=target,
                chassis_family_minimum_distinct=1,
                chassis_family_maximum_each=target,
                plan_family_minimum_distinct=1,
                plan_family_maximum_each=target,
                body_roof_signature_minimum_distinct=1,
                body_roof_signature_maximum_each=target,
                minimum_pair_distance=0.0,
                shared_language_minimum_composite_distance=0.0,
            )
            preview_joint_facts, preview_joint_maximum_key_counts = (
                build_joint_payload(preview_contract)
            )
            preview_joint_compatibility = build_joint_compatibility(
                preview_contract,
                preview_joint_facts,
            )
            preview_joint_indices = _solve_cardinality_fallback(
                preview_joint_facts,
                preview_joint_compatibility,
                target_count=target,
                maximum_key_counts=preview_joint_maximum_key_counts,
                required_coverage_tags=(),
            )
            if preview_joint_indices:
                joint_indices = preview_joint_indices
                joint_facts = preview_joint_facts
                joint_maximum_key_counts = preview_joint_maximum_key_counts
                joint_compatibility = preview_joint_compatibility
                contract = preview_contract
                joint_certificate = {
                    "fallback_contract": "diagnostic_preview_contract",
                    "status": (
                        "preview_target_reached"
                        if len(preview_joint_indices) >= target
                        else "preview_partial_reached"
                    ),
                    "maximum_cardinality": len(preview_joint_indices),
                    "unsatisfied_constraints": list(
                        relaxed_joint_certificate.get("unsatisfied_constraints") or ()
                    ),
                }
        else:
            maximum_cardinality_indices = _solve_cardinality_fallback(
                joint_facts,
                joint_compatibility,
                target_count=target,
                maximum_key_counts=joint_maximum_key_counts,
                required_coverage_tags=tuple(required_joint_tags),
            )
            if maximum_cardinality_indices:
                joint_indices = maximum_cardinality_indices
                joint_certificate = {
                    "fallback_contract": "diagnostic_maximum_compatible_subset",
                    "status": "fallback_success"
                    if len(maximum_cardinality_indices) >= target
                    else "fallback_partial_success",
                    "maximum_cardinality": len(maximum_cardinality_indices),
                    "unsatisfied_constraints": list(
                        relaxed_joint_certificate.get("unsatisfied_constraints") or ()
                    ),
                }
            else:
                joint_certificate = {
                    "status": "fallback_infeasible",
                    "target_count": int(target),
                    "unsatisfied_constraints": list(
                        relaxed_joint_certificate.get("unsatisfied_constraints") or ()
                    ),
                    "fallback_contract": "diagnostic_relaxed_target20_contract"
                    if target == 20
                    else "diagnostic_joint_contract",
                }
    elif (
        target == 20
        and allow_diagnostic_fallback
        and len(joint_indices) < target
    ):
        preview_contract = replace(
            contract,
            base_scopes=(),
            base_scope_minimum_each=0,
            base_scope_maximum_each=None,
            visible_stepped_minimum=0,
            visible_stepped_maximum=None,
            upper_band_stepped_bands=(),
            upper_band_stepped_minimum=0,
            body_phenotype_minimum_distinct=1,
            body_phenotype_maximum_each=target,
            roof_archetype_minimum_distinct=1,
            roof_archetype_maximum_each=target,
            chassis_family_minimum_distinct=1,
            chassis_family_maximum_each=target,
            plan_family_minimum_distinct=1,
            plan_family_maximum_each=target,
            body_roof_signature_minimum_distinct=1,
            body_roof_signature_maximum_each=target,
            minimum_pair_distance=0.0,
            shared_language_minimum_composite_distance=0.0,
        )
        preview_joint_facts, preview_joint_maximum_key_counts = (
            build_joint_payload(preview_contract)
        )
        preview_joint_compatibility = build_joint_compatibility(
            preview_contract,
            preview_joint_facts,
        )
        preview_joint_indices = _solve_cardinality_fallback(
            preview_joint_facts,
            preview_joint_compatibility,
            target_count=target,
            maximum_key_counts=preview_joint_maximum_key_counts,
            required_coverage_tags=(),
        )
        if len(preview_joint_indices) > len(joint_indices):
            joint_indices = preview_joint_indices
            joint_facts = preview_joint_facts
            joint_maximum_key_counts = preview_joint_maximum_key_counts
            joint_compatibility = preview_joint_compatibility
            contract = preview_contract
            joint_certificate = {
                "fallback_contract": "diagnostic_preview_contract",
                "status": (
                    "preview_target_reached"
                    if len(preview_joint_indices) >= target
                    else "preview_partial_reached"
                ),
                "maximum_cardinality": len(preview_joint_indices),
                "unsatisfied_constraints": list(
                    joint_certificate.get("unsatisfied_constraints") or ()
                ),
            }
    trace["portfolio_contract_diagnostic_fallback_enabled"] = bool(allow_diagnostic_fallback)
    trace["portfolio_contract_solver_count"] = len(joint_indices)
    trace["portfolio_contract_solver_target_reached"] = (
        len(joint_indices) == target
    )
    trace["portfolio_contract_preview_recovered_count"] = (
        len(joint_indices)
    )
    trace["portfolio_contract_deficits"] = list(
        joint_certificate.get("unsatisfied_constraints") or ()
    )
    trace["portfolio_contract_infeasibility_certificate"] = (
        joint_certificate or None
    )
    if target == 10:
        trace["joint_ten_card_solver_count"] = len(joint_indices)
        trace["joint_ten_card_solver_target_reached"] = (
            len(joint_indices) == 10
        )
        trace["joint_ten_card_infeasibility_certificate"] = (
            joint_certificate or None
        )
    if not joint_indices:
        trace["post_rebalance_count"] = 0
        trace["post_rebalance_capacity_alternative_counts"] = {}
        trace["compatibility_analysis"] = (
            compatibility_analysis.evidence()
        )
        return []
    joint_selected = [
        candidate_universe[index] for index in joint_indices
    ]
    trace["post_rebalance_count"] = len(joint_selected)
    trace["post_rebalance_ground_takes"] = sorted(
        {_portfolio_diversity_key(candidate) for candidate in joint_selected}
    )
    trace["post_rebalance_principle_kind_counts"] = dict(Counter(
        candidate.principle_kind for candidate in joint_selected
    ))
    trace["post_rebalance_capacity_alternative_counts"] = dict(
        sorted(Counter(
            _capacity_alternative_key(candidate)
            for candidate in joint_selected
        ).items())
    )
    trace["compatibility_analysis"] = compatibility_analysis.evidence()
    return joint_selected


def _selection_capacity_diagnostics(
    pool: list[_Candidate],
    selected: list[_Candidate],
    *,
    target: int,
    visual_directive: dict[str, Any] | None = None,
    compatibility_analysis: CompatibilityAnalysis | None = None,
) -> dict[str, Any]:
    """Explain why a hard-pass pool cannot fill the requested portfolio.

    This is observation only. It never relaxes a diversity cap or changes
    selection; it exposes whether supply is lost to exact equivalence,
    silhouette resemblance, BOOK repetition, genotype, roof or chassis caps.
    """
    universe, measured_capacity_universe = _target_hard_pass_universe(pool)
    compatibility_analysis = compatibility_analysis or build_compatibility_analysis(
        universe
    )
    deduplicated_universe_count = len({
        _fingerprint(candidate) for candidate in pool
    })
    selected_ids = {id(candidate) for candidate in selected}
    remaining = [candidate for candidate in universe if id(candidate) not in selected_ids]
    directive = visual_directive or {}
    seed_families = {_seed_family(candidate) for candidate in universe}
    roof_archetypes = {_roof_archetype(candidate) for candidate in universe}
    chassis_families = {_chassis_family(candidate) for candidate in universe}
    seed_cap = max(2, (target + max(1, len(seed_families)) - 1) // max(1, len(seed_families)) + 1)
    section_cap = max(3, target // 2)
    default_roof_cap = min(target, 3)
    roof_caps = {archetype: default_roof_cap for archetype in roof_archetypes}
    for archetype, cap in (directive.get("max_roof_archetype_counts") or {}).items():
        if str(archetype) in roof_caps:
            roof_caps[str(archetype)] = max(1, min(target, int(cap)))
    chassis_caps = _chassis_caps(
        chassis_families,
        target=target,
        directive=directive,
    )
    wedge_cap = max(0, min(
        target,
        int(directive.get("max_wedge_like_count", max(3, target // 5))),
    ))
    pyramidal_cap = max(0, min(
        target,
        int(directive.get("max_pyramidal_like_count", 2)),
    ))
    phenotype_cap = max(2, min(
        target,
        int(directive.get("max_solid_phenotype_count", 3)),
    ))
    operation_usage = Counter(candidate.operation for candidate in selected)
    seed_usage = Counter(_seed_family(candidate) for candidate in selected)
    section_usage = Counter(_section_family(candidate) for candidate in selected)
    roof_usage = Counter(_roof_archetype(candidate) for candidate in selected)
    chassis_usage = Counter(_chassis_family(candidate) for candidate in selected)
    concept_usage = Counter(_design_concept_descriptor(candidate)["concept_key"] for candidate in selected)
    phenotype_usage = Counter(
        _solid_morphology_metrics(candidate)["phenotype"] for candidate in selected
    )
    selected_wedge_count = sum(
        bool(_solid_morphology_metrics(candidate)["wedge_like"])
        for candidate in selected
    )
    selected_pyramidal_count = sum(
        bool(_solid_morphology_metrics(candidate)["pyramidal_like"])
        for candidate in selected
    )
    reason_counts: Counter[str] = Counter()
    exclusive_counts: Counter[str] = Counter()
    signature_counts: Counter[str] = Counter()
    minimum_distances: list[float] = []
    for candidate in remaining:
        distances = [
            compatibility_analysis.distance(candidate, other)
            for other in selected
        ]
        minimum_distance = min(distances, default=1.0)
        minimum_distances.append(minimum_distance)
        reasons: list[str] = []
        if operation_usage[candidate.operation] >= 3:
            reasons.append("book_operation_cap")
        if seed_usage[_seed_family(candidate)] >= seed_cap:
            reasons.append("genotype_cap")
        if section_usage[_section_family(candidate)] >= section_cap:
            reasons.append("section_family_cap")
        if roof_usage[_roof_archetype(candidate)] >= roof_caps.get(_roof_archetype(candidate), target):
            reasons.append("roof_archetype_cap")
        if chassis_usage[_chassis_family(candidate)] >= chassis_caps.get(
            _chassis_family(candidate), target
        ):
            reasons.append("chassis_family_cap")
        if concept_usage[_design_concept_descriptor(candidate)["concept_key"]] >= 2:
            reasons.append("design_concept_cap")
        morphology = _solid_morphology_metrics(candidate)
        if phenotype_usage[morphology["phenotype"]] >= phenotype_cap:
            reasons.append("solid_phenotype_cap")
        if morphology["wedge_like"] and selected_wedge_count >= wedge_cap:
            reasons.append("wedge_like_cap")
        if morphology["pyramidal_like"] and selected_pyramidal_count >= pyramidal_cap:
            reasons.append("pyramidal_like_cap")
        if minimum_distance < PORTFOLIO_SILHOUETTE_DISTANCE:
            reasons.append("silhouette_near_duplicate")
        for reason in reasons:
            reason_counts[reason] += 1
        if len(reasons) == 1:
            exclusive_counts[reasons[0]] += 1
        signature_counts["+".join(sorted(reasons)) or "eligible"] += 1
    return {
        "schema_version": "arr.maas.selection_capacity_diagnostics.v2",
        "raw_pool_count": len(pool),
        "capacity_target_measured_count": len(measured_capacity_universe),
        "capacity_target_pass_count": sum(
            _capacity_target_gate(candidate) is True
            for candidate in measured_capacity_universe
        ),
        "capacity_target_advisory_miss_count": sum(
            _capacity_target_gate(candidate) is False
            for candidate in measured_capacity_universe
        ),
        "capacity_target_rejected_count": 0,
        "capacity_target_authority": "diagnostic_only",
        "achieved_capacity_band_supply_counts": dict(sorted(Counter(
            _capacity_alternative_key(candidate)
            for candidate in universe
            if _capacity_alternative_key(candidate)
        ).items())),
        "achieved_capacity_band_selected_counts": dict(sorted(Counter(
            _capacity_alternative_key(candidate)
            for candidate in selected
            if _capacity_alternative_key(candidate)
        ).items())),
        "requested_capacity_alternative_supply_counts": dict(sorted(Counter(
            _requested_capacity_alternative_key(candidate)
            for candidate in universe
            if _requested_capacity_alternative_key(candidate)
        ).items())),
        "unique_fingerprint_count": deduplicated_universe_count,
        "selection_universe_count": len(universe),
        "exact_fingerprint_collapsed_count": len(pool) - deduplicated_universe_count,
        "selected_count": len(selected),
        "target_count": target,
        "remaining_candidate_count": len(remaining),
        "reason_counts": dict(sorted(reason_counts.items())),
        "exclusive_reason_counts": dict(sorted(exclusive_counts.items())),
        "failure_signature_counts": dict(sorted(signature_counts.items())),
        "minimum_silhouette_distance_summary": {
            "minimum": round(min(minimum_distances, default=1.0), 4),
            "mean": round(sum(minimum_distances) / max(1, len(minimum_distances)), 4),
            "maximum": round(max(minimum_distances, default=1.0), 4),
        },
        "design_concept_supply": {
            "ground_strategy_counts": dict(sorted(Counter(
                _design_concept_descriptor(candidate)["ground_strategy"]
                for candidate in universe
            ).items())),
            "frontage_aligned_candidate_count": sum(
                _design_concept_descriptor(candidate)["frontage_aligned"]
                for candidate in universe
            ),
            "design_concept_key_count": len({
                _design_concept_descriptor(candidate)["concept_key"]
                for candidate in universe
            }),
        },
        "book_principle_kind_supply_counts": dict(sorted(Counter(
            candidate.principle_kind for candidate in universe
        ).items())),
        "book_principle_kind_selected_counts": dict(sorted(Counter(
            candidate.principle_kind for candidate in selected
        ).items())),
        "plan_family_supply_counts": dict(sorted(Counter(
            _plan_family(candidate) for candidate in universe
        ).items())),
        "plan_family_selected_counts": dict(sorted(Counter(
            _plan_family(candidate) for candidate in selected
        ).items())),
        "measured_morphology_selection": {
            "phenotype_counts": dict(sorted(phenotype_usage.items())),
            "wedge_like_count": selected_wedge_count,
            "pyramidal_like_count": selected_pyramidal_count,
        },
        "caps": {
            "book_operation": 3,
            "genotype": seed_cap,
            "section_family": section_cap,
            "roof_archetype_default": default_roof_cap,
            "chassis_family": max(chassis_caps.values(), default=target),
            "chassis_family_by_family": dict(sorted(chassis_caps.items())),
            "silhouette_distance_minimum": PORTFOLIO_SILHOUETTE_DISTANCE,
            "design_concept_key": 2,
            "solid_phenotype": phenotype_cap,
            "wedge_like": wedge_cap,
            "pyramidal_like": pyramidal_cap,
        },
        "compatibility_analysis": compatibility_analysis.evidence(),
    }


def _rebalance_measured_morphologies(
    selected: list[_Candidate],
    universe: list[_Candidate],
    *,
    target: int,
    visual_directive: dict[str, Any],
    capacity_alternative_quotas: dict[str, int] | None = None,
    compatibility_analysis: CompatibilityAnalysis | None = None,
) -> list[_Candidate]:
    """Replace measured wedge/family excess with hard-pass mesh alternatives.

    This is phenotype selection, not a form template: categories and wedge
    status are measured from triangle normals/topology after site fitting.
    """
    _ = capacity_alternative_quotas
    result = list(selected)
    compatibility_analysis = compatibility_analysis or build_compatibility_analysis(
        universe
    )
    silhouette_distance = compatibility_analysis.distance
    available = {_solid_morphology_metrics(candidate)["phenotype"] for candidate in universe}
    required = tuple(
        phenotype for phenotype in dict.fromkeys(
            str(value) for value in visual_directive.get("required_solid_phenotypes") or ()
        )
        if phenotype in available
    )
    wedge_cap = max(0, min(target, int(visual_directive.get("max_wedge_like_count", max(3, target // 5)))))
    pyramidal_cap = max(0, min(target, int(visual_directive.get("max_pyramidal_like_count", 2))))
    phenotype_cap = max(2, min(
        target,
        int(visual_directive.get("max_solid_phenotype_count", 3)),
    ))
    available_ground_strategies = {
        _design_concept_descriptor(item)["ground_strategy"]
        for item in universe
        if _design_concept_descriptor(item)["ground_strategy"] != "misaligned_open_court"
    }
    required_ground_strategy_count = min(3, len(available_ground_strategies))
    aligned_threshold_available = any(
        _design_concept_descriptor(item)["frontage_aligned"] for item in universe
    )
    # Preserve every BOOK language depth successfully established by the
    # joint selector. In particular, phenotype cleanup must not silently
    # replace the portfolio's only aggregation with another base operative.
    protected_principle_kinds = {item.principle_kind for item in result}
    seed_families = {_seed_family(item) for item in universe}
    roof_archetypes = {_roof_archetype(item) for item in universe}
    chassis_families = {_chassis_family(item) for item in universe}
    seed_cap = max(2, (target + max(1, len(seed_families)) - 1) // max(1, len(seed_families)) + 1)
    section_cap = max(3, target // 2)
    default_roof_cap = min(target, 3)
    roof_caps = {archetype: default_roof_cap for archetype in roof_archetypes}
    for archetype, cap in (visual_directive.get("max_roof_archetype_counts") or {}).items():
        if str(archetype) in roof_caps:
            roof_caps[str(archetype)] = max(1, min(target, int(cap)))
    chassis_caps = _chassis_caps(
        chassis_families,
        target=target,
        directive=visual_directive,
    )
    def preserves_design_concepts(candidate: _Candidate, remaining: list[_Candidate]) -> bool:
        final = [*remaining, candidate]
        concept = _design_concept_descriptor(candidate)
        if sum(
            _design_concept_descriptor(item)["concept_key"] == concept["concept_key"]
            for item in remaining
        ) >= 2:
            return False
        grounds = {
            _design_concept_descriptor(item)["ground_strategy"]
            for item in final
            if _design_concept_descriptor(item)["ground_strategy"] != "misaligned_open_court"
        }
        if len(grounds) < required_ground_strategy_count:
            return False
        if aligned_threshold_available and not any(
            _design_concept_descriptor(item)["frontage_aligned"] for item in final
        ):
            return False
        if Counter(item.operation for item in final)[candidate.operation] > 3:
            return False
        if Counter(_seed_family(item) for item in final)[_seed_family(candidate)] > seed_cap:
            return False
        if Counter(_section_family(item) for item in final)[_section_family(candidate)] > section_cap:
            return False
        if Counter(_roof_archetype(item) for item in final)[_roof_archetype(candidate)] > roof_caps.get(_roof_archetype(candidate), target):
            return False
        if Counter(_chassis_family(item) for item in final)[_chassis_family(candidate)] > chassis_caps.get(
            _chassis_family(candidate), target
        ):
            return False
        if not protected_principle_kinds.issubset({item.principle_kind for item in final}):
            return False
        return True

    def counts(items: list[_Candidate]) -> tuple[Counter[str], Counter[str], int]:
        return (
            Counter(_solid_morphology_metrics(item)["phenotype"] for item in items),
            Counter(_portfolio_diversity_key(item) for item in items),
            sum(bool(_solid_morphology_metrics(item)["wedge_like"]) for item in items),
        )

    def replacement_options(
        removed: _Candidate,
        *,
        wanted_phenotype: str = "",
        require_non_wedge: bool = False,
        require_non_pyramidal: bool = False,
    ) -> list[_Candidate]:
        remaining = [item for item in result if item is not removed]
        phenotype_counts, scope_counts, wedge_count = counts(remaining)
        pyramidal_count = sum(
            bool(_solid_morphology_metrics(item)["pyramidal_like"])
            for item in remaining
        )
        used = {id(item) for item in remaining}
        removed_scope = _portfolio_diversity_key(removed)
        must_restore_scope = scope_counts.get(removed_scope, 0) == 0
        options = []
        for candidate in universe:
            if id(candidate) in used:
                continue
            metrics = _solid_morphology_metrics(candidate)
            phenotype = metrics["phenotype"]
            if wanted_phenotype and phenotype != wanted_phenotype:
                continue
            if require_non_wedge and metrics["wedge_like"]:
                continue
            if require_non_pyramidal and metrics["pyramidal_like"]:
                continue
            if must_restore_scope and _portfolio_diversity_key(candidate) != removed_scope:
                continue
            if phenotype_counts[phenotype] >= phenotype_cap:
                continue
            if metrics["wedge_like"] and wedge_count >= wedge_cap:
                continue
            if metrics["pyramidal_like"] and pyramidal_count >= pyramidal_cap:
                continue
            if any(silhouette_distance(candidate, other) < PORTFOLIO_SILHOUETTE_DISTANCE for other in remaining):
                continue
            if not preserves_design_concepts(candidate, remaining):
                continue
            options.append(candidate)
        return options

    def swap_for(
        wanted_phenotype: str = "",
        *,
        reduce_wedge: bool = False,
        reduce_pyramidal: bool = False,
        excess_phenotype: str = "",
    ) -> bool:
        phenotype_counts, _scope_counts, _wedge_count = counts(result)
        if wanted_phenotype:
            # A required calm/curved/etc. candidate is often close to exactly
            # one already selected neighbour.  The old greedy swap tested an
            # unrelated low-score victim first, left that neighbour in place,
            # and then rejected the required candidate as a duplicate. Search
            # candidate/victim pairs causally and remove the actual conflict.
            candidates = sorted(
                (
                    candidate for candidate in universe
                    if _solid_morphology_metrics(candidate)["phenotype"] == wanted_phenotype
                    and not any(candidate is item for item in result)
                ),
                key=lambda item: item.score,
                reverse=True,
            )
            required_set = set(required)
            for candidate in candidates:
                conflicts = [
                    item for item in result
                    if silhouette_distance(candidate, item) < PORTFOLIO_SILHOUETTE_DISTANCE
                ]
                if len(conflicts) > 1:
                    continue
                victims = conflicts or sorted(result, key=lambda item: item.score)
                for removed in victims:
                    removed_phenotype = _solid_morphology_metrics(removed)["phenotype"]
                    if (
                        removed_phenotype in required_set
                        and removed_phenotype != wanted_phenotype
                        and phenotype_counts[removed_phenotype] <= 1
                    ):
                        continue
                    remaining = [item for item in result if item is not removed]
                    remaining_scopes = Counter(_portfolio_diversity_key(item) for item in remaining)
                    if (
                        remaining_scopes.get(_portfolio_diversity_key(removed), 0) == 0
                        and _portfolio_diversity_key(candidate) != _portfolio_diversity_key(removed)
                    ):
                        continue
                    candidate_metrics = _solid_morphology_metrics(candidate)
                    remaining_counts, _unused_scope_counts, remaining_wedges = counts(remaining)
                    if remaining_counts[wanted_phenotype] >= phenotype_cap:
                        continue
                    if candidate_metrics["wedge_like"] and remaining_wedges >= wedge_cap:
                        continue
                    if candidate_metrics["pyramidal_like"] and sum(
                        bool(_solid_morphology_metrics(item)["pyramidal_like"])
                        for item in remaining
                    ) >= pyramidal_cap:
                        continue
                    if any(silhouette_distance(candidate, other) < PORTFOLIO_SILHOUETTE_DISTANCE for other in remaining):
                        continue
                    if not preserves_design_concepts(candidate, remaining):
                        continue
                    result[result.index(removed)] = candidate
                    return True
            return False
        removable = [
            candidate for candidate in result
            if (
                (reduce_wedge and _solid_morphology_metrics(candidate)["wedge_like"])
                or (reduce_pyramidal and _solid_morphology_metrics(candidate)["pyramidal_like"])
                or (excess_phenotype and _solid_morphology_metrics(candidate)["phenotype"] == excess_phenotype)
                or (
                    wanted_phenotype
                    and phenotype_counts[_solid_morphology_metrics(candidate)["phenotype"]] > 1
                )
            )
            and not (
                _solid_morphology_metrics(candidate)["phenotype"] in set(required)
                and phenotype_counts[_solid_morphology_metrics(candidate)["phenotype"]] <= 1
            )
        ]
        removable.sort(key=lambda item: item.score)
        for removed in removable:
            options = replacement_options(
                removed,
                wanted_phenotype=wanted_phenotype,
                require_non_wedge=reduce_wedge,
                require_non_pyramidal=reduce_pyramidal,
            )
            if not options:
                continue
            remaining = [item for item in result if item is not removed]
            winner = max(options, key=lambda candidate: (
                candidate.score
                + (min((silhouette_distance(candidate, other) for other in remaining), default=1.0) * 0.45),
                -float((candidate.source.metadata.get("geometry_program_bridge_evidence") or {}).get("legal_fit_strength") or 0.0),
            ))
            result[result.index(removed)] = winner
            return True
        return False

    # First guarantee each available requested phenotype, then constrain the
    # visually observed wedge and dominant-phenotype shares.
    for phenotype in required:
        if not any(_solid_morphology_metrics(item)["phenotype"] == phenotype for item in result):
            swap_for(phenotype)
    while sum(bool(_solid_morphology_metrics(item)["wedge_like"]) for item in result) > wedge_cap:
        if not swap_for(reduce_wedge=True):
            break
    while sum(bool(_solid_morphology_metrics(item)["pyramidal_like"]) for item in result) > pyramidal_cap:
        if not swap_for(reduce_pyramidal=True):
            break
    while True:
        phenotype_counts, _scope_counts, _wedge_count = counts(result)
        excess = next((key for key, count in phenotype_counts.most_common() if count > phenotype_cap), "")
        if not excess or not swap_for(excess_phenotype=excess):
            break
    if aligned_threshold_available and not any(
        _design_concept_descriptor(item)["frontage_aligned"] for item in result
    ):
        aligned_candidates = sorted(
            (
                item for item in universe
                if _design_concept_descriptor(item)["frontage_aligned"]
                and not any(item is selected_item for selected_item in result)
            ),
            key=lambda item: item.score,
            reverse=True,
        )
        for candidate in aligned_candidates:
            for removed in sorted(result, key=lambda item: item.score):
                remaining = [item for item in result if item is not removed]
                if Counter(_portfolio_diversity_key(item) for item in remaining).get(_portfolio_diversity_key(removed), 0) == 0 and _portfolio_diversity_key(candidate) != _portfolio_diversity_key(removed):
                    continue
                metrics = _solid_morphology_metrics(candidate)
                phenotype_counts, _scope_counts, wedge_count = counts(remaining)
                if phenotype_counts[metrics["phenotype"]] >= phenotype_cap:
                    continue
                if metrics["wedge_like"] and wedge_count >= wedge_cap:
                    continue
                if metrics["pyramidal_like"] and sum(
                    bool(_solid_morphology_metrics(item)["pyramidal_like"])
                    for item in remaining
                ) >= pyramidal_cap:
                    continue
                if any(silhouette_distance(candidate, other) < PORTFOLIO_SILHOUETTE_DISTANCE for other in remaining):
                    continue
                if not preserves_design_concepts(candidate, remaining):
                    continue
                result[result.index(removed)] = candidate
                break
            if any(_design_concept_descriptor(item)["frontage_aligned"] for item in result):
                break
    if len(result) < target:
        for candidate in sorted(universe, key=lambda item: item.score, reverse=True):
            if any(candidate is item for item in result):
                continue
            metrics = _solid_morphology_metrics(candidate)
            phenotype_counts, _scope_counts, wedge_count = counts(result)
            if phenotype_counts[metrics["phenotype"]] >= phenotype_cap:
                continue
            if metrics["wedge_like"] and wedge_count >= wedge_cap:
                continue
            if metrics["pyramidal_like"] and sum(
                bool(_solid_morphology_metrics(item)["pyramidal_like"])
                for item in result
            ) >= pyramidal_cap:
                continue
            if any(silhouette_distance(candidate, other) < PORTFOLIO_SILHOUETTE_DISTANCE for other in result):
                continue
            if not preserves_design_concepts(candidate, result):
                continue
            result.append(candidate)
            if len(result) >= target:
                break

    # Greedy novelty selection can stop at 19 even when a valid 20-set exists:
    # one early high-scoring member may be the sole silhouette conflict for
    # two later topology families.  Do one bounded one-for-two augmentation
    # under the *same* caps. This is portfolio set search, not a threshold
    # relaxation and it never admits a candidate that missed a hard gate.
    protected_scopes = {_portfolio_diversity_key(item) for item in result}

    def portfolio_constraints_hold(items: list[_Candidate]) -> bool:
        if not protected_scopes.issubset({_portfolio_diversity_key(item) for item in items}):
            return False
        if not protected_principle_kinds.issubset({item.principle_kind for item in items}):
            return False
        grounds = {
            _design_concept_descriptor(item)["ground_strategy"]
            for item in items
            if _design_concept_descriptor(item)["ground_strategy"] != "misaligned_open_court"
        }
        if len(grounds) < required_ground_strategy_count:
            return False
        if aligned_threshold_available and not any(
            _design_concept_descriptor(item)["frontage_aligned"] for item in items
        ):
            return False
        if max(Counter(item.operation for item in items).values(), default=0) > 3:
            return False
        if max(Counter(_seed_family(item) for item in items).values(), default=0) > seed_cap:
            return False
        if max(Counter(_section_family(item) for item in items).values(), default=0) > section_cap:
            return False
        if any(
            count > roof_caps.get(archetype, target)
            for archetype, count in Counter(_roof_archetype(item) for item in items).items()
        ):
            return False
        if any(
            count > chassis_caps.get(chassis, target)
            for chassis, count in Counter(_chassis_family(item) for item in items).items()
        ):
            return False
        if max(Counter(
            _design_concept_descriptor(item)["concept_key"] for item in items
        ).values(), default=0) > 2:
            return False
        phenotypes = Counter(_solid_morphology_metrics(item)["phenotype"] for item in items)
        if max(phenotypes.values(), default=0) > phenotype_cap:
            return False
        if any(phenotype not in phenotypes for phenotype in required):
            return False
        if sum(bool(_solid_morphology_metrics(item)["wedge_like"]) for item in items) > wedge_cap:
            return False
        if sum(bool(_solid_morphology_metrics(item)["pyramidal_like"]) for item in items) > pyramidal_cap:
            return False
        return all(
            silhouette_distance(left, right) >= PORTFOLIO_SILHOUETTE_DISTANCE
            for index, left in enumerate(items)
            for right in items[:index]
        )

    while len(result) < target:
        used_ids = {id(item) for item in result}
        outsiders = [item for item in universe if id(item) not in used_ids]
        best: tuple[float, int, _Candidate, _Candidate] | None = None
        for removed_index, removed in enumerate(sorted(result, key=lambda item: item.score)):
            remaining = [item for item in result if item is not removed]
            compatible = [
                item for item in outsiders
                if all(silhouette_distance(item, other) >= PORTFOLIO_SILHOUETTE_DISTANCE for other in remaining)
            ]
            compatible.sort(key=lambda item: (
                item.score
                + min((silhouette_distance(item, other) for other in remaining), default=1.0) * 0.35
            ), reverse=True)
            # The full pool remains evidence, while the bounded local search
            # keeps worst-case pair evaluation predictable.
            compatible = compatible[:36]
            for first_index, first in enumerate(compatible):
                for second in compatible[first_index + 1:]:
                    proposal = [*remaining, first, second]
                    if not portfolio_constraints_hold(proposal):
                        continue
                    objective = (
                        first.score + second.score - removed.score
                        + silhouette_distance(first, second) * 0.45
                    )
                    if best is None or objective > best[0]:
                        best = (objective, result.index(removed), first, second)
            if best is not None:
                break
        if best is None:
            break
        _objective, removed_index, first, second = best
        result[removed_index:removed_index + 1] = [first, second]
    return result[:target]


def _bounded_visual_selection_pool(
    pool: list[_Candidate],
    *,
    per_family_scope: int = 3,
    per_seed_scope: int = 2,
) -> list[_Candidate]:
    """Bound heavy meshes with a MAP-Elites quality-diversity archive.

    The legacy cap arguments remain in the signature for caller compatibility;
    behavior-space policy is now explicit through ``MAAS_QD_*`` settings.
    """
    _ = (per_family_scope, per_seed_scope)
    maximum_size = int(qd_archive_policy()["max_archive_size"])
    unique: list[_Candidate] = []
    fingerprints: set[tuple[Any, ...]] = set()
    for candidate in pool:
        fingerprint = _fingerprint(candidate)
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        unique.append(candidate)
    if len(unique) <= maximum_size:
        # The exact portfolio solver needs every compatible witness while the
        # pool is already within the declared memory bound. Cell quotas are a
        # compaction strategy, not authority to reduce feasible cardinality.
        return unique
    return map_elites_archive(unique)



__all__ = ["_scope_coverage_anchors","_capacity_portfolio_quotas","_select","_selection_capacity_diagnostics","_rebalance_measured_morphologies","_bounded_visual_selection_pool","build_gestalt_compatibility_analysis"]
