"""BOOK portfolio adapter for the core per-MASS execution passport."""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any, Mapping, MutableMapping

from backend.app.modules.design.generation.maas.agents.law_graph_agent.evidence import canonical_agent_evidence_hash, validate_persisted_law_agent_evidence
from backend.app.modules.design.generation.maas.agents.shared.types import AgentEvidence, ExecutionIdentity

from backend.app.modules.design.generation.maas.geometry_language.execution_passport import build_mass_execution_passport, enrich_mass_execution_passport


def selected_candidate_execution_passport(
    *,
    compilation: Mapping[str, Any],
    downstream_row: Mapping[str, Any],
    source_metadata: Mapping[str, Any],
    program_evidence: Mapping[str, Any],
    descriptor: Mapping[str, Any],
    pnu: str,
    candidate_finalization_evidence: Mapping[str, Any] | None = None,
    expected_finalization_identity: Mapping[str, Any] | None = None,
    allow_relaxed_finalization: bool = False,
) -> dict[str, Any]:
    """Merge already-computed candidate evidence; never rerun a hard gate."""

    capacity_projection = source_metadata.get("capacity_alternative_projection") or {}
    capacity_measurement = source_metadata.get("source_capacity_measurement") or {}
    shared_floor_contract = source_metadata.get("shared_floor_contract") or {}
    capacity_evidence = _resolved_capacity_evidence(
        capacity_projection=capacity_projection,
        capacity_measurement=capacity_measurement,
        shared_floor_contract=shared_floor_contract,
        descriptor=descriptor,
    )
    downstream_evidence = {
        "site": {
            **deepcopy(downstream_row.get("legal_generation_context_evidence") or {}),
            "status": "passed",
            "pnu": pnu,
        },
        "capacity": capacity_evidence,
        "law": deepcopy(downstream_row.get("legal_projection") or {}),
        "parking": deepcopy(downstream_row.get("parking_hard_gate") or {}),
        "program_fit": deepcopy(program_evidence),
        "selector": {
            "selected": True,
            "hard_pass": True,
            "selection_role": "portfolio_archive",
            "selection_effect": "none_shadow_only",
        },
    }
    vlm_audit = deepcopy(source_metadata.get("final_book_vlm_audit") or {})
    if str(vlm_audit.get("status") or "") in {"", "not_run", "not_evaluated"}:
        vlm_audit = {}
    certified_compilation = compilation.get("certified_compilation")
    if certified_compilation is not None:
        try:
            passport = build_mass_execution_passport(
                certified_compilation,
                vlm_result=vlm_audit or None,
                downstream_evidence=downstream_evidence,
                geometry_gate_evidence={
                    "hard_pass": bool(compilation.get("combined_hard_pass")),
                    "authority": "benchmark_final_hard_gates",
                },
                render_evidence=(
                    compilation.get("archive_render_evidence")
                    if isinstance(compilation.get("archive_render_evidence"), Mapping)
                    else None
                ),
                certified_vlm_binding_required=True,
            )
        except ValueError:
            if not allow_relaxed_finalization:
                raise
            compiled_render_hash = str(
                certified_compilation.geometry_hash
                if certified_compilation is not None
                else ""
            )
            provided_render_evidence = (
                deepcopy(compilation.get("archive_render_evidence"))
                if isinstance(compilation.get("archive_render_evidence"), Mapping)
                else {}
            )
            fallback_render_evidence = {
                **(provided_render_evidence if isinstance(
                    provided_render_evidence,
                    Mapping,
                ) else {}),
                "status": "warning",
                "hard_pass": False,
                "reason": "render_identity_mismatch",
                "render_identity_relaxed": True,
                "projected_visual_geometry_hash": compiled_render_hash,
                "geometry_hash": compiled_render_hash,
            }
            passport = build_mass_execution_passport(
                certified_compilation,
                vlm_result=vlm_audit or None,
                downstream_evidence=downstream_evidence,
                geometry_gate_evidence={
                    "hard_pass": bool(compilation.get("combined_hard_pass")),
                    "authority": "benchmark_final_hard_gates_relaxed",
                },
                render_evidence=fallback_render_evidence,
                certified_vlm_binding_required=True,
            )
            passport["stages"] = [
                *deepcopy(passport.get("stages") or ()),
                {
                    "id": "render_identity_fallback",
                    "label": "Render identity fallback",
                    "status": "not_evaluated",
                    "required_for_final": False,
                    "node_ids": [],
                    "evidence": {
                        "status": "warn",
                        "reason": "render identity mismatch relaxed in diagnostic mode",
                    },
                },
            ]
        return _bind_candidate_finalization_to_passport(
            passport,
            candidate_finalization_evidence,
            expected_identity=expected_finalization_identity,
            allow_relaxed_finalization=allow_relaxed_finalization,
        )

    initial = deepcopy(
        downstream_row.get("mass_execution_passport")
        or compilation.get("execution_passport")
        or {}
    )
    if not initial:
        return {}
    passport = enrich_mass_execution_passport(
        initial,
        downstream_evidence=downstream_evidence,
        vlm_result=vlm_audit or None,
    )
    return _bind_candidate_finalization_to_passport(
        passport,
        candidate_finalization_evidence,
        expected_identity=expected_finalization_identity,
        allow_relaxed_finalization=allow_relaxed_finalization,
    )


