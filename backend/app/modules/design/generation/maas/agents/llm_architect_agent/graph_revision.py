"""Apply validated VLM/A2A critic edits to the architectural genotype."""

from __future__ import annotations

from dataclasses import replace

from shapely.geometry import Polygon

from backend.app.modules.design.generation.maas.agents.orchestrator.generative_loop import CriticDirective
from backend.app.modules.design.generation.maas.grammar.component_graph import MassComponentGraph, MassComponentNode, graph_with_nodes
from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall, VerbSequence
from backend.app.modules.design.generation.maas.grammar.vocab import SUPPORTED_VERBS
from backend.app.modules.design.generation.maas.grammar.parameter_schema import CATEGORICAL_PARAMETER_VALUES, PARAMETER_BOUNDS, PARAMETERS_BY_VERB, bounded_parameter


ALLOWED_ROLES = {"primary", "support", "void", "connector"}


def _edit_parameter_value(edit, verb: str):
    """Return a validated typed value, or ``None`` for an invalid edit."""
    name = edit.parameter_name
    if name not in PARAMETERS_BY_VERB.get(verb, ()):
        return None
    if name in PARAMETER_BOUNDS:
        return bounded_parameter(name, edit.numeric_value)
    allowed = CATEGORICAL_PARAMETER_VALUES.get(name)
    value = str(edit.string_value or "").strip().lower()
    return value if allowed and value in allowed else None


def _has_followup_parameter(
    edits: tuple,
    start_index: int,
    *,
    node_id: str,
    verb: str,
) -> bool:
    """Topology edits must carry an authored parameter, not empty defaults."""
    return any(
        later.operation == "set_parameter"
        and later.target_node_id == node_id
        and _edit_parameter_value(later, verb) is not None
        for later in edits[start_index + 1:]
    )


