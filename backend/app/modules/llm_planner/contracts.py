from __future__ import annotations

import json
import math
from dataclasses import asdict
from typing import Any

from backend.app.schemas.llm import (
    SUPPORTED_USE_TYPES,
    BuildingFloorAssignments,
    FloorAssignment,
    ProgramEdgeProposal,
    ProgramGraphProposal,
    ProgramNodeProposal,
)


class ContractValidationError(ValueError):
    pass


def parse_building_floor_assignments_json(
    payload: str,
) -> BuildingFloorAssignments:
    document = _load_document(payload)
    _require_fields(
        document,
        required={"project_id", "assignments"},
        label="building floor assignments",
    )
    project_id = _require_text(document["project_id"], "project_id")
    assignments_payload = _require_list(document["assignments"], "assignments")
    if not assignments_payload:
        raise ContractValidationError("assignments must not be empty")

    assignments: list[FloorAssignment] = []
    seen_floors: set[int] = set()
    for index, value in enumerate(assignments_payload):
        label = f"assignments[{index}]"
        item = _require_object(value, label)
        _require_fields(item, required={"floor_index", "use_type"}, label=label)
        floor_index = _require_positive_int(item["floor_index"], f"{label}.floor_index")
        use_type = _require_use_type(item["use_type"], f"{label}.use_type")
        if floor_index in seen_floors:
            raise ContractValidationError(f"duplicate floor_index {floor_index}")
        seen_floors.add(floor_index)
        assignments.append(FloorAssignment(floor_index=floor_index, use_type=use_type))

    return BuildingFloorAssignments(
        project_id=project_id,
        assignments=tuple(sorted(assignments, key=lambda item: item.floor_index)),
    )


def parse_program_graph_proposal_json(payload: str) -> ProgramGraphProposal:
    document = _load_document(payload)
    _require_fields(
        document,
        required={"project_id", "floor_index", "use_type", "nodes", "edges"},
        label="program graph proposal",
    )
    project_id = _require_text(document["project_id"], "project_id")
    floor_index = _require_positive_int(document["floor_index"], "floor_index")
    use_type = _require_use_type(document["use_type"], "use_type")
    nodes = _parse_nodes(document["nodes"])
    edges = _parse_edges(document["edges"], {node.node_id for node in nodes})

    core_count = sum(
        node.node_id == "core" and node.space_type == "core" for node in nodes
    )
    if core_count != 1:
        raise ContractValidationError(
            "program graph proposal must contain exactly one core node"
        )

    return ProgramGraphProposal(
        project_id=project_id,
        floor_index=floor_index,
        use_type=use_type,
        nodes=tuple(sorted(nodes, key=lambda node: node.node_id)),
        edges=tuple(
            sorted(
                edges,
                key=lambda edge: (
                    edge.source,
                    edge.target,
                    edge.relation,
                    edge.weight,
                ),
            )
        ),
    )


def dump_building_floor_assignments_json(
    assignments: BuildingFloorAssignments,
) -> str:
    if not isinstance(assignments, BuildingFloorAssignments):
        raise TypeError("assignments must be BuildingFloorAssignments")
    return _canonical_json(asdict(assignments))


def dump_program_graph_proposal_json(proposal: ProgramGraphProposal) -> str:
    if not isinstance(proposal, ProgramGraphProposal):
        raise TypeError("proposal must be ProgramGraphProposal")
    return _canonical_json(asdict(proposal))


def _parse_nodes(value: Any) -> list[ProgramNodeProposal]:
    nodes_payload = _require_list(value, "nodes")
    if not nodes_payload:
        raise ContractValidationError("nodes must not be empty")

    nodes: list[ProgramNodeProposal] = []
    seen_ids: set[str] = set()
    for index, value in enumerate(nodes_payload):
        label = f"nodes[{index}]"
        item = _require_object(value, label)
        _require_fields(
            item,
            required={"node_id", "space_type", "target_area"},
            optional={"min_area", "max_area", "frontage_required"},
            label=label,
        )
        node_id = _require_text(item["node_id"], f"{label}.node_id")
        if node_id in seen_ids:
            raise ContractValidationError(f"duplicate node_id '{node_id}'")
        seen_ids.add(node_id)

        target_area = _require_positive_number(
            item["target_area"], f"{label}.target_area"
        )
        min_area = _optional_positive_number(item, "min_area", label)
        max_area = _optional_positive_number(item, "max_area", label)
        if min_area is not None and min_area > target_area:
            raise ContractValidationError(
                f"{label}.min_area must not exceed target_area"
            )
        if max_area is not None and max_area < target_area:
            raise ContractValidationError(
                f"{label}.max_area must not be below target_area"
            )
        frontage_required = item.get("frontage_required", False)
        if type(frontage_required) is not bool:
            raise ContractValidationError(
                f"{label}.frontage_required must be a boolean"
            )
        nodes.append(
            ProgramNodeProposal(
                node_id=node_id,
                space_type=_require_text(
                    item["space_type"], f"{label}.space_type"
                ),
                target_area=target_area,
                min_area=min_area,
                max_area=max_area,
                frontage_required=frontage_required,
            )
        )
    return nodes


