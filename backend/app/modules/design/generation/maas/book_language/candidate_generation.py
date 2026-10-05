"""Staged BOOK candidate authorship, materialization and hard gating."""

from __future__ import annotations

from dataclasses import dataclass

import hashlib
import json
import logging
import os
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from math import ceil, cos, floor, hypot, isfinite, sin
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from shapely.errors import GEOSException
from shapely.geometry import Polygon, mapping, shape

from backend.app.modules.design.generation.maas.geometry_language import GeometryAuthorError, GeometryOutcomeGraph, GeometryProgram, apply_book_projection_to_geometry_program, apply_capacity_composition_to_geometry_program, stratified_form_supply_order, universal_form_program_pages, apply_geometry_edits_compiler_safe, architectural_shape_programs, author_geometry_programs_with_openai, build_geometry_graph_notes, build_geometry_graph_snapshot, compile_geometry_program, compile_geometry_program_to_source_mass, openai_vlm_geometry_critic, project_program_requirements, reference_language_programs, recursive_book_projection_evidence, retrieve_geometry_reference_matches, run_geometry_program_a2a_loop, synthesize_architectural_programs
from backend.app.modules.design.generation.maas.paid_provider_budget import PaidProviderBudgetError, paid_provider_budget_snapshot
from backend.app.modules.design.generation.maas.geometry_language.floorwise_legal_program import is_intentional_floorwise_stepped_program
from backend.app.modules.design.generation.maas.geometry_language.floorwise_visual_projection import certified_actual_section_areas
from backend.app.modules.design.generation.maas.geometry_language.gate import GeometryGatePolicy, compilation_gate
from backend.app.modules.design.generation.maas.geometry_language.legal_field_affine_placement import select_legal_field_affine_projection
from backend.app.modules.design.generation.maas.book_language.legal_fit_deficit import build_legal_fit_deficit
from backend.app.modules.design.generation.maas.book_language.legal_mass_archive import LegalMassArchive
from backend.app.modules.design.generation.maas.book_language.stage_outcome import StageOutcome, record_stage_outcome
from backend.app.modules.design.generation.maas.book_language.authorship_policy import bounded_llm_author_batch_count
from backend.app.modules.design.generation.maas.design_space import COVERAGE_BANDS, delivered_ground_take_band, delivered_void_band, plan_area_for_band
from backend.app.modules.design.generation.maas.geometry_language.source_bridge import compile_normalized_geometry_program_to_source_mass, compile_site_bound_geometry_program_to_source_mass, materialize_floorwise_legal_source, normalized_component_layout, source_surface_payload_hash, source_volume_payload_hash
from backend.app.modules.design.generation.maas.geometry_language.projected_visual_contract import canonical_metric_surface_payload, final_floorwise_visual_geometry_hash, has_strict_height_dependent_legal_section_contraction, serialize_certified_projected_visual
from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall, VerbSequence
from backend.app.modules.design.generation.maas.program_massing import ProgramSectionGraphEdit, compose_program_with_book_operations, mutate_program_section_sequence, program_reference_contract, program_seed_sequences
from backend.app.modules.design.generation.maas.program_massing.book_projection import book_projection_calls, book_sentence_variants
from backend.app.modules.design.generation.maas.program_massing.scoring import attach_program_massing_evidence
from backend.app.modules.design.generation.maas.program_massing.morphology import authoritative_surface_morphology, authoritative_surface_silhouette_distance
from backend.app.modules.design.generation.maas.program_massing.semantic_carriers import REQUIRED_RELATIONS, bind_source_role_scaffold_to_program, build_program_semantic_carrier_evidence, rebind_semantic_projection_capacity, semantic_capacity_measurement_hash, semantic_site_context_hash
from backend.app.modules.design.generation.maas.program_massing.search import program_seed_variants, source_feature
from backend.app.modules.design.generation.maas.preference.loop import feature_preview_png
from backend.app.modules.design.generation.maas.source_geometry import compile_sequence_to_source_mass
from backend.app.modules.design.generation.maas.shared_floor_contract import bind_shared_floor_contract_capacity, materialize_shared_floor_contract

from backend.app.modules.design.generation.maas.book_language.candidate_analysis import _Candidate, _clean_mass_gate, _inside_site, _program_form_gate, _section_family, _seed_family, _seed_is_llm_authored, _site_access_side_in_principal_frame, _solid_morphology_metrics
from backend.app.modules.design.generation.maas.book_language.candidate_floor_authority import _capacity_pack_retry_eligible, _capacity_retry_required, _candidate_floor_context, _compact_candidate_capacity_evidence, _shared_floor_capacity_measurement as _measure_candidate_floor_capacity
from backend.app.modules.design.generation.maas.book_language.capacity_contract import evaluate_legal_capacity_authority, measure_source_capacity, recursive_plan_coverage_floor
from backend.app.modules.design.generation.maas.book_language.mass_passport_bridge import resolve_capacity_band_evidence
from backend.app.modules.design.generation.maas.book_language.capacity_alternatives import CAPACITY_ALTERNATIVE_SPECS, build_capacity_alternative, coverage_band_of_alternative, capacity_fit_score, capacity_retry_floor_targets, capacity_retry_plan_coverage, capacity_contract_with_retry_targets, capacity_alternative_for_host, capacity_contract_for_alternative, evaluate_capacity_alternative


logger = logging.getLogger(__name__)

GEOMETRY_RETRY_POLICY = "measured_typed_ast_capacity_composition"
from backend.app.modules.design.generation.maas.book_language.competition_candidate_screen import _capacity_alternative_schedule_index, _cheap_ast_bounds, _cheap_morphology_preclassification, _cheap_typed_ast_candidate_evidence, _balanced_principle_window_with_lineage_bases, _lineage_stable_scope_label, _competition_cheap_candidate_records, _competition_pre_exact_shortlist, _diagnostic_generation_cap_reached, _legal_section_dimensions, _recursive_principle_schedule_limit, competition_breadth_generation_budget, resolve_competition_breadth_generation_budget
from backend.app.modules.design.generation.maas.book_language.diagnostic_anchor_scheduler import diagnostic_anchor_capacity_schedule_index, diagnostic_anchor_schedule_active, diagnostic_anchor_principles, diagnostic_anchor_sentence_variants, diagnostic_anchor_scope, diagnostic_anchor_spec, schedule_diagnostic_anchor_parents
from backend.app.modules.design.generation.maas.book_language.variation_lattice import book_probe_scope, book_variation_indices
from backend.app.modules.design.generation.maas.book_language.downstream_hard_gate import LegalGenerationContext, fit_source_to_sunlight_field, generation_site_at_height
from backend.app.modules.design.generation.maas.book_language.gate_diagnostics import _empty_gate_diagnostic, _merge_gate_diagnostics, _record_gate_diagnostic, _summarize_gate_diagnostic
from backend.app.modules.design.generation.maas.book_language.lineage import canonical_lineage_parent_key, gate_descendants_by_base, lineage_record, staged_principle_schedule
from backend.app.modules.design.generation.maas.book_language.program_catalog import PROGRAMS
from backend.app.modules.design.generation.maas.book_language.reference_context import _audited_final_book_references, _reference_language_author_context
from backend.app.modules.design.generation.maas.book_language.registry import build_book_language_registry
from backend.app.modules.design.generation.maas.book_language.semantics import BASE_VOLUME_FRACTIONS
from backend.app.modules.design.generation.maas.book_language.legal_floor_field import validate_legal_floor_field


class _PostBookVlmOnly(RuntimeError):
    """Stop pre-BOOK review after authorship; the exact final solid owns VLM."""


def _site_seed_extent(
    site: Polygon | None, height_m: float
) -> tuple[float, float, float] | None:
    """The parcel's own box: its minimum rotated rectangle, and the height.

    The same rectangle massv2 starts every sentence from - `seed_rectangle` -
    read off the polygon here rather than imported, so this layer keeps its
    one-way dependency on massv2.
    """

    if site is None or site.is_empty or float(height_m) <= 1e-9:
        return None
    rectangle = site.minimum_rotated_rectangle
    ring = getattr(rectangle, "exterior", None)
    coordinates = list(ring.coords) if ring is not None else []
    if len(coordinates) < 4:
        return None
    edges = sorted(
        hypot(right[0] - left[0], right[1] - left[1])
        for left, right in zip(coordinates, coordinates[1:])
    )
    if len(edges) < 2 or edges[-1] <= 1e-9:
        return None
    # A rectangle's ring gives each side twice, so the two dimensions are the
    # longest and the shortest - taking the top two returned the long side
    # twice and squared the parcel (57.8 x 57.8 where it is 68.7 x 54.6).
    return (float(edges[-1]), float(edges[0]), float(height_m))


def _book_graph_author_vocabulary() -> dict[str, Any]:
    """Project the canonical BOOK graph into a compact author vocabulary."""

    registry = build_book_language_registry()
    principle_fields = (
        "principle_id",
        "kind",
        "label",
        "execution_verbs",
        "generation_stage",
        "generation_stage_order",
        "lineage_base_operative_id",
        "lineage_parent_principle_id",
        "transformation",
        "cardinality",
        "aggregation_methods",
        "implementation_elements",
        "semantics",
    )
    principles = [
        {
            key: deepcopy(principle.get(key))
            for key in principle_fields
            if principle.get(key) is not None
        }
        for principle in registry["principles"]
    ]
    return {
        "schema_version": "arr.maas.book_graph_author_vocabulary.v1",
        "corpus_id": registry["corpus_id"],
        "base_volumes": deepcopy(registry["base_volumes"]),
        "principle_count": len(principles),
        "principles": principles,
    }




















def _mass_stage_design_score(
    *,
    program_fit_score: float,
    architectural_score: float,
    advisory_capacity_score: float | None = None,
) -> float:
    """Score MASS design without letting downstream capacity rank the board."""

    _ = advisory_capacity_score
    return (
        float(program_fit_score) * 0.56
        + float(architectural_score) * 0.44
    )


def _retain_candidate_with_legal_capacity_authority(
    source: Any,
    shared_floor_contract: dict[str, Any] | None,
    capacity_measurement: dict[str, Any] | None,
    capacity_contract: dict[str, Any] | None,
    *,
    capacity_projection: dict[str, Any] | None = None,
    rejection_evidence_sink: list[dict[str, Any]] | None = None,
) -> Any | None:
    """Annotate legal candidates and reject independently uncertified floors."""

    authority = evaluate_legal_capacity_authority(
        shared_floor_contract,
        capacity_measurement,
        capacity_contract,
    )
    metadata = deepcopy(source.metadata)
    metadata["source_capacity_measurement"] = deepcopy(
        capacity_measurement or {}
    )
    metadata["capacity_alternative_projection"] = deepcopy(
        capacity_projection or {}
    )
    if isinstance(shared_floor_contract, dict):
        metadata["shared_floor_contract"] = deepcopy(
            shared_floor_contract
        )
    metadata["legal_capacity_authority"] = authority
    metadata.update(authority)
    annotated = replace(source, metadata=metadata)
    if (
        authority["legal_hard_pass"] is not True
        and rejection_evidence_sink is not None
    ):
        shared = (
            shared_floor_contract
            if isinstance(shared_floor_contract, dict)
            else {}
        )
        measurement = (
            capacity_measurement
            if isinstance(capacity_measurement, dict)
            else {}
        )
        contract = (
            capacity_contract
            if isinstance(capacity_contract, dict)
            else {}
        )
        rejection_evidence_sink.append({
            "schema_version": "arr.maas.projection_authority_failure.v1",
            "failure_reason": "legal_capacity_authority_rejected",
            "failure_reasons": ["legal_capacity_authority_rejected"],
            "legal_hard_pass": False,
            "shared_floor_measured": bool(
                authority.get("shared_floor_measured")
            ),
            "shared_floor_contract_failure_reasons": sorted({
                str(reason)
                for reason in shared.get("failure_reasons") or ()
                if str(reason)
            }),
            "plate_recertification_failures": list(
                authority.get("plate_recertification_failures") or []
            ),
            "plate_recertification_failure_reasons": list(
                authority.get("plate_recertification_failure_reasons") or []
            ),
            "feasible_capacity_utilization": float(
                authority.get("feasible_capacity_utilization") or 0.0
            ),
            "capacity_objective_status": str(
                authority.get("capacity_objective_status") or "unavailable"
            ),
            "shared_floor_contract_hard_pass": (
                shared.get("hard_pass") is True
            ),
            "shared_floor_plate_count": len(
                shared.get("plates")
                if isinstance(shared.get("plates"), list)
                else ()
            ),
            "capacity_measurement_hard_pass": (
                measurement.get("hard_pass") is True
            ),
            "floor_contract_hash": str(
                measurement.get("floor_contract_hash")
                or shared.get("floor_contract_hash")
                or ""
            ),
            "legal_floor_field_hash": str(
                contract.get("legal_floor_field_hash") or ""
            ),
        })
    return annotated if authority["legal_hard_pass"] is True else None


