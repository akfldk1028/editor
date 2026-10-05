"""OpenAI-backed MassDSL population proposal loop for MAAS."""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from math import atan2, degrees
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely.geometry import Polygon

from backend.app.modules.design.generation.maas.grammar.component_graph import MassComponentGraph, MassComponentNode, graph_from_sequence
from backend.app.modules.design.generation.maas.grammar.parameter_schema import PARAMETER_BOUNDS, bounded_parameter
from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbSequence, call
from backend.app.modules.design.generation.maas.grammar.vocab import SUPPORTED_VERBS


LLM_BATCH_SCHEMA_VERSION = "arr.maas.llm_massdsl_batch.v1"
LLM_PARAMETER_SOURCE = "llm_arch_language_proposal"
DEFAULT_MODEL = "gpt-5.4-mini"

ARCHITECTURAL_PRECEDENT_PRINCIPLES = (
    "user-provided architecture book/reference formal principles",
    "Trimage-like slender tower and disciplined podium/base relationship",
    "Vancouver House/BIG-like undercut, taper, torque, and strong silhouette transition",
    "OMA/Seattle Central Library-like stacked platforms, shifted volumes, and diagrammatic section",
    "BIG/OMA-like single dominant gesture reinforced by one compatible secondary gesture",
)

GENERATOR_MODE_BY_FAMILY = {
    "array_cluster": "additive",
    "offset": "additive",
    "reflected_pair": "additive",
    "slender_bar": "additive",
    "extrude": "additive",
    "courtyard": "subtractive",
    "void_notch": "subtractive",
    "pinch": "subtractive",
    "embed": "subtractive",
    "nest": "subtractive",
    "split": "hybrid",
    "bend": "hybrid",
    "interlock": "hybrid",
    "overlap": "hybrid",
    "branch": "hybrid",
    "diagonal_connect": "sectional",
    "terrace_link": "sectional",
    "sloped_roof": "sectional",
}

MASS_LANGUAGE_BY_FAMILY = {
    "courtyard": "courtyard_atrium",
    "void_notch": "notched_void",
    "split": "split_bridge",
    "diagonal_connect": "diagonal_connector",
    "array_cluster": "array_cluster",
    "offset": "offset_twin_bar",
    "reflected_pair": "reflected_court_pair",
    "slender_bar": "bar_notch_terrace",
    "bend": "bend_ribbon",
    "interlock": "cross_interlock",
    "overlap": "overlap_slabs",
    "branch": "branch_taper",
    "pinch": "pinched_waist",
    "embed": "embedded_void",
    "extrude": "extruded_fin",
    "nest": "nested_atrium_stack",
    "terrace_link": "terrace_ribbon",
    "sloped_roof": "sloped_roof",
}

PARAMETER_ALIASES_BY_VERB = {
    "notch": {"ratio": ("size", "depth_ratio", "void_ratio", "notch_ratio")},
    "cave": {
        "side": ("face",),
        "width_ratio": ("aperture_ratio", "opening_ratio"),
        "depth_ratio": ("depth", "void_ratio", "carve_ratio"),
    },
    "courtyard": {
        "ratio": ("court_ratio", "void_ratio", "atrium_ratio"),
        "open_side": ("side", "court_open_side", "access_side"),
    },
    "split": {"gap_ratio": ("gap", "void_ratio"), "bridge_ratio": ("bridge",)},
    "pinch": {"waist_ratio": ("factor", "pinch_ratio")},
    "offset": {"distance_ratio": ("distance", "magnitude_ratio", "offset_ratio")},
    "shift": {"distance_ratio": ("distance", "magnitude_ratio", "offset_ratio")},
    "array": {
        "spacing_ratio": ("spacing", "gap_ratio"),
        "hierarchy_ratio": ("size_gradient", "scale_gradient"),
        "stagger_ratio": ("stagger", "cross_shift_ratio"),
    },
    "taper": {"x_ratio": ("top_ratio",), "y_ratio": ("top_ratio",)},
    "sloped_roof_mass": {"x_ratio": ("roof_taper_ratio",), "y_ratio": ("roof_span_ratio",)},
}

REQUIRED_PARAMS_BY_VERB = {
    "notch": ("corner", "ratio"),
    "cave": ("side", "width_ratio", "depth_ratio"),
    "courtyard": ("ratio", "upper_ratio", "lower_floor_fraction"),
    "split": ("axis", "gap_ratio", "bridge_ratio", "upper_ratio", "lower_floor_fraction"),
    "bar": ("axis", "factor", "shift", "upper_ratio", "lower_floor_fraction"),
    "branch": ("angle", "trunk_ratio", "arm_ratio", "upper_ratio", "lower_floor_fraction"),
    "pinch": ("axis", "waist_ratio", "depth_ratio", "upper_ratio", "lower_floor_fraction"),
    "bend": ("axis", "angle", "factor", "upper_ratio", "lower_floor_fraction"),
    "embed": ("guest_scale", "position", "upper_ratio", "distance_ratio", "lower_floor_fraction"),
    "extrude": ("axis", "length", "size", "upper_ratio", "lower_floor_fraction"),
    "nest": ("inner_scale", "upper_ratio", "lower_floor_fraction"),
    "stack": ("levels", "upper_ratio", "lower_floor_fraction"),
    "offset": ("axis", "distance_ratio", "other_scale", "upper_ratio", "lower_floor_fraction"),
    "array": (
        "axis", "n", "spacing_ratio", "unit_scale", "hierarchy_ratio",
        "stagger_ratio", "lower_floor_fraction",
    ),
    "reflect": ("axis", "gap_ratio", "unit_scale", "upper_ratio", "lower_floor_fraction"),
    "interlock": ("angle", "bar_ratio", "upper_ratio", "distance_ratio", "lower_floor_fraction"),
    "overlap": ("axis", "slab_ratio", "shift_ratio", "upper_ratio", "distance_ratio", "lower_floor_fraction"),
    "lift": ("upper_ratio", "lower_floor_fraction"),
    "taper": ("x_ratio", "y_ratio", "lower_floor_fraction"),
    "grade": ("side", "width_ratio", "depth_ratio", "lower_floor_fraction"),
    "shift": ("axis", "distance_ratio"),
    "diagonal_connect": ("axis", "upper_ratio", "distance_ratio", "angle", "lower_floor_fraction"),
    "terrace_link": ("side", "upper_ratio", "width_ratio", "depth_ratio", "lower_floor_fraction"),
    "sloped_roof_mass": ("upper_ratio", "x_ratio", "y_ratio", "lower_floor_fraction"),
}

AXIS_PARAMS_BY_VERB = {
    "bar",
    "split",
    "pinch",
    "bend",
    "extrude",
    "offset",
    "array",
    "reflect",
    "overlap",
    "shift",
    "diagonal_connect",
}

TYPOLOGY_FAMILY_ALIASES = {
    "cluster": "array_cluster",
    "array": "array_cluster",
    "bridge": "diagonal_connect",
    "connector": "diagonal_connect",
    "bar_slab": "slender_bar",
    "bar": "slender_bar",
    "bent": "bend",
    "roof_envelope": "sloped_roof",
    "roof": "sloped_roof",
    "terrace": "terrace_link",
    "terrace_ribbon": "terrace_link",
    "void_carve": "void_notch",
    "void": "void_notch",
    "nested": "nest",
    "reflect": "reflected_pair",
    "reflected": "reflected_pair",
    "cave": "void_notch",
    "carve": "void_notch",
    "pinching": "pinch",
    "branching": "branch",
}

REQUIRED_COVERAGE_FAMILIES = (
    "courtyard",
    "void_notch",
    "split",
    "diagonal_connect",
    "array_cluster",
    "offset",
    "reflected_pair",
    "slender_bar",
    "bend",
    "interlock",
    "overlap",
    "branch",
    "pinch",
    "embed",
    "extrude",
    "nest",
    "terrace_link",
    "sloped_roof",
)

BATCH_FAMILY_FOCUS = (
    ("array_cluster", "offset", "reflected_pair", "slender_bar", "extrude"),
    ("courtyard", "void_notch", "pinch", "embed", "nest"),
    ("split", "bend", "interlock", "overlap", "branch"),
    ("diagonal_connect", "terrace_link", "sloped_roof", "split", "overlap"),
)

ROLE_VERBS = {
    "root": {"base"},
    # Primary is the dominant operation and may legitimately be subtractive
    # (for example a courtyard or notched monolith).
    "primary": set(SUPPORTED_VERBS) - {"base"},
    "void": {"cave", "courtyard", "embed", "nest", "notch", "pinch"},
    "connector": {"diagonal_connect", "interlock", "overlap", "terrace_link"},
    "support": {"array", "bar", "branch", "extrude", "grade", "inset", "lift", "offset", "reflect", "shift", "sloped_roof_mass", "stack", "taper", "terrace_link"},
}

ROLE_RELATIONS = {
    "root": {"input"},
    "primary": {"attach", "deform", "input"},
    "support": {"attach", "deform", "input"},
    "void": {"subtract"},
    "connector": {"connect"},
}


def _call_node_schema() -> dict[str, Any]:
    """Role-discriminated node union accepted by Structured Outputs."""
    variants = []
    for role in sorted(ROLE_VERBS):
        variants.append({
            "type": "object",
            "additionalProperties": False,
            "required": ["node_id", "parent_node_id", "role", "relation", "verb", "params"],
            "properties": {
                "node_id": {"type": "string"},
                "parent_node_id": {"type": "string"},
                "role": {"type": "string", "const": role},
                "relation": {"type": "string", "enum": sorted(ROLE_RELATIONS[role])},
                "verb": {"type": "string", "enum": sorted(ROLE_VERBS[role])},
                "params": {"type": "string"},
            },
        })
    return {"anyOf": variants}