def _parse_edges(
    value: Any,
    node_ids: set[str],
) -> list[ProgramEdgeProposal]:
    edges_payload = _require_list(value, "edges")
    allowed_endpoints = node_ids | {"street"}
    edges: list[ProgramEdgeProposal] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for index, value in enumerate(edges_payload):
        label = f"edges[{index}]"
        item = _require_object(value, label)
        _require_fields(
            item,
            required={"source", "target", "relation"},
            optional={"weight"},
            label=label,
        )
        source = _require_text(item["source"], f"{label}.source")
        target = _require_text(item["target"], f"{label}.target")
        relation = _require_text(item["relation"], f"{label}.relation")
        if source not in allowed_endpoints or target not in allowed_endpoints:
            raise ContractValidationError(f"{label} has an unknown endpoint")
        if source == target:
            raise ContractValidationError(f"{label} must not be a self-edge")
        edge_key = (source, target, relation)
        if edge_key in seen_edges:
            raise ContractValidationError(f"{label} duplicates an existing edge")
        seen_edges.add(edge_key)
        edges.append(
            ProgramEdgeProposal(
                source=source,
                target=target,
                relation=relation,
                weight=_require_positive_number(
                    item.get("weight", 1.0), f"{label}.weight"
                ),
            )
        )
    return edges


def _load_document(payload: str) -> dict[str, Any]:
    if not isinstance(payload, str):
        raise ContractValidationError("payload must be a JSON string")
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda constant: _reject_json_constant(constant),
        )
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        if isinstance(error, ContractValidationError):
            raise
        raise ContractValidationError(f"invalid JSON: {error}") from error
    return _require_object(value, "document")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ContractValidationError(f"duplicate JSON field '{key}'")
        value[key] = item
    return value


def _reject_json_constant(constant: str) -> None:
    raise ContractValidationError(f"invalid JSON constant '{constant}'")


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractValidationError(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractValidationError(f"{label} must be an array")
    return value


def _require_fields(
    value: dict[str, Any],
    *,
    required: set[str],
    label: str,
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    missing = sorted(required - value.keys())
    if missing:
        raise ContractValidationError(
            f"{label} is missing required fields: {', '.join(missing)}"
        )
    unknown = sorted(value.keys() - required - optional)
    if unknown:
        raise ContractValidationError(
            f"{label} has unknown fields: {', '.join(unknown)}"
        )


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{label} must be a non-empty string")
    if value != value.strip():
        raise ContractValidationError(f"{label} must not have surrounding whitespace")
    return value


def _require_positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ContractValidationError(f"{label} must be a positive integer")
    return value


def _require_positive_number(value: Any, label: str) -> float:
    if type(value) not in (int, float):
        raise ContractValidationError(f"{label} must be a finite and positive number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ContractValidationError(f"{label} must be a finite and positive number")
    return number


def _optional_positive_number(
    value: dict[str, Any],
    field: str,
    label: str,
) -> float | None:
    if field not in value or value[field] is None:
        return None
    return _require_positive_number(value[field], f"{label}.{field}")


def _require_use_type(value: Any, label: str) -> str:
    use_type = _require_text(value, label)
    if use_type not in SUPPORTED_USE_TYPES:
        supported = ", ".join(sorted(SUPPORTED_USE_TYPES))
        raise ContractValidationError(
            f"{label} has unsupported use_type '{use_type}'; expected one of: {supported}"
        )
    return use_type


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
