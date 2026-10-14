"""Normalize authored affine states to explicit Matrix4 BaseVolumes."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Any

from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import compose_matrix4, identity_matrix4, matrix4_for_transform, matrix4_to_lists
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program, resolve_solid_pivot
from backend.app.modules.design.generation.maas.geometry_language.unitbox_normalization import normalize_unitbox_program


AFFINE_SHORTHANDS = frozenset({
    "scale",
    "rotate",
    "translate",
    "mirror",
    "shear",
})
_UNIT_PARAMETERS = {"width": 1.0, "depth": 1.0, "height": 1.0}
BASE_FORM_OPERATORS = frozenset({"ellipsoidize", "tetrahedralize"})


def normalize_affine_basevolume_program(
    program: GeometryProgram,
) -> GeometryProgram:
    """Return one-UnitBox geometry with explicit affine Matrix4 nodes."""

    unitbox_program = normalize_unitbox_program(program)
    lowered = _lower_affine_shorthands(unitbox_program)
    with_basevolume = _ensure_basevolume_matrix(lowered)
    composed = _compose_single_consumer_matrix_chains(with_basevolume)
    _validate_affine_authority(composed)
    return replace(
        composed,
        metadata={
            **composed.metadata,
            "base_volume_authority": "1/1 UnitBox",
            "affine_authority": "explicit_matrix4",
        },
    )


def _lower_affine_shorthands(program: GeometryProgram) -> GeometryProgram:
    converted: list[GeometryNode] = []
    converted_by_id: dict[str, GeometryNode] = {}
    for node in program.topological_nodes():
        if node.kind != "transform" or node.operator not in AFFINE_SHORTHANDS:
            converted.append(node)
            converted_by_id[node.id] = node
            continue
        parameters = dict(node.parameters)
        if str(parameters.get("pivot") or "").lower() in {
            "center",
            "centroid",
        }:
            parameters["pivot"] = _resolved_pivot(
                program,
                converted,
                converted_by_id,
                node.inputs[0],
                parameters["pivot"],
            )
        matrix = matrix4_for_transform(node.operator, parameters)
        lowered = replace(
            node,
            operator="matrix4",
            parameters={"matrix4": matrix4_to_lists(matrix)},
            provenance={
                **node.provenance,
                "lowered_affine_operator": node.operator,
            },
        )
        converted.append(lowered)
        converted_by_id[node.id] = lowered
    return replace(
        program,
        nodes=tuple(converted_by_id[node.id] for node in program.nodes),
    )


def _resolved_pivot(
    program: GeometryProgram,
    converted: list[GeometryNode],
    converted_by_id: dict[str, GeometryNode],
    input_id: str,
    pivot: str,
) -> tuple[float, float, float]:
    ancestor_ids: set[str] = set()

    def collect(node_id: str) -> None:
        if node_id in ancestor_ids:
            return
        ancestor_ids.add(node_id)
        for parent_id in converted_by_id[node_id].inputs:
            collect(parent_id)

    collect(input_id)
    prefix = GeometryProgram(
        nodes=tuple(
            node for node in converted if node.id in ancestor_ids
        ),
        root_id=input_id,
        name=f"{program.name}__affine_pivot_probe",
    )
    compilation = compile_geometry_program(prefix)
    if compilation.status != "compiled":
        raise ValueError(f"cannot resolve affine pivot for {input_id}")
    if str(pivot).lower() == "centroid":
        return resolve_solid_pivot(compilation._solid, pivot, input_id)
    bounds = compilation.metrics.get("bounds")
    if not bounds or len(bounds) != 2:
        raise ValueError(f"cannot resolve affine pivot for {input_id}")
    return tuple(
        (float(bounds[0][axis]) + float(bounds[1][axis])) / 2.0
        for axis in range(3)
    )


def _ensure_basevolume_matrix(program: GeometryProgram) -> GeometryProgram:
    unitbox = _canonical_unitbox(program)
    matrices = [node for node in program.nodes if node.operator == "matrix4"]
    if (
        len(matrices) == 1
        and _matrix_follows_unitbox_base_form_chain(
            program, unitbox.id, matrices[0]
        )
    ):
        return program
    consumers = [
        node for node in program.nodes if unitbox.id in node.inputs
    ]
    if consumers and all(node.operator == "matrix4" for node in consumers):
        return program
    if program.root_id != unitbox.id and not consumers:
        raise ValueError("canonical UnitBox has no BaseVolume descendant")

    occupied = {node.id for node in program.nodes}
    matrix_id = _unique_id("canonical_basevolume_matrix4", occupied)
    matrix = GeometryNode(
        matrix_id,
        "transform",
        "matrix4",
        inputs=(unitbox.id,),
        parameters={"matrix4": matrix4_to_lists(identity_matrix4())},
        semantic_role="base_volume",
        provenance={
            "authority": "canonical_unitbox",
            "base_volume_matrix": True,
        },
    )
    nodes: list[GeometryNode] = []
    for node in program.nodes:
        nodes.append(node)
        if node.id == unitbox.id:
            nodes.append(matrix)
    nodes = [
        replace(
            node,
            inputs=tuple(
                matrix_id
                if input_id == unitbox.id and node.operator != "matrix4"
                else input_id
                for input_id in node.inputs
            ),
        )
        if node.id != matrix_id
        else node
        for node in nodes
    ]
    return replace(
        program,
        nodes=tuple(nodes),
        root_id=matrix_id if program.root_id == unitbox.id else program.root_id,
    )


def _compose_single_consumer_matrix_chains(
    program: GeometryProgram,
) -> GeometryProgram:
    current = program
    while True:
        node_map = current.node_map
        consumer_counts = Counter(
            input_id
            for node in current.nodes
            for input_id in node.inputs
        )
        pair: tuple[GeometryNode, GeometryNode] | None = None
        for child in current.topological_nodes():
            if child.operator != "matrix4" or len(child.inputs) != 1:
                continue
            parent = node_map[child.inputs[0]]
            if (
                parent.operator == "matrix4"
                and len(parent.inputs) == 1
                and consumer_counts[parent.id] == 1
            ):
                pair = (parent, child)
                break
        if pair is None:
            return current
        parent, child = pair
        combined = compose_matrix4(
            parent.parameters["matrix4"],
            child.parameters["matrix4"],
        )
        parent_ids = list(
            parent.provenance.get("composed_matrix4_node_ids")
            or (parent.id,)
        )
        child_ids = list(
            child.provenance.get("composed_matrix4_node_ids")
            or (child.id,)
        )
        replacement = replace(
            child,
            inputs=parent.inputs,
            parameters={"matrix4": matrix4_to_lists(combined)},
            provenance={
                **parent.provenance,
                **child.provenance,
                "composed_matrix4_node_ids": [*parent_ids, *child_ids],
            },
        )
        current = replace(
            current,
            nodes=tuple(
                replacement if node.id == child.id else node
                for node in current.nodes
                if node.id != parent.id
            ),
        )


def _validate_affine_authority(program: GeometryProgram) -> None:
    unitbox = _canonical_unitbox(program)
    if any(
        node.kind == "transform" and node.operator in AFFINE_SHORTHANDS
        for node in program.nodes
    ):
        raise ValueError("affine shorthand remains after normalization")
    matrices = [node for node in program.nodes if node.operator == "matrix4"]
    # Exactly one matrix carries the BASE VOLUME's pose - that is the
    # authority this rule defends. Others may exist: an affine verb spoken
    # later in the sentence (BOOK's `skew` projects to `shear`, which lowers
    # to a matrix) is a modelling operation on a body that is already posed,
    # not a second claim about where the unit box sits. Demanding exactly one
    # matrix in the whole program conflated the two and refused every BOOK
    # sentence built on skew - one of the thirty base operatives - which is
    # why the exploration pipeline could not start.
    on_the_base_chain = [
        node for node in matrices
        if _matrix_follows_unitbox_base_form_chain(program, unitbox.id, node)
    ]
    # And at least one, not exactly one: a program may place the same unit box
    # several times - a bridge is two supports and a deck, each its own matrix
    # off the same box, which is what every multi-volume massing is. The
    # authority claim is that the box is ONE and every pose is explicit, not
    # that the building is one volume. Demanding a single matrix refused the
    # bridge and the interlocking discs outright.
    if not on_the_base_chain:
        raise ValueError("canonical UnitBox lacks an explicit BaseVolume Matrix4")


def _matrix_follows_unitbox_base_form_chain(
    program: GeometryProgram,
    unitbox_id: str,
    matrix: GeometryNode,
) -> bool:
    if len(matrix.inputs) != 1:
        return False
    current_id = matrix.inputs[0]
    visited: set[str] = set()
    while current_id != unitbox_id:
        if current_id in visited:
            return False
        visited.add(current_id)
        current = program.node_map.get(current_id)
        if (
            current is None
            or current.operator not in BASE_FORM_OPERATORS
            or len(current.inputs) != 1
        ):
            return False
        current_id = current.inputs[0]
    return True


def _canonical_unitbox(program: GeometryProgram) -> GeometryNode:
    unitboxes = [
        node
        for node in program.nodes
        if node.kind == "primitive"
        and node.operator == "box"
        and {
            key: float(node.parameters.get(key, 1.0))
            for key in _UNIT_PARAMETERS
        } == _UNIT_PARAMETERS
        and not bool(node.parameters.get("center", False))
    ]
    if len(unitboxes) != 1:
        raise ValueError(
            "affine authority requires exactly one canonical UnitBox"
        )
    return unitboxes[0]


def _unique_id(preferred: str, occupied: set[str]) -> str:
    if preferred not in occupied:
        return preferred
    suffix = 2
    while f"{preferred}_{suffix}" in occupied:
        suffix += 1
    return f"{preferred}_{suffix}"


__all__ = ["AFFINE_SHORTHANDS", "normalize_affine_basevolume_program"]