def _bind_candidate_finalization_to_passport(
    passport: dict[str, Any],
    evidence: Any,
    *,
    expected_identity: Mapping[str, Any] | None = None,
    allow_relaxed_finalization: bool = False,
) -> dict[str, Any]:
    """Bind the already-certified final-mesh floor authority once."""

    if not isinstance(evidence, Mapping):
        reason = "candidate_finalization_evidence_missing_or_invalid"
        if not allow_relaxed_finalization:
            raise ValueError(reason)
        return _append_relaxed_finalization_stage(
            passport,
            evidence={},
            reason=reason,
        )
    payload = deepcopy(dict(evidence))
    certificate = payload.get("candidate_actual_gfa_stop_certificate")
    measured_identity = payload.get("measured_identity")
    reason = ""
    finalization_schema = payload.get("schema_version")
    if (
        finalization_schema not in {
            "arr.maas.candidate_final_mesh_floor_finalization.v1",
            "arr.maas.candidate_final_mesh_floor_finalization.v2",
        }
        or payload.get("status") != "certified"
        or payload.get("hard_pass") is not True
    ):
        reason = "candidate_finalization_evidence_invalid_or_failed"
    elif not isinstance(certificate, Mapping):
        reason = (
            "candidate_finalization_missing_required_field:"
            "candidate_actual_gfa_stop_certificate"
        )
    elif not isinstance(measured_identity, Mapping):
        reason = (
            "candidate_finalization_missing_required_field:"
            "measured_identity"
        )
    else:
        expected = (
            dict(expected_identity)
            if isinstance(expected_identity, Mapping)
            else {}
        )
        required_values = {
            "expected_identity.program_hash": expected.get("program_hash"),
            "expected_identity.final_geometry_hash": expected.get(
                "final_geometry_hash"
            ),
            "expected_identity.visual_hash": expected.get("visual_hash"),
            "passport.program_hash": passport.get("program_hash"),
            "passport.visual_hash": passport.get("visual_hash"),
            "measured_identity.program_hash": measured_identity.get(
                "program_hash"
            ),
            "measured_identity.final_geometry_hash": measured_identity.get(
                "final_geometry_hash"
            ),
            "measured_identity.visual_hash": measured_identity.get(
                "visual_hash"
            ),
            "legal_floor_field_hash": payload.get("legal_floor_field_hash"),
            "candidate_actual_gfa_stop_hash": payload.get(
                "candidate_actual_gfa_stop_hash"
            ),
            "certificate.program_hash": certificate.get("program_hash"),
            "certificate.final_geometry_hash": certificate.get(
                "final_geometry_hash"
            ),
            "certificate.visual_hash": certificate.get("visual_hash"),
            "certificate.legal_floor_field_hash": certificate.get(
                "legal_floor_field_hash"
            ),
            "certificate.candidate_actual_gfa_stop_hash": certificate.get(
                "candidate_actual_gfa_stop_hash"
            ),
        }
        missing = next(
            (key for key, value in required_values.items() if not str(value or "")),
            "",
        )
        if missing:
            reason = f"candidate_finalization_missing_required_field:{missing}"
        elif certificate.get("hard_pass") is not True:
            reason = "candidate_finalization_evidence_invalid_or_failed"
        else:
            identity_bindings = {
                "passport.program_hash": (
                    passport.get("program_hash"),
                    expected.get("program_hash"),
                ),
                "passport.visual_hash": (
                    passport.get("visual_hash"),
                    expected.get("visual_hash"),
                ),
                "measured_identity.program_hash": (
                    measured_identity.get("program_hash"),
                    expected.get("program_hash"),
                ),
                "measured_identity.final_geometry_hash": (
                    measured_identity.get("final_geometry_hash"),
                    expected.get("final_geometry_hash"),
                ),
                "measured_identity.visual_hash": (
                    measured_identity.get("visual_hash"),
                    expected.get("visual_hash"),
                ),
                "certificate.program_hash": (
                    certificate.get("program_hash"),
                    expected.get("program_hash"),
                ),
                "certificate.final_geometry_hash": (
                    certificate.get("final_geometry_hash"),
                    expected.get("final_geometry_hash"),
                ),
                "certificate.visual_hash": (
                    certificate.get("visual_hash"),
                    expected.get("visual_hash"),
                ),
                "certificate.legal_floor_field_hash": (
                    certificate.get("legal_floor_field_hash"),
                    payload.get("legal_floor_field_hash"),
                ),
                "certificate.candidate_actual_gfa_stop_hash": (
                    certificate.get("candidate_actual_gfa_stop_hash"),
                    payload.get("candidate_actual_gfa_stop_hash"),
                ),
            }
            mismatch = next(
                (
                    key
                    for key, (actual, expected_value) in identity_bindings.items()
                    if str(actual) != str(expected_value)
                ),
                "",
            )
            if mismatch:
                reason = f"candidate_finalization_identity_mismatch:{mismatch}"
            elif (
                finalization_schema
                == "arr.maas.candidate_final_mesh_floor_finalization.v2"
                and not _valid_v2_finalization_capacity_contract(
                    payload,
                    certificate,
                )
            ):
                reason = (
                    "candidate_finalization_capacity_contract_mismatch"
                )
    if reason:
        if not allow_relaxed_finalization:
            raise ValueError(reason)
        return _append_relaxed_finalization_stage(
            passport,
            evidence=payload,
            reason=reason,
        )
    passport.update({
        "final_legal_geometry_hash": str(
            measured_identity.get("final_geometry_hash") or ""
        ),
        "legal_floor_field_hash": str(
            payload.get("legal_floor_field_hash") or ""
        ),
        "candidate_actual_gfa_stop_hash": str(
            payload.get("candidate_actual_gfa_stop_hash") or ""
        ),
        "candidate_actual_gfa_stop_certificate": deepcopy(certificate),
        "candidate_floor_count": payload.get("candidate_floor_count"),
        "candidate_target_gfa_m2": payload.get(
            "candidate_target_gfa_m2"
        ),
        "achieved_gfa_m2": payload.get("achieved_gfa_m2"),
        "requested_candidate_target_gfa_m2": payload.get(
            "requested_candidate_target_gfa_m2"
        ),
        "candidate_feasible_maximum_gfa_m2": payload.get(
            "candidate_feasible_maximum_gfa_m2"
        ),
        "candidate_minimum_capacity_utilization": payload.get(
            "candidate_minimum_capacity_utilization"
        ),
        "achieved_capacity_utilization": payload.get(
            "achieved_capacity_utilization"
        ),
        "candidate_capacity_resolution_hard_pass": payload.get(
            "candidate_capacity_resolution_hard_pass"
        ),
        "capacity_contract_mode": payload.get(
            "capacity_contract_mode"
        ),
    })
    return passport


