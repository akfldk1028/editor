"""Typed, normalized section/roof relations for program massing.

The graph is deliberately separate from parcel coordinates.  Program data
defines component roles and normalized section controls; BOOK, LLM or VLM
edits mutate those bounded controls.  The deterministic compiler remains the
only layer that turns the graph into surfaces and legal/FAR proxy volumes.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable

from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall, VerbSequence


PROGRAM_SECTION_GRAPH_SCHEMA = "arr.maas.program_section_graph.v1"
PROGRAM_SECTION_GRAPH_NOTE_PREFIX = "program_section_graph_json="

_RELATIONS = {"input", "deform", "attach", "subtract", "monitor"}
_ROOF_OPERATORS = {
    "ridge_roof",
    "folded_roof",
    "sawtooth_roof",
    "stepped_section",
    "flat_roof",
    "shed_roof",
    "barrel_roof",
}
_DEFAULT_ROOF_CONTROLS = {
    "ridge_roof": [[0.0, 0.66], [0.5, 1.0], [1.0, 0.66]],
    "folded_roof": [[0.0, 0.62], [0.28, 0.96], [0.52, 0.70], [0.76, 1.0], [1.0, 0.64]],
    "sawtooth_roof": [[0.0, 0.64], [0.20, 0.94], [0.23, 0.62], [0.50, 0.98], [0.53, 0.64], [0.80, 0.92], [0.83, 0.66], [1.0, 0.86]],
    "stepped_section": [[0.0, 0.60], [0.30, 0.60], [0.34, 0.78], [0.62, 0.78], [0.66, 0.96], [1.0, 0.96]],
    "flat_roof": [[0.0, 0.82], [0.5, 0.82], [1.0, 0.82]],
    "shed_roof": [[0.0, 0.56], [0.5, 0.76], [1.0, 0.96]],
    "barrel_roof": [[0.0, 0.56], [0.20, 0.82], [0.5, 1.0], [0.80, 0.82], [1.0, 0.56]],
}
_OPERATORS = _ROOF_OPERATORS | {
    "long_span_hall",
    "service_spine",
    "carved_entry",
    "entry_canopy",
    "daylight_monitor",
}
_ADDITIVE = {"branch", "expand", "extrude", "inflate", "merge"}
_DISPLACE = {
    "bend", "interlock", "intersect", "lift", "lodge", "overlap", "rotate",
    "shift", "skew", "split", "twist",
}
_SUBTRACTIVE = {
    "carve", "compress", "embed", "extract", "fracture", "grade", "inscribe",
    "notch", "pinch", "puncture", "shear", "taper",
}


@dataclass(frozen=True)
class ProgramSectionGraphEdit:
    operation: str
    target_node_id: str
    parameter_name: str
    numeric_value: float | None = None
    control_index: int | None = None
    rationale: str = ""
    operator_value: str | None = None


def validate_program_section_graph(graph: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if graph.get("schema_version") != PROGRAM_SECTION_GRAPH_SCHEMA:
        errors.append("unsupported program section graph schema")
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return [*errors, "program section graph nodes are required"]
    node_ids = [str(node.get("node_id") or "") for node in nodes if isinstance(node, dict)]
    if len(node_ids) != len(nodes) or any(not node_id for node_id in node_ids):
        errors.append("every program section node requires node_id")
    if len(node_ids) != len(set(node_ids)):
        errors.append("duplicate program section node id")
    dominant = [node for node in nodes if node.get("role") == "dominant_hall"]
    if len(dominant) != 1 or dominant[0].get("operator") != "long_span_hall":
        errors.append("program section graph requires exactly one dominant long-span hall")
    known: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("node_id") or "")
        operator = str(node.get("operator") or "")
        relation = str(node.get("relation") or "")
        parent_id = node.get("parent_id")
        component_role = str(node.get("component_role") or "")
        if operator not in _OPERATORS:
            errors.append(f"node {node_id}: unsupported operator {operator!r}")
        if relation not in _RELATIONS:
            errors.append(f"node {node_id}: unsupported relation {relation!r}")
        if parent_id is not None and str(parent_id) not in known:
            errors.append(f"node {node_id}: parent must precede child")
        if not component_role:
            errors.append(f"node {node_id}: component_role is required")
        params = node.get("params") if isinstance(node.get("params"), dict) else {}
        if operator in _ROOF_OPERATORS:
            controls = params.get("section_controls")
            if not _valid_section_controls(controls):
                errors.append(f"node {node_id}: section_controls must be 3-10 ordered normalized pairs")
        known.add(node_id)
    if len(nodes) > 6:
        errors.append("program section graph exceeds six-node early-massing budget")
    return errors


def program_section_graph_note(graph: dict[str, Any]) -> str:
    errors = validate_program_section_graph(graph)
    if errors:
        raise ValueError("invalid program section graph: " + "; ".join(errors))
    return PROGRAM_SECTION_GRAPH_NOTE_PREFIX + json.dumps(
        graph,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def program_section_graph_from_sequence(sequence: VerbSequence) -> dict[str, Any]:
    for note in reversed(sequence.notes):
        if not note.startswith(PROGRAM_SECTION_GRAPH_NOTE_PREFIX):
            continue
        try:
            graph = json.loads(note[len(PROGRAM_SECTION_GRAPH_NOTE_PREFIX):])
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return graph if not validate_program_section_graph(graph) else {}
    return {}


def replace_program_section_graph_note(
    notes: Iterable[str],
    graph: dict[str, Any],
) -> tuple[str, ...]:
    return tuple(
        note for note in notes if not note.startswith(PROGRAM_SECTION_GRAPH_NOTE_PREFIX)
    ) + (program_section_graph_note(graph),)


def mutate_program_section_sequence(
    sequence: VerbSequence,
    edits: Iterable[ProgramSectionGraphEdit],
    *,
    director: str,
    name_suffix: str,
) -> VerbSequence:
    """Return a new seed from agent-authored typed section-graph edits.

    This deliberately does not define a completed building template.  The
    source program roles and normalized assembly remain reusable; an agent,
    VLM critic, or BOOK director supplies only bounded graph mutations.
    """
    graph = program_section_graph_from_sequence(sequence)
    if not graph:
        return sequence
    mutated = apply_program_section_graph_edits(graph, edits)
    mutated["agent_director"] = str(director or "typed_graph_agent")
    return VerbSequence(
        name=f"{sequence.name}__agent_{name_suffix}",
        label=sequence.label,
        calls=sequence.calls,
        notes=replace_program_section_graph_note(sequence.notes, mutated),
    )


def apply_program_section_graph_edits(
    graph: dict[str, Any],
    edits: Iterable[ProgramSectionGraphEdit],
) -> dict[str, Any]:
    """Apply bounded typed edits shared by BOOK, LLM and VLM directors."""
    result = deepcopy(graph)
    nodes = {str(node.get("node_id") or ""): node for node in result.get("nodes") or []}
    trace: list[dict[str, Any]] = list(result.get("mutation_trace") or [])
    for edit in edits:
        node = nodes.get(edit.target_node_id)
        if node is None or edit.operation not in {
            "set_parameter", "set_section_control", "replace_roof_operator",
        }:
            continue
        params = node.setdefault("params", {})
        if edit.operation == "replace_roof_operator":
            current_operator = str(node.get("operator") or "")
            replacement = str(edit.operator_value or "")
            if current_operator not in _ROOF_OPERATORS or replacement not in _ROOF_OPERATORS:
                continue
            node["operator"] = replacement
            # Operator replacement is a topology mutation, not a label swap:
            # reset the normalized section genotype to the replacement's
            # executable default before any bounded point edits are applied.
            params["section_controls"] = deepcopy(_DEFAULT_ROOF_CONTROLS[replacement])
            params["rise_ratio"] = round(
                max(height for _position, height in _DEFAULT_ROOF_CONTROLS[replacement])
                - min(height for _position, height in _DEFAULT_ROOF_CONTROLS[replacement]),
                4,
            )
        elif edit.operation == "set_section_control":
            controls = deepcopy(params.get("section_controls") or [])
            index = int(edit.control_index if edit.control_index is not None else -1)
            if index <= 0 or index >= len(controls) - 1 or edit.numeric_value is None:
                continue
            controls[index][1] = round(_bounded(edit.numeric_value, 0.42, 1.0), 4)
            if not _valid_section_controls(controls):
                continue
            params["section_controls"] = controls
        else:
            if edit.numeric_value is None or edit.parameter_name not in {
                "rise_ratio", "depth_scale", "width_scale", "height_scale",
                "shift_ratio", "monitor_height_ratio",
            }:
                continue
            low, high = {
                "rise_ratio": (0.08, 0.42),
                "depth_scale": (0.72, 1.28),
                "width_scale": (0.72, 1.28),
                "height_scale": (0.72, 1.18),
                "shift_ratio": (-0.18, 0.18),
                "monitor_height_ratio": (0.04, 0.24),
            }[edit.parameter_name]
            params[edit.parameter_name] = round(_bounded(edit.numeric_value, low, high), 4)
        trace.append({
            "operation": edit.operation,
            "target_node_id": edit.target_node_id,
            "parameter_name": edit.parameter_name,
            "control_index": edit.control_index,
            "numeric_value": edit.numeric_value,
            "operator_value": edit.operator_value,
            "rationale": edit.rationale,
        })
    result["mutation_trace"] = trace
    errors = validate_program_section_graph(result)
    if errors:
        raise ValueError("invalid mutated program section graph: " + "; ".join(errors))
    return result


def mutate_program_section_graph_for_book(
    graph: dict[str, Any],
    calls: Iterable[VerbCall],
    *,
    scope_label: str,
    scope_fraction: float,
) -> dict[str, Any]:
    """Translate one BOOK sentence into small, bounded section-graph edits."""
    execution = tuple(calls)
    if not graph or not execution:
        return graph
    verbs = tuple(call.verb for call in execution)
    additive = sum(verb in _ADDITIVE for verb in verbs)
    displaced = sum(verb in _DISPLACE for verb in verbs)
    subtractive = sum(verb in _SUBTRACTIVE for verb in verbs)
    strength = 0.55 + 0.45 * max(1.0 / 16.0, min(1.0, float(scope_fraction))) ** 0.5
    edits: list[ProgramSectionGraphEdit] = []
    for node in graph.get("nodes") or []:
        node_id = str(node.get("node_id") or "")
        operator = str(node.get("operator") or "")
        params = node.get("params") if isinstance(node.get("params"), dict) else {}
        if operator in _ROOF_OPERATORS:
            controls = params.get("section_controls") or []
            for index in range(1, len(controls) - 1):
                current = float(controls[index][1])
                alternating = 1.0 if index % 2 else -1.0
                delta = strength * (
                    additive * 0.018
                    + displaced * alternating * 0.014
                    - subtractive * (1.0 if current < 0.78 else 0.35) * 0.018
                )
                if abs(delta) >= 1e-6:
                    edits.append(ProgramSectionGraphEdit(
                        "set_section_control",
                        node_id,
                        "section_controls",
                        round(current + delta, 4),
                        index,
                        f"BOOK {' + '.join(verbs)} mutates {scope_label} roof section",
                    ))
        elif operator == "service_spine":
            current = float(params.get("depth_scale") or 1.0)
            edits.append(ProgramSectionGraphEdit(
                "set_parameter", node_id, "depth_scale",
                round(current + strength * (additive - subtractive) * 0.025, 4),
                rationale="retain a subordinate service spine while the hall changes",
            ))
        elif operator == "carved_entry":
            current = float(params.get("depth_scale") or 1.0)
            edits.append(ProgramSectionGraphEdit(
                "set_parameter", node_id, "depth_scale",
                round(current + strength * (subtractive + displaced * 0.35) * 0.035, 4),
                rationale="couple the entry carve to subtractive/displaced BOOK intent",
            ))
    result = apply_program_section_graph_edits(graph, edits)
    result["book_mutation"] = {
        "operations": list(verbs),
        "scope_label": scope_label,
        "scope_fraction": round(float(scope_fraction), 6),
        "edit_count": len(edits),
    }
    return result


def _valid_section_controls(value: Any) -> bool:
    if not isinstance(value, list) or not 3 <= len(value) <= 10:
        return False
    positions: list[float] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            return False
        try:
            position, height = float(item[0]), float(item[1])
        except (TypeError, ValueError):
            return False
        if not 0.0 <= position <= 1.0 or not 0.42 <= height <= 1.0:
            return False
        positions.append(position)
    return positions == sorted(positions) and positions[0] <= 0.02 and positions[-1] >= 0.98


def _bounded(value: Any, low: float, high: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


__all__ = [
    "PROGRAM_SECTION_GRAPH_NOTE_PREFIX",
    "PROGRAM_SECTION_GRAPH_SCHEMA",
    "ProgramSectionGraphEdit",
    "apply_program_section_graph_edits",
    "mutate_program_section_graph_for_book",
    "mutate_program_section_sequence",
    "program_section_graph_from_sequence",
    "program_section_graph_note",
    "replace_program_section_graph_note",
    "validate_program_section_graph",
]
