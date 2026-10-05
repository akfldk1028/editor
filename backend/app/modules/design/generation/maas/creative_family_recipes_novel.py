"""Disc-cluster and long-span recipes split from the legacy family module."""

from __future__ import annotations

from backend.app.modules.design.generation.maas.creative_family_contract import CreativeRecipeContext, CreativeRecipeResult
from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import compose_matrix4, matrix4_for_transform, matrix4_to_lists, rotation_matrix4, scale_matrix4, translation_matrix4
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode


def build_oblique_crystal_recipe(
    context: CreativeRecipeContext,
) -> CreativeRecipeResult:
    from backend.app.modules.design.generation.maas.creative_family_recipes import _matrix_node, _program, _project_new_result, _unitbox

    variation = context.variation_index
    unitbox = _unitbox()
    shear_amount = 0.18 + 0.025 * variation
    matrix = compose_matrix4(
        scale_matrix4((3.6, 2.8 + 0.08 * variation, 5.2)),
        matrix4_for_transform(
            "shear",
            {"axis": "x", "direction": "z", "amount": shear_amount},
        ),
    )
    oblique = _matrix_node(
        "oblique_crystal_shear_matrix4",
        unitbox.id,
        matrix,
        "oblique_crystal_shear",
        provenance={"affine_evidence": "shear"},
    )
    clip_a = GeometryNode(
        "oblique_crystal_lower_clip",
        "modifier",
        "clip",
        inputs=(oblique.id,),
        parameters={
            "normal": [1.0, -0.45, 0.22],
            "offset_ratio": 0.09 + 0.005 * variation,
        },
        semantic_role="oblique_crystal_clip",
    )
    clip_b = GeometryNode(
        "oblique_crystal_loft_clip",
        "modifier",
        "clip",
        inputs=(clip_a.id,),
        parameters={
            "normal": [-0.35, 0.18, 1.0],
            "offset_ratio": 0.14,
        },
        semantic_role="oblique_crystal_loft_facets",
        provenance={"topology_evidence": "loft_equivalent_faceted_envelope"},
    )
    program = _program(
        "oblique_crystal",
        (unitbox, oblique, clip_a, clip_b),
        clip_b.id,
        context,
    )
    return _project_new_result(
        CreativeRecipeResult(
            program=program,
            contact_type="core",
            contact_node_id=clip_b.id,
            form_class="non_stepped",
            recipe_parameters={
                "shear_amount": shear_amount,
                "clip_plane_count": 2,
                "loft_evidence": "faceted_clip_envelope",
            },
        ),
        context,
        verb="skew",
    )


def build_thin_disc_cluster_recipe(
    context: CreativeRecipeContext,
) -> CreativeRecipeResult:
    from backend.app.modules.design.generation.maas.creative_family_recipes import _matrix_node, _program, _project_new_result, _unitbox

    variation = context.variation_index
    unitbox = _unitbox()
    slab = _matrix_node(
        "thin_disc_slab_matrix4",
        unitbox.id,
        compose_matrix4(
            scale_matrix4((4.4, 3.4, 0.34)),
            translation_matrix4((-2.2, -1.7, -0.17)),
        ),
        "thin_disc_source_slab",
    )
    circular = GeometryNode(
        "thin_disc_circularize",
        "modifier",
        "circularize",
        inputs=(slab.id,),
        parameters={"segments": 28 + 2 * (variation % 5)},
        semantic_role="thin_disc_topology",
    )
    branch_specs = (
        ((14.0 + variation, 0.0, -11.0), (-0.35, 0.0, 0.0)),
        ((-10.0, 18.0 + variation, 8.0), (0.35, 0.12, 0.05)),
        ((8.0, -15.0, 23.0 + variation), (0.0, -0.25, 0.1)),
    )
    branches = tuple(
        _matrix_node(
            f"thin_disc_branch_{index + 1}_matrix4",
            circular.id,
            compose_matrix4(
                rotation_matrix4(angles),
                translation_matrix4(translation),
            ),
            "independent_thin_disc_branch",
        )
        for index, (angles, translation) in enumerate(branch_specs)
    )
    union = GeometryNode(
        "thin_disc_cluster_union",
        "boolean",
        "union",
        inputs=tuple(branch.id for branch in branches),
        semantic_role="thin_disc_cluster_contact",
    )
    program = _program(
        "thin_disc_cluster",
        (unitbox, slab, circular, *branches, union),
        union.id,
        context,
    )
    return _project_new_result(
        CreativeRecipeResult(
            program=program,
            contact_type="hub",
            contact_node_id=union.id,
            form_class="non_stepped",
            recipe_parameters={
                "disc_count": 3,
                "independent_matrix_branches": True,
                "segments": circular.parameters["segments"],
            },
        ),
        context,
        verb="rotate",
    )


