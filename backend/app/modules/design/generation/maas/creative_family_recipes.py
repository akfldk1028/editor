"""Strict UnitBox recipe builders for the creative MASS family registry."""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from typing import Callable

from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall, VerbSequence
from backend.app.modules.design.generation.maas.program_massing.book_projection import book_sentence_variants, compose_program_with_book_operations

from backend.app.modules.design.generation.maas.creative_family_contract import CreativeRecipeContext, CreativeRecipeResult
from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import matrix4_to_lists, scale_matrix4
from backend.app.modules.design.generation.maas.geometry_language.affine_normalization import normalize_affine_basevolume_program
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.book_adapter import apply_book_projection_to_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.universal_form_bank import universal_form_programs


BOOK_SCOPE_ORIENTATIONS = {
    "1/1": "long_axis",
    "1/2": "long_axis",
    "3/8": "short_axis",
    "1/4": "short_axis",
    "1/8": "vertical",
    "1/16": "vertical",
}

_LEGACY_RECIPE_CONFIG = {
    "bent": ("agent_bend", "notch", "spine", ("bend", "bent_bar")),
    "carved_void": (
        "agent_carve_void",
        "skew",
        "core",
        ("carve_void", "difference"),
    ),
    "courtyard": (
        "agent_courtyard",
        "rotate",
        "core",
        ("courtyard",),
    ),
    "cross": (
        "agent_cross_mass",
        "taper",
        "spine",
        ("cross_mass",),
    ),
    "grid": (
        "agent_grid_mass",
        "pinch",
        "shared_edge",
        ("grid_mass",),
    ),
    "inflated": (
        "agent_inflate",
        "carve",
        "core",
        ("inflate",),
    ),
    "notch": ("agent_notch", "taper", "core", ("notch",)),
    "radial": (
        "agent_radial_array",
        "skew",
        "hub",
        ("radial_array",),
    ),
    "split_wing": (
        "agent_split_wing",
        "lift",
        "bridge",
        ("split_wing", "bridge"),
    ),
    "stepped": (
        "agent_stepped_mass",
        "taper",
        "core",
        ("stepped_mass",),
    ),
}

_LEGACY_SOURCE_STRIDES = {
    "bent": 11,
    "carved_void": 19,
    "inflated": 20,
    "split_wing": 7,
    "stepped": 16,
}


def _unitbox() -> GeometryNode:
    return GeometryNode(
        "unit_box",
        "primitive",
        "box",
        parameters={"width": 1.0, "depth": 1.0, "height": 1.0},
        semantic_role="canonical_unitbox",
        provenance={"authority": "canonical_unitbox"},
    )


def _matrix_node(
    node_id: str,
    input_id: str,
    matrix,
    semantic_role: str,
    *,
    provenance: dict | None = None,
) -> GeometryNode:
    return GeometryNode(
        node_id,
        "transform",
        "matrix4",
        inputs=(input_id,),
        parameters={"matrix4": matrix4_to_lists(matrix)},
        semantic_role=semantic_role,
        provenance={
            "authority": "canonical_unitbox_lineage",
            **(provenance or {}),
        },
    )


def _program(
    family: str,
    nodes: tuple[GeometryNode, ...],
    root_id: str,
    context: CreativeRecipeContext,
) -> GeometryProgram:
    return GeometryProgram(
        nodes=nodes,
        root_id=root_id,
        name=f"creative_{family}_{context.variation_index:02d}",
        metadata={
            "creative_family": family,
            "variation_index": context.variation_index,
            "book_scope_label": context.book_scope_label,
            "capacity_band": context.capacity_band,
            "strict_unitbox": True,
            "form_class": (
                "stepped" if family == "stepped" else "non_stepped"
            ),
        },
    )