COVERAGE_REPAIR_CALLS = {
    "courtyard": [
        ("base", {"coverage_ratio": 0.42}),
        ("courtyard", {"ratio": 0.24, "upper_ratio": 0.86, "lower_floor_fraction": 0.42}),
        ("offset", {"axis": "x", "distance_ratio": 0.06, "other_scale": 0.72, "upper_ratio": 0.80, "lower_floor_fraction": 0.42}),
    ],
    "void_notch": [
        ("base", {"coverage_ratio": 0.44}),
        ("notch", {"corner": "+x+y", "ratio": 0.18, "upper_ratio": 0.88, "lower_floor_fraction": 0.46}),
        ("cave", {"side": "west", "width_ratio": 0.38, "depth_ratio": 0.16}),
    ],
    "split": [
        ("base", {"coverage_ratio": 0.46}),
        ("split", {"axis": "x", "gap_ratio": 0.20, "bridge_ratio": 0.24, "upper_ratio": 0.78, "distance_ratio": 0.06, "lower_floor_fraction": 0.40}),
        ("lift", {"upper_ratio": 0.76, "lower_floor_fraction": 0.40}),
    ],
    "diagonal_connect": [
        ("base", {"coverage_ratio": 0.42}),
        ("diagonal_connect", {"axis": "x", "upper_ratio": 0.74, "distance_ratio": 0.10, "angle": 28.0, "lower_floor_fraction": 0.38}),
        ("notch", {"corner": "-x+y", "ratio": 0.12}),
    ],
    "array_cluster": [
        ("base", {"coverage_ratio": 0.46}),
        ("array", {"axis": "x", "n": 3, "spacing_ratio": 0.18, "unit_scale": 0.34, "lower_floor_fraction": 0.34}),
        ("shift", {"axis": "y", "distance_ratio": 0.05}),
    ],
    "offset": [
        ("base", {"coverage_ratio": 0.44}),
        ("offset", {"axis": "y", "distance_ratio": 0.18, "other_scale": 0.62, "upper_ratio": 0.78, "lower_floor_fraction": 0.38}),
        ("bar", {"axis": "x", "factor": 0.58, "shift": 0.04, "upper_ratio": 0.82, "lower_floor_fraction": 0.46}),
    ],
    "reflected_pair": [
        ("base", {"coverage_ratio": 0.44}),
        ("reflect", {"axis": "x", "gap_ratio": 0.16, "unit_scale": 0.46, "upper_ratio": 0.80, "lower_floor_fraction": 0.40}),
        ("courtyard", {"ratio": 0.18, "upper_ratio": 0.82, "lower_floor_fraction": 0.40}),
    ],
    "slender_bar": [
        ("base", {"coverage_ratio": 0.42}),
        ("bar", {"axis": "y", "factor": 0.48, "shift": 0.08, "upper_ratio": 0.88, "lower_floor_fraction": 0.56}),
        ("notch", {"corner": "+x-y", "ratio": 0.12}),
    ],
    "bend": [
        ("base", {"coverage_ratio": 0.44}),
        ("bend", {"axis": "y", "angle": 30.0, "factor": 0.56, "upper_ratio": 0.80, "lower_floor_fraction": 0.42}),
        ("shift", {"axis": "x", "distance_ratio": 0.05}),
    ],
    "interlock": [
        ("base", {"coverage_ratio": 0.44}),
        ("interlock", {"angle": 28.0, "bar_ratio": 0.34, "upper_ratio": 0.74, "distance_ratio": 0.06, "lower_floor_fraction": 0.42}),
        ("cave", {"side": "south", "width_ratio": 0.34, "depth_ratio": 0.14}),
    ],
    "overlap": [
        ("base", {"coverage_ratio": 0.44}),
        ("overlap", {"axis": "x", "slab_ratio": 0.52, "shift_ratio": 0.18, "upper_ratio": 0.78, "distance_ratio": 0.06, "lower_floor_fraction": 0.42}),
        ("notch", {"corner": "-x-y", "ratio": 0.10}),
    ],
    "branch": [
        ("base", {"coverage_ratio": 0.42}),
        ("branch", {"angle": 34.0, "trunk_ratio": 0.30, "arm_ratio": 0.20, "upper_ratio": 0.78, "lower_floor_fraction": 0.42}),
        ("shift", {"axis": "y", "distance_ratio": 0.04}),
    ],
    "pinch": [
        ("base", {"coverage_ratio": 0.44}),
        ("pinch", {"axis": "x", "waist_ratio": 0.58, "depth_ratio": 0.34, "upper_ratio": 0.82, "lower_floor_fraction": 0.46}),
        ("cave", {"side": "east", "width_ratio": 0.32, "depth_ratio": 0.12}),
    ],
    "embed": [
        ("base", {"coverage_ratio": 0.44}),
        ("embed", {"guest_scale": 0.38, "position": [0.12, -0.08, 0.0], "upper_ratio": 0.76, "distance_ratio": 0.06, "lower_floor_fraction": 0.38}),
        ("lift", {"upper_ratio": 0.76, "lower_floor_fraction": 0.38}),
    ],
    "extrude": [
        ("base", {"coverage_ratio": 0.42}),
        ("extrude", {"axis": "x", "length": 0.34, "size": 0.30, "upper_ratio": 0.70, "lower_floor_fraction": 0.36}),
        ("bar", {"axis": "y", "factor": 0.62, "shift": -0.04, "upper_ratio": 0.82, "lower_floor_fraction": 0.44}),
    ],
    "nest": [
        ("base", {"coverage_ratio": 0.44}),
        ("nest", {"inner_scale": 0.44, "upper_ratio": 0.76, "lower_floor_fraction": 0.40}),
        ("stack", {"levels": 3, "z_step_ratio": 0.08, "upper_ratio": 0.74, "lower_floor_fraction": 0.36}),
    ],
    "terrace_link": [
        ("base", {"coverage_ratio": 0.44}),
        ("lift", {"upper_ratio": 0.82, "lower_floor_fraction": 0.40}),
        ("terrace_link", {"side": "east", "upper_ratio": 0.84, "width_ratio": 0.58, "depth_ratio": 0.22, "lower_floor_fraction": 0.40}),
        ("shift", {"axis": "x", "distance_ratio": 0.05}),
    ],
    "sloped_roof": [
        ("base", {"coverage_ratio": 0.44}),
        ("sloped_roof_mass", {"upper_ratio": 0.90, "x_ratio": 0.70, "y_ratio": 0.90, "lower_floor_fraction": 0.48}),
        ("bar", {"axis": "x", "factor": 0.64, "shift": 0.03, "upper_ratio": 0.86, "lower_floor_fraction": 0.50}),
    ],
}


class LlmProposalError(RuntimeError):
    pass


@dataclass(frozen=True)
class LlmProposalBatch:
    artifact: dict[str, Any]
    sequences: tuple[VerbSequence, ...]


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _supports_reasoning_effort(model: str) -> bool:
    model_name = str(model or "").lower()
    return model_name.startswith(("gpt-5", "o1", "o3", "o4"))


