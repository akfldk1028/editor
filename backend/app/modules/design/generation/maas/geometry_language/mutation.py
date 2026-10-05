"""Bounded typed mutation of recursive geometry programs.

VLM/LLM agents never write kernel objects.  They emit these small edits; this
module validates references, operator compatibility and parameter bounds before
the compiler is allowed to see the revised program.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from typing import TYPE_CHECKING, Any, Iterable

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryIssue, GeometryNode, GeometryProgram, OPERATORS_BY_KIND, MACRO_VERTICAL_ANCHORS, MACRO_VERTICAL_ANCHOR_OPERATORS
from backend.app.modules.design.generation.maas.geometry_language.section_profiles import SECTION_PROFILES, section_profile_controls

if TYPE_CHECKING:
    from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult


@dataclass(frozen=True)
class GeometryEdit:
    operation: str
    target_node_id: str = ""
    node_id: str = ""
    node_kind: str = ""
    operator: str = ""
    input_ids: tuple[str, ...] = ()
    input_index: int = 0
    input_node_id: str = ""
    parameter_name: str = ""
    numeric_value: float = 0.0
    string_value: str = ""
    boolean_value: bool | None = None
    vector_value: tuple[float, ...] = ()
    semantic_role: str = ""
    rationale: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GeometryEdit":
        return cls(
            operation=str(value.get("operation") or ""),
            target_node_id=str(value.get("target_node_id") or ""),
            node_id=str(value.get("node_id") or ""),
            node_kind=str(value.get("node_kind") or ""),
            operator=str(value.get("operator") or ""),
            input_ids=tuple(str(item) for item in value.get("input_ids") or ()),
            input_index=int(value.get("input_index") or 0),
            input_node_id=str(value.get("input_node_id") or ""),
            parameter_name=str(value.get("parameter_name") or ""),
            numeric_value=float(value.get("numeric_value") or 0.0),
            string_value=str(value.get("string_value") or ""),
            boolean_value=(
                bool(value.get("boolean_value"))
                if "boolean_value" in value
                else None
            ),
            vector_value=tuple(float(item) for item in value.get("vector_value") or ()),
            semantic_role=str(value.get("semantic_role") or ""),
            rationale=str(value.get("rationale") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "target_node_id": self.target_node_id,
            "node_id": self.node_id,
            "node_kind": self.node_kind,
            "operator": self.operator,
            "input_ids": list(self.input_ids),
            "input_index": self.input_index,
            "input_node_id": self.input_node_id,
            "parameter_name": self.parameter_name,
            "numeric_value": self.numeric_value,
            "string_value": self.string_value,
            "boolean_value": bool(self.boolean_value),
            "vector_value": list(self.vector_value),
            "semantic_role": self.semantic_role,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class MutationResult:
    status: str
    program: GeometryProgram | None
    applied_edits: tuple[GeometryEdit, ...] = ()
    issues: tuple[GeometryIssue, ...] = ()


@dataclass(frozen=True)
class CompilerSafeMutationResult:
    """A typed mutation proven against the same solid compiler used downstream.

    The critic is allowed to propose several bounded edits at once.  A single
    kernel-invalid edit must not erase independent, executable edits from the
    same response, so the recovery lane retries atomic per-node edit groups and
    retains only groups that produce a real compiled geometry delta.
    """

    mutation: MutationResult
    compilation: "CompilationResult | None" = None
    recovery_mode: str = "none"
    rejected_groups: tuple[dict[str, Any], ...] = ()
    target_resolution_evidence: tuple[dict[str, Any], ...] = ()


ALLOWED_EDIT_OPERATIONS = frozenset({
    "set_parameter",
    "replace_operator",
    "add_node",
    "remove_node",
    "rewire_input",
    "set_root",
})

NUMERIC_BOUNDS: dict[str, tuple[float, float]] = {
    "angle": (-180.0, 180.0),
    "angle_degrees": (-180.0, 180.0),
    "amount": (-0.85, 0.85),
    "ratio": (0.03, 0.75),
    "margin": (0.03, 0.45),
    "margin_ratio": (0.03, 0.45),
    "width_ratio": (0.08, 0.75),
    "setback_ratio": (0.0, 0.32),
    "gap_ratio": (0.04, 0.5),
    "row_spacing_ratio": (1.05, 1.8),
    "column_offset_ratio": (0.12, 0.38),
    "height_ratio": (0.05, 1.4),
    "offset": (-1000.0, 1000.0),
    "offset_ratio": (0.02, 0.45),
    "distance": (0.001, 1000.0),
    "count": (1.0, 24.0),
    "levels": (2.0, 10.0),
    "subdivisions": (2.0, 7.0),
    "segments": (8.0, 96.0),
    "lower_floor_fraction": (0.0, 0.8),
    "width": (0.01, 1000.0),
    "depth": (0.01, 1000.0),
    "height": (0.01, 1000.0),
    "profile_width": (0.01, 1000.0),
    "profile_height": (0.01, 1000.0),
}

VECTOR_LENGTHS: dict[str, tuple[int, ...]] = {
    "vector": (3,),
    "pivot": (3,),
    "normal": (3,),
    "angles": (3,),
    "scale": (2, 3),
    "start_scale": (2,),
    "end_scale": (2,),
    "shift_per_level": (3,),
}

STRING_PARAMETER_VALUES: dict[tuple[str, str], frozenset[str]] = {
    ("book_base_volume", "label"): frozenset({
        "1/1", "3/8", "1/2", "1/4", "1/8", "1/16",
    }),
    ("book_base_volume", "orientation"): frozenset({
        "long_axis", "short_axis", "vertical",
    }),
    ("lift", "access_side"): frozenset({
        "closed", "east", "west", "north", "south",
    }),
    ("split_wing", "access_side"): frozenset({
        "closed", "east", "west", "north", "south",
    }),
    ("twist", "axis"): frozenset({"x", "y", "z"}),
    ("setback", "direction"): frozenset({"x", "y"}),
    ("stepped_mass", "direction"): frozenset({"x", "y"}),
    ("book_stack", "mode"): frozenset({"none", "rotate", "shift"}),
    ("book_array", "mode"): frozenset({"array", "pack", "offset"}),
    ("book_array", "axis"): frozenset({"x", "y"}),
    ("book_stack", "axis"): frozenset({"x", "y"}),
    ("terrace", "direction"): frozenset({"x", "y"}),
    ("cut_corner", "corner"): frozenset({"ne", "nw", "se", "sw"}),
    ("notch", "corner"): frozenset({"ne", "nw", "se", "sw"}),
    ("notch", "side"): frozenset({"", "east", "west", "north", "south"}),
    ("courtyard", "open_side"): frozenset({"closed", "east", "west", "north", "south"}),
    ("carve_void", "open_side"): frozenset({"closed", "east", "west", "north", "south"}),
    ("slice", "keep_side"): frozenset({"positive", "negative", "above", "below", "front", "back"}),
    ("clip", "keep_side"): frozenset({"positive", "negative", "above", "below", "front", "back"}),
    ("clip_fraction", "anchor"): frozenset({"start", "center", "end", "low", "middle", "high", "negative", "positive"}),
    ("profiled_hall", "span_axis"): frozenset({"x", "y"}),
    ("profiled_hall", "section_family"): frozenset(SECTION_PROFILES),
    ("leaning_tower", "direction"): frozenset({"x", "y"}),
    ("merge_related", "axis"): frozenset({"x", "y"}),
    ("offset_related", "axis"): frozenset({"x", "y"}),
    ("nested_related", "axis"): frozenset({"x", "y"}),
    ("interlock_related", "axis"): frozenset({"x", "y"}),
    ("overlap_related", "axis"): frozenset({"x", "y"}),
    ("related_array", "axis"): frozenset({"x", "y"}),
    ("related_array", "mode"): frozenset({"array", "pack"}),
    ("shift_related", "axis"): frozenset({"x", "y"}),
    ("split_wing", "axis"): frozenset({"x", "y"}),
    ("split_wing", "layout"): frozenset({"split", "parallel"}),
    ("book_split", "axis"): frozenset({"x", "y"}),
    ("book_carve", "axis"): frozenset({"x", "y", "z"}),
    ("book_carve", "face_side"): frozenset({"east", "west", "north", "south"}),
    ("book_fracture", "axis"): frozenset({"x", "y", "z"}),
    ("book_grade", "axis"): frozenset({"x", "y", "z"}),
    ("book_grade", "face_side"): frozenset({"east", "west", "north", "south"}),
    ("book_notch", "axis"): frozenset({"x", "y", "z"}),
    ("book_notch", "corner"): frozenset({"ne", "nw", "se", "sw"}),
    ("embed_void", "axis"): frozenset({"x", "y", "z"}),
    ("embed_void", "position"): frozenset({"center", "east", "west", "north", "south"}),
    ("book_extract", "axis"): frozenset({"x", "y", "z"}),
    ("book_extract", "face_side"): frozenset({"east", "west", "north", "south"}),
}

BOOLEAN_PARAMETERS = frozenset({"center", "bridge", "ground_spine"})

# Executable compiler parameters exposed to LLM/VLM graph editors.  This is
# deliberately exhaustive: an unknown parameter must not be accepted merely
# because it changes the JSON hash while the geometry compiler silently falls
# back to a default.  Primitive authoring is included as well, even though the
# critic normally edits operators above an existing base seed.
for _operator in MACRO_VERTICAL_ANCHOR_OPERATORS:
    STRING_PARAMETER_VALUES[(_operator, "vertical_anchor")] = frozenset(MACRO_VERTICAL_ANCHORS)


OPERATOR_PARAMETER_CONTRACTS: dict[str, frozenset[str]] = {
    "box": frozenset({"width", "depth", "height", "center"}),
    "matrix4": frozenset({"matrix4"}),
    "cylinder": frozenset({"height", "radius", "radius_low", "radius_high", "segments", "center"}),
    "extruded_polygon": frozenset({"points", "holes", "height", "divisions"}),
    "wedge": frozenset({"width", "depth", "start_height", "end_height"}),
    "sweep": frozenset({"path", "profile_width", "profile_height", "width", "height"}),
    "loft": frozenset({"profiles"}),
    "translate": frozenset({"vector", "x", "y", "z"}),
    "rotate": frozenset({"axis", "angle", "angle_degrees", "angles", "pivot"}),
    "scale": frozenset({"vector", "scale", "pivot"}),
    "mirror": frozenset({"normal", "pivot"}),
    "shear": frozenset({"axis", "direction", "amount", "pivot"}),
    "bend": frozenset({"axis", "angle", "angle_degrees", "subdivisions"}),
    "taper": frozenset({
        "axis", "start_scale", "end_scale", "scale_top", "pivot",
        "lower_floor_fraction", "subdivisions",
    }),
    "twist": frozenset({"axis", "angle", "angle_degrees", "pivot", "subdivisions"}),
    "pinch": frozenset({"axis", "waist_scale", "waist_ratio", "profile_power", "subdivisions"}),
    "inflate": frozenset({"axis", "middle_scale", "factor", "profile_power", "subdivisions"}),
    "book_base_volume": frozenset({"label", "orientation"}),
    "circularize": frozenset({"segments"}),
    "ellipsoidize": frozenset({"segments"}),
    "tetrahedralize": frozenset(),
    "profile_sweep_3d": frozenset({"path"}),
    "slice": frozenset({"normal", "offset", "offset_ratio", "keep_side"}),
    "clip": frozenset({"normal", "offset", "offset_ratio", "keep_side"}),
    "clip_fraction": frozenset({"axis", "fraction", "anchor"}),
    "cut_corner": frozenset({"corner", "ratio", "distance"}),
    "duplicate": frozenset({"count", "vector", "spacing"}),
    "linear_array": frozenset({"count", "vector", "spacing"}),
    "matrix_array": frozenset({"matrices", "require_connected"}),
    "radial_array": frozenset({"count", "total_angle_degrees", "angle_degrees", "pivot"}),
    "mirror_array": frozenset({"normal", "pivot"}),
    "stack": frozenset({"count", "spacing", "shift_per_level"}),
    "union": frozenset(),
    "difference": frozenset(),
    "intersection": frozenset(),
    "attach": frozenset({
        "host_face", "anchor", "anchor_u", "anchor_v", "guest_extent",
        "depth_ratio", "width_ratio", "height_ratio", "engagement", "embed_ratio",
        "rotation_degrees",
    }),
    "bridge": frozenset({"z", "height_ratio", "height", "width"}),
    "courtyard": frozenset({"margin_ratio", "open_side"}),
    "carve_void": frozenset({"margin_ratio", "open_side"}),
    "notch": frozenset({"corner", "side", "ratio", "width_ratio", "height_ratio"}),
    "setback": frozenset({"levels", "setback_ratio", "direction", "shift_per_level"}),
    "terrace": frozenset({"levels", "setback_ratio", "direction", "direction_sign", "shift_per_level"}),
    "stepped_mass": frozenset({
        "levels", "setback_ratio", "direction", "shift_per_level",
        "podium_scale", "podium_height_ratio",
    }),
    "profiled_hall": frozenset({"section_family", "section_controls", "span_axis"}),
    "bound_surfaces": frozenset({"top_surface", "bottom_surface"}),
    "cantilever": frozenset({"start_ratio", "vector"}),
    "cross_mass": frozenset({"angle_degrees"}),
    "grid_mass": frozenset({"row_spacing_ratio", "column_offset_ratio"}),
    "bent_bar": frozenset({"axis", "angle", "angle_degrees", "subdivisions"}),
    "split_wing": frozenset({
        "axis", "gap_ratio", "bridge", "height_ratio", "height",
        "ground_spine", "ground_spine_width_ratio", "ground_spine_height_ratio",
        "access_side", "layout", "connector_width_ratio",
    }),
    "book_split": frozenset({
        "axis", "gap_ratio", "terminal_ratio", "angle_degrees", "outward_sign",
        "branch_sign", "split_generation", "access_side",
    }),
    "attach_volume": frozenset(),
    "tapered_tower": frozenset({"axis", "start_scale", "end_scale", "scale_top", "pivot", "subdivisions"}),
    "leaning_tower": frozenset({"direction", "amount"}),
    "lift": frozenset({"rise_ratio", "support_ratio", "access_side"}),
    "book_lift": frozenset({"axis", "guest_scale", "distance_ratio", "outward_sign"}),
    "book_lodge": frozenset({"axis", "guest_scale", "distance_ratio", "outward_sign"}),
    "book_rotate": frozenset({"axis", "angle_degrees", "related_ratio", "outward_sign"}),
    "book_carve": frozenset({"axis", "face_side", "width_ratio", "depth_ratio", "outward_sign"}),
    "book_fracture": frozenset({"axis", "gap_ratio", "angle_degrees", "retained_back_ratio", "outward_sign"}),
    "book_grade": frozenset({"axis", "face_side", "levels", "width_ratio", "depth_ratio", "outward_sign"}),
    "book_notch": frozenset({"axis", "corner", "ratio", "outward_sign"}),
    "book_extract": frozenset({"axis", "face_side", "guest_scale", "distance_ratio", "outward_sign"}),
    "puncture": frozenset({"axis", "count", "n", "ratio", "spacing_ratio"}),
    "book_branch": frozenset({"angle_degrees", "trunk_ratio", "arm_ratio", "vertical_anchor"}),
    "book_stack": frozenset({"levels", "mode", "axis", "step_degrees", "shift_ratio"}),
    "book_array": frozenset({"mode", "count", "axis", "pitch_ratio"}),
    "boundary_expand": frozenset({"axis", "amount", "shoulder_fraction"}),
    "shift_related": frozenset({"axis", "distance_ratio", "split_ratio", "outward_sign"}),
    "offset_related": frozenset({"axis", "distance_ratio", "unit_scale", "outward_sign"}),
    "nested_related": frozenset({"axis", "distance_ratio", "unit_scale"}),
    "interlock_related": frozenset({
        "axis", "angle_degrees", "bar_ratio", "distance_ratio", "outward_sign",
    }),
    "intersect_related": frozenset({"axis", "angle_degrees", "bar_ratio", "unit_scale"}),
    "merge_related": frozenset({"axis", "gap_ratio", "unit_scale"}),
    "overlap_related": frozenset({
        "axis", "slab_ratio", "shift_ratio", "vertical_overlap", "outward_sign",
    }),
    "embed_void": frozenset({"axis", "outward_sign", "guest_scale", "position", "embedded_ratio"}),
    "related_array": frozenset({"mode", "axis", "count", "spacing_ratio", "unit_scale", "stagger_ratio", "vertical_anchor"}),
    "join_related": frozenset({"bridge_ratio"}),
}

OPERATOR_PARAMETER_ALIASES: dict[str, dict[str, str]] = {
    "courtyard": {"void_ratio": "margin_ratio", "court_ratio": "margin_ratio"},
    "carve_void": {"void_ratio": "margin_ratio", "court_ratio": "margin_ratio"},
}

SECTION_FAMILY_ALIASES = {
    "gable": "ridge",
    "gable_ridge": "ridge",
    "mono_shed": "shed",
    "monitor": "sawtooth",
    "daylight_monitor": "sawtooth",
    "arched": "barrel",
    "barrel_vault": "barrel",
}


def apply_geometry_edits(program: GeometryProgram, edits: Iterable[GeometryEdit | dict[str, Any]]) -> MutationResult:
    normalized = tuple(edit if isinstance(edit, GeometryEdit) else GeometryEdit.from_dict(edit) for edit in edits)
    if not normalized:
        return MutationResult("no_edits", None)
    nodes = list(program.nodes)
    root_id = program.root_id
    protected_section_node_ids = {
        node.id for node in nodes
        if node.operator == "profiled_hall"
        or node.semantic_role == "program_section_invariant"
    }
    protected_relation_node_ids = {
        node.id for node in nodes
        if node.operator in {"courtyard", "carve_void", "notch", "lift", "cantilever", "split_wing"}
        and any(
            token in str(node.semantic_role or "").strip().lower()
            for token in ("threshold", "entry", "public", "court", "atrium", "ground")
        )
    }
    protected_node_ids = protected_section_node_ids | protected_relation_node_ids | {
        node.id for node in nodes
        if bool((node.provenance or {}).get("program_invariant"))
    }
    applied: list[GeometryEdit] = []
    issues: list[GeometryIssue] = []
    parameterized_targets = {
        edit.target_node_id
        for edit in normalized
        if edit.operation == "set_parameter" and edit.target_node_id
    }

    for edit in normalized:
        if edit.operation not in ALLOWED_EDIT_OPERATIONS:
            issues.append(GeometryIssue("unsupported_edit", edit.operation, edit.target_node_id))
            continue
        node_map = {node.id: node for node in nodes}
        target = node_map.get(edit.target_node_id)
        if target is not None and target.id in protected_node_ids:
            if edit.operation in {"replace_operator", "remove_node", "rewire_input"}:
                issues.append(GeometryIssue(
                    "protected_program_invariant",
                    "program section/access invariant cannot be replaced, removed, or rewired",
                    target.id,
                ))
                continue
            if (
                target.id in protected_section_node_ids
                and edit.operation == "set_parameter"
                and edit.parameter_name not in {"section_family", "span_axis"}
            ):
                issues.append(GeometryIssue(
                    "protected_program_invariant_parameter",
                    "only section_family or span_axis may be edited on a program section invariant",
                    target.id,
                ))
                continue
        if edit.operation == "set_parameter":
            if target is None:
                issues.append(GeometryIssue("edit_target_missing", "parameter target does not exist", edit.target_node_id))
                continue
            parameter_name = OPERATOR_PARAMETER_ALIASES.get(target.operator, {}).get(
                edit.parameter_name,
                edit.parameter_name,
            )
            allowed_parameters = OPERATOR_PARAMETER_CONTRACTS.get(target.operator)
            if allowed_parameters is not None and parameter_name not in allowed_parameters:
                issues.append(GeometryIssue(
                    "unsupported_operator_parameter",
                    f"{target.operator} supports {sorted(allowed_parameters)}",
                    edit.target_node_id,
                ))
                continue
            normalized_edit = replace(edit, parameter_name=parameter_name)
            value, issue = _parameter_value(normalized_edit)
            if issue is not None:
                issues.append(issue)
                continue
            if target.operator == "profiled_hall" and parameter_name == "section_family":
                value = SECTION_FAMILY_ALIASES.get(str(value), str(value))
            value_issue = _operator_parameter_value_issue(
                target.operator,
                parameter_name,
                value,
                target.id,
            )
            if value_issue is not None:
                issues.append(value_issue)
                continue
            params = json.loads(json.dumps(target.parameters))
            if target.operator == "profiled_hall" and parameter_name == "section_family":
                if value not in SECTION_PROFILES:
                    issues.append(GeometryIssue(
                        "unknown_section_family",
                        f"profiled_hall supports {sorted(SECTION_PROFILES)}",
                        edit.target_node_id,
                    ))
                    continue
                # section_controls are the compiler authority. Updating only
                # the family label used to produce no geometry delta whenever
                # controls already existed on the protected hall node.
                params["section_controls"] = section_profile_controls(value)
            params[parameter_name] = value
            nodes[nodes.index(target)] = replace(target, parameters=params)
            applied.append(normalized_edit)
        elif edit.operation == "replace_operator":
            replacement_kind = _replacement_node_kind(target, edit)
            if target is None or replacement_kind is None:
                issues.append(GeometryIssue(
                    "incompatible_operator",
                    f"{target.kind if target else '?'}:{edit.operator}",
                    edit.target_node_id,
                ))
                continue
            if OPERATOR_PARAMETER_CONTRACTS.get(edit.operator) and target.id not in parameterized_targets:
                issues.append(GeometryIssue(
                    "replacement_parameters_missing",
                    "a parameterized replacement must include a typed set_parameter edit",
                    target.id,
                ))
                continue
            # Parameters belong to an operator contract. Carrying cantilever
            # vector/start_ratio into a courtyard replacement creates a JSON
            # change that the compiler ignores, so start the new operator with
            # a clean parameter set and let following typed edits populate it.
            nodes[nodes.index(target)] = replace(
                target,
                kind=replacement_kind,
                operator=edit.operator,
                parameters={},
            )
            applied.append(replace(edit, node_kind=replacement_kind))
        elif edit.operation == "add_node":
            if not edit.node_id or edit.node_id in node_map:
                issues.append(GeometryIssue("duplicate_or_missing_new_node_id", "new node id is invalid", edit.node_id))
                continue
            if edit.node_kind not in OPERATORS_BY_KIND or edit.operator not in OPERATORS_BY_KIND[edit.node_kind]:
                issues.append(GeometryIssue("invalid_new_operator", f"{edit.node_kind}:{edit.operator}", edit.node_id))
                continue
            if any(input_id not in node_map for input_id in edit.input_ids):
                issues.append(GeometryIssue("missing_input", "new node references a missing input", edit.node_id))
                continue
            if OPERATOR_PARAMETER_CONTRACTS.get(edit.operator) and edit.node_id not in parameterized_targets:
                issues.append(GeometryIssue(
                    "new_node_parameters_missing",
                    "a parameterized new node must include a typed set_parameter edit",
                    edit.node_id,
                ))
                continue
            nodes.append(GeometryNode(
                id=edit.node_id,
                kind=edit.node_kind,
                operator=edit.operator,
                inputs=edit.input_ids,
                parameters={},
                semantic_role=edit.semantic_role,
                provenance={"source": "critic_geometry_edit", "rationale": edit.rationale},
            ))
            applied.append(edit)
        elif edit.operation == "rewire_input":
            if target is None or edit.input_node_id not in node_map or not 0 <= edit.input_index < len(target.inputs):
                issues.append(GeometryIssue("invalid_rewire", "rewire target/input/index is invalid", edit.target_node_id))
                continue
            inputs = list(target.inputs)
            inputs[edit.input_index] = edit.input_node_id
            nodes[nodes.index(target)] = replace(target, inputs=tuple(inputs))
            applied.append(edit)
        elif edit.operation == "set_root":
            candidate = edit.target_node_id or edit.node_id
            if candidate not in node_map:
                issues.append(GeometryIssue("missing_root", "requested root does not exist", candidate))
                continue
            if protected_node_ids and not all(
                _node_depends_on(candidate, protected_id, node_map)
                for protected_id in protected_node_ids
            ):
                issues.append(GeometryIssue(
                    "program_invariant_bypassed",
                    "new root must retain every protected program invariant in its ancestry",
                    candidate,
                ))
                continue
            root_id = candidate
            applied.append(edit)
        elif edit.operation == "remove_node":
            if target is None or target.id == root_id or any(target.id in node.inputs for node in nodes):
                issues.append(GeometryIssue("node_not_removable", "node is root or still referenced", edit.target_node_id))
                continue
            nodes.remove(target)
            applied.append(edit)

    if not applied:
        return MutationResult("no_valid_edit_applied", None, issues=tuple(issues))
    revised = program.with_nodes(nodes, root_id=root_id, name_suffix="__critic_revision")
    validation = tuple(issue for issue in revised.validate() if issue.severity == "error")
    if validation:
        return MutationResult("invalid_revision", None, tuple(applied), tuple((*issues, *validation)))
    if revised.program_hash() == program.program_hash():
        return MutationResult("no_program_change", None, tuple(applied), tuple(issues))
    return MutationResult("revised", revised, tuple(applied), tuple(issues))


def apply_geometry_edits_compiler_safe(
    program: GeometryProgram,
    edits: Iterable[GeometryEdit | dict[str, Any]],
) -> CompilerSafeMutationResult:
    """Apply critic edits transactionally and prove every retained group.

    The all-at-once program remains the preferred interpretation.  Recovery is
    attempted only when that exact program does not compile.  Groups are based
    on stable AST node IDs, not parcel coordinates or pre-authored forms.
    """

    from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program

    normalized = tuple(
        edit if isinstance(edit, GeometryEdit) else GeometryEdit.from_dict(edit)
        for edit in edits
    )
    normalized, target_resolution_evidence, target_resolution_issues = (
        _resolve_semantic_projection_root_references(program, normalized)
    )
    if target_resolution_issues:
        return CompilerSafeMutationResult(
            mutation=MutationResult(
                "target_resolution_failed",
                None,
                issues=target_resolution_issues,
            ),
            recovery_mode="target_resolution_rejected",
            target_resolution_evidence=target_resolution_evidence,
        )
    direct = apply_geometry_edits(program, normalized)
    if direct.program is not None:
        direct_compilation = compile_geometry_program(direct.program)
        if direct_compilation.status == "compiled":
            return CompilerSafeMutationResult(
                mutation=direct,
                compilation=direct_compilation,
                recovery_mode="all_edits_compiled",
                target_resolution_evidence=target_resolution_evidence,
            )

    parent_compilation = compile_geometry_program(program)
    if parent_compilation.status != "compiled":
        return CompilerSafeMutationResult(
            mutation=MutationResult(
                "parent_compile_failed",
                None,
                issues=tuple((*direct.issues, *parent_compilation.issues)),
            ),
            compilation=parent_compilation,
            recovery_mode="unavailable",
            target_resolution_evidence=target_resolution_evidence,
        )

    groups = _atomic_edit_groups(normalized)
    current = program
    current_compilation = parent_compilation
    applied: list[GeometryEdit] = []
    issues: list[GeometryIssue] = list(direct.issues)
    rejected: list[dict[str, Any]] = []
    for group_key, group in groups:
        attempted = apply_geometry_edits(current, group)
        issues.extend(attempted.issues)
        if attempted.program is None:
            rejected.append({
                "group": group_key,
                "status": attempted.status,
                "issues": [issue.to_dict() for issue in attempted.issues],
            })
            continue
        compilation = compile_geometry_program(attempted.program)
        geometry_changed = (
            compilation.status == "compiled"
            and bool(compilation.geometry_hash)
            and compilation.geometry_hash != current_compilation.geometry_hash
        )
        if not geometry_changed:
            rejected.append({
                "group": group_key,
                "status": (
                    "compiled_without_geometry_delta"
                    if compilation.status == "compiled"
                    else "compile_rejected"
                ),
                "issues": [issue.to_dict() for issue in compilation.issues],
            })
            continue
        current = attempted.program
        current_compilation = compilation
        applied.extend(attempted.applied_edits)

    if not applied:
        direct_compilation = (
            compile_geometry_program(direct.program)
            if direct.program is not None
            else None
        )
        compile_issues = tuple(direct_compilation.issues) if direct_compilation is not None else ()
        return CompilerSafeMutationResult(
            mutation=MutationResult(
                "no_compiler_safe_edit",
                None,
                issues=tuple((*issues, *compile_issues)),
            ),
            compilation=direct_compilation,
            recovery_mode="recovery_exhausted",
            rejected_groups=tuple(rejected),
            target_resolution_evidence=target_resolution_evidence,
        )
    return CompilerSafeMutationResult(
        mutation=MutationResult(
            "revised",
            current,
            applied_edits=tuple(applied),
            issues=tuple(_deduplicate_geometry_issues(issues)),
        ),
        compilation=current_compilation,
        recovery_mode="atomic_group_recovery",
        rejected_groups=tuple(rejected),
        target_resolution_evidence=target_resolution_evidence,
    )


def _resolve_semantic_projection_root_references(
    program: GeometryProgram,
    edits: tuple[GeometryEdit, ...],
) -> tuple[
    tuple[GeometryEdit, ...],
    tuple[dict[str, Any], ...],
    tuple[GeometryIssue, ...],
]:
    """Keep a proven add-node/set-root repair above final semantic identity.

    Final semantic projection binds an identity Matrix4 above the authored
    geometry root. Only the r57 repair pattern may use the authored child as a
    stale ancestry alias: one new node consumes that child and the same node is
    selected as root. Ordinary rewires and parameter targets are never mapped.
    """

    node_map = program.node_map
    evidence: list[dict[str, Any]] = []
    issues: list[GeometryIssue] = []

    wrapper = node_map.get(program.root_id)
    wrapper_id = str(wrapper.id if wrapper is not None else "")
    prefix = "semantic_projection:"
    marker = ":source_role_origin"
    marker_index = wrapper_id.find(marker)
    bound_program_id = (
        wrapper_id[len(prefix):marker_index]
        if wrapper_id.startswith(prefix) and marker_index > len(prefix)
        else ""
    )
    provenance = wrapper.provenance if wrapper is not None else {}
    canonical_wrapper = bool(
        wrapper is not None
        and wrapper.kind == "transform"
        and wrapper.operator == "matrix4"
        and len(wrapper.inputs) == 1
        and wrapper.semantic_role == "source_role_scaffold_origin"
        and str((provenance or {}).get("source") or "")
        == "compiled_source_role_scaffold_binding"
        and str((provenance or {}).get("program_id") or "")
        == bound_program_id
        and bool(bound_program_id)
        and (provenance or {}).get("geometry_effect") == "identity"
        and (provenance or {}).get("reachable_final_root_required") is True
    )
    authored_root_id = wrapper.inputs[0] if canonical_wrapper else ""
    root_targets = {
        edit.target_node_id or edit.node_id
        for edit in edits
        if edit.operation == "set_root"
    }

    def semantic_reference(node_id: str) -> bool:
        return node_id.startswith(prefix) and marker in node_id

    resolved_edits: list[GeometryEdit] = []
    for edit in edits:
        resolved = edit
        if (
            edit.operation == "add_node"
            and edit.node_id
            and edit.node_id in root_targets
            and len(edit.input_ids) == 1
            and edit.input_ids[0] == authored_root_id
            and canonical_wrapper
        ):
            resolved = replace(edit, input_ids=(wrapper_id,))
            evidence.append({
                "schema_version": "arr.maas.semantic_projection_target_resolution.v1",
                "status": "resolved",
                "operation": "add_node",
                "reference_field": "input_ids",
                "original_node_id": authored_root_id,
                "resolved_node_id": wrapper_id,
                "candidate_node_ids": [wrapper_id],
                "program_root_id": program.root_id,
                "program_hash": program.program_hash(),
                "program_id": bound_program_id,
                "resolution_basis": (
                    "matched_add_node_set_root_pair_above_canonical_source_role_identity"
                ),
            })
        elif (
            edit.operation == "add_node"
            and edit.node_id in root_targets
            and any(semantic_reference(node_id) for node_id in edit.input_ids)
            and any(node_id != wrapper_id for node_id in edit.input_ids)
        ):
            stale_ids = sorted(
                node_id for node_id in edit.input_ids
                if semantic_reference(node_id) and node_id != wrapper_id
            )
            evidence.append({
                "schema_version": "arr.maas.semantic_projection_target_resolution.v1",
                "status": "rejected_identity_mismatch",
                "operation": "add_node",
                "reference_field": "input_ids",
                "original_node_id": stale_ids[0],
                "resolved_node_id": "",
                "candidate_node_ids": [wrapper_id] if canonical_wrapper else [],
                "program_root_id": program.root_id,
                "program_hash": program.program_hash(),
                "program_id": bound_program_id,
                "resolution_basis": "semantic_projection_program_or_provenance_mismatch",
            })
            issues.append(GeometryIssue(
                "semantic_projection_target_identity_mismatch",
                "stale semantic projection does not match the candidate canonical identity",
                stale_ids[0],
            ))
        resolved_edits.append(resolved)

    return tuple(resolved_edits), tuple(evidence), tuple(issues)


def _atomic_edit_groups(edits: tuple[GeometryEdit, ...]) -> tuple[tuple[str, tuple[GeometryEdit, ...]], ...]:
    """Keep operator replacement/addition and its typed parameters together."""

    added_ids = {edit.node_id for edit in edits if edit.operation == "add_node" and edit.node_id}
    ordered_keys: list[str] = []
    grouped: dict[str, list[GeometryEdit]] = {}
    for index, edit in enumerate(edits):
        if edit.operation == "add_node":
            key = edit.node_id
        elif edit.operation == "rewire_input" and edit.input_node_id in added_ids:
            key = edit.input_node_id
        elif edit.operation == "set_root" and (edit.target_node_id or edit.node_id) in added_ids:
            key = edit.target_node_id or edit.node_id
        else:
            key = edit.target_node_id or edit.node_id or f"edit_{index}"
        if key not in grouped:
            ordered_keys.append(key)
            grouped[key] = []
        grouped[key].append(edit)
    return tuple((key, tuple(grouped[key])) for key in ordered_keys)


def _replacement_node_kind(
    target: GeometryNode | None,
    edit: GeometryEdit,
) -> str | None:
    """Resolve an operator's executable kind instead of trusting stale prose.

    A critic edits a typed solid node, but changing an operation family may
    legitimately cross the implementation taxonomy while retaining the same
    one-solid input (for example ``taper`` modifier -> ``stepped_mass`` macro).
    The operator registry is authoritative. Ambiguous operators keep a valid
    requested/current kind; otherwise only a unique registered kind is safe.
    Final arity and graph validity are still enforced by ``GeometryProgram``.
    """
    if target is None or not edit.operator:
        return None
    candidates = tuple(
        kind for kind, operators in OPERATORS_BY_KIND.items()
        if edit.operator in operators
    )
    if edit.node_kind in candidates:
        return edit.node_kind
    if target.kind in candidates:
        return target.kind
    if len(candidates) == 1:
        return candidates[0]
    return None


def _deduplicate_geometry_issues(issues: Iterable[GeometryIssue]) -> tuple[GeometryIssue, ...]:
    unique: dict[tuple[str, str, str, str], GeometryIssue] = {}
    for issue in issues:
        key = (issue.code, issue.message, issue.node_id, issue.severity)
        unique.setdefault(key, issue)
    return tuple(unique.values())


def _node_depends_on(candidate_id: str, required_id: str, node_map: dict[str, GeometryNode]) -> bool:
    frontier = [candidate_id]
    visited: set[str] = set()
    while frontier:
        node_id = frontier.pop()
        if node_id == required_id:
            return True
        if node_id in visited:
            continue
        visited.add(node_id)
        node = node_map.get(node_id)
        if node is not None:
            frontier.extend(node.inputs)
    return False


def _parameter_value(edit: GeometryEdit) -> tuple[Any, GeometryIssue | None]:
    name = edit.parameter_name.strip()
    if not name:
        return None, GeometryIssue("missing_parameter_name", "parameter edit has no name", edit.target_node_id)
    if name in BOOLEAN_PARAMETERS:
        if edit.boolean_value is not None:
            return bool(edit.boolean_value), None
        legacy = edit.string_value.strip().lower()
        if legacy in {"true", "1", "yes"}:
            return True, None
        if legacy in {"false", "0", "no"}:
            return False, None
        return None, GeometryIssue(
            "boolean_parameter_required",
            f"{name} must be supplied through boolean_value",
            edit.target_node_id,
        )
    # Structured-output schemas include every value carrier on every edit.
    # Models may therefore emit a harmless placeholder vector such as
    # [0, 0, 0] beside a numeric margin_ratio or string open_side.  Dispatch
    # by the executable parameter contract, never by which placeholder field
    # happens to be non-empty; the old value-first decoder turned 0.24 into a
    # list and failed later as float(list) inside the geometry compiler.
    if name in VECTOR_LENGTHS:
        if not edit.vector_value:
            return None, GeometryIssue(
                "vector_parameter_required",
                f"{name} must be supplied through vector_value",
                edit.target_node_id,
            )
        allowed_lengths = VECTOR_LENGTHS[name]
        if len(edit.vector_value) not in allowed_lengths:
            return None, GeometryIssue("invalid_vector_length", f"{name} expects {allowed_lengths}", edit.target_node_id)
        values = [round(float(value), 6) for value in edit.vector_value]
        if name in {"scale", "start_scale", "end_scale"} and min(values) <= 0.02:
            return None, GeometryIssue("degenerate_scale", f"{name} values must exceed 0.02", edit.target_node_id)
        return values, None
    if edit.string_value:
        return edit.string_value.strip().lower()[:80], None
    value = float(edit.numeric_value)
    lower, upper = NUMERIC_BOUNDS.get(name, (-1000.0, 1000.0))
    if not lower <= value <= upper:
        return None, GeometryIssue("parameter_out_of_bounds", f"{name} must be in {lower}..{upper}", edit.target_node_id)
    if name in {"count", "levels", "subdivisions"}:
        return int(round(value)), None
    return round(value, 6), None


def _operator_parameter_value_issue(
    operator: str,
    parameter_name: str,
    value: Any,
    node_id: str,
) -> GeometryIssue | None:
    allowed = STRING_PARAMETER_VALUES.get((operator, parameter_name))
    if allowed is not None and str(value) not in allowed:
        return GeometryIssue(
            "unsupported_parameter_value",
            f"{operator}.{parameter_name} supports {sorted(allowed)}",
            node_id,
        )
    if parameter_name == "axis" and operator != "twist" and str(value) not in {"x", "y", "z"}:
        return GeometryIssue(
            "unsupported_parameter_value",
            f"{operator}.axis supports x, y, or z",
            node_id,
        )
    return None


__all__ = [
    "ALLOWED_EDIT_OPERATIONS",
    "GeometryEdit",
    "CompilerSafeMutationResult",
    "MutationResult",
    "OPERATOR_PARAMETER_CONTRACTS",
    "STRING_PARAMETER_VALUES",
    "apply_geometry_edits",
    "apply_geometry_edits_compiler_safe",
]
