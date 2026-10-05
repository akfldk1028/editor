"""Bounded causal replenishment for a BOOK portfolio.

Each call owns one parent-variant generation cycle.  The benchmark decides
whether another cycle is needed from the accumulated exact hard-pass pool;
this module guarantees every new candidate follows the same base VLM,
program, legal/parking, final VLM and typed-repair path.
"""

from __future__ import annotations

import os
import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from backend.app.modules.design.generation.maas.book_language.candidate_analysis import _Candidate, _capacity_alternative_key, _chassis_family, _geometry_program_family, _fingerprint, _plan_family, _roof_archetype, _scope_key, _solid_morphology_metrics, _vlm_reviewed_program_candidate
from backend.app.modules.design.generation.maas.book_language.candidate_generation import CertifiedReviewedBaseParent, _certified_reviewed_base_parent_records, _exact_canonical_reviewed_parent_keys, _program_pool, _reviewed_archived_base_registry, _reviewed_base_development_audits
from backend.app.modules.design.generation.maas.book_language.competition_breadth_scheduler import BreadthScheduleResult, CompetitionBreadthScheduler, STAGE_FAILURE_NAMES
from backend.app.modules.design.generation.maas.book_language.competition_portfolio_contract import competition_family_supply_deficits
from backend.app.modules.design.generation.maas.book_language.downstream_hard_gate import evaluate_accepted_sources_downstream
from backend.app.modules.design.generation.maas.book_language.final_vlm_cycle import _bounded_final_review_pool, run_final_vlm_cycle
from backend.app.modules.design.generation.maas.book_language.portfolio_selection import _bounded_visual_selection_pool
from backend.app.modules.design.generation.maas.book_language.quality_diversity_archive import map_elites_archive
from backend.app.modules.design.generation.maas.book_language.run_budget import MAX_REPLENISHMENT_CYCLES
from backend.app.modules.design.generation.maas.book_language.vlm_review import _bind_final_visual_authority_for_review, audit_book_base_stage_with_vlm
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.projected_visual_contract import final_floorwise_visual_geometry_hash
from backend.app.modules.design.generation.maas.geometry_language.source_bridge import source_surface_payload_hash


@dataclass(frozen=True)
class ReplenishmentCycleResult:
    selection_pool: list[_Candidate]
    generated_pool: list[_Candidate]
    downstream_evaluation_pool: list[_Candidate]
    downstream_report: dict[str, Any] | None
    evidence: dict[str, Any]
    reviewed_parent_keys: set[str]
    reviewed_parent_fingerprints: set[str]
    live_qd_reserve: list[_Candidate]
    reviewed_final_vlm_fingerprints: set[tuple[Any, ...]]
    certified_reviewed_base_parents: tuple[Any, ...] = ()
    replenishment_work_dispositions: tuple[Any, ...] = ()


_MAX_CERTIFIED_REVIEWED_BASE_PARENTS = 64
_MAX_REPLENISHMENT_WORK_DISPOSITIONS = 256


@dataclass(frozen=True)
class ReplenishmentWorkDisposition:
    work_key: str
    parent_authority_fingerprint: str
    causal_request_hash: str
    child_principle_id: str
    variant_index: int
    candidate_identity_hash: str
    terminal_stage: str
    terminal_reason: str
    cycle_index: int


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")).hexdigest()


def replenishment_effective_context_hash(
    synthesis_requests: list[Any] | tuple[Any, ...],
) -> str:
    return _canonical_hash([
        deepcopy(request)
        for request in synthesis_requests
        if isinstance(request, dict)
    ])


def _synthesis_requests_with_author_rate_limit_cooldown(
    synthesis_requests: list[Any] | tuple[Any, ...],
    cooldown: dict[str, Any] | None,
) -> list[Any]:
    return [
        {
            **request,
            **(
                {"author_rate_limit_cooldown": deepcopy(cooldown)}
                if isinstance(cooldown, dict)
                else {}
            ),
        }
        if isinstance(request, dict)
        else request
        for request in synthesis_requests
    ]


def replenishment_request_hash(
    synthesis_requests: list[Any] | tuple[Any, ...],
) -> str:
    """Deprecated alias for the full effective provider-context hash."""

    return replenishment_effective_context_hash(synthesis_requests)


_TYPED_FEEDBACK_FIELDS = (
    "schema_version", "type", "stage", "kind", "reason", "reason_code",
    "failure_reason", "repair_reason", "structural_failure",
    "structural_subreason", "typed_reasons", "failure_reasons", "failures",
    "certificate_causes", "certificate_modes", "critic_actions",
    "required_next_relations", "required_relation_ids",
    "required_geometry_families", "required_scope_ids",
    "required_principle_ids", "missing_descriptor_cells", "geometry_family",
    "body_phenotype", "book_scope", "scope", "visual_authority",
    "failed_gates", "geometry_edit_intents", "required_threshold", "cap",
    "portfolio_contract_deficits",
)

_NESTED_CAUSAL_CONTROL_FIELDS = (
    "required_threshold",
    "cap",
    "portfolio_contract_deficits",
    "missing_descriptor_cells",
)

_NON_CAUSAL_EDIT_KEYS = frozenset({
    "rationale", "reasoning", "description", "instruction", "prose",
    "evidence", "response_id", "provider_id", "audit_id", "timestamp",
})

_LEGAL_FIT_MEASURED_FIELDS = (
    "target_floor_areas_m2", "legal_section_areas_m2", "target_total_m2",
    "legal_total_m2", "target_floor_area_decimal_places",
    "target_floor_area_rounding_tolerance_m2",
)

_CAPACITY_CAUSAL_FIELDS = (
    "schema_version", "type", "geometry_retry_policy", "geometry_family",
    "body_phenotype", "scope", "capacity_band", "achieved_utilization",
    "required_minimum_utilization", "measured_gfa_m2", "required_gfa_m2",
    "gfa_deficit_m2", "terminal_materialization_reason",
    "per_floor_deficit_status", "per_floor_gfa_deficits_m2", "typed_reasons",
    "failure_reasons", "plate_recertification_failure_reasons",
    "vertical_support_ratio", "minimum_vertical_support_ratio",
    "vertical_support_deficit_ratio", "measured_clear_depth_m", "clear_depth_m",
    "minimum_clear_depth_m", "clear_depth_deficit_m", "containment_status",
    "containment", "outside_distance_m", "outside_area_m2",
)

_FAMILY_SUPPLY_CAUSAL_FIELDS = (
    "schema_version", "family", "geometry_family", "phenotype",
    "body_phenotype", "required_body_phenotype_distinct",
    "available_body_phenotype_distinct", "body_phenotype_shortfall",
    "required_body_roof_signature_distinct",
    "available_body_roof_signature_distinct", "body_roof_signature_shortfall",
    "overrepresented_body_phenotype_counts",
    "overrepresented_body_roof_signature_counts",
    "overrepresented_geometry_family_counts", "minimum_pair_distance",
    "pair_distance_conflict_count", "visible_stepped_maximum",
    "visible_stepped_excess", "count", "shortfall", "missing_descriptor_cells",
)


