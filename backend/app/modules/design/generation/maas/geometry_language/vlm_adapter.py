"""Adapter from compiled geometry programs to the existing OpenAI VLM critic."""

from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable
import uuid

from backend.app.modules.design.generation.maas.preference.vlm_scorer import DEFAULT_VLM_MODEL, VLM_PROMPT_CONTRACT_VERSION, audit_reference_image_for_massing, score_candidate_with_openai_vlm
from backend.app.modules.design.generation.maas.preference.reference_paths import resolve_reference_image_path, workspace_root
from backend.app.modules.design.generation.maas.preference.reference_corpus import ReferenceItem, default_reference_root, load_reference_tree, match_reference_context
from backend.app.modules.design.generation.maas.program_massing.profiles import program_reference_contract

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.base_seeds import base_seed_catalog
from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult
from backend.app.modules.design.generation.maas.geometry_language.mutation import ALLOWED_EDIT_OPERATIONS, BOOLEAN_PARAMETERS, NUMERIC_BOUNDS, OPERATOR_PARAMETER_CONTRACTS, STRING_PARAMETER_VALUES, VECTOR_LENGTHS


OPERATOR_EFFECTS = {
    "box": "establish a rectilinear solid datum",
    "extruded_polygon": "establish a profiled plan extrusion",
    "translate": "move a solid without changing its topology",
    "scale": "change normalized width, depth or height proportion",
    "rotate": "change orientation about a declared pivot",
    "shear": "lean one section while retaining a continuous solid",
    "bend": "curve a continuous longitudinal solid axis",
    "taper": "change section scale along an axis",
    "twist": "rotate successive sections along an axis",
    "pinch": "contract an intermediate waist while preserving both ends",
    "inflate": "swell the middle of a continuous solid without adding fragments",
    "slice": "retain one side of a declared cutting plane",
    "clip_fraction": "select a normalized BOOK p.3 fraction of the live solid bounds",
    "book_base_volume": "select the exact connected normalized cell volume shown on BOOK p.3",
    "cut_corner": "remove a bounded corner with a plane cut",
    "lift": "raise a dominant body over bounded structural supports",
    "book_lift": "displace one smaller related volume from a larger host while retaining overlap",
    "book_lodge": "lodge one smaller guest between two related host volumes",
    "book_rotate": "rotate one partitioned bar about a shared hinge edge",
    "book_carve": "subtract a bounded rectangular recess normal to the selected base-volume face",
    "book_fracture": "subtract a bent fissure from one selected face while retaining a connected back layer",
    "book_grade": "subtract successively deeper face bands to form a connected four-step grade",
    "book_notch": "subtract a triangular wedge from one selected base-volume face",
    "book_extract": "subtract an overlapping guest path from an internal position through an exterior mouth",
    "puncture": "subtract a bounded array of through-openings",
    "union": "join input solids into one Boolean result",
    "difference": "subtract the second input from the first",
    "radial_array": "repeat and rotate a solid about a pivot",
    "grid_mass": "cross connected parallel rows and columns into an occupiable field",
    "merge_related": "fuse a scaled related unit through a measured live-solid overlap",
    "overlap_related": "overlap a shifted slab while retaining a measured vertical intersection",
    "offset_related": "offset a scaled related body by a measured live-solid span",
    "nested_related": "retain an inner related volume inside the host plan and reveal its roof datum",
    "interlock_related": "cross a locking bar through the host using measured live-solid spans",
    "intersect_related": "cross and retain two overlapping volumes as one connected relation",
    "stack": "repeat a solid across height levels",
    "courtyard": "carve an inner public or environmental void",
    "setback": "form successively reduced occupied levels",
    "split_wing": "separate wings and optionally reconnect them",
    "book_split": "hinge-displace one terminal child while retaining a shared opposite trunk",
    "sweep": "carry a profile along an explicit spatial path",
    "loft": "interpolate a solid between explicit profiles",
    "profiled_hall": "compile a normalized long-span roof/section profile over the live base solid",
}


