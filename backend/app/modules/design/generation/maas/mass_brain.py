"""Fail-open shadow bridge from ARR's Python mass generator to Mass-Brain/GRL."""

from __future__ import annotations

import os
import re
import uuid
import json
from dataclasses import dataclass, replace
from itertools import combinations
from typing import Any, Callable, Iterable

import httpx

from backend.app.modules.design.generation import config
from backend.app.modules.design.generation.maas.grammar.component_graph import graph_from_sequence
from backend.app.modules.design.generation.maas.grammar.parameter_schema import CATEGORICAL_PARAMETER_VALUES, PARAMETERS_BY_VERB, PARAMETER_BOUNDS
from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall, VerbSequence
from backend.app.modules.design.generation.maas.grammar.vocab import SUPPORTED_VERBS
from backend.app.modules.design.generation.maas.book_language import audited_book_language_registry
from backend.app.modules.design.generation.maas.morphology_operators import MorphologyVariant
from backend.app.modules.design.generation.maas.mass_brain_relation_profile import relation_profile_from_feature, relation_profile_from_sequence, site_aspect_bucket


InterpretSequence = Callable[[Any, VerbSequence], MorphologyVariant | None]


@dataclass(frozen=True)
class MassBrainShadowBatch:
    variants: tuple[MorphologyVariant, ...]
    proposals_by_operator: dict[str, dict[str, Any]]
    artifact: dict[str, Any]


@dataclass(frozen=True)
class MassBrainSequenceBatch:
    sequences: tuple[VerbSequence, ...]
    proposals_by_sequence: dict[str, dict[str, Any]]
    artifact: dict[str, Any]


def sync_book_language_corpus() -> dict[str, Any]:
    """Idempotently publish ARR's audited BOOK registry to Mass-Brain.

    This is explicit rather than coupled to routine generation because
    Mass-Brain is intentionally OFF for selection after the fair ablation.
    """
    try:
        response = config.mass_brain_client.post(
            "/v1/corpora/ingest",
            json=audited_book_language_registry(),
        )
        response.raise_for_status()
        payload = response.json()
        return {"status": "synced", **(payload if isinstance(payload, dict) else {})}
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        response = getattr(exc, "response", None)
        detail = response.text[:2000] if response is not None else ""
        return {"status": "unavailable_fail_open", "error": f"{exc}{': ' + detail if detail else ''}"}


def mass_brain_config(parking_options: dict[str, Any] | None) -> dict[str, Any]:
    options = parking_options or {}
    raw = options.get("mass_brain") if isinstance(options.get("mass_brain"), dict) else {}
    env_enabled = os.getenv("MASS_BRAIN_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    return {
        "enabled": bool(raw.get("enabled", env_enabled)),
        "count": max(1, min(40, int(raw.get("count") or 12))),
        "seed": int(raw.get("seed") or 20260713),
        "include_experimental": bool(raw.get("include_experimental", True)),
    }