def _canonical_causal_value(value: Any, *, ordered: bool = False) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonical_causal_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_canonical_causal_value(item) for item in value]
        if ordered:
            return items
        return sorted(
            items,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        )
    return value


def _typed_edit_control_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _typed_edit_control_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key).strip().lower() not in _NON_CAUSAL_EDIT_KEYS
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_typed_edit_control_value(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        )
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _causal_projection(
    record: dict[str, Any],
    fields: tuple[str, ...],
    *,
    ordered_fields: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    return {
        field: (
            _typed_edit_control_value(record[field])
            if field == "geometry_edit_intents"
            else _canonical_causal_value(
                record[field], ordered=field in ordered_fields
            )
        )
        for field in fields
        if field in record and record[field] not in (None, "", [], {})
    }


def _causal_records(value: Any, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        source = [value]
    elif isinstance(value, (list, tuple)):
        source = [record for record in value if isinstance(record, dict)]
    else:
        source = []
    records = [_causal_projection(record, fields) for record in source]
    return sorted(
        (record for record in records if record),
        key=lambda record: json.dumps(record, sort_keys=True, separators=(",", ":")),
    )


def _typed_feedback_causal_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        source = [value]
    elif isinstance(value, (list, tuple)):
        source = [record for record in value if isinstance(record, dict)]
    else:
        source = []
    records: list[dict[str, Any]] = []
    for record in source:
        projected = _causal_projection(record, _TYPED_FEEDBACK_FIELDS)
        evidence = record.get("evidence")
        if isinstance(evidence, dict):
            nested = _causal_projection(evidence, _NESTED_CAUSAL_CONTROL_FIELDS)
            if nested:
                projected["evidence"] = nested
        if projected:
            records.append(projected)
    return sorted(
        records,
        key=lambda record: json.dumps(record, sort_keys=True, separators=(",", ":")),
    )


def _legal_fit_causal_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        source = [value]
    elif isinstance(value, (list, tuple)):
        source = [record for record in value if isinstance(record, dict)]
    else:
        source = []
    records: list[dict[str, Any]] = []
    for record in source:
        projected = _causal_projection(
            record,
            ("schema_version", "stage", "typed_reasons", "legal_section_indices"),
        )
        measured = record.get("measured_values")
        if isinstance(measured, dict):
            measured_projection = _causal_projection(
                measured,
                _LEGAL_FIT_MEASURED_FIELDS,
                ordered_fields=frozenset(
                    {"target_floor_areas_m2", "legal_section_areas_m2"}
                ),
            )
            if measured_projection:
                projected["measured_values"] = measured_projection
        if projected:
            records.append(projected)
    return sorted(
        records,
        key=lambda record: json.dumps(record, sort_keys=True, separators=(",", ":")),
    )


def _deduplicate_causal_records(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_canonical_bytes = {
        json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ): record
        for record in records
    }
    return [
        by_canonical_bytes[canonical]
        for canonical in sorted(by_canonical_bytes)
    ]


def replenishment_causal_request_payload(
    synthesis_requests: list[Any] | tuple[Any, ...],
) -> dict[str, Any]:
    """Project production deficit contracts into stable causal work identity."""

    requests = [request for request in synthesis_requests if isinstance(request, dict)]
    payload: dict[str, Any] = {
        "schema_version": "arr.maas.replenishment_causal_request.v2",
        "request_kinds": sorted({
            str(request[field])
            for request in requests
            for field in ("author_request_kind", "request_kind", "synthesis_request_kind")
            if request.get(field) not in (None, "")
        }),
        "program_roles": sorted({
            str(request[field])
            for request in requests
            for field in ("program_role", "target_role", "program_slug")
            if request.get(field) not in (None, "")
        }),
    }
    channels = (
        ("legal_fit_repair_feedback", _legal_fit_causal_records),
        ("capacity_authoring_deficits", lambda value: _causal_records(value, _CAPACITY_CAUSAL_FIELDS)),
        ("family_supply_deficits", lambda value: _causal_records(value, _FAMILY_SUPPLY_CAUSAL_FIELDS)),
        ("base_book_vlm_replenishment_feedback", _typed_feedback_causal_records),
        ("authored_visual_authority_replenishment_feedback", _typed_feedback_causal_records),
        ("selector_stage_outcomes", _typed_feedback_causal_records),
        ("candidate_supply_deficits", _typed_feedback_causal_records),
    )
    for channel, normalizer in channels:
        records = [
            record
            for request in requests
            for record in normalizer(request.get(channel))
        ]
        if records:
            payload[channel] = _deduplicate_causal_records(records)
    return payload


def replenishment_causal_request_hash(
    synthesis_requests: list[Any] | tuple[Any, ...],
) -> str:
    return _canonical_hash(replenishment_causal_request_payload(synthesis_requests))


def candidate_disposition_identity_hash(candidate: Any) -> str:
    metadata = getattr(getattr(candidate, "source", None), "metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    return _canonical_hash({
        "program_hash": str(metadata.get("final_program_hash") or ""),
        "geometry_hash": str(metadata.get("final_geometry_hash") or ""),
        "surface_payload_hash": str(
            metadata.get("final_surface_payload_hash") or ""
        ),
    })


def bounded_replenishment_work_dispositions(
    records: tuple[ReplenishmentWorkDisposition, ...]
    | list[ReplenishmentWorkDisposition],
) -> tuple[ReplenishmentWorkDisposition, ...]:
    by_work_key: dict[str, ReplenishmentWorkDisposition] = {}
    for record in records:
        if not isinstance(record, ReplenishmentWorkDisposition):
            continue
        current = by_work_key.get(record.work_key)
        if current is None or (
            record.cycle_index,
            bool(record.candidate_identity_hash),
            record.terminal_stage,
            record.terminal_reason,
        ) > (
            current.cycle_index,
            bool(current.candidate_identity_hash),
            current.terminal_stage,
            current.terminal_reason,
        ):
            by_work_key[record.work_key] = deepcopy(record)
    ordered = sorted(
        by_work_key.values(),
        key=lambda record: (record.cycle_index, record.work_key),
    )
    return tuple(ordered[-_MAX_REPLENISHMENT_WORK_DISPOSITIONS:])


def filter_terminal_reserve_candidates(
    candidates: list[Any],
    *,
    causal_request_hash: str,
    dispositions: tuple[ReplenishmentWorkDisposition, ...],
) -> tuple[list[Any], int]:
    terminal_identities = {
        record.candidate_identity_hash
        for record in dispositions
        if record.causal_request_hash == causal_request_hash
        and record.candidate_identity_hash
        and record.terminal_stage not in {"", "generation"}
    }
    pending = [
        candidate for candidate in candidates
        if candidate_disposition_identity_hash(candidate)
        not in terminal_identities
    ]
    return pending, len(candidates) - len(pending)


def certified_reviewed_base_parent_snapshot(
    candidates: list[Any] | tuple[Any, ...] = (),
    *,
    parent_seeds: list[Any] | tuple[Any, ...] = (),
    carried: list[CertifiedReviewedBaseParent] | tuple[CertifiedReviewedBaseParent, ...] = (),
) -> tuple[Any, ...]:
    """Return bounded exact BASE authority plus immutable seed bindings."""

    carried_records = tuple(
        record for record in deepcopy(tuple(carried or ()))
        if isinstance(record, CertifiedReviewedBaseParent)
    )
    records = _certified_reviewed_base_parent_records(
        [
            *deepcopy(list(candidates or ())),
            *(record.candidate for record in carried_records),
        ],
        [
            *deepcopy(list(parent_seeds or ())),
            *(record.parent_seed() for record in carried_records),
        ],
    )
    return tuple(
        deepcopy(record)
        for record in records[:_MAX_CERTIFIED_REVIEWED_BASE_PARENTS]
    )


def _live_qd_reserve_eligible(candidate: Any) -> bool:
    if not isinstance(candidate, _Candidate):
        return False
    source = getattr(candidate, "source", None)
    metadata = getattr(source, "metadata", None)
    if not isinstance(metadata, dict) or not tuple(
        getattr(source, "surfaces", ()) or ()
    ):
        return False
    program_payload = metadata.get("geometry_program")
    if not isinstance(program_payload, dict):
        return False
    try:
        actual_program_hash = GeometryProgram.from_dict(
            program_payload
        ).program_hash()
        actual_geometry_hash = final_floorwise_visual_geometry_hash(source)
        actual_surface_payload_hash = source_surface_payload_hash(
            source.surfaces
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return False
    if (
        str(metadata.get("final_program_hash") or "")
        != actual_program_hash
        or str(metadata.get("final_geometry_hash") or "")
        != actual_geometry_hash
        or str(metadata.get("final_surface_payload_hash") or "")
        != actual_surface_payload_hash
    ):
        return False
    bridge = metadata.get("geometry_program_bridge_evidence")
    if not isinstance(bridge, dict) or (
        str(bridge.get("program_hash") or "") != actual_program_hash
        or str(bridge.get("geometry_hash") or "") != actual_geometry_hash
        or str(bridge.get("surface_payload_hash") or "")
        != actual_surface_payload_hash
    ):
        return False
    projection_identity = metadata.get("authored_projection_identity")
    if not (
        isinstance(projection_identity, dict)
        and projection_identity.get("schema_version")
        == "arr.maas.authored_projection_identity.v1"
        and projection_identity.get("hard_pass") is True
    ):
        return False
    certificate = metadata.get("authored_legal_projection_certificate")
    if not (
        isinstance(certificate, dict)
        and certificate.get("schema_version")
        == "arr.maas.authored_legal_projection_certificate.v1"
        and certificate.get("status") == "verified"
        and certificate.get("hard_pass") is True
        and str(certificate.get("input_authored_program_hash") or "")
        == actual_program_hash
        and str(certificate.get("projected_surface_hash") or "")
        == actual_geometry_hash
        and str(certificate.get("projected_surface_payload_hash") or "")
        == actual_surface_payload_hash
    ):
        return False
    lineage = metadata.get("book_generation_lineage")
    authority = metadata.get("program_review_authority")
    program_gate = metadata.get("program_gate_result")
    legal_capacity = metadata.get("legal_capacity_authority")
    return bool(
        isinstance(lineage, dict)
        and str(lineage.get("parent_key") or "")
        and isinstance(authority, dict)
        and authority.get("legal_archive_authority") is True
        and authority.get("selection_eligible") is True
        and authority.get("hard_pass") is True
        and isinstance(program_gate, dict)
        and program_gate.get("hard_pass") is True
        and isinstance(legal_capacity, dict)
        and legal_capacity.get("legal_hard_pass") is True
    )


def _merge_live_qd_reserve(
    prior_reserve: list[Any] | tuple[Any, ...],
    generated_candidates: list[Any] | tuple[Any, ...],
) -> list[_Candidate]:
    unique: list[_Candidate] = []
    seen: set[tuple[Any, ...]] = set()
    for candidate in (*prior_reserve, *generated_candidates):
        if not _live_qd_reserve_eligible(candidate):
            continue
        fingerprint = _fingerprint(candidate)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(candidate)
    return map_elites_archive(unique)


def _repair_final_vlm_submission_fingerprints(cycle: Any) -> set[tuple[Any, ...]]:
    repair_pool = list(getattr(cycle, "repair_pool", ()) or ())
    repair_passes = list(getattr(cycle, "repair_vlm_passes", ()) or ())
    repair_evidence = getattr(cycle, "repair_evidence", {}) or {}
    gate = repair_evidence.get("final_book_vlm_gate") or {}
    audit_records = gate.get("audit_records") or ()
    reviewed = {_fingerprint(candidate) for candidate in repair_passes}
    for candidate in repair_pool:
        metadata = getattr(candidate.source, "metadata", {}) or {}
        identity = (
            str(metadata.get("final_program_hash") or ""),
            str(metadata.get("final_geometry_hash") or ""),
            str(metadata.get("final_surface_payload_hash") or ""),
        )
        if all(identity) and any(
            identity
            == (
                str(record.get("final_program_hash") or ""),
                str(record.get("final_geometry_hash") or ""),
                str(record.get("final_surface_payload_hash") or ""),
            )
            for record in audit_records
            if isinstance(record, dict)
        ):
            reviewed.add(_fingerprint(candidate))
    if int(gate.get("input_count") or 0) == len(repair_pool):
        reviewed.update(_fingerprint(candidate) for candidate in repair_pool)
    return reviewed


def _candidate_program_hashes(candidate: _Candidate) -> set[str]:
    metadata = getattr(getattr(candidate, "source", None), "metadata", {}) or {}
    bridge = metadata.get("geometry_program_bridge_evidence") or {}
    semantic = metadata.get("final_semantic_projection_context") or {}
    snapshot = metadata.get("geometry_graph_snapshot") or {}
    program = metadata.get("geometry_program") or {}
    return {
        str(value)
        for value in (
            bridge.get("program_hash"),
            semantic.get("program_hash"),
            snapshot.get("program_hash"),
            program.get("program_hash"),
        )
        if str(value or "")
    }


def _exclude_duplicate_program_hashes(
    candidates: list[_Candidate],
    excluded_program_hashes: set[str],
) -> tuple[list[_Candidate], int]:
    excluded = {str(value) for value in excluded_program_hashes if str(value)}
    retained = [
        candidate for candidate in candidates
        if not (_candidate_program_hashes(candidate) & excluded)
    ]
    return retained, len(candidates) - len(retained)


def family_supply_deficits_for_candidates(
    candidates: list[_Candidate],
    *,
    target_count: int,
    compatibility_analysis: Any | None = None,
) -> dict[str, Any]:
    facts = []
    for candidate in candidates:
        morphology = _solid_morphology_metrics(candidate)
        body = str(
            morphology.get("body_phenotype")
            or morphology.get("phenotype")
            or "unclassified"
        )
        roof = _roof_archetype(candidate)
        facts.append({
            "body_phenotype": body,
            "roof_archetype": roof,
            "body_roof_signature": f"{body}|{roof}",
            "geometry_family": _geometry_program_family(candidate),
            "visible_stepped": bool(morphology.get("visible_stepped")),
        })
    pair_distances = []
    if compatibility_analysis is not None:
        for left_index, left in enumerate(candidates):
            for right in candidates[left_index + 1:]:
                pair_distances.append(
                    compatibility_analysis.distance(left, right)
                )
    return competition_family_supply_deficits(
        facts,
        target_count=target_count,
        pair_distances=pair_distances,
    )


def book_graph_supply_for_candidates(
    candidates: list[_Candidate],
) -> dict[str, Any]:
    """Describe retained BOOK principle supply without creating a hard gate."""

    principle_id_counts: dict[str, int] = {}
    principle_kind_counts: dict[str, int] = {}
    for candidate in candidates:
        principle_id = str(
            getattr(candidate, "principle_id", "") or ""
        )
        principle_kind = str(
            getattr(candidate, "principle_kind", "") or ""
        )
        if principle_id:
            principle_id_counts[principle_id] = (
                principle_id_counts.get(principle_id, 0) + 1
            )
        if principle_kind:
            principle_kind_counts[principle_kind] = (
                principle_kind_counts.get(principle_kind, 0) + 1
            )
    return {
        "schema_version": "arr.maas.book_graph_supply.v1",
        "hard_gate_effect": "none_diagnostic_only",
        "principle_id_counts": dict(sorted(principle_id_counts.items())),
        "principle_kind_counts": dict(
            sorted(principle_kind_counts.items())
        ),
    }


def competition_breadth_replenishment_state(
    schedule: BreadthScheduleResult,
    *,
    exact_hard_pass_count: int,
    feasible_portfolio: bool | None,
    downstream_stage_failure_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Persist the typed reason to stop or advance exactly one form-bank page."""

    state = competition_exact_reserve_transition(
        page_index=int(schedule.page_index),
        exact_hard_pass_count=exact_hard_pass_count,
        feasible_portfolio=feasible_portfolio,
    )
    stage_failure_counts = dict(schedule.stage_failure_counts)
    for stage, count in (downstream_stage_failure_counts or {}).items():
        if stage not in STAGE_FAILURE_NAMES:
            raise ValueError(f"unknown breadth failure stage: {stage}")
        stage_failure_counts[stage] = (
            int(stage_failure_counts.get(stage, 0))
            + max(0, int(count))
        )
    return {
        **state,
        "exact_shortlist_count": len(schedule.exact_shortlist),
        "breadth_deficits": [
            deficit.to_dict() for deficit in schedule.deficits
            if not (
                deficit.axis == "exact_shortlist"
                and deficit.cell == "total"
            )
        ],
        "stage_failure_counts": stage_failure_counts,
    }


def competition_exact_reserve_transition(
    *,
    page_index: int,
    exact_hard_pass_count: int,
    feasible_portfolio: bool | None,
) -> dict[str, Any]:
    """Return the operational stop/advance state consumed by the page loop."""

    stop = CompetitionBreadthScheduler.exact_pool_ready(
        exact_hard_pass_count=exact_hard_pass_count,
        feasible_portfolio=feasible_portfolio is True,
    )
    return {
        "schema_version": "arr.maas.competition_breadth_replenishment.v1",
        "stop": stop,
        "page_index": int(page_index),
        "next_page_index": (
            None if stop else int(page_index) + 1
        ),
        "exact_hard_pass_count": max(0, int(exact_hard_pass_count)),
        "feasible_portfolio": feasible_portfolio,
    }


def _downstream_breadth_failure_counts(
    report: dict[str, Any] | None,
) -> dict[str, int]:
    counts = {stage: 0 for stage in STAGE_FAILURE_NAMES}
    for row in (report or {}).get("rows") or ():
        legal = row.get("legal_projection") or {}
        parking = row.get("parking_hard_gate") or {}
        semantic = row.get("semantic_projection_hard_gate") or {}
        capacity = (
            row.get("capacity_hard_gate")
            or row.get("source_capacity_measurement")
            or {}
        )
        if legal.get("evaluated") is True and legal.get("hard_pass") is not True:
            counts["exact_csg"] += 1
        if (
            parking.get("evaluated") is True
            and parking.get("hard_pass") is not True
        ):
            counts["parking"] += 1
        if (
            semantic.get("evaluated") is True
            and semantic.get("hard_pass") is not True
        ):
            counts["hash_bridge"] += 1
        if (
            capacity.get("evaluated") is True
            and capacity.get("hard_pass") is not True
        ):
            counts["capacity"] += 1
    return counts


def competition_breadth_shortlist_candidates(
    candidates: list[_Candidate],
    *,
    page_index: int,
    target_count: int,
) -> tuple[list[_Candidate], BreadthScheduleResult]:
    """Adapt compiled candidates into the shared quota-aware exact shortlist."""

    wrapped = []
    for index, candidate in enumerate(candidates):
        morphology = _solid_morphology_metrics(candidate)
        wrapped.append(SimpleNamespace(
            key=f"breadth-{int(page_index):02d}-{index:04d}",
            original_candidate=candidate,
            page_index=int(page_index),
            base_scope=_scope_key(candidate),
            genotype_family=_geometry_program_family(candidate),
            book_principle_kind=str(candidate.principle_kind),
            book_principle_id=str(
                getattr(candidate, "principle_id", "unclassified")
            ),
            body_family=str(
                morphology.get("body_phenotype")
                or morphology.get("phenotype")
                or "unclassified"
            ),
            roof_family=_roof_archetype(candidate),
            chassis_family=_chassis_family(candidate),
            plan_family=_plan_family(candidate),
            capacity_band=_capacity_alternative_key(candidate),
            score=float(candidate.score),
            book_bind_pass=True,
            authored_compile_pass=True,
            legal_section_screen_pass=True,
            affine_screen_pass=True,
            approximate_capacity_pass=True,
        ))
    schedule = CompetitionBreadthScheduler(
        target_count=int(target_count),
    ).schedule_page(
        wrapped,
        page_index=int(page_index),
    )
    return [
        item.original_candidate for item in schedule.exact_shortlist
    ], schedule


def competition_exact_hard_pass_deficits(
    candidates: list[_Candidate],
    *,
    page_index: int,
    target_count: int,
    exact_compile_limit: int | None = None,
) -> list[dict[str, Any]]:
    """Recompute quota deficits over the actual exact hard-pass pool.

    ``exact_compile_limit`` is accepted at the initial-selection boundary for
    progressive runs.  The pool already contains only completed exact passes,
    so the limit must not reclassify or discard those observed candidates.
    """

    _ = exact_compile_limit

    _retained, schedule = competition_breadth_shortlist_candidates(
        candidates,
        page_index=page_index,
        target_count=target_count,
    )
    deficits = [
        deficit.to_dict() for deficit in schedule.deficits
        if not (
            deficit.axis == "exact_shortlist"
            and deficit.cell == "total"
        )
    ]
    if int(target_count) == 20 and len(candidates) < 24:
        deficits.append({
            "axis": "exact_hard_pass_reserve",
            "cell": "total",
            "required_count": 24,
            "available_count": len(candidates),
            "shortfall": 24 - len(candidates),
            "stage": "exact_hard_pass",
            "page_index": int(page_index),
        })
    return deficits


def replenishment_cycle_budget(
    *,
    run_budget_limit: int = MAX_REPLENISHMENT_CYCLES,
) -> int:
    """Return an explicit lowering of the run-owned cycle ceiling.

    Parent indices are an actual deterministic variation-lattice axis. The
    progressive run budget owns the default ceiling; this environment setting
    can only reduce it for a bounded diagnostic run.
    """
    hard_limit = max(
        0,
        min(MAX_REPLENISHMENT_CYCLES, int(run_budget_limit)),
    )
    configured = os.getenv("MAAS_BOOK_REPLENISHMENT_CYCLES")
    if configured is None:
        return hard_limit
    try:
        return max(0, min(hard_limit, int(configured)))
    except (TypeError, ValueError):
        return hard_limit


def replenishment_cycle_budget_for_run(
    *,
    live_vlm: bool,
    smoke_mode: bool = False,
    run_budget_limit: int | None = None,
) -> int:
    """Keep paid review bounded while letting local geometry pages close."""

    hard_limit = (
        MAX_REPLENISHMENT_CYCLES
        if run_budget_limit is None
        else max(
            0,
            min(MAX_REPLENISHMENT_CYCLES, int(run_budget_limit)),
        )
    )
    configured = replenishment_cycle_budget(
        run_budget_limit=hard_limit,
    )
    if smoke_mode:
        smoke_diagnostic = os.getenv(
            "MAAS_BOOK_SMOKE_REPLENISHMENT_CYCLES"
        )
        if smoke_diagnostic is not None:
            try:
                # Zero is an explicit diagnostic-only request. It never makes
                # an undersized portfolio pass; it only persists the initial
                # selection diagnostics without compiling another page.
                return min(
                    configured,
                    max(0, min(hard_limit, int(smoke_diagnostic))),
                )
            except (TypeError, ValueError):
                pass
    if live_vlm or smoke_mode or run_budget_limit is not None:
        return configured
    # Production/local closure still defaults to seven geometry pages. A
    # deliberately named diagnostic override can stop after an early page so
    # solver supply is inspected before another hour-long run. It never changes
    # any geometry, legal, parking, capacity or silhouette threshold.
    diagnostic = os.getenv("MAAS_BOOK_NONLIVE_REPLENISHMENT_CYCLES")
    if diagnostic is not None:
        try:
            return min(
                configured,
                max(0, min(hard_limit, int(diagnostic))),
            )
        except (TypeError, ValueError):
            pass
    return min(hard_limit, max(7, configured))


def replenishment_stop_reason(
    *,
    selected_count: int,
    selected_scope_count: int,
    target_count: int,
    required_scope_count: int,
    cycles_run: int,
    cycle_budget: int,
    exact_hard_pass_count: int | None = None,
    feasible_portfolio: bool | None = None,
    author_budget_failure: dict[str, Any] | None = None,
    exact_compile_remaining: int | None = None,
    author_replenishment_remaining: int | None = None,
    successful_author_count: int | None = None,
    successful_author_limit: int | None = None,
    provider_attempts_remaining: int | None = None,
    runtime_reserve_available: bool | None = None,
) -> str:
    """Return a terminal reason only for success or an exhausted budget.

    A cycle can approve new base parents without immediately increasing the
    final hard-pass pool: their descendants may fail the current BOOK or
    program projection while the next parent variant succeeds.  Treating two
    zero-growth final pools as stagnation skipped that next bounded variant
    and contradicted the three-cycle exploration contract.
    """
    if int(target_count) == 20:
        if CompetitionBreadthScheduler.exact_pool_ready(
            exact_hard_pass_count=int(exact_hard_pass_count or 0),
            feasible_portfolio=feasible_portfolio is True,
        ):
            return "competition_exact_reserve_feasible"
    elif selected_count >= target_count and selected_scope_count >= required_scope_count:
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
    if runtime_reserve_available is False:
        return "runtime_reserve_exhausted"
    failure = author_budget_failure or {}
    if (
        not successful_author_quota_active
        and
        failure.get("code") == "request_quota_exhausted"
        and failure.get("quota") == "author_replenishment"
        and failure.get("author_stage") == "replenishment"
        and (
            author_replenishment_remaining is None
            or author_replenishment_remaining <= 0
        )
    ):
        return "replenishment_author_quota_exhausted"
    if cycles_run >= cycle_budget:
        return "cycle_budget_exhausted"
    return ""


def critic_feedback_consumption_evidence(
    *,
    feedback_count: int,
    included_in_author_context: bool,
    author_request_executed: bool,
) -> dict[str, Any]:
    count = max(0, int(feedback_count))
    consumed = bool(
        count > 0
        and included_in_author_context
        and author_request_executed
    )
    if consumed:
        reason = "consumed"
    elif count == 0:
        reason = "no_feedback"
    elif not included_in_author_context:
        reason = "not_included_in_author_context"
    else:
        reason = "author_request_not_executed"
    return {
        "critic_feedback_consumed_same_run": consumed,
        "feedback_count": count,
        "included_in_author_context": bool(included_in_author_context),
        "author_request_executed": bool(author_request_executed),
        "reason": reason,
    }


def competition_exact_hard_pass_reserve(
    pool: list[_Candidate],
    *,
    selected: list[_Candidate],
) -> list[_Candidate]:
    """Keep a feasible 20-set plus at most eight deterministic reserve cards."""

    if len(selected) != 20:
        return list(pool)
    retained: list[_Candidate] = []
    seen: set[int] = set()
    for candidate in (*selected, *pool):
        identity = id(candidate)
        if identity in seen:
            continue
        seen.add(identity)
        retained.append(candidate)
        if len(retained) >= 28:
            break
    return retained


def run_replenishment_cycle(
    *,
    cycle_index: int,
    parent_variant_index: int,
    retained_selection_pool: list[_Candidate],
    excluded_parent_keys: set[str],
    excluded_parent_fingerprints: set[str],
    excluded_program_hashes: set[str],
    generation_site: Any,
    building_type: str,
    height: float,
    floors: int,
    generation_context: Any,
    typed_graph_mutations: list[Any],
    geometry_program_mutations: list[Any],
    synthesis_requests: list[Any],
    outcome_graph: Any,
    recursive_only: bool,
    target_count: int = 0,
    exact_compile_limit: int | None = None,
    program_dimensional_context: dict[str, Any] | None,
    site_boundary_source: str,
    site_access_context: dict[str, Any] | None,
    site_access_geometry: dict[str, Any] | None,
    runtime_live_vlm: bool,
    live_vlm_selection_required: bool,
    base_capacity_contract: dict[str, Any] | None,
    trusted_legal_floor_field: dict[str, Any] | None,
    trusted_legal_floor_field_hash: str,
    trusted_clear_span_floor_plan: dict[str, Any] | None,
    capacity_site: Any,
    output_dir: Path,
    program_slug: str,
    visual_directive: dict[str, Any],
    downstream_context: dict[str, Any],
    hard_gate_summary: Callable[[dict[str, Any] | None, list[_Candidate]], dict[str, Any]],
    stop_after_shared_floor_hard_passes: int | None = None,
    diagnostic_generation_budget: dict[str, Any] | None = None,
    progress_callback: Callable[[dict[str, int]], None] | None = None,
    retained_live_qd_reserve: list[_Candidate] | None = None,
    reviewed_final_vlm_fingerprints: set[tuple[Any, ...]] | None = None,
    certified_reviewed_base_parents: tuple[Any, ...] = (),
    replenishment_work_dispositions: tuple[
        ReplenishmentWorkDisposition, ...
    ] = (),
    author_rate_limit_cooldown: dict[str, Any] | None = None,
) -> ReplenishmentCycleResult:
    diagnostic_budget = dict(diagnostic_generation_budget or {})
    book_graph_supply = book_graph_supply_for_candidates(
        retained_selection_pool
    )
    effective_synthesis_requests = [
        {
            **dict(request),
            "book_graph_supply": {
                **book_graph_supply,
                "principle_id_counts": dict(
                    book_graph_supply["principle_id_counts"]
                ),
                "principle_kind_counts": dict(
                    book_graph_supply["principle_kind_counts"]
                ),
            },
        }
        for request in synthesis_requests
        if isinstance(request, dict)
    ]
    effective_synthesis_requests = (
        _synthesis_requests_with_author_rate_limit_cooldown(
            effective_synthesis_requests,
            author_rate_limit_cooldown,
        )
    )
    effective_context_hash = replenishment_effective_context_hash(
        effective_synthesis_requests
    )
    causal_request_hash = replenishment_causal_request_hash(
        effective_synthesis_requests
    )
    prior_work_dispositions = bounded_replenishment_work_dispositions(
        replenishment_work_dispositions
    )
    generated_pool, generation_counts = _program_pool(
        generation_site,
        building_type,
        height,
        floors,
        generation_context=generation_context,
        parent_variant_indices=(parent_variant_index,),
        typed_graph_mutations=typed_graph_mutations,
        geometry_program_mutations=geometry_program_mutations,
        synthesis_requests=effective_synthesis_requests,
        outcome_graph=outcome_graph,
        recursive_only=recursive_only,
        target_count=int(target_count),
        exact_compile_limit=exact_compile_limit,
        program_dimensional_context=program_dimensional_context,
        site_boundary_source=site_boundary_source,
        site_access_context=site_access_context,
        site_access_geometry=site_access_geometry,
        live_geometry_vlm_revision=runtime_live_vlm,
        base_capacity_contract=base_capacity_contract,
        trusted_legal_floor_field=trusted_legal_floor_field,
        trusted_legal_floor_field_hash=(
            trusted_legal_floor_field_hash
        ),
        trusted_clear_span_floor_plan=(
            trusted_clear_span_floor_plan
        ),
        capacity_site=capacity_site,
        pnu=str(downstream_context.get("pnu") or ""),
        stop_after_shared_floor_hard_passes=stop_after_shared_floor_hard_passes,
        diagnostic_scope_labels=tuple(
            diagnostic_budget.get("scope_labels") or ()
        ),
        diagnostic_book_probe_count=diagnostic_budget.get(
            "book_probe_count"
        ),
        diagnostic_evaluation_cap=diagnostic_budget.get("evaluation_cap"),
        diagnostic_candidate_cap=diagnostic_budget.get("candidate_cap"),
        progress_callback=progress_callback,
        base_review_callback=(
            (
                lambda base_pool: audit_book_base_stage_with_vlm(
                    base_pool,
                    building_type=building_type,
                    output_dir=(
                        output_dir
                        / f"replenishment-cycle-{cycle_index}"
                        / "book-base-stage"
                    ),
                    visual_directive=visual_directive,
                    outcome_graph=outcome_graph,
                    program_slug=program_slug,
                    excluded_parent_keys=excluded_parent_keys,
                    excluded_parent_fingerprints=(
                        excluded_parent_fingerprints
                    ),
                )
            )
            if runtime_live_vlm
            else None
        ),
        reviewed_base_parent_carry=deepcopy(
            tuple(certified_reviewed_base_parents or ())
        ),
        _replenishment_causal_request_hash=causal_request_hash,
        _replenishment_effective_context_hash=effective_context_hash,
        _replenishment_attempted_work_keys=frozenset(
            record.work_key
            for record in prior_work_dispositions
            if record.causal_request_hash == causal_request_hash
        ),
    )
    runtime_certified_reviewed_base_parents = tuple(
        generation_counts.pop(
            "_runtime_certified_reviewed_base_parents", ()
        ) or ()
    )
    next_certified_reviewed_base_parents = (
        certified_reviewed_base_parent_snapshot(
            carried=runtime_certified_reviewed_base_parents,
        )
    )
    generated_pool, duplicate_program_hash_count = (
        _exclude_duplicate_program_hashes(
            generated_pool,
            set(excluded_program_hashes or ()),
        )
    )
    generated_pool = [
        candidate
        for candidate in generated_pool
        if (
            isinstance(
                candidate.source.metadata.get("shared_floor_contract"),
                dict,
            )
            and candidate.source.metadata["shared_floor_contract"].get("hard_pass")
            is True
        )
    ]
    generated_pool, generated_terminal_skip_count = (
        filter_terminal_reserve_candidates(
            generated_pool,
            causal_request_hash=causal_request_hash,
            dispositions=prior_work_dispositions,
        )
    )
    prior_live_qd_reserve = _merge_live_qd_reserve(
        list(retained_live_qd_reserve or ()),
        [],
    )
    live_qd_reserve = _merge_live_qd_reserve(
        prior_live_qd_reserve,
        generated_pool,
    )
    reserve_by_fingerprint = {
        _fingerprint(candidate): candidate for candidate in live_qd_reserve
    }
    canonical_generated_pool: list[_Candidate] = []
    current_fingerprints: set[tuple[Any, ...]] = set()
    for candidate in generated_pool:
        fingerprint = _fingerprint(candidate)
        if fingerprint in current_fingerprints:
            continue
        current_fingerprints.add(fingerprint)
        canonical_generated_pool.append(
            reserve_by_fingerprint.get(fingerprint, candidate)
        )
    generated_pool = canonical_generated_pool
    retained_hard_pass_fingerprints = {
        _fingerprint(candidate) for candidate in retained_selection_pool
    }
    carried_candidates = [
        candidate
        for candidate in prior_live_qd_reserve
        if _live_qd_reserve_eligible(candidate)
        and _fingerprint(candidate) not in current_fingerprints
        and _fingerprint(candidate) not in retained_hard_pass_fingerprints
    ]
    carried_candidates, terminal_reserve_skip_count = (
        filter_terminal_reserve_candidates(
            carried_candidates,
            causal_request_hash=causal_request_hash,
            dispositions=prior_work_dispositions,
        )
    )
    generated_pool = [*generated_pool, *carried_candidates]
    breadth_schedule = None
    if (
        int(target_count) == 20
        and not diagnostic_budget
        and stop_after_shared_floor_hard_passes is None
    ):
        generated_pool, breadth_schedule = (
            competition_breadth_shortlist_candidates(
                generated_pool,
                page_index=parent_variant_index,
                target_count=int(target_count),
            )
        )
    if runtime_live_vlm:
        two_phase_base_vlm = generation_counts.get("two_phase_base_vlm") or {}
        base_gate = dict(two_phase_base_vlm.get("base_vlm_gate") or {})
        if two_phase_base_vlm.get("active") is not True or not base_gate:
            raise ValueError(
                "replenishment_two_phase_base_vlm_evidence_missing"
            )
        downstream_evaluation_pool = [
            candidate
            for candidate in generated_pool
            if not (
                str(
                    (
                        candidate.source.metadata.get(
                            "book_generation_lineage"
                        )
                        or {}
                    ).get("stage")
                    or ""
                )
                == "base"
                and (
                    candidate.source.metadata.get("program_gate_result")
                    or {}
                ).get("hard_pass")
                is not True
            )
        ]
    else:
        downstream_evaluation_pool = generated_pool
        base_gate = {
            "required": False,
            "status": "not_requested",
            "input_count": len(generated_pool),
            "reviewed_parent_keys": [],
            "reviewed_parent_fingerprints": [],
        }
    downstream_report = None
    downstream_passes = list(downstream_evaluation_pool)
    if generation_context is not None:
        downstream_report = evaluate_accepted_sources_downstream(
            downstream_evaluation_pool,
            **downstream_context,
        )
        downstream_passes = []
        for candidate, row in zip(
            downstream_evaluation_pool,
            downstream_report["rows"],
        ):
            if not row["combined_hard_pass"]:
                continue
            if runtime_live_vlm:
                _bind_final_visual_authority_for_review(
                    candidate,
                    row.get("semantic_projection_hard_gate") or {},
                )
            downstream_passes.append(candidate)
    new_work_dispositions = [
        ReplenishmentWorkDisposition(
            work_key=str(record.get("work_key") or ""),
            parent_authority_fingerprint=str(
                record.get("parent_authority_fingerprint") or ""
            ),
            causal_request_hash=str(
                record.get("causal_request_hash") or causal_request_hash
            ),
            child_principle_id=str(
                record.get("child_principle_id") or ""
            ),
            variant_index=int(record.get("variant_index") or 0),
            candidate_identity_hash="",
            terminal_stage=str(record.get("terminal_stage") or "generation"),
            terminal_reason=str(record.get("terminal_reason") or "attempted"),
            cycle_index=int(cycle_index),
        )
        for record in (
            generation_counts.get("replenishment_work_disposition", {}).get(
                "attempted_work_dispositions"
            ) or ()
        )
        if isinstance(record, dict) and str(record.get("work_key") or "")
    ]
    if downstream_report is not None:
        for candidate, row in zip(
            downstream_evaluation_pool,
            downstream_report.get("rows") or (),
        ):
            lineage = candidate.source.metadata.get(
                "book_generation_lineage"
            ) or {}
            identity = lineage.get("replenishment_work_identity") or {}
            if not isinstance(identity, dict):
                identity = {}
            work_key = str(identity.get("work_key") or "") or (
                "candidate:" + candidate_disposition_identity_hash(candidate)
                + ":" + causal_request_hash
            )
            failed = (
                row.get("failure_reasons")
                or row.get("failed_gates")
                or ()
            ) if isinstance(row, dict) else ()
            new_work_dispositions.append(ReplenishmentWorkDisposition(
                work_key=work_key,
                parent_authority_fingerprint=str(
                    identity.get("parent_authority_fingerprint") or ""
                ),
                causal_request_hash=causal_request_hash,
                child_principle_id=str(
                    identity.get("child_principle_id")
                    or getattr(candidate, "principle_id", "")
                ),
                variant_index=int(identity.get("variant_index") or 0),
                candidate_identity_hash=(
                    candidate_disposition_identity_hash(candidate)
                ),
                terminal_stage="downstream",
                terminal_reason=(
                    "combined_hard_pass"
                    if isinstance(row, dict)
                    and row.get("combined_hard_pass") is True
                    else str(next(iter(failed), "combined_hard_fail"))
                ),
                cycle_index=int(cycle_index),
            ))
    updated_work_dispositions = bounded_replenishment_work_dispositions((
        *prior_work_dispositions,
        *new_work_dispositions,
    ))
    if live_vlm_selection_required:
        downstream_passes = [
            candidate for candidate in downstream_passes
            if _vlm_reviewed_program_candidate(candidate)
        ]
    degenerate_count = sum(
        bool(_solid_morphology_metrics(candidate)["degenerate_sheet_like"])
        for candidate in downstream_passes
    )
    downstream_passes = [
        candidate for candidate in downstream_passes
        if not _solid_morphology_metrics(candidate)["degenerate_sheet_like"]
    ]
    evidence = {
        **generation_counts,
        "schema_version": "arr.maas.bounded_parent_replenishment_cycle.v2",
        "replenishment_request_identity": {
            "schema_version": "arr.maas.replenishment_request_identity.v2",
            "causal_request_hash": causal_request_hash,
            "effective_context_hash": effective_context_hash,
            "causal_request": replenishment_causal_request_payload(
                effective_synthesis_requests
            ),
        },
        "cycle_index": cycle_index,
        "parent_variant_index": parent_variant_index,
        "causal_trigger": "exact_post_book_vlm_and_portfolio_capacity",
        **critic_feedback_consumption_evidence(
            feedback_count=int(
                generation_counts.get("base_book_vlm_feedback_count") or 0
            ),
            included_in_author_context=bool(
                generation_counts.get(
                    "base_book_vlm_feedback_in_author_context"
                )
            ),
            author_request_executed=bool(
                generation_counts.get("llm_author_request_executed")
            ),
        ),
        "authored_visual_authority_feedback_consumption": {
            "feedback_count": int(
                generation_counts.get(
                    "authored_visual_authority_feedback_count"
                ) or 0
            ),
            "included_in_author_context": bool(
                generation_counts.get(
                    "authored_visual_authority_feedback_in_author_context"
                )
            ),
            "author_request_executed": bool(
                generation_counts.get("llm_author_request_executed")
            ),
            "revision_target": "typed_geometry_program_ast_mechanism",
            "legal_floor_loft_or_prism_replay_allowed": False,
        },
        "recursive_geometry_lane_enabled": bool(recursive_only),
        "preselection_hard_gate": hard_gate_summary(
            downstream_report,
            downstream_evaluation_pool,
        ),
        "degenerate_sheet_like_rejected_count": degenerate_count,
        "book_base_stage_vlm_gate": base_gate,
        "duplicate_parent_program_hash_excluded_count": (
            duplicate_program_hash_count
        ),
        "terminal_reserve_disposition_skip_count": (
            terminal_reserve_skip_count
            + generated_terminal_skip_count
        ),
        "replenishment_work_disposition_count": len(
            updated_work_dispositions
        ),
        "live_qd_reserve_count": len(live_qd_reserve),
        "live_qd_reserve_carried_count": len(carried_candidates),
        "certified_reviewed_base_parent_count": len(
            next_certified_reviewed_base_parents
        ),
    }
    if breadth_schedule is not None:
        exact_hard_pass_deficits = competition_exact_hard_pass_deficits(
            downstream_passes,
            page_index=parent_variant_index,
            target_count=int(target_count),
        )
        evidence["competition_breadth_schedule"] = (
            breadth_schedule.evidence()
        )
        evidence["competition_breadth_replenishment"] = (
            competition_breadth_replenishment_state(
                breadth_schedule,
                exact_hard_pass_count=len(downstream_passes),
                # Solver feasibility remains authoritative downstream.  This
                # cycle records supply and requests the next page until that
                # exact solver result is available.
                feasible_portfolio=None,
                downstream_stage_failure_counts=(
                    _downstream_breadth_failure_counts(
                        downstream_report
                    )
                ),
            )
        )
        evidence["competition_breadth_replenishment"][
            "breadth_deficits"
        ] = exact_hard_pass_deficits
    if runtime_live_vlm:
        prior_reviewed_final_vlm_fingerprints = set(
            reviewed_final_vlm_fingerprints or ()
        )
        final_review_pool = _bounded_final_review_pool([
            candidate
            for candidate in downstream_passes
            if _fingerprint(candidate)
            not in prior_reviewed_final_vlm_fingerprints
        ])
        submitted_final_vlm_fingerprints = {
            _fingerprint(candidate) for candidate in final_review_pool
        }
        cycle = run_final_vlm_cycle(
            final_review_pool,
            retained_hard_passes=list(retained_selection_pool),
            building_type=building_type,
            output_dir=output_dir / f"replenishment-cycle-{cycle_index}" / "final",
            visual_directive=visual_directive,
            outcome_graph=outcome_graph,
            program_slug=program_slug,
            generation_site=generation_site,
            height=height,
            floors=floors,
            generation_context=generation_context,
            program_dimensional_context=program_dimensional_context,
            site_boundary_source=site_boundary_source,
            site_access_context=site_access_context,
            site_access_geometry=site_access_geometry,
            base_capacity_contract=base_capacity_contract,
            downstream_context=downstream_context,
            hard_gate_summary=hard_gate_summary,
            completion_status="replenishment_exact_typed_repair_cycle_complete",
            no_repair_status="no_downstream_hard_pass_replenishment_repair_candidates",
        )
        selection_pool = cycle.selection_pool
        evidence["exact_post_book_typed_repair"] = cycle.repair_evidence
        evidence["final_book_vlm_gate"] = cycle.final_vlm_gate
        submitted_final_vlm_fingerprints.update(
            _repair_final_vlm_submission_fingerprints(cycle)
        )
    else:
        prior_reviewed_final_vlm_fingerprints = set(
            reviewed_final_vlm_fingerprints or ()
        )
        submitted_final_vlm_fingerprints = set()
        selection_pool = _bounded_visual_selection_pool([
            *retained_selection_pool,
            *downstream_passes,
        ])
    updated_reviewed_final_vlm_fingerprints = (
        prior_reviewed_final_vlm_fingerprints
        | submitted_final_vlm_fingerprints
    )
    evidence["final_vlm_already_reviewed_count"] = len(
        prior_reviewed_final_vlm_fingerprints
    )
    evidence["final_vlm_submitted_fingerprint_count"] = len(
        submitted_final_vlm_fingerprints
    )
    evidence["reviewed_final_vlm_fingerprint_count"] = len(
        updated_reviewed_final_vlm_fingerprints
    )
    return ReplenishmentCycleResult(
        selection_pool=selection_pool,
        generated_pool=generated_pool,
        downstream_evaluation_pool=downstream_evaluation_pool,
        downstream_report=downstream_report,
        evidence=evidence,
        reviewed_parent_keys=set(str(value) for value in base_gate.get("reviewed_parent_keys") or ()),
        reviewed_parent_fingerprints=set(
            str(value) for value in base_gate.get("reviewed_parent_fingerprints") or ()
        ),
        live_qd_reserve=live_qd_reserve,
        reviewed_final_vlm_fingerprints=(
            updated_reviewed_final_vlm_fingerprints
        ),
        certified_reviewed_base_parents=(
            next_certified_reviewed_base_parents
        ),
        replenishment_work_dispositions=updated_work_dispositions,
    )


__all__ = [
    "ReplenishmentCycleResult",
    "ReplenishmentWorkDisposition",
    "bounded_replenishment_work_dispositions",
    "candidate_disposition_identity_hash",
    "filter_terminal_reserve_candidates",
    "replenishment_request_hash",
    "certified_reviewed_base_parent_snapshot",
    "competition_breadth_replenishment_state",
    "competition_breadth_shortlist_candidates",
    "competition_exact_hard_pass_reserve",
    "competition_exact_hard_pass_deficits",
    "competition_exact_reserve_transition",
    "family_supply_deficits_for_candidates",
    "replenishment_cycle_budget",
    "replenishment_cycle_budget_for_run",
    "replenishment_stop_reason",
    "run_replenishment_cycle",
]