def build_geometry_graph_notes(
    program: GeometryProgram,
    compilation: CompilationResult,
) -> list[dict[str, Any]]:
    """Expose agent-readable intent without making notes executable geometry."""
    trace_by_node = {str(item.get("node_id") or ""): item for item in compilation.trace}
    notes = []
    for node in program.topological_nodes():
        provenance = node.provenance if isinstance(node.provenance, dict) else {}
        trace = trace_by_node.get(node.id, {})
        notes.append({
            "node_id": node.id,
            "semantic_role": node.semantic_role or "unspecified",
            "operator": node.operator,
            "input_ids": list(node.inputs),
            "design_intent": str(
                provenance.get("rationale")
                or provenance.get("architectural_use")
                or OPERATOR_EFFECTS.get(node.operator, f"apply typed {node.operator} geometry operation")
            ),
            "expected_geometry_effect": OPERATOR_EFFECTS.get(node.operator, f"apply typed {node.operator} geometry operation"),
            "editable_parameters": sorted(node.parameters),
            "operator_parameter_contract": sorted(OPERATOR_PARAMETER_CONTRACTS.get(node.operator, ())),
            "protected_program_invariant": bool(
                node.operator == "profiled_hall"
                or node.semantic_role == "program_section_invariant"
                or provenance.get("program_invariant")
            ),
            "allowed_edit_operations": (
                ["set_parameter:section_family", "set_parameter:span_axis"]
                if node.operator == "profiled_hall"
                else sorted(ALLOWED_EDIT_OPERATIONS)
            ),
            "preserve": [
                "declared input references", "closed manifold solid", "hard-gate constraints",
                *( ["program section invariant"] if node.operator == "profiled_hall" else [] ),
            ],
            "compiled_evidence": {
                "triangle_count": int(trace.get("triangle_count") or 0),
                "volume": float(trace.get("volume") or 0.0),
            },
            "note_is_non_executable": True,
        })
    return notes