def _normalise_params(verb: str, params: dict[str, Any]) -> dict[str, Any]:
    """Translate common architectural synonyms into compiler canonical keys."""
    normalised = dict(params)
    for canonical, aliases in PARAMETER_ALIASES_BY_VERB.get(verb, {}).items():
        if canonical in normalised:
            continue
        for alias in aliases:
            if alias in normalised:
                normalised[canonical] = normalised[alias]
                break
    if verb == "cave":
        if "side" not in normalised and normalised.get("axis") in {"x", "y"}:
            normalised["side"] = "east" if normalised["axis"] == "x" else "north"
        if "void_ratio" in normalised:
            void_ratio = _safe_float(normalised.get("void_ratio"), 0.16)
            normalised.setdefault("depth_ratio", _clamp(void_ratio, 0.08, 0.36))
            normalised.setdefault("width_ratio", _clamp(void_ratio * 2.8, 0.28, 0.68))
    if verb == "notch" and "ratio" not in normalised and "depth_ratio" in normalised:
        normalised["ratio"] = normalised["depth_ratio"]
    if verb in {"offset", "shift"} and "distance_ratio" not in normalised and "magnitude_ratio" in normalised:
        normalised["distance_ratio"] = normalised["magnitude_ratio"]
    if verb == "array":
        # A cluster language needs controllable hierarchy and stagger. Older
        # cached author records remain executable through explicit defaults,
        # while new prompts expose both values to the authoring agent.
        normalised["hierarchy_ratio"] = round(
            _clamp(_safe_float(normalised.get("hierarchy_ratio"), 0.18), 0.08, 0.36),
            4,
        )
        normalised["stagger_ratio"] = round(
            _clamp(_safe_float(normalised.get("stagger_ratio"), 0.12), 0.04, 0.28),
            4,
        )
    if verb == "sloped_roof_mass" and "pitch_proxy" in normalised:
        pitch = _clamp(_safe_float(normalised.get("pitch_proxy"), 0.18), 0.06, 0.32)
        ridge_axis = str(normalised.get("ridge_axis") or normalised.get("axis") or "x")
        if "x_ratio" not in normalised:
            normalised["x_ratio"] = round(_clamp(1.0 - pitch * (1.5 if ridge_axis == "y" else 1.0), 0.58, 0.92), 3)
        if "y_ratio" not in normalised:
            normalised["y_ratio"] = round(_clamp(1.0 - pitch * (1.5 if ridge_axis == "x" else 1.0), 0.58, 0.92), 3)
    if verb == "sloped_roof_mass":
        axis = str(normalised.get("axis") or normalised.get("ridge_axis") or "x").strip().lower()
        normalised["axis"] = axis if axis in {"x", "y"} else "x"
        normalised["field_samples"] = int(round(_clamp(_safe_float(normalised.get("field_samples"), 5), 5, 9)))
        normalised["longitudinal_wave"] = round(
            _clamp(_safe_float(normalised.get("longitudinal_wave"), 0.0), -0.24, 0.24), 4
        )
        normalised["twist"] = round(
            _clamp(_safe_float(normalised.get("twist"), 0.0), -0.30, 0.30), 4
        )
    if verb == "taper" and isinstance(normalised.get("plan_control_points"), list):
        raw_plan_controls = normalised["plan_control_points"]
        plan_controls: list[list[float]] = []
        for point in raw_plan_controls:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError("taper plan_control_points must contain only [u,v] polygon vertices")
            try:
                u, v = float(point[0]), float(point[1])
            except (TypeError, ValueError) as exc:
                raise ValueError("taper plan_control_points must contain numeric [u,v] polygon vertices") from exc
            plan_controls.append([
                round(_clamp(u, 0.02, 0.98), 4),
                round(_clamp(v, 0.02, 0.98), 4),
            ])
        if not 3 <= len(plan_controls) <= 8:
            raise ValueError("taper plan_control_points must contain 3 to 8 polygon vertices")
        plan_polygon = Polygon(plan_controls)
        if not plan_polygon.is_valid or plan_polygon.area < 0.06:
            raise ValueError("taper plan_control_points must form one non-self-crossing plan polygon with area >= 0.06")
        heights = normalised.get("top_height_controls")
        if not isinstance(heights, list) or len(heights) != len(plan_controls):
            raise ValueError("taper top_height_controls must match plan_control_points length")
        clean_heights: list[float] = []
        for height in heights:
            if isinstance(height, (list, tuple, dict)):
                raise ValueError("taper top_height_controls must be a scalar height list, not [u,height] pairs")
            try:
                clean_heights.append(round(_clamp(float(height), 0.42, 1.0), 4))
            except (TypeError, ValueError) as exc:
                raise ValueError("taper top_height_controls must contain numeric scalar heights") from exc
        normalised["plan_control_points"] = plan_controls
        normalised["top_height_controls"] = clean_heights
    if verb == "bend":
        width = _safe_float(normalised.get("lane_width_ratio"), 0.10)
        # Models sometimes express ribbon width as a full-depth factor (0.5)
        # instead of the half-width ratio contract (0.06). Convert units at
        # the typed boundary rather than letting the compiler clamp every such
        # candidate to the same maximum-width ribbon.
        if width > 0.20:
            width *= 0.12
        normalised["lane_width_ratio"] = round(_clamp(width, 0.075, 0.22), 4)
        normalised["vertical_overlap"] = round(
            _clamp(_safe_float(normalised.get("vertical_overlap"), 0.22), 0.16, 0.30),
            4,
        )
        vertical = str(normalised.get("vertical_mode") or "terraced").strip().lower()
        normalised["vertical_mode"] = {
            "rise": "terraced",
            "ramp": "terraced",
            "cascade": "terraced",
            "stacked": "terraced",
        }.get(vertical, vertical if vertical in {"terraced", "grounded"} else "terraced")
        topology = str(normalised.get("field_topology") or "parallel").strip().lower()
        normalised["field_topology"] = topology if topology in {"parallel", "branched"} else "parallel"
        for key, default, lower, upper in (
            ("width_start_ratio", 0.72, 0.45, 1.35),
            ("width_mid_ratio", 1.20, 0.65, 1.55),
            ("width_end_ratio", 0.78, 0.45, 1.35),
            ("width_wave", 0.10, -0.28, 0.28),
            ("branch_point_ratio", 0.36, 0.22, 0.58),
            ("height_start_ratio", 0.64, 0.40, 1.00),
            ("height_mid_ratio", 0.96, 0.50, 1.00),
            ("height_end_ratio", 0.70, 0.40, 1.00),
            ("height_wave", 0.10, -0.24, 0.24),
        ):
            normalised[key] = round(
                _clamp(_safe_float(normalised.get(key), default), lower, upper),
                4,
            )
    # Persist the same typed numeric contract that the compiler consumes.
    # Previously out-of-range LLM values survived in graph JSON while the
    # compiler silently clamped them, so later agents edited a graph that did
    # not actually describe the rendered geometry.
    for key in set(normalised) & set(PARAMETER_BOUNDS):
        try:
            normalised[key] = bounded_parameter(key, float(normalised[key]))
        except (TypeError, ValueError):
            continue
    return normalised


def _validate_call_params(candidate_name: str, verb: str, params: dict[str, Any]) -> None:
    required = REQUIRED_PARAMS_BY_VERB.get(verb, ())
    missing = [key for key in required if key not in params]
    if missing:
        raise ValueError(f"{candidate_name}: {verb!r} missing required params {missing}")
    if verb in AXIS_PARAMS_BY_VERB and "axis" in params and str(params["axis"]) not in {"x", "y"}:
        raise ValueError(f"{candidate_name}: {verb!r} axis must be x or y, got {params['axis']!r}")
    if verb == "array":
        count = int(_safe_float(params.get("n"), 0))
        if count < 3:
            raise ValueError(f"{candidate_name}: array n must be >= 3, got {params.get('n')!r}")


def _record_family(record: dict[str, Any]) -> str | None:
    raw = " ".join([
        str(record.get("name") or ""),
        str(record.get("typology") or ""),
        str(record.get("architectural_language") or ""),
    ]).lower().replace("-", "_").replace(" ", "_")
    for family in REQUIRED_COVERAGE_FAMILIES:
        if family in raw:
            return family
    for alias, family in TYPOLOGY_FAMILY_ALIASES.items():
        if alias in raw:
            return family
    return None


def _coverage_repair_record(family: str, index: int) -> dict[str, Any]:
    calls = []
    previous = "root"
    for call_index, (verb, params) in enumerate(COVERAGE_REPAIR_CALLS[family]):
        role = "root" if call_index == 0 else "primary" if call_index == 1 else (
            "void" if verb in {"notch", "cave", "courtyard", "puncture", "pinch", "embed", "nest"}
            else "connector" if verb in {"bridge", "diagonal_connect", "terrace_link", "interlock", "overlap"}
            else "support"
        )
        node_id = "root" if call_index == 0 else f"{role}_{call_index}_{verb}"
        calls.append({
            "node_id": node_id,
            "parent_node_id": "" if call_index == 0 else ("root" if role == "primary" else previous),
            "role": role,
            "relation": "input" if role == "root" else "subtract" if role == "void" else "connect" if role == "connector" else "attach",
            "verb": verb,
            "params": json.dumps(params, separators=(",", ":")),
        })
        previous = node_id
    authored_keys = [
        f"{verb}.{key}"
        for verb, params in COVERAGE_REPAIR_CALLS[family]
        for key in sorted(params)
    ]
    secondary_language = {
        "array_cluster": "courtyard_atrium",
        "offset": "sloped_roof",
        "reflected_pair": "sloped_roof",
        "slender_bar": "bend_ribbon",
        "extrude": "offset_twin_bar",
        "courtyard": "diagonal_connector",
        "void_notch": "bar_notch_terrace",
        "pinch": "diagonal_connector",
        "embed": "courtyard_atrium",
        "nest": "courtyard_atrium",
        "split": "diagonal_connector",
        "bend": "overlap_slabs",
        "interlock": "diagonal_connector",
        "overlap": "branch_taper",
        "branch": "sloped_roof",
        "diagonal_connect": "void_notch",
        "terrace_link": "offset_twin_bar",
        "sloped_roof": "offset_twin_bar",
    }.get(family, "courtyard_atrium")
    return {
        "name": f"llm_coverage_repair_{family}_{index:03d}",
        "label": f"coverage repair {family}",
        "typology": family,
        "architectural_language": f"{family} coverage repair from required LLM family contract",
        "reference_basis": "fallback formal-principle coverage, not precedent copy",
        "formal_principle": MASS_LANGUAGE_BY_FAMILY.get(family, family),
        "dominant_gesture": f"{family}_dominant_gesture",
        "generator_mode": GENERATOR_MODE_BY_FAMILY.get(family, "hybrid"),
        "mass_language": MASS_LANGUAGE_BY_FAMILY.get(family, family),
        "primary_language": MASS_LANGUAGE_BY_FAMILY.get(family, family),
        "secondary_language": secondary_language,
        "topology_intent": f"{family} source topology with explicit authored MassDSL parameters",
        "primitive_intent": f"{family} primitives validated through ARR source geometry compiler",
        "intent_tags": [family, "coverage_repair", "legal_solver_validated"],
        "rule_name": f"{family}_coverage_rule",
        "rule_inputs": authored_keys,
        "expected_geometry_actions": [
            f"compile {family} MassDSL verbs into source volumes",
            "clip source volumes inside legal envelope",
            "reject if FAR/BCR/height/parking checks fail",
        ],
        "calls": calls,
        "rationale": "Added because the structured LLM population omitted this required family; still compiled and validated by ARR legal solver.",
    }


def _coverage_repair_population(target_count: int, *, start_index: int = 0) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    index = start_index
    while len(records) < max(0, target_count):
        family = REQUIRED_COVERAGE_FAMILIES[index % len(REQUIRED_COVERAGE_FAMILIES)]
        cycle = index // len(REQUIRED_COVERAGE_FAMILIES)
        record = _coverage_repair_record(family, index + 1)
        record["name"] = f"{record['name']}_{cycle:02d}"
        record["label"] = f"{record['label']} {cycle + 1}"
        record["architectural_language"] = (
            f"{record['architectural_language']}; timeout coverage cycle {cycle + 1}"
        )
        record["intent_tags"] = [*record["intent_tags"], "timeout_coverage_repair"]
        records.append(record)
        index += 1
    return records


def _ensure_family_coverage(data: dict[str, Any]) -> None:
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        return
    present: set[str] = set()
    for record in candidates:
        if not isinstance(record, dict):
            continue
        family = str(record.get("typology") or record.get("family") or "")
        family = TYPOLOGY_FAMILY_ALIASES.get(family, family)
        language = str(record.get("mass_language") or record.get("primary_language") or "")
        for required in REQUIRED_COVERAGE_FAMILIES:
            if family == required or language == MASS_LANGUAGE_BY_FAMILY.get(required):
                present.add(required)
    # Prefer actual LLM-authored diversity. Deterministic coverage records are a
    # last-resort guard for sparse/failed LLM populations, not a normal source
    # of architectural variety.
    if len(candidates) >= 40 and len(present) >= 12:
        return
    missing = [family for family in REQUIRED_COVERAGE_FAMILIES if family not in present]
    repairs = [_coverage_repair_record(family, len(candidates) + index + 1) for index, family in enumerate(missing)]
    for record in repairs:
        record["intent_tags"] = [*record["intent_tags"], "coverage_family_repair"]
    data["candidates"] = [*candidates, *repairs]


