"""Image-grounded review and typed repair of staged BOOK candidates."""

from __future__ import annotations

import os
import hashlib
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

from shapely.geometry import Polygon, mapping

from backend.app.modules.design.generation.maas.geometry_language import GeometryOutcomeGraph, GeometryProgram, apply_geometry_edits_compiler_safe, build_geometry_graph_notes, build_geometry_graph_snapshot, compile_geometry_program, materialize_floorwise_legal_source, replace_source_dominant_with_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.floorwise_visual_projection import certify_authored_visual_mesh
from backend.app.modules.design.generation.maas.geometry_language.projected_visual_contract import CertifiedMassArtifact, semantic_audit_payload_hash
from backend.app.modules.design.generation.maas.program_massing import program_reference_contract
from backend.app.modules.design.generation.maas.program_massing.semantic_carriers import audit_source_semantic_projection
from backend.app.modules.design.generation.maas.program_massing.scoring import attach_program_massing_evidence
from backend.app.modules.design.generation.maas.program_massing.search import materialize_source_feature_surfaces, source_feature
from backend.app.modules.design.generation.maas.preference.loop import openai_preview_preference_scorer
from backend.app.modules.design.generation.maas.preference.vlm_scorer import DEFAULT_VLM_MODEL, VLM_PROMPT_CONTRACT_VERSION, VlmBudgetExhaustedError, vlm_request_kind_scope
from backend.app.modules.design.generation.maas.paid_provider_budget import paid_provider_budget_snapshot
from backend.app.modules.design.generation.maas.book_language.typed_edit_completion import complete_empty_final_vlm_repair_records
from backend.app.modules.design.generation.maas.shared_floor_contract import bind_shared_floor_contract_capacity, materialize_shared_floor_contract
from backend.app.modules.design.generation.maas.source_geometry import compile_sequence_to_source_mass

from backend.app.modules.design.generation.maas.book_language.candidate_analysis import _Candidate, _chassis_family, _clean_mass_gate, _design_concept_descriptor, _form_bank_lane, _geometry_program_family, _inside_site, _llm_authored_candidate, _program_form_gate, _scope_key, _site_access_side_in_principal_frame, _solid_morphology_metrics
from backend.app.modules.design.generation.maas.book_language.candidate_generation import _bind_book_program_source_role, _issue_authored_legal_projection_authority, _mass_stage_design_score
from backend.app.modules.design.generation.maas.book_language.base_volume_contract import book_base_volume_spec
from backend.app.modules.design.generation.maas.book_language.capacity_alternatives import capacity_fit_score, capacity_contract_for_alternative, evaluate_capacity_alternative
from backend.app.modules.design.generation.maas.book_language.capacity_contract import measure_source_capacity, recursive_plan_coverage_floor
from backend.app.modules.design.generation.maas.book_language.capacity_routing import build_capacity_review_context
from backend.app.modules.design.generation.maas.book_language.downstream_hard_gate import LegalGenerationContext, generation_site_at_height
from backend.app.modules.design.generation.maas.book_language.final_mesh_floor_evidence import FinalMeshFloorEvidenceError, resolve_candidate_finalization_context
from backend.app.modules.design.generation.maas.book_language.portfolio_selection import _select
from backend.app.modules.design.generation.maas.book_language.reference_context import _audited_final_book_references
from backend.app.modules.design.generation.maas.book_language.stage_outcome import StageOutcome, record_stage_outcome
from backend.app.modules.design.generation.maas.book_language.vlm_stage_policy import book_vlm_stage_policy


class _RepairParentFinalizationContextMismatch(ValueError):
    def __init__(self, evidence: dict[str, Any]) -> None:
        super().__init__("repair_parent_finalization_context_mismatch")
        self.evidence = evidence


