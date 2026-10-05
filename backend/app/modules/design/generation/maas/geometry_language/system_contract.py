"""Machine-readable contract for the extended-CSG architectural mass system.

This is the design authority shared by the API, graph UI, LLM author and
tests.  It describes the executable modules already implemented by ``ast``,
``compiler``, ``programs``, ``gate`` and ``vlm_adapter`` without adding a
second geometry engine.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from backend.app.modules.design.generation.maas.geometry_language.ast import NODE_KINDS, OPERATORS_BY_KIND
from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.cost import program_cost
from backend.app.modules.design.generation.maas.geometry_language.dsl import program_to_dsl
from backend.app.modules.design.generation.maas.geometry_language.gate import compilation_gate
from backend.app.modules.design.generation.maas.geometry_language.programs import architectural_shape_programs


SCHEMA_VERSION = "arr.maas.extended_csg_contract.v1"

_SHAPE_CONTRACTS: tuple[dict[str, str], ...] = (
    {"family": "bent_linear_mass", "name": "Bent Linear Mass", "feature": "long rectangular bar curved in plan", "recommended": "sweep for an exact constant section; bend for editing an existing solid", "risk": "bend needs adequate longitudinal subdivision"},
    {"family": "radial_fan", "name": "Radial Fan Mass", "feature": "three connected wings rotate from a common hub", "recommended": "radial_array plus hub union", "risk": "thin arms or a missing hub create fragmented sculpture"},
    {"family": "l_mass", "name": "L Mass", "feature": "two perpendicular bars form one L-shaped body", "recommended": "two-box union is the canonical short program", "risk": "coplanar coincident faces if bars only touch"},
    {"family": "u_mass", "name": "U Mass", "feature": "three bars enclose an open-sided court", "recommended": "three-box union", "risk": "zero overlap at joints can split components"},
    {"family": "courtyard", "name": "Courtyard Mass", "feature": "closed perimeter mass around an internal open void", "recommended": "difference with an overshooting inner cutter", "risk": "coplanar cutter caps cause Boolean ambiguity"},
    {"family": "attached_volume", "name": "Attached Volume", "feature": "small annex is attached to a dominant body", "recommended": "attach composition with positive overlap", "risk": "a tangent annex is not a connected solid"},
    {"family": "overlapping_mass", "name": "Overlapping Rotated Mass", "feature": "two bars overlap with rotation and vertical offset", "recommended": "transform then union", "risk": "insufficient overlap yields disconnected components"},
    {"family": "setback", "name": "Setback Mass", "feature": "upper floors recede in repeated levels", "recommended": "setback macro lowered to scaled translated level union", "risk": "tiny terraces and excessive triangle count"},
    {"family": "cross_mass", "name": "Cross Mass", "feature": "two orthogonal bars cross at a shared center", "recommended": "rotate duplicate then union", "risk": "arms that are too thin fail occupiable-mass gates"},
    {"family": "tapered_tower", "name": "Tapered Tower", "feature": "top plan is smaller than the lower plan", "recommended": "taper modifier or loft for exact section control", "risk": "near-zero end scale creates inverted or tiny faces"},
    {"family": "leaning_tower", "name": "Leaning Tower", "feature": "floor plates translate progressively while remaining level", "recommended": "shear; rotate only when the entire building including floors should tilt", "risk": "large shear exceeds the permitted envelope"},
    {"family": "notch", "name": "Notched Mass", "feature": "a bounded corner portion is removed", "recommended": "notch macro lowered to difference", "risk": "cutter aligned exactly to a face is numerically unstable"},
    {"family": "diagonal_slice", "name": "Diagonal Slice Mass", "feature": "an oblique plane trims the solid", "recommended": "half-space clip rather than a huge cutter box", "risk": "zero normal or plane outside the solid returns empty/unchanged geometry"},
    {"family": "cut_corner", "name": "Cut-corner Polyhedron", "feature": "one plan corner becomes a chamfered face", "recommended": "cut_corner macro using a bounded wedge cutter", "risk": "corner ratio near zero creates tiny faces"},
    {"family": "lofted_envelope", "name": "Lofted Top/Bottom Mass", "feature": "lower, middle and upper profiles have different sizes", "recommended": "loft ordered compatible profiles", "risk": "profile winding or vertex-count mismatch can self-intersect"},
    {"family": "swept_bar", "name": "Swept Curved Bar", "feature": "constant rectangle section follows a curved path", "recommended": "rectangle profile sweep", "risk": "sharp path turns can overlap adjacent sweep segments"},
    {"family": "split_bridge", "name": "Split Wing + Bridge", "feature": "two wings frame a gap and reconnect with an elevated bridge", "recommended": "split_wing macro plus bridge composition", "risk": "bridge misses either wing or blocks the public gap"},
    {"family": "twisted_mass", "name": "Twisted Mass", "feature": "cross-section rotates gradually over height", "recommended": "bounded twist modifier", "risk": "high twist or subdivision count causes dense faceting"},
)

_MACRO_LOWERINGS = {
    "courtyard": "difference(base, overshooting_inner_box)",
    "carve_void": "difference(base, transformed_cutter)",
    "notch": "difference(base, corner_cutter)",
    "setback": "union(level_1, translate(scale(level_2)), ...)",
    "terrace": "union(shifted_and_scaled_levels)",
    "cantilever": "union(base_lower, translate(base_upper))",
    "bridge": "union(left, right, beam_between(left, right))",
    "cross_mass": "union(base, rotate(base, z, angle))",
    "bent_bar": "bend(base) or sweep(rectangle_profile, arc_path)",
    "split_wing": "split(base) + separate halves + optional bridge",
    "attach_volume": "attach(base, translated_scaled_annex)",
    "tapered_tower": "taper(base, axis=z, start_scale, end_scale)",
    "leaning_tower": "shear(base, horizontal_direction, amount)",
    "cut_corner": "difference(base, corner_wedge)",
    "stepped_mass": "union(repeated scaled translated levels)",
}


def _geometry_language_graph(shape_rows: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [{
        "id": "geometry:base-rectangle",
        "kind": "base_model",
        "stage": "base_model",
        "label": "Rectangle Profile / Box Base Model",
        "attributes": {"recursive_solid_root": True},
    }]
    edges: list[dict[str, str]] = []
    used_operators = sorted({
        operator
        for row in shape_rows
        for operator in row["operators"]
    })
    for operator in used_operators:
        kind = next(kind for kind, values in OPERATORS_BY_KIND.items() if operator in values)
        stage = "architectural_macro" if kind == "macro" else "core_operator"
        nodes.append({
            "id": f"geometry:operator:{operator}",
            "kind": kind,
            "stage": stage,
            "label": operator,
            "attributes": {"returns": "SolidNode", "recursive": True},
        })
        edges.append({
            "source": "geometry:base-rectangle",
            "target": f"geometry:operator:{operator}",
            "kind": "available_operation",
        })
    for row in shape_rows:
        shape_id = f"geometry:phenotype:{row['index']:02d}"
        nodes.append({
            "id": shape_id,
            "kind": "phenotype",
            "stage": "phenotype",
            "label": f"{row['index']:02d} {row['name']}",
            "attributes": {
                "family": row["family"],
                "compile_status": row["compile_status"],
                "geometry_hash": row["geometry_hash"],
            },
        })
        for operator in row["operators"]:
            edges.append({
                "source": f"geometry:operator:{operator}",
                "target": shape_id,
                "kind": "participates_in_program",
            })
        edges.append({"source": shape_id, "target": "geometry:compiler", "kind": "compiled_by"})
    tail = (
        ("geometry:compiler", "compiler", "compiler", "Geometry Compiler"),
        ("geometry:render", "render", "render_vlm_gate", "Four-view MASS PNG"),
        ("geometry:vlm", "vlm_critic", "render_vlm_gate", "Reference VLM Critic"),
        ("geometry:gate", "hard_gate", "render_vlm_gate", "Geometry GATE"),
        ("geometry:selector", "selector", "render_vlm_gate", "Canonical Selector"),
    )
    nodes.extend({"id": i, "kind": k, "stage": s, "label": label, "attributes": {}} for i, k, s, label in tail)
    edges.extend((
        {"source": "geometry:compiler", "target": "geometry:render", "kind": "renders"},
        {"source": "geometry:render", "target": "geometry:vlm", "kind": "reviewed_by"},
        {"source": "geometry:vlm", "target": "geometry:gate", "kind": "typed_revision_then_gate"},
        {"source": "geometry:gate", "target": "geometry:selector", "kind": "selects_valid_program"},
    ))
    return {
        "stage_order": ["base_model", "core_operator", "architectural_macro", "phenotype", "compiler", "render_vlm_gate"],
        "nodes": nodes,
        "edges": edges,
    }


@lru_cache(maxsize=1)
def build_extended_csg_contract() -> dict[str, Any]:
    programs = architectural_shape_programs()
    descriptions = {item["family"]: item for item in _SHAPE_CONTRACTS}
    shape_rows: list[dict[str, Any]] = []
    for index, program in enumerate(programs, start=1):
        family = str(program.metadata["family"])
        compilation = compile_geometry_program(program)
        description = descriptions[family]
        shape_rows.append({
            "index": index,
            **description,
            "primitive_operators": sorted({node.operator for node in program.nodes if node.kind == "primitive"}),
            "operators": [node.operator for node in program.topological_nodes()],
            "minimum_program": program_to_dsl(program),
            "ast": program.to_dict(),
            "compile_status": compilation.status,
            "gate_pass": not compilation_gate(compilation),
            "geometry_hash": compilation.geometry_hash,
            "metrics": compilation.metrics,
            "program_cost": program_cost(program, compilation).to_dict(),
        })

    graph = _geometry_language_graph(shape_rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "definition": "Extended CSG-based Procedural Architectural Massing Language",
        "not_plain_csg_because": [
            "transforms and modifier stacks preserve order",
            "non-linear deformation maps coordinates inside one solid",
            "profile/path constructors create sweep and loft solids",
            "patterns and architectural macros expand to recursive core nodes",
            "LLM/VLM author typed programs and edits rather than mesh vertices",
        ],
        "type_invariant": "Every GeometryNode consumes zero or more SolidNode references and returns exactly one SolidNode; profiles and paths are immutable parameter values.",
        "recursive_grammar": [
            "Solid := Primitive",
            "Solid := Transform(Solid)",
            "Solid := Modifier(Solid)",
            "Solid := Boolean(Solid, Solid...)",
            "Solid := Pattern(Solid)",
            "Solid := Composition(Solid, Solid...)",
            "Solid := Macro(Solid, Solid...)",
        ],
        "minimal_primitives": {
            "box": "width, depth, height, center=false",
            "cylinder": "radius_low, radius_high, height, segments",
            "extruded_polygon": "points, holes, height",
            "wedge": "width, depth, start_height, end_height",
            "sweep": "rectangle profile dimensions plus path points",
            "loft": "ordered compatible polygon profiles with z",
        },
        "operator_inventory": {kind: sorted(values) for kind, values in OPERATORS_BY_KIND.items()},
        "node_kinds": sorted(NODE_KINDS),
        "architectural_macro_lowerings": _MACRO_LOWERINGS,
        "semantic_distinctions": {
            "rotate_vs_shear": "Rotate tilts the entire local frame and floor plates; shear keeps horizontal sections level while their centers drift with height.",
            "bend_vs_sweep": "Bend warps an existing solid and needs subdivision; sweep constructs a section along a path and is more stable for a constant rectangular curved bar.",
            "plane_clip_vs_large_cutter": "Half-space clipping has an explicit infinite-plane meaning and better scale conditioning; a huge Boolean cutter is easier to prototype but introduces arbitrary extents and coplanar faces.",
            "modifier_order": "bend(difference(base,cutter)) is not equivalent to difference(bend(base),cutter) because the first also bends the cut boundary.",
        },
        "compiler_stages": [
            "DSL parser", "semantic validation", "macro expansion", "core geometry AST",
            "recursive transform/CSG/deformation evaluation", "solid validation",
            "mesh generation", "triangulation", "normal generation", "four-view rendering",
        ],
        "gate_rules": [
            "valid syntax and known operators", "existing references and acyclic graph",
            "positive primitive dimensions", "non-empty Boolean results", "closed solid",
            "watertight manifold mesh", "kernel self-intersection check", "valid triangle orientation",
            "minimum edge and face tolerances", "coplanar Boolean avoidance", "mesh complexity budget",
            "component budget", "allowed bounding box",
        ],
        "recovery_policy": [
            "reject invalid AST before kernel evaluation",
            "report the exact node id and typed issue code",
            "prefer half-space cuts and overshooting cutters for numerical repair",
            "request bounded parameter or operator replacement edits from the critic",
            "recompile, rerender and rerun every hard gate before selection",
        ],
        "selection_policy": {
            "canonicalization": "topological typed AST plus commutative-input ordering",
            "equivalence": "geometry hash first, symmetric solid difference second",
            "cost": "node_count + tree_depth_penalty + boolean_penalty + deformation_penalty + topology_complexity + unstable_operation_penalty + invalid_geometry_penalty",
        },
        "image_program_synthesis": [
            "Reference VLM extracts proportion, topology, likely operators and part relations",
            "LLM emits multiple schema-valid Geometry Programs",
            "Compiler produces solid, mesh, views and node-local errors",
            "VLM critic returns scores and bounded typed edits",
            "GATE rejects invalid or architecturally broken geometry",
            "Selector deduplicates equivalent solids and minimizes program cost",
        ],
        "shape_count": len(shape_rows),
        "shapes": shape_rows,
        "graph": graph,
    }


__all__ = ["SCHEMA_VERSION", "build_extended_csg_contract"]