def request_shadow_variants(
    *,
    base_footprint: Any,
    source_variants: Iterable[MorphologyVariant],
    project_key: str,
    interpret: InterpretSequence,
    parking_options: dict[str, Any] | None = None,
    program_type: str | None = None,
) -> MassBrainShadowBatch:
    settings = mass_brain_config(parking_options)
    if not settings["enabled"]:
        return MassBrainShadowBatch((), {}, {"schema_version": "arr.maas.mass_brain_shadow.v1", "status": "disabled"})
    source_variants = list(source_variants)
    sequences = _unique_sequences(source_variants)
    if len(sequences) < 2:
        return MassBrainShadowBatch((), {}, {"schema_version": "arr.maas.mass_brain_shadow.v1", "status": "insufficient_sources", "source_count": len(sequences)})
    signatures = {
        variant.operator: dict(variant.source_signature)
        for variant in source_variants
        if isinstance(variant.source_signature, dict)
    }
    context = {
        "programType": str(program_type or "unknown"),
        "siteAspectBucket": site_aspect_bucket(base_footprint),
    }
    envelope = _build_envelope(project_key, sequences, source_signatures=signatures, context=context)
    run_id = str(uuid.uuid4())
    payload, error = _request_proposals(envelope, project_key=project_key, settings=settings)
    if error:
        return MassBrainShadowBatch((), {}, {
            "schema_version": "arr.maas.mass_brain_shadow.v1",
            "status": "unavailable_fail_open",
            "error": error,
        })
    compiled: list[MorphologyVariant] = []
    proposals_by_operator: dict[str, dict[str, Any]] = {}
    experimental_count = 0
    compile_rejected = 0
    for proposal in payload.get("proposals") or []:
        if not isinstance(proposal, dict):
            continue
        if proposal.get("lane") != "executable":
            experimental_count += int(proposal.get("lane") == "experimental")
            continue
        sequence = _sequence_from_proposal(proposal)
        if sequence is None:
            compile_rejected += 1
            continue
        variant = interpret(base_footprint, sequence)
        if variant is None:
            compile_rejected += 1
            continue
        operator = f"mass_brain_shadow_{_safe_id(str(proposal.get('proposalId') or sequence.name))}"
        variant = replace(
            variant,
            operator=operator,
            notes=variant.notes + (
                "proposal_source=mass_brain_shadow",
                f"mass_brain_proposal_id={proposal.get('proposalId')}",
            ),
        )
        compiled.append(variant)
        proposals_by_operator[operator] = proposal
    return MassBrainShadowBatch(tuple(compiled), proposals_by_operator, {
        "schema_version": "arr.maas.mass_brain_shadow.v1",
        "status": "shadow_generated",
        "project_key": project_key,
        "run_id": run_id,
        "source_count": len(sequences),
        "proposal_count": len(payload.get("proposals") or []),
        "compiled_count": len(compiled),
        "experimental_count": experimental_count,
        "compile_rejected_count": compile_rejected,
        "assistant_status": payload.get("assistantStatus"),
        "rollout": payload.get("rollout") if isinstance(payload.get("rollout"), dict) else {"mode": "shadow", "slots": 0},
        "selection_effect": "none_shadow_only",
    })


def request_shadow_sequences(
    *,
    source_sequences: Iterable[VerbSequence],
    project_key: str,
    program_type: str,
    site_aspect: str,
    parking_options: dict[str, Any] | None = None,
    source_features_by_sequence: dict[str, dict[str, Any]] | None = None,
) -> MassBrainSequenceBatch:
    """Request graph-memory variants without coupling to legal geometry.

    Program-massing/VLM loops use this lane to score Mass-Brain proposals as
    shadow evidence. They are not admitted to the final archive unless the
    service's separate promotion contract is active.
    """
    settings = mass_brain_config(parking_options)
    if not settings["enabled"]:
        return MassBrainSequenceBatch((), {}, {"schema_version": "arr.maas.mass_brain_shadow.v1", "status": "disabled"})
    sequences = _unique_verb_sequences(source_sequences)
    if len(sequences) < 2:
        return MassBrainSequenceBatch((), {}, {
            "schema_version": "arr.maas.mass_brain_shadow.v1",
            "status": "insufficient_sources",
            "source_count": len(sequences),
        })
    envelope = _build_envelope(
        project_key,
        sequences,
        context={"programType": program_type, "siteAspectBucket": site_aspect},
        source_features_by_sequence=source_features_by_sequence,
    )
    payload, error = _request_proposals(envelope, project_key=project_key, settings=settings)
    if error:
        return MassBrainSequenceBatch((), {}, {
            "schema_version": "arr.maas.mass_brain_shadow.v1",
            "status": "unavailable_fail_open",
            "error": error,
        })
    compiled: list[VerbSequence] = []
    proposals: dict[str, dict[str, Any]] = {}
    for proposal in payload.get("proposals") or []:
        if not isinstance(proposal, dict) or proposal.get("lane") != "executable":
            continue
        sequence = _sequence_from_proposal(proposal)
        if sequence is None:
            continue
        sequence = VerbSequence(
            name=sequence.name,
            label=sequence.label,
            calls=sequence.calls,
            notes=sequence.notes + (
                "proposal_source=mass_brain_shadow",
                f"mass_brain_proposal_id={proposal.get('proposalId')}",
            ),
        )
        compiled.append(sequence)
        proposals[sequence.name] = proposal
    return MassBrainSequenceBatch(tuple(compiled), proposals, {
        "schema_version": "arr.maas.mass_brain_shadow.v1",
        "status": "shadow_sequences_generated",
        "project_key": project_key,
        "source_count": len(sequences),
        "proposal_count": len(payload.get("proposals") or []),
        "compiled_count": len(compiled),
        "assistant_status": payload.get("assistantStatus"),
        "rollout": payload.get("rollout") if isinstance(payload.get("rollout"), dict) else {"mode": "shadow", "slots": 0},
    })


