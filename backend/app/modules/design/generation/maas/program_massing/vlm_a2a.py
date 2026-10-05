"""Full-pool neighborhood mass search with image-backed A2A graph revision."""

from __future__ import annotations

import json
import hashlib
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from statistics import mean
from collections import Counter
from threading import Lock
from typing import Any

from shapely.geometry import Polygon, box, mapping
from backend.app.modules.design.generation.maas.agents.llm_architect_agent.agent import LLMArchitectAgent
from backend.app.modules.design.generation.maas.agents.llm_architect_agent.graph_revision import apply_critic_graph_edits
from backend.app.modules.design.generation.maas.agents.orchestrator.generative_loop import critic_directive_from_feature
from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall, VerbSequence
from backend.app.modules.design.generation.maas.grammar.component_graph import primary_operation_from_sequence
from backend.app.modules.design.generation.maas.llm_proposals import build_site_context
from backend.app.modules.design.generation.maas.capacity_policy import resolve_massing_capacity_policy
from backend.app.modules.design.generation.maas.preference.loop import feature_preview_png
from backend.app.modules.design.generation.maas.preference.reference_corpus import default_reference_root, load_reference_tree, match_reference_context
from backend.app.modules.design.generation.maas.preference.reference_language_distiller import distill_reference_languages_with_openai, language_briefs_for_generation
from backend.app.modules.design.generation.maas.preference.vlm_scorer import VLM_PROMPT_CONTRACT_VERSION, score_candidate_with_openai_vlm
from backend.app.modules.design.generation.maas.source_geometry import compile_sequence_to_source_mass
from backend.app.modules.design.generation.maas.mass_brain import record_shadow_outcomes, request_shadow_sequences
from backend.app.modules.design.generation.maas.mass_brain_relation_profile import site_aspect_bucket

from backend.app.modules.design.generation.maas.program_massing.benchmark import _render_archive_sheet
from backend.app.modules.design.generation.maas.program_massing.creative import creative_seed_sequences
from backend.app.modules.design.generation.maas.program_massing.graph_archive import GraphBehaviorArchive, bounded_behavior_frontier, field_topology_coverage
from backend.app.modules.design.generation.maas.program_massing.geometry_safety import safe_unary_union
from backend.app.modules.design.generation.maas.program_massing.grl_contract import build_archive_grl_contract
from backend.app.modules.design.generation.maas.program_massing.language_quality import assess_language_geometry
from backend.app.modules.design.generation.maas.program_massing.morphology import DEFAULT_NOVELTY_POLICY, intrinsic_silhouette_distance
from backend.app.modules.design.generation.maas.program_massing.portfolio_solver import PortfolioCandidateFacts, solve_portfolio_beam
from backend.app.modules.design.generation.maas.program_massing.capacity_projection import project_bend_capacity
from backend.app.modules.design.generation.maas.program_massing.scoring import attach_program_massing_evidence
from backend.app.modules.design.generation.maas.program_massing.search import ProgramElite, _descriptor_distance, _feature, _formal_principle, _geometric_language_count, _select_diverse_archive, _topology, search_program_elites
from backend.app.modules.design.generation.maas.program_massing.sequences import program_seed_sequences


def _historical_author_target(cache_path: Path, *, fallback: int) -> int:
    """Validate a historical population against its own authored contract.

    A supplemental cache is archive evidence, not a response to the current
    round's larger population request. Requiring an old 24/29-candidate cache
    to contain 32 candidates aborts after the fresh paid author call succeeds.
    """
    try:
        payload = json.loads(Path(cache_path).read_text(encoding="utf-8"))
        cached_target = int(payload.get("target_count") or 0)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        candidate_count = len(data.get("candidates") or [])
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return max(1, int(fallback))
    if cached_target > 0 and candidate_count >= cached_target:
        return cached_target
    if candidate_count > 0:
        return candidate_count
    return max(1, int(fallback))


