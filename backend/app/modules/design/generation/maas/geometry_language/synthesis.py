"""Program-neutral synthesis of recursive architectural solid graphs.

This module deliberately does not contain parcel coordinates or completed
building templates.  It turns a normalized base seed, architectural intent
tags and bounded variation indices into a typed :class:`GeometryProgram`.
The compiler remains the only authority that can turn the graph into a solid.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Iterable

from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import compose_matrix4, matrix4_to_lists, scale_matrix4, translation_matrix4
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.base_seeds import BASE_SEED_SPECS, base_seed_program, profiled_prism_parameters
from backend.app.modules.design.generation.maas.geometry_language.scope_composition import sample_connected_scope_set
from backend.app.modules.design.generation.maas.geometry_language.book_chassis_compatibility import split_wing_gap_ratio_from_unit
from backend.app.modules.design.generation.maas.geometry_language.section_profiles import SECTION_PROFILES, section_profile_controls
from backend.app.modules.design.generation.maas.geometry_language.host_face_relations import sample_face_attachment_parameters
from backend.app.modules.design.generation.maas.geometry_language.typology_priors import typology_prior, typology_priors_for_program


_PROFILE_FAMILY_INTENTS: dict[str, tuple[str, ...]] = {
    "courtyard": ("carved_void",),
    "void_notch": ("carved_void",),
    "bend": ("continuous_curve",),
    "slender_bar": ("long_span", "continuous_curve"),
    "sloped_roof": ("profiled_span_section", "long_span", "daylight_section", "oblique_section"),
    "terrace_link": ("stepped_section", "lifted_ground"),
    "offset": ("stepped_section",),
    "stepback_tower": ("stepped_section", "vertical_landmark"),
    "nested_stack": ("stepped_section", "carved_void"),
    "split": ("distributed_wings", "lifted_ground"),
    "diagonal_connect": ("distributed_wings", "oblique_section"),
    "array_cluster": ("distributed_wings",),
    "taper": ("vertical_landmark",),
}


_TAG_OPERATOR_PALETTE: dict[str, tuple[str, ...]] = {
    "calm_prismatic": ("identity",),
    "continuous_curve": ("bend", "bent_bar", "inflate"),
    "long_span": ("split_wing", "identity", "bend", "inflate"),
    "oblique_section": ("slice", "shear", "cut_corner"),
    "stepped_section": ("setback", "stepped_mass", "terrace"),
    "carved_void": ("courtyard", "notch", "carve_void", "puncture"),
    "lifted_ground": ("lift", "cantilever", "split_wing"),
    "daylight_section": ("puncture", "inflate", "setback"),
    "distributed_wings": ("cross_mass", "radial_array", "split_wing"),
    "vertical_landmark": ("taper", "shear", "twist"),
    # Repetition weights the general section-profile operator so bounded
    # synthesis explores several roof/section graphs before generic cuts and
    # setbacks. The profiles remain parameters, not named building templates.
    "profiled_span_section": ("profiled_hall", "profiled_hall", "profiled_hall", "profiled_hall", "profiled_hall", "profiled_hall"),
    "face_composition": ("attach",),
}

_BODY_PHENOTYPE_INTENTS: dict[str, str] = {
    "prismatic": "calm_prismatic",
    "curved": "continuous_curve",
    "stepped": "stepped_section",
    "voided": "carved_void",
    "oblique": "oblique_section",
    "winged": "distributed_wings",
    "lifted": "lifted_ground",
    "attached": "face_composition",
}

# One in three programs is a composed mass rather than a single body. The
# counts are walked by the same cursor as the operator palette, so the composed
# share is spread evenly through a page instead of clustered.
_COMPOSITION_SCOPE_COUNTS: tuple[int, ...] = (1, 1, 2, 1, 1, 3, 1, 1, 4)
# Distinct prime bases keep the placement dimensions from correlating.
_COMPOSITION_BASES: tuple[int, ...] = (2, 3, 5, 7, 11, 13)
# Macros that remove material through the body, which a composition cannot
# survive: the cut is parameterized independently of the engagement.
_VOID_MACROS: frozenset[str] = frozenset({
    "carve_void", "courtyard", "notch", "puncture",
})
# Macros that are already a multi-part figure. `program_projection` keeps its
# own version of this list (`_OPEN_COURT_HAZARDS`) for the same reason: these
# operators replicate whatever they are given, so composing underneath one
# multiplies the parts and the result reads as clutter rather than as a
# composition. One program makes its parts one way.
_MULTIPART_MACROS: frozenset[str] = frozenset({
    "cross_mass", "grid_mass", "radial_array", "split_wing",
})

_OPERATOR_KIND: dict[str, str] = {
    "bend": "modifier",
    "taper": "modifier",
    "twist": "modifier",
    "inflate": "modifier",
    "pinch": "modifier",
    "slice": "modifier",
    "cut_corner": "modifier",
    "shear": "transform",
    "radial_array": "pattern",
    "courtyard": "macro",
    "notch": "macro",
    "carve_void": "macro",
    "setback": "macro",
    "terrace": "macro",
    "cantilever": "macro",
    "lift": "macro",
    "puncture": "macro",
    "cross_mass": "macro",
    "grid_mass": "macro",
    "bent_bar": "macro",
    "split_wing": "macro",
    "stepped_mass": "macro",
    "profiled_hall": "macro",
    "attach": "composition",
}

_OPERATOR_EFFECT_FAMILY: dict[str, str] = {
    "bend": "deformation", "bent_bar": "deformation", "twist": "deformation",
    "inflate": "deformation", "pinch": "deformation", "taper": "deformation",
    "shear": "deformation",
    "setback": "step", "stepped_mass": "step", "terrace": "step",
    "courtyard": "void", "carve_void": "void", "notch": "void",
    "puncture": "void", "cut_corner": "void",
    "slice": "cut",
    "radial_array": "array", "cross_mass": "array", "grid_mass": "array", "split_wing": "array",
    "cantilever": "support", "lift": "support",
    "attach": "attachment",
}


def synthesize_architectural_programs(
    request: dict[str, Any],
    *,
    building_type: str,
) -> tuple[GeometryProgram, ...]:
    """Create bounded graph alternatives from intent, not named forms.

    ``request`` may choose base seeds and intent tags, but it cannot provide
    world coordinates.  Parameter samples are deterministic so every program
    can be reproduced, hashed, compared and revised by a later VLM critic.
    """
    if not isinstance(request, dict):
        return ()
    known_seeds = {item.seed_id for item in BASE_SEED_SPECS}
    raw_seeds = request.get("base_seeds") or ("slab", "bar", "block", "profiled_prism")
    base_seeds = tuple(dict.fromkeys(
        str(value) for value in raw_seeds if str(value) in known_seeds
    ))
    if not base_seeds:
        return ()
    intent_tags = tuple(dict.fromkeys(
        str(value) for value in (request.get("intent_tags") or ())
        if str(value) in _TAG_OPERATOR_PALETTE
    ))
    try:
        # A strict program/VLM critic is expected to reject a meaningful
        # fraction of authored programs.  Capping the author pool at 24 made
        # a 20-alternative portfolio mathematically depend on near-perfect
        # critic acceptance.  Keep the search bounded, but allow enough
        # genotype supply for hard rejection instead of weakening gates.
        target_count = max(1, min(64, int(request.get("candidate_count") or 12)))
        maximum_depth = max(1, min(3, int(request.get("maximum_operator_depth") or 2)))
        downstream_body_rule_reserve = max(
            0,
            min(2, int(request.get("downstream_body_rule_reserve") or 0)),
        )
        variation_offset = max(0, min(4096, int(request.get("variation_offset") or 0)))
        # The parcel's own box, if the caller knows it: the seed rectangle's
        # width and depth and the storey budget the law allows. A seed authored
        # without it is a proportion and the size arrives later, at the fit -
        # which is where it was going missing. massv2's seed has carried the
        # parcel's metres from its first word since it was written.
        site_extent = request.get("site_extent")
        if site_extent is not None:
            try:
                site_extent = tuple(float(value) for value in site_extent)
            except (TypeError, ValueError):
                site_extent = None
            if site_extent is not None and (
                len(site_extent) != 3 or min(site_extent) <= 1e-9
            ):
                site_extent = None
    except (TypeError, ValueError):
        return ()
    required_terminal_operator = str(request.get("required_terminal_operator") or "").strip().lower()
    if required_terminal_operator and required_terminal_operator != "profiled_hall":
        return ()
    allowed_macro_operator_order = tuple(dict.fromkeys(
        str(value).strip().lower()
        for value in request.get("allowed_macro_operators") or ()
        if str(value).strip()
    ))
    allowed_macro_operators = set(allowed_macro_operator_order)
    requested_typology_priors = []
    for value in request.get("typology_priors") or ():
        try:
            prior = typology_prior(str(value))
        except KeyError:
            continue
        if (
            prior.primary_operator in _OPERATOR_KIND
            and (
                _OPERATOR_KIND[prior.primary_operator] != "macro"
                or not allowed_macro_operators
                or prior.primary_operator in allowed_macro_operators
            )
        ):
            requested_typology_priors.append(prior)
    requested_typology_priors = list(dict.fromkeys(requested_typology_priors))
    required_macro_operators_all = tuple(dict.fromkeys(
        str(value).strip().lower()
        for value in request.get("required_macro_operators_all") or ()
        if str(value).strip()
    ))
    required_macro_operators_any = tuple(dict.fromkeys(
        str(value).strip().lower()
        for value in request.get("required_macro_operators_any") or ()
        if str(value).strip()
    ))
    if required_terminal_operator:
        required_macro_operators_all = tuple(dict.fromkeys((
            *required_macro_operators_all,
            required_terminal_operator,
        )))
    required_access_bound_relation = bool(request.get("required_access_bound_relation"))
    inferred_intents = tuple(
        _BODY_PHENOTYPE_INTENTS[str(value)]
        for value in (request.get("required_body_phenotypes") or ())
        if str(value) in _BODY_PHENOTYPE_INTENTS
    )
    if required_terminal_operator == "profiled_hall":
        inferred_intents = (*inferred_intents, "long_span")
    intent_tags = tuple(dict.fromkeys((*intent_tags, *inferred_intents)))
    if not intent_tags:
        return ()

    intent_palette = tuple(
        operator
        for tag in intent_tags
        for operator in _TAG_OPERATOR_PALETTE[tag]
        if (
            operator not in _OPERATOR_KIND
            or _OPERATOR_KIND[operator] != "macro"
            or not allowed_macro_operators
            or operator in allowed_macro_operators
        )
    )
    # ``allowed_macro_operators`` is an executable program-language contract,
    # not documentation for the VLM alone.  Previously profile synthesis only
    # traversed operators that happened to be named by ``preferred_families``;
    # neighborhood programs therefore advertised cross/split/stepped/cut
    # language but deterministically authored almost only bend/inflate/notch.
    # Add every unary contract operator to the search alphabet. Binary bridge
    # and attach relations remain available to the LLM/AST author, because a
    # one-input modifier stack cannot fabricate their second typed solid.
    contract_palette = tuple(
        operator
        for operator in allowed_macro_operator_order
        if operator in _OPERATOR_KIND
        and operator not in {"profiled_hall"}
    )
    raw_palette = tuple((*intent_palette, *contract_palette))
    # A use-specific author may intentionally weight a capability named by
    # several semantic intents.  The program-independent universal bank has a
    # different job: cover the alphabet before any use is known.  Let that
    # caller request a stratified first-operator traversal so repeated intent
    # aliases do not turn into repeated form families (for example nine
    # profiled halls before the gymnasium contract has even been projected).
    palette = (
        tuple(dict.fromkeys(raw_palette))
        if bool(request.get("balanced_operator_sampling"))
        else _weighted_operator_palette(raw_palette)
    )
    # A program-profile source is not the final graph: one BOOK sentence is
    # still projected over it.  Previously both layers independently spent a
    # two-rule budget, so source cross+setback+threshold plus BOOK helpers
    # produced technically valid but visually accumulated Lego objects.  The
    # request now reserves a body-rule slot for that downstream author.  A
    # standalone DSL request keeps the old full depth because its reserve is
    # zero.
    source_body_rule_budget = max(1, maximum_depth - downstream_body_rule_reserve)
    records: list[GeometryProgram] = []
    seen_hashes: set[str] = set()
    cursor = variation_offset
    attempts = 0
    # A low-discrepancy traversal of seed/operator pairs avoids making the
    # first tag or first base seed dominate a bounded batch.
    attempt_budget = max(target_count * 8, len(base_seeds) * len(palette) * 2)
    while len(records) < target_count and attempts < attempt_budget:
        # Cycle the first operator directly.  A fixed multiplier can share a
        # divisor with the runtime palette length and accidentally collapse a
        # 14-operator language to only bend/setback.
        active_typology_prior = (
            requested_typology_priors[
                (variation_offset + attempts) % len(requested_typology_priors)
            ]
            if attempts < len(requested_typology_priors)
            else None
        )
        first = (
            active_typology_prior.primary_operator
            if active_typology_prior is not None
            else palette[cursor % len(palette)]
        )
        preferred_prior_seeds = tuple(
            seed for seed in (active_typology_prior.preferred_base_seeds if active_typology_prior else ())
            if seed in base_seeds
        )
        seed_id = (
            # The first executable representative of a named early typology
            # is its canonical chassis, so its declared seed order is a real
            # priority contract. Cursor-driven seed variation resumes after
            # the one-pass typology-prior tranche.
            preferred_prior_seeds[0]
            if preferred_prior_seeds
            else _base_seed_for_operator(
                first,
                base_seeds,
                cursor=cursor,
                palette_size=len(palette),
                intent_tags=intent_tags,
            )
        )
        operators = [first]
        operator_variant_indices = [_operator_occurrence_index(palette, cursor, first)]
        if source_body_rule_budget >= 2 and len(palette) > 1 and cursor % 3 != 0:
            second = palette[(cursor * 5 + 3) % len(palette)]
            if second != first and second != "profiled_hall" and _compatible_stack(first, second):
                operators.append(second)
                operator_variant_indices.append(_operator_occurrence_index(palette, cursor, second))
        if source_body_rule_budget >= 3 and len(palette) > 2 and cursor % 7 == 0:
            third = palette[(cursor * 13 + 5) % len(palette)]
            if third != "profiled_hall" and third not in operators and all(_compatible_stack(item, third) for item in operators):
                operators.append(third)
                operator_variant_indices.append(_operator_occurrence_index(palette, cursor, third))
        for required_operator in required_macro_operators_all:
            if required_operator not in operators:
                operators.append(required_operator)
                operator_variant_indices.append(cursor)
        if required_macro_operators_any:
            required_set = set(required_macro_operators_any)
            if not any(operator in required_set for operator in operators):
                any_operator = None
                for required_operator in required_macro_operators_any:
                    if all(_compatible_stack(existing, required_operator) for existing in operators):
                        any_operator = required_operator
                        break
                if any_operator is None:
                    cursor += 1
                    attempts += 1
                    continue
                operators.append(any_operator)
                operator_variant_indices.append(cursor)
        if required_access_bound_relation and not any(
            operator in {"courtyard", "carve_void", "notch", "lift", "split_wing"}
            for operator in operators
        ):
            access_choices = tuple(
                operator for operator in ("courtyard", "carve_void", "notch", "lift", "split_wing")
                if not allowed_macro_operators or operator in allowed_macro_operators
                if all(_compatible_stack(existing, operator) for existing in operators)
            )
            if not access_choices:
                cursor += 1
                attempts += 1
                continue
            access_operator = access_choices[cursor % len(access_choices)]
            operators.append(access_operator)
            operator_variant_indices.append(cursor)
        # A CSG tree has rigid motions *and* regularized booleans at its
        # internal nodes; this generator only ever emitted the motions, so
        # every synthesized program was one body. The scope count is drawn
        # from the same low-discrepancy cursor as everything else, so the
        # composed share is spread through the page rather than blocked.
        #
        # The decision rides on the operator stack instead of steering it. An
        # earlier version drew the operators from a composition-compatible
        # palette, which raised the composed share but changed the operator
        # every cursor resolved to - and with it the seed assignment of
        # programs that were not composing at all. That cost the bank its
        # slab-borne relational and oblique programs, which two downstream
        # consumers look up by structure. Composition rides along; it does not
        # displace what was already there.
        scope_count = _COMPOSITION_SCOPE_COUNTS[
            cursor % len(_COMPOSITION_SCOPE_COUNTS)
        ]
        if any(
            operator in _VOID_MACROS or operator in _MULTIPART_MACROS
            for operator in operators
        ):
            # A void macro cut across a composition's engagement severs it, and
            # no engagement bound prevents that because the void is
            # parameterized independently - measured on `carve_void`, whose
            # projected parameters split a composed mass into two components.
            # A multi-part macro instead multiplies the composition's volumes
            # into clutter. Either way the program is already making its parts
            # some other way, so it makes them only that way.
            scope_count = 1
        program = _program_from_stack(
            seed_id,
            operators,
            site_extent=site_extent,
            scope_count=scope_count,
            operator_variant_indices=operator_variant_indices,
            variation_index=cursor,
            variation_offset=variation_offset,
            intent_tags=intent_tags,
            building_type=building_type,
            required_terminal_operator=required_terminal_operator,
            site_access_side=str(request.get("site_access_side") or "closed"),
            required_access_bound_relation=required_access_bound_relation,
            required_macro_operators_all=required_macro_operators_all,
            typology_prior_id=(active_typology_prior.typology_id if active_typology_prior else ""),
        )
        cursor += 1
        attempts += 1
        errors = [issue for issue in program.validate() if issue.severity == "error"]
        if errors:
            continue
        program_hash = program.program_hash()
        if program_hash in seen_hashes:
            continue
        seen_hashes.add(program_hash)
        records.append(program)
    return tuple(records)


def synthesis_requests_from_program_profile(
    building_type: str,
    *,
    source_seeds: Iterable[str],
    candidates_per_lineage: int = 18,
) -> tuple[dict[str, Any], ...]:
    """Infer graph-search intent from program semantics, not named forms.

    The profile contributes program requirements and preferred language words.
    This adapter maps those words to operator *capabilities*. It never reads a
    profile's hand-authored section controls, parcel coordinates, or completed
    geometry. Two source role lineages are enough to keep entry/service/gallery
    semantics while the recursive agent authors the dominant solid.
    """
    from backend.app.modules.design.generation.maas.program_massing.profiles import resolve_program_profile

    profile = resolve_program_profile(building_type)
    profile_id = str(profile.get("id") or building_type)
    geometry_language_contract = (
        profile.get("geometry_language_contract")
        if isinstance(profile.get("geometry_language_contract"), dict)
        else {}
    )
    allowed_macro_operators = [
        str(value)
        for value in geometry_language_contract.get("allowed_macro_operators") or ()
        if str(value)
    ]
    required_macro_operators_all = [
        str(value)
        for value in geometry_language_contract.get("required_macro_operators_all") or ()
        if str(value)
    ]
    required_macro_operators_any = [
        str(value)
        for value in geometry_language_contract.get("required_macro_operators_any") or ()
        if str(value)
    ]
    preferred = tuple(str(value) for value in profile.get("preferred_families") or ())
    intents = tuple(dict.fromkeys(
        intent
        for family in preferred
        for intent in _PROFILE_FAMILY_INTENTS.get(family, ())
    ))
    if not intents:
        intents = ("carved_void", "stepped_section", "oblique_section")
    # Every search needs one topology-preserving control.  Without it the
    # preferred-language list can contain only setbacks/cuts and an otherwise
    # diverse program collapses into one wedge or terrace phenotype.  This is
    # a grammar capability, not a prescribed box-shaped final answer.
    intents = tuple(dict.fromkeys(("calm_prismatic", *intents)))
    text = " ".join((
        str(profile.get("id") or ""),
        str(profile.get("design_intent") or ""),
        *preferred,
    )).lower()
    base_seeds: list[str] = ["block", "slab"]
    if any(token in text for token in ("bar", "span", "street", "wing")):
        base_seeds.insert(0, "bar")
    if any(token in text for token in ("court", "gallery", "museum", "public", "civic")):
        base_seeds.append("profiled_prism")
    if any(token in text for token in ("tower", "vertical")):
        base_seeds.append("tower")
    bases = list(dict.fromkeys(base_seeds))
    lineage_names = tuple(dict.fromkeys(str(value) for value in source_seeds if str(value)))[:2]
    lineage_candidate_count = max(4, min(24, int(candidates_per_lineage)))
    compatible_typologies = typology_priors_for_program(
        profile_id,
        allowed_macro_operators=allowed_macro_operators,
    )
    # A compatible named chassis must carry at least one of its own primitive
    # proportions into the author pool. Otherwise Tower + Podium silently
    # degrades to a block merely because the program prose did not say
    # "tower", even though the executable typology contract did.
    bases = list(dict.fromkeys((
        *bases,
        *(
            seed
            for prior in compatible_typologies
            for seed in prior.preferred_base_seeds[:1]
        ),
    )))
    return tuple({
        "source_seed": source_seed,
        "base_seeds": bases,
        "intent_tags": list(intents),
        "typology_priors": [prior.typology_id for prior in compatible_typologies],
        "candidate_count": lineage_candidate_count,
        "maximum_operator_depth": 2,
        # Reserve one visual body relation for the later BOOK projection.
        # Public access/court is a separate terminal invariant and keeps its
        # own one-rule budget.
        "downstream_body_rule_reserve": 1,
        "allowed_macro_operators": allowed_macro_operators,
        "required_macro_operators_all": required_macro_operators_all,
        "required_macro_operators_any": required_macro_operators_any,
        "required_terminal_operator": (
            "profiled_hall" if "profiled_hall" in required_macro_operators_all else ""
        ),
        "required_access_bound_relation": bool(
            geometry_language_contract.get("requires_access_bound_relation")
        ),
        # Each semantic source lineage explores a disjoint low-discrepancy
        # interval.  Previously both started at zero and authored the same 12
        # solid programs, so doubling the advertised candidate count did not
        # double form-language coverage.
        "variation_offset": lineage_index * lineage_candidate_count,
        # A legal envelope is a hard constraint, not an untyped form author.
        # Height-interpolating the lower/upper parcel frames globally tapered
        # every otherwise distinct courtyard, split wing and cantilever into
        # the same shed/wedge silhouette.  Keep the recursive AST geometry
        # unchanged here; the downstream legal lane may uniformly fit, clip
        # and reject it while explicitly measuring geometry retention.
        "legal_fit_strengths": [0.0],
        "rationale": (
            "agent-inferred recursive geometry search from program design intent "
            "and preferred language capabilities; named section templates ignored"
        ),
        "inference_evidence": {
            "profile_id": profile_id or "generic",
            "early_typology_priors": [prior.typology_id for prior in compatible_typologies],
            "preferred_families": list(preferred),
            "section_control_templates_used": False,
            "parcel_coordinates_used": False,
            "disjoint_low_discrepancy_lineage_interval": True,
        },
    } for lineage_index, source_seed in enumerate(lineage_names))


def _program_from_stack(
    seed_id: str,
    operators: Iterable[str],
    *,
    site_extent: tuple[float, float, float] | None = None,
    scope_count: int = 1,
    operator_variant_indices: Iterable[int] | None = None,
    variation_index: int,
    variation_offset: int = 0,
    intent_tags: tuple[str, ...],
    building_type: str,
    required_terminal_operator: str = "",
    site_access_side: str = "closed",
    required_access_bound_relation: bool = False,
    required_macro_operators_all: tuple[str, ...] = (),
    typology_prior_id: str = "",
) -> GeometryProgram:
    seed = base_seed_program(seed_id, variation_index=variation_index,
                             site_extent=site_extent)
    nodes = list(seed.nodes)
    root_id = seed.root_id
    composed_scope_count = 1
    if scope_count > 1:
        composed = _composed_scope_root(nodes, seed, variation_index, scope_count)
        if composed is not None:
            root_id, composed_scope_count = composed
    operator_records = list(zip(
        operators,
        operator_variant_indices or (),
    ))
    if not operator_records:
        operator_records = [(operator, variation_index) for operator in operators]
    # Program thresholds and section are terminal relations over the mutated
    # body. BOOK/body operations are inserted before this suffix later, so a
    # rotate/taper cannot silently erase the street court or turn a hall roof
    # into a pyramid. This is relation ordering, not a completed form template.
    threshold_operators = {"courtyard", "carve_void", "notch", "lift", "cantilever", "split_wing"}
    operator_records.sort(key=lambda item: (
        2 if item[0] == "profiled_hall"
        else 1 if item[0] in threshold_operators
        else 0
    ))
    operator_path: list[str] = []
    for stack_index, (operator, operator_variant_index) in enumerate(operator_records, start=1):
        if operator == "identity":
            continue
        kind = _OPERATOR_KIND[operator]
        node_id = f"agent_{stack_index:02d}_{operator}"
        parameters = _bounded_parameters(
            operator,
            operator_variant_index if operator == "profiled_hall" else variation_index + stack_index * 17,
            intent_tags=intent_tags,
            site_access_side=site_access_side,
            force_access_bound=required_access_bound_relation,
            typology_prior_id=typology_prior_id,
        )
        inputs = (root_id,)
        if operator == "attach":
            # The attached guest remains an explicit graph node.  The
            # composition node places it in the selected host-face frame;
            # neither the author nor a later agent needs parcel coordinates.
            guest_parameters = profiled_prism_parameters(operator_variant_index + 1)
            guest_id = f"agent_{stack_index:02d}_attach_guest"
            nodes.append(GeometryNode(
                id=guest_id,
                kind="primitive",
                operator="extruded_polygon",
                parameters=guest_parameters,
                semantic_role="attached_guest_volume",
                provenance={
                    "source": "procedural_geometry_synthesis_agent",
                    "variation_index": variation_index,
                    "host_face_placement_deferred_to_attach_node": True,
                    "parcel_coordinates_used": False,
                },
            ))
            inputs = (root_id, guest_id)
        nodes.append(GeometryNode(
            id=node_id,
            kind=kind,
            operator=operator,
            inputs=inputs,
            parameters=parameters,
            semantic_role=(
                "program_section_invariant"
                if operator == "profiled_hall"
                else "public_threshold"
                if operator in threshold_operators
                else "dominant_mass"
            ),
            provenance={
                "source": "procedural_geometry_synthesis_agent",
                "intent_tags": list(intent_tags),
                "variation_index": variation_index,
                "bounded_parameter_generation": True,
                "parcel_coordinates_used": False,
                "completed_building_template": False,
                "program_invariant": operator == "profiled_hall" or operator in threshold_operators,
                "early_typology_prior": typology_prior_id,
            },
        ))
        root_id = node_id
        operator_path.append(operator)
    family = "agent_" + ("_".join(operator_path) if operator_path else "prismatic")
    digest = hashlib.sha256(json.dumps({
        "seed": seed_id,
        "operators": operator_path,
        "variation": variation_index,
        "intent": intent_tags,
    }, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    safe_program = re.sub(r"[^A-Za-z0-9]+", "_", building_type).strip("_").lower() or "program"
    return GeometryProgram(
        nodes=tuple(nodes),
        root_id=root_id,
        name=f"synth_{safe_program}_{seed_id}_{digest}",
        metadata={
            "family": family,
            "language_layer": "agent_synthesized_recursive_geometry",
            "base_seed": seed_id,
            "intent_tags": list(intent_tags),
            "operator_path": operator_path or ["prismatic"],
            "variation_index": variation_index,
            "variation_offset": variation_offset,
            "author_provider": "bounded_procedural_geometry_agent",
            "parcel_coordinates_in_program": False,
            "completed_building_template": False,
            "required_terminal_operator": required_terminal_operator,
            "required_macro_operators_all": list(required_macro_operators_all),
            "required_access_bound_relation": required_access_bound_relation,
            "site_access_side": site_access_side,
            "early_typology_prior": typology_prior_id,
        },
    )


def _compatible_stack(left: str, right: str) -> bool:
    # Keep one readable dominant rule.  Multiple repetition or void macros in
    # one short stack tend to create fragments or nested Boolean instability.
    if "identity" in {left, right}:
        return True
    left_family = _OPERATOR_EFFECT_FAMILY.get(left)
    right_family = _OPERATOR_EFFECT_FAMILY.get(right)
    if left_family and left_family == right_family:
        # The downstream articulation gate treats this as duplicated visual
        # effect stacking. Do not spend author/critic/BOOK budget on a graph
        # that is invalid by construction; continue the low-discrepancy
        # search to a different semantic relationship instead.
        return False
    repetition = {"radial_array", "cross_mass", "grid_mass", "split_wing"}
    voids = {"courtyard", "notch", "carve_void"}
    steps = {"setback", "stepped_mass", "terrace"}
    if left in repetition and right in repetition:
        return False
    if left in voids and right in voids:
        return False
    if left in steps and right in steps:
        return False
    return not ({left, right} & repetition and {left, right} & voids)


def _weighted_operator_palette(raw_palette: tuple[str, ...]) -> tuple[str, ...]:
    """Interleave weighted capabilities without starving other intent tags."""
    if not raw_palette:
        return ()
    unique = list(dict.fromkeys(raw_palette))
    counts = {operator: raw_palette.count(operator) for operator in unique}
    # Four or more repetitions are an explicit capability weight. Lower
    # counts usually come from the same operator appearing naturally in two
    # related intent tags and must not crowd out the rest of the grammar.
    weighted = [operator for operator in unique if counts[operator] >= 4]
    if not weighted:
        return tuple(unique)
    others = [operator for operator in unique if operator not in weighted]
    scheduled: list[str] = []
    if others:
        scheduled.append(others.pop(0))
    remaining = {operator: counts[operator] for operator in weighted}
    while any(remaining.values()) or others:
        for operator in weighted:
            if remaining[operator] > 0:
                scheduled.append(operator)
                remaining[operator] -= 1
        if others:
            scheduled.append(others.pop(0))
    return tuple(scheduled)


def _operator_occurrence_index(palette: tuple[str, ...], cursor: int, operator: str) -> int:
    """Return the zero-based visit count for one weighted operator."""
    if not palette:
        return 0
    cycles, remainder = divmod(max(0, int(cursor)), len(palette))
    return cycles * palette.count(operator) + sum(
        item == operator for item in palette[:remainder]
    )


def _base_seed_for_operator(
    operator: str,
    base_seeds: tuple[str, ...],
    *,
    cursor: int,
    palette_size: int,
    intent_tags: tuple[str, ...],
) -> str:
    """Choose a primitive/operator pairing from architectural capabilities.

    A base seed is not a frozen form.  Still, a compact profiled prism cannot
    serve as the only host for a long-span cut: it repeatedly failed coverage
    before the cut was even judged.  Pair longitudinal modifiers with BAR/SLAB
    when the program asks for long span, while later palette cycles may still
    explore every requested seed.  This is shape grammar compatibility, never
    parcel coordinates or a completed mass recipe.
    """
    choices = base_seeds
    if operator in {"cross_mass", "grid_mass", "split_wing", "bent_bar"}:
        relational = tuple(
            seed for seed in ("bar", "slab", "profiled_prism", "block")
            if seed in base_seeds
        )
        if relational:
            # These operators express a relation between long wings. A BLOCK
            # either makes cross_mass an identity-like rotated cube or makes
            # split_wing read as two toy chunks. Keep the seed normalized and
            # coordinate-free, but start from a legible longitudinal body.
            # A grid needs longitudinal rows whose rotated columns span and
            # join them. A broad slab produces three disconnected plates;
            # other relational operators can safely rotate through chassis.
            if operator == "grid_mass" and "bar" in relational:
                return "bar"
            choices = relational
            # Re-visiting one relation must advance through its compatible
            # chassis.  The former unconditional BAR return contradicted the
            # comment above and turned every split/cross/bent family into the
            # same thin ribbon.
            return choices[_cyclic_seed_index(cursor, len(choices))]
    if operator == "slice" and "long_span" in intent_tags:
        long_span = tuple(seed for seed in ("bar", "slab") if seed in base_seeds)
        if long_span:
            choices = long_span
    return choices[_cyclic_seed_index(cursor, len(choices))]


def _cyclic_seed_index(cursor: int, choices: int) -> int:
    """Return a low-collision seed index that reaches all choices deterministically."""
    if choices <= 1:
        return 0
    step = 1
    while math.gcd(step, choices) != 1:
        step += 1
    return (cursor * step) % choices


def _bounded_parameters(
    operator: str,
    index: int,
    *,
    intent_tags: tuple[str, ...] = (),
    site_access_side: str = "closed",
    force_access_bound: bool = False,
    typology_prior_id: str = "",
) -> dict[str, Any]:
    u = _halton(index + 1, 2)
    v = _halton(index + 1, 3)
    if operator == "bend":
        return {
            "axis": "x",
            "angle_degrees": round((28.0 if typology_prior_id == "freeform" else 20.0) + 34.0 * u, 3),
            "subdivisions": 8 if typology_prior_id == "freeform" else 4,
        }
    if operator == "bent_bar":
        return {"axis": "x", "angle_degrees": round(18.0 + 38.0 * u, 3), "subdivisions": 4}
    if operator == "taper":
        return {"axis": "z", "start_scale": [1.0, 1.0], "end_scale": [round(0.52 + 0.30 * u, 3), round(0.60 + 0.28 * v, 3)], "subdivisions": 3}
    if operator == "twist":
        return {"axis": "z", "angle_degrees": round(-28.0 + 56.0 * u, 3), "subdivisions": 4}
    if operator == "inflate":
        return {"axis": "z", "middle_scale": round(1.10 + 0.28 * u, 3), "subdivisions": 4}
    if operator == "pinch":
        return {"axis": "x", "waist_scale": round(0.44 + 0.32 * u, 3), "subdivisions": 4}
    if operator == "slice":
        return {
            "normal": [round(0.55 + 0.35 * u, 3), round(-0.2 + 0.4 * v, 3), -1.0],
            "offset_ratio": round(0.08 + 0.12 * u, 3),
            "keep_side": "positive",
        }
    if operator == "cut_corner":
        return {"corner": ("ne", "nw", "se", "sw")[index % 4], "ratio": round(0.16 + 0.18 * u, 3)}
    if operator == "shear":
        return {"axis": "x", "direction": "z", "amount": round(-0.18 + 0.36 * u, 3)}
    if operator == "radial_array":
        return {"count": 3 + index % 3, "total_angle_degrees": round(42.0 + 48.0 * u, 3), "pivot": "center"}
    if operator == "attach":
        return sample_face_attachment_parameters(index, u, v)
    if operator in {"courtyard", "carve_void"}:
        return {
            "margin_ratio": round(0.18 + 0.16 * u, 3),
            # The access side is derived from the live parcel's principal
            # frame before synthesis. It is a normalized semantic relation,
            # not a parcel coordinate or completed-form template.
            "open_side": (
                "closed" if typology_prior_id == "courtyard"
                else site_access_side if site_access_side != "closed" and (
                    force_access_bound or typology_prior_id == "ushape" or index % 3 != 0
                )
                else "south" if typology_prior_id == "ushape"
                else "closed"
            ),
        }
    if operator == "notch":
        if typology_prior_id == "lshape":
            return {
                "corner": "ne",
                "side": (
                    site_access_side
                    if force_access_bound and site_access_side != "closed"
                    else ""
                ),
                # Preserve the L topology while sampling the corner removal
                # from the normalized host.  A fixed 0.52 replayed identical
                # geometry on every form-bank replenishment page.
                "ratio": round(0.46 + 0.12 * u, 3),
                "width_ratio": round(0.44 + 0.14 * v, 3),
                "height_ratio": 1.0,
            }
        return {
            "corner": ("ne", "nw", "se", "sw")[index % 4],
            "side": (
                site_access_side
                if site_access_side != "closed" and (force_access_bound or index % 3 != 0)
                else ""
            ),
            "ratio": round(0.14 + 0.14 * u, 3),
            "width_ratio": round(0.28 + 0.22 * v, 3),
            "height_ratio": round(0.48 + 0.28 * v, 3),
        }
    if operator in {"setback", "stepped_mass", "terrace"}:
        return {
            "levels": 4 if typology_prior_id == "tower_podium" else 3 + index % 2,
            "setback_ratio": round((0.12 if typology_prior_id == "tower_podium" else 0.08) + 0.10 * u, 3),
            "shift_per_level": [round(0.02 + 0.08 * v, 3), 0.0, 0.0],
            "podium_scale": 1.65 if typology_prior_id == "tower_podium" else 1.0,
            "podium_height_ratio": 0.22 if typology_prior_id == "tower_podium" else 0.0,
        }
    if operator == "profiled_hall":
        families = tuple(SECTION_PROFILES)
        family = families[index % len(families)]
        cycle = (index // len(families)) % 4
        gain, eave_shift = (
            (1.0, 0.0),
            (0.86, 0.025),
            (1.12, -0.02),
            (0.96, 0.045),
        )[cycle]
        controls = section_profile_controls(family)
        eave = min(value[1] for value in controls)
        controls = [
            [
                value[0],
                round(max(0.18, min(1.20, eave + eave_shift + (value[1] - eave) * gain)), 4),
            ]
            for value in controls
        ]
        return {
            "span_axis": "x",
            "section_family": family,
            "section_controls": controls,
            "section_variant_index": cycle,
        }
    if operator == "cantilever":
        return {"start_ratio": round(0.48 + 0.22 * u, 3), "vector": [round(0.08 + 0.18 * v, 3), 0.0, 0.0]}
    if operator == "lift":
        return {
            "rise_ratio": round(0.12 + 0.20 * u, 3),
            "support_ratio": round(0.10 + 0.08 * v, 3),
            "access_side": site_access_side if force_access_bound else "closed",
        }
    if operator == "puncture":
        return {"axis": "x" if index % 2 == 0 else "y", "count": 2 + index % 2, "ratio": round(0.10 + 0.10 * u, 3)}
    if operator == "cross_mass":
        return {
            "angle_degrees": (
                90.0 if typology_prior_id == "grid"
                else round(74.0 + 22.0 * u, 3) if typology_prior_id == "cross"
                else round(68.0 + 34.0 * u, 3)
            ),
        }
    if operator == "grid_mass":
        return {
            "row_spacing_ratio": round(1.16 + 0.22 * u, 3),
            "column_offset_ratio": round(0.20 + 0.12 * v, 3),
        }
    if operator == "split_wing":
        long_span = "long_span" in intent_tags
        access_bound = force_access_bound and site_access_side in {"east", "west", "north", "south"}
        return {
            "axis": (
                "y" if access_bound and site_access_side in {"east", "west"}
                else "x"
            ),
            "gap_ratio": split_wing_gap_ratio_from_unit(u),
            "bridge": True,
            "height_ratio": round(0.48 + 0.24 * v, 3),
            "height": round(0.12 + 0.18 * u, 3),
            "ground_spine": bool(long_span or access_bound or typology_prior_id == "hshape"),
            "ground_spine_width_ratio": round(0.30 + 0.18 * v, 3),
            "ground_spine_height_ratio": round(0.16 + 0.12 * u, 3),
            "access_side": site_access_side if access_bound else "closed",
            "layout": "parallel" if typology_prior_id == "hshape" else "split",
        }
    return {}


def _composed_scope_root(
    nodes: list[GeometryNode],
    seed: Any,
    variation_index: int,
    scope_count: int,
) -> tuple[str, int] | None:
    """Replace the seed body with a connected set of UnitBox placements.

    Returns None when the seed is not UnitBox-derived - a profiled prism has
    no unit box to place - so those seeds keep their single-body path.

    Every added volume is another Matrix4 over the *same* primitive node, so
    the program still holds exactly one primitive. That is what the form
    bank's single-primitive rule checks, and it is why the existing `attach`
    path (which appends a second primitive) was being silently discarded.
    """

    unit = next(
        (node for node in nodes if node.kind == "primitive"),
        None,
    )
    if unit is None or unit.operator != "box":
        return None
    seed_matrix = next(
        (node for node in nodes if node.id == seed.root_id),
        None,
    )
    if seed_matrix is None or seed_matrix.operator != "matrix4":
        return None
    rows = seed_matrix.parameters.get("matrix4") or ()
    try:
        base_scale = (
            float(rows[0][0]), float(rows[1][1]), float(rows[2][2]),
        )
    except (IndexError, TypeError, ValueError):
        return None
    if min(base_scale) <= 0.0:
        return None

    placements = sample_connected_scope_set(
        scope_count,
        base_scale,
        lambda index: _halton(variation_index * 31 + index + 1,
                              _COMPOSITION_BASES[index % len(_COMPOSITION_BASES)]),
    )
    # Placement 0 is the base scale at zero offset by construction, which is
    # exactly the seed's own matrix. Reusing it keeps the seed node reachable;
    # emitting a duplicate left it orphaned and the program failed validation
    # with `unreachable_node`.
    placed_ids: list[str] = [seed_matrix.id]
    for index, placement in enumerate(placements[1:], start=1):
        node_id = f"scope_{index:02d}"
        nodes.append(GeometryNode(
            id=node_id,
            kind="transform",
            operator="matrix4",
            inputs=(unit.id,),
            parameters={"matrix4": matrix4_to_lists(compose_matrix4(
                scale_matrix4(placement.scale),
                translation_matrix4(placement.offset),
            ))},
            semantic_role="base_seed" if index == 0 else "composed_scope",
            provenance={
                "source": "procedural_geometry_synthesis_agent",
                "canonical_base_model": "1/1 UnitBox",
                "composed_scope_index": index,
                "parcel_coordinates_used": False,
            },
        ))
        placed_ids.append(node_id)
    root_id = placed_ids[0]
    for index, placed in enumerate(placed_ids[1:], start=1):
        node_id = f"scope_union_{index:02d}"
        nodes.append(GeometryNode(
            id=node_id,
            kind="boolean",
            operator="union",
            inputs=(root_id, placed),
            semantic_role="main",
            provenance={
                "source": "procedural_geometry_synthesis_agent",
                "regularized_boolean": True,
                "connected_by_construction": True,
            },
        ))
        root_id = node_id
    return root_id, len(placements)


def _halton(index: int, base: int) -> float:
    result = 0.0
    factor = 1.0
    value = max(1, int(index))
    while value:
        factor /= base
        value, remainder = divmod(value, base)
        result += remainder * factor
    return result


__all__ = ["synthesize_architectural_programs", "synthesis_requests_from_program_profile"]