def record_shadow_outcomes(
    *,
    project_key: str,
    proposals_by_operator: dict[str, dict[str, Any]],
    features_by_operator: dict[str, dict[str, Any]],
    run_id: str | None = None,
    comparisons_by_operator: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    recorded = 0
    failed = 0
    for operator, proposal in proposals_by_operator.items():
        feature = features_by_operator.get(operator)
        props = feature.get("properties") if isinstance(feature, dict) and isinstance(feature.get("properties"), dict) else {}
        parking = props.get("parking_precheck") if isinstance(props.get("parking_precheck"), dict) else {}
        layout = parking.get("layout") if isinstance(parking.get("layout"), dict) else {}
        design_quality = props.get("design_quality") if isinstance(props.get("design_quality"), dict) else {}
        preference = props.get("preference_distillation") if isinstance(props.get("preference_distillation"), dict) else {}
        relation_profile = relation_profile_from_feature(feature)
        clean_mass_passed = _clean_mass_pass(relation_profile)
        payload = {
            "projectKey": project_key,
            "proposalId": proposal.get("proposalId"),
            "runId": f"{run_id}:{proposal.get('proposalId')}" if run_id else None,
            # A proposal that never reached an ARR ProgramElite is a compile /
            # hard-gate rejection, not a successful compile with a zero score.
            "compilePassed": feature is not None,
            # This shadow program loop has not run deterministic legal
            # projection. Never turn mere feature existence into a legal pass.
            "legalPassed": False,
            "parkingPassed": bool(layout.get("status") == "pass"),
            "geometryPassed": bool(feature and feature.get("geometry") and clean_mass_passed),
            "designQuality": _score01(design_quality.get("score") or design_quality.get("overall")),
            "novelty": _score01((proposal.get("scoreBreakdown") or {}).get("novelty")),
            "vlmScore": _score01(preference.get("distilled_preference_score")),
            "evidenceScore": _score01((proposal.get("scoreBreakdown") or {}).get("evidence")),
            "details": {
                "operator": operator,
                "shadow": True,
                "legalProjectionStatus": "not_run",
                "relationProfile": relation_profile,
                "cleanMassPassed": clean_mass_passed,
                "farUtilization": _score01(props.get("far_utilization")),
                "bcrUtilization": _score01(props.get("bcr_utilization")),
            },
        }
        comparison = (comparisons_by_operator or {}).get(operator)
        if isinstance(comparison, dict) and comparison.get("comparison_id"):
            payload.update({
                "comparisonId": str(comparison["comparison_id"]),
                "blindVlmWon": bool(comparison.get("blind_vlm_won")),
                "baselineHardPassed": bool(comparison.get("baseline_hard_passed")),
            })
        try:
            response = config.mass_brain_client.post("/v1/outcomes", json=payload)
            response.raise_for_status()
            recorded += 1
        except (httpx.HTTPError, ValueError, TypeError):
            failed += 1
    return {"recorded_count": recorded, "failed_count": failed}


def record_proposal_feedback(
    *,
    project_key: str,
    proposal_id: str,
    feedback_id: str,
    decision: str,
    rating: float | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Forward an ARR decision without making the ARR request depend on the service."""
    payload = {
        "projectKey": project_key,
        "proposalId": proposal_id,
        "feedbackId": feedback_id,
        "decision": decision,
        "note": note,
    }
    if rating is not None:
        payload["rating"] = rating
    try:
        response = config.mass_brain_client.post("/v1/feedback", json=payload)
        response.raise_for_status()
        return {"status": "recorded", "response": response.json()}
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return {"status": "unavailable_fail_open", "error": str(exc)}


def publish_geometry_portfolio_shadow(
    *,
    project_key: str,
    source_sequences: Iterable[VerbSequence],
    source_features_by_sequence: dict[str, dict[str, Any]],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Publish exact compiled portfolio traces without changing selection.

    Unlike ``request_shadow_sequences`` this endpoint performs no proposal
    generation.  It gives the graph service the exact AST/compiler/VLM/hard-
    gate evidence that ARR already used, while ARR remains the authority for
    geometry and final selection.
    """
    # Final recursive artifacts can share the same legacy VerbCall sequence
    # while carrying different AST/program/geometry hashes.  The proposal lane
    # intentionally deduplicates such flat sequences; the evidence lane must
    # not, or twenty distinct compiled solids collapse back into one graph
    # record.  Trace identity is the caller-provided unique sequence name,
    # backed by the artifact hashes below.
    sequences: list[VerbSequence] = []
    seen_names: set[str] = set()
    for sequence in source_sequences:
        if not sequence.calls or sequence.validate() or sequence.name in seen_names:
            continue
        seen_names.add(sequence.name)
        sequences.append(sequence)
        if len(sequences) >= 64:
            break
    if not sequences:
        return {
            "schema_version": "arr.maas.mass_brain_geometry_trace.v1",
            "status": "empty",
            "project_key": project_key,
            "source_count": 0,
        }
    envelope = _build_envelope(
        project_key,
        sequences,
        context={**dict(context or {}), "selectionEffect": "none_shadow_only"},
        source_features_by_sequence=source_features_by_sequence,
    )
    artifact_count = sum(
        isinstance(payload.get("geometryArtifact"), dict)
        for payload in envelope["domainPayloads"].values()
    )
    try:
        response = config.mass_brain_client.post("/v1/contracts/ingest", json=envelope)
        response.raise_for_status()
        result = response.json()
        return {
            "schema_version": "arr.maas.mass_brain_geometry_trace.v1",
            "status": "published_shadow_only",
            "project_key": project_key,
            "source_count": len(sequences),
            "geometry_artifact_count": artifact_count,
            "selection_effect": "none_shadow_only",
            "response": result if isinstance(result, dict) else {},
        }
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        response = getattr(exc, "response", None)
        detail = response.text[:2000] if response is not None else ""
        return {
            "schema_version": "arr.maas.mass_brain_geometry_trace.v1",
            "status": "unavailable_fail_open",
            "project_key": project_key,
            "source_count": len(sequences),
            "geometry_artifact_count": artifact_count,
            "selection_effect": "none_shadow_only",
            "error": f"{exc}{': ' + detail if detail else ''}",
        }


def _build_envelope(
    project_key: str,
    sequences: list[VerbSequence],
    *,
    source_signatures: dict[str, dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
    source_features_by_sequence: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    payloads: dict[str, Any] = {}
    feature_ids: list[str] = []
    relation_profiles: dict[str, dict[str, Any]] = {}
    for index, sequence in enumerate(sequences):
        feature_id = f"feature:arr-seed:{_safe_id(sequence.name)}"
        evidence_id = f"evidence:arr-seed:{_safe_id(sequence.name)}"
        feature_ids.append(feature_id)
        family = _family(sequence)
        features.append({
            "id": feature_id,
            "label": sequence.label or sequence.name,
            "kind": "massdsl_seed",
            "confidence": 0.82,
            "pipelineStage": "seed_generation",
            "evidenceDensity": max(1, len(sequence.notes)),
            "metadata": {"family": family, "operator": sequence.name},
        })
        evidence.append({
            "id": evidence_id,
            "featureId": feature_id,
            "sourcePath": "ARR/design/maas",
            "excerpt": "; ".join(sequence.notes[:4]) or f"ARR executable MassDSL seed {sequence.name}",
            "evidenceType": "generator_trace",
            "confidence": 0.8,
        })
        component = graph_from_sequence(sequence).to_dict()
        source_feature = (source_features_by_sequence or {}).get(sequence.name)
        relation_profile = (
            relation_profile_from_feature(source_feature)
            if isinstance(source_feature, dict)
            else relation_profile_from_sequence(
                sequence.calls,
                source_signature=(source_signatures or {}).get(sequence.name),
            )
        )
        relation_profiles[feature_id] = relation_profile
        evaluation = _evaluated_parent_evidence(source_feature, relation_profile)
        features[-1]["pipelineStage"] = "evaluated_parent" if evaluation["eligibleForRecombination"] else "seed_generation"
        features[-1]["metadata"]["formal_principle"] = relation_profile["formalStrategy"]
        payloads[feature_id] = {
            "family": family,
            "relationProfile": relation_profile,
            "context": dict(context or {}),
            "evaluation": evaluation,
            "source": {
                "sequenceName": sequence.name,
                "provenanceNotes": list(sequence.notes[:8]),
            },
            "componentGraph": {
                "schemaVersion": component.get("schema_version"),
                "name": component["name"],
                "label": component["label"],
                "nodes": [
                    {
                        "nodeId": node["node_id"],
                        "role": node["role"],
                        "parentId": node["parent_id"],
                        "optional": node["optional"],
                        "operation": node["operation"],
                        "constraints": dict(node.get("constraints") or {}),
                        "relation": str(node.get("relation") or "attach"),
                        "parameterSchema": _parameter_schema_for_verb(
                            str((node.get("operation") or {}).get("verb") or ""),
                            dict((node.get("operation") or {}).get("params") or {}),
                        ),
                    }
                    for node in component["nodes"]
                ],
            },
        }
        geometry_artifact = _geometry_artifact_from_feature(source_feature)
        if geometry_artifact:
            payloads[feature_id]["geometryArtifact"] = geometry_artifact
    circuits = []
    relations = []
    for index, (source, target) in enumerate(_sparse_relation_pairs(feature_ids, payloads)):
        source_sequence = sequences[feature_ids.index(source)]
        target_sequence = sequences[feature_ids.index(target)]
        confidence = 0.9 if _family(source_sequence) != _family(target_sequence) else 0.68
        circuits.append({
            "id": f"circuit:arr-seed:{index}",
            "sourceFeatureId": source,
            "targetFeatureId": target,
            "type": "contrasts" if confidence > 0.8 else "same_family",
            "confidence": confidence,
            "evidenceDensity": 2,
            "edgeWeight": 1.2 if confidence > 0.8 else 0.7,
            "evidenceIds": [f"evidence:arr-seed:{_safe_id(source_sequence.name)}", f"evidence:arr-seed:{_safe_id(target_sequence.name)}"],
        })
        relations.append({
            "id": f"relation:arr-seed:{index}",
            "sourceNodeId": source,
            "targetNodeId": target,
            "type": "recombination_candidate" if confidence > 0.8 else "same_strategy_support",
            "confidence": confidence,
            "evidenceIds": [],
            "metadata": {"source": "arr_massdsl"},
        })
    return {
        "schemaVersion": "mass-brain/v1",
        "projectKey": project_key,
        "contract": {
            "schemaVersion": "grl/v1",
            "dataset": {"id": project_key, "title": f"ARR Mass Brain {project_key}", "source": "ARR/design/maas"},
            "stages": [
                {"id": "seed_generation", "label": "Seed Generation"},
                {"id": "evaluated_parent", "label": "Evaluated Parent"},
            ],
            "features": features,
            "evidence": evidence,
            "circuits": circuits,
            "relations": relations,
            "queryHints": ["Find structurally distant executable MassDSL seeds"],
        },
        "domainPayloads": payloads,
    }


def _geometry_artifact_from_feature(feature: dict[str, Any] | None) -> dict[str, Any]:
    """Extract the exact executable trace; never infer geometry from notes."""
    props = feature.get("properties") if isinstance(feature, dict) and isinstance(feature.get("properties"), dict) else {}
    explicit = props.get("geometry_artifact")
    if isinstance(explicit, dict):
        return deepcopy_json(explicit)
    program = props.get("geometry_program")
    compilation = props.get("geometry_program_compilation")
    graph = props.get("geometry_graph_snapshot")
    program_relations = props.get("program_component_relation_evidence")
    if not isinstance(program, dict) or not program:
        return {}
    compilation = compilation if isinstance(compilation, dict) else {}
    graph = graph if isinstance(graph, dict) else {}
    final_vlm = props.get("final_book_vlm_audit")
    program_evidence = props.get("program_massing_evidence")
    clean_evidence = props.get("source_signature")
    return {
        "schemaVersion": "arr.maas.geometry_artifact.v1",
        "authority": "arr_recursive_geometry_program",
        "geometryProgram": deepcopy_json(program),
        "geometryGraphSnapshot": deepcopy_json(graph),
        "programRelationEvidence": (
            deepcopy_json(program_relations)
            if isinstance(program_relations, dict)
            else {}
        ),
        "compilation": deepcopy_json(compilation),
        "identity": {
            "programHash": str(compilation.get("program_hash") or ""),
            "geometryHash": str(compilation.get("geometry_hash") or ""),
        },
        "vlmAudit": deepcopy_json(final_vlm) if isinstance(final_vlm, dict) else {},
        "hardGates": {
            "program": deepcopy_json(program_evidence) if isinstance(program_evidence, dict) else {},
            "cleanMass": deepcopy_json(clean_evidence.get("coherence_evidence") or {}) if isinstance(clean_evidence, dict) else {},
        },
        "selectionEffect": "none_shadow_only",
    }


def deepcopy_json(value: Any) -> Any:
    """Detach JSON-compatible artifacts without importing geometry objects."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _evaluated_parent_evidence(
    feature: dict[str, Any] | None,
    relation_profile: dict[str, Any],
) -> dict[str, Any]:
    props = feature.get("properties") if isinstance(feature, dict) and isinstance(feature.get("properties"), dict) else {}
    spatial = props.get("program_spatial_evidence") if isinstance(props.get("program_spatial_evidence"), dict) else {}
    capacity = props.get("massing_capacity_policy") if isinstance(props.get("massing_capacity_policy"), dict) else {}
    far_utilization = _score01(props.get("normalized_far_utilization"))
    minimum_far = _score01(capacity.get("min_far_utilization"))
    has_feature = isinstance(feature, dict)
    compile_passed = bool(has_feature and feature.get("geometry"))
    program_passed = bool(spatial.get("hard_pass", True)) if has_feature else False
    capacity_passed = bool(has_feature and far_utilization + 1e-9 >= minimum_far)
    clean_mass_passed = bool(has_feature and _clean_mass_pass(relation_profile))
    eligible = bool(compile_passed and program_passed and capacity_passed and clean_mass_passed)
    return {
        "requiredForRecombination": True,
        "eligibleForRecombination": eligible,
        "compilePassed": compile_passed,
        "geometryPassed": compile_passed,
        "programPassed": program_passed,
        "capacityPassed": capacity_passed,
        "cleanMassPassed": clean_mass_passed,
        "farUtilization": far_utilization,
        "minimumFarUtilization": minimum_far,
        "legalPassed": None,
        "parkingPassed": None,
    }


def _sparse_relation_pairs(
    feature_ids: list[str],
    payloads: dict[str, Any],
    *,
    maximum_degree: int = 4,
) -> list[tuple[str, str]]:
    """Build a readable evidence graph without changing generation search.

    Mass-Brain computes compatibility from typed payloads. GRL edges are for
    evidence/navigation, so a complete n*(n-1)/2 graph adds no intelligence and
    makes the activation UI unreadable. Each feature keeps one same-strategy
    neighbor and up to three contrasting strategy/family neighbors.
    """
    if len(feature_ids) < 2:
        return []
    pairs: set[tuple[str, str]] = set()
    for index, source in enumerate(feature_ids):
        source_payload = payloads[source]
        source_strategy = str((source_payload.get("relationProfile") or {}).get("formalStrategy") or "")
        source_family = str(source_payload.get("family") or "")
        candidates = [*feature_ids[index + 1:], *feature_ids[:index]]
        same = [target for target in candidates if str((payloads[target].get("relationProfile") or {}).get("formalStrategy") or "") == source_strategy]
        contrast = [
            target for target in candidates
            if str((payloads[target].get("relationProfile") or {}).get("formalStrategy") or "") != source_strategy
            or str(payloads[target].get("family") or "") != source_family
        ]
        selected = same[:1] + contrast[: max(0, maximum_degree - min(1, len(same)))]
        for target in selected:
            pairs.add(tuple(sorted((source, target))))
    return sorted(pairs)


def _sequence_from_proposal(proposal: dict[str, Any]) -> VerbSequence | None:
    graph = proposal.get("componentGraph") if isinstance(proposal.get("componentGraph"), dict) else None
    nodes = graph.get("nodes") if isinstance(graph, dict) and isinstance(graph.get("nodes"), list) else []
    calls = tuple(
        VerbCall(str((node.get("operation") or {}).get("verb") or ""), dict((node.get("operation") or {}).get("params") or {}))
        for node in nodes if isinstance(node, dict) and isinstance(node.get("operation"), dict)
    )
    sequence = VerbSequence(
        name=f"mass_brain_{_safe_id(str(proposal.get('proposalId') or 'proposal'))}",
        label=str(graph.get("label") or "Mass-Brain shadow proposal") if isinstance(graph, dict) else "Mass-Brain shadow proposal",
        calls=calls,
        notes=(f"mass_brain_sources={','.join(str(item) for item in proposal.get('sourceNodeIds') or [])}",),
    )
    return None if sequence.validate() else sequence


def _parameter_schema_for_verb(verb: str, observed_params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Export ARR's executable parameter contract with every graph node.

    Mass-Brain must preserve these declared bounds/types when it recombines a
    typed subgraph. This is metadata, not a parcel-specific hardcoded form.
    """
    observed = dict(observed_params or {})
    # Persisted/LLM-authored graphs predate parts of the canonical contract.
    # An already compiled parent must remain exactly reproducible, so export
    # the canonical mutation domain plus any observed source fields instead of
    # rejecting the complete envelope at the service boundary.
    names = tuple(dict.fromkeys((*PARAMETERS_BY_VERB.get(verb, ()), *observed.keys())))
    numeric_bounds: dict[str, dict[str, float]] = {}
    categorical_values: dict[str, list[str]] = {}
    for name in names:
        value = observed.get(name)
        if name in PARAMETER_BOUNDS:
            low, high = PARAMETER_BOUNDS[name]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                low = min(low, float(value))
                high = max(high, float(value))
            numeric_bounds[name] = {"minimum": low, "maximum": high}
        if name in CATEGORICAL_PARAMETER_VALUES:
            values = list(CATEGORICAL_PARAMETER_VALUES[name])
            if isinstance(value, str) and value not in values:
                values.append(value)
            categorical_values[name] = values
    return {
        "allowedParameters": list(names),
        "numericBounds": numeric_bounds,
        "categoricalValues": categorical_values,
        "structuredParameters": [
            name for name in names
            if name not in PARAMETER_BOUNDS and name not in CATEGORICAL_PARAMETER_VALUES
        ],
    }


def _unique_sequences(variants: Iterable[MorphologyVariant]) -> list[VerbSequence]:
    result: list[VerbSequence] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for variant in variants:
        raw = variant.verb_sequence or ()
        calls = tuple(VerbCall(str(item.get("verb") or ""), dict(item.get("params") or {})) for item in raw if isinstance(item, dict))
        if not calls:
            continue
        sequence = VerbSequence(variant.operator, variant.operator.replace("_", " "), calls, variant.notes)
        signature = _sequence_signature(calls)
        if signature in seen or sequence.validate():
            continue
        seen.add(signature)
        result.append(sequence)
    return result[:32]


def _unique_verb_sequences(sequences: Iterable[VerbSequence]) -> list[VerbSequence]:
    result: list[VerbSequence] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for sequence in sequences:
        signature = _sequence_signature(sequence.calls)
        if not sequence.calls or signature in seen or sequence.validate():
            continue
        seen.add(signature)
        result.append(sequence)
    return result[:64]


def _sequence_signature(calls: Iterable[VerbCall]) -> tuple[tuple[str, str], ...]:
    return tuple(
        (call.verb, json.dumps(call.params, ensure_ascii=False, sort_keys=True, default=str))
        for call in calls
    )


def _request_proposals(
    envelope: dict[str, Any],
    *,
    project_key: str,
    settings: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    try:
        ingest_response = config.mass_brain_client.post("/v1/contracts/ingest", json=envelope)
        ingest_response.raise_for_status()
        proposal_response = config.mass_brain_client.post("/v1/proposals/generate", json={
            "projectKey": project_key,
            "count": settings["count"],
            "seed": settings["seed"],
            "includeExperimental": settings["include_experimental"],
            "registeredVerbs": sorted(SUPPORTED_VERBS),
        })
        proposal_response.raise_for_status()
        payload = proposal_response.json()
        return (payload if isinstance(payload, dict) else {}), None
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        response = getattr(exc, "response", None)
        detail = response.text[:2000] if response is not None else ""
        return {}, f"{exc}{': ' + detail if detail else ''}"


def _family(sequence: VerbSequence) -> str:
    verbs = {call.verb for call in sequence.calls}
    for family, family_verbs in (
        ("court", {"courtyard", "cave", "notch", "pinch"}),
        ("connector", {"bridge", "diagonal_connect", "terrace_link", "interlock", "overlap"}),
        ("section", {"grade", "step_envelope", "sloped_roof_mass", "taper"}),
        ("bar", {"bar", "bend", "shift"}),
        ("cluster", {"branch", "split", "nest", "embed"}),
    ):
        if verbs & family_verbs:
            return family
    return "mass"


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")[:80] or "item"


def _score01(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _clean_mass_pass(profile: dict[str, Any]) -> bool:
    """Keep weak learning behind the same clean-mass limits as visual review."""
    surface_count = int(profile.get("surfaceCount") or 0)
    return bool(
        surface_count > 0
        and surface_count <= 48
        and int(profile.get("componentCount") or 0) <= 5
        and int(profile.get("smallFragmentCount") or 0) <= 1
        and float(profile.get("primaryEnvelopeRetention") or 0.0) >= 0.55
        and int(profile.get("dominantOperationCount") or 0) <= 3
    )


__all__ = [
    "MassBrainSequenceBatch",
    "MassBrainShadowBatch",
    "mass_brain_config",
    "publish_geometry_portfolio_shadow",
    "record_shadow_outcomes",
    "record_proposal_feedback",
    "request_shadow_sequences",
    "request_shadow_variants",
    "sync_book_language_corpus",
]
