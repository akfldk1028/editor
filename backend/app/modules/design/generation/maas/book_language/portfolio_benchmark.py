"""Fast, measured BOOK-operation portfolios on one real parcel.

This benchmark is intentionally bounded: it compiles typed operations over
program assemblies once, filters by clean/program gates, and performs measured
shape-diverse selection.  It is the synchronous diagnostic counterpart to the
slower evolutionary/VLM loop, not a replacement for legal/FAR/parking repair.
"""

from __future__ import annotations

import math
import json
import hashlib
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass, replace
from email.utils import parsedate_to_datetime
from math import atan2, cos, degrees, hypot, pi, sin, sqrt
from pathlib import Path
from time import perf_counter, time
from typing import Any, Callable

from PIL import Image
from shapely.errors import GEOSException
from shapely.geometry import Polygon, mapping, shape

from backend.app.modules.design.generation.maas.geometry_language import GeometryOutcomeGraph, GeometryProgram, GeometryAuthorError, audit_reference_matches_for_massing, build_geometry_graph_notes, build_geometry_graph_snapshot, apply_book_projection_to_geometry_program, apply_geometry_edits, apply_geometry_edits_compiler_safe, architectural_shape_programs, reference_language_programs, replace_source_dominant_with_geometry_program, openai_vlm_geometry_critic, retrieve_geometry_reference_matches, run_geometry_program_a2a_loop, compile_geometry_program_to_source_mass, compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.gate import GeometryGatePolicy, compilation_gate
from backend.app.modules.design.generation.maas.geometry_language.compiler import revalidate_compilation_mesh
from backend.app.modules.design.generation.maas.geometry_language.run_state import update_run_progress
from backend.app.modules.design.generation.maas.geometry_language.projected_visual_contract import CertifiedMassArtifact, projected_visual_z_coordinate_mode, semantic_audit_payload_hash
from backend.app.modules.design.generation.maas.capacity_policy import resolve_massing_capacity_policy
from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbSequence
from backend.app.modules.design.generation.maas.mass_brain import publish_geometry_portfolio_shadow
from backend.app.modules.design.generation.maas.program_massing import ProgramSectionGraphEdit, book_sentence_variants, compose_program_with_book_operations, mutate_program_section_sequence, program_reference_contract, program_seed_sequences, resolve_program_profile
DIAGNOSTIC_TARGET_OPTIONS = (1, 2, 3, 5, 20)
_PROJECTED_VISUAL_ARTIFACT_ABSENT = object()

from backend.app.modules.design.generation.maas.paid_provider_budget import paid_provider_budget_snapshot
from backend.app.modules.design.generation.maas.program_massing.assembly import program_component_chassis
from backend.app.modules.design.generation.maas.program_massing.benchmark import render_archive_sheet
from backend.app.modules.design.generation.maas.program_massing.morphology import intrinsic_section_profile_distance, intrinsic_shape_distance, intrinsic_silhouette_distance
from backend.app.modules.design.generation.maas.program_massing.scoring import attach_program_massing_evidence
from backend.app.modules.design.generation.maas.program_massing.competition_gestalt import build_certified_mesh_gestalt_evidence, certified_mesh_morphology_payload_hash, competition_gestalt_distance, competition_gestalt_key
from backend.app.modules.design.generation.maas.program_massing.certified_artifact_measurement import exact_compilation_mesh_payload_hash, measure_authoritative_geometry_artifact
from backend.app.modules.design.generation.maas.program_massing.search import materialize_source_feature_surfaces, program_seed_variants, source_feature
from backend.app.modules.design.generation.maas.preference.loop import feature_preview_png, openai_preview_preference_scorer
from backend.app.modules.design.generation.maas.book_language.archive_layout import ARCHIVE_CARD_WIDTH, ARCHIVE_PREVIEW_HEIGHT, archive_card_crop_box
from backend.app.modules.design.generation.maas.preference.vlm_scorer import score_portfolio_board_with_openai_vlm
from backend.app.modules.design.generation.maas.source_geometry import compile_sequence_to_source_mass
from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass, SourceSurface
from backend.app.modules.design.generation.maas.agents.law_graph_agent.evidence import collect_law_agent_evidence_batch
from backend.app.modules.design.generation.maas.agents.shared.types import ExecutionIdentity
from backend.app.modules.design.generation.maas.mass_product_evidence import resolve_floor_capacity_plan_identity
from backend.app.modules.design.generation.maas.book_language.mass_passport_bridge import persist_selected_law_agent_evidence, resolve_capacity_band_evidence, selected_candidate_execution_passport


def default_outcome_graph_path(output_dir: Path) -> Path:
    """Return the one-run causal graph owned by ``output_dir``.

    A generated MASS must be reproducible from the references, typed program,
    compiler evidence and critic observations that belonged to that run.  A
    parcel-wide append-only graph silently imported old selection caps and VLM
    repairs into unrelated runs and eventually grew large enough to exhaust
    memory.  Cross-run transfer is therefore opt-in through
    ``outcome_graph_path``; the safe default is this self-contained shard.
    """
    return Path(output_dir).resolve() / "maas-geometry-mutation-outcome-graph.json"

from backend.app.modules.design.generation.maas.book_language.registry import build_book_language_registry
from backend.app.modules.design.generation.maas.book_language.semantics import BASE_VOLUME_FRACTIONS
from backend.app.modules.design.generation.maas.book_language.downstream_hard_gate import LegalGenerationContext, build_legal_generation_context, evaluate_accepted_sources_downstream, fit_source_to_sunlight_field, generation_site_at_height
from backend.app.modules.design.generation.maas.book_language.capacity_contract import build_feasible_capacity_contract, measure_source_capacity, recursive_plan_coverage_floor
from backend.app.modules.design.generation.maas.book_language.floor_capacity_plan import derive_program_floor_capacity_plan
from backend.app.modules.design.generation.maas.book_language.final_mesh_floor_evidence import FinalMeshFloorEvidenceError, certify_final_mesh_actual_gfa_stop, resolve_candidate_finalization_context
from backend.app.modules.design.generation.maas.book_language.legal_floor_field import validate_legal_floor_field
from backend.app.modules.design.generation.maas.book_language.lineage import AppliedBookCandidateReason, classify_applied_book_candidate, gate_descendants_by_base, lineage_record, staged_principle_schedule


from backend.app.modules.design.generation.maas.book_language.candidate_analysis import _Candidate, _distance, _silhouette_distance, _portfolio_diversity_key, _scope_key, _capacity_alternative_key, _seed_family, _section_family, _roof_archetype, _chassis_family, _geometry_program_family, _geometry_program_metadata, _plan_family, _vlm_reviewed_program_candidate, _llm_authored_candidate, _seed_is_llm_authored, _solid_morphology_metrics, _section_silhouette_flags, _program_form_gate, _architectural_articulation_metrics, _design_concept_descriptor, _program_section_phenotype, _oriented_aspect, _oriented_plan_dimensions, _program_dimensional_context, _fingerprint, _inside_site, _clean_mass_gate, _site_access_side_in_principal_frame
from backend.app.modules.design.generation.maas.book_language.agent_authored_supply import AgentAuthoredAdmission, AgentAuthoredSupplyError, CODEX_OAUTH_AUTHOR_PROVIDER, build_agent_authored_program_seeds, filter_agent_authored_replay_programs, is_validated_codex_oauth_candidate, load_agent_authored_geometry_programs


def _bind_trusted_codex_completion(
    completion: dict[str, Any],
    *,
    manifest_required: bool,
    selected_count: int,
    trusted_codex_selected_count: int,
) -> dict[str, Any]:
    """Make trusted Codex lineage part of the persisted completion contract."""

    bound = deepcopy(completion)
    bound["trusted_codex_selected_count"] = int(
        trusted_codex_selected_count
    )
    bound["trusted_codex_lineage_required"] = bool(manifest_required)
    if (
        manifest_required
        and int(trusted_codex_selected_count) != int(selected_count)
    ):
        failures = [
            str(value)
            for value in bound.get("failures") or ()
        ]
        if "selected_codex_oauth_lineage_incomplete" not in failures:
            failures.append("selected_codex_oauth_lineage_incomplete")
        bound["failures"] = failures
        bound["hard_pass"] = False
    return bound


def _trusted_codex_selection_pool(
    candidates: list[_Candidate],
    *,
    admission: AgentAuthoredAdmission | None,
) -> tuple[list[_Candidate], int]:
    """Exclude every non-admitted candidate before manifest-mode selection."""

    trusted = [
        candidate
        for candidate in candidates
        if is_validated_codex_oauth_candidate(
            candidate,
            admission=admission,
        )
    ]
    return trusted, len(candidates) - len(trusted)


def _capacity_hard_pass_selection_pool(
    candidates: list[_Candidate],
    *,
    required: bool,
) -> tuple[list[_Candidate], list[dict[str, Any]]]:
    """Keep underfilled geometry available for repair, not final selection."""

    if not required:
        return list(candidates), []
    retained: list[_Candidate] = []
    exclusions: list[dict[str, Any]] = []
    for candidate in candidates:
        metadata = candidate.source.metadata
        resolution = resolve_capacity_band_evidence(
            metadata.get("capacity_alternative_projection") or {},
            capacity_measurement=(
                metadata.get("source_capacity_measurement") or {}
            ),
        )
        if resolution.get("resolved_capacity_hard_pass") is True:
            retained.append(candidate)
            continue
        exclusions.append({
            "reason": "capacity_hard_pass_required",
            "resolved_capacity_alternative_id": str(
                resolution.get("resolved_capacity_alternative_id") or ""
            ),
            "achieved_capacity_utilization": float(
                resolution.get("achieved_capacity_utilization") or 0.0
            ),
            "minimum_capacity_utilization": float(
                resolution.get("resolved_capacity_minimum_utilization")
                or 0.0
            ),
        })
    return retained, exclusions


def _certified_mesh_source(
    source: SourceMass,
    compilation: Any,
) -> SourceMass:
    """Materialize the exact selected visual mesh as gestalt authority."""

    root_operator = (
        compilation.program.node_map[
            compilation.program.root_id
        ].operator
    )
    surfaces = tuple(
        SourceSurface(
            role=f"certified_visual_mesh_{index}",
            volume_role="certified_visual_mesh",
            verb="geometry_program",
            surface_type="profiled_recursive_solid_mesh",
            vertices_m=tuple(
                tuple(float(value) for value in compilation.vertices[
                    vertex_index
                ])
                for vertex_index in triangle
            ),
            operator=root_operator,
            semantic_patch_id=(
                f"certified_visual_mesh:triangle:{index}"
            ),
        )
        for index, triangle in enumerate(compilation.triangles)
    )
    metadata = deepcopy(source.metadata)
    metadata.pop("measured_solid_morphology", None)
    metadata["geometry_program_compilation"] = (
        compilation.to_dict(include_mesh=False)
    )
    metadata["authored_legal_preservation"] = {
        "status": "certified",
        "hard_pass": True,
        "projection_mode": "certified_projected_visual_mesh",
    }
    return replace(
        source,
        surfaces=surfaces,
        metadata=metadata,
    )


def _exact_compilation_mesh_payload_hash(compilation: Any) -> str:
    return exact_compilation_mesh_payload_hash(compilation)


def _resolve_authoritative_floor_context(
    *,
    pnu: str = "",
    generation_context: LegalGenerationContext | None,
    site_local_utm: Polygon,
    building_type: str,
    catalog_height_m: float,
    catalog_floors: int,
    dimensional_context: dict[str, Any],
    target_utilization: float,
) -> tuple[float, int, dict[str, Any]]:
    """Resolve the sole pre-authoring floor authority for one program run."""

    if generation_context is None:
        return (
            float(dimensional_context.get("effective_height_m") or catalog_height_m),
            int(dimensional_context.get("effective_floors") or catalog_floors),
            {},
        )
    plan = derive_program_floor_capacity_plan(
        generation_context,
        site_local_utm=site_local_utm,
        building_type=building_type,
        target_utilization=target_utilization,
        dimensional_context=dimensional_context,
        legacy_floor_hint=catalog_floors,
        pnu=pnu,
    )
    return (
        float(plan.get("selected_height_m") or 0.0),
        int(plan.get("selected_floor_count") or 0),
        plan,
    )


def _shared_floor_hard_pass_candidates(candidates):
    """Retain the exact MASS pool; shared-floor evidence is diagnostic here."""
    return list(candidates)


def _candidate_program_hard_pass(candidate) -> bool:
    """Read only the canonical program authority and fail closed if absent."""

    result = candidate.source.metadata.get("program_gate_result") or {}
    return bool(isinstance(result, dict) and result.get("hard_pass") is True)


def _program_selection_candidates(candidates):
    """Exclude development-only BASE review inputs from selection/downstream."""

    return [
        candidate
        for candidate in candidates
        if _candidate_program_hard_pass(candidate)
    ]


def _smoke_pre_downstream_candidate_pass(candidate, row) -> bool:
    """Apply only MASS-owned gates before downstream legal/parking review."""
    return bool(row.get("inside_site") and row.get("program_hard_pass"))


def _final_downstream_publish_failures(
    rows: list[dict[str, Any]],
    *,
    selected_count: int,
) -> list[str]:
    """Fail closed unless every selected MASS has a final passing gate row."""
    if len(rows) != selected_count:
        return ["final_downstream_cardinality_mismatch"]
    if any(not bool(row.get("combined_hard_pass")) for row in rows):
        return ["final_downstream_hard_gate_failed"]
    return []


def _apply_final_downstream_publish_gate(
    *,
    failures: list[str],
    downstream_rows: list[dict[str, Any]],
    selected_count: int,
    smoke_mode: bool,
) -> dict[str, Any]:
    """Apply the same final downstream authority in every run mode."""
    del smoke_mode
    resolved_failures = list(failures)
    for failure in _final_downstream_publish_failures(
        downstream_rows,
        selected_count=selected_count,
    ):
        if failure not in resolved_failures:
            resolved_failures.append(failure)
    return {
        "status": "fail" if resolved_failures else "pass",
        "failures": resolved_failures,
    }


def _persist_final_downstream_authority(
    row: dict[str, Any],
    downstream_row: dict[str, Any],
) -> None:
    """Copy exact final gate evidence without trusting request projections."""
    row["capacity_hard_gate"] = deepcopy(
        downstream_row.get("capacity_hard_gate") or {}
    )
    row["semantic_projection_hard_gate"] = deepcopy(
        downstream_row.get("semantic_projection_hard_gate") or {}
    )
    row["combined_hard_pass"] = bool(
        downstream_row.get("combined_hard_pass")
    )


class SelectedSemanticProjectionHardGateError(ValueError):
    """Typed persistence failure for absent/rejected selected authority."""

    def __init__(self, evidence: dict[str, Any]) -> None:
        self.evidence = dict(evidence)
        super().__init__(
            "selected_semantic_projection_hard_gate_invalid: "
            + str(self.evidence.get("reason") or "unknown")
        )


def _selected_semantic_projection_hard_gate(
    feature: dict[str, Any],
    *,
    candidate_id: str,
) -> dict[str, Any]:
    """Load the final-VLM-bound gate from this exact selected feature."""

    properties = (
        feature.get("properties")
        if isinstance(feature, dict)
        and isinstance(feature.get("properties"), dict)
        else {}
    )
    artifact = properties.get("geometry_artifact")
    artifact = artifact if isinstance(artifact, dict) else {}
    gate = artifact.get("semanticProjectionAudit")
    if not isinstance(gate, dict) or not gate:
        raise SelectedSemanticProjectionHardGateError({
            "schema_version": "arr.maas.selected_semantic_projection_failure.v1",
            "reason": "selected_semantic_projection_hard_gate_missing",
            "candidate_id": str(candidate_id or ""),
            "hard_pass": False,
            "failures": ["semantic_projection_hard_gate_missing"],
        })
    if gate.get("hard_pass") is not True:
        raise SelectedSemanticProjectionHardGateError({
            "schema_version": "arr.maas.selected_semantic_projection_failure.v1",
            "reason": "selected_semantic_projection_hard_gate_failed",
            "candidate_id": str(candidate_id or ""),
            "hard_pass": False,
            "failures": list(gate.get("failures") or ()),
        })
    return deepcopy(gate)


def _portfolio_witness_candidate_status(
    candidate_program_hash: str,
    *,
    selected_program_hashes: set[str],
    selection_pool_hashes: set[str],
) -> str:
    if candidate_program_hash in selected_program_hashes:
        return "selected"
    if candidate_program_hash in selection_pool_hashes:
        return "hard_pass_not_selected"
    return "rejected"

from backend.app.modules.design.generation.maas.book_language.portfolio_selection import PORTFOLIO_SILHOUETTE_DISTANCE, build_gestalt_compatibility_analysis, _scope_coverage_anchors, _select, _selection_capacity_diagnostics, _rebalance_measured_morphologies, _bounded_visual_selection_pool, _target_hard_pass_universe
from backend.app.modules.design.generation.maas.book_language.competition_portfolio_contract import competition_pair_required_distance, competition_portfolio_contract
from backend.app.modules.design.generation.maas.book_language.quality_diversity_archive import qd_archive_evidence
from backend.app.modules.design.generation.maas.book_language.legal_mass_archive_board import render_legal_mass_archive_board

from backend.app.modules.design.generation.maas.book_language.gate_diagnostics import _empty_gate_diagnostic, _record_gate_diagnostic, _metric_summary, _summarize_gate_diagnostic, _merge_gate_diagnostics

from backend.app.modules.design.generation.maas.book_language.program_catalog import PROGRAMS
from backend.app.modules.design.generation.maas.book_language.portfolio_feedback import enrich_portfolio_vlm_feedback
from backend.app.modules.design.generation.maas.book_language.authorship_policy import REQUIRED_ARCHITECTURAL_STRATEGIES, bounded_live_llm_synthesis_requests
from backend.app.modules.design.generation.maas.book_language.portfolio_witness import persist_portfolio_witness
from backend.app.modules.design.generation.maas.book_language.portfolio_evaluation_bridge import book_candidate_evaluation_input, build_portfolio_evaluation_ledger
from backend.app.modules.design.generation.maas.book_language.portfolio_candidate_previews import render_candidate_preview_assets
from backend.app.modules.design.generation.maas.book_language.run_budget import progressive_mass_run_budget, replenishment_allowed_by_deadline
from backend.app.modules.design.generation.maas.paid_provider_budget import paid_provider_budget_snapshot
from backend.app.modules.design.generation.maas.book_language.portfolio_contract import evaluate_portfolio_completion, resolve_progressive_portfolio_requirement, resolve_portfolio_requirement
from backend.app.modules.design.generation.maas.book_language.final_vlm_cycle import run_final_vlm_cycle
from backend.app.modules.design.generation.maas.book_language.portfolio_replenishment import _synthesis_requests_with_author_rate_limit_cooldown, bounded_replenishment_work_dispositions, _merge_live_qd_reserve, _repair_final_vlm_submission_fingerprints, competition_exact_hard_pass_reserve, competition_exact_hard_pass_deficits, competition_exact_reserve_transition, family_supply_deficits_for_candidates, replenishment_cycle_budget_for_run, replenishment_stop_reason, run_replenishment_cycle, certified_reviewed_base_parent_snapshot