def _valid_v2_finalization_capacity_contract(
    payload: Mapping[str, Any],
    certificate: Mapping[str, Any],
) -> bool:
    """Validate the resolved minimum-band contract bound to final mesh v2."""

    names = (
        "candidate_target_gfa_m2",
        "requested_candidate_target_gfa_m2",
        "achieved_gfa_m2",
        "candidate_feasible_maximum_gfa_m2",
        "candidate_minimum_capacity_utilization",
        "achieved_capacity_utilization",
    )
    if any(
        type(payload.get(name)) not in (int, float)
        or not isfinite(float(payload[name]))
        for name in names
    ):
        return False
    actual_target = float(payload["candidate_target_gfa_m2"])
    requested_target = float(
        payload["requested_candidate_target_gfa_m2"]
    )
    achieved = float(payload["achieved_gfa_m2"])
    feasible = float(payload["candidate_feasible_maximum_gfa_m2"])
    minimum = float(payload["candidate_minimum_capacity_utilization"])
    utilization = float(payload["achieved_capacity_utilization"])
    certificate_target = certificate.get("target_gfa_m2")
    certificate_achieved = certificate.get("achieved_gfa_m2")
    if (
        type(certificate_target) not in (int, float)
        or type(certificate_achieved) not in (int, float)
        or not isfinite(float(certificate_target))
        or not isfinite(float(certificate_achieved))
    ):
        return False
    # Underfill against the requested minimum is advisory: FAR is a statutory
    # ceiling, so a lawful mass may yield less than the requested band. The
    # utilization floor is therefore only asserted for the accepted-band mode;
    # every other identity and arithmetic binding below stays mandatory in both.
    mode = payload.get("capacity_contract_mode")
    if mode == "advisory_actual_gfa_underfill":
        advisory = payload.get("capacity_underfill_advisory")
        if (
            not isinstance(advisory, dict)
            or advisory.get("statutory_minimum") is not False
            or abs(
                float(advisory.get("achieved_capacity_utilization") or -1.0)
                - utilization
            ) > 1e-9
        ):
            return False
    elif mode != "accepted_actual_gfa_minimum_band":
        return False
    return bool(
        payload.get("candidate_capacity_resolution_hard_pass") is True
        and actual_target > 0.0
        and requested_target > 0.0
        and feasible > 0.0
        and 0.0 < minimum <= 1.0
        and (
            utilization + 1e-9 >= minimum
            or mode == "advisory_actual_gfa_underfill"
        )
        and abs(actual_target - achieved) <= 1e-6
        and abs(float(certificate_target) - actual_target) <= 1e-6
        and abs(float(certificate_achieved) - achieved) <= 1e-6
        and abs(utilization - achieved / feasible) <= 1e-9
    )