def apply_critic_graph_mutations(
    graph: MassComponentGraph,
    directive: CriticDirective,
) -> tuple[MassComponentGraph, ...]:
    """Apply bounded edits without crossing the lossy flat-sequence boundary."""
    nodes = list(graph.nodes)
    changed = False
    edits = tuple(directive.graph_edits)
    for edit_index, edit in enumerate(edits):
        operation = edit.operation
        index = next((i for i, node in enumerate(nodes) if node.node_id == edit.target_node_id), None)
        if operation == "set_control_point":
            if (
                index is None
                or nodes[index].role == "root"
                or nodes[index].operation.verb not in {"bend", "sloped_roof_mass", "taper"}
            ):
                continue
            node = nodes[index]
            control_field = (
                "plan_control_points"
                if node.operation.verb == "taper" and edit.parameter_name == "plan_control_points"
                else "control_points"
            )
            raw_controls = node.operation.params.get(control_field)
            minimum_count, maximum_count = ((3, 8) if control_field == "plan_control_points" else (4, 6))
            if not isinstance(raw_controls, list) or not minimum_count <= len(raw_controls) <= maximum_count:
                continue
            controls: list[list[float]] = []
            try:
                controls = [[float(point[0]), float(point[1])] for point in raw_controls]
            except (TypeError, ValueError, IndexError):
                continue
            point_index = int(edit.control_point_index)
            if point_index < 0 or point_index >= len(controls):
                continue
            if control_field == "plan_control_points":
                new_point = [
                    round(max(0.03, min(0.97, float(edit.control_point_u))), 4),
                    round(max(0.03, min(0.97, float(edit.control_point_v))), 4),
                ]
            else:
                lower_u = 0.03 if point_index == 0 else controls[point_index - 1][0] + 0.02
                upper_u = 0.97 if point_index + 1 == len(controls) else controls[point_index + 1][0] - 0.02
                if lower_u > upper_u:
                    continue
                new_point = [
                    round(max(lower_u, min(upper_u, float(edit.control_point_u))), 4),
                    round(max(0.12, min(0.88, float(edit.control_point_v))), 4),
                ]
            if new_point == controls[point_index]:
                continue
            candidate_controls = list(controls)
            candidate_controls[point_index] = new_point
            if control_field == "plan_control_points":
                polygon = Polygon(candidate_controls)
                if not polygon.is_valid or polygon.area < 0.04:
                    continue
            controls = candidate_controls
            params = dict(node.operation.params)
            params[control_field] = controls
            nodes[index] = replace(node, operation=VerbCall(node.operation.verb, params))
            changed = True
        elif operation == "set_parameter":
            if (
                index is None
                or nodes[index].role == "root"
            ):
                continue
            node = nodes[index]
            value = _edit_parameter_value(edit, node.operation.verb)
            if value is None:
                continue
            params = dict(node.operation.params)
            params[edit.parameter_name] = value
            nodes[index] = replace(node, operation=VerbCall(node.operation.verb, params))
            changed = True
        elif operation == "replace_operation":
            if (
                index is None
                or nodes[index].role == "root"
                or edit.verb not in SUPPORTED_VERBS
                or edit.verb == "base"
                or not _has_followup_parameter(
                    edits,
                    edit_index,
                    node_id=nodes[index].node_id,
                    verb=edit.verb,
                )
            ):
                continue
            node = nodes[index]
            compatible = {
                key: value
                for key, value in node.operation.params.items()
                if key in PARAMETERS_BY_VERB.get(edit.verb, ())
            }
            nodes[index] = replace(node, operation=VerbCall(edit.verb, compatible))
            changed = True
        elif operation == "remove_optional":
            if index is None or not nodes[index].optional or any(node.parent_id == nodes[index].node_id for node in nodes):
                continue
            nodes.pop(index)
            changed = True
        elif operation == "reparent":
            ids = {node.node_id for node in nodes}
            if (
                index is None
                or nodes[index].role == "root"
                or edit.parent_node_id not in ids
                or edit.parent_node_id == nodes[index].node_id
            ):
                continue
            parent_index = next(i for i, node in enumerate(nodes) if node.node_id == edit.parent_node_id)
            if parent_index >= index:
                continue
            nodes[index] = replace(nodes[index], parent_id=edit.parent_node_id)
            changed = True
        elif operation == "add_operation":
            ids = {node.node_id for node in nodes}
            if (
                not edit.node_id or edit.node_id in ids or edit.parent_node_id not in ids
                or edit.role not in ALLOWED_ROLES or edit.role == "primary"
                or edit.verb not in SUPPORTED_VERBS or edit.verb == "base"
                or len(nodes) >= 6
                or not _has_followup_parameter(
                    edits,
                    edit_index,
                    node_id=edit.node_id,
                    verb=edit.verb,
                )
            ):
                continue
            nodes.append(MassComponentNode(
                node_id=edit.node_id,
                role=edit.role,
                parent_id=edit.parent_node_id,
                optional=edit.role in {"support", "connector"},
                operation=VerbCall(edit.verb, {}),
                constraints={"inside_legal_envelope": True, "critic_authored": True},
                relation="subtract" if edit.role == "void" else "connect" if edit.role == "connector" else "attach",
            ))
            changed = True
    if not changed:
        return ()
    revised = graph_with_nodes(graph, nodes, suffix="__a2a_critic_revision")
    if revised.validate():
        return ()
    return (revised,)


def apply_critic_graph_edits(sequence: VerbSequence, directive: CriticDirective) -> tuple[VerbSequence, ...]:
    """Legacy adapter that transports the complete V2 graph envelope."""
    from backend.app.modules.design.generation.maas.grammar.component_graph import graph_from_sequence

    revised = apply_critic_graph_mutations(graph_from_sequence(sequence), directive)
    return tuple(graph.to_sequence(name=graph.name) for graph in revised)


__all__ = ["apply_critic_graph_edits", "apply_critic_graph_mutations"]