def _bounded_replenishment_causal_feedback(
    existing_feedback: list[dict[str, Any]] | None,
    *,
    exact_repair_evidence: dict[str, Any] | None = None,
    stage_outcomes: list[dict[str, Any]] | None = None,
    final_vlm_gate: dict[str, Any] | None = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Merge coordinate-free causal failures into the existing author channel."""

    import json

    bounded_limit = max(0, min(24, int(limit)))
    if bounded_limit <= 0:
        return []
    source_limit = min(24, max(bounded_limit, 12))
    remaining_nodes = 384

    blocked_keys = {
        "coordinate",
        "coordinates",
        "vertices",
        "vertices_m",
        "triangles",
        "surfaces",
        "surface_payload",
        "mesh_payload",
        "image",
        "image_url",
        "vlm_image_inputs",
        "site_boundary_geometry",
        "legal_geometry_utm",
        "occupied_geometry_utm",
        "final_authored_surface_payload",
        "typed_surface_payload",
    }

    def bounded(value: Any, depth: int = 0) -> Any:
        nonlocal remaining_nodes
        if remaining_nodes <= 0:
            return None
        remaining_nodes -= 1
        if depth > 4:
            return None
        if isinstance(value, str):
            return value[:500]
        if isinstance(value, (bool, int, float)) or value is None:
            return value
        if isinstance(value, (list, tuple)):
            return [
                converted
                for item in value[:12]
                if (converted := bounded(item, depth + 1)) is not None
            ]
        if isinstance(value, dict):
            if "coordinates" in value and str(value.get("type") or ""):
                return None
            result: dict[str, Any] = {}
            for key, item in list(value.items())[:32]:
                safe_key = str(key)[:100]
                if safe_key.lower() in blocked_keys:
                    continue
                converted = bounded(item, depth + 1)
                if converted is not None:
                    result[safe_key] = converted
            return result
        return None

    def capped_tail(value: Any) -> list[Any]:
        if not isinstance(value, (list, tuple)):
            return []
        return list(value[-source_limit:])

    candidates: list[dict[str, Any]] = [
        safe
        for item in capped_tail(existing_feedback)
        if isinstance(item, dict)
        and isinstance((safe := bounded(item)), dict)
        and safe
    ]
    repair = exact_repair_evidence if isinstance(exact_repair_evidence, dict) else {}
    for failure in capped_tail(repair.get("failure_records")):
        if not isinstance(failure, dict):
            continue
        safe_failure = bounded(failure)
        if not isinstance(safe_failure, dict):
            continue
        candidates.append({
            "schema_version": "arr.maas.replenishment_causal_feedback.v1",
            "feedback_source": "exact_post_book_typed_repair",
            "stage": str(failure.get("stage") or "typed_repair")[:120],
            "reason": str(
                failure.get("status")
                or failure.get("failure_reason")
                or "typed_repair_failed"
            )[:160],
            "program_hash": str(failure.get("program_hash") or "")[:160],
            "source_sequence": str(failure.get("source_sequence") or "")[:200],
            "geometry_family": str(failure.get("geometry_family") or "")[:120],
            "evidence": safe_failure,
        })
    for outcome in capped_tail(stage_outcomes):
        if not isinstance(outcome, dict) or outcome.get("kind") != "failed":
            continue
        safe_outcome = bounded(outcome)
        if not isinstance(safe_outcome, dict):
            continue
        evidence = outcome.get("evidence") if isinstance(outcome.get("evidence"), dict) else {}
        candidates.append({
            "schema_version": "arr.maas.replenishment_causal_feedback.v1",
            "feedback_source": "stage_outcome",
            "stage": str(outcome.get("stage") or "unknown_stage")[:120],
            "reason": str(outcome.get("reason") or "stage_failed")[:160],
            "program_hash": str(evidence.get("program_hash") or "")[:160],
            "geometry_family": str(evidence.get("geometry_family") or "")[:120],
            "book_scope": str(evidence.get("book_scope") or "")[:40],
            "evidence": safe_outcome,
        })
    gate = final_vlm_gate if isinstance(final_vlm_gate, dict) else {}
    for audit in capped_tail(gate.get("audit_records")):
        if not isinstance(audit, dict) or audit.get("hard_pass") is True:
            continue
        safe_audit = bounded(audit)
        if not isinstance(safe_audit, dict):
            continue
        failures = [str(value) for value in audit.get("failures") or () if str(value)]
        candidates.append({
            "schema_version": "arr.maas.replenishment_causal_feedback.v1",
            "feedback_source": "final_book_vlm",
            "stage": "final_book_vlm",
            "reason": (failures[0] if failures else "final_book_vlm_rejected")[:160],
            "program_hash": str(audit.get("program_hash") or "")[:160],
            "source_sequence": str(audit.get("source_sequence") or "")[:200],
            "geometry_family": str(audit.get("geometry_family") or "")[:120],
            "book_scope": str(audit.get("book_scope") or "")[:40],
            "critic_actions": bounded(list(audit.get("critic_actions") or ())),
            "geometry_edits": bounded(list(audit.get("geometry_edits") or ())),
            "evidence": safe_audit,
        })

    deduplicated: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        sources = {
            str(source)
            for source in candidate.get("feedback_sources") or ()
            if str(source)
        }
        if candidate.get("feedback_source"):
            sources.add(str(candidate["feedback_source"]))
        causal_identity = {
            key: candidate.get(key)
            for key in (
                "stage",
                "reason",
                "program_hash",
                "source_sequence",
                "geometry_family",
                "book_scope",
            )
        }
        if any(value not in (None, "", [], {}) for value in causal_identity.values()):
            identity_payload = {"causal_identity": causal_identity}
        else:
            identity_payload = {
                "legacy_payload": {
                    key: value
                    for key, value in candidate.items()
                    if key not in {"feedback_source", "feedback_sources"}
                }
            }
        identity = json.dumps(
            identity_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        if identity in deduplicated:
            prior = deduplicated[identity]
            sources.update(
                str(source)
                for source in prior.get("feedback_sources") or ()
                if str(source)
            )
            if prior.get("feedback_source"):
                sources.add(str(prior["feedback_source"]))
            candidate["feedback_sources"] = sorted(sources)
            del deduplicated[identity]
            deduplicated[identity] = candidate
            continue
        candidate["feedback_sources"] = sorted(sources)
        deduplicated[identity] = candidate
    return list(deduplicated.values())[-bounded_limit:]


def _selector_replenishment_stage_outcomes(
    *,
    selection_trace: dict[str, Any] | None,
    selection_capacity_diagnostics: dict[str, Any] | None,
    family_supply_deficits: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Describe selector exclusions for the existing causal-feedback channel."""

    trace = selection_trace if isinstance(selection_trace, dict) else {}
    diagnostics = (
        selection_capacity_diagnostics
        if isinstance(selection_capacity_diagnostics, dict)
        else {}
    )
    family = (
        family_supply_deficits
        if isinstance(family_supply_deficits, dict)
        else {}
    )
    reason_counts = diagnostics.get("reason_counts") or {}
    exclusive_counts = diagnostics.get("exclusive_reason_counts") or {}
    distance_summary = diagnostics.get(
        "minimum_silhouette_distance_summary"
    ) or {}
    caps = diagnostics.get("caps") or {}
    cap_keys = {
        "book_operation_cap": "book_operation",
        "genotype_cap": "genotype",
        "section_family_cap": "section_family",
        "roof_archetype_cap": "roof_archetype_default",
        "chassis_family_cap": "chassis_family",
        "design_concept_cap": "design_concept_key",
        "solid_phenotype_cap": "solid_phenotype",
        "wedge_like_cap": "wedge_like",
        "pyramidal_like_cap": "pyramidal_like",
    }
    outcomes: list[dict[str, Any]] = []
    for reason, count in sorted(reason_counts.items()):
        if not str(reason) or int(count or 0) <= 0:
            continue
        evidence: dict[str, Any] = {
            "excluded_candidate_count": int(count),
            "exclusive_candidate_count": int(
                exclusive_counts.get(reason) or 0
            ),
        }
        if reason == "silhouette_near_duplicate":
            evidence.update({
                "measured_distance": float(
                    distance_summary.get("minimum") or 0.0
                ),
                "measured_distance_summary": deepcopy(distance_summary),
                "required_threshold": float(
                    caps.get("silhouette_distance_minimum") or 0.0
                ),
            })
        elif reason in cap_keys:
            evidence["cap"] = int(caps.get(cap_keys[reason]) or 0)
        outcomes.append({
            "kind": "failed",
            "stage": "portfolio_selection",
            "reason": str(reason),
            **evidence,
            "evidence": evidence,
        })

    target_count = max(0, int(diagnostics.get("target_count") or 0))
    selected_count = max(0, int(diagnostics.get("selected_count") or 0))
    selection_universe_count = max(
        0,
        int(diagnostics.get("selection_universe_count") or 0),
    )
    remaining_candidate_count = max(
        0,
        int(diagnostics.get("remaining_candidate_count") or 0),
    )
    if (
        target_count > 0
        and selected_count < target_count
        and remaining_candidate_count == 0
    ):
        evidence = {
            "target_count": target_count,
            "selected_count": selected_count,
            "selection_universe_count": selection_universe_count,
            "remaining_candidate_count": remaining_candidate_count,
            "candidate_supply_shortfall": target_count - selected_count,
            "portfolio_contract_deficits": [
                str(item)[:200]
                for item in (trace.get("portfolio_contract_deficits") or [])[:12]
                if str(item).strip()
            ],
        }
        outcomes.append({
            "kind": "failed",
            "stage": "portfolio_selection",
            "reason": "candidate_supply_exhausted",
            **evidence,
            "evidence": evidence,
        })

    missing_descriptor_cells: list[str] = []
    for source in (trace, family):
        for key, value in source.items():
            normalized_key = str(key).lower()
            if not (
                "missing" in normalized_key
                and ("descriptor" in normalized_key or "cell" in normalized_key)
            ):
                continue
            values = value if isinstance(value, (list, tuple)) else [value]
            missing_descriptor_cells.extend(
                str(item)[:200]
                for item in values[:12]
                if str(item)
            )
    trace_deficits = trace.get("portfolio_contract_deficits") or []
    missing_descriptor_cells.extend(
        str(item)[:200]
        for item in trace_deficits[:12]
        if "missing" in str(item).lower()
        and not (
            missing_descriptor_cells
            and str(item).lower() == "missing_descriptor_cells"
        )
    )
    missing_descriptor_cells = list(dict.fromkeys(missing_descriptor_cells))[:12]
    if missing_descriptor_cells:
        outcomes.append({
            "kind": "failed",
            "stage": "portfolio_selection",
            "reason": "missing_descriptor_cells",
            "missing_descriptor_cells": missing_descriptor_cells,
            "evidence": {
                "missing_descriptor_cells": missing_descriptor_cells,
            },
        })
    return outcomes


def _post_selection_family_supply_deficits(
    selection_pool: list[_Candidate],
    selected: list[_Candidate],
    *,
    target_count: int,
    compatibility_analysis: Any,
    selection_trace: dict[str, Any] | None,
    selection_capacity_diagnostics: dict[str, Any] | None,
) -> dict[str, Any]:
    """Recompute supply from selected witnesses plus every selector exclusion."""

    selected_ids = {id(candidate) for candidate in selected}
    selected_and_excluded = [
        *selected,
        *(
            candidate
            for candidate in selection_pool
            if id(candidate) not in selected_ids
        ),
    ]
    deficits = family_supply_deficits_for_candidates(
        selected_and_excluded,
        target_count=target_count,
        compatibility_analysis=compatibility_analysis,
    )
    diagnostics = (
        selection_capacity_diagnostics
        if isinstance(selection_capacity_diagnostics, dict)
        else {}
    )
    trace = selection_trace if isinstance(selection_trace, dict) else {}
    return {
        **deficits,
        "candidate_supply_count": len(selected_and_excluded),
        "candidate_supply_shortfall": max(
            0,
            int(target_count) - len(selected_and_excluded),
        ),
        "selection_exclusion_evidence": {
            "reason_counts": deepcopy(diagnostics.get("reason_counts") or {}),
            "portfolio_contract_deficits": deepcopy(
                trace.get("portfolio_contract_deficits") or []
            ),
        },
    }


@dataclass(frozen=True)
class SelectorReplenishmentState:
    phase: str
    selection_capacity_diagnostics: dict[str, Any]
    family_supply_deficits: dict[str, Any]
    selector_stage_outcomes: tuple[dict[str, Any], ...]
    prior_cycle_causal_evidence: dict[str, Any]


def _selector_replenishment_state_boundary(
    *,
    phase: str,
    selection_pool: list[_Candidate],
    selected: list[_Candidate],
    target_count: int,
    visual_directive: dict[str, Any] | None,
    compatibility_analysis: Any,
    selection_trace: dict[str, Any] | None,
    exact_repair_evidence: dict[str, Any] | None,
    stage_outcomes: list[dict[str, Any]] | None,
    final_vlm_gate: dict[str, Any] | None,
) -> SelectorReplenishmentState:
    """Commit post-selector evidence for the next author cycle."""

    diagnostics = _selection_capacity_diagnostics(
        selection_pool,
        selected,
        target=target_count,
        visual_directive=visual_directive,
        compatibility_analysis=compatibility_analysis,
    )
    family_deficits = _post_selection_family_supply_deficits(
        selection_pool,
        selected,
        target_count=target_count,
        compatibility_analysis=compatibility_analysis,
        selection_trace=selection_trace,
        selection_capacity_diagnostics=diagnostics,
    )
    selector_outcomes = _selector_replenishment_stage_outcomes(
        selection_trace=selection_trace,
        selection_capacity_diagnostics=diagnostics,
        family_supply_deficits=family_deficits,
    )
    return SelectorReplenishmentState(
        phase=str(phase),
        selection_capacity_diagnostics=diagnostics,
        family_supply_deficits=family_deficits,
        selector_stage_outcomes=tuple(selector_outcomes),
        prior_cycle_causal_evidence={
            "exact_post_book_typed_repair": deepcopy(
                exact_repair_evidence or {}
            ),
            "stage_outcomes": [
                *deepcopy(stage_outcomes or []),
                *deepcopy(selector_outcomes),
            ],
            "final_book_vlm_gate": deepcopy(final_vlm_gate or {}),
        },
    )


def _select_with_replenishment_state(
    *,
    phase: str,
    selection_pool: list[_Candidate],
    target_count: int,
    visual_directive: dict[str, Any] | None,
    compatibility_analysis: Any,
    allow_diagnostic_fallback: bool,
    exact_repair_evidence: dict[str, Any] | None,
    stage_outcomes: list[dict[str, Any]] | None,
    final_vlm_gate: dict[str, Any] | None,
) -> tuple[list[_Candidate], dict[str, Any], SelectorReplenishmentState]:
    """Run selection before freezing the evidence consumed next cycle."""

    selection_trace: dict[str, Any] = {}
    selected = _select(
        selection_pool,
        target_count,
        visual_directive=visual_directive,
        selection_trace=selection_trace,
        compatibility_analysis=compatibility_analysis,
        allow_diagnostic_fallback=allow_diagnostic_fallback,
    )
    state = _selector_replenishment_state_boundary(
        phase=phase,
        selection_pool=selection_pool,
        selected=selected,
        target_count=target_count,
        visual_directive=visual_directive,
        compatibility_analysis=compatibility_analysis,
        selection_trace=selection_trace,
        exact_repair_evidence=exact_repair_evidence,
        stage_outcomes=stage_outcomes,
        final_vlm_gate=final_vlm_gate,
    )
    return selected, selection_trace, state


def _next_synthesis_inputs_from_selector_state(
    state: SelectorReplenishmentState,
    *,
    synthesis_requests: list[dict[str, Any]],
    authored_visual_authority_replenishment_feedback: list[dict[str, Any]],
    legal_fit_repair_feedback: list[dict[str, Any]],
    capacity_authoring_deficits: list[dict[str, Any]],
    progressive_target: int | None,
    base_book_vlm_replenishment_feedback: list[dict[str, Any]],
    selected_count: int,
    selected_scope_count: int,
    target_count: int,
    required_scope_count: int,
    exact_compile_remaining: int | None,
    cycle_index: int,
    cycle_budget: int,
    author_replenishment_remaining: int | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Consume one frozen selector state through the existing author channel."""

    causal = state.prior_cycle_causal_evidence
    feedback = _bounded_replenishment_causal_feedback(
        authored_visual_authority_replenishment_feedback,
        exact_repair_evidence=causal.get("exact_post_book_typed_repair"),
        stage_outcomes=causal.get("stage_outcomes"),
        final_vlm_gate=causal.get("final_book_vlm_gate"),
    )
    inputs = _deficit_directed_replenishment_inputs(
        synthesis_requests,
        legal_fit_repair_feedback=legal_fit_repair_feedback,
        capacity_authoring_deficits=capacity_authoring_deficits,
        family_supply_deficits=state.family_supply_deficits,
        progressive_target=progressive_target,
        base_book_vlm_replenishment_feedback=(
            base_book_vlm_replenishment_feedback
        ),
        authored_visual_authority_replenishment_feedback=feedback,
        selected_count=selected_count,
        selected_scope_count=selected_scope_count,
        target_count=target_count,
        required_scope_count=required_scope_count,
        exact_compile_remaining=exact_compile_remaining,
        cycle_index=cycle_index,
        cycle_budget=cycle_budget,
        author_replenishment_remaining=author_replenishment_remaining,
    )
    return inputs, feedback


def _deficit_directed_replenishment_inputs(
    synthesis_requests: list[dict[str, Any]],
    *,
    legal_fit_repair_feedback: list[dict[str, Any]],
    capacity_authoring_deficits: list[dict[str, Any]],
    family_supply_deficits: dict[str, Any],
    progressive_target: int | None,
    base_book_vlm_replenishment_feedback: list[dict[str, Any]] | None = None,
    authored_visual_authority_replenishment_feedback: list[dict[str, Any]] | None = None,
    selected_count: int,
    selected_scope_count: int,
    target_count: int,
    required_scope_count: int,
    exact_compile_remaining: int | None = None,
    cycle_index: int = 1,
    cycle_budget: int = 1,
    author_replenishment_remaining: int | None = None,
) -> dict[str, Any]:
    bounded_legal = deepcopy(legal_fit_repair_feedback[-12:])
    bounded_capacity_source = deepcopy(capacity_authoring_deficits[-12:])
    bounded_family = deepcopy(dict(list(family_supply_deficits.items())[-12:]))
    bounded_base_critique = deepcopy(
        (base_book_vlm_replenishment_feedback or [])[-12:]
    )
    bounded_authored_visual_authority = deepcopy(
        (authored_visual_authority_replenishment_feedback or [])[-12:]
    )
    capacity_replenishment_contract = {
        "schema_version": "arr.maas.capacity_replenishment_contract.v1",
        "require_new_geometry_program_ast": True,
        "respond_to_measured_per_floor_gfa_deficits": True,
        "respond_to_required_utilization": True,
        "preserve_legal_floor_sections": True,
        "preserve_typed_book_operations": True,
        "preserve_authored_identity": True,
        "require_family_diversity_response": True,
        "forbid_named_form_recipes": True,
        "forbid_deterministic_geometry_replacement": True,
        "forbid_gate_lowering": True,
    }
    capacity_authoring_instruction = (
        "author a new GeometryProgram/AST that responds to measured per-floor "
        "GFA deficits and required utilization through authored AST changes; "
        "preserve legal floor sections, typed BOOK operations, authored identity, "
        "and family diversity; never use a named form recipe, deterministic "
        "geometry replacement, or gate lowering"
    )
    bounded_capacity = [
        {
            **deficit,
            "replenishment_response_contract": deepcopy(
                capacity_replenishment_contract
            ),
            "authoring_instruction": capacity_authoring_instruction,
        }
        for deficit in bounded_capacity_source
        if isinstance(deficit, dict)
    ]
    valid_requests = [
        request
        for request in synthesis_requests
        if isinstance(request, dict)
    ]
    selected_requests = (
        [valid_requests[(max(1, int(cycle_index)) - 1) % len(valid_requests)]]
        if valid_requests
        else []
    )
    compile_remaining = exact_compile_remaining
    if compile_remaining is None and progressive_target is not None:
        compile_remaining = progressive_mass_run_budget(
            progressive_target
        ).compile_limit
    remaining_exact = max(0, int(compile_remaining or 0))
    remaining_cycle_opportunities = max(
        1,
        int(cycle_budget) - max(1, int(cycle_index)) + 1,
    )
    author_opportunities = (
        remaining_cycle_opportunities
        if author_replenishment_remaining is None
        else max(1, int(author_replenishment_remaining))
    )
    viable_cycles = max(1, min(
        remaining_cycle_opportunities,
        author_opportunities,
        max(1, remaining_exact),
    ))
    cycle_exact_limit = (
        (remaining_exact + viable_cycles - 1) // viable_cycles
        if remaining_exact > 0
        else 0
    )
    candidate_demand = max(
        0,
        int(target_count) - int(selected_count),
        int(required_scope_count) - int(selected_scope_count),
    )

    def cycle_request(request: dict[str, Any]) -> dict[str, Any]:
        original_counts = [
            max(0, int(request.get(name) or 0))
            for name in ("candidate_count", "llm_author_count")
            if int(request.get(name) or 0) > 0
        ]
        original_count = min(original_counts) if original_counts else 8
        effective_count = min(
            original_count,
            candidate_demand,
            cycle_exact_limit,
        )
        return {
            **dict(request),
            "candidate_count": effective_count,
            "llm_author_count": effective_count,
            "legal_fit_repair_feedback": bounded_legal,
            "capacity_authoring_deficits": bounded_capacity,
            "family_supply_deficits": bounded_family,
            "require_new_geometry_program_ast": True,
            "author_stage": "replenishment",
            "author_request_kind": "geometry_author_replenishment",
            "base_book_vlm_replenishment_feedback": bounded_base_critique,
            "authored_visual_authority_replenishment_feedback": (
                bounded_authored_visual_authority
            ),
            "instruction": (
                str(request.get("instruction") or "")
                + "; author a new GeometryProgram/AST whose program_hash differs "
                "from rejected parents; " + capacity_authoring_instruction
            ).strip("; "),
        }
    requests = [cycle_request(request) for request in selected_requests]
    return {
        "synthesis_requests": requests,
        "exact_compile_limit": cycle_exact_limit,
    }


def _remaining_exact_compile_budget(limit: int, *actual_usage: int) -> int:
    return max(0, int(limit) - sum(max(0, int(value)) for value in actual_usage))


def _replenishment_cycle_preflight_stop_reason(
    *,
    selected_count: int,
    selected_scope_count: int,
    target_count: int,
    required_scope_count: int,
    exact_compile_remaining: int | None,
    author_replenishment_remaining: int | None,
    runtime_reserve_available: bool,
    successful_author_count: int | None = None,
    successful_author_limit: int | None = None,
    provider_attempts_remaining: int | None = None,
) -> str:
    """Stop before a cycle only for completion or an exhausted real budget."""

    if (
        selected_count >= target_count
        and selected_scope_count >= required_scope_count
    ):
        return "target_and_scope_coverage_reached"
    if exact_compile_remaining is not None and exact_compile_remaining <= 0:
        return "cumulative_exact_compile_budget_exhausted"
    successful_author_quota_active = (
        successful_author_count is not None
        and successful_author_limit is not None
    )
    if successful_author_quota_active:
        if int(successful_author_count) >= max(0, int(successful_author_limit)):
            return "replenishment_author_quota_exhausted"
        if provider_attempts_remaining is not None and provider_attempts_remaining <= 0:
            return "replenishment_provider_attempt_budget_exhausted"
    elif (
        author_replenishment_remaining is not None
        and author_replenishment_remaining <= 0
    ):
        return "replenishment_author_quota_exhausted"
    if not runtime_reserve_available:
        return "runtime_reserve_exhausted"
    return ""


def _materialized_authored_supply_success(cycle_evidence: dict[str, Any]) -> int:
    if not bool(cycle_evidence.get("llm_author_request_executed")):
        return 0
    stage_counts = cycle_evidence.get(
        "geometry_program_llm_author_stage_counts"
    ) or {}
    return int(int(stage_counts.get("directed_geometry_materialized") or 0) > 0)


def _replenishment_author_budget_state(
    provider_snapshot: dict[str, Any],
    *,
    successful_author_count: int,
) -> dict[str, int | None]:
    quota_limits = provider_snapshot.get("quota_limits") or {}
    quota_remaining = provider_snapshot.get("quota_remaining_counts") or {}
    author_remaining_raw = quota_remaining.get("author_replenishment")
    author_limit_raw = quota_limits.get("author_replenishment")
    total_remaining_raw = provider_snapshot.get("remaining_count")
    author_remaining = (
        max(0, int(author_remaining_raw))
        if author_remaining_raw is not None
        else None
    )
    return {
        "author_replenishment_remaining": author_remaining,
        "successful_author_count": max(0, int(successful_author_count)),
        "successful_author_limit": (
            max(0, int(author_limit_raw))
            if author_limit_raw is not None
            else None
        ),
        "provider_attempts_remaining": (
            max(0, int(total_remaining_raw))
            if total_remaining_raw is not None
            else None
        ),
    }


def _run_replenishment_cycle_with_compile_authority(
    run_cycle: Callable[..., Any],
    *,
    exact_compile_remaining: int | None,
    compile_stop_sink: dict[str, Any],
    cycle_index: int,
    **cycle_kwargs: Any,
) -> Any | None:
    """Call the cycle without exceeding the run-global exact remainder."""

    if exact_compile_remaining is not None and exact_compile_remaining <= 0:
        compile_stop_sink["progressive_exact_compile_stop"] = {
            "schema_version": "arr.maas.progressive_exact_compile_stop.v1",
            "status": "cumulative_exact_compile_budget_exhausted",
            "cycle_not_started": int(cycle_index),
            "remaining": 0,
        }
        return None
    if exact_compile_remaining is not None:
        cycle_limit = cycle_kwargs.get("exact_compile_limit")
        cycle_kwargs["exact_compile_limit"] = min(
            int(exact_compile_remaining),
            int(cycle_limit)
            if cycle_limit is not None
            else int(exact_compile_remaining),
        )
    return run_cycle(cycle_index=cycle_index, **cycle_kwargs)


@dataclass(frozen=True)
class _AuthorRateLimitCooldownState:
    attempt_count: int = 0
    deadline_epoch_seconds: float | None = None
    backoff_seconds: float = 0.0
    source: str = ""
    http_status: int | None = None
    retry_after_seconds: float | None = None
    retry_after_http_date: str = ""
    scope: str = ""
    circuit_open: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "arr.maas.author_rate_limit_cooldown.v1",
            "attempt_count": int(self.attempt_count),
            "deadline_epoch_seconds": self.deadline_epoch_seconds,
            "backoff_seconds": float(self.backoff_seconds),
            "source": self.source,
            "http_status": self.http_status,
            "retry_after_seconds": self.retry_after_seconds,
            "retry_after_http_date": self.retry_after_http_date,
            "scope": self.scope,
            "circuit_open": bool(self.circuit_open),
        }


def _author_rate_limit_cooldown_before_cycle(
    state: _AuthorRateLimitCooldownState,
    *,
    now: float,
) -> tuple[_AuthorRateLimitCooldownState, dict[str, Any] | None]:
    if state.circuit_open and state.scope == "benchmark_run":
        return state, {
            **state.to_dict(),
            "active": True,
        }
    deadline = state.deadline_epoch_seconds
    if deadline is None:
        return state, None
    remaining = max(0.0, float(deadline) - float(now))
    if remaining <= 0.0:
        return _AuthorRateLimitCooldownState(
            attempt_count=state.attempt_count,
            backoff_seconds=state.backoff_seconds,
            source=state.source,
            http_status=state.http_status,
            retry_after_seconds=state.retry_after_seconds,
            retry_after_http_date=state.retry_after_http_date,
            scope=state.scope,
        ), None
    return state, {
        **state.to_dict(),
        "active": True,
        "remaining_seconds": remaining,
    }


def _author_rate_limit_cooldown_after_cycle(
    state: _AuthorRateLimitCooldownState,
    outcomes: list[Any] | tuple[Any, ...],
    *,
    now: float,
) -> _AuthorRateLimitCooldownState:
    def nested_rate_limits(value: Any) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        if isinstance(value, dict):
            if (
                value.get("category") == "rate_limited"
                and int(value.get("http_status") or 0) == 429
            ):
                found.append(value)
            for nested in value.values():
                found.extend(nested_rate_limits(nested))
        elif isinstance(value, (list, tuple)):
            for nested in value:
                found.extend(nested_rate_limits(nested))
        return found

    updated = state
    for raw_outcome in outcomes:
        if not isinstance(raw_outcome, dict):
            continue
        executed = bool(raw_outcome.get("provider_request_executed"))
        valid_count = max(0, int(
            raw_outcome.get("valid_authored_program_count") or 0
        ))
        diagnostics = raw_outcome.get("failure_diagnostics") or {}
        rate_limits = nested_rate_limits(diagnostics)
        if executed and valid_count > 0 and not rate_limits:
            updated = _AuthorRateLimitCooldownState()
            continue
        if not executed or not rate_limits:
            continue
        provider_error = rate_limits[0]
        attempt_count = int(updated.attempt_count) + 1
        retry_after_raw = provider_error.get("retry_after_seconds")
        retry_after = (
            max(0.0, float(retry_after_raw))
            if isinstance(retry_after_raw, (int, float))
            else None
        )
        retry_after_http_date = str(
            provider_error.get("retry_after_http_date") or ""
        )
        http_date_backoff: float | None = None
        if retry_after is None and retry_after_http_date:
            try:
                parsed_retry_after = parsedate_to_datetime(
                    retry_after_http_date
                )
                if parsed_retry_after.tzinfo is not None:
                    http_date_backoff = max(
                        0.0,
                        parsed_retry_after.timestamp() - float(now),
                    )
            except (TypeError, ValueError, OverflowError):
                http_date_backoff = None
        if retry_after is not None:
            backoff = retry_after
            source = "retry_after"
            scope = "deadline"
            circuit_open = False
            deadline = float(now) + backoff
        elif http_date_backoff is not None:
            backoff = http_date_backoff
            source = "retry_after_http_date"
            scope = "deadline"
            circuit_open = False
            deadline = float(now) + backoff
        else:
            backoff = 0.0
            source = "benchmark_run_circuit"
            scope = "benchmark_run"
            circuit_open = True
            deadline = None
        updated = _AuthorRateLimitCooldownState(
            attempt_count=attempt_count,
            deadline_epoch_seconds=deadline,
            backoff_seconds=backoff,
            source=source,
            http_status=429,
            retry_after_seconds=retry_after,
            retry_after_http_date=(
                retry_after_http_date
                if http_date_backoff is not None
                else ""
            ),
            scope=scope,
            circuit_open=circuit_open,
        )
    return updated


def _run_initial_generation_with_author_cooldown(
    generation_function: Callable[..., tuple[list[Any], dict[str, Any]]],
    *generation_args: Any,
    cooldown_state: _AuthorRateLimitCooldownState,
    synthesis_requests: list[Any] | tuple[Any, ...],
    clock: Callable[[], float] = time,
    **generation_kwargs: Any,
) -> tuple[list[Any], dict[str, Any], _AuthorRateLimitCooldownState]:
    active_state, cooldown_payload = (
        _author_rate_limit_cooldown_before_cycle(
            cooldown_state,
            now=float(clock()),
        )
    )
    pool, counts = generation_function(
        *generation_args,
        synthesis_requests=(
            _synthesis_requests_with_author_rate_limit_cooldown(
                synthesis_requests,
                cooldown_payload,
            )
        ),
        **generation_kwargs,
    )
    return pool, counts, _author_rate_limit_cooldown_after_cycle(
        active_state,
        list(counts.get("llm_author_request_outcomes") or ()),
        now=float(clock()),
    )


def optional_book_base_review_callback(
    enabled: bool,
    callback: Callable[[list[Any]], tuple[list[Any], dict[str, Any]]],
) -> Callable[[list[Any]], tuple[list[Any], dict[str, Any]]] | None:
    """Keep the disabled path as ``None`` at the generation boundary."""

    return callback if enabled else None


def partition_finalizable_candidates(
    candidates: list[Any],
    *,
    resolver: Callable[[Any], Any],
) -> tuple[list[Any], list[tuple[Any, dict[str, Any]]]]:
    """Fail one incoherent finalization identity without losing its evidence."""

    accepted = []
    rejected = []
    for candidate in candidates:
        try:
            resolver(candidate)
        except FinalMeshFloorEvidenceError as error:
            rejected.append((candidate, deepcopy(error.evidence)))
        else:
            accepted.append(candidate)
    return accepted, rejected


def portfolio_candidate_id(
    book_principle_id: str,
    program_hash: str,
) -> str:
    """Bind a reusable BOOK principle to one executable candidate identity."""

    return f"{str(book_principle_id)}:{str(program_hash)[:12]}"


def downstream_rows_indexed_by_program_hash(
    rows: list[dict[str, Any]],
    *,
    fallback_program_hashes: tuple[str, ...] = (),
) -> dict[str, dict[str, Any]]:
    """Index gate rows by persisted or same-order candidate identity."""

    return {
        resolved_hash: row
        for index, row in enumerate(rows)
        if isinstance(row, dict)
        and (
            resolved_hash := str(
                row.get("final_legal_program_hash")
                or (
                    fallback_program_hashes[index]
                    if index < len(fallback_program_hashes)
                    else ""
                )
                or ""
            )
        )
    }


@dataclass(frozen=True)
class _ReplenishmentLiveState:
    live_qd_reserve: tuple[Any, ...]
    reviewed_final_vlm_fingerprints: frozenset[tuple[Any, ...]]
    certified_reviewed_base_parents: tuple[Any, ...] = ()
    replenishment_work_dispositions: tuple[Any, ...] = ()
    author_rate_limit_cooldown: _AuthorRateLimitCooldownState = (
        _AuthorRateLimitCooldownState()
    )


def _initial_replenishment_live_state(
    candidates: list[Any],
    *,
    reviewed_final_vlm_fingerprints: set[tuple[Any, ...]],
    certified_reviewed_base_parents: tuple[Any, ...] = (),
    replenishment_work_dispositions: tuple[Any, ...] = (),
    author_rate_limit_cooldown: _AuthorRateLimitCooldownState = (
        _AuthorRateLimitCooldownState()
    ),
) -> _ReplenishmentLiveState:
    return _ReplenishmentLiveState(
        live_qd_reserve=tuple(_merge_live_qd_reserve([], candidates)),
        reviewed_final_vlm_fingerprints=frozenset(
            reviewed_final_vlm_fingerprints
        ),
        certified_reviewed_base_parents=(
            certified_reviewed_base_parent_snapshot(
                carried=certified_reviewed_base_parents
            )
        ),
        replenishment_work_dispositions=(
            bounded_replenishment_work_dispositions(
                replenishment_work_dispositions
            )
        ),
        author_rate_limit_cooldown=author_rate_limit_cooldown,
    )


def _run_replenishment_cycle_with_live_state(
    cycle_boundary: Callable[..., Any],
    cycle_function: Callable[..., Any],
    *,
    state: _ReplenishmentLiveState,
    clock: Callable[[], float] = time,
    **cycle_kwargs: Any,
) -> tuple[Any, _ReplenishmentLiveState]:
    cooldown_state, cooldown_payload = (
        _author_rate_limit_cooldown_before_cycle(
            state.author_rate_limit_cooldown,
            now=float(clock()),
        )
    )
    active_state = _ReplenishmentLiveState(
        live_qd_reserve=state.live_qd_reserve,
        reviewed_final_vlm_fingerprints=state.reviewed_final_vlm_fingerprints,
        certified_reviewed_base_parents=state.certified_reviewed_base_parents,
        replenishment_work_dispositions=state.replenishment_work_dispositions,
        author_rate_limit_cooldown=cooldown_state,
    )
    cycle = cycle_boundary(
        cycle_function,
        retained_live_qd_reserve=list(state.live_qd_reserve),
        reviewed_final_vlm_fingerprints=set(
            state.reviewed_final_vlm_fingerprints
        ),
        certified_reviewed_base_parents=deepcopy(
            state.certified_reviewed_base_parents
        ),
        replenishment_work_dispositions=deepcopy(
            state.replenishment_work_dispositions
        ),
        author_rate_limit_cooldown=deepcopy(cooldown_payload),
        **cycle_kwargs,
    )
    if cycle is None:
        return cycle, active_state
    evidence = getattr(cycle, "evidence", {}) or {}
    next_cooldown_state = _author_rate_limit_cooldown_after_cycle(
        cooldown_state,
        list(evidence.get("llm_author_request_outcomes") or ()),
        now=float(clock()),
    )
    return cycle, _ReplenishmentLiveState(
        live_qd_reserve=tuple(cycle.live_qd_reserve),
        reviewed_final_vlm_fingerprints=frozenset(
            cycle.reviewed_final_vlm_fingerprints
        ),
        certified_reviewed_base_parents=(
                certified_reviewed_base_parent_snapshot(
                    carried=getattr(
                        cycle,
                        "certified_reviewed_base_parents",
                        state.certified_reviewed_base_parents,
                    )
                )
        ),
        replenishment_work_dispositions=(
                bounded_replenishment_work_dispositions(
                    getattr(
                        cycle,
                        "replenishment_work_dispositions",
                        state.replenishment_work_dispositions,
                    )
                )
        ),
        author_rate_limit_cooldown=next_cooldown_state,
    )
from backend.app.modules.design.generation.maas.book_language.reference_context import _audited_final_book_references, _reference_language_author_context

from backend.app.modules.design.generation.maas.book_language.candidate_generation import _agent_mutated_seeds, _prebook_vlm_quarantined_llm_parents, _geometry_program_registry, _materialize_directed_geometry, _program_pool

from backend.app.modules.design.generation.maas.book_language.vlm_review import _bind_final_visual_authority_for_review, _book_vlm_review_budget, _final_book_vlm_hard_pass, _final_book_vlm_shortlist, _audit_final_book_geometry_with_vlm, audit_book_base_stage_with_vlm, _repair_exact_post_book_candidates_from_vlm, _exact_post_book_repair_shortlist


def _smoke_floor_pass_reserve(
    selection_target: int,
    *,
    live_vlm: bool = False,
) -> int:
    """Keep a bounded reserve for downstream parking and legal survival."""

    selection_reserve = max(1, int(selection_target)) * 3
    if not live_vlm:
        return selection_reserve
    paid_review_slots = min(4, _book_vlm_review_budget("final_book"))
    return max(selection_reserve, paid_review_slots * 3)


def _partition_replenishment_vlm_candidates(
    retained_hard_passes: list[_Candidate],
    new_candidates: list[_Candidate],
) -> tuple[list[_Candidate], list[_Candidate]]:
    """Keep prior exact passes out of the new-candidate VLM review pool."""
    return (
        list(retained_hard_passes),
        _bounded_visual_selection_pool(list(new_candidates)),
    )


def _load_visual_directive(output_dir: Path, pnu: str) -> dict[str, Any]:
    path = output_dir / "maas-book-programs-vlm-directive.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "arr.maas.portfolio_vlm_directive.v1"
        or str(payload.get("pnu") or "") != pnu
        or payload.get("status") != "active"
    ):
        return {}
    return payload


def _projected_visual_handoff_artifact(
    source: Any,
    *,
    final_semantic_audit: dict[str, Any] | None = None,
    existing_artifact: Any = None,
    existing_authority_context: dict[str, Any] | None = None,
) -> Any:
    """Preserve an absent authority separately from malformed payload values."""

    if isinstance(source, CertifiedMassArtifact):
        return source.payload()
    if isinstance(source, dict) and isinstance(
        source.get("properties"), dict
    ):
        properties = source["properties"]
        if "geometry_artifact" not in properties:
            raise ValueError(
                "selected candidate has no certified MASS artifact"
            )
        existing_artifact = properties.get("geometry_artifact")
        existing_authority_context = properties.get(
            "final_semantic_anchor"
        )

    if (
        isinstance(existing_artifact, dict)
        and (
            "projectedVisualMesh" in existing_artifact
            or "projectedVisualCertificate" in existing_artifact
        )
    ):
        return CertifiedMassArtifact.load(
            existing_artifact,
            authority_context=(
                existing_authority_context
                if isinstance(existing_authority_context, dict)
                else {}
            ),
        ).payload()
    metadata = getattr(source, "metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    certificate = metadata.get("floorwise_visual_projection")
    source_declares_authority = (
        metadata.get("geometry_authority") in {
            "authored_projected_surface_payload",
            "authored_compiled_surface_payload",
        }
        or (
            isinstance(certificate, dict)
            and certificate.get("status")
            != "not_applicable_no_authored_mesh"
        )
    )
    if not source_declares_authority:
        return _PROJECTED_VISUAL_ARTIFACT_ABSENT
    raise ValueError("selected final candidate has no CertifiedMassArtifact")


class ProjectedVisualHandoffError(ValueError):
    """Raised when projected visual authority cannot supply render geometry."""

    def __init__(self, evidence: dict[str, Any]) -> None:
        self.evidence = dict(evidence)
        super().__init__(
            "projected_visual_handoff_invalid: "
            + str(self.evidence["reason"])
        )


def _projected_visual_handoff_error(
    reason: str,
    *,
    triangle_count: int,
    triangle_index: int | None = None,
) -> ProjectedVisualHandoffError:
    evidence: dict[str, Any] = {
        "failure_code": "projected_visual_handoff_invalid",
        "reason": reason,
        "triangle_count": int(triangle_count),
    }
    if triangle_index is not None:
        evidence["triangle_index"] = int(triangle_index)
    return ProjectedVisualHandoffError(evidence)


def _staged_projected_visual_surfaces(
    projected_visual_artifact: Any,
    *,
    visual_origin: Any,
    candidate_height: float,
) -> list[dict[str, Any]]:
    """Build a complete render replacement without mutating feature state."""

    if not isinstance(projected_visual_artifact, dict):
        raise _projected_visual_handoff_error(
            "invalid_artifact",
            triangle_count=0,
        )
    mesh = projected_visual_artifact.get("projectedVisualMesh")
    if not isinstance(mesh, dict):
        raise _projected_visual_handoff_error(
            "invalid_projected_visual_mesh",
            triangle_count=0,
        )
    triangles = mesh.get("triangles")
    if not isinstance(triangles, list):
        raise _projected_visual_handoff_error(
            "invalid_triangle_payload",
            triangle_count=0,
        )
    if not triangles:
        raise _projected_visual_handoff_error(
            "empty_triangles",
            triangle_count=0,
        )
    legacy_normalized_z = (
        projected_visual_z_coordinate_mode(projected_visual_artifact)
        == "normalized_height_fraction_z"
    )

    replacement: list[dict[str, Any]] = []
    for triangle_index, triangle in enumerate(triangles):
        if not isinstance(triangle, dict):
            raise _projected_visual_handoff_error(
                "invalid_triangle_record",
                triangle_count=len(triangles),
                triangle_index=triangle_index,
            )
        vertices = triangle.get("vertices_m")
        if not isinstance(vertices, (list, tuple)) or len(vertices) != 3:
            raise _projected_visual_handoff_error(
                "invalid_triangle_vertices",
                triangle_count=len(triangles),
                triangle_index=triangle_index,
            )
        world_vertices: list[list[float]] = []
        for vertex in vertices:
            if not isinstance(vertex, (list, tuple)) or len(vertex) != 3:
                raise _projected_visual_handoff_error(
                    "invalid_triangle_vertices",
                    triangle_count=len(triangles),
                    triangle_index=triangle_index,
                )
            if not all(
                isinstance(component, (int, float))
                and not isinstance(component, bool)
                and math.isfinite(float(component))
                for component in vertex
            ):
                raise _projected_visual_handoff_error(
                    "invalid_triangle_vertices",
                    triangle_count=len(triangles),
                    triangle_index=triangle_index,
                )
            x, y, z = (float(component) for component in vertex)
            world_vertices.append([
                float(visual_origin.x) + x,
                float(visual_origin.y) + y,
                float(candidate_height) * z if legacy_normalized_z else z,
            ])
        rendered_triangle = deepcopy(triangle)
        rendered_triangle["vertices_world_m"] = world_vertices
        replacement.append(rendered_triangle)

    return replacement


def _atomically_replace_projected_visual_surfaces(
    props: dict[str, Any],
    projected_visual_artifact: Any,
    *,
    visual_origin: Any,
    candidate_height: float,
) -> None:
    """Replace surfaces only after the complete projected payload validates."""

    replacement = _staged_projected_visual_surfaces(
        projected_visual_artifact,
        visual_origin=visual_origin,
        candidate_height=candidate_height,
    )
    props["source_surfaces"] = replacement


def _stage_projected_visual_handoff(
    projected_visual_artifact: Any,
    *,
    final_semantic_anchor: dict[str, Any],
    visual_origin: Any,
    candidate_height: float,
    authority_present: bool | None = None,
) -> dict[str, Any]:
    """Stage all projected-authority property changes without mutation."""

    staged = {
        "projected_visual_section_geometry_binding_hash": str(
            final_semantic_anchor.get(
                "expected_section_geometry_binding_hash"
            ) or ""
        ),
    }
    if authority_present is None:
        authority_present = (
            projected_visual_artifact
            is not _PROJECTED_VISUAL_ARTIFACT_ABSENT
        )
    if not authority_present:
        if (
            projected_visual_artifact
            is not _PROJECTED_VISUAL_ARTIFACT_ABSENT
        ):
            raise _projected_visual_handoff_error(
                "authority_presence_mismatch",
                triangle_count=0,
            )
        return staged
    _staged_projected_visual_surfaces(
        projected_visual_artifact,
        visual_origin=visual_origin,
        candidate_height=candidate_height,
    )
    staged.update({
        "projected_visual_geometry_hash": str(
            projected_visual_artifact.get("projectedVisualGeometryHash") or ""
        ),
    })
    return staged


def _persist_projected_visual_authority(
    props: dict[str, Any],
    *,
    geometry_artifact: dict[str, Any],
    staged_handoff: dict[str, Any],
    final_semantic_anchor: dict[str, Any],
) -> Any:
    """Validate canonical artifact authority before atomically rebinding props."""

    certified = CertifiedMassArtifact.load(
        geometry_artifact,
        authority_context=final_semantic_anchor,
    )
    binding = certified.feature_binding()
    props.update({
        **staged_handoff,
        **binding,
    })
    return certified.validated_visual


def _candidate_program_hash(candidate: _Candidate) -> str:
    source = getattr(candidate, "source", None)
    metadata = getattr(source, "metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    for key in ("final_legal_program_hash", "authored_program_hash"):
        value = str(metadata.get(key) or "")
        if value:
            return value
    for key in ("geometry_program", "authored_geometry_program"):
        payload = metadata.get(key)
        if not isinstance(payload, dict):
            continue
        try:
            value = str(GeometryProgram.from_dict(payload).program_hash() or "")
        except (KeyError, TypeError, ValueError):
            value = ""
        if value:
            return value
    compilation = metadata.get("geometry_program_compilation") or {}
    if isinstance(compilation, dict):
        value = str(compilation.get("program_hash") or "")
        if value:
            return value
    return f"candidate:{getattr(candidate, 'principle_id', '')}"


def _allow_partial_portfolio_preview(
    *,
    diagnostic_target: int | None,
    progressive_target: int | None,
) -> bool:
    return diagnostic_target is not None or progressive_target is not None


def _portfolio_count_requirements(
    *,
    selection_target: int,
    required_scope_target: int,
    available_principle_kind_count: int,
) -> dict[str, int]:
    target = max(1, int(selection_target))
    return {
        "book_operation_count": min(10, target),
        "visual_language_count": min(10, target),
        "base_volume_scope_count": min(target, int(required_scope_target)),
        "principle_kind_count": min(target, int(available_principle_kind_count)),
    }


def _allow_incomplete_preview_finalization(
    *,
    diagnostic_target: int | None,
    smoke_mode: bool,
    progressive_target: int | None,
    selected_count: int,
    selection_target: int,
    explicitly_relaxed: bool,
) -> bool:
    return bool(
        diagnostic_target is not None
        or smoke_mode
        or explicitly_relaxed
        or (
            progressive_target is not None
            and 0 < int(selected_count) < int(selection_target)
        )
    )


def _synchronize_finalization_publish_authority(
    *,
    passport: dict[str, Any],
    artifact: dict[str, Any],
    downstream_row: dict[str, Any],
    final_row: dict[str, Any],
) -> dict[str, Any]:
    """Keep every publish authority aligned with finalization certification."""

    finalization_hard_pass = bool(
        passport.get("candidate_finalization_hard_pass") is not False
        and passport.get("publishable") is not False
        and str(passport.get("status") or "")
        != "diagnostic_non_publishable"
    )
    reason = ""
    if not finalization_hard_pass:
        fallback_stage = next(
            (
                stage
                for stage in reversed(passport.get("stages") or ())
                if isinstance(stage, dict)
                and stage.get("id") == "candidate_finalization_fallback"
            ),
            {},
        )
        stage_evidence = (
            fallback_stage.get("evidence")
            if isinstance(fallback_stage.get("evidence"), dict)
            else {}
        )
        reason = str(
            stage_evidence.get("reason")
            or "candidate_finalization_not_strict_publishable"
        )[:240]
    authority = {
        "schema_version": "arr.maas.finalization_publish_authority.v1",
        "status": "passed" if finalization_hard_pass else "failed",
        "hard_pass": finalization_hard_pass,
        "publishable": finalization_hard_pass,
        "reason": reason,
        "authority": "execution_passport_candidate_finalization",
    }
    hard_gates = artifact.get("hardGates")
    if not isinstance(hard_gates, dict):
        hard_gates = {}
        artifact["hardGates"] = hard_gates
    hard_gates["candidateFinalization"] = deepcopy(authority)
    downstream_row["candidate_finalization_hard_gate"] = deepcopy(authority)
    final_row["candidate_finalization_hard_gate"] = deepcopy(authority)
    if not finalization_hard_pass:
        hard_gates["combinedHardPass"] = False
        downstream_row["combined_hard_pass"] = False
        final_row["combined_hard_pass"] = False
    return authority


def _archive_render_evidence(
    board: Path,
    candidate_count: int,
    *,
    projected_visual_hashes: list[str] | tuple[str, ...] = (),
    final_legal_geometry_hashes: list[str] | tuple[str, ...] = (),
    exact_mesh_payload_hashes: list[str] | tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Measure whether each accepted card visibly contains rendered mass.

    Geometry validity alone cannot catch a camera/transport regression that
    produces an apparently empty review card.  The archive renderer uses one
    stable orange material, so record a conservative material-pixel ratio as
    post-render evidence.  This is not a design-quality score and does not
    replace direct PNG review.
    """
    try:
        image = Image.open(board).convert("RGB")
    except (OSError, ValueError):
        return []
    evidence: list[dict[str, Any]] = []
    for index in range(max(0, int(candidate_count))):
        crop_box = archive_card_crop_box(index + 1)
        pixels = image.crop(crop_box).getdata()
        material_pixels = sum(
            1 for red, green, blue in pixels
            if red > 90 and red >= green + 18 and green >= blue + 8
        )
        ratio = material_pixels / float(ARCHIVE_CARD_WIDTH * ARCHIVE_PREVIEW_HEIGHT)
        projected_visual_hash = (
            str(projected_visual_hashes[index])
            if index < len(projected_visual_hashes)
            else ""
        )
        final_legal_geometry_hash = (
            str(final_legal_geometry_hashes[index])
            if index < len(final_legal_geometry_hashes)
            else projected_visual_hash
        )
        exact_mesh_payload_hash = (
            str(exact_mesh_payload_hashes[index])
            if index < len(exact_mesh_payload_hashes)
            else ""
        )
        evidence.append({
            "card_index": index + 1,
            "board_png": str(board),
            "crop_box": list(crop_box),
            "rendered_mass_pixel_count": material_pixels,
            "rendered_mass_pixel_ratio": round(ratio, 5),
            "hard_pass": ratio >= 0.005,
            "evidence_role": "human_and_vlm_visual_observation_not_geometry_authority",
            "projected_visual_geometry_hash": projected_visual_hash,
            "final_legal_geometry_hash": final_legal_geometry_hash,
            "exact_mesh_payload_hash": exact_mesh_payload_hash,
        })
    return evidence


def _candidate_language_descriptor(candidate: _Candidate) -> dict[str, Any]:
    source = candidate.source
    poly = source.footprint
    aspect = _oriented_aspect(poly)
    compactness = 4.0 * pi * float(poly.area) / max(float(poly.length) ** 2, 1e-9)
    spatial = candidate.feature.get("properties", {}).get("program_spatial_evidence", {})
    section = source.metadata.get("program_section_graph_evidence") or {}
    materialized = section.get("materialized_nodes") if isinstance(section, dict) else ()
    controls = tuple(
        tuple(tuple(float(value) for value in item) for item in (node.get("section_controls") or ()))
        for node in (materialized or ())
        if isinstance(node, dict) and node.get("section_controls")
    )
    role_tokens = Counter()
    for volume in source.volumes:
        role = str(volume.role).lower()
        for token in (
            "hall", "service", "entry", "monitor", "canopy", "gallery",
            "public", "bridge", "ramp", "court", "street", "terrace", "ribbon",
        ):
            if token in role:
                role_tokens[token] += 1
    for zone in source.metadata.get("program_space_zones") or ():
        role = str(zone.get("role") or "").lower() if isinstance(zone, dict) else ""
        for token in (
            "hall", "service", "entry", "monitor", "canopy", "gallery",
            "public", "bridge", "ramp", "court", "street", "terrace", "ribbon",
        ):
            if token in role:
                role_tokens[token] += 1
    morphology = _solid_morphology_metrics(candidate)
    articulation = _architectural_articulation_metrics(source)
    design_concept = _design_concept_descriptor(candidate)
    program_form = candidate.feature.get("properties", {}).get("program_form_gate", {})
    capacity_alternative = source.metadata.get("capacity_alternative_projection") or {}
    capacity_measurement = source.metadata.get("source_capacity_measurement") or {}
    capacity_resolution = resolve_capacity_band_evidence(
        capacity_alternative,
        capacity_measurement=capacity_measurement,
    )
    return {
        "seed_family": _seed_family(candidate),
        "section_family": _section_family(candidate),
        "roof_archetype": _roof_archetype(candidate),
        "chassis_family": _chassis_family(candidate),
        "geometry_program_family": _geometry_program_family(candidate) or "none",
        "solid_phenotype": morphology["phenotype"],
        "body_phenotype": morphology.get("body_phenotype") or morphology["phenotype"],
        "section_phenotype": morphology.get("section_phenotype") or "none",
        "wedge_like": morphology["wedge_like"],
        "pyramidal_like": morphology["pyramidal_like"],
        "collapsed_profiled_tent_like": bool(morphology.get("collapsed_profiled_tent_like")),
        "degenerate_sheet_like": morphology["degenerate_sheet_like"],
        "horizontal_surface_ratio": morphology["horizontal_surface_ratio"],
        "vertical_surface_ratio": morphology["vertical_surface_ratio"],
        "sloped_surface_ratio": morphology["sloped_surface_ratio"],
        "normal_direction_bin_count": morphology["normal_direction_bin_count"],
        "horizontal_level_count": morphology["horizontal_level_count"],
        "plan_convexity": morphology["plan_convexity"],
        "upper_area_ratio": morphology["upper_area_ratio"],
        "solid_genus": morphology["genus"],
        "solid_component_count": morphology["component_count"],
        "book_scope": _scope_key(candidate),
        **capacity_resolution,
        "capacity_alternative_id": _capacity_alternative_key(candidate),
        "achieved_capacity_band": _capacity_alternative_key(candidate),
        "capacity_target_utilization": capacity_resolution[
            "resolved_capacity_target_utilization"
        ],
        "capacity_achieved_utilization": float(
            capacity_measurement.get("feasible_capacity_utilization") or 0.0
        ),
        "capacity_target_hard_pass": capacity_resolution[
            "resolved_capacity_hard_pass"
        ],
        "far_pct": float(capacity_measurement.get("far_pct") or 0.0),
        "oriented_plan_aspect_ratio": round(aspect, 4),
        "plan_compactness": round(compactness, 4),
        "plan_family": _plan_family(candidate),
        "dominant_component_ratio": round(float(spatial.get("dominant_component_ratio") or 0.0), 4),
        "site_coverage_ratio": round(float(spatial.get("site_coverage_ratio") or 0.0), 4),
        "hierarchy_score": round(float(spatial.get("hierarchy_score") or 0.0), 4),
        "section_control_signature": controls,
        "semantic_role_tokens": dict(sorted(role_tokens.items())),
        "body_rule_count": articulation["body_rule_count"],
        "program_body_rule_count": articulation["program_rule_count"],
        "public_threshold_rule_count": articulation["public_threshold_rule_count"],
        "book_body_rule_count": articulation["book_rule_count"],
        "body_rule_family_counts": articulation["family_counts"],
        "body_rules": articulation["rules"],
        "design_concept": design_concept,
        "design_concept_key": design_concept["concept_key"],
        "ground_strategy": design_concept["ground_strategy"],
        "frontage_aligned_public_threshold": design_concept["frontage_aligned"],
        "missing_required_design_concepts": design_concept["missing_required_concepts"],
        "measured_clear_span_m": float(program_form.get("measured_clear_span_m") or 0.0),
        "measured_solid_height_m": float(program_form.get("measured_solid_height_m") or 0.0),
        "height_to_clear_span_ratio": float(program_form.get("height_to_clear_span_ratio") or 0.0),
    }


def _portfolio_language_metrics(selected: list[_Candidate]) -> dict[str, Any]:
    descriptors = [_candidate_language_descriptor(candidate) for candidate in selected]
    seed_counts = Counter(item["seed_family"] for item in descriptors)
    section_counts = Counter(item["section_family"] for item in descriptors)
    roof_archetype_counts = Counter(item["roof_archetype"] for item in descriptors)
    chassis_counts = Counter(item["chassis_family"] for item in descriptors)
    geometry_program_counts = Counter(
        item["geometry_program_family"]
        for item in descriptors
        if item["geometry_program_family"] != "none"
    )
    phenotype_counts = Counter(item["solid_phenotype"] for item in descriptors)
    section_phenotype_counts = Counter(item["section_phenotype"] for item in descriptors)
    wedge_like_count = sum(bool(item["wedge_like"]) for item in descriptors)
    pyramidal_like_count = sum(bool(item["pyramidal_like"]) for item in descriptors)
    plan_counts = Counter(item["plan_family"] for item in descriptors)
    ground_strategy_counts = Counter(item["ground_strategy"] for item in descriptors)
    concept_key_counts = Counter(item["design_concept_key"] for item in descriptors)
    capacity_alternative_counts = Counter(
        item["capacity_alternative_id"] for item in descriptors
        if item["capacity_alternative_id"]
    )
    requested_capacity_alternative_counts = Counter(
        item["requested_capacity_alternative_id"]
        for item in descriptors
        if item["requested_capacity_alternative_id"]
    )
    control_signatures = {
        json.dumps(item["section_control_signature"], sort_keys=True)
        for item in descriptors
        if item["section_control_signature"]
    }

    def mean(name: str) -> float:
        values = [float(item[name]) for item in descriptors]
        return round(sum(values) / len(values), 4) if values else 0.0

    total = max(1, len(descriptors))
    return {
        "schema_version": "arr.maas.program_language_metrics.v1",
        "candidate_count": len(descriptors),
        "capacity_alternative_counts": dict(sorted(capacity_alternative_counts.items())),
        "capacity_alternative_count": len(capacity_alternative_counts),
        "achieved_capacity_band_counts": dict(
            sorted(capacity_alternative_counts.items())
        ),
        "requested_capacity_alternative_counts": dict(
            sorted(requested_capacity_alternative_counts.items())
        ),
        "capacity_target_pass_count": sum(
            bool(item["capacity_target_hard_pass"]) for item in descriptors
        ),
        "mean_capacity_target_utilization": mean("capacity_target_utilization"),
        "mean_capacity_achieved_utilization": mean("capacity_achieved_utilization"),
        "mean_far_pct": mean("far_pct"),
        "seed_family_counts": dict(sorted(seed_counts.items())),
        "seed_family_count": len(seed_counts),
        "dominant_seed_family_share": round(max(seed_counts.values(), default=0) / total, 4),
        "roof_section_family_counts": dict(sorted(section_counts.items())),
        "roof_section_family_count": len(section_counts),
        "dominant_roof_section_family_share": round(max(section_counts.values(), default=0) / total, 4),
        "roof_archetype_counts": dict(sorted(roof_archetype_counts.items())),
        "roof_archetype_count": len(roof_archetype_counts),
        "dominant_roof_archetype_share": round(max(roof_archetype_counts.values(), default=0) / total, 4),
        "chassis_family_counts": dict(sorted(chassis_counts.items())),
        "chassis_family_count": len(chassis_counts),
        "dominant_chassis_family_share": round(max(chassis_counts.values(), default=0) / total, 4),
        "recursive_geometry_program_counts": dict(sorted(geometry_program_counts.items())),
        "recursive_geometry_program_count": sum(geometry_program_counts.values()),
        "recursive_geometry_family_count": len(geometry_program_counts),
        "solid_phenotype_counts": dict(sorted(phenotype_counts.items())),
        "solid_phenotype_count": len(phenotype_counts),
        "dominant_solid_phenotype_share": round(max(phenotype_counts.values(), default=0) / total, 4),
        "section_phenotype_counts": dict(sorted(section_phenotype_counts.items())),
        "section_phenotype_count": len(section_phenotype_counts),
        "stepped_count": sum(
            item["solid_phenotype"] == "stepped"
            or item["section_phenotype"] == "stepped"
            for item in descriptors
        ),
        "upper_band_stepped_count": sum(
            (
                item["solid_phenotype"] == "stepped"
                or item["section_phenotype"] == "stepped"
            )
            and item["capacity_alternative_id"] in {
                "brief_target", "maximum_feasible",
            }
            for item in descriptors
        ),
        "collapsed_profiled_tent_like_count": sum(
            bool(item["collapsed_profiled_tent_like"]) for item in descriptors
        ),
        "wedge_like_count": wedge_like_count,
        "wedge_like_share": round(wedge_like_count / total, 4),
        "pyramidal_like_count": pyramidal_like_count,
        "pyramidal_like_share": round(pyramidal_like_count / total, 4),
        "mean_horizontal_surface_ratio": mean("horizontal_surface_ratio"),
        "mean_vertical_surface_ratio": mean("vertical_surface_ratio"),
        "mean_sloped_surface_ratio": mean("sloped_surface_ratio"),
        "section_control_signature_count": len(control_signatures),
        "plan_family_counts": dict(sorted(plan_counts.items())),
        "ground_strategy_counts": dict(sorted(ground_strategy_counts.items())),
        "ground_strategy_count": len(ground_strategy_counts),
        "frontage_aligned_public_threshold_count": sum(
            bool(item["frontage_aligned_public_threshold"]) for item in descriptors
        ),
        "design_concept_key_count": len(concept_key_counts),
        "maximum_design_concept_key_repeat": max(concept_key_counts.values(), default=0),
        "missing_required_design_concept_count": sum(
            len(item["missing_required_design_concepts"]) for item in descriptors
        ),
        "mean_oriented_plan_aspect_ratio": mean("oriented_plan_aspect_ratio"),
        "mean_plan_compactness": mean("plan_compactness"),
        "mean_dominant_component_ratio": mean("dominant_component_ratio"),
        "mean_site_coverage_ratio": mean("site_coverage_ratio"),
        "mean_hierarchy_score": mean("hierarchy_score"),
        "mean_volume_count": round(sum(len(candidate.source.volumes) for candidate in selected) / total, 4),
        "mean_effective_surface_count": round(
            sum(int(candidate.source.signature().get("effective_surface_count") or 0) for candidate in selected) / total,
            4,
        ),
        "mean_body_rule_count": mean("body_rule_count"),
        "maximum_body_rule_count": max((int(item["body_rule_count"]) for item in descriptors), default=0),
        "mean_public_threshold_rule_count": mean("public_threshold_rule_count"),
        "body_rule_family_counts": dict(sorted(sum((Counter(item["body_rule_family_counts"]) for item in descriptors), Counter()).items())),
        "semantic_role_token_counts": dict(sorted(sum((Counter(item["semantic_role_tokens"]) for item in descriptors), Counter()).items())),
    }


def _achieved_capacity_balance_pass(
    capacity_keys,
    *,
    target_count: int,
) -> bool:
    """Apply the same target-aware capacity contract as final selection."""

    keys = [str(value or "") for value in capacity_keys]
    contract = competition_portfolio_contract(target_count)
    counts = Counter(keys)
    if len(keys) != int(target_count):
        return False
    if contract.capacity_band_exact_counts:
        return bool(
            set(counts) == set(contract.capacity_band_exact_counts)
            and all(
                counts[band] == exact
                for band, exact in (
                    contract.capacity_band_exact_counts.items()
                )
            )
        )
    constrained_bands = (
        set(contract.capacity_band_minimum_counts)
        | set(contract.capacity_band_maximum_counts)
    )
    if not constrained_bands:
        return True
    return bool(
        set(counts) == constrained_bands
        and all(
            counts[band] >= minimum
            for band, minimum in (
                contract.capacity_band_minimum_counts.items()
            )
        )
        and all(
            counts[band] <= maximum
            for band, maximum in (
                contract.capacity_band_maximum_counts.items()
            )
        )
    )


def _portfolio_contract_morphology_failures(
    language_metrics: dict[str, Any],
    *,
    target_count: int,
    visual_directive: dict[str, Any] | None = None,
) -> list[str]:
    """Audit morphology with the same target contract as final selection."""

    contract = competition_portfolio_contract(target_count)
    failures: list[str] = []
    stepped_count = int(language_metrics.get("stepped_count") or 0)
    if stepped_count < contract.visible_stepped_minimum or (
        contract.visible_stepped_maximum is not None
        and stepped_count > contract.visible_stepped_maximum
    ):
        failures.append("stepped_count_outside_target_contract")
    if int(
        language_metrics.get("upper_band_stepped_count") or 0
    ) < contract.upper_band_stepped_minimum:
        failures.append(
            "upper_band_stepped_below_target_contract"
        )
    phenotype_cap = contract.body_phenotype_maximum_each
    directive = visual_directive or {}
    if "max_solid_phenotype_count" in directive:
        directive_cap = max(
            0,
            int(directive["max_solid_phenotype_count"]),
        )
        phenotype_cap = (
            directive_cap
            if phenotype_cap is None
            else min(phenotype_cap, directive_cap)
        )
    if (
        phenotype_cap is not None
        and max(
            (
                language_metrics.get("solid_phenotype_counts")
                or {}
            ).values(),
            default=0,
        )
        > phenotype_cap
    ):
        failures.append(
            "solid_phenotype_count_above_measured_cap"
        )
    return failures


def _order_portfolio_for_capacity_review(
    selected: list[_Candidate],
) -> list[_Candidate]:
    """Group the 5-column review board by yield band, then visual family."""
    capacity_rank = {
        "spatial_reserve": 0,
        "balanced_yield": 1,
        "brief_target": 2,
        "maximum_feasible": 3,
        "unclassified": 4,
    }
    return sorted(
        selected,
        key=lambda candidate: (
            capacity_rank.get(_capacity_alternative_key(candidate), 4),
            _solid_morphology_metrics(candidate)["phenotype"],
            _geometry_program_family(candidate),
            -float(candidate.score),
        ),
    )


def _cross_program_language_comparison(
    selected_by_program: dict[str, list[_Candidate]],
    metrics_by_program: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    slugs = tuple(selected_by_program)
    pairs: list[dict[str, Any]] = []
    for index, left_slug in enumerate(slugs):
        for right_slug in slugs[:index]:
            left = selected_by_program[left_slug]
            right = selected_by_program[right_slug]
            distances = [
                _silhouette_distance(left_candidate, right_candidate)
                for left_candidate in left
                for right_candidate in right
            ]
            left_sections = set(metrics_by_program[left_slug]["roof_section_family_counts"])
            right_sections = set(metrics_by_program[right_slug]["roof_section_family_counts"])
            union = left_sections | right_sections
            jaccard_distance = 1.0 - len(left_sections & right_sections) / max(1, len(union))
            pairs.append({
                "programs": [right_slug, left_slug],
                "mean_cross_program_silhouette_distance": round(sum(distances) / len(distances), 4) if distances else 0.0,
                "minimum_cross_program_silhouette_distance": round(min(distances), 4) if distances else 0.0,
                "roof_section_family_jaccard_distance": round(jaccard_distance, 4),
                "mean_plan_aspect_ratio_delta": round(abs(
                    metrics_by_program[left_slug]["mean_oriented_plan_aspect_ratio"]
                    - metrics_by_program[right_slug]["mean_oriented_plan_aspect_ratio"]
                ), 4),
                "mean_plan_compactness_delta": round(abs(
                    metrics_by_program[left_slug]["mean_plan_compactness"]
                    - metrics_by_program[right_slug]["mean_plan_compactness"]
                ), 4),
                "mean_dominant_ratio_delta": round(abs(
                    metrics_by_program[left_slug]["mean_dominant_component_ratio"]
                    - metrics_by_program[right_slug]["mean_dominant_component_ratio"]
                ), 4),
            })
    return {
        "schema_version": "arr.maas.cross_program_language_comparison.v1",
        "program_metrics": metrics_by_program,
        "pairwise_comparisons": pairs,
        "interpretation": "Measured geometry descriptors; visual review remains required.",
    }


def _hard_gate_count_summary(
    report: dict[str, Any] | None,
    candidates: list[_Candidate],
) -> dict[str, Any]:
    candidate_count = len(candidates)
    if report is None:
        return {"status": "not_run", "candidate_count": candidate_count}
    summary = {
        key: report[key]
        for key in (
            "candidate_count",
            "legal_hard_pass_count",
            "geometry_retention_pass_count",
            "parking_hard_pass_count",
            "capacity_hard_pass_count",
            "combined_hard_pass_count",
            "mean_volume_retention",
            "minimum_volume_retention",
            "legal_failure_reason_counts",
            "geometry_failure_reason_counts",
            "parking_failure_reason_counts",
            "capacity_failure_reason_counts",
            "semantic_failure_reason_counts",
        )
    }
    by_scope: dict[str, dict[str, int]] = {}
    by_host_mode: Counter[str] = Counter()
    hard_pass_by_host_mode: Counter[str] = Counter()
    by_geometry_family: dict[str, dict[str, Any]] = {}
    by_geometry_genotype: dict[str, dict[str, Any]] = {}
    for candidate, row in zip(candidates, report["rows"]):
        scope = str(row.get("book_scope") or "1/1")
        bucket = by_scope.setdefault(scope, {
            "candidate_count": 0,
            "legal_hard_pass_count": 0,
            "geometry_retention_pass_count": 0,
            "parking_hard_pass_count": 0,
            "capacity_hard_pass_count": 0,
            "combined_hard_pass_count": 0,
        })
        bucket["candidate_count"] += 1
        bucket["legal_hard_pass_count"] += int(bool(row["legal_projection"]["hard_pass"]))
        bucket["geometry_retention_pass_count"] += int(bool(row["legal_projection"]["geometry_retention_pass"]))
        bucket["parking_hard_pass_count"] += int(bool(row["parking_hard_gate"]["hard_pass"]))
        bucket["capacity_hard_pass_count"] += int(bool(
            row.get("capacity_hard_gate", {}).get("hard_pass")
        ))
        bucket["combined_hard_pass_count"] += int(bool(row["combined_hard_pass"]))
        host_mode = str(row.get("generation_host_mode") or "horizontal_buildable_envelope")
        by_host_mode[host_mode] += 1
        if row["combined_hard_pass"]:
            hard_pass_by_host_mode[host_mode] += 1
        geometry_family = _geometry_program_family(candidate)
        if geometry_family:
            empty_bucket = lambda: {
                "candidate_count": 0,
                "geometry_retention_pass_count": 0,
                "combined_hard_pass_count": 0,
                "volume_retentions": [],
                "failure_reason_counts": Counter(),
            }
            for bucket in (
                by_geometry_family.setdefault(geometry_family, empty_bucket()),
                by_geometry_genotype.setdefault(_seed_family(candidate), empty_bucket()),
            ):
                bucket["candidate_count"] += 1
                bucket["geometry_retention_pass_count"] += int(bool(row["legal_projection"]["geometry_retention_pass"]))
                bucket["combined_hard_pass_count"] += int(bool(row["combined_hard_pass"]))
                bucket["volume_retentions"].append(float(row["legal_projection"].get("volume_retention") or 0.0))
                bucket["failure_reason_counts"].update(row["legal_projection"].get("geometry_failure_reasons") or ())
    summary["by_scope"] = dict(sorted(by_scope.items()))
    summary["candidate_count_by_generation_host"] = dict(sorted(by_host_mode.items()))
    summary["combined_hard_pass_by_generation_host"] = dict(sorted(hard_pass_by_host_mode.items()))
    def serialize_geometry_buckets(buckets: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return {
        family: {
            "candidate_count": bucket["candidate_count"],
            "geometry_retention_pass_count": bucket["geometry_retention_pass_count"],
            "combined_hard_pass_count": bucket["combined_hard_pass_count"],
            "mean_volume_retention": round(sum(bucket["volume_retentions"]) / len(bucket["volume_retentions"]), 4),
            "minimum_volume_retention": round(min(bucket["volume_retentions"]), 4),
            "failure_reason_counts": dict(sorted(bucket["failure_reason_counts"].items())),
        }
        for family, bucket in sorted(buckets.items())
        }

    summary["by_recursive_geometry_family"] = serialize_geometry_buckets(by_geometry_family)
    summary["by_recursive_geometry_genotype"] = serialize_geometry_buckets(by_geometry_genotype)
    summary["semantic_binding_diagnostics"] = [
        {
            "candidate": str(
                candidate.feature.get("properties", {}).get("variant_id")
                or candidate.sequence.name
            ),
            "bound_achieved_capacity_band": str(
                (
                    candidate.source.metadata.get(
                        "program_semantic_carrier_evidence"
                    )
                    or {}
                ).get("achieved_capacity_band")
                or ""
            ),
            "audited_achieved_capacity_band": str(
                (
                    row.get("semantic_projection_hard_gate", {}).get(
                        "audited_context"
                    )
                    or {}
                ).get("achieved_capacity_band")
                or ""
            ),
            "failures": list(
                row.get("semantic_projection_hard_gate", {}).get("failures")
                or ()
            ),
        }
        for candidate, row in zip(candidates, report["rows"])
        if row.get("semantic_projection_hard_gate", {}).get("hard_pass")
        is not True
    ]
    return summary


def _final_vlm_input_from_downstream(
    candidates: list[_Candidate],
    downstream_report: dict[str, Any],
) -> list[_Candidate]:
    """Route statutory-law/parking-valid descendants to final small VLM."""

    rows = list((downstream_report or {}).get("rows") or ())
    final_vlm_input: list[_Candidate] = []
    combined_hard_pass_count = 0
    base_only_count = 0
    non_book_count = 0
    exclusion_reason_counts: dict[str, int] = {}
    for candidate, row in zip(candidates, rows):
        if not isinstance(row, dict) or row.get("combined_hard_pass") is not True:
            continue
        combined_hard_pass_count += 1
        classification = classify_applied_book_candidate(candidate)
        if not classification.eligible:
            reason = classification.reason.value
            exclusion_reason_counts[reason] = (
                exclusion_reason_counts.get(reason, 0) + 1
            )
            if classification.reason is AppliedBookCandidateReason.RAW_BASE:
                base_only_count += 1
            else:
                non_book_count += 1
            continue
        _bind_final_visual_authority_for_review(
            candidate,
            row.get("semantic_projection_hard_gate") or {},
        )
        final_vlm_input.append(candidate)
    if isinstance(downstream_report, dict):
        downstream_report["final_vlm_routing"] = {
            "schema_version": "arr.maas.final_vlm_applied_book_routing.v2",
            "input_count": len(candidates),
            "row_count": len(rows),
            "combined_hard_pass_count": combined_hard_pass_count,
            "routed_applied_book_candidate_count": len(final_vlm_input),
            "raw_base_excluded_count": base_only_count,
            "typed_contract_excluded_count": sum(
                exclusion_reason_counts.values()
            ),
            "exclusion_reason_counts": dict(sorted(
                exclusion_reason_counts.items()
            )),
            # Deprecated v1 aliases retained for artifact consumers.
            "base_only_excluded_count": base_only_count,
            "non_book_excluded_count": non_book_count,
            "routed_book_descendant_count": len(final_vlm_input),
            "exact_archived_surface_bound_count": len(final_vlm_input),
            "no_call_reason": (
                "" if final_vlm_input
                else "no_law_parking_structural_valid_applied_book_candidates"
            ),
        }
    return final_vlm_input


def _legal_mass_archive_portfolio_summary(
    program_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Collect bounded generation archives independently of final selection."""

    legal_mass_archives = {
        str(item["slug"]): deepcopy(
            (item.get("counts") or {}).get("legal_mass_archive") or {}
        )
        for item in program_results
    }
    return {
        "schema_version": "arr.maas.legal_mass_archive_portfolio.v1",
        "selection_effect": "none_archive_only",
        "program_count": len(legal_mass_archives),
        "record_count": sum(
            int(archive.get("record_count") or 0)
            for archive in legal_mass_archives.values()
        ),
        "programs": legal_mass_archives,
    }


def attach_legal_mass_archive_boards(
    result: dict[str, Any],
    *,
    output_dir: Path,
) -> dict[str, Any]:
    """Attach rendered archive evidence without changing selection results."""

    archive_summary = result.get("legal_mass_archive")
    if not isinstance(archive_summary, dict):
        return result
    program_results = {
        str(item.get("slug") or ""): item
        for item in result.get("programs") or ()
        if isinstance(item, dict)
    }
    boards: dict[str, Any] = {}
    for slug, archive in (archive_summary.get("programs") or {}).items():
        if not isinstance(archive, dict):
            continue
        records = archive.get("records")
        if not isinstance(records, list) or not records:
            continue
        program = program_results.get(str(slug)) or {}
        requirement = program.get("portfolio_requirement") if isinstance(program.get("portfolio_requirement"), dict) else {}
        boards[str(slug)] = render_legal_mass_archive_board(
            output_dir=output_dir,
            program_slug=str(slug),
            target_count=int(requirement.get("target_count") or program.get("selection_target") or 0),
            selected_count=int(program.get("selected_count") or 0),
            archive_records=records,
        )
    archive_summary["boards"] = boards
    return result


def run_book_program_portfolios(
    site: Polygon,
    *,
    pnu: str,
    output_dir: Path,
    site_origin_utm: tuple[float, float] = (0.0, 0.0),
    constraints: list[dict[str, Any]] | None = None,
    regulation_evidence: dict[str, Any] | None = None,
    sunlight_envelope: dict[str, Any] | None = None,
    parking_options: dict[str, Any] | None = None,
    program_slugs: tuple[str, ...] | None = None,
    recursive_only: bool = False,
    visual_directive_path: Path | None = None,
    outcome_graph_path: Path | None = None,
    site_boundary_source: str = "",
    site_access_context: dict[str, Any] | None = None,
    site_access_geometry: dict[str, Any] | None = None,
    live_geometry_vlm_revision: bool = False,
    live_llm_author: bool = False,
    agent_authored_manifest_path: Path | None = None,
    agent_authored_admission: AgentAuthoredAdmission | None = None,
    agent_authored_replay_program_hashes: tuple[str, ...] = (),
    smoke_mode: bool = False,
    diagnostic_target: int | None = None,
    progressive_target: int | None = None,
) -> dict[str, Any]:
    portfolio_started_at = perf_counter()
    if (
        agent_authored_manifest_path is not None
        and not isinstance(agent_authored_admission, AgentAuthoredAdmission)
    ):
        raise AgentAuthoredSupplyError(
            "trusted admission contract is required for agent-authored manifest"
        )
    validated_agent_authored_programs = (
        load_agent_authored_geometry_programs(
            agent_authored_manifest_path,
            admission=agent_authored_admission,
        )
        if agent_authored_manifest_path is not None
        else ()
    )
    agent_authored_programs = filter_agent_authored_replay_programs(
        validated_agent_authored_programs,
        agent_authored_replay_program_hashes,
    )
    agent_authored_manifest_active = bool(agent_authored_programs)
    llm_authorship_required = bool(
        live_llm_author or agent_authored_manifest_active
    )
    agent_authored_manifest_evidence = (
        {
            "schema_version": (
                "arr.maas.codex_oauth_geometry_supply_evidence.v1"
            ),
            "provider": CODEX_OAUTH_AUTHOR_PROVIDER,
            "authoring_session_id": str(
                agent_authored_programs[0].metadata.get(
                    "authoring_session_id"
                )
                or ""
            ),
            "request_id": str(
                agent_authored_programs[0].metadata.get("author_request_id")
                or ""
            ),
            "manifest_sha256": str(
                agent_authored_programs[0].metadata.get(
                    "author_manifest_sha256"
                )
                or ""
            ),
            "validated_program_count": len(agent_authored_programs),
            "validated_manifest_program_count": len(
                validated_agent_authored_programs
            ),
            "replay_subset_active": bool(agent_authored_replay_program_hashes),
            "program_hashes": [
                program.program_hash()
                for program in agent_authored_programs
            ],
            "paid_author_fallback_allowed": False,
            "deterministic_author_fallback_allowed": False,
        }
        if agent_authored_manifest_active
        else {}
    )
    if diagnostic_target is not None and int(diagnostic_target) not in DIAGNOSTIC_TARGET_OPTIONS:
        raise ValueError("diagnostic_target must be one of 1, 2, 3, 5, or 20")
    diagnostic_target_int = int(diagnostic_target) if diagnostic_target is not None else None
    if progressive_target is not None and int(progressive_target) not in (3, 5, 10, 20):
        raise ValueError("progressive_target must be one of 3, 5, 10, or 20")
    progressive_target_int = (
        int(progressive_target) if progressive_target is not None else None
    )
    if progressive_target_int is not None and diagnostic_target_int is not None:
        raise ValueError("progressive_target and diagnostic_target are mutually exclusive")
    if diagnostic_target_int is not None:
        os.environ.setdefault("MAAS_ALLOW_TINY_GEOMETRY_GATES", "1")
    output_dir.mkdir(parents=True, exist_ok=True)
    directive_dir = visual_directive_path.parent if visual_directive_path is not None else output_dir
    visual_directive_payload = _load_visual_directive(directive_dir, pnu)
    outcome_graph_path_was_explicit = outcome_graph_path is not None
    outcome_graph_snapshot_path = output_dir / "maas-geometry-mutation-outcome-graph.json"
    outcome_graph_path = outcome_graph_path or default_outcome_graph_path(output_dir)
    outcome_graph = GeometryOutcomeGraph.load(outcome_graph_path, pnu=pnu)
    program_results: list[dict[str, Any]] = []
    selected_by_program: dict[str, list[_Candidate]] = {}
    metrics_by_program: dict[str, dict[str, Any]] = {}
    board_paths: list[Path] = []
    mass_brain_trace_sequences: list[VerbSequence] = []
    mass_brain_trace_features: dict[str, dict[str, Any]] = {}
    phase_durations_seconds = {
        phase: 0.0
        for phase in (
            "breadth_enumeration",
            "cheap_screen",
            "exact_compile",
            "law",
            "parking",
            "solver",
            "render",
        )
    }

    def record_downstream_timings(report: dict[str, Any] | None) -> None:
        for row in (report or {}).get("rows") or ():
            timings = (
                row.get("phase_durations_seconds")
                if isinstance(row, dict)
                and isinstance(
                    row.get("phase_durations_seconds"),
                    dict,
                )
                else {}
            )
            for phase in ("law", "parking"):
                phase_durations_seconds[phase] += float(
                    timings.get(phase) or 0.0
                )
    portfolio_requirement = (
        resolve_progressive_portfolio_requirement(
            target_count=progressive_target_int,
            base_volume_scope_count=len(BASE_VOLUME_FRACTIONS),
        )
        if progressive_target_int is not None
        else resolve_portfolio_requirement(
            smoke_mode=smoke_mode,
            base_volume_scope_count=len(BASE_VOLUME_FRACTIONS),
        )
    )
    selection_target = (
        diagnostic_target_int
        if diagnostic_target is not None
        else portfolio_requirement.selection_target
    )
    required_scope_target = (
        min(portfolio_requirement.required_scope_count, selection_target)
        if diagnostic_target is not None
        else portfolio_requirement.required_scope_count
    )
    requested_slugs = set(program_slugs or ())
    invocation_author_rate_limit_cooldown = (
        _AuthorRateLimitCooldownState()
    )
    for slug, building_type, catalog_height, catalog_floors in PROGRAMS:
        if requested_slugs and slug not in requested_slugs:
            continue
        started = perf_counter()
        update_run_progress(
            output_dir,
            phase="candidate_generation",
            program=slug,
            selected_mass_count=0,
            required_scope_count=required_scope_target,
            selected_scope_count=0,
        )
        outcome_graph.begin_program_run(slug)
        memory_visual_directive = outcome_graph.latest_portfolio_directive(slug)
        program_visual_directive = dict(
            (visual_directive_payload.get("programs") or {}).get(slug) or {}
        )
        # Plan topology is measured from the final footprint. Requesting a
        # triangular member has no effect when no valid triangular candidate
        # survives; when one does survive, the portfolio must not silently
        # discard the entire non-orthogonal plan language.
        program_visual_directive.setdefault("required_plan_families", ["triangular"])
        remembered_families = list(
            memory_visual_directive.get("required_geometry_program_families") or ()
        )
        if remembered_families:
            program_visual_directive["required_geometry_program_families"] = list(dict.fromkeys((
                *remembered_families,
                *(program_visual_directive.get("required_geometry_program_families") or ()),
            )))
        remembered_chassis = list(
            memory_visual_directive.get("required_chassis_families") or ()
        )
        if remembered_chassis:
            program_visual_directive["required_chassis_families"] = list(dict.fromkeys((
                *remembered_chassis,
                *(program_visual_directive.get("required_chassis_families") or ()),
            )))
        program_visual_directive["portfolio_memory_directive"] = memory_visual_directive
        remembered_family_caps = dict(
            memory_visual_directive.get("max_geometry_family_counts") or {}
        )
        if remembered_family_caps:
            program_visual_directive["max_geometry_family_counts"] = {
                **remembered_family_caps,
                **dict(program_visual_directive.get("max_geometry_family_counts") or {}),
            }
        remembered_chassis_caps = dict(
            memory_visual_directive.get("max_chassis_family_counts") or {}
        )
        if remembered_chassis_caps:
            program_visual_directive["max_chassis_family_counts"] = {
                **remembered_chassis_caps,
                **dict(program_visual_directive.get("max_chassis_family_counts") or {}),
            }
        remembered_chassis_cap = int(
            memory_visual_directive.get("max_chassis_family_count") or 0
        )
        if remembered_chassis_cap and not remembered_chassis_caps and not program_visual_directive.get(
            "max_chassis_family_count"
        ):
            program_visual_directive["max_chassis_family_count"] = remembered_chassis_cap
        runtime_live_vlm = bool(
            live_geometry_vlm_revision
            or program_visual_directive.get("live_geometry_vlm_revision")
        )
        typed_graph_mutations = program_visual_directive.get("typed_graph_mutations") or []
        geometry_program_mutations = program_visual_directive.get("geometry_program_mutations") or []
        synthesis_requests = program_visual_directive.get("geometry_synthesis_requests") or []
        if live_llm_author and not agent_authored_manifest_active:
            synthesis_requests = list(bounded_live_llm_synthesis_requests(
                building_type,
                source_seed_names=(
                    sequence.name
                    for sequence in program_seed_sequences(building_type)
                ),
                target_count=selection_target,
                prior_requests=synthesis_requests,
            ))
            program_visual_directive[
                "required_architectural_strategies"
            ] = list(REQUIRED_ARCHITECTURAL_STRATEGIES)
            program_visual_directive[
                "authorship_completion_policy"
            ] = "all_selected_llm_authored"
        elif agent_authored_manifest_active:
            synthesis_requests = []
            program_visual_directive.update({
                "authorship_completion_policy": (
                    "all_selected_codex_oauth_llm_authored"
                ),
                "author_provider": CODEX_OAUTH_AUTHOR_PROVIDER,
                "agent_authored_manifest": deepcopy(
                    agent_authored_manifest_evidence
                ),
            })
        if synthesis_requests:
            live_requested = runtime_live_vlm
            reference_matches = [
                {
                    "local_path": str(path),
                    "title": Path(str(path)).stem,
                    "selection_role": "operation_language_reference_not_shape_template",
                    "source": "portfolio_vlm_directive",
                }
                for path in visual_directive_payload.get("reference_images") or ()
            ]
            synthesis_requests = [
                {
                    **dict(request),
                    "live_vlm_revision": bool(request.get("live_vlm_revision", live_requested)),
                    "reference_matches": reference_matches,
                    "required_body_phenotypes": list(
                        program_visual_directive.get("required_solid_phenotypes") or ()
                    ),
                }
                for request in synthesis_requests
                if isinstance(request, dict)
            ]
        # The universal recursive form bank is the default dominant-form
        # authority.  Legacy program sequences are role/context carriers, not
        # selectable finished geometry.  Previously this flag became false
        # without an explicit session mutation even though _program_pool still
        # injected the universal bank; legacy candidates could then enter the
        # exact-AST VLM shortlist with no geometry_program nodes at all.
        geometry_program_authority = True
        generation_context = (
            build_legal_generation_context(
                site_local_utm=site,
                site_origin_utm=site_origin_utm,
                building_type=building_type,
                constraints=constraints,
                sunlight_envelope=sunlight_envelope,
            )
            if constraints is not None
            else None
        )
        generation_site = generation_context.generation_site if generation_context is not None else site
        dimensional_context = _program_dimensional_context(
            generation_site,
            building_type,
            catalog_height,
            catalog_floors,
        )
        capacity_policy = resolve_massing_capacity_policy(
            building_type=building_type,
            site_area_m2=float(site.area),
            parking_options=parking_options,
        )
        height, floors, floor_capacity_plan = _resolve_authoritative_floor_context(
            pnu=pnu,
            generation_context=generation_context,
            site_local_utm=site,
            building_type=building_type,
            catalog_height_m=catalog_height,
            catalog_floors=catalog_floors,
            dimensional_context=dimensional_context,
            target_utilization=float(capacity_policy["target_far_utilization"]),
        )
        trusted_run_legal_floor_field: dict[str, Any] | None = None
        trusted_run_legal_floor_field_hash = ""
        trusted_run_clear_span_floor_plan: dict[str, Any] | None = None
        if (
            isinstance(floor_capacity_plan, dict)
            and floor_capacity_plan.get("status")
            in {"materialized", "target_unreachable"}
        ):
            authoritative_field = floor_capacity_plan.get(
                "legal_floor_field"
            )
            authoritative_hash = str(
                floor_capacity_plan.get("legal_floor_field_hash") or ""
            )
            if (
                not validate_legal_floor_field(authoritative_field)
                or not authoritative_hash
                or str(
                    authoritative_field.get(
                        "legal_floor_field_hash"
                    )
                    or ""
                )
                != authoritative_hash
            ):
                raise ValueError(
                    "authoritative_run_legal_floor_field_invalid"
                )
            # This run-local copy is captured before the mutable base and
            # candidate contracts exist.  Downstream trust checks never
            # derive their expected identity from the object under review.
            trusted_run_legal_floor_field = deepcopy(
                authoritative_field
            )
            trusted_run_legal_floor_field_hash = authoritative_hash
            if floor_capacity_plan.get("planning_mode") == "clear_span":
                trusted_run_clear_span_floor_plan = deepcopy(
                    floor_capacity_plan
                )
        plan_infeasible = bool(
            floor_capacity_plan
            and floor_capacity_plan.get("status") == "infeasible"
        )
        pre_generation_capacity_advisory = {
            "schema_version": "arr.maas.pre_generation_capacity_advisory.v1",
            "authority": "diagnostic_only",
            "generation_continued": (
                dimensional_context["status"] != "infeasible"
            ),
            "dimensional_context_infeasible": (
                dimensional_context["status"] == "infeasible"
            ),
            "floor_capacity_plan_infeasible": plan_infeasible,
            "failure_reasons": list(dict.fromkeys((
                *(dimensional_context.get("failure_reasons") or ()),
                *((floor_capacity_plan or {}).get("failure_reasons") or ()),
            ))),
        }
        dimensional_context = {
            **dimensional_context,
            "catalog_height_hint_m": float(catalog_height),
            "catalog_floor_hint": int(catalog_floors),
            "effective_height_m": float(
                dimensional_context.get("effective_height_m", height)
                if dimensional_context["status"] == "infeasible"
                else height
            ),
            "effective_floors": int(
                dimensional_context.get("effective_floors", floors)
                if dimensional_context["status"] == "infeasible"
                else floors
            ),
            "pre_generation_capacity_advisory": (
                pre_generation_capacity_advisory
            ),
            "floor_capacity_plan_hash": str(
                floor_capacity_plan.get("floor_capacity_plan_hash") or ""
            ),
            "floor_authority": (
                "law_derived_floor_capacity_plan"
                if floor_capacity_plan
                else "legacy_no_legal_context"
            ),
        }
        program_agent_authored_programs = (
            filter_agent_authored_replay_programs(
                load_agent_authored_geometry_programs(
                    agent_authored_manifest_path,
                    admission=agent_authored_admission,
                    author_context={
                        "program_context": {
                            **program_reference_contract(building_type),
                            "program_dimensional_context": dict(
                                dimensional_context
                            ),
                            "site_boundary_source": site_boundary_source,
                            "site_access_context": dict(
                                site_access_context or {}
                            ),
                            "site_access_side_in_program_frame": (
                                _site_access_side_in_principal_frame(
                                    generation_site,
                                    site_access_geometry,
                                )
                            ),
                        },
                        "maximum_operator_depth": 2,
                        "downstream_body_rule_reserve": 0,
                    },
                ),
                agent_authored_replay_program_hashes,
            )
            if agent_authored_manifest_active
            else ()
        )
        if dimensional_context["status"] == "infeasible":
            empty_metrics = _portfolio_language_metrics([])
            board = output_dir / (
                f"maas-book-{slug}-{selection_target}-smoke.png"
                if smoke_mode
                else f"maas-book-{slug}-{selection_target}.png"
            )
            render_archive_sheet(
                [],
                board,
                title=f"MAAS BOOK × {building_type} · PNU {pnu} · PROGRAM INFEASIBLE",
            )
            board_paths.append(board)
            selected_by_program[slug] = []
            metrics_by_program[slug] = empty_metrics
            portfolio_vlm_audit = {
                "schema_version": "arr.maas.portfolio_visual_audit.v1",
                "status": "not_run_program_site_infeasible",
                "hard_pass": False,
                "evaluated": False,
                "candidate_count": 0,
                "legal_or_parking_score": False,
            }
            portfolio_completion = evaluate_portfolio_completion(
                portfolio_requirement,
                selected_count=0,
                selected_scope_count=0,
                runtime_live_vlm=runtime_live_vlm,
                exact_vlm_hard_pass_count=0,
                require_llm_authored_ast=llm_authorship_required,
                llm_authored_selected_count=0,
                portfolio_vlm_audit=portfolio_vlm_audit,
            )
            portfolio_completion = _bind_trusted_codex_completion(
                portfolio_completion,
                manifest_required=agent_authored_manifest_active,
                selected_count=0,
                trusted_codex_selected_count=0,
            )
            early_stop_evidence = {
                "schema_version": "arr.maas.program_site_early_stop.v1",
                "status": "program_site_infeasible",
                "generation_attempted": False,
                "evaluated_count": 0,
                "compiled_count": 0,
                "clean_count": 0,
                "program_passed_count": 0,
                "dimensional_evidence": deepcopy(dimensional_context),
                "floor_capacity_plan_evidence": deepcopy(
                    floor_capacity_plan
                ),
            }
            downstream_hard_gate = {
                "schema_version": "arr.maas.book_downstream_hard_gate.v1",
                "status": "fail",
                "same_accepted_source": True,
                "candidate_count": 0,
                "legal_hard_pass_count": 0,
                "geometry_retention_pass_count": 0,
                "parking_hard_pass_count": 0,
                "combined_hard_pass_count": 0,
                "mean_volume_retention": 0.0,
                "minimum_volume_retention": 0.0,
                "legal_failure_reason_counts": {},
                "geometry_failure_reason_counts": {},
                "parking_failure_reason_counts": {},
                "program_failure_reason_counts": {
                    "program_site_infeasible": 1,
                },
                "failure_reasons": ["program_site_infeasible"],
                "program_dimensional_context": deepcopy(
                    dimensional_context
                ),
                "rows": [],
            }
            failures = [
                "program_site_infeasible",
                *(
                    str(value)
                    for value in dimensional_context.get(
                        "failure_reasons"
                    )
                    or ()
                ),
                f"selected_count_below_target_{selection_target}",
            ]
            if smoke_mode:
                failures.append("smoke_portfolio_target_not_met")
            failures.extend(
                failure
                for failure in portfolio_completion["failures"]
                if failure not in failures
            )
            counts = {
                "evaluated": 0,
                "compiled": 0,
                "clean": 0,
                "program_passed": 0,
                "program_dimensional_context": deepcopy(
                    dimensional_context
                ),
                "floor_capacity_plan": deepcopy(floor_capacity_plan),
                "capacity_policy": deepcopy(capacity_policy),
                "early_stop": early_stop_evidence,
                "preselection_hard_gate": {
                    "candidate_count": 0,
                    "legal_hard_pass_count": 0,
                    "geometry_retention_pass_count": 0,
                    "parking_hard_pass_count": 0,
                    "combined_hard_pass_count": 0,
                },
                "selection_trace": {
                    "raw_pool_count": 0,
                    "unique_candidate_count": 0,
                    "post_rebalance_count": 0,
                },
            }
            update_run_progress(
                output_dir,
                phase="program_site_infeasible",
                program=slug,
                selected_mass_count=0,
                required_scope_count=required_scope_target,
                selected_scope_count=0,
                generation_status="program_site_infeasible",
                evaluated_count=0,
                compiled_count=0,
                program_passed_count=0,
            )
            program_results.append({
                "program": building_type,
                "slug": slug,
                "status": "program_site_infeasible",
                "generation_status": "program_site_infeasible",
                "selected_count": 0,
                "portfolio_requirement": (
                    portfolio_requirement.to_evidence()
                ),
                "portfolio_completion": portfolio_completion,
                "book_operation_count": 0,
                "book_principle_kind_counts": {
                    "base_operative": 0,
                    "combination": 0,
                    "aggregation": 0,
                    "case_study": 0,
                },
                "visual_language_count": 0,
                "book_base_volume_scope_count": 0,
                "book_base_volume_scopes": [],
                "capacity_alternative_count": 0,
                "capacity_alternatives": [],
                "near_duplicate_pair_count": 0,
                "portfolio_vlm_audit": portfolio_vlm_audit,
                "archive_render_evidence": {
                    "card_count": 0,
                    "visible_mass_card_count": 0,
                    "minimum_rendered_mass_pixel_ratio": 0.0,
                    "direct_png_review_required": True,
                },
                "program_language_metrics": empty_metrics,
                "program_dimensional_context": dimensional_context,
                "floor_capacity_plan": deepcopy(floor_capacity_plan),
                "vlm_portfolio_directive": {
                    "active": bool(runtime_live_vlm or program_visual_directive),
                    "runtime_live_vlm_requested": runtime_live_vlm,
                },
                "downstream_hard_gate": downstream_hard_gate,
                "counts": counts,
                "failures": failures,
                "missing_vlm_required_roof_archetypes": [],
                "missing_required_solid_phenotypes": [],
                "duration_seconds": round(perf_counter() - started, 3),
                "smoke_mode": bool(smoke_mode),
                "rows": [],
                "png": str(board),
            })
            continue
        if (
            dimensional_context["status"] == "infeasible"
            or plan_infeasible
            or height <= 0.0
            or floors <= 0
        ):
            height = float(
                dimensional_context.get("effective_height_m")
                or catalog_height
            )
            floors = int(
                dimensional_context.get("effective_floors")
                or catalog_floors
            )
        dimensional_context = {
            **dimensional_context,
            "catalog_height_hint_m": float(catalog_height),
            "catalog_floor_hint": int(catalog_floors),
            "effective_height_m": float(height),
            "effective_floors": int(floors),
            "pre_generation_capacity_advisory": (
                pre_generation_capacity_advisory
            ),
            "floor_capacity_plan_hash": str(
                floor_capacity_plan.get("floor_capacity_plan_hash") or ""
            ),
            "floor_authority": (
                "law_derived_floor_capacity_plan"
                if floor_capacity_plan
                else "legacy_no_legal_context"
            ),
        }
        base_capacity_contract = (
            build_feasible_capacity_contract(
                generation_context,
                site_local_utm=site,
                height_m=height,
                floors=floors,
                target_utilization=float(capacity_policy["target_far_utilization"]),
                minimum_utilization=float(capacity_policy["min_far_utilization"]),
                floor_capacity_plan=floor_capacity_plan,
            )
            if generation_context is not None
            else None
        )
        diagnostic_budget = diagnostic_generation_budget(
            diagnostic_target
        )
        if diagnostic_budget is not None:
            persist_diagnostic_generation_progress(
                output_dir,
                program=slug,
                target=int(diagnostic_target),
                counters={
                    "evaluated_count": 0,
                    "compiled_count": 0,
                    "program_passed_count": 0,
                },
            )
        agent_authored_seed_kwargs = (
            {
                "_directed_seeds_override": (
                    build_agent_authored_program_seeds(
                        program_agent_authored_programs,
                        building_type=building_type,
                        admission=agent_authored_admission,
                    )
                )
            }
            if agent_authored_manifest_active
            else {}
        )
        pool, counts, invocation_author_rate_limit_cooldown = (
            _run_initial_generation_with_author_cooldown(
            _program_pool,
            generation_site,
            building_type,
            height,
            floors,
            cooldown_state=invocation_author_rate_limit_cooldown,
            generation_context=generation_context,
            typed_graph_mutations=typed_graph_mutations,
            geometry_program_mutations=geometry_program_mutations,
            synthesis_requests=synthesis_requests,
            outcome_graph=outcome_graph,
            recursive_only=geometry_program_authority,
            target_count=selection_target,
            exact_compile_limit=(
                progressive_mass_run_budget(
                    progressive_target_int
                ).initial_compile_limit
                if progressive_target_int is not None
                else None
            ),
            program_dimensional_context=dimensional_context,
            site_boundary_source=site_boundary_source,
            site_access_context=site_access_context,
            site_access_geometry=site_access_geometry,
            live_geometry_vlm_revision=runtime_live_vlm,
            base_capacity_contract=base_capacity_contract,
            trusted_legal_floor_field=(
                trusted_run_legal_floor_field
            ),
            trusted_legal_floor_field_hash=(
                trusted_run_legal_floor_field_hash
            ),
            trusted_clear_span_floor_plan=(
                trusted_run_clear_span_floor_plan
            ),
            capacity_site=site,
            pnu=pnu,
            parent_variant_indices=(
                diagnostic_budget["parent_variant_indices"]
                if diagnostic_budget is not None
                else (0,)
            ),
            diagnostic_scope_labels=(
                diagnostic_budget["scope_labels"]
                if diagnostic_budget is not None
                else ()
            ),
            diagnostic_book_probe_count=(
                diagnostic_budget["book_probe_count"]
                if diagnostic_budget is not None
                else None
            ),
            diagnostic_evaluation_cap=(
                diagnostic_budget["evaluation_cap"]
                if diagnostic_budget is not None
                else None
            ),
            diagnostic_candidate_cap=(
                diagnostic_budget["candidate_cap"]
                if diagnostic_budget is not None
                else None
            ),
            progress_callback=(
                lambda counters: persist_diagnostic_generation_progress(
                    output_dir,
                    program=slug,
                    target=int(diagnostic_target),
                    counters=counters,
                )
                if diagnostic_budget is not None
                else None
            ),
            stop_after_shared_floor_hard_passes=(
                _smoke_floor_pass_reserve(
                    selection_target,
                    live_vlm=runtime_live_vlm,
                )
                if smoke_mode or progressive_target_int is not None
                else None
            ),
            base_review_callback=optional_book_base_review_callback(
                runtime_live_vlm
                and not smoke_mode
                and not agent_authored_manifest_active,
                lambda base_pool: audit_book_base_stage_with_vlm(
                    base_pool,
                    building_type=building_type,
                    output_dir=output_dir / slug / "book-base-stage",
                    visual_directive=program_visual_directive,
                    outcome_graph=outcome_graph,
                    program_slug=slug,
                    target_count=selection_target,
                ),
            ),
            **agent_authored_seed_kwargs,
            )
        )
        initial_certified_reviewed_base_parents = tuple(
            counts.pop(
                "_runtime_certified_reviewed_base_parents",
                (),
            ) or ()
        )
        generation_timings = (
            counts.get("phase_durations_seconds")
            if isinstance(counts.get("phase_durations_seconds"), dict)
            else {}
        )
        for phase in (
            "breadth_enumeration",
            "cheap_screen",
            "exact_compile",
        ):
            phase_durations_seconds[phase] += float(
                generation_timings.get(phase) or 0.0
            )
        counts["program_dimensional_context"] = deepcopy(dimensional_context)
        counts["floor_capacity_plan"] = deepcopy(floor_capacity_plan)
        counts["capacity_policy"] = deepcopy(capacity_policy)
        counts["base_capacity_contract"] = deepcopy(base_capacity_contract or {})
        if agent_authored_manifest_active:
            counts["agent_authored_manifest_supply"] = deepcopy(
                agent_authored_manifest_evidence
            )
        pre_floor_contract_count = len(pool)
        pool = _shared_floor_hard_pass_candidates(pool)
        shared_floor_hard_pass_count = sum(
            1
            for candidate in pool
            if (
                isinstance(
                    candidate.source.metadata.get("shared_floor_contract"),
                    dict,
                )
                and candidate.source.metadata["shared_floor_contract"].get(
                    "schema_version"
                )
                == "arr.maas.shared_floor_contract.v1"
                and candidate.source.metadata["shared_floor_contract"].get(
                    "hard_pass"
                )
                is True
            )
        )
        counts["shared_floor_contract"] = {
            "evaluated_count": pre_floor_contract_count,
            "hard_pass_count": shared_floor_hard_pass_count,
            "advisory_miss_count": (
                pre_floor_contract_count - shared_floor_hard_pass_count
            ),
            "rejected_before_paid_vlm_count": 0,
            "authority": "diagnostic_only",
        }
        # The base is a causal visual parent, not necessarily a final legal or
        # parking solution. Review that parent after program/clean gates, then
        # release its exact descendants and apply downstream hard gates to
        # each released candidate. Reversing this order deleted a legal,
        # parking-valid split+shift descendant merely because its unshifted
        # visual parent could not itself lay out parking.
        two_phase_base_vlm = counts.get("two_phase_base_vlm") or {}
        if two_phase_base_vlm.get("active") is True:
            downstream_evaluation_pool = pool
            base_stage_vlm_gate = deepcopy(
                two_phase_base_vlm.get("base_vlm_gate") or {}
            )
        elif runtime_live_vlm and not smoke_mode:
            downstream_evaluation_pool, base_stage_vlm_gate = audit_book_base_stage_with_vlm(
                pool,
                building_type=building_type,
                output_dir=output_dir / slug / "book-base-stage",
                visual_directive=program_visual_directive,
                outcome_graph=outcome_graph,
                program_slug=slug,
            )
        else:
            downstream_evaluation_pool = pool
            base_stage_vlm_gate = {
                "schema_version": "arr.maas.book_base_stage_vlm_gate.v1",
                "required": False,
                "status": (
                    "skipped_cost_bounded_smoke_exact_final_only"
                    if runtime_live_vlm and smoke_mode
                    else "not_requested"
                ),
                "input_count": len(pool),
            }
        program_selection_input_count = len(downstream_evaluation_pool)
        downstream_evaluation_pool = _program_selection_candidates(
            downstream_evaluation_pool
        )
        counts["program_selection_routing"] = {
            "schema_version": "arr.maas.program_selection_routing.v1",
            "input_count": program_selection_input_count,
            "canonical_hard_pass_count": len(downstream_evaluation_pool),
            "development_only_excluded_count": (
                program_selection_input_count - len(downstream_evaluation_pool)
            ),
        }
        preselection_hard_gate = None
        selection_pool = downstream_evaluation_pool
        if generation_context is not None:
            preselection_hard_gate = evaluate_accepted_sources_downstream(
                downstream_evaluation_pool,
                site_local_utm=site,
                site_origin_utm=site_origin_utm,
                pnu=pnu,
                building_type=building_type,
                height_m=height,
                floors=floors,
                constraints=constraints,
                regulation_evidence=regulation_evidence or {},
                sunlight_envelope=sunlight_envelope,
                parking_options=parking_options,
                generation_context=generation_context,
            )
            record_downstream_timings(preselection_hard_gate)
            selection_pool = _final_vlm_input_from_downstream(
                downstream_evaluation_pool,
                preselection_hard_gate,
            )
        counts["preselection_hard_gate"] = _hard_gate_count_summary(
            preselection_hard_gate,
            downstream_evaluation_pool,
        )
        counts["final_vlm_routing"] = deepcopy(
            (preselection_hard_gate or {}).get("final_vlm_routing") or {
                "schema_version": "arr.maas.final_vlm_descendant_routing.v1",
                "input_count": len(downstream_evaluation_pool),
                "routed_book_descendant_count": 0,
                "no_call_reason": "downstream_hard_gate_not_available",
            }
        )
        counts["geometry_program_authority"] = {
            "required": geometry_program_authority,
            "reason": (
                "recursive_only_flag"
                if recursive_only
                else (
                    "geometry_synthesis_request"
                    if synthesis_requests
                    else (
                        "geometry_program_mutation"
                        if geometry_program_mutations
                        else "universal_form_bank_default"
                    )
                )
            ),
            "legacy_geometry_final_selection_allowed": False,
        }
        # The default dominant-form supply is now the universal bank. Program
        # evidence and BOOK projection exist before the live critic sees a
        # candidate; no program-conditioned VLM authors the base/chassis lane.
        # Explicit session directives remain additive feedback only.
        live_vlm_selection_required = False
        pre_vlm_selection_count = len(selection_pool)
        pre_book_reviewed_count = sum(
            _vlm_reviewed_program_candidate(candidate)
            for candidate in selection_pool
        )
        counts["vlm_final_selection_gate"] = {
            "required": False,
            "role": "post_program_exact_book_critic",
            "universal_form_bank_precedes_program_and_vlm": True,
            "input_count": pre_vlm_selection_count,
            "legacy_prebook_reviewed_program_fit_pass_count": pre_book_reviewed_count,
            "universal_control_count": pre_vlm_selection_count - pre_book_reviewed_count,
            "universal_control_retained_for_exact_post_book_review": True,
            "exact_post_book_vlm_is_final_selection_authority": bool(runtime_live_vlm),
        }
        counts["book_base_stage_vlm_gate"] = base_stage_vlm_gate
        degenerate_sheet_count = sum(
            bool(_solid_morphology_metrics(candidate)["degenerate_sheet_like"])
            for candidate in selection_pool
        )
        # Structurally valid exact descendants must reach the final critic.
        # Degenerate-sheet morphology is visual/design evidence for that
        # critic, not an additional pre-VLM hard gate.
        raw_selection_pool_count = len(selection_pool)
        selection_pool = _bounded_visual_selection_pool(selection_pool)
        counts["visual_selection_pool"] = {
            "input_count": raw_selection_pool_count,
            "bounded_count": len(selection_pool),
            "quality_diversity_archive": qd_archive_evidence(selection_pool),
            "degenerate_sheet_like_rejected_count": degenerate_sheet_count,
            "measured_solid_phenotype_counts": dict(sorted(Counter(
                _solid_morphology_metrics(candidate)["phenotype"]
                for candidate in selection_pool
            ).items())),
            "measured_wedge_like_count": sum(
                bool(_solid_morphology_metrics(candidate)["wedge_like"])
                for candidate in selection_pool
            ),
            "measured_pyramidal_like_count": sum(
                bool(_solid_morphology_metrics(candidate)["pyramidal_like"])
                for candidate in selection_pool
            ),
            "ground_strategy_counts": dict(sorted(Counter(
                _design_concept_descriptor(candidate)["ground_strategy"]
                for candidate in selection_pool
            ).items())),
        }
        pre_final_book_vlm_pool = list(selection_pool)
        reviewed_final_vlm_fingerprints: set[tuple[Any, ...]] = set()
        if runtime_live_vlm:
            initial_final_review_pool = (
                list(pre_final_book_vlm_pool)
                if len(pre_final_book_vlm_pool) <= 5
                else _bounded_visual_selection_pool(
                    pre_final_book_vlm_pool
                )
            )
            reviewed_final_vlm_fingerprints.update(
                _fingerprint(candidate)
                for candidate in initial_final_review_pool
            )
            initial_cycle = run_final_vlm_cycle(
                initial_final_review_pool,
                retained_hard_passes=[],
                building_type=building_type,
                output_dir=output_dir / slug,
                visual_directive=program_visual_directive,
                outcome_graph=outcome_graph,
                program_slug=slug,
                generation_site=generation_site,
                height=height,
                floors=floors,
                generation_context=generation_context,
                program_dimensional_context=dimensional_context,
                site_boundary_source=site_boundary_source,
                site_access_context=site_access_context,
                site_access_geometry=site_access_geometry,
                base_capacity_contract=base_capacity_contract,
                downstream_context={
                    "site_local_utm": site,
                    "site_origin_utm": site_origin_utm,
                    "pnu": pnu,
                    "building_type": building_type,
                    "height_m": height,
                    "floors": floors,
                    "constraints": constraints,
                    "regulation_evidence": regulation_evidence or {},
                    "sunlight_envelope": sunlight_envelope,
                    "parking_options": parking_options,
                    "generation_context": generation_context,
                },
                hard_gate_summary=_hard_gate_count_summary,
                completion_status="exact_typed_repair_cycle_complete",
                no_repair_status="no_downstream_hard_pass_repair_candidates",
            )
            reviewed_final_vlm_fingerprints.update(
                _repair_final_vlm_submission_fingerprints(initial_cycle)
            )
            selection_pool = initial_cycle.selection_pool
            counts["initial_final_book_vlm_gate"] = initial_cycle.initial_vlm_gate
            counts["exact_post_book_typed_repair"] = initial_cycle.repair_evidence
            final_book_vlm_gate = initial_cycle.final_vlm_gate
        else:
            final_book_vlm_gate = {
                "schema_version": "arr.maas.final_book_vlm_portfolio_gate.v1",
                "required": False,
                "status": "not_requested",
                "input_count": len(selection_pool),
                "post_book_geometry_reviewed": False,
            }
        counts["final_book_vlm_gate"] = final_book_vlm_gate
        if agent_authored_manifest_active:
            selection_pool, rejected_count = _trusted_codex_selection_pool(
                selection_pool,
                admission=agent_authored_admission,
            )
            counts["agent_authored_manifest_selection_gate"] = {
                "schema_version": "arr.maas.codex_oauth_selection_gate.v1",
                "status": "pass",
                "input_count": len(selection_pool) + rejected_count,
                "trusted_retained_count": len(selection_pool),
                "nontrusted_rejected_count": rejected_count,
                "rejection_reason": "selected_candidate_not_in_trusted_codex_admission",
            }
        selection_pool, capacity_selection_exclusions = (
            _capacity_hard_pass_selection_pool(
                selection_pool,
                required=bool(base_capacity_contract),
            )
        )
        counts["capacity_selection_admission"] = {
            "schema_version": "arr.maas.capacity_selection_admission.v1",
            "status": "pass",
            "hard_pass_required": bool(base_capacity_contract),
            "retained_count": len(selection_pool),
            "excluded_count": len(capacity_selection_exclusions),
            "exclusions": capacity_selection_exclusions,
        }
        selection_compatibility_analysis = build_gestalt_compatibility_analysis(
            selection_pool,
            target_count=selection_target,
        )
        initial_final_vlm_feedback = {
            "audit_records": [
                *list((counts.get("initial_final_book_vlm_gate") or {}).get(
                    "audit_records"
                ) or ()),
                *list((final_book_vlm_gate or {}).get("audit_records") or ()),
            ]
        }
        solver_started = perf_counter()
        selected, selection_trace, selector_state = (
            _select_with_replenishment_state(
            phase="initial_selection",
            selection_pool=selection_pool,
            target_count=selection_target,
            visual_directive=program_visual_directive,
            compatibility_analysis=selection_compatibility_analysis,
            allow_diagnostic_fallback=_allow_partial_portfolio_preview(
                diagnostic_target=diagnostic_target_int,
                progressive_target=progressive_target_int,
            ),
            exact_repair_evidence=(
                counts.get("exact_post_book_typed_repair") or {}
            ),
            stage_outcomes=counts.get("stage_outcomes") or [],
            final_vlm_gate=initial_final_vlm_feedback,
            )
        )
        phase_durations_seconds["solver"] += (
            perf_counter() - solver_started
        )
        selection_capacity_diagnostics = (
            selector_state.selection_capacity_diagnostics
        )
        family_supply_deficits = selector_state.family_supply_deficits
        selector_stage_outcomes = selector_state.selector_stage_outcomes
        update_run_progress(
            output_dir,
            phase="initial_selection",
            program=slug,
            selection_pool_count=len(selection_pool),
            selected_mass_count=len(selected),
            required_scope_count=required_scope_target,
            selected_scope_count=len({_portfolio_diversity_key(candidate) for candidate in selected}),
        )
        outcome_graph.observe_candidates(
            program_slug=slug,
            candidates=downstream_evaluation_pool,
            downstream_report=preselection_hard_gate,
            selected=selected,
        )
        initial_selected_snapshot = list(selected)
        initial_selected_fingerprints = {
            _fingerprint(candidate) for candidate in initial_selected_snapshot
        }
        missing_scope = (
            len({_portfolio_diversity_key(candidate) for candidate in selected})
            < required_scope_target
        )
        initial_feasible_portfolio = bool(
            len(selected) == selection_target
            and not missing_scope
        )
        initial_reserve_state = None
        if selection_target == 20:
            if initial_feasible_portfolio and len(selection_pool) >= 24:
                selection_pool = competition_exact_hard_pass_reserve(
                    selection_pool,
                    selected=selected,
                )
            initial_reserve_state = competition_exact_reserve_transition(
                page_index=0,
                exact_hard_pass_count=len(selection_pool),
                feasible_portfolio=initial_feasible_portfolio,
            )
            initial_reserve_state["breadth_deficits"] = (
                competition_exact_hard_pass_deficits(
                    selection_pool,
                    page_index=0,
                    target_count=selection_target,
                    exact_compile_limit=(
                        progressive_mass_run_budget(
                            progressive_target_int
                        ).compile_limit
                        if progressive_target_int is not None
                        else None
                    ),
                )
            )
            counts["competition_breadth_initial_transition"] = (
                initial_reserve_state
            )
        replenishment_cycles: list[dict[str, Any]] = []
        progressive_exact_compile_limit = (
            progressive_mass_run_budget(
                progressive_target_int
            ).compile_limit
            if progressive_target_int is not None
            else None
        )
        exact_compile_used = int(
            counts.get("exact_compile_invocation_count") or 0
        )
        exact_compile_remaining = (
            _remaining_exact_compile_budget(
                progressive_exact_compile_limit,
                exact_compile_used,
            )
            if progressive_exact_compile_limit is not None
            else None
        )
        counts["cumulative_exact_compile_budget"] = {
            "schema_version": "arr.maas.cumulative_exact_compile_budget.v1",
            "limit": progressive_exact_compile_limit,
            "initial_actual_usage": exact_compile_used,
            "remaining_after_initial": exact_compile_remaining,
        }
        replenishment_deficit_present = (
            not initial_reserve_state["stop"]
            if initial_reserve_state is not None
            else len(selected) < selection_target or missing_scope
        )
        replenishment_required = bool(
            replenishment_deficit_present
            and not agent_authored_manifest_active
        )
        if replenishment_deficit_present and agent_authored_manifest_active:
            counts["agent_authored_manifest_supply_exhausted"] = {
                "schema_version": (
                    "arr.maas.agent_authored_supply_exhausted.v1"
                ),
                "status": "incomplete_no_authorship_fallback",
                "selected_count": len(selected),
                "target_count": selection_target,
                "deterministic_author_fallback_used": False,
                "paid_author_fallback_used": False,
            }
        if replenishment_required:
            excluded_parent_keys = set(base_stage_vlm_gate.get("reviewed_parent_keys") or ())
            excluded_parent_fingerprints = set(
                base_stage_vlm_gate.get("reviewed_parent_fingerprints") or ()
            )
            stop_reason = "cycle_budget_exhausted"
            progressive_budget = (
                progressive_mass_run_budget(progressive_target_int)
                if progressive_target_int is not None
                else None
            )
            cycle_budget = replenishment_cycle_budget_for_run(
                live_vlm=runtime_live_vlm,
                smoke_mode=smoke_mode,
                run_budget_limit=(
                    progressive_budget.replenishment_author_request_limit
                    if progressive_budget is not None
                    else None
                ),
            )
            if diagnostic_budget is not None:
                cycle_budget = min(
                    cycle_budget,
                    int(diagnostic_budget["replenishment_cycle_cap"]),
                )
            downstream_context = {
                "site_local_utm": site,
                "site_origin_utm": site_origin_utm,
                "pnu": pnu,
                "building_type": building_type,
                "height_m": height,
                "floors": floors,
                "constraints": constraints,
                "regulation_evidence": regulation_evidence or {},
                "sunlight_envelope": sunlight_envelope,
                "parking_options": parking_options,
                "generation_context": generation_context,
            }
            # The exact initial observations are already persisted in the
            # run-local outcome graph. Retaining the full compiled pool here
            # kept hundreds of heavyweight meshes alive across all later
            # cycles. Only the bounded QD archive and the at-most-20 initial
            # selected candidates are needed to refresh final selection flags.
            replenishment_live_state = _initial_replenishment_live_state(
                pool,
                reviewed_final_vlm_fingerprints=(
                    reviewed_final_vlm_fingerprints
                ),
                certified_reviewed_base_parents=tuple(
                    initial_certified_reviewed_base_parents
                ),
                author_rate_limit_cooldown=(
                    invocation_author_rate_limit_cooldown
                ),
            )
            pool = []
            downstream_evaluation_pool = []
            legal_fit_repair_feedback = list(
                counts.get("legal_fit_deficits") or ()
            )[-12:]
            capacity_authoring_deficits = list(
                counts.get("capacity_authoring_deficits") or ()
            )[-12:]
            base_book_vlm_replenishment_feedback = (
                outcome_graph.base_book_vlm_replenishment_feedback(
                    program_slug=slug,
                )
                if outcome_graph is not None
                else []
            )
            authored_visual_authority_replenishment_feedback = (
                outcome_graph.authored_visual_authority_replenishment_feedback(
                    program_slug=slug,
                )
                if outcome_graph is not None
                and hasattr(
                    outcome_graph,
                    "authored_visual_authority_replenishment_feedback",
                )
                else []
            )
            excluded_program_hashes = {
                str(deficit.get("rejected_parent_program_hash") or "")
                for deficit in capacity_authoring_deficits
                if str(deficit.get("rejected_parent_program_hash") or "")
            }
            successful_author_count = 0
            for cycle_index in range(1, cycle_budget + 1):
                runtime_reserve_available = True
                if progressive_budget is not None:
                    runtime_reserve_available = replenishment_allowed_by_deadline(
                        started_at=portfolio_started_at,
                        timeout_seconds=progressive_budget.timeout_seconds,
                        now=perf_counter(),
                    )
                provider_snapshot = paid_provider_budget_snapshot()
                author_budget_state = _replenishment_author_budget_state(
                    provider_snapshot,
                    successful_author_count=successful_author_count,
                )
                author_replenishment_remaining = author_budget_state[
                    "author_replenishment_remaining"
                ]
                selected_count = len(selected)
                selected_scope_count = len({
                    _portfolio_diversity_key(candidate)
                    for candidate in selected
                })
                preflight_stop_reason = (
                    _replenishment_cycle_preflight_stop_reason(
                        selected_count=selected_count,
                        selected_scope_count=selected_scope_count,
                        target_count=selection_target,
                        required_scope_count=required_scope_target,
                        exact_compile_remaining=exact_compile_remaining,
                        author_replenishment_remaining=(
                            int(author_replenishment_remaining)
                            if author_replenishment_remaining is not None
                            else None
                        ),
                        runtime_reserve_available=runtime_reserve_available,
                        successful_author_count=author_budget_state[
                            "successful_author_count"
                        ],
                        successful_author_limit=author_budget_state[
                            "successful_author_limit"
                        ],
                        provider_attempts_remaining=author_budget_state[
                            "provider_attempts_remaining"
                        ],
                    )
                )
                if preflight_stop_reason:
                    stop_reason = preflight_stop_reason
                    if stop_reason == "cumulative_exact_compile_budget_exhausted":
                        counts["progressive_exact_compile_stop"] = {
                            "schema_version": (
                                "arr.maas.progressive_exact_compile_stop.v1"
                            ),
                            "status": stop_reason,
                            "cycle_not_started": cycle_index,
                            "limit": progressive_exact_compile_limit,
                            "actual_usage": exact_compile_used,
                            "remaining": 0,
                        }
                    if stop_reason == "runtime_reserve_exhausted":
                        counts["progressive_runtime_stop"] = {
                            "schema_version": (
                                "arr.maas.progressive_runtime_stop.v1"
                            ),
                            "status": "runtime_reserve_exhausted",
                            "target_count": progressive_target_int,
                            "cycle_not_started": cycle_index,
                            "timeout_seconds": (
                                progressive_budget.timeout_seconds
                            ),
                        }
                    break
                previous_pool_count = len(selection_pool)
                replenishment_inputs, authored_visual_authority_replenishment_feedback = (
                    _next_synthesis_inputs_from_selector_state(
                        selector_state,
                        synthesis_requests=synthesis_requests,
                        authored_visual_authority_replenishment_feedback=(
                            authored_visual_authority_replenishment_feedback
                        ),
                        legal_fit_repair_feedback=legal_fit_repair_feedback,
                        capacity_authoring_deficits=capacity_authoring_deficits,
                        progressive_target=progressive_target_int,
                        base_book_vlm_replenishment_feedback=(
                            base_book_vlm_replenishment_feedback
                        ),
                        selected_count=selected_count,
                        selected_scope_count=selected_scope_count,
                        target_count=selection_target,
                        required_scope_count=required_scope_target,
                        exact_compile_remaining=exact_compile_remaining,
                        cycle_index=cycle_index,
                        cycle_budget=cycle_budget,
                        author_replenishment_remaining=(
                            int(author_replenishment_remaining)
                            if author_replenishment_remaining is not None
                            else None
                        ),
                    )
                )
                counts["authored_visual_authority_replenishment_feedback"] = deepcopy(
                    authored_visual_authority_replenishment_feedback
                )
                cycle_synthesis_requests = replenishment_inputs[
                    "synthesis_requests"
                ]
                cycle, replenishment_live_state = (
                    _run_replenishment_cycle_with_live_state(
                    _run_replenishment_cycle_with_compile_authority,
                    run_replenishment_cycle,
                    state=replenishment_live_state,
                    exact_compile_remaining=exact_compile_remaining,
                    compile_stop_sink=counts,
                    cycle_index=cycle_index,
                    parent_variant_index=cycle_index,
                    retained_selection_pool=selection_pool,
                    excluded_parent_keys=excluded_parent_keys,
                    excluded_parent_fingerprints=excluded_parent_fingerprints,
                    excluded_program_hashes=excluded_program_hashes,
                    generation_site=generation_site,
                    building_type=building_type,
                    height=height,
                    floors=floors,
                    generation_context=generation_context,
                    typed_graph_mutations=typed_graph_mutations,
                    geometry_program_mutations=geometry_program_mutations,
                    synthesis_requests=cycle_synthesis_requests,
                    outcome_graph=outcome_graph,
                    recursive_only=geometry_program_authority,
                    target_count=selection_target,
                    exact_compile_limit=replenishment_inputs[
                        "exact_compile_limit"
                    ],
                    program_dimensional_context=dimensional_context,
                    site_boundary_source=site_boundary_source,
                    site_access_context=site_access_context,
                    site_access_geometry=site_access_geometry,
                    runtime_live_vlm=runtime_live_vlm,
                    live_vlm_selection_required=live_vlm_selection_required,
                    base_capacity_contract=base_capacity_contract,
                    trusted_legal_floor_field=(
                        trusted_run_legal_floor_field
                    ),
                    trusted_legal_floor_field_hash=(
                        trusted_run_legal_floor_field_hash
                    ),
                    trusted_clear_span_floor_plan=(
                        trusted_run_clear_span_floor_plan
                    ),
                    capacity_site=site,
                    output_dir=output_dir / slug,
                    program_slug=slug,
                    visual_directive=program_visual_directive,
                    downstream_context=downstream_context,
                    hard_gate_summary=_hard_gate_count_summary,
                    stop_after_shared_floor_hard_passes=(
                        _smoke_floor_pass_reserve(
                            selection_target,
                            live_vlm=runtime_live_vlm,
                        )
                        if smoke_mode or progressive_target_int is not None
                        else None
                    ),
                    diagnostic_generation_budget=diagnostic_budget,
                    progress_callback=(
                        lambda counters: persist_diagnostic_generation_progress(
                            output_dir,
                            program=slug,
                            target=int(diagnostic_target),
                            counters=counters,
                            phase="replenishment_generation",
                        )
                        if diagnostic_budget is not None
                        else None
                    ),
                    )
                )
                invocation_author_rate_limit_cooldown = (
                    replenishment_live_state.author_rate_limit_cooldown
                )
                successful_author_count += _materialized_authored_supply_success(
                    cycle.evidence
                )
                legal_fit_repair_feedback = list(
                    cycle.evidence.get("legal_fit_deficits") or ()
                )[-12:]
                cycle_exact_compile_usage = int(
                    cycle.evidence.get("exact_compile_invocation_count") or 0
                )
                exact_compile_used += cycle_exact_compile_usage
                if progressive_exact_compile_limit is not None:
                    exact_compile_remaining = _remaining_exact_compile_budget(
                        progressive_exact_compile_limit,
                        exact_compile_used,
                    )
                counts["cumulative_exact_compile_budget"].update({
                    "actual_usage": exact_compile_used,
                    "remaining": exact_compile_remaining,
                })
                capacity_authoring_deficits = list(
                    cycle.evidence.get("capacity_authoring_deficits") or ()
                )[-12:]
                excluded_program_hashes.update(
                    str(deficit.get("rejected_parent_program_hash") or "")
                    for deficit in capacity_authoring_deficits
                    if str(deficit.get("rejected_parent_program_hash") or "")
                )
                selection_pool = cycle.selection_pool
                if agent_authored_manifest_active:
                    selection_pool, rejected_count = (
                        _trusted_codex_selection_pool(
                            selection_pool,
                            admission=agent_authored_admission,
                        )
                    )
                    gate = counts.setdefault(
                        "agent_authored_manifest_selection_gate",
                        {
                            "schema_version": "arr.maas.codex_oauth_selection_gate.v1",
                            "status": "pass",
                            "input_count": 0,
                            "trusted_retained_count": 0,
                            "nontrusted_rejected_count": 0,
                            "rejection_reason": "selected_candidate_not_in_trusted_codex_admission",
                        },
                    )
                    gate["input_count"] += len(selection_pool) + rejected_count
                    gate["trusted_retained_count"] += len(selection_pool)
                    gate["nontrusted_rejected_count"] += rejected_count
                selection_pool, cycle_capacity_exclusions = (
                    _capacity_hard_pass_selection_pool(
                        selection_pool,
                        required=bool(base_capacity_contract),
                    )
                )
                capacity_gate = counts.setdefault(
                    "capacity_selection_admission",
                    {
                        "schema_version": (
                            "arr.maas.capacity_selection_admission.v1"
                        ),
                        "status": "pass",
                        "hard_pass_required": bool(base_capacity_contract),
                        "retained_count": 0,
                        "excluded_count": 0,
                        "exclusions": [],
                    },
                )
                capacity_gate["retained_count"] = len(selection_pool)
                capacity_gate["excluded_count"] += len(
                    cycle_capacity_exclusions
                )
                capacity_gate["exclusions"].extend(
                    cycle_capacity_exclusions
                )
                excluded_parent_keys.update(cycle.reviewed_parent_keys)
                excluded_parent_fingerprints.update(cycle.reviewed_parent_fingerprints)
                selection_compatibility_analysis = build_gestalt_compatibility_analysis(
                    selection_pool,
                    target_count=selection_target,
                )
                solver_started = perf_counter()
                selected, selection_trace, selector_state = (
                    _select_with_replenishment_state(
                        phase="post_cycle_selection",
                        selection_pool=selection_pool,
                        target_count=selection_target,
                        visual_directive=program_visual_directive,
                        compatibility_analysis=selection_compatibility_analysis,
                        allow_diagnostic_fallback=_allow_partial_portfolio_preview(
                        diagnostic_target=diagnostic_target_int,
                        progressive_target=progressive_target_int,
                        ),
                        exact_repair_evidence=(
                            cycle.evidence.get(
                                "exact_post_book_typed_repair"
                            ) or {}
                        ),
                        stage_outcomes=(
                            cycle.evidence.get("stage_outcomes") or []
                        ),
                        final_vlm_gate=(
                            cycle.evidence.get("final_book_vlm_gate") or {}
                        ),
                    )
                )
                phase_durations_seconds["solver"] += (
                    perf_counter() - solver_started
                )
                selection_capacity_diagnostics = (
                    selector_state.selection_capacity_diagnostics
                )
                family_supply_deficits = selector_state.family_supply_deficits
                selector_stage_outcomes = selector_state.selector_stage_outcomes
                pool_growth = len(selection_pool) - previous_pool_count
                missing_scope = (
                    len({_portfolio_diversity_key(candidate) for candidate in selected})
                    < required_scope_target
                )
                feasible_portfolio = bool(
                    len(selected) == selection_target
                    and not missing_scope
                )
                reserve_state = None
                if selection_target == 20:
                    if feasible_portfolio and len(selection_pool) >= 24:
                        selection_pool = (
                            competition_exact_hard_pass_reserve(
                                selection_pool,
                                selected=selected,
                            )
                        )
                    reserve_state = competition_exact_reserve_transition(
                        page_index=cycle_index,
                        exact_hard_pass_count=len(selection_pool),
                        feasible_portfolio=feasible_portfolio,
                    )
                    reserve_state["breadth_deficits"] = (
                        competition_exact_hard_pass_deficits(
                            selection_pool,
                            page_index=cycle_index,
                            target_count=selection_target,
                        )
                    )
                cycle_evidence = {
                    **cycle.evidence,
                    "selection_pool_count_before": previous_pool_count,
                    "selection_pool_count_after": len(selection_pool),
                    "selection_pool_growth": pool_growth,
                    "selected_count_after": len(selected),
                    "competition_breadth_replenishment": reserve_state,
                    "selection_capacity_diagnostics": deepcopy(
                        selection_capacity_diagnostics
                    ),
                }
                replenishment_cycles.append(cycle_evidence)
                update_run_progress(
                    output_dir,
                    phase="replenishment",
                    program=slug,
                    cycle_index=cycle_index,
                    cycle_budget=cycle_budget,
                    selection_pool_count=len(selection_pool),
                    selected_mass_count=len(selected),
                    required_scope_count=required_scope_target,
                    selected_scope_count=len({_portfolio_diversity_key(candidate) for candidate in selected}),
                )
                if runtime_live_vlm and cycle.evidence.get("final_book_vlm_gate"):
                    counts["final_book_vlm_gate"] = cycle.evidence["final_book_vlm_gate"]
                outcome_graph.observe_candidates(
                    program_slug=slug,
                    candidates=cycle.downstream_evaluation_pool,
                    downstream_report=cycle.downstream_report,
                    selected=selected,
                )
                terminal_author_budget_state = _replenishment_author_budget_state(
                    paid_provider_budget_snapshot(),
                    successful_author_count=successful_author_count,
                )
                terminal_reason = replenishment_stop_reason(
                    selected_count=len(selected),
                    selected_scope_count=len({_portfolio_diversity_key(candidate) for candidate in selected}),
                    target_count=selection_target,
                    required_scope_count=required_scope_target,
                    cycles_run=cycle_index,
                    cycle_budget=cycle_budget,
                    exact_hard_pass_count=len(selection_pool),
                    feasible_portfolio=feasible_portfolio,
                    author_budget_failure=next(iter(
                        cycle.evidence.get(
                            "geometry_program_llm_author_budget_failures"
                        ) or ()
                    ), None),
                    exact_compile_remaining=exact_compile_remaining,
                    **terminal_author_budget_state,
                )
                del cycle
                if terminal_reason:
                    stop_reason = terminal_reason
                    break
            if replenishment_cycles:
                counts["bounded_parent_replenishment"] = {
                    **replenishment_cycles[-1],
                    "schema_version": "arr.maas.bounded_parent_replenishment.v2",
                    "cycle_budget": cycle_budget,
                    "cycle_count": len(replenishment_cycles),
                    "cycles": replenishment_cycles,
                    "stop_reason": stop_reason,
                }
            # The final selection can displace a first-pass incumbent. Update
            # observation flags instead of leaving stale selected=true memory.
            outcome_graph.observe_candidates(
                program_slug=slug,
                candidates=[
                    *initial_selected_snapshot,
                    *(
                        candidate for candidate in selected
                        if _fingerprint(candidate) not in initial_selected_fingerprints
                    ),
                ],
                downstream_report=None,
                selected=selected,
            )
        counts["final_hard_pass_selection_pool_count"] = len(selection_pool)
        # The quota can only cover positions the pool actually holds. Reporting
        # the pool's ground takes separates "selection did not spread" from
        # "there was nothing to spread over" - two different repairs.
        pool_ground_takes: dict[str, int] = {}
        for candidate in selection_pool:
            key = _portfolio_diversity_key(candidate)
            pool_ground_takes[key] = pool_ground_takes.get(key, 0) + 1
        counts["selection_pool_ground_takes"] = dict(
            sorted(pool_ground_takes.items())
        )
        counts["partial_portfolio_preview"] = bool(
            progressive_target_int is not None
            and 0 < len(selected) < selection_target
        )
        counts["selection_trace"] = selection_trace
        counts["selection_capacity_diagnostics"] = _selection_capacity_diagnostics(
            selection_pool,
            selected,
            target=selection_target,
            visual_directive=program_visual_directive,
            compatibility_analysis=selection_compatibility_analysis,
        )
        selected, finalization_rejections = partition_finalizable_candidates(
            selected,
            resolver=lambda candidate: resolve_candidate_finalization_context(
                candidate.source.metadata,
                trusted_legal_floor_field=trusted_run_legal_floor_field,
                expected_legal_floor_field_hash=(
                    trusted_run_legal_floor_field_hash
                ),
                expected_pnu=pnu,
            ),
        )
        finalization_rejections_by_program_hash = {
            _candidate_program_hash(candidate): evidence
            for candidate, evidence in finalization_rejections
        }
        counts["candidate_finalization_rejections"] = [
            {
                "program_hash": _candidate_program_hash(candidate),
                "evidence": evidence,
            }
            for candidate, evidence in finalization_rejections
        ]
        selected = _order_portfolio_for_capacity_review(selected)
        update_run_progress(
            output_dir,
            phase="final_gate_and_render",
            program=slug,
            selection_pool_count=len(selection_pool),
            selected_mass_count=len(selected),
            required_scope_count=required_scope_target,
            selected_scope_count=len({_portfolio_diversity_key(candidate) for candidate in selected}),
        )
        selected_by_program[slug] = selected
        language_metrics = _portfolio_language_metrics(selected)
        metrics_by_program[slug] = language_metrics
        allow_relaxed_finalization = _allow_incomplete_preview_finalization(
            diagnostic_target=diagnostic_target_int,
            smoke_mode=smoke_mode,
            progressive_target=progressive_target_int,
            selected_count=len(selected),
            selection_target=selection_target,
            explicitly_relaxed=bool(
                os.getenv("MAAS_RELAX_BOOK_FINALIZATION_GATE")
            ),
        )
        downstream_hard_gate = (
            evaluate_accepted_sources_downstream(
                selected,
                site_local_utm=site,
                site_origin_utm=site_origin_utm,
                pnu=pnu,
                building_type=building_type,
                height_m=height,
                floors=floors,
                constraints=constraints,
                regulation_evidence=regulation_evidence or {},
                sunlight_envelope=sunlight_envelope,
                parking_options=parking_options,
                generation_context=generation_context,
            )
            if constraints is not None
            else {
                "schema_version": "arr.maas.book_downstream_hard_gate.v1",
                "status": "not_run",
                "same_accepted_source": True,
                "candidate_count": len(selected),
            }
        )
        record_downstream_timings(downstream_hard_gate)
        features: list[dict[str, Any]] = []
        rows: list[dict[str, Any]] = []
        archive_compilations: list[Any] = []
        downstream_rows = (
            list(downstream_hard_gate.get("rows") or ())
            if isinstance(downstream_hard_gate, dict)
            else []
        )
        for index, candidate in enumerate(selected):
            candidate_soft_finalization_reject = False
            candidate_finalization_evidence: dict[str, Any] | None = None
            candidate_review_status = "accept"
            candidate_review_reasons = [
                "program hard pass",
                "clean mass pass",
            ]
            candidate_finalization_context = (
                resolve_candidate_finalization_context(
                    candidate.source.metadata,
                    trusted_legal_floor_field=(
                        trusted_run_legal_floor_field
                    ),
                    expected_legal_floor_field_hash=(
                        trusted_run_legal_floor_field_hash
                    ),
                    expected_pnu=pnu,
                )
            )
            candidate_height = (
                candidate_finalization_context.candidate_height_m
            )
            candidate_floors = (
                candidate_finalization_context.candidate_floor_count
            )
            feature = deepcopy(candidate.feature)
            materialize_source_feature_surfaces(
                feature,
                candidate.source,
                height=candidate_height,
            )
            props = feature["properties"]
            props["archive_variant_id"] = props["variant_id"]
            props["variant_id"] = f"maas_{index + 1:02d}"
            props["mass_shape"] = candidate.operation
            props["review_status"] = "accept"
            props["portfolio_selection_status"] = "selected"
            props["review_reasons"] = candidate_review_reasons
            if runtime_live_vlm:
                props["review_reasons"].append("exact post-BOOK VLM hard pass")
            features.append(feature)
            signature = candidate.source.signature()
            descriptor = _candidate_language_descriptor(candidate)
            rows.append({
                "variant_id": props["variant_id"],
                "source_sequence": candidate.sequence.name,
                "book_operation": candidate.operation,
                "book_principle_id": candidate.principle_id,
                "book_principle_kind": candidate.principle_kind,
                "book_scope": candidate.source.metadata.get("program_book_projection_evidence", {}).get("scope", {}),
                "capacity_alternative": deepcopy(
                    candidate.source.metadata.get("capacity_alternative_projection") or {}
                ),
                "score": candidate.score,
                "volume_count": len(candidate.source.volumes),
                "surface_count": int(signature.get("effective_surface_count") or signature.get("surface_count") or 0),
                "inside_site": _inside_site(candidate.source, generation_site),
                "generation_host_mode": str((
                    candidate.source.metadata.get("legal_generation_context_evidence") or {}
                ).get("generation_host_mode") or "unconstrained_site"),
                "legal_generation_context_evidence": deepcopy(
                    candidate.source.metadata.get("legal_generation_context_evidence") or {}
                ),
                "program_hard_pass": _candidate_program_hard_pass(candidate),
                "vlm_geometry_critic_active": bool(
                    _geometry_program_metadata(candidate).get("vlm_geometry_critic_active")
                ),
                "vlm_program_fit_hard_pass": bool(
                    _geometry_program_metadata(candidate).get("vlm_program_fit_hard_pass")
                ),
                "vlm_critic_score": _geometry_program_metadata(candidate).get("vlm_critic_score"),
                "vlm_program_appropriateness": _geometry_program_metadata(candidate).get("vlm_program_appropriateness"),
                "vlm_section_program_fit": _geometry_program_metadata(candidate).get("vlm_section_program_fit"),
                "final_book_vlm_audit": deepcopy(
                    candidate.source.metadata.get("final_book_vlm_audit") or {}
                ),
                "seed_family": descriptor["seed_family"],
                "roof_section_family": descriptor["section_family"],
                "roof_archetype": descriptor["roof_archetype"],
                "chassis_family": descriptor["chassis_family"],
                "solid_phenotype": descriptor["solid_phenotype"],
                "body_phenotype": descriptor["body_phenotype"],
                "section_phenotype": descriptor["section_phenotype"],
                "wedge_like": descriptor["wedge_like"],
                "pyramidal_like": descriptor["pyramidal_like"],
                "collapsed_profiled_tent_like": descriptor["collapsed_profiled_tent_like"],
                "degenerate_sheet_like": descriptor["degenerate_sheet_like"],
                "horizontal_surface_ratio": descriptor["horizontal_surface_ratio"],
                "vertical_surface_ratio": descriptor["vertical_surface_ratio"],
                "sloped_surface_ratio": descriptor["sloped_surface_ratio"],
                "normal_direction_bin_count": descriptor["normal_direction_bin_count"],
                "horizontal_level_count": descriptor["horizontal_level_count"],
                "plan_convexity": descriptor["plan_convexity"],
                "upper_area_ratio": descriptor["upper_area_ratio"],
                "solid_genus": descriptor["solid_genus"],
                "solid_component_count": descriptor["solid_component_count"],
                "oriented_plan_aspect_ratio": descriptor["oriented_plan_aspect_ratio"],
                "plan_compactness": descriptor["plan_compactness"],
                "plan_family": descriptor["plan_family"],
                "dominant_component_ratio": descriptor["dominant_component_ratio"],
                "site_coverage_ratio": descriptor["site_coverage_ratio"],
                "hierarchy_score": descriptor["hierarchy_score"],
                "section_control_signature": descriptor["section_control_signature"],
                "semantic_role_tokens": descriptor["semantic_role_tokens"],
                "body_rule_count": descriptor["body_rule_count"],
                "program_body_rule_count": descriptor["program_body_rule_count"],
                "public_threshold_rule_count": descriptor["public_threshold_rule_count"],
                "book_body_rule_count": descriptor["book_body_rule_count"],
                "body_rule_family_counts": descriptor["body_rule_family_counts"],
                "body_rules": descriptor["body_rules"],
                "design_concept": descriptor["design_concept"],
                "design_concept_key": descriptor["design_concept_key"],
                "ground_strategy": descriptor["ground_strategy"],
                "frontage_aligned_public_threshold": descriptor["frontage_aligned_public_threshold"],
                "missing_required_design_concepts": descriptor["missing_required_design_concepts"],
                "measured_clear_span_m": descriptor["measured_clear_span_m"],
                "measured_solid_height_m": descriptor["measured_solid_height_m"],
                "height_to_clear_span_ratio": descriptor["height_to_clear_span_ratio"],
                "capacity_alternative_id": descriptor["capacity_alternative_id"],
                "capacity_target_utilization": descriptor["capacity_target_utilization"],
                "capacity_achieved_utilization": descriptor["capacity_achieved_utilization"],
                "capacity_target_hard_pass": descriptor["capacity_target_hard_pass"],
                "requested_capacity_alternative_id": descriptor[
                    "requested_capacity_alternative_id"
                ],
                "requested_capacity_target_utilization": descriptor[
                    "requested_capacity_target_utilization"
                ],
                "requested_capacity_target_hard_pass": descriptor[
                    "requested_target_hard_pass"
                ],
                "resolved_capacity_alternative_id": descriptor[
                    "resolved_capacity_alternative_id"
                ],
                "resolved_capacity_target_utilization": descriptor[
                    "resolved_capacity_target_utilization"
                ],
                "resolved_capacity_hard_pass": descriptor[
                    "resolved_capacity_hard_pass"
                ],
                "far_pct": descriptor["far_pct"],
            })
            downstream_row = (
                downstream_rows[index]
                if index < len(downstream_rows) and isinstance(downstream_rows[index], dict)
                else {}
            )
            authored_compilation = deepcopy(
                candidate.source.metadata.get("geometry_program_compilation") or {}
            )
            bridge = deepcopy(
                candidate.source.metadata.get("geometry_program_bridge_evidence") or {}
            )
            authored_program_payload = deepcopy(
                candidate.source.metadata.get("geometry_program") or {}
            )
            execution_program = GeometryProgram.from_dict(
                authored_program_payload
            )
            expected_final_program_hash = str(
                candidate.source.metadata.get("final_program_hash") or ""
            )
            if (
                expected_final_program_hash
                and execution_program.program_hash()
                != expected_final_program_hash
            ):
                raise RuntimeError(
                    "stored final legal geometry program hash mismatch"
                )
            execution_compilation = compile_geometry_program(execution_program)
            if execution_compilation.status != "compiled":
                raise RuntimeError(
                    "selected final SourceMass could not compile for exact replay: "
                    f"{execution_compilation.status} {execution_compilation.issues}"
                )
            program_payload = execution_program.to_dict()
            compilation = execution_compilation.to_dict(include_mesh=False)
            authored_graph_snapshot = deepcopy(
                candidate.source.metadata.get("geometry_graph_snapshot") or {}
            )
            graph_snapshot = build_geometry_graph_snapshot(
                execution_program,
                execution_compilation,
            )
            props["geometry_program_compilation"] = compilation
            props["authored_geometry_program_compilation"] = authored_compilation
            trace_name = f"{slug}__{index + 1:02d}__{candidate.sequence.name}"
            trace_sequence = VerbSequence(
                name=trace_name,
                label=f"{slug} {index + 1:02d} {candidate.sequence.label or candidate.sequence.name}",
                calls=candidate.sequence.calls,
                notes=tuple(candidate.sequence.notes) + (
                    "trace_source=exact_final_selected_geometry",
                    "selection_effect=none_shadow_only",
                ),
            )
            hard_gates = {
                "program": {
                    "hard_pass": _candidate_program_hard_pass(candidate),
                    "evidence": deepcopy(
                        candidate.source.metadata.get("program_gate_result") or {}
                    ),
                },
                "cleanMass": {
                    "hard_pass": True,
                    "visibleVolumeCount": len(candidate.source.volumes),
                    "effectiveSurfaceCount": int(
                        candidate.source.signature().get("effective_surface_count")
                        or candidate.source.signature().get("surface_count")
                        or 0
                    ),
                    "coherence": deepcopy(
                        (props.get("source_signature") or {}).get("coherence_evidence") or {}
                    ),
                },
                "legal": deepcopy(downstream_row.get("legal_projection") or {}),
                "parking": deepcopy(downstream_row.get("parking_hard_gate") or {}),
                "originalMetrics": deepcopy(downstream_row.get("original_metrics") or {}),
                "projectedMetrics": deepcopy(downstream_row.get("projected_metrics") or {}),
                "combinedHardPass": bool(downstream_row.get("combined_hard_pass")),
            }
            projected_visual_artifact = _projected_visual_handoff_artifact(
                candidate.feature,
            )
            projected_visual_authority_present = (
                projected_visual_artifact
                is not _PROJECTED_VISUAL_ARTIFACT_ABSENT
            )
            projected_visual_artifact_payload = (
                projected_visual_artifact
                if projected_visual_authority_present
                else {}
            )
            projected_visual_certificate = (
                projected_visual_artifact_payload.get(
                    "projectedVisualCertificate"
                )
                if isinstance(projected_visual_artifact_payload, dict)
                else {}
            )
            projected_visual_certificate = (
                projected_visual_certificate
                if isinstance(projected_visual_certificate, dict)
                else {}
            )
            final_semantic_anchor = deepcopy(
                props.get("final_semantic_anchor") or {}
            )
            visual_origin = candidate.source.footprint.centroid
            staged_handoff = _stage_projected_visual_handoff(
                projected_visual_artifact,
                final_semantic_anchor=final_semantic_anchor,
                visual_origin=visual_origin,
                candidate_height=candidate_height,
                authority_present=projected_visual_authority_present,
            )
            projected_visual_hash = str(
                staged_handoff.get("projected_visual_geometry_hash") or ""
            )
            final_legal_geometry_hash = str(
                (
                    projected_visual_artifact_payload.get(
                        "finalLegalGeometryHash"
                    )
                    if isinstance(projected_visual_artifact_payload, dict)
                    else ""
                )
                or compilation.get("geometry_hash")
                or bridge.get("geometry_hash")
                or ""
            )
            geometry_artifact = {
                "schemaVersion": "arr.maas.geometry_artifact.v1",
                "authority": (
                    "certified_projected_visual_mesh"
                    if projected_visual_authority_present
                    else "final_legal_geometry_program"
                ),
                "geometryProgramRole": (
                    "authored_projected_surface_program_and_provenance"
                    if projected_visual_authority_present
                    else "executable_geometry"
                ),
                "programType": slug,
                "programLabel": building_type,
                "sourceSequence": candidate.sequence.name,
                "bookPrincipleId": candidate.principle_id,
                "bookScope": _scope_key(candidate),
                "capacityAlternative": deepcopy(
                    candidate.source.metadata.get("capacity_alternative_projection") or {}
                ),
                "geometryProgram": program_payload,
                "authoredGeometryProgram": authored_program_payload,
                "geometryGraphSnapshot": graph_snapshot,
                "authoredGeometryGraphSnapshot": authored_graph_snapshot,
                "programRelationEvidence": deepcopy(
                    candidate.source.metadata.get("program_component_relation_evidence") or {}
                ),
                "compilation": compilation,
                "authoredCompilation": authored_compilation,
                "identity": {
                    "programHash": str(
                        projected_visual_certificate.get(
                            "final_program_hash"
                        )
                        or compilation.get("program_hash")
                        or bridge.get("program_hash")
                        or ""
                    ),
                    "geometryHash": str(
                        projected_visual_hash
                        or compilation.get("geometry_hash")
                        or bridge.get("geometry_hash")
                        or ""
                    ),
                    "finalLegalGeometryHash": str(
                        final_legal_geometry_hash
                    ),
                },
                "finalLegalGeometryHash": str(
                    final_legal_geometry_hash
                ),
                "upstreamIdentity": {
                    "programHash": str(
                        authored_compilation.get("program_hash")
                        or bridge.get("program_hash")
                        or ""
                    ),
                    "geometryHash": str(
                        authored_compilation.get("geometry_hash")
                        or bridge.get("geometry_hash")
                        or ""
                    ),
                },
                "floorwiseProjection": deepcopy(
                    execution_program.metadata.get("floorwise_projection") or {}
                ),
                "floorwiseLegalMatrixStack": deepcopy(
                    candidate.source.metadata.get(
                        "floorwise_legal_matrix_stack"
                    )
                    or {}
                ),
                "vlmAudit": deepcopy(
                    candidate.source.metadata.get("final_book_vlm_audit") or {}
                ),
                "hardGates": hard_gates,
                "executionPassport": {},
                "selectionEffect": "none_shadow_only",
                **projected_visual_artifact_payload,
            }
            validated_visual = _persist_projected_visual_authority(
                props,
                geometry_artifact=geometry_artifact,
                staged_handoff=staged_handoff,
                final_semantic_anchor=final_semantic_anchor,
            )
            rows[index]["semantic_projection_hard_gate"] = (
                _selected_semantic_projection_hard_gate(
                    feature,
                    candidate_id=str(props.get("variant_id") or ""),
                )
            )
            certified_compilation = (
                revalidate_compilation_mesh(replace(
                    execution_compilation,
                    vertices=validated_visual.vertices,
                    triangles=validated_visual.triangles,
                    metrics={
                        "coordinate_space": validated_visual.coordinate_space,
                        "geometry_authority": "certified_projected_visual_mesh",
                        "exact_payload_hash": validated_visual.exact_payload_hash,
                        "capacity_geometry_hash": execution_compilation.geometry_hash,
                    },
                    geometry_hash=validated_visual.visual_hash,
                ))
                if validated_visual is not None
                else execution_compilation
            )
            certified_gate_issues = compilation_gate(certified_compilation)
            certified_gate_codes = tuple(issue.code for issue in certified_gate_issues)
            if (
                certified_compilation.status != "compiled"
                or certified_gate_issues
            ):
                if (
                    allow_relaxed_finalization
                    and certified_gate_issues
                    and all(
                        code in {"tiny_face", "tiny_edge"}
                        for code in certified_gate_codes
                    )
                ):
                    certified_compilation = execution_compilation
                    candidate_soft_finalization_reject = True
                    candidate_review_status = "warn"
                    candidate_review_reasons.append(
                        "certified projected mesh tiny geometry fallback"
                    )
                    candidate_finalization_evidence = {
                        "schema_version": "arr.maas.finalization_fallback.v1",
                        "status": "projected_visual_mesh_gate_soft_fail",
                        "fallback_reason": "tiny_geometry",
                        "gate_issues": list(certified_gate_codes),
                        "candidate_id": props["variant_id"],
                    }
                else:
                    raise RuntimeError(
                        "certified projected visual mesh failed geometry gate: "
                        f"{certified_compilation.status} "
                        f"{certified_gate_codes}"
                    )
            expected_final_mesh_identity = {
                "program_hash": execution_program.program_hash(),
                "final_geometry_hash": final_legal_geometry_hash,
                "visual_hash": (
                    validated_visual.visual_hash
                    if validated_visual is not None
                    else ""
                ),
            }
            final_capacity_measurement = (
                candidate.source.metadata.get(
                    "source_capacity_measurement"
                )
                or {}
            )
            final_capacity_resolution = resolve_capacity_band_evidence(
                candidate.source.metadata.get(
                    "capacity_alternative_projection"
                )
                or {},
                capacity_measurement=final_capacity_measurement,
            )
            final_required_capacity_utilization = max(
                float(
                    final_capacity_resolution.get(
                        "resolved_capacity_target_utilization"
                    )
                    or 0.0
                ),
                float(
                    final_capacity_resolution.get(
                        "resolved_capacity_minimum_utilization"
                    )
                    or 0.0
                ),
            )
            try:
                finalization_evidence = (
                    certify_final_mesh_actual_gfa_stop(
                        certified_compilation=certified_compilation,
                        projected_visual_certificate=(
                            validated_visual.certificate
                            if validated_visual is not None
                            else {}
                        ),
                        legal_floor_field=trusted_run_legal_floor_field,
                        expected_legal_floor_field_hash=(
                            trusted_run_legal_floor_field_hash
                        ),
                        expected_pnu=pnu,
                        candidate_height_m=candidate_height,
                        candidate_floor_count=candidate_floors,
                        candidate_target_gfa_m2=(
                            candidate_finalization_context
                            .candidate_target_gfa_m2
                        ),
                        candidate_feasible_maximum_gfa_m2=(
                            final_capacity_measurement.get(
                                "feasible_maximum_floor_area_m2"
                            )
                        ),
                        candidate_minimum_capacity_utilization=(
                            final_required_capacity_utilization
                        ),
                        candidate_capacity_resolution_hard_pass=(
                            final_capacity_resolution.get(
                                "resolved_capacity_hard_pass"
                            )
                        ),
                        expected_identity=expected_final_mesh_identity,
                    )
                )
            except FinalMeshFloorEvidenceError as error:
                error.evidence.update({
                    "variant_id": props["variant_id"],
                    "candidate_height_m": candidate_height,
                    "candidate_floor_count": candidate_floors,
                    "candidate_target_gfa_m2": (
                        candidate_finalization_context
                        .candidate_target_gfa_m2
                    ),
                    "legal_floor_field_hash": (
                        trusted_run_legal_floor_field_hash
                    ),
                })
                if allow_relaxed_finalization:
                    candidate_soft_finalization_reject = True
                    candidate_review_status = "warn"
                    candidate_review_reasons.append(
                        "final mesh gfa floor soft-fail"
                    )
                    finalization_evidence = {
                        "schema_version": "arr.maas.final_mesh_v1",
                        "status": "soft_failure",
                        "message": str(error),
                        "candidate_id": props["variant_id"],
                        "candidate_height_m": candidate_height,
                        "candidate_floor_count": candidate_floors,
                        "candidate_target_gfa_m2": (
                            candidate_finalization_context
                            .candidate_target_gfa_m2
                        ),
                        "legal_floor_field_hash": (
                            trusted_run_legal_floor_field_hash
                        ),
                    }
                    finalization_evidence.update(error.evidence)
                    candidate_finalization_evidence = finalization_evidence
                else:
                    props["candidate_finalization_evidence"] = deepcopy(
                        error.evidence
                    )
                    rows[index][
                        "candidate_finalization_evidence"
                    ] = deepcopy(error.evidence)
                    raise
            props["candidate_finalization_evidence"] = deepcopy(
                finalization_evidence
            )
            if candidate_finalization_evidence is not None and isinstance(
                finalization_evidence,
                dict,
            ):
                finalization_evidence = {
                    **finalization_evidence,
                    "fallback_summary": candidate_finalization_evidence,
                }
                props["candidate_finalization_evidence"] = deepcopy(
                    finalization_evidence
                )
            props["review_status"] = candidate_review_status
            props["review_reasons"] = candidate_review_reasons
            rows[index]["review_status"] = candidate_review_status
            rows[index]["review_reasons"] = list(candidate_review_reasons)
            fallback_finalization = {
                "candidate_height_m": float(candidate_height),
                "candidate_floor_count": int(candidate_floors),
                "candidate_target_gfa_m2": (
                    finalization_evidence.get(
                        "candidate_target_gfa_m2",
                        candidate_finalization_context
                        .candidate_target_gfa_m2,
                    )
                ),
                "achieved_gfa_m2": finalization_evidence.get(
                    "achieved_gfa_m2",
                    0.0,
                ),
                "legal_floor_field_hash": finalization_evidence.get(
                    "legal_floor_field_hash",
                    candidate_finalization_context.legal_floor_field_hash,
                ),
                "candidate_actual_gfa_stop_hash": finalization_evidence.get(
                    "candidate_actual_gfa_stop_hash",
                    "",
                ),
                "candidate_actual_gfa_stop_certificate": deepcopy(
                    finalization_evidence.get(
                        "candidate_actual_gfa_stop_certificate",
                        {},
                    )
                ),
                "candidate_finalization_evidence": deepcopy(
                    finalization_evidence
                ),
            }
            rows[index].update(fallback_finalization)
            archive_compilations.append(certified_compilation)
            mass_brain_trace_sequences.append(trace_sequence)
            mass_brain_trace_features[trace_name] = feature
        board = output_dir / (
            f"maas-book-{slug}-{selection_target}-smoke.png"
            if smoke_mode
            else f"maas-book-{slug}-{selection_target}.png"
        )
        render_started = perf_counter()
        render_archive_sheet(
            features,
            board,
            title=(
                f"MAAS BOOK × {building_type} · PNU {pnu} · "
                f"{len(features)}/{selection_target} floor-verified masses"
            ),
        )
        witness_candidates: list[_Candidate] = []
        witness_program_hashes: set[str] = set()
        for candidate in [
            *selected,
            *selection_pool,
            *downstream_evaluation_pool,
            *pool,
        ]:
            candidate_program_hash = _candidate_program_hash(candidate)
            if candidate_program_hash in witness_program_hashes:
                continue
            witness_program_hashes.add(candidate_program_hash)
            witness_candidates.append(candidate)
            if len(witness_candidates) >= selection_target:
                break
        selection_pool_hashes = {
            _candidate_program_hash(candidate) for candidate in selection_pool
        }
        selected_program_hashes = {
            _candidate_program_hash(candidate) for candidate in selected
        }
        candidate_preview_exclusions: list[dict[str, str]] = []
        candidate_preview_paths = render_candidate_preview_assets(
            (
                (_candidate_program_hash(candidate), candidate.feature)
                for candidate in witness_candidates
            ),
            output_dir=output_dir,
            program_slug=slug,
            exclusion_sink=candidate_preview_exclusions,
        )
        candidate_preview_exclusions_by_hash = {
            str(exclusion.get("program_hash") or ""): str(
                exclusion.get("reason") or ""
            )
            for exclusion in candidate_preview_exclusions
        }
        witness_records: list[dict[str, Any]] = []
        witness_failure_histogram: Counter[str] = Counter()
        # The final downstream gate is evaluated after the preselection pass and
        # carries the authoritative law, parking, and capacity evidence for the
        # selected candidates.  Using the earlier report here silently left the
        # portfolio ledger unevaluated even though the final rows existed.
        preselection_rows = list(
            (downstream_hard_gate or {}).get("rows") or ()
        )
        downstream_rows_by_program_hash = (
            downstream_rows_indexed_by_program_hash(
                preselection_rows,
                fallback_program_hashes=tuple(
                    _candidate_program_hash(candidate)
                    for candidate in selected
                ),
            )
        )
        portfolio_evaluation_inputs = []
        for candidate in witness_candidates:
            metadata = candidate.source.metadata
            final_audit = metadata.get("final_book_vlm_audit") or {}
            failure_reasons = list(final_audit.get("failures") or ())
            candidate_program_hash = _candidate_program_hash(candidate)
            finalization_rejection = (
                finalization_rejections_by_program_hash.get(
                    candidate_program_hash
                )
            )
            if finalization_rejection:
                failure_reasons = [
                    str(finalization_rejection.get("failure_code") or (
                        "candidate_finalization_rejected"
                    )),
                    *failure_reasons,
                ]
            preview_exclusion = candidate_preview_exclusions_by_hash.get(
                candidate_program_hash
            )
            if preview_exclusion and preview_exclusion not in failure_reasons:
                failure_reasons.append(preview_exclusion)
            status = _portfolio_witness_candidate_status(
                candidate_program_hash,
                selected_program_hashes=selected_program_hashes,
                selection_pool_hashes=selection_pool_hashes,
            )
            if not failure_reasons and status != "selected":
                failure_reasons = [
                    "strict_portfolio_not_selected"
                    if status == "hard_pass_not_selected"
                    else "downstream_or_final_vlm_hard_gate_failed"
                ]
            if status != "selected":
                witness_failure_histogram.update(failure_reasons)
            compilation = metadata.get("geometry_program_compilation") or {}
            visual = metadata.get("floorwise_visual_projection") or {}
            witness_records.append({
                "candidate_id": portfolio_candidate_id(
                    candidate.principle_id,
                    candidate_program_hash,
                ),
                "program_hash": candidate_program_hash,
                "geometry_hash": str(
                    metadata.get("final_legal_geometry_hash")
                    or metadata.get("final_floorwise_visual_geometry_hash")
                    or compilation.get("geometry_hash")
                    or ""
                ),
                "visual_hash": str(visual.get("visual_hash") or ""),
                "status": status,
                "failure_reasons": failure_reasons,
            })
            portfolio_evaluation_inputs.append(
                book_candidate_evaluation_input(
                    candidate_id=portfolio_candidate_id(
                        candidate.principle_id,
                        candidate_program_hash,
                    ),
                    program_hash=candidate_program_hash,
                    geometry_hash=str(
                        metadata.get("final_legal_geometry_hash")
                        or metadata.get(
                            "final_floorwise_visual_geometry_hash"
                        )
                        or compilation.get("geometry_hash")
                        or ""
                    ),
                    metadata=metadata,
                    downstream_row=downstream_rows_by_program_hash.get(
                        candidate_program_hash
                    ),
                    selected=status == "selected",
                    selection_reasons=tuple(failure_reasons),
                    preview_path=candidate_preview_paths.get(
                        candidate_program_hash,
                        "",
                    ),
                    lineage={
                        "book_principle_id": str(candidate.principle_id),
                        "book_scope": _scope_key(candidate),
                        "geometry_family": _geometry_program_family(
                            candidate
                        ),
                    },
                )
            )
        portfolio_evaluation = build_portfolio_evaluation_ledger(
            run_id=output_dir.name,
            pnu=pnu,
            target_count=selection_target,
            candidates=portfolio_evaluation_inputs,
        ).evidence()
        portfolio_evaluation["program_slug"] = slug
        counts["portfolio_witness"] = persist_portfolio_witness(
            output_dir,
            program_slug=slug,
            target_count=selection_target,
            selected_count=len(selected),
            records=witness_records,
            features=[candidate.feature for candidate in witness_candidates],
            failure_histogram=dict(witness_failure_histogram),
        )
        phase_durations_seconds["render"] += (
            perf_counter() - render_started
        )
        render_evidence = _archive_render_evidence(
            board,
            len(features),
            projected_visual_hashes=[
                str(
                    (
                        (
                            feature.get("properties")
                            if isinstance(feature.get("properties"), dict)
                            else {}
                        ).get("geometry_artifact")
                        or {}
                    ).get("projectedVisualGeometryHash")
                    or ""
                )
                for feature in features
            ],
            final_legal_geometry_hashes=[
                str(
                    (
                        (
                            feature.get("properties")
                            if isinstance(feature.get("properties"), dict)
                            else {}
                        ).get("geometry_artifact")
                        or {}
                    ).get("finalLegalGeometryHash")
                    or ""
                )
                for feature in features
            ],
            exact_mesh_payload_hashes=[
                _exact_compilation_mesh_payload_hash(compilation)
                for compilation in archive_compilations
            ],
        )
        for row, evidence, feature in zip(rows, render_evidence, features):
            feature_props = (
                feature.get("properties")
                if isinstance(feature.get("properties"), dict)
                else {}
            )
            geometry_artifact = (
                feature_props.get("geometry_artifact")
                if isinstance(
                    feature_props.get("geometry_artifact"),
                    dict,
                )
                else {}
            )
            evidence["final_semantic_anchor"] = deepcopy(
                feature_props.get("final_semantic_anchor") or {}
            )
            evidence["semantic_projection_audit"] = deepcopy(
                geometry_artifact.get("semanticProjectionAudit") or {}
            )
            evidence["certified_mass_artifact_core_hash"] = str(
                feature_props.get("certified_mass_artifact_core_hash") or ""
            )
            row["archive_render_evidence"] = evidence
        law_batch_requests: list[
            tuple[ExecutionIdentity, dict[str, Any]]
        ] = []
        law_identities: list[ExecutionIdentity] = []
        for index, (
            candidate,
            feature,
            certified_compilation,
        ) in enumerate(zip(selected, features, archive_compilations)):
            props = feature["properties"]
            artifact = props["geometry_artifact"]
            downstream_row = (
                downstream_rows[index]
                if index < len(downstream_rows)
                and isinstance(downstream_rows[index], dict)
                else {}
            )
            capacity_plan_hash = resolve_floor_capacity_plan_identity(
                program=certified_compilation.program,
                shared_floor_contract=(
                    candidate.source.metadata.get(
                        "shared_floor_contract"
                    )
                    if isinstance(
                        candidate.source.metadata.get(
                            "shared_floor_contract"
                        ),
                        dict,
                    )
                    else None
                ),
                unresolved=(
                    "FLOOR_CAPACITY_PLAN_HASH_UNRESOLVED"
                ),
            )
            identity = ExecutionIdentity(
                execution_id=(
                    f"book:{slug}:"
                    f"{rows[index].get('variant_id') or index + 1}"
                ),
                program_hash=str(
                    certified_compilation.program.program_hash() or ""
                ),
                geometry_hash=str(
                    artifact.get("finalLegalGeometryHash") or ""
                ),
                floor_capacity_plan_hash=capacity_plan_hash,
                pnu=str(pnu),
            )
            law_identities.append(identity)
            law_batch_requests.append((
                identity,
                {
                    "law": deepcopy(
                        downstream_row.get("legal_projection") or {}
                    ),
                    "building_type": building_type,
                },
            ))
        law_agent_evidence = collect_law_agent_evidence_batch(
            law_batch_requests
        )
        law_graph_evidence_program_hard_pass = True
        for index, (
            candidate,
            feature,
            certified_compilation,
            evidence,
            identity,
            law_evidence,
        ) in enumerate(zip(
            selected,
            features,
            archive_compilations,
            render_evidence,
            law_identities,
            law_agent_evidence,
        )):
            props = feature["properties"]
            artifact = props["geometry_artifact"]
            downstream_row = (
                downstream_rows[index]
                if index < len(downstream_rows)
                and isinstance(downstream_rows[index], dict)
                else {}
            )
            final_hash = str(
                artifact.get("finalLegalGeometryHash") or ""
            )
            authoritative_identity_hash = str(
                (artifact.get("identity") or {}).get("geometryHash") or ""
            )
            passport = selected_candidate_execution_passport(
                compilation={
                    "execution_passport": {},
                    "certified_compilation": certified_compilation,
                    "archive_render_evidence": evidence,
                    "combined_hard_pass": bool(
                        (artifact.get("hardGates") or {}).get(
                            "combinedHardPass"
                        )
                    ),
                },
                downstream_row=downstream_row,
                source_metadata=candidate.source.metadata,
                program_evidence=props.get("program_massing_evidence") or {},
                descriptor=_candidate_language_descriptor(candidate),
                pnu=pnu,
                candidate_finalization_evidence=(
                    rows[index].get("candidate_finalization_evidence")
                    if isinstance(
                        rows[index].get(
                            "candidate_finalization_evidence"
                        ),
                        dict,
                    )
                    else None
                ),
                expected_finalization_identity={
                    "program_hash": identity.program_hash,
                    "final_geometry_hash": final_hash,
                    "visual_hash": authoritative_identity_hash,
                },
                allow_relaxed_finalization=bool(
                    allow_relaxed_finalization
                ),
            )
            _synchronize_finalization_publish_authority(
                passport=passport,
                artifact=artifact,
                downstream_row=downstream_row,
                final_row=rows[index],
            )
            if allow_relaxed_finalization:
                if authoritative_identity_hash and not passport.get("visual_hash"):
                    passport["visual_hash"] = authoritative_identity_hash
                    passport.setdefault("stages", []).append(
                        {
                            "id": "passport_visual_hash_relaxed_override",
                            "label": "Passport visual hash relaxed override",
                            "status": "not_evaluated",
                            "required_for_final": False,
                            "node_ids": [],
                            "evidence": {
                                "status": "warn",
                                "reason": (
                                    "passport visual_hash was empty, "
                                    "aligned to authoritative geometry "
                                    "identity in diagnostic/smoke mode"
                                ),
                                "authoritative_geometry_hash": (
                                    authoritative_identity_hash
                                ),
                            },
                        }
                    )
            for passport_stage in passport.get("stages") or ():
                if (
                    isinstance(passport_stage, dict)
                    and passport_stage.get("id") == "render"
                    and isinstance(passport_stage.get("evidence"), dict)
                ):
                    passport_stage["evidence"][
                        "final_legal_geometry_hash"
                    ] = final_hash
                    break
            rows[index]["final_legal_geometry_hash"] = final_hash
            finalization = (
                rows[index].get("candidate_finalization_evidence")
                if isinstance(
                    rows[index].get("candidate_finalization_evidence"),
                    dict,
                )
                else {}
            )
            artifact.update({
                "legalFloorFieldHash": str(
                    finalization.get("legal_floor_field_hash") or ""
                ),
                "candidateActualGfaStopHash": str(
                    finalization.get(
                        "candidate_actual_gfa_stop_hash"
                    )
                    or ""
                ),
                "candidateActualGfaStopCertificate": deepcopy(
                    finalization.get(
                        "candidate_actual_gfa_stop_certificate"
                    )
                    or {}
                ),
            })
            persisted_law = persist_selected_law_agent_evidence(
                selected_row=downstream_row,
                passport=passport,
                geometry_artifact=artifact,
                evidence=law_evidence,
                expected_identity=identity,
            )
            rows[index].update(deepcopy(persisted_law))
            rows[index].update({
                "selected_execution_id": identity.execution_id,
                "final_legal_program_hash": identity.program_hash,
                "floor_capacity_plan_hash": (
                    identity.floor_capacity_plan_hash
                ),
                "combined_hard_pass": bool(
                    downstream_row.get("combined_hard_pass")
                ),
            })
            law_graph_evidence_program_hard_pass = bool(
                law_graph_evidence_program_hard_pass
                and persisted_law["law_graph_evidence_hard_pass"]
            )
            parking_gate = (
                downstream_row.get("parking_hard_gate")
                if isinstance(
                    downstream_row.get("parking_hard_gate"),
                    dict,
                )
                else {}
            )
            parking_requirement = (
                parking_gate.get("requirement")
                if isinstance(parking_gate.get("requirement"), dict)
                else {}
            )
            parking_rule_source = str(
                parking_gate.get("rule_repository_source")
                or parking_requirement.get("rule_repository_source")
                or ""
            )
            parking_graph_status = str(
                parking_gate.get("graph_status")
                or parking_requirement.get("graph_status")
                or ""
            )
            parking_provenance = {
                "parking_rule_source": parking_rule_source,
                "parking_graph_status": parking_graph_status,
            }
            rows[index].update(parking_provenance)
            downstream_row.update(parking_provenance)
            passport.update(deepcopy(parking_provenance))
            artifact.update(deepcopy(parking_provenance))
            downstream_row["mass_execution_passport"] = deepcopy(
                passport
            )
            rows[index]["mass_execution_passport"] = deepcopy(passport)
            artifact["executionPassport"] = passport
            props["mass_execution_passport"] = passport
            rows[index]["authoritative_geometry_artifact"] = deepcopy(
                artifact
            )
            render_authority = (
                rows[index].get("archive_render_evidence")
                if isinstance(
                    rows[index].get("archive_render_evidence"), dict
                )
                else {}
            )
            rows[index]["final_semantic_anchor"] = deepcopy(
                render_authority.get("final_semantic_anchor") or {}
            )
            rows[index]["semantic_projection_audit"] = deepcopy(
                artifact.get("semanticProjectionAudit") or {}
            )
            rows[index]["certified_mass_artifact_core_hash"] = str(
                render_authority.get("certified_mass_artifact_core_hash")
                or ""
            )
        outcome_graph.observe_portfolio_render(
            program_slug=slug,
            candidates=selected,
            render_features=features,
            board_path=board,
            render_evidence=render_evidence,
        )
        board_paths.append(board)
        if runtime_live_vlm and selected:
            try:
                portfolio_vlm_audit = score_portfolio_board_with_openai_vlm(
                    image_path=board,
                    program_context={
                        **program_reference_contract(building_type),
                        "site_access_side_in_program_frame": _site_access_side_in_principal_frame(
                            generation_site,
                            site_access_geometry,
                        ),
                    },
                    candidate_summaries=[{
                        "candidate_id": row["variant_id"],
                        "book_scope": str((row.get("book_scope") or {}).get("base_volume_label") or ""),
                        "capacity_alternative_id": row.get("capacity_alternative_id"),
                        "capacity_target_utilization": row.get("capacity_target_utilization"),
                        "capacity_achieved_utilization": row.get("capacity_achieved_utilization"),
                        "base_seed": str((row.get("design_concept") or {}).get("base_seed") or ""),
                        "body_phenotype": row.get("body_phenotype"),
                        "roof_archetype": row.get("roof_archetype"),
                        "ground_strategy": row.get("ground_strategy"),
                        "design_concept_key": row.get("design_concept_key"),
                        "geometry_family": _geometry_program_family(candidate),
                        "form_bank_lane": _geometry_program_metadata(candidate).get("form_bank_lane"),
                        "chassis_family": row.get("chassis_family"),
                        "program_hash": str(
                            row.get("final_legal_program_hash")
                            or _candidate_program_hash(candidate)
                            or ""
                        ),
                        "geometry_hash": str(
                            row.get("final_legal_geometry_hash")
                            or (
                                (
                                    row.get("authoritative_geometry_artifact")
                                    or {}
                                ).get("identity")
                                or {}
                            ).get("geometryHash")
                            or ""
                        ),
                    } for row, candidate in zip(rows, selected)],
                    reference_matches=[{
                        "local_path": str(path),
                        "title": Path(str(path)).stem,
                        "selection_role": "counterfactual",
                        "source": "portfolio_vlm_directive",
                    } for path in (
                        visual_directive_payload.get("reference_images")
                        or ()
                    )[:2]],
                )
                portfolio_vlm_audit = enrich_portfolio_vlm_feedback(
                    portfolio_vlm_audit,
                    rows=rows,
                    candidates=selected,
                )
                portfolio_vlm_audit["evaluated"] = True
            except Exception as exc:
                portfolio_vlm_audit = {
                    "schema_version": "arr.maas.portfolio_visual_audit.v1",
                    "status": "call_failed",
                    "hard_pass": False,
                    "candidate_count": len(selected),
                    "failure_reasons": ["portfolio_vlm_call_failed"],
                    "error": f"{type(exc).__name__}:{str(exc)[:240]}",
                    "legal_or_parking_score": False,
                }
            outcome_graph.observe_portfolio_vlm_audit(
                program_slug=slug,
                candidate_geometry_hashes=[
                    str((candidate.source.metadata.get("geometry_program_bridge_evidence") or {}).get("geometry_hash") or "")
                    for candidate in selected
                ],
                audit=portfolio_vlm_audit,
            )
        else:
            portfolio_vlm_audit = {
                "schema_version": "arr.maas.portfolio_visual_audit.v1",
                "status": (
                    "not_requested"
                    if not runtime_live_vlm
                    else "no_selected_candidates"
                ),
                # Not evaluated is not a visual approval.  Overall non-live
                # diagnostics remain governed by their numeric gates, while
                # this field now reports the VLM state truthfully.
                "hard_pass": False,
                "evaluated": False,
                "candidate_count": len(selected),
                "legal_or_parking_score": False,
            }
        counts["portfolio_vlm_audit"] = deepcopy(portfolio_vlm_audit)
        near_duplicates = sum(
            1
            for index, left in enumerate(selected)
            for right in selected[:index]
            if _silhouette_distance(left, right)
            < PORTFOLIO_SILHOUETTE_DISTANCE
        )
        failures = []
        if not law_graph_evidence_program_hard_pass:
            failures.append(
                "law_graph_agent_evidence_hard_gate_failed"
            )
        if runtime_live_vlm and not portfolio_vlm_audit.get("hard_pass"):
            failures.append("portfolio_vlm_visual_diversity_hard_gate_failed")
        if len(selected) != selection_target:
            failures.append(f"selected_count_below_target_{selection_target}")
        operation_count = len({candidate.principle_id for candidate in selected})
        selectable_universe, _measured_capacity_universe = (
            _target_hard_pass_universe(selection_pool)
        )
        available_principle_kinds = {
            candidate.principle_kind for candidate in selectable_universe
        }
        selected_principle_kinds = {
            candidate.principle_kind for candidate in selected
        }
        count_requirements = _portfolio_count_requirements(
            selection_target=selection_target,
            required_scope_target=required_scope_target,
            available_principle_kind_count=len(available_principle_kinds),
        )
        counts["portfolio_count_requirements"] = dict(count_requirements)
        if operation_count < count_requirements["book_operation_count"]:
            failures.append("book_operation_count_below_required_target")
        if (
            len(selected_principle_kinds)
            < count_requirements["principle_kind_count"]
        ):
            failures.append("available_book_principle_kind_missing_from_portfolio")
        visual_languages: list[_Candidate] = []
        for candidate in selected:
            if all(
                _silhouette_distance(candidate, representative)
                >= PORTFOLIO_SILHOUETTE_DISTANCE
                for representative in visual_languages
            ):
                visual_languages.append(candidate)
        if len(visual_languages) < count_requirements["visual_language_count"]:
            failures.append("visual_language_count_below_required_target")
        scope_count = len({_portfolio_diversity_key(candidate) for candidate in selected})
        if scope_count < count_requirements["base_volume_scope_count"]:
            failures.append("book_base_volume_scope_count_below_required_target")
        available_capacity_alternatives = {
            _capacity_alternative_key(candidate)
            for candidate in selectable_universe
            if _capacity_alternative_key(candidate)
        }
        selected_capacity_alternatives = {
            _capacity_alternative_key(candidate)
            for candidate in selected
            if _capacity_alternative_key(candidate)
        }
        requested_capacity_alternatives = Counter(
            str(
                (
                    candidate.source.metadata.get(
                        "capacity_alternative_projection"
                    )
                    or {}
                ).get("requested_capacity_alternative_id")
                or (
                    candidate.source.metadata.get(
                        "capacity_alternative_projection"
                    )
                    or {}
                ).get("alternative_id")
                or ""
            )
            for candidate in selected
        )
        requested_capacity_alternatives.pop("", None)
        capacity_composition_objective_met = _achieved_capacity_balance_pass(
            (
                _capacity_alternative_key(candidate)
                for candidate in selected
            ),
            target_count=selection_target,
        )
        counts["capacity_alternative_diagnostics"] = {
            "authority": "diagnostic_capacity_objective",
            "hard_gate_effect": "none_diagnostic_only",
            "composition_objective_met": capacity_composition_objective_met,
            "available_achieved_bands": sorted(
                available_capacity_alternatives
            ),
            "selected_achieved_bands": sorted(
                selected_capacity_alternatives
            ),
            "selected_achieved_band_counts": dict(sorted(Counter(
                _capacity_alternative_key(candidate)
                for candidate in selected
                if _capacity_alternative_key(candidate)
            ).items())),
            "selected_requested_alternative_counts": dict(
                sorted(requested_capacity_alternatives.items())
            ),
            "missing_selected_alternatives": sorted(
                available_capacity_alternatives - selected_capacity_alternatives
            ),
            "selected_target_miss_count": sum(
                1
                for candidate in selected
                if _capacity_alternative_key(candidate)
                and not resolve_capacity_band_evidence(
                    candidate.source.metadata.get(
                        "capacity_alternative_projection"
                    )
                    or {},
                    capacity_measurement=candidate.source.metadata.get(
                        "source_capacity_measurement"
                    )
                    or {},
                )["resolved_capacity_hard_pass"]
            ),
        }
        failures.extend(_portfolio_contract_morphology_failures(
            language_metrics,
            target_count=selection_target,
            visual_directive=program_visual_directive,
        ))
        if any(not row["inside_site"] or not row["program_hard_pass"] for row in rows):
            failures.append("hard_gate_failure_in_selected_portfolio")
        final_downstream_publish_gate = (
            _apply_final_downstream_publish_gate(
                failures=failures,
                downstream_rows=downstream_rows,
                selected_count=len(selected),
                smoke_mode=smoke_mode,
            )
        )
        failures = final_downstream_publish_gate["failures"]
        if len(render_evidence) != len(features) or any(
            not item.get("hard_pass") for item in render_evidence
        ):
            failures.append("accepted_mass_not_visible_in_archive_render")
        if language_metrics["dominant_seed_family_share"] > 0.40:
            failures.append("repeated_seed_footprint_family_above_40_percent")
        if language_metrics["dominant_roof_section_family_share"] > 0.50:
            failures.append("repeated_roof_section_family_above_50_percent")
        if (
            language_metrics["roof_archetype_count"] > 1
            and language_metrics["dominant_roof_archetype_share"] > 0.30
        ):
            failures.append("repeated_roof_archetype_above_30_percent")
        if max(
            language_metrics["roof_archetype_counts"].values(),
            default=0,
        ) > 3:
            failures.append("roof_archetype_count_above_3")
        missing_required_roofs = sorted(
            set(program_visual_directive.get("required_roof_archetypes") or ())
            - set(language_metrics["roof_archetype_counts"])
        )
        if missing_required_roofs:
            failures.append("vlm_required_roof_archetype_missing")
        required_phenotypes = set(program_visual_directive.get("required_solid_phenotypes") or ())
        missing_required_phenotypes = sorted(
            required_phenotypes - set(language_metrics["solid_phenotype_counts"])
        )
        if missing_required_phenotypes:
            failures.append("required_solid_phenotype_missing")
        wedge_cap = int(program_visual_directive.get("max_wedge_like_count", max(3, len(selected) // 5)))
        if language_metrics["wedge_like_count"] > wedge_cap:
            failures.append("wedge_like_count_above_measured_cap")
        pyramidal_cap = int(program_visual_directive.get("max_pyramidal_like_count", 2))
        if language_metrics["pyramidal_like_count"] > pyramidal_cap:
            failures.append("pyramidal_like_count_above_measured_cap")
        if language_metrics["ground_strategy_count"] < 3:
            failures.append("ground_strategy_count_below_3")
        if (
            site_access_geometry
            and language_metrics["frontage_aligned_public_threshold_count"] < 1
        ):
            failures.append("frontage_aligned_public_threshold_missing")
        if language_metrics["maximum_design_concept_key_repeat"] > 2:
            failures.append("design_concept_key_repeated_above_2")
        if language_metrics["missing_required_design_concept_count"]:
            failures.append("required_design_concept_controller_missing")
        if smoke_mode:
            if len(selected) != selection_target:
                failures.append("smoke_portfolio_target_not_met")
            if any(
                not _smoke_pre_downstream_candidate_pass(
                    selected[index],
                    row,
                )
                for index, row in enumerate(rows)
            ):
                failures.append("smoke_mass_hard_gate_failed")
            if len(render_evidence) != len(features) or any(
                not item.get("hard_pass") for item in render_evidence
            ):
                failures.append("smoke_mass_not_visible_in_render")
        exact_vlm_hard_pass_count = sum(
            bool(
                (
                    candidate.source.metadata.get("final_book_vlm_audit")
                    or {}
                ).get("hard_pass")
            )
            for candidate in selected
        )
        llm_authored_selected_count = sum(
            _llm_authored_candidate(
                candidate,
                codex_admission=(
                    agent_authored_admission
                    if agent_authored_manifest_active
                    else None
                ),
            )
            for candidate in selected
        )
        codex_oauth_selected_count = sum(
            is_validated_codex_oauth_candidate(
                candidate,
                admission=agent_authored_admission,
            )
            for candidate in selected
        )
        counts["llm_authored_selected_count"] = (
            llm_authored_selected_count
        )
        if agent_authored_manifest_active:
            counts["codex_oauth_llm_authored_selected_count"] = (
                codex_oauth_selected_count
            )
        portfolio_completion = evaluate_portfolio_completion(
            portfolio_requirement,
            selected_count=len(selected),
            selected_scope_count=scope_count,
            runtime_live_vlm=runtime_live_vlm,
            exact_vlm_hard_pass_count=exact_vlm_hard_pass_count,
            require_llm_authored_ast=llm_authorship_required,
            llm_authored_selected_count=llm_authored_selected_count,
            portfolio_vlm_audit=portfolio_vlm_audit,
        )
        portfolio_completion = _bind_trusted_codex_completion(
            portfolio_completion,
            manifest_required=agent_authored_manifest_active,
            selected_count=len(selected),
            trusted_codex_selected_count=codex_oauth_selected_count,
        )
        failures.extend(
            failure
            for failure in portfolio_completion["failures"]
            if failure not in failures
        )
        authoritative_measurements = [
            measure_authoritative_geometry_artifact(
                row.get("authoritative_geometry_artifact"),
                expected_program_hash=str(
                    (
                        row.get("authoritative_geometry_artifact", {})
                        .get("identity", {})
                        .get("programHash")
                    )
                    or row.get("final_legal_program_hash")
                    or ""
                ),
                expected_final_geometry_hash=str(
                    row.get("final_legal_geometry_hash") or ""
                ),
                expected_visual_hash=str(
                    (
                        row.get("mass_execution_passport")
                        if isinstance(
                            row.get("mass_execution_passport"),
                            dict,
                        )
                        else {}
                    ).get("visual_hash")
                    or (
                        row.get("authoritative_geometry_artifact", {})
                        .get("identity")
                        or {}
                    ).get("geometryHash")
                    or ""
                ),
                semantic_projection_hard_gate=(
                    row.get("semantic_projection_hard_gate")
                    if isinstance(
                        row.get("semantic_projection_hard_gate"),
                        dict,
                    )
                    else {}
                ),
                expected_section_geometry_binding_hash=str(
                    (
                        row.get("final_semantic_anchor")
                        if isinstance(
                            row.get("final_semantic_anchor"),
                            dict,
                        )
                        else {}
                    ).get("expected_section_geometry_binding_hash")
                    or ""
                ),
                final_semantic_anchor=(
                    row.get("final_semantic_anchor")
                    if isinstance(row.get("final_semantic_anchor"), dict)
                    else None
                ),
                semantic_projection_audit=(
                    row.get("semantic_projection_audit")
                    if isinstance(
                        row.get("semantic_projection_audit"), dict
                    )
                    else None
                ),
                expected_certified_mass_artifact_core_hash=str(
                    row.get("certified_mass_artifact_core_hash") or ""
                ),
            )
            for row in rows
        ]
        certified_gestalt_keys = [
            measurement.gestalt_key
            for measurement in authoritative_measurements
        ]
        certified_morphologies = [
            measurement.morphology
            for measurement in authoritative_measurements
        ]
        for downstream_index, (
            row,
            measurement,
            morphology,
        ) in enumerate(zip(
            rows,
            authoritative_measurements,
            certified_morphologies,
        )):
            gestalt_key = measurement.gestalt_key
            row["certified_gestalt_key"] = gestalt_key.to_payload()
            row["certified_mesh_evidence"] = (
                build_certified_mesh_gestalt_evidence(
                    gestalt_key=gestalt_key,
                    visual_hash=measurement.visual_hash,
                    exact_mesh_payload_hash=(
                        measurement.exact_mesh_payload_hash
                    ),
                    morphology=morphology,
                )
            )
            render_binding = row.get("archive_render_evidence")
            if isinstance(render_binding, dict):
                render_binding["morphology_payload_hash"] = (
                    certified_mesh_morphology_payload_hash(
                        morphology
                    )
                )
            row.update(deepcopy(morphology))
            row["visible_stepped"] = bool(gestalt_key.visible_stepped)
            if downstream_index < len(downstream_rows):
                downstream_row = downstream_rows[downstream_index]
                if isinstance(downstream_row, dict):
                    row["legal_projection"] = deepcopy(
                        downstream_row.get("legal_projection") or {}
                    )
                    row["parking_hard_gate"] = deepcopy(
                        downstream_row.get("parking_hard_gate") or {}
                    )
                    _persist_final_downstream_authority(
                        row,
                        downstream_row,
                    )
        selected_pair_comparisons = []
        for right_index, right_key in enumerate(certified_gestalt_keys):
            for left_index in range(right_index):
                left_key = certified_gestalt_keys[left_index]
                same_body = (
                    certified_morphologies[left_index][
                        "body_phenotype"
                    ]
                    == certified_morphologies[right_index][
                        "body_phenotype"
                    ]
                )
                same_roof = (
                    certified_morphologies[left_index][
                        "roof_archetype"
                    ]
                    == certified_morphologies[right_index][
                        "roof_archetype"
                    ]
                )
                required_distance = competition_pair_required_distance(
                    target_count=selection_target,
                    same_body_phenotype=same_body,
                    same_roof_archetype=same_roof,
                )
                measured_distance = competition_gestalt_distance(
                    left_key,
                    right_key,
                )
                selected_pair_comparisons.append({
                    "left_variant_id": rows[left_index]["variant_id"],
                    "right_variant_id": rows[right_index]["variant_id"],
                    "distance": measured_distance,
                    "required_distance": required_distance,
                    "same_body_phenotype": same_body,
                    "same_roof_archetype": same_roof,
                    "hard_pass": measured_distance >= required_distance,
                })
        selected_pair_certificate = {
            "schema_version": (
                "arr.maas.competition_gestalt_pair_certificate.v1"
            ),
            "measurement_authority": "certified_final_mesh",
            "expected_pair_count": (
                len(rows) * (len(rows) - 1) // 2
            ),
            "pair_count": len(selected_pair_comparisons),
            "hard_pass": all(
                pair["hard_pass"]
                for pair in selected_pair_comparisons
            ),
            "pairs": selected_pair_comparisons,
        }
        program_results.append({
            "program": building_type,
            "slug": slug,
            "status": "pass" if not failures else "fail",
            "selected_count": len(selected),
            "portfolio_requirement": portfolio_requirement.to_evidence(),
            "portfolio_completion": portfolio_completion,
            "agent_authored_manifest_supply": deepcopy(
                agent_authored_manifest_evidence
            ),
            "book_operation_count": operation_count,
            "book_principle_kind_counts": {
                kind: sum(candidate.principle_kind == kind for candidate in selected)
                for kind in ("base_operative", "combination", "aggregation", "case_study")
            },
            "visual_language_count": len(visual_languages),
            "book_base_volume_scope_count": scope_count,
            "book_base_volume_scopes": sorted({_portfolio_diversity_key(candidate) for candidate in selected}),
            "capacity_alternative_count": len(selected_capacity_alternatives),
            "capacity_alternatives": sorted(selected_capacity_alternatives),
            "near_duplicate_pair_count": near_duplicates,
            "portfolio_vlm_audit": deepcopy(portfolio_vlm_audit),
            "archive_render_evidence": {
                "card_count": len(render_evidence),
                "visible_mass_card_count": sum(bool(item.get("hard_pass")) for item in render_evidence),
                "minimum_rendered_mass_pixel_ratio": round(min(
                    (float(item.get("rendered_mass_pixel_ratio") or 0.0) for item in render_evidence),
                    default=0.0,
                ), 5),
                "direct_png_review_required": True,
            },
            "program_language_metrics": language_metrics,
            "program_dimensional_context": dimensional_context,
            "floor_capacity_plan": deepcopy(floor_capacity_plan),
            "vlm_portfolio_directive": {
                "active": bool(runtime_live_vlm or program_visual_directive),
                "provider": (
                    visual_directive_payload.get("provider")
                    if program_visual_directive
                    else ("openai_program_conditioned_vlm" if runtime_live_vlm else None)
                ),
                "runtime_live_vlm_requested": runtime_live_vlm,
                "typed_graph_mutation_count": len(typed_graph_mutations),
                "geometry_synthesis_request_count": int(counts.get("geometry_synthesis_request_count") or 0),
                "geometry_synthesis_request_source": counts.get("geometry_synthesis_request_source"),
                "geometry_program_llm_author_status_counts": counts.get("geometry_program_llm_author_status_counts") or {},
                "geometry_program_llm_author_active_seed_count": int(
                    counts.get("geometry_program_llm_author_active_seed_count") or 0
                ),
                "geometry_program_prebook_vlm_quarantined_seed_count": int(
                    counts.get("geometry_program_prebook_vlm_quarantined_seed_count") or 0
                ),
                "geometry_program_vlm_status_counts": counts.get("geometry_program_vlm_status_counts") or {},
                "geometry_program_vlm_causal_trace": counts.get("geometry_program_vlm_causal_trace") or {},
                "required_roof_archetypes": list(program_visual_directive.get("required_roof_archetypes") or ()),
                "required_solid_phenotypes": list(program_visual_directive.get("required_solid_phenotypes") or ()),
                "required_geometry_program_families": list(
                    program_visual_directive.get("required_geometry_program_families") or ()
                ),
                "required_chassis_families": list(
                    program_visual_directive.get("required_chassis_families") or ()
                ),
                "portfolio_memory_directive": deepcopy(memory_visual_directive),
                "max_geometry_family_counts": dict(
                    program_visual_directive.get("max_geometry_family_counts") or {}
                ),
                "max_chassis_family_counts": dict(
                    program_visual_directive.get("max_chassis_family_counts") or {}
                ),
                "max_wedge_like_count": wedge_cap,
                "max_pyramidal_like_count": pyramidal_cap,
            },
            "downstream_hard_gate": downstream_hard_gate,
            "portfolio_evaluation": portfolio_evaluation,
            "selected_pair_certificate": selected_pair_certificate,
            "counts": counts,
            "failures": failures,
            "missing_vlm_required_roof_archetypes": missing_required_roofs,
            "missing_required_solid_phenotypes": missing_required_phenotypes,
            "duration_seconds": round(perf_counter() - started, 3),
            "smoke_mode": bool(smoke_mode),
            "rows": rows,
            "png": str(board),
        })
    summary_board = output_dir / "maas-book-programs-60-summary.png"
    images = [Image.open(path).convert("RGB") for path in board_paths]
    combined = Image.new("RGB", (max(image.width for image in images), sum(image.height for image in images)), "#07111f")
    y = 0
    for image in images:
        combined.paste(image, (0, y))
        y += image.height
    combined.save(summary_board)
    book_program_numeric_status = "pass" if all(item["status"] == "pass" for item in program_results) else "fail"
    downstream_status = (
        "pass"
        if program_results and all(item["downstream_hard_gate"]["status"] == "pass" for item in program_results)
        else ("not_run" if all(item["downstream_hard_gate"]["status"] == "not_run" for item in program_results) else "fail")
    )
    result = {
        "schema_version": "arr.maas.book_program_portfolios.v1",
        "status": "pass" if book_program_numeric_status == "pass" and downstream_status in {"pass", "not_run"} else "fail",
        "book_program_numeric_status": book_program_numeric_status,
        "downstream_hard_gate_status": downstream_status,
        "pnu": pnu,
        "site_area_m2": round(float(site.area), 3),
        "program_count": len(program_results),
        "smoke_mode": bool(smoke_mode),
        "programs": program_results,
        "cross_program_language_comparison": _cross_program_language_comparison(
            selected_by_program,
            metrics_by_program,
        ),
        "legal_parking_checked": downstream_status != "not_run",
        "visual_duplicate_metric": "pose-invariant top/front/side silhouette distance",
        "summary_png": str(summary_board),
        "phase_durations_seconds": {
            phase: max(float(duration), 1e-9)
            for phase, duration in phase_durations_seconds.items()
        },
        "paid_provider_budget": paid_provider_budget_snapshot(),
        "agent_authored_manifest_supply": deepcopy(
            agent_authored_manifest_evidence
        ),
    }
    result["legal_mass_archive"] = _legal_mass_archive_portfolio_summary(
        program_results
    )
    attach_legal_mass_archive_boards(result, output_dir=output_dir)
    review_fingerprint_payload = [
        {
            "slug": item["slug"],
            "status": item["status"],
            "selected": [
                (
                    row.get("source_sequence"), row.get("book_principle_id"),
                    (row.get("book_scope") or {}).get("base_volume_label"),
                    row.get("solid_phenotype"), row.get("roof_archetype"),
                )
                for row in item.get("rows") or ()
            ],
        }
        for item in program_results
    ]
    result["visual_review_fingerprint"] = hashlib.sha256(
        json.dumps(review_fingerprint_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    outcome_graph_payload = outcome_graph.save()
    # Preserve a self-contained evidence snapshot beside every PNG/summary.
    # An explicitly supplied transfer graph remains separate and is never
    # mistaken for the run-owned provenance shard.
    if outcome_graph_snapshot_path.resolve() != outcome_graph_path.resolve():
        snapshot_temporary = outcome_graph_snapshot_path.with_suffix(
            outcome_graph_snapshot_path.suffix + ".tmp"
        )
        snapshot_temporary.write_text(
            json.dumps(outcome_graph_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        snapshot_temporary.replace(outcome_graph_snapshot_path)
    result["geometry_mutation_outcome_graph"] = {
        "status": "materialized",
        "path": str(outcome_graph_path),
        "snapshot_path": str(outcome_graph_snapshot_path),
        "path_policy": (
            "explicit_controlled_memory"
            if outcome_graph_path_was_explicit
            else "default_run_local_provenance"
        ),
        "persistent_across_output_directories": bool(outcome_graph_path_was_explicit),
        "node_count": outcome_graph_payload["node_count"],
        "edge_count": outcome_graph_payload["edge_count"],
        "observation_count": outcome_graph_payload["observation_count"],
        "neo4j_mirror": outcome_graph.mirror_to_neo4j(),
    }
    geometry_artifact_records = []
    for sequence in mass_brain_trace_sequences:
        feature = mass_brain_trace_features.get(sequence.name) or {}
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        artifact = props.get("geometry_artifact") if isinstance(props.get("geometry_artifact"), dict) else None
        if artifact is None:
            continue
        geometry_artifact_records.append({
            "trace_sequence_name": sequence.name,
            "trace_sequence_label": sequence.label,
            "legacy_verb_calls": sequence.to_list(),
            "geometry_artifact": artifact,
        })
    geometry_artifact_path = output_dir / "maas-book-exact-geometry-artifacts.json"
    geometry_artifact_path.write_text(
        json.dumps({
            "schema_version": "arr.maas.geometry_artifact_archive.v1",
            "pnu": pnu,
            "selection_effect": "none_shadow_only",
            "record_count": len(geometry_artifact_records),
            "records": geometry_artifact_records,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result["geometry_artifact_archive"] = {
        "status": "materialized",
        "path": str(geometry_artifact_path),
        "record_count": len(geometry_artifact_records),
        "program_count": len({
            str((record["geometry_artifact"] or {}).get("programType") or "")
            for record in geometry_artifact_records
        }),
    }
    result["mass_brain_geometry_trace"] = publish_geometry_portfolio_shadow(
        project_key=pnu,
        source_sequences=mass_brain_trace_sequences,
        source_features_by_sequence=mass_brain_trace_features,
        context={
            "programType": "verified_multi_program_portfolio",
            "programSlugs": [item["slug"] for item in program_results],
            "pnu": pnu,
            "outcomeGraphPath": str(outcome_graph_path),
            "selectionEffect": "none_shadow_only",
        },
    )
    visual_review_path = output_dir / "maas-book-programs-visual-review.json"
    if visual_review_path.exists():
        try:
            visual_review = json.loads(visual_review_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            visual_review = {}
        if (
            isinstance(visual_review, dict)
            and str(visual_review.get("pnu") or "") == pnu
            and str(visual_review.get("source_summary_fingerprint") or "") == result["visual_review_fingerprint"]
        ):
            result["numeric_status"] = book_program_numeric_status
            result["visual_design_review"] = visual_review
            result["visual_design_review_path"] = str(visual_review_path)
            if visual_review.get("status") == "fail":
                result["status"] = "fail"
        elif isinstance(visual_review, dict) and str(visual_review.get("pnu") or "") == pnu:
            result["visual_design_review"] = {
                "status": "not_run_for_current_fingerprint",
                "stale_review_ignored": True,
            }
    if diagnostic_target is not None:
        apply_diagnostic_summary_policy(
            result,
            target=int(diagnostic_target),
        )
    persist_book_program_summary(output_dir, result)
    return result


def persist_book_program_summary(
    output_dir: Path,
    result: dict[str, Any],
) -> Path:
    """Write one strict JSON document with normal control-character escaping."""

    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "maas-book-programs-summary.json"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    evaluations = []
    for program in result.get("programs") or ():
        if not isinstance(program, dict) or not isinstance(
            program.get("portfolio_evaluation"), dict
        ):
            continue
        evaluation = deepcopy(program["portfolio_evaluation"])
        evaluation["program_slug"] = str(
            evaluation.get("program_slug")
            or program.get("slug")
            or program.get("program")
            or ""
        )
        evaluations.append(evaluation)
    if evaluations:
        evaluation_path = directory / "maas-portfolio-evaluation.json"
        temporary = evaluation_path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump({
                "schema_version": (
                    "arr.maas.portfolio_evaluation_manifest.v1"
                ),
                "pnu": str(result.get("pnu") or ""),
                "programs": evaluations,
            }, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temporary.replace(evaluation_path)
    return path


def diagnostic_generation_budget(
    target: int | None,
) -> dict[str, Any] | None:
    """Return a bounded diagnostic search without changing production defaults."""

    if target is None:
        return None
    resolved = int(target)
    if resolved not in DIAGNOSTIC_TARGET_OPTIONS:
        raise ValueError("diagnostic target must be one of 1, 2, 3, 5, or 20")
    budget_scale_raw = os.getenv("MAAS_DIAGNOSTIC_BUDGET_SCALE", "1")
    try:
        budget_scale = max(1, int(budget_scale_raw))
    except (TypeError, ValueError):
        budget_scale = 1
    if resolved == 20:
        return {
            "scope_labels": tuple(label for label, _fraction in BASE_VOLUME_FRACTIONS),
            "parent_variant_indices": (0, 1),
            "book_probe_count": 1,
            "evaluation_cap": resolved * 12 * budget_scale,
            "candidate_cap": resolved * 4 * budget_scale,
            "replenishment_cycle_cap": 2,
        }
    diagnostic_scope_labels = tuple(
        label for label, _fraction in BASE_VOLUME_FRACTIONS
    ) if resolved == 5 else tuple(
        label for label, _fraction in BASE_VOLUME_FRACTIONS[:resolved]
    )
    return {
        "scope_labels": diagnostic_scope_labels,
        "parent_variant_indices": (0,),
        "book_probe_count": 1,
        "evaluation_cap": resolved * 12,
        "candidate_cap": resolved * 4,
        "replenishment_cycle_cap": 1,
    }


def persist_diagnostic_generation_progress(
    output_dir: Path,
    *,
    program: str,
    target: int,
    counters: dict[str, int],
    phase: str = "candidate_generation",
) -> Path:
    return update_run_progress(
        output_dir,
        phase=str(phase),
        program=str(program),
        diagnostic_target=int(target),
        evaluated_count=int(counters.get("evaluated_count") or 0),
        compiled_count=int(counters.get("compiled_count") or 0),
        program_passed_count=int(
            counters.get("program_passed_count") or 0
        ),
        candidate_cap=int(target) * 4,
    )


def apply_diagnostic_summary_policy(
    summary: dict[str, Any],
    *,
    target: int,
) -> dict[str, Any]:
    """Suppress every portfolio-completion claim for a bounded probe."""

    resolved_target = int(target)
    if resolved_target not in DIAGNOSTIC_TARGET_OPTIONS:
        raise ValueError("diagnostic target must be one of 1, 2, 3, 5, or 20")
    summary.update({
        "diagnostic_only": True,
        "diagnostic_target": resolved_target,
        "status": "diagnostic_only",
        "final_pass": False,
        "portfolio_complete": False,
    })
    for program in summary.get("programs") or ():
        if not isinstance(program, dict):
            continue
        counts = program.get("counts")
        if not isinstance(counts, dict):
            counts = {}
        selection_trace = counts.get("selection_trace")
        if not isinstance(selection_trace, dict):
            selection_trace = {}
        compatible_selected_count = int(
            selection_trace.get("portfolio_contract_solver_count")
            or program.get("selected_count")
            or 0
        )
        program["mass_progress"] = {
            "schema_version": "arr.maas.mass_progress.v1",
            "evaluated_count": int(counts.get("evaluated") or 0),
            "compiled_count": int(counts.get("compiled") or 0),
            "individual_hard_pass_count": int(
                counts.get("final_hard_pass_selection_pool_count") or 0
            ),
            "compatible_selected_count": compatible_selected_count,
            "diagnostic_target_count": resolved_target,
            "diagnostic_target_reached": bool(
                selection_trace.get("portfolio_contract_solver_target_reached")
                or compatible_selected_count >= resolved_target
            ),
            "canonical_target_count": 20,
            "canonical_complete": False,
        }
        program.update({
            "diagnostic_only": True,
            "diagnostic_target": resolved_target,
            "status": "diagnostic_only",
            "final_pass": False,
            "portfolio_complete": False,
        })
        completion = program.get("portfolio_completion")
        if not isinstance(completion, dict):
            completion = {}
            program["portfolio_completion"] = completion
        completion["hard_pass"] = False
        failures = [
            str(value)
            for value in completion.get("failures") or ()
        ]
        if "diagnostic_only_not_portfolio_acceptance" not in failures:
            failures.append("diagnostic_only_not_portfolio_acceptance")
        completion["failures"] = failures
        completion["diagnostic_only"] = True
    return summary


__all__ = [
    "PROGRAMS",
    "apply_diagnostic_summary_policy",
    "diagnostic_generation_budget",
    "persist_diagnostic_generation_progress",
    "run_book_program_portfolios",
]
