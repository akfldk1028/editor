"""Stateful, bounded component-graph revision for conversational MAAS edits."""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any

from backend.app.modules.design.generation.maas.grammar.component_graph import MassComponentGraph, MassComponentNode
from backend.app.modules.design.generation.maas.grammar.component_graph import graph_from_dict, graph_from_sequence
from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall
from backend.app.modules.design.generation.maas.grammar.parameter_schema import PARAMETER_BOUNDS, bounded_parameter
from backend.app.modules.design.generation.maas.legal_mesh_optimizer import _apply_source_volumes_as_mass_geometry, _architectural_order_gate, _attach_visual_diversity_evidence
from backend.app.modules.design.generation.maas.parking_strategy import attach_parking_strategy
from backend.app.modules.design.generation.maas.selection import final_mass_stage_parking_pass
from backend.app.modules.design.generation.maas.source_geometry import compile_component_graph_to_source_mass
from backend.app.modules.design.generation.services.site_geometry import geojson_to_polygon, wgs84_to_utm
from backend.app.modules.design.generation.maas.interactive.reference_intent import interpret_reference_intent_with_openai_vlm
from backend.app.modules.design.generation.maas.interactive.language_brain import propose_language_mutation
from backend.app.modules.design.generation.maas.interactive.revision_evaluation import evaluate_reference_revision


REVISION_SCHEMA_VERSION = "arr.maas.conversational_revision.v1"
ALLOWED_OPERATION_TYPES = {"set_parameter", "scale_parameter", "remove_optional_node"}
def infer_graph_operations(graph: MassComponentGraph, instruction: str) -> list[dict[str, Any]]:
    """Translate a small, deterministic conversational vocabulary into one bounded edit."""
    text = str(instruction or "").strip().lower()
    if not text:
        return []
    intents = (
        (("낮", "lower", "shorter", "줄여"), ("upper_ratio", "top_ratio", "factor"), 0.88),
        (("높", "taller", "higher", "raise"), ("upper_ratio", "top_ratio", "factor"), 1.12),
        (("넓", "크게", "wider", "bigger", "expand"), ("width_ratio", "slab_ratio", "factor"), 1.12),
        (("좁", "작게", "narrower", "smaller", "shrink"), ("width_ratio", "slab_ratio", "factor"), 0.88),
        (("캔틸레버", "돌출", "cantilever", "project"), ("distance_ratio", "shift_ratio"), 1.20),
        (("중정", "courtyard", "void"), ("ratio", "width_ratio", "depth_ratio"), 1.12),
    )
    for tokens, parameters, factor in intents:
        if not any(token in text for token in tokens):
            continue
        for node in graph.nodes[1:]:
            for parameter in parameters:
                if isinstance(node.operation.params.get(parameter), int | float):
                    return [{
                        "type": "scale_parameter",
                        "node_id": node.node_id,
                        "parameter": parameter,
                        "factor": factor,
                        "inference_source": "deterministic_conversation_v1",
                    }]
    return []


def _bounded_parameter(name: str, value: float) -> float:
    return bounded_parameter(name, value)


def _reference_provenance(reference: dict[str, Any]) -> dict[str, Any]:
    """Keep traceability without echoing a potentially multi-megabyte data URL."""
    return {
        key: value for key, value in reference.items()
        if key not in {"data_url"} and key in {"id", "title", "source", "image_url", "local_path", "media_type"}
    }