def build_geometry_graph_snapshot(
    program: GeometryProgram,
    compilation: CompilationResult,
    *,
    program_context: dict[str, Any] | None = None,
    reference_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the stable, machine-readable graph contract used by AI agents.

    The program AST remains authoritative.  Notes and compiled measurements are
    observation data bound to node IDs, never an alternate source of geometry.
    """
    notes = build_geometry_graph_notes(program, compilation)
    protected_node_ids = [
        str(note["node_id"])
        for note in notes
        if note.get("protected_program_invariant")
    ]
    context = dict(program_context or {})
    invariants = [
        dict(item) for item in context.get("semantic_invariants") or ()
        if isinstance(item, dict) and item.get("id")
    ]
    reference_nodes = [
        {
            "node_id": f"reference:{str(item.get('source_id') or item.get('title') or index)}",
            "node_kind": "reference_evidence",
            "source_id": str(item.get("source_id") or ""),
            "title": str(item.get("title") or ""),
            "selection_role": str(item.get("selection_role") or ""),
            "program_match_tier": str(item.get("program_match_tier") or ""),
            "reference_collection": str(item.get("reference_collection") or ""),
            "program_matched_terms": list(item.get("program_matched_terms") or ()),
            "editable": False,
        }
        for index, item in enumerate(reference_matches or ())
        if isinstance(item, dict)
    ]
    program_node_id = f"program:{str(context.get('program_id') or 'generic')}"
    site_access = (
        dict(context.get("site_access_context") or {})
        if isinstance(context.get("site_access_context"), dict)
        else {}
    )
    dimensional = (
        dict(context.get("program_dimensional_context") or {})
        if isinstance(context.get("program_dimensional_context"), dict)
        else {}
    )
    program_zones = [
        dict(item) for item in context.get("program_space_zones") or ()
        if isinstance(item, dict) and item.get("zone_id")
    ]
    site_access_node_id = "site:primary_access"
    dimensional_node_id = f"program:{str(context.get('program_id') or 'generic')}:dimensions"
    context_graph = {
        "schema_version": "arr.maas.program_context_graph.v1",
        "root_node_id": program_node_id,
        "nodes": [
            {
                "node_id": program_node_id,
                "node_kind": "program_contract",
                "program_id": str(context.get("program_id") or "generic"),
                "design_intent": str(context.get("design_intent") or ""),
                "editable": False,
            },
            *([{
                "node_id": site_access_node_id,
                "node_kind": "site_access_contract",
                "primary_access_edge": str(site_access.get("primary_access_edge") or ""),
                "program_frame_side": str(context.get("site_access_side_in_program_frame") or "closed"),
                "road_width_m": site_access.get("road_width_m"),
                "editable": False,
            }] if site_access else []),
            *([{
                "node_id": dimensional_node_id,
                "node_kind": "program_dimensional_contract",
                "selected_subtype": str(dimensional.get("selected_subtype") or ""),
                "minimum_clear_span_m": dimensional.get("minimum_clear_span_m"),
                "effective_height_m": dimensional.get("effective_height_m"),
                "maximum_height_to_clear_span_ratio": dimensional.get("maximum_height_to_clear_span_ratio"),
                "editable": False,
            }] if dimensional else []),
            *[
                {
                    "node_id": f"invariant:{item['id']}",
                    "node_kind": "semantic_invariant",
                    **item,
                    "editable": False,
                }
                for item in invariants
            ],
            *reference_nodes,
            *[
                {
                    "node_id": str(item["zone_id"]),
                    "node_kind": "normalized_program_space_zone",
                    "role": str(item.get("role") or ""),
                    "normalized_center": list(item.get("normalized_center") or ()),
                    "nearest_envelope_side": str(item.get("nearest_envelope_side") or ""),
                    "physical_envelope_owner_role": str(item.get("physical_envelope_owner_role") or ""),
                    "editable": False,
                }
                for item in program_zones
            ],
        ],
        "edges": [
            *[
                {
                    "source_node_id": f"invariant:{item['id']}",
                    "target_node_id": program_node_id,
                    "relation": "required_by_program",
                }
                for item in invariants
            ],
            *[
                {
                    "source_node_id": item["node_id"],
                    "target_node_id": program_node_id,
                    "relation": "retrieved_as_program_evidence",
                }
                for item in reference_nodes
            ],
            *([{
                "source_node_id": site_access_node_id,
                "target_node_id": program_node_id,
                "relation": "conditions_public_threshold",
            }] if site_access else []),
            *([{
                "source_node_id": dimensional_node_id,
                "target_node_id": program_node_id,
                "relation": "bounds_program_envelope",
            }] if dimensional else []),
            *[
                {
                    "source_node_id": str(item["zone_id"]),
                    "target_node_id": program_node_id,
                    "relation": "occupies_normalized_program_zone",
                }
                for item in program_zones
            ],
        ],
        "context_nodes_are_edit_targets": False,
    }
    ordered_geometry_nodes = program.topological_nodes()
    dominant_controller_ids = [
        node.id for node in ordered_geometry_nodes
        if (
            "dominant" in str(node.semantic_role or "").strip().lower()
            or str(node.semantic_role or "").strip().lower() in {
                "main_mass", "primary_mass", "public_gallery_hall", "clear_span_program",
            }
        )
    ]
    # Unlike a public threshold, every compiled program necessarily has a
    # dominant solid controller: the executable root.  Expose it as the
    # fallback edit target when an author omitted the richer program role.
    if not dominant_controller_ids:
        dominant_controller_ids = [program.root_id]
    section_controller_ids = [
        node.id for node in ordered_geometry_nodes
        if node.operator == "profiled_hall"
        or str(node.semantic_role or "").strip().lower() in {
            "program_section_invariant", "roof_section", "structure_daylight_section",
        }
    ]
    explicit_threshold_controller_nodes = [
        node for node in ordered_geometry_nodes
        if node.operator in {"courtyard", "carve_void", "notch", "lift", "cantilever", "split_wing"}
    ]
    # A geometry node only controls a public threshold after an explicit
    # architectural operation materialises that relation.  The current root
    # remains a legal *wrap target* for a critic-authored node, but calling the
    # root itself a controller tells the LLM/VLM that an unresolved direct edge
    # is already designed.  Keep those two meanings separate in the graph.
    threshold_controller_nodes = explicit_threshold_controller_nodes
    threshold_controller_ids = [node.id for node in threshold_controller_nodes]
    threshold_wrap_target_ids = (
        [] if explicit_threshold_controller_nodes else [program.root_id]
    )
    target_open_side = str(context.get("site_access_side_in_program_frame") or "closed")
    threshold_controller_bindings = [
        {
            "geometry_node_id": node.id,
            "operator": node.operator,
            "open_side": str(node.parameters.get("open_side") or "not_applicable"),
            "aligned_to_access": bool(
                node.operator in {"courtyard", "carve_void", "notch", "lift", "split_wing"}
                and target_open_side != "closed"
                and str(
                    node.parameters.get("open_side")
                    if node.operator in {"courtyard", "carve_void"}
                    else node.parameters.get("side")
                    if node.operator == "notch"
                    else node.parameters.get("access_side")
                    or "closed"
                ) == target_open_side
            ),
            "access_side_parameter": str(
                node.parameters.get("open_side")
                if node.operator in {"courtyard", "carve_void"}
                else node.parameters.get("side")
                if node.operator == "notch"
                else node.parameters.get("access_side")
                or "not_applicable"
            ),
        }
        for node in threshold_controller_nodes
    ]
    aligned_threshold_controller_ids = [
        item["geometry_node_id"] for item in threshold_controller_bindings
        if item["aligned_to_access"]
    ]
    entry_zone_nodes = [
        str(item["zone_id"]) for item in program_zones
        if any(token in str(item.get("role") or "").lower() for token in ("entry", "public", "lobby"))
    ]
    access_aligned_entry_zone_nodes = [
        str(item["zone_id"]) for item in program_zones
        if str(item["zone_id"]) in entry_zone_nodes
        and str(item.get("nearest_envelope_side") or "") == target_open_side
    ]
    design_concept_graph = {
        "schema_version": "arr.maas.design_concept_graph.v1",
        "status": "materialized",
        "concept_nodes": [
            {
                "concept_id": "concept:dominant_program_space",
                "architectural_question": "What is the one dominant occupiable program volume?",
                "controller_node_ids": dominant_controller_ids,
                "required": True,
            },
            {
                "concept_id": "concept:public_threshold",
                "architectural_question": "How does the building open toward the verified public access edge?",
                "controller_node_ids": threshold_controller_ids,
                "available_wrap_target_node_ids": threshold_wrap_target_ids,
                "required": bool(site_access),
                "target_open_side": target_open_side,
                "controller_bindings": threshold_controller_bindings,
                "controller_mode": (
                    "explicit_mass_articulation"
                    if explicit_threshold_controller_nodes
                    else "direct_edge_root_available_for_typed_add_node"
                ),
                "frontage_aligned_controller_node_ids": aligned_threshold_controller_ids,
                "program_entry_zone_node_ids": entry_zone_nodes,
                "access_aligned_program_entry_zone_node_ids": access_aligned_entry_zone_nodes,
                "frontage_alignment_status": (
                    "aligned" if aligned_threshold_controller_ids
                    else (
                        "controller_without_explicit_alignment"
                        if explicit_threshold_controller_nodes
                        else "direct_edge_unarticulated"
                    )
                ),
                "missing_controller": bool(site_access and not explicit_threshold_controller_nodes),
            },
            {
                "concept_id": "concept:structure_daylight_section",
                "architectural_question": "How does roof and section express span, structure or daylight?",
                "controller_node_ids": section_controller_ids,
                "required": any("roof" in str(item.get("id") or "") for item in invariants),
                "missing_controller": bool(
                    any("roof" in str(item.get("id") or "") for item in invariants)
                    and not section_controller_ids
                ),
            },
        ],
        "causal_bindings": [
            *[
                {
                    "source_context_node_id": program_node_id,
                    "target_geometry_node_id": node_id,
                    "relation": "controls_dominant_program_space",
                }
                for node_id in dominant_controller_ids
            ],
            *[
                {
                    "source_context_node_id": site_access_node_id,
                    "target_geometry_node_id": node_id,
                    "relation": "controls_public_threshold",
                }
                for node_id in threshold_controller_ids
            ],
            *[
                {
                    "source_context_node_id": site_access_node_id,
                    "target_geometry_node_id": node_id,
                    "relation": "available_for_public_threshold_mutation",
                }
                for node_id in threshold_wrap_target_ids
            ],
            *[
                {
                    "source_context_node_id": program_node_id,
                    "target_geometry_node_id": node_id,
                    "relation": "controls_structure_daylight_section",
                }
                for node_id in section_controller_ids
            ],
        ],
        "context_is_observation_only": True,
        "geometry_controller_ids_are_typed_edit_targets": True,
    }
    return {
        "schema_version": "arr.maas.ai_readable_geometry_graph.v2",
        "program_name": program.name,
        "root_node_id": program.root_id,
        "nodes": notes,
        "edges": [
            {
                "source_node_id": input_id,
                "target_node_id": node.id,
                "input_index": input_index,
                "relation": "solid_input",
            }
            for node in program.topological_nodes()
            for input_index, input_id in enumerate(node.inputs)
        ],
        "agent_edit_contract": {
            "authoritative_source": "geometry_program",
            "target_selector": "node_id",
            "response_field": "geometry_edits",
            "allowed_operations": sorted(ALLOWED_EDIT_OPERATIONS),
            "requires_semantic_validation": True,
            "requires_recompile_and_rerender": True,
            "requires_geometry_hash_change": True,
            "requires_hard_gate_recheck": True,
            "must_preserve_program_context_graph": True,
            "protected_geometry_node_ids": protected_node_ids,
            "protected_node_rule": "never replace/remove/rewire; a new root must keep protected nodes in its ancestry",
            "operator_parameter_contracts": {
                operator: sorted(parameters)
                for operator, parameters in sorted(OPERATOR_PARAMETER_CONTRACTS.items())
            },
            "operator_parameter_value_contracts": {
                operator: {
                    parameter: _agent_parameter_value_contract(operator, parameter)
                    for parameter in sorted(parameters)
                }
                for operator, parameters in sorted(OPERATOR_PARAMETER_CONTRACTS.items())
            },
        },
        "program_context_graph": context_graph,
        "design_concept_graph": design_concept_graph,
        "compiled_root_evidence": {
            "status": compilation.status,
            "geometry_hash": compilation.geometry_hash,
            "triangle_count": int(compilation.metrics.get("triangle_count") or 0),
            "volume": float(compilation.metrics.get("volume") or 0.0),
        },
    }


def _agent_parameter_value_contract(operator: str, parameter: str) -> dict[str, Any]:
    allowed = STRING_PARAMETER_VALUES.get((operator, parameter))
    if allowed is not None:
        return {"type": "string", "enum": sorted(allowed)}
    if parameter == "axis":
        return {"type": "string", "enum": ["x", "y", "z"]}
    if parameter in VECTOR_LENGTHS:
        return {"type": "numeric_vector", "lengths": list(VECTOR_LENGTHS[parameter])}
    if parameter in NUMERIC_BOUNDS:
        lower, upper = NUMERIC_BOUNDS[parameter]
        return {"type": "number", "minimum": lower, "maximum": upper}
    if parameter in BOOLEAN_PARAMETERS:
        return {"type": "boolean"}
    if parameter in {"points", "holes", "path", "profiles", "section_controls"}:
        return {"type": "structured_literal", "critic_editable": False, "dsl_author_only": True}
    return {"type": "literal", "requires_compile_validation": True}


def score_geometry_program_with_openai_vlm(
    program: GeometryProgram,
    compilation: CompilationResult,
    preview_path: Path,
    *,
    reference_matches: list[dict[str, Any]] | None = None,
    outcome_memory_context: dict[str, Any] | None = None,
    building_type: str = "",
    program_context: dict[str, Any] | None = None,
    model: str | None = None,
    write_passport_sidecar: bool = True,
    max_retries: int | None = None,
) -> dict[str, Any]:
    """Ask the live critic for bounded typed AST edits, not descriptive labels."""
    from backend.app.modules.design.generation.maas.geometry_language.execution_agent_context import build_mass_execution_agent_context
    from backend.app.modules.design.generation.maas.geometry_language.execution_passport import build_mass_execution_passport

    context = dict(program_context or program_reference_contract(building_type))
    reference_audit = audit_reference_matches_for_massing(
        reference_matches or [],
        building_type=building_type,
        model=model,
        limit=5,
        max_retries=max_retries,
    )
    reference_matches = list(reference_audit["accepted"])
    pre_review_passport = build_mass_execution_passport(
        compilation,
        preview_path=preview_path,
    )
    graph_snapshot = build_geometry_graph_snapshot(
        program,
        compilation,
        program_context=context,
        reference_matches=reference_matches or [],
    )
    execution_agent_context = build_mass_execution_agent_context(
        pre_review_passport,
        geometry_graph_snapshot=graph_snapshot,
    )
    feature = {
        "type": "Feature",
        "geometry": None,
        "properties": {
            "candidate_id": program.name,
            "geometry_program": program.to_dict(),
            "geometry_program_compilation": compilation.to_dict(include_mesh=False),
            "geometry_graph_notes": build_geometry_graph_notes(program, compilation),
            "program_context": context,
            "geometry_graph_snapshot": graph_snapshot,
            "base_seed_catalog": list(base_seed_catalog()),
            "geometry_language": sorted({node.operator for node in program.nodes}),
            "outcome_memory_context": outcome_memory_context or {
                "schema_version": "arr.maas.geometry_agent_neighborhood.v1",
                "observation_count": 0,
                "status": "no_prior_observation",
            },
            "mass_execution_agent_context": execution_agent_context,
        },
    }
    cache_path = _geometry_vlm_cache_path(
        program=program,
        compilation=compilation,
        preview_path=preview_path,
        reference_matches=reference_matches or [],
        program_context=context,
        outcome_memory_context=outcome_memory_context or {},
        model=model,
    )
    result: dict[str, Any] | None = None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            isinstance(cached, dict)
            and cached.get("cache_schema_version") == "arr.maas.geometry_vlm_cache.v2"
            and isinstance(cached.get("concept_scores"), dict)
        ):
            result = {**cached, "cache_hit": True}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    if result is None:
        result = score_candidate_with_openai_vlm(
            feature=feature,
            image_path=preview_path,
            reference_matches=reference_matches or [],
            model=model,
            max_retries=max_retries,
            program_hash=program.program_hash(),
            geometry_hash=str(compilation.geometry_hash or ""),
        )
        result = {
            **result,
            "cache_schema_version": "arr.maas.geometry_vlm_cache.v2",
            "cache_hit": False,
        }
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix(f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
            temporary.write_text(
                json.dumps(result, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            temporary.replace(cache_path)
        except OSError:
            # A cache failure must not turn a valid live critic result into a
            # fabricated geometry failure.
            pass
    image_inputs = result.get("vlm_image_inputs")
    if isinstance(image_inputs, dict):
        from backend.app.modules.design.generation.maas.preference.vlm_scorer import _bind_submitted_reference_identity

        response_id = str(result.get("response_id") or "")
        image_inputs["references"] = _bind_submitted_reference_identity(
            [
                item for item in image_inputs.get("references") or ()
                if isinstance(item, dict)
            ],
            response_id=response_id,
            program_hash=program.program_hash(),
            geometry_hash=str(compilation.geometry_hash or ""),
        )
        candidate_input = image_inputs.get("candidate")
        if isinstance(candidate_input, dict):
            candidate_input.update({
                "response_id": response_id,
                "program_hash": program.program_hash(),
                "geometry_hash": str(compilation.geometry_hash or ""),
            })
    result["maas_causal_context"] = {
        "schema_version": "arr.maas.vlm_geometry_causal_context.v1",
        "reference_matches": [
            {
                key: item.get(key)
                for key in (
                    "source", "source_id", "title", "selection_role", "matched_tags", "score",
                    "program_id", "program_match_tier", "program_matched_terms",
                    "reference_collection", "program_relevance_score",
                )
                if item.get(key) not in (None, "", [])
            }
            for item in (reference_matches or [])
            if isinstance(item, dict)
        ],
        "program_context": context,
        "reference_assessments": list(result.get("reference_assessments") or ()),
        "outcome_memory": outcome_memory_context or {},
        "reference_massing_gate": {
            key: value
            for key, value in reference_audit.items()
            if key not in {"accepted"}
        },
    }
    result["reference_massing_gate"] = {
        key: value
        for key, value in reference_audit.items()
        if key not in {"accepted"}
    }
    reviewed_passport = build_mass_execution_passport(
        compilation,
        preview_path=preview_path,
        vlm_result=result,
    )
    result["mass_execution_agent_context"] = build_mass_execution_agent_context(
        reviewed_passport,
        geometry_graph_snapshot=graph_snapshot,
    )
    # Update the same per-MASS sidecar with the exact cached/live critic result.
    # No concept activation is drawn before this material evidence exists.
    from backend.app.modules.design.generation.maas.geometry_language.execution_passport import write_mass_execution_passport

    if write_passport_sidecar:
        write_mass_execution_passport(
            compilation,
            preview_path,
            vlm_result=result,
            geometry_graph_snapshot=graph_snapshot,
        )
    return result


def _geometry_vlm_cache_path(
    *,
    program: GeometryProgram,
    compilation: CompilationResult,
    preview_path: Path,
    reference_matches: list[dict[str, Any]],
    program_context: dict[str, Any],
    outcome_memory_context: dict[str, Any],
    model: str | None,
) -> Path:
    """Address immutable critic evidence without storing credentials.

    Causal outcome memory is part of the critic input. Reusing an older answer
    after new typed repair/outcome evidence arrives silently disables the graph
    feedback loop, so a bounded canonical fingerprint participates in the key.
    Credentials and parcel coordinates are never included.
    """
    try:
        preview_hash = hashlib.sha256(preview_path.read_bytes()).hexdigest()
    except OSError:
        preview_hash = "missing-preview"
    payload = {
        "schema": "arr.maas.geometry_vlm_cache_key.v2",
        "prompt_contract": VLM_PROMPT_CONTRACT_VERSION,
        "model": model or os.getenv("MAAS_PREFERENCE_VLM_MODEL") or DEFAULT_VLM_MODEL,
        "program_hash": program.program_hash(),
        "geometry_hash": compilation.geometry_hash,
        "preview_hash": preview_hash,
        "program_context": program_context,
        "outcome_memory_fingerprint": hashlib.sha256(json.dumps(
            outcome_memory_context,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest(),
        "references": [
            {
                "source": item.get("source"),
                "source_id": item.get("source_id"),
                "local_path": item.get("local_path"),
                "reference_collection": item.get("reference_collection"),
                "program_match_tier": item.get("program_match_tier"),
            }
            for item in reference_matches
            if isinstance(item, dict)
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    key = hashlib.sha256(encoded).hexdigest()
    configured_root = os.getenv("MAAS_GEOMETRY_VLM_CACHE_DIR", "").strip()
    root = (
        Path(configured_root).resolve()
        if configured_root
        else workspace_root() / "docs" / "ai-session-memory" / "reference-corpus" / "geometry-vlm-cache"
    )
    return root / f"{key}.json"


@lru_cache(maxsize=4)
def _cached_reference_items(root: str) -> tuple[ReferenceItem, ...]:
    return tuple(load_reference_tree(Path(root)))


def retrieve_geometry_reference_matches(
    program: GeometryProgram,
    *,
    building_type: str,
    explicit_matches: list[dict[str, Any]] | None = None,
    reference_root: str | Path | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Retrieve image-backed precedents from intent, never parcel coordinates."""
    bounded_limit = max(1, int(limit))
    root = Path(reference_root) if reference_root is not None else default_reference_root() / "archdaily"
    context = program_reference_contract(building_type)
    feature = {
        "type": "Feature",
        "geometry": None,
        "properties": {
            "operator_family": " ".join(str(item) for item in program.metadata.get("operator_path") or ()),
            "source_signature": {
                "family": str(program.metadata.get("family") or building_type),
                "formal_principle": " ".join(str(item) for item in program.metadata.get("intent_tags") or ()),
                "primary_language": " ".join(sorted({node.operator for node in program.nodes})),
                "secondary_language": str(program.metadata.get("base_seed") or ""),
            },
        },
    }
    retrieved = match_reference_context(
        feature,
        _cached_reference_items(str(root.resolve())),
        limit=bounded_limit,
        program_contract=context,
    )
    # The minimum primary evidence should come from the curated program
    # collection when it exists. Semantic matches remain useful as later
    # counterfactuals, but a generic residential "court" must not displace a
    # sports hall in the first gym references.
    retrieved = sorted(
        retrieved,
        key=lambda item: (
            str(item.get("program_match_tier") or "") == "preferred_collection",
            float(item.get("program_relevance_score") or 0.0),
            float(item.get("score") or 0.0),
        ),
        reverse=True,
    )
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    ordered = (*retrieved[:bounded_limit], *(explicit_matches or []), *retrieved[bounded_limit:])
    for item in ordered:
        if not isinstance(item, dict) or not (item.get("local_path") or item.get("image_url")):
            continue
        key = (
            str(item.get("source") or "explicit"),
            str(item.get("source_id") or item.get("local_path") or item.get("image_url") or item.get("title") or ""),
        )
        if not key[1] or key in seen:
            continue
        seen.add(key)
        merged.append(dict(item))
    result = merged[:bounded_limit]
    minimum = int(context.get("minimum_program_specific_images") or 0)
    program_specific_count = sum(
        str(item.get("program_match_tier") or "") in {"preferred_collection", "semantic_program_match"}
        for item in result
    )
    for item in result:
        item["reference_contract"] = {
            "program_id": str(context.get("program_id") or "generic"),
            "minimum_program_specific_images": minimum,
            "program_specific_image_count": program_specific_count,
            "hard_pass": program_specific_count >= minimum,
        }
    return result


def audit_reference_matches_for_massing(
    reference_matches: list[dict[str, Any]],
    *,
    building_type: str,
    model: str | None = None,
    limit: int = 5,
    max_retries: int | None = None,
) -> dict[str, Any]:
    """Remove program-correct but visually unusable precedent frames."""

    context = program_reference_contract(building_type)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for index, raw in enumerate(reference_matches):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        path = resolve_reference_image_path(str(item.get("local_path") or ""))
        if path is None:
            rejected.append({
                "source_id": str(item.get("source_id") or ""),
                "status": "missing_local_image",
                "hard_pass": False,
            })
            continue
        try:
            audit = audit_reference_image_for_massing(
                path,
                model=model,
                max_retries=max_retries,
            )
        except Exception as exc:
            rejected.append({
                "source_id": str(item.get("source_id") or ""),
                "status": "audit_failed",
                "hard_pass": False,
                "error": f"{type(exc).__name__}:{str(exc)[:180]}",
            })
            continue
        compact_audit = {
            key: audit.get(key)
            for key in (
                "schema_version", "prompt_contract_version", "provider", "model",
                "response_id", "view_type", "whole_building_visible",
                "massing_legibility", "operation_clarity", "building_scale_typology",
                "primary_building_typology", "typology_confidence", "hard_pass",
                "failure_reasons", "visible_form_traits", "cache_hit",
                "api_usage",
            )
        }
        compact_audit["input_rank"] = index
        scale_typology = str(compact_audit.get("building_scale_typology") or "unknown")
        excluded_scales = {
            str(value) for value in context.get("excluded_scale_typologies") or ()
        }
        program_scale_compatible = scale_typology not in excluded_scales
        compact_audit["program_scale_compatible"] = program_scale_compatible
        compact_audit["excluded_scale_typologies"] = sorted(excluded_scales)
        item["massing_image_audit"] = compact_audit
        if audit.get("hard_pass") and program_scale_compatible:
            accepted.append(item)
        else:
            rejected.append({
                "source_id": str(item.get("source_id") or ""),
                "status": (
                    "rejected_program_scale_mismatch"
                    if audit.get("hard_pass") and not program_scale_compatible
                    else "rejected_non_massing_image"
                ),
                **compact_audit,
            })
    accepted.sort(key=lambda item: (
        str(item.get("program_match_tier") or "") == "preferred_collection",
        float((item.get("massing_image_audit") or {}).get("operation_clarity") or 0.0),
        float((item.get("massing_image_audit") or {}).get("massing_legibility") or 0.0),
        float(item.get("program_relevance_score") or 0.0),
        -int((item.get("massing_image_audit") or {}).get("input_rank") or 0),
    ), reverse=True)
    accepted = accepted[: max(1, int(limit))]
    minimum = int(context.get("minimum_program_specific_images") or 0)
    suitable_program_count = sum(
        str(item.get("program_match_tier") or "") in {"preferred_collection", "semantic_program_match"}
        for item in accepted
    )
    hard_pass = suitable_program_count >= minimum
    for item in accepted:
        previous = item.get("reference_contract") if isinstance(item.get("reference_contract"), dict) else {}
        item["reference_contract"] = {
            **previous,
            "program_id": str(context.get("program_id") or "generic"),
            "minimum_program_specific_images": minimum,
            "massing_suitable_program_image_count": suitable_program_count,
            "massing_image_hard_pass": hard_pass,
            "hard_pass": bool(previous.get("hard_pass", True) and hard_pass),
        }
    return {
        "schema_version": "arr.maas.reference_massing_gate.v1",
        "program_id": str(context.get("program_id") or "generic"),
        "minimum_program_specific_images": minimum,
        "input_image_count": len(reference_matches),
        "audited_image_count": len(accepted) + len(rejected),
        "massing_suitable_image_count": len(accepted),
        "massing_suitable_program_image_count": suitable_program_count,
        "hard_pass": hard_pass,
        "accepted": accepted,
        "rejected": rejected,
    }


def openai_vlm_geometry_critic(
    *,
    reference_matches: list[dict[str, Any]] | None = None,
    reference_provider: Callable[[GeometryProgram], list[dict[str, Any]]] | None = None,
    memory_provider: Callable[[GeometryProgram], dict[str, Any]] | None = None,
    building_type: str = "",
    program_context: dict[str, Any] | None = None,
    model: str | None = None,
) -> Callable[[GeometryProgram, CompilationResult, Path], dict[str, Any]]:
    static_matches = list(reference_matches or [])

    def critic(program: GeometryProgram, compilation: CompilationResult, preview_path: Path) -> dict[str, Any]:
        dynamic_matches = reference_provider(program) if reference_provider is not None else []
        memory = memory_provider(program) if memory_provider is not None else {}
        section_families = ("ridge", "shed", "folded", "sawtooth", "stepped", "barrel")
        try:
            variation_index = int(program.metadata.get("variation_index") or 0)
        except (TypeError, ValueError):
            variation_index = int(program.program_hash()[:8], 16)
        candidate_context = {
            **dict(program_context or {}),
            "portfolio_diversity_contract": {
                "schema_version": "arr.maas.portfolio_diversity_slot.v1",
                "assignment_mode": "stable_variation_index_balanced_slot",
                "preferred_section_family": section_families[variation_index % len(section_families)],
                "allowed_section_families": list(section_families),
                "maximum_single_roof_family_share": 0.30,
                "preference_only_when_program_and_reference_compatible": True,
                "completed_form_template": False,
            },
        }
        return score_geometry_program_with_openai_vlm(
            program,
            compilation,
            preview_path,
            reference_matches=dynamic_matches or static_matches,
            outcome_memory_context=memory,
            building_type=building_type,
            program_context=candidate_context,
            model=model,
        )

    return critic


__all__ = [
    "build_geometry_graph_notes",
    "build_geometry_graph_snapshot",
    "audit_reference_matches_for_massing",
    "openai_vlm_geometry_critic",
    "retrieve_geometry_reference_matches",
    "score_geometry_program_with_openai_vlm",
]