def _append_relaxed_finalization_stage(
    passport: dict[str, Any],
    *,
    evidence: Mapping[str, Any],
    reason: str,
) -> dict[str, Any]:
    """Persist one bounded diagnostic reason without granting authority."""

    passport.update({
        "hard_pass": False,
        "final_hard_pass": False,
        "full_flow_complete": False,
        "publishable": False,
        "status": "diagnostic_non_publishable",
        "candidate_finalization_hard_pass": False,
    })
    existing_stages = deepcopy(passport.get("stages") or ())
    for stage in existing_stages:
        if not isinstance(stage, dict) or stage.get("id") != "selector":
            continue
        stage["status"] = "failed"
        selector_evidence = stage.get("evidence")
        if not isinstance(selector_evidence, dict):
            selector_evidence = {}
            stage["evidence"] = selector_evidence
        selector_evidence.update({
            "selected": False,
            "hard_pass": False,
            "reason": "candidate_finalization_diagnostic_non_publishable",
        })
    passport["stages"] = [
        *existing_stages,
        {
            "id": "candidate_finalization_fallback",
            "label": "Candidate finalization evidence fallback",
            "status": "not_evaluated",
            "required_for_final": False,
            "node_ids": [],
            "evidence": {
                "status": "warn",
                "reason": reason,
                "candidate_finalization_evidence": deepcopy(dict(evidence)),
            },
        },
    ]
    return passport