def _admit_legal_mass_candidate(
    archive: LegalMassArchive,
    source: Any,
    *,
    compiler_clean_passed: bool,
    site_containment_passed: bool,
    rejection_evidence_sink: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Archive only a source that passed the real gates and final certificate."""

    def reject(reason: str, **evidence: Any) -> None:
        if rejection_evidence_sink is not None:
            rejection_evidence_sink.append({
                "failure_reason": reason,
                **evidence,
            })
        return None

    if not compiler_clean_passed or not site_containment_passed:
        return reject(
            "legal_archive_upstream_gate_failed",
            compiler_clean_passed=bool(compiler_clean_passed),
            site_containment_passed=bool(site_containment_passed),
        )
    metadata = source.metadata if isinstance(source.metadata, dict) else {}
    certificate = metadata.get("authored_legal_projection_certificate")
    certificate = certificate if isinstance(certificate, dict) else {}
    program_hash = str(metadata.get("final_program_hash") or "")
    geometry_hash = str(metadata.get("final_geometry_hash") or "")
    surface_payload_hash = str(
        metadata.get("final_surface_payload_hash") or ""
    )
    surfaces = tuple(getattr(source, "surfaces", ()) or ())
    try:
        actual_surface_payload_hash = source_surface_payload_hash(surfaces)
    except (TypeError, ValueError):
        return reject("legal_archive_surface_payload_hash_failed")
    if not (
        certificate.get("schema_version")
        == "arr.maas.authored_legal_projection_certificate.v1"
        and certificate.get("status") == "verified"
        and certificate.get("hard_pass") is True
        and program_hash
        and geometry_hash
        and surface_payload_hash
        and str(certificate.get("input_authored_program_hash") or "")
        == program_hash
        and str(certificate.get("projected_surface_hash") or "")
        == geometry_hash
        and str(certificate.get("projected_surface_payload_hash") or "")
        == surface_payload_hash
        and surfaces
        and actual_surface_payload_hash == surface_payload_hash
    ):
        return reject(
            "legal_archive_projection_certificate_mismatch",
            certificate_schema_version=str(certificate.get("schema_version") or ""),
            certificate_status=str(certificate.get("status") or ""),
            certificate_hard_pass=certificate.get("hard_pass") is True,
            program_hash_present=bool(program_hash),
            geometry_hash_present=bool(geometry_hash),
            surface_payload_hash_present=bool(surface_payload_hash),
            surface_payload_present=bool(surfaces),
            actual_surface_payload_hash_matches=(
                bool(surface_payload_hash)
                and actual_surface_payload_hash == surface_payload_hash
            ),
        )
    try:
        metric_payload = canonical_metric_surface_payload(source)
    except (TypeError, ValueError):
        return reject("legal_archive_metric_payload_failed")
    if (
        metric_payload["normalized_source_surface_payload_hash"]
        != surface_payload_hash
    ):
        return reject(
            "legal_archive_normalized_payload_hash_mismatch",
            normalized_surface_payload_hash=str(
                metric_payload.get("normalized_source_surface_payload_hash") or ""
            ),
            expected_surface_payload_hash=surface_payload_hash,
        )
    authority = metadata.get("legal_capacity_authority")
    authority = authority if isinstance(authority, dict) else {}
    return archive.admit({
        "geometry_hash": geometry_hash,
        "program_hash": program_hash,
        "final_authored_surface_payload": metric_payload["triangles"],
        "final_surface_payload_hash": metric_payload["surface_payload_hash"],
        "normalized_source_surface_payload_hash": surface_payload_hash,
        "surface_coordinate_frame": metric_payload["coordinate_space"],
        "policy_evidence": {
            "compiler_clean": compiler_clean_passed,
            "contained": site_containment_passed,
            "authored_surface_certified": True,
            "legal_hard_pass": authority.get("legal_hard_pass") is True,
        },
        "capacity_evidence": {
            "legal_capacity_authority": deepcopy(authority),
            "source_capacity_measurement": deepcopy(
                metadata.get("source_capacity_measurement") or {}
            ),
            "capacity_alternative_projection": deepcopy(
                metadata.get("capacity_alternative_projection") or {}
            ),
        },
        "scope": deepcopy(
            metadata.get("book_scope")
            or metadata.get("generation_scope")
            or {}
        ),
        "family": str(metadata.get("family") or ""),
        "lineage": deepcopy(metadata.get("book_generation_lineage") or {}),
    })


def _record_capacity_projection_diagnostics(
    capacity_stage_counts: Counter,
    *,
    alternative_id: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Observe advisory capacity state without gating candidate publication."""

    metadata = metadata if isinstance(metadata, dict) else {}
    projection = metadata.get("capacity_alternative_projection")
    projection = projection if isinstance(projection, dict) else {}
    authority = metadata.get("legal_capacity_authority")
    authority = authority if isinstance(authority, dict) else {}
    status = str(
        projection.get("capacity_objective_status")
        or authority.get("capacity_objective_status")
        or "unreported"
    )
    revision_recommended = bool(
        projection.get("revision_recommended")
        or authority.get("revision_recommended")
    )
    prefix = f"alternative:{str(alternative_id or 'unclassified')}"
    capacity_stage_counts[f"{prefix}:capacity_diagnostic_observed"] += 1
    capacity_stage_counts[
        f"{prefix}:capacity_objective_status:{status}"
    ] += 1
    if revision_recommended:
        capacity_stage_counts[f"{prefix}:capacity_revision_recommended"] += 1
    return {
        "capacity_objective_status": status,
        "revision_recommended": revision_recommended,
        "hard_gate": False,
    }


def _program_gate_result(
    *,
    program_evidence: dict[str, Any] | None,
    program_form_gate: dict[str, Any] | None,
    gate_pass: dict[str, bool] | None,
) -> dict[str, Any]:
    """Return the single program authority consumed by every later stage."""

    program_evidence = (
        program_evidence if isinstance(program_evidence, dict) else {}
    )
    program_form_gate = (
        program_form_gate if isinstance(program_form_gate, dict) else {}
    )
    gate_pass = gate_pass if isinstance(gate_pass, dict) else {}
    return {
        "schema_version": "arr.maas.program_gate_result.v1",
        "hard_pass": bool(
            program_evidence.get("hard_pass") is True
            and program_form_gate.get("hard_pass") is True
        ),
        "failed_gates": tuple(
            str(name) for name, passed in gate_pass.items() if not passed
        ),
        "gate_pass": dict(gate_pass),
        "program_evidence": deepcopy(program_evidence),
        "program_form_gate": deepcopy(program_form_gate),
    }


def _program_review_authority(
    *,
    archived_record: dict[str, Any] | None,
    program_gate_result: dict[str, Any] | None,
    coherence_evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep legal MASS reviewable while preserving design-quality evidence."""

    program_gate_result = (
        program_gate_result if isinstance(program_gate_result, dict) else {}
    )
    coherence_evidence = (
        coherence_evidence if isinstance(coherence_evidence, dict) else {}
    )
    failed_design_gates = tuple(program_gate_result.get("failed_gates") or ())
    program_form_gate = program_gate_result.get("program_form_gate") or {}
    design_pass = program_gate_result.get("hard_pass") is True
    archive_authority = isinstance(archived_record, dict)
    development_review_eligible = bool(archive_authority and not design_pass)
    return {
        "schema_version": "arr.maas.program_review_authority.v1",
        "hard_pass": design_pass,
        "selection_eligible": design_pass,
        "development_review_eligible": development_review_eligible,
        "release_authority": (
            "canonical_program_gate"
            if design_pass
            else (
                "developmental_base_vlm_only"
                if development_review_eligible
                else "none"
            )
        ),
        "legal_archive_authority": archive_authority,
        "design_quality_hard_gate": True,
        "design_quality_pass": design_pass,
        "failed_design_gates": list(failed_design_gates),
        "program_form_failures": list(
            program_form_gate.get("failures") or ()
        ),
        "coherence_evidence": deepcopy(coherence_evidence),
        "typed_revision_signal": {
            "active": development_review_eligible,
            "hard_gate": False,
            "route": "base_vlm_then_typed_revision",
            "reasons": list(failed_design_gates) + list(
                program_form_gate.get("failures") or ()
            ),
        },
    }


def _book_projection_stage_outcome(
    projection_evidence: dict[str, Any] | None,
) -> StageOutcome[Any]:
    evidence = dict(projection_evidence or {})
    status = str(evidence.get("status") or "missing")
    evidence.setdefault("status", status)
    if status == "materialized":
        return StageOutcome.passed("book_projection", evidence=evidence)
    reason = str(
        evidence.get("failure_reason")
        or evidence.get("book_projection_failure")
        or "book_projection_failed"
    )
    return StageOutcome.failed("book_projection", reason, evidence=evidence)


def _site_containment_stage_outcome(contained: bool) -> StageOutcome[Any]:
    evidence = {"contained": bool(contained)}
    if contained:
        return StageOutcome.passed("site_containment", evidence=evidence)
    return StageOutcome.failed(
        "site_containment",
        "containment_failed",
        evidence=evidence,
    )


def _inside_floorwise_legal_sections(
    source: Any,
    legal_sections: tuple[Polygon, ...],
) -> bool:
    """Check every legal proxy band against its own law-derived section."""

    floor_count = len(legal_sections)
    if floor_count <= 0 or any(
        not isinstance(section, Polygon)
        or section.is_empty
        or not section.is_valid
        for section in legal_sections
    ):
        return False
    try:
        for volume in source.volumes:
            bottom = float(volume.bottom_fraction)
            top = float(volume.top_fraction)
            if (
                not isfinite(bottom)
                or not isfinite(top)
                or bottom < -1e-9
                or top > 1.0 + 1e-9
                or top <= bottom + 1e-9
                or not volume.footprint.is_valid
            ):
                return False
            first = max(
                0,
                min(floor_count - 1, floor(bottom * floor_count + 1e-9)),
            )
            last = max(
                first + 1,
                min(floor_count, ceil(top * floor_count - 1e-9)),
            )
            if any(
                volume.footprint.difference(legal_sections[index]).area
                > 1e-6
                for index in range(first, last)
            ):
                return False
        return True
    except (GEOSException, TypeError, ValueError):
        return False


def _legal_archive_stage_outcome(
    archived_record: dict[str, Any] | None,
    *,
    reason: str,
    evidence: dict[str, Any],
) -> StageOutcome[Any]:
    payload = {**dict(evidence), "archive_admitted": isinstance(archived_record, dict)}
    if isinstance(archived_record, dict):
        return StageOutcome.passed(
            "legal_archive",
            evidence=payload,
            value=archived_record,
        )
    return StageOutcome.failed(
        "legal_archive",
        reason or "legal_archive_admission_failed",
        evidence=payload,
    )


def _program_review_stage_outcome(
    program_review_authority: dict[str, Any],
) -> StageOutcome[Any]:
    evidence = deepcopy(program_review_authority)
    if program_review_authority.get("selection_eligible") is True:
        return StageOutcome.passed(
            "program_review",
            evidence=evidence,
            value=program_review_authority,
        )
    if program_review_authority.get("development_review_eligible") is True:
        return StageOutcome.diagnostic(
            "program_review",
            "development_review_only",
            evidence=evidence,
            value=program_review_authority,
        )
    failed_gates = tuple(program_review_authority.get("failed_design_gates") or ())
    reason = str(failed_gates[0]) if failed_gates else "program_review_rejected"
    return StageOutcome.failed("program_review", reason, evidence=evidence)


def _empty_scope_stage_counts() -> dict[str, int]:
    """Return the authoritative per-scope generation counter schema."""

    return {
        "evaluated": 0,
        "compiled": 0,
        "projection_materialized": 0,
        "projection_failed": 0,
        "clean": 0,
        "program_passed": 0,
        "program_development_review_eligible": 0,
    }


def _record_program_scope_outcome(
    scope_counts: dict[str, int],
    program_review_authority: dict[str, Any],
) -> int:
    """Record one canonical pass or development-only program outcome."""

    if program_review_authority.get("selection_eligible") is True:
        scope_counts["program_passed"] += 1
        return 1
    if program_review_authority.get("development_review_eligible") is True:
        scope_counts["program_development_review_eligible"] += 1
    return 0


def _eligible_smoke_floor_candidate(
    source: Any,
    shared_floor_contract: dict[str, Any] | None,
    capacity_measurement: dict[str, Any] | None,
    capacity_projection: dict[str, Any] | None,
    viable_base_keys: set[str],
) -> bool:
    """Count only candidates carrying the requested shared-floor hard pass."""

    if not (
        isinstance(shared_floor_contract, dict)
        and shared_floor_contract.get("hard_pass") is True
        and isinstance(capacity_measurement, dict)
        and capacity_measurement.get("hard_pass") is True
        and isinstance(capacity_projection, dict)
        and capacity_projection.get("target_hard_pass") is True
    ):
        return False
    lineage = source.metadata.get("book_generation_lineage") or {}
    return (
        str(lineage.get("stage") or "") == "base"
        or str(lineage.get("parent_key") or "") in viable_base_keys
    )


def _proven_llm_pre_book_parent_key(
    source: Any,
    generation_lineage: dict[str, Any],
) -> str:
    """Read a lineage key only from matching, compiler-clean parent proof."""
    canonical_key = canonical_lineage_parent_key(generation_lineage)
    if not canonical_key or not isinstance(source.metadata, dict):
        return ""
    bridge = source.metadata.get("geometry_program_bridge_evidence") or {}
    proof = bridge.get("pre_book_lineage_parent_proof") or {}
    if not isinstance(bridge, dict) or not isinstance(proof, dict):
        return ""
    if not (
        bridge.get("llm_geometry_author_active") is True
        and proof.get("compiler_clean") is True
        and proof.get("contained") is True
        and str(proof.get("parent_key") or "") == canonical_key
        and str(proof.get("program_hash") or "")
        == str(bridge.get("initial_llm_authored_pre_book_program_hash") or "")
        and str(proof.get("geometry_hash") or "")
        == str(bridge.get("initial_llm_authored_pre_book_geometry_hash") or "")
    ):
        return ""
    return canonical_key


def _observe_compiler_clean_base_geometry_hash(
    bindings: dict[str, str | None],
    parent_key: str,
    geometry_hash: str,
) -> None:
    """Record one exact base hash, invalidating ambiguous parent keys."""
    canonical_key = str(parent_key or "")
    canonical_hash = str(geometry_hash or "")
    if not canonical_key or not canonical_hash:
        return
    if canonical_key not in bindings:
        bindings[canonical_key] = canonical_hash
    elif bindings[canonical_key] != canonical_hash:
        bindings[canonical_key] = None


def _bind_parent_geometry_hash(
    generation_lineage: dict[str, Any],
    bindings: dict[str, str | None],
) -> dict[str, Any]:
    """Bind descendants only to one exact compiler-clean base geometry."""
    bound = dict(generation_lineage)
    if str(bound.get("stage") or "") == "base":
        bound.pop("parent_geometry_hash", None)
        return bound
    parent_base_lineage = bound.get("parent_base_lineage") or {}
    parent_key = canonical_lineage_parent_key(parent_base_lineage)
    if not parent_key or str(bound.get("parent_key") or "") != parent_key:
        bound.pop("parent_geometry_hash", None)
        return bound
    parent_geometry_hash = bindings.get(parent_key)
    if isinstance(parent_geometry_hash, str) and parent_geometry_hash:
        bound["parent_geometry_hash"] = parent_geometry_hash
    elif not isinstance(bound.get("parent_geometry_hash"), str):
        bound.pop("parent_geometry_hash", None)
    return bound


def _source_with_book_generation_lineage(
    source: Any,
    generation_lineage: dict[str, Any],
    *,
    parent_audit: dict[str, Any] | None = None,
) -> Any:
    """Persist one immutable copy of the authorized parent/operation record."""

    metadata = deepcopy(getattr(source, "metadata", None) or {})
    metadata["book_generation_lineage"] = deepcopy(generation_lineage)
    if isinstance(parent_audit, dict):
        metadata["base_book_vlm_parent_audit"] = deepcopy(parent_audit)
    return replace(source, metadata=metadata)


def _authorize_descendant_lineage_for_materialization(
    generation_lineage: dict[str, Any],
    registry: dict[str, str | None],
    reviewed_base_audits: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    """Bind one descendant to its exact canonical reviewed BASE authority."""
    if str(generation_lineage.get("stage") or "") == "base":
        parent_base_lineage = generation_lineage
    else:
        parent_base_lineage = generation_lineage.get(
            "parent_base_lineage"
        ) or {}
    parent_key = canonical_lineage_parent_key(parent_base_lineage)
    if (
        not parent_key
        or str(generation_lineage.get("parent_key") or "") != parent_key
    ):
        return None, "lineage_parent_key_disagreement"
    if parent_key not in registry:
        return None, "unknown_parent"
    parent_geometry_hash = registry.get(parent_key)
    if parent_geometry_hash is None:
        return None, "conflicting_registry_hash"
    if not isinstance(parent_geometry_hash, str) or not parent_geometry_hash:
        return None, "unknown_parent"
    audit = reviewed_base_audits.get(parent_key)
    if not isinstance(audit, dict):
        return None, "missing_reviewed_audit"
    if str(audit.get("geometry_hash") or "") != parent_geometry_hash:
        return None, "reviewed_audit_geometry_mismatch"
    if not str(audit.get("program_hash") or ""):
        return None, "reviewed_audit_program_missing"
    expected_fingerprint = hashlib.sha256(
        json.dumps(
            {"geometry_hash": parent_geometry_hash},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if str(audit.get("base_review_fingerprint") or "") != expected_fingerprint:
        return None, "reviewed_audit_fingerprint_mismatch"
    bound = dict(generation_lineage)
    bound["parent_geometry_hash"] = parent_geometry_hash
    return bound, "authorized"


def _authorize_and_compose_descendant_candidate(
    seed: VerbSequence,
    operations: tuple[Any, ...],
    *,
    generation_lineage: dict[str, Any],
    generation_phase: str,
    registry: dict[str, str | None],
    reviewed_base_audits: dict[str, dict[str, Any]],
    name_suffix: str,
    base_volume_label: str,
    orientation: str,
) -> tuple[dict[str, Any] | None, VerbSequence | None, str]:
    """Authorize exact descendant identity before any BOOK composition."""
    authorization_reason = "not_required"
    if generation_phase == "descendant":
        generation_lineage, authorization_reason = (
            _authorize_descendant_lineage_for_materialization(
                generation_lineage,
                registry,
                reviewed_base_audits,
            )
        )
        if generation_lineage is None:
            return None, None, authorization_reason
    composed = compose_program_with_book_operations(
        seed,
        operations,
        name_suffix=name_suffix,
        base_volume_label=base_volume_label,
        orientation=orientation,
    )
    return generation_lineage, composed, authorization_reason


def _capacity_retry_result_is_selectable(
    floor_contract: dict[str, Any] | None,
    retried_capacity: dict[str, Any] | None,
    baseline_capacity: dict[str, Any] | None,
) -> bool:
    """Select only a recompiled typed AST that improves measured capacity."""

    if not all(isinstance(value, dict) for value in (
        floor_contract,
        retried_capacity,
        baseline_capacity,
    )):
        return False
    if floor_contract.get("hard_pass") is not True:
        return False
    if retried_capacity.get("hard_pass") is not True:
        return False
    retried = float(retried_capacity.get("feasible_capacity_utilization") or 0.0)
    baseline = float(baseline_capacity.get("feasible_capacity_utilization") or 0.0)
    return retried > baseline + 1e-6


def _materialize_once_for_capacity_policy(
    materializer: Callable[[float, tuple[float, ...], tuple[float, float] | None], Any],
    coverage: float,
    floor_targets: tuple[float, ...],
    capacity_composition_utilizations: tuple[float, float] | None = None,
) -> Any:
    """Materialize one authored or measured typed-composition AST."""

    return materializer(
        float(coverage),
        tuple(floor_targets),
        capacity_composition_utilizations,
    )


def _capacity_authoring_deficit(
    *,
    resolved_capacity_hard_pass: bool,
    parent_fingerprint: str,
    parent_program_hash: str,
    geometry_family: str,
    body_phenotype: str,
    scope: str,
    capacity_band: str,
    achieved_utilization: float | None,
    required_utilization: float | None,
    measured_gfa_m2: float | None,
    feasible_gfa_m2: float | None,
    achieved_floor_areas_m2: Sequence[float] | None,
    target_floor_areas_m2: Sequence[float] | None,
    terminal_materialization_reason: str = "",
) -> dict[str, Any] | None:
    if resolved_capacity_hard_pass:
        return None
    achieved = float(achieved_utilization or 0.0)
    required = float(required_utilization or 0.0)
    measured_gfa = float(measured_gfa_m2 or 0.0)
    feasible_gfa = float(feasible_gfa_m2 or 0.0)
    required_gfa = feasible_gfa * required
    payload = {
        "schema_version": "arr.maas.capacity_authoring_deficit.v1",
        "type": "capacity_authoring_deficit",
        "geometry_retry_policy": GEOMETRY_RETRY_POLICY,
        "parent_fingerprint": str(parent_fingerprint or "")[:160],
        "rejected_parent_program_hash": str(parent_program_hash or "")[:160],
        "geometry_family": str(geometry_family or "unclassified")[:96],
        "body_phenotype": str(body_phenotype or "unclassified")[:96],
        "scope": str(scope or "unclassified")[:32],
        "capacity_band": str(capacity_band or "unclassified")[:96],
        "achieved_utilization": round(achieved, 6),
        "required_minimum_utilization": (
            round(float(required_utilization), 6)
            if required_utilization is not None
            else None
        ),
        "measured_gfa_m2": round(measured_gfa, 3),
        "required_gfa_m2": round(required_gfa, 3),
        "gfa_deficit_m2": round(max(0.0, required_gfa - measured_gfa), 3),
        "terminal_materialization_reason": str(
            terminal_materialization_reason or ""
        )[:96],
    }
    achieved_floors = tuple(achieved_floor_areas_m2 or ())
    target_floors = tuple(target_floor_areas_m2 or ())
    if achieved_floors and len(achieved_floors) == len(target_floors):
        payload["per_floor_deficit_status"] = "measured"
        payload["per_floor_gfa_deficits_m2"] = [
            round(max(0.0, float(target) - float(actual)), 3)
            for actual, target in zip(achieved_floors, target_floors)
        ]
    else:
        payload["per_floor_deficit_status"] = "unavailable"
    return payload


def _shared_floor_capacity_measurement(
    source: Any,
    base_capacity_contract: dict[str, Any],
    *,
    generation_context: Any,
    capacity_site: Polygon,
    height: float,
    floors: int,
    pnu: str = "",
    trusted_legal_floor_field: dict[str, Any] | None = None,
    expected_legal_floor_field_hash: str = "",
    trusted_clear_span_floor_plan: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Preserve the legacy sampler patch seam for floor measurement."""

    return _measure_candidate_floor_capacity(
        source,
        base_capacity_contract,
        generation_context=generation_context,
        capacity_site=capacity_site,
        height=height,
        floors=floors,
        pnu=pnu,
        trusted_legal_floor_field=trusted_legal_floor_field,
        expected_legal_floor_field_hash=expected_legal_floor_field_hash,
        trusted_clear_span_floor_plan=trusted_clear_span_floor_plan,
        generation_site_sampler=generation_site_at_height,
    )


@dataclass(frozen=True)
class LlmAuthorRequestOutcome:
    provider_request_executed: bool
    author_stage: str
    request_kind: str
    requested_count: int
    feedback_count: int
    base_feedback_count: int
    cache_hit_count: int
    valid_authored_program_count: int
    terminal_status: str
    failure_reason: str
    failure_diagnostics: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        counts = (
            self.requested_count,
            self.feedback_count,
            self.base_feedback_count,
            self.cache_hit_count,
            self.valid_authored_program_count,
        )
        if any(int(value) < 0 for value in counts):
            raise ValueError("LLM author request outcome counts must be nonnegative")
        if self.cache_hit_count > self.valid_authored_program_count:
            raise ValueError("cache hits cannot exceed valid authored programs")
        if not self.author_stage or not self.request_kind or not self.terminal_status:
            raise ValueError("LLM author request outcome identity is required")
        if self.terminal_status != "completed" and not self.failure_reason:
            raise ValueError("non-completed LLM author outcome requires a reason")
        object.__setattr__(
            self,
            "failure_diagnostics",
            deepcopy(self.failure_diagnostics or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "arr.maas.llm_author_request_outcome.v1",
            "provider_request_executed": self.provider_request_executed,
            "author_stage": self.author_stage,
            "request_kind": self.request_kind,
            "requested_count": self.requested_count,
            "feedback_count": self.feedback_count,
            "base_feedback_count": self.base_feedback_count,
            "cache_hit_count": self.cache_hit_count,
            "valid_authored_program_count": self.valid_authored_program_count,
            "terminal_status": self.terminal_status,
            "failure_reason": self.failure_reason,
            "failure_diagnostics": deepcopy(self.failure_diagnostics or {}),
        }


def _paid_provider_request_count() -> int:
    snapshot = paid_provider_budget_snapshot()
    by_kind = snapshot.get("request_counts_by_kind") or {}
    kind_total = sum(
        max(0, int(value or 0))
        for value in by_kind.values()
    ) if isinstance(by_kind, dict) else 0
    try:
        declared_total = max(0, int(snapshot.get("request_count") or 0))
    except (TypeError, ValueError):
        declared_total = 0
    return max(declared_total, kind_total)


def _agent_mutated_seeds(
    building_type: str,
    mutations: list[dict[str, Any]] | None,
    geometry_mutations: list[dict[str, Any]] | None = None,
    synthesis_requests: list[dict[str, Any]] | None = None,
    outcome_graph: GeometryOutcomeGraph | None = None,
    site: Polygon | None = None,
    site_boundary_source: str = "",
    site_access_context: dict[str, Any] | None = None,
    site_access_geometry: dict[str, Any] | None = None,
    program_dimensional_context: dict[str, Any] | None = None,
    height: float = 1.0,
    floors: int = 1,
    live_geometry_vlm_revision: bool = False,
    base_capacity_contract: dict[str, Any] | None = None,
    universal_variation_pages: tuple[int, ...] = (0,),
    author_request_outcomes: list[LlmAuthorRequestOutcome] | None = None,
) -> tuple[VerbSequence, ...]:
    """Apply agent/VLM graph edits to reusable role seeds, never finished forms."""
    seeds = list(program_seed_sequences(building_type))
    originals = {sequence.name: sequence for sequence in seeds}
    for index, record in enumerate(mutations or ()):  # bounded external genotype proposals
        if not isinstance(record, dict):
            continue
        source = originals.get(str(record.get("source_seed") or ""))
        if source is None:
            continue
        edit_records = record.get("edits") if isinstance(record.get("edits"), list) else [record]
        typed_edits: list[ProgramSectionGraphEdit] = []
        replacement = "genotype"
        for edit_record in edit_records:
            if not isinstance(edit_record, dict):
                continue
            operation = str(edit_record.get("operation") or "")
            if operation not in {"replace_roof_operator", "set_parameter", "set_section_control"}:
                continue
            operator_value = str(edit_record.get("operator_value") or "") or None
            if operator_value:
                replacement = operator_value
            try:
                numeric_value = (
                    float(edit_record["numeric_value"])
                    if edit_record.get("numeric_value") is not None
                    else None
                )
                control_index = (
                    int(edit_record["control_index"])
                    if edit_record.get("control_index") is not None
                    else None
                )
            except (TypeError, ValueError):
                continue
            typed_edits.append(ProgramSectionGraphEdit(
                operation=operation,
                target_node_id=str(edit_record.get("target_node_id") or "roof"),
                parameter_name=str(edit_record.get("parameter_name") or "operator"),
                numeric_value=numeric_value,
                control_index=control_index,
                operator_value=operator_value,
                rationale=str(edit_record.get("rationale") or record.get("rationale") or "agent-directed genotype mutation"),
            ))
        if not typed_edits:
            continue
        try:
            mutated = mutate_program_section_sequence(
                source,
                typed_edits,
                director="vlm_portfolio_critic",
                name_suffix=f"genotype_{index}_{replacement}",
            )
        except ValueError:
            continue
        if mutated.name != source.name:
            seeds.append(mutated)
    # A geometry directive creates another typed program seed, not a frozen
    # mesh.  The same program roles and BOOK projection compile first; only
    # then is the dominant role replaced by the recursive solid program.
    for index, record in enumerate(geometry_mutations or ()):
        if not isinstance(record, dict):
            continue
        source = originals.get(str(record.get("source_seed") or ""))
        program_id = str(record.get("geometry_program") or "")
        if source is None or program_id not in _geometry_program_registry():
            continue
        raw_strengths = (
            record.get("legal_fit_strengths")
            if isinstance(record.get("legal_fit_strengths"), list)
            else [record.get("legal_fit_strength") or 0.0]
        )
        try:
            legal_fit_strengths = tuple(dict.fromkeys(
                max(0.0, min(1.0, float(value))) for value in raw_strengths
            ))
        except (TypeError, ValueError):
            continue
        edit_records = record.get("geometry_edits") if isinstance(record.get("geometry_edits"), list) else []
        for strength_index, legal_fit_strength in enumerate(legal_fit_strengths):
            notes = tuple((*source.notes,
                f"geometry_program_directive={program_id}",
                f"geometry_program_source_seed={source.name}",
                f"geometry_program_edits={json.dumps(edit_records, sort_keys=True, separators=(',', ':'))}",
                f"geometry_program_rationale={str(record.get('rationale') or 'agent-authored recursive solid mutation')}",
                f"geometry_program_legal_fit_strength={legal_fit_strength}",
                "geometry_program_source=typed_agent_directive",
            ))
            seeds.append(replace(
                source,
                name=f"{source.name}__geometry_genotype_{index}_{strength_index}_{program_id}",
                notes=notes,
            ))
    # The dominant form control lane is program-independent.  Program role
    # seeds are only carriers here: the shared recursive solid is projected by
    # BOOK first and receives use-specific roles/gates downstream.  The old
    # profile request authored a gym/neighbourhood/cultural body before p.3 and
    # BOOK, which made the supposedly fundamental grammar program-shaped.
    requested_universal_pages = tuple(sorted({
        max(0, min(7, int(page))) for page in universal_variation_pages
    })) or (0,)
    # Supply ordering was measured twice and is not a quality lever: nearest-
    # proportion order lifted program-gate throughput by a third while narrowing
    # the selected portfolio's aspect spread, and dispersed order cut throughput
    # without recovering it.  The conditioning modules remain available; the
    # pipeline stays on unordered supply until something proves otherwise.
    # The cross product below is truncated downstream by the exact-compile cap,
    # so its *order* is the portfolio's whole diversity budget. Built source-
    # major over the bank's construction order it delivered a head of one
    # program seed crossed with the first ~20 forms: the third cultural seed
    # never appeared, the four rare (elliptical/triangular) forms sat at 82-85,
    # and lift/terrace/setback/bridge were scattered past the cut. Form-major
    # over a family-stratified supply, with the program seed rotating, makes
    # any head span both axes. Every pairing that existed still exists.
    universal_programs = stratified_form_supply_order(
        universal_form_program_pages(requested_universal_pages)
    )
    source_seeds = tuple(originals.values())
    for rotation in range(len(source_seeds)):
        for program_index, program in enumerate(universal_programs):
            source_index = (program_index + rotation) % len(source_seeds)
            source = source_seeds[source_index]
            payload = json.dumps(
                program.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            notes = tuple((*source.notes,
                f"geometry_program_payload={payload}",
                f"geometry_program_source_seed={source.name}",
                "geometry_program_edits=[]",
                "geometry_program_rationale=program-independent base seed and chassis bank before BOOK and use projection",
                "geometry_program_legal_fit_strength=0.0",
                "geometry_program_source=universal_form_bank",
                f"geometry_program_form_bank_page={int(program.metadata.get('form_bank_variation_page') or 0)}",
                "geometry_program_synthesis_request_source=universal_form_bank_control",
                "geometry_program_vlm_status=not_requested_pre_program",
                "geometry_program_llm_author_status=not_requested_pre_program",
                "geometry_program_llm_author_active=False",
                "geometry_program_prebook_vlm_quarantined=False",
            ))
            seeds.append(replace(
                source,
                name=(
                    f"{source.name}__universal_{source_index}_{program_index}_"
                    f"{program.program_hash()[:10]}"
                ),
                notes=notes,
            ))

    # Explicit session mutations remain additive. They are feedback requests,
    # not the default control population and cannot replace the universal bank.
    directive_requests = tuple({
        **dict(request),
        "synthesis_request_source": "vlm_or_session_directive",
        "site_access_side": str(
            request.get("site_access_side")
            or (_site_access_side_in_principal_frame(site, site_access_geometry) if site is not None else "closed")
        ),
        # The parcel's own box, so the seed is authored in this site's metres.
        # A base seed is otherwise a proportion and its size arrives later at
        # the host fit, which is where it was going missing: fitted INSIDE the
        # buildable polygon a BOOK mass delivered 664 m2 against a 1,497.9 m2
        # coverage cap on 의정부 4115011300106840001. massv2's seed has been the
        # parcel's own rectangle since it was written, which is why it has
        # never had this problem.
        "site_extent": _site_seed_extent(site, height),
    } for request in (synthesis_requests or ()) if isinstance(request, dict))
    effective_synthesis_requests = tuple((
        *directive_requests,
    ))

    # A synthesis request describes architectural intent and normalized base
    # seeds.  The agent expands it into recursive ASTs; unlike the legacy
    # geometry_program registry, no named completed-form record is selected.
    for request_index, request in enumerate(effective_synthesis_requests):
        if not isinstance(request, dict):
            continue
        source = originals.get(str(request.get("source_seed") or ""))
        if source is None:
            continue
        programs = synthesize_architectural_programs(request, building_type=building_type)
        vlm_status = "not_requested"
        llm_author_status = "not_requested"
        llm_author_budget_failure: dict[str, Any] | None = None
        llm_author_request_executed = False
        base_book_vlm_feedback_count = 0
        base_book_vlm_feedback_in_author_context = False
        authored_visual_authority_feedback_count = 0
        authored_visual_authority_feedback_in_author_context = False
        llm_author_cache_hit_count = 0
        llm_author_valid_program_count = 0
        llm_author_failure_reason = ""
        provider_request_count_before: int | None = None
        live_prebook_vlm_requested = bool(request.get("live_vlm_revision"))
        llm_author_requested = bool(request.get("live_llm_author")) or str(
            request.get("synthesis_request_source") or ""
        ) == "openai_vlm_experimental"
        llm_author_only = bool(request.get("llm_author_only")) or (
            llm_author_requested and not live_prebook_vlm_requested
        )
        if live_prebook_vlm_requested or llm_author_requested:
            live_opt_in = os.getenv("MAAS_LIVE_GEOMETRY_VLM", "").strip().lower() in {"1", "true", "yes", "on"}
            rotated_credential_confirmed = os.getenv("MAAS_LIVE_VLM_CREDENTIAL_ROTATED", "").strip().lower() in {"1", "true", "yes", "on"}
            if live_prebook_vlm_requested and not live_opt_in:
                vlm_status = "inactive_requires_explicit_MAAS_LIVE_GEOMETRY_VLM_opt_in"
            elif live_prebook_vlm_requested and not rotated_credential_confirmed:
                vlm_status = "inactive_requires_rotated_credential_confirmation"
            elif (
                not os.getenv("OPENAI_API_KEY")
                and not os.getenv(
                    "MAAS_GEOMETRY_AUTHOR_REPLAY_CACHE_PATH"
                )
            ):
                vlm_status = "inactive_missing_rotated_environment_key"
            else:
                try:
                    reference_contract = {
                        **program_reference_contract(building_type),
                        "program_dimensional_context": dict(program_dimensional_context or {}),
                        "base_capacity_contract": dict(base_capacity_contract or {}),
                        "site_boundary_source": site_boundary_source,
                        "site_access_context": dict(site_access_context or {}),
                        "site_access_side_in_program_frame": str(request.get("site_access_side") or "closed"),
                    }
                    explicit_reference_matches = [
                        item for item in (request.get("reference_matches") or ())
                        if isinstance(item, dict)
                    ]
                    # Reference understanding precedes geometry authorship.
                    # Feed the LLM only VLM-audited, coordinate-free massing
                    # relations; the downstream critic still sees the actual
                    # images and remains the selection authority.
                    reference_matches: list[dict[str, Any]] = []
                    reference_language_context: dict[str, Any] = {
                        "schema_version": "arr.maas.reference_vlm_author_context.v1",
                        "status": "not_available",
                        "selection_authority": "none_author_prior_only",
                        "references": [],
                    }
                    if programs and not llm_author_only:
                        reference_matches, reference_language_audit = _audited_final_book_references(
                            programs[0],
                            building_type=building_type,
                            explicit_matches=explicit_reference_matches,
                        )
                        reference_language_context = _reference_language_author_context(
                            reference_matches,
                            reference_language_audit,
                        )
                    llm_author_context = {
                        "schema_version": "arr.maas.geometry_llm_author_context.v1",
                        "building_type": building_type,
                        "program_context": reference_contract,
                        "base_capacity_contract": dict(base_capacity_contract or {}),
                        "source_program_seed": source.name,
                        "base_seeds": list(request.get("base_seeds") or ()),
                        "intent_tags": list(request.get("intent_tags") or ()),
                        "book_graph_vocabulary": (
                            _book_graph_author_vocabulary()
                        ),
                        "book_graph_supply": deepcopy(
                            request.get("book_graph_supply") or {}
                        ),
                        "maximum_operator_depth": max(1, min(3, int(request.get("maximum_operator_depth") or 2))),
                        "downstream_body_rule_reserve": max(
                            0,
                            min(2, int(request.get("downstream_body_rule_reserve") or 0)),
                        ),
                        "site_relation": {
                            "boundary_source": site_boundary_source,
                            "access_side_in_program_frame": str(request.get("site_access_side") or "closed"),
                            "coordinates_available_to_author": False,
                        },
                        "reference_vlm_language": reference_language_context,
                        "outcome_graph_memory": (
                            outcome_graph.author_context(
                                source_seed=source.name,
                                program_slug=building_type,
                                program_aliases=tuple(sorted({
                                    building_type,
                                    next(
                                        (slug for slug, label, _height, _floors in PROGRAMS if label == building_type),
                                        building_type,
                                    ),
                                    str(reference_contract.get("program_id") or ""),
                                })),
                            )
                            if outcome_graph is not None
                            else {
                                "schema_version": "arr.maas.geometry_author_context.v1",
                                "observation_count": 0,
                                "status": "no_prior_observation",
                            }
                        ),
                        "instruction": (
                            "author materially different recursive solid ASTs; references are reviewed "
                            "later by the image-grounded VLM critic; no parcel coordinates or completed form"
                        ),
                        "author_batch_index": int(
                            request.get("llm_author_batch_index") or 0
                        ),
                        "author_batch_count": int(
                            request.get("llm_author_batch_count") or 1
                        ),
                        "author_variation_offset": int(
                            request.get("llm_author_variation_offset") or 0
                        ),
                        "legal_fit_repair_feedback": list(
                            request.get("legal_fit_repair_feedback") or ()
                        )[:12],
                        "capacity_authoring_deficits": deepcopy(list(
                            request.get("capacity_authoring_deficits") or ()
                        )[:12]),
                        "family_supply_deficits": deepcopy(dict(
                            request.get("family_supply_deficits") or {}
                        )),
                        "require_new_geometry_program_ast": bool(
                            request.get("require_new_geometry_program_ast")
                        ),
                        "author_stage": str(
                            request.get("author_stage") or "initial"
                        ),
                        "author_request_kind": str(
                            request.get("author_request_kind")
                            or "geometry_author_initial"
                        ),
                        "base_book_vlm_replenishment_feedback": deepcopy(list(
                            request.get(
                                "base_book_vlm_replenishment_feedback"
                            ) or ()
                        )[:12]),
                        "authored_visual_authority_replenishment_feedback": deepcopy(list(
                            request.get(
                                "authored_visual_authority_replenishment_feedback"
                            ) or ()
                        )[:12]),
                    }
                    base_book_vlm_feedback_count = len(
                        llm_author_context[
                            "base_book_vlm_replenishment_feedback"
                        ]
                    )
                    base_book_vlm_feedback_in_author_context = bool(
                        base_book_vlm_feedback_count
                    )
                    authored_visual_authority_feedback_count = len(
                        llm_author_context[
                            "authored_visual_authority_replenishment_feedback"
                        ]
                    )
                    authored_visual_authority_feedback_in_author_context = bool(
                        authored_visual_authority_feedback_count
                    )
                    llm_author_failure_diagnostics: dict[str, Any] = {}
                    cooldown = request.get("author_rate_limit_cooldown")
                    if llm_author_requested and isinstance(cooldown, dict):
                        llm_author_failure_reason = "rate_limited_cooldown"
                        llm_author_status = "deferred:rate_limited_cooldown"
                        llm_author_failure_diagnostics = {
                            "schema_version": (
                                "arr.maas.geometry_author_failure_diagnostics.v1"
                            ),
                            "provider_error": {
                                "category": "rate_limited_cooldown",
                                "http_status": 429,
                            },
                            "cooldown": {
                                key: cooldown[key]
                                for key in (
                                    "schema_version",
                                    "attempt_count",
                                    "deadline_epoch_seconds",
                                    "backoff_seconds",
                                    "source",
                                    "http_status",
                                    "retry_after_seconds",
                                    "remaining_seconds",
                                    "active",
                                    "scope",
                                    "circuit_open",
                                )
                                if key in cooldown
                            },
                        }
                        if llm_author_only:
                            programs = ()
                    elif llm_author_requested:
                        provider_request_count_before = (
                            _paid_provider_request_count()
                        )
                        try:
                            llm_authored = author_geometry_programs_with_openai(
                                llm_author_context,
                                target_count=bounded_llm_author_batch_count(
                                    int(request.get("llm_author_count") or 8)
                                ),
                                model=str(request.get("llm_author_model") or "") or None,
                            )
                            llm_authored = tuple(replace(item, metadata={
                                **item.metadata,
                                "reference_vlm_author_context": reference_language_context,
                                "reference_vlm_precedes_author": bool(
                                    reference_language_context.get("status")
                                    not in {"", "not_available"}
                                ),
                                "llm_geometry_author_active": True,
                            }) for item in llm_authored)
                            if llm_author_only:
                                programs = tuple(llm_authored)
                            else:
                                unique_programs = {
                                    program.program_hash(): program
                                    for program in programs
                                }
                                for authored in llm_authored:
                                    unique_programs.setdefault(
                                        authored.program_hash(),
                                        authored,
                                    )
                                programs = tuple(unique_programs.values())
                            llm_author_status = (
                                f"completed:{len(llm_authored)}:"
                                f"cache_hits={sum(bool(item.metadata.get('author_cache_hit')) for item in llm_authored)}"
                            )
                            llm_author_valid_program_count = len(llm_authored)
                            llm_author_cache_hit_count = sum(
                                bool(item.metadata.get("author_cache_hit"))
                                for item in llm_authored
                            )
                            llm_author_request_executed = bool(
                                not llm_authored
                                or llm_author_cache_hit_count < len(llm_authored)
                            )
                            if not llm_authored:
                                llm_author_failure_reason = (
                                    "no_valid_authored_program"
                                )
                            llm_author_budget_failure = next((
                                deepcopy(item.metadata.get(
                                    "author_compiler_repair_budget_failure"
                                ))
                                for item in llm_authored
                                if (
                                    not bool(item.metadata.get(
                                        "author_cache_hit"
                                    ))
                                    and isinstance(item.metadata.get(
                                        "author_compiler_repair_budget_failure"
                                    ), dict)
                                )
                            ), None)
                            llm_author_failure_diagnostics = next((
                                deepcopy(item.metadata.get(
                                    "author_failure_diagnostics"
                                ))
                                for item in llm_authored
                                if isinstance(item.metadata.get(
                                    "author_failure_diagnostics"
                                ), dict)
                            ), {})
                        except PaidProviderBudgetError as exc:
                            llm_author_request_executed = (
                                str(exc.request_kind) == "provider_retry"
                            )
                            llm_author_failure_reason = (
                                "paid_provider_budget_error"
                            )
                            llm_author_budget_failure = {
                                "code": exc.code,
                                "request_kind": exc.request_kind,
                                "quota": exc.quota,
                                "used": exc.used,
                                "limit": exc.limit,
                                "remaining": exc.remaining,
                                "author_stage": str(
                                    llm_author_context.get("author_stage") or ""
                                ),
                            }
                            llm_author_status = (
                                "budget_error:"
                                + json.dumps(
                                    llm_author_budget_failure,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                )
                            )
                            if llm_author_only:
                                programs = ()
                        except GeometryAuthorError as exc:
                            llm_author_failure_reason = "geometry_author_error"
                            llm_author_failure_diagnostics = deepcopy(
                                getattr(exc, "diagnostics", {}) or {}
                            )
                            # The deterministic control population remains in the
                            # additive lane; a failed external author is explicit
                            # evidence and never replaced with fabricated DSL.
                            llm_author_status = f"error:{type(exc).__name__}"
                            logger.warning(
                                "LLM geometry author request failed: %s",
                                llm_author_status,
                            )
                            if llm_author_only:
                                programs = ()
                        finally:
                            llm_author_request_executed = bool(
                                provider_request_count_before is not None
                                and _paid_provider_request_count()
                                > provider_request_count_before
                            )
                    if llm_author_only:
                        raise _PostBookVlmOnly
                    seed_source = (
                        compile_sequence_to_source_mass(site, source)
                        if site is not None
                        else None
                    )
                    capacity_target_plan_area = float(
                        (base_capacity_contract or {}).get("target_base_plan_area_m2") or 0.0
                    )
                    target_plan_area = (
                        capacity_target_plan_area
                        if capacity_target_plan_area > 0.0
                        else (
                            float(seed_source.footprint.area)
                            if seed_source is not None
                            else None
                        )
                    )

                    def render_site_conditioned_preview(
                        program: GeometryProgram,
                        _compilation: Any,
                        output_path: Path,
                    ) -> Path:
                        if site is None:
                            from backend.app.modules.design.generation.maas.geometry_language import render_compilation_preview
                            return render_compilation_preview(_compilation, output_path, title=program.name)
                        preview_source = compile_geometry_program_to_source_mass(
                            program,
                            site,
                            target_plan_area=target_plan_area,
                            name=f"vlm_preview__{program.name}",
                            max_volume_bands=3,
                        )
                        if preview_source is None:
                            from backend.app.modules.design.generation.maas.geometry_language import render_compilation_preview
                            return render_compilation_preview(_compilation, output_path, title=program.name)
                        preview_feature = source_feature(
                            preview_source,
                            source,
                            building_type=building_type,
                            height=height,
                            floors=floors,
                            site_area=float(site.area),
                        )
                        props = preview_feature.setdefault("properties", {})
                        props["site_boundary_geometry"] = mapping(site)
                        props["site_boundary_source"] = site_boundary_source
                        props["site_access_context"] = dict(site_access_context or {})
                        props["site_access_geometry"] = site_access_geometry
                        props["program_context"] = reference_contract
                        props["base_capacity_contract"] = dict(base_capacity_contract or {})
                        props["preview_target_plan_area_m2"] = target_plan_area
                        return feature_preview_png(preview_feature, output_path.parent)

                    prebook_parent_programs = tuple(programs)
                    loop = run_geometry_program_a2a_loop(
                        context={
                            "building_type": building_type,
                            "intent_tags": list(request.get("intent_tags") or ()),
                            "base_seeds": list(request.get("base_seeds") or ()),
                            "base_capacity_contract": dict(base_capacity_contract or {}),
                            "instruction": "critic must propose typed node edits, never a completed mesh",
                        },
                        target_count=len(programs),
                        author_programs=lambda _context, authored=programs: authored,
                        critic_program=openai_vlm_geometry_critic(
                            reference_provider=lambda program, explicit=reference_matches: retrieve_geometry_reference_matches(
                                program,
                                building_type=building_type,
                                explicit_matches=explicit,
                                # The image-suitability audit can reject
                                # interiors and close facade shots. Retrieve a
                                # deeper program-specific pool so at least
                                # three whole-building massing views remain.
                                # The reference-image VLM will reject interiors,
                                # detail shots and incompatible building scales.
                                # Search deeply enough that the unchanged
                                # three-image program evidence contract can be
                                # satisfied by whole-building views.
                                limit=max(24, min(32, int(request.get("reference_limit") or 24))),
                            ),
                            memory_provider=(
                                 lambda program: outcome_graph.agent_neighborhood(
                                     source_seed=source.name,
                                     program_hash=program.program_hash(),
                                     program_slug=building_type,
                                     program_aliases=tuple(sorted({
                                         building_type,
                                         str(reference_contract.get("program_id") or ""),
                                     })),
                                 )
                                if outcome_graph is not None
                                else {}
                            ),
                            building_type=building_type,
                            program_context=reference_contract,
                            model=str(request.get("vlm_model") or "") or None,
                        ),
                        max_generations=max(1, min(3, int(request.get("vlm_generations") or 2))),
                        gate_policy=GeometryGatePolicy(maximum_components=1),
                        author_provider=(
                            "bounded_procedural_plus_openai_llm"
                            if any(
                                item.metadata.get("author_provider") == "openai_llm_geometry_author"
                                for item in programs
                            )
                            else "bounded_procedural_geometry_agent"
                        ),
                        critic_provider="openai_vlm",
                        preview_renderer=render_site_conditioned_preview,
                    )
                    if outcome_graph is not None:
                        outcome_graph.observe_vlm_loop(
                            program_slug=building_type,
                            source_seed=source.name,
                            trace=loop.trace,
                        )
                    archive_programs = tuple(replace(
                            candidate.program,
                            metadata={
                                **candidate.program.metadata,
                                "vlm_critic_score": round(float(candidate.critic_score), 4),
                                "vlm_revision_generation": int(candidate.generation),
                                "vlm_geometry_critic_active": True,
                                "vlm_geometry_revision_count": int(loop.trace.get("geometry_revision_count") or 0),
                                "vlm_unique_geometry_count": int(loop.trace.get("unique_geometry_count") or 0),
                                "vlm_model": str(candidate.critic_payload.get("model") or ""),
                                "vlm_response_id": str(candidate.critic_payload.get("response_id") or ""),
                                "vlm_program_fit_hard_pass": bool(
                                    candidate.critic_payload.get("program_fit_hard_pass", True)
                                ),
                                "vlm_program_appropriateness": float(
                                    (candidate.critic_payload.get("concept_scores") or {}).get("program_appropriateness") or 0.0
                                ),
                                "vlm_section_program_fit": float(
                                    (candidate.critic_payload.get("concept_scores") or {}).get("section_program_fit") or 0.0
                                ),
                                "vlm_reference_assessments": list(
                                    candidate.critic_payload.get("reference_assessments") or ()
                                ),
                                "vlm_reference_count": len(
                                    ((candidate.critic_payload.get("maas_causal_context") or {}).get("reference_matches") or ())
                                ),
                                "vlm_memory_observation_count": int(
                                    (((candidate.critic_payload.get("maas_causal_context") or {}).get("outcome_memory") or {}).get("observation_count") or 0)
                                ),
                                "llm_geometry_author_active": bool(
                                    candidate.program.metadata.get("author_provider") == "openai_llm_geometry_author"
                                ),
                                "llm_geometry_author_model": str(
                                    candidate.program.metadata.get("author_model") or ""
                                ),
                                "llm_geometry_author_response_id": str(
                                    candidate.program.metadata.get("author_response_id") or ""
                                ),
                            },
                        ) for candidate in loop.archive)
                    quarantined_programs = _prebook_vlm_quarantined_llm_parents(
                        prebook_parent_programs,
                        loop.trace,
                    )
                    unique_programs = {
                        program.program_hash(): program
                        for program in archive_programs
                    }
                    for program in quarantined_programs:
                        unique_programs.setdefault(program.program_hash(), program)
                    # Quarantine is candidate supply only. Every such parent
                    # must still pass BOOK projection, clean/program/legal
                    # gates and the exact post-BOOK VLM hard gate; it receives
                    # no positive score or final-selection authority here.
                    programs = tuple(unique_programs.values())
                    vlm_status = str(loop.trace.get("status") or "completed")
                except _PostBookVlmOnly:
                    vlm_status = "deferred_to_exact_post_book_final_solid"
                except Exception as exc:
                    # The deterministic graph author and hard gates remain
                    # usable when an external critic is unavailable. Record
                    # the failure; never fabricate a synthetic VLM score.
                    vlm_status = f"error:{type(exc).__name__}"
                    logger.warning(
                        "Geometry author/VLM synthesis stage failed: %s: %s",
                        type(exc).__name__,
                        str(exc)[:300],
                    )
        if llm_author_requested and author_request_outcomes is not None:
            if llm_author_valid_program_count > 0:
                terminal_status = "completed"
                terminal_failure_reason = ""
            elif llm_author_failure_reason:
                terminal_status = (
                    "deferred"
                    if llm_author_failure_reason == "rate_limited_cooldown"
                    else "failed"
                )
                terminal_failure_reason = llm_author_failure_reason
            else:
                terminal_status = "not_executed"
                terminal_failure_reason = str(vlm_status or llm_author_status)
            author_request_outcomes.append(LlmAuthorRequestOutcome(
                provider_request_executed=llm_author_request_executed,
                author_stage=str(request.get("author_stage") or "initial"),
                request_kind=str(
                    request.get("author_request_kind")
                    or "geometry_author_initial"
                ),
                requested_count=bounded_llm_author_batch_count(
                    int(request.get("llm_author_count") or 8)
                ),
                feedback_count=authored_visual_authority_feedback_count,
                base_feedback_count=base_book_vlm_feedback_count,
                cache_hit_count=llm_author_cache_hit_count,
                valid_authored_program_count=llm_author_valid_program_count,
                terminal_status=terminal_status,
                failure_reason=terminal_failure_reason,
                failure_diagnostics=llm_author_failure_diagnostics,
            ))
        # Legal compliance must not silently author a second geometry on top
        # of the typed recursive program.  The former 0.25..1.0 frame blend
        # changed every vertex as a function of height and collapsed diverse
        # programs into one tapered/wedge family.  Legal adaptation remains in
        # the downstream hard-gate lane (bounded scale/translate, clipping and
        # measured retention); this synthesis lane always preserves the AST.
        fallback_strengths = (0.0,)
        for program_index, program in enumerate(programs):
            # Do not allow historic outcome-graph observations from the old
            # tapering policy to reintroduce a non-zero frame blend.
            strengths = fallback_strengths
            payload = json.dumps(program.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            family = str(program.metadata.get("family") or "agent_recursive")
            for strength_index, legal_fit_strength in enumerate(strengths):
                notes = tuple((*source.notes,
                    f"geometry_program_payload={payload}",
                    f"geometry_program_source_seed={source.name}",
                    "geometry_program_edits=[]",
                    f"geometry_program_rationale=agent synthesis from normalized base and intent tags: {','.join(program.metadata.get('intent_tags') or ())}",
                    f"geometry_program_legal_fit_strength={legal_fit_strength}",
                    "geometry_program_source=procedural_geometry_synthesis_agent",
                    f"geometry_program_synthesis_request_source={str(request.get('synthesis_request_source') or 'program_profile_control')}",
                    f"geometry_program_vlm_status={vlm_status}",
                    f"geometry_program_vlm_reference_count={int(program.metadata.get('vlm_reference_count') or 0)}",
                    f"geometry_program_vlm_memory_observation_count={int(program.metadata.get('vlm_memory_observation_count') or 0)}",
                    f"geometry_program_vlm_revision_count={int(program.metadata.get('vlm_geometry_revision_count') or 0)}",
                    f"geometry_program_llm_author_status={llm_author_status}",
                    "geometry_program_llm_author_request_executed="
                    f"{llm_author_request_executed}",
                    "geometry_program_base_book_vlm_feedback_count="
                    f"{base_book_vlm_feedback_count}",
                    "geometry_program_base_book_vlm_feedback_in_author_context="
                    f"{base_book_vlm_feedback_in_author_context}",
                    "geometry_program_authored_visual_authority_feedback_count="
                    f"{authored_visual_authority_feedback_count}",
                    "geometry_program_authored_visual_authority_feedback_in_author_context="
                    f"{authored_visual_authority_feedback_in_author_context}",
                    "geometry_program_llm_author_budget_failure="
                    + (
                        json.dumps(
                            llm_author_budget_failure,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        if llm_author_budget_failure is not None
                        else ""
                    ),
                    f"geometry_program_llm_author_active={bool(program.metadata.get('llm_geometry_author_active'))}",
                    f"geometry_program_prebook_vlm_quarantined={bool(program.metadata.get('pre_book_vlm_quarantined'))}",
                ))
                seeds.append(replace(
                    source,
                    name=(
                        f"{source.name}__synth_{request_index}_{program_index}_{strength_index}_"
                        f"{family}_{program.program_hash()[:10]}"
                    ),
                    notes=notes,
                ))
    # A cost-bounded smoke run may stop after three floor-valid candidates.
    # Put explicitly requested paid authorship at the front so the large
    # deterministic control bank cannot consume the whole smoke budget before
    # the authored AST is even compiled. This grants review opportunity only;
    # every authored candidate still faces BOOK, legal, FAR, parking and VLM.
    if any(
        bool(request.get("live_llm_author"))
        for request in effective_synthesis_requests
        if isinstance(request, dict)
    ):
        seeds.sort(key=lambda sequence: (
            not any(
                note == "geometry_program_llm_author_active=True"
                for note in sequence.notes
            ),
        ))
    return tuple(seeds)


def _prebook_vlm_quarantined_llm_parents(
    parents: tuple[GeometryProgram, ...],
    trace: dict[str, Any],
) -> tuple[GeometryProgram, ...]:
    """Retain clean LLM parents only as exact-post-BOOK repair supply.

    A pre-BOOK critic sees neither BOOK scope nor the final projected solid.
    Its rejection remains negative evidence, but deleting the genotype here
    prevents the authoritative exact-post-BOOK critic from testing whether a
    typed BOOK mutation resolves that failure. Quarantined parents therefore
    carry zero selection authority until every downstream hard gate passes.
    """
    rejected_records = {
        str(record.get("program_hash") or ""): record
        for generation in trace.get("generations") or ()
        if isinstance(generation, dict)
        for record in generation.get("records") or ()
        if isinstance(record, dict)
        and record.get("status") == "critic_program_fit_rejected"
        and record.get("program_hash")
    }
    quarantined: list[GeometryProgram] = []
    for program in parents:
        if program.metadata.get("author_provider") != "openai_llm_geometry_author":
            continue
        program_hash = program.program_hash()
        record = rejected_records.get(program_hash)
        if record is None:
            continue
        compilation = compile_geometry_program(program)
        if compilation.status != "compiled" or compilation_gate(
            compilation,
            GeometryGatePolicy(maximum_components=1),
        ):
            continue
        quarantined.append(replace(program, metadata={
            **program.metadata,
            "vlm_geometry_critic_active": True,
            "vlm_program_fit_hard_pass": False,
            "pre_book_vlm_quarantined": True,
            "pre_book_vlm_response_id": str(record.get("critic_response_id") or ""),
            "pre_book_vlm_critic_actions": list(record.get("critic_actions") or ()),
            "pre_book_vlm_concept_scores": {
                "program_appropriateness": float(record.get("program_appropriateness") or 0.0),
                "section_program_fit": float(record.get("section_program_fit") or 0.0),
            },
            "pre_book_vlm_quarantine_selection_authority": "none_until_exact_final_vlm_hard_pass",
            "pre_book_vlm_quarantine_reason": "critic_program_fit_rejected_before_book_projection",
            "llm_geometry_author_active": True,
        }))
    return tuple(quarantined)


def _geometry_program_registry() -> dict[str, Any]:
    references = reference_language_programs()
    programs = tuple((*references.values(), *architectural_shape_programs()))
    registry: dict[str, Any] = dict(references)
    for program in programs:
        family = str(program.metadata.get("family") or "")
        for key in (program.name, family):
            if key:
                registry.setdefault(key, program)
    return registry


def _body_program_for_book_projection(
    program: GeometryProgram,
    sequence: VerbSequence,
) -> GeometryProgram:
    if not book_projection_calls(sequence):
        return program
    return apply_book_projection_to_geometry_program(program, sequence)


def _bind_book_program_source_role(
    post_book_program: GeometryProgram,
    source: Any,
    *,
    program_id: str,
) -> GeometryProgram:
    """Attach source-role identity as a reachable geometry-identity root."""

    binding_failures: list[dict[str, Any]] = []
    bound = bind_source_role_scaffold_to_program(
        post_book_program,
        source,
        program_id=program_id,
        failure_sink=binding_failures,
    )
    if bound is None:
        evidence = (
            binding_failures[-1]
            if binding_failures
            else {
                "reason": "source_role_scaffold_binding_failed",
                "program_id": str(program_id or ""),
                "required_relations": [],
            }
        )
        error = ValueError(
            "source_role_scaffold_binding_failed:"
            f"{evidence.get('reason') or 'unknown'}:"
            f"required={evidence.get('required_relations') or []}:"
            f"missing={evidence.get('missing_relations') or []}:"
            f"available={evidence.get('available_relations') or []}:"
            f"scaffold_failures={evidence.get('scaffold_failures') or []}"
        )
        error.evidence = evidence
        raise error
    return bound


def _required_book_projection_failure(
    sequence: VerbSequence,
    *,
    pre_book_program: GeometryProgram,
    pre_book_compilation: Any,
    post_book_program: GeometryProgram,
    post_book_compilation: Any,
) -> dict[str, Any] | None:
    """Return typed evidence when an explicitly requested BOOK edit is inert."""

    calls = book_projection_calls(sequence)
    if not calls:
        return None
    projection = post_book_program.metadata.get("book_recursive_projection")
    if not isinstance(projection, dict) or projection.get("active") is not True:
        return {
            "book_projection_failure": "book_projection_adapter_inactive",
            "book_projection_call_count": len(calls),
        }
    if post_book_compilation.status != "compiled":
        return {
            "book_projection_failure": "book_projection_post_compile_failed",
            "book_projection_call_count": len(calls),
            "compilation_status": str(post_book_compilation.status),
        }
    if pre_book_program.program_hash() == post_book_program.program_hash():
        return {
            "book_projection_failure": "book_projection_program_noop",
            "book_projection_call_count": len(calls),
            "pre_book_program_hash": pre_book_program.program_hash(),
            "post_book_program_hash": post_book_program.program_hash(),
        }
    if (
        pre_book_compilation.status == "compiled"
        and str(pre_book_compilation.geometry_hash or "")
        and str(pre_book_compilation.geometry_hash)
        == str(post_book_compilation.geometry_hash or "")
    ):
        return {
            "book_projection_failure": "book_projection_geometry_noop",
            "book_projection_call_count": len(calls),
            "pre_book_geometry_hash": str(pre_book_compilation.geometry_hash),
            "post_book_geometry_hash": str(post_book_compilation.geometry_hash),
        }
    return None


def _book_projection_terminal_evidence(
    reason: str,
    **safe_evidence: Any,
) -> dict[str, Any]:
    """Return stable branch identity before terminal evidence is bounded."""
    return {
        "failure_reason": str(reason),
        **{
            str(key): value
            for key, value in safe_evidence.items()
            if str(key) != "failure_reason"
        },
    }


def _principles_for_seed(
    scheduled_principles: tuple[tuple[int, dict[str, Any]], ...],
    *,
    seed_index: int,
    llm_authored_seed: bool,
    selected_principle_ids: frozenset[str] | None = None,
    descendant_probe_count: int = 1,
) -> tuple[tuple[int, dict[str, Any]], ...]:
    if not llm_authored_seed or not scheduled_principles:
        return scheduled_principles
    selectable = tuple(
        item
        for item in scheduled_principles
        if selected_principle_ids is None
        or str(item[1].get("principle_id") or "")
        in selected_principle_ids
    )
    if not selectable:
        return ()
    selected = selectable[int(seed_index) % len(selectable)]
    selected_id = str(selected[1].get("principle_id") or "")
    base_id = str(
        selected[1].get("lineage_base_operative_id")
        or selected_id
    )
    if not selected_id:
        return ()
    if max(1, int(descendant_probe_count)) == 1 and base_id == selected_id:
        return (selected,)
    base = next((
        item
        for item in scheduled_principles
        if str(item[1].get("principle_id") or "") == base_id
    ), None)
    if base is None:
        return ()
    probe_count = max(1, int(descendant_probe_count))
    if probe_count > 1:
        descendants = [
            item for item in selectable
            if str(item[1].get("principle_id") or "") != base_id
            and str(item[1].get("lineage_base_operative_id") or "")
            == base_id
        ]
        if selected in descendants:
            descendants.remove(selected)
            descendants.insert(0, selected)
        diverse: list[tuple[int, dict[str, Any]]] = []
        deferred: list[tuple[int, dict[str, Any]]] = []
        seen_kinds: set[str] = set()
        for item in descendants:
            kind = str(item[1].get("kind") or "")
            if kind and kind not in seen_kinds:
                diverse.append(item)
                seen_kinds.add(kind)
            else:
                deferred.append(item)
        return tuple((base, *(diverse + deferred)[:probe_count]))
    if base_id == selected_id:
        return (selected,)
    return (base, selected)


def _llm_book_path_execution_contract(
    program: GeometryProgram | None,
    principles: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Resolve one LLM-selected BOOK path into its exact production axes."""

    if program is None:
        return None
    path_id = str(
        program.metadata.get("book_composition_path_id") or ""
    ).strip()
    if not path_id:
        return None
    from backend.app.modules.design.generation.maas.book_language.composition_lattice import book_composition_path_by_id

    path = book_composition_path_by_id(path_id)
    if path is None or not path.executable:
        return None
    principle = next((
        item for item in principles
        if str(item.get("principle_id") or "") == path.principle_id
    ), None)
    if principle is None:
        return None
    if tuple(principle.get("execution_verbs") or ()) != path.ordered_operations:
        return None
    return {
        "schema_version": "arr.maas.llm_book_path_execution_contract.v1",
        "path_id": path.path_id,
        "base_volume_label": path.base_volume_label,
        "orientation": path.orientation,
        "variation_index": path.variation_index,
        "principle_id": path.principle_id,
        "principle_kind": path.principle_kind,
        "ordered_operations": list(path.ordered_operations),
        "graph_edges": [list(edge) for edge in path.graph_edges],
        "topology_class": path.topology_class,
        "matrix4_count": 1,
        "principle": principle,
    }


def _canonical_descendant_tuple_schedule(
    principles: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    reviewed_parent_lineages: tuple[dict[str, Any], ...],
    *,
    seed: VerbSequence,
    seed_index: int,
    selected_principle_ids: frozenset[str] | None,
    descendant_probe_count: int,
    variant_count: int,
    schedule_cap: int | None,
    rotation_offset: int,
    selected_candidate_keys: frozenset[str] | None = None,
    allowed_variant_indices: frozenset[int] | None = None,
    replenishment_causal_request_hash: str = "",
    reviewed_parent_authority: dict[str, dict[str, Any]] | None = None,
    attempted_work_keys: frozenset[str] = frozenset(),
    work_disposition_evidence: dict[str, Any] | None = None,
) -> tuple[
    tuple[int, dict[str, Any], int, tuple[Any, ...], dict[str, Any]],
    ...,
]:
    """Schedule exact reviewed parent/allowed child/variant tuples fairly."""

    indexed_principles = tuple(enumerate(principles))
    reviewed_parents: list[dict[str, Any]] = []
    seen_parent_keys: set[str] = set()
    for lineage in reviewed_parent_lineages:
        parent_key = canonical_lineage_parent_key(lineage)
        base_id = str(lineage.get("base_operative_id") or "")
        if (
            not base_id
            or str(lineage.get("source_seed") or "") != seed.name
            or not parent_key
            or parent_key in seen_parent_keys
        ):
            continue
        seen_parent_keys.add(parent_key)
        reviewed_parents.append(lineage)
    if reviewed_parents:
        offset = int(rotation_offset) % len(reviewed_parents)
        reviewed_parents = (
            reviewed_parents[offset:] + reviewed_parents[:offset]
        )

    exact_variants_by_principle: dict[str, set[int]] | None = None
    if selected_candidate_keys is not None:
        exact_variants_by_principle = {}
        for key in selected_candidate_keys:
            parts = _competition_exact_key_parts(key)
            if parts is None or int(parts[0]) != int(seed_index):
                continue
            exact_variants_by_principle.setdefault(parts[1], set()).add(
                int(parts[2])
            )

    parent_queues: list[
        list[tuple[int, dict[str, Any], int, tuple[Any, ...], dict[str, Any]]]
    ] = []
    for parent_position, parent in enumerate(reviewed_parents):
        base_id = str(parent.get("base_operative_id") or "")
        canonical_child_ids = frozenset(
            str(principle.get("principle_id") or "")
            for principle in principles
            if str(principle.get("lineage_base_operative_id") or "")
            == base_id
            and str(principle.get("principle_id") or "") != base_id
        )
        allowed_child_ids = canonical_child_ids
        if selected_principle_ids is not None:
            allowed_child_ids &= selected_principle_ids
        if exact_variants_by_principle is not None:
            allowed_child_ids &= frozenset(exact_variants_by_principle)
        if not allowed_child_ids:
            continue
        children_list: list[tuple[int, dict[str, Any]]] = []
        seen_child_ids: set[str] = set()
        for probe_offset in range(max(1, int(descendant_probe_count))):
            allowed_pool = _principles_for_seed(
                indexed_principles,
                seed_index=(
                    int(seed_index)
                    + int(rotation_offset)
                    + parent_position
                    + probe_offset
                ),
                llm_authored_seed=True,
                selected_principle_ids=allowed_child_ids,
            )
            for item in allowed_pool:
                child_id = str(item[1].get("principle_id") or "")
                if (
                    str(item[1].get("lineage_base_operative_id") or "")
                    == base_id
                    and child_id != base_id
                    and child_id not in seen_child_ids
                ):
                    seen_child_ids.add(child_id)
                    children_list.append(item)
        children = tuple(children_list)
        variants_by_child = []
        for principle_index, principle in children:
            principle_id = str(principle.get("principle_id") or "")
            indexed_variants = tuple(zip(
                book_variation_indices(variant_count),
                diagnostic_anchor_sentence_variants(
                    seed,
                    tuple(principle["execution_verbs"]),
                    default_count=variant_count,
                ),
            ))
            if allowed_variant_indices is not None:
                indexed_variants = tuple(
                    item for item in indexed_variants
                    if int(item[0]) in allowed_variant_indices
                )
            if exact_variants_by_principle is not None:
                exact_variants = exact_variants_by_principle.get(
                    principle_id,
                    set(),
                )
                indexed_variants = tuple(
                    item for item in indexed_variants
                    if int(item[0]) in exact_variants
                )
            variants_by_child.append((
                principle_index,
                principle,
                indexed_variants,
            ))
        queue = [
            (principle_index, principle, variant_index, operations, parent)
            for variant_position in range(max(
                (len(variants) for _index, _principle, variants in variants_by_child),
                default=0,
            ))
            for principle_index, principle, variants in variants_by_child
            if variant_position < len(variants)
            for variant_index, operations in (variants[variant_position],)
            if not (
                replenishment_causal_request_hash
                and _replenishment_descendant_work_identity(
                    parent,
                    principle_id=str(principle.get("principle_id") or ""),
                    variant_index=int(variant_index),
                    causal_request_hash=replenishment_causal_request_hash,
                    reviewed_parent_authority=(
                        reviewed_parent_authority or {}
                    ),
                )["work_key"] in attempted_work_keys
            )
        ]
        if queue:
            parent_queues.append(queue)
    limit = (
        sum(len(queue) for queue in parent_queues)
        if schedule_cap is None or int(schedule_cap) <= 0
        else int(schedule_cap)
    )
    scheduled = []
    tuple_index = 0
    while len(scheduled) < limit:
        appended = False
        for queue in parent_queues:
            if tuple_index < len(queue):
                scheduled.append(queue[tuple_index])
                appended = True
                if len(scheduled) >= limit:
                    break
        if not appended:
            break
        tuple_index += 1
    if work_disposition_evidence is not None:
        all_candidate_count = sum(
            len(variants)
            for parent in reviewed_parents
            for principle in principles
            if str(principle.get("lineage_base_operative_id") or "")
            == str(parent.get("base_operative_id") or "")
            and str(principle.get("principle_id") or "")
            != str(parent.get("base_operative_id") or "")
            for variants in (book_variation_indices(variant_count),)
        )
        work_disposition_evidence.update({
            "schema_version": "arr.maas.replenishment_work_schedule.v1",
            "attempted_work_dispositions": [],
            "scheduled_work_count": len(scheduled),
            "skipped_attempted_work_count": max(
                0,
                all_candidate_count - len(scheduled),
            ) if attempted_work_keys else 0,
        })
    return tuple(scheduled)


def _replenishment_descendant_work_identity(
    parent_lineage: dict[str, Any],
    *,
    principle_id: str,
    variant_index: int,
    causal_request_hash: str,
    reviewed_parent_authority: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    parent_key = canonical_lineage_parent_key(parent_lineage)
    authority = reviewed_parent_authority.get(parent_key) or {}
    authority_payload = {
        "parent_key": parent_key,
        "geometry_hash": str(authority.get("geometry_hash") or ""),
        "program_hash": str(authority.get("program_hash") or ""),
        "base_review_fingerprint": str(
            authority.get("base_review_fingerprint") or ""
        ),
    }
    authority_fingerprint = hashlib.sha256(json.dumps(
        authority_payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    identity_payload = {
        "parent_authority_fingerprint": authority_fingerprint,
        "causal_request_hash": str(causal_request_hash or ""),
        "child_principle_id": str(principle_id or ""),
        "variant_index": int(variant_index),
    }
    return {
        **identity_payload,
        "work_key": hashlib.sha256(json.dumps(
            identity_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest(),
    }


def _begin_replenishment_work_disposition(
    identity: dict[str, Any],
    *,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    record = {
        **deepcopy(identity),
        "terminal_stage": "generation",
        "terminal_reason": "attempted",
    }
    evidence.setdefault("attempted_work_dispositions", []).append(record)
    return record


def _finish_replenishment_work_disposition(
    record: dict[str, Any] | None,
    *,
    terminal_stage: str,
    terminal_reason: str,
) -> None:
    if not isinstance(record, dict):
        return
    record["terminal_stage"] = str(terminal_stage or "generation_terminal")
    record["terminal_reason"] = str(terminal_reason or "not_released")


def _finalize_replenishment_work_dispositions(
    evidence: dict[str, Any],
    *,
    terminal_records: tuple[dict[str, Any], ...]
    | list[dict[str, Any]],
) -> None:
    unresolved = [
        record
        for record in evidence.get("attempted_work_dispositions", ())
        if isinstance(record, dict)
        and record.get("terminal_reason") == "attempted"
    ]
    failures = [
        record for record in terminal_records if isinstance(record, dict)
    ]
    for index, record in enumerate(unresolved):
        failure = failures[index] if index < len(failures) else {}
        failure_evidence = failure.get("evidence") or {}
        failure_evidence = (
            failure_evidence if isinstance(failure_evidence, dict) else {}
        )
        reason = (
            failure.get("reason")
            or failure.get("failure_reason")
            or failure_evidence.get("reason")
            or failure_evidence.get("failure_reason")
        )
        if not reason:
            reasons = (
                failure.get("failure_reasons")
                or failure.get("failed_gates")
                or failure_evidence.get("failure_reasons")
                or failure_evidence.get("failed_gates")
                or ()
            )
            reason = next(iter(reasons), "not_released")
        _finish_replenishment_work_disposition(
            record,
            terminal_stage=str(
                failure.get("stage") or "generation_terminal"
            ),
            terminal_reason=str(reason),
        )


def _llm_base_then_descendant_schedule(
    scheduled_principles: tuple[tuple[int, dict[str, Any]], ...],
) -> tuple[tuple[int, dict[str, Any]], ...]:
    """Execute each LLM lineage's BASE work before its descendants."""

    base_phase: list[tuple[int, dict[str, Any]]] = []
    descendant_phase: list[tuple[int, dict[str, Any]]] = []
    for item in scheduled_principles:
        principle = item[1]
        principle_id = str(principle.get("principle_id") or "")
        lineage_base_id = str(
            principle.get("lineage_base_operative_id") or principle_id
        )
        if (
            str(principle.get("generation_stage") or "") == "base"
            or principle_id == lineage_base_id
        ):
            base_phase.append(item)
        else:
            descendant_phase.append(item)
    return tuple(base_phase + descendant_phase)


def _competition_exact_key_parts(
    key: str,
) -> tuple[str, str, str] | None:
    seed_index, separator, remainder = str(key).partition(":")
    principle_id, variant_separator, variant_index = remainder.rpartition(":")
    if not separator or not variant_separator:
        return None
    if not seed_index.isdigit() or not variant_index.isdigit() or not principle_id:
        return None
    return seed_index, principle_id, variant_index


def _expand_competition_exact_lineage_dependencies(
    selected_keys: frozenset[str],
    principles: tuple[dict[str, Any], ...],
) -> frozenset[str]:
    """Add each selected descendant's exact base key or reject it closed."""

    principle_by_id = {
        str(principle.get("principle_id") or ""): principle
        for principle in principles
        if str(principle.get("principle_id") or "")
    }
    expanded: set[str] = set()
    for key in selected_keys:
        parts = _competition_exact_key_parts(key)
        if parts is None:
            continue
        seed_index, principle_id, variant_index = parts
        principle = principle_by_id.get(principle_id)
        if principle is None:
            continue
        base_id = str(
            principle.get("lineage_base_operative_id")
            or principle_id
        )
        base = principle_by_id.get(base_id)
        if base is None:
            continue
        if str(base.get("lineage_base_operative_id") or base_id) != base_id:
            continue
        expanded.add(key)
        expanded.add(f"{seed_index}:{base_id}:{variant_index}")
    return frozenset(expanded)


def _competition_base_anchor_keys(
    *,
    parent_count: int,
    principles: tuple[dict[str, Any], ...],
    book_probe_count: int,
) -> frozenset[str]:
    """Give every competition parent one registry-native BASE runway."""

    bases = tuple(
        principle
        for principle in principles
        if (
            str(principle.get("generation_stage") or "") == "base"
            or str(principle.get("principle_id") or "")
            == str(
                principle.get("lineage_base_operative_id")
                or principle.get("principle_id")
                or ""
            )
        )
    )
    variants = book_variation_indices(book_probe_count)
    if not bases or not variants:
        return frozenset()
    return frozenset(
        f"{seed_index}:"
        f"{bases[(seed_index * 7) % len(bases)]['principle_id']}:"
        f"{variants[seed_index % len(variants)]}"
        for seed_index in range(max(0, int(parent_count)))
    )


def _competition_language_anchor_keys(
    *,
    parent_count: int,
    principles: tuple[dict[str, Any], ...],
    book_probe_count: int,
) -> frozenset[str]:
    """Pair one rotated descendant language with its exact BASE per parent."""

    by_id = {
        str(principle.get("principle_id") or ""): principle
        for principle in principles
        if str(principle.get("principle_id") or "")
    }
    kind_order = ("combination", "aggregation", "case_study")
    by_kind = {
        kind: tuple(
            principle
            for principle in principles
            if str(principle.get("kind") or "") == kind
            or str(principle.get("generation_stage") or "") == kind
        )
        for kind in kind_order
    }
    variants = book_variation_indices(book_probe_count)
    if not variants or any(not by_kind[kind] for kind in kind_order):
        return frozenset()
    keys: set[str] = set()
    for seed_index in range(max(0, int(parent_count))):
        kind = kind_order[seed_index % len(kind_order)]
        descendants = by_kind[kind]
        descendant = descendants[(seed_index * 7) % len(descendants)]
        descendant_id = str(descendant.get("principle_id") or "")
        base_id = str(
            descendant.get("lineage_base_operative_id") or ""
        )
        if not descendant_id or base_id not in by_id:
            continue
        variant = variants[seed_index % len(variants)]
        keys.add(f"{seed_index}:{base_id}:{variant}")
        keys.add(f"{seed_index}:{descendant_id}:{variant}")
    return frozenset(keys)


def _competition_exact_principle_schedule(
    exact_keys: frozenset[str],
    principles: tuple[dict[str, Any], ...],
    *,
    seed_index: int,
) -> tuple[tuple[int, dict[str, Any]], ...]:
    """Materialize the exact shortlist, independent of local BOOK windows."""

    selected_ids = {
        parts[1]
        for key in exact_keys
        if (parts := _competition_exact_key_parts(key)) is not None
        and int(parts[0]) == int(seed_index)
    }
    selected = tuple(
        (index, principle)
        for index, principle in enumerate(principles)
        if str(principle.get("principle_id") or "") in selected_ids
    )
    return _llm_base_then_descendant_schedule(selected)


def _competition_exact_variant_schedule(
    exact_keys: frozenset[str],
    *,
    seed_index: int,
    principle_id: str,
    indexed_variants: tuple[tuple[int, tuple[Any, ...]], ...],
) -> tuple[tuple[int, tuple[Any, ...]], ...]:
    """Execute the variant encoded in each exact shortlist identity."""

    selected_variants = {
        int(parts[2])
        for key in exact_keys
        if (parts := _competition_exact_key_parts(key)) is not None
        and int(parts[0]) == int(seed_index)
        and parts[1] == str(principle_id)
    }
    return tuple(
        (variant_index, operations)
        for variant_index, operations in indexed_variants
        if int(variant_index) in selected_variants
    )


def _program_projection_evidence(
    program: GeometryProgram,
    bridge_evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    return recursive_book_projection_evidence(program, bridge_evidence)


_AUTHORED_PROJECTION_MAX_SILHOUETTE_DISTANCE = 0.40
_AUTHORED_LEGAL_CSG_MAX_SILHOUETTE_DISTANCE = 0.10
_AUTHORED_PROJECTION_IDENTITY_PREDICATE = (
    "preserve_pose_invariant_top_front_side_figure_and_do_not_"
    "invent_visible_step_morphology"
)
_AUTHORED_PROJECTION_IDENTITY_PREDICATE_VERSION = (
    "arr.maas.authored_projection_identity_predicate.v7_visible_step_distortion"
)
def _allow_tiny_geometry_gates() -> bool:
    """Check whether tiny-geometry gate relaxations are allowed."""

    return os.getenv("MAAS_ALLOW_TINY_GEOMETRY_GATES", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
_AUTHORED_STEP_OPERATORS = frozenset({
    "book_grade",
    "setback",
    "stack",
    "stepped_mass",
    "terrace",
})


def _authored_projection_terminal_stage(identity_evidence: dict[str, Any]) -> str:
    reasons = tuple(str(value) for value in identity_evidence.get("failure_reasons") or ())
    if "authored_ast_noop" in reasons:
        return "authored_ast_noop"
    if "book_projection_noop" in reasons:
        return "book_projection_noop"
    if any("authoritative_visual_surfaces_missing" in reason for reason in reasons):
        return "authored_visual_authority"
    return "authored_identity_collapse"


def _authored_projection_identity_evidence(
    authored_source: Any,
    projected_source: Any,
    *,
    enforce_morphology_preservation: bool = True,
    base_primitive_geometry_hash: str = "",
    authored_ast_geometry_hash: str = "",
    book_projection_required: bool = False,
    pre_book_program_hash: str = "",
    post_book_program_hash: str = "",
    pre_book_geometry_hash: str = "",
    post_book_geometry_hash: str = "",
) -> dict[str, Any]:
    """Certify that legal projection did not replace the authored architecture."""

    authored_metrics = authoritative_surface_morphology(authored_source)
    projected_metrics = authoritative_surface_morphology(projected_source)
    program = authored_source.metadata.get("geometry_program")
    program = program if isinstance(program, dict) else {}
    authored_operators = {
        str(node.get("operator") or "")
        for node in (program.get("nodes") or ())
        if isinstance(node, dict)
    }
    authored_step_intent = bool(
        authored_operators & _AUTHORED_STEP_OPERATORS
    )
    # A continuous taper/pyramid is an architectural section language, not a
    # staircase.  Portfolio selection may cap repeated pyramidal forms, while
    # identity protection hard-rejects only a genuinely new visible step (or
    # excessive silhouette distance).  Conflating the two discarded C119 even
    # though both authoritative surfaces reported ``visible_stepped=false``.
    authored_step_visible = bool(authored_metrics.get("visible_stepped"))
    projected_step_visible = bool(projected_metrics.get("visible_stepped"))
    silhouette_distance = float(authoritative_surface_silhouette_distance(authored_source, projected_source))
    visual_certificate = projected_source.metadata.get(
        "floorwise_visual_projection"
    )
    visual_certificate = (
        visual_certificate
        if isinstance(visual_certificate, dict)
        else {}
    )
    mandatory_legal_field_setback = False
    if (
        visual_certificate.get("status") == "certified"
        and visual_certificate.get("hard_pass") is True
        and (
            visual_certificate.get("certification_mode"),
            visual_certificate.get("visible_geometry_operation"),
        ) in {
            (
                "floorwise_profiled_continuous_envelope_clip",
                "authored_profiled_mesh_continuous_legal_envelope_intersection",
            ),
            (
                "floorwise_profiled_legal_clip",
                "authored_profiled_mesh_legal_solid_intersection",
            ),
        }
        and visual_certificate.get("visible_step_fallback") is False
    ):
        try:
            certified_artifact = serialize_certified_projected_visual(
                projected_source
            )
            certified_certificate = certified_artifact.get(
                "projectedVisualCertificate"
            )
            mandatory_legal_field_setback = bool(
                isinstance(certified_certificate, dict)
                and has_strict_height_dependent_legal_section_contraction(
                    certified_certificate
                )
            )
        except (AttributeError, TypeError, ValueError):
            mandatory_legal_field_setback = False
    maximum_silhouette_distance = (
        _AUTHORED_LEGAL_CSG_MAX_SILHOUETTE_DISTANCE
        if mandatory_legal_field_setback
        else _AUTHORED_PROJECTION_MAX_SILHOUETTE_DISTANCE
    )
    failures: list[str] = []
    diagnostic_reasons: list[str] = []
    internal_void_step_signal = bool(
        authored_metrics.get("phenotype") == "voided"
        and projected_step_visible
        and not authored_step_visible
        and not authored_step_intent
        and silhouette_distance <= 1e-6
        and visual_certificate.get("visible_step_fallback") is not True
    )
    if not authored_metrics.get("hard_pass"):
        failures.append("authored_authoritative_visual_surfaces_missing")
    if not projected_metrics.get("hard_pass"):
        failures.append("projected_authoritative_visual_surfaces_missing")
    if (
        authored_metrics.get("hard_pass")
        and projected_metrics.get("hard_pass")
        and
        projected_step_visible
        and not authored_step_visible
        and not authored_step_intent
        and not internal_void_step_signal
    ):
        (
            failures
            if enforce_morphology_preservation
            else diagnostic_reasons
        ).append("unrequested_legal_step_collapse")
    if internal_void_step_signal:
        diagnostic_reasons.append(
            "internal_void_surface_step_signal_ignored"
        )
    if (
        authored_metrics.get("hard_pass")
        and projected_metrics.get("hard_pass")
        and
        silhouette_distance > maximum_silhouette_distance
        and not authored_step_intent
    ):
        failures.append(
            "authored_projection_silhouette_distance_exceeded"
        )
    if (
        visual_certificate.get("visible_step_fallback") is True
        and not authored_step_visible
        and not authored_step_intent
    ):
        failures.append("unrequested_visible_step_fallback")
    if (
        base_primitive_geometry_hash
        and authored_ast_geometry_hash
        and base_primitive_geometry_hash == authored_ast_geometry_hash
    ):
        failures.append("authored_ast_noop")
    if book_projection_required:
        program_noop = bool(
            pre_book_program_hash
            and post_book_program_hash
            and pre_book_program_hash == post_book_program_hash
        )
        geometry_noop = bool(
            pre_book_geometry_hash
            and post_book_geometry_hash
            and pre_book_geometry_hash == post_book_geometry_hash
        )
        if program_noop or geometry_noop:
            failures.append("book_projection_noop")
    try:
        authored_surface_hash = source_surface_payload_hash(tuple(authored_source.surfaces or ()))
    except (AttributeError, TypeError, ValueError):
        authored_surface_hash = ""
    try:
        projected_surface_hash = source_surface_payload_hash(tuple(projected_source.surfaces or ()))
    except (AttributeError, TypeError, ValueError):
        projected_surface_hash = ""
    try:
        authored_proxy_hash = source_volume_payload_hash(tuple(authored_source.volumes or ()))
    except (AttributeError, TypeError, ValueError):
        authored_proxy_hash = "invalid_proxy_volume_payload"
    try:
        projected_proxy_hash = source_volume_payload_hash(tuple(projected_source.volumes or ()))
    except (AttributeError, TypeError, ValueError):
        projected_proxy_hash = "invalid_proxy_volume_payload"
    frozen_identity_evidence = {
        "schema_version": "arr.maas.authored_projection_identity_frozen.v1",
        "frozen_at_source_pair_comparison": True,
        "predicate": _AUTHORED_PROJECTION_IDENTITY_PREDICATE,
        "predicate_version": _AUTHORED_PROJECTION_IDENTITY_PREDICATE_VERSION,
        "before_phenotype": str(authored_metrics.get("phenotype") or ""),
        "after_phenotype": str(projected_metrics.get("phenotype") or ""),
        "before_step_visible": authored_step_visible,
        "after_step_visible": projected_step_visible,
        "step_requested": authored_step_intent,
        "raw_silhouette_distance": silhouette_distance,
        "maximum_silhouette_distance": (
            maximum_silhouette_distance
        ),
    }
    return {
        "schema_version": "arr.maas.authored_projection_identity.v1",
        "status": (
            "fail"
            if failures
            else "pass_with_revision_signal"
            if diagnostic_reasons
            else "pass"
        ),
        "hard_pass": not failures,
        "failure_reasons": failures,
        "diagnostic_reasons": diagnostic_reasons,
        "typed_revision_signal": {
            "schema_version": "arr.maas.projected_identity_revision_signal.v1",
            "active": bool(failures or diagnostic_reasons),
            "hard_gate": bool(failures),
            "route": "typed_revision_or_vlm_review",
            "reasons": list(dict.fromkeys(
                [*failures, *diagnostic_reasons]
            )),
        },
        "mandatory_legal_field_setback": mandatory_legal_field_setback,
        "visual_identity_authority": "profiled_surface_payload",
        "authored_surface_payload_hash": authored_surface_hash,
        "projected_surface_payload_hash": projected_surface_hash,
        "proxy_volume_hashes_diagnostic_only": True,
        "authored_proxy_volume_payload_hash": authored_proxy_hash,
        "projected_proxy_volume_payload_hash": projected_proxy_hash,
        "authored_program_operators": sorted(authored_operators),
        "authored_step_intent": authored_step_intent,
        "frozen_identity_evidence": frozen_identity_evidence,
        "authored_phenotype": str(
            authored_metrics.get("phenotype") or ""
        ),
        "projected_phenotype": str(
            projected_metrics.get("phenotype") or ""
        ),
        "authored_visible_stepped": bool(
            authored_metrics.get("visible_stepped")
        ),
        "projected_visible_stepped": bool(
            projected_metrics.get("visible_stepped")
        ),
        "authored_pyramidal_like": bool(
            authored_metrics.get("pyramidal_like")
        ),
        "projected_pyramidal_like": bool(
            projected_metrics.get("pyramidal_like")
        ),
        "silhouette_distance": round(silhouette_distance, 6),
        "maximum_silhouette_distance": (
            maximum_silhouette_distance
        ),
        "visible_step_fallback": bool(
            visual_certificate.get("visible_step_fallback")
        ),
        "base_primitive_geometry_hash": str(base_primitive_geometry_hash),
        "authored_ast_geometry_hash": str(authored_ast_geometry_hash),
        "book_projection_required": bool(book_projection_required),
        "pre_book_program_hash": str(pre_book_program_hash),
        "post_book_program_hash": str(post_book_program_hash),
        "pre_book_geometry_hash": str(pre_book_geometry_hash),
        "post_book_geometry_hash": str(post_book_geometry_hash),
        "identity_policy": _AUTHORED_PROJECTION_IDENTITY_PREDICATE,
        "identity_policy_version": (
            _AUTHORED_PROJECTION_IDENTITY_PREDICATE_VERSION
        ),
    }


_TERMINAL_CERTIFICATE_EVIDENCE_SCHEMA_VERSION = (
    "arr.maas.authored_visual_authority_terminal_certificate.v1"
)
_TERMINAL_CERTIFICATE_STRING_LIMIT = 160
_TERMINAL_CERTIFICATE_REASON_LIMIT = 12
_TERMINAL_CERTIFICATE_WITNESS_LIMIT = 48
_TERMINAL_FLOOR_UNION_ENDPOINT_EVIDENCE_FIELDS = frozenset(
    f"{endpoint}_{field}"
    for endpoint in ("ground", "upper")
    for field in (
        "geom_type",
        "is_valid",
        "validity_reason",
        "is_empty",
        "aggregate_area_m2",
        "component_count",
        "polygon_count",
        "largest_polygon_area_m2",
        "post_repair_geom_type",
        "failure_branch",
    )
)
_TERMINAL_EVIDENCE_SCALAR_FIELDS = frozenset({
    "repair_reason",
    "failure_reason",
    "legal_floor_field_hash",
    "floor_index",
    "floor_count",
    "floor_union_count",
    "measured_section_present",
    "fitted_floor_count",
    "source_volume_count",
    "legal_section_count",
    "viable_section_count",
    "source_present",
    "legal_present",
    "containment",
    "stage_detail",
}) | _TERMINAL_FLOOR_UNION_ENDPOINT_EVIDENCE_FIELDS
_TERMINAL_EVIDENCE_LIST_FIELDS = frozenset({
    "failure_reasons",
    "certificate_causes",
    "certificate_modes",
    "identity_failure_reasons",
})


def _bounded_terminal_record_evidence(raw_evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the explicit coordinate-free terminal certificate schema."""

    bounded: dict[str, Any] = {}
    for key in _TERMINAL_EVIDENCE_SCALAR_FIELDS:
        value = raw_evidence.get(key)
        if isinstance(value, str):
            bounded[key] = value[:_TERMINAL_CERTIFICATE_STRING_LIMIT]
        elif isinstance(value, (bool, int, float)) or value is None:
            if key in raw_evidence:
                bounded[key] = value
    for key in _TERMINAL_EVIDENCE_LIST_FIELDS:
        value = raw_evidence.get(key)
        if not isinstance(value, (list, tuple)):
            continue
        bounded[key] = list(dict.fromkeys(
            str(item)[:_TERMINAL_CERTIFICATE_STRING_LIMIT]
            for item in value[:_TERMINAL_CERTIFICATE_REASON_LIMIT]
            if isinstance(item, str) and item
        ))
    failure_witness = raw_evidence.get("failure_witness")
    if isinstance(failure_witness, dict):
        bounded_witness: dict[str, Any] = {}
        for key in sorted(failure_witness, key=str):
            if len(bounded_witness) >= _TERMINAL_CERTIFICATE_WITNESS_LIMIT:
                break
            value = failure_witness[key]
            if isinstance(value, str):
                bounded_witness[str(key)] = value[
                    :_TERMINAL_CERTIFICATE_STRING_LIMIT
                ]
            elif isinstance(value, (bool, int, float)) or value is None:
                bounded_witness[str(key)] = value
            elif (
                str(key) == "failed_predicates"
                and isinstance(value, (list, tuple))
            ):
                bounded_witness[str(key)] = list(dict.fromkeys(
                    str(item)[:_TERMINAL_CERTIFICATE_STRING_LIMIT]
                    for item in value[:_TERMINAL_CERTIFICATE_REASON_LIMIT]
                    if isinstance(item, str) and item
                ))
            elif (
                str(key) == "profiled_mesh_revalidation"
                and isinstance(value, dict)
            ):
                typed_revalidation: dict[str, Any] = {}
                for typed_key in (
                    "repair_attempted",
                    "max_physical_displacement_m",
                    "raw_component_count",
                    "post_repair_component_count",
                ):
                    typed_value = value.get(typed_key)
                    if isinstance(typed_value, (bool, int, float)):
                        typed_revalidation[typed_key] = typed_value
                for typed_key in (
                    "raw_gate_codes",
                    "post_repair_gate_codes",
                ):
                    typed_value = value.get(typed_key)
                    if isinstance(typed_value, (list, tuple)):
                        typed_revalidation[typed_key] = list(dict.fromkeys(
                            str(item)[:_TERMINAL_CERTIFICATE_STRING_LIMIT]
                            for item in typed_value[
                                :_TERMINAL_CERTIFICATE_REASON_LIMIT
                            ]
                            if isinstance(item, str) and item
                        ))
                numeric = value.get("numeric_measurements")
                if isinstance(numeric, dict):
                    typed_revalidation["numeric_measurements"] = {
                        str(name): measurement
                        for name, measurement in list(numeric.items())[:8]
                        if isinstance(measurement, (int, float))
                    }
                attempts = value.get("attempt_records")
                if isinstance(attempts, list):
                    bounded_attempts = []
                    required_numeric = (
                        "threshold_m",
                        "max_chain_displacement_m",
                        "minimum_surviving_edge_physical_m",
                        "minimum_surviving_edge_coordinate",
                    )
                    for attempt in attempts[:5]:
                        if not isinstance(attempt, dict):
                            continue
                        numeric_values = {
                            name: attempt.get(name) for name in required_numeric
                        }
                        if not all(
                            isinstance(measurement, (int, float))
                            and measurement == measurement
                            and abs(float(measurement)) != float("inf")
                            for measurement in numeric_values.values()
                        ):
                            continue
                        reason = attempt.get("termination_reason")
                        endpoints = attempt.get("minimum_edge_endpoint_indices")
                        delta = attempt.get("minimum_edge_delta_xyz")
                        post_codes = attempt.get("post_gate_codes")
                        structural = attempt.get("structural_evidence")
                        if (
                            reason not in {
                                "no_eligible_edge",
                                "chain_displacement_exceeded",
                                "invalid_effective_height",
                                "completed",
                            }
                            or not isinstance(attempt.get("collapse_count"), int)
                            or not isinstance(attempt.get("raw_component_count"), int)
                            or not isinstance(attempt.get("post_component_count"), int)
                            or not isinstance(attempt.get("selected_as_final"), bool)
                            or not isinstance(endpoints, list)
                            or len(endpoints) > 2
                            or not all(isinstance(index, int) for index in endpoints)
                            or not isinstance(delta, list)
                            or len(delta) != 3
                            or not all(
                                isinstance(measurement, (int, float))
                                and measurement == measurement
                                and abs(float(measurement)) != float("inf")
                                for measurement in delta
                            )
                            or not isinstance(post_codes, list)
                            or not all(isinstance(code, str) for code in post_codes[:12])
                            or not isinstance(structural, dict)
                            or not all(
                                isinstance(name, str) and isinstance(flag, bool)
                                for name, flag in structural.items()
                            )
                        ):
                            continue
                        bounded_attempts.append({
                            **numeric_values,
                            "collapse_count": attempt["collapse_count"],
                            "termination_reason": reason,
                            "minimum_edge_endpoint_indices": endpoints[:2],
                            "minimum_edge_delta_xyz": list(delta),
                            "post_gate_codes": list(dict.fromkeys(post_codes[:12])),
                            "raw_component_count": attempt["raw_component_count"],
                            "post_component_count": attempt["post_component_count"],
                            "structural_evidence": dict(
                                list(structural.items())[:5]
                            ),
                            "selected_as_final": attempt["selected_as_final"],
                        })
                    typed_revalidation["attempt_records"] = bounded_attempts
                bounded_witness[str(key)] = typed_revalidation
        bounded["failure_witness"] = bounded_witness
    plate_failures = raw_evidence.get("plate_recertification_failures")
    if isinstance(plate_failures, (list, tuple)):
        bounded_plate_failures: list[dict[str, Any]] = []
        for raw_plate in plate_failures[:_TERMINAL_CERTIFICATE_REASON_LIMIT]:
            if not isinstance(raw_plate, dict):
                continue
            bounded_plate: dict[str, Any] = {}
            for key in ("floor_index", "floor"):
                value = raw_plate.get(key)
                if isinstance(value, (bool, int, float, str)) or value is None:
                    bounded_plate[key] = value
            for key in ("reasons", "contract_failure_reasons"):
                values = raw_plate.get(key)
                if isinstance(values, (list, tuple)):
                    bounded_plate[key] = list(dict.fromkeys(
                        str(value)[:_TERMINAL_CERTIFICATE_STRING_LIMIT]
                        for value in values[:_TERMINAL_CERTIFICATE_REASON_LIMIT]
                        if isinstance(value, str) and value
                    ))
            for key in ("measured_values", "thresholds", "threshold_sources"):
                values = raw_plate.get(key)
                if not isinstance(values, dict):
                    continue
                bounded_values: dict[str, Any] = {}
                for value_key in sorted(values, key=str):
                    value = values[value_key]
                    if isinstance(value, str):
                        bounded_values[str(value_key)] = value[
                            :_TERMINAL_CERTIFICATE_STRING_LIMIT
                        ]
                    elif isinstance(value, (bool, int, float)) or value is None:
                        bounded_values[str(value_key)] = value
                bounded_plate[key] = bounded_values
            bounded_plate_failures.append(bounded_plate)
        bounded["plate_recertification_failures"] = bounded_plate_failures
    identity = raw_evidence.get("identity_evidence")
    if isinstance(identity, dict):
        identity_reasons = identity.get("failure_reasons")
        if isinstance(identity_reasons, (list, tuple)):
            bounded["identity_failure_reasons"] = list(dict.fromkeys(
                str(item)[:_TERMINAL_CERTIFICATE_STRING_LIMIT]
                for item in identity_reasons[:_TERMINAL_CERTIFICATE_REASON_LIMIT]
                if isinstance(item, str) and item
            ))
        frozen_identity = identity.get("frozen_identity_evidence")
        if isinstance(frozen_identity, dict):
            bounded["frozen_identity_evidence"] = deepcopy(
                frozen_identity
            )
    return bounded


def _authored_visual_authority_subreason(
    *,
    stage: str,
    repair_reason: str,
    failure_reason: str,
    certificate_causes: Sequence[str] = (),
    certificate_modes: Sequence[str] = (),
) -> str:
    """Classify terminal visual-authority failures without naming a form."""

    if stage != "authored_visual_authority":
        return ""
    detail = " ".join((
        repair_reason,
        failure_reason,
        *certificate_causes,
        *certificate_modes,
    )).lower()
    if any(token in detail for token in (
        "empty",
        "no_valid_surface",
        "no_valid_surfaces",
        "no valid surface",
        "no valid surfaces",
        "surface_missing",
        "surfaces_missing",
        "surface absent",
        "surfaces absent",
    )):
        return "authored_visual_authority_empty_or_no_valid_surface"
    if "revalidat" in detail:
        return "authored_visual_authority_revalidation"
    if repair_reason == "authored_matrix4_projection_failed":
        return "authored_visual_authority_matrix4_projection"
    if repair_reason == "authored_profiled_legal_clip_failed":
        return "authored_visual_authority_profiled_clip"
    return "authored_visual_authority_csg_midplane_certificate"


def _terminal_certificate_evidence(
    *,
    stage: str,
    evidence: Mapping[str, Any],
    program: Any,
    source_seed: str,
    book_scope: str,
    legal_floor_field_hash: str,
) -> dict[str, Any]:
    """Return a small coordinate-free repair payload for later AST authoring."""

    repair_reason = str(evidence.get("repair_reason") or "")[:_TERMINAL_CERTIFICATE_STRING_LIMIT]
    failure_reason = str(evidence.get("failure_reason") or "")[:_TERMINAL_CERTIFICATE_STRING_LIMIT]
    raw_failure_reasons = evidence.get("failure_reasons") or ()
    failure_reasons = [
        str(value)[:_TERMINAL_CERTIFICATE_STRING_LIMIT]
        for value in raw_failure_reasons[:_TERMINAL_CERTIFICATE_REASON_LIMIT]
        if str(value)
    ] if isinstance(raw_failure_reasons, (list, tuple)) else []
    program_payload = program.to_dict() if hasattr(program, "to_dict") else {}
    program_metadata = (
        program_payload.get("metadata")
        if isinstance(program_payload, dict)
        and isinstance(program_payload.get("metadata"), dict)
        else {}
    )
    program_hash = str(
        program.program_hash() if hasattr(program, "program_hash") else ""
    )[:_TERMINAL_CERTIFICATE_STRING_LIMIT]
    raw_causes = evidence.get("certificate_causes") or failure_reasons
    certificate_causes = list(dict.fromkeys(
        str(value)[:_TERMINAL_CERTIFICATE_STRING_LIMIT]
        for value in raw_causes[:_TERMINAL_CERTIFICATE_REASON_LIMIT]
        if isinstance(value, str) and value
    )) if isinstance(raw_causes, (list, tuple)) else []
    raw_modes = evidence.get("certificate_modes") or ()
    certificate_modes = list(dict.fromkeys(
        str(value)[:_TERMINAL_CERTIFICATE_STRING_LIMIT]
        for value in raw_modes[:_TERMINAL_CERTIFICATE_REASON_LIMIT]
        if isinstance(value, str) and value
    )) if isinstance(raw_modes, (list, tuple)) else []
    subreason = _authored_visual_authority_subreason(
        stage=stage,
        repair_reason=repair_reason,
        failure_reason=failure_reason,
        certificate_causes=certificate_causes,
        certificate_modes=certificate_modes,
    )
    certificate = {
        "schema_version": _TERMINAL_CERTIFICATE_EVIDENCE_SCHEMA_VERSION,
        "structural_failure": str(stage)[:_TERMINAL_CERTIFICATE_STRING_LIMIT],
        "structural_subreason": subreason,
        "repair_reason": repair_reason,
        "failure_reason": failure_reason,
        "failure_reasons": failure_reasons,
        "certificate_causes": certificate_causes,
        "certificate_modes": certificate_modes,
        "hard_fail_closed": stage == "authored_visual_authority",
        "visual_authority": "profiled_surface_payload",
        "legal_floor_loft_or_prism_replay_allowed": False,
        "program_hash": program_hash,
        "geometry_family": str(program_metadata.get("family") or "")[:_TERMINAL_CERTIFICATE_STRING_LIMIT],
        "book_scope": str(book_scope)[:_TERMINAL_CERTIFICATE_STRING_LIMIT],
        "legal_floor_field_hash": str(
            evidence.get("legal_floor_field_hash") or legal_floor_field_hash
        )[:_TERMINAL_CERTIFICATE_STRING_LIMIT],
        "source_seed": str(source_seed)[:_TERMINAL_CERTIFICATE_STRING_LIMIT],
    }
    frozen_identity = evidence.get("frozen_identity_evidence")
    if isinstance(frozen_identity, dict):
        certificate["frozen_identity_evidence"] = deepcopy(
            frozen_identity
        )
    plate_failures = evidence.get("plate_recertification_failures")
    if isinstance(plate_failures, list):
        certificate["plate_recertification_failures"] = deepcopy(
            plate_failures
        )
    return certificate


def _propagate_terminal_materialization_failure(
    *,
    terminal_record: dict[str, Any],
    report_records: list[dict[str, Any]],
    outcome_graph: Any | None,
    program_slug: str,
    source_seed: str,
    program: Any,
    principle_id: str,
    book_scope: str,
    legal_floor_field_hash: str = "",
) -> None:
    """Preserve one bounded typed terminal record without string flattening."""

    raw_stage = str(terminal_record.get("stage") or "outer_precondition")
    stage = (
        "authored_visual_authority"
        if raw_stage == "visual_projection_or_replay"
        else raw_stage
    )
    raw_evidence = terminal_record.get("evidence")
    raw_evidence = raw_evidence if isinstance(raw_evidence, dict) else {}
    evidence = _bounded_terminal_record_evidence(raw_evidence)
    if raw_stage == "visual_projection_or_replay":
        evidence.setdefault(
            "repair_reason",
            "authored_visual_projection_revalidation_failed",
        )
        evidence.setdefault(
            "failure_reason",
            "revalidation_floor_section_mismatch",
        )
        evidence.setdefault(
            "failure_reasons",
            [evidence["failure_reason"]],
        )
        evidence.setdefault(
            "certificate_causes",
            list(evidence["failure_reasons"]),
        )
        evidence.setdefault(
            "certificate_modes",
            ["post_projection_section_revalidation"],
        )
    certificate_evidence = _terminal_certificate_evidence(
        stage=stage,
        evidence=evidence,
        program=program,
        source_seed=source_seed,
        book_scope=book_scope,
        legal_floor_field_hash=legal_floor_field_hash,
    )
    record = {
        "stage": stage,
        "evidence": evidence,
        "terminal_certificate_evidence": certificate_evidence,
    }
    report_records.append(record)
    del report_records[:-48]
    if outcome_graph is None:
        return
    failure_reason = str(evidence.get("failure_reason") or "")
    structural_subreason = str(
        certificate_evidence.get("structural_subreason") or ""
    )
    identity_reasons = tuple(
        str(value) for value in evidence.get("identity_failure_reasons") or ()
    )
    reasons = tuple(dict.fromkeys(
        value for value in (
            stage,
            structural_subreason,
            failure_reason,
            *identity_reasons,
        ) if value
    ))
    outcome_graph.observe_geometry_gate_failure(
        program_slug=program_slug,
        source_seed=source_seed,
        program=program,
        principle_id=principle_id,
        book_scope=book_scope,
        stage=stage,
        failure_reasons=reasons,
        terminal_certificate_evidence=certificate_evidence,
        legal_floor_field_hash=str(
            certificate_evidence.get("legal_floor_field_hash") or ""
        ),
    )
    observations = getattr(outcome_graph, "observations", None)
    if not isinstance(observations, list):
        return
    for observation in reversed(observations):
        if (
            str(observation.get("geometry_gate_stage") or "") == stage
            and str(observation.get("program_slug") or "") == str(program_slug)
        ):
            observation["terminal_materialization_evidence"] = deepcopy(evidence)
            observation["terminal_certificate_evidence"] = deepcopy(
                certificate_evidence
            )
            break


def _record_generation_stage_outcome(
    outcome: StageOutcome[Any],
    *,
    stage_outcomes: list[dict[str, Any]],
    terminal_records: list[dict[str, Any]],
    outcome_graph: Any | None,
    program_slug: str,
    source_seed: str,
    program: Any,
    principle_id: str,
    book_scope: str,
    legal_floor_field_hash: str,
    counter_updates: tuple[tuple[dict[str, int], str], ...] = (),
) -> None:
    def record_terminal(failed: StageOutcome[Any]) -> None:
        evidence = deepcopy(dict(failed.evidence))
        evidence["failure_reason"] = failed.reason
        evidence.setdefault("failure_reasons", [failed.reason])
        _propagate_terminal_materialization_failure(
            terminal_record={"stage": failed.stage, "evidence": evidence},
            report_records=terminal_records,
            outcome_graph=outcome_graph,
            program_slug=program_slug,
            source_seed=source_seed,
            program=program,
            principle_id=principle_id,
            book_scope=book_scope,
            legal_floor_field_hash=legal_floor_field_hash,
        )

    record_stage_outcome(
        outcome,
        records=stage_outcomes,
        counter_updates=counter_updates,
        terminal_recorder=record_terminal,
    )


def _record_projection_authority_failure(
    *,
    authority_evidence: dict[str, Any],
    report_records: list[dict[str, Any]],
    outcome_graph: Any | None,
    program_slug: str,
    source_seed: str,
    program: Any,
    principle_id: str,
    book_scope: str,
    legal_floor_field_hash: str,
    scope_counts: dict[str, int],
    geometry_stages: dict[str, int] | None,
    llm_authored_failure_counts: dict[str, int] | Counter[str],
    stage_outcomes: list[dict[str, Any]] | None = None,
) -> None:
    """Record legal authority attrition before projection evidence exists."""
    failure_reason = str(
        authority_evidence.get("failure_reason")
        or "legal_capacity_authority_rejected"
    )
    contract_failures = sorted({
        str(value)
        for values in (
            authority_evidence.get("shared_floor_contract_failure_reasons") or (),
            authority_evidence.get("plate_recertification_failure_reasons") or (),
        )
        for value in values
        if str(value)
    })
    failure_witness = {
        str(key): value
        for key, value in authority_evidence.items()
        if key not in {
            "schema_version",
            "failure_reason",
            "failure_reasons",
            "shared_floor_contract_failure_reasons",
            "plate_recertification_failures",
            "plate_recertification_failure_reasons",
        }
        and (
            isinstance(value, (bool, int, float, str))
            or value is None
        )
    }
    outcome = StageOutcome.failed(
        "projection_authority",
        failure_reason,
        evidence={
            "failure_reason": failure_reason,
            "failure_reasons": [failure_reason],
            "certificate_causes": contract_failures,
            "certificate_modes": ["legal_capacity_authority"],
            "failure_witness": failure_witness,
            "plate_recertification_failures": list(
                authority_evidence.get("plate_recertification_failures") or []
            ),
        },
    )
    counter_updates: list[tuple[dict[str, int], str]] = [
        (scope_counts, "projection_failed"),
        (llm_authored_failure_counts, failure_reason),
    ]
    if geometry_stages is not None:
        counter_updates.extend((
            (geometry_stages, "projection_failed"),
            (geometry_stages, "projection_authority_failed"),
        ))
    _record_generation_stage_outcome(
        outcome,
        stage_outcomes=(stage_outcomes if stage_outcomes is not None else []),
        terminal_records=report_records,
        outcome_graph=outcome_graph,
        program_slug=program_slug,
        source_seed=source_seed,
        program=program,
        principle_id=principle_id,
        book_scope=book_scope,
        legal_floor_field_hash=legal_floor_field_hash,
        counter_updates=tuple(counter_updates),
    )


def _record_clean_mass_rejection(
    *,
    source: Any,
    clean_mass_evidence: dict[str, Any],
    report_records: list[dict[str, Any]],
    outcome_graph: Any | None,
    program_slug: str,
    source_seed: str,
    program: Any,
    principle_id: str,
    book_scope: str,
    legal_floor_field_hash: str = "",
) -> dict[str, Any]:
    """Persist one typed clean-mass rejection without a mesh payload."""
    source_metadata = (
        source.metadata
        if isinstance(getattr(source, "metadata", None), dict)
        else {}
    )
    bridge = source_metadata.get("geometry_program_bridge_evidence") or {}
    bridge = bridge if isinstance(bridge, dict) else {}
    program_metadata = getattr(program, "metadata", {})
    program_metadata = (
        program_metadata if isinstance(program_metadata, dict) else {}
    )
    program_hash = str(
        bridge.get("program_hash")
        or (
            program.program_hash()
            if hasattr(program, "program_hash")
            else ""
        )
    )
    geometry_family = str(
        source_metadata.get("family")
        or program_metadata.get("family")
        or "recursive_solid"
    )
    subreasons = tuple(
        str(value)
        for value in clean_mass_evidence.get("subreasons")
        or clean_mass_evidence.get("failure_reasons")
        or ()
        if str(value)
    )
    measurements = deepcopy(
        clean_mass_evidence.get("measurements") or {}
    )
    artifact = {
        "schema_version": "arr.maas.clean_mass_rejection.v1",
        "stage": "clean_mass",
        "hard_pass": False,
        "subreasons": list(subreasons),
        "measurements": measurements,
        "program_hash": program_hash,
        "geometry_family": geometry_family,
        "book_principle_id": str(principle_id),
        "book_scope": str(book_scope),
    }
    report_records.append(artifact)
    del report_records[:-48]
    if outcome_graph is not None and subreasons:
        outcome_graph.observe_geometry_gate_failure(
            program_slug=program_slug,
            source_seed=source_seed,
            program=program,
            principle_id=principle_id,
            book_scope=book_scope,
            stage="clean_mass",
            failure_reasons=subreasons,
            source=source,
            terminal_certificate_evidence={
                "schema_version": "arr.maas.clean_mass_rejection.v1",
                "structural_failure": True,
                "structural_subreason": subreasons[0],
                "failure_reason": subreasons[0],
                "failure_reasons": list(subreasons),
                "certificate_causes": [{
                    "subreasons": list(subreasons),
                    "measurements": measurements,
                }],
                "certificate_modes": ["clean_mass_gate"],
                "program_hash": program_hash,
                "geometry_family": geometry_family,
                "book_scope": str(book_scope),
                "legal_floor_field_hash": str(legal_floor_field_hash),
                "source_seed": str(source_seed),
            },
            legal_floor_field_hash=legal_floor_field_hash,
        )
    return artifact


def _issue_authored_legal_projection_authority(
    authored_source: Any,
    projected_source: Any,
    *,
    authored_program: GeometryProgram,
    authored_compilation: Any,
    building_type: str,
    containment_host: Polygon,
    pnu: str,
    legal_floor_field_hash: str,
    floor_capacity_plan_hash: str,
    target_floor_areas_m2: tuple[float, ...],
    capacity_measurement: dict[str, Any],
    capacity_projection: dict[str, Any],
    failure_sink: list[dict[str, Any]] | None = None,
) -> Any | None:
    """Issue a complete authority chain from the newly projected surface."""

    def fail(reason: str, **evidence: Any) -> None:
        if failure_sink is not None:
            failure_sink.append({
                "schema_version": (
                    "arr.maas.authored_legal_projection_issuance_failure.v1"
                ),
                "stage": "authored_legal_projection_authority_issuance",
                "reason": reason,
                "evidence": deepcopy(evidence),
            })

    compilation_geometry_hash = str(
        getattr(authored_compilation, "geometry_hash", "") or ""
    )
    program_hash = authored_program.program_hash()
    targets = tuple(float(value) for value in target_floor_areas_m2)
    if (
        getattr(authored_compilation, "status", "") != "compiled"
        or not program_hash
        or not compilation_geometry_hash
        or len(str(legal_floor_field_hash or "")) != 64
        or len(str(floor_capacity_plan_hash or "")) != 64
        or not str(pnu or "")
        or not targets
        or not projected_source.surfaces
        or not projected_source.volumes
        or not capacity_measurement
        or not capacity_projection
    ):
        fail(
            "authority_issuance_precondition_failed",
            program_hash=program_hash,
            compilation_geometry_hash=compilation_geometry_hash,
            legal_floor_field_hash=str(legal_floor_field_hash or ""),
            floor_capacity_plan_hash=str(floor_capacity_plan_hash or ""),
            surface_count=len(projected_source.surfaces or ()),
            proxy_volume_count=len(projected_source.volumes or ()),
        )
        return None

    final_geometry_hash = final_floorwise_visual_geometry_hash(projected_source)
    surface_payload_hash = source_surface_payload_hash(
        tuple(projected_source.surfaces)
    )
    proxy_payload_hash = source_volume_payload_hash(
        tuple(projected_source.volumes)
    )
    if not final_geometry_hash or not surface_payload_hash or not proxy_payload_hash:
        fail("authority_payload_hash_missing")
        return None

    band_counts = Counter(
        (float(volume.bottom_fraction), float(volume.top_fraction))
        for volume in projected_source.volumes
    )
    achieved_floor_areas = tuple(
        sum(
            float(volume.footprint.area)
            for volume in projected_source.volumes
            if (
                float(volume.bottom_fraction),
                float(volume.top_fraction),
            ) == band
        )
        for band in sorted(band_counts)
    )
    requested_floor_area = sum(targets)
    achieved_floor_area = sum(achieved_floor_areas)
    certificate = {
        "schema_version": "arr.maas.authored_legal_projection_certificate.v1",
        "status": "verified",
        "hard_pass": True,
        "input_authored_program_hash": program_hash,
        "input_authored_geometry_hash": compilation_geometry_hash,
        "legal_floor_field_hash": str(legal_floor_field_hash),
        "projected_surface_hash": final_geometry_hash,
        "projected_surface_payload_hash": surface_payload_hash,
        "legal_proxy_role": "analysis_only_gfa_parking_containment",
    }
    compilation_payload = authored_compilation.to_dict(include_mesh=False)
    metadata = deepcopy(projected_source.metadata)
    projection = deepcopy(metadata.get("floorwise_legal_matrix_stack") or {})
    projection.update({
        "projection_mode": "floorwise_matrix_field_authored_mesh_preserved",
        "hard_pass": True,
        "final_program_hash": program_hash,
        "final_geometry_hash": final_geometry_hash,
        "authored_legal_projection_certificate": deepcopy(certificate),
    })
    bridge = deepcopy(metadata.get("geometry_program_bridge_evidence") or {})
    for stale_key in (
        "authored_legal_projection_certificate",
        "post_book_authored_program_hash",
        "post_book_authored_geometry_hash",
        "final_projected_surface_hash",
        "final_projected_surface_payload_hash",
        "geometry_authority",
    ):
        bridge.pop(stale_key, None)
    bridge.update({
        "program_hash": program_hash,
        "geometry_hash": final_geometry_hash,
        # Three routes write this identity, and when the final visual authority
        # certificate refuses it, the digest alone cannot say which one put the
        # value there. A guard at the write itself cannot help: the hash is
        # taken from the very object being written, so it always agrees here
        # and the drift happens further downstream. Naming the writer is what
        # turns that refusal into an address.
        "bridge_identity_writer": "floorwise_matrix_field",
        "surface_payload_hash": surface_payload_hash,
        "raw_mesh_triangle_count": len(projected_source.surfaces),
        "exported_surface_count": len(projected_source.surfaces),
        "surface_export_complete": True,
        "proxy_volume_payload_hash": proxy_payload_hash,
        "requested_proxy_band_count": len(band_counts),
        "exported_proxy_band_count": len(band_counts),
        "exported_proxy_part_count": len(projected_source.volumes),
        "proxy_volume_count": len(projected_source.volumes),
        "proxy_band_part_counts": [
            band_counts[band] for band in sorted(band_counts)
        ],
        "legal_proxy_authority": "analysis_only_gfa_parking_containment",
        "legal_floor_loft_or_prism_replay_allowed": False,
        "post_book_authored_program_hash": program_hash,
        "post_book_authored_geometry_hash": compilation_geometry_hash,
        "final_projected_surface_hash": final_geometry_hash,
        "final_projected_surface_payload_hash": surface_payload_hash,
        "authored_legal_projection_certificate": deepcopy(certificate),
    })
    capacity_resolution = resolve_capacity_band_evidence(
        capacity_projection,
        capacity_measurement=capacity_measurement,
    )
    capacity_alternative_id = str(
        capacity_projection.get("alternative_id")
        or capacity_resolution.get("resolved_capacity_alternative_id")
        or ""
    )
    achieved_capacity_band = str(
        capacity_resolution.get("resolved_capacity_alternative_id")
        or capacity_alternative_id
    )
    capacity_measurement_hash = semantic_capacity_measurement_hash(
        capacity_measurement,
        capacity_projection,
    )
    site_context_hash = semantic_site_context_hash(
        pnu=str(pnu),
        building_type=building_type,
        site=containment_host,
    )
    semantic_context = {
        "floor_capacity_plan_hash": str(floor_capacity_plan_hash),
        "legal_floor_field_hash": str(legal_floor_field_hash),
        "candidate_requested_floors": len(targets),
        "candidate_target_gfa_m2": round(requested_floor_area, 6),
        "pnu": str(pnu),
        "site_context_hash": site_context_hash,
        "capacity_alternative_id": capacity_alternative_id,
        "achieved_capacity_band": achieved_capacity_band,
        "capacity_measurement_hash": capacity_measurement_hash,
    }
    metadata.update({
        "geometry_program": authored_program.to_dict(),
        "authored_geometry_program": authored_program.to_dict(),
        "geometry_program_compilation": compilation_payload,
        "mass_execution_passport": deepcopy(
            compilation_payload.get("execution_passport") or {}
        ),
        "geometry_graph_notes": build_geometry_graph_notes(
            authored_program, authored_compilation
        ),
        "geometry_graph_snapshot": build_geometry_graph_snapshot(
            authored_program, authored_compilation
        ),
        "authored_legal_projection_certificate": deepcopy(certificate),
        "final_program_hash": program_hash,
        "final_geometry_hash": final_geometry_hash,
        "final_surface_payload_hash": surface_payload_hash,
        "final_proxy_volume_payload_hash": proxy_payload_hash,
        "floorwise_legal_projection": projection,
        "legal_field_affine_placement": deepcopy(projection),
        "capacity_projection_measurement": {
            "schema_version": "arr.maas.capacity_projection_measurement.v1",
            "authority": "diagnostic_only_task4_classification",
            "requested_floor_area_m2": round(requested_floor_area, 6),
            "achieved_floor_area_m2": round(achieved_floor_area, 6),
            "achieved_to_requested_ratio": round(
                achieved_floor_area / max(requested_floor_area, 1e-9), 8
            ),
            "requested_capacity_satisfied": bool(
                requested_floor_area > 0.0
                and achieved_floor_area + 1e-7
                >= requested_floor_area * 0.995
            ),
            "candidate_requested_floors": len(targets),
            "legal_floor_field_hash": str(legal_floor_field_hash),
        },
        "final_semantic_projection_context": semantic_context,
        "geometry_program_bridge_evidence": bridge,
    })
    staged_source = replace(projected_source, metadata=metadata)
    semantic_projection = build_program_semantic_carrier_evidence(
        authored_source,
        staged_source,
        program_id=building_type,
        final_program_hash=program_hash,
        final_geometry_hash=final_geometry_hash,
        floor_capacity_plan_hash=str(floor_capacity_plan_hash),
        pnu=str(pnu),
        site_context_hash=site_context_hash,
        capacity_alternative_id=capacity_alternative_id,
        achieved_capacity_band=achieved_capacity_band,
        capacity_measurement_hash=capacity_measurement_hash,
    )
    resolved_program_id = str(
        semantic_projection.get("program_id") or ""
    )
    required_relations = set(
        REQUIRED_RELATIONS.get(resolved_program_id, ())
    )
    scaffold_records = tuple(
        record
        for record in semantic_projection.get("source_role_scaffold") or ()
        if isinstance(record, dict)
    )
    carrier_records = tuple(
        record
        for record in semantic_projection.get("carriers") or ()
        if isinstance(record, dict)
        and float(record.get("measured_area_m2") or 0.0) > 0.0
    )
    scaffold_relations = {
        str(record.get("source_relation") or "")
        for record in scaffold_records
    }
    carrier_relations = {
        str(record.get("source_relation") or "")
        for record in carrier_records
    }
    role_evidence_complete = all(
        str(record.get("source_relation") or "")
        and str(record.get("semantic_role") or "")
        and str(record.get("source_component_id") or "")
        for record in (*scaffold_records, *carrier_records)
    )
    missing_scaffold_relations = sorted(
        required_relations - scaffold_relations
    )
    missing_carrier_relations = sorted(
        required_relations - carrier_relations
    )
    if (
        semantic_projection.get("hard_pass") is not True
        or missing_scaffold_relations
        or missing_carrier_relations
        or (required_relations and not role_evidence_complete)
    ):
        fail(
            "semantic_projection_authority_issuance_failed",
            failures=list(semantic_projection.get("failures") or ()),
            required_relations=sorted(required_relations),
            missing_scaffold_relations=missing_scaffold_relations,
            missing_carrier_relations=missing_carrier_relations,
            role_evidence_complete=role_evidence_complete,
        )
        return None
    metadata["program_semantic_carrier_evidence"] = semantic_projection
    metadata.pop("program_space_zones", None)
    metadata.pop("program_role_integration_evidence", None)
    bridge = deepcopy(metadata["geometry_program_bridge_evidence"])
    bridge["geometry_authority"] = "authored_projected_surface_payload"
    metadata["geometry_program_bridge_evidence"] = bridge
    metadata["geometry_authority"] = "authored_projected_surface_payload"
    return replace(projected_source, metadata=metadata)


class _MaterializationAttemptDiagnostics:
    def __init__(self) -> None:
        self.materialization_invocation_count = 0
        self.terminal_failure_reason_counts: Counter[str] = Counter()

    def record_invocation(
        self,
        *,
        materialized: Any | None,
        terminal_failures: Sequence[Mapping[str, Any]],
    ) -> None:
        self.materialization_invocation_count += 1
        if materialized is not None:
            return
        reason = "unclassified_terminal_materialization_failure"
        if terminal_failures:
            reason = str(terminal_failures[0].get("stage") or reason)
        self.terminal_failure_reason_counts[reason] += 1

    def metadata(
        self,
        legal_fit_deficits: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        terminal_reason_counts = dict(
            sorted(self.terminal_failure_reason_counts.items())
        )
        terminal_failure_count = sum(terminal_reason_counts.values())
        if terminal_failure_count > self.materialization_invocation_count:
            raise AssertionError(
                "terminal materialization failures exceed invocation count"
            )
        return {
            "legal_fit_failure_reason_counts": dict(sorted(Counter(
                reason
                for deficit in legal_fit_deficits
                for reason in deficit.get("typed_reasons") or ()
            ).items())),
            "legal_fit_failure_count_unit": "deficit_reason_event",
            "terminal_materialization_failure_reason_counts": (
                terminal_reason_counts
            ),
            "terminal_materialization_failure_count_unit": (
                "failed_materialization_invocation"
            ),
            "materialization_invocation_count": (
                self.materialization_invocation_count
            ),
            "terminal_materialization_failure_count": terminal_failure_count,
        }


def _ground_take_bounded_coverage_capacity(
    trusted_legal_floor_field: Any,
    capacity_alternative: Any,
) -> float:
    """The 건축면적 the fit may take: the law's ceiling, lowered by the choice.

    The band lowered the plate *targets* while the geometry stayed bounded by
    the full 건폐율 capacity, so the fit was free to grow back up to it and did.
    Measured on PNU 4115011300106840001: a dispersed_ground candidate asked for
    225.0 m2 and delivered 499.9 - exactly the legal cap - and the median
    delivered/asked across the archive was 1.162. A ground take that only moves
    the target is a suggestion; bounding the projection is what makes it a
    choice.

    Legal by construction: every band is a fraction of the certified capacity,
    so this can only lower the bound, never raise it. With no declared band the
    law's ceiling is returned unchanged.
    """

    capacity = float(
        (trusted_legal_floor_field or {}).get("bcr_footprint_capacity_m2")
        or 0.0
    )
    if capacity <= 1e-9:
        return capacity
    band = coverage_band_of_alternative(capacity_alternative)
    if band is None:
        return capacity
    return plan_area_for_band(capacity, band)


def _materialize_directed_geometry(
    source: Any,
    sequence: VerbSequence,
    *,
    containment_host: Polygon | None = None,
    upper_containment_host: Polygon | None = None,
    floor_containment_hosts: tuple[Polygon | None, ...] = (),
    minimum_host_plan_coverage: float = 0.0,
    capacity_composition_utilizations: tuple[float, float] | None = None,
    floor_capacity_plan_hash: str = "",
    target_floor_areas_m2: tuple[float, ...] = (),
    coverage_capacity_m2: float = 0.0,
    building_type: str = "",
    site_access_side: str = "closed",
    pnu: str = "",
    capacity_alternative_id: str = "",
    achieved_capacity_band: str = "",
    capacity_measurement_hash: str = "",
    site_context_hash: str = "",
    legal_floor_field_hash: str = "",
    legal_fit_failure_sink: list[dict[str, Any]] | None = None,
    terminal_failure_sink: list[dict[str, Any]] | None = None,
    lineage_parent_key: str = "",
    pre_book_parent_compiler_clean: bool = False,
    pre_book_parent_contained: bool = False,
) -> Any | None:
    terminal_failure_sink_start = (
        len(terminal_failure_sink)
        if terminal_failure_sink is not None
        else 0
    )
    terminal_failure_emitted = False

    def terminal_failure(stage: str, **evidence: Any) -> None:
        nonlocal terminal_failure_emitted
        if terminal_failure_sink is None or terminal_failure_emitted:
            return
        if len(terminal_failure_sink) > terminal_failure_sink_start:
            terminal_failure_emitted = True
            return
        bounded_evidence: dict[str, Any] = {}
        for key, value in evidence.items():
            if len(bounded_evidence) >= 8:
                break
            if isinstance(value, dict):
                bounded_evidence[str(key)] = deepcopy(
                    dict(tuple(value.items())[:24])
                )
            elif isinstance(value, (list, tuple)):
                bounded_evidence[str(key)] = deepcopy(list(value[:24]))
            elif isinstance(value, str):
                bounded_evidence[str(key)] = value[:160]
            elif isinstance(value, (bool, int, float)) or value is None:
                bounded_evidence[str(key)] = value
        if legal_floor_field_hash:
            bounded_evidence["legal_floor_field_hash"] = str(
                legal_floor_field_hash
            )[:160]
        terminal_failure_sink.append({
            "stage": stage,
            "evidence": bounded_evidence,
        })
        terminal_failure_emitted = True

    # Both legal fit routes read this as "bound present" or "no bound at all",
    # and a missing capacity took the second branch silently - a mass built with
    # no 건폐율 bound whatsoever, indistinguishable downstream from one that was
    # bounded and fit. A candidate whose floors come from a legal floor field
    # must be bounded by that field's coverage capacity; a trusted field always
    # carries one. Candidates fitted against the generation context instead
    # (no field hash) have no capacity to be bounded by, and are left alone.
    if str(legal_floor_field_hash or "") and coverage_capacity_m2 <= 1e-9:
        terminal_failure(
            "coverage_capacity",
            failure_reason="legal_floor_field_declares_no_coverage_capacity",
            legal_floor_field_hash=str(legal_floor_field_hash or ""),
            coverage_capacity_m2=float(coverage_capacity_m2),
        )
        return None
    directive = next((
        note.split("=", 1)[1]
        for note in sequence.notes
        if note.startswith("geometry_program_directive=")
    ), "")
    raw_payload = next((
        note.split("=", 1)[1]
        for note in sequence.notes
        if note.startswith("geometry_program_payload=")
    ), "")
    if not directive and not raw_payload:
        return source
    raw_fit_strength = next((
        note.split("=", 1)[1]
        for note in sequence.notes
        if note.startswith("geometry_program_legal_fit_strength=")
    ), "0")
    try:
        fit_strength = max(0.0, min(1.0, float(raw_fit_strength)))
    except (TypeError, ValueError):
        terminal_failure("outer_precondition", field="legal_fit_strength")
        return None
    if raw_payload:
        try:
            program = GeometryProgram.from_dict(json.loads(raw_payload))
        except (TypeError, ValueError, json.JSONDecodeError):
            terminal_failure("outer_precondition", field="geometry_payload")
            return None
    else:
        program = _geometry_program_registry().get(directive)
    if program is None:
        terminal_failure("outer_precondition", field="geometry_program")
        return None
    if capacity_composition_utilizations is not None:
        achieved_utilization, target_utilization = capacity_composition_utilizations
        program = apply_capacity_composition_to_geometry_program(
            program,
            achieved_utilization=achieved_utilization,
            target_utilization=target_utilization,
        )
    raw_edits = next((
        note.split("=", 1)[1]
        for note in sequence.notes
        if note.startswith("geometry_program_edits=")
    ), "[]")
    try:
        edit_records = json.loads(raw_edits)
    except (TypeError, ValueError, json.JSONDecodeError):
        terminal_failure("outer_precondition", field="geometry_edits")
        return None
    if edit_records:
        safe_mutation = apply_geometry_edits_compiler_safe(program, edit_records)
        mutation = safe_mutation.mutation
        if mutation.status != "revised" or mutation.program is None:
            terminal_failure(
                "book_projection",
                **_book_projection_terminal_evidence(
                    "geometry_edit_binding_failed",
                    mutation_status=mutation.status,
                ),
            )
            return None
        program = mutation.program
    # BOOK p.3 scope and ordered operations must mutate the same recursive
    # manifold later rendered and gated. The old SourceMass projection remains
    # as program/legal evidence, but it is no longer the geometry authority.
    pre_book_program = program
    pre_book_compilation = compile_geometry_program(pre_book_program)
    pre_book_lineage_parent_proof: dict[str, Any] = {}
    if (
        lineage_parent_key
        and pre_book_parent_compiler_clean
        and pre_book_parent_contained
        and pre_book_compilation.status == "compiled"
        and not compilation_gate(
            pre_book_compilation,
            GeometryGatePolicy(maximum_components=1),
        )
    ):
        pre_book_lineage_parent_proof = {
            "schema_version": "arr.maas.pre_book_lineage_parent_proof.v1",
            "parent_key": str(lineage_parent_key),
            "program_hash": pre_book_program.program_hash(),
            "geometry_hash": str(pre_book_compilation.geometry_hash or ""),
            "compiler_clean": True,
            "contained": True,
        }
    try:
        book_geometry_program = _body_program_for_book_projection(
            program,
            sequence,
        )
    except (TypeError, ValueError) as exc:
        typed_evidence = getattr(exc, "evidence", None)
        if isinstance(typed_evidence, dict):
            terminal_failure(
                "book_projection",
                **_book_projection_terminal_evidence(
                    str(
                        typed_evidence.get("failure_reason")
                        or typed_evidence.get("book_projection_failure")
                        or "book_projection_application_failed"
                    ),
                    **typed_evidence,
                ),
            )
        else:
            terminal_failure(
                "book_projection",
                **_book_projection_terminal_evidence(
                    "book_projection_application_failed",
                    code="book_projection_application_failed",
                    failure_type=type(exc).__name__,
                    failure_detail=str(exc),
                    pre_program_hash=pre_book_program.program_hash(),
                ),
            )
        return None
    try:
        if book_projection_calls(sequence):
            program = _bind_book_program_source_role(
                book_geometry_program,
                source,
                program_id=building_type,
            )
        else:
            program = book_geometry_program
        # At MASS, program relations are certified semantic carriers over the
        # legal floor bands. They must not silently replace the authored
        # BaseVolume→BOOK body with a near-complete program template before
        # plan design. The visible authority therefore remains the BOOK AST.
    except (TypeError, ValueError) as exc:
        terminal_failure(
            "book_projection",
            **_book_projection_terminal_evidence(
                "source_role_scaffold_binding_failed",
                code="source_role_scaffold_binding_failed",
                stage_detail="role_scaffold",
                failure_type=type(exc).__name__,
                failure_detail=str(exc),
                pre_program_hash=pre_book_program.program_hash(),
                post_book_program_hash=book_geometry_program.program_hash(),
            ),
        )
        return None
    if program is None:
        terminal_failure(
            "book_projection",
            **_book_projection_terminal_evidence(
                "projected_program_missing",
                stage_detail="book_program",
                pre_program_hash=pre_book_program.program_hash(),
            ),
        )
        return None
    legal_sections = tuple(floor_containment_hosts)
    if (
        not isinstance(containment_host, Polygon)
        or not legal_sections
        or len(legal_sections) != len(target_floor_areas_m2)
        or not floor_capacity_plan_hash.strip()
        or any(
            not isinstance(section, Polygon)
            or section.is_empty
            or not section.is_valid
            or float(section.area) <= 1e-9
            for section in legal_sections
        )
    ):
        terminal_failure(
            "outer_precondition",
            legal_section_count=len(legal_sections),
            target_floor_count=len(target_floor_areas_m2),
        )
        return None
    authored_program = program
    authored_compilation = compile_geometry_program(authored_program)
    book_projection_failure = _required_book_projection_failure(
        sequence,
        pre_book_program=pre_book_program,
        pre_book_compilation=pre_book_compilation,
        post_book_program=authored_program,
        post_book_compilation=authored_compilation,
    )
    if book_projection_failure is not None:
        terminal_failure(
            "book_projection",
            **_book_projection_terminal_evidence(
                str(
                    book_projection_failure.get("book_projection_failure")
                    or "required_book_projection_validation_failed"
                ),
                **book_projection_failure,
            ),
        )
        return None
    authored_geometry_gate_failures = (
        compilation_gate(
            authored_compilation,
            GeometryGatePolicy(maximum_components=1),
        )
        if authored_compilation.status == "compiled"
        else ()
    )
    if (
        authored_compilation.status != "compiled"
        or authored_geometry_gate_failures
    ):
        terminal_failure(
            "book_projection",
            **_book_projection_terminal_evidence(
                "projected_compile_or_geometry_gate_failed",
                compilation_status=authored_compilation.status,
                geometry_gate_failures=list(
                    authored_geometry_gate_failures or ()
                ),
                post_book_program_hash=authored_program.program_hash(),
            ),
        )
        return None
    if not source.volumes:
        terminal_failure("outer_precondition", source_volume_count=0)
        return None
    primary_volume_role = max(
        source.volumes,
        key=lambda volume: (
            float(volume.footprint.area)
            * (
                float(volume.top_fraction)
                - float(volume.bottom_fraction)
            )
        ),
    ).role
    target_areas = tuple(float(value) for value in target_floor_areas_m2)
    legal_field_selection = select_legal_field_affine_projection(
        authored_program,
        legal_sections=legal_sections,
        target_floor_areas_m2=target_floor_areas_m2,
        floor_capacity_plan_hash=floor_capacity_plan_hash,
        aggregate_target_area_m2=sum(target_areas),
        # 건축면적 - the building's horizontal projection - is what the coverage
        # limit bounds (건축법 시행령 제119조 제1항 제2호). Without it here the
        # pose search aims only at the sunlight envelope and overshoots: 23 of
        # 28 archived masses on PNU 4115011300106840001 covered more than the
        # 499.938 m2 limit, up to 1.94x, each costing a full legal
        # materialization before `bcr_limit_exceeded` discarded it downstream.
        coverage_capacity_m2=(
            coverage_capacity_m2 if coverage_capacity_m2 > 1e-9 else None
        ),
        maximum_exact_candidates=4,
        # This selector is an acceptance path, not a loose morphology probe.
        # Returning a 35%-of-target affine body suppresses the capacity-aware
        # repair below and guarantees a later FAR rejection.  Require the
        # selected unchanged body to satisfy the complete requested budget;
        # infeasible authored bodies continue into the explicit repair path.
        minimum_aggregate_target_ratio=0.995,
    )
    final_projection_book_program = authored_program
    if legal_field_selection is None:
        legal_fit_deficit = build_legal_fit_deficit(
            authored_program_hash=authored_program.program_hash(),
            legal_sections=legal_sections,
            target_floor_areas_m2=target_areas,
            floor_capacity_plan_hash=floor_capacity_plan_hash,
        ).to_dict()
        if legal_fit_failure_sink is not None:
            legal_fit_failure_sink.append(legal_fit_deficit)
        logger.info(
            "Principal-frame legal fit requires typed repair: %s",
            legal_fit_deficit,
        )
        candidate_floor_context = (
            source.metadata.get("candidate_floor_context")
            if isinstance(
                source.metadata.get("candidate_floor_context"),
                dict,
            )
            else {}
        )
        try:
            candidate_height_m = float(
                candidate_floor_context.get("height_m")
            )
            candidate_floor_count = int(
                candidate_floor_context.get("floors")
            )
        except (TypeError, ValueError):
            terminal_failure("outer_precondition", field="candidate_floor_context")
            return None
        if (
            not isfinite(candidate_height_m)
            or candidate_height_m <= 0.0
            or candidate_floor_count != len(legal_sections)
        ):
            terminal_failure("outer_precondition", field="candidate_floor_context")
            return None
        authored_source = compile_normalized_geometry_program_to_source_mass(
            authored_program,
            name=f"{source.name}__authored_{authored_program.name}",
            volume_role=primary_volume_role,
            max_volume_bands=max(3, len(legal_sections)),
        )
        if authored_source is None:
            terminal_failure(
                "book_projection",
                **_book_projection_terminal_evidence(
                    "authored_source_construction_failed",
                    stage_detail="authored_source",
                    authored_program_hash=authored_program.program_hash(),
                    compilation_geometry_hash=str(
                        authored_compilation.geometry_hash or ""
                    ),
                ),
            )
            return None
        authored_source = replace(
            authored_source,
            metadata={
                **authored_source.metadata,
                "candidate_floor_context": deepcopy(candidate_floor_context),
            },
        )
        materialized = materialize_floorwise_legal_source(
            authored_source,
            legal_sections=legal_sections,
            target_plan_coverage=minimum_host_plan_coverage,
            coverage_capacity_m2=(
                coverage_capacity_m2 if coverage_capacity_m2 > 1e-9 else None
            ),
            site_access_side=site_access_side,
            floor_capacity_plan_hash=floor_capacity_plan_hash,
            legal_floor_field_hash=legal_floor_field_hash,
            target_floor_areas_m2=target_areas,
            # `authored_source` is rebuilt from the AST, which carries one body
            # and one role by contract, so its own volumes cannot describe the
            # program's composition. The seed still can - it is where the
            # program template's components were materialized - so the layout
            # is read there and carried as proportions, which survive the
            # normalized/site frame change the AST round trip imposes.
            component_layout=normalized_component_layout(source),
            terminal_failure_sink=terminal_failure_sink,
        )
        if materialized is None:
            terminal_failure("floor_affine_fit", floor_count=len(legal_sections))
            return None
        authored_projection_identity = (
            _authored_projection_identity_evidence(
                authored_source,
                materialized,
                base_primitive_geometry_hash=str(
                    pre_book_program.metadata.get("base_primitive_geometry_hash") or ""
                ),
                authored_ast_geometry_hash=str(authored_compilation.geometry_hash or ""),
                book_projection_required=bool(book_projection_calls(sequence)),
                pre_book_program_hash=pre_book_program.program_hash(),
                post_book_program_hash=authored_program.program_hash(),
                pre_book_geometry_hash=str(pre_book_compilation.geometry_hash or ""),
                post_book_geometry_hash=str(authored_compilation.geometry_hash or ""),
            )
        )
        if not authored_projection_identity["hard_pass"]:
            logger.info(
                "Rejecting authored legal projection identity collapse: %s",
                authored_projection_identity,
            )
            terminal_failure(
                _authored_projection_terminal_stage(authored_projection_identity),
                failure_reason=str(
                    (authored_projection_identity.get("failure_reasons") or ["authored_identity_collapse"])[0]
                ),
                identity_evidence=authored_projection_identity,
            )
            return None
        # The projected authored surface payload is the sole final visual
        # authority. Legal floor volumes remain analysis proxies and must not
        # be serialized into a replacement prism/loft execution program.
        final_compilation = authored_compilation
        final_program_hash = authored_program.program_hash()
        final_geometry_hash = final_floorwise_visual_geometry_hash(
            materialized
        )
        band_areas: dict[tuple[float, float], float] = {}
        for volume in materialized.volumes:
            band = (
                float(volume.bottom_fraction),
                float(volume.top_fraction),
            )
            band_areas[band] = (
                band_areas.get(band, 0.0)
                + float(volume.footprint.area)
            )
        proxy_floor_areas = tuple(
            band_areas[band]
            for band in sorted(band_areas)
        )
        certified_floor_areas = certified_actual_section_areas(
            materialized.metadata.get("floorwise_visual_projection") or {}
        )
        achieved_floor_areas = (
            certified_floor_areas
            if certified_floor_areas
            else proxy_floor_areas
        )
        projection_evidence = deepcopy(
            materialized.metadata.get("floorwise_legal_matrix_stack")
            or {}
        )
        projection_evidence.update({
            "projection_mode": (
                "floorwise_matrix_field_authored_mesh_preserved"
            ),
            "hard_pass": True,
            "final_program_hash": final_program_hash,
            "final_geometry_hash": final_geometry_hash,
        })
        fallback_metadata = deepcopy(materialized.metadata)
        fallback_metadata["authored_projection_identity"] = deepcopy(
            authored_projection_identity
        )
        final_surface_payload_hash = source_surface_payload_hash(
            tuple(materialized.surfaces)
        )
        final_proxy_volume_payload_hash = source_volume_payload_hash(
            tuple(materialized.volumes)
        )
        proxy_band_counts = Counter(
            (
                float(volume.bottom_fraction),
                float(volume.top_fraction),
            )
            for volume in materialized.volumes
        )
        proxy_band_part_counts = tuple(
            proxy_band_counts[band]
            for band in sorted(proxy_band_counts)
        )
        fallback_metadata["final_surface_payload_hash"] = (
            final_surface_payload_hash
        )
        fallback_metadata["final_proxy_volume_payload_hash"] = (
            final_proxy_volume_payload_hash
        )
        authored_legal_projection_certificate = {
            "schema_version": (
                "arr.maas.authored_legal_projection_certificate.v1"
            ),
            "status": "verified",
            "hard_pass": True,
            "input_authored_program_hash": authored_program.program_hash(),
            "input_authored_geometry_hash": str(
                authored_compilation.geometry_hash or ""
            ),
            "legal_floor_field_hash": str(legal_floor_field_hash or ""),
            "projected_surface_hash": final_geometry_hash,
            "projected_surface_payload_hash": final_surface_payload_hash,
            "achieved_floor_areas_m2": [
                round(float(value), 8)
                for value in achieved_floor_areas
            ],
            "legal_proxy_role": "analysis_only_gfa_parking_containment",
        }
        fallback_metadata["authored_legal_projection_certificate"] = (
            deepcopy(authored_legal_projection_certificate)
        )
        projection_evidence["authored_legal_projection_certificate"] = (
            deepcopy(authored_legal_projection_certificate)
        )
        final_compilation_payload = authored_compilation.to_dict(
            include_mesh=False
        )
        fallback_metadata["geometry_program"] = authored_program.to_dict()
        fallback_metadata["geometry_program_compilation"] = (
            final_compilation_payload
        )
        fallback_metadata["mass_execution_passport"] = deepcopy(
            final_compilation_payload.get("execution_passport") or {}
        )
        fallback_metadata["geometry_graph_notes"] = (
            build_geometry_graph_notes(
                authored_program,
                authored_compilation,
            )
        )
        fallback_metadata["geometry_graph_snapshot"] = (
            build_geometry_graph_snapshot(
                authored_program,
                authored_compilation,
            )
        )
        fallback_bridge = deepcopy(
            fallback_metadata.get("geometry_program_bridge_evidence")
            or {}
        )
        fallback_bridge.update({
            "program_hash": final_program_hash,
            "geometry_hash": final_geometry_hash,
            "bridge_identity_writer": "typed_repair",
            "surface_payload_hash": final_surface_payload_hash,
            "raw_mesh_triangle_count": len(materialized.surfaces),
            "exported_surface_count": len(materialized.surfaces),
            "surface_export_complete": bool(materialized.surfaces),
            "proxy_volume_payload_hash": final_proxy_volume_payload_hash,
            "requested_proxy_band_count": len(proxy_band_counts),
            "exported_proxy_band_count": len(proxy_band_counts),
            "exported_proxy_part_count": len(materialized.volumes),
            "proxy_volume_count": len(materialized.volumes),
            "proxy_band_part_counts": list(proxy_band_part_counts),
            "geometry_authority": "authored_projected_surface_payload",
            "legal_proxy_authority": "analysis_only_gfa_parking_containment",
            "legal_floor_loft_or_prism_replay_allowed": False,
            "upstream_authored_program_hash": (
                authored_program.program_hash()
            ),
            "upstream_authored_geometry_hash": (
                authored_compilation.geometry_hash
            ),
            "authored_legal_projection_certificate": deepcopy(
                authored_legal_projection_certificate
            ),
        })
        fallback_metadata["geometry_program_bridge_evidence"] = (
            fallback_bridge
        )
        materialized = replace(
            materialized,
            metadata=fallback_metadata,
        )
    else:
        projected = legal_field_selection.projection
        if projected.certificate.get("hard_pass") is not True:
            terminal_failure(
                "book_projection",
                **_book_projection_terminal_evidence(
                    "legal_projection_selector_failed",
                    stage_detail="legal_projection",
                    certificate_causes=list(
                        projected.certificate.get("causes")
                        or projected.certificate.get("failure_reasons")
                        or ()
                    ),
                    certificate_status=projected.certificate.get("status"),
                ),
            )
            return None
        materialized = compile_site_bound_geometry_program_to_source_mass(
            projected.program,
            containment_host,
            name=f"{source.name}__geometry_{projected.program.name}",
            volume_role=primary_volume_role,
            floor_count=len(legal_sections),
        )
        if materialized is None:
            terminal_failure(
                "book_projection",
                **_book_projection_terminal_evidence(
                    "projected_program_materialization_failed",
                    stage_detail="site_bound_compile",
                    projected_program_hash=projected.program.program_hash(),
                    final_geometry_hash=str(
                        projected.certificate.get("final_geometry_hash") or ""
                    ),
                ),
            )
            return None
        final_projection_book_program = authored_program
        final_program_hash = authored_program.program_hash()
        # `projected.certificate` carries the compiler's own `_mesh_hash` of
        # the finalized program, taken in the compiler frame. What is delivered
        # and later certified is the SourceMass just compiled above, whose
        # identity is the surfaces offset by the footprint centroid. Two
        # different identities of two different things, so copying the compiler
        # hash here made the final visual authority certificate hold a digest
        # that could never match its own surfaces. The typed repair route
        # already publishes the delivered identity; do the same here.
        final_geometry_hash = final_floorwise_visual_geometry_hash(materialized)
        achieved_floor_areas = tuple(
            float(value)
            for value in (
                projected.certificate.get("achieved_floor_areas_m2")
                or ()
            )
        )
        projection_evidence = deepcopy(legal_field_selection.evidence)

    # Three identities remain distinct through every legal-fit route:
    # initial LLM-authored pre-BOOK AST/mesh, post-BOOK authored AST/mesh,
    # and the final post-legal-projection visual surface. The legal projection
    # may supply the final surface, but it never replaces the authored AST.
    final_program_hash = authored_program.program_hash()
    final_projection_book_program = authored_program
    final_surface_payload_hash = source_surface_payload_hash(
        tuple(materialized.surfaces)
    )
    final_proxy_volume_payload_hash = source_volume_payload_hash(
        tuple(materialized.volumes)
    )
    proxy_band_counts = Counter(
        (
            float(volume.bottom_fraction),
            float(volume.top_fraction),
        )
        for volume in materialized.volumes
    )
    proxy_band_part_counts = tuple(
        proxy_band_counts[band]
        for band in sorted(proxy_band_counts)
    )
    # Both the unchanged-affine path and the explicit repair path terminate
    # in the same certified projection contract.  Bind that contract here so
    # downstream law/parking gates do not depend on which materializer won.
    projection_evidence.update({
        "hard_pass": True,
        "final_program_hash": final_program_hash,
        "final_geometry_hash": final_geometry_hash,
    })
    authored_legal_projection_certificate = {
        "schema_version": (
            "arr.maas.authored_legal_projection_certificate.v1"
        ),
        "status": "verified",
        "hard_pass": True,
        "input_authored_program_hash": authored_program.program_hash(),
        "input_authored_geometry_hash": str(
            authored_compilation.geometry_hash or ""
        ),
        "legal_floor_field_hash": str(legal_floor_field_hash or ""),
        "projected_surface_hash": final_geometry_hash,
        "projected_surface_payload_hash": final_surface_payload_hash,
        "achieved_floor_areas_m2": [
            round(float(value), 8)
            for value in achieved_floor_areas
        ],
        "legal_proxy_role": "analysis_only_gfa_parking_containment",
    }
    authoritative_metadata = deepcopy(materialized.metadata)
    authoritative_compilation_payload = authored_compilation.to_dict(
        include_mesh=False
    )
    authoritative_metadata.update({
        "geometry_program": authored_program.to_dict(),
        "authored_geometry_program": authored_program.to_dict(),
        "geometry_program_compilation": authoritative_compilation_payload,
        "mass_execution_passport": deepcopy(
            authoritative_compilation_payload.get("execution_passport") or {}
        ),
        "geometry_graph_notes": build_geometry_graph_notes(
            authored_program,
            authored_compilation,
        ),
        "geometry_graph_snapshot": build_geometry_graph_snapshot(
            authored_program,
            authored_compilation,
        ),
        "authored_legal_projection_certificate": deepcopy(
            authored_legal_projection_certificate
        ),
        "final_surface_payload_hash": final_surface_payload_hash,
        "final_proxy_volume_payload_hash": (
            final_proxy_volume_payload_hash
        ),
    })
    authoritative_bridge = deepcopy(
        authoritative_metadata.get("geometry_program_bridge_evidence") or {}
    )
    authoritative_bridge.pop("upstream_authored_program_hash", None)
    authoritative_bridge.pop("upstream_authored_geometry_hash", None)
    authoritative_bridge.update({
        "program_hash": final_program_hash,
        "geometry_hash": final_geometry_hash,
        "bridge_identity_writer": "legal_field_affine",
        "surface_payload_hash": final_surface_payload_hash,
        "proxy_volume_payload_hash": final_proxy_volume_payload_hash,
        "requested_proxy_band_count": len(proxy_band_counts),
        "exported_proxy_band_count": len(proxy_band_counts),
        "exported_proxy_part_count": len(materialized.volumes),
        "proxy_volume_count": len(materialized.volumes),
        "proxy_band_part_counts": list(proxy_band_part_counts),
        "geometry_authority": "authored_projected_surface_payload",
        "legal_proxy_authority": "analysis_only_gfa_parking_containment",
        "legal_floor_loft_or_prism_replay_allowed": False,
        "initial_authored_pre_book_program_hash": (
            pre_book_program.program_hash()
        ),
        "initial_authored_pre_book_geometry_hash": str(
            pre_book_compilation.geometry_hash or ""
        ),
        "post_book_authored_program_hash": authored_program.program_hash(),
        "post_book_authored_geometry_hash": str(
            authored_compilation.geometry_hash or ""
        ),
        "final_projected_surface_hash": final_geometry_hash,
        "final_projected_surface_payload_hash": final_surface_payload_hash,
        "authored_legal_projection_certificate": deepcopy(
            authored_legal_projection_certificate
        ),
    })
    if pre_book_program.metadata.get("llm_geometry_author_active") is True:
        authoritative_bridge.update({
            "initial_llm_authored_pre_book_program_hash": (
                pre_book_program.program_hash()
            ),
            "initial_llm_authored_pre_book_geometry_hash": str(
                pre_book_compilation.geometry_hash or ""
            ),
        })
    authoritative_metadata["geometry_program_bridge_evidence"] = (
        authoritative_bridge
    )
    materialized = replace(materialized, metadata=authoritative_metadata)
    projection_evidence["authored_legal_projection_certificate"] = deepcopy(
        authored_legal_projection_certificate
    )
    bridge = (
        materialized.metadata.get("geometry_program_bridge_evidence")
        if isinstance(
            materialized.metadata.get("geometry_program_bridge_evidence"),
            dict,
        )
        else {}
    )
    compilation = (
        materialized.metadata.get("geometry_program_compilation")
        if isinstance(
            materialized.metadata.get("geometry_program_compilation"),
            dict,
        )
        else {}
    )
    # Every other field on this bridge is recomputed from `materialized`, so
    # the geometry hash must be too. When it was copied from an upstream
    # certificate instead, nothing here noticed and the candidate died twenty
    # minutes later inside the final visual authority certificate, which is the
    # first place that recomputes the identity from the delivered surfaces.
    try:
        delivered_geometry_hash = final_floorwise_visual_geometry_hash(
            materialized
        )
    except ValueError:
        delivered_geometry_hash = ""
    if (
        not final_program_hash
        or not final_geometry_hash
        or str(bridge.get("program_hash") or "") != final_program_hash
        or str(bridge.get("geometry_hash") or "") != final_geometry_hash
        or delivered_geometry_hash != final_geometry_hash
        or (
            str(bridge.get("geometry_authority") or "")
            == "authored_projected_surface_payload"
            and (
                not isinstance(
                    bridge.get("authored_legal_projection_certificate"),
                    dict,
                )
                or bridge["authored_legal_projection_certificate"].get(
                    "hard_pass"
                ) is not True
                or str(compilation.get("geometry_hash") or "")
                != str(bridge.get("post_book_authored_geometry_hash") or "")
                or str(
                    bridge["authored_legal_projection_certificate"].get(
                        "input_authored_geometry_hash"
                    ) or ""
                ) != str(bridge.get("post_book_authored_geometry_hash") or "")
                or str(
                    bridge["authored_legal_projection_certificate"].get(
                        "input_authored_program_hash"
                    ) or ""
                ) != str(bridge.get("post_book_authored_program_hash") or "")
                or str(
                    bridge["authored_legal_projection_certificate"].get(
                        "legal_floor_field_hash"
                    ) or ""
                ) != str(legal_floor_field_hash or "")
                or str(
                    bridge["authored_legal_projection_certificate"].get(
                        "projected_surface_hash"
                    ) or ""
                ) != final_geometry_hash
            )
        )
        or (
            str(bridge.get("geometry_authority") or "")
            != "authored_projected_surface_payload"
            and str(compilation.get("geometry_hash") or "")
            != final_geometry_hash
        )
    ):
        logger.info(
            "Rejecting authored projection identity binding mismatch: %s",
            {
                "final_program_hash": final_program_hash,
                "final_geometry_hash": final_geometry_hash,
                "bridge_program_hash": str(
                    bridge.get("program_hash") or ""
                ),
                "bridge_geometry_hash": str(
                    bridge.get("geometry_hash") or ""
                ),
                "compilation_geometry_hash": str(
                    compilation.get("geometry_hash") or ""
                ),
                "delivered_geometry_hash": delivered_geometry_hash,
            },
        )
        terminal_failure("final_identity_binding")
        return None
    requested_floor_area = sum(float(value) for value in target_floor_areas_m2)
    achieved_floor_area = sum(achieved_floor_areas)
    requested_capacity_satisfied = bool(
        requested_floor_area > 0.0
        and achieved_floor_area + 1e-7 >= requested_floor_area * 0.995
    )
    source_seed = next((
        note.split("=", 1)[1]
        for note in sequence.notes
        if note.startswith("geometry_program_source_seed=")
    ), "")
    declared_author_source = next((
        note.split("=", 1)[1]
        for note in sequence.notes
        if note.startswith("geometry_program_source=")
    ), "")
    metadata = {
        **deepcopy(source.metadata),
        **deepcopy(materialized.metadata),
    }
    bridge = deepcopy(metadata.get("geometry_program_bridge_evidence") or {})
    bridge["source_seed"] = source_seed
    bridge["llm_geometry_author_active"] = bool(
        pre_book_program.metadata.get("llm_geometry_author_active")
    )
    for field in (
        "author_model",
        "author_response_id",
        "llm_geometry_author_model",
        "llm_geometry_author_response_id",
        "initial_llm_authored_pre_book_program_hash",
        "initial_llm_authored_pre_book_geometry_hash",
    ):
        bridge.pop(field, None)
    if bridge["llm_geometry_author_active"]:
        bridge["author_provider"] = str(
            pre_book_program.metadata.get("author_provider")
            or "openai_llm_geometry_author"
        )
        bridge["author_source"] = str(
            pre_book_program.metadata.get("author_source")
            or bridge["author_provider"]
        )
        author_model = str(
            pre_book_program.metadata.get("author_model")
            or pre_book_program.metadata.get("llm_geometry_author_model")
            or ""
        )
        author_response_id = str(
            pre_book_program.metadata.get("author_response_id")
            or pre_book_program.metadata.get(
                "llm_geometry_author_response_id"
            )
            or ""
        )
        if author_model:
            bridge["author_model"] = author_model
            bridge["llm_geometry_author_model"] = author_model
        if author_response_id:
            bridge["author_response_id"] = author_response_id
            bridge["llm_geometry_author_response_id"] = author_response_id
        if pre_book_lineage_parent_proof:
            bridge["pre_book_lineage_parent_proof"] = deepcopy(
                pre_book_lineage_parent_proof
            )
        else:
            bridge.pop("pre_book_lineage_parent_proof", None)
    else:
        authored_provider = str(
            pre_book_program.metadata.get("author_provider") or ""
        )
        if authored_provider == "openai_llm_geometry_author":
            authored_provider = ""
        procedural_source = str(declared_author_source or "")
        if procedural_source == "openai_llm_geometry_author":
            procedural_source = ""
        bridge["author_provider"] = (
            authored_provider
            or procedural_source
            or "bounded_procedural_geometry_agent"
        )
        bridge["author_source"] = (
            procedural_source or bridge["author_provider"]
        )
        bridge.pop("pre_book_lineage_parent_proof", None)
    bridge.setdefault(
        "geometry_authority",
        "authored_compiled_surface_payload",
    )
    bridge["legal_proxy_authority"] = (
        "analysis_only_gfa_parking_containment"
    )
    bridge["legal_floor_loft_or_prism_replay_allowed"] = False
    bridge["initial_authored_pre_book_program_hash"] = (
        pre_book_program.program_hash()
    )
    bridge["initial_authored_pre_book_geometry_hash"] = str(
        pre_book_compilation.geometry_hash or ""
    )
    if bridge["llm_geometry_author_active"]:
        bridge["initial_llm_authored_pre_book_program_hash"] = (
            pre_book_program.program_hash()
        )
        bridge["initial_llm_authored_pre_book_geometry_hash"] = str(
            pre_book_compilation.geometry_hash or ""
        )
    else:
        bridge.pop("initial_llm_authored_pre_book_program_hash", None)
        bridge.pop("initial_llm_authored_pre_book_geometry_hash", None)
    bridge["post_book_authored_program_hash"] = authored_program.program_hash()
    bridge["post_book_authored_geometry_hash"] = str(
        authored_compilation.geometry_hash or ""
    )
    bridge["final_projected_surface_hash"] = final_geometry_hash
    bridge["final_projected_surface_payload_hash"] = str(
        metadata.get("final_surface_payload_hash") or ""
    )
    metadata["geometry_program_bridge_evidence"] = bridge
    metadata["geometry_authority"] = bridge["geometry_authority"]
    metadata["final_program_hash"] = final_program_hash
    metadata["final_geometry_hash"] = final_geometry_hash
    metadata["legal_field_affine_placement"] = projection_evidence
    metadata["floorwise_legal_projection"] = deepcopy(
        projection_evidence
    )
    metadata["capacity_projection_measurement"] = {
        "schema_version": "arr.maas.capacity_projection_measurement.v1",
        "authority": "diagnostic_only_task4_classification",
        "requested_floor_area_m2": round(requested_floor_area, 6),
        "achieved_floor_area_m2": round(achieved_floor_area, 6),
        "achieved_to_requested_ratio": round(
            achieved_floor_area / max(requested_floor_area, 1e-9),
            8,
        ),
        "requested_capacity_satisfied": requested_capacity_satisfied,
        "candidate_requested_floors": len(legal_sections),
        "legal_floor_field_hash": str(legal_floor_field_hash or ""),
    }
    metadata["authored_geometry_program"] = authored_program.to_dict()
    metadata["authored_geometry_graph_snapshot"] = (
        build_geometry_graph_snapshot(
            authored_program,
            authored_compilation,
        )
    )
    metadata["authored_geometry_provenance"] = {
        "initial_authored_pre_book_program_hash": (
            pre_book_program.program_hash()
        ),
        "initial_authored_pre_book_geometry_hash": str(
            pre_book_compilation.geometry_hash or ""
        ),
        "post_book_authored_program_hash": authored_program.program_hash(),
        "post_book_authored_geometry_hash": str(
            authored_compilation.geometry_hash or ""
        ),
        "final_projected_surface_hash": final_geometry_hash,
        "final_projected_surface_payload_hash": str(
            metadata.get("final_surface_payload_hash") or ""
        ),
        "authority": "post_book_authored_ast",
        "final_visual_authority": "post_legal_projected_surface",
    }
    if bridge["llm_geometry_author_active"]:
        metadata["authored_geometry_provenance"].update({
            "initial_llm_authored_pre_book_program_hash": (
                pre_book_program.program_hash()
            ),
            "initial_llm_authored_pre_book_geometry_hash": str(
                pre_book_compilation.geometry_hash or ""
            ),
        })
    site_context_hash = str(site_context_hash or semantic_site_context_hash(
        pnu=pnu,
        building_type=building_type,
        site=containment_host,
    ))
    semantic_projection_context = {
        "floor_capacity_plan_hash": floor_capacity_plan_hash,
        "legal_floor_field_hash": str(legal_floor_field_hash or ""),
        "candidate_requested_floors": len(legal_sections),
        "candidate_target_gfa_m2": round(requested_floor_area, 6),
        "pnu": str(pnu or ""),
        "site_context_hash": site_context_hash,
        "capacity_alternative_id": str(capacity_alternative_id or ""),
        "achieved_capacity_band": str(
            achieved_capacity_band or capacity_alternative_id or ""
        ),
        "capacity_measurement_hash": str(
            capacity_measurement_hash or "pending_capacity_measurement"
        ),
    }
    semantic_projection = build_program_semantic_carrier_evidence(
        source,
        materialized,
        program_id=building_type,
        final_program_hash=final_program_hash,
        final_geometry_hash=final_geometry_hash,
        floor_capacity_plan_hash=str(
            semantic_projection_context["floor_capacity_plan_hash"]
        ),
        pnu=str(semantic_projection_context["pnu"]),
        site_context_hash=str(
            semantic_projection_context["site_context_hash"]
        ),
        capacity_alternative_id=str(
            semantic_projection_context["capacity_alternative_id"]
        ),
        achieved_capacity_band=str(
            semantic_projection_context["achieved_capacity_band"]
        ),
        capacity_measurement_hash=str(
            semantic_projection_context["capacity_measurement_hash"]
        ),
    )
    if semantic_projection.get("hard_pass") is not True:
        terminal_failure(
            "semantic_carrier",
            failures=list(semantic_projection.get("failures") or ()),
            program_id=str(semantic_projection.get("program_id") or ""),
            source_role_count=len(
                semantic_projection.get("source_role_scaffold") or ()
            ),
            carrier_count=len(semantic_projection.get("carriers") or ()),
        )
        return None
    metadata["final_semantic_projection_context"] = semantic_projection_context
    metadata["program_semantic_carrier_evidence"] = semantic_projection
    metadata.pop("floorwise_legal_sibling_evidence", None)
    if legal_field_selection is not None:
        metadata.pop("floorwise_legal_matrix_stack", None)
        metadata.pop("floorwise_visual_projection", None)
    metadata.pop("program_space_zones", None)
    metadata.pop("program_role_integration_evidence", None)
    metadata["program_book_projection_evidence"] = _program_projection_evidence(
        final_projection_book_program,
        bridge,
    )
    return replace(materialized, metadata=metadata)






def _program_pool_single_phase(
    site: Polygon,
    building_type: str,
    height: float,
    floors: int,
    *,
    generation_context: LegalGenerationContext | None = None,
    parent_variant_indices: tuple[int, ...] = (0,),
    typed_graph_mutations: list[dict[str, Any]] | None = None,
    geometry_program_mutations: list[dict[str, Any]] | None = None,
    synthesis_requests: list[dict[str, Any]] | None = None,
    outcome_graph: GeometryOutcomeGraph | None = None,
    recursive_only: bool = False,
    target_count: int = 0,
    exact_compile_limit: int | None = None,
    program_dimensional_context: dict[str, Any] | None = None,
    site_boundary_source: str = "",
    site_access_context: dict[str, Any] | None = None,
    site_access_geometry: dict[str, Any] | None = None,
    live_geometry_vlm_revision: bool = False,
    base_capacity_contract: dict[str, Any] | None = None,
    trusted_legal_floor_field: dict[str, Any] | None = None,
    trusted_legal_floor_field_hash: str = "",
    trusted_clear_span_floor_plan: dict[str, Any] | None = None,
    capacity_site: Polygon | None = None,
    pnu: str = "",
    stop_after_shared_floor_hard_passes: int | None = None,
    diagnostic_scope_labels: tuple[str, ...] = (),
    diagnostic_book_probe_count: int | None = None,
    diagnostic_evaluation_cap: int | None = None,
    diagnostic_candidate_cap: int | None = None,
    progress_callback: Callable[[dict[str, int]], None] | None = None,
    diagnostic_evaluation_trace_callback: (
        Callable[[dict[str, Any]], None] | None
    ) = None,
    _directed_seeds_override: tuple[VerbSequence, ...] | None = None,
    _parent_seeds_override: tuple[VerbSequence, ...] | None = None,
    _generation_phase: str = "all",
    _reviewed_base_registry: dict[str, str | None] | None = None,
    _reviewed_base_audits: dict[str, dict[str, Any]] | None = None,
    _reviewed_base_lineages: tuple[dict[str, Any], ...] | None = None,
    _replenishment_causal_request_hash: str = "",
    _replenishment_effective_context_hash: str = "",
    _replenishment_attempted_work_keys: frozenset[str] = frozenset(),
) -> tuple[list[_Candidate], dict[str, Any]]:
    # Local import avoids expanding the ordinary candidate-analysis import
    # surface while allowing online quality-diversity compaction.
    from backend.app.modules.design.generation.maas.book_language.quality_diversity_archive import StreamingMapElitesArchive

    legal_fit_deficits: list[dict[str, Any]] = []
    terminal_materialization_failures: list[dict[str, Any]] = []
    clean_mass_rejections: list[dict[str, Any]] = []
    stage_outcomes: list[dict[str, Any]] = []
    capacity_authoring_deficits: list[dict[str, Any]] = []
    materialization_diagnostics = _MaterializationAttemptDiagnostics()
    legal_mass_archive = LegalMassArchive()
    descendant_parent_authorization = {
        "schema_version": "arr.maas.descendant_parent_authorization.v1",
        "input_count": 0,
        "authorized_count": 0,
        "filtered_count": 0,
        "filtered_by_reason": {},
    }
    replenishment_work_evidence: dict[str, Any] = {}

    if (
        (base_capacity_contract or {}).get("legal_floor_field")
        or (base_capacity_contract or {}).get("legal_floor_field_hash")
    ):
        trusted_field = (
            trusted_legal_floor_field
            if isinstance(trusted_legal_floor_field, dict)
            else None
        )
        trusted_hash = str(trusted_legal_floor_field_hash or "")
        base_field = (base_capacity_contract or {}).get(
            "legal_floor_field"
        )
        if (
            trusted_field is None
            or not trusted_hash
            or not validate_legal_floor_field(trusted_field)
            or str(
                trusted_field.get("legal_floor_field_hash") or ""
            )
            != trusted_hash
            or not validate_legal_floor_field(base_field)
            or str(
                (base_capacity_contract or {}).get(
                    "legal_floor_field_hash"
                )
                or ""
            )
            != trusted_hash
            or base_field != trusted_field
        ):
            raise ValueError(
                "trusted_run_legal_floor_authority_mismatch"
            )
        if (
            (base_capacity_contract or {}).get("floor_planning_mode")
            == "clear_span"
            and (
                not isinstance(trusted_clear_span_floor_plan, dict)
                or str(
                    trusted_clear_span_floor_plan.get(
                        "legal_floor_field_hash"
                    )
                    or ""
                )
                != trusted_hash
                or trusted_clear_span_floor_plan.get(
                    "legal_floor_field"
                )
                != trusted_field
            )
        ):
            raise ValueError(
                "trusted_run_clear_span_floor_authority_mismatch"
            )

    pool_started = perf_counter()
    accepted_archive = StreamingMapElitesArchive()
    evaluated = compiled = clean = program_passed = 0
    scope_stage_counts = {
        label: _empty_scope_stage_counts()
        for label, _fraction in BASE_VOLUME_FRACTIONS
    }
    gate_names = ("role_coverage", "dominant_ratio", "site_coverage", "hierarchy", "coherence", "program_form")
    gate_diagnostics = {label: _empty_gate_diagnostic() for label, _fraction in BASE_VOLUME_FRACTIONS}
    geometry_gate_diagnostics: dict[str, dict[str, Any]] = {}
    geometry_stage_counts: dict[str, dict[str, int]] = {}
    llm_authored_stage_counts: Counter[str] = Counter()
    llm_authored_failure_counts: Counter[str] = Counter()
    capacity_stage_counts: Counter[str] = Counter()
    capacity_target_floor_failure_counts: Counter[str] = Counter()
    floor_hard_capacity_utilizations: list[float] = []
    smoke_floor_pass_candidates = 0
    compiler_clean_base_geometry_hashes: dict[str, str | None] = dict(
        _reviewed_base_registry or {}
    )

    def certified_archived_base_keys() -> set[str]:
        return {
            key
            for key, geometry_hash in (
                compiler_clean_base_geometry_hashes.items()
            )
            if isinstance(geometry_hash, str) and geometry_hash
        }
    requested_early_stop_target = max(
        0,
        int(stop_after_shared_floor_hard_passes or 0),
    )
    early_stop_target = requested_early_stop_target
    explicit_diagnostic_budget = bool(
        diagnostic_scope_labels
        or diagnostic_book_probe_count is not None
        or diagnostic_evaluation_cap is not None
        or diagnostic_candidate_cap is not None
    )
    competition_breadth_budget = (
        resolve_competition_breadth_generation_budget(
            target_count=int(target_count),
            recursive_only=recursive_only,
            explicit_diagnostic_budget=explicit_diagnostic_budget,
            smoke_mode=requested_early_stop_target > 0,
        )
    )
    scope_schedule_labels = tuple(
        diagnostic_scope_labels
        or competition_breadth_budget.get("scope_labels")
        or ()
    )
    evaluation_cap = max(0, int(
        diagnostic_evaluation_cap
        if diagnostic_evaluation_cap is not None
        else competition_breadth_budget.get("cheap_evaluation_limit")
        or 0
    ))
    candidate_cap = max(0, int(
        diagnostic_candidate_cap
        if diagnostic_candidate_cap is not None
        else competition_breadth_budget.get("exact_shortlist_maximum")
        or 0
    ))
    book_probe_count = (
        max(1, int(diagnostic_book_probe_count))
        if diagnostic_book_probe_count is not None
        else int(competition_breadth_budget.get("book_probe_count") or 3)
    )

    def diagnostic_cap_reached() -> bool:
        return _diagnostic_generation_cap_reached(
            evaluated=evaluated,
            program_passed=program_passed,
            evaluation_cap=evaluation_cap,
            candidate_cap=candidate_cap,
        )

    def emit_progress() -> None:
        if progress_callback is not None:
            progress_callback({
                "evaluated_count": evaluated,
                "compiled_count": compiled,
                "program_passed_count": program_passed,
            })

    requested_parent_indices = tuple(sorted({max(0, int(index)) for index in parent_variant_indices})) or (0,)
    author_request_outcomes: list[LlmAuthorRequestOutcome] = []
    directed_seeds = (
        tuple(_directed_seeds_override)
        if _directed_seeds_override is not None
        else _agent_mutated_seeds(
            building_type,
            typed_graph_mutations,
            geometry_program_mutations,
            synthesis_requests,
            outcome_graph,
            site=site,
            site_boundary_source=site_boundary_source,
            site_access_context=site_access_context,
            site_access_geometry=site_access_geometry,
            program_dimensional_context=program_dimensional_context,
            height=height,
            floors=floors,
            live_geometry_vlm_revision=live_geometry_vlm_revision,
            base_capacity_contract=base_capacity_contract,
            universal_variation_pages=requested_parent_indices,
            author_request_outcomes=author_request_outcomes,
        )
    )
    llm_author_only_active = any(
        isinstance(request, dict)
        and bool(request.get("llm_author_only"))
        for request in (synthesis_requests or ())
    ) or bool(directed_seeds) and all(
        _seed_is_llm_authored(seed)
        for seed in directed_seeds
    )
    if recursive_only:
        directed_seeds = tuple(
            seed for seed in directed_seeds
            if (
                _seed_is_llm_authored(seed)
                if llm_author_only_active
                else any(
                    note.startswith((
                        "geometry_program_directive=",
                        "geometry_program_payload=",
                    ))
                    for note in seed.notes
                )
            )
        )
    parent_seeds = (
        tuple(deepcopy(_parent_seeds_override))
        if _parent_seeds_override is not None
        else tuple(
            variant
            for seed_index, seed in enumerate(directed_seeds)
            for variant_index, variant in enumerate(program_seed_variants(
                seed,
                count=max(requested_parent_indices) + 1,
                random_seed=417 + seed_index * 97,
            ))
            if variant_index in requested_parent_indices
        )
    )
    diagnostic_anchors_active = diagnostic_anchor_schedule_active(
        recursive_only=recursive_only,
        evaluation_cap=evaluation_cap,
        parent_indices=requested_parent_indices,
        has_capacity_contract=bool(base_capacity_contract),
        target_count=target_count,
        llm_author_only=llm_author_only_active,
    )
    if diagnostic_anchors_active:
        parent_seeds = schedule_diagnostic_anchor_parents(parent_seeds)
    compile_limit = (
        None
        if exact_compile_limit is None
        else max(0, int(exact_compile_limit))
    )
    if compile_limit is not None:
        parent_seeds = parent_seeds[:compile_limit]

    def exact_compile_cap_reached() -> bool:
        return bool(
            compile_limit is not None
            and materialization_diagnostics.materialization_invocation_count
            >= compile_limit
        )
    outcome_program_slug = next(
        (slug for slug, label, _height, _floors in PROGRAMS if label == building_type),
        str(building_type),
    )
    llm_authored_stage_counts["directed_seed_count"] = sum(
        _seed_is_llm_authored(seed) for seed in directed_seeds
    )
    llm_authored_stage_counts["parent_seed_count"] = sum(
        _seed_is_llm_authored(seed) for seed in parent_seeds
    )
    principles = tuple(build_book_language_registry()["principles"])
    principle_by_id = {
        str(principle["principle_id"]): (index, principle)
        for index, principle in enumerate(principles)
    }
    breadth_enumeration_duration = perf_counter() - pool_started
    # The legal section field is invariant across every seed/BOOK probe in
    # this program run.  Materializing it inside the 1,968-candidate loop
    # repeated the same intersection/repair work thousands of times.
    run_floor_containment_hosts: tuple[Polygon | None, ...] = ()
    if trusted_legal_floor_field:
        authoritative_sections = (
            trusted_clear_span_floor_plan.get("legal_floor_sections")
            if (
                (base_capacity_contract or {}).get(
                    "floor_planning_mode"
                )
                == "clear_span"
                and isinstance(trusted_clear_span_floor_plan, dict)
            )
            else trusted_legal_floor_field.get(
                "legal_floor_sections"
            )
        )
        run_floor_containment_hosts = tuple(
            shape(section) for section in authoritative_sections or ()
        )
    elif generation_context is not None:
        run_floor_containment_hosts = tuple(
            generation_site_at_height(
                generation_context,
                float(height) * floor_number / max(1, int(floors)),
            )
            for floor_number in range(
                1,
                max(1, int(floors)) + 1,
            )
        )
    run_upper_containment_host = (
        run_floor_containment_hosts[-1]
        if run_floor_containment_hosts
        else None
    )
    competition_selected_exact_keys: frozenset[str] = frozenset()
    competition_exact_keys: frozenset[str] = frozenset()
    competition_base_anchor_keys: frozenset[str] = frozenset()
    competition_language_anchor_keys: frozenset[str] = frozenset()
    competition_cheap_schedule = None
    cheap_screen_duration = 0.0
    if competition_breadth_budget:
        cheap_screen_started = perf_counter()
        cheap_records = _competition_cheap_candidate_records(
            parent_seeds,
            principles,
            book_probe_count=book_probe_count,
            evaluation_limit=evaluation_cap,
            scope_labels=scope_schedule_labels,
            page_index=min(requested_parent_indices),
            legal_sections=run_floor_containment_hosts,
            capacity_contract=base_capacity_contract,
        )
        competition_selected_exact_keys, competition_cheap_schedule = (
            _competition_pre_exact_shortlist(
                cheap_records,
                page_index=min(requested_parent_indices),
                target_count=int(target_count),
            )
        )
        competition_exact_keys = (
            _expand_competition_exact_lineage_dependencies(
                competition_selected_exact_keys,
                tuple(principles),
            )
        )
        competition_base_anchor_keys = _competition_base_anchor_keys(
            parent_count=len(parent_seeds),
            principles=tuple(principles),
            book_probe_count=book_probe_count,
        )
        competition_language_anchor_keys = _competition_language_anchor_keys(
            parent_count=len(parent_seeds),
            principles=tuple(principles),
            book_probe_count=book_probe_count,
        )
        competition_exact_keys = frozenset({
            *competition_exact_keys,
            *competition_base_anchor_keys,
            *competition_language_anchor_keys,
        })
        cheap_screen_duration = perf_counter() - cheap_screen_started
    exact_compile_started = perf_counter()
    for seed_index, seed in enumerate(parent_seeds):
        if exact_compile_cap_reached():
            break
        if (
            diagnostic_cap_reached()
            or early_stop_target
            and smoke_floor_pass_candidates >= early_stop_target
        ):
            break
        llm_authored_seed = _seed_is_llm_authored(seed)
        recursive_seed = any(
            note.startswith(("geometry_program_directive=", "geometry_program_payload="))
            for note in seed.notes
        )
        recursive_program: GeometryProgram | None = None
        llm_book_path_contract: dict[str, Any] | None = None
        if recursive_seed:
            payload = next((
                note.split("=", 1)[1]
                for note in seed.notes
                if note.startswith("geometry_program_payload=")
            ), "")
            try:
                recursive_program = GeometryProgram.from_dict(json.loads(payload))
            except (TypeError, ValueError, json.JSONDecodeError):
                recursive_program = None
        if llm_authored_seed:
            llm_book_path_contract = _llm_book_path_execution_contract(
                recursive_program,
                tuple(principles),
            )
        source_seed_name = next((
            note.split("=", 1)[1]
            for note in seed.notes
            if note.startswith("geometry_program_source_seed=")
        ), "") if recursive_seed else ""
        anchor_spec = diagnostic_anchor_spec(seed)
        # The exhaustive 69/69 BOOK compiler audit remains a separate hard
        # regression. In portfolio synthesis, multiplying every recursive AST
        # by all 69 sentences and all three probes mostly relabelled the same
        # geometry thousands of times. Give each genotype a deterministic,
        # scope-balanced BOOK neighbourhood so the compute budget explores
        # more actual graph topologies instead.
        scheduled_principles = (
            staged_principle_schedule(principles, seed_index, count=12)
            if recursive_seed
            else tuple(enumerate(principles))
        )
        if (
            recursive_seed
            and outcome_graph is not None
            and not competition_breadth_budget
        ):
            genotype_hash = recursive_program.program_hash() if recursive_program is not None else ""
            if genotype_hash and source_seed_name:
                preferred_ids = outcome_graph.preferred_book_principle_ids(
                    source_seed=source_seed_name,
                    program_hash=genotype_hash,
                    fallback=(str(principle["principle_id"]) for _index, principle in scheduled_principles),
                    limit=12,
                )
                preferred_rank = {
                    principle_id: rank
                    for rank, principle_id in enumerate(preferred_ids)
                }
                scheduled_principles = tuple(sorted(
                    scheduled_principles,
                    key=lambda item: (
                        int(item[1].get("generation_stage_order") or 1),
                        preferred_rank.get(str(item[1]["principle_id"]), len(preferred_rank)),
                    ),
                ))
        principle_schedule_limit = _recursive_principle_schedule_limit(
            evaluation_cap=evaluation_cap,
            explicit_diagnostic_budget=explicit_diagnostic_budget,
        )
        if recursive_seed and principle_schedule_limit is not None:
            scheduled_principles = (
                _balanced_principle_window_with_lineage_bases(
                    scheduled_principles,
                    seed_index=seed_index,
                    count=principle_schedule_limit,
                )
            )
        scheduled_principles = diagnostic_anchor_principles(
            seed,
            principle_by_id,
            scheduled_principles,
        )
        if competition_breadth_budget:
            # The cheap screen already chose the exact descriptor keys.
            # Consume those same keys directly instead of spending the exact
            # cap against a separately reconstructed local BOOK window.
            scheduled_principles = _competition_exact_principle_schedule(
                competition_exact_keys,
                tuple(principles),
                seed_index=seed_index,
            )
        if llm_book_path_contract is not None:
            selected_principle_id = str(
                llm_book_path_contract["principle_id"]
            )
            selected_item = principle_by_id.get(selected_principle_id)
            base_id = str(
                llm_book_path_contract["principle"].get(
                    "lineage_base_operative_id"
                ) or selected_principle_id
            )
            base_item = principle_by_id.get(base_id)
            exact_schedule: list[tuple[int, dict[str, Any]]] = []
            exact_ids: set[str] = set()
            for item in (base_item, selected_item):
                if item is None:
                    continue
                item_id = str(item[1].get("principle_id") or "")
                if not item_id or item_id in exact_ids:
                    continue
                exact_ids.add(item_id)
                exact_schedule.append(item)
            scheduled_principles = tuple(exact_schedule)
        recursive_family = str((recursive_program.metadata if recursive_program else {}).get("family") or "")
        geometry_stages = None
        if recursive_seed:
            geometry_stages = geometry_stage_counts.setdefault(
                recursive_family or "invalid_recursive_program",
                {
                    "evaluated": 0,
                    "sequence_compiled": 0,
                    "sequence_compile_failed": 0,
                    "directed_geometry_materialized": 0,
                    "directed_geometry_materialization_failed": 0,
                    "projection_materialized": 0,
                    "projection_failed": 0,
                    "clean_mass_passed": 0,
                    "containment_failed": 0,
                    "program_hard_passed": 0,
                },
            )
        selected_principle_ids = (
            frozenset(
                parts[1]
                for key in competition_selected_exact_keys
                if (parts := _competition_exact_key_parts(key))
                is not None
                and int(parts[0]) == seed_index
            )
            if competition_breadth_budget
            else None
        )
        descendant_tuple_schedule = ()
        seed_principles = (
            scheduled_principles
            if llm_book_path_contract is not None
            else _principles_for_seed(
                scheduled_principles,
                seed_index=seed_index,
                llm_authored_seed=llm_authored_seed,
                selected_principle_ids=selected_principle_ids,
                descendant_probe_count=(
                    max(1, int(book_probe_count))
                    if _generation_phase == "descendant"
                    else 1
                ),
            )
        )
        if llm_authored_seed:
            llm_authored_stage_counts[
                "outer_book_schedule_duplicates_skipped"
            ] += max(0, len(scheduled_principles) - len(seed_principles))
            # BASE candidates must finish certification and archive admission
            # before any descendant reads the exact parent geometry registry.
            seed_principles = _llm_base_then_descendant_schedule(
                seed_principles
            )
        if _generation_phase == "base":
            seed_principles = tuple(
                item for item in seed_principles
                if str(item[1].get("generation_stage") or "") == "base"
                or str(item[1].get("principle_id") or "")
                == str(
                    item[1].get("lineage_base_operative_id")
                    or item[1].get("principle_id")
                    or ""
                )
            )
        elif _generation_phase == "descendant":
            reviewed_seed_parent_lineages = tuple(
                lineage
                for lineage in (_reviewed_base_lineages or ())
                if canonical_lineage_parent_key(lineage)
                and str(lineage.get("source_seed") or "") == seed.name
            )
            descendant_schedule_cap = (
                12 if recursive_seed else len(principles)
            )
            if (
                principle_schedule_limit is not None
                and int(principle_schedule_limit) > 0
            ):
                descendant_schedule_cap = min(
                    descendant_schedule_cap,
                    int(principle_schedule_limit),
                )
            if evaluation_cap is not None and int(evaluation_cap) > 0:
                descendant_schedule_cap = min(
                    descendant_schedule_cap,
                    int(evaluation_cap),
                )
            if llm_book_path_contract is not None:
                selected = next((
                    item for item in seed_principles
                    if str(item[1].get("principle_id") or "")
                    == str(llm_book_path_contract["principle_id"])
                ), None)
                exact_variants = book_sentence_variants(
                    tuple(llm_book_path_contract["ordered_operations"]),
                    count=11,
                )
                reviewed_parent = next(iter(
                    reviewed_seed_parent_lineages
                ), None)
                descendant_tuple_schedule = (
                    (
                        selected[0],
                        selected[1],
                        int(llm_book_path_contract["variation_index"]),
                        exact_variants[
                            int(llm_book_path_contract["variation_index"])
                        ],
                        reviewed_parent,
                    ),
                ) if selected is not None and reviewed_parent is not None else ()
            else:
                descendant_tuple_schedule = _canonical_descendant_tuple_schedule(
                    tuple(principles),
                    reviewed_seed_parent_lineages,
                    seed=seed,
                    seed_index=seed_index,
                    selected_principle_ids=selected_principle_ids,
                    descendant_probe_count=max(1, int(book_probe_count)),
                    variant_count=max(1, int(book_probe_count)),
                    schedule_cap=descendant_schedule_cap,
                    rotation_offset=(
                        min(parent_variant_indices)
                        if parent_variant_indices
                        else 0
                    ),
                    selected_candidate_keys=(
                        competition_selected_exact_keys
                        if competition_breadth_budget
                        else None
                    ),
                    allowed_variant_indices=(
                        frozenset({int(anchor_spec.variant_index)})
                        if anchor_spec is not None
                        else None
                    ),
                    replenishment_causal_request_hash=(
                        _replenishment_causal_request_hash
                    ),
                    reviewed_parent_authority={
                        parent_key: {
                            "parent_key": parent_key,
                            "geometry_hash": str(
                                (_reviewed_base_registry or {}).get(
                                    parent_key
                                ) or ""
                            ),
                            "program_hash": str(
                                audit.get("program_hash") or ""
                            ),
                            "base_review_fingerprint": str(
                                audit.get("base_review_fingerprint") or ""
                            ),
                        }
                        for parent_key, audit in (
                            _reviewed_base_audits or {}
                        ).items()
                        if isinstance(audit, dict)
                    },
                    attempted_work_keys=(
                        _replenishment_attempted_work_keys
                    ),
                    work_disposition_evidence=(
                        replenishment_work_evidence
                    ),
                )
            seed_principles = tuple(
                (principle_index, principle)
                for principle_index, principle, _variant, _operations, _parent
                in descendant_tuple_schedule
            )
        for schedule_index, (principle_index, principle) in enumerate(seed_principles):
            if exact_compile_cap_reached():
                break
            if (
                diagnostic_cap_reached()
                or early_stop_target
                and smoke_floor_pass_candidates >= early_stop_target
            ):
                break
            execution_verbs = tuple(principle["execution_verbs"])
            lineage_base_id = str(
                principle.get("lineage_base_operative_id")
                or principle["principle_id"]
            )
            lineage_base_index = principle_by_id.get(
                lineage_base_id,
                (principle_index, principle),
            )[0]
            # One BOOK sentence is a typed operator family, not one frozen
            # geometry.  Execute three bounded schema-derived parameter probes
            # so selection can compare real alternatives without parcel or
            # finished-form templates.
            variation_indices = book_variation_indices(book_probe_count)
            sentence_variants = diagnostic_anchor_sentence_variants(
                seed,
                execution_verbs,
                default_count=book_probe_count,
            )
            if llm_book_path_contract is not None:
                exact_variation_index = int(
                    llm_book_path_contract["variation_index"]
                )
                variation_indices = (exact_variation_index,)
                sentence_variants = (
                    book_sentence_variants(
                        execution_verbs,
                        count=11,
                    )[exact_variation_index],
                )
            if anchor_spec is not None:
                variation_indices = (anchor_spec.variant_index,)
            indexed_variants = tuple(zip(variation_indices, sentence_variants))
            scheduled_variants = (
                _competition_exact_variant_schedule(
                    competition_exact_keys,
                    seed_index=seed_index,
                    principle_id=str(principle["principle_id"]),
                    indexed_variants=indexed_variants,
                )
                if competition_breadth_budget
                else (
                    indexed_variants[
                        (seed_index + lineage_base_index)
                        % len(indexed_variants)
                    ],
                )
                if recursive_seed
                else indexed_variants
            )
            reviewed_parent_lineages = tuple(
                lineage
                for lineage in (
                    reviewed_seed_parent_lineages
                    if _generation_phase == "descendant"
                    else ()
                )
                if str(lineage.get("base_operative_id") or "")
                == lineage_base_id
            )
            if _generation_phase == "descendant":
                (
                    _scheduled_principle_index,
                    _scheduled_principle,
                    scheduled_variant_index,
                    scheduled_operations,
                    scheduled_parent,
                ) = descendant_tuple_schedule[schedule_index]
                scheduled_lineage_variants = ((
                    scheduled_variant_index,
                    scheduled_operations,
                    scheduled_parent,
                ),)
            else:
                scheduled_lineage_variants = tuple(
                    (variant_index, operations, reviewed_parent)
                    for variant_index, operations in scheduled_variants
                    for reviewed_parent in (None,)
                )
            for variant_index, operations, reviewed_parent in (
                scheduled_lineage_variants
            ):
                if exact_compile_cap_reached():
                    break
                if (
                    diagnostic_cap_reached()
                    or early_stop_target
                    and smoke_floor_pass_candidates >= early_stop_target
                ):
                    break
                active_work_disposition = None
                if (
                    _generation_phase == "descendant"
                    and reviewed_parent is not None
                    and _replenishment_causal_request_hash
                ):
                    active_work_disposition = (
                        _begin_replenishment_work_disposition(
                            _replenishment_descendant_work_identity(
                                reviewed_parent,
                                principle_id=str(principle["principle_id"]),
                                variant_index=int(variant_index),
                                causal_request_hash=(
                                    _replenishment_causal_request_hash
                                ),
                                reviewed_parent_authority={
                                    parent_key: {
                                        "parent_key": parent_key,
                                        "geometry_hash": str(
                                            (_reviewed_base_registry or {}).get(
                                                parent_key
                                            ) or ""
                                        ),
                                        "program_hash": str(
                                            audit.get("program_hash") or ""
                                        ),
                                        "base_review_fingerprint": str(
                                            audit.get(
                                                "base_review_fingerprint"
                                            ) or ""
                                        ),
                                    }
                                    for parent_key, audit in (
                                        _reviewed_base_audits or {}
                                    ).items()
                                    if isinstance(audit, dict)
                                },
                            ),
                            evidence=replenishment_work_evidence,
                        )
                    )
                evaluated += 1
                emit_progress()
                if llm_authored_seed:
                    llm_authored_stage_counts["evaluated"] += 1
                if geometry_stages is not None:
                    geometry_stages["evaluated"] += 1
                suffix = str(principle["principle_id"]).split("book:", 1)[-1].replace(":", "_")
                # The page grammar crosses each operation variation with the
                # six base volumes and three shown orientations.  Including
                # the canonical variation state here prevents one seed from
                # receiving three parameter edits on the same frozen host.
                base_volume_label, orientation = book_probe_scope(
                    seed_index,
                    lineage_base_index,
                    variant_index,
                    force_vertical=(
                        recursive_program is not None
                        and lineage_base_id == "book:operative:extrude"
                    ),
                    # A recursive seed evaluates one representative variant
                    # for budget control. Coupling that single variant back
                    # into p.3 scope made 1/1 and 1/4 mathematically
                    # unreachable; scope must rotate independently here.
                    couple_variation=not recursive_seed,
                )
                if scope_schedule_labels and llm_book_path_contract is None:
                    base_volume_label = _lineage_stable_scope_label(
                        scope_schedule_labels,
                        seed_index=seed_index,
                        lineage_base_index=lineage_base_index,
                        variant_index=variant_index,
                    )
                if llm_book_path_contract is not None:
                    base_volume_label = str(
                        llm_book_path_contract["base_volume_label"]
                    )
                    orientation = str(
                        llm_book_path_contract["orientation"]
                    )
                base_volume_label, orientation = diagnostic_anchor_scope(
                    seed,
                    default_label=base_volume_label,
                    default_orientation=orientation,
                )
                scope_counts = scope_stage_counts[base_volume_label]
                scope_counts["evaluated"] += 1
                if reviewed_parent is not None:
                    generation_lineage = lineage_record(
                        principle,
                        source_seed=seed.name,
                        scope_label=base_volume_label,
                        orientation=orientation,
                        variant_index=variant_index,
                    )
                    generation_lineage["parent_base_lineage"] = deepcopy(
                        reviewed_parent
                    )
                    generation_lineage["parent_key"] = (
                        canonical_lineage_parent_key(reviewed_parent)
                    )
                    generation_lineage["descendant_operation"] = {
                        "schema_version": (
                            "arr.maas.book_descendant_operation.v1"
                        ),
                        "stage": str(
                            principle.get("generation_stage")
                            or principle.get("kind")
                            or "descendant"
                        ),
                        "stage_order": int(
                            principle.get("generation_stage_order") or 2
                        ),
                        "principle_id": str(principle["principle_id"]),
                        "principle_label": str(principle.get("label") or ""),
                        "principle_kind": str(principle.get("kind") or ""),
                        "parent_principle_id": principle.get(
                            "lineage_parent_principle_id"
                        ),
                        "execution_verbs": list(
                            principle.get("execution_verbs") or ()
                        ),
                        "implementation_elements": list(
                            principle.get("implementation_elements") or ()
                        ),
                        "scope_label": base_volume_label,
                        "orientation": orientation,
                        "variant_index": int(variant_index),
                    }
                    if _replenishment_causal_request_hash:
                        generation_lineage[
                            "replenishment_work_identity"
                        ] = _replenishment_descendant_work_identity(
                            reviewed_parent,
                            principle_id=str(principle["principle_id"]),
                            variant_index=int(variant_index),
                            causal_request_hash=(
                                _replenishment_causal_request_hash
                            ),
                            reviewed_parent_authority={
                                parent_key: {
                                    "parent_key": parent_key,
                                    "geometry_hash": str(
                                        (_reviewed_base_registry or {}).get(
                                            parent_key
                                        ) or ""
                                    ),
                                    "program_hash": str(
                                        audit.get("program_hash") or ""
                                    ),
                                    "base_review_fingerprint": str(
                                        audit.get(
                                            "base_review_fingerprint"
                                        ) or ""
                                    ),
                                }
                                for parent_key, audit in (
                                    _reviewed_base_audits or {}
                                ).items()
                                if isinstance(audit, dict)
                            },
                        )
                else:
                    generation_lineage = lineage_record(
                        principle,
                        source_seed=seed.name,
                        scope_label=base_volume_label,
                        orientation=orientation,
                        variant_index=variant_index,
                    )
                if llm_book_path_contract is not None:
                    generation_lineage["llm_book_path_execution_contract"] = (
                        deepcopy(llm_book_path_contract)
                    )
                generation_lineage, composed, authorization_reason = (
                    _authorize_and_compose_descendant_candidate(
                        seed,
                        operations,
                        generation_lineage=generation_lineage,
                        generation_phase=_generation_phase,
                        registry=_reviewed_base_registry or {},
                        reviewed_base_audits=_reviewed_base_audits or {},
                        name_suffix=suffix,
                        base_volume_label=base_volume_label,
                        orientation=orientation,
                    )
                )
                if _generation_phase == "descendant":
                    descendant_parent_authorization["input_count"] += 1
                    if generation_lineage is None or composed is None:
                        descendant_parent_authorization["filtered_count"] += 1
                        reasons = descendant_parent_authorization[
                            "filtered_by_reason"
                        ]
                        reasons[authorization_reason] = (
                            int(reasons.get(authorization_reason) or 0) + 1
                        )
                        _finish_replenishment_work_disposition(
                            active_work_disposition,
                            terminal_stage="lineage_authorization",
                            terminal_reason=authorization_reason,
                        )
                        continue
                    descendant_parent_authorization["authorized_count"] += 1
                sequence = VerbSequence(
                    name=f"{composed.name}__search_v{variant_index}",
                    label=composed.label,
                    calls=composed.calls,
                    notes=composed.notes,
                )
                competition_candidate_key = (
                    f"{seed_index}:"
                    f"{principle['principle_id']}:"
                    f"{variant_index}"
                )
                if (
                    competition_breadth_budget
                    and competition_candidate_key
                    not in competition_exact_keys
                ):
                    capacity_stage_counts[
                        "competition_cheap_screen_deferred_from_exact"
                    ] += 1
                    continue
                if competition_breadth_budget:
                    capacity_stage_counts[
                        "competition_exact_shortlist_entered"
                    ] += 1
                compile_site = site
                generation_host_mode = "horizontal_buildable_envelope"
                recursive_directed = any(
                    note.startswith(("geometry_program_directive=", "geometry_program_payload="))
                    for note in sequence.notes
                )
                # The third typed parameter probe also explores the vertical
                # legal field.  Its base host is the sunlight-safe section at
                # the requested program height, so the resulting geometry is
                # born inside the envelope instead of repaired after selection.
                use_height_safe_host = variant_index >= 8 or (
                    base_volume_label == "1/16" and variant_index == 0
                )
                if (
                    generation_context is not None
                    and use_height_safe_host
                    and not recursive_directed
                ):
                    # Use the section at two thirds of design height.  The
                    # remaining cap is still measured by the exact downstream
                    # retention gate, while the host remains large enough to
                    # carry a coherent long-span/program role graph.
                    generation_section_ratio = 2.0 / 3.0
                    height_safe_site = generation_site_at_height(
                        generation_context,
                        height * generation_section_ratio,
                    )
                    if height_safe_site is not None:
                        compile_site = height_safe_site
                        generation_host_mode = "height_safe_sunlight_section"
                genotype_schedule_index = (
                    seed_index + lineage_base_index + variant_index
                )
                capacity_schedule_index = (
                    diagnostic_anchor_capacity_schedule_index(
                        seed,
                        default_index=_capacity_alternative_schedule_index(
                            evaluation_index=evaluated - 1,
                            diagnostic_evaluation_cap=evaluation_cap,
                            genotype_schedule_index=genotype_schedule_index,
                            competition_target_count=(
                                int(target_count)
                                if competition_breadth_budget
                                else 0
                            ),
                            page_index=min(requested_parent_indices),
                        ),
                    )
                )
                # Two axes, two cursors. Sharing one would pin a ground-take to
                # a floor-area band for the whole run and leave the portfolio
                # with a single diagonal instead of a grid - the same aliasing
                # that pinned every seed to one BOOK scope (38b2756). Dividing
                # by the alternative count advances the ground-take once the
                # floor-area bands have been walked, so the pair covers all
                # sixteen combinations.
                capacity_alternative = build_capacity_alternative(
                    base_capacity_contract,
                    capacity_alternative_for_host(
                        capacity_schedule_index,
                        base_capacity_contract,
                        host_area_m2=float(compile_site.area),
                        floor_count=floors,
                    ),
                    coverage_band=COVERAGE_BANDS[
                        (
                            capacity_schedule_index
                            // len(CAPACITY_ALTERNATIVE_SPECS)
                        )
                        % len(COVERAGE_BANDS)
                    ],
                )
                if diagnostic_evaluation_trace_callback is not None:
                    diagnostic_evaluation_trace_callback({
                        "evaluation_index": evaluated - 1,
                        "genotype_hash": (
                            recursive_program.program_hash()
                            if recursive_program is not None
                            else ""
                        ),
                        "form_bank_lane": str(
                            (recursive_program.metadata if recursive_program else {}).get(
                                "form_bank_lane"
                            )
                            or ""
                        ),
                        "book_stage": str(
                            generation_lineage.get("stage") or ""
                        ),
                        "book_stage_order": int(
                            generation_lineage.get("stage_order") or 0
                        ),
                        "principle_id": str(
                            generation_lineage.get("principle_id") or ""
                        ),
                        "parent_key": str(
                            generation_lineage.get("parent_key") or ""
                        ),
                        "scope_label": base_volume_label,
                        "orientation": orientation,
                        "variant_index": int(variant_index),
                        "capacity_schedule_index": capacity_schedule_index,
                        "capacity_alternative_id": str(
                            capacity_alternative.get("alternative_id") or ""
                        ),
                        "diagnostic_anchor_body_family": (
                            anchor_spec.body_family
                            if anchor_spec is not None
                            else ""
                        ),
                        "diagnostic_anchor_principle_id": (
                            anchor_spec.principle_id
                            if anchor_spec is not None
                            else ""
                        ),
                    })
                alternative_capacity_contract = capacity_contract_for_alternative(
                    base_capacity_contract,
                    capacity_alternative,
                )
                candidate_floor_context = _candidate_floor_context(
                    alternative_capacity_contract,
                    fallback_height=height,
                    fallback_floors=floors,
                    fallback_legal_sections=run_floor_containment_hosts,
                    trusted_legal_floor_field=trusted_legal_floor_field,
                    expected_legal_floor_field_hash=(
                        trusted_legal_floor_field_hash
                    ),
                    trusted_clear_span_floor_plan=(
                        trusted_clear_span_floor_plan
                    ),
                )
                if candidate_floor_context.get("hard_pass") is not True:
                    capacity_stage_counts[
                        "candidate_floor_context_failed"
                    ] += 1
                    continue
                candidate_height = float(
                    candidate_floor_context["height_m"]
                )
                candidate_floors = int(
                    candidate_floor_context["floors"]
                )
                candidate_legal_sections = tuple(
                    candidate_floor_context["legal_sections"]
                )
                candidate_floor_tops = tuple(
                    candidate_floor_context["floor_top_heights_m"]
                )
                capacity_alternative = {
                    **capacity_alternative,
                    "candidate_requested_floors": candidate_floors,
                    "candidate_requested_height_m": round(
                        candidate_height,
                        3,
                    ),
                    "candidate_floor_count_authority": str(
                        candidate_floor_context.get("authority") or ""
                    ),
                    "legal_floor_field_hash": str(
                        candidate_floor_context.get(
                            "legal_floor_field_hash"
                        )
                        or ""
                    ),
                }
                if use_height_safe_host and recursive_directed:
                    host_floor_index = min(
                        candidate_floors - 1,
                        max(
                            0,
                            (candidate_floors * 2 + 2) // 3 - 1,
                        ),
                    )
                    compile_site = candidate_legal_sections[
                        host_floor_index
                    ]
                    generation_host_mode = (
                        "candidate_legal_floor_prefix_section"
                    )
                    generation_host_section_height = (
                        candidate_floor_tops[host_floor_index]
                    )
                else:
                    generation_host_section_height = 0.0
                # A recursive candidate has one BOOK geometry authority. The
                # source compiler establishes only its program-role scaffold;
                # the exact p.3 selector and ordered operations are applied
                # once, below, to the manifold AST.
                source_sequence = seed if recursive_directed else sequence
                source = compile_sequence_to_source_mass(compile_site, source_sequence)
                if source is None:
                    if outcome_graph is not None and recursive_program is not None and source_seed_name:
                        outcome_graph.observe_geometry_gate_failure(
                            program_slug=outcome_program_slug,
                            source_seed=source_seed_name,
                            program=recursive_program,
                            principle_id=str(principle["principle_id"]),
                            book_scope=base_volume_label,
                            legal_floor_field_hash=str(
                                candidate_floor_context.get(
                                    "legal_floor_field_hash"
                                ) or ""
                            ),
                            stage="sequence_compile",
                            failure_reasons=("sequence_compile_failed",),
                        )
                    if llm_authored_seed:
                        llm_authored_failure_counts["sequence_compile_failed"] += 1
                    if geometry_stages is not None:
                        geometry_stages["sequence_compile_failed"] += 1
                    continue
                pre_book_parent_compiler_clean = False
                pre_book_parent_contained = False
                lineage_parent_key = ""
                if llm_authored_seed and recursive_directed:
                    parent_clean, _parent_clean_evidence = _clean_mass_gate(source)
                    parent_contained = _inside_site(source, compile_site)
                    candidate_parent_key = canonical_lineage_parent_key(
                        generation_lineage
                    )
                    if parent_clean and parent_contained and candidate_parent_key:
                        pre_book_parent_compiler_clean = True
                        pre_book_parent_contained = True
                        lineage_parent_key = candidate_parent_key
                capacity_measurement: dict[str, Any] = {}
                if geometry_stages is not None:
                    geometry_stages["sequence_compiled"] += 1
                if llm_authored_seed:
                    llm_authored_stage_counts["sequence_compiled"] += 1
                materialization_source = replace(
                    source,
                    metadata={
                        **deepcopy(source.metadata),
                        "candidate_floor_context": deepcopy(
                            candidate_floor_context
                        ),
                    },
                )
                upper_containment_host = (
                    candidate_floor_context["upper_legal_section"]
                    if recursive_directed
                    else None
                )
                floor_containment_hosts = (
                    candidate_legal_sections
                    if recursive_directed
                    else ()
                )
                plan_coverage = recursive_plan_coverage_floor(
                    building_type,
                    alternative_capacity_contract,
                    host_area_m2=float(compile_site.area),
                )
                candidate_terminal_failures: list[dict[str, Any]] = []
                def materialize_capacity_fit(
                    coverage: float,
                    floor_targets: tuple[float, ...],
                    capacity_utilizations: tuple[float, float] | None = None,
                ) -> SourceMass | None:
                    candidate_terminal_failures.clear()
                    materialized = _materialize_directed_geometry(
                        materialization_source,
                        sequence,
                        building_type=building_type,
                        site_access_side=(
                            _site_access_side_in_principal_frame(
                                site,
                                site_access_geometry,
                            )
                        ),
                        containment_host=compile_site,
                        upper_containment_host=upper_containment_host,
                        floor_containment_hosts=floor_containment_hosts,
                        minimum_host_plan_coverage=coverage,
                        capacity_composition_utilizations=capacity_utilizations,
                        floor_capacity_plan_hash=str(
                            alternative_capacity_contract.get(
                                "floor_capacity_plan_hash"
                            )
                            or ""
                        ),
                        legal_floor_field_hash=str(
                            candidate_floor_context.get(
                                "legal_floor_field_hash"
                            )
                            or ""
                        ),
                        legal_fit_failure_sink=legal_fit_deficits,
                        terminal_failure_sink=candidate_terminal_failures,
                        target_floor_areas_m2=floor_targets,
                        coverage_capacity_m2=_ground_take_bounded_coverage_capacity(
                            trusted_legal_floor_field,
                            capacity_alternative,
                        ),
                        pnu=pnu,
                        capacity_alternative_id=str(
                            capacity_alternative.get(
                                "alternative_id"
                            )
                            or ""
                        ),
                        site_context_hash=semantic_site_context_hash(
                            pnu=pnu,
                            building_type=building_type,
                            site=(
                                generation_context.generation_site
                                if generation_context is not None
                                else site
                            ),
                        ),
                        lineage_parent_key=lineage_parent_key,
                        pre_book_parent_compiler_clean=(
                            pre_book_parent_compiler_clean
                        ),
                        pre_book_parent_contained=pre_book_parent_contained,
                    )
                    materialization_diagnostics.record_invocation(
                        materialized=materialized,
                        terminal_failures=candidate_terminal_failures,
                    )
                    return materialized

                if exact_compile_cap_reached():
                    break
                source = _materialize_once_for_capacity_policy(
                    materialize_capacity_fit,
                    plan_coverage,
                    tuple(
                        float(value)
                        for value in (
                            alternative_capacity_contract.get(
                                "target_floor_areas_m2"
                            )
                            or ()
                        )
                    ),
                )
                if source is None:
                    terminal_record = (
                        candidate_terminal_failures[0]
                        if candidate_terminal_failures
                        else {"stage": "outer_precondition", "evidence": {}}
                    )
                    terminal_stage = str(
                        terminal_record.get("stage") or "outer_precondition"
                    )
                    if recursive_program is not None and source_seed_name:
                        _propagate_terminal_materialization_failure(
                            terminal_record=terminal_record,
                            report_records=terminal_materialization_failures,
                            outcome_graph=outcome_graph,
                            program_slug=outcome_program_slug,
                            source_seed=source_seed_name,
                            program=recursive_program,
                            principle_id=str(principle["principle_id"]),
                            book_scope=base_volume_label,
                            legal_floor_field_hash=str(
                                candidate_floor_context.get(
                                    "legal_floor_field_hash"
                                ) or ""
                            ),
                        )
                    if llm_authored_seed:
                        llm_authored_failure_counts["directed_geometry_materialization_failed"] += 1
                        llm_authored_failure_counts[terminal_stage] += 1
                    if geometry_stages is not None:
                        geometry_stages["directed_geometry_materialization_failed"] += 1
                        geometry_stages[terminal_stage] = (
                            geometry_stages.get(terminal_stage, 0) + 1
                        )
                    continue
                capacity_plan_fit_evidence: dict[str, Any] = {
                    "schema_version": "arr.maas.capacity_plan_fit.v1",
                    "retry_limit": 2,
                    "retry_attempted": False,
                    "geometry_retry_policy": GEOMETRY_RETRY_POLICY,
                    "initial_plan_coverage": round(plan_coverage, 6),
                }
                if base_capacity_contract and capacity_site is not None and recursive_directed:
                    initial_floor_contract, initial_capacity = (
                        _shared_floor_capacity_measurement(
                        source,
                        alternative_capacity_contract,
                        generation_context=generation_context,
                        capacity_site=capacity_site,
                        height=candidate_height,
                        floors=candidate_floors,
                        pnu=pnu,
                        trusted_legal_floor_field=(
                            trusted_legal_floor_field
                        ),
                        expected_legal_floor_field_hash=(
                            trusted_legal_floor_field_hash
                        ),
                        trusted_clear_span_floor_plan=(
                            trusted_clear_span_floor_plan
                        ),
                        )
                    )
                    retry_coverage = capacity_retry_plan_coverage(
                        plan_coverage,
                        capacity_alternative,
                        initial_capacity,
                    )
                    retry_floor_targets = capacity_retry_floor_targets(
                        alternative_capacity_contract,
                        capacity_alternative,
                        initial_capacity,
                    )
                    retry_required = _capacity_retry_required(
                        current_plan_coverage=plan_coverage,
                        retry_plan_coverage=retry_coverage,
                        current_floor_targets=alternative_capacity_contract.get(
                            "target_floor_areas_m2"
                        ),
                        retry_floor_targets=retry_floor_targets,
                    )
                    capacity_plan_fit_evidence.update({
                        "initial_achieved_utilization": initial_capacity.get(
                            "feasible_capacity_utilization"
                        ),
                        "derived_retry_plan_coverage": retry_coverage,
                        "derived_retry_floor_targets_m2": list(
                            retry_floor_targets
                        ),
                        "retry_required": retry_required,
                        "retry_attempted": False,
                        "retry_selected": False,
                        "geometry_retry_bypassed": bool(retry_required),
                        "geometry_retry_policy": GEOMETRY_RETRY_POLICY,
                        "retry_authority": GEOMETRY_RETRY_POLICY,
                        "retry_floor_source_eligible": (
                            _capacity_pack_retry_eligible(initial_floor_contract)
                        ),
                    })
                    if retry_required:
                        capacity_stage_counts[
                            "plan_fit_retry_advisory_opportunity"
                        ] += 1
                    retry_eligible = bool(
                        retry_required
                        and _capacity_pack_retry_eligible(initial_floor_contract)
                        and not exact_compile_cap_reached()
                    )
                    if retry_eligible:
                        target_utilization = max(
                            float(capacity_alternative.get("target_utilization") or 0.0),
                            float(capacity_alternative.get("feasible_minimum_utilization") or 0.0),
                        )
                        retried_source = _materialize_once_for_capacity_policy(
                            materialize_capacity_fit,
                            retry_coverage,
                            retry_floor_targets,
                            (
                                float(initial_capacity.get("feasible_capacity_utilization") or 0.0),
                                target_utilization,
                            ),
                        )
                        capacity_plan_fit_evidence["retry_attempted"] = True
                        capacity_plan_fit_evidence["geometry_retry_bypassed"] = False
                        capacity_plan_fit_evidence["geometry_retry_policy"] = (
                            "measured_typed_ast_capacity_composition"
                        )
                        capacity_plan_fit_evidence["retry_authority"] = (
                            "recompiled_geometry_program_ast"
                        )
                        if retried_source is not None:
                            retried_floor_contract, retried_capacity = (
                                _shared_floor_capacity_measurement(
                                    retried_source,
                                    alternative_capacity_contract,
                                    generation_context=generation_context,
                                    capacity_site=capacity_site,
                                    height=candidate_height,
                                    floors=candidate_floors,
                                    pnu=pnu,
                                    trusted_legal_floor_field=trusted_legal_floor_field,
                                    expected_legal_floor_field_hash=(
                                        trusted_legal_floor_field_hash
                                    ),
                                    trusted_clear_span_floor_plan=(
                                        trusted_clear_span_floor_plan
                                    ),
                                )
                            )
                            capacity_plan_fit_evidence["retried_achieved_utilization"] = (
                                retried_capacity.get("feasible_capacity_utilization")
                            )
                            if _capacity_retry_result_is_selectable(
                                retried_floor_contract,
                                retried_capacity,
                                initial_capacity,
                            ):
                                alternative_capacity_contract = (
                                    capacity_contract_with_retry_targets(
                                        alternative_capacity_contract,
                                        retry_floor_targets,
                                    )
                                )
                                source = retried_source
                                capacity_plan_fit_evidence["retry_selected"] = True
                                capacity_stage_counts["typed_capacity_retry_selected"] += 1
                if geometry_stages is not None:
                    geometry_stages["directed_geometry_materialized"] += 1
                if llm_authored_seed:
                    llm_authored_stage_counts["directed_geometry_materialized"] += 1
                if program_dimensional_context:
                    source = replace(source, metadata={
                        **deepcopy(source.metadata),
                        "program_dimensional_context": deepcopy(program_dimensional_context),
                    })
                geometry_payload = source.metadata.get("geometry_program")
                if isinstance(geometry_payload, dict) and geometry_payload.get("nodes"):
                    try:
                        geometry_program = GeometryProgram.from_dict(geometry_payload)
                        geometry_compilation = compile_geometry_program(geometry_program)
                        program_context = {
                            **program_reference_contract(building_type),
                            "program_dimensional_context": dict(program_dimensional_context or {}),
                            "base_capacity_contract": dict(base_capacity_contract or {}),
                            "candidate_capacity_contract": (
                                _compact_candidate_capacity_evidence(
                                    alternative_capacity_contract
                                )
                            ),
                            "site_boundary_source": site_boundary_source,
                            "site_access_context": dict(site_access_context or {}),
                            "site_access_side_in_program_frame": _site_access_side_in_principal_frame(
                                site,
                                site_access_geometry,
                            ),
                            "program_space_zones": deepcopy(source.metadata.get("program_space_zones") or []),
                        }
                        metadata = deepcopy(source.metadata)
                        metadata["program_context"] = program_context
                        metadata["geometry_graph_notes"] = build_geometry_graph_notes(
                            geometry_program,
                            geometry_compilation,
                        )
                        metadata["geometry_graph_snapshot"] = build_geometry_graph_snapshot(
                            geometry_program,
                            geometry_compilation,
                            program_context=program_context,
                        )
                        source = replace(source, metadata=metadata)
                    except (TypeError, ValueError):
                        # Invalid ASTs are rejected by the recursive compiler;
                        # context annotation must never fabricate a fallback.
                        pass
                if generation_context is not None:
                    metadata = deepcopy(source.metadata)
                    legal_evidence = deepcopy(generation_context.evidence)
                    legal_evidence.update({
                        "generation_host_mode": generation_host_mode,
                        "candidate_generation_site_area_m2": round(float(compile_site.area), 3),
                        "requested_program_height_m": candidate_height,
                        "requested_program_floors": candidate_floors,
                        "candidate_floor_count_authority": str(
                            candidate_floor_context.get("authority") or ""
                        ),
                        "legal_floor_field_hash": str(
                            candidate_floor_context.get(
                                "legal_floor_field_hash"
                            )
                            or ""
                        ),
                        "generation_host_section_height_m": (
                            round(
                                float(generation_host_section_height),
                                3,
                            )
                        ),
                    })
                    metadata["legal_generation_context_evidence"] = legal_evidence
                    source = replace(source, metadata=metadata)
                    if (
                        not recursive_directed
                        and base_volume_label == "1/16"
                        and generation_host_mode == "horizontal_buildable_envelope"
                    ):
                        source = fit_source_to_sunlight_field(
                            source,
                            generation_context,
                            height_m=candidate_height,
                            floors=candidate_floors,
                        )
                generation_lineage = _bind_parent_geometry_hash(
                    generation_lineage,
                    compiler_clean_base_geometry_hashes,
                )
                parent_key = str(generation_lineage.get("parent_key") or "")
                parent_audit = (
                    (_reviewed_base_audits or {}).get(parent_key)
                    if str(generation_lineage.get("stage") or "") != "base"
                    else None
                )
                source = _source_with_book_generation_lineage(
                    source,
                    generation_lineage,
                    parent_audit=(
                        parent_audit
                        if isinstance(parent_audit, dict)
                        else None
                    ),
                )
                metadata = deepcopy(source.metadata)
                metadata["base_capacity_contract"] = deepcopy(base_capacity_contract or {})
                metadata["candidate_capacity_contract"] = (
                    _compact_candidate_capacity_evidence(
                        alternative_capacity_contract
                    )
                )
                metadata["candidate_floor_context"] = {
                    key: deepcopy(value)
                    for key, value in candidate_floor_context.items()
                    if key not in {
                        "legal_sections",
                        "upper_legal_section",
                    }
                }
                metadata["capacity_alternative_projection"] = deepcopy(capacity_alternative)
                metadata["capacity_plan_fit_evidence"] = deepcopy(capacity_plan_fit_evidence)
                source = replace(source, metadata=metadata)
                shared_floor_contract: dict[str, Any] | None = None
                if generation_context is not None and capacity_site is not None:
                    bridge = (
                        source.metadata.get("geometry_program_bridge_evidence")
                        if isinstance(
                            source.metadata.get("geometry_program_bridge_evidence"),
                            dict,
                        )
                        else {}
                    )
                    shared_floor_contract = materialize_shared_floor_contract(
                        source,
                        site_local_utm=capacity_site,
                        legal_sections=candidate_legal_sections,
                        height_m=candidate_height,
                        floors=candidate_floors,
                        pnu=pnu,
                        program_hash=str(bridge.get("program_hash") or ""),
                        geometry_hash=str(bridge.get("geometry_hash") or ""),
                        floor_capacity_plan_hash=str(
                            (alternative_capacity_contract or {}).get(
                                "floor_capacity_plan_hash"
                            )
                            or ""
                        ),
                        feasible_capacity_m2=float(
                            (base_capacity_contract or {}).get(
                                "feasible_maximum_floor_area_m2"
                            )
                            or 0.0
                        ),
                    )
                    metadata = deepcopy(source.metadata)
                    metadata["shared_floor_contract"] = shared_floor_contract
                    source = replace(source, metadata=metadata)
                if base_capacity_contract and capacity_site is not None:
                    capacity_stage_counts["measured"] += 1
                    capacity_measurement = measure_source_capacity(
                        source,
                        alternative_capacity_contract,
                        site_local_utm=capacity_site,
                        height_m=candidate_height,
                        floors=candidate_floors,
                        shared_floor_contract=shared_floor_contract,
                    )
                    metadata = deepcopy(source.metadata)
                    metadata["source_capacity_measurement"] = capacity_measurement
                    metadata["capacity_alternative_projection"] = evaluate_capacity_alternative(
                        capacity_alternative,
                        capacity_measurement,
                    )
                    if shared_floor_contract is not None:
                        shared_floor_contract = bind_shared_floor_contract_capacity(
                            shared_floor_contract,
                            metadata["capacity_alternative_projection"],
                        )
                        metadata["shared_floor_contract"] = shared_floor_contract
                    authority_rejection_evidence: list[dict[str, Any]] = []
                    retained_source = _retain_candidate_with_legal_capacity_authority(
                        source,
                        shared_floor_contract,
                        capacity_measurement,
                        alternative_capacity_contract,
                        capacity_projection=metadata[
                            "capacity_alternative_projection"
                        ],
                        rejection_evidence_sink=authority_rejection_evidence,
                    )
                    if retained_source is None:
                        _record_projection_authority_failure(
                            authority_evidence=(
                                authority_rejection_evidence[0]
                                if authority_rejection_evidence
                                else {
                                    "failure_reason": (
                                        "legal_capacity_authority_rejected"
                                    ),
                                    "failure_reasons": [
                                        "legal_capacity_authority_rejected"
                                    ],
                                }
                            ),
                            report_records=terminal_materialization_failures,
                            outcome_graph=outcome_graph,
                            program_slug=outcome_program_slug,
                            source_seed=source_seed_name,
                            program=recursive_program,
                            principle_id=str(principle["principle_id"]),
                            book_scope=base_volume_label,
                            legal_floor_field_hash=str(
                                candidate_floor_context.get(
                                    "legal_floor_field_hash"
                                )
                                or ""
                            ),
                            scope_counts=scope_counts,
                            geometry_stages=geometry_stages,
                            llm_authored_failure_counts=(
                                llm_authored_failure_counts
                            ),
                            stage_outcomes=stage_outcomes,
                        )
                        continue
                    record_stage_outcome(
                        StageOutcome.passed(
                            "projection_authority",
                            evidence=deepcopy(
                                retained_source.metadata.get(
                                    "legal_capacity_authority"
                                ) or {"legal_hard_pass": True}
                            ),
                            value=retained_source,
                        ),
                        records=stage_outcomes,
                    )
                    source = retained_source
                    metadata = deepcopy(source.metadata)
                    capacity_resolution = resolve_capacity_band_evidence(
                        metadata["capacity_alternative_projection"],
                        capacity_measurement=capacity_measurement,
                    )
                    achieved_capacity_band = str(
                        capacity_resolution.get(
                            "resolved_capacity_alternative_id"
                        )
                        or ""
                    )
                    capacity_identity_hash = semantic_capacity_measurement_hash(
                        capacity_measurement,
                        metadata["capacity_alternative_projection"],
                    )
                    semantic_evidence = (
                        metadata.get("program_semantic_carrier_evidence")
                        if isinstance(
                            metadata.get("program_semantic_carrier_evidence"),
                            dict,
                        )
                        else {}
                    )
                    if semantic_evidence.get("status") != "not_required":
                        metadata["program_semantic_carrier_evidence"] = (
                            rebind_semantic_projection_capacity(
                                semantic_evidence,
                                achieved_capacity_band=achieved_capacity_band,
                                capacity_measurement_hash=capacity_identity_hash,
                            )
                        )
                        semantic_context = dict(
                            metadata.get("final_semantic_projection_context")
                            or {}
                        )
                        semantic_context.update({
                            "achieved_capacity_band": achieved_capacity_band,
                            "capacity_measurement_hash": capacity_identity_hash,
                        })
                        metadata["final_semantic_projection_context"] = (
                            semantic_context
                        )
                    source = replace(source, metadata=metadata)
                    if capacity_resolution.get(
                        "resolved_capacity_hard_pass"
                    ) is not True:
                        plates = (
                            shared_floor_contract.get("plates") or ()
                            if isinstance(shared_floor_contract, dict)
                            else ()
                        )
                        achieved_floor_areas = tuple(
                            float(plate.get("gross_area_m2") or 0.0)
                            for plate in plates
                            if isinstance(plate, dict)
                        )
                        bridge = source.metadata.get(
                            "geometry_program_bridge_evidence"
                        ) or {}
                        morphology = _solid_morphology_metrics(source)
                        deficit = _capacity_authoring_deficit(
                            resolved_capacity_hard_pass=False,
                            parent_fingerprint=str(
                                generation_lineage.get("parent_fingerprint")
                                or generation_lineage.get("fingerprint")
                                or ""
                            ),
                            parent_program_hash=str(
                                bridge.get("program_hash") or ""
                            ),
                            geometry_family=str(
                                source.metadata.get("family") or ""
                            ),
                            body_phenotype=str(
                                morphology.get("body_phenotype")
                                or morphology.get("phenotype")
                                or ""
                            ),
                            scope=base_volume_label,
                            capacity_band=achieved_capacity_band,
                            achieved_utilization=capacity_resolution.get(
                                "achieved_capacity_utilization"
                            ),
                            required_utilization=max(
                                float(capacity_resolution.get(
                                    "resolved_capacity_target_utilization"
                                ) or 0.0),
                                float(capacity_resolution.get(
                                    "resolved_capacity_minimum_utilization"
                                ) or 0.0),
                            ),
                            measured_gfa_m2=capacity_measurement.get(
                                "floor_area_m2"
                            ),
                            feasible_gfa_m2=capacity_measurement.get(
                                "feasible_maximum_floor_area_m2"
                            ),
                            achieved_floor_areas_m2=(
                                achieved_floor_areas or None
                            ),
                            target_floor_areas_m2=(
                                alternative_capacity_contract.get(
                                    "target_floor_areas_m2"
                                )
                            ),
                            terminal_materialization_reason="",
                        )
                        if deficit is not None:
                            capacity_authoring_deficits.append(deficit)
                    capacity_stage_counts[
                        f"alternative:{capacity_alternative['alternative_id']}:measured"
                    ] += 1
                    _record_capacity_projection_diagnostics(
                        capacity_stage_counts,
                        alternative_id=str(
                            capacity_alternative["alternative_id"]
                        ),
                        metadata=metadata,
                    )
                    if not capacity_measurement["hard_pass"]:
                        capacity_stage_counts["below_feasible_capacity_floor"] += 1
                        capacity_stage_counts["retained_for_stage_aware_vlm"] += 1
                    else:
                        capacity_stage_counts["hard_passed"] += 1
                compiled += 1
                emit_progress()
                scope_counts["compiled"] += 1
                projection_evidence = source.metadata.get("program_book_projection_evidence") or {}
                projection_outcome = _book_projection_stage_outcome(
                    projection_evidence
                )
                projection_counter_updates = [(scope_counts, (
                    "projection_failed"
                    if projection_outcome.kind == "failed"
                    else "projection_materialized"
                ))]
                if geometry_stages is not None:
                    projection_counter_updates.append((geometry_stages, (
                        "projection_failed"
                        if projection_outcome.kind == "failed"
                        else "projection_materialized"
                    )))
                if llm_authored_seed and projection_outcome.kind == "failed":
                    projection_counter_updates.append((
                        llm_authored_failure_counts,
                        "book_projection_failed",
                    ))
                _record_generation_stage_outcome(
                    projection_outcome,
                    stage_outcomes=stage_outcomes,
                    terminal_records=terminal_materialization_failures,
                    outcome_graph=outcome_graph,
                    program_slug=outcome_program_slug,
                    source_seed=source_seed_name,
                    program=recursive_program,
                    principle_id=str(principle["principle_id"]),
                    book_scope=base_volume_label,
                    legal_floor_field_hash=str(
                        candidate_floor_context.get("legal_floor_field_hash") or ""
                    ),
                    counter_updates=tuple(projection_counter_updates),
                )
                if projection_outcome.kind == "failed":
                    continue
                clean_mass_pass, clean_mass_evidence = _clean_mass_gate(source)
                if not clean_mass_pass:
                    clean_reasons = tuple(
                        clean_mass_evidence.get("failure_reasons")
                        or ("clean_mass_failed",)
                    )
                    clean_counter_updates = []
                    if llm_authored_seed:
                        clean_counter_updates.extend(
                            (llm_authored_failure_counts, f"clean_{reason}")
                            for reason in clean_reasons
                        )
                    if geometry_stages is not None:
                        clean_counter_updates.extend(
                            (geometry_stages, f"clean_failed_{reason}")
                            for reason in clean_reasons
                        )

                    def record_clean_terminal(_outcome: StageOutcome[Any]) -> None:
                        if recursive_program is not None and source_seed_name:
                            _record_clean_mass_rejection(
                                source=source,
                                clean_mass_evidence=clean_mass_evidence,
                                report_records=clean_mass_rejections,
                                outcome_graph=outcome_graph,
                                program_slug=outcome_program_slug,
                                source_seed=source_seed_name,
                                program=recursive_program,
                                principle_id=str(principle["principle_id"]),
                                book_scope=base_volume_label,
                                legal_floor_field_hash=str(
                                    candidate_floor_context.get(
                                        "legal_floor_field_hash"
                                    )
                                    or ""
                                ),
                            )
                        else:
                            clean_mass_rejections.append({
                                "stage": "clean_mass",
                                "evidence": deepcopy(clean_mass_evidence),
                            })

                    record_stage_outcome(
                        StageOutcome.failed(
                            "clean_mass",
                            str(clean_reasons[0]),
                            evidence=clean_mass_evidence,
                        ),
                        records=stage_outcomes,
                        counter_updates=tuple(clean_counter_updates),
                        terminal_recorder=record_clean_terminal,
                    )
                    continue
                clean_counter_updates = []
                if geometry_stages is not None:
                    clean_counter_updates.append(
                        (geometry_stages, "clean_mass_passed")
                    )
                if llm_authored_seed:
                    clean_counter_updates.append(
                        (llm_authored_stage_counts, "clean_mass_passed")
                    )
                record_stage_outcome(
                    StageOutcome.passed(
                        "clean_mass",
                        evidence=clean_mass_evidence,
                        value=source,
                    ),
                    records=stage_outcomes,
                    counter_updates=tuple(clean_counter_updates),
                )
                projection_certificate = (
                    source.metadata.get(
                        "authored_legal_projection_certificate"
                    )
                    if isinstance(source.metadata, dict)
                    else None
                )
                site_containment_passed = (
                    _inside_floorwise_legal_sections(
                        source,
                        candidate_legal_sections,
                    )
                    if (
                        recursive_directed
                        and isinstance(projection_certificate, dict)
                        and projection_certificate.get("hard_pass") is True
                    )
                    else _inside_site(source, compile_site)
                )
                containment_outcome = _site_containment_stage_outcome(
                    site_containment_passed
                )
                containment_counter_updates = []
                if containment_outcome.kind == "failed":
                    if llm_authored_seed:
                        containment_counter_updates.append((
                            llm_authored_failure_counts,
                            "containment_failed",
                        ))
                    if geometry_stages is not None:
                        containment_counter_updates.append((
                            geometry_stages,
                            "containment_failed",
                        ))
                else:
                    containment_counter_updates.append((scope_counts, "clean"))
                _record_generation_stage_outcome(
                    containment_outcome,
                    stage_outcomes=stage_outcomes,
                    terminal_records=terminal_materialization_failures,
                    outcome_graph=outcome_graph,
                    program_slug=outcome_program_slug,
                    source_seed=source_seed_name,
                    program=recursive_program,
                    principle_id=str(principle["principle_id"]),
                    book_scope=base_volume_label,
                    legal_floor_field_hash=str(
                        candidate_floor_context.get("legal_floor_field_hash") or ""
                    ),
                    counter_updates=tuple(containment_counter_updates),
                )
                if containment_outcome.kind == "failed":
                    continue
                archive_rejection_evidence: list[dict[str, Any]] = []
                archived_record = _admit_legal_mass_candidate(
                    legal_mass_archive,
                    source,
                    compiler_clean_passed=clean_mass_pass,
                    site_containment_passed=site_containment_passed,
                    rejection_evidence_sink=archive_rejection_evidence,
                )
                archive_failure = (
                    archive_rejection_evidence[0]
                    if archive_rejection_evidence
                    else {}
                )
                archive_outcome = _legal_archive_stage_outcome(
                    archived_record,
                    reason=str(
                        archive_failure.get("failure_reason")
                        or "legal_archive_admission_failed"
                    ),
                    evidence=archive_failure or {"archive_admitted": True},
                )
                _record_generation_stage_outcome(
                    archive_outcome,
                    stage_outcomes=stage_outcomes,
                    terminal_records=terminal_materialization_failures,
                    outcome_graph=outcome_graph,
                    program_slug=outcome_program_slug,
                    source_seed=source_seed_name,
                    program=recursive_program,
                    principle_id=str(principle["principle_id"]),
                    book_scope=base_volume_label,
                    legal_floor_field_hash=str(
                        candidate_floor_context.get("legal_floor_field_hash") or ""
                    ),
                )
                clean += 1
                # A BOOK descendant is allowed to repair its base parent's
                # program relation.  Its causal parent therefore needs to be
                # compiler-clean and contained, not already a final
                # program-hard-pass design.  Record this before the program
                # gate and carry it across QD compaction.
                if str(generation_lineage.get("stage") or "") == "base":
                    base_key = str(generation_lineage.get("parent_key") or "")
                    if base_key and isinstance(archived_record, dict):
                        _observe_compiler_clean_base_geometry_hash(
                            compiler_clean_base_geometry_hashes,
                            base_key,
                            str(
                                archived_record.get("geometry_hash") or ""
                            ),
                        )
                if (
                    llm_book_path_contract is not None
                    and str(principle.get("principle_id") or "")
                    != str(
                        llm_book_path_contract.get("principle_id") or ""
                    )
                ):
                    # A combination/aggregation/case-study path may require
                    # its base operative to be compiled and certified first.
                    # That base is causal execution evidence, not a second
                    # LLM-authored design choice and must never enter final
                    # selection as if the author selected two paths.
                    capacity_stage_counts[
                        "causal_book_path_intermediate_certified"
                    ] += 1
                    _finish_replenishment_work_disposition(
                        active_work_disposition,
                        terminal_stage="causal_path_intermediate",
                        terminal_reason="certified_not_selection_eligible",
                    )
                    continue
                capacity_stage_counts[
                    f"alternative:{capacity_alternative['alternative_id']}:clean_passed"
                ] += 1
                feature = source_feature(
                    source,
                    sequence,
                    building_type=building_type,
                    height=candidate_height,
                    floors=candidate_floors,
                    site_area=float(compile_site.area),
                    surface_materialization="summary_only",
                )
                props = feature.setdefault("properties", {})
                props["site_boundary_geometry"] = mapping(site)
                props["site_boundary_source"] = site_boundary_source
                props["site_access_context"] = dict(site_access_context or {})
                props["site_access_geometry"] = site_access_geometry
                props["program_context"] = {
                    **program_reference_contract(building_type),
                    "program_dimensional_context": dict(program_dimensional_context or {}),
                    "base_capacity_contract": dict(base_capacity_contract or {}),
                    "candidate_capacity_contract": (
                        _compact_candidate_capacity_evidence(
                            alternative_capacity_contract
                        )
                    ),
                    "site_boundary_source": site_boundary_source,
                    "site_access_context": dict(site_access_context or {}),
                    "site_access_side_in_program_frame": _site_access_side_in_principal_frame(
                        site,
                        site_access_geometry,
                    ),
                    "program_space_zones": deepcopy(source.metadata.get("program_space_zones") or []),
                }
                # These records are immutable evidence already owned by this
                # candidate's SourceMass. Sharing them avoids a second deep
                # object graph per heavy candidate while preserving exact AST
                # identity for render/VLM/selector consumers.
                props["geometry_program"] = source.metadata.get("geometry_program") or {}
                props["geometry_graph_notes"] = source.metadata.get("geometry_graph_notes") or []
                props["geometry_graph_snapshot"] = source.metadata.get("geometry_graph_snapshot") or {}
                props["book_generation_lineage"] = deepcopy(generation_lineage)
                props["base_capacity_contract"] = deepcopy(base_capacity_contract or {})
                props["candidate_capacity_contract"] = (
                    _compact_candidate_capacity_evidence(
                        alternative_capacity_contract
                    )
                )
                props["candidate_floor_context"] = deepcopy(
                    source.metadata.get("candidate_floor_context") or {}
                )
                props["source_capacity_measurement"] = deepcopy(capacity_measurement)
                props["capacity_alternative_projection"] = deepcopy(
                    source.metadata.get("capacity_alternative_projection") or {}
                )
                program = attach_program_massing_evidence(feature, building_type=building_type)
                spatial = feature["properties"]["program_spatial_evidence"]
                program_form_gate = _program_form_gate(source, building_type)
                feature["properties"]["program_form_gate"] = program_form_gate
                gate_pass = {
                    "role_coverage": bool(all(spatial.get("required_role_hits") or ())),
                    "dominant_ratio": float(spatial.get("dominant_ratio_score") or 0.0) >= 0.55,
                    "site_coverage": float(spatial.get("site_coverage_score") or 0.0) >= 0.55,
                    "hierarchy": float(spatial.get("hierarchy_score") or 0.0) >= 0.50,
                    "coherence": bool((feature["properties"].get("source_signature", {}).get("coherence_evidence") or {}).get("hard_pass", False)),
                    "program_form": bool(program_form_gate["hard_pass"]),
                }
                program_gate_result = _program_gate_result(
                    program_evidence=program,
                    program_form_gate=program_form_gate,
                    gate_pass=gate_pass,
                )
                failed_gates = tuple(program_gate_result["failed_gates"])
                combined_program_hard_pass = bool(program_gate_result["hard_pass"])
                coherence_evidence = (
                    feature["properties"].get("source_signature", {}).get("coherence_evidence") or {}
                )
                program_review_authority = _program_review_authority(
                    archived_record=archived_record,
                    program_gate_result=program_gate_result,
                    coherence_evidence=coherence_evidence,
                )
                feature["properties"]["program_gate_result"] = deepcopy(
                    program_gate_result
                )
                feature["properties"]["program_review_authority"] = deepcopy(
                    program_review_authority
                )
                source = replace(
                    source,
                    metadata={
                        **source.metadata,
                        "program_gate_result": deepcopy(program_gate_result),
                        "program_review_authority": deepcopy(
                            program_review_authority
                        ),
                        # The portfolio quota needs an axis that is visible in
                        # the delivered building. This is the measured ground
                        # take - 건축면적 over the lawful capacity - read back
                        # onto the same axis the candidate was authored along,
                        # so a mass that asked to disperse and came out filling
                        # the ground counts as full ground.
                        "delivered_ground_take": {
                            "schema_version": (
                                "arr.maas.delivered_ground_take.v1"
                            ),
                            # 건축면적 is the horizontal projection of the
                            # whole building (건축법 시행령 제119조 제1항
                            # 제2호), which is the union over every height -
                            # not the ground plate. A mass whose ground floor
                            # takes 45% while its upper floors overhang to the
                            # cap covers the full ground, and keying the axis
                            # on the plate would file it under "dispersed".
                            # This is the same quantity the coverage hard gate
                            # enforces.
                            "ratio": round(
                                float(
                                    spatial.get(
                                        "all_height_projected_plan_union_ratio"
                                    )
                                    or 0.0
                                ),
                                4,
                            ),
                            "band_id": delivered_ground_take_band(
                                spatial.get(
                                    "all_height_projected_plan_union_ratio"
                                )
                                or 0.0
                            ).band_id,
                            "ground_plate_ratio": round(
                                float(
                                    spatial.get("site_coverage_ratio") or 0.0
                                ),
                                4,
                            ),
                            "measured_against": str(
                                spatial.get("coverage_measurement_mode") or ""
                            ),
                            "lawful_ground_capacity_m2": float(
                                spatial.get("lawful_ground_capacity_m2") or 0.0
                            ),
                        },
                        # Solid or void is the other axis an architect chooses
                        # along, and it was pure loss here: a court cost floor
                        # area and nothing scored it, so a scheme with one always
                        # lost to the same scheme without. Read as a position it
                        # stops competing with its own absence.
                        "delivered_void": {
                            "schema_version": "arr.maas.delivered_void.v1",
                            "ratio": round(
                                float(
                                    (
                                        spatial.get("spatial_role_projection")
                                        or {}
                                    ).get("plan_void_ratio")
                                    or 0.0
                                ),
                                4,
                            ),
                            "band_id": delivered_void_band(
                                (
                                    spatial.get("spatial_role_projection") or {}
                                ).get("plan_void_ratio")
                                or 0.0
                            ).band_id,
                            "measured_as": "open_share_of_minimum_rotated_rectangle",
                        },
                    },
                )
                _record_gate_diagnostic(
                    gate_diagnostics[base_volume_label],
                    spatial=spatial,
                    hard_pass=combined_program_hard_pass,
                    failed_gates=failed_gates,
                    program_form_failures=tuple(program_form_gate.get("failures") or ()),
                    coherence_evidence=coherence_evidence,
                )
                geometry_family = str(source.metadata.get("family") or "") if source.metadata.get("geometry_program_bridge_evidence") else ""
                if geometry_family:
                    _record_gate_diagnostic(
                        geometry_gate_diagnostics.setdefault(geometry_family, _empty_gate_diagnostic()),
                        spatial=spatial,
                        hard_pass=combined_program_hard_pass,
                        failed_gates=failed_gates,
                        program_form_failures=tuple(program_form_gate.get("failures") or ()),
                        coherence_evidence=coherence_evidence,
                    )
                    if outcome_graph is not None:
                        outcome_graph.observe_program_evaluation(
                            program_slug=next(
                                (slug for slug, label, _height, _floors in PROGRAMS if label == building_type),
                                str(building_type),
                            ),
                            source=source,
                            sequence_name=sequence.name,
                            principle_id=str(principle["principle_id"]),
                            spatial=spatial,
                            failed_gates=failed_gates,
                            program_hard_pass=combined_program_hard_pass,
                            program_evidence=program,
                        )
                program_outcome = _program_review_stage_outcome(
                    program_review_authority
                )
                program_counter_updates = []
                if program_outcome.kind == "failed" and llm_authored_seed:
                    program_counter_updates.extend(
                        (llm_authored_failure_counts, f"program_{name}")
                        for name in failed_gates
                    )
                elif program_outcome.kind == "diagnostic":
                    program_counter_updates.append((
                        scope_counts,
                        "program_development_review_eligible",
                    ))
                elif program_outcome.kind == "passed":
                    program_counter_updates.append((
                        scope_counts,
                        "program_passed",
                    ))
                _record_generation_stage_outcome(
                    program_outcome,
                    stage_outcomes=stage_outcomes,
                    terminal_records=terminal_materialization_failures,
                    outcome_graph=outcome_graph,
                    program_slug=outcome_program_slug,
                    source_seed=source_seed_name,
                    program=recursive_program,
                    principle_id=str(principle["principle_id"]),
                    book_scope=base_volume_label,
                    legal_floor_field_hash=str(
                        candidate_floor_context.get("legal_floor_field_hash") or ""
                    ),
                    counter_updates=tuple(program_counter_updates),
                )
                if program_outcome.kind == "failed":
                    if llm_authored_seed:
                        logger.info(
                            "Rejecting LLM-authored program hard gate: "
                            "failed_gates=%s coherence=%s program_form=%s",
                            failed_gates,
                            deepcopy(coherence_evidence),
                            deepcopy(program_form_gate),
                        )
                    continue
                program_passed_increment = int(
                    program_outcome.kind == "passed"
                )
                if program_passed_increment:
                    program_passed += program_passed_increment
                    capacity_stage_counts[
                        f"alternative:{capacity_alternative['alternative_id']}:program_passed"
                    ] += 1
                    if geometry_stages is not None:
                        geometry_stages["program_hard_passed"] += 1
                    if llm_authored_seed:
                        llm_authored_stage_counts["program_hard_passed"] += 1
                elif program_review_authority["development_review_eligible"]:
                    capacity_stage_counts[
                        "program_development_review_eligible"
                    ] += 1
                if capacity_measurement:
                    capacity_projection = (
                        source.metadata.get("capacity_alternative_projection")
                        if isinstance(source.metadata, dict)
                        else {}
                    ) or {}
                    if (
                        isinstance(shared_floor_contract, dict)
                        and shared_floor_contract.get("hard_pass") is True
                    ):
                        floor_hard_capacity_utilizations.append(
                            float(
                                capacity_measurement.get(
                                    "feasible_capacity_utilization"
                                )
                                or 0.0
                            )
                        )
                    if capacity_projection.get("target_hard_pass") is True:
                        if (
                            isinstance(shared_floor_contract, dict)
                            and shared_floor_contract.get("hard_pass") is True
                        ):
                            capacity_stage_counts[
                                "capacity_target_and_floor_contract_passed"
                            ] += 1
                        else:
                            capacity_stage_counts[
                                "capacity_target_passed_floor_contract_failed"
                            ] += 1
                            capacity_target_floor_failure_counts.update(
                                shared_floor_contract.get("failure_reasons") or ()
                                if isinstance(shared_floor_contract, dict)
                                else ("missing_shared_floor_contract",)
                            )
                    if capacity_projection.get(
                        "selectable_capacity_hard_pass"
                    ) is True and (
                        isinstance(shared_floor_contract, dict)
                        and shared_floor_contract.get("hard_pass") is True
                    ):
                        capacity_stage_counts[
                            "capacity_selectable_and_floor_contract_passed"
                        ] += 1
                    capacity_score = capacity_fit_score(
                        capacity_alternative,
                        capacity_measurement,
                    )
                    capacity_plan_fit_evidence[
                        "advisory_capacity_fit_score"
                    ] = capacity_score
                    score = _mass_stage_design_score(
                        program_fit_score=float(program["program_fit_score"]),
                        architectural_score=float(
                            spatial["architectural_score"]
                        ),
                        advisory_capacity_score=capacity_score,
                    )
                else:
                    score = _mass_stage_design_score(
                        program_fit_score=float(program["program_fit_score"]),
                        architectural_score=float(
                            spatial["architectural_score"]
                        ),
                    )
                bridge = source.metadata.get("geometry_program_bridge_evidence") or {}
                fit_strength = float(bridge.get("legal_fit_strength") or 0.0) if isinstance(bridge, dict) else 0.0
                # Selection must not reward a legal interpolation that erases
                # the AST's section language. Hard gates already decide legal
                # validity; this small tie-break preserves design geometry.
                score -= fit_strength * 0.10
                accepted_archive.append(_Candidate(
                    str(principle["principle_id"]),
                    str(principle["kind"]),
                    str(principle["label"]),
                    sequence,
                    source,
                    feature,
                    round(score, 6),
                ))
                _finish_replenishment_work_disposition(
                    active_work_disposition,
                    terminal_stage="program_release",
                    terminal_reason=(
                        "program_hard_pass"
                        if program_outcome.kind == "passed"
                        else "development_review_eligible"
                    ),
                )
                if early_stop_target and _eligible_smoke_floor_candidate(
                    source,
                    shared_floor_contract,
                    capacity_measurement,
                    capacity_projection,
                    certified_archived_base_keys(),
                ):
                    smoke_floor_pass_candidates += 1
                emit_progress()
    accepted = accepted_archive.finalize()
    _finalize_replenishment_work_dispositions(
        replenishment_work_evidence,
        terminal_records=terminal_materialization_failures,
    )
    capacity_stage_counts["qd_stream_compaction_count"] += accepted_archive.compaction_count
    capacity_stage_counts["qd_stream_candidates_released"] += accepted_archive.released_count
    capacity_stage_counts["qd_stream_peak_candidate_count"] = accepted_archive.peak_candidate_count
    accepted, lineage_gate = gate_descendants_by_base(
        accepted,
        known_viable_base_keys=certified_archived_base_keys(),
        require_known_viable_base_keys=True,
    )
    if candidate_cap:
        accepted = accepted[:candidate_cap]
    active_universal_programs = universal_form_program_pages(requested_parent_indices)
    summarized_gate_diagnostics = {
        label: _summarize_gate_diagnostic(diagnostic)
        for label, diagnostic in gate_diagnostics.items()
    }
    return accepted, {
        "_runtime_directed_seeds": directed_seeds,
        "_runtime_parent_seeds": parent_seeds,
        "generation_phase": _generation_phase,
        "descendant_parent_authorization": deepcopy(
            descendant_parent_authorization
        ),
        "replenishment_work_disposition": deepcopy(
            replenishment_work_evidence
        ),
        "evaluated": evaluated,
        "compiled": compiled,
        "clean": clean,
        "program_passed": program_passed,
        "legal_mass_archive": legal_mass_archive.evidence(),
        "diagnostic_generation_budget": {
            "active": bool(
                explicit_diagnostic_budget
            ),
            "scope_labels": list(diagnostic_scope_labels),
            "book_probe_count": book_probe_count,
            "evaluation_cap": (
                max(0, int(diagnostic_evaluation_cap or 0))
            ),
            "candidate_cap": (
                max(0, int(diagnostic_candidate_cap or 0))
            ),
        },
        "competition_breadth_generation_budget": {
            "active": bool(competition_breadth_budget),
            "activation_authority": (
                "portfolio_contract_full_target_20_non_smoke"
                if competition_breadth_budget else "inactive"
            ),
            "target_count": 20 if competition_breadth_budget else 0,
            "scope_labels": list(scope_schedule_labels)
            if competition_breadth_budget else [],
            "book_probe_count": book_probe_count
            if competition_breadth_budget else 0,
            "cheap_evaluation_limit": evaluation_cap
            if competition_breadth_budget else 0,
            "exact_shortlist_minimum": int(
                competition_breadth_budget.get(
                    "exact_shortlist_minimum"
                )
                or 0
            ),
            "exact_shortlist_maximum": candidate_cap
            if competition_breadth_budget else 0,
            "historical_36_cap_bypassed": bool(
                competition_breadth_budget and evaluation_cap > 36
            ),
            "cheap_screen": (
                competition_cheap_schedule.evidence()
                if competition_cheap_schedule is not None
                else {}
            ),
            "pre_exact_selected_keys": sorted(
                competition_exact_keys
            ),
            "base_runway_anchor_count": len(
                competition_base_anchor_keys
            ),
            "language_runway_anchor_count": len(
                competition_language_anchor_keys
            ),
        },
        "phase_durations_seconds": {
            "breadth_enumeration": max(
                breadth_enumeration_duration,
                1e-9,
            ),
            "cheap_screen": max(cheap_screen_duration, 1e-9),
            "exact_compile": max(
                perf_counter() - exact_compile_started,
                1e-9,
            ),
        },
        "hard_acceptance_early_stop": {
            "active": bool(early_stop_target),
            "target": early_stop_target,
            "requested_target": requested_early_stop_target,
            "disabled_reason": "" if early_stop_target else "not_requested",
            "observed_hard_acceptance_candidates": smoke_floor_pass_candidates,
            "stopped_early": bool(
                early_stop_target
                and smoke_floor_pass_candidates >= early_stop_target
            ),
        },
        "capacity_floor_intersection": {
            "target_and_floor_hard_pass_count": int(
                capacity_stage_counts.get(
                    "capacity_target_and_floor_contract_passed",
                    0,
                )
            ),
            "target_pass_floor_failure_reason_counts": dict(
                capacity_target_floor_failure_counts
            ),
            "floor_hard_candidate_count": len(floor_hard_capacity_utilizations),
            "maximum_floor_hard_capacity_utilization": round(
                max(floor_hard_capacity_utilizations, default=0.0),
                6,
            ),
        },
        "base_role_seed_count": len(program_seed_sequences(building_type)),
        "agent_mutated_seed_count": max(0, len(directed_seeds) - len(program_seed_sequences(building_type))),
        "recursive_geometry_seed_count": sum(
            any(
                note.startswith(("geometry_program_directive=", "geometry_program_payload="))
                for note in seed.notes
            )
            for seed in directed_seeds
        ),
        "geometry_synthesis_request_source": (
            "universal_form_bank_control+vlm_or_session_directive"
            if synthesis_requests
            else "universal_form_bank_control"
        ),
        "geometry_synthesis_request_count": (
            1
            + len(tuple(record for record in (synthesis_requests or ()) if isinstance(record, dict)))
        ),
        "geometry_synthesis_request_diagnostics": [
            {
                "source_seed": str(record.get("source_seed") or ""),
                "live_llm_author": bool(record.get("live_llm_author")),
                "llm_author_only": bool(record.get("llm_author_only")),
                "llm_author_count": int(record.get("llm_author_count") or 0),
                "intent_tags": list(record.get("intent_tags") or ()),
            }
            for record in (synthesis_requests or ())
            if isinstance(record, dict)
        ],
        "universal_form_bank": {
            "program_conditioned": False,
            "variation_pages": list(requested_parent_indices),
            "form_program_count": len(active_universal_programs),
            "role_carrier_count": min(2, len(program_seed_sequences(building_type))),
            "dominant_form_seed_count": (
                len(active_universal_programs)
                * min(2, len(program_seed_sequences(building_type)))
            ),
            "prebook_live_vlm_author_active": False,
            "program_projection_and_vlm_are_downstream": True,
        },
        "geometry_program_vlm_status_counts": dict(sorted(Counter(
            note.split("=", 1)[1]
            for seed in directed_seeds
            for note in seed.notes
            if note.startswith("geometry_program_vlm_status=")
        ).items())),
        "llm_author_request_outcomes": [
            outcome.to_dict() for outcome in author_request_outcomes
        ],
        "geometry_program_llm_author_status_counts": dict(sorted(Counter(
            note.split("=", 1)[1]
            for seed in directed_seeds
            for note in seed.notes
            if note.startswith("geometry_program_llm_author_status=")
        ).items())),
        "base_book_vlm_feedback_count": max(
            [outcome.base_feedback_count for outcome in author_request_outcomes]
            or [
                int(note.split("=", 1)[1])
                for seed in directed_seeds
                for note in seed.notes
                if note.startswith(
                    "geometry_program_base_book_vlm_feedback_count="
                )
            ],
            default=0,
        ),
        "base_book_vlm_feedback_in_author_context": (
            any(outcome.base_feedback_count > 0 for outcome in author_request_outcomes)
            if author_request_outcomes
            else any(
                note == (
                    "geometry_program_base_book_vlm_feedback_in_author_context=True"
                )
                for seed in directed_seeds
                for note in seed.notes
            )
        ),
        "authored_visual_authority_feedback_count": max(
            [outcome.feedback_count for outcome in author_request_outcomes]
            or [
                int(note.split("=", 1)[1])
                for seed in directed_seeds
                for note in seed.notes
                if note.startswith(
                    "geometry_program_authored_visual_authority_feedback_count="
                )
            ],
            default=0,
        ),
        "authored_visual_authority_feedback_in_author_context": (
            any(outcome.feedback_count > 0 for outcome in author_request_outcomes)
            if author_request_outcomes
            else any(
                note == (
                    "geometry_program_authored_visual_authority_feedback_in_author_context=True"
                )
                for seed in directed_seeds
                for note in seed.notes
            )
        ),
        "llm_author_request_executed": (
            any(
                outcome.provider_request_executed
                for outcome in author_request_outcomes
            )
            if author_request_outcomes
            else any(
                note == "geometry_program_llm_author_request_executed=True"
                for seed in directed_seeds
                for note in seed.notes
            )
        ),
        "llm_author_valid_program_count": sum(
            outcome.valid_authored_program_count
            for outcome in author_request_outcomes
        ),
        "llm_author_cache_hit_count": sum(
            outcome.cache_hit_count for outcome in author_request_outcomes
        ),
        "geometry_program_llm_author_budget_failures": [
            json.loads(payload)
            for payload in sorted({
                note.split("=", 1)[1]
                for seed in directed_seeds
                for note in seed.notes
                if note.startswith(
                    "geometry_program_llm_author_budget_failure="
                ) and note.split("=", 1)[1]
            })
        ],
        "geometry_program_llm_author_active_seed_count": sum(
            note == "geometry_program_llm_author_active=True"
            for seed in directed_seeds
            for note in seed.notes
        ),
        "geometry_program_prebook_vlm_quarantined_seed_count": sum(
            note == "geometry_program_prebook_vlm_quarantined=True"
            for seed in directed_seeds
            for note in seed.notes
        ),
        "geometry_program_llm_author_stage_counts": dict(sorted(llm_authored_stage_counts.items())),
        "geometry_program_llm_author_failure_counts": dict(sorted(llm_authored_failure_counts.items())),
        "geometry_program_vlm_causal_trace": {
            "maximum_reference_count": max((
                int(note.split("=", 1)[1])
                for seed in directed_seeds for note in seed.notes
                if note.startswith("geometry_program_vlm_reference_count=")
            ), default=0),
            "maximum_memory_observation_count": max((
                int(note.split("=", 1)[1])
                for seed in directed_seeds for note in seed.notes
                if note.startswith("geometry_program_vlm_memory_observation_count=")
            ), default=0),
            "geometry_revision_count": max((
                int(note.split("=", 1)[1])
                for seed in directed_seeds for note in seed.notes
                if note.startswith("geometry_program_vlm_revision_count=")
            ), default=0),
        },
        "base_capacity_contract": deepcopy(base_capacity_contract or {}),
        "legal_fit_deficits": deepcopy(legal_fit_deficits),
        "terminal_materialization_failures": deepcopy(
            terminal_materialization_failures
        ),
        "clean_mass_rejections": deepcopy(clean_mass_rejections),
        "stage_outcomes": deepcopy(stage_outcomes),
        "capacity_authoring_deficits": deepcopy(
            capacity_authoring_deficits[-24:]
        ),
        "geometry_retry_policy": GEOMETRY_RETRY_POLICY,
        "exact_compile_invocation_count": (
            materialization_diagnostics.materialization_invocation_count
        ),
        "exact_compile_limit": compile_limit,
        "exact_compile_remaining": (
            None
            if compile_limit is None
            else max(
                0,
                compile_limit
                - materialization_diagnostics.materialization_invocation_count,
            )
        ),
        "exact_compile_stop_reason": (
            "cumulative_exact_compile_budget_exhausted"
            if exact_compile_cap_reached()
            else ""
        ),
        **materialization_diagnostics.metadata(legal_fit_deficits),
        "capacity_stage_counts": dict(sorted(capacity_stage_counts.items())),
        "book_lineage_gate": lineage_gate,
        "program_passed_by_seed_family": dict(sorted(Counter(
            _seed_family(candidate)
            for candidate in accepted
            if (candidate.source.metadata.get("program_gate_result") or {}).get("hard_pass") is True
        ).items())),
        "program_passed_by_section_family": dict(sorted(Counter(
            _section_family(candidate)
            for candidate in accepted
            if (candidate.source.metadata.get("program_gate_result") or {}).get("hard_pass") is True
        ).items())),
        "scope_stage_counts": scope_stage_counts,
        "program_gate_diagnostics_by_scope": summarized_gate_diagnostics,
        "program_gate_diagnostics_by_recursive_geometry_family": {
            family: _summarize_gate_diagnostic(diagnostic)
            for family, diagnostic in sorted(geometry_gate_diagnostics.items())
        },
        "recursive_geometry_stage_counts": dict(sorted(geometry_stage_counts.items())),
        "program_gate_diagnostics_total": _merge_gate_diagnostics(summarized_gate_diagnostics),
    }


def _reviewed_archived_base_registry(
    reviewed_bases: list[_Candidate],
) -> dict[str, str | None]:
    """Bind only unique archived final hashes carrying an actual BASE review."""

    registry: dict[str, str | None] = {}
    for candidate in reviewed_bases:
        metadata = candidate.source.metadata
        lineage = metadata.get("book_generation_lineage") or {}
        authority = metadata.get("program_review_authority") or {}
        program_gate_result = metadata.get("program_gate_result") or {}
        audit = metadata.get("base_book_vlm_audit") or {}
        parent_key = str(lineage.get("parent_key") or "")
        final_hash = str(metadata.get("final_geometry_hash") or "")
        final_program_hash = str(metadata.get("final_program_hash") or "")
        final_surface_payload_hash = str(
            metadata.get("final_surface_payload_hash") or ""
        )
        base_review_fingerprint = (
            hashlib.sha256(
                json.dumps(
                    {"geometry_hash": final_hash},
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if final_hash
            else ""
        )
        explicit_parking = tuple(
            value for value in (
                metadata.get("parking_hard_gate"),
                metadata.get("parking_compliance"),
            )
            if isinstance(value, dict)
        )
        certificate = metadata.get("authored_legal_projection_certificate")
        certificate = certificate if isinstance(certificate, dict) else {}
        legal_authority = metadata.get("legal_capacity_authority")
        legal_authority = (
            legal_authority if isinstance(legal_authority, dict) else {}
        )
        selectable_release = bool(
            isinstance(program_gate_result, dict)
            and program_gate_result.get("hard_pass") is True
            and authority.get("selection_eligible") is True
        )
        development_release = bool(
            authority.get("development_review_eligible") is True
            and certificate.get("schema_version")
            == "arr.maas.authored_legal_projection_certificate.v1"
            and certificate.get("status") == "verified"
            and certificate.get("hard_pass") is True
            and final_program_hash
            and str(certificate.get("input_authored_program_hash") or "")
            == final_program_hash
            and str(certificate.get("projected_surface_hash") or "")
            == final_hash
            and final_surface_payload_hash
            and str(certificate.get("projected_surface_payload_hash") or "")
            == final_surface_payload_hash
            and legal_authority.get("legal_hard_pass") is True
            and str(audit.get("geometry_hash") or "") == final_hash
            and str(audit.get("program_hash") or "") == final_program_hash
            and str(audit.get("base_review_fingerprint") or "")
            == base_review_fingerprint
        )
        if not (
            str(lineage.get("stage") or "") == "base"
            and isinstance(authority, dict)
            and authority.get("legal_archive_authority") is True
            and (selectable_release or development_release)
            and isinstance(audit, dict)
            and str(audit.get("response_id") or "")
            and str(audit.get("review_stage") or "") == "book_base_operative"
            and audit.get("reviewed_exact_post_book_geometry") is True
            and audit.get("descendant_development_hard_pass") is True
            and not any(
                record.get("hard_pass") is False
                for record in explicit_parking
            )
            and parent_key
            and final_hash
        ):
            continue
        _observe_compiler_clean_base_geometry_hash(
            registry,
            parent_key,
            final_hash,
        )
    return registry


def _reviewed_base_development_audits(
    reviewed_bases: list[_Candidate],
    registry: dict[str, str | None],
) -> dict[str, dict[str, Any]]:
    audits: dict[str, dict[str, Any]] = {}
    for candidate in reviewed_bases:
        metadata = candidate.source.metadata
        lineage = metadata.get("book_generation_lineage") or {}
        parent_key = str(lineage.get("parent_key") or "")
        audit = metadata.get("base_book_vlm_audit") or {}
        final_geometry_hash = str(metadata.get("final_geometry_hash") or "")
        final_program_hash = str(metadata.get("final_program_hash") or "")
        expected_fingerprint = (
            hashlib.sha256(
                json.dumps(
                    {"geometry_hash": final_geometry_hash},
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if final_geometry_hash
            else ""
        )
        if (
            canonical_lineage_parent_key(lineage) == parent_key
            and isinstance(registry.get(parent_key), str)
            and registry.get(parent_key)
            == final_geometry_hash
            and isinstance(audit, dict)
            and audit.get("descendant_development_hard_pass") is True
            and str(audit.get("geometry_hash") or "")
            == final_geometry_hash
            and final_program_hash
            and str(audit.get("program_hash") or "")
            == final_program_hash
            and str(audit.get("base_review_fingerprint") or "")
            == expected_fingerprint
        ):
            audits[parent_key] = deepcopy(audit)
    return audits


def _exact_canonical_reviewed_parent_keys(
    reviewed_bases: list[_Candidate],
    registry: dict[str, str | None],
    reviewed_base_audits: dict[str, dict[str, Any]],
) -> set[str]:
    keys: set[str] = set()
    for candidate in reviewed_bases:
        source = getattr(candidate, "source", None)
        metadata = getattr(source, "metadata", None)
        if not isinstance(metadata, dict):
            continue
        lineage = metadata.get("book_generation_lineage") or {}
        parent_key = canonical_lineage_parent_key(lineage)
        if not parent_key:
            continue
        authorized, _reason = _authorize_descendant_lineage_for_materialization(
            lineage,
            registry,
            reviewed_base_audits,
        )
        if authorized is None:
            continue
        audit = reviewed_base_audits[parent_key]
        if str(audit.get("program_hash") or "") != str(
            metadata.get("final_program_hash") or ""
        ):
            continue
        keys.add(parent_key)
    return keys


@dataclass(frozen=True)
class CertifiedReviewedBaseParent:
    parent_key: str
    source_seed: str
    geometry_hash: str
    program_hash: str
    base_review_fingerprint: str
    sequence_payload: str
    sequence_hash: str
    candidate: Any

    def parent_seed(self) -> VerbSequence:
        payload = json.loads(self.sequence_payload)
        return VerbSequence(
            name=str(payload["name"]),
            label=str(payload["label"]),
            calls=tuple(
                VerbCall(
                    verb=str(call["verb"]),
                    params=deepcopy(call.get("params") or {}),
                )
                for call in payload["calls"]
            ),
            notes=tuple(str(note) for note in payload.get("notes") or ()),
        )


def _certified_reviewed_base_parent_records(
    reviewed_bases: list[Any],
    parent_seeds: tuple[VerbSequence, ...] | list[VerbSequence],
) -> tuple[CertifiedReviewedBaseParent, ...]:
    isolated_bases = deepcopy(list(reviewed_bases or ()))
    isolated_seeds = deepcopy(tuple(parent_seeds or ()))
    registry = _reviewed_archived_base_registry(isolated_bases)
    audits = _reviewed_base_development_audits(isolated_bases, registry)
    exact_keys = _exact_canonical_reviewed_parent_keys(
        isolated_bases,
        registry,
        audits,
    )
    seed_bindings: dict[str, dict[str, tuple[str, VerbSequence]]] = {}
    for seed in isolated_seeds:
        payload = json.dumps(
            {
                "name": seed.name,
                "label": seed.label,
                "calls": seed.to_list(),
                "notes": list(seed.notes),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        seed_bindings.setdefault(seed.name, {})[digest] = (payload, seed)
    conflicting_seed_names = {
        name for name, bindings in seed_bindings.items()
        if len(bindings) != 1
    }
    records_by_key: dict[str, list[CertifiedReviewedBaseParent]] = {}
    for candidate in isolated_bases:
        metadata = getattr(getattr(candidate, "source", None), "metadata", None)
        if not isinstance(metadata, dict):
            continue
        lineage = metadata.get("book_generation_lineage") or {}
        parent_key = str(lineage.get("parent_key") or "")
        source_seed = str(lineage.get("source_seed") or "")
        bindings = seed_bindings.get(source_seed) or {}
        if (
            parent_key not in exact_keys
            or source_seed in conflicting_seed_names
            or len(bindings) != 1
        ):
            continue
        local_registry = _reviewed_archived_base_registry([candidate])
        local_audit = _reviewed_base_development_audits(
            [candidate], local_registry
        ).get(parent_key)
        if (
            local_registry.get(parent_key) != registry.get(parent_key)
            or local_audit != audits.get(parent_key)
        ):
            continue
        sequence_hash, (sequence_payload, _seed) = next(iter(bindings.items()))
        record = CertifiedReviewedBaseParent(
            parent_key=parent_key,
            source_seed=source_seed,
            geometry_hash=str(metadata.get("final_geometry_hash") or ""),
            program_hash=str(metadata.get("final_program_hash") or ""),
            base_review_fingerprint=str(
                local_audit.get("base_review_fingerprint") or ""
            ),
            sequence_payload=sequence_payload,
            sequence_hash=sequence_hash,
            candidate=deepcopy(candidate),
        )
        records_by_key.setdefault(parent_key, []).append(record)
    records = [
        values[0]
        for parent_key, values in sorted(records_by_key.items())
        if len({
            (
                value.geometry_hash,
                value.program_hash,
                value.base_review_fingerprint,
                value.source_seed,
                value.sequence_hash,
            )
            for value in values
        }) == 1
    ]
    conflicting_program_seed_names = {
        source_seed
        for source_seed in {record.source_seed for record in records}
        if len({
            (record.program_hash, record.sequence_hash)
            for record in records
            if record.source_seed == source_seed
        }) != 1
    }
    return tuple(
        record for record in records
        if record.source_seed not in conflicting_program_seed_names
    )


def _merge_two_phase_generation_counts(
    base_counts: dict[str, Any],
    descendant_counts: dict[str, Any],
    *,
    base_vlm_evidence: dict[str, Any],
    registry: dict[str, str | None],
) -> dict[str, Any]:
    merged = deepcopy(descendant_counts or base_counts)
    author_outcomes = [
        *deepcopy(base_counts.get("llm_author_request_outcomes") or []),
        *deepcopy(descendant_counts.get("llm_author_request_outcomes") or []),
    ]
    merged["llm_author_request_outcomes"] = author_outcomes
    merged["llm_author_request_executed"] = any(
        bool(outcome.get("provider_request_executed"))
        for outcome in author_outcomes
        if isinstance(outcome, dict)
    )
    merged["llm_author_valid_program_count"] = sum(
        max(0, int(outcome.get("valid_authored_program_count") or 0))
        for outcome in author_outcomes
        if isinstance(outcome, dict)
    )
    merged["llm_author_cache_hit_count"] = sum(
        max(0, int(outcome.get("cache_hit_count") or 0))
        for outcome in author_outcomes
        if isinstance(outcome, dict)
    )
    for key in ("evaluated", "compiled", "clean", "program_passed"):
        merged[key] = int(base_counts.get(key) or 0) + int(
            descendant_counts.get(key) or 0
        )
    base_archive = base_counts.get("legal_mass_archive") or {}
    descendant_archive = descendant_counts.get("legal_mass_archive") or {}
    records_by_hash = {
        str(record.get("geometry_hash") or ""): deepcopy(record)
        for record in (
            list(base_archive.get("records") or ())
            + list(descendant_archive.get("records") or ())
        )
        if isinstance(record, dict) and str(record.get("geometry_hash") or "")
    }
    merged["legal_mass_archive"] = {
        **deepcopy(base_archive),
        "record_count": len(records_by_hash),
        "records": list(records_by_hash.values()),
    }
    base_timings = base_counts.get("phase_durations_seconds") or {}
    descendant_timings = descendant_counts.get("phase_durations_seconds") or {}
    merged["phase_durations_seconds"] = {
        phase: float(base_timings.get(phase) or 0.0)
        + float(descendant_timings.get(phase) or 0.0)
        for phase in {**base_timings, **descendant_timings}
    }
    merged["two_phase_base_vlm"] = {
        "schema_version": "arr.maas.two_phase_base_vlm_generation.v1",
        "active": True,
        "base_generation_count": len(base_archive.get("records") or ()),
        "reviewed_base_count": len(
            base_vlm_evidence.get("reviewed_parent_fingerprints") or ()
        ),
        "registered_unique_parent_count": sum(
            isinstance(value, str) and bool(value)
            for value in registry.values()
        ),
        "conflicting_parent_count": sum(value is None for value in registry.values()),
        "descendant_generation_count": int(
            descendant_counts.get("program_passed") or 0
        ),
        "descendant_parent_authorization": deepcopy(
            descendant_counts.get("descendant_parent_authorization") or {
                "schema_version": (
                    "arr.maas.descendant_parent_authorization.v1"
                ),
                "input_count": 0,
                "authorized_count": 0,
                "filtered_count": 0,
                "filtered_by_reason": {},
            }
        ),
        "base_vlm_gate": deepcopy(base_vlm_evidence),
    }
    return merged


def _program_pool(
    site: Polygon,
    building_type: str,
    height: float,
    floors: int,
    *,
    base_review_callback: (
        Callable[[list[_Candidate]], tuple[list[_Candidate], dict[str, Any]]]
        | None
    ) = None,
    reviewed_base_parent_carry: tuple[CertifiedReviewedBaseParent, ...] = (),
    **kwargs: Any,
) -> tuple[list[_Candidate], dict[str, Any]]:
    """Execute BASE review before descendant enumeration in one run."""

    if base_review_callback is None:
        pool, counts = _program_pool_single_phase(
            site, building_type, height, floors, **kwargs
        )
        counts.pop("_runtime_directed_seeds", None)
        counts.pop("_runtime_parent_seeds", None)
        return pool, counts
    base_pool, base_counts = _program_pool_single_phase(
        site,
        building_type,
        height,
        floors,
        _generation_phase="base",
        **kwargs,
    )
    directed_seeds = tuple(base_counts.pop("_runtime_directed_seeds", ()) or ())
    fresh_parent_seeds = tuple(
        base_counts.pop("_runtime_parent_seeds", ()) or ()
    )
    fresh_reviewed_bases, base_vlm_evidence = base_review_callback(
        list(base_pool)
    )
    fresh_parent_records = _certified_reviewed_base_parent_records(
        list(fresh_reviewed_bases),
        fresh_parent_seeds,
    )
    carried_input = tuple(
        record for record in deepcopy(reviewed_base_parent_carry or ())
        if isinstance(record, CertifiedReviewedBaseParent)
    )
    carried_parent_records = _certified_reviewed_base_parent_records(
        [record.candidate for record in carried_input],
        [record.parent_seed() for record in carried_input],
    )
    reviewed_parent_records = _certified_reviewed_base_parent_records(
        [
            record.candidate
            for record in (*fresh_parent_records, *carried_parent_records)
        ],
        [
            *fresh_parent_seeds,
            *(record.parent_seed() for record in carried_parent_records),
        ],
    )
    reviewed_bases = [record.candidate for record in reviewed_parent_records]
    registry = _reviewed_archived_base_registry(list(reviewed_bases))
    reviewed_base_audits = _reviewed_base_development_audits(
        list(reviewed_bases),
        registry,
    )
    exact_parent_keys = _exact_canonical_reviewed_parent_keys(
        list(reviewed_bases),
        registry,
        reviewed_base_audits,
    )
    base_vlm_evidence = deepcopy(base_vlm_evidence)
    base_vlm_evidence["reviewed_parent_keys"] = sorted(exact_parent_keys)
    base_vlm_evidence["reviewed_parent_fingerprints"] = sorted({
        str(audit.get("base_review_fingerprint") or "")
        for parent_key, audit in reviewed_base_audits.items()
        if parent_key in exact_parent_keys
        and str(audit.get("base_review_fingerprint") or "")
    })
    base_vlm_evidence["fresh_reviewed_parent_count"] = len(
        fresh_reviewed_bases
    )
    base_vlm_evidence["carried_reviewed_parent_count"] = len(
        carried_parent_records
    )
    if not exact_parent_keys:
        counts = _merge_two_phase_generation_counts(
            base_counts,
            {},
            base_vlm_evidence=base_vlm_evidence,
            registry=registry,
        )
        counts["two_phase_base_vlm"]["descendant_parent_authorization"] = {
            "schema_version": "arr.maas.descendant_parent_authorization.v1",
            "phase_skipped": True,
            "reason": "no_exact_canonical_reviewed_parent",
            "input_count": 0,
            "authorized_count": 0,
            "filtered_count": 0,
            "filtered_by_reason": {},
        }
        counts["two_phase_base_vlm"]["carried_parent_count"] = len(
            carried_parent_records
        )
        counts["_runtime_certified_reviewed_base_parents"] = (
            reviewed_parent_records
        )
        return list(fresh_reviewed_bases), counts
    reviewed_base_lineages_by_key: dict[str, dict[str, Any]] = {}
    for candidate in reviewed_bases:
        metadata = getattr(getattr(candidate, "source", None), "metadata", None)
        if not isinstance(metadata, dict):
            continue
        lineage = metadata.get("book_generation_lineage") or {}
        parent_key = canonical_lineage_parent_key(lineage)
        if parent_key not in exact_parent_keys:
            continue
        candidate_registry = _reviewed_archived_base_registry([candidate])
        if candidate_registry.get(parent_key) != registry.get(parent_key):
            continue
        candidate_audit = _reviewed_base_development_audits(
            [candidate],
            candidate_registry,
        ).get(parent_key)
        if (
            not isinstance(candidate_audit, dict)
            or candidate_audit != reviewed_base_audits.get(parent_key)
        ):
            continue
        authorized_lineage, _reason = (
            _authorize_descendant_lineage_for_materialization(
                lineage,
                candidate_registry,
                {parent_key: candidate_audit},
            )
        )
        if authorized_lineage is None:
            continue
        reviewed_base_lineages_by_key[parent_key] = deepcopy(lineage)
    descendant_pool, descendant_counts = _program_pool_single_phase(
        site,
        building_type,
        height,
        floors,
        _directed_seeds_override=directed_seeds,
        _parent_seeds_override=tuple(
            record.parent_seed() for record in reviewed_parent_records
        ),
        _generation_phase="descendant",
        _reviewed_base_registry={
            key: registry[key] for key in exact_parent_keys
        },
        _reviewed_base_audits={
            key: reviewed_base_audits[key] for key in exact_parent_keys
        },
        _reviewed_base_lineages=tuple(
            reviewed_base_lineages_by_key.values()
        ),
        **kwargs,
    )
    descendant_counts.pop("_runtime_directed_seeds", None)
    descendant_counts.pop("_runtime_parent_seeds", None)
    counts = _merge_two_phase_generation_counts(
        base_counts,
        descendant_counts,
        base_vlm_evidence=base_vlm_evidence,
        registry=registry,
    )
    counts["two_phase_base_vlm"]["carried_parent_count"] = len(
        carried_parent_records
    )
    counts["_runtime_certified_reviewed_base_parents"] = (
        reviewed_parent_records
    )
    return list(fresh_reviewed_bases) + list(descendant_pool), counts



__all__ = ["_agent_mutated_seeds","_prebook_vlm_quarantined_llm_parents","_geometry_program_registry","_materialize_directed_geometry","_program_pool","_program_review_authority"]
