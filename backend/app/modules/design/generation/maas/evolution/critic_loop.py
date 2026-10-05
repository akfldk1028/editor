"""Same-run VLM critic -> MassDSL mutation loop for MAAS."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall, VerbSequence
from backend.app.modules.design.generation.maas.grammar.component_graph import graph_from_sequence, graph_with_nodes, strengthen_node
from backend.app.modules.design.generation.maas.morphology_operators import MorphologyVariant


Feature = dict[str, Any]
EvaluateVariant = Callable[[MorphologyVariant], Feature | None]
InterpretSequence = Callable[[Any, VerbSequence], MorphologyVariant | None]
QualityKey = Callable[[Feature], tuple[float, ...]]
Rescore = Callable[[list[Feature]], None]
ObjectiveVector = Callable[[Feature], tuple[float, ...]]


@dataclass(frozen=True)
class CriticLoopResult:
    accepted: list[Feature]
    trace: dict[str, Any]


def _sequence_from_feature(feature: Feature) -> VerbSequence | None:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    raw = props.get("maas_verb_sequence")
    if not isinstance(raw, list):
        model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
        raw = model.get("verb_sequence")
    calls: list[VerbCall] = []
    for item in raw or []:
        if isinstance(item, dict) and isinstance(item.get("verb"), str):
            calls.append(VerbCall(item["verb"], dict(item.get("params") or {})))
    if not calls:
        return None
    shape = str(props.get("mass_shape") or "critic_seed")
    sequence = VerbSequence(shape, shape, tuple(calls), (f"critic_parent={shape}",))
    return None if sequence.validate() else sequence


def _strengthen_primary(call: VerbCall) -> VerbCall:
    params = dict(call.params)
    for key in ("ratio", "factor", "width_ratio", "depth_ratio", "upper_ratio", "slab_ratio"):
        if isinstance(params.get(key), int | float):
            params[key] = round(min(0.92, max(0.18, float(params[key]) * 1.12)), 3)
    return VerbCall(call.verb, params)


def _mutations(sequence: VerbSequence, actions: list[str], generation: int) -> list[VerbSequence]:
    graph = graph_from_sequence(sequence)
    base = sequence.calls[0]
    tail = list(sequence.calls[1:])
    notes = sequence.notes + (f"critic_generation={generation}", f"critic_actions={','.join(actions)}")
    candidates: list[VerbSequence] = []
    numeric_params = {
        key: float(value)
        for call in tail
        for key, value in call.params.items()
        if isinstance(value, int | float) and not isinstance(value, bool)
    }
    if any(action in actions for action in ("too_fragmented", "too_many_surface_pieces", "overlapping_volumes")) and tail:
        retained = [node for node in graph.nodes if not node.optional]
        if len(retained) == len(graph.nodes) and len(retained) > 2:
            retained = retained[:-1]
        simplified_graph = graph_with_nodes(
            graph,
            retained,
            suffix=f"__critic_simplify_g{generation}",
        )
        candidates.append(simplified_graph.to_sequence())
    if "weak_primary_mass" in actions and tail:
        strengthened_nodes = list(graph.nodes)
        primary_index = next((i for i, node in enumerate(strengthened_nodes) if node.role == "primary"), 1)
        strengthened_nodes[primary_index] = strengthen_node(strengthened_nodes[primary_index])
        strengthened_nodes = [node for node in strengthened_nodes if not node.optional or node.role != "support"]
        primary_graph = graph_with_nodes(
            graph,
            strengthened_nodes,
            suffix=f"__critic_primary_g{generation}",
        )
        candidates.append(primary_graph.to_sequence())
    if "needs_clean_anchor" in actions:
        # Keep the anchor architectural rather than collapsing it to a single
        # extrusion: a dominant bar plus one restrained vertical move compiles
        # to a legible podium/stepped mass without reintroducing fragments.
        anchor = VerbCall("bar", {"axis": "x", "factor": 0.72})
        cap = VerbCall("stack", {
            "levels": 2,
            "z_step_ratio": 0.06,
            "slide_axis": "x",
            "slide_ratio": 0.0,
            "upper_ratio": 0.62,
            "lower_floor_fraction": 0.42,
        })
        candidates.append(VerbSequence(
            f"{sequence.name}__critic_anchor_g{generation}",
            f"{sequence.label} critic anchor",
            (base, anchor, cap),
            notes + ("critic_mutation=clean_slender_bar_anchor",),
        ))
        courtyard = VerbCall("courtyard", {"ratio": 0.22, "upper_ratio": 0.84})
        candidates.append(VerbSequence(
            f"{sequence.name}__critic_courtyard_g{generation}",
            f"{sequence.label} critic courtyard",
            (base, courtyard),
            notes + ("critic_mutation=clean_courtyard_anchor",),
        ))
        taper = VerbCall("taper", {"top_ratio": 0.58, "lower_floor_fraction": 0.42})
        candidates.append(VerbSequence(
            f"{sequence.name}__critic_podium_g{generation}",
            f"{sequence.label} critic podium tower",
            (base, taper),
            notes + ("critic_mutation=clean_podium_tower_anchor",),
        ))
    if any(action in actions for action in ("too_box_like", "weak_form_continuity", "needs_profiled_surface")):
        # CAD-Assistant-style typed topology revision: the visual diagnosis is
        # converted into a graph operation that the source compiler can render
        # as a non-flat field. Parameters are inherited when possible and vary
        # by critic generation; this is not a parcel-specific shape template.
        angle = max(16.0, min(42.0, numeric_params.get("angle", 22.0 + generation * 4.0)))
        lane_width = max(0.075, min(0.125, numeric_params.get("lane_width_ratio", 0.095 + generation * 0.006)))
        curvature = max(0.045, min(0.16, abs(angle) / 260.0))
        candidates.append(VerbSequence(
            f"{sequence.name}__critic_ribbon_field_g{generation}",
            f"{sequence.label} critic continuous ribbon field",
            (base, VerbCall("bend", {
                "lane_count": 3,
                "field_samples": 5,
                "lane_width_ratio": round(lane_width, 4),
                "width_gradient": 0.20,
                "curvature": round(curvature, 4),
                "vertical_mode": "grounded",
                "design_field_source": "vlm_critic_graph_edit",
            })),
            notes + ("critic_mutation=continuous_ribbon_field",),
        ))
        roof_x = max(0.56, min(0.82, numeric_params.get("x_ratio", 0.64 + generation * 0.04)))
        candidates.append(VerbSequence(
            f"{sequence.name}__critic_folded_field_g{generation}",
            f"{sequence.label} critic folded section field",
            (base, VerbCall("sloped_roof_mass", {"x_ratio": round(roof_x, 3), "y_ratio": 0.90})),
            notes + ("critic_mutation=folded_section_field",),
        ))
    if "needs_carved_void" in actions:
        void_ratio = max(0.18, min(0.42, numeric_params.get("ratio", 0.24 + generation * 0.03)))
        candidates.append(VerbSequence(
            f"{sequence.name}__critic_carved_void_g{generation}",
            f"{sequence.label} critic carved public void",
            (base, VerbCall("courtyard", {"ratio": round(void_ratio, 3), "upper_ratio": 0.84})),
            notes + ("critic_mutation=carved_atrium",),
        ))
    unique: list[VerbSequence] = []
    seen: set[tuple[str, ...]] = set()
    for candidate in candidates:
        key = tuple(call.verb for call in candidate.calls)
        if key not in seen and not candidate.validate():
            seen.add(key)
            unique.append(candidate)
    return unique[:4]


def run_critic_geometry_loop(
    *,
    base_footprint: Any,
    scored_features: list[Feature],
    interpret: InterpretSequence,
    evaluate: EvaluateVariant,
    rescore: Rescore,
    quality_key: QualityKey,
    objective_vector: ObjectiveVector | None = None,
    max_generations: int = 2,
    max_parents_per_generation: int = 8,
) -> CriticLoopResult:
    accepted: list[Feature] = []
    frontier = list(scored_features)
    archive: list[Feature] = list(scored_features)
    trace: dict[str, Any] = {
        "schema_version": "arr.maas.critic_geometry_loop.v1",
        "max_generations": max_generations,
        "max_parents_per_generation": max_parents_per_generation,
        "generations": [],
        "accepted_child_count": 0,
        "status": "no_actionable_critics",
    }
    for generation in range(1, max_generations + 1):
        records: list[dict[str, Any]] = []
        next_frontier: list[Feature] = []
        pending: list[tuple[Feature, Feature, VerbSequence, list[str], dict[str, Any]]] = []
        for parent in frontier[:max_parents_per_generation]:
            props = parent.get("properties") if isinstance(parent.get("properties"), dict) else {}
            pref = props.get("preference_distillation") if isinstance(props.get("preference_distillation"), dict) else {}
            actions = [str(item) for item in pref.get("critic_actions") or []]
            if not actions or actions == ["preserve_dominant_gesture"]:
                continue
            sequence = _sequence_from_feature(parent)
            if sequence is None:
                continue
            for child_sequence in _mutations(sequence, actions, generation):
                record = {
                    "generation": generation,
                    "parent_shape": props.get("mass_shape"),
                    "child_sequence": child_sequence.name,
                    "critic_actions": actions,
                    "verbs": [call.verb for call in child_sequence.calls],
                }
                variant = interpret(base_footprint, child_sequence)
                if variant is None:
                    record["status"] = "compile_rejected"
                    records.append(record)
                    continue
                child = evaluate(variant)
                if child is None:
                    record["status"] = "legal_parking_or_clean_gate_rejected"
                    records.append(record)
                    continue
                pending.append((parent, child, child_sequence, actions, record))
                records.append(record)
        if pending:
            rescore([child for _, child, _, _, _ in pending])
        for parent, child, child_sequence, actions, record in pending:
            parent_vector = objective_vector(parent) if objective_vector else ()
            child_vector = objective_vector(child) if objective_vector else ()
            pareto_improved = bool(parent_vector) and all(
                child_value >= parent_value
                for child_value, parent_value in zip(child_vector, parent_vector)
            ) and any(
                child_value > parent_value
                for child_value, parent_value in zip(child_vector, parent_vector)
            )
            record["parent_objective"] = list(parent_vector)
            record["child_objective"] = list(child_vector)
            record["pareto_improved"] = pareto_improved
            if not pareto_improved and quality_key(child) <= quality_key(parent):
                record["status"] = "no_quality_improvement"
                continue
            props = parent.get("properties") if isinstance(parent.get("properties"), dict) else {}
            child_props = child.setdefault("properties", {})
            child_props["critic_revision_evidence"] = {
                "schema_version": "arr.maas.critic_revision.v1",
                "parent_shape": props.get("mass_shape"),
                "critic_actions": actions,
                "generation": generation,
                "mutation_sequence": child_sequence.to_list(),
            }
            research = child_props.get("research_basis") if isinstance(child_props.get("research_basis"), dict) else {}
            research.update({
                "optimization_mode": "vlm_critic_geometry_revision",
                "parameter_source": "vlm_critic_geometry_revision",
                "requires_llm_authoring": False,
            })
            child_props["research_basis"] = research
            proposal = child_props.get("massdsl_proposal") if isinstance(child_props.get("massdsl_proposal"), dict) else {}
            design_parameters = proposal.get("design_parameters") if isinstance(proposal.get("design_parameters"), dict) else {}
            design_parameters.update({
                "parameter_source": "vlm_critic_geometry_revision",
                "requires_llm_authoring": False,
                "authoring_gap": "",
                "critic_actions": list(actions),
            })
            proposal["design_parameters"] = design_parameters
            proposal["proposal_source"] = "vlm_critic_geometry_revision"
            child_props["massdsl_proposal"] = proposal
            record["status"] = "accepted_after_revalidation"
            record["child_shape"] = child_props.get("mass_shape")
            accepted.append(child)
            archive.append(child)
            next_frontier.append(child)
        trace["generations"].append({"generation": generation, "records": records})
        if not next_frontier:
            break
        frontier = next_frontier
    trace["accepted_child_count"] = len(accepted)
    archive_by_shape: dict[str, Feature] = {}
    for feature in archive:
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        shape = str(props.get("mass_shape") or f"candidate_{id(feature)}")
        archive_by_shape[shape] = feature
    trace["constrained_archive_count"] = len(archive_by_shape)
    trace["constrained_archive_shapes"] = list(archive_by_shape)[:64]
    if accepted:
        trace["status"] = "accepted_revisions"
    elif any(generation.get("records") for generation in trace["generations"]):
        trace["status"] = "evaluated_no_accepted_revision"
    return CriticLoopResult(accepted, trace)


__all__ = ["CriticLoopResult", "run_critic_geometry_loop"]
