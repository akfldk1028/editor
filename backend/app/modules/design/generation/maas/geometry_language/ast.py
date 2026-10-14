"""Recursive, serializable geometry-program AST for architectural massing.

The legacy MAAS source IR is intentionally optimized for parcel-derived 2.5D
volumes.  This AST is the solid-program layer above a real geometry kernel:
every node consumes and returns a solid, so Boolean, deformation, cutting,
pattern and composition results can be nested without a lossy flat verb list.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from math import isfinite
import re
from typing import Any, Iterable


NODE_KINDS = frozenset({
    "primitive",
    "transform",
    "modifier",
    "boolean",
    "pattern",
    "composition",
    "macro",
})

OPERATORS_BY_KIND: dict[str, frozenset[str]] = {
    "primitive": frozenset({"box", "cylinder", "extruded_polygon", "wedge", "sweep", "loft"}),
    "transform": frozenset({"matrix4", "translate", "rotate", "scale", "mirror", "shear"}),
    "modifier": frozenset({
        "bend", "taper", "twist", "pinch", "inflate",
        "slice", "clip", "clip_fraction", "book_base_volume", "cut_corner",
        "legal_section_clip", "circularize", "ellipsoidize",
        "tetrahedralize", "profile_sweep_3d", "bound_surfaces",
    }),
    "boolean": frozenset({"union", "difference", "intersection"}),
    "pattern": frozenset({
        "duplicate", "linear_array", "radial_array", "mirror_array", "stack",
        "matrix_array",
    }),
    "composition": frozenset({"attach", "bridge"}),
    "macro": frozenset({
        "courtyard",
        "carve_void",
        "notch",
        "setback",
        "terrace",
        "cantilever",
        "bridge",
        "cross_mass",
        "grid_mass",
        "bent_bar",
        "split_wing",
        "book_split",
        "attach_volume",
        "tapered_tower",
        "leaning_tower",
        "lift",
        "book_lift",
        "book_lodge",
        "book_rotate",
        "book_carve",
        "book_fracture",
        "book_grade",
        "book_notch",
        "book_extract",
        "puncture",
        "cut_corner",
        "stepped_mass",
        "profiled_hall",
        "book_branch",
        "book_stack",
        "book_array",
        "boundary_expand",
        "shift_related",
        "offset_related",
        "nested_related",
        "interlock_related",
        "intersect_related",
        "embed_void",
        "related_array",
        "join_related",
        "merge_related",
        "overlap_related",
    }),
}

UNARY_KINDS = frozenset({"transform", "modifier", "pattern"})
IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,79}$")
FLOORWISE_CAPACITY_REPLAY_TRANSPORT_CONTRACT = {
    "schema_version": "arr.maas.geometry_execution_contract.v1",
    "capacity_replay_numeric_transport": {
        "collapse_threshold_m": 1e-5,
        "maximum_3d_displacement_m": 1e-5,
        "retry_on_issue_codes": ["tiny_edge"],
        "floor_center_section_equivalence_required": True,
    },
}
CODEX_BOOK_PATH_EXECUTION_BINDING_SCHEMA = (
    "arr.maas.codex_book_path_execution_binding.v1"
)


def _valid_codex_book_path_execution_binding(value: Any) -> bool:
    return bool(
        isinstance(value, dict)
        and frozenset(value) == frozenset({
            "schema_version",
            "book_composition_path_id",
            "author_response_sha256",
        })
        and value.get("schema_version")
        == CODEX_BOOK_PATH_EXECUTION_BINDING_SCHEMA
        and re.fullmatch(
            r"book:path:[0-9a-f]{64}",
            str(value.get("book_composition_path_id") or ""),
        )
        and re.fullmatch(
            r"[0-9a-f]{64}",
            str(value.get("author_response_sha256") or ""),
        )
    )


@dataclass(frozen=True)
class GeometryIssue:
    code: str
    message: str
    node_id: str = ""
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "node_id": self.node_id,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class GeometryNode:
    id: str
    kind: str
    operator: str
    inputs: tuple[str, ...] = ()
    parameters: dict[str, Any] = field(default_factory=dict)
    semantic_role: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GeometryNode":
        if not isinstance(value, dict):
            raise TypeError("geometry node must be an object")
        raw_inputs = value.get("inputs") or ()
        if not isinstance(raw_inputs, (list, tuple)):
            raise TypeError("geometry node inputs must be an array")
        parameters = value.get("parameters") or {}
        provenance = value.get("provenance") or {}
        if not isinstance(parameters, dict) or not isinstance(provenance, dict):
            raise TypeError("geometry node parameters/provenance must be objects")
        return cls(
            id=str(value.get("id") or ""),
            kind=str(value.get("kind") or value.get("type") or "").lower(),
            operator=str(value.get("operator") or "").lower(),
            inputs=tuple(str(item) for item in raw_inputs),
            parameters=_json_copy(parameters),
            semantic_role=str(value.get("semantic_role") or ""),
            provenance=_json_copy(provenance),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "operator": self.operator,
            "inputs": list(self.inputs),
            "parameters": _json_copy(self.parameters),
            "semantic_role": self.semantic_role,
            "provenance": _json_copy(self.provenance),
        }


@dataclass(frozen=True)
class GeometryProgram:
    nodes: tuple[GeometryNode, ...]
    root_id: str
    name: str = "geometry_program"
    schema_version: str = "arr.maas.geometry_program.v1"
    metadata: dict[str, Any] = field(default_factory=dict)
    execution_contract: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GeometryProgram":
        if not isinstance(value, dict):
            raise TypeError("geometry program must be an object")
        nodes = value.get("nodes") or ()
        if not isinstance(nodes, list):
            raise TypeError("geometry program nodes must be an array")
        metadata = value.get("metadata") or {}
        execution_contract = value.get("execution_contract") or {}
        if not isinstance(metadata, dict) or not isinstance(execution_contract, dict):
            raise TypeError(
                "geometry program metadata/execution_contract must be objects"
            )
        return cls(
            nodes=tuple(GeometryNode.from_dict(item) for item in nodes),
            root_id=str(value.get("root_id") or ""),
            name=str(value.get("name") or "geometry_program"),
            schema_version=str(value.get("schema_version") or "arr.maas.geometry_program.v1"),
            metadata=_json_copy(metadata),
            execution_contract=_json_copy(execution_contract),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "root_id": self.root_id,
            "nodes": [node.to_dict() for node in self.nodes],
            "metadata": _json_copy(self.metadata),
            **(
                {"execution_contract": _json_copy(self.execution_contract)}
                if self.execution_contract
                else {}
            ),
        }

    @property
    def node_map(self) -> dict[str, GeometryNode]:
        return {node.id: node for node in self.nodes}

    def with_nodes(
        self,
        nodes: Iterable[GeometryNode],
        *,
        root_id: str | None = None,
        name_suffix: str = "",
    ) -> "GeometryProgram":
        return replace(
            self,
            nodes=tuple(nodes),
            root_id=root_id or self.root_id,
            name=f"{self.name}{name_suffix}",
        )

    def validate(self, *, maximum_nodes: int = 96, maximum_depth: int = 32) -> tuple[GeometryIssue, ...]:
        issues: list[GeometryIssue] = []
        if (
            self.execution_contract not in (
                {},
                FLOORWISE_CAPACITY_REPLAY_TRANSPORT_CONTRACT,
            )
            and not _valid_codex_book_path_execution_binding(
                self.execution_contract
            )
        ):
            issues.append(GeometryIssue(
                "invalid_execution_contract",
                "execution_contract is not a whitelisted deterministic contract",
            ))
        if not self.nodes:
            return (GeometryIssue("empty_program", "program has no nodes"),)
        if len(self.nodes) > maximum_nodes:
            issues.append(GeometryIssue("node_budget_exceeded", f"{len(self.nodes)} > {maximum_nodes}"))
        seen: set[str] = set()
        for node in self.nodes:
            if not IDENTIFIER_RE.match(node.id):
                issues.append(GeometryIssue("invalid_node_id", "node id is not a stable identifier", node.id))
            if node.id in seen:
                issues.append(GeometryIssue("duplicate_node_id", "node id appears more than once", node.id))
            seen.add(node.id)
            if node.kind not in NODE_KINDS:
                issues.append(GeometryIssue("unknown_node_kind", node.kind, node.id))
                continue
            if node.operator not in OPERATORS_BY_KIND[node.kind]:
                issues.append(GeometryIssue("unknown_operator", f"{node.kind}:{node.operator}", node.id))
            issues.extend(_arity_issues(node))
            issues.extend(_parameter_issues(node))
        if self.root_id not in seen:
            issues.append(GeometryIssue("missing_root", "root_id does not reference a node", self.root_id))
        for node in self.nodes:
            for input_id in node.inputs:
                if input_id not in seen:
                    issues.append(GeometryIssue("missing_input", f"missing input {input_id}", node.id))

        node_map = self.node_map
        state: dict[str, int] = {}

        def visit(node_id: str, depth: int) -> None:
            if depth > maximum_depth:
                issues.append(GeometryIssue("tree_depth_exceeded", f"depth > {maximum_depth}", node_id))
                return
            if state.get(node_id) == 1:
                issues.append(GeometryIssue("cyclic_reference", "geometry program contains a cycle", node_id))
                return
            if state.get(node_id) == 2 or node_id not in node_map:
                return
            state[node_id] = 1
            for input_id in node_map[node_id].inputs:
                visit(input_id, depth + 1)
            state[node_id] = 2

        if self.root_id in node_map:
            visit(self.root_id, 1)
        reachable = {node_id for node_id, value in state.items() if value == 2}
        for node in self.nodes:
            if node.id not in reachable:
                # A SolidNode graph is an executable program, not a drawing
                # document with spare objects.  Treating an unreachable node
                # as a warning let a critic add a ``courtyard``/``void`` node
                # beside the real root: graph notes then advertised a public
                # void even though the compiler and render never consumed it.
                # Requiring every declared solid to participate in the root
                # ancestry keeps the AI-readable graph, semantic roles and
                # compiled geometry causally identical.
                issues.append(GeometryIssue("unreachable_node", "node is not reachable from root", node.id))
        return tuple(_deduplicate_issues(issues))

    def topological_nodes(self) -> tuple[GeometryNode, ...]:
        issues = [issue for issue in self.validate() if issue.severity == "error"]
        if issues:
            raise ValueError("invalid geometry program: " + ", ".join(issue.code for issue in issues))
        node_map = self.node_map
        ordered: list[GeometryNode] = []
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visited:
                return
            node = node_map[node_id]
            for input_id in node.inputs:
                visit(input_id)
            visited.add(node_id)
            ordered.append(node)

        visit(self.root_id)
        return tuple(ordered)

    def canonical_dict(self) -> dict[str, Any]:
        ordered = self.topological_nodes()
        result = {
            "schema_version": self.schema_version,
            "root_id": self.root_id,
            "nodes": [
                {
                    "id": node.id,
                    "kind": node.kind,
                    "operator": node.operator,
                    "inputs": sorted(node.inputs) if node.operator in {"union", "intersection", "attach"} else list(node.inputs),
                    "parameters": _canonical_value(node.parameters),
                    "semantic_role": node.semantic_role,
                }
                for node in ordered
            ],
        }
        if self.execution_contract:
            result["execution_contract"] = _canonical_value(
                self.execution_contract
            )
        return result

    def program_hash(self) -> str:
        payload = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def canonical_structure_dict(self) -> dict[str, Any]:
        """Return an alpha-renaming-independent typed structure.

        ``program_hash`` intentionally preserves stable edit-target ids.  This
        second form is for candidate deduplication: two LLM programs that only
        differ in variable/node names receive the same structural hash.
        """
        ordered = self.topological_nodes()
        canonical_ids = {node.id: f"g{index:03d}" for index, node in enumerate(ordered, start=1)}
        rows = []
        for node in ordered:
            inputs = [canonical_ids[value] for value in node.inputs]
            # Attach is ordered: input 0 is the host and later inputs are
            # guests. Only genuinely commutative operators may sort inputs.
            if node.operator in {"union", "intersection"}:
                inputs.sort()
            rows.append({
                "id": canonical_ids[node.id],
                "kind": node.kind,
                "operator": node.operator,
                "inputs": inputs,
                "parameters": _canonical_value(node.parameters),
                "semantic_role": node.semantic_role,
            })
        return {"root_id": canonical_ids[self.root_id], "nodes": rows}

    def canonical_structure_hash(self) -> str:
        payload = json.dumps(
            self.canonical_structure_dict(), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _arity_issues(node: GeometryNode) -> list[GeometryIssue]:
    count = len(node.inputs)
    if node.kind == "primitive" and count != 0:
        return [GeometryIssue("invalid_arity", "primitive accepts no solid inputs", node.id)]
    if node.kind in UNARY_KINDS and count != 1:
        return [GeometryIssue("invalid_arity", f"{node.kind} requires one input", node.id)]
    if node.kind == "boolean":
        if node.operator == "difference" and count != 2:
            return [GeometryIssue("invalid_arity", "difference requires exactly two inputs", node.id)]
        if node.operator in {"union", "intersection"} and count < 2:
            return [GeometryIssue("invalid_arity", f"{node.operator} requires at least two inputs", node.id)]
    if node.kind == "composition" and count < 2:
        return [GeometryIssue("invalid_arity", "composition requires at least two inputs", node.id)]
    if node.kind == "macro" and count < 1:
        return [GeometryIssue("invalid_arity", "architectural macro requires a base input", node.id)]
    return []


MACRO_VERTICAL_ANCHORS = ("center", "input_base")
MACRO_VERTICAL_ANCHOR_OPERATORS = ("book_branch", "related_array")


def surface_parameter_issues(node: GeometryNode) -> list[GeometryIssue]:
    from backend.app.modules.design.generation.maas.geometry_language.surface_bounds import SURFACE_PARAMETERS, parse_surface_bounds

    if node.operator != "bound_surfaces":
        if SURFACE_PARAMETERS.intersection(node.parameters):
            return [GeometryIssue("unsupported_surface_parameters",
                "top_surface/bottom_surface require the bound_surfaces modifier", node.id)]
        return []
    try:
        parse_surface_bounds(node.parameters)
    except (ValueError, TypeError, OverflowError) as exc:
        return [GeometryIssue("invalid_surface_bounds", str(exc), node.id)]
    return []


def _parameter_issues(node: GeometryNode) -> list[GeometryIssue]:
    issues: list[GeometryIssue] = surface_parameter_issues(node)
    params = node.parameters
    if node.operator in MACRO_VERTICAL_ANCHOR_OPERATORS:
        if params.get("vertical_anchor", "center") not in MACRO_VERTICAL_ANCHORS:
            issues.append(GeometryIssue("invalid_vertical_anchor",
                "vertical_anchor must be center or input_base", node.id))
    positive_fields = {
        "width", "depth", "height", "radius", "radius_low", "radius_high",
        "start_height", "end_height", "profile_width", "profile_height", "level_height",
    }
    for key in positive_fields:
        if key not in params:
            continue
        try:
            if float(params[key]) <= 0:
                issues.append(GeometryIssue("non_positive_dimension", f"{key} must be positive", node.id))
        except (TypeError, ValueError):
            issues.append(GeometryIssue("invalid_parameter_type", f"{key} must be numeric", node.id))
    if node.operator in {"linear_array", "radial_array", "stack", "duplicate"}:
        try:
            count = int(params.get("count", 2))
            if not 1 <= count <= 24:
                issues.append(GeometryIssue("pattern_count_out_of_bounds", "count must be 1..24", node.id))
        except (TypeError, ValueError):
            issues.append(GeometryIssue("invalid_parameter_type", "count must be integer", node.id))
    if node.operator in {"extruded_polygon", "loft"}:
        key = "points" if node.operator == "extruded_polygon" else "profiles"
        minimum = 3 if node.operator == "extruded_polygon" else 2
        if not isinstance(params.get(key), list) or len(params[key]) < minimum:
            issues.append(GeometryIssue("missing_profile", f"{node.operator} requires at least {minimum} {key}", node.id))
    if node.operator == "sweep":
        path = params.get("path")
        if not isinstance(path, list) or len(path) < 2:
            issues.append(GeometryIssue("missing_path", "sweep requires at least two path points", node.id))
    if node.operator == "profile_sweep_3d":
        path = params.get("path")
        if not isinstance(path, list) or len(path) < 2:
            issues.append(GeometryIssue(
                "missing_path",
                "profile_sweep_3d requires at least two path points",
                node.id,
            ))
        elif not all(_finite_vector(point, 3) for point in path):
            issues.append(GeometryIssue(
                "invalid_profile_sweep_path",
                "profile_sweep_3d path points must contain three finite numbers",
                node.id,
            ))
        else:
            points = [tuple(float(value) for value in point) for point in path]
            segment_lengths = [
                sum((end[axis] - start[axis]) ** 2 for axis in range(3)) ** 0.5
                for start, end in zip(points, points[1:])
            ]
            if any(length <= 1e-9 for length in segment_lengths):
                issues.append(GeometryIssue(
                    "zero_length_profile_sweep_path",
                    "profile_sweep_3d path contains a zero-length segment",
                    node.id,
                ))
            if any(
                sum((right[axis] - left[axis]) ** 2 for axis in range(3)) ** 0.5 <= 1e-9
                for index, left in enumerate(points)
                for right in points[index + 1:]
            ):
                issues.append(GeometryIssue(
                    "repeated_profile_sweep_point",
                    "profile_sweep_3d path points must be unique",
                    node.id,
                ))
    if node.operator == "matrix_array":
        matrices = params.get("matrices")
        if not isinstance(matrices, list) or not 2 <= len(matrices) <= 24:
            issues.append(GeometryIssue(
                "matrix_array_count_out_of_bounds",
                "matrix_array requires 2..24 explicit matrices",
                node.id,
            ))
        elif not all(_affine_matrix4(matrix) for matrix in matrices):
            issues.append(GeometryIssue(
                "invalid_matrix_array_matrix",
                "matrix_array matrices must be finite affine 4x4 matrices",
                node.id,
            ))
    if node.operator in {"slice", "clip"}:
        normal = params.get("normal")
        if not _vector(normal, 3) or sum(float(value) ** 2 for value in normal) <= 1e-12:
            issues.append(GeometryIssue("invalid_plane", "cutting plane needs a non-zero normal", node.id))
    if node.operator == "clip_fraction":
        try:
            fraction = float(params.get("fraction", 1.0))
            if not 0.01 <= fraction <= 1.0:
                issues.append(GeometryIssue("scope_fraction_out_of_bounds", "fraction must be 0.01..1.0", node.id))
        except (TypeError, ValueError):
            issues.append(GeometryIssue("invalid_parameter_type", "fraction must be numeric", node.id))
    if node.operator == "book_base_volume":
        if str(params.get("label") or "") not in {"1/1", "3/8", "1/2", "1/4", "1/8", "1/16"}:
            issues.append(GeometryIssue("invalid_book_base_volume", "label must come from BOOK p.3", node.id))
        if str(params.get("orientation") or "") not in {"long_axis", "short_axis", "vertical"}:
            issues.append(GeometryIssue("invalid_book_orientation", "orientation must be long_axis, short_axis or vertical", node.id))
    vector_lengths = {
        "vector": 3,
        "normal": 3,
        "angles": 3,
        "start_scale": 2,
        "end_scale": 2,
        "shift_per_level": 3,
        "anchor": 2,
        "guest_extent": 3,
    }
    for parameter_name, length in vector_lengths.items():
        # A fraction selects a named side; attachment anchors remain local u/v.
        if parameter_name == "anchor" and node.operator == "clip_fraction":
            continue
        if parameter_name in params and not _vector(params[parameter_name], length):
            issues.append(GeometryIssue(
                "invalid_vector_parameter",
                f"{parameter_name} must contain {length} numeric values",
                node.id,
            ))
    enum_contracts = {
        ("clip_fraction", "anchor"): {"start", "center", "end", "low", "middle", "high", "negative", "positive"},
        ("cut_corner", "corner"): {"ne", "nw", "se", "sw"},
        ("notch", "corner"): {"ne", "nw", "se", "sw"},
        ("setback", "direction"): {"x", "y"},
        ("stepped_mass", "direction"): {"x", "y"},
        ("terrace", "direction"): {"x", "y"},
        ("leaning_tower", "direction"): {"x", "y"},
        ("profiled_hall", "span_axis"): {"x", "y"},
        ("attach", "host_face"): {"east", "west", "north", "south", "top", "bottom"},
    }
    for (operator, parameter_name), allowed in enum_contracts.items():
        if node.operator != operator or parameter_name not in params:
            continue
        if str(params[parameter_name]).lower() not in allowed:
            issues.append(GeometryIssue(
                "unsupported_parameter_value",
                f"{operator}.{parameter_name} supports {sorted(allowed)}",
                node.id,
            ))
    return issues


def _vector(value: Any, length: int) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        return False
    try:
        return all(float(item) == float(item) for item in value)
    except (TypeError, ValueError):
        return False


def _finite_vector(value: Any, length: int) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        return False
    try:
        return all(isfinite(float(item)) for item in value)
    except (TypeError, ValueError):
        return False


def _affine_matrix4(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return False
    if not all(_finite_vector(row, 4) for row in value):
        return False
    expected = (0.0, 0.0, 0.0, 1.0)
    return all(
        abs(float(value[3][index]) - expected[index]) <= 1e-9
        for index in range(4)
    )


def _deduplicate_issues(issues: Iterable[GeometryIssue]) -> list[GeometryIssue]:
    result: list[GeometryIssue] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in issues:
        key = (issue.code, issue.node_id, issue.message)
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return result


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, float):
        return round(value, 8)
    return value


GEOMETRY_PROGRAM_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://arr.local/schema/maas-geometry-program-v1.json",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "name", "root_id", "nodes", "metadata"],
    "properties": {
        "schema_version": {"const": "arr.maas.geometry_program.v1"},
        "name": {"type": "string", "minLength": 1, "maxLength": 120},
        "root_id": {"type": "string", "pattern": IDENTIFIER_RE.pattern},
        "metadata": {"type": "object"},
        "execution_contract": {"type": "object"},
        "nodes": {
            "type": "array",
            "minItems": 1,
            "maxItems": 96,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "kind", "operator", "inputs", "parameters", "semantic_role", "provenance"],
                "properties": {
                    "id": {"type": "string", "pattern": IDENTIFIER_RE.pattern},
                    "kind": {"enum": sorted(NODE_KINDS)},
                    "operator": {"type": "string"},
                    "inputs": {"type": "array", "items": {"type": "string"}, "maxItems": 24},
                    "parameters": {"type": "object"},
                    "semantic_role": {"type": "string", "maxLength": 80},
                    "provenance": {"type": "object"},
                },
            },
        },
    },
}


__all__ = [
    "GEOMETRY_PROGRAM_JSON_SCHEMA",
    "FLOORWISE_CAPACITY_REPLAY_TRANSPORT_CONTRACT",
    "GeometryIssue",
    "GeometryNode",
    "GeometryProgram",
    "NODE_KINDS",
    "OPERATORS_BY_KIND",
]