def run_neighborhood_vlm_a2a_loop(
    *,
    output_json: Path,
    output_png: Path,
    model: str = "gpt-5.4-mini",
    author_model: str | None = None,
    author_target_count: int = 24,
    author_cache_path: Path | None = None,
    supplemental_author_cache_paths: tuple[Path, ...] = (),
    accepted_seed_result_paths: tuple[Path, ...] = (),
    reference_language_cache_path: Path | None = None,
    generation_feedback: dict[str, Any] | None = None,
    target_count: int = 20,
    review_pool_count: int = 30,
    minimum_vlm_score: float = 0.55,
    capacity_mode: str = "capacity-first",
    workers: int = 4,
    critic_generations: int = 3,
    search_generations: int = 4,
    offspring_per_seed: int = 10,
    author_timeout: float = 180.0,
    require_live_graph_author: bool = True,
    vlm_cache_path: Path | None = None,
    supplemental_vlm_cache_paths: tuple[Path, ...] = (),
    site_polygon: Polygon | None = None,
    site_pnu: str | None = None,
    site_boundary_source: str = "synthetic_benchmark",
    site_access_context: dict[str, Any] | None = None,
    site_access_geometry: dict[str, Any] | None = None,
    far_limit_ratio: float = 3.0,
    mass_brain_enabled: bool = False,
) -> dict[str, Any]:
    base = site_polygon if isinstance(site_polygon, Polygon) else box(0, 0, 60, 40)
    if base.is_empty or not base.is_valid or base.area <= 0:
        raise ValueError("site_polygon must be a valid non-empty metric Polygon")
    far_limit_ratio = max(0.1, float(far_limit_ratio))
    building_type = "neighborhood living"
    author_model = author_model or model
    site_context = build_site_context(
        site_area_m2=float(base.area),
        building_type=building_type,
        limits={"far": far_limit_ratio, "bcr": 0.6, "height": 20.0, "max_seed_floors": 5},
        max_variants=target_count,
        site_polygon=base,
        access_context=site_access_context,
    )
    references = load_reference_tree(default_reference_root())
    resolved_vlm_cache = vlm_cache_path or output_json.with_name(f"{output_json.stem}-vlm-score-cache.json")
    vlm_cache = _load_vlm_cache(resolved_vlm_cache)
    for cache_path in supplemental_vlm_cache_paths:
        # Keys include model, graph, volumes, surfaces and reference IDs, so
        # merging caches cannot transplant a score onto different geometry.
        vlm_cache.update(_load_vlm_cache(cache_path))
    reference_distillation = distill_reference_languages_with_openai(
        references,
        building_type=building_type,
        model=author_model,
        cache_path=(
            reference_language_cache_path
            or output_json.parent / "maas-reference-language-neighborhood-v4.json"
        ),
    )
    feedback = dict(generation_feedback or _author_feedback())
    feedback["reference_language_briefs"] = language_briefs_for_generation(reference_distillation)
    capacity_policy = resolve_massing_capacity_policy(
        building_type=building_type,
        site_area_m2=float(base.area),
        parking_options={"massing_mode": capacity_mode},
    )
    author_batch = LLMArchitectAgent().propose_population(
        site_context=site_context,
        target_count=max(target_count, int(author_target_count)),
        model=author_model,
        batch_size=min(8, max(target_count, int(author_target_count))),
        batch_retries=2,
        batch_workers=3,
        max_openai_batches=4,
        overgenerate_count=4,
        timeout=max(30.0, float(author_timeout)),
        allow_subbatch_recovery=False,
        cache_path=author_cache_path,
        generation_feedback=feedback,
    )
    author_batches = [author_batch]
    for cache_path in supplemental_author_cache_paths:
        historical_target = _historical_author_target(
            cache_path,
            fallback=max(target_count, int(author_target_count)),
        )
        supplemental = LLMArchitectAgent().propose_population(
            site_context=site_context,
            target_count=historical_target,
            model=author_model,
            batch_size=min(8, historical_target),
            batch_retries=2,
            batch_workers=3,
            max_openai_batches=4,
            overgenerate_count=4,
            timeout=max(30.0, float(author_timeout)),
            allow_subbatch_recovery=False,
            cache_path=cache_path,
            # Historical populations are archive evidence, not the fresh
            # response to this round's deficits. Revalidating an old cache
            # against new quotas incorrectly rejects useful graph diversity.
            generation_feedback=None,
        )
        author_batches.append(supplemental)
    if require_live_graph_author:
        for batch in author_batches:
            if int(batch.artifact.get("deterministic_coverage_repair_count") or 0) <= 0:
                continue
            errors = batch.artifact.get("openai_batch_errors") or []
            raise RuntimeError(
                "graph-native author population required deterministic coverage repair; "
                f"rejected instead of presenting fallback as authored: {errors[:3]}"
            )
    authored_sequences = tuple({
        sequence.name: sequence
        for batch in author_batches
        for sequence in batch.sequences
    }.values())
    persisted_accepted_sequences: list[VerbSequence] = []
    for result_path in accepted_seed_result_paths:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        for record in payload.get("accepted_sequences") or []:
            sequence = _sequence_from_record(record)
            if sequence is not None:
                persisted_accepted_sequences.append(sequence)
    base_seeds = tuple({
        sequence.name: sequence
        for sequence in (
            *persisted_accepted_sequences,
            *authored_sequences,
            *program_seed_sequences(building_type),
            *creative_seed_sequences(),
        )
    }.values())
    # Exact persisted/authored seeds belong to the baseline generator. They
    # must remain available when Mass-Brain is disabled, otherwise an ON/OFF
    # comparison also removes proven baseline geometry and is not an ablation.
    persisted_seed_elites = [
        elite
        for sequence in persisted_accepted_sequences
        if (elite := _compile_verified(
            base,
            sequence,
            building_type=building_type,
            capacity_policy=capacity_policy,
            far_limit_ratio=far_limit_ratio,
        )) is not None
    ]
    authored_seed_elites = [
        elite
        for sequence in authored_sequences
        if (elite := _compile_verified(
            base,
            sequence,
            building_type=building_type,
            capacity_policy=capacity_policy,
            far_limit_ratio=far_limit_ratio,
        )) is not None
    ]

    # Mass-Brain learns from executable geometry, not raw labels. Its stricter
    # no-capacity-projection evidence pass is isolated from the baseline pool
    # so disabling memory changes only memory/proposal work.
    evaluated_base_seed_elites: dict[str, ProgramElite] = {}
    if mass_brain_enabled:
        for sequence in base_seeds:
            elite = _compile_verified(
                base,
                sequence,
                building_type=building_type,
                capacity_policy=capacity_policy,
                far_limit_ratio=far_limit_ratio,
                _allow_capacity_projection=False,
            )
            if elite is not None:
                evaluated_base_seed_elites[sequence.name] = elite
    mass_brain_source_sequences = tuple(
        elite.sequence for elite in evaluated_base_seed_elites.values()
    )
    brain_options = {
        "mass_brain": {"enabled": bool(mass_brain_enabled), "count": min(20, max(8, target_count))}
    }
    mass_brain_batch = request_shadow_sequences(
        source_sequences=mass_brain_source_sequences,
        project_key=str(site_pnu or output_json.stem),
        program_type=building_type,
        site_aspect=site_aspect_bucket(base),
        parking_options=brain_options,
        source_features_by_sequence={
            elite.sequence.name: elite.feature
            for elite in evaluated_base_seed_elites.values()
        },
    )
    mass_brain_rollout = mass_brain_batch.artifact.get("rollout") if isinstance(mass_brain_batch.artifact.get("rollout"), dict) else {}
    mass_brain_active_slots = (
        min(4, max(0, int(mass_brain_rollout.get("slots") or 0)))
        if mass_brain_rollout.get("mode") == "active"
        else 0
    )
    seeds = tuple({
        sequence.name: sequence
        for sequence in (
            *base_seeds,
            *(mass_brain_batch.sequences if mass_brain_active_slots else ()),
        )
    }.values())
    mass_brain_seed_elites = [
        elite
        for sequence in mass_brain_batch.sequences
        if (elite := _compile_verified(
            base,
            sequence,
            building_type=building_type,
            capacity_policy=capacity_policy,
            far_limit_ratio=far_limit_ratio,
        )) is not None
    ]
    for elite in mass_brain_seed_elites:
        proposal = mass_brain_batch.proposals_by_sequence.get(elite.sequence.name) or {}
        elite.feature.setdefault("properties", {})["mass_brain_shadow"] = {
            "schema_version": "arr.maas.mass_brain_candidate.v1",
            "proposal_id": proposal.get("proposalId"),
            "relation_profile": proposal.get("relationProfile") or {},
            "behavior_cell": proposal.get("behaviorCell"),
            "score_breakdown": proposal.get("scoreBreakdown") or {},
            "selection_effect": "none_shadow_only",
        }
    # Search generations may mutate a seed immediately. Keep the exact
    # executable graph in the archive as well; otherwise both an append-only
    # accepted seed and a fresh authored graph silently become only a g0 child.
    # This distinction matters for curve control fields: a generic search
    # mutation can erase the authored path before the VLM ever sees it.
    clean_pool: list[ProgramElite] = [*persisted_seed_elites, *authored_seed_elites]
    _, search_report = search_program_elites(
        base,
        building_type=building_type,
        height=15.0,
        floors=5,
        generations=max(1, int(search_generations)),
        offspring_per_seed=max(2, int(offspring_per_seed)),
        random_seed=417,
        target_count=target_count,
        seed_sequences=seeds,
        minimum_architectural_score=0.76,
        selection_minimum_distance=0.14,
        accepted_sink=clean_pool,
    )
    capacity_pool: list[ProgramElite] = []
    for elite in clean_pool:
        far_utilization = _source_far_utilization(
            elite.source,
            site_area=float(base.area),
            floors=5,
            far_limit_ratio=far_limit_ratio,
        )
        props = elite.feature.setdefault("properties", {})
        # Site response is part of the visual evidence, not only an author
        # prompt fact. The preview renderer draws this metric parcel outline.
        props["site_boundary_geometry"] = mapping(base)
        props["site_boundary_source"] = site_boundary_source
        props["site_access_context"] = dict(site_access_context or {})
        props["site_access_geometry"] = site_access_geometry
        props["normalized_far_utilization"] = far_utilization
        props["massing_capacity_policy"] = dict(capacity_policy)
        if far_utilization >= float(capacity_policy["min_far_utilization"]):
            target = max(float(capacity_policy["target_far_utilization"]), 1e-9)
            capacity_fit = min(1.0, far_utilization / target)
            props["capacity_target_fit"] = round(capacity_fit, 4)
            capacity_pool.append(replace(elite, score=round(elite.score * 0.82 + capacity_fit * 0.18, 6)))
    review_group_minimums = {
        "continuous_field": 1,
        # Capability, not monoculture: require one reviewable agent-authored
        # oblique envelope while keeping most of the board in other languages.
        "oblique_envelope": 1,
        "carved_void": 1,
        "bridge_interlock": 1,
        "folded_section": 1,
        # The final board requires three. Review a surplus so one weak/boxy
        # step candidate cannot collapse the whole language cell.
        "stepped_capacity": 3,
        "cluster_field": 1,
    }
    behavior_archive = GraphBehaviorArchive()
    behavior_archive.extend(capacity_pool)
    behavior_frontier = bounded_behavior_frontier(
        capacity_pool,
        per_cell=4,
        minimum_count=max(120, int(review_pool_count) * 5),
    )
    # MAP-Elites is an audit/archive and mutation source. Do not collapse the
    # review frontier to one item per coarse behavior cell before the stricter
    # geometric-distance selector has had a chance to build the 24-parent set.
    parents = _select_language_balanced_archive(
        behavior_frontier,
        target_count=max(target_count, int(review_pool_count)),
        # This is a review frontier, not the final archive. A strict scalar
        # distance here discarded authored bend/fold/cluster graphs before the
        # image critic ever saw them because their FAR/coverage resembled a bar.
        minimum_distance=0.08,
        minimum_groups=review_group_minimums,
        minimum_field_topologies={"parallel": 1, "branched": 1},
        minimum_editable_field_count=2,
        minimum_authored_count=max(8, int(review_pool_count) // 2),
        minimum_capacity_target_count=max(8, (int(review_pool_count) * 2 + 4) // 5),
        capacity_target_utilization=float(capacity_policy["target_far_utilization"]),
        # Proven candidates remain available as parents, but cannot occupy the
        # complete VLM frontier. Fresh graph/search variants must be reviewed.
        maximum_persisted_count=max(8, (int(review_pool_count) * 3) // 5),
        minimum_fresh_count=max(6, (int(review_pool_count) * 2) // 5),
        maximum_groups={
            # This is the VLM review frontier, not the final 20-card quota.
            # The previous caps summed to 28 and made review_pool_count=48
            # impossible before visual scoring even started.
            "carved_void": 8,
            "stepped_capacity": 8,
            "continuous_field": 8,
            "oblique_envelope": 4,
            "bridge_interlock": 8,
            "folded_section": 8,
            "cluster_field": 8,
            "calm_anchor": 2,
        },
    )
    trace: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="maas-neighborhood-vlm-a2a-") as temporary:
        preview_root = Path(temporary)
        parent_scored = _score_population(
            parents, references, preview_root, model=model, workers=workers,
            score_cache=vlm_cache, score_cache_path=resolved_vlm_cache,
        )
        _save_vlm_cache(resolved_vlm_cache, vlm_cache, model=model)
        for parent_index, (parent, vlm, matches) in enumerate(parent_scored):
            _attach_vlm(parent.feature, vlm, matches)
            parent = _with_dual_objective_score(parent, vlm)
            parent_scored[parent_index] = (parent, vlm, matches)
        # Critic revision is a branching search, not destructive in-place
        # optimization. Preserve every distinct VLM-scored geometry so a
        # child that improves one scalar score but later fails the strict
        # visual floor cannot erase its valid parent or an earlier generation.
        critic_geometry_archive: dict[str, ProgramElite] = {}
        for parent, _, _ in parent_scored:
            _retain_geometry_best(critic_geometry_archive, parent)
        # The VLM parent frontier is an exploration budget, not the durable
        # accepted archive. Score every exact accepted seed (normally a cache
        # hit) so a proven diagram does not vanish merely because it was not
        # chosen as one of this run's mutation parents.
        persisted_scored = _score_population(
            persisted_seed_elites,
            references,
            preview_root,
            model=model,
            workers=workers,
            score_cache=vlm_cache,
            score_cache_path=resolved_vlm_cache,
        )
        _save_vlm_cache(resolved_vlm_cache, vlm_cache, model=model)
        persisted_parent_elites: list[ProgramElite] = []
        for item, vlm, matches in persisted_scored:
            _attach_vlm(item.feature, vlm, matches)
            persisted_parent_elites.append(_with_dual_objective_score(item, vlm))
        mass_brain_scored = _score_population(
            mass_brain_seed_elites,
            references,
            preview_root,
            model=model,
            workers=workers,
            score_cache=vlm_cache,
            score_cache_path=resolved_vlm_cache,
        )
        _save_vlm_cache(resolved_vlm_cache, vlm_cache, model=model)
        mass_brain_scored_elites: list[ProgramElite] = []
        for item, vlm, matches in mass_brain_scored:
            _attach_vlm(item.feature, vlm, matches)
            mass_brain_scored_elites.append(_with_dual_objective_score(item, vlm))
        mass_brain_artifact = dict(mass_brain_batch.artifact)
        mass_brain_artifact["vlm_evaluated_count"] = len(mass_brain_scored_elites)
        mass_brain_artifact["outcomes"] = record_shadow_outcomes(
            project_key=str(site_pnu or output_json.stem),
            proposals_by_operator=mass_brain_batch.proposals_by_sequence,
            features_by_operator={item.sequence.name: item.feature for item in mass_brain_scored_elites},
            run_id=f"program-massing:{output_json.stem}",
        ) if mass_brain_batch.proposals_by_sequence else {"recorded_count": 0, "failed_count": 0}
        current_scored = list(parent_scored)
        seen_child_graphs: set[str] = set()
        child_scored_count = 0
        for generation in range(1, max(1, int(critic_generations)) + 1):
            pending: list[tuple[int, ProgramElite, dict[str, Any]]] = []
            generation_records: list[dict[str, Any]] = []
            for parent_index, (parent, vlm, matches) in enumerate(current_scored):
                directive = critic_directive_from_feature(parent.feature)
                record = {
                    "generation": generation,
                    "parent": parent.sequence.name,
                    "parent_vlm_score": round(_feature_vlm_design_score(parent.feature), 4),
                    "reference_count": len(matches),
                    "reference_matches": [_reference_summary(match) for match in matches],
                    "critic_actions": list(directive.actions),
                    "graph_edits": [edit.__dict__ for edit in directive.graph_edits],
                    "children": [],
                }
                revised_sequences = apply_critic_graph_edits(parent.sequence, directive)
                record["graph_revision_status"] = (
                    "candidate_emitted"
                    if revised_sequences
                    else "no_valid_edit_applied"
                    if directive.graph_edits
                    else "no_graph_edit_requested"
                )
                for sequence in revised_sequences:
                    graph_key = json.dumps(sequence.to_list(), sort_keys=True) + "|" + "|".join(sequence.notes)
                    if graph_key in seen_child_graphs:
                        continue
                    seen_child_graphs.add(graph_key)
                    child = _compile_verified(
                        base, sequence, building_type=building_type,
                        capacity_policy=capacity_policy, far_limit_ratio=far_limit_ratio,
                    )
                    if child is None:
                        record["children"].append({"sequence": sequence.name, "status": "compile_or_hard_gate_rejected"})
                        continue
                    if _same_source_geometry(parent.source, child.source):
                        record["children"].append({
                            "sequence": sequence.name,
                            "status": "graph_edit_no_geometry_change",
                        })
                        continue
                    child_record: dict[str, Any] = {"sequence": sequence.name, "status": "awaiting_vlm_recheck"}
                    record["children"].append(child_record)
                    pending.append((parent_index, child, child_record))
                generation_records.append(record)
            if not pending:
                trace.extend(generation_records)
                break
            rescored = _score_population(
                [child for _, child, _ in pending], references, preview_root,
                model=model, workers=workers, score_cache=vlm_cache,
                score_cache_path=resolved_vlm_cache,
            )
            _save_vlm_cache(resolved_vlm_cache, vlm_cache, model=model)
            child_scored_count += len(rescored)
            accepted_count = 0
            for (parent_index, child, child_record), (_, child_vlm_payload, child_matches) in zip(pending, rescored):
                _attach_vlm(child.feature, child_vlm_payload, child_matches)
                child = _with_dual_objective_score(child, child_vlm_payload)
                _retain_geometry_best(critic_geometry_archive, child)
                parent, parent_vlm_payload, _ = current_scored[parent_index]
                parent_vlm = _feature_vlm_design_score(parent.feature)
                child_vlm = _feature_vlm_design_score(child.feature)
                parent_program = float(parent.feature["properties"]["program_massing_evidence"]["program_fit_score"])
                child_program = float(child.feature["properties"]["program_massing_evidence"]["program_fit_score"])
                improved = child_vlm >= parent_vlm + 0.015 and child_program >= parent_program - 0.03
                child_record.update({
                    "child_vlm_score": round(child_vlm, 4),
                    "child_program_score": child_program,
                    "accepted": improved,
                })
                if improved:
                    current_scored[parent_index] = (child, child_vlm_payload, child_matches)
                    behavior_archive.add(child)
                    accepted_count += 1
            trace.extend(generation_records)
            if accepted_count == 0:
                break
        finalists_by_geometry = dict(critic_geometry_archive)
        for item in persisted_parent_elites:
            _retain_geometry_best(finalists_by_geometry, item)
        for item in sorted(mass_brain_scored_elites, key=lambda candidate: candidate.score, reverse=True)[:mass_brain_active_slots]:
            item.feature["properties"]["mass_brain_shadow"]["selection_effect"] = "promotion_eligible_active_pool"
            _retain_geometry_best(finalists_by_geometry, item)
        finalists = list(finalists_by_geometry.values())

    visual_floor_rejections = [
        {
            "candidate": item.sequence.name,
            "language_group": _language_group(item),
            "vlm_design_score": round(_feature_vlm_design_score(item.feature), 4),
            "language_adjusted_vlm_score": (item.feature.get("properties") or {}).get("language_adjusted_vlm_score"),
            "reasons": _visual_floor_failure_reasons(item, minimum_score=minimum_vlm_score),
        }
        for item in finalists
        if _visual_floor_failure_reasons(item, minimum_score=minimum_vlm_score)
    ]
    visual_floor_pool = [
        item for item in finalists
        if not _visual_floor_failure_reasons(item, minimum_score=minimum_vlm_score)
    ]
    final_group_minimums = {
        "continuous_field": 2,
        "oblique_envelope": 1,
        "carved_void": 3,
        "bridge_interlock": 2,
        "folded_section": 2,
        "stepped_capacity": 2,
        "cluster_field": 2,
    }
    final_group_maximums = {
        # Courtyard, atrium, notch, embedded void and carved monolith share a
        # portfolio label but not a single visible idea. Descriptor distance
        # and the per-principle cap still prevent duplicates, so permit one
        # additional geometrically distinct void language when other groups
        # cannot fill the twentieth cell without violating distance.
        # Six carved candidates made the board read as repeated notched boxes
        # even when descriptor distance passed. Preserve room for an extra
        # continuous, folded, bridge, or coherent field language instead.
        "carved_void": 5,
        "stepped_capacity": 3,
        "continuous_field": 4,
        "oblique_envelope": 2,
        "bridge_interlock": 4,
        "folded_section": 4,
        "cluster_field": 4,
        "calm_anchor": 1,
    }
    # Never fill a 20-card sheet with a known visual-floor failure. Returning
    # 19 is an honest failed generation and triggers a new author population.
    final_archive = _select_language_balanced_archive(
        visual_floor_pool,
        target_count=target_count,
        minimum_distance=0.16,
        minimum_groups=final_group_minimums,
        minimum_field_topologies={"parallel": 1, "branched": 1},
        # Reserve several geometries whose path/section genotype can be
        # changed by both bounded search and the VLM critic. A portfolio of
        # twenty immutable box proxies cannot evolve from image feedback.
        minimum_editable_field_count=max(2, target_count // 6),
        minimum_authored_count=max(1, target_count // 2),
        maximum_groups=final_group_maximums,
        minimum_capacity_target_count=max(1, (target_count * 2 + 4) // 5),
        capacity_target_utilization=float(capacity_policy["target_far_utilization"]),
        # Stability without stagnation: at least half of the board may be
        # replaced when better graph-native candidates survive the same gates.
        maximum_persisted_count=max(1, (target_count * 4) // 5),
        minimum_fresh_count=max(2, target_count // 5),
    )
    capacity_target_required_count = max(1, (target_count * 2 + 4) // 5)
    final_archive, capacity_rebalance_audit = _rebalance_capacity_archive(
        final_archive,
        visual_floor_pool,
        required_count=capacity_target_required_count,
        target_utilization=float(capacity_policy["target_far_utilization"]),
        minimum_groups=final_group_minimums,
        minimum_field_topologies={"parallel": 1, "branched": 1},
        maximum_groups=final_group_maximums,
        minimum_distance=0.16,
        minimum_editable_field_count=max(2, target_count // 6),
        minimum_authored_count=max(1, target_count // 2),
        maximum_persisted_count=max(1, (target_count * 4) // 5),
        minimum_fresh_count=max(2, target_count // 5),
    )
    final_selection_audit = _archive_selection_audit(
        visual_floor_pool,
        final_archive,
        minimum_distance=0.16,
    )
    final_group_counts = _language_group_counts(final_archive)
    missing_groups = {
        group: required - final_group_counts.get(group, 0)
        for group, required in final_group_minimums.items()
        if final_group_counts.get(group, 0) < required
    }
    near_duplicate_pairs = _near_duplicate_pairs(final_archive, threshold=0.20)
    morphology_repeat_pairs = _morphology_repeat_pairs(final_archive)
    silhouette_repeat_pairs = _silhouette_repeat_pairs(final_archive)
    geometric_language_count = _geometric_language_count(final_archive, threshold=0.20)
    accepted_ids = {id(item) for item in final_archive}
    visual_reasons_by_name = {
        str(record["candidate"]): list(record.get("reasons") or [])
        for record in visual_floor_rejections
    }
    selection_reasons_by_name = {
        str(record["candidate"]): list(record.get("reasons") or [])
        for record in final_selection_audit.get("rejection_samples") or []
    }
    # The primary human-review artifact must always show the full 20-candidate
    # comparison. Quality gates decide the badge, not whether the card
    # disappears. Accepted-only evidence is written separately so a 2/20
    # failure can never be mistaken for a generator that produced only two.
    review_archive = list(sorted(final_archive, key=lambda item: item.score, reverse=True))
    review_archive.extend(
        item
        for item in sorted(finalists, key=lambda candidate: candidate.score, reverse=True)
        if id(item) not in accepted_ids
        and all(id(item) != id(existing) for existing in review_archive)
    )
    review_archive = review_archive[:target_count]
    review_rows: list[dict[str, Any]] = []
    for item in review_archive:
        accepted = id(item) in accepted_ids
        reasons = (
            []
            if accepted
            else visual_reasons_by_name.get(item.sequence.name)
            or selection_reasons_by_name.get(item.sequence.name)
            or ["not_selected_by_balanced_archive"]
        )
        props = item.feature.setdefault("properties", {})
        props["review_status"] = "accept" if accepted else "reject"
        props["review_reasons"] = list(reasons)
        review_rows.append({
            "variant_id": props.get("variant_id"),
            "status": props["review_status"],
            "reasons": list(reasons),
            "language_group": _language_group(item),
            "vlm_design_score": round(_feature_vlm_design_score(item.feature), 4),
            "language_adjusted_vlm_score": props.get("language_adjusted_vlm_score"),
            "language_geometry_quality": props.get("language_geometry_quality"),
        })
    review_accepted_count = sum(1 for row in review_rows if row["status"] == "accept")
    _render_archive_sheet(
        [item.feature for item in review_archive],
        output_png,
        title=(
            "MAAS - neighborhood living: 20-candidate visual review "
            f"({review_accepted_count} accepted / {len(review_archive) - review_accepted_count} rejected)"
        ),
    )
    accepted_output_png = output_png.with_name(f"{output_png.stem}-accepted-only{output_png.suffix}")
    _render_archive_sheet(
        [item.feature for item in final_archive],
        accepted_output_png,
        title=f"MAAS - accepted-only diagnostic ({len(final_archive)}/{target_count})",
    )
    rows = []
    for elite in final_archive:
        props = elite.feature["properties"]
        signature = props["source_signature"]
        preference = props.get("preference_distillation") or {}
        rows.append({
            "variant_id": props["variant_id"],
            "language_group": _language_group(elite),
            "formal_principle": signature.get("formal_principle"),
            "volume_count": len(elite.source.volumes),
            "surface_count": signature.get("surface_count"),
            "program_fit_score": props["program_massing_evidence"]["program_fit_score"],
            "normalized_far_utilization": props.get("normalized_far_utilization"),
            "capacity_target_fit": props.get("capacity_target_fit"),
            "vlm_score": round(mean((preference.get("concept_scores") or {"missing": 0.0}).values()), 4),
            "vlm_model": preference.get("vlm_model"),
            "reference_count": len(preference.get("reference_matches") or []),
            "critic_actions": preference.get("critic_actions") or [],
            "vlm_design_score": round(_feature_vlm_design_score(elite.feature), 4),
            "language_adjusted_vlm_score": props.get("language_adjusted_vlm_score"),
            "language_geometry_quality": props.get("language_geometry_quality"),
        })
    capacity_target_met_count = sum(
        1
        for row in rows
        if float(row.get("normalized_far_utilization") or 0.0)
        >= float(capacity_policy["target_far_utilization"])
    )
    authored_selected_count = sum(1 for item in final_archive if _is_live_authored_graph(item))
    authored_selected_required_count = max(1, target_count // 2)
    authored_field_topology_coverage = field_topology_coverage(authored_sequences)
    selected_field_topology_coverage = field_topology_coverage(
        item.sequence for item in final_archive
    )
    persisted_selected_count = sum(1 for item in final_archive if _is_persisted_accepted_seed(item))
    fresh_selected_count = len(final_archive) - persisted_selected_count
    mass_brain_selected_count = sum(
        1
        for item in final_archive
        if isinstance(item.feature.get("properties", {}).get("mass_brain_shadow"), dict)
    )
    mass_brain_artifact["final_selection_admitted_count"] = mass_brain_selected_count
    mass_brain_artifact["final_selection_effect"] = (
        "candidate_admitted"
        if mass_brain_selected_count
        else "none"
    )
    site_record = {
        "pnu": site_pnu,
        "boundary_source": site_boundary_source,
        "area_m2": round(float(base.area), 2),
        "bounds_m": [round(float(value), 3) for value in base.bounds],
        "far_limit_ratio": round(far_limit_ratio, 4),
        "access_context": dict(site_access_context or {}),
        "access_geometry": site_access_geometry,
        "synthetic": site_polygon is None,
    }
    morphology_relations = [
        {
            "left": left_index,
            "right": right_index,
            "distance": round(distance, 4),
            "repeat_kind": DEFAULT_NOVELTY_POLICY.repeat_kind(
                distance,
                same_principle=_formal_principle(left) == _formal_principle(right),
                same_topology=_topology(left) == _topology(right),
            ),
        }
        for left_index, left in enumerate(final_archive)
        for right_index, right in enumerate(final_archive[left_index + 1:], start=left_index + 1)
        if (distance := _descriptor_distance(left, right))
        <= DEFAULT_NOVELTY_POLICY.graph_audit_neighbor
    ]
    grl_path = output_json.with_name(f"{output_json.stem}-grl.json")
    grl_contract = build_archive_grl_contract(
        dataset_id=f"maas:{site_pnu or output_json.stem}",
        title=f"MAAS morphology audit - {site_pnu or 'synthetic site'}",
        source_path=str(output_json),
        site=site_record,
        candidates=rows,
        morphology_relations=morphology_relations,
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)
    grl_path.write_text(json.dumps(grl_contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "schema_version": "arr.maas.neighborhood_vlm_a2a_loop.v1",
        "status": "technical_pass" if len(rows) == target_count and all(row["reference_count"] > 0 for row in rows) else "technical_fail",
        "visual_status": (
            "review_required"
            if (
                len(final_archive) == target_count
                and not missing_groups
                and not near_duplicate_pairs
                and not morphology_repeat_pairs
                and not silhouette_repeat_pairs
                and geometric_language_count >= max(1, target_count - 2)
                and capacity_target_met_count >= capacity_target_required_count
                and authored_selected_count >= authored_selected_required_count
                and authored_field_topology_coverage["hard_pass"]
                and selected_field_topology_coverage["hard_pass"]
                and persisted_selected_count <= max(1, (target_count * 4) // 5)
                and fresh_selected_count >= max(2, target_count // 5)
            )
            else "automatic_visual_floor_failed"
        ),
        "legal_projection_status": "not_run",
        "site": site_record,
        "raw_evaluated_count": search_report["evaluated_count"],
        "clean_pool_count": len(clean_pool),
        "capacity_pool_count": len(capacity_pool),
        "vlm_parent_count": len(parent_scored),
        "vlm_child_count": child_scored_count,
        "critic_geometry_archive_count": len(critic_geometry_archive),
        "selected_count": len(rows),
        "model": model,
        "vlm_score_cache": {"path": str(resolved_vlm_cache), "entry_count": len(vlm_cache)},
        "supplemental_vlm_cache_paths": [str(path) for path in supplemental_vlm_cache_paths],
        "author_model": author_model,
        "author_artifact": author_batch.artifact,
        "author_population_artifacts": [batch.artifact for batch in author_batches],
        "author_population_count": len(author_batches),
        "mass_brain_shadow": mass_brain_artifact,
        "authored_sequence_count": len(authored_sequences),
        "persisted_accepted_seed_count": len(persisted_accepted_sequences),
        "persisted_accepted_exact_compile_count": len(persisted_seed_elites),
        "authored_exact_compile_count": len(authored_seed_elites),
        "persisted_selected_count": persisted_selected_count,
        "persisted_selected_maximum": max(1, (target_count * 4) // 5),
        "fresh_selected_count": fresh_selected_count,
        "fresh_selected_minimum": max(2, target_count // 5),
        "seed_count": len(seeds),
        "generation_feedback": feedback,
        "capacity_policy": capacity_policy,
        "critic_generations": max(1, int(critic_generations)),
        "search_generations": max(1, int(search_generations)),
        "offspring_per_seed": max(2, int(offspring_per_seed)),
        "graph_behavior_archive": behavior_archive.evidence(),
        "behavior_frontier_pool_count": len(behavior_frontier),
        "capacity_target_met_count": capacity_target_met_count,
        "capacity_target_required_count": capacity_target_required_count,
        "authored_selected_count": authored_selected_count,
        "authored_field_topology_coverage": authored_field_topology_coverage,
        "selected_field_topology_coverage": selected_field_topology_coverage,
        "authored_selected_required_count": authored_selected_required_count,
        "minimum_vlm_score": minimum_vlm_score,
        "visual_floor_pool_count": len(visual_floor_pool),
        "visual_floor_rejection_counts": _reason_counts(visual_floor_rejections),
        "visual_floor_rejection_samples": visual_floor_rejections[:20],
        "final_selection_audit": final_selection_audit,
        "capacity_rebalance_audit": capacity_rebalance_audit,
        "final_language_group_counts": final_group_counts,
        "missing_language_groups": missing_groups,
        "geometric_language_count": geometric_language_count,
        "near_duplicate_pairs": near_duplicate_pairs,
        "morphology_repeat_pairs": morphology_repeat_pairs,
        "silhouette_repeat_pairs": silhouette_repeat_pairs,
        "morphology_neighbor_relations": morphology_relations,
        "grl_audit": {
            "schema_version": "arr.maas.grl_audit.v1",
            "role": "evidence_and_lineage_viewer_not_geometry_generator",
            "path": str(grl_path),
            "relation_count": len(morphology_relations),
            "rotation_invariant_duplicate_count": len(morphology_repeat_pairs),
        },
        "reference_corpus_count": len(references),
        "reference_language_distillation": reference_distillation,
        "review_candidate_count": len(review_rows),
        "review_rows": review_rows,
        "accepted_sequences": [_sequence_record(item.sequence) for item in final_archive],
        "rows": rows,
        "trace": trace,
        "png": str(output_png),
        "accepted_only_png": str(accepted_output_png),
    }
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _author_feedback() -> dict[str, Any]:
    """Topology-level design pressure with no parcel coordinates or form template."""
    return {
        "schema_version": "arr.maas.vlm_generation_feedback.v1",
        "source": "direct_visual_review_v3",
        "must_use": [
            "one legible dominant gesture",
            "inhabitable public ground relationship",
            "topology-changing void bridge fold bend or courtyard operation",
            "site-conditioned access and long-axis response",
        ],
        "avoid": [
            "podium with arbitrary small upper box",
            "repeated stepback tower",
            "decorative fragments",
            "stacked unrelated cuboids",
        ],
        "quota": {
            "continuous_or_bent": 4,
            "carved_or_courtyard": 4,
            "bridge_or_interlock": 4,
            "folded_or_sloped_section": 4,
            "stepped_or_terraced_anchor": 2,
            # Survival buffer only. Final selection still caps this language
            # at two, so the board gains the capability without becoming an
            # all-polygon exercise.
            "oblique_or_polygon_envelope": 3,
            "cluster_or_branch": 3,
        },
        "required_language_groups": {
            "oblique_envelope": 1,
            "cluster_field": 2,
        },
        "formal_principle_targets": [
            "figure_ground", "carved_solid", "continuous_field", "folded_section",
            "split_bridge", "datum_shift", "courtyard_atrium", "stepped_landform",
            "agent_oblique_polygon_envelope",
        ],
        "reference_precedent_targets": [
            "BIG: one diagrammatic operation with programmatic consequence",
            "OMA: program and circulation expressed as sectional mass logic",
            "ArchDaily civic and neighborhood projects: readable public ground and coherent silhouette",
        ],
        "critic_actions": {
            "author_new_topology": 20,
            "reject_box_bias": 20,
            "preserve_clean_mass": 20,
        },
    }


def generation_feedback_from_result(result: dict[str, Any]) -> dict[str, Any]:
    """Turn one failed visual generation into pressure for the next author.

    This is population-level feedback, not a geometry template: the next LLM
    author still chooses topology and parameters, while the diagnosis carries
    forward what the image critic repeatedly rejected.
    """
    feedback = _author_feedback()
    action_counts: Counter[str] = Counter()
    bottom: list[dict[str, Any]] = []
    top: list[dict[str, Any]] = []
    for record in result.get("trace") or []:
        if not isinstance(record, dict):
            continue
        actions = [str(item) for item in record.get("critic_actions") or []]
        action_counts.update(actions)
        brief = {
            "candidate": str(record.get("parent") or ""),
            "vlm_score": float(record.get("parent_vlm_score") or 0.0),
            "critic_actions": actions,
        }
        if actions and any(action in actions for action in (
            "too_box_like", "weak_form_continuity", "too_fragmented", "weak_primary_mass"
        )):
            bottom.append(brief)
        elif brief["vlm_score"] >= 0.70:
            top.append(brief)
    missing = result.get("missing_language_groups") if isinstance(result.get("missing_language_groups"), dict) else {}
    selected_field_coverage = (
        result.get("selected_field_topology_coverage")
        if isinstance(result.get("selected_field_topology_coverage"), dict)
        else {}
    )
    missing_selected_field_topologies = (
        selected_field_coverage.get("missing")
        if isinstance(selected_field_coverage.get("missing"), dict)
        else {}
    )
    authored_field_coverage = (
        result.get("authored_field_topology_coverage")
        if isinstance(result.get("authored_field_topology_coverage"), dict)
        else {}
    )
    missing_authored_field_topologies = (
        authored_field_coverage.get("missing")
        if isinstance(authored_field_coverage.get("missing"), dict)
        else missing_selected_field_topologies
    )
    authored_topology_archive_ready = bool(authored_field_coverage.get("hard_pass"))
    quota = dict(feedback.get("quota") or {})
    group_to_quota = {
        "continuous_field": "continuous_or_bent",
        "oblique_envelope": "oblique_or_polygon_envelope",
        "carved_void": "carved_or_courtyard",
        "bridge_interlock": "bridge_or_interlock",
        "folded_section": "folded_or_sloped_section",
        "stepped_capacity": "stepped_or_terraced_anchor",
        "cluster_field": "cluster_or_branch",
    }
    for group, deficit in missing.items():
        key = group_to_quota.get(str(group))
        if key:
            quota[key] = max(int(quota.get(key) or 0), int(deficit) + 2)
    if missing_selected_field_topologies.get("branched"):
        quota["continuous_or_bent"] = max(
            int(quota.get("continuous_or_bent") or 0),
            int(missing_selected_field_topologies["branched"]) + 3,
        )
    feedback.update({
        "schema_version": "arr.maas.vlm_generation_feedback.v2",
        "source": "previous_full_png_vlm_a2a_failure",
        "quota": quota,
        "reference_signal_diagnosis": {
            "previous_status": result.get("status"),
            "previous_visual_status": result.get("visual_status"),
            "selected_count": result.get("selected_count"),
            "missing_language_groups": missing,
            "missing_selected_field_topologies": missing_selected_field_topologies,
            "missing_authored_field_topologies": missing_authored_field_topologies,
            # Backward-compatible diagnostic key means selected retention.
            "missing_field_topologies": missing_selected_field_topologies,
            "critic_action_counts": dict(action_counts.most_common()),
        },
        "required_field_topologies": {
            "parallel": 0 if authored_topology_archive_ready else 1,
            # The adaptive archive already retains prior branched graphs. A
            # fresh author round must prove one executable branched field;
            # require extras only when the selected archive actually lost it.
            "branched": (
                0
                if authored_topology_archive_ready
                else max(1, int(missing_authored_field_topologies.get("branched") or 0) + 1)
            ),
            "instruction": (
                "Author genuinely branched continuous fields whose sole primary node is bend, with one joined trunk and occupiable branches; "
                "do not relabel parallel bars as branched and do not fragment them into detached boxes."
            ),
        },
        # These are executable-population minimums, not final-sheet quotas.
        # A small survival buffer lets clean-mass, capacity and VLM gates reject
        # weak graphs without erasing the requested language from the board.
        "required_language_groups": {
            # Hard author minimum closes the measured deficit only. The quota
            # above still asks for a survival buffer, but failing to produce
            # three examples must not discard one genuinely new executable
            # graph before clean/VLM/novelty evaluation.
            str(group): max(1, int(deficit))
            for group, deficit in missing.items()
        },
        "language_group_repair": {
            "missing": {str(group): int(deficit) for group, deficit in missing.items()},
            "instruction": (
                "Author new executable graph topologies for the missing groups. "
                "Do not relabel an existing box, rotated duplicate, or previous accepted graph."
            ),
        } if missing else {},
        "top_candidate_brief": sorted(top, key=lambda item: item["vlm_score"], reverse=True)[:5],
        "bottom_candidate_brief": sorted(
            bottom,
            key=lambda item: (
                "too_box_like" not in item["critic_actions"],
                item["vlm_score"],
            ),
        )[:8],
    })
    return feedback


def _reference_summary(match: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": match.get("source"),
        "source_id": match.get("source_id"),
        "title": match.get("title"),
        "page_url": match.get("page_url"),
        "local_path": match.get("local_path"),
        "matched_tags": match.get("matched_tags") or [],
        "score": match.get("score"),
        "selection_role": match.get("selection_role") or "similar",
    }


def _select_language_balanced_archive(
    pool: list[ProgramElite],
    *,
    target_count: int,
    minimum_distance: float,
    minimum_groups: dict[str, int],
    minimum_field_topologies: dict[str, int] | None = None,
    minimum_editable_field_count: int = 0,
    minimum_authored_count: int = 0,
    maximum_groups: dict[str, int] | None = None,
    minimum_capacity_target_count: int = 0,
    capacity_target_utilization: float = 0.9,
    maximum_persisted_count: int | None = None,
    minimum_fresh_count: int = 0,
) -> list[ProgramElite]:
    """Quality-floor archive with language, novelty and capacity coverage.

    Accepted graphs are durable *memory*, not permanent occupants of the next
    presentation sheet.  A bounded stability quota keeps proven diagrams while
    leaving room for newly authored/search-derived alternatives to replace
    them.  This distinction prevents an append-only provenance store from
    turning the visible archive into a frozen, increasingly prefixed rerun.
    """
    unique: dict[str, ProgramElite] = {}
    for item in pool:
        # Profiled/folded candidates deliberately share conservative volume
        # proxies with their surfaces.  A volume-only fingerprint erased those
        # visible differences before the surface-aware novelty gate ran.
        fingerprint = _source_geometry_fingerprint(item.source)
        incumbent = unique.get(fingerprint)
        # For the same rendered/legal geometry, retain the genotype that can
        # still respond to image critique. A tiny scalar advantage must not
        # erase its editable path and strand the critic on a frozen proxy.
        if (
            incumbent is None
            or (_has_editable_control_field(item) and not _has_editable_control_field(incumbent))
            or (
                _has_editable_control_field(item) == _has_editable_control_field(incumbent)
                and item.score > incumbent.score
            )
        ):
            unique[fingerprint] = item
    candidates = sorted(unique.values(), key=lambda item: item.score, reverse=True)
    editable_requirement = min(
        max(0, int(minimum_editable_field_count)),
        sum(_has_editable_control_field(item) for item in candidates),
    )
    selected: list[ProgramElite] = []
    topology_counts: dict[str, int] = {}
    principle_counts: dict[str, int] = {}
    language_group_counts: dict[str, int] = {}
    field_topology_counts: dict[str, int] = {}
    persisted_limit = (
        target_count
        if maximum_persisted_count is None
        else max(0, min(target_count, int(maximum_persisted_count)))
    )

    def admissible(item: ProgramElite) -> bool:
        if item in selected:
            return False
        if (
            _is_persisted_accepted_seed(item)
            and sum(_is_persisted_accepted_seed(other) for other in selected) >= persisted_limit
        ):
            return False
        topology = _topology(item)
        topology_peers = [other for other in selected if _topology(other) == topology]
        # Permit a second realization only when the 3D descriptor below proves
        # it is a materially different diagram. The old >=1 return made that
        # later distance check unreachable and capped a requested 48-parent
        # VLM frontier at roughly 24 topology labels.
        if len(topology_peers) >= 3:
            return False
        if principle_counts.get(_formal_principle(item), 0) >= 4:
            return False
        group = _language_group(item)
        if maximum_groups and language_group_counts.get(group, 0) >= int(maximum_groups.get(group, target_count)):
            return False
        for other in selected:
            distance = _descriptor_distance(item, other)
            visual_distance = intrinsic_silhouette_distance(item.source, other.source)
            if visual_distance < DEFAULT_NOVELTY_POLICY.visual_silhouette_repeat:
                return False
            if distance < minimum_distance:
                return False
            if (
                _topology(item) == _topology(other)
                and distance < DEFAULT_NOVELTY_POLICY.same_topology_repeat
            ):
                return False
            if (
                _formal_principle(item) == _formal_principle(other)
                and distance < DEFAULT_NOVELTY_POLICY.same_principle_repeat
            ):
                return False
        # Variants of the same graph can differ numerically in FAR/height yet
        # remain the same visible idea. Require a substantially different 3D
        # diagram before a second mutation of one topology enters the sheet.
        topology_distance = max(DEFAULT_NOVELTY_POLICY.same_topology_repeat, minimum_distance)
        if topology_peers and min(_descriptor_distance(item, other) for other in topology_peers) < topology_distance:
            return False
        return True

    def add(item: ProgramElite) -> None:
        selected.append(item)
        topology_counts[_topology(item)] = topology_counts.get(_topology(item), 0) + 1
        principle = _formal_principle(item)
        principle_counts[principle] = principle_counts.get(principle, 0) + 1
        group = _language_group(item)
        language_group_counts[group] = language_group_counts.get(group, 0) + 1
        field_topology = _field_topology(item)
        if field_topology:
            field_topology_counts[field_topology] = field_topology_counts.get(field_topology, 0) + 1

    def capacity_utilization(item: ProgramElite) -> float:
        return float(
            ((item.feature.get("properties") or {}).get("normalized_far_utilization"))
            or 0.0
        )

    # Reserve genuinely editable path genotypes before older scalar-only bend
    # seeds consume the continuous-field cells. Without this exploration
    # budget the VLM can see a ribbon but cannot ever receive a parent whose
    # spatial path it is capable of mutating from the image critique.
    while (
        len(selected) < target_count
        and sum(_has_editable_control_field(item) for item in selected)
        < editable_requirement
    ):
        eligible = [item for item in candidates if _has_editable_control_field(item) and admissible(item)]
        if not eligible:
            break
        add(max(
            eligible,
            key=lambda item: (
                item.score * 0.58
                + (1.0 if not selected else min(_descriptor_distance(item, other) for other in selected)) * 0.42
            ),
        ))

    # A continuous-field quota is not enough: several parallel ribbons can
    # satisfy it while the authored branched topology disappears before VLM.
    for topology, required in (minimum_field_topologies or {}).items():
        deficit = max(0, int(required) - field_topology_counts.get(topology, 0))
        for _ in range(deficit):
            eligible = [item for item in candidates if _field_topology(item) == topology and admissible(item)]
            if not eligible:
                break
            add(max(eligible, key=lambda item: item.score))

    # Require a small replenishment frontier before stability fill. This is
    # gradual archive evolution: fresh candidates earn places through the same
    # gates, while proven accepted graphs remain available for every unfilled
    # cell. A hard 50% eviction made a healthy archive collapse whenever one
    # author batch was weak.
    while (
        len(selected) < target_count
        and sum(not _is_persisted_accepted_seed(item) for item in selected)
        < max(0, int(minimum_fresh_count))
    ):
        eligible = [
            item for item in candidates
            if not _is_persisted_accepted_seed(item) and admissible(item)
        ]
        if not eligible:
            break
        add(max(
            eligible,
            key=lambda item: (
                item.score * 0.58
                + (1.0 if not selected else min(_descriptor_distance(item, other) for other in selected)) * 0.42
            ),
        ))

    # Reserve the live author frontier before deterministic anchors consume
    # the coarse behavior cells. Every authored candidate has already passed
    # program/capacity hard gates at this point.
    while (
        len(selected) < target_count
        and sum(1 for item in selected if _is_live_authored_graph(item)) < minimum_authored_count
    ):
        eligible = [item for item in candidates if _is_live_authored_graph(item) and admissible(item)]
        if not eligible:
            break
        add(max(
            eligible,
            key=lambda item: (
                item.score * 0.58
                + (1.0 if not selected else min(_descriptor_distance(item, other) for other in selected)) * 0.42
            ),
        ))

    for group, required in minimum_groups.items():
        # Fill only the deficit. Persisted/authored reservations may already
        # satisfy a language cell; adding ``required`` again biased every run
        # toward whichever groups appeared first in this dictionary.
        deficit = max(0, int(required) - language_group_counts.get(group, 0))
        for _ in range(deficit):
            eligible = [item for item in candidates if _language_group(item) == group and admissible(item)]
            if not eligible:
                break
            add(max(eligible, key=lambda item: item.score))

    # Capacity is a portfolio constraint, not a small scalar bonus.  Reserve
    # enough VLM-review/final slots for candidates that actually reach the
    # policy target; otherwise a visually safe low-FAR archive can make the
    # target mathematically impossible after selection.
    while (
        len(selected) < target_count
        and sum(capacity_utilization(item) >= capacity_target_utilization for item in selected)
        < max(0, int(minimum_capacity_target_count))
    ):
        eligible = [
            item
            for item in candidates
            if capacity_utilization(item) >= capacity_target_utilization and admissible(item)
        ]
        if not eligible:
            break
        add(max(
            eligible,
            key=lambda item: (
                item.score * 0.58
                + (1.0 if not selected else min(_descriptor_distance(item, other) for other in selected)) * 0.32
                + min(1.0, capacity_utilization(item)) * 0.10
            ),
        ))

    # Stability fill happens only after authored, language and capacity
    # deficits have reserved their cells. Proven graphs can no longer consume
    # the complete sheet before those portfolio constraints run.
    for item in candidates:
        if len(selected) >= target_count:
            break
        if _is_persisted_accepted_seed(item) and admissible(item):
            add(item)

    while len(selected) < target_count:
        eligible = [item for item in candidates if admissible(item)]
        if not eligible:
            break
        winner = max(
            eligible,
            key=lambda item: (
                item.score * 0.58
                + (1.0 if not selected else min(_descriptor_distance(item, other) for other in selected)) * 0.42
            ),
        )
        add(winner)
    # The ordered quota passes above are fast but greedy: one early candidate
    # can block two mutually compatible later candidates. On a bounded final
    # pool, solve the same hard constraints as a combination problem. Gates
    # are never weakened; the beam result replaces greedy output only when it
    # produces a strictly larger valid portfolio.
    if len(selected) < target_count and len(candidates) <= 64:
        compatibility = [[True for _ in candidates] for _ in candidates]
        for left_index, left in enumerate(candidates):
            for right_index in range(left_index):
                right = candidates[right_index]
                distance = _descriptor_distance(left, right)
                silhouette = intrinsic_silhouette_distance(left.source, right.source)
                compatible = (
                    distance >= minimum_distance
                    and silhouette >= DEFAULT_NOVELTY_POLICY.visual_silhouette_repeat
                    and not (
                        _topology(left) == _topology(right)
                        and distance < DEFAULT_NOVELTY_POLICY.same_topology_repeat
                    )
                    and not (
                        _formal_principle(left) == _formal_principle(right)
                        and distance < DEFAULT_NOVELTY_POLICY.same_principle_repeat
                    )
                )
                compatibility[left_index][right_index] = compatible
                compatibility[right_index][left_index] = compatible
        facts = [PortfolioCandidateFacts(
            score=float(item.score),
            group=_language_group(item),
            principle=_formal_principle(item),
            topology=_topology(item),
            field_topology=_field_topology(item) or "",
            persisted=_is_persisted_accepted_seed(item),
            authored=_is_live_authored_graph(item),
            capacity_target=capacity_utilization(item) >= capacity_target_utilization,
            editable_field=_has_editable_control_field(item),
        ) for item in candidates]
        solved_indices = solve_portfolio_beam(
            facts,
            compatibility,
            target_count=target_count,
            minimum_groups=minimum_groups,
            maximum_groups=maximum_groups,
            minimum_field_topologies=minimum_field_topologies,
            minimum_authored_count=minimum_authored_count,
            # Do not make the combination problem infeasible when the current
            # visual-floor pool contains fewer editable fields than requested.
            # The run-level coverage audit still reports the shortage and
            # triggers replenishment; the solver may retain every available
            # field while finding a larger honest portfolio.
            minimum_editable_field_count=editable_requirement,
            minimum_capacity_target_count=minimum_capacity_target_count,
            maximum_persisted_count=persisted_limit,
            minimum_fresh_count=minimum_fresh_count,
            # A 35-45 candidate visual-floor pool has many high-scoring but
            # mutually blocking 19-card states. The smaller review frontiers
            # stay cheap, while the final bounded pool retains enough alternate
            # compatibility histories to discover a valid twentieth card.
            beam_width=32768 if len(candidates) >= 32 else 4096,
        )
        solved = [candidates[index] for index in solved_indices]
        if len(solved) > len(selected):
            selected = solved
    return selected


def _rebalance_capacity_archive(
    selected: list[ProgramElite],
    pool: list[ProgramElite],
    *,
    required_count: int,
    target_utilization: float,
    minimum_groups: dict[str, int],
    minimum_field_topologies: dict[str, int] | None,
    maximum_groups: dict[str, int],
    minimum_distance: float,
    minimum_editable_field_count: int,
    minimum_authored_count: int,
    maximum_persisted_count: int,
    minimum_fresh_count: int,
) -> tuple[list[ProgramElite], dict[str, Any]]:
    """Meet the mass-stage FAR target without relaxing visual/diversity gates."""
    archive = list(selected)
    editable_requirement = min(
        max(0, int(minimum_editable_field_count)),
        sum(_has_editable_control_field(item) for item in pool),
    )

    def utilization(item: ProgramElite) -> float:
        return float((item.feature.get("properties") or {}).get("normalized_far_utilization") or 0.0)

    def target_count(items: list[ProgramElite]) -> int:
        return sum(utilization(item) >= target_utilization for item in items)

    initial_count = target_count(archive)
    swaps: list[dict[str, Any]] = []
    selected_ids = {id(item) for item in archive}
    candidates = sorted(
        (item for item in pool if id(item) not in selected_ids and utilization(item) >= target_utilization),
        key=lambda item: (utilization(item), item.score),
        reverse=True,
    )
    while len(archive) > 0 and target_count(archive) < required_count:
        replacement_made = False
        donors = sorted(
            (item for item in archive if utilization(item) < target_utilization),
            key=lambda item: (utilization(item), item.score),
        )
        for candidate in candidates:
            if id(candidate) in {id(item) for item in archive}:
                continue
            for donor in donors:
                remaining = [item for item in archive if id(item) != id(donor)]
                proposed = [*remaining, candidate]
                groups = _language_group_counts(proposed)
                if any(groups.get(group, 0) < required for group, required in minimum_groups.items()):
                    continue
                topology_counts = Counter(_field_topology(item) for item in proposed if _field_topology(item))
                if any(
                    topology_counts.get(topology, 0) < required
                    for topology, required in (minimum_field_topologies or {}).items()
                ):
                    continue
                if any(groups.get(group, 0) > allowed for group, allowed in maximum_groups.items()):
                    continue
                if sum(_is_live_authored_graph(item) for item in proposed) < minimum_authored_count:
                    continue
                if sum(_has_editable_control_field(item) for item in proposed) < editable_requirement:
                    continue
                persisted_count = sum(_is_persisted_accepted_seed(item) for item in proposed)
                if persisted_count > maximum_persisted_count:
                    continue
                if len(proposed) - persisted_count < minimum_fresh_count:
                    continue
                if remaining and min(_descriptor_distance(candidate, item) for item in remaining) < minimum_distance:
                    continue
                topology_peers = [item for item in remaining if _topology(item) == _topology(candidate)]
                if len(topology_peers) >= 3:
                    continue
                if topology_peers and min(
                    _descriptor_distance(candidate, item) for item in topology_peers
                ) < DEFAULT_NOVELTY_POLICY.same_topology_repeat:
                    continue
                if any(
                    intrinsic_silhouette_distance(candidate.source, item.source)
                    < DEFAULT_NOVELTY_POLICY.visual_silhouette_repeat
                    for item in remaining
                ):
                    continue
                principle_peers = [
                    item for item in remaining
                    if _formal_principle(item) == _formal_principle(candidate)
                ]
                if principle_peers and min(
                    _descriptor_distance(candidate, item) for item in principle_peers
                ) < DEFAULT_NOVELTY_POLICY.same_principle_repeat:
                    continue
                principle_count = sum(_formal_principle(item) == _formal_principle(candidate) for item in remaining)
                if principle_count >= 4:
                    continue
                archive = proposed
                swaps.append({
                    "out": donor.sequence.name,
                    "out_far_utilization": round(utilization(donor), 4),
                    "in": candidate.sequence.name,
                    "in_far_utilization": round(utilization(candidate), 4),
                    "language_group": _language_group(candidate),
                })
                replacement_made = True
                break
            if replacement_made:
                break
        if not replacement_made:
            break
    return archive, {
        "schema_version": "arr.maas.capacity_rebalance.v1",
        "target_utilization": target_utilization,
        "required_count": required_count,
        "initial_count": initial_count,
        "final_count": target_count(archive),
        "swaps": swaps,
        "target_met": target_count(archive) >= required_count,
        "persisted_count": sum(_is_persisted_accepted_seed(item) for item in archive),
        "fresh_count": sum(not _is_persisted_accepted_seed(item) for item in archive),
    }


def _reason_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        counts.update(str(reason) for reason in record.get("reasons") or [])
    return dict(counts.most_common())


def _same_source_geometry(left: Any, right: Any) -> bool:
    """Reject critic edits that change graph prose but not rendered geometry."""
    return (
        left.source_volume_signatures() == right.source_volume_signatures()
        and left.source_surface_signatures() == right.source_surface_signatures()
    )


def _source_geometry_fingerprint(source: Any) -> str:
    """Lossless-enough archive key that does not erase profiled surfaces."""
    return json.dumps({
        "volumes": source.source_volume_signatures(),
        "surfaces": source.source_surface_signatures(),
    }, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _retain_geometry_best(archive: dict[str, ProgramElite], elite: ProgramElite) -> None:
    """Keep the best scored representative without deleting other geometry."""
    key = _source_geometry_fingerprint(elite.source)
    incumbent = archive.get(key)
    if incumbent is None or elite.score > incumbent.score:
        archive[key] = elite


def _archive_selection_audit(
    pool: list[ProgramElite],
    selected: list[ProgramElite],
    *,
    minimum_distance: float,
) -> dict[str, Any]:
    """Explain why visual-floor survivors did not enter the final sheet.

    Reasons are intentionally non-exclusive: a candidate can be both the same
    graph topology and visually too close to a selected candidate.  That is
    more useful for author feedback than hiding the second failure behind the
    first branch taken by the greedy selector.
    """
    selected_ids = {id(item) for item in selected}
    selected_topologies = {_topology(item) for item in selected}
    records: list[dict[str, Any]] = []
    for item in pool:
        if id(item) in selected_ids:
            continue
        reasons: list[str] = []
        topology = _topology(item)
        if topology in selected_topologies:
            reasons.append("same_topology_as_selected")
        if selected:
            nearest = min(_descriptor_distance(item, other) for other in selected)
            nearest_silhouette = min(
                intrinsic_silhouette_distance(item.source, other.source)
                for other in selected
            )
            if nearest < minimum_distance:
                reasons.append("descriptor_too_close_to_selected")
            if nearest_silhouette < DEFAULT_NOVELTY_POLICY.visual_silhouette_repeat:
                reasons.append("silhouette_too_close_to_selected")
        else:
            nearest = 1.0
            nearest_silhouette = 1.0
        if not reasons:
            reasons.append("greedy_quota_or_cap_order")
        records.append({
            "candidate": item.sequence.name,
            "language_group": _language_group(item),
            "nearest_selected_distance": round(nearest, 4),
            "nearest_selected_silhouette_distance": round(nearest_silhouette, 4),
            "reasons": reasons,
        })
    return {
        "pool_count": len(pool),
        "selected_count": len(selected),
        "rejection_counts": _reason_counts(records),
        "rejection_samples": records[:20],
    }


def _is_live_authored_graph(item: ProgramElite) -> bool:
    signature = item.source.signature()
    graph = signature.get("component_graph") if isinstance(signature.get("component_graph"), dict) else {}
    for node in graph.get("nodes") or []:
        constraints = node.get("constraints") if isinstance(node, dict) and isinstance(node.get("constraints"), dict) else {}
        if constraints.get("author_graph_native"):
            return True
    return False


def _is_persisted_accepted_seed(item: ProgramElite) -> bool:
    return any(str(note).strip().lower() == "replenishment_accepted_seed=true" for note in item.sequence.notes)


def _sequence_record(sequence: VerbSequence) -> dict[str, Any]:
    return {
        "name": sequence.name,
        "label": sequence.label,
        "calls": sequence.to_list(),
        "notes": list(sequence.notes),
    }


def _sequence_from_record(record: Any) -> VerbSequence | None:
    if not isinstance(record, dict):
        return None
    calls = tuple(
        VerbCall(str(item.get("verb") or ""), dict(item.get("params") or {}))
        for item in record.get("calls") or []
        if isinstance(item, dict)
    )
    source_name = str(record.get("name") or "candidate")
    while source_name.startswith("llm_accepted_seed_"):
        source_name = source_name[len("llm_accepted_seed_"):]
    sequence = VerbSequence(
        name=f"llm_accepted_seed_{source_name}",
        label=str(record.get("label") or record.get("name") or "accepted archive seed"),
        calls=calls,
        notes=tuple(str(value) for value in record.get("notes") or ()) + ("replenishment_accepted_seed=true",),
    )
    return sequence if not sequence.validate() else None


def _language_group(item: ProgramElite) -> str:
    principle = _formal_principle(item)
    surface = item.source.signature().get("continuous_surface_evidence") or {}
    verbs = {call.verb for call in item.sequence.calls}
    primary_verb = primary_operation_from_sequence(item.sequence).verb
    height_levels = len({round(volume.top_fraction, 2) for volume in item.source.volumes})
    if principle == "continuous_ribbon_field" or primary_verb == "bend":
        return "continuous_field"
    if surface.get("representation") in {
        "agent_oblique_envelope_mesh",
        "agent_oblique_polygon_envelope",
    }:
        return "oblique_envelope"
    if (
        principle == "folded_section"
        or principle == "torqued_stack"
        or primary_verb == "sloped_roof_mass"
    ):
        return "folded_section"
    if principle == "split_bridge_connector" or primary_verb in {"split", "diagonal_connect", "interlock"}:
        return "bridge_interlock"
    # An array/branch is still a field language when it also carries a court.
    # Checking carved verbs first made every porous cluster disappear into the
    # carved bucket, so the cluster quota could never be satisfied by design.
    if primary_verb in {"array", "branch"}:
        return "cluster_field"
    if principle in {
        "slender_podium_tower",
        "slender_tower",
        "podium_tower",
        "undercut_tapered_tower",
    }:
        return "oblique_envelope"
    if (
        principle in {"terraced_ribbon_section", "stacked_shifted_platforms"}
        and height_levels >= 3
        and float((item.feature.get("properties") or {}).get("normalized_far_utilization") or 0.0) >= 0.55
    ):
        return "stepped_capacity"
    if principle in {"carved_atrium", "carved_monolith"} or verbs & {"courtyard", "cave", "notch", "embed", "nest"}:
        return "carved_void"
    return "calm_anchor"


def _language_group_counts(items: list[ProgramElite]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        group = _language_group(item)
        counts[group] = counts.get(group, 0) + 1
    return counts


def _field_topology(item: ProgramElite) -> str:
    primary = primary_operation_from_sequence(item.sequence)
    if primary.verb == "bend":
        topology = str(primary.params.get("field_topology") or "parallel").strip().lower()
        return topology if topology in {"parallel", "branched"} else "parallel"
    return ""


def _has_editable_control_field(item: ProgramElite) -> bool:
    primary = primary_operation_from_sequence(item.sequence)
    controls = (
        primary.params.get("control_points")
        if primary.verb in {"bend", "sloped_roof_mass"}
        else primary.params.get("plan_control_points") if primary.verb == "taper" else None
    )
    minimum, maximum = ((3, 8) if primary.verb == "taper" else (4, 6))
    return isinstance(controls, list) and minimum <= len(controls) <= maximum


def _near_duplicate_pairs(items: list[ProgramElite], *, threshold: float) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for index, left in enumerate(items):
        for right in items[:index]:
            distance = _descriptor_distance(left, right)
            if distance < threshold:
                pairs.append({
                    "left": left.sequence.name,
                    "right": right.sequence.name,
                    "distance": round(distance, 4),
                })
    return pairs


def _morphology_repeat_pairs(items: list[ProgramElite]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for left_index, left in enumerate(items):
        for right_index, right in enumerate(items[left_index + 1:], start=left_index + 1):
            distance = _descriptor_distance(left, right)
            repeat_kind = DEFAULT_NOVELTY_POLICY.repeat_kind(
                distance,
                same_principle=_formal_principle(left) == _formal_principle(right),
                same_topology=_topology(left) == _topology(right),
            )
            if repeat_kind:
                pairs.append({
                    "left_index": left_index,
                    "right_index": right_index,
                    "left": left.sequence.name,
                    "right": right.sequence.name,
                    "distance": round(distance, 4),
                    "repeat_kind": repeat_kind,
                    "left_principle": _formal_principle(left),
                    "right_principle": _formal_principle(right),
                })
    return pairs


def _silhouette_repeat_pairs(items: list[ProgramElite]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    threshold = DEFAULT_NOVELTY_POLICY.visual_silhouette_repeat
    for left_index, left in enumerate(items):
        for right_index, right in enumerate(items[left_index + 1:], start=left_index + 1):
            distance = intrinsic_silhouette_distance(left.source, right.source)
            if distance >= threshold:
                continue
            pairs.append({
                "left": left_index,
                "right": right_index,
                "distance": round(distance, 4),
                "kind": "three_view_silhouette_repeat",
            })
    return pairs


def _score_population(
    population: list[ProgramElite],
    references: list[Any],
    preview_root: Path,
    *,
    model: str,
    workers: int,
    score_cache: dict[str, dict[str, Any]] | None = None,
    score_cache_path: Path | None = None,
) -> list[tuple[ProgramElite, dict[str, Any], list[dict[str, Any]]]]:
    cache_write_lock = Lock()

    def score(elite: ProgramElite):
        matches = match_reference_context(elite.feature, references, limit=5)
        cache_key = _vlm_cache_key(elite, matches, model=model)
        if score_cache is not None and isinstance(score_cache.get(cache_key), dict):
            return elite, dict(score_cache[cache_key]), matches
        preview = feature_preview_png(elite.feature, preview_root)
        vlm = score_candidate_with_openai_vlm(
            feature=elite.feature,
            image_path=preview,
            reference_matches=matches,
            model=model,
        )
        if score_cache is not None:
            with cache_write_lock:
                score_cache[cache_key] = dict(vlm)
                if score_cache_path is not None:
                    # Persist each completed paid evaluation. A later timeout
                    # in another worker must not discard already received VLM
                    # evidence and force the next run to buy it again.
                    _save_vlm_cache(score_cache_path, score_cache, model=model)
        return elite, vlm, matches

    results: dict[int, tuple[ProgramElite, dict[str, Any], list[dict[str, Any]]]] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(population) or 1))) as executor:
        futures = {executor.submit(score, elite): index for index, elite in enumerate(population)}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return [results[index] for index in range(len(population))]


def _vlm_cache_key(elite: ProgramElite, matches: list[dict[str, Any]], *, model: str) -> str:
    feature = getattr(elite, "feature", {})
    props = feature.get("properties") if isinstance(feature, dict) and isinstance(feature.get("properties"), dict) else {}
    payload = {
        "schema": "arr.maas.program_vlm_cache.v6",
        "prompt_contract_version": VLM_PROMPT_CONTRACT_VERSION,
        "model": model,
        "graph": _canonical_component_graph(elite.source.signature().get("component_graph") or {}),
        "volumes": [volume.signature() for volume in elite.source.volumes],
        # The preview renderer can replace an extruded volume with authored
        # profile/mesh surfaces.  Volume-only keys therefore reused a score
        # for an obsolete box preview after the surface compiler changed.
        "surfaces": [surface.signature() for surface in elite.source.surfaces],
        # Identical geometry on a differently shaped parcel is a different
        # visual/site-fit judgment. Never reuse a geometry-only score there.
        "site_boundary_geometry": props.get("site_boundary_geometry"),
        "site_access_context": props.get("site_access_context"),
        "site_access_geometry": props.get("site_access_geometry"),
        "references": [str(item.get("source_id") or item.get("local_path") or "") for item in matches],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _canonical_component_graph(graph: Any) -> dict[str, Any]:
    """Remove archive identity while preserving executable graph semantics.

    Replenishment prefixes a sequence name with ``llm_accepted_seed_``. The
    preview and geometry do not change, so name/label/notes must not invalidate
    a paid VLM score. Node IDs remain because cached graph edits target them.
    """
    if not isinstance(graph, dict):
        return {}
    return {
        "schema_version": graph.get("schema_version"),
        "nodes": [
            {
                "node_id": node.get("node_id"),
                "parent_id": node.get("parent_id"),
                "role": node.get("role"),
                "relation": node.get("relation"),
                "operation": node.get("operation") or {},
                "optional": bool(node.get("optional")),
            }
            for node in graph.get("nodes") or []
            if isinstance(node, dict)
        ],
    }


def _load_vlm_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entries = data.get("entries") if isinstance(data, dict) else None
    return {str(key): dict(value) for key, value in (entries or {}).items() if isinstance(value, dict)}


def _save_vlm_cache(path: Path, entries: dict[str, dict[str, Any]], *, model: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({
        "schema_version": "arr.maas.vlm_score_cache.v1",
        "model": model,
        "entries": entries,
    }, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def _compile_verified(
    base,
    sequence,
    *,
    building_type: str,
    capacity_policy: dict[str, Any] | None = None,
    far_limit_ratio: float = 3.0,
    _allow_capacity_projection: bool = True,
    _capacity_projection_depth: int = 0,
) -> ProgramElite | None:
    source = compile_sequence_to_source_mass(base, sequence)
    if source is None:
        return None
    signature = source.signature()
    raw_surfaces = int(signature.get("surface_count") or 0)
    effective_surfaces = int(signature.get("effective_surface_count") or raw_surfaces)
    profiled = bool(signature.get("continuous_surface_evidence", {}).get("hard_pass"))
    raw_surface_limit = 160 if profiled else 48
    if len(source.volumes) > 4 or raw_surfaces > raw_surface_limit or effective_surfaces > 28:
        return None
    feature = _feature(source, sequence, building_type=building_type, height=15.0, floors=5, site_area=float(base.area))
    evidence = attach_program_massing_evidence(feature, building_type=building_type)
    capacity_policy = capacity_policy or resolve_massing_capacity_policy(
        building_type=building_type,
        site_area_m2=float(base.area),
        parking_options=None,
    )
    far_utilization = _source_far_utilization(
        source, site_area=float(base.area), floors=5, far_limit_ratio=far_limit_ratio,
    )
    feature["properties"]["normalized_far_utilization"] = far_utilization
    feature["properties"]["massing_capacity_policy"] = capacity_policy
    target = max(float(capacity_policy["target_far_utilization"]), 1e-9)
    feature["properties"]["capacity_target_fit"] = round(min(1.0, far_utilization / target), 4)
    spatial = feature["properties"]["program_spatial_evidence"]
    if not evidence["hard_pass"] or float(spatial["architectural_score"]) < 0.76:
        return None
    minimum_utilization = float(capacity_policy["min_far_utilization"])
    if far_utilization < minimum_utilization:
        if _allow_capacity_projection and _capacity_projection_depth < 2:
            projected = project_bend_capacity(
                sequence,
                observed_utilization=far_utilization,
                target_utilization=max(
                    minimum_utilization + 0.03,
                    float(capacity_policy["target_far_utilization"]),
                ),
            )
            if projected is not None:
                return _compile_verified(
                    base,
                    projected,
                    building_type=building_type,
                    capacity_policy=capacity_policy,
                    far_limit_ratio=far_limit_ratio,
                    _allow_capacity_projection=True,
                    _capacity_projection_depth=_capacity_projection_depth + 1,
                )
        return None
    score = float(evidence["program_fit_score"]) * 0.55 + float(spatial["architectural_score"]) * 0.45
    return ProgramElite(sequence, source, feature, round(score, 6), 1)


def _attach_vlm(feature: dict[str, Any], vlm: dict[str, Any], matches: list[dict[str, Any]]) -> None:
    feature.setdefault("properties", {})["preference_distillation"] = {
        "schema_version": "arr.maas.preference_distill.v1",
        "mode": "vlm_scored",
        "vlm_status": "scored",
        "vlm_model": vlm.get("model"),
        "concept_scores": vlm.get("concept_scores") or {},
        "critic_actions": vlm.get("critic_actions") or [],
        "graph_edits": vlm.get("graph_edits") or [],
        "geometry_edits": vlm.get("geometry_edits") or [],
        "reference_matches": matches,
        "rationale": vlm.get("rationale") or "",
    }


def _vlm_mean(vlm: dict[str, Any]) -> float:
    scores = vlm.get("concept_scores") if isinstance(vlm.get("concept_scores"), dict) else {}
    return mean(scores.values()) if scores else 0.0


def _vlm_design_score(vlm: dict[str, Any]) -> float:
    """Action-aware visual score used for selection and critic acceptance.

    A critic cannot call a mass ``too_box_like`` or ``overlapping_volumes``
    and then have the unpenalized arithmetic mean resurrect it.
    """
    score = _vlm_mean(vlm)
    actions = {str(item) for item in vlm.get("critic_actions") or []}
    penalties = {
        "overlapping_volumes": 0.18,
        "too_fragmented": 0.14,
        "too_box_like": 0.16,
        "weak_form_continuity": 0.12,
        "weak_primary_mass": 0.08,
        "needs_clean_anchor": 0.06,
        "too_many_surface_pieces": 0.08,
        "needs_profiled_surface": 0.04,
        "needs_carved_void": 0.03,
    }
    return max(0.0, min(1.0, score - sum(penalties.get(action, 0.0) for action in actions)))


def _feature_vlm_mean(feature: dict[str, Any]) -> float:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    preference = props.get("preference_distillation") if isinstance(props.get("preference_distillation"), dict) else {}
    scores = preference.get("concept_scores") if isinstance(preference.get("concept_scores"), dict) else {}
    return mean(scores.values()) if scores else 0.0


def _feature_vlm_design_score(feature: dict[str, Any]) -> float:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    preference = props.get("preference_distillation") if isinstance(props.get("preference_distillation"), dict) else {}
    score = _vlm_design_score({
        "concept_scores": preference.get("concept_scores") or {},
        "critic_actions": preference.get("critic_actions") or [],
    })
    actions = {str(value) for value in preference.get("critic_actions") or []}
    if "too_box_like" in actions and _has_legible_non_box_evidence(feature, actions):
        score = min(1.0, score + 0.16)
    return score


def _generic_box_bias(feature: dict[str, Any], actions: set[str] | None = None) -> bool:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    spatial = props.get("program_spatial_evidence") if isinstance(props.get("program_spatial_evidence"), dict) else {}
    projection = spatial.get("spatial_role_projection") if isinstance(spatial.get("spatial_role_projection"), dict) else {}
    signature = props.get("source_signature") if isinstance(props.get("source_signature"), dict) else {}
    surface_evidence = (
        signature.get("continuous_surface_evidence")
        if isinstance(signature.get("continuous_surface_evidence"), dict)
        else {}
    )
    if bool(projection.get("profiled_roof_present")) or bool(surface_evidence.get("hard_pass")):
        return False
    if int(projection.get("non_rectilinear_component_count") or 0) > 0:
        return False
    legible_void = (
        "good_void" in (actions or set())
        and float(projection.get("envelope_void_ratio") or 0.0) >= 0.10
    )
    # Three stacked rectangular levels are still a box-stack language.  Height
    # count alone must not let repeated cuboids masquerade as silhouette or
    # figure-ground diversity.
    return not legible_void


def _has_legible_non_box_evidence(feature: dict[str, Any], actions: set[str]) -> bool:
    """Allow a VLM box label override only with positive geometric evidence.

    A tiny notch used to flip ``_generic_box_bias`` and rescue an otherwise
    generic extrusion.  Profiled surfaces are direct evidence.  Carved or
    non-rectilinear forms need both critic acknowledgement and adequate design
    score, and cannot simultaneously be asking for the missing profile.
    """
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    spatial = props.get("program_spatial_evidence") if isinstance(props.get("program_spatial_evidence"), dict) else {}
    projection = spatial.get("spatial_role_projection") if isinstance(spatial.get("spatial_role_projection"), dict) else {}
    signature = props.get("source_signature") if isinstance(props.get("source_signature"), dict) else {}
    surface_evidence = (
        signature.get("continuous_surface_evidence")
        if isinstance(signature.get("continuous_surface_evidence"), dict)
        else {}
    )
    if bool(projection.get("profiled_roof_present")) or bool(surface_evidence.get("hard_pass")):
        return True
    if "needs_profiled_surface" in actions:
        return False
    design_score = _vlm_design_score({
        "concept_scores": (props.get("preference_distillation") or {}).get("concept_scores") or {},
        "critic_actions": [],
    })
    strong_void = (
        "good_void" in actions
        and float(projection.get("envelope_void_ratio") or 0.0) >= 0.12
    )
    return design_score >= 0.70 and strong_void


def _binding_box_rejection(feature: dict[str, Any], actions: set[str]) -> bool:
    """Keep a critic box rejection binding without geometric counter-evidence.

    A cluster can be four valid components and a bridge can connect two valid
    bodies while still reading as arbitrary cuboids. Family correctness is not
    visual quality; only a profiled envelope or a strong critic-confirmed void
    can overturn this image judgment.
    """
    return "too_box_like" in actions and not _has_legible_non_box_evidence(feature, actions)


def _visual_floor_failure_reasons(item: ProgramElite, *, minimum_score: float) -> list[str]:
    props = item.feature.get("properties") if isinstance(item.feature.get("properties"), dict) else {}
    preference = props.get("preference_distillation") if isinstance(props.get("preference_distillation"), dict) else {}
    actions = {str(value) for value in preference.get("critic_actions") or []}
    language_group = _language_group(item)
    language_evidence = assess_language_geometry(item.source, item.feature, language_group)
    props["language_geometry_quality"] = language_evidence
    language_geometry_pass = bool(language_evidence.get("geometry_pass"))
    reasons: list[str] = []
    for action in sorted(actions & {"overlapping_volumes", "too_fragmented", "too_many_surface_pieces"}):
        reasons.append(action)
    if language_group != "calm_anchor" and not language_geometry_pass:
        reasons.append("language_geometry_gate_failed")
    # A VLM box rejection is binding unless the compiled geometry contains
    # direct evidence that the label was over-broad. A token notch/courtyard is
    # no longer enough to turn a generic extrusion into a design language.
    if _binding_box_rejection(item.feature, actions):
        reasons.append("too_box_like_without_geometric_evidence")
    if (
        language_group == "carved_void"
        and "needs_carved_void" in actions
        and "good_void" not in actions
    ):
        # Envelope whitespace can be numerically large while the rendered
        # mass still reads as stacked boxes. For a language whose primary
        # claim is subtraction, the image critic's missing-void diagnosis is
        # binding unless it also confirms a legible void.
        reasons.append("critic_rejects_weak_carved_void")
    design_score = _feature_vlm_design_score(item.feature)
    raw_vlm_score = _feature_vlm_mean(item.feature)
    # A validated stepped/bridge/folded/courtyard diagram may recover the
    # generic-box penalty, but never fragmentation/overlap penalties. This
    # keeps a coherent rectilinear language without reviving arbitrary stacks.
    effective_score = design_score
    if language_geometry_pass and not actions & {
        "overlapping_volumes", "too_fragmented", "too_many_surface_pieces", "weak_form_continuity"
    }:
        effective_score = max(effective_score, raw_vlm_score - 0.08)
    props["language_adjusted_vlm_score"] = round(effective_score, 4)
    if effective_score < minimum_score:
        reasons.append("vlm_design_score_below_minimum")
    generic_box = _generic_box_bias(item.feature, actions)
    # One calm/simple anchor is a legitimate language; generic boxes are not
    # allowed to masquerade as every other language group.
    if generic_box and not language_geometry_pass and language_group != "calm_anchor":
        reasons.append("generic_box_outside_calm_anchor")
    return reasons


def _passes_visual_floor(item: ProgramElite, *, minimum_score: float) -> bool:
    return not _visual_floor_failure_reasons(item, minimum_score=minimum_score)


def _with_dual_objective_score(elite: ProgramElite, vlm: dict[str, Any]) -> ProgramElite:
    """Rank design only after program/capacity hard gates have already passed."""
    props = elite.feature.get("properties") or {}
    program = props.get("program_massing_evidence") or {}
    spatial = props.get("program_spatial_evidence") or {}
    design = _feature_vlm_design_score(elite.feature)
    capacity_fit = float(props.get("capacity_target_fit") or 0.0)
    combined = (
        design * 0.50
        + float(program.get("program_fit_score") or 0.0) * 0.19
        + float(spatial.get("architectural_score") or 0.0) * 0.17
        + capacity_fit * 0.14
    )
    return replace(elite, score=round(combined, 6))


def _source_far_utilization(source, *, site_area: float, floors: int, far_limit_ratio: float) -> float:
    floor_area = 0.0
    for floor_index in range(max(1, int(floors))):
        level = (floor_index + 0.5) / max(1, int(floors))
        active = [
            volume.footprint
            for volume in source.volumes
            if float(volume.bottom_fraction) <= level < float(volume.top_fraction)
        ]
        if active:
            union = safe_unary_union(active)
            if union is not None:
                floor_area += float(union.area)
    denominator = max(float(site_area) * float(far_limit_ratio), 1e-9)
    return round(min(1.0, floor_area / denominator), 4)


__all__ = ["generation_feedback_from_result", "run_neighborhood_vlm_a2a_loop"]