def _finalization_context_fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _certified_repair_floor_context_binding(
    parent_metadata: dict[str, Any],
    *,
    expected_context: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Copy only a canonically certified parent's immutable floor binding."""

    floor_context = parent_metadata.get("candidate_floor_context")
    capacity_contract = parent_metadata.get("candidate_capacity_contract")
    semantic_context = parent_metadata.get("final_semantic_projection_context")
    base_capacity_contract = parent_metadata.get("base_capacity_contract")
    missing_fields = [
        name
        for name, value in (
            ("candidate_floor_context", floor_context),
            ("candidate_capacity_contract", capacity_contract),
            ("final_semantic_projection_context", semantic_context),
            ("base_capacity_contract", base_capacity_contract),
        )
        if type(value) is not dict
    ]
    floor_context = floor_context if type(floor_context) is dict else {}
    capacity_contract = (
        capacity_contract if type(capacity_contract) is dict else {}
    )
    semantic_context = semantic_context if type(semantic_context) is dict else {}
    base_capacity_contract = (
        base_capacity_contract if type(base_capacity_contract) is dict else {}
    )
    trusted_legal_floor_field = base_capacity_contract.get("legal_floor_field")
    required_aliases = (
        (
            "candidate_floor_context.legal_floor_field_hash",
            floor_context.get("legal_floor_field_hash"),
        ),
        (
            "candidate_capacity_contract.legal_floor_field_hash",
            capacity_contract.get("legal_floor_field_hash"),
        ),
        (
            "candidate_capacity_contract.candidate_legal_floor_field_hash",
            capacity_contract.get("candidate_legal_floor_field_hash"),
        ),
        (
            "candidate_capacity_contract.floor_capacity_plan_hash",
            capacity_contract.get("floor_capacity_plan_hash"),
        ),
        (
            "final_semantic_projection_context.pnu",
            semantic_context.get("pnu"),
        ),
        (
            "final_semantic_projection_context.legal_floor_field_hash",
            semantic_context.get("legal_floor_field_hash"),
        ),
        (
            "final_semantic_projection_context.floor_capacity_plan_hash",
            semantic_context.get("floor_capacity_plan_hash"),
        ),
        (
            "base_capacity_contract.legal_floor_field",
            trusted_legal_floor_field,
        ),
        (
            "base_capacity_contract.legal_floor_field.legal_floor_field_hash",
            (
                trusted_legal_floor_field.get("legal_floor_field_hash")
                if type(trusted_legal_floor_field) is dict
                else None
            ),
        ),
        (
            "base_capacity_contract.floor_capacity_plan_hash",
            base_capacity_contract.get("floor_capacity_plan_hash"),
        ),
    )
    missing_fields.extend(
        path
        for path, value in required_aliases
        if value is None or value == ""
    )
    missing_fields = list(dict.fromkeys(missing_fields))
    source_legal_floor_field_hash = str(
        floor_context.get("legal_floor_field_hash") or ""
    )
    source_pnu = str(semantic_context.get("pnu") or "")
    source_floor_plan_hash = str(
        capacity_contract.get("floor_capacity_plan_hash")
        or semantic_context.get("floor_capacity_plan_hash")
        or base_capacity_contract.get("floor_capacity_plan_hash")
        or ""
    )
    source_context = {
        "pnu": source_pnu,
        "legal_floor_field_hashes": sorted({str(value or "") for value in (
            floor_context.get("legal_floor_field_hash"),
            capacity_contract.get("legal_floor_field_hash"),
            capacity_contract.get("candidate_legal_floor_field_hash"),
            semantic_context.get("legal_floor_field_hash"),
            (
                trusted_legal_floor_field.get("legal_floor_field_hash")
                if isinstance(trusted_legal_floor_field, dict)
                else ""
            ),
        )}),
        "floor_capacity_plan_hashes": sorted({str(value or "") for value in (
            capacity_contract.get("floor_capacity_plan_hash"),
            semantic_context.get("floor_capacity_plan_hash"),
            base_capacity_contract.get("floor_capacity_plan_hash"),
        )}),
    }
    normalized_expected_context = {
        "pnu": str((expected_context or {}).get("pnu") or ""),
        "legal_floor_field_hash": str(
            (expected_context or {}).get("legal_floor_field_hash") or ""
        ),
        "floor_capacity_plan_hash": str(
            (expected_context or {}).get("floor_capacity_plan_hash") or ""
        ),
    }
    mismatched_fields: list[str] = []
    if expected_context is not None:
        if source_pnu != normalized_expected_context["pnu"]:
            mismatched_fields.append("pnu")
        if (
            not normalized_expected_context["legal_floor_field_hash"]
            or any(
                value != normalized_expected_context["legal_floor_field_hash"]
                for value in source_context["legal_floor_field_hashes"]
            )
        ):
            mismatched_fields.append("legal_floor_field_hash")
        if (
            not normalized_expected_context["floor_capacity_plan_hash"]
            or any(
                value != normalized_expected_context["floor_capacity_plan_hash"]
                for value in source_context["floor_capacity_plan_hashes"]
            )
        ):
            mismatched_fields.append("floor_capacity_plan_hash")
    mismatch_evidence = {
        "source_context_fingerprint": _finalization_context_fingerprint(
            source_context
        ),
        "expected_context_fingerprint": _finalization_context_fingerprint(
            normalized_expected_context
        ),
        "missing_fields": missing_fields,
        "mismatched_fields": list(dict.fromkeys(mismatched_fields)),
    }
    if missing_fields or mismatched_fields:
        raise _RepairParentFinalizationContextMismatch(mismatch_evidence)
    try:
        resolve_candidate_finalization_context(
            parent_metadata,
            trusted_legal_floor_field=trusted_legal_floor_field,
            expected_legal_floor_field_hash=source_legal_floor_field_hash,
            expected_pnu=source_pnu,
        )
    except FinalMeshFloorEvidenceError as exc:
        raise _RepairParentFinalizationContextMismatch({
            **mismatch_evidence,
            "mismatched_fields": [str(exc.code)],
        }) from exc
    return {
        "candidate_floor_context": deepcopy(floor_context),
        "candidate_capacity_contract": deepcopy(capacity_contract),
    }


def _materialize_repaired_floor_contract(
    source: Any,
    *,
    generation_context: LegalGenerationContext | None,
    capacity_site: Polygon | None,
    height: float,
    floors: int,
    base_capacity_contract: dict[str, Any] | None,
    repaired_program: GeometryProgram,
    repaired_compilation: Any,
) -> dict[str, Any] | None:
    """Recompute floor plates from the exact post-VLM geometry identity."""

    if generation_context is None or capacity_site is None:
        return None
    return materialize_shared_floor_contract(
        source,
        site_local_utm=capacity_site,
        legal_sections=tuple(
            generation_site_at_height(
                generation_context,
                float(height) * floor_number / max(1, int(floors)),
            )
            for floor_number in range(1, max(1, int(floors)) + 1)
        ),
        height_m=height,
        floors=floors,
        program_hash=repaired_program.program_hash(),
        geometry_hash=str(repaired_compilation.geometry_hash or ""),
        floor_capacity_plan_hash=str(
            (base_capacity_contract or {}).get("floor_capacity_plan_hash")
            or ""
        ),
        feasible_capacity_m2=float(
            (base_capacity_contract or {}).get("feasible_maximum_floor_area_m2")
            or 0.0
        ),
    )


def _book_stage_capacity_floor(candidate: _Candidate, review_stage: str) -> float:
    """Normalize a developmental base floor by the exact p.3 scope.

    A 1/16 base is intentionally one sixteenth of its host; judging it against
    40% of the completed program before combination/aggregation erases the
    source grammar. Final solids retain the unscaled competition floor.
    """
    policy = book_vlm_stage_policy(review_stage)
    floor = max(0.0, float(policy.minimum_feasible_capacity_utilization))
    if policy.capacity_normalization != "book_scope_fraction":
        return floor
    try:
        fraction = float(book_base_volume_spec(_scope_key(candidate)).fraction)
    except (KeyError, TypeError, ValueError):
        fraction = 1.0
    return floor * max(0.0, min(1.0, fraction))


def _has_exact_geometry_program(candidate: _Candidate) -> bool:
    """Return whether the exact recursive AST required by this critic exists."""
    raw = candidate.source.metadata.get("geometry_program") or {}
    if not isinstance(raw, dict) or not isinstance(raw.get("nodes"), list):
        return False
    try:
        GeometryProgram.from_dict(raw)
    except (TypeError, ValueError):
        return False
    return True


def _final_book_vlm_hard_pass(
    result: dict[str, Any],
    *,
    candidate_morphology: dict[str, Any] | None = None,
    candidate_design_concept: dict[str, Any] | None = None,
    candidate_capacity: dict[str, Any] | None = None,
    minimum_capacity_utilization: float = 0.0,
    review_stage: str = "final_book",
) -> tuple[bool, list[str]]:
    """Gate an image review with an explicit BOOK-stage quality contract."""
    policy = book_vlm_stage_policy(review_stage)
    scores = result.get("concept_scores") if isinstance(result.get("concept_scores"), dict) else {}
    actions = {str(value) for value in result.get("critic_actions") or ()}
    provider_action_payload = result.get("provider_critic_actions")
    provider_actions = (
        {str(value) for value in provider_action_payload}
        if isinstance(provider_action_payload, list)
        else set(actions)
    )
    local_actions = {
        str(value)
        for value in result.get("locally_derived_critic_actions") or ()
    }
    provider_program_fit_hard_pass = bool(result.get(
        "provider_program_fit_hard_pass",
        result.get("program_fit_hard_pass"),
    ))
    failures: list[str] = []
    hard_failures: list[str] = []
    reference_gate = (
        result.get("reference_massing_gate")
        if isinstance(result.get("reference_massing_gate"), dict)
        else {}
    )
    if reference_gate and not bool(reference_gate.get("hard_pass")):
        code = f"{policy.stage}_reference_massing_suitability_failed"
        failures.append(code)
        hard_failures.append(code)
    if policy.require_program_fit and not provider_program_fit_hard_pass:
        failures.append("final_book_program_fit_failed")
        hard_failures.append("final_book_program_fit_failed")
    for action in sorted(actions & policy.blocking_actions):
        code = f"{policy.stage}_vlm_{action}"
        failures.append(code)
        if (
            action in provider_actions
            or policy.locally_derived_actions_hard_gate
            and action in local_actions
        ):
            hard_failures.append(code)
    for concept, floor in policy.quality_floors.items():
        if float(scores.get(concept) or 0.0) + 1e-9 < floor:
            code = f"{policy.stage}_{concept}_below_{policy.quality_floor_label}"
            failures.append(code)
            if policy.quality_floors_hard_gate:
                hard_failures.append(code)
    # Capacity utilization is a design-development diagnostic, not a visual
    # acceptance authority.  Statutory BCR/FAR and program feasibility are
    # enforced by their dedicated gates; a VLM-approved mass must not be
    # discarded merely because it leaves optional capacity unused.
    if not policy.require_finished_silhouette:
        return not hard_failures, failures
    # The scorer already derives fragmentation actions from hierarchy and
    # repair integrity. This additional explicit field catches arbitrary cake
    # tiers that can retain both scores while repeating one silhouette.
    if (
        float(scores.get("non_stair_silhouette") or 0.0) < 0.55
        and "good_step_mass" not in actions
    ):
        failures.append("final_book_arbitrary_tier_silhouette")
    # ``pyramidal_like`` is a coarse morphology diagnostic.  The visual critic
    # already scores hierarchy, silhouette and program fit and can explicitly
    # approve a good stepped mass.  Do not let this static label overrule that
    # typed VLM judgment; unresolved relations remain useful downstream repair
    # context rather than a pruning gate.
    # A critic request for a carved public void is advisory only when no
    # verified access relation exists.  Once the final AST declares an access
    # side, however, accepting the same sealed mass would contradict both the
    # visual diagnosis and the typed design-concept graph.  Require a revised
    # frontage-bound controller instead of letting a high average score hide
    # the unresolved public threshold.
    target_access_side = str(
        (candidate_design_concept or {}).get("target_access_side_in_program_frame")
        or "closed"
    )
    if (
        target_access_side != "closed"
        and not bool((candidate_design_concept or {}).get("frontage_aligned"))
        and "needs_carved_void" in actions
    ):
        failures.append("final_book_unresolved_public_threshold_relation")
    return not hard_failures, failures


def _final_book_vlm_shortlist(
    pool: list[_Candidate],
    *,
    target: int,
    visual_directive: dict[str, Any],
) -> list[_Candidate]:
    """Stratify exact final solids before the expensive visual critic."""
    if not pool or target <= 0:
        return []
    if target == 1:
        # A one-shot smoke review has no diversity quota to allocate. The
        # former family-round-robin picked the alphabetically first core
        # family (attached_volume) even when the measured selector ranked a
        # cleaner, capacity-target five-floor MASS first. Review the exact
        # candidate that would otherwise be selected.
        selector = _select(
            pool,
            1,
            visual_directive=visual_directive,
        )[:1]
        selector_winner = (
            selector[0]
            if selector
            else max(
                pool,
                key=lambda candidate: float(
                    getattr(candidate, "score", 0.0) or 0.0
                ),
            )
        )
        return [
            _architectural_one_shot_candidate(
                pool,
                selector_winner=selector_winner,
            )
        ]
    # The procedural control archive is much larger than the live authored
    # lane. Without a review reservation, valid LLM ASTs can pass compiler,
    # clean and program gates yet receive only 2/64 final image reviews. This
    # quota grants review bandwidth, never selection or score preference.
    authored = [candidate for candidate in pool if _llm_authored_candidate(candidate)]
    authored_target = min(
        len(authored),
        target,
        max(1, target // 4),
    )
    authored_strata: dict[tuple[str, str, str], list[_Candidate]] = {}
    for candidate in sorted(authored, key=lambda item: item.score, reverse=True):
        key = (
            _geometry_program_family(candidate),
            _scope_key(candidate),
            str(_solid_morphology_metrics(candidate)["phenotype"]),
        )
        authored_strata.setdefault(key, []).append(candidate)
    chosen: list[_Candidate] = []
    authored_depth = 0
    while len(chosen) < authored_target:
        added = False
        for key in sorted(authored_strata):
            bucket = authored_strata[key]
            if authored_depth >= len(bucket):
                continue
            chosen.append(bucket[authored_depth])
            added = True
            if len(chosen) >= authored_target:
                break
        if not added:
            break
        authored_depth += 1
    # The executable core lane is the architectural alphabet (L/U/court,
    # cross, split bridge, sweep, overlap...), while bounded synthesis is the
    # larger combinatorial vocabulary.  A score-only shortlist let the 64
    # synthesis programs consume almost every review slot: in r144, seven
    # core families had 113 program-hard-pass descendants, yet only six exact
    # core candidates were ever shown to the VLM.  Reserve *review bandwidth*
    # across core family/scope strata.  This grants no hard-pass or selection
    # preference; every reserved candidate still faces the identical critic.
    core = [
        candidate for candidate in pool
        if _form_bank_lane(candidate) == "executable_core_language"
    ]
    core_family_count = len({
        _geometry_program_family(candidate) for candidate in core
        if _geometry_program_family(candidate)
    })
    core_target = min(
        len(core),
        # Review two BOOK projections per available core family when budget
        # permits. One projection can distort a good chassis (r145's only
        # split-bridge review used SHIFT and read as toy blocks); a second is
        # still a review quota, not a pass or selection preference.
        max(min(core_family_count * 2, target), target // 3),
    )
    core_strata: dict[str, list[_Candidate]] = {}
    for candidate in sorted(core, key=lambda item: item.score, reverse=True):
        # Family is the first axis on purpose: using family+scope as a key
        # allowed two high-score variants from the first nine alphabetic
        # families to consume all 18 reserved slots.
        key = _geometry_program_family(candidate)
        core_strata.setdefault(key, []).append(candidate)
    chosen_ids = {id(candidate) for candidate in chosen}
    core_depth = 0
    while sum(_form_bank_lane(candidate) == "executable_core_language" for candidate in chosen) < core_target:
        added = False
        for key in sorted(core_strata):
            bucket = core_strata[key]
            if core_depth >= len(bucket):
                continue
            candidate = bucket[core_depth]
            if id(candidate) not in chosen_ids:
                chosen.append(candidate)
                chosen_ids.add(id(candidate))
                added = True
            if sum(_form_bank_lane(item) == "executable_core_language" for item in chosen) >= core_target:
                break
        if not added:
            break
        core_depth += 1

    # Board-level family supply caps belong to final selection. Applying them
    # here prevented the individual critic from ever seeing alternate members
    # of an overrepresented family, even though one could be the single keeper.
    review_directive = dict(visual_directive)
    review_directive.pop("max_geometry_family_counts", None)
    provisional = _select(pool, min(20, target), visual_directive=review_directive)
    chosen.extend(candidate for candidate in provisional if id(candidate) not in chosen_ids)
    chosen_ids = {id(candidate) for candidate in chosen}
    strata: dict[tuple[str, str, str, str], list[_Candidate]] = {}
    for candidate in sorted(pool, key=lambda item: item.score, reverse=True):
        if id(candidate) in chosen_ids:
            continue
        key = (
            _geometry_program_family(candidate),
            str(_solid_morphology_metrics(candidate)["phenotype"]),
            _scope_key(candidate),
            candidate.principle_kind,
        )
        strata.setdefault(key, []).append(candidate)
    depth = 0
    while len(chosen) < target:
        added = False
        for key in sorted(strata):
            bucket = strata[key]
            if depth >= len(bucket):
                continue
            candidate = bucket[depth]
            if id(candidate) not in chosen_ids:
                chosen.append(candidate)
                chosen_ids.add(id(candidate))
                added = True
            if len(chosen) >= target:
                break
        if not added:
            break
        depth += 1
    return chosen[:target]


def _architectural_one_shot_candidate(
    pool: list[_Candidate],
    *,
    selector_winner: _Candidate,
) -> _Candidate:
    """Prefer typed public/program evidence before spending one paid review.

    Every input has already passed the same capacity, legal, parking and
    shared-floor gates.  This function only prevents a one-shot smoke budget
    from repeatedly choosing a generic capacity pack when another hard-pass
    candidate carries executable public-space and program/section relations.
    """

    priorities: dict[int, tuple[float, float]] = {}
    for candidate in pool:
        try:
            concept = _design_concept_descriptor(candidate)
            morphology = _solid_morphology_metrics(candidate)
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        public_controller = bool(
            concept.get("open_voids")
            or concept.get("frontage_notches")
            or concept.get("frontage_relations")
        )
        phenotype = str(morphology.get("phenotype") or "prismatic")
        score = 0.0
        score += 4.0 if concept.get("frontage_aligned") else 0.0
        score += 3.0 if public_controller else 0.0
        score += 2.0 if concept.get("program_controller_node_ids") else 0.0
        score += 2.0 if concept.get("section_controller_node_ids") else 0.0
        score += 2.0 if phenotype == "voided" else 0.0
        score += 1.0 if phenotype in {"winged", "stepped", "curved", "oblique"} else 0.0
        score -= 3.0 if concept.get("missing_required_concepts") else 0.0
        score -= 2.0 if concept.get("ground_strategy") == "direct_edge" else 0.0
        score -= 2.0 if phenotype == "prismatic" else 0.0
        score -= 2.0 if (
            morphology.get("pyramidal_like")
            or morphology.get("wedge_like")
        ) else 0.0
        priorities[id(candidate)] = (
            score,
            float(getattr(candidate, "score", 0.0) or 0.0),
        )

    winner_priority = priorities.get(id(selector_winner))
    if not priorities or winner_priority is None:
        return selector_winner
    architectural_winner = max(
        (
            candidate for candidate in pool
            if id(candidate) in priorities
        ),
        key=lambda candidate: priorities[id(candidate)],
    )
    if priorities[id(architectural_winner)] <= winner_priority:
        return selector_winner
    return architectural_winner


def _exclude_prior_final_book_vlm_failures(
    pool: list[_Candidate],
    *,
    outcome_graph: GeometryOutcomeGraph | None,
    program_slug: str,
) -> tuple[list[_Candidate], dict[str, Any]]:
    """Avoid paying to review one unchanged exact geometry twice."""

    failed_hashes = (
        outcome_graph.failed_final_book_geometry_hashes(program_slug)
        if outcome_graph is not None
        else set()
    )
    filtered = [
        candidate
        for candidate in pool
        if str(
            (
                candidate.source.metadata.get(
                    "geometry_program_bridge_evidence"
                )
                or {}
            ).get("geometry_hash")
            or ""
        )
        not in failed_hashes
    ]
    return filtered, {
        "schema_version": "arr.maas.prior_final_vlm_failure_filter.v1",
        "program_slug": str(program_slug),
        "known_failed_geometry_count": len(failed_hashes),
        "prior_exact_failure_count": len(pool) - len(filtered),
        "remaining_candidate_count": len(filtered),
        "identity": "exact_geometry_hash",
        "paid_repeat_prevented": len(pool) - len(filtered) > 0,
    }


def _lineage_parent_key(candidate: _Candidate) -> str:
    lineage = candidate.source.metadata.get("book_generation_lineage") or {}
    return str(lineage.get("parent_key") or "")


def _archived_exact_surface_geometry_hash(candidate: _Candidate) -> str:
    """Return only the independently archived projected-surface identity."""

    metadata = candidate.source.metadata
    review_authority = metadata.get("program_review_authority") or {}
    program_gate_result = metadata.get("program_gate_result") or {}
    certificate = metadata.get("authored_legal_projection_certificate") or {}
    geometry_hash = str(metadata.get("final_geometry_hash") or "")
    surface_payload_hash = str(
        metadata.get("final_surface_payload_hash") or ""
    )
    if not (
        isinstance(review_authority, dict)
        and review_authority.get("legal_archive_authority") is True
        and isinstance(program_gate_result, dict)
        and (
            (
                program_gate_result.get("hard_pass") is True
                and review_authority.get("selection_eligible") is True
            )
            or (
                program_gate_result.get("hard_pass") is False
                and review_authority.get("development_review_eligible") is True
            )
        )
        and isinstance(certificate, dict)
        and certificate.get("status") == "verified"
        and certificate.get("hard_pass") is True
        and geometry_hash
        and surface_payload_hash
        and str(certificate.get("projected_surface_hash") or "")
        == geometry_hash
        and str(certificate.get("projected_surface_payload_hash") or "")
        == surface_payload_hash
    ):
        return ""
    return geometry_hash


def _base_review_fingerprint(candidate: _Candidate) -> str:
    """Stable identity for one rendered base, independent of run-local names."""
    compilation = candidate.source.metadata.get("geometry_program_compilation") or {}
    geometry_hash = (
        _archived_exact_surface_geometry_hash(candidate)
        or str(compilation.get("geometry_hash") or "")
    )
    raw_program = candidate.source.metadata.get("geometry_program") or {}
    if geometry_hash:
        payload = {"geometry_hash": geometry_hash}
    elif isinstance(raw_program, dict) and raw_program:
        try:
            payload = {"program_hash": GeometryProgram.from_dict(raw_program).program_hash()}
        except (KeyError, TypeError, ValueError):
            payload = {"program": raw_program}
    else:
        payload = {
            "parent_key": _lineage_parent_key(candidate),
            "principle_id": candidate.principle_id,
            "scope": _scope_key(candidate),
        }
    return hashlib.sha256(json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _book_vlm_review_contract(review_stage: str) -> dict[str, Any]:
    """Return the immutable contract that makes a visual verdict reusable.

    Exact geometry alone is insufficient: a verdict from another model,
    prompt, or stage gate must never silently approve a current base.  The PNU
    and program are graph-level/query-level boundaries; this fingerprint
    covers the remaining visual-review semantics.
    """
    policy = book_vlm_stage_policy(review_stage)
    evidence = {
        "review_stage": str(review_stage),
        "model": str(os.getenv("MAAS_PREFERENCE_VLM_MODEL") or DEFAULT_VLM_MODEL),
        "prompt_contract_version": VLM_PROMPT_CONTRACT_VERSION,
        "gate_policy": policy.to_evidence(),
    }
    evidence["fingerprint"] = hashlib.sha256(json.dumps(
        evidence,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return evidence


def _book_vlm_review_budget(review_stage: str) -> int:
    """Keep base-parent and final-solid review coverage independently bounded."""
    if review_stage == "book_base_operative":
        variable, default, ceiling = "MAAS_BOOK_BASE_VLM_TOP_K", 8, 32
    else:
        variable, default, ceiling = "MAAS_FINAL_BOOK_VLM_TOP_K", 12, 48
    try:
        return max(1, min(ceiling, int(os.getenv(variable, str(default)))))
    except (TypeError, ValueError):
        return default


def _final_book_vlm_recovery_workers() -> int:
    try:
        return max(
            0,
            min(
                2,
                int(os.getenv("MAAS_FINAL_BOOK_VLM_RECOVERY_WORKERS", "1")),
            ),
        )
    except (TypeError, ValueError):
        return 1


class FinalSemanticProjectionAuthorityError(ValueError):
    """Typed refusal to certify a stale or invalid semantic projection."""

    def __init__(self, evidence: dict[str, Any]) -> None:
        self.evidence = dict(evidence)
        super().__init__(
            "final_semantic_projection_authority_invalid: "
            + str(self.evidence.get("reason") or "unknown")
        )


def _repaired_source_semantic_projection_gate(
    candidate: _Candidate,
    downstream_gate: dict[str, Any],
) -> dict[str, Any]:
    downstream_failures = {
        str(reason)
        for reason in downstream_gate.get("failures") or ()
        if str(reason)
    }
    if (
        downstream_gate.get("hard_pass") is not True
        and downstream_failures != {"capacity_measurement_hash_mismatch"}
    ):
        raise FinalSemanticProjectionAuthorityError({
            "reason": "downstream_semantic_projection_hard_gate_failed",
            "failures": sorted(downstream_failures),
        })
    evidence = candidate.source.metadata.get(
        "program_semantic_carrier_evidence"
    )
    if not isinstance(evidence, dict) or evidence.get("hard_pass") is not True:
        raise FinalSemanticProjectionAuthorityError({
            "reason": "source_semantic_projection_certificate_missing_or_failed",
            "failures": list(
                evidence.get("failures") or ()
                if isinstance(evidence, dict)
                else ()
            ),
        })
    expected_context = {
        key: evidence.get(key)
        for key in (
            "floor_capacity_plan_hash",
            "pnu",
            "site_context_hash",
            "capacity_alternative_id",
            "achieved_capacity_band",
            "capacity_measurement_hash",
        )
    }
    audit = audit_source_semantic_projection(
        candidate.source,
        building_type=str(evidence.get("program_id") or ""),
        expected_context=expected_context,
    )
    if audit.get("hard_pass") is not True:
        raise FinalSemanticProjectionAuthorityError({
            "reason": "source_semantic_projection_certificate_revalidation_failed",
            "failures": list(audit.get("failures") or ()),
        })
    return deepcopy(audit)


def _bind_final_visual_authority_for_review(
    candidate: _Candidate,
    semantic_projection_hard_gate: dict[str, Any],
) -> None:
    audit = _repaired_source_semantic_projection_gate(
        candidate,
        semantic_projection_hard_gate,
    )
    certified = CertifiedMassArtifact.issue(
        candidate.source,
        semantic_audit=audit,
    )
    props = candidate.feature.setdefault("properties", {})
    props.update(certified.feature_binding())
    props["semantic_projection_hard_gate"] = audit


def _book_base_parent_shortlist(
    pool: list[_Candidate],
    *,
    target: int,
    visual_directive: dict[str, Any],
) -> tuple[list[_Candidate], dict[str, Any]]:
    """Choose base reviews from the descendants the final board may use.

    A generic base-only shortlist can spend the complete VLM budget on
    attractive one-operative masses whose exact lineages have no competitive
    combination or aggregation left in the downstream pool.  Start from a
    structurally stratified descendant shortlist, resolve its exact base
    parents, then use ordinary base strata only to fill unused review slots.
    This preserves the base-before-descendant causal contract without making
    unreviewed parents indistinguishable from visually rejected parents.
    """
    review_target = max(0, min(int(target), len(pool)))
    bases = [
        candidate for candidate in pool
        if str((candidate.source.metadata.get("book_generation_lineage") or {}).get("stage") or "")
        == "base"
    ]
    descendants = [
        candidate for candidate in pool
        if str((candidate.source.metadata.get("book_generation_lineage") or {}).get("stage") or "")
        != "base"
    ]
    bases_by_key: dict[str, _Candidate] = {}
    base_fingerprints_by_geometry: dict[str, set[str]] = {}
    base_fingerprints_by_program: dict[str, set[str]] = {}
    for candidate in sorted(bases, key=lambda item: item.score, reverse=True):
        fingerprint = _base_review_fingerprint(candidate)
        bases_by_key[fingerprint] = candidate
        metadata = candidate.source.metadata
        compilation = metadata.get("geometry_program_compilation") or {}
        geometry_hash = _archived_exact_surface_geometry_hash(candidate)
        if geometry_hash:
            base_fingerprints_by_geometry.setdefault(geometry_hash, set()).add(fingerprint)
        program = metadata.get("geometry_program") or {}
        program_metadata = program.get("metadata") or {}
        program_hash = str(
            compilation.get("program_hash")
            or program.get("program_hash")
            or program_metadata.get("pre_book_program_hash")
            or ""
        )
        if program_hash:
            base_fingerprints_by_program.setdefault(program_hash, set()).add(fingerprint)

    def exact_parent_fingerprint(candidate: _Candidate) -> str:
        lineage = candidate.source.metadata.get("book_generation_lineage") or {}
        supplied: list[str] = []
        fingerprint = str(
            lineage.get("parent_base_review_fingerprint")
            or lineage.get("base_review_fingerprint")
            or ""
        )
        if fingerprint:
            if fingerprint not in bases_by_key:
                return ""
            supplied.append(fingerprint)
        geometry_hash = str(lineage.get("parent_geometry_hash") or "")
        if geometry_hash:
            matches = base_fingerprints_by_geometry.get(geometry_hash, set())
            if len(matches) != 1:
                return ""
            supplied.append(next(iter(matches)))
        program_hash = str(lineage.get("parent_program_hash") or "")
        if program_hash:
            matches = base_fingerprints_by_program.get(program_hash, set())
            if len(matches) != 1:
                return ""
            supplied.append(next(iter(matches)))
        return supplied[0] if supplied and len(set(supplied)) == 1 else ""

    # Reserve base-review bandwidth before descendant parent resolution.  In
    # r150, 60 descendant parents consumed a 64-image budget and left only
    # four generic fallback slots. Three valid split_bridge bases therefore
    # existed but were never seen by the VLM. Required families and one
    # representative of every executable core family are review anchors only;
    # they gain no score or hard-pass preference.
    required_families = tuple(dict.fromkeys(
        str(value)
        for value in visual_directive.get("required_geometry_program_families") or ()
        if str(value)
    ))
    geometry_review_caps = {
        str(family): max(1, int(cap))
        for family, cap in (visual_directive.get("max_geometry_family_counts") or {}).items()
        if str(family)
    }
    chassis_review_caps = {
        str(family): max(1, int(cap))
        for family, cap in (visual_directive.get("max_chassis_family_counts") or {}).items()
        if str(family)
    }
    global_chassis_review_cap = max(
        0,
        int(visual_directive.get("max_chassis_family_count") or 0),
    )
    review_geometry_usage: Counter[str] = Counter()
    review_chassis_usage: Counter[str] = Counter()
    review_cap_skip_counts: Counter[str] = Counter()

    def capped_chassis_family(candidate: _Candidate) -> str:
        if not chassis_review_caps and not global_chassis_review_cap:
            return ""
        return _chassis_family(candidate)

    def can_add(candidate: _Candidate) -> bool:
        geometry_family = _geometry_program_family(candidate)
        chassis_family = capped_chassis_family(candidate)
        geometry_cap = geometry_review_caps.get(geometry_family)
        chassis_cap = chassis_review_caps.get(chassis_family, global_chassis_review_cap or None)
        if geometry_cap is not None and review_geometry_usage[geometry_family] >= geometry_cap:
            review_cap_skip_counts[f"geometry:{geometry_family}"] += 1
            return False
        if chassis_cap is not None and review_chassis_usage[chassis_family] >= chassis_cap:
            review_cap_skip_counts[f"chassis:{chassis_family}"] += 1
            return False
        return True

    def add(candidate: _Candidate) -> bool:
        if id(candidate) in chosen_ids or not can_add(candidate):
            return False
        chosen.append(candidate)
        chosen_ids.add(id(candidate))
        review_geometry_usage[_geometry_program_family(candidate)] += 1
        chassis_family = capped_chassis_family(candidate)
        if chassis_family:
            review_chassis_usage[chassis_family] += 1
        return True

    base_strata: dict[str, list[_Candidate]] = {}
    base_chassis_strata: dict[str, list[_Candidate]] = {}
    for candidate in sorted(bases, key=lambda item: item.score, reverse=True):
        base_strata.setdefault(_geometry_program_family(candidate), []).append(candidate)
        chassis_family = _chassis_family(candidate)
        if chassis_family not in {"", "generic_chassis", "recursive_chassis:unclassified"}:
            base_chassis_strata.setdefault(chassis_family, []).append(candidate)
    core_families = sorted({
        _geometry_program_family(candidate)
        for candidate in bases
        if _form_bank_lane(candidate) == "executable_core_language"
        and _geometry_program_family(candidate)
    })
    anchor_target = min(
        review_target,
        max(
            len([family for family in required_families if family in base_strata]),
            len(core_families),
            len(base_chassis_strata),
            review_target // 3,
        ),
    )
    chosen: list[_Candidate] = []
    chosen_ids: set[int] = set()
    for family in required_families:
        if len(chosen) >= review_target:
            break
        match = next((
            candidate for candidate in base_strata.get(family, ())
            if id(candidate) not in chosen_ids and can_add(candidate)
        ), None)
        if match is not None:
            add(match)
    # Geometry-family anchors alone still allowed several author families to
    # collapse onto the same plan chassis (for example many agents producing
    # the same courtyard or bent bar). Reserve one review seat per measured
    # chassis, rarest supply first. This is taxonomy-derived coverage only:
    # each candidate must still pass the unchanged base and final VLM gates.
    chassis_families = sorted(
        base_chassis_strata,
        key=lambda family: (len(base_chassis_strata[family]), family),
    )
    for chassis_family in chassis_families:
        if len(chosen) >= anchor_target:
            break
        match = next((
            candidate for candidate in base_chassis_strata[chassis_family]
            if id(candidate) not in chosen_ids and can_add(candidate)
        ), None)
        if match is not None:
            add(match)
    core_depth = 0
    while len(chosen) < anchor_target:
        added = False
        for family in core_families:
            bucket = base_strata.get(family, [])
            if core_depth >= len(bucket):
                continue
            candidate = bucket[core_depth]
            if add(candidate):
                added = True
            if len(chosen) >= anchor_target:
                break
        if not added:
            break
        core_depth += 1

    descendant_shortlist = _final_book_vlm_shortlist(
        descendants,
        # Inspect the complete bounded descendant pool before applying typed
        # family quotas; taking only the first review_target here could leave
        # every alternate parent hidden behind capped families.
        target=len(descendants),
        visual_directive=visual_directive,
    )
    requested_parent_keys: list[str] = []
    for descendant in descendant_shortlist:
        parent_key = exact_parent_fingerprint(descendant)
        if parent_key and parent_key not in requested_parent_keys:
            requested_parent_keys.append(parent_key)

    for parent_key in requested_parent_keys:
        candidate = bases_by_key[parent_key]
        if id(candidate) in chosen_ids or not can_add(candidate):
            continue
        add(candidate)
        if len(chosen) >= review_target:
            break
    fallback = _final_book_vlm_shortlist(
        bases,
        target=len(bases),
        visual_directive=visual_directive,
    )
    for candidate in fallback:
        if id(candidate) in chosen_ids or not can_add(candidate):
            continue
        add(candidate)
        if len(chosen) >= review_target:
            break
    return chosen[:review_target], {
        "schema_version": "arr.maas.book_base_parent_shortlist.v1",
        "review_target": review_target,
        "base_candidate_count": len(bases),
        "descendant_candidate_count": len(descendants),
        "descendant_shortlist_count": len(descendant_shortlist),
        "requested_exact_parent_count": len(requested_parent_keys),
        "resolved_exact_parent_count": sum(
            _base_review_fingerprint(candidate) in requested_parent_keys
            for candidate in chosen[:review_target]
        ),
        "required_family_anchor_count": sum(
            _geometry_program_family(candidate) in required_families
            for candidate in chosen[:anchor_target]
        ),
        "executable_core_family_anchor_count": len({
            _geometry_program_family(candidate)
            for candidate in chosen[:anchor_target]
            if _form_bank_lane(candidate) == "executable_core_language"
        }),
        "chassis_family_anchor_count": len({
            _chassis_family(candidate)
            for candidate in chosen[:anchor_target]
        }),
        "base_anchor_target": anchor_target,
        "base_anchor_family_counts": dict(sorted(Counter(
            _geometry_program_family(candidate) or "unclassified"
            for candidate in chosen[:anchor_target]
        ).items())),
        "fallback_base_count": max(
            0,
            min(len(chosen), review_target)
            - anchor_target
            - sum(
                _base_review_fingerprint(candidate) in requested_parent_keys
                for candidate in chosen[anchor_target:review_target]
            ),
        ),
        "base_family_supply_counts": dict(sorted(Counter(
            _geometry_program_family(candidate) or "unclassified"
            for candidate in bases
        ).items())),
        "base_chassis_supply_counts": dict(sorted(Counter(
            _chassis_family(candidate) or "unclassified"
            for candidate in bases
        ).items())),
        "descendant_family_supply_counts": dict(sorted(Counter(
            _geometry_program_family(candidate) or "unclassified"
            for candidate in descendants
        ).items())),
        "descendant_shortlist_family_counts": dict(sorted(Counter(
            _geometry_program_family(candidate) or "unclassified"
            for candidate in descendant_shortlist
        ).items())),
        "resolved_parent_family_counts": dict(sorted(Counter(
            _geometry_program_family(candidate) or "unclassified"
            for candidate in chosen[:review_target]
        ).items())),
        "geometry_family_review_caps": dict(sorted(geometry_review_caps.items())),
        "chassis_family_review_caps": dict(sorted(chassis_review_caps.items())),
        "global_chassis_review_cap": global_chassis_review_cap,
        "review_cap_skip_counts": dict(sorted(review_cap_skip_counts.items())),
        "review_caps_are_supply_quotas_not_quality_relaxations": True,
        "review_order": "required_family_then_rare_chassis_then_core_alphabet_then_descendant_parent_then_fallback",
        "descendant_first_parent_resolution": True,
        "review_anchors_grant_no_hard_pass_or_selection_preference": True,
    }


def _attach_base_book_vlm_audit(
    candidate: _Candidate,
    audit: dict[str, Any],
    *,
    reused_from_outcome_graph: bool,
) -> _Candidate:
    """Normalize one base verdict without leaving a false final-stage audit."""
    normalized = deepcopy(audit)
    nested_audit = normalized.get("vlm_audit")
    nested_audit = nested_audit if isinstance(nested_audit, dict) else {}
    failures = tuple(
        str(value)
        for value in (
            normalized.get("failures")
            or nested_audit.get("failures")
            or ()
        )
    )
    response_id = str(
        normalized.get("response_id")
        or nested_audit.get("response_id")
        or ""
    )
    reviewed_exact = bool(
        normalized.get("reviewed_exact_post_book_geometry") is True
        or nested_audit.get("reviewed_exact_post_book_geometry") is True
    )
    review_stage = str(
        normalized.get("review_stage")
        or nested_audit.get("review_stage")
        or ""
    )
    blocking_tokens = (
        "structural", "invalid", "nonfinite", "degenerate", "empty_surface",
        "legal", "containment", "parking", "height", "bcr", "far",
    )
    blocking_failures = tuple(
        failure for failure in failures
        if any(token in failure.lower() for token in blocking_tokens)
    )
    actual_review = bool(
        response_id
        and reviewed_exact
        and review_stage == "book_base_operative"
    )
    descendant_development_hard_pass = bool(
        actual_review and not blocking_failures
    )
    normalized.update({
        "review_stage": "book_base_operative",
        "response_id": response_id,
        "failures": list(failures),
        "reviewed_exact_post_book_geometry": reviewed_exact,
        "reviewed_before_descendant_release": True,
        "reused_from_outcome_graph": bool(reused_from_outcome_graph),
        "base_review_fingerprint": _base_review_fingerprint(candidate),
        "base_selection_hard_pass": bool(normalized.get("hard_pass")),
        "descendant_development_hard_pass": (
            descendant_development_hard_pass
        ),
        "development_blocking_failures": list(blocking_failures),
        "capacity_is_diagnostic_for_descendant_development": True,
        "final_selection_authority": False,
    })
    metadata = dict(candidate.source.metadata)
    metadata.pop("final_book_vlm_audit", None)
    metadata["base_book_vlm_audit"] = normalized
    feature = deepcopy(candidate.feature)
    properties = feature.setdefault("properties", {})
    properties.pop("final_book_vlm_audit", None)
    properties["base_book_vlm_audit"] = deepcopy(normalized)
    scores = normalized.get("concept_scores")
    if isinstance(scores, dict) and scores:
        visual_score = sum(float(scores.get(key) or 0.0) for key in (
            "gesture_clarity", "hierarchy", "non_stair_silhouette", "void_publicness",
            "repair_integrity", "precedent_resonance", "program_appropriateness",
            "section_program_fit",
        )) / 8.0
        score = candidate.score * 0.72 + visual_score * 0.28
    else:
        score = candidate.score
    return replace(
        candidate,
        source=replace(candidate.source, metadata=metadata),
        feature=feature,
        score=score,
    )


def _audit_final_book_geometry_with_vlm(
    pool: list[_Candidate],
    *,
    building_type: str,
    output_dir: Path,
    visual_directive: dict[str, Any],
    outcome_graph: GeometryOutcomeGraph | None = None,
    program_slug: str = "",
    scorer: Any | None = None,
    reference_provider: Any | None = None,
    review_stage: str = "final_book",
    shortlist_override: list[_Candidate] | None = None,
    request_kind: str = "exact_candidate_vlm",
    paid_opportunity_limit: int | None = None,
) -> tuple[list[_Candidate], dict[str, Any]]:
    """Review the post-BOOK solid the user actually sees.

    The earlier recursive-program critic remains the author/reviser. This
    bounded pass closes the causal gap where later BOOK projection could make
    a floating plate or cake-tier silhouette that inherited an obsolete VLM
    score from its pre-BOOK parent.
    """
    maximum = _book_vlm_review_budget(review_stage)
    if paid_opportunity_limit is not None:
        maximum = min(maximum, max(0, int(paid_opportunity_limit)))
    snapshot = paid_provider_budget_snapshot()
    quota_name = (
        "base_candidate"
        if request_kind == "base_candidate_vlm"
        else "exact_candidate"
    )
    quota_remaining = (snapshot.get("quota_remaining_counts") or {}).get(
        quota_name
    )
    if quota_remaining is not None:
        maximum = min(maximum, max(0, int(quota_remaining)))
    try:
        workers = max(1, min(6, int(os.getenv("MAAS_FINAL_BOOK_VLM_WORKERS", "4"))))
    except (TypeError, ValueError):
        workers = 4
    input_count = len(pool)
    pool = [candidate for candidate in pool if _has_exact_geometry_program(candidate)]
    invalid_geometry_program_count = input_count - len(pool)
    if review_stage == "final_book":
        pool, prior_failure_filter = _exclude_prior_final_book_vlm_failures(
            pool,
            outcome_graph=outcome_graph,
            program_slug=program_slug or building_type,
        )
    else:
        prior_failure_filter = {
            "schema_version": "arr.maas.prior_final_vlm_failure_filter.v1",
            "status": "not_applicable_to_base_stage",
            "prior_exact_failure_count": 0,
            "remaining_candidate_count": len(pool),
            "paid_repeat_prevented": False,
        }
    if shortlist_override is not None:
        shortlist = [
            candidate for candidate in list(shortlist_override)
            if _has_exact_geometry_program(candidate)
        ][:min(maximum, len(pool))]
        target = min(maximum, len(pool))
        if len(shortlist) < target:
            selected_ids = {id(candidate) for candidate in shortlist}
            fallback = _final_book_vlm_shortlist(
                [candidate for candidate in pool if id(candidate) not in selected_ids],
                target=target - len(shortlist),
                visual_directive=visual_directive,
            )
            shortlist.extend(fallback)
    else:
        shortlist = _final_book_vlm_shortlist(
            pool,
            target=min(maximum, len(pool)),
            visual_directive=visual_directive,
        )
    cache_dir = Path(os.getenv(
        "MAAS_FINAL_BOOK_VLM_CACHE_DIR",
        "docs/ai-session-memory/reference-corpus/final-book-vlm-cache",
    ))
    preview_dir = output_dir / "final-book-vlm-previews"
    scorer = scorer or openai_preview_preference_scorer(
        preview_dir=preview_dir,
        cache_dir=cache_dir,
    )
    def evaluate(candidate: _Candidate) -> tuple[_Candidate, list[dict[str, Any]], dict[str, Any]]:
        raw_program = candidate.source.metadata.get("geometry_program") or {}
        program = GeometryProgram.from_dict(raw_program)
        references, reference_audit = _audited_final_book_references(
            program,
            building_type=building_type,
            reference_provider=reference_provider,
        )
        review_feature = deepcopy(candidate.feature)
        materialize_source_feature_surfaces(
            review_feature,
            candidate.source,
            height=float(
                review_feature.get("properties", {}).get("height")
                or review_feature.get("properties", {}).get("height_m")
                or 1.0
            ),
        )
        # This critic repairs the exact recursive post-BOOK AST.  It must not
        # emit edits against the separate legacy program-role component graph.
        review_feature.setdefault("properties", {})["geometry_only_critic_mode"] = True
        candidate_morphology = _solid_morphology_metrics(candidate)
        review_feature.setdefault("properties", {})["portfolio_diversity_context"] = {
            "schema_version": "arr.maas.final_book_candidate_context.v2",
            "candidate_phenotype": str(candidate_morphology["phenotype"]),
            "candidate_pyramidal_like": bool(candidate_morphology["pyramidal_like"]),
            "maximum_final_pyramidal_like_count": int(
                visual_directive.get("max_pyramidal_like_count", 2)
            ),
            "maximum_final_single_phenotype_count": int(
                visual_directive.get("max_solid_phenotype_count", 5)
            ),
            "critic_is_reviewing_exact_post_book_geometry": True,
            "book_review_stage": review_stage,
            "board_level_sibling_diversity_is_a_separate_vlm_gate": True,
            "volatile_pool_composition_excluded_from_candidate_identity": True,
        }
        review_feature["properties"]["capacity_review_context"] = (
            build_capacity_review_context(candidate.source.metadata)
        )
        with vlm_request_kind_scope(request_kind):
            result = scorer(
                feature=review_feature,
                reference_matches=list(references or ()),
                model=os.getenv("MAAS_PREFERENCE_VLM_MODEL") or None,
            )
        result["reference_massing_gate"] = {
            key: value
            for key, value in reference_audit.items()
            if key != "accepted"
        }
        return candidate, list(references or ()), result

    evaluated: dict[
        int,
        tuple[
            list[dict[str, Any]],
            dict[str, Any] | None,
            str,
            dict[str, Any],
        ],
    ] = {}
    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(shortlist)))) as executor:
        futures = {executor.submit(evaluate, candidate): candidate for candidate in shortlist}
        for future in as_completed(futures):
            candidate = futures[future]
            try:
                _candidate, references, result = future.result()
                evaluated[id(candidate)] = (references, result, "", {})
            except VlmBudgetExhaustedError as exc:
                evaluated[id(candidate)] = ([], None, str(exc)[:500], {
                    "budget_code": exc.budget_code,
                    "request_kind": exc.request_kind,
                    "quota": exc.quota,
                    "used": exc.used,
                    "limit": exc.limit,
                    "remaining": exc.remaining,
                })
            except Exception as exc:
                evaluated[id(candidate)] = ([], None, str(exc)[:500], {})

    # A transient provider timeout is not architectural evidence.  The scorer
    # already retries one HTTP request, but a burst of parallel calls can still
    # exhaust those attempts together.  Re-run only failed candidates at low
    # concurrency; completed paid calls are retained in the cache and never
    # repeated here.  Candidates that still fail remain rejected.
    initial_call_failures = {
        id(candidate): evaluated.get(
            id(candidate), ([], None, "missing_result", {})
        )[2]
        for candidate in shortlist
        if (
            evaluated.get(id(candidate), ([], None, "missing_result", {}))[2]
            or not isinstance(
                evaluated.get(id(candidate), ([], None, "missing_result", {}))[1],
                dict,
            )
        )
    }
    recovery_workers = _final_book_vlm_recovery_workers()
    recovery_candidates = [
        candidate for candidate in shortlist
        if id(candidate) in initial_call_failures
        and not evaluated.get(id(candidate), ([], None, "", {}))[3]
    ]
    if recovery_candidates and recovery_workers:
        with ThreadPoolExecutor(max_workers=min(recovery_workers, len(recovery_candidates))) as executor:
            futures = {
                executor.submit(evaluate, candidate): candidate
                for candidate in recovery_candidates
            }
            for future in as_completed(futures):
                candidate = futures[future]
                try:
                    _candidate, references, result = future.result()
                    evaluated[id(candidate)] = (references, result, "", {})
                except VlmBudgetExhaustedError as exc:
                    evaluated[id(candidate)] = ([], None, str(exc)[:500], {
                        "budget_code": exc.budget_code,
                        "request_kind": exc.request_kind,
                        "quota": exc.quota,
                        "used": exc.used,
                        "limit": exc.limit,
                        "remaining": exc.remaining,
                    })
                except Exception as exc:
                    evaluated[id(candidate)] = ([], None, str(exc)[:500], {})

    review_contract = _book_vlm_review_contract(review_stage)
    accepted: list[_Candidate] = []
    failure_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    llm_failure_counts: Counter[str] = Counter()
    llm_action_counts: Counter[str] = Counter()
    llm_hard_pass_count = 0
    scored_count = cache_hit_count = 0
    audit_records: list[dict[str, Any]] = []
    call_failure_records: list[dict[str, Any]] = []
    for candidate in shortlist:
        references, result, error, budget_failure = evaluated.get(
            id(candidate), ([], None, "missing_result", {})
        )
        if error or not isinstance(result, dict):
            failure_code = (
                "vlm_provider_budget_exhausted"
                if budget_failure
                else "final_book_vlm_call_failed"
            )
            failure_counts[failure_code] += 1
            call_failure_records.append({
                "source_sequence": candidate.sequence.name,
                "parent_key": _lineage_parent_key(candidate),
                "book_principle_id": candidate.principle_id,
                "book_scope": _scope_key(candidate),
                "geometry_family": _geometry_program_family(candidate),
                "error": error or "missing_result",
                "failure_code": failure_code,
                "budget_code": str(budget_failure.get("budget_code") or ""),
                "request_kind": str(
                    budget_failure.get("request_kind") or request_kind
                ),
                "quota": str(budget_failure.get("quota") or ""),
                "used": budget_failure.get("used"),
                "limit": budget_failure.get("limit"),
                "remaining": budget_failure.get("remaining"),
            })
            continue
        program = GeometryProgram.from_dict(
            candidate.source.metadata.get("geometry_program") or {}
        )
        scored_count += 1
        cache_hit_count += int(bool(result.get("cache_hit")))
        stage_policy = book_vlm_stage_policy(review_stage)
        candidate_morphology = _solid_morphology_metrics(candidate)
        candidate_design_concept = _design_concept_descriptor(candidate)
        candidate_capacity = (
            candidate.source.metadata.get("source_capacity_measurement") or {}
        )
        effective_capacity_floor = _book_stage_capacity_floor(candidate, review_stage)
        hard_pass, failures = _final_book_vlm_hard_pass(
            result,
            candidate_morphology=candidate_morphology,
            candidate_design_concept=candidate_design_concept,
            candidate_capacity=candidate_capacity,
            minimum_capacity_utilization=effective_capacity_floor,
            review_stage=review_stage,
        )
        failure_counts.update(failures)
        action_counts.update(str(value) for value in result.get("critic_actions") or ())
        if _llm_authored_candidate(candidate):
            llm_failure_counts.update(failures)
            llm_action_counts.update(str(value) for value in result.get("critic_actions") or ())
            llm_hard_pass_count += int(hard_pass)
        scores = result.get("concept_scores") if isinstance(result.get("concept_scores"), dict) else {}
        visual_score = sum(float(scores.get(key) or 0.0) for key in (
            "gesture_clarity", "hierarchy", "non_stair_silhouette", "void_publicness",
            "repair_integrity", "precedent_resonance", "program_appropriateness", "section_program_fit",
        )) / 8.0
        audit = {
            "schema_version": "arr.maas.final_book_vlm_audit.v1",
            "status": "pass" if hard_pass else "fail",
            "hard_pass": hard_pass,
            "failures": failures,
            "model": str(result.get("model") or ""),
            "prompt_contract_version": str(
                result.get("prompt_contract_version")
                or review_contract["prompt_contract_version"]
            ),
            "review_contract_fingerprint": str(review_contract["fingerprint"]),
            "response_id": str(result.get("response_id") or ""),
            "cache_hit": bool(result.get("cache_hit")),
            "concept_scores": dict(scores),
            "provider_program_fit_hard_pass": bool(result.get(
                "provider_program_fit_hard_pass",
                result.get("program_fit_hard_pass"),
            )),
            "normalized_program_fit_hard_pass": bool(
                result.get("program_fit_hard_pass")
            ),
            "critic_actions": list(result.get("critic_actions") or ()),
            "provider_critic_actions": list(
                result.get("provider_critic_actions")
                if isinstance(result.get("provider_critic_actions"), list)
                else result.get("critic_actions") or ()
            ),
            "locally_derived_critic_actions": list(
                result.get("locally_derived_critic_actions") or ()
            ),
            "geometry_edits": list(result.get("geometry_edits") or ()),
            "rationale": str(result.get("rationale") or "")[:1000],
            "capacity_review_context": build_capacity_review_context(
                candidate.source.metadata
            ),
            "reference_ids": [str(item.get("source_id") or "") for item in references[:5]],
            "reference_records": [
                {
                    "source_id": str(item.get("source_id") or ""),
                    "source": str(item.get("source") or ""),
                    "title": str(item.get("title") or ""),
                    "selection_role": str(item.get("selection_role") or ""),
                    "program_id": str(item.get("program_id") or ""),
                    "program_match_tier": str(item.get("program_match_tier") or ""),
                    "matched_tags": list(item.get("matched_tags") or ()),
                    "source_url": str(item.get("source_url") or item.get("page_url") or ""),
                    "local_path": str(item.get("local_path") or ""),
                    "image_url": str(item.get("image_url") or ""),
                    "massing_image_audit": deepcopy(item.get("massing_image_audit") or {}),
                }
                for item in references[:5]
                if isinstance(item, dict)
            ],
            "reviewed_exact_post_book_geometry": True,
            "review_stage": review_stage,
            "gate_policy": stage_policy.to_evidence(),
            "minimum_feasible_capacity_utilization": stage_policy.minimum_feasible_capacity_utilization,
            "effective_minimum_feasible_capacity_utilization": effective_capacity_floor,
            "capacity_normalization": stage_policy.capacity_normalization,
            "candidate_capacity": deepcopy(candidate_capacity),
            "candidate_morphology": deepcopy(candidate_morphology),
            "candidate_design_concept": deepcopy(candidate_design_concept),
            "legal_or_parking_score": False,
            "reference_massing_gate": deepcopy(result.get("reference_massing_gate") or {}),
            "vlm_image_inputs": deepcopy(result.get("vlm_image_inputs") or {}),
        }
        audit_records.append({
            "source_sequence": candidate.sequence.name,
            "parent_key": _lineage_parent_key(candidate),
            "base_review_fingerprint": _base_review_fingerprint(candidate),
            "book_principle_id": candidate.principle_id,
            "book_scope": _scope_key(candidate),
            "geometry_family": _geometry_program_family(candidate),
            "form_bank_lane": _form_bank_lane(candidate),
            "llm_authored_lane": _llm_authored_candidate(candidate),
            "hard_pass": hard_pass,
            "failures": failures,
            "response_id": audit["response_id"],
            "concept_scores": dict(scores),
            "critic_actions": list(audit["critic_actions"]),
            "provider_program_fit_hard_pass": audit[
                "provider_program_fit_hard_pass"
            ],
            "normalized_program_fit_hard_pass": audit[
                "normalized_program_fit_hard_pass"
            ],
            "provider_critic_actions": list(audit["provider_critic_actions"]),
            "locally_derived_critic_actions": list(
                audit["locally_derived_critic_actions"]
            ),
            "geometry_edits": list(audit["geometry_edits"]),
            "reference_ids": list(audit["reference_ids"]),
            "reference_massing_gate": deepcopy(audit["reference_massing_gate"]),
            "candidate_capacity": deepcopy(candidate_capacity),
            "candidate_morphology": deepcopy(candidate_morphology),
            "candidate_design_concept": deepcopy(candidate_design_concept),
            "program_hash": program.program_hash(),
            "geometry_hash": _archived_exact_surface_geometry_hash(candidate),
            "geometry_program": program.to_dict(),
            "review_image_path": str(result.get("review_image_path") or ""),
            "vlm_audit": deepcopy(audit),
            "chronological_archive_replayable": bool(result.get("review_image_path")),
        })
        if outcome_graph is not None:
            if review_stage == "book_base_operative":
                outcome_graph.observe_base_book_vlm_audit(
                    program_slug=program_slug or building_type,
                    candidate=candidate,
                    base_review_fingerprint=_base_review_fingerprint(candidate),
                    review_contract_fingerprint=str(review_contract["fingerprint"]),
                    audit=audit,
                )
            else:
                outcome_graph.observe_final_book_vlm_audit(
                    program_slug=program_slug or building_type,
                    candidate=candidate,
                    audit=audit,
                )
        source_metadata = dict(candidate.source.metadata)
        source_metadata["final_book_vlm_audit"] = audit
        feature = deepcopy(candidate.feature)
        feature.setdefault("properties", {})["final_book_vlm_audit"] = deepcopy(audit)
        revised = replace(
            candidate,
            source=replace(candidate.source, metadata=source_metadata),
            feature=feature,
            score=candidate.score * 0.72 + visual_score * 0.28,
        )
        if hard_pass:
            accepted.append(revised)
    evidence = {
        "schema_version": "arr.maas.final_book_vlm_portfolio_gate.v1",
        "required": True,
        "input_count": input_count,
        "exact_geometry_program_input_count": len(pool),
        "invalid_geometry_program_rejected_count": invalid_geometry_program_count,
        "prior_final_vlm_failure_filter": prior_failure_filter,
        "shortlist_count": len(shortlist),
        "review_budget": maximum,
        "request_kind": request_kind,
        "paid_opportunity_limit": paid_opportunity_limit,
        "scored_count": scored_count,
        "cache_hit_count": cache_hit_count,
        "initial_call_failure_count": len(initial_call_failures),
        "recovered_call_failure_count": max(
            0,
            len(initial_call_failures) - len(call_failure_records),
        ),
        "unrecovered_call_failure_count": len(call_failure_records),
        "call_failure_records": call_failure_records,
        "recovery_workers": recovery_workers,
        "hard_pass_count": len(accepted),
        "failure_counts": dict(sorted(failure_counts.items())),
        "critic_action_counts": dict(sorted(action_counts.items())),
        "llm_authored_input_count": sum(_llm_authored_candidate(candidate) for candidate in pool),
        "llm_authored_shortlist_count": sum(_llm_authored_candidate(candidate) for candidate in shortlist),
        "llm_authored_hard_pass_count": llm_hard_pass_count,
        "llm_authored_failure_counts": dict(sorted(llm_failure_counts.items())),
        "llm_authored_critic_action_counts": dict(sorted(llm_action_counts.items())),
        "llm_authored_review_quota_only_not_selection_preference": True,
        "executable_core_input_count": sum(
            _form_bank_lane(candidate) == "executable_core_language"
            for candidate in pool
        ),
        "executable_core_shortlist_count": sum(
            _form_bank_lane(candidate) == "executable_core_language"
            for candidate in shortlist
        ),
        "executable_core_hard_pass_count": sum(
            _form_bank_lane(candidate) == "executable_core_language"
            for candidate in accepted
        ),
        "geometry_family_input_counts": dict(sorted(Counter(
            _geometry_program_family(candidate) or "unclassified"
            for candidate in pool
        ).items())),
        "geometry_family_shortlist_counts": dict(sorted(Counter(
            _geometry_program_family(candidate) or "unclassified"
            for candidate in shortlist
        ).items())),
        "geometry_family_hard_pass_counts": dict(sorted(Counter(
            _geometry_program_family(candidate) or "unclassified"
            for candidate in accepted
        ).items())),
        "executable_core_review_quota_only_not_selection_preference": True,
        "post_book_geometry_reviewed": True,
        "review_stage": review_stage,
        "synthetic_fallback_used": False,
        "selection_input_is_reviewed_hard_pass_only": True,
        "audit_records": audit_records,
        "no_call_reason": (
            ""
            if shortlist
            else (
                "routing_pool_empty"
                if input_count == 0
                else (
                    "no_exact_geometry_program_for_final_review"
                    if invalid_geometry_program_count == input_count
                    else (
                        "paid_vlm_review_budget_unavailable"
                        if maximum <= 0
                        else "final_vlm_shortlist_empty"
                    )
                )
            )
        ),
    }
    return accepted, evidence


def audit_book_base_stage_with_vlm(
    pool: list[_Candidate],
    *,
    building_type: str,
    output_dir: Path,
    visual_directive: dict[str, Any],
    outcome_graph: GeometryOutcomeGraph | None = None,
    program_slug: str = "",
    scorer: Any | None = None,
    reference_provider: Any | None = None,
    excluded_parent_keys: set[str] | None = None,
    excluded_parent_fingerprints: set[str] | None = None,
    target_count: int | None = None,
) -> tuple[list[_Candidate], dict[str, Any]]:
    """Approve descendants only after their exact BOOK base parent is seen.

    The former pre-BOOK critic reviewed the recursive author body before any
    BOOK language existed.  This gate instead renders the one-operative base
    stage at its capacity-conditioned site scale, records that image audit,
    and releases only combinations/aggregations sharing the approved parent
    key.  Every released descendant is still reviewed again at the final
    post-BOOK stage.
    """
    excluded_parent_keys = {
        str(value) for value in (excluded_parent_keys or set()) if str(value)
    }
    excluded_parent_fingerprints = {
        str(value) for value in (excluded_parent_fingerprints or set()) if str(value)
    }
    all_bases = [
        candidate for candidate in pool
        if str((candidate.source.metadata.get("book_generation_lineage") or {}).get("stage") or "")
        == "base"
    ]
    base_by_fingerprint = {
        _base_review_fingerprint(candidate): candidate
        for candidate in all_bases
    }
    base_fingerprints_by_parent: dict[str, set[str]] = {}
    base_fingerprints_by_geometry: dict[str, set[str]] = {}
    base_fingerprints_by_program: dict[str, set[str]] = {}
    for fingerprint, candidate in base_by_fingerprint.items():
        parent_key = _lineage_parent_key(candidate)
        if parent_key:
            base_fingerprints_by_parent.setdefault(parent_key, set()).add(fingerprint)
        metadata = candidate.source.metadata
        compilation = metadata.get("geometry_program_compilation") or {}
        geometry_hash = _archived_exact_surface_geometry_hash(candidate)
        if geometry_hash:
            base_fingerprints_by_geometry.setdefault(geometry_hash, set()).add(fingerprint)
        program = metadata.get("geometry_program") or {}
        program_metadata = program.get("metadata") or {}
        program_hash = str(
            compilation.get("program_hash")
            or program.get("program_hash")
            or program_metadata.get("pre_book_program_hash")
            or ""
        )
        if program_hash:
            base_fingerprints_by_program.setdefault(program_hash, set()).add(fingerprint)

    def exact_parent_fingerprint(candidate: _Candidate) -> str:
        metadata = candidate.source.metadata
        lineage = metadata.get("book_generation_lineage") or {}
        prior_audit = metadata.get("base_book_vlm_parent_audit") or {}
        fingerprint = str(
            lineage.get("parent_base_review_fingerprint")
            or lineage.get("base_review_fingerprint")
            or prior_audit.get("base_review_fingerprint")
            or ""
        )
        exact_matches: list[str] = []
        if fingerprint:
            if fingerprint not in base_by_fingerprint:
                return ""
            exact_matches.append(fingerprint)
        geometry_hash = str(lineage.get("parent_geometry_hash") or "")
        if geometry_hash:
            geometry_matches = base_fingerprints_by_geometry.get(geometry_hash, set())
            if len(geometry_matches) != 1:
                return ""
            exact_matches.append(next(iter(geometry_matches)))
        program_hash = str(lineage.get("parent_program_hash") or "")
        if program_hash:
            program_matches = base_fingerprints_by_program.get(program_hash, set())
            if len(program_matches) != 1:
                return ""
            exact_matches.append(next(iter(program_matches)))
        return exact_matches[0] if exact_matches and len(set(exact_matches)) == 1 else ""

    # Exclusions prevent duplicate fresh VLM work. Do not erase descendants
    # before exact persisted base audits can release them.
    eligible_pool = list(pool)
    bases = list(all_bases)
    if not bases:
        return [], {
            "schema_version": "arr.maas.book_base_stage_vlm_gate.v2",
            "required": True,
            "status": "no_viable_base_stage_candidates",
            "input_count": len(pool),
            "eligible_input_count": len(eligible_pool),
            "excluded_parent_count": len(excluded_parent_keys),
            "excluded_parent_fingerprint_count": len(excluded_parent_fingerprints),
            "base_input_count": 0,
            "approved_base_count": 0,
            "released_descendant_count": 0,
            "hard_pass": False,
        }

    review_contract = _book_vlm_review_contract("book_base_operative")
    persisted_audits = (
        outcome_graph.approved_base_book_vlm_audits(
            program_slug=program_slug or building_type,
            base_review_fingerprints=(
                _base_review_fingerprint(candidate) for candidate in bases
            ),
            review_contract_fingerprint=str(review_contract["fingerprint"]),
        )
        if outcome_graph is not None
        else {}
    )
    reused_by_fingerprint: dict[str, _Candidate] = {}
    reused_audits: dict[str, dict[str, Any]] = {}
    for candidate in bases:
        fingerprint = _base_review_fingerprint(candidate)
        audit = persisted_audits.get(fingerprint)
        if not isinstance(audit, dict):
            continue
        reused_by_fingerprint[fingerprint] = _attach_base_book_vlm_audit(
            candidate,
            audit,
            reused_from_outcome_graph=True,
        )
        reused_audits[fingerprint] = deepcopy(audit)

    fresh_base_fingerprints = {
        _base_review_fingerprint(candidate)
        for candidate in bases
        if _base_review_fingerprint(candidate) not in reused_by_fingerprint
        and _lineage_parent_key(candidate) not in excluded_parent_keys
        and _base_review_fingerprint(candidate) not in excluded_parent_fingerprints
    }
    fresh_pool = [
        candidate for candidate in eligible_pool
        if (
            str((candidate.source.metadata.get("book_generation_lineage") or {}).get("stage") or "")
            == "base"
            and _base_review_fingerprint(candidate) in fresh_base_fingerprints
        )
        or (
            str((candidate.source.metadata.get("book_generation_lineage") or {}).get("stage") or "")
            != "base"
            and exact_parent_fingerprint(candidate) in fresh_base_fingerprints
        )
    ]
    fresh_bases = [
        candidate for candidate in bases
        if _base_review_fingerprint(candidate) in fresh_base_fingerprints
    ]
    review_budget = _book_vlm_review_budget("book_base_operative")
    if fresh_bases:
        parent_shortlist, parent_shortlist_evidence = _book_base_parent_shortlist(
            fresh_pool,
            target=min(review_budget, len(fresh_bases)),
            visual_directive=visual_directive,
        )
        configured_target = int(
            target_count
            or (paid_provider_budget_snapshot().get("run_metadata") or {}).get(
                "target_count"
            )
            or review_budget
        )
        approved, raw_evidence = _audit_final_book_geometry_with_vlm(
            fresh_bases,
            building_type=building_type,
            output_dir=output_dir,
            visual_directive=visual_directive,
            outcome_graph=outcome_graph,
            program_slug=program_slug,
            scorer=scorer,
            reference_provider=reference_provider,
            review_stage="book_base_operative",
            shortlist_override=parent_shortlist,
            request_kind="base_candidate_vlm",
            paid_opportunity_limit=configured_target,
        )
    else:
        parent_shortlist = []
        parent_shortlist_evidence = {
            "status": "all_exact_bases_resolved_from_outcome_graph",
            "review_target": 0,
        }
        approved = []
        raw_evidence = {
            "schema_version": "arr.maas.final_book_vlm_portfolio_gate.v1",
            "required": True,
            "status": "all_exact_bases_resolved_from_outcome_graph",
            "input_count": 0,
            "shortlist_count": 0,
            "scored_count": 0,
            "hard_pass_count": 0,
            "audit_records": [],
            "review_stage": "book_base_operative",
        }

    approved_by_fingerprint: dict[str, _Candidate] = dict(reused_by_fingerprint)
    base_audits: dict[str, dict[str, Any]] = dict(reused_audits)
    for candidate in approved:
        audit = dict(candidate.source.metadata.get("final_book_vlm_audit") or {})
        fingerprint = _base_review_fingerprint(candidate)
        approved_by_fingerprint[fingerprint] = _attach_base_book_vlm_audit(
            candidate,
            audit,
            reused_from_outcome_graph=False,
        )
        base_audits[fingerprint] = audit

    # Base VLM is a developmental critic. A reviewed failure must retain its
    # typed critique so the exact post-BOOK repair loop can improve it; only an
    # unreviewed parent is withheld. Final exact-render VLM remains the visual
    # acceptance authority.
    reviewed_by_fingerprint: dict[str, _Candidate] = dict(approved_by_fingerprint)
    for record in raw_evidence.get("audit_records") or ():
        vlm_audit = record.get("vlm_audit") or {}
        if not (
            str(record.get("response_id") or "")
            and isinstance(vlm_audit, dict)
            and vlm_audit.get("reviewed_exact_post_book_geometry") is True
            and str(vlm_audit.get("review_stage") or "")
            == "book_base_operative"
        ):
            continue
        fingerprint = str(record.get("base_review_fingerprint") or "")
        if fingerprint not in base_by_fingerprint:
            parent_matches = base_fingerprints_by_parent.get(
                str(record.get("parent_key") or ""),
                set(),
            )
            fingerprint = next(iter(parent_matches)) if len(parent_matches) == 1 else ""
        if not fingerprint or fingerprint in reviewed_by_fingerprint:
            continue
        candidate = base_by_fingerprint.get(fingerprint)
        if candidate is None:
            continue
        audit = {
            **dict(record),
            "review_stage": "book_base_operative",
            "status": "pass" if bool(record.get("hard_pass")) else "critique",
        }
        reviewed_by_fingerprint[fingerprint] = _attach_base_book_vlm_audit(
            candidate,
            audit,
            reused_from_outcome_graph=False,
        )
        base_audits[fingerprint] = audit

    released: list[_Candidate] = list(reviewed_by_fingerprint.values())
    descendant_count = 0
    for candidate in eligible_pool:
        lineage = candidate.source.metadata.get("book_generation_lineage") or {}
        if str(lineage.get("stage") or "") == "base":
            continue
        parent_key = str(lineage.get("parent_key") or "")
        fingerprint = exact_parent_fingerprint(candidate)
        if fingerprint not in reviewed_by_fingerprint:
            continue
        parent_audit = base_audits[fingerprint]
        metadata = dict(candidate.source.metadata)
        metadata["base_book_vlm_parent_audit"] = {
            "parent_key": parent_key,
            "hard_pass": bool(parent_audit.get("hard_pass")),
            "response_id": str(parent_audit.get("response_id") or ""),
            "review_stage": "book_base_operative",
            "critic_actions": list(parent_audit.get("critic_actions") or ()),
            "geometry_edits": list(parent_audit.get("geometry_edits") or ()),
            "base_review_fingerprint": fingerprint,
            "review_contract_fingerprint": str(review_contract["fingerprint"]),
            "reused_from_outcome_graph": fingerprint in reused_by_fingerprint,
        }
        feature = deepcopy(candidate.feature)
        feature.setdefault("properties", {})["base_book_vlm_parent_audit"] = deepcopy(
            metadata["base_book_vlm_parent_audit"]
        )
        released.append(replace(
            candidate,
            source=replace(candidate.source, metadata=metadata),
            feature=feature,
        ))
        descendant_count += 1

    reviewed_parent_keys = sorted({
        _lineage_parent_key(candidate)
        for candidate in reviewed_by_fingerprint.values()
        if _lineage_parent_key(candidate)
    })
    reviewed_parent_fingerprints = sorted(reviewed_by_fingerprint)
    return released, {
        "schema_version": "arr.maas.book_base_stage_vlm_gate.v2",
        "required": True,
        "status": "complete",
        "input_count": len(pool),
        "eligible_input_count": len(eligible_pool),
        "excluded_parent_count": len(excluded_parent_keys),
        "excluded_parent_fingerprint_count": len(excluded_parent_fingerprints),
        "base_input_count": len(bases),
        "fresh_base_input_count": len(fresh_bases),
        "persisted_approved_base_count": len(reused_by_fingerprint),
        "newly_approved_base_count": len(approved_by_fingerprint) - len(reused_by_fingerprint),
        "approved_base_count": len(approved_by_fingerprint),
        "developmental_critique_parent_count": max(
            0,
            len(reviewed_by_fingerprint) - len(approved_by_fingerprint),
        ),
        "reviewed_base_count": len(reviewed_by_fingerprint),
        "base_stage_selection_authority": False,
        "released_descendant_count": descendant_count,
        "rejected_descendant_count": max(
            0,
            len(eligible_pool) - len(bases) - descendant_count,
        ),
        "hard_pass": bool(approved_by_fingerprint),
        "development_release_hard_pass": bool(reviewed_by_fingerprint),
        "capacity_excluded_from_development_release_hard_pass": True,
        "base_audit": raw_evidence,
        "parent_shortlist": parent_shortlist_evidence,
        "reviewed_parent_keys": reviewed_parent_keys,
        "reviewed_parent_fingerprints": reviewed_parent_fingerprints,
        "review_contract": review_contract,
        "persistent_approval_requires_exact_geometry_program_site_and_contract": True,
        "descendants_require_exact_approved_parent_key": True,
        "final_post_book_vlm_still_required": True,
    }


def _final_authority_repair_requires_canonical_reprojection(
    source: SourceMass,
) -> bool:
    """Return whether a VLM edit must re-enter the sole final-authority path."""

    return str(source.metadata.get("geometry_authority") or "") in {
        "authored_projected_surface_payload",
        "authored_compiled_surface_payload",
    }


def _repaired_program_release_contract(
    program: dict[str, Any],
    program_form: dict[str, Any],
) -> dict[str, Any]:
    """Separate repaired-surface authority from design-review evidence."""

    explicit_components = all(
        key in program
        for key in ("volume_hard_pass", "floor_hard_pass")
    )
    volume_hard_pass = bool(
        program.get("volume_hard_pass")
        if explicit_components
        else program.get("hard_pass")
    )
    floor_hard_pass = bool(
        program.get("floor_hard_pass")
        if explicit_components
        else program.get("hard_pass")
    )
    coherence_hard_pass = bool(program.get("coherence_hard_pass", True))
    spatial_hard_pass = bool(program.get("spatial_hard_pass", True))
    program_form_hard_pass = program_form.get("hard_pass") is True
    component_reasons = program.get("component_failure_reasons")
    component_reasons = (
        deepcopy(component_reasons)
        if isinstance(component_reasons, dict)
        else {}
    )
    design_failure_reasons = [
        *list(component_reasons.get("coherence") or ()),
        *list(component_reasons.get("spatial") or ()),
    ]
    if not coherence_hard_pass and not component_reasons.get("coherence"):
        design_failure_reasons.append("coherence_hard_pass_false")
    if not spatial_hard_pass and not component_reasons.get("spatial"):
        design_failure_reasons.append("spatial_hard_pass_false")
    hard_failure_reasons = []
    if not volume_hard_pass:
        hard_failure_reasons.extend(
            component_reasons.get("volume") or ("volume_hard_pass_false",)
        )
    if not floor_hard_pass:
        hard_failure_reasons.extend(
            component_reasons.get("floor") or ("floor_hard_pass_false",)
        )
    if not program_form_hard_pass:
        hard_failure_reasons.extend(
            program_form.get("failure_reasons")
            or program_form.get("failures")
            or ("program_form_hard_pass_false",)
        )
    return {
        "schema_version": "arr.maas.repaired_program_release.v1",
        "hard_pass": bool(
            volume_hard_pass
            and floor_hard_pass
            and program_form_hard_pass
        ),
        "volume_hard_pass": volume_hard_pass,
        "floor_hard_pass": floor_hard_pass,
        "program_form_hard_pass": program_form_hard_pass,
        "coherence_hard_pass": coherence_hard_pass,
        "spatial_hard_pass": spatial_hard_pass,
        "hard_failure_reasons": list(dict.fromkeys(hard_failure_reasons)),
        "design_review_required": bool(design_failure_reasons),
        "design_failure_reasons": list(dict.fromkeys(design_failure_reasons)),
        "coherence_and_spatial_are_final_vlm_diagnostics": True,
        "statutory_structural_clean_gates_precede_this_contract": True,
    }


def _repair_exact_post_book_candidates_from_vlm(
    audited_pool: list[_Candidate],
    audit_gate: dict[str, Any],
    *,
    generation_site: Polygon,
    building_type: str,
    height: float,
    floors: int,
    generation_context: LegalGenerationContext | None,
    program_dimensional_context: dict[str, Any] | None,
    site_boundary_source: str,
    site_access_context: dict[str, Any] | None,
    site_access_geometry: dict[str, Any] | None,
    base_capacity_contract: dict[str, Any] | None = None,
    capacity_site: Polygon | None = None,
    expected_finalization_context: dict[str, Any] | None = None,
    repair_budget: int = 32,
    typed_edit_completion_provider: Any = None,
) -> tuple[list[_Candidate], dict[str, Any]]:
    """Apply exact final-image VLM edits to that candidate's final AST.

    Outcome memory and a fresh LLM author remain useful for exploration, but
    they are an indirect repair path.  This function closes the shorter causal
    loop: final render -> typed edit -> same final AST -> compiler -> clean and
    program gates.  BOOK nodes already exist in the audited program, so they
    are not projected a second time.
    """

    local_audit_gate = deepcopy(audit_gate)
    completion_evidence = complete_empty_final_vlm_repair_records(
        audited_pool,
        local_audit_gate,
        provider=typed_edit_completion_provider,
    )
    records = {
        str(record.get("source_sequence") or ""): record
        for record in local_audit_gate.get("audit_records") or ()
        if isinstance(record, dict)
        and not record.get("hard_pass")
        and isinstance(record.get("geometry_edits"), list)
        and record.get("geometry_edits")
    }
    eligible = [
        candidate for candidate in audited_pool
        if candidate.sequence.name in records
        and isinstance(candidate.source.metadata.get("geometry_program"), dict)
    ]
    candidates = _exact_post_book_repair_shortlist(
        eligible,
        records,
        repair_budget=max(0, int(repair_budget)),
    )
    repaired: list[_Candidate] = []
    failures: Counter[str] = Counter()
    mutation_issue_counts: Counter[str] = Counter()
    compilation_issue_counts: Counter[str] = Counter()
    compilation_issue_detail_counts: Counter[str] = Counter()
    authored_failure_counts: Counter[str] = Counter()
    failure_records: list[dict[str, Any]] = []
    stage_outcomes: list[dict[str, Any]] = []
    counts = {
        "schema_version": "arr.maas.exact_post_book_typed_repair.v1",
        "requested_count": len(candidates),
        "requested_llm_authored_count": sum(_llm_authored_candidate(candidate) for candidate in candidates),
        "mutation_revised_count": 0,
        "geometry_changed_count": 0,
        "source_materialized_count": 0,
        "clean_mass_pass_count": 0,
        "program_hard_pass_count": 0,
        "repaired_candidate_count": 0,
        "repair_budget": max(0, int(repair_budget)),
        "same_final_ast_edited": True,
        "book_reprojection_applied": False,
        "synthetic_fallback_used": False,
        "compiler_safe_recovery_count": 0,
        "compiler_safe_rejected_group_count": 0,
        "floorwise_legal_reprojection_count": 0,
        **completion_evidence,
    }
    site_access_context = dict(site_access_context or {})
    repair_outcomes: list[dict[str, Any]] = []

    def record_repair_failure(
        *,
        candidate: _Candidate,
        critic_record: dict[str, Any],
        stage: str,
        reason: str,
        evidence: dict[str, Any],
        legacy_counter: str,
    ) -> None:
        outcome = StageOutcome.failed(
            stage,
            reason,
            evidence={
                "source_sequence": candidate.sequence.name,
                "geometry_family": _geometry_program_family(candidate),
                "llm_authored_lane": _llm_authored_candidate(candidate),
                "critic_response_id": str(
                    critic_record.get("response_id") or ""
                ),
                **deepcopy(evidence),
            },
        )
        record_stage_outcome(
            outcome,
            records=stage_outcomes,
            counter_updates=((failures, legacy_counter),),
            terminal_recorder=lambda terminal: failure_records.append(
                terminal.to_record()
            ),
        )
        repair_outcomes.append(outcome.to_record())

    for candidate in candidates:
        record = records[candidate.sequence.name]
        requires_canonical_reprojection = (
            _final_authority_repair_requires_canonical_reprojection(
            candidate.source
            )
        )
        try:
            parent_program = GeometryProgram.from_dict(candidate.source.metadata["geometry_program"])
        except (TypeError, ValueError):
            failures["invalid_parent_geometry_program"] += 1
            continue
        parent_compilation = compile_geometry_program(parent_program)
        try:
            certified_floor_binding = _certified_repair_floor_context_binding(
                candidate.source.metadata,
                expected_context=expected_finalization_context,
            )
        except _RepairParentFinalizationContextMismatch as exc:
            provenance = (
                candidate.source.metadata.get("replenishment_provenance")
                or {}
            )
            feature_provenance = (
                (candidate.feature.get("properties") or {}).get(
                    "replenishment_provenance"
                )
                if isinstance(candidate.feature, dict)
                else {}
            ) or {}
            carried = bool(
                provenance.get("carried")
                or feature_provenance.get("carried")
            )
            cycle_index = (
                provenance.get("cycle_index")
                if provenance.get("cycle_index") is not None
                else feature_provenance.get("cycle_index")
            )
            record_repair_failure(
                candidate=candidate,
                critic_record=record,
                stage="final_vlm_repair_parent_context",
                reason="repair_parent_finalization_context_mismatch",
                evidence={
                    "candidate_program_hash": str(
                        candidate.source.metadata.get("final_program_hash")
                        or parent_program.program_hash()
                    ),
                    "candidate_geometry_hash": str(
                        candidate.source.metadata.get("final_geometry_hash")
                        or parent_compilation.geometry_hash
                    ),
                    **deepcopy(exc.evidence),
                    "carried": carried,
                    "cycle_index": cycle_index,
                },
                legacy_counter=(
                    "repair_parent_finalization_context_mismatch"
                ),
            )
            continue
        safe_mutation = apply_geometry_edits_compiler_safe(
            parent_program,
            record["geometry_edits"],
        )
        mutation = safe_mutation.mutation
        if safe_mutation.recovery_mode == "atomic_group_recovery":
            counts["compiler_safe_recovery_count"] += 1
        counts["compiler_safe_rejected_group_count"] += len(safe_mutation.rejected_groups)
        if mutation.status != "revised" or mutation.program is None:
            failures[f"mutation_{mutation.status}"] += 1
            for issue in mutation.issues:
                mutation_issue_counts[str(issue.code or "unknown")] += 1
            if _llm_authored_candidate(candidate):
                authored_failure_counts[f"mutation_{mutation.status}"] += 1
            failure_records.append({
                "source_sequence": candidate.sequence.name,
                "geometry_family": _geometry_program_family(candidate),
                "llm_authored_lane": _llm_authored_candidate(candidate),
                "stage": "typed_mutation",
                "status": mutation.status,
                "issues": [issue.to_dict() for issue in mutation.issues],
                "compiler_safe_recovery_mode": safe_mutation.recovery_mode,
                "compiler_safe_rejected_groups": list(safe_mutation.rejected_groups),
            })
            continue
        counts["mutation_revised_count"] += 1
        repaired_program = replace(
            mutation.program,
            name=f"{mutation.program.name}__final_vlm_repair",
            metadata={
                **dict(mutation.program.metadata),
                "final_vlm_repair": {
                    "schema_version": "arr.maas.final_vlm_typed_repair_lineage.v1",
                    "parent_program_hash": parent_program.program_hash(),
                    "parent_geometry_hash": parent_compilation.geometry_hash,
                    "critic_response_id": str(record.get("response_id") or ""),
                    "edit_count": len(record.get("geometry_edits") or ()),
                    "source_sequence": candidate.sequence.name,
                    "typed_edit_completion": deepcopy(
                        record.get("typed_edit_completion") or {}
                    ),
                },
            },
        )
        # The safe mutation compiled the same nodes before lineage metadata and
        # name were added. Recompile the exact persisted AST so the evidence
        # always belongs to the artifact sent downstream.
        repaired_compilation = compile_geometry_program(repaired_program)
        if repaired_compilation.status != "compiled":
            failures["repaired_program_compile_failed"] += 1
            for issue in repaired_compilation.issues:
                compilation_issue_counts[str(issue.code or "unknown")] += 1
                compilation_issue_detail_counts[
                    f"{issue.code}:{issue.node_id}:{str(issue.message)[:160]}"
                ] += 1
            if _llm_authored_candidate(candidate):
                authored_failure_counts["repaired_program_compile_failed"] += 1
            failure_records.append({
                "source_sequence": candidate.sequence.name,
                "geometry_family": _geometry_program_family(candidate),
                "llm_authored_lane": _llm_authored_candidate(candidate),
                "stage": "repaired_program_compile",
                "status": repaired_compilation.status,
                "issues": [issue.to_dict() for issue in repaired_compilation.issues],
                "typed_ast": {
                    "name": repaired_program.name,
                    "root_id": repaired_program.root_id,
                    "nodes": [node.to_dict() for node in repaired_program.topological_nodes()],
                    "contains_parcel_coordinates": False,
                    "contains_mesh_payload": False,
                },
            })
            continue
        if repaired_compilation.geometry_hash == parent_compilation.geometry_hash:
            failures["typed_edit_did_not_change_geometry"] += 1
            continue
        counts["geometry_changed_count"] += 1

        legal_generation = candidate.source.metadata.get("legal_generation_context_evidence") or {}
        host_mode = str(legal_generation.get("generation_host_mode") or "horizontal_buildable_envelope")
        compile_site = generation_site
        if host_mode == "height_safe_sunlight_section" and generation_context is not None:
            height_safe = generation_site_at_height(generation_context, height * (2.0 / 3.0))
            if height_safe is not None:
                compile_site = height_safe
        base_source = compile_sequence_to_source_mass(compile_site, candidate.sequence)
        if base_source is None:
            failures["program_sequence_recompile_failed"] += 1
            continue
        unbound_repaired_program_hash = repaired_program.program_hash()
        unbound_repaired_geometry_hash = str(
            repaired_compilation.geometry_hash or ""
        )
        try:
            source_role_bound_program = _bind_book_program_source_role(
                repaired_program,
                base_source,
                program_id=building_type,
            )
        except (TypeError, ValueError) as exc:
            binding_evidence = getattr(exc, "evidence", None)
            record_repair_failure(
                candidate=candidate,
                critic_record=record,
                stage="final_vlm_repair_source_role_binding",
                reason="source_role_scaffold_binding_failed",
                evidence={
                    "repaired_program_hash": unbound_repaired_program_hash,
                    "repaired_geometry_hash": unbound_repaired_geometry_hash,
                    "failure_type": type(exc).__name__,
                    "failure_detail": str(exc),
                    "source_role_binding_failure": (
                        deepcopy(binding_evidence)
                        if isinstance(binding_evidence, dict)
                        else {}
                    ),
                },
                legacy_counter="repaired_source_role_binding_failed",
            )
            continue
        source_role_bound_compilation = compile_geometry_program(
            source_role_bound_program
        )
        if (
            source_role_bound_compilation.status != "compiled"
            or str(source_role_bound_compilation.geometry_hash or "")
            != unbound_repaired_geometry_hash
        ):
            record_repair_failure(
                candidate=candidate,
                critic_record=record,
                stage="final_vlm_repair_source_role_binding",
                reason=(
                    "source_role_binding_compile_failed"
                    if source_role_bound_compilation.status != "compiled"
                    else "source_role_binding_geometry_identity_mismatch"
                ),
                evidence={
                    "unbound_repaired_program_hash": (
                        unbound_repaired_program_hash
                    ),
                    "bound_repaired_program_hash": (
                        source_role_bound_program.program_hash()
                    ),
                    "expected_geometry_hash": unbound_repaired_geometry_hash,
                    "bound_geometry_hash": str(
                        source_role_bound_compilation.geometry_hash or ""
                    ),
                    "compilation_status": (
                        source_role_bound_compilation.status
                    ),
                },
                legacy_counter="repaired_source_role_binding_failed",
            )
            continue
        repaired_program = source_role_bound_program
        repaired_compilation = source_role_bound_compilation
        counts["source_role_scaffold_bound_count"] = (
            counts.get("source_role_scaffold_bound_count", 0) + 1
        )
        bridge = candidate.source.metadata.get("geometry_program_bridge_evidence") or {}
        parent_capacity_alternative = deepcopy(
            candidate.source.metadata.get("capacity_alternative_projection") or {}
        )
        alternative_capacity_contract = capacity_contract_for_alternative(
            base_capacity_contract,
            parent_capacity_alternative,
        )
        try:
            fit_strength = max(0.0, min(1.0, float(bridge.get("legal_fit_strength") or 0.0)))
        except (TypeError, ValueError):
            fit_strength = 0.0
        materialization_failures: list[dict[str, Any]] = []
        source = replace_source_dominant_with_geometry_program(
            base_source,
            repaired_program,
            containment_host=compile_site,
            upper_containment_host=(
                generation_site_at_height(generation_context, height)
                if generation_context is not None
                else None
            ),
            upper_fit_strength=fit_strength,
            minimum_host_plan_coverage=0.0,
            failure_sink=materialization_failures,
        )
        if source is None:
            typed_failure = (
                materialization_failures[-1]
                if materialization_failures
                else {
                    "reason": "source_materialization_returned_none_without_evidence",
                    "evidence": {},
                }
            )
            record_repair_failure(
                candidate=candidate,
                critic_record=record,
                stage="final_vlm_repair_materialization",
                reason=str(typed_failure.get("reason") or "repaired_source_materialization_failed"),
                evidence={
                    "parent_program_hash": parent_program.program_hash(),
                    "parent_geometry_hash": parent_compilation.geometry_hash,
                    "repaired_program_hash": repaired_program.program_hash(),
                    "repaired_geometry_hash": repaired_compilation.geometry_hash,
                    "materialization_failure": deepcopy(typed_failure),
                },
                legacy_counter="repaired_source_materialization_failed",
            )
            continue
        counts["source_materialized_count"] += 1
        program_context = {
            **program_reference_contract(building_type),
            "program_dimensional_context": dict(program_dimensional_context or {}),
            "base_capacity_contract": dict(base_capacity_contract or {}),
            "site_boundary_source": site_boundary_source,
            "site_access_context": site_access_context,
            "site_access_side_in_program_frame": _site_access_side_in_principal_frame(
                generation_site,
                site_access_geometry,
            ),
            "verified_semantic_carriers": deepcopy(
                (
                    source.metadata.get(
                        "program_semantic_carrier_evidence"
                    )
                    or {}
                ).get("carriers")
                or []
            ),
        }
        metadata = deepcopy(source.metadata)
        for stale_authority_key in (
            "geometry_authority",
            "authored_legal_projection_certificate",
            "floorwise_legal_projection",
            "legal_field_affine_placement",
            "final_surface_payload_hash",
            "final_proxy_volume_payload_hash",
            "final_semantic_projection_context",
            "program_semantic_carrier_evidence",
            "capacity_projection_measurement",
        ):
            metadata.pop(stale_authority_key, None)
        metadata.update(certified_floor_binding)
        metadata["program_dimensional_context"] = deepcopy(program_dimensional_context or {})
        metadata["program_context"] = program_context
        metadata["geometry_graph_notes"] = build_geometry_graph_notes(
            repaired_program,
            repaired_compilation,
        )
        metadata["geometry_graph_snapshot"] = build_geometry_graph_snapshot(
            repaired_program,
            repaired_compilation,
            program_context=program_context,
        )
        metadata["legal_generation_context_evidence"] = deepcopy(legal_generation)
        metadata["base_capacity_contract"] = deepcopy(base_capacity_contract or {})
        metadata["capacity_alternative_projection"] = parent_capacity_alternative
        metadata["final_vlm_repair_parent_audit"] = deepcopy(record)
        repaired_bridge = deepcopy(metadata.get("geometry_program_bridge_evidence") or {})
        for stale_bridge_key in (
            "geometry_authority",
            "authored_legal_projection_certificate",
            "post_book_authored_program_hash",
            "post_book_authored_geometry_hash",
            "final_projected_surface_hash",
            "final_projected_surface_payload_hash",
            "surface_payload_hash",
            "proxy_volume_payload_hash",
        ):
            repaired_bridge.pop(stale_bridge_key, None)
        repaired_bridge.update({
            "source_seed": str((bridge or {}).get("source_seed") or ""),
            "legal_fit_strength": round(fit_strength, 4),
            "repair_stage": "exact_post_book_vlm_typed_edit",
            "parent_geometry_hash": parent_compilation.geometry_hash,
            "program_hash": repaired_program.program_hash(),
            "geometry_hash": repaired_compilation.geometry_hash,
        })
        metadata["geometry_program_bridge_evidence"] = repaired_bridge
        metadata["geometry_program"] = repaired_program.to_dict()
        metadata["authored_geometry_program"] = repaired_program.to_dict()
        metadata["final_program_hash"] = repaired_program.program_hash()
        metadata["final_geometry_hash"] = repaired_compilation.geometry_hash
        source = replace(source, metadata=metadata)
        authored_repaired_source = source
        if generation_context is None:
            failures["repaired_authored_visual_legal_sections_missing"] += 1
            continue
        legal_sections = tuple(
            generation_site_at_height(
                generation_context,
                float(height) * floor_number / max(1, int(floors)),
            )
            for floor_number in range(1, max(1, int(floors)) + 1)
        )
        if any(section is None for section in legal_sections):
            failures["repaired_authored_visual_legal_sections_missing"] += 1
            continue
        parent_floorwise_stack = candidate.source.metadata.get(
            "floorwise_legal_matrix_stack"
        )
        parent_floorwise_stack = (
            parent_floorwise_stack
            if isinstance(parent_floorwise_stack, dict)
            else {}
        )
        if requires_canonical_reprojection:
            try:
                target_plan_coverage = float(
                    parent_floorwise_stack.get("target_plan_coverage")
                    or parent_capacity_alternative.get(
                        "target_base_plan_coverage"
                    )
                    or recursive_plan_coverage_floor(
                        building_type,
                        alternative_capacity_contract,
                        host_area_m2=float(compile_site.area),
                    )
                )
            except (TypeError, ValueError):
                failures["repaired_floorwise_target_coverage_invalid"] += 1
                continue
            terminal_failure_sink: list[dict[str, Any]] = []
            projected_source = materialize_floorwise_legal_source(
                source,
                legal_sections=legal_sections,
                target_plan_coverage=target_plan_coverage,
                floor_capacity_plan_hash=str(
                    parent_floorwise_stack.get("floor_capacity_plan_hash")
                    or (base_capacity_contract or {}).get(
                        "floor_capacity_plan_hash"
                    )
                    or ""
                ),
                target_floor_areas_m2=tuple(
                    float(value)
                    for value in (
                        parent_floorwise_stack.get("target_floor_areas_m2")
                        or (base_capacity_contract or {}).get(
                            "target_floor_areas_m2"
                        )
                        or ()
                    )
                ),
                terminal_failure_sink=terminal_failure_sink,
            )
            if projected_source is None:
                terminal_reasons = [
                    str(
                        (item.get("evidence") or {}).get("repair_reason")
                        or item.get("stage")
                        or ""
                    )
                    for item in terminal_failure_sink
                    if isinstance(item, dict)
                ]
                failures.update(
                    terminal_reasons
                    or ["repaired_floorwise_legal_reprojection_failed"]
                )
                failure_records.append({
                    "source_sequence": candidate.sequence.name,
                    "geometry_family": _geometry_program_family(candidate),
                    "llm_authored_lane": _llm_authored_candidate(candidate),
                    "stage": "final_authority_repair_reprojection",
                    "status": "canonical_reprojection_failed",
                    "issues": deepcopy(terminal_failure_sink),
                })
                continue
            projected_metadata = deepcopy(projected_source.metadata)
            projected_bridge = deepcopy(
                projected_metadata.get("geometry_program_bridge_evidence")
                or repaired_bridge
            )
            projected_bridge.update({
                "program_hash": repaired_program.program_hash(),
                "geometry_hash": repaired_compilation.geometry_hash,
                "repair_stage": "exact_post_book_vlm_typed_edit",
                "parent_geometry_hash": parent_compilation.geometry_hash,
            })
            projected_metadata.update({
                "geometry_program": repaired_program.to_dict(),
                "authored_geometry_program": repaired_program.to_dict(),
                "final_program_hash": repaired_program.program_hash(),
                "geometry_program_bridge_evidence": projected_bridge,
                "final_vlm_repair_parent_audit": deepcopy(record),
            })
            source = replace(
                projected_source,
                metadata=projected_metadata,
            )
            counts["floorwise_legal_reprojection_count"] += 1
            floorwise_sibling_evidence = {
                "schema_version": (
                    "arr.maas.floorwise_legal_sibling_evidence.v1"
                ),
                "status": "promoted_to_visual_authority",
                "visible_authored_geometry_preserved": True,
                "authority": "final_visual_authority",
                "failure_reasons": [],
                "floorwise_legal_matrix_stack": deepcopy(
                    source.metadata.get("floorwise_legal_matrix_stack") or {}
                ),
            }
        else:
            authored_visual = certify_authored_visual_mesh(
                source,
                legal_sections,
            )
        if (
            not requires_canonical_reprojection
            and not authored_visual.certificate.hard_pass
        ):
            failures.update(
                authored_visual.certificate.failure_reasons
                or ("repaired_authored_visual_certification_failed",)
            )
            continue
        if not requires_canonical_reprojection:
            metadata = deepcopy(source.metadata)
            metadata["floorwise_visual_projection"] = (
                authored_visual.certificate.to_dict()
            )
            source = replace(source, metadata=metadata)
            floorwise_sibling_evidence = {
                "schema_version": "arr.maas.floorwise_legal_sibling_evidence.v1",
                "status": "not_requested",
                "visible_authored_geometry_preserved": True,
                "authority": "diagnostic_only",
                "failure_reasons": [],
            }
        if legal_sections and not requires_canonical_reprojection:
            try:
                target_plan_coverage = float(
                    parent_floorwise_stack.get("target_plan_coverage")
                    or parent_capacity_alternative.get("target_base_plan_coverage")
                    or recursive_plan_coverage_floor(
                        building_type,
                        alternative_capacity_contract,
                        host_area_m2=float(compile_site.area),
                    )
                )
            except (TypeError, ValueError):
                target_plan_coverage = 0.0
                floorwise_sibling_evidence.update({
                    "status": "unavailable",
                    "failure_reasons": [
                        "repaired_floorwise_target_coverage_invalid"
                    ],
                })
            if not floorwise_sibling_evidence["failure_reasons"]:
                terminal_failure_sink: list[dict[str, Any]] = []
                floorwise_source = materialize_floorwise_legal_source(
                    source,
                    legal_sections=legal_sections,
                    target_plan_coverage=target_plan_coverage,
                    floor_capacity_plan_hash=str(
                        parent_floorwise_stack.get("floor_capacity_plan_hash")
                        or (base_capacity_contract or {}).get(
                            "floor_capacity_plan_hash"
                        )
                        or ""
                    ),
                    target_floor_areas_m2=tuple(
                        float(value)
                        for value in (
                            parent_floorwise_stack.get("target_floor_areas_m2")
                            or (base_capacity_contract or {}).get(
                                "target_floor_areas_m2"
                            )
                            or ()
                        )
                    ),
                    terminal_failure_sink=terminal_failure_sink,
                )
                if floorwise_source is None:
                    terminal_reasons = [
                        str(
                            (
                                record.get("evidence") or {}
                            ).get("repair_reason")
                            or record.get("stage")
                            or ""
                        )
                        for record in terminal_failure_sink
                        if isinstance(record, dict)
                    ]
                    floorwise_sibling_evidence.update({
                        "status": "unavailable",
                        "failure_reasons": (
                            terminal_reasons
                            or ["repaired_floorwise_legal_reprojection_failed"]
                        ),
                        "terminal_failure_evidence": deepcopy(
                            terminal_failure_sink
                        ),
                    })
                else:
                    sibling_metadata = (
                        floorwise_source.metadata
                        if isinstance(floorwise_source.metadata, dict)
                        else {}
                    )
                    floorwise_sibling_evidence.update({
                        "status": "materialized",
                        "sibling_volume_count": len(floorwise_source.volumes),
                        "sibling_surface_count": len(floorwise_source.surfaces),
                        "floorwise_legal_matrix_stack": deepcopy(
                            sibling_metadata.get("floorwise_legal_matrix_stack")
                            or {}
                        ),
                    })
                    counts["floorwise_legal_sibling_evidence_count"] = (
                        counts.get("floorwise_legal_sibling_evidence_count", 0)
                        + 1
                    )
        metadata = deepcopy(source.metadata)
        metadata["floorwise_legal_sibling_evidence"] = (
            floorwise_sibling_evidence
        )
        source = replace(source, metadata=metadata)
        shared_floor_contract = _materialize_repaired_floor_contract(
            source,
            generation_context=generation_context,
            capacity_site=capacity_site,
            height=height,
            floors=floors,
            base_capacity_contract=base_capacity_contract,
            repaired_program=repaired_program,
            repaired_compilation=repaired_compilation,
        )
        if shared_floor_contract is not None:
            metadata = deepcopy(source.metadata)
            metadata["shared_floor_contract"] = shared_floor_contract
            source = replace(source, metadata=metadata)
        capacity_measurement: dict[str, Any] = {}
        if base_capacity_contract and capacity_site is not None:
            capacity_measurement = measure_source_capacity(
                source,
                base_capacity_contract,
                site_local_utm=capacity_site,
                height_m=height,
                floors=floors,
                shared_floor_contract=shared_floor_contract,
            )
            metadata = deepcopy(source.metadata)
            metadata["source_capacity_measurement"] = capacity_measurement
            metadata["capacity_alternative_projection"] = evaluate_capacity_alternative(
                parent_capacity_alternative,
                capacity_measurement,
            )
            if (
                shared_floor_contract is not None
                and shared_floor_contract.get("schema_version")
                == "arr.maas.shared_floor_contract.v1"
            ):
                shared_floor_contract = bind_shared_floor_contract_capacity(
                    shared_floor_contract,
                    metadata["capacity_alternative_projection"],
                )
                metadata["shared_floor_contract"] = shared_floor_contract
            source = replace(source, metadata=metadata)
        if requires_canonical_reprojection:
            authority_failures: list[dict[str, Any]] = []
            floor_context = (
                candidate.source.metadata.get("candidate_floor_context")
                if isinstance(
                    candidate.source.metadata.get("candidate_floor_context"),
                    dict,
                )
                else {}
            )
            candidate_capacity_contract = (
                candidate.source.metadata.get("candidate_capacity_contract")
                if isinstance(
                    candidate.source.metadata.get("candidate_capacity_contract"),
                    dict,
                )
                else {}
            )
            legal_floor_field = (
                (base_capacity_contract or {}).get("legal_floor_field")
                if isinstance(base_capacity_contract, dict)
                else {}
            )
            issued_source = _issue_authored_legal_projection_authority(
                base_source,
                source,
                authored_program=repaired_program,
                authored_compilation=repaired_compilation,
                building_type=building_type,
                containment_host=compile_site,
                pnu=str((legal_floor_field or {}).get("pnu") or ""),
                legal_floor_field_hash=str(
                    floor_context.get("legal_floor_field_hash") or ""
                ),
                floor_capacity_plan_hash=str(
                    candidate_capacity_contract.get("floor_capacity_plan_hash")
                    or (base_capacity_contract or {}).get(
                        "floor_capacity_plan_hash"
                    )
                    or ""
                ),
                target_floor_areas_m2=tuple(
                    float(value)
                    for value in (
                        candidate_capacity_contract.get(
                            "target_floor_areas_m2"
                        )
                        or (base_capacity_contract or {}).get(
                            "target_floor_areas_m2"
                        )
                        or ()
                    )
                ),
                capacity_measurement=capacity_measurement,
                capacity_projection=(
                    source.metadata.get("capacity_alternative_projection")
                    if isinstance(
                        source.metadata.get("capacity_alternative_projection"),
                        dict,
                    )
                    else {}
                ),
                failure_sink=authority_failures,
            )
            if issued_source is None:
                typed_failure = (
                    authority_failures[-1]
                    if authority_failures
                    else {
                        "reason": "authority_issuance_returned_none",
                        "evidence": {},
                    }
                )
                record_repair_failure(
                    candidate=candidate,
                    critic_record=record,
                    stage="final_vlm_repair_authority_issuance",
                    reason=str(
                        typed_failure.get("reason")
                        or "repaired_authority_issuance_failed"
                    ),
                    evidence={
                        "repaired_program_hash": repaired_program.program_hash(),
                        "repaired_geometry_hash": repaired_compilation.geometry_hash,
                        "authority_failure": deepcopy(typed_failure),
                    },
                    legacy_counter="repaired_authority_issuance_failed",
                )
                continue
            source = issued_source
        clean_pass, clean_evidence = _clean_mass_gate(source)
        if not clean_pass:
            failures.update(f"clean_{reason}" for reason in clean_evidence.get("failure_reasons") or ())
            continue
        if not _inside_site(source, compile_site):
            failures["containment_failed"] += 1
            continue
        counts["clean_mass_pass_count"] += 1
        repair_sequence = replace(
            candidate.sequence,
            name=f"{candidate.sequence.name}__final_vlm_repair",
            label=f"{candidate.sequence.label} · final VLM typed repair",
            notes=tuple((*candidate.sequence.notes,
                f"final_vlm_typed_repair_response={str(record.get('response_id') or '')}",
                f"final_vlm_typed_repair_parent_geometry={parent_compilation.geometry_hash}",
                "final_vlm_typed_repair_book_reprojection=false",
            )),
        )
        feature = source_feature(
            source,
            repair_sequence,
            building_type=building_type,
            height=height,
            floors=floors,
            site_area=float(compile_site.area),
        )
        props = feature.setdefault("properties", {})
        props.update({
            "candidate_floor_context": deepcopy(
                source.metadata.get("candidate_floor_context") or {}
            ),
            "candidate_capacity_contract": deepcopy(
                source.metadata.get("candidate_capacity_contract") or {}
            ),
            "site_boundary_geometry": mapping(generation_site),
            "site_boundary_source": site_boundary_source,
            "site_access_context": site_access_context,
            "site_access_geometry": site_access_geometry,
            "program_context": program_context,
            "geometry_program": deepcopy(source.metadata.get("geometry_program") or {}),
            "geometry_graph_notes": deepcopy(source.metadata.get("geometry_graph_notes") or []),
            "geometry_graph_snapshot": deepcopy(source.metadata.get("geometry_graph_snapshot") or {}),
            "base_capacity_contract": deepcopy(base_capacity_contract or {}),
            "source_capacity_measurement": deepcopy(capacity_measurement),
            "capacity_alternative_projection": deepcopy(
                source.metadata.get("capacity_alternative_projection") or {}
            ),
            "geometry_authority": str(
                source.metadata.get("geometry_authority") or ""
            ),
            "final_program_hash": str(
                source.metadata.get("final_program_hash") or ""
            ),
            "final_geometry_hash": str(
                source.metadata.get("final_geometry_hash") or ""
            ),
            "final_surface_payload_hash": str(
                source.metadata.get("final_surface_payload_hash") or ""
            ),
            "authored_legal_projection_certificate": deepcopy(
                source.metadata.get("authored_legal_projection_certificate")
                or {}
            ),
            "geometry_program_bridge_evidence": deepcopy(
                source.metadata.get("geometry_program_bridge_evidence") or {}
            ),
            "floorwise_legal_projection": deepcopy(
                source.metadata.get("floorwise_legal_projection") or {}
            ),
            "final_semantic_projection_context": deepcopy(
                source.metadata.get("final_semantic_projection_context") or {}
            ),
            "program_semantic_carrier_evidence": deepcopy(
                source.metadata.get("program_semantic_carrier_evidence") or {}
            ),
        })
        program = attach_program_massing_evidence(feature, building_type=building_type)
        program_form = _program_form_gate(source, building_type)
        feature["properties"]["program_form_gate"] = program_form
        release_contract = _repaired_program_release_contract(
            program,
            program_form,
        )
        feature["properties"]["final_vlm_repair_program_release"] = deepcopy(
            release_contract
        )
        source_metadata = deepcopy(source.metadata)
        source_metadata["final_vlm_repair_program_release"] = deepcopy(
            release_contract
        )
        source = replace(source, metadata=source_metadata)
        if not release_contract["hard_pass"]:
            program_failed = bool(
                not release_contract["volume_hard_pass"]
                or not release_contract["floor_hard_pass"]
            )
            program_form_failed = not release_contract[
                "program_form_hard_pass"
            ]
            failure_reason = (
                "program_and_program_form_gate_failed"
                if program_failed and program_form_failed
                else (
                    "program_gate_failed"
                    if program_failed
                    else "program_form_gate_failed"
                )
            )
            record_repair_failure(
                candidate=candidate,
                critic_record=record,
                stage="final_vlm_repair_program_gate",
                reason=failure_reason,
                evidence={
                    "repaired_program_hash": repaired_program.program_hash(),
                    "repaired_geometry_hash": repaired_compilation.geometry_hash,
                    "program_gate": deepcopy(program),
                    "program_form_gate": deepcopy(program_form),
                    "repaired_program_release": deepcopy(release_contract),
                    "program_failed_gates": list(
                        program.get("failed_gates")
                        or program.get("failure_reasons")
                        or ()
                    ),
                    "program_form_failed_gates": list(
                        program_form.get("failed_gates")
                        or program_form.get("failure_reasons")
                        or ()
                    ),
                },
                legacy_counter="program_hard_gate_failed",
            )
            continue
        counts["program_hard_pass_count"] += 1
        if release_contract["design_review_required"]:
            outcome = StageOutcome.diagnostic(
                "final_vlm_repair_program_design_review",
                "non_statutory_program_design_review_required",
                evidence={
                    "source_sequence": candidate.sequence.name,
                    "geometry_family": _geometry_program_family(candidate),
                    "critic_response_id": str(record.get("response_id") or ""),
                    "repaired_program_hash": repaired_program.program_hash(),
                    "repaired_geometry_hash": repaired_compilation.geometry_hash,
                    "repaired_program_release": deepcopy(release_contract),
                    "program_gate": deepcopy(program),
                    "program_form_gate": deepcopy(program_form),
                },
            )
            record_stage_outcome(outcome, records=stage_outcomes)
            repair_outcomes.append(outcome.to_record())
            counts["design_diagnostic_release_count"] = (
                int(counts.get("design_diagnostic_release_count") or 0) + 1
            )
        spatial = feature["properties"]["program_spatial_evidence"]
        if capacity_measurement:
            capacity_score = capacity_fit_score(
                source.metadata.get("capacity_alternative_projection") or {},
                capacity_measurement,
            )
            score = _mass_stage_design_score(
                program_fit_score=float(program["program_fit_score"]),
                architectural_score=float(spatial["architectural_score"]),
                advisory_capacity_score=capacity_score,
            )
        else:
            score = _mass_stage_design_score(
                program_fit_score=float(program["program_fit_score"]),
                architectural_score=float(spatial["architectural_score"]),
            )
        repaired.append(_Candidate(
            candidate.principle_id,
            candidate.principle_kind,
            candidate.operation,
            repair_sequence,
            source,
            feature,
            round(score, 6),
        ))
    counts["repaired_candidate_count"] = len(repaired)
    counts["repaired_llm_authored_count"] = sum(_llm_authored_candidate(candidate) for candidate in repaired)
    counts["failure_counts"] = dict(sorted(failures.items()))
    counts["mutation_issue_counts"] = dict(sorted(mutation_issue_counts.items()))
    counts["compilation_issue_counts"] = dict(sorted(compilation_issue_counts.items()))
    counts["compilation_issue_detail_counts"] = dict(sorted(compilation_issue_detail_counts.items()))
    counts["llm_authored_failure_counts"] = dict(sorted(authored_failure_counts.items()))
    counts["stage_outcomes"] = stage_outcomes
    counts["failure_records"] = failure_records
    counts["repair_outcomes"] = repair_outcomes
    return repaired, counts


def _exact_post_book_repair_shortlist(
    candidates: list[_Candidate],
    records: dict[str, dict[str, Any]],
    *,
    repair_budget: int,
) -> list[_Candidate]:
    """Allocate repair bandwidth from exact VLM evidence, not proxy score.

    The previous implementation sorted only by the pre-VLM procedural score.
    That discarded nearly all typed LLM candidates even when the exact critic
    gave them one localized, executable repair.  This reservation changes only
    which failed ASTs are repaired; it grants no selection preference and all
    repaired solids still repeat every hard gate and exact VLM review.
    """
    budget = max(0, int(repair_budget))
    if not candidates or budget <= 0:
        return []

    def priority(candidate: _Candidate) -> tuple[float, ...]:
        record = records.get(candidate.sequence.name) or {}
        scores = record.get("concept_scores") if isinstance(record.get("concept_scores"), dict) else {}
        failures = list(record.get("failures") or ())
        visual_mean = sum(float(scores.get(key) or 0.0) for key in (
            "gesture_clarity", "hierarchy", "repair_integrity",
            "program_appropriateness", "void_publicness", "section_program_fit",
        )) / 6.0
        program_fit = "final_book_program_fit_failed" not in failures
        return (
            float(program_fit),
            -float(len(failures)),
            float(scores.get("repair_integrity") or 0.0),
            visual_mean,
            float(candidate.score),
        )

    ranked = sorted(candidates, key=priority, reverse=True)
    authored = [candidate for candidate in ranked if _llm_authored_candidate(candidate)]
    authored_quota = min(len(authored), max(4, budget // 3), budget)
    chosen = authored[:authored_quota]
    chosen_ids = {id(candidate) for candidate in chosen}
    for candidate in ranked:
        if len(chosen) >= budget:
            break
        if id(candidate) in chosen_ids:
            continue
        chosen.append(candidate)
        chosen_ids.add(id(candidate))
    return chosen



__all__ = ["_final_book_vlm_hard_pass","_final_book_vlm_shortlist","_audit_final_book_geometry_with_vlm","audit_book_base_stage_with_vlm","_repair_exact_post_book_candidates_from_vlm","_exact_post_book_repair_shortlist"]