def apply_graph_operations(
    graph: MassComponentGraph,
    operations: list[dict[str, Any]],
) -> tuple[MassComponentGraph, list[dict[str, Any]]]:
    nodes = list(graph.nodes)
    diffs: list[dict[str, Any]] = []
    for raw in operations:
        if not isinstance(raw, dict) or raw.get("type") not in ALLOWED_OPERATION_TYPES:
            raise ValueError("unsupported graph revision operation")
        operation_type = str(raw["type"])
        node_id = str(raw.get("node_id") or "")
        index = next((i for i, node in enumerate(nodes) if node.node_id == node_id), None)
        if index is None:
            raise ValueError(f"unknown component node {node_id!r}")
        node = nodes[index]
        if node.role == "root":
            raise ValueError("root component cannot be revised directly")
        if operation_type == "remove_optional_node":
            if not node.optional:
                raise ValueError("only optional nodes may be removed")
            if any(candidate.parent_id == node.node_id for candidate in nodes):
                raise ValueError("component with children cannot be removed")
            nodes.pop(index)
            diffs.append({"type": operation_type, "node_id": node_id, "before": node.to_dict(), "after": None})
            continue
        parameter = str(raw.get("parameter") or "")
        if parameter not in PARAMETER_BOUNDS:
            raise ValueError(f"parameter {parameter!r} is not conversationally editable")
        before = node.operation.params.get(parameter)
        if not isinstance(before, int | float):
            raise ValueError(f"node {node_id!r} has no numeric parameter {parameter!r}")
        if operation_type == "set_parameter":
            after = _bounded_parameter(parameter, float(raw.get("value")))
        else:
            after = _bounded_parameter(parameter, float(before) * float(raw.get("factor") or 1.0))
        params = dict(node.operation.params)
        params[parameter] = after
        nodes[index] = replace(node, operation=VerbCall(node.operation.verb, params))
        diffs.append({
            "type": operation_type,
            "node_id": node_id,
            "parameter": parameter,
            "before": before,
            "after": after,
        })
    revised = MassComponentGraph(
        name=f"{graph.name}__revision",
        label=graph.label,
        nodes=tuple(nodes),
        notes=graph.notes + ("revision_mode=bounded_component_graph",),
    )
    errors = revised.validate()
    if errors:
        raise ValueError("revised component graph invalid: " + "; ".join(errors))
    return revised, diffs