def _schema(
    min_candidates: int = 120,
    *,
    min_palette: int = 30,
    min_rules: int = 10,
) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["language_palette", "combination_rules", "candidates"],
        "properties": {
            "language_palette": {
                "type": "array",
                "minItems": min_palette,
                "items": {"type": "string"},
            },
            "combination_rules": {
                "type": "array",
                "minItems": min_rules,
                "items": {"type": "string"},
            },
            "candidates": {
                "type": "array",
                "minItems": min_candidates,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "name",
                        "label",
                        "typology",
                        "architectural_language",
                        "reference_basis",
                        "formal_principle",
                        "dominant_gesture",
                        "generator_mode",
                        "mass_language",
                        "primary_language",
                        "secondary_language",
                        "topology_intent",
                        "primitive_intent",
                        "intent_tags",
                        "rule_name",
                        "rule_inputs",
                        "expected_geometry_actions",
                        "calls",
                        "rationale",
                    ],
                    "properties": {
                        "name": {"type": "string"},
                        "label": {"type": "string"},
                        "typology": {"type": "string"},
                        "architectural_language": {"type": "string"},
                        "reference_basis": {"type": "string"},
                        "formal_principle": {"type": "string"},
                        "dominant_gesture": {"type": "string"},
                        "generator_mode": {"type": "string", "enum": ["additive", "subtractive", "hybrid", "sectional"]},
                        "mass_language": {"type": "string"},
                        "primary_language": {"type": "string"},
                        "secondary_language": {"type": "string"},
                        "topology_intent": {"type": "string"},
                        "primitive_intent": {"type": "string"},
                        "intent_tags": {"type": "array", "items": {"type": "string"}},
                        "rule_name": {"type": "string"},
                        "rule_inputs": {"type": "array", "items": {"type": "string"}},
                        "expected_geometry_actions": {"type": "array", "items": {"type": "string"}},
                        "rationale": {"type": "string"},
                        "calls": {
                            "type": "array",
                            "minItems": 4,
                            "maxItems": 6,
                            "items": _call_node_schema(),
                        },
                    },
                },
            },
        },
    }


def _batch_family_focus(batch_index: int | str, target_count: int) -> tuple[str, ...]:
    raw_index = str(batch_index).split(".", 1)[0]
    try:
        index = max(1, int(raw_index))
    except ValueError:
        index = 1
    focus = BATCH_FAMILY_FOCUS[(index - 1) % len(BATCH_FAMILY_FOCUS)]
    return focus[: max(1, min(len(focus), int(target_count)))]


def _batch_focus_payload(batch_index: int | str, target_count: int) -> dict[str, Any]:
    focus = _batch_family_focus(batch_index, target_count)
    return {
        "families": list(focus),
        "generator_modes": [GENERATOR_MODE_BY_FAMILY.get(family, "hybrid") for family in focus],
        "mass_languages": [MASS_LANGUAGE_BY_FAMILY.get(family, family) for family in focus],
    }


def _prompt(
    site_context: dict[str, Any],
    target_count: int,
    *,
    batch_index: int = 1,
    generation_feedback: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    verbs = ", ".join(sorted(SUPPORTED_VERBS))
    required_params = "; ".join(
        f"{verb}: {', '.join(params)}"
        for verb, params in sorted(REQUIRED_PARAMS_BY_VERB.items())
    )
    batch_focus = _batch_focus_payload(batch_index, target_count)
    system = (
        "You are a rigorous architectural massing planner. Emit only MassDSL "
        "proposal JSON that follows the schema. You propose design language; "
        "a deterministic legal solver will validate, clip, or reject every candidate. "
        "Do not rely on compiler defaults for design-critical geometry parameters."
    )
    feedback_text = ""
    if generation_feedback:
        feedback_text = (
            "\nVLM generation feedback from the previous MAAS pass:\n"
            f"{json.dumps(_feedback_prompt_payload(generation_feedback), ensure_ascii=False, sort_keys=True)}\n"
            "This feedback is mandatory: generate new MassDSL candidates, not a rerank of the previous 20. "
            "Use must_use, quota, formal_principle_targets, reference_precedent_targets, and reference_language_briefs as positive design pressure, "
            "and treat avoid terms as rejection risks. Translate reference_precedent_targets into executable massing operations: "
            "Vancouver House/BIG-like torqued_stack or undercut tower must become pinch/taper/offset/bend/branch geometry; "
            "OMA/Seattle/Qatar-like stacked_platform or folded_section must become split/overlap/diagonal_connect/sloped_roof geometry; "
            "Mountain Dwellings/8 House-like terrace_ribbon must become terrace_link/grade/lift geometry. "
            "For torqued_stack or undercut_tapered_tower candidates, author strong but legal-source parameters: "
            "angle between 24 and 38 degrees, distance_ratio or shift_ratio between 0.18 and 0.32, "
            "upper_ratio between 0.72 and 0.88, and lower_floor_fraction between 0.28 and 0.48. "
            "For stacked_platform candidates, use overlap or split with 4 to 5 visible source tiers/roles where possible. "
            "Do not merely write reference names in labels; the MassDSL calls must express the reference-backed massing principle. "
            "For each reference_language_brief, preserve primary_operation as the first non-base call so the compiler materializes the intended family. "
            "When required_language_groups or language_group_repair is present, satisfy it with the executable primary graph operation and formal principle, "
            "not with labels, typology names, or rationale text. Folded candidates need a real sloped_roof_mass/folded section; stepped candidates need an "
            "occupiable stack, terrace_link, or grade sequence whose plates carry capacity. "
        )
    user = (
        "Generate a broad MAAS massing population for early architectural review.\n"
        "The goal is architecture-grade geometric massing, not just legal boxes. "
        "Read site_geometry_intelligence as mandatory design evidence: select an explicit dominant-axis response, "
        "a boundary/concavity response, and an access/open-space response for every proposal. "
        "Use the user's architecture book/reference principles and precedent principles without copying exact buildings: "
        "Trimage-like slender tower/podium order; Vancouver House/BIG-like undercut, taper, torque, and strong silhouette transition; "
        "OMA/Seattle Central Library-like stacked platforms, shifted volumes, and diagrammatic section. "
        "Each candidate needs one dominant geometric gesture and one compatible secondary gesture. "
        "Avoid random fragments and avoid legal-envelope stacks unless transformed into a clear architectural idea.\n"
        f"Batch index: {batch_index}.\n"
        f"Target candidate count for this batch: at least {target_count}.\n"
        f"Required batch family focus JSON: {json.dumps(batch_focus, ensure_ascii=True, sort_keys=True)}.\n"
        "For this batch, use each focused family at most once before any repeat. "
        "If target_count equals the number of focused families, every candidate must use a different focused family. "
        "Do not repeat mass_language, primary_language, formal_principle, or dominant role pattern inside this batch. "
        "Do not emit more than one undercut_tapered_tower, stacked_shifted_platforms, or simple slab stack in this batch. "
        "If a focused family is sectional, make the sectional move legible through diagonal_connect, terrace_link, or sloped_roof_mass rather than a stair-step envelope. "
        f"Supported verbs: {verbs}.\n"
        "Every candidate must start with one root/base node, contain exactly one primary node, and contain 4 to 6 graph nodes total. "
        "Every later operation must be support, void, or connector; never label a second operation as primary. "
        "Every call is a graph node: provide a unique node_id, "
        "an earlier parent_node_id (empty only for root), an architectural role, and a typed relation. Branch voids, "
        "bridges, and supports from their actual host instead of describing a flat operation chain. At least half the batch must contain "
        "two non-root nodes that share the same parent. For bend candidates, include lane_count 2-3, occupiable half-width "
        "lane_width_ratio 0.075-0.22, vertical_overlap 0.16-0.30, "
        "vertical_mode exactly terraced or grounded, curvature -0.18 to 0.18, "
        "field_topology exactly parallel or branched, branch_point_ratio 0.22-0.58, and an intentional variable-width profile using "
        "width_start_ratio 0.45-1.35, width_mid_ratio 0.65-1.55, width_end_ratio 0.45-1.35, and width_wave -0.28 to 0.28. "
        "Author one continuous roof-section profile with height_start_ratio 0.40-1.00, height_mid_ratio 0.50-1.00, "
        "height_end_ratio 0.40-1.00, and height_wave -0.24 to 0.24; this is a section field, not decorative facade variation. "
        "Include 4 to 6 normalized control_points such as [[0.04,0.25],[0.32,0.62],[0.68,0.38],[0.96,0.72]]; vary these from the site and brief. "
        "Across a 20-or-more candidate population, author at least two bend candidates: at least one parallel field and at least one branched field. "
        "They must differ in topology and section profile, not merely direction, reflection, labels, or control-point order. "
        "For every sloped_roof_mass candidate, author 4 to 6 ordered normalized control_points [[section_position,height], ...], "
        "and choose section_interpolation='smooth' for a continuous roof or 'linear' for an intentionally faceted fold. "
        "plus axis x/y, field_samples 5-9, longitudinal_wave -0.24 to 0.24, and twist -0.30 to 0.30. "
        "These points are the executable building section lofted through parcel cross-sections; do not describe a named roof preset. "
        "Folded candidates must differ by their authored section topology (ridge, valley, alternating fold, asymmetric canopy, etc.), "
        "not only by x_ratio/y_ratio or orientation. "
        "Author oblique-envelope candidates as a primary taper with formal_principle undercut_tapered_tower. "
        "Supply required x_ratio and y_ratio plus 3 to 8 perimeter-ordered normalized plan_control_points, for example "
        "[[0.08,0.12],[0.88,0.08],[0.94,0.78],[0.52,0.96],[0.10,0.82]]. This must be a real non-self-crossing "
        "plan polygon with area, never a left-to-right section polyline. Supply matching scalar top_height_controls such as "
        "[0.55,1.0,0.92,0.70,0.58], never [u,height] pairs, plus shoulder_fraction, "
        "base_scale_x_ratio/base_scale_y_ratio, base_shift_x_ratio/base_shift_y_ratio, "
        "top_scale_x_ratio/top_scale_y_ratio, and top_shift_x_ratio/top_shift_y_ratio. "
        "These parameters define bottom, shoulder, and top polygon rings of one continuous mass: use them for a wedge monolith, "
        "leaning or cantilevered envelope, diagonal undercut, or shifted polygon plate. Do not attach a decorative diagonal box, "
        "copy a precedent outline, or satisfy this instruction with x_ratio/y_ratio alone. "
        "For a public courtyard facing the supplied access edge, set courtyard open_side to south/north/east/west; use closed only when an enclosed atrium is intentional. "
        "Prefer creative combinations of "
        "plan, section, void, connector, array, offset, stack, and roof language. "
        "Typed roles are executable constraints: void may use only cave/courtyard/embed/nest/notch/pinch; connector may use only "
        "diagonal_connect/interlock/overlap/terrace_link; support may use bar/grade/inset/lift/offset/reflect/shift/sloped_roof_mass/stack/taper/terrace_link. "
        "Do not label lift, shift, reflect, or inset as a void, and do not label a generic shift as a connector. "
        "Distinguish arbitrary code-minimum stepback from an architectural stepped landform. In a 20-candidate set, author at least three "
        "capacity-bearing stepped or terraced sections whose floor plates remain usable and whose cascade is one dominant gesture. "
        "Avoid a simple cake-tier podium; transform stepped massing through a continuous terrace_link, grade, or stack rule plus a public void, courtyard, bridge, or inhabited roof. "
        "Prefer non-stair silhouettes: diagonal split blocks, bent bars, reflected pairs, caved courtyards, interlocked volumes, nested atria, and offset clusters. "
        "Use explicit typology language such as courtyard, cluster, bridge, bar_slab, "
        "interlock, bent, branch, roof_envelope, or void_carve. "
        "Across all batches the population must cover these source families; this batch should cover a different subset: "
        "courtyard, void_notch, split, diagonal_connect, terrace_link, array_cluster, offset, reflected_pair, "
        "slender_bar, bend, interlock, overlap, branch, pinch, embed, extrude, nest, sloped_roof. "
        "Do not collapse massing language into only additive/subtractive/hybrid/sectional buckets. "
        "Use specific mass_language values such as courtyard_atrium, notched_void, split_bridge, "
        "diagonal_connector, array_cluster, offset_twin_bar, reflected_court_pair, bar_notch_terrace, "
        "bend_ribbon, cross_interlock, overlap_slabs, branch_taper, pinched_waist, embedded_void, "
        "extruded_fin, nested_atrium_stack, sloped_roof, terrace_ribbon. "
        "Every candidate must declare primary_language and secondary_language. The two languages must be compatible and legible together, "
        "for example bar_notch_terrace + courtyard_atrium, split_bridge + diagonal_connector, "
        "offset_twin_bar + sloped_roof, bend_ribbon + overlap_slabs, or nested_atrium_stack + embedded_void. "
        "Do not combine unrelated gestures as random add-ons; secondary_language should modify the primary mass by void, roof, bridge, court, offset, or terrace logic. "
        "Do not use placeholder names; candidate names must describe the typology and primary verbs. "
        "Keep language_palette and combination_rules concise for this batch; do not repeat long explanations. "
        "For every non-base call, include all required canonical params; missing params cause rejection before legal review. "
        f"Required canonical params by verb: {required_params}. "
        "Axes must be x or y; do not use z-axis extrusion. "
        "For each candidate include rule_name, rule_inputs, and expected_geometry_actions that explain the architectural grammar. "
        "Also include reference_basis, formal_principle, and dominant_gesture. "
        "reference_basis should cite a book/reference category or precedent principle, not a copied building shape. "
        "formal_principle should use architectural language such as figure_ground, tower_base, carved_solid, slab_stack, datum_shift, torqued_taper, undercut_podium, split_bridge, or folded_section. "
        "dominant_gesture must name the large readable mass gesture, not a list of fragments. "
        "Encode the reference/formal principle inside architectural_language, primary_language, secondary_language, or rule_name using terms such as "
        "slender_podium_tower, undercut_tapered_tower, torqued_stack, stacked_shifted_platforms, folded_roof_volume, carved_atrium, split_bridge_connector. "
        "rule_inputs must cite authored parameter names, not prose only. "
        "Use candidate names that include the batch index and do not repeat prior obvious typologies. "
        "For every call, encode params as a compact JSON object string such as "
        "{\"axis\":\"x\",\"upper_ratio\":0.72}; use \"{}\" when no parameters are needed. "
        "Avoid making tiny demonstration masses; most candidates should use enough "
        "site capacity to be reviewable. Do not claim legal compliance.\n"
        f"{feedback_text}"
        f"Site/legal summary JSON:\n{json.dumps(site_context, ensure_ascii=False, sort_keys=True)}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _feedback_prompt_payload(feedback: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": feedback.get("schema_version"),
        "must_use": feedback.get("must_use") or [],
        "avoid": feedback.get("avoid") or [],
        "quota": feedback.get("quota") or {},
        "formal_principle_targets": feedback.get("formal_principle_targets") or [],
        "reference_precedent_targets": feedback.get("reference_precedent_targets") or [],
        "reference_language_briefs": feedback.get("reference_language_briefs") or [],
        "reference_signal_diagnosis": feedback.get("reference_signal_diagnosis") or {},
        "required_field_topologies": feedback.get("required_field_topologies") or {},
        "field_topology_repair": feedback.get("field_topology_repair") or {},
        "required_language_groups": feedback.get("required_language_groups") or {},
        "language_group_repair": feedback.get("language_group_repair") or {},
        "top_candidate_brief": (feedback.get("top_candidate_brief") or [])[:5],
        "bottom_candidate_brief": (feedback.get("bottom_candidate_brief") or [])[:5],
        "critic_actions": feedback.get("critic_actions") or {},
    }


def _extract_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    chunks: list[str] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict):
                text = content.get("text")
                if isinstance(text, str):
                    chunks.append(text)
    return "\n".join(chunks)


