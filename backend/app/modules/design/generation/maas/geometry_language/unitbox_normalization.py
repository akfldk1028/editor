"""Canonical one-UnitBox authority for box-derived MASS programs.

Authored box dimensions are parameters, not independent primitive authority.
This pass rewrites every reachable Box into an affine instance of one 1/1
UnitBox while preserving node references and the recursive Boolean/modifier
program above those instances.
"""

from __future__ import annotations

from dataclasses import replace
from math import isfinite
from typing import Any

from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import compose_matrix4, matrix4_to_lists, scale_matrix4, translation_matrix4
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram, surface_parameter_issues


_UNIT_PARAMETERS = {"width": 1.0, "depth": 1.0, "height": 1.0}


def normalize_unitbox_program(program: GeometryProgram) -> GeometryProgram:
    """Return an equivalent program with at most one box primitive authority."""

    box_nodes = [
        node for node in program.nodes
        if node.kind == "primitive" and node.operator == "box"
    ]
    if not box_nodes:
        return program
    if any(surface_parameter_issues(node) for node in program.nodes):
        # Preserve invalid authored fields for the semantic validator instead
        # of erasing them while canonicalizing a dimensional box.
        return program
    if not all(_has_positive_finite_dimensions(node) for node in box_nodes):
        # Leave malformed author input untouched so the ordinary semantic
        # validator reports its precise non-positive/non-finite issue.
        return program
    if len(box_nodes) == 1 and _is_unitbox(box_nodes[0]):
        return program

    canonical_source = next((node for node in box_nodes if _is_unitbox(node)), box_nodes[0])
    canonical_id = canonical_source.id
    occupied_ids = {node.id for node in program.nodes}
    first_instance_id = _unique_id(f"{canonical_id}_matrix4", occupied_ids)
    replacement_ids: dict[str, str] = {}
    replacement_nodes: dict[str, GeometryNode | None] = {}

    canonical_instance_needed = not _is_unitbox(canonical_source)
    if canonical_instance_needed:
        replacement_ids[canonical_id] = first_instance_id

    for node in box_nodes:
        if node.id == canonical_id:
            continue
        if _is_unitbox(node):
            replacement_ids[node.id] = canonical_id
            replacement_nodes[node.id] = None
            continue
        replacement_nodes[node.id] = _matrix_instance(
            node,
            canonical_id=canonical_id,
            node_id=node.id,
        )

    canonical = GeometryNode(
        id=canonical_id,
        kind="primitive",
        operator="box",
        parameters=dict(_UNIT_PARAMETERS),
        semantic_role="base_authority",
        provenance={
            **canonical_source.provenance,
            "canonical_base_model": "1/1 UnitBox",
            "unitbox_authority": True,
        },
    )
    canonical_instance = (
        _matrix_instance(
            canonical_source,
            canonical_id=canonical_id,
            node_id=first_instance_id,
        )
        if canonical_instance_needed
        else None
    )

    normalized_nodes: list[GeometryNode] = []
    for node in program.nodes:
        if node.id == canonical_id:
            normalized_nodes.append(canonical)
            if canonical_instance is not None:
                normalized_nodes.append(canonical_instance)
            continue
        if node.id in replacement_nodes:
            replacement = replacement_nodes[node.id]
            if replacement is not None:
                normalized_nodes.append(replacement)
            continue
        normalized_nodes.append(replace(
            node,
            inputs=tuple(replacement_ids.get(input_id, input_id) for input_id in node.inputs),
        ))

    metadata = {
        **program.metadata,
        "base_volume_authority": "1/1 UnitBox",
        "box_instance_contract": "shared_unitbox_matrix4",
    }
    return GeometryProgram(
        nodes=tuple(normalized_nodes),
        root_id=replacement_ids.get(program.root_id, program.root_id),
        name=program.name,
        schema_version=program.schema_version,
        metadata=metadata,
        execution_contract=program.execution_contract,
    )


def _matrix_instance(
    source: GeometryNode,
    *,
    canonical_id: str,
    node_id: str,
) -> GeometryNode:
    width = float(source.parameters.get("width", 1.0))
    depth = float(source.parameters.get("depth", 1.0))
    height = float(source.parameters.get("height", 1.0))
    scale = scale_matrix4((width, depth, height))
    matrix = (
        compose_matrix4(
            scale,
            translation_matrix4((-width / 2.0, -depth / 2.0, -height / 2.0)),
        )
        if bool(source.parameters.get("center", False))
        else scale
    )
    return GeometryNode(
        id=node_id,
        kind="transform",
        operator="matrix4",
        inputs=(canonical_id,),
        parameters={"matrix4": matrix4_to_lists(matrix)},
        semantic_role=source.semantic_role,
        provenance={
            **source.provenance,
            "canonical_base_model": "1/1 UnitBox",
            "authored_operator": "box",
            "authored_box_parameters": _authored_box_parameters(source.parameters),
        },
    )


def _authored_box_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        key: parameters[key]
        for key in ("width", "depth", "height", "center")
        if key in parameters
    }


def _is_unitbox(node: GeometryNode) -> bool:
    parameters = node.parameters
    return (
        not bool(parameters.get("center", False))
        and float(parameters.get("width", 1.0)) == 1.0
        and float(parameters.get("depth", 1.0)) == 1.0
        and float(parameters.get("height", 1.0)) == 1.0
    )


def _has_positive_finite_dimensions(node: GeometryNode) -> bool:
    try:
        dimensions = tuple(
            float(node.parameters.get(key, 1.0))
            for key in ("width", "depth", "height")
        )
    except (TypeError, ValueError):
        return False
    return all(isfinite(value) and value > 0.0 for value in dimensions)


def _unique_id(preferred: str, occupied: set[str]) -> str:
    if preferred not in occupied:
        return preferred
    suffix = 2
    while f"{preferred}_{suffix}" in occupied:
        suffix += 1
    return f"{preferred}_{suffix}"


__all__ = ["normalize_unitbox_program"]