def persist_selected_law_agent_evidence(
    *,
    selected_row: MutableMapping[str, Any],
    passport: MutableMapping[str, Any],
    geometry_artifact: MutableMapping[str, Any],
    evidence: AgentEvidence,
    expected_identity: ExecutionIdentity,
) -> dict[str, Any]:
    """Persist and fail-close one exact selected MASS law-agent binding."""

    payload = evidence.to_dict()
    evidence_hash = canonical_agent_evidence_hash(payload)
    issues = validate_persisted_law_agent_evidence(
        payload,
        evidence_hash,
        expected_identity=expected_identity,
    )
    hard_pass = not issues
    persisted_law = {
        "law_graph_agent_evidence": deepcopy(payload),
        "law_graph_evidence_hash": evidence_hash,
        "law_graph_evidence_hard_pass": hard_pass,
        "law_graph_evidence_failure_reasons": list(issues),
    }
    artifact_binding = {
        "schema_version": "arr.maas.geometry_artifact_law_binding.v1",
        "identity": expected_identity.to_dict(),
        **deepcopy(persisted_law),
    }
    persisted = {
        **deepcopy(persisted_law),
        "geometry_artifact_law_binding": deepcopy(artifact_binding),
    }
    selected_row.update(deepcopy(persisted))
    selected_row.update({
        "selected_execution_id": expected_identity.execution_id,
        "final_legal_program_hash": expected_identity.program_hash,
        "floor_capacity_plan_hash": (
            expected_identity.floor_capacity_plan_hash
        ),
    })
    passport.update(deepcopy(persisted_law))
    geometry_artifact.update(deepcopy(persisted_law))
    geometry_artifact["geometry_artifact_law_binding"] = deepcopy(
        artifact_binding
    )

    for passport_stage in passport.get("stages") or ():
        if not isinstance(passport_stage, dict):
            continue
        if passport_stage.get("id") == "law":
            stage_evidence = passport_stage.get("evidence")
            if not isinstance(stage_evidence, dict):
                stage_evidence = {}
                passport_stage["evidence"] = stage_evidence
            stage_evidence.update(deepcopy(persisted_law))
        if not hard_pass and passport_stage.get("id") == "selector":
            passport_stage["status"] = "failed"
            selector_evidence = passport_stage.get("evidence")
            if not isinstance(selector_evidence, dict):
                selector_evidence = {}
                passport_stage["evidence"] = selector_evidence
            selector_evidence.update({
                "selected": False,
                "hard_pass": False,
                "law_graph_evidence_failure_reasons": list(issues),
            })

    hard_gates = geometry_artifact.get("hardGates")
    if not isinstance(hard_gates, dict):
        hard_gates = {}
        geometry_artifact["hardGates"] = hard_gates
    hard_gates["lawGraph"] = deepcopy(persisted_law)
    if not hard_pass:
        selected_row["combined_hard_pass"] = False
        passport["hard_pass"] = False
        hard_gates["combinedHardPass"] = False
    return persisted


def _resolved_capacity_evidence(
    *,
    capacity_projection: Mapping[str, Any],
    capacity_measurement: Mapping[str, Any],
    shared_floor_contract: Mapping[str, Any],
    descriptor: Mapping[str, Any],
) -> dict[str, Any]:
    projection = deepcopy(dict(capacity_projection or {}))
    resolution = resolve_capacity_band_evidence(
        projection,
        capacity_measurement=capacity_measurement,
        fallback_requested_hard_pass=bool(
            descriptor.get("capacity_target_hard_pass")
        ),
    )
    shared_floor_gate = resolve_shared_floor_contract_hard_gate(
        shared_floor_contract
    )
    hard_pass = bool(
        resolution["resolved_capacity_hard_pass"]
        and shared_floor_gate["hard_pass"]
    )
    return {
        **projection,
        "measurement": deepcopy(dict(capacity_measurement or {})),
        "shared_floor_contract": deepcopy(dict(shared_floor_contract or {})),
        "floor_contract_hash": str(
            shared_floor_contract.get("floor_contract_hash") or ""
        ),
        "shared_floor_contract_hard_pass": shared_floor_gate["hard_pass"],
        "shared_floor_contract_failure_reasons": list(
            shared_floor_gate["failure_reasons"]
        ),
        "evaluated": bool(capacity_projection or capacity_measurement),
        **resolution,
        "hard_pass": hard_pass,
        "status": (
            "passed"
            if hard_pass
            else "failed"
        ),
    }