@lru_cache(maxsize=1)
def _legacy_supply() -> dict[str, tuple[GeometryProgram, ...]]:
    supply: dict[str, list[GeometryProgram]] = {
        source_family: []
        for source_family, _verb, _contact, _witnesses
        in _LEGACY_RECIPE_CONFIG.values()
    }
    seen: set[str] = set()
    for page in range(8):
        for program in universal_form_programs(page):
            source_family = str(program.metadata.get("family") or "")
            if source_family not in supply:
                continue
            program_hash = program.program_hash()
            if program_hash in seen:
                continue
            seen.add(program_hash)
            supply[source_family].append(program)
    return {
        source_family: tuple(programs)
        for source_family, programs in supply.items()
    }


def _matrix4_only(program: GeometryProgram) -> GeometryProgram:
    """Lower every affine transform to its equivalent explicit Matrix4."""
    return normalize_affine_basevolume_program(program)


def _with_material_recipe_variation(
    program: GeometryProgram,
    *,
    family: str,
    variation_index: int,
) -> GeometryProgram:
    """Spread architectural parameters that the source bank clusters tightly."""

    nodes: list[GeometryNode] = []
    for node in program.nodes:
        parameters = dict(node.parameters)
        if family == "grid" and node.operator == "grid_mass":
            parameters.update({
                "row_spacing_ratio": round(
                    1.05 + 0.12 * ((variation_index * 3) % 7),
                    3,
                ),
                "column_offset_ratio": round(
                    0.12 + 0.04 * ((variation_index * 5) % 7),
                    3,
                ),
            })
        elif family == "radial" and node.operator == "radial_array":
            parameters.update({
                "count": 3 + ((variation_index * 2) % 5),
                "total_angle_degrees": float(
                    40 + 20 * ((variation_index * 3) % 7)
                ),
            })
        nodes.append(replace(node, parameters=parameters))
    return replace(program, nodes=tuple(nodes))


def _with_book_projection(
    program: GeometryProgram,
    *,
    source_family: str,
    verb: str,
    context: CreativeRecipeContext,
) -> GeometryProgram:
    scheduled_verbs = tuple(context.book_execution_verbs)
    if scheduled_verbs:
        effective_verbs = scheduled_verbs
        operations = book_sentence_variants(
            effective_verbs,
            count=1,
        )[0]
        name_suffix = context.book_principle_id.replace(":", "-")
    else:
        effective_verb = verb
        if source_family == "agent_stepped_mass" and (
            context.book_scope_label == "1/16"
        ):
            effective_verb = "taper"
        effective_verbs = (effective_verb,)
        sentences = book_sentence_variants(effective_verbs, count=16)
        operations = sentences[context.variation_index % len(sentences)]
        name_suffix = (
            f"{context.book_scope_label.replace('/', '_')}"
            f"-{effective_verb}"
        )
    sequence = compose_program_with_book_operations(
        VerbSequence(
            name=f"creative-{source_family}-source",
            label=source_family,
            calls=(VerbCall("base", {}),),
        ),
        operations,
        name_suffix=name_suffix,
        base_volume_label=context.book_scope_label,
        orientation=BOOK_SCOPE_ORIENTATIONS[context.book_scope_label],
    )
    projected = _matrix4_only(
        apply_book_projection_to_geometry_program(program, sequence)
    )
    if not context.book_principle_id:
        return projected
    return replace(
        projected,
        metadata={
            **projected.metadata,
            "creative_book_assignment": {
                "principle_id": context.book_principle_id,
                "principle_kind": context.book_principle_kind,
                "execution_verbs": list(effective_verbs),
                "aggregation_methods": list(
                    context.book_aggregation_methods
                ),
                "scope_label": context.book_scope_label,
                "orientation": BOOK_SCOPE_ORIENTATIONS[
                    context.book_scope_label
                ],
            },
        },
    )