def _call_openai(
    messages: list[dict[str, str]],
    *,
    model: str,
    timeout: float,
    min_candidates: int,
    min_palette: int = 3,
    min_rules: int = 2,
    max_output_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LlmProposalError("OPENAI_API_KEY is not set")
    verbosity = os.getenv("MAAS_LLM_VERBOSITY")
    if not verbosity:
        verbosity = "low" if _supports_reasoning_effort(model) else "medium"
    body = {
        "model": model,
        "input": messages,
        "max_output_tokens": int(max_output_tokens or os.getenv("MAAS_LLM_MAX_OUTPUT_TOKENS", "12000")),
        "text": {
            "verbosity": verbosity,
            "format": {
                "type": "json_schema",
                "name": "maas_llm_massdsl_batch",
                "strict": True,
                "schema": _schema(
                    min_candidates,
                    min_palette=min_palette,
                    min_rules=min_rules,
                ),
            }
        },
    }
    if _supports_reasoning_effort(model):
        body["reasoning"] = {
            "effort": reasoning_effort or os.getenv("MAAS_LLM_REASONING_EFFORT", "medium"),
        }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")[:500]
        except Exception:
            detail = str(exc)
        raise LlmProposalError(f"OpenAI response failed: HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise LlmProposalError(f"OpenAI response failed: {exc}") from exc


def _record_to_sequence(record: dict[str, Any], index: int, *, prompt_hash: str, model: str) -> VerbSequence:
    raw_name = str(record.get("name") or f"candidate_{index:03d}")
    safe_name = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in raw_name.lower())
    if not safe_name.startswith("llm_"):
        safe_name = f"llm_{safe_name}"
    calls = []
    graph_specs: list[dict[str, str]] = []
    for call_index, item in enumerate(record.get("calls") or []):
        if not isinstance(item, dict):
            raise ValueError(f"{safe_name}: call {call_index} must be an object")
        verb = item.get("verb")
        if verb not in SUPPORTED_VERBS:
            raise ValueError(f"{safe_name}: unsupported verb {verb!r}")
        raw_params = item.get("params")
        if isinstance(raw_params, str):
            try:
                params = json.loads(raw_params)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{safe_name}: params for {verb!r} must be JSON object string") from exc
        else:
            params = raw_params if isinstance(raw_params, dict) else {}
        if not isinstance(params, dict):
            raise ValueError(f"{safe_name}: params for {verb!r} must decode to an object")
        params = _normalise_params(str(verb), params)
        _validate_call_params(safe_name, str(verb), params)
        clean_params = {}
        for key, value in dict(params).items():
            if value is None:
                continue
            if isinstance(value, list) and key not in {
                "offset_vec", "position", "control_points",
                "plan_control_points", "top_height_controls",
            }:
                continue
            if isinstance(value, dict):
                continue
            clean_params[key] = value
        calls.append(call(str(verb), **clean_params))
        graph_specs.append({
            "node_id": str(item.get("node_id") or ""),
            "parent_node_id": str(item.get("parent_node_id") or ""),
            "role": str(item.get("role") or ""),
            "relation": str(item.get("relation") or ""),
        })
    if not calls or calls[0].verb != "base":
        calls.insert(0, call("base", proportion="site"))
        graph_specs.insert(0, {"node_id": "root", "parent_node_id": "", "role": "root", "relation": "input"})
    sequence = VerbSequence(
        name=f"{safe_name}_{index:03d}",
        label=str(record.get("label") or safe_name),
        calls=tuple(calls),
        notes=(
            "proposal_source=openai_responses_structured_output",
            f"parameter_source={LLM_PARAMETER_SOURCE}",
            "requires_llm_authoring=false",
            f"prompt_hash={prompt_hash}",
            f"model={model}",
            f"architectural_language={record.get('architectural_language') or ''}",
            f"reference_basis={record.get('reference_basis') or ''}",
            f"formal_principle={record.get('formal_principle') or ''}",
            f"dominant_gesture={record.get('dominant_gesture') or ''}",
            f"generator_mode={record.get('generator_mode') or ''}",
            f"mass_language={record.get('mass_language') or ''}",
            f"primary_language={record.get('primary_language') or record.get('mass_language') or ''}",
            f"secondary_language={record.get('secondary_language') or ''}",
            f"topology_intent={record.get('topology_intent') or ''}",
            f"primitive_intent={record.get('primitive_intent') or ''}",
            f"typology={record.get('typology') or ''}",
            f"rule_name={record.get('rule_name') or ''}",
            f"rule_inputs={json.dumps(record.get('rule_inputs') or [], ensure_ascii=True, separators=(',', ':'))}",
            f"expected_geometry_actions={json.dumps(record.get('expected_geometry_actions') or [], ensure_ascii=True, separators=(',', ':'))}",
            str(record.get("rationale") or ""),
        ),
    )
    errors = sequence.validate()
    if errors:
        raise ValueError(f"{sequence.name}: {'; '.join(errors)}")
    # Old caches remain readable through the compatibility graph. New model
    # responses carry explicit topology and are embedded losslessly in the
    # sequence envelope used by older service boundaries.
    fallback = graph_from_sequence(sequence)
    explicit = bool(graph_specs) and all(spec.get("node_id") and spec.get("role") for spec in graph_specs)
    if not explicit:
        return fallback.to_sequence(name=sequence.name)
    nodes = []
    for call_index, operation in enumerate(sequence.calls):
        spec = graph_specs[call_index]
        role = spec["role"]
        if operation.verb not in ROLE_VERBS.get(role, set()):
            raise ValueError(
                f"{sequence.name}: role {role!r} cannot execute verb {operation.verb!r}"
            )
        relation = spec["relation"] or ("subtract" if role == "void" else "connect" if role == "connector" else "attach")
        if relation not in ROLE_RELATIONS.get(role, set()):
            raise ValueError(
                f"{sequence.name}: role {role!r} cannot use relation {relation!r}"
            )
        nodes.append(MassComponentNode(
            node_id=spec["node_id"],
            role=role,
            parent_id=spec["parent_node_id"] or None,
            optional=role in {"support", "connector"},
            operation=operation,
            constraints={"inside_legal_envelope": True, "author_graph_native": True},
            relation=relation,
        ))
    graph = MassComponentGraph(sequence.name, sequence.label, tuple(nodes), sequence.notes)
    graph_errors = graph.validate()
    if graph_errors:
        raise ValueError(f"{sequence.name}: invalid authored graph: {'; '.join(graph_errors)}")
    return graph.to_sequence(name=sequence.name)


def _validate_batch(
    data: dict[str, Any],
    *,
    min_candidates: int,
    min_palette: int = 30,
    min_rules: int = 10,
) -> None:
    palette = data.get("language_palette")
    rules = data.get("combination_rules")
    candidates = data.get("candidates")
    if not isinstance(palette, list) or len(palette) < min_palette:
        raise LlmProposalError(f"LLM proposal must include at least {min_palette} language_palette items")
    if not isinstance(rules, list) or len(rules) < min_rules:
        raise LlmProposalError(f"LLM proposal must include at least {min_rules} combination_rules")
    if not isinstance(candidates, list) or len(candidates) < min_candidates:
        raise LlmProposalError(f"LLM proposal must include at least {min_candidates} candidates")


def _field_topology_counts(data: dict[str, Any]) -> dict[str, int]:
    counts = {"parallel": 0, "branched": 0}
    for record in data.get("candidates") or []:
        if not isinstance(record, dict):
            continue
        calls = [item for item in record.get("calls") or [] if isinstance(item, dict)]
        primary = next((item for item in calls if item.get("role") == "primary"), None)
        if primary is None:
            primary = next((item for item in calls if item.get("verb") != "base"), None)
        for item in (primary,):
            if not isinstance(item, dict) or item.get("verb") != "bend":
                continue
            raw = item.get("params")
            if isinstance(raw, str):
                try:
                    params = json.loads(raw)
                except json.JSONDecodeError:
                    params = {}
            else:
                params = raw if isinstance(raw, dict) else {}
            topology = str(params.get("field_topology") or "parallel").strip().lower()
            topology = topology if topology in counts else "parallel"
            counts[topology] += 1
    return counts


def _record_language_group(record: dict[str, Any]) -> str:
    """Classify the executable primary operation, not the candidate label.

    The author prompt has always carried family quotas, but a prose label could
    satisfy the prompt while the primary graph node compiled to another form.
    This mirrors the downstream archive groups closely enough to decide whether
    a focused author repair batch is required before geometry search starts.
    """
    calls = [item for item in record.get("calls") or [] if isinstance(item, dict)]
    primary = next((item for item in calls if item.get("role") == "primary"), None)
    if primary is None:
        primary = next((item for item in calls if item.get("verb") != "base"), None)
    primary_verb = str((primary or {}).get("verb") or "").strip().lower()
    raw_params = (primary or {}).get("params")
    if isinstance(raw_params, str):
        try:
            primary_params = json.loads(raw_params)
        except json.JSONDecodeError:
            primary_params = {}
    else:
        primary_params = raw_params if isinstance(raw_params, dict) else {}
    principle = " ".join((
        str(record.get("formal_principle") or ""),
        str(record.get("mass_language") or ""),
        str(record.get("primary_language") or ""),
    )).strip().lower().replace("-", "_").replace(" ", "_")

    if primary_verb == "bend" or any(token in principle for token in ("continuous_field", "ribbon_field")):
        return "continuous_field"
    if primary_verb == "taper" and isinstance(primary_params.get("plan_control_points"), list):
        try:
            validated_primary_params = _normalise_params("taper", primary_params)
        except ValueError:
            validated_primary_params = {}
        if isinstance(validated_primary_params.get("plan_control_points"), list):
            return "oblique_envelope"
    if primary_verb == "sloped_roof_mass" or any(token in principle for token in ("folded_section", "folded_roof", "sloped_roof")):
        return "folded_section"
    if primary_verb in {"split", "diagonal_connect", "interlock"} or any(
        token in principle for token in ("split_bridge", "bridge_connector", "interlock")
    ):
        return "bridge_interlock"
    if primary_verb in {"array", "branch"}:
        return "cluster_field"
    if primary_verb in {"stack", "terrace_link", "grade"} or any(
        token in principle for token in ("stepped_landform", "stepped_capacity", "terraced_ribbon", "stacked_shifted_platform")
    ):
        return "stepped_capacity"
    if primary_verb in {"courtyard", "cave", "notch", "embed", "nest", "pinch"} or any(
        token in principle for token in ("carved_atrium", "carved_monolith", "carved_solid", "courtyard_atrium", "notched_void", "embedded_void")
    ):
        return "carved_void"
    return "calm_anchor"


def _language_group_counts(data: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in data.get("candidates") or []:
        if not isinstance(record, dict):
            continue
        group = _record_language_group(record)
        counts[group] = counts.get(group, 0) + 1
    return counts


def _missing_requested_language_groups(
    data: dict[str, Any],
    generation_feedback: dict[str, Any] | None,
) -> dict[str, int]:
    requested = (
        generation_feedback.get("required_language_groups")
        if isinstance(generation_feedback, dict)
        and isinstance(generation_feedback.get("required_language_groups"), dict)
        else {}
    )
    counts = _language_group_counts(data)
    return {
        str(group): int(required) - counts.get(str(group), 0)
        for group, required in requested.items()
        if isinstance(required, int | float)
        and counts.get(str(group), 0) < int(required)
    }


def _validate_requested_language_groups(
    data: dict[str, Any],
    generation_feedback: dict[str, Any] | None,
) -> None:
    missing = _missing_requested_language_groups(data, generation_feedback)
    if missing:
        raise LlmProposalError(
            "LLM author batch missed required executable language groups: "
            f"missing={missing}, counts={_language_group_counts(data)}"
        )


def _missing_requested_field_topologies(
    data: dict[str, Any],
    generation_feedback: dict[str, Any] | None,
) -> dict[str, int]:
    requested = (
        generation_feedback.get("required_field_topologies")
        if isinstance(generation_feedback, dict)
        and isinstance(generation_feedback.get("required_field_topologies"), dict)
        else {}
    )
    counts = _field_topology_counts(data)
    return {
        topology: int(required) - counts.get(topology, 0)
        for topology, required in requested.items()
        if topology in counts
        and isinstance(required, int | float)
        and counts.get(topology, 0) < int(required)
    }


def _validate_requested_field_topologies(
    data: dict[str, Any],
    generation_feedback: dict[str, Any] | None,
) -> None:
    missing = _missing_requested_field_topologies(data, generation_feedback)
    if missing:
        raise LlmProposalError(
            "LLM author batch missed required executable field topologies: "
            f"missing={missing}, counts={_field_topology_counts(data)}"
        )


def build_site_context(
    *,
    site_area_m2: float,
    building_type: str,
    limits: dict[str, Any],
    max_variants: int,
    site_polygon: Any | None = None,
    access_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from backend.app.modules.design.generation.maas.program_massing import program_search_prior, resolve_program_profile
    program = resolve_program_profile(building_type)
    return {
        "building_type": building_type,
        "site_area_m2": round(float(site_area_m2), 2),
        "max_variants": int(max_variants),
        "limits": {
            "far": limits.get("far"),
            "bcr": limits.get("bcr"),
            "height": limits.get("height"),
            "max_seed_floors": limits.get("max_seed_floors"),
        },
        "selection_goal": "creative architectural language first; deterministic law solver remains source of truth",
        "site_geometry_intelligence": _site_geometry_intelligence(
            site_polygon,
            access_context=access_context,
        ),
        "program_massing": {
            "profile_id": program["id"],
            "design_intent": program["design_intent"],
            "target_volume_range": program["target_volume_range"],
            "target_floor_range": program["target_floor_range"],
            "preferred_families": program["preferred_families"],
            "search_prior": program_search_prior(building_type),
        },
    }


def _site_geometry_intelligence(
    site_polygon: Any | None,
    *,
    access_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe the parcel in design terms without asking the LLM to do GIS.

    Coordinates remain in the deterministic geometry layer.  The language
    agent receives stable shape/axis/access facts and must choose a compatible
    formal strategy; the compiler then works in the same dominant-axis frame.
    """
    missing = {
        "schema_version": "arr.maas.site_geometry_intelligence.v1",
        "status": "geometry_not_supplied",
        "design_directives": [
            "do not claim parcel-specific alignment without site geometry",
        ],
    }
    if site_polygon is None or getattr(site_polygon, "is_empty", True):
        return missing
    try:
        hull = site_polygon.convex_hull
        rectangle = site_polygon.minimum_rotated_rectangle
        coords = list(rectangle.exterior.coords)
        edges = []
        for start, end in zip(coords, coords[1:]):
            dx = float(end[0] - start[0])
            dy = float(end[1] - start[1])
            edges.append(((dx * dx + dy * dy) ** 0.5, dx, dy))
        length, dx, dy = max(edges, key=lambda item: item[0])
        width = min(item[0] for item in edges if item[0] > 1e-8)
        axis = degrees(atan2(dy, dx))
        while axis >= 90.0:
            axis -= 180.0
        while axis < -90.0:
            axis += 180.0
        exterior = list(site_polygon.exterior.coords)[:-1]
        compactness = float(site_polygon.area) / max(float(rectangle.area), 1e-9)
        convexity = float(site_polygon.area) / max(float(hull.area), 1e-9)
        aspect = float(length) / max(float(width), 1e-9)
        directives = [
            "align or deliberately counterpoint the dominant parcel axis; record which choice is used",
            "keep primary mass and public/open-space figure legible against the actual boundary",
        ]
        if aspect >= 2.0:
            directives.append("test bar, ribbon, bridge, or terraced-section languages along the long axis")
        elif aspect <= 1.25:
            directives.append("test courtyard, carved-solid, cluster, or rotated-datum languages rather than one full-site slab")
        if convexity < 0.92:
            directives.append("use the concavity as court/entry/void logic; do not fill it with a bounding box")
        if len(exterior) >= 7:
            directives.append("simplify the dominant gesture; do not imitate every parcel edge as fragments")
        access = access_context if isinstance(access_context, dict) else {}
        return {
            "schema_version": "arr.maas.site_geometry_intelligence.v1",
            "status": "available",
            "dominant_axis_world_degrees": round(axis, 3),
            "oriented_aspect_ratio": round(aspect, 3),
            "oriented_length_m": round(float(length), 2),
            "oriented_width_m": round(float(width), 2),
            "rectangle_compactness": round(compactness, 3),
            "convexity_ratio": round(convexity, 3),
            "boundary_vertex_count": len(exterior),
            "is_concave": convexity < 0.995,
            "access_context": access,
            "design_directives": directives,
        }
    except Exception as exc:
        return {**missing, "status": "geometry_analysis_failed", "error": str(exc)[:160]}


def generate_llm_massdsl_batch(
    *,
    site_context: dict[str, Any],
    target_count: int = 120,
    model: str | None = None,
    timeout: float | None = None,
    batch_size: int | None = None,
    batch_retries: int | None = None,
    batch_workers: int | None = None,
    max_openai_batches: int | None = None,
    max_output_tokens: int | None = None,
    overgenerate_count: int | None = None,
    cache_path: str | Path | None = None,
    generation_feedback: dict[str, Any] | None = None,
    response_override: dict[str, Any] | None = None,
    allow_subbatch_recovery: bool = True,
    allow_deterministic_coverage_repair: bool = False,
) -> LlmProposalBatch:
    model = model or os.getenv("MAAS_LLM_MODEL") or DEFAULT_MODEL
    timeout = timeout if timeout is not None else _safe_float(os.getenv("MAAS_LLM_TIMEOUT"), 90.0)
    batch_size = max(3, min(40, int(batch_size or os.getenv("MAAS_LLM_BATCH_SIZE", "30"))))
    started = time.time()
    batch_errors: list[dict[str, Any]] = []
    cache_path_raw = str(cache_path or os.getenv("MAAS_LLM_BATCH_CACHE_PATH", "")).strip()
    resolved_cache_path = Path(cache_path_raw).expanduser() if cache_path_raw else None
    cache_hit = False
    if response_override is None and resolved_cache_path and resolved_cache_path.exists():
        try:
            cached = json.loads(resolved_cache_path.read_text(encoding="utf-8"))
            response_override = cached.get("data") if isinstance(cached.get("data"), dict) else cached
            cache_hit = isinstance(response_override, dict)
        except Exception:
            response_override = None
            cache_hit = False
    if response_override is None:
        merged: dict[str, Any] = {
            "language_palette": [],
            "combination_rules": [],
            "candidates": [],
        }
        raw_response = {"id": None, "batch_ids": []}
        resolved_overgenerate_count = (
            int(overgenerate_count)
            if overgenerate_count is not None
            else int(os.getenv("MAAS_LLM_OVERGENERATE_COUNT", "8"))
        )
        resolved_overgenerate_count = max(0, resolved_overgenerate_count)
        request_count = target_count + resolved_overgenerate_count
        batches = (request_count + batch_size - 1) // batch_size
        if max_openai_batches is None:
            raw_max_batches = os.getenv("MAAS_LLM_MAX_OPENAI_BATCHES")
            max_openai_batches = int(raw_max_batches) if raw_max_batches else batches
        batches = max(1, min(batches, int(max_openai_batches)))
        prompt_hashes: list[str] = []
        max_attempts = max(1, int(batch_retries or os.getenv("MAAS_LLM_BATCH_RETRIES", "3")))
        messages: list[dict[str, str]] = []
        batch_focuses: list[dict[str, Any]] = []

        def merge_batch_data(batch_data: dict[str, Any]) -> None:
            merged["language_palette"].extend(batch_data.get("language_palette") or [])
            merged["combination_rules"].extend(batch_data.get("combination_rules") or [])
            merged["candidates"].extend(batch_data.get("candidates") or [])

        def request_llm_batch(
            batch_label: int | str,
            count: int,
            attempts: int,
            feedback_override: dict[str, Any] | None = None,
        ) -> tuple[dict[str, Any] | None, Exception | None, dict[str, Any]]:
            batch_messages = _prompt(
                site_context,
                count,
                batch_index=batch_label,
                generation_feedback=feedback_override or generation_feedback,
            )
            metadata = {
                "prompt_hash": _stable_hash(batch_messages),
                "message_count": len(batch_messages),
                "focus": {
                    "batch_label": str(batch_label),
                    "target_count": count,
                    **_batch_focus_payload(batch_label, count),
                },
                "response_ids": [],
            }
            last_error: Exception | None = None
            for attempt in range(1, max(1, attempts) + 1):
                attempt_messages = batch_messages
                if attempt > 1:
                    attempt_messages = [
                        *batch_messages,
                        {
                            "role": "user",
                            "content": (
                                "The previous structured output for this batch was truncated or invalid JSON. "
                                "Retry the same batch with complete valid JSON only, no omissions."
                            ),
                        },
                    ]
                try:
                    response = _call_openai(
                        attempt_messages,
                        model=model,
                        timeout=timeout,
                        min_candidates=count,
                        min_palette=3,
                        min_rules=2,
                        max_output_tokens=max_output_tokens,
                        # Reasoning tokens can consume the complete output
                        # budget before strict JSON is emitted.  Preserve the
                        # normal effort on the first pass, then recover with a
                        # low-effort structured-output retry instead of a
                        # deterministic geometry fallback.
                        reasoning_effort="low" if attempt > 1 else None,
                    )
                except LlmProposalError as exc:
                    last_error = exc
                    continue
                response_id = response.get("id")
                if response_id:
                    metadata["response_ids"].append(response_id)
                raw_text = _extract_text(response)
                if not raw_text:
                    incomplete = response.get("incomplete_details")
                    usage = response.get("usage")
                    last_error = LlmProposalError(
                        "OpenAI response did not include output text for batch "
                        f"{batch_label}; status={response.get('status')!r}; "
                        f"incomplete_details={incomplete!r}; usage={usage!r}"
                    )
                    continue
                try:
                    parsed = json.loads(raw_text)
                    _validate_batch(parsed, min_candidates=count, min_palette=3, min_rules=2)
                    if feedback_override and feedback_override.get("field_topology_repair"):
                        _validate_requested_field_topologies(parsed, feedback_override)
                    if feedback_override and feedback_override.get("language_group_repair"):
                        _validate_requested_language_groups(parsed, feedback_override)
                    return parsed, None, metadata
                except (json.JSONDecodeError, LlmProposalError) as exc:
                    last_error = exc
                    continue
            return None, last_error, metadata

        batch_plan = [
            (batch_index, min(batch_size, max(0, request_count - (batch_index - 1) * batch_size)))
            for batch_index in range(1, batches + 1)
        ]
        batch_plan = [(label, count) for label, count in batch_plan if count > 0]
        worker_count = max(1, min(len(batch_plan), int(batch_workers or os.getenv("MAAS_LLM_BATCH_WORKERS", "1"))))
        batch_results: list[tuple[int, int, dict[str, Any] | None, Exception | None, dict[str, Any]]] = []
        if worker_count > 1:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(request_llm_batch, batch_index, count, max_attempts): (batch_index, count)
                    for batch_index, count in batch_plan
                }
                for future in as_completed(futures):
                    batch_index, count = futures[future]
                    batch_data, last_error, metadata = future.result()
                    batch_results.append((batch_index, count, batch_data, last_error, metadata))
        else:
            for batch_index, count in batch_plan:
                batch_data, last_error, metadata = request_llm_batch(batch_index, count, max_attempts)
                batch_results.append((batch_index, count, batch_data, last_error, metadata))

        for batch_index, count, batch_data, last_error, metadata in sorted(batch_results, key=lambda item: item[0]):
            prompt_hashes.append(str(metadata.get("prompt_hash") or ""))
            if metadata.get("focus"):
                batch_focuses.append(metadata["focus"])
            for response_id in metadata.get("response_ids") or []:
                raw_response["batch_ids"].append(response_id)
                raw_response["id"] = response_id
            if batch_data is None:
                recovered = 0
                if allow_subbatch_recovery:
                    sub_count = max(3, min(5, count // 2 or 3))
                    sub_index = 1
                    while recovered < count:
                        current_count = min(sub_count, count - recovered)
                        if current_count < 3 and recovered > 0:
                            break
                        sub_data, sub_error, sub_metadata = request_llm_batch(f"{batch_index}.{sub_index}", current_count, 1)
                        prompt_hashes.append(str(sub_metadata.get("prompt_hash") or ""))
                        if sub_metadata.get("focus"):
                            batch_focuses.append(sub_metadata["focus"])
                        for response_id in sub_metadata.get("response_ids") or []:
                            raw_response["batch_ids"].append(response_id)
                            raw_response["id"] = response_id
                        if sub_data is None:
                            last_error = sub_error or last_error
                            break
                        merge_batch_data(sub_data)
                        recovered += len(sub_data.get("candidates") or [])
                        sub_index += 1
                if recovered >= max(3, count // 2):
                    continue
                batch_errors.append({
                    "batch_index": batch_index,
                    "attempts": max_attempts,
                    "error": str(last_error),
                })
                continue
            merge_batch_data(batch_data)
        missing_field_topologies = _missing_requested_field_topologies(merged, generation_feedback)
        if missing_field_topologies:
            repair_feedback = dict(generation_feedback or {})
            repair_feedback["field_topology_repair"] = {
                "missing": missing_field_topologies,
                "instruction": (
                    "This supplemental batch is accepted only if every candidate uses bend as its sole primary node "
                    "with field_topology='branched'. Use one joined trunk and occupiable branches, not parallel bars; "
                    "branch may appear only as an optional support operation."
                ),
            }
            repair_feedback["required_field_topologies"] = {
                "parallel": 0,
                "branched": max(1, sum(missing_field_topologies.values())),
            }
            repair_count = max(3, sum(missing_field_topologies.values()) + 2)
            repair_data, repair_error, repair_metadata = request_llm_batch(
                "field-topology-repair",
                repair_count,
                max_attempts,
                feedback_override=repair_feedback,
            )
            prompt_hashes.append(str(repair_metadata.get("prompt_hash") or ""))
            for response_id in repair_metadata.get("response_ids") or []:
                raw_response["batch_ids"].append(response_id)
                raw_response["id"] = response_id
            if repair_data is not None:
                merge_batch_data(repair_data)
            else:
                batch_errors.append({
                    "batch_index": "field-topology-repair",
                    "attempts": max_attempts,
                    "error": str(repair_error),
                })
        _validate_requested_field_topologies(merged, generation_feedback)
        missing_language_groups = _missing_requested_language_groups(merged, generation_feedback)
        if missing_language_groups:
            repair_feedback = dict(generation_feedback or {})
            # Ask for a survival buffer because capacity, clean-mass and VLM
            # gates legitimately reject some authored graphs downstream.
            repair_feedback["language_group_repair"] = {
                "missing": missing_language_groups,
                "instruction": (
                    "This supplemental batch is accepted only when the executable primary graph nodes close the listed language deficits. "
                    "Use one dominant gesture, 1-3 clean legal solids, occupiable section depth and no decorative box attachments."
                ),
            }
            repair_feedback["required_language_groups"] = {
                group: max(1, int(deficit))
                for group, deficit in missing_language_groups.items()
            }
            repair_count = max(3, sum(repair_feedback["required_language_groups"].values()) + 2)
            repair_data, repair_error, repair_metadata = request_llm_batch(
                "language-group-repair",
                repair_count,
                max_attempts,
                feedback_override=repair_feedback,
            )
            prompt_hashes.append(str(repair_metadata.get("prompt_hash") or ""))
            if repair_metadata.get("focus"):
                batch_focuses.append(repair_metadata["focus"])
            for response_id in repair_metadata.get("response_ids") or []:
                raw_response["batch_ids"].append(response_id)
                raw_response["id"] = response_id
            if repair_data is not None:
                merge_batch_data(repair_data)
            else:
                batch_errors.append({
                    "batch_index": "language-group-repair",
                    "attempts": max_attempts,
                    "error": str(repair_error),
                })
        _validate_requested_language_groups(merged, generation_feedback)
        if len(merged["language_palette"]) < 30:
            needed_palette = 30 - len(merged["language_palette"])
            merged["language_palette"].extend([
                f"timeout coverage language {index + 1} {REQUIRED_COVERAGE_FAMILIES[index % len(REQUIRED_COVERAGE_FAMILIES)]}"
                for index in range(needed_palette)
            ])
        if len(merged["combination_rules"]) < 10:
            merged["combination_rules"].extend([
                "combine one plan operation with one section or void operation",
                "avoid repeating stepback as the primary language",
                "prefer reviewable BCR/FAR before legal solver clipping",
                "keep roof, bridge, courtyard, and array as separate families",
                "treat parking and legal envelope as hard post checks",
                "use asymmetric offsets to separate bars and courts",
                "use voids to produce inhabitable atria rather than decorative holes",
                "use connector verbs for sectionally legible masses",
                "use single-slab overlap before adding stacked towers",
                "reserve stack for nest, roof, and legal-envelope anchors",
            ])
        if allow_deterministic_coverage_repair and len(merged["candidates"]) < target_count:
            merged["candidates"].extend(
                _coverage_repair_population(
                    target_count - len(merged["candidates"]),
                    start_index=len(merged["candidates"]),
                )
            )
        data = merged
        prompt_hash = _stable_hash(prompt_hashes)
        if resolved_cache_path:
            try:
                resolved_cache_path.parent.mkdir(parents=True, exist_ok=True)
                resolved_cache_path.write_text(json.dumps({
                    "schema_version": "arr.maas.llm_massdsl_cache.v1",
                    "model": model,
                    "prompt_hash": prompt_hash,
                    "created_at_unix": int(time.time()),
                    "target_count": target_count,
                    "batch_size": batch_size,
                    "data": data,
                }, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
    else:
        request_count = target_count
        resolved_overgenerate_count = 0
        raw_response = {"id": "test-response-override"}
        data = response_override
        messages = _prompt(site_context, target_count, generation_feedback=generation_feedback)
        prompt_hash = _stable_hash(messages)
        batch_focuses = [_batch_focus_payload(1, target_count)]
    if not isinstance(data, dict):
        raise LlmProposalError("LLM proposal response must be a JSON object")
    _validate_requested_field_topologies(data, generation_feedback)
    _validate_requested_language_groups(data, generation_feedback)
    if allow_deterministic_coverage_repair:
        _ensure_family_coverage(data)
    _validate_batch(data, min_candidates=target_count)
    sequence_list: list[VerbSequence] = []
    rejected_records: list[str] = []
    for index, record in enumerate(data.get("candidates") or []):
        if not isinstance(record, dict):
            rejected_records.append(f"{index}:not_object")
            continue
        try:
            sequence_list.append(_record_to_sequence(record, index + 1, prompt_hash=prompt_hash, model=model))
        except ValueError as exc:
            rejected_records.append(str(exc))
    if len(sequence_list) < target_count and allow_deterministic_coverage_repair:
        repair_records = _coverage_repair_population(
            target_count - len(sequence_list),
            start_index=len(data.get("candidates") or []),
        )
        for repair_index, record in enumerate(repair_records, start=len(data.get("candidates") or []) + 1):
            try:
                sequence_list.append(_record_to_sequence(record, repair_index, prompt_hash=prompt_hash, model=model))
                data.setdefault("candidates", []).append(record)
            except ValueError as exc:
                rejected_records.append(str(exc))
    sequences = tuple(sequence_list)
    min_valid = max(10, int(target_count * 0.75)) if allow_deterministic_coverage_repair else target_count
    if len(sequences) < min_valid:
        raise LlmProposalError(f"only {len(sequences)} valid LLM sequences compiled; rejected={rejected_records[:5]}")
    artifact = {
        "schema_version": LLM_BATCH_SCHEMA_VERSION,
        "run_id": f"maas-llm-{int(started)}-{prompt_hash}",
        "model": model,
        "provider": "openai",
        "api": "responses",
        "prompt_hash": prompt_hash,
        "elapsed_ms": int((time.time() - started) * 1000),
        "target_count": target_count,
        "requested_candidate_count": request_count,
        "overgenerate_count": resolved_overgenerate_count,
        "batch_size": batch_size,
        "batch_retries": max_attempts if response_override is None else None,
        "max_output_tokens": int(max_output_tokens or os.getenv("MAAS_LLM_MAX_OUTPUT_TOKENS", "12000")),
        "raw_candidate_count": len(data.get("candidates") or []),
        "compiled_sequence_count": len(sequences),
        "rejected_sequence_count": len(rejected_records),
        "rejected_sequence_samples": rejected_records[:10],
        "openai_batch_error_count": len(batch_errors) if response_override is None else 0,
        "openai_batch_errors": batch_errors[:8] if response_override is None else [],
        "timeout_coverage_repair_count": sum(
            1
            for record in data.get("candidates") or []
            if isinstance(record, dict)
            and "timeout_coverage_repair" in (record.get("intent_tags") or [])
        ),
        "deterministic_coverage_repair_count": sum(
            1
            for record in data.get("candidates") or []
            if isinstance(record, dict)
            and any(
                tag in {"timeout_coverage_repair", "coverage_family_repair"}
                for tag in (record.get("intent_tags") or [])
            )
        ),
        "language_palette_count": len(data.get("language_palette") or []),
        "combination_rule_count": len(data.get("combination_rules") or []),
        "site_summary": site_context,
        "generation_feedback": _feedback_prompt_payload(generation_feedback) if generation_feedback else {},
        "authored_language_group_counts": _language_group_counts(data),
        "batch_family_focuses": batch_focuses[:40],
        "cache": {
            "enabled": bool(resolved_cache_path),
            "hit": cache_hit,
            "path": str(resolved_cache_path) if resolved_cache_path else "",
        },
        "transcript": {
            "request": {
                "model": model,
                "message_count": len(messages),
                "prompt_hash": prompt_hash,
                "schema_version": LLM_BATCH_SCHEMA_VERSION,
            },
            "response": {
                "id": raw_response.get("id"),
                "candidate_count": len(data.get("candidates") or []),
            },
        },
    }
    return LlmProposalBatch(artifact=artifact, sequences=sequences)


__all__ = [
    "LLM_BATCH_SCHEMA_VERSION",
    "LLM_PARAMETER_SOURCE",
    "LlmProposalBatch",
    "LlmProposalError",
    "build_site_context",
    "generate_llm_massdsl_batch",
]
