"""Post-BOOK projection of program relations onto a universal form.

This layer deliberately does not author a base mass.  It consumes the final
BOOK-projected recursive AST and adds only the typed relation controllers that
the resolved program contract requires: an access-bound public threshold and,
where declared, a terminal section invariant.  VLM review remains downstream.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
from typing import Any

from backend.app.modules.design.generation.maas.program_massing import program_reference_contract

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.book_chassis_compatibility import SPLIT_WING_RELATION_CONTRACT
from backend.app.modules.design.generation.maas.geometry_language.program_controller_contract import PROGRAM_PROJECTION_SOURCE, is_program_relation_candidate, is_usable_public_space_controller, relation_access_side
from backend.app.modules.design.generation.maas.geometry_language.section_profiles import SECTION_PROFILES, section_profile_controls


PROGRAM_PROJECTION_SCHEMA = "arr.maas.post_book_program_projection.v2"
_ACCESS_SIDES = frozenset({"east", "west", "north", "south"})
_OPEN_COURT_HAZARDS = frozenset({
    "cross_mass", "grid_mass", "radial_array", "related_array",
    "split_wing", "book_split", "book_branch", "shift_related", "offset_related",
    "bend", "bent_bar", "twist", "inflate", "pinch",
    "union", "cut_corner",
})
_LIFT_HAZARDS = frozenset({"union", "leaning_tower"})
_SPLIT_WING_HAZARDS = frozenset({
    "cross_mass", "grid_mass", "radial_array", "related_array",
    "split_wing", "book_split", "book_branch", "shift_related", "offset_related",
    "bend", "bent_bar", "twist", "union", "leaning_tower",
})


def _normalized_access_side(value: str) -> str:
    side = str(value or "").strip().lower()
    return side if side in _ACCESS_SIDES else "closed"


def _stable_unit(program: GeometryProgram, program_id: str, salt: str) -> float:
    digest = hashlib.sha256(
        f"{program.program_hash()}|{program_id}|{salt}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:4], "big") / float(2**32 - 1)


def _threshold_contract_value(
    contract: dict[str, Any],
    key: str,
    unit: float,
    fallback: tuple[float, float],
) -> float:
    """Read one normalized relation range from the data-backed use contract."""
    language_contract = (
        dict(contract.get("geometry_language_contract") or {})
        if isinstance(contract.get("geometry_language_contract"), dict)
        else {}
    )
    parameters = (
        dict(language_contract.get("public_threshold_parameters") or {})
        if isinstance(language_contract.get("public_threshold_parameters"), dict)
        else {}
    )
    raw = parameters.get(key)
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        try:
            lower, upper = sorted((float(raw[0]), float(raw[1])))
        except (TypeError, ValueError):
            lower, upper = fallback
    else:
        lower, upper = fallback
    lower = max(0.01, min(0.95, lower))
    upper = max(lower, min(0.95, upper))
    return lower + (upper - lower) * max(0.0, min(1.0, unit))


def _unique_node_id(program: GeometryProgram, suffix: str) -> str:
    existing = set(program.node_map)
    base = f"program_projection:{suffix}"
    if base not in existing:
        return base
    index = 2
    while f"{base}:{index}" in existing:
        index += 1
    return f"{base}:{index}"


def _append_connectivity_guard(
    program: GeometryProgram,
    *,
    program_id: str,
    suffix: str,
    architectural_use: str,
) -> GeometryProgram:
    """Apply an idempotent one-component postcondition to a projection."""
    node = GeometryNode(
        id=_unique_node_id(program, f"{program_id}:{suffix}_connectivity"),
        kind="macro",
        operator="join_related",
        inputs=(program.root_id,),
        parameters={"width_ratio": 0.20, "height_ratio": 0.28},
        semantic_role="program_connectivity_guard",
        provenance={
            "source": "program_projection_connectivity_guard",
            "program_conditioning_stage": "after_book",
            "program_id": program_id,
            "architectural_use": architectural_use,
            "program_invariant": True,
            "base_or_book_authority": False,
            "parcel_coordinates_used": False,
            "completed_building_template": False,
        },
    )
    return replace(program, nodes=(*program.nodes, node), root_id=node.id)


def _aligned_threshold_node(
    program: GeometryProgram,
    access_side: str,
) -> GeometryNode | None:
    if access_side == "closed":
        return None
    for node in reversed(program.topological_nodes()):
        if not is_program_relation_candidate(node):
            continue
        if (
            str(node.provenance.get("source") or "") == PROGRAM_PROJECTION_SOURCE
            and relation_access_side(node) == access_side
        ):
            return node
    return None


def _bind_existing_threshold_to_access(
    program: GeometryProgram,
    access_side: str,
    *,
    program_id: str,
    contract: dict[str, Any],
) -> tuple[GeometryProgram, GeometryNode | None]:
    """Bind one existing threshold relation instead of stacking another cut.

    Universal geometry may already contain a court, notch or lifted
    threshold whose side was intentionally unresolved before a use and live
    access edge were known.  Adding a second notch to that body produced the
    small detached-looking pieces seen by the final VLM.  Program projection
    may resolve the relation parameter, but it does not replace the base mass
    or add another form language.
    """
    if access_side == "closed":
        return program, None
    nodes = list(program.nodes)
    for index in range(len(nodes) - 1, -1, -1):
        node = nodes[index]
        if not is_program_relation_candidate(node):
            continue
        parameters = dict(node.parameters)
        relation_parameters = _threshold_parameters(
            program,
            program_id,
            node.operator,
            access_side,
            contract,
        )
        if node.operator in {"courtyard", "carve_void"}:
            parameters.update(relation_parameters)
        elif node.operator == "notch":
            parameters.update(relation_parameters)
        elif node.operator == "lift":
            parameters.update(relation_parameters)
        elif node.operator == "split_wing":
            parameters.update(relation_parameters)
        else:
            parameters["access_side"] = access_side
        rebound = replace(node, parameters=parameters, provenance={
            **node.provenance,
            "upstream_source": str(node.provenance.get("source") or ""),
            "source": PROGRAM_PROJECTION_SOURCE,
            "program_conditioning_stage": "after_book",
            "architectural_use": "resolve the existing public threshold to the verified access side",
            "program_invariant": True,
            "base_or_book_authority": False,
            "parcel_coordinates_used": False,
            "completed_building_template": False,
        })
        nodes[index] = rebound
        return replace(program, nodes=tuple(nodes)), rebound
    return program, None


def _threshold_operator(
    program: GeometryProgram,
    contract: dict[str, Any],
) -> str:
    """Select a minimal relation from semantics and final topology.

    Open courts express a declared court/atrium invariant only when the final
    BOOK topology can accept one safely.  Distributed or already cut bodies
    receive a shallow frontage notch so program projection cannot fragment the
    universal form merely to satisfy a label.
    """
    operators = {node.operator for node in program.nodes}
    # `union` stands in these hazard sets for "this body might be severed by a
    # void or a lift". That is true of an arbitrary union and false of a scope
    # composition, which is grown with a guaranteed overlap and is connected by
    # construction - a property the generator records on the union node itself.
    # Treating the operator as the proxy meant every composed program kept
    # ground_strategy = direct_edge, so adding composed supply made the
    # portfolio's ground-strategy spread worse rather than better and selection
    # failed on `ground_strategy_count_below_3`.
    if operators and all(
        node.provenance.get("connected_by_construction") is True
        for node in program.nodes
        if node.operator == "union"
    ) and any(node.operator == "union" for node in program.nodes):
        operators = operators - {"union"}
    program_id = str(contract.get("program_id") or "generic")
    language_contract = (
        dict(contract.get("geometry_language_contract") or {})
        if isinstance(contract.get("geometry_language_contract"), dict)
        else {}
    )
    allowed = {
        str(value or "").strip().lower()
        for value in language_contract.get("allowed_macro_operators") or ()
    }
    invariant_roles = {
        str(value or "").strip().lower()
        for item in contract.get("semantic_invariants") or ()
        if isinstance(item, dict)
        for value in (item.get("subject_role"), item.get("object_role"))
    }
    has_public_void_invariant = any(
        token in role
        for role in invariant_roles
        for token in ("court", "atrium", "void", "terrace")
    )
    u = _stable_unit(program, program_id, "threshold-language")
    profile_families = {
        str(node.parameters.get("profile_family") or "").strip().lower()
        for node in program.nodes
        if isinstance(node.parameters, dict)
    }
    preserves_nonorthogonal_profile = bool(
        profile_families.intersection({"triangular", "trapezoidal", "kite"})
    )
    topology_accepts_open_court = not (
        operators.intersection(_OPEN_COURT_HAZARDS)
        or operators.intersection({"courtyard", "carve_void", "notch"})
    )
    open_court_operator = (
        "courtyard" if "courtyard" in allowed
        else "carve_void" if "carve_void" in allowed
        else ""
    )
    # A non-orthogonal base profile is already a meaningful plan language.
    # Satisfy access with an undercroft when topology permits, instead of
    # automatically turning the measured footprint into a split or notched
    # orthogonal-looking outline. This is derived from the primitive's typed
    # profile family, never from candidate IDs or absolute coordinates.
    if (
        preserves_nonorthogonal_profile
        and "lift" in allowed
        and "lift" not in operators
        and not operators.intersection(_LIFT_HAZARDS)
    ):
        return "lift"
    # Program contracts select a relation vocabulary; the final BOOK topology
    # and a stable normalized sample select one member.  This produces real
    # threshold diversity without turning a use label into a base-form mold.
    if topology_accepts_open_court and open_court_operator and (
        u < (0.34 if has_public_void_invariant else 0.24)
    ):
        return open_court_operator
    if (
        "split_wing" in allowed
        and not operators.intersection(_SPLIT_WING_HAZARDS)
        and u < (0.58 if has_public_void_invariant else 0.42)
    ):
        return "split_wing"
    # A twisted vertical chassis cannot accept another plan split without
    # multiplying its section bands and outline vertices. Its program relation
    # belongs at the ground: one lifted undercroft supplies both access and a
    # usable public threshold while the upper torsion remains the base gesture.
    if (
        "twist" in operators
        and "lift" in allowed
        and not operators.intersection(_LIFT_HAZARDS)
    ):
        return "lift"
    if (
        "lift" in allowed
        and "lift" not in operators
        and not operators.intersection(_LIFT_HAZARDS)
        and u < 0.78
    ):
        return "lift"
    return "notch"


def _threshold_parameters(
    program: GeometryProgram,
    program_id: str,
    operator: str,
    access_side: str,
    contract: dict[str, Any],
) -> dict[str, Any]:
    # Bounded normalized variations are intentionally independent of parcel
    # coordinates and completed-building templates.
    u = _stable_unit(program, program_id, "threshold-primary")
    v = _stable_unit(program, program_id, "threshold-secondary")
    if operator in {"courtyard", "carve_void"}:
        return {
            "margin_ratio": round(_threshold_contract_value(
                contract,
                "courtyard_margin_ratio",
                u,
                (0.24, 0.30),
            ), 3),
            "open_side": access_side,
        }
    if operator == "lift":
        return {
            "rise_ratio": round(_threshold_contract_value(
                contract,
                "lift_rise_ratio",
                u,
                (0.12, 0.26),
            ), 3),
            "support_ratio": round(_threshold_contract_value(
                contract,
                "lift_support_ratio",
                v,
                (0.10, 0.16),
            ), 3),
            "access_side": access_side,
        }
    if operator == "split_wing":
        return {
            "layout": "split",
            "gap_ratio": round(_threshold_contract_value(
                contract,
                "split_gap_ratio",
                u,
                (
                    SPLIT_WING_RELATION_CONTRACT.minimum_public_gap_ratio,
                    SPLIT_WING_RELATION_CONTRACT.maximum_public_gap_ratio,
                ),
            ), 3),
            "ground_spine": True,
            "ground_spine_width_ratio": round(_threshold_contract_value(
                contract,
                "split_ground_spine_width_ratio",
                v,
                (0.22, 0.34),
            ), 3),
            "ground_spine_height_ratio": round(_threshold_contract_value(
                contract,
                "split_ground_spine_height_ratio",
                u,
                (0.16, 0.24),
            ), 3),
            "access_side": access_side,
        }
    return {
        "corner": ("ne", "nw", "se", "sw")[min(3, int(u * 4.0))],
        "side": access_side,
        "ratio": round(_threshold_contract_value(
            contract,
            "notch_depth_ratio",
            u,
            (0.14, 0.22),
        ), 3),
        "width_ratio": round(_threshold_contract_value(
            contract,
            "notch_width_ratio",
            v,
            (0.28, 0.42),
        ), 3),
        "height_ratio": round(_threshold_contract_value(
            contract,
            "notch_height_ratio",
            v,
            (0.48, 0.64),
        ), 3),
    }


def _append_threshold(
    program: GeometryProgram,
    *,
    program_id: str,
    contract: dict[str, Any],
    access_side: str,
) -> tuple[GeometryProgram, str, str]:
    existing = _aligned_threshold_node(program, access_side)
    if existing is not None:
        return program, existing.id, "reused_aligned_final_ast_controller"
    if access_side == "closed":
        return program, "", "unresolved_no_verified_access_side"

    rebound_program, rebound = _bind_existing_threshold_to_access(
        program,
        access_side,
        program_id=program_id,
        contract=contract,
    )
    if rebound is not None:
        return rebound_program, rebound.id, "rebound_existing_final_ast_controller"

    operator = _threshold_operator(program, contract)
    node = GeometryNode(
        id=_unique_node_id(program, f"{program_id}:public_threshold"),
        kind="macro",
        operator=operator,
        inputs=(program.root_id,),
        parameters=_threshold_parameters(
            program,
            program_id,
            operator,
            access_side,
            contract,
        ),
        semantic_role="public_threshold",
        provenance={
            "source": "post_book_program_projection",
            "program_conditioning_stage": "after_book",
            "program_id": program_id,
            "architectural_use": "bind the public threshold to the verified access side",
            "program_invariant": True,
            "base_or_book_authority": False,
            "bounded_parameter_generation": True,
            "parcel_coordinates_used": False,
            "completed_building_template": False,
        },
    )
    thresholded = replace(
        program,
        nodes=(*program.nodes, node),
        root_id=node.id,
    )
    return _append_connectivity_guard(
        thresholded,
        program_id=program_id,
        suffix="public_threshold",
        architectural_use="retain one connected building after public-threshold projection",
    ), node.id, "added_post_book_controller"


def _public_space_invariant_id(contract: dict[str, Any]) -> str:
    for item in contract.get("semantic_invariants") or ():
        if not isinstance(item, dict):
            continue
        text = " ".join(str(item.get(key) or "") for key in (
            "id", "subject_role", "relation", "object_role",
        )).lower()
        if any(token in text for token in (
            "void_or_terrace", "mixed_public_program", "public_space",
        )):
            return str(item.get("id") or "program_public_space")
    return ""


def _is_substantial_frontage_cut(
    node: GeometryNode,
    contract: dict[str, Any],
) -> bool:
    """Whether a normalized access notch is large enough to be occupiable.

    The minimums come from the resolved program contract.  This prevents a
    decorative shallow cut from satisfying a public-space invariant while
    avoiding a second court/split operation when the first cut is already a
    usable Base-relative street room.
    """
    if (
        node.operator != "notch"
        or str(node.provenance.get("source") or "") != PROGRAM_PROJECTION_SOURCE
        or relation_access_side(node) == "closed"
    ):
        return False
    parameters = node.parameters
    return bool(
        float(parameters.get("ratio") or 0.0) >= _threshold_contract_value(
            contract, "notch_depth_ratio", 0.0, (0.14, 0.22)
        )
        and float(parameters.get("width_ratio") or 0.0) >= _threshold_contract_value(
            contract, "notch_width_ratio", 0.0, (0.28, 0.42)
        )
        and float(parameters.get("height_ratio") or 0.0) >= _threshold_contract_value(
            contract, "notch_height_ratio", 0.0, (0.48, 0.64)
        )
    )


def _append_public_space_invariant(
    program: GeometryProgram,
    *,
    program_id: str,
    contract: dict[str, Any],
    access_side: str,
) -> tuple[GeometryProgram, str, str]:
    """Add one missing usable-space relation without replacing base/BOOK nodes."""
    invariant_id = _public_space_invariant_id(contract)
    if not invariant_id:
        return program, "", "not_required"
    existing = next((
        node for node in program.nodes
        if (
            is_usable_public_space_controller(node)
            or _is_substantial_frontage_cut(node, contract)
        )
    ), None)
    if existing is not None:
        status = (
            "reused_substantial_frontage_cut_as_public_space"
            if _is_substantial_frontage_cut(existing, contract)
            else
            "reused_program_threshold_as_public_space"
            if existing.semantic_role == "public_threshold"
            and existing.provenance.get("source") == "post_book_program_projection"
            else "reused_existing_spatial_relation"
        )
        return program, existing.id, status
    language_contract = (
        dict(contract.get("geometry_language_contract") or {})
        if isinstance(contract.get("geometry_language_contract"), dict)
        else {}
    )
    allowed = {
        str(value or "").strip().lower()
        for value in language_contract.get("allowed_macro_operators") or ()
    }
    configured = [
        str(value or "").strip().lower()
        for value in language_contract.get("public_space_operators") or ()
    ]
    operators = [
        operator for operator in configured
        if operator in {"courtyard", "split_wing"}
        and (not allowed or operator in allowed)
    ]
    if not operators:
        return program, "", "required_operator_unavailable"
    unit = _stable_unit(program, program_id, "public-space-language")
    start = min(len(operators) - 1, int(unit * len(operators)))
    operator = operators[start]
    parameters = _threshold_parameters(
        program,
        program_id,
        operator,
        access_side,
        contract,
    )
    node = GeometryNode(
        id=_unique_node_id(program, f"{program_id}:public_space"),
        kind="macro",
        operator=operator,
        inputs=(program.root_id,),
        parameters=parameters,
        semantic_role="program_public_space",
        provenance={
            "source": PROGRAM_PROJECTION_SOURCE,
            "program_conditioning_stage": "after_book",
            "program_id": program_id,
            "semantic_invariant_id": invariant_id,
            "architectural_use": "form one usable public court or passage beyond the street threshold",
            "program_invariant": True,
            "base_or_book_authority": False,
            "bounded_parameter_generation": True,
            "parcel_coordinates_used": False,
            "completed_building_template": False,
        },
    )
    projected = replace(program, nodes=(*program.nodes, node), root_id=node.id)
    connected = _append_connectivity_guard(
        projected,
        program_id=program_id,
        suffix="public_space",
        architectural_use="retain one connected building after public-space projection",
    )
    return connected, node.id, "added_missing_program_spatial_relation"


def _append_required_section(
    program: GeometryProgram,
    *,
    program_id: str,
    contract: dict[str, Any],
) -> tuple[GeometryProgram, str]:
    language_contract = (
        dict(contract.get("geometry_language_contract") or {})
        if isinstance(contract.get("geometry_language_contract"), dict)
        else {}
    )
    required_all = {
        str(value or "").strip().lower()
        for value in language_contract.get("required_macro_operators_all") or ()
    }
    if "profiled_hall" not in required_all:
        return program, ""
    existing = next((
        node for node in program.nodes
        if node.operator == "profiled_hall"
        and node.provenance.get("source") == "post_book_program_projection"
    ), None)
    if existing is not None:
        return program, existing.id

    families = tuple(SECTION_PROFILES)
    unit = _stable_unit(program, program_id, "required-section")
    family = families[min(len(families) - 1, int(unit * len(families)))]
    node = GeometryNode(
        id=_unique_node_id(program, f"{program_id}:section"),
        kind="macro",
        operator="profiled_hall",
        inputs=(program.root_id,),
        parameters={
            "span_axis": "x",
            "section_family": family,
            "section_controls": section_profile_controls(family),
            "section_variant_index": 0,
        },
        semantic_role="program_section_invariant",
        provenance={
            "source": "post_book_program_projection",
            "program_conditioning_stage": "after_book",
            "program_id": program_id,
            "architectural_use": "express the declared long-span structure and daylight section",
            "program_invariant": True,
            "base_or_book_authority": False,
            "bounded_parameter_generation": True,
            "parcel_coordinates_used": False,
            "completed_building_template": False,
        },
    )
    sectioned = replace(
        program,
        nodes=(*program.nodes, node),
        root_id=node.id,
    )
    # A normalized roof profile can reveal separate lobes in an otherwise
    # connected distributed plan. ``join_related`` is a no-op for one
    # component and adds the minimum nearest-component connector only when
    # necessary; it is a postcondition, not another form language.
    return _append_connectivity_guard(
        sectioned,
        program_id=program_id,
        suffix="section",
        architectural_use="retain one occupiable connected hall after section projection",
    ), node.id


def project_program_requirements(
    program: GeometryProgram,
    *,
    building_type: str,
    access_side: str,
) -> GeometryProgram:
    """Project resolved program relations after BOOK and before hard gates."""
    contract = program_reference_contract(building_type)
    program_id = str(contract.get("program_id") or "generic")
    side = _normalized_access_side(access_side)
    before_hash = program.program_hash()

    projected, threshold_id, threshold_status = _append_threshold(
        program,
        program_id=program_id,
        contract=contract,
        access_side=side,
    )
    projected, public_space_id, public_space_status = _append_public_space_invariant(
        projected,
        program_id=program_id,
        contract=contract,
        access_side=side,
    )
    projected, section_id = _append_required_section(
        projected,
        program_id=program_id,
        contract=contract,
    )
    node_ids = tuple(value for value in (
        threshold_id,
        public_space_id,
        section_id,
    ) if value)
    metadata = {
        **projected.metadata,
        "program_conditioned": True,
        "program_projection_applied": True,
        "program_projection_stage": "post_book",
        "program_projection": {
            "schema_version": PROGRAM_PROJECTION_SCHEMA,
            "program_id": program_id,
            "building_type": str(building_type or ""),
            "access_side": side,
            "threshold_status": threshold_status,
            "threshold_controller_node_id": threshold_id,
            "public_space_status": public_space_status,
            "public_space_controller_node_id": public_space_id,
            "section_controller_node_id": section_id,
            "controller_node_ids": list(node_ids),
            "pre_program_projection_hash": before_hash,
            "universal_form_preserved": True,
            "base_or_book_authority": False,
            "vlm_role": "downstream_critic_and_repair_only",
        },
    }
    return replace(projected, metadata=metadata)


__all__ = [
    "PROGRAM_PROJECTION_SCHEMA",
    "project_program_requirements",
]