def _legacy_result(
    family: str,
    context: CreativeRecipeContext,
) -> CreativeRecipeResult:
    source_family, verb, contact_type, preferred = (
        _LEGACY_RECIPE_CONFIG[family]
    )
    supply = _legacy_supply()[source_family]
    source_stride = _LEGACY_SOURCE_STRIDES.get(family, 1)
    source_index = (
        context.variation_index * source_stride
    ) % len(supply)
    source = supply[source_index]
    authored = _matrix4_only(source)
    authored = _with_material_recipe_variation(
        authored,
        family=family,
        variation_index=context.variation_index,
    )
    authored = _with_book_projection(
        authored,
        source_family=source_family,
        verb=verb,
        context=context,
    )
    authored = replace(
        authored,
        name=f"creative_{family}_{context.variation_index:02d}",
        metadata={
            **authored.metadata,
            "creative_family": family,
            "strict_unitbox": True,
            "form_class": (
                "stepped" if family == "stepped" else "non_stepped"
            ),
            "variation_index": context.variation_index,
            "book_scope_label": context.book_scope_label,
            "capacity_band": context.capacity_band,
        },
    )
    witness = next(
        node
        for node in reversed(authored.nodes)
        if node.operator in preferred
    )
    return CreativeRecipeResult(
        program=authored,
        contact_type=contact_type,
        contact_node_id=witness.id,
        form_class="stepped" if family == "stepped" else "non_stepped",
        recipe_parameters={
            "source_family": source_family,
            "book_verb": verb,
            "variation_index": context.variation_index,
            "source_index": source_index,
            "source_stride": source_stride,
            "index_scale_perturbation": False,
        },
    )


def _project_new_result(
    result: CreativeRecipeResult,
    context: CreativeRecipeContext,
    *,
    verb: str,
) -> CreativeRecipeResult:
    return replace(
        result,
        program=_with_book_projection(
            result.program,
            source_family=str(
                result.program.metadata["creative_family"]
            ),
            verb=verb,
            context=context,
        ),
        recipe_parameters={
            **result.recipe_parameters,
            "book_verb": verb,
        },
    )


def build_bent_recipe(context: CreativeRecipeContext) -> CreativeRecipeResult:
    return _legacy_result("bent", context)


def build_carved_void_recipe(
    context: CreativeRecipeContext,
) -> CreativeRecipeResult:
    return _legacy_result("carved_void", context)


def build_courtyard_recipe(
    context: CreativeRecipeContext,
) -> CreativeRecipeResult:
    return _legacy_result("courtyard", context)


def build_cross_recipe(context: CreativeRecipeContext) -> CreativeRecipeResult:
    return _legacy_result("cross", context)


def build_grid_recipe(context: CreativeRecipeContext) -> CreativeRecipeResult:
    return _legacy_result("grid", context)


def build_inflated_recipe(
    context: CreativeRecipeContext,
) -> CreativeRecipeResult:
    return _legacy_result("inflated", context)


def build_notch_recipe(context: CreativeRecipeContext) -> CreativeRecipeResult:
    return _legacy_result("notch", context)


def build_radial_recipe(context: CreativeRecipeContext) -> CreativeRecipeResult:
    return _legacy_result("radial", context)


def build_split_wing_recipe(
    context: CreativeRecipeContext,
) -> CreativeRecipeResult:
    return _legacy_result("split_wing", context)


def build_stepped_recipe(
    context: CreativeRecipeContext,
) -> CreativeRecipeResult:
    return _legacy_result("stepped", context)


