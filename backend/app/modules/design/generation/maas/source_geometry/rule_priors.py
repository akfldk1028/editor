"""Architectural rule priors for MAAS source-geometry compilation.

This registry makes the compiler's non-legal geometric priors explicit. These
values are source-geometry defaults and bounds only; FAR, BCR, height, setback,
and parking compliance remain enforced by the legal optimizer.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


RULE_PRIOR_SCHEMA_VERSION = "arr.maas.architectural_rule_priors.v1"
RULE_EVIDENCE_SCHEMA_VERSION = "arr.maas.rule_evidence.v1"

CANONICAL_RULE_FAMILIES = (
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
    "sloped_roof",
)


_COMMON_BOUNDS = {
    "upper_ratio": (0.52, 1.0),
    "bar_ratio": (0.12, 0.62),
    "depth_ratio": (0.08, 0.58),
    "side_ratio": (0.12, 0.68),
    "gap_ratio": (0.03, 0.42),
    "angle": (-55.0, 55.0),
    "lower_floor_fraction": (0.18, 0.78),
}

_RULE_RESEARCH_METADATA = {
    "courtyard": {
        "generator_mode": "subtractive",
        "mass_language": "courtyard_atrium",
        "primitive_types": ["perimeter_bar", "central_void"],
        "topology_tags": ["courtyard", "void", "perimeter_ring"],
        "quota_group": "subtractive",
    },
    "void_notch": {
        "generator_mode": "subtractive",
        "mass_language": "notched_void",
        "primitive_types": ["edge_notch", "liner_bar"],
        "topology_tags": ["notch", "void", "edge_carve"],
        "quota_group": "subtractive",
    },
    "split": {
        "generator_mode": "hybrid",
        "mass_language": "split_bridge",
        "primitive_types": ["split_wing", "bridge_bar"],
        "topology_tags": ["split", "bridge", "gap"],
        "quota_group": "hybrid",
    },
    "diagonal_connect": {
        "generator_mode": "sectional",
        "mass_language": "diagonal_connector",
        "primitive_types": ["offset_plate", "rotated_connector"],
        "topology_tags": ["diagonal", "connector", "section_link"],
        "quota_group": "sectional",
    },
    "array_cluster": {
        "generator_mode": "additive",
        "mass_language": "array_cluster",
        "primitive_types": ["repeated_cell", "staggered_cluster"],
        "topology_tags": ["array", "cluster", "cellular"],
        "quota_group": "additive",
    },
    "offset": {
        "generator_mode": "additive",
        "mass_language": "offset_twin_bar",
        "primitive_types": ["offset_unit", "bridge_spine"],
        "topology_tags": ["offset", "paired_blocks", "spine"],
        "quota_group": "additive",
    },
    "reflected_pair": {
        "generator_mode": "additive",
        "mass_language": "reflected_court_pair",
        "primitive_types": ["mirrored_unit", "bridge_spine"],
        "topology_tags": ["reflected_pair", "paired_blocks", "spine"],
        "quota_group": "additive",
    },
    "slender_bar": {
        "generator_mode": "additive",
        "mass_language": "bar_notch_terrace",
        "primitive_types": ["long_bar", "return_bar", "hinge_core"],
        "topology_tags": ["bar", "return", "hinge"],
        "quota_group": "additive",
    },
    "bend": {
        "generator_mode": "hybrid",
        "mass_language": "bend_ribbon",
        "primitive_types": ["rotated_bar", "return_bar", "hinge_core"],
        "topology_tags": ["bend", "ribbon", "hinge"],
        "quota_group": "hybrid",
    },
    "interlock": {
        "generator_mode": "hybrid",
        "mass_language": "cross_interlock",
        "primitive_types": ["cross_bar", "knuckle_core"],
        "topology_tags": ["interlock", "cross", "knuckle"],
        "quota_group": "hybrid",
    },
    "overlap": {
        "generator_mode": "hybrid",
        "mass_language": "overlap_slabs",
        "primitive_types": ["overlap_slab", "shared_core"],
        "topology_tags": ["overlap", "slab", "shared_core"],
        "quota_group": "hybrid",
    },
    "branch": {
        "generator_mode": "hybrid",
        "mass_language": "branch_taper",
        "primitive_types": ["trunk", "branch_arm"],
        "topology_tags": ["branch", "trunk", "arms"],
        "quota_group": "hybrid",
    },
    "pinch": {
        "generator_mode": "subtractive",
        "mass_language": "pinched_waist",
        "primitive_types": ["lobe", "waist_bridge"],
        "topology_tags": ["pinch", "waist", "lobes"],
        "quota_group": "subtractive",
    },
    "embed": {
        "generator_mode": "subtractive",
        "mass_language": "embedded_void",
        "primitive_types": ["embedded_void", "host_liner"],
        "topology_tags": ["embed", "void", "host_shell"],
        "quota_group": "subtractive",
    },
    "extrude": {
        "generator_mode": "additive",
        "mass_language": "extruded_fin",
        "primitive_types": ["core", "fin", "head"],
        "topology_tags": ["extrude", "fin", "head"],
        "quota_group": "additive",
    },
    "nest": {
        "generator_mode": "subtractive",
        "mass_language": "nested_atrium_stack",
        "primitive_types": ["outer_shell", "inner_volume", "liner_spine"],
        "topology_tags": ["nest", "inner_volume", "shell"],
        "quota_group": "subtractive",
    },
    "sloped_roof": {
        "generator_mode": "sectional",
        "mass_language": "sloped_roof",
        "primitive_types": ["roof_plinth", "sloped_plane"],
        "topology_tags": ["sloped_roof", "section_plane", "roof"],
        "quota_group": "sectional",
    },
    "terrace_link": {
        "generator_mode": "sectional",
        "mass_language": "terrace_ribbon",
        "primitive_types": ["terrace_plate", "section_link"],
        "topology_tags": ["terrace", "ribbon", "section_link"],
        "quota_group": "sectional",
    },
}


def _rule(
    family: str,
    *,
    required_inputs: tuple[str, ...],
    optional_inputs: tuple[str, ...],
    prior_defaults: dict[str, float],
    bounds: dict[str, tuple[float, float]] | None,
    height_band_profile: dict[str, float],
    geometry_actions: tuple[str, ...],
    rationale: str,
) -> dict[str, Any]:
    merged_bounds = dict(_COMMON_BOUNDS)
    if bounds:
        merged_bounds.update(bounds)
    metadata = _RULE_RESEARCH_METADATA.get(family, {})
    return {
        "schema_version": RULE_PRIOR_SCHEMA_VERSION,
        "rule_name": f"architectural_rule:{family}",
        "family": family,
        "generator_mode": metadata.get("generator_mode", "generic"),
        "mass_language": metadata.get("mass_language", family),
        "primitive_types": list(metadata.get("primitive_types", [])),
        "topology_tags": list(metadata.get("topology_tags", [])),
        "quota_group": metadata.get("quota_group", "generic"),
        "required_inputs": list(required_inputs),
        "optional_inputs": list(optional_inputs),
        "prior_defaults": prior_defaults,
        "bounds": {key: list(value) for key, value in merged_bounds.items()},
        "height_band_profile": height_band_profile,
        "geometry_actions": list(geometry_actions),
        "rationale": rationale,
    }


ARCHITECTURAL_RULE_PRIORS: dict[str, dict[str, Any]] = {
    "courtyard": _rule(
        "courtyard",
        required_inputs=("ratio",),
        optional_inputs=("upper_ratio", "lower_floor_fraction"),
        prior_defaults={"upper_ratio": 0.82, "ratio": 0.24, "court_ratio": 0.24},
        bounds={"ratio": (0.12, 0.54), "court_ratio": (0.12, 0.54)},
        height_band_profile={"lower_split": 0.45, "low_band": 0.25, "high_band": 1.0},
        geometry_actions=("subtract_central_court", "decompose_into_perimeter_bars", "stagger_bar_heights"),
        rationale="Courtyard massing is represented as perimeter bars around an authored void ratio.",
    ),
    "void_notch": _rule(
        "void_notch",
        required_inputs=("side_or_corner", "depth_ratio"),
        optional_inputs=("upper_ratio", "width_ratio", "lower_floor_fraction"),
        prior_defaults={"upper_ratio": 0.82, "cut_ratio": 0.32, "depth_ratio": 0.28, "side_ratio": 0.34},
        bounds={"cut_ratio": (0.12, 0.58), "depth_ratio": (0.08, 0.58), "side_ratio": (0.12, 0.68)},
        height_band_profile={"lower_split": 0.45, "liner_band": 0.75, "raised_band": 1.0},
        geometry_actions=("cut_edge_or_corner_void", "retain_main_bar", "add_side_lip_and_liner"),
        rationale="Void/notch massing starts from an authored subtraction and exposes remaining lips as separate volumes.",
    ),
    "split": _rule(
        "split",
        required_inputs=("axis", "gap_ratio", "bridge_ratio"),
        optional_inputs=("upper_ratio", "distance_ratio", "lower_floor_fraction"),
        prior_defaults={"upper_ratio": 0.82, "gap_ratio": 0.14, "depth_ratio": 0.24, "bridge_ratio": 0.24},
        bounds={"gap_ratio": (0.03, 0.42), "bridge_ratio": (0.06, 0.30), "depth_ratio": (0.08, 0.58)},
        height_band_profile={"lower_split": 0.42, "wing_band": 0.80, "bridge_band": 1.0},
        geometry_actions=("split_into_two_wings", "reserve_gap", "add_bridge_bar"),
        rationale="Split massing separates wings and treats connector geometry as a bridge volume.",
    ),
    "diagonal_connect": _rule(
        "diagonal_connect",
        required_inputs=("axis", "distance_ratio", "angle"),
        optional_inputs=("upper_ratio", "depth_ratio", "lower_floor_fraction"),
        prior_defaults={"upper_ratio": 0.82, "gap_ratio": 0.14, "depth_ratio": 0.24, "angle": 24.0},
        bounds={"angle": (-55.0, 55.0), "depth_ratio": (0.08, 0.58)},
        height_band_profile={"lower_split": 0.40, "connector_band": 1.0},
        geometry_actions=("offset_lower_and_upper_plates", "rotate_connector_bar", "clip_to_source_footprint"),
        rationale="Diagonal connection is authored as two plates plus a rotated connector rather than a stair stack.",
    ),
    "array_cluster": _rule(
        "array_cluster",
        required_inputs=("n", "axis", "spacing_ratio", "unit_scale"),
        optional_inputs=("hierarchy_ratio", "stagger_ratio", "lower_floor_fraction"),
        prior_defaults={
            "upper_ratio": 0.82,
            "count": 3.0,
            "unit": 0.46,
            "spacing": 0.26,
            "hierarchy_ratio": 0.18,
            "stagger_ratio": 0.12,
        },
        bounds={
            "count": (3.0, 4.0),
            "unit": (0.36, 0.58),
            "spacing": (0.18, 0.38),
            "hierarchy_ratio": (0.08, 0.36),
            "stagger_ratio": (0.04, 0.28),
        },
        height_band_profile={"lower_split": 0.36, "alternating_band": 0.75, "cap_band": 1.0},
        geometry_actions=(
            "instantiate_cluster_cells",
            "author_component_hierarchy",
            "stagger_around_shared_open_space",
            "vary_cell_height_bands",
        ),
        rationale="Array cluster massing uses three or four related but unequal program pieces around shared open space, never uniform detached copies.",
    ),
    "offset": _rule(
        "offset",
        required_inputs=("axis", "distance_ratio", "other_scale"),
        optional_inputs=("upper_ratio", "lower_floor_fraction"),
        prior_defaults={"upper_ratio": 0.86, "gap_ratio": 0.18, "side_ratio": 0.34, "unit": 0.34},
        bounds={"gap_ratio": (0.04, 0.34), "side_ratio": (0.18, 0.58), "unit": (0.18, 0.58)},
        height_band_profile={"lower_split": 0.42, "shifted_band": 0.85, "spine_band": 1.0},
        geometry_actions=("place_offset_units", "add_bridge_spine", "add_shared_core"),
        rationale="Offset massing keeps separated units legible while adding a connector volume only as source geometry.",
    ),
    "reflected_pair": _rule(
        "reflected_pair",
        required_inputs=("axis", "gap_ratio", "unit_scale"),
        optional_inputs=("upper_ratio", "lower_floor_fraction"),
        prior_defaults={"upper_ratio": 0.86, "gap_ratio": 0.18, "side_ratio": 0.34, "unit": 0.34},
        bounds={"gap_ratio": (0.04, 0.34), "side_ratio": (0.18, 0.58), "unit": (0.18, 0.58)},
        height_band_profile={"lower_split": 0.44, "pair_band": 0.85, "spine_band": 1.0},
        geometry_actions=("mirror_two_units", "hold_center_gap", "add_bridge_spine"),
        rationale="Reflected-pair massing records mirrored units and shared spine as separate roles.",
    ),
    "slender_bar": _rule(
        "slender_bar",
        required_inputs=("axis", "factor"),
        optional_inputs=("shift", "upper_ratio", "lower_floor_fraction"),
        prior_defaults={"upper_ratio": 0.82, "bar_ratio": 0.30, "side_ratio": 0.34},
        bounds={"bar_ratio": (0.12, 0.62), "side_ratio": (0.12, 0.68)},
        height_band_profile={"lower_split": 0.60, "return_band": 0.75, "core_band": 1.0},
        geometry_actions=("make_long_bar", "add_return_bar", "mark_hinge_core"),
        rationale="Slender bar massing uses bar and return roles so it does not collapse into a two-tier block.",
    ),
    "bend": _rule(
        "bend",
        required_inputs=("axis", "angle", "factor"),
        optional_inputs=("upper_ratio", "lower_floor_fraction"),
        prior_defaults={"upper_ratio": 0.82, "bar_ratio": 0.30, "side_ratio": 0.34, "angle": 24.0},
        bounds={"angle": (-55.0, 55.0), "bar_ratio": (0.12, 0.62), "side_ratio": (0.12, 0.68)},
        height_band_profile={"lower_split": 0.44, "return_band": 0.75, "hinge_band": 1.0},
        geometry_actions=("rotate_primary_bar", "rotate_return_bar", "add_hinge_core"),
        rationale="Bend massing expresses rotation and hinge, not just a narrowed rectangle.",
    ),
    "interlock": _rule(
        "interlock",
        required_inputs=("angle", "bar_ratio"),
        optional_inputs=("upper_ratio", "distance_ratio", "lower_floor_fraction"),
        prior_defaults={"upper_ratio": 0.82, "bar_ratio": 0.30, "side_ratio": 0.34, "angle": 24.0},
        bounds={"angle": (-55.0, 55.0), "bar_ratio": (0.12, 0.62), "side_ratio": (0.12, 0.68)},
        height_band_profile={"lower_split": 0.46, "cross_band": 0.75, "knuckle_band": 1.0},
        geometry_actions=("cross_two_bars", "rotate_interlocking_axes", "add_knuckle_core"),
        rationale="Interlock massing records crossed volumes and a knuckle instead of a single overlap patch.",
    ),
    "overlap": _rule(
        "overlap",
        required_inputs=("axis", "slab_ratio", "shift_ratio"),
        optional_inputs=("upper_ratio", "lower_floor_fraction"),
        prior_defaults={"upper_ratio": 0.82, "bar_ratio": 0.30, "gap_ratio": 0.14, "side_ratio": 0.34},
        bounds={"bar_ratio": (0.12, 0.46), "gap_ratio": (0.03, 0.30), "side_ratio": (0.12, 0.68)},
        height_band_profile={"lower_split": 0.44, "overlap_band": 1.0},
        geometry_actions=("create_low_slab", "create_shifted_high_slab", "add_shared_core"),
        rationale="Overlap massing keeps two slabs and their shared core separately measurable.",
    ),
    "branch": _rule(
        "branch",
        required_inputs=("angle", "trunk_ratio", "arm_ratio"),
        optional_inputs=("upper_ratio", "lower_floor_fraction"),
        prior_defaults={"upper_ratio": 0.82, "side_ratio": 0.30, "bar_ratio": 0.24, "angle": 24.0},
        bounds={"side_ratio": (0.08, 0.46), "bar_ratio": (0.06, 0.42), "angle": (-55.0, 55.0)},
        height_band_profile={"lower_split": 0.46, "arm_band": 0.90},
        geometry_actions=("make_trunk", "add_left_arm", "add_right_arm"),
        rationale="Branch massing decomposes trunk and arms to preserve authored branching language.",
    ),
    "pinch": _rule(
        "pinch",
        required_inputs=("axis", "waist_ratio", "depth_ratio"),
        optional_inputs=("upper_ratio", "lower_floor_fraction"),
        prior_defaults={"upper_ratio": 0.82, "waist_ratio": 0.58, "depth_ratio": 0.24},
        bounds={"waist_ratio": (0.28, 0.84), "depth_ratio": (0.08, 0.58)},
        height_band_profile={"lower_split": 0.50, "lobe_band": 0.80, "waist_band": 1.0},
        geometry_actions=("separate_two_lobes", "preserve_waist_bridge", "stagger_lobe_heights"),
        rationale="Pinch massing is represented as lobes plus waist bridge, not as uniform scaling.",
    ),
    "embed": _rule(
        "embed",
        required_inputs=("guest_scale", "position"),
        optional_inputs=("upper_ratio", "distance_ratio", "lower_floor_fraction"),
        prior_defaults={"upper_ratio": 0.82, "cut_ratio": 0.32, "side_ratio": 0.34, "depth_ratio": 0.28},
        bounds={"cut_ratio": (0.12, 0.58), "side_ratio": (0.12, 0.68), "depth_ratio": (0.08, 0.58)},
        height_band_profile={"lower_split": 0.38, "liner_band": 0.75, "raised_band": 1.0},
        geometry_actions=("subtract_embedded_guest", "add_main_bar", "add_liner_volume"),
        rationale="Embed massing treats inserted void/guest scale as the authored driver and exposes host remainder.",
    ),
    "extrude": _rule(
        "extrude",
        required_inputs=("axis", "length", "size"),
        optional_inputs=("upper_ratio", "lower_floor_fraction"),
        prior_defaults={"upper_ratio": 0.82, "length": 0.36, "side_ratio": 0.34, "depth_ratio": 0.24},
        bounds={"length": (0.12, 0.70), "side_ratio": (0.12, 0.68), "depth_ratio": (0.08, 0.58)},
        height_band_profile={"lower_split": 0.34, "fin_band": 0.90, "head_band": 1.0},
        geometry_actions=("keep_core", "extrude_fin", "terminate_with_head"),
        rationale="Extrude massing records core, fin, and head so extrusion reads in rendered geometry.",
    ),
    "nest": _rule(
        "nest",
        required_inputs=("inner_scale",),
        optional_inputs=("upper_ratio", "levels", "lower_floor_fraction"),
        prior_defaults={"upper_ratio": 0.82, "inner": 0.42, "side_ratio": 0.34},
        bounds={"inner": (0.18, 0.62), "side_ratio": (0.12, 0.68)},
        height_band_profile={"lower_split": 0.42, "inner_band": 0.85, "liner_band": 1.0},
        geometry_actions=("make_outer_shell", "place_inner_volume", "add_liner_spine"),
        rationale="Nested massing separates outer shell, inner volume, and liner spine for visible depth.",
    ),
    "sloped_roof": _rule(
        "sloped_roof",
        required_inputs=("upper_ratio", "x_ratio_or_y_ratio"),
        optional_inputs=("axis", "lower_floor_fraction"),
        prior_defaults={"upper_ratio": 0.82, "ridge_ratio": 0.42},
        bounds={"ridge_ratio": (0.16, 0.72), "upper_ratio": (0.52, 1.0)},
        height_band_profile={"lower_split": 0.56, "low_plane": 0.82, "high_plane": 1.0},
        geometry_actions=("keep_roof_plinth", "split_low_roof_plane", "split_high_roof_plane"),
        rationale="Sloped roof massing is encoded as sectional planes rather than flat stepbacks.",
    ),
}


def get_rule_prior(family: str | None) -> dict[str, Any] | None:
    """Return a deep-copied rule prior for a canonical family."""
    if not family:
        return None
    prior = ARCHITECTURAL_RULE_PRIORS.get(str(family))
    return deepcopy(prior) if prior else None


def rule_default(rule: dict[str, Any] | None, key: str, fallback: float) -> float:
    defaults = rule.get("prior_defaults") if isinstance(rule, dict) else None
    if isinstance(defaults, dict) and key in defaults:
        try:
            return float(defaults[key])
        except (TypeError, ValueError):
            return float(fallback)
    return float(fallback)


def rule_bounds(rule: dict[str, Any] | None, key: str, fallback: tuple[float, float]) -> tuple[float, float]:
    bounds = rule.get("bounds") if isinstance(rule, dict) else None
    value = bounds.get(key) if isinstance(bounds, dict) else None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return fallback
    return fallback


def init_rule_evidence(
    family: str | None,
    *,
    sequence_name: str,
    sequence_source: str,
    language_params: dict[str, Any] | None,
) -> dict[str, Any]:
    rule = get_rule_prior(family)
    authored_keys = sorted(str(key) for key in (language_params or {}).keys())
    return {
        "schema_version": RULE_EVIDENCE_SCHEMA_VERSION,
        "prior_schema_version": RULE_PRIOR_SCHEMA_VERSION,
        "sequence_name": sequence_name,
        "sequence_source": sequence_source,
        "family": family,
        "rule_name": rule.get("rule_name") if rule else f"architectural_rule:{family or 'unknown'}:unregistered",
        "generator_mode": rule.get("generator_mode") if rule else "generic",
        "mass_language": rule.get("mass_language") if rule else str(family or "generic"),
        "quota_group": rule.get("quota_group") if rule else "generic",
        "primitive_types": rule.get("primitive_types", []) if rule else [],
        "topology_tags": rule.get("topology_tags", []) if rule else [],
        "required_inputs": rule.get("required_inputs", []) if rule else [],
        "optional_inputs": rule.get("optional_inputs", []) if rule else [],
        "geometry_actions": rule.get("geometry_actions", []) if rule else ["compile_source_geometry", "clip_to_legal_envelope"],
        "height_band_profile": rule.get("height_band_profile", {}) if rule else {},
        "rationale": rule.get("rationale") if rule else "No named architectural prior is registered; compiler may only validate generic source geometry.",
        "llm_authored_keys": authored_keys,
        "llm_authored_params": [],
        "rule_prior_params": [],
        "invalid_params": [],
        "source_volume_roles": [],
        "research_diversity_descriptor": {},
    }


def _evidence_relevant_keys(evidence: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    aliases = {
        "side_or_corner": {"side", "corner", "face", "width_ratio", "depth_ratio"},
        "x_ratio_or_y_ratio": {"x_ratio", "y_ratio", "ridge_ratio", "factor"},
        "depth_ratio": {"depth_ratio", "depth", "bridge_ratio", "cut_ratio"},
        "gap_ratio": {"gap_ratio", "gap", "distance_ratio", "distance"},
        "distance_ratio": {"distance_ratio", "distance", "gap_ratio"},
        "unit_scale": {"unit_scale", "unit", "size", "side_ratio"},
        "inner_scale": {"inner_scale", "inner", "guest_scale", "ratio"},
        "guest_scale": {"guest_scale", "cut_ratio", "side_ratio", "ratio"},
        "slab_ratio": {"slab_ratio", "bar_ratio", "factor"},
        "shift_ratio": {"shift_ratio", "gap_ratio", "distance_ratio"},
        "trunk_ratio": {"trunk_ratio", "side_ratio"},
        "arm_ratio": {"arm_ratio", "bar_ratio"},
        "ratio": {"ratio", "court_ratio", "guest_scale"},
        "n": {"n", "count"},
        "spacing_ratio": {"spacing_ratio", "spacing"},
        "size": {"size", "side_ratio"},
    }
    for key in list(evidence.get("required_inputs") or []) + list(evidence.get("optional_inputs") or []):
        token = str(key)
        keys.add(token)
        keys.update(aliases.get(token, set()))
    return keys


def _filter_param_records(records: Any, relevant_keys: set[str]) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        return []
    filtered = []
    for record in records:
        if not isinstance(record, dict):
            continue
        key = str(record.get("key") or "")
        alias_key = str(record.get("alias_key") or "")
        if key in relevant_keys or alias_key in relevant_keys:
            filtered.append(record)
    return filtered


def finalize_rule_evidence(evidence: dict[str, Any], volume_roles: list[str]) -> dict[str, Any]:
    authored = evidence.get("llm_authored_params")
    priors = evidence.get("rule_prior_params")
    invalid = evidence.get("invalid_params")
    relevant_keys = _evidence_relevant_keys(evidence)
    effective_authored = _filter_param_records(authored, relevant_keys)
    effective_priors = _filter_param_records(priors, relevant_keys)
    authored_count = len(effective_authored)
    prior_count = len(effective_priors)
    invalid_count = len(invalid) if isinstance(invalid, list) else 0
    total = authored_count + prior_count
    evidence["effective_llm_authored_params"] = effective_authored
    evidence["effective_rule_prior_params"] = effective_priors
    evidence["llm_authored_param_count"] = authored_count
    evidence["rule_prior_param_count"] = prior_count
    evidence["invalid_rule_param_count"] = invalid_count
    evidence["rule_prior_param_ratio"] = round(prior_count / total, 4) if total else 0.0
    evidence["source_volume_roles"] = list(volume_roles)
    role_tokens = {
        token
        for role in volume_roles
        for token in str(role).replace("-", "_").split("_")
        if token
    }
    topology_tags = sorted(set(evidence.get("topology_tags") or []) | role_tokens)
    evidence["topology_tags"] = topology_tags
    evidence["research_diversity_descriptor"] = {
        "schema_version": "arr.maas.research_diversity_descriptor.v1",
        "generator_mode": evidence.get("generator_mode") or "generic",
        "mass_language": evidence.get("mass_language") or evidence.get("family") or "generic",
        "quota_group": evidence.get("quota_group") or "generic",
        "primitive_types": list(evidence.get("primitive_types") or []),
        "topology_tags": topology_tags,
        "volume_count": len(volume_roles),
        "role_pattern": "|".join(str(role) for role in volume_roles),
        "rectilinear_template": len(volume_roles) == 3 and not any(
            tag in topology_tags
            for tag in {"array", "courtyard", "sloped", "diagonal", "interlock", "branch"}
        ),
    }
    return evidence
