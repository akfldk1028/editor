"""Focused phenotype contracts for bounded fresh MASS generation.

Most fresh families remain open-ended synthesis problems. A small number have
non-negotiable topological semantics that generic BOOK lowering cannot infer
from a label alone. This module owns only those narrow contracts so
``fresh_batch`` stays an orchestrator rather than another geometry monolith.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.programs import GeometryProgramBuilder

if TYPE_CHECKING:
    from backend.app.modules.design.generation.maas.fresh_batch import FreshMassSpec


def build_family_contract_program(
    spec: "FreshMassSpec",
    *,
    variation_offset: int,
) -> GeometryProgram | None:
    """Author a focused program when ``spec`` has a strict phenotype.

    Returning ``None`` delegates the family to the ordinary synthesis and BOOK
    projection path. All dimensions below are local UnitBox-relative ratios,
    never parcel or world coordinates.
    """

    if spec.spec_id != "radial-cross":
        return None
    return _build_common_hub_radial(spec, variation_offset=variation_offset)


def family_phenotype_issues(
    program: GeometryProgram,
    spec: "FreshMassSpec",
    *,
    compilation: Any | None = None,
) -> tuple[str, ...]:
    """Return structural and, when supplied, compiled phenotype violations."""

    if spec.spec_id != "radial-cross":
        return ()
    nodes = tuple(program.topological_nodes())
    by_id = {node.id: node for node in nodes}
    issues: list[str] = []
    unitboxes = [
        node
        for node in nodes
        if node.kind == "primitive"
        and node.operator == "box"
        and node.provenance.get("unitbox_authority") is True
    ]
    if len(unitboxes) != 1:
        issues.append("radial_requires_one_unitbox_authority")
        unitbox_id = ""
    else:
        unitbox_id = unitboxes[0].id

    forbidden = {
        node.operator
        for node in nodes
        if node.operator in {"bend", "book_rotate", "merge_related"}
    }
    if forbidden:
        issues.append("radial_forbids_bent_or_hinged_lowering")

    radial_nodes = [
        node
        for node in nodes
        if node.kind == "pattern" and node.operator == "radial_array"
    ]
    if len(radial_nodes) != 1:
        issues.append("radial_requires_one_radial_array")
        radial = None
    else:
        radial = radial_nodes[0]
        if int(radial.parameters.get("count", 0)) < 3:
            issues.append("radial_requires_three_plan_directions")

    root = by_id.get(program.root_id)
    if root is None or root.kind != "boolean" or root.operator != "union":
        issues.append("radial_requires_hub_union_root")
    elif radial is not None and radial.id not in root.inputs:
        issues.append("radial_array_must_feed_hub_union")

    hub_nodes = [
        node
        for node in nodes
        if node.semantic_role == "hub" and node.operator == "translate"
    ]
    if len(hub_nodes) != 1:
        issues.append("radial_requires_one_common_hub")
    elif root is not None and hub_nodes[0].id not in root.inputs:
        issues.append("common_hub_must_feed_union")

    if unitbox_id:
        derived_matrices = [
            node
            for node in nodes
            if node.operator == "matrix4" and node.inputs == (unitbox_id,)
        ]
        roles = {node.semantic_role for node in derived_matrices}
        if not {"wing", "hub"}.issubset(roles):
            issues.append("wing_and_hub_must_derive_from_unitbox")

    if compilation is not None:
        metrics = getattr(compilation, "metrics", {}) or {}
        if getattr(compilation, "status", "") != "compiled":
            issues.append("radial_geometry_must_compile")
        if int(metrics.get("component_count") or 0) != 1:
            issues.append("radial_geometry_must_be_one_component")
        if metrics.get("watertight") is not True:
            issues.append("radial_geometry_must_be_watertight")
        if metrics.get("manifold") is not True:
            issues.append("radial_geometry_must_be_manifold")

    return tuple(issues)


def _build_common_hub_radial(
    spec: "FreshMassSpec",
    *,
    variation_offset: int,
) -> GeometryProgram:
    u = _unit_interval(variation_offset, 997)
    v = _unit_interval(variation_offset * 37 + 17, 991)
    wing_count = 3 + (variation_offset % 2)
    wing_length = round(3.2 + 1.2 * u, 6)
    wing_depth = round(0.9 + 0.35 * v, 6)
    height = round(1.2 + 0.8 * (1.0 - u), 6)
    hub_size = round(wing_depth * (1.55 + 0.1 * v), 6)
    total_angle = 360.0 * (wing_count - 1) / wing_count

    builder = GeometryProgramBuilder(
        f"fresh_{spec.spec_id}_{variation_offset}"
    )
    wing = builder.add(
        "primitive",
        "box",
        parameters={
            "width": wing_length,
            "depth": wing_depth,
            "height": height,
        },
        semantic_role="wing",
    )
    aligned_wing = builder.add(
        "transform",
        "translate",
        inputs=(wing,),
        parameters={"vector": [0.0, -wing_depth / 2.0, 0.0]},
        semantic_role="wing",
    )
    wings = builder.add(
        "pattern",
        "radial_array",
        inputs=(aligned_wing,),
        parameters={
            "count": wing_count,
            "total_angle_degrees": total_angle,
            "pivot": [0.0, 0.0, 0.0],
        },
        semantic_role="wing",
    )
    hub = builder.add(
        "primitive",
        "box",
        parameters={
            "width": hub_size,
            "depth": hub_size,
            "height": height,
        },
        semantic_role="hub",
    )
    centered_hub = builder.add(
        "transform",
        "translate",
        inputs=(hub,),
        parameters={"vector": [-hub_size / 2.0, -hub_size / 2.0, 0.0]},
        semantic_role="hub",
    )
    root = builder.add(
        "boolean",
        "union",
        inputs=(centered_hub, wings),
        semantic_role="main",
    )
    return builder.build(
        root,
        family=spec.family,
        generation_mode="fresh_synthesis",
        normalized_parameter_authority="1/1 UnitBox",
        family_contract={
            "schema_version": "arr.maas.fresh_family_contract.v1",
            "contract_id": "common_hub_radial",
            "core_lowering": ["radial_array", "common_hub_union"],
            "variation_offset": variation_offset,
            "relative_parameters": {
                "wing_count": wing_count,
                "wing_length_ratio": wing_length,
                "wing_depth_ratio": wing_depth,
                "height_ratio": height,
                "hub_size_ratio": hub_size,
            },
        },
        book_recursive_projection={
            "active": True,
            "geometry_authority": "recursive_manifold_ast",
            "application_order": "book_semantics_lowered_to_core_geometry_ast",
            "ordered_verbs": list(spec.book_verbs),
            "scope_label": spec.scope_label,
            "scope_fraction": 1.0,
            "scope_orientation": spec.orientation,
            "parcel_coordinates_hardcoded": False,
            "core_lowering": ["radial_array", "common_hub_union"],
        },
    )


def _unit_interval(value: int, modulus: int) -> float:
    return ((abs(int(value)) % modulus) + 1) / (modulus + 1)


__all__ = [
    "build_family_contract_program",
    "family_phenotype_issues",
]