def build_interlocking_tilted_discs_recipe(
    context: CreativeRecipeContext,
) -> CreativeRecipeResult:
    from backend.app.modules.design.generation.maas.creative_family_recipes import _matrix_node, _program, _project_new_result, _unitbox

    variation = context.variation_index
    unitbox = _unitbox()
    slab = _matrix_node(
        "interlocking_disc_slab_matrix4",
        unitbox.id,
        compose_matrix4(
            scale_matrix4((4.0, 4.0, 0.4)),
            translation_matrix4((-2.0, -2.0, -0.2)),
        ),
        "interlocking_disc_source_slab",
    )
    circular = GeometryNode(
        "interlocking_disc_circularize",
        "modifier",
        "circularize",
        inputs=(slab.id,),
        parameters={"segments": 32 + 2 * (variation % 4)},
        semantic_role="interlocking_disc_topology",
    )
    matrices = [
        matrix4_to_lists(rotation_matrix4((24.0 + variation, 0.0, 0.0))),
        matrix4_to_lists(rotation_matrix4((0.0, -27.0, 18.0 + variation))),
        matrix4_to_lists(rotation_matrix4((-19.0, 22.0, -12.0))),
    ]
    array = GeometryNode(
        "interlocking_disc_matrix_array",
        "pattern",
        "matrix_array",
        inputs=(circular.id,),
        parameters={"matrices": matrices, "require_connected": True},
        semantic_role="interlocking_tilted_disc_array",
    )
    spine = _matrix_node(
        "interlocking_disc_spine_matrix4",
        unitbox.id,
        compose_matrix4(
            scale_matrix4((0.56, 0.56, 4.8)),
            translation_matrix4((-0.28, -0.28, -2.4)),
        ),
        "interlocking_disc_spine",
    )
    contact = GeometryNode(
        "interlocking_disc_contact_union",
        "boolean",
        "union",
        inputs=(array.id, spine.id),
        semantic_role="interlocking_disc_bridge",
        provenance={"occupied_contact": True},
    )
    program = _program(
        "interlocking_tilted_discs",
        (unitbox, slab, circular, array, spine, contact),
        contact.id,
        context,
    )
    book_verb = (
        "notch"
        if context.book_scope_label == "1/8" and context.variation_index == 1
        else "rotate"
    )
    return _project_new_result(
        CreativeRecipeResult(
            program=program,
            contact_type="shared_edge",
            contact_node_id=contact.id,
            form_class="non_stepped",
            recipe_parameters={
                "disc_count": len(matrices),
                "matrix_array": True,
                "occupied_contact": True,
            },
        ),
        context,
        verb=book_verb,
    )


def build_long_span_bridge_recipe(
    context: CreativeRecipeContext,
) -> CreativeRecipeResult:
    from backend.app.modules.design.generation.maas.creative_family_recipes import _matrix_node, _program, _project_new_result, _unitbox

    variation = context.variation_index
    span = 10.0 + 0.45 * variation
    support_width = 1.5
    unitbox = _unitbox()
    left = _matrix_node(
        "long_span_left_support_matrix4",
        unitbox.id,
        compose_matrix4(
            scale_matrix4((support_width, 2.2, 3.8)),
            translation_matrix4((-span / 2.0 - support_width / 2.0, -1.1, 0.0)),
        ),
        "long_span_support",
        provenance={"support_side": "left", "grounded": True},
    )
    right = _matrix_node(
        "long_span_right_support_matrix4",
        unitbox.id,
        compose_matrix4(
            scale_matrix4((support_width, 2.2, 3.8)),
            translation_matrix4((span / 2.0 - support_width / 2.0, -1.1, 0.0)),
        ),
        "long_span_support",
        provenance={"support_side": "right", "grounded": True},
    )
    profile = _matrix_node(
        "long_span_profile_matrix4",
        unitbox.id,
        compose_matrix4(
            scale_matrix4((0.5, 0.7, 0.5)),
            translation_matrix4((-0.25, -0.35, -0.25)),
        ),
        "long_span_sweep_profile",
    )
    sweep = GeometryNode(
        "long_span_occupied_profile_sweep",
        "modifier",
        "profile_sweep_3d",
        inputs=(profile.id,),
        parameters={
            "path": [
                [-span / 2.0 - 0.1, 0.0, 3.25],
                [0.0, 0.0, 3.45 + 0.03 * variation],
                [span / 2.0 + 0.1, 0.0, 3.25],
            ],
            "require_connected": True,
        },
        semantic_role="occupied_long_span_connector",
        provenance={"occupied_connector": True},
    )
    union = GeometryNode(
        "long_span_connected_union",
        "boolean",
        "union",
        inputs=(left.id, right.id, sweep.id),
        semantic_role="long_span_support_bridge_contact",
    )
    program = _program(
        "long_span_bridge",
        (unitbox, left, right, profile, sweep, union),
        union.id,
        context,
    )
    book_verb = "rotate" if context.book_scope_label == "3/8" else "lift"
    return _project_new_result(
        CreativeRecipeResult(
            program=program,
            contact_type="bridge",
            contact_node_id=sweep.id,
            form_class="non_stepped",
            recipe_parameters={
                "span_length": span,
                "support_contact_count": 2,
                "occupied_connector": True,
            },
        ),
        context,
        verb=book_verb,
    )


__all__ = [
    "build_interlocking_tilted_discs_recipe",
    "build_long_span_bridge_recipe",
    "build_oblique_crystal_recipe",
    "build_thin_disc_cluster_recipe",
]