def resolve_shared_floor_contract_hard_gate(
    shared_floor_contract: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Fail closed when the selected MASS lacks its required floor contract."""

    contract = (
        dict(shared_floor_contract)
        if isinstance(shared_floor_contract, Mapping)
        else {}
    )
    structurally_valid = bool(
        contract.get("schema_version")
        == "arr.maas.shared_floor_contract.v1"
        and str(contract.get("floor_contract_hash") or "")
    )
    if not structurally_valid:
        return {
            "hard_pass": False,
            "failure_reasons": [
                "shared_floor_contract_missing_or_invalid"
            ],
        }
    if contract.get("hard_pass") is not True:
        return {
            "hard_pass": False,
            "failure_reasons": list(dict.fromkeys([
                "shared_floor_contract_failed",
                *(
                    str(reason)
                    for reason in contract.get("failure_reasons") or ()
                    if str(reason)
                ),
            ])),
        }
    return {"hard_pass": True, "failure_reasons": []}


def resolve_capacity_band_evidence(
    capacity_projection: Mapping[str, Any],
    *,
    capacity_measurement: Mapping[str, Any] | None = None,
    fallback_requested_hard_pass: bool = False,
) -> dict[str, Any]:
    projection = dict(capacity_projection or {})
    measurement = dict(capacity_measurement or {})
    selectable_measured = "selectable_capacity_hard_pass" in projection
    requested_id = str(
        projection.get("requested_capacity_alternative_id")
        or projection.get("alternative_id")
        or ""
    )
    requested_target = float(
        projection.get("requested_target_utilization")
        or projection.get("target_utilization")
        or 0.0
    )
    requested_hard_pass = bool(
        projection.get("target_hard_pass")
        if "target_hard_pass" in projection
        else fallback_requested_hard_pass
    )
    measured_value = (
        measurement.get("feasible_capacity_utilization")
        if "feasible_capacity_utilization" in measurement
        else measurement.get("utilization_ratio")
        if "utilization_ratio" in measurement
        else None
    )
    try:
        achieved = float(measured_value)
    except (TypeError, ValueError):
        achieved = 0.0
    measured_available = bool(
        measured_value is not None
        and isfinite(achieved)
        and achieved >= 0.0
    )
    measured_aggregate = bool(
        measured_available
        and measurement.get("hard_pass") is not False
    )
    minimum_value = (
        projection.get("feasible_minimum_utilization")
        if "feasible_minimum_utilization" in projection
        else measurement.get("feasible_minimum_utilization")
    )
    try:
        minimum = float(minimum_value)
    except (TypeError, ValueError):
        minimum = 0.0
    minimum_is_authoritative = bool(
        minimum_value is not None
        and isfinite(minimum)
        and minimum > 0.0
    )
    measurement_minimum_pass = bool(
        measured_aggregate
        and measurement.get("hard_pass") is True
    )

    def achieved_required_capacity(required: float) -> bool:
        return bool(
            achieved + 1e-9 >= required
            or (
                required <= minimum + 1e-9
                and measurement_minimum_pass
            )
        )

    if selectable_measured:
        resolved_id = str(
            projection.get("selectable_capacity_alternative_id") or ""
        )
        if not resolved_id and measured_available:
            resolved_id = "below_feasible_minimum"
        resolved_target = float(
            projection.get("selectable_capacity_target_utilization") or 0.0
        )
        resolved_hard_pass = bool(
            projection.get("selectable_capacity_hard_pass")
            and resolved_id
            and resolved_target > 0.0
            and measured_aggregate
            and minimum_is_authoritative
            and achieved_required_capacity(max(minimum, resolved_target))
        )
    else:
        resolved_id = requested_id
        resolved_target = requested_target
        resolved_hard_pass = bool(
            requested_hard_pass
            and resolved_id
            and resolved_target > 0.0
            and measured_aggregate
            and minimum_is_authoritative
            and achieved_required_capacity(max(minimum, resolved_target))
        )
    failure_reasons: list[str] = []
    if not resolved_id:
        failure_reasons.append("resolved_capacity_alternative_missing")
    if resolved_target <= 0.0:
        failure_reasons.append("resolved_capacity_target_invalid")
    if not measured_available:
        failure_reasons.append("final_capacity_measurement_missing_or_invalid")
    elif measurement.get("hard_pass") is False:
        failure_reasons.append("final_capacity_measurement_failed")
    if not minimum_is_authoritative:
        failure_reasons.append("capacity_minimum_missing_or_invalid")
    if (
        resolved_id
        and resolved_target > 0.0
        and measured_aggregate
        and minimum_is_authoritative
        and not achieved_required_capacity(max(minimum, resolved_target))
    ):
        failure_reasons.append("achieved_capacity_below_required_threshold")
    projection_hard_pass = (
        bool(projection.get("selectable_capacity_hard_pass"))
        if selectable_measured
        else requested_hard_pass
    )
    if (
        not projection_hard_pass
        and not failure_reasons
    ):
        failure_reasons.append("capacity_projection_not_hard_pass")
    return {
        "requested_capacity_alternative_id": requested_id,
        "requested_capacity_target_utilization": requested_target,
        "requested_target_hard_pass": requested_hard_pass,
        "resolved_capacity_alternative_id": resolved_id,
        "resolved_capacity_target_utilization": resolved_target,
        "resolved_capacity_hard_pass": resolved_hard_pass,
        "resolved_capacity_failure_reasons": failure_reasons,
        "resolved_capacity_minimum_utilization": minimum,
        "achieved_capacity_utilization": achieved,
    }


__all__ = [
    "persist_selected_law_agent_evidence",
    "resolve_capacity_band_evidence",
    "selected_candidate_execution_passport",
]