def build_triangular_shard_recipe(
    context: CreativeRecipeContext,
) -> CreativeRecipeResult:
    variation = context.variation_index
    unitbox = _unitbox()
    proportion = _matrix_node(
        "triangular_shard_proportion_matrix4",
        unitbox.id,
        scale_matrix4((4.2 + 0.17 * variation, 3.1, 4.8)),
        "triangular_shard_proportion",
    )
    clip_a = GeometryNode(
        "triangular_shard_clip_a",
        "modifier",
        "clip",
        inputs=(proportion.id,),
        parameters={
            "normal": [1.0, 1.0 + 0.03 * variation, 0.0],
            "offset_ratio": 0.12 + 0.025 * variation,
        },
        semantic_role="triangular_shard_plane",
    )
    clip_b = GeometryNode(
        "triangular_shard_clip_b",
        "modifier",
        "clip",
        inputs=(clip_a.id,),
        parameters={
            "normal": [-0.35, 1.0, 0.16 + 0.01 * variation],
            "offset_ratio": 0.08 + 0.018 * variation,
        },
        semantic_role="triangular_shard_contact",
    )
    program = _program(
        "triangular_shard",
        (unitbox, proportion, clip_a, clip_b),
        clip_b.id,
        context,
    )
    return _project_new_result(CreativeRecipeResult(
        program=program,
        contact_type="core",
        contact_node_id=clip_b.id,
        form_class="non_stepped",
        recipe_parameters={
            "clip_plane_count": 2,
            "nonparallel_clip_planes": True,
            "variation_index": variation,
        },
    ), context, verb="notch")


def build_oblique_crystal_recipe(
    context: CreativeRecipeContext,
) -> CreativeRecipeResult:
    from backend.app.modules.design.generation.maas.creative_family_recipes_novel import build_oblique_crystal_recipe as build

    return build(context)


def build_thin_disc_cluster_recipe(
    context: CreativeRecipeContext,
) -> CreativeRecipeResult:
    from backend.app.modules.design.generation.maas.creative_family_recipes_novel import build_thin_disc_cluster_recipe as build

    return build(context)


def build_interlocking_tilted_discs_recipe(
    context: CreativeRecipeContext,
) -> CreativeRecipeResult:
    from backend.app.modules.design.generation.maas.creative_family_recipes_novel import build_interlocking_tilted_discs_recipe as build

    return build(context)


def build_long_span_bridge_recipe(
    context: CreativeRecipeContext,
) -> CreativeRecipeResult:
    from backend.app.modules.design.generation.maas.creative_family_recipes_novel import build_long_span_bridge_recipe as build

    return build(context)


RECIPE_BUILDERS: dict[
    str,
    Callable[[CreativeRecipeContext], CreativeRecipeResult],
] = {
    "creative_bent_v1": build_bent_recipe,
    "creative_carved_void_v1": build_carved_void_recipe,
    "creative_courtyard_v1": build_courtyard_recipe,
    "creative_cross_v1": build_cross_recipe,
    "creative_grid_v1": build_grid_recipe,
    "creative_inflated_v1": build_inflated_recipe,
    "creative_notch_v1": build_notch_recipe,
    "creative_radial_v1": build_radial_recipe,
    "creative_split_wing_v1": build_split_wing_recipe,
    "creative_stepped_v1": build_stepped_recipe,
    "creative_triangular_shard_v1": build_triangular_shard_recipe,
    "creative_oblique_crystal_v1": build_oblique_crystal_recipe,
    "creative_thin_disc_cluster_v1": build_thin_disc_cluster_recipe,
    "creative_interlocking_tilted_discs_v1": (
        build_interlocking_tilted_discs_recipe
    ),
    "creative_long_span_bridge_v1": build_long_span_bridge_recipe,
}


__all__ = [
    "RECIPE_BUILDERS",
    "build_bent_recipe",
    "build_carved_void_recipe",
    "build_courtyard_recipe",
    "build_cross_recipe",
    "build_grid_recipe",
    "build_inflated_recipe",
    "build_interlocking_tilted_discs_recipe",
    "build_long_span_bridge_recipe",
    "build_notch_recipe",
    "build_oblique_crystal_recipe",
    "build_radial_recipe",
    "build_split_wing_recipe",
    "build_stepped_recipe",
    "build_thin_disc_cluster_recipe",
    "build_triangular_shard_recipe",
]