def _legal_metrics_pass(feature: dict[str, Any], constraints: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    props = feature.get("properties") or {}
    issues: list[str] = []
    metric_map = {"bcr": "bcr", "far": "far", "height": "height"}
    for constraint in constraints:
        name = str(constraint.get("name") or "").lower()
        metric = metric_map.get(name)
        if not metric or not isinstance(constraint.get("val"), int | float):
            continue
        value = float(props.get(metric) or 0.0)
        limit = float(constraint["val"])
        requirement = str(constraint.get("Requirement") or "Less than").lower()
        if "less" in requirement and value > limit + 1e-6:
            issues.append(f"{metric}_limit_exceeded")
        if "greater" in requirement and value + 1e-6 < limit:
            issues.append(f"{metric}_minimum_not_met")
    return not issues, issues


def apply_conversational_graph_revision(
    *,
    accepted_feature: dict[str, Any],
    site_polygon_geojson: dict[str, Any],
    graph_operations: list[dict[str, Any]],
    constraints: list[dict[str, Any]] | None = None,
    building_type: str = "공동주택",
    instruction: str = "",
    references: list[dict[str, Any]] | None = None,
    revision_history: list[dict[str, Any]] | None = None,
    reference_vlm_model: str | None = None,
    learning_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    props = accepted_feature.get("properties") if isinstance(accepted_feature.get("properties"), dict) else {}
    signature = props.get("source_signature") if isinstance(props.get("source_signature"), dict) else {}
    graph_data = signature.get("component_graph")
    if not isinstance(graph_data, dict):
        raise ValueError("accepted_feature requires source_signature.component_graph")
    graph = graph_from_dict(graph_data)
    original_graph = graph
    references = [dict(item) for item in references or [] if isinstance(item, dict)]
    effective_operations = list(graph_operations or [])
    inference_source = "explicit_typed_operations"
    reference_intent: dict[str, Any] | None = None
    language_mutation = None
    if not effective_operations and references:
        reference_intent = interpret_reference_intent_with_openai_vlm(
            graph=graph,
            references=references,
            instruction=instruction,
            model=reference_vlm_model,
            learning_profile=learning_profile,
        )
        effective_operations = list(reference_intent["operations"])
        inference_source = "openai_reference_vlm_v1"
        used_languages = tuple(
            str(((item.get("reference_evidence") or {}).get("language_mutation") or {}).get("target_language") or "")
            for item in revision_history or [] if isinstance(item, dict)
        )
        language_mutation = propose_language_mutation(
            reference_intent=reference_intent,
            instruction=instruction,
            current_language=graph.name.split("__", 1)[0],
            used_languages=used_languages,
        )
        if language_mutation is not None:
            graph = graph_from_sequence(language_mutation.sequence)
            effective_operations = []
            inference_source = "openai_reference_vlm_to_language_brain_v1"
    elif not effective_operations:
        effective_operations = infer_graph_operations(graph, instruction)
        inference_source = "deterministic_conversation_v1"
    if not effective_operations and language_mutation is None:
        raise ValueError("instruction could not be translated; provide graph_operations")
    if language_mutation is not None:
        revised_graph = graph
        graph_diff = [{
            "type": "replace_topology",
            "before": original_graph.name,
            "after": revised_graph.name,
            "evidence": language_mutation.evidence(),
        }]
    else:
        revised_graph, graph_diff = apply_graph_operations(graph, effective_operations)
    base_utm = wgs84_to_utm(geojson_to_polygon(accepted_feature.get("geometry")))
    source = compile_component_graph_to_source_mass(base_utm, revised_graph)
    if source is None:
        raise ValueError("revised component graph did not compile")

    candidate = copy.deepcopy(accepted_feature)
    candidate_props = candidate.setdefault("properties", {})
    candidate_props["source_geometry_status"] = source.status
    candidate_props["source_signature"] = source.signature()
    candidate_props["source_volumes"] = [volume.signature() for volume in source.volumes]
    candidate_props["source_surfaces"] = [surface.signature() for surface in source.surfaces]
    candidate_props["maas_verb_sequence"] = revised_graph.to_sequence().to_list()
    model = candidate_props.get("maas_model") if isinstance(candidate_props.get("maas_model"), dict) else {}
    if model:
        model["source_signature"] = candidate_props["source_signature"]
        model["source_volumes"] = candidate_props["source_volumes"]
        model["component_graph"] = revised_graph.to_dict()
    if not _apply_source_volumes_as_mass_geometry(candidate):
        raise ValueError("revised source volumes could not be materialized inside accepted legal footprint")
    _attach_visual_diversity_evidence(candidate)

    site_utm = wgs84_to_utm(geojson_to_polygon(site_polygon_geojson))
    footprint_utm = wgs84_to_utm(geojson_to_polygon(candidate.get("geometry")))
    attach_parking_strategy(
        candidate_props,
        site_area_m2=float(site_utm.area),
        building_type=building_type,
        footprint_utm=footprint_utm,
        site_utm=site_utm,
    )
    legal_pass, legal_issues = _legal_metrics_pass(candidate, constraints or [])
    coherence = (candidate_props.get("source_signature") or {}).get("coherence_evidence") or {}
    order_pass, order_issues = _architectural_order_gate(candidate)
    parking_pass = final_mass_stage_parking_pass(candidate)
    structural_pass = bool(legal_pass and coherence.get("hard_pass") and order_pass and parking_pass)
    failures = [*legal_issues]
    if not coherence.get("hard_pass"):
        failures.append("coherence_hard_gate_failed")
    failures.extend(order_issues)
    if not parking_pass:
        failures.append("mass_stage_parking_hard_gate_failed")

    revision_evaluation: dict[str, Any] | None = None
    improvement_pass = True
    if reference_intent and structural_pass:
        revision_evaluation = evaluate_reference_revision(
            before_feature=accepted_feature,
            after_feature=candidate,
            references=references,
            intent_confidence=float(reference_intent.get("confidence") or 0.0),
            model=reference_vlm_model,
        )
        improvement_pass = bool(revision_evaluation.get("improvement_gate_pass"))
        failures.extend(str(item) for item in revision_evaluation.get("failures") or [])
        if not improvement_pass and len(effective_operations) > 1:
            alternative_records: list[dict[str, Any]] = []
            passing_trials: list[tuple[tuple[float, float], dict[str, Any], dict[str, Any], dict[str, Any]]] = []
            for index, operation in enumerate(effective_operations):
                trial = apply_conversational_graph_revision(
                    accepted_feature=accepted_feature,
                    site_polygon_geojson=site_polygon_geojson,
                    graph_operations=[operation],
                    constraints=constraints,
                    building_type=building_type,
                    instruction=instruction,
                    references=[],
                    revision_history=[],
                    reference_vlm_model=reference_vlm_model,
                    learning_profile=learning_profile,
                )
                record: dict[str, Any] = {
                    "alternative_index": index,
                    "operations": [operation],
                    "structural_gate_pass": bool(trial.get("accepted")),
                    "graph_diff": trial.get("graph_diff") or [],
                }
                if trial.get("accepted"):
                    evaluation = evaluate_reference_revision(
                        before_feature=accepted_feature,
                        after_feature=trial["feature"],
                        references=references,
                        intent_confidence=float(reference_intent.get("confidence") or 0.0),
                        model=reference_vlm_model,
                    )
                    record["evaluation"] = evaluation
                    if evaluation.get("improvement_gate_pass"):
                        key = (
                            float(evaluation.get("reference_adherence_delta") or 0.0),
                            float(evaluation.get("mass_quality_delta") or 0.0),
                        )
                        passing_trials.append((key, trial, evaluation, operation))
                alternative_records.append(record)
            revision_evaluation["alternative_evaluations"] = alternative_records
            if passing_trials:
                _, trial, chosen_evaluation, chosen_operation = max(passing_trials, key=lambda item: item[0])
                candidate = trial["feature"]
                candidate_props = candidate.get("properties") or {}
                revised_graph = graph_from_dict(trial["graph_after"])
                graph_diff = list(trial.get("graph_diff") or [])
                effective_operations = [chosen_operation]
                trial_validation = trial.get("validation") or {}
                legal_pass = bool(trial_validation.get("legal_pass"))
                parking_pass = bool(trial_validation.get("parking_pass"))
                order_pass = bool(trial_validation.get("architectural_order_pass"))
                coherence = {"hard_pass": bool(trial_validation.get("coherence_pass"))}
                structural_pass = True
                improvement_pass = True
                failures = []
                revision_evaluation = {
                    **chosen_evaluation,
                    "selection_mode": "best_independent_vlm_operation",
                    "selected_operation": chosen_operation,
                    "alternative_evaluations": alternative_records,
                }
    elif reference_intent:
        improvement_pass = False
        revision_evaluation = {
            "schema_version": "arr.maas.revision_evaluation.v1",
            "status": "skipped_structural_gate_failure",
            "improvement_gate_pass": False,
            "failures": ["structural_hard_gate_failed_before_visual_evaluation"],
        }
    accepted = bool(structural_pass and improvement_pass)

    reference_evidence = {
        "status": "vlm_interpreted" if reference_intent else ("provided_with_explicit_operations" if references else "not_provided"),
        "references": [_reference_provenance(item) for item in references],
    }
    if reference_intent:
        reference_evidence["intent"] = reference_intent
        reference_evidence["learning_profile"] = learning_profile or {}
    if language_mutation is not None:
        reference_evidence["language_mutation"] = language_mutation.evidence()
    event = {
        "schema_version": REVISION_SCHEMA_VERSION,
        "instruction": str(instruction or ""),
        "intent_translation": {
            "source": inference_source,
            "operations": effective_operations,
        },
        "graph_diff": graph_diff,
        "decision": "accepted" if accepted else "rejected_previous_graph_retained",
        "failures": sorted(set(failures)),
        "reference_evidence": reference_evidence,
        "revision_evaluation": revision_evaluation,
    }
    history = [dict(item) for item in revision_history or [] if isinstance(item, dict)] + [event]
    return {
        "schema_version": REVISION_SCHEMA_VERSION,
        "mode": "conversational_component_graph_revision",
        "accepted": accepted,
        "feature": candidate if accepted else accepted_feature,
        "candidate_feature": candidate,
        "previous_feature_retained": not accepted,
        "graph_before": original_graph.to_dict(),
        "graph_after": revised_graph.to_dict(),
        "graph_diff": graph_diff,
        "intent_translation": event["intent_translation"],
        "validation": {
            "legal_pass": legal_pass,
            "parking_pass": parking_pass,
            "coherence_pass": bool(coherence.get("hard_pass")),
            "architectural_order_pass": order_pass,
            "failures": sorted(set(failures)),
        },
        "reference_evidence": event["reference_evidence"],
        "revision_evaluation": revision_evaluation,
        "revision_history": history,
    }


__all__ = [
    "REVISION_SCHEMA_VERSION",
    "apply_conversational_graph_revision",
    "apply_graph_operations",
    "graph_from_dict",
    "infer_graph_operations",
]
