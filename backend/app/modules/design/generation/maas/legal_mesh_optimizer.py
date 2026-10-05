"""Legal MAAS variant generator for ARR mass GeoJSON.

Take one candidate mass, expand/mutate it with deterministic MAAS morphology
operators, then repair and rank the results by legal FAR/BCR utilization and
diversity. The hard rule is simple: never return a variant that fails the
available ARR legal constraints.
"""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import copy
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, box, mapping, shape
from shapely.affinity import rotate as shapely_rotate, scale as shapely_scale, translate as shapely_translate
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.diversity import diversity_score, polygon_iou, sequence_distance, sequence_diversity_score, sequence_verbs, shape_signature
from backend.app.modules.design.generation.maas.design_quality import attach_design_quality_evidence
from backend.app.modules.design.generation.maas.capacity_policy import resolve_massing_capacity_policy as _massing_capacity_policy
from backend.app.modules.design.generation.maas.candidate_pipeline import build_bounded_review_pool
from backend.app.modules.design.generation.maas.generation_trace import GenerationTrace
from backend.app.modules.design.generation.maas.parking_stage import parking_repair_budget
from backend.app.modules.design.generation.maas.agents import build_agent_review_a2ui_messages, build_agent_reviews
from backend.app.modules.design.generation.maas.agents.grammar_critic_agent import build_grammar_review
from backend.app.modules.design.generation.maas.agents.llm_architect_agent import LLMArchitectAgent
from backend.app.modules.design.generation.maas.agents.massdsl_agent import build_massdsl_proposal
from backend.app.modules.design.generation.maas.floor_groups import build_floor_groups
from backend.app.modules.design.generation.maas.final_floorwise_legal import revalidate_final_floorwise_feature
from backend.app.modules.design.generation.maas.geometry_language.floorwise_visual_projection import clip_and_certify_projected_piloti_visual
from backend.app.modules.design.generation.maas.evolution import evolve_massdsl_islands, run_critic_geometry_loop
from backend.app.modules.design.generation.maas.evolution.island_loop import sequence_from_variant
from backend.app.modules.design.generation.maas.grammar import VerbCall, VerbSequence, generate_grammar_variants, get_sequence_label
from backend.app.modules.design.generation.maas.grammar.component_graph import graph_from_sequence
from backend.app.modules.design.generation.maas.grammar.legal_interpreter import interpret_sequence
from backend.app.modules.design.generation.maas.legal_envelope import FloorPlateStack, build_floor_plate_stack, build_legal_envelope, failed_constraint_metrics
from backend.app.modules.design.generation.maas.agent_revision import build_agent_revision_trace
from backend.app.modules.design.generation.maas.llm_proposals import LLM_BATCH_SCHEMA_VERSION, LLM_PARAMETER_SOURCE, LlmProposalError, build_site_context
from backend.app.modules.design.generation.maas.morphology_operators import largest_polygon
from backend.app.modules.design.generation.maas.mass_brain import record_shadow_outcomes, request_shadow_variants
from backend.app.modules.design.generation.maas.paper_alignment import attach_paper_alignment_and_preference_evidence
from backend.app.modules.design.generation.maas.parking_requirements import apply_parking_requirement_to_props, load_parking_requirement_rules, resolve_candidate_parking_requirement
from backend.app.modules.design.generation.maas.parking_strategy import attach_parking_strategy
from backend.app.modules.design.generation.maas.performance_objectives import early_massing_performance_proxy
from backend.app.modules.design.generation.maas.preference import PreferenceLoopCallbacks, apply_preference_loop, preference_loop_config as build_preference_loop_config, preference_score, preference_vlm_scored
from backend.app.modules.design.generation.maas.program_massing import attach_program_massing_evidence
from backend.app.modules.design.generation.maas.research_backends import d4descent_design_evidence
from backend.app.modules.design.generation.maas.source_geometry import SourceVolume, evaluate_source_volume_coherence
from backend.app.modules.design.generation.maas.source_geometry.ir import SourceSurface
from backend.app.modules.design.generation.maas.seed_library import generate_seed_variants, seed_library_metadata
from backend.app.modules.design.generation.maas.selection.integer_projection import ProjectionDescriptor, solve_final_integer_projection
from backend.app.modules.design.generation.maas.selection.visual_similarity import visual_precedent_signature
from backend.app.modules.design.generation.maas.selection import BalancedSelectionDeps, FinalReviewRefinementCallbacks, FinalMetricCallbacks, FormalDiversityCallbacks, IslandQuotaCallbacks, RecoveryRefinementCallbacks, ReviewSetConstraintCallbacks, SelectionState, enforce_formal_diversity_replacements, enforce_island_quota_replacements, enforce_initial_recovery_replacements, final_hard_quotas_ok_after as selection_final_hard_quotas_ok_after, final_metric_snapshot as selection_final_metric_snapshot, final_metrics_ok_after as selection_final_metrics_ok_after, final_structural_quotas_ok_after as selection_final_structural_quotas_ok_after, final_mass_stage_parking_pass, final_design_balanced_selection as selection_final_design_balanced_selection, height_bucket, layout_status, PreferenceGuardCallbacks, enforce_final_direct_llm_minimum, enforce_final_vlm_preference_minimum, refine_final_review_set, recover_final_vlm_review_metrics, review_set_constraints_ok as selection_review_set_constraints_ok, review_set_geometry_ok as selection_review_set_geometry_ok, source_reviewable as selection_source_reviewable, unique_family_count_after as selection_unique_family_count_after
from backend.app.modules.design.generation.services.mass_evaluator import get_floor_height
from backend.app.modules.design.generation.services.repair_operator import repair_design
from backend.app.modules.design.generation.services.site_geometry import geojson_to_polygon, utm_to_wgs84, wgs84_to_utm


def _operator_family(operator: str) -> str:
    operator = operator.split("__sweep_", 1)[0]
    if operator.endswith("_layered"):
        operator = operator[:-8]
    if operator == "legal_layered_max":
        return "legal_layered"
    if operator.startswith("legal_buildable"):
        return "legal_buildable"
    if operator.startswith("bcr_fill"):
        return "bcr_fill"
    if operator.startswith("notch") or operator.startswith("court_open"):
        return "void_notch"
    if operator.startswith("slender_bar"):
        return "slender_bar"
    if operator.startswith("split_bridge"):
        return "split"
    if operator.startswith("branch_y"):
        return "branch"
    if operator.startswith("pinch_waist"):
        return "pinch"
    if operator.startswith("interlock_cross"):
        return "interlock"
    if operator.startswith("overlap_slabs"):
        return "overlap"
    if operator.startswith("parking_repair_diagonal_connector"):
        return "diagonal_connect"
    if operator.startswith("parking_repair_terrace_ribbon"):
        return "terrace_link"
    if operator.startswith("parking_repair_sloped_roof"):
        return "sloped_roof"
    if operator.startswith("parking_repair_split_bridge"):
        return "split"
    if operator.startswith("parking_repair_tapered_slab"):
        return "taper"
    if operator.startswith("parking_repair_single_bar"):
        return "slender_bar"
    if operator.startswith("parking_repair_grammar_split"):
        return "split"
    if operator.startswith("parking_repair_grammar_bar"):
        return "slender_bar"
    if operator.startswith("parking_repair_grammar_podium") or operator.startswith("parking_repair_grammar_sunlight"):
        return "stepback_tower"
    if operator.startswith("parking_repair_grammar_diagonal"):
        return "diagonal_connect"
    if operator.startswith("parking_repair_grammar_terrace") or operator.startswith("parking_repair_grammar_overlap_shift_terrace"):
        return "terrace_link"
    if operator.startswith("parking_repair_grammar_sloped"):
        return "sloped_roof"
    if operator.startswith("diagonal_connect"):
        return "diagonal_connect"
    if operator.startswith("terrace_link"):
        return "terrace_link"
    if operator.startswith("sloped_roof"):
        return "sloped_roof"
    if operator in {"courtyard_void"}:
        return "courtyard"
    if operator.startswith("tapered"):
        return "taper"
    if operator.startswith("grade_terrace"):
        return "grade"
    if operator in {"terrace_stepback", "shifted_tower", "lift_overlap_slabs"}:
        return "stepback_tower"
    if operator == "grammar_sunlight_multi_step":
        return "stepback_tower"
    if operator == "grammar_courtyard_lift_taper":
        return "courtyard"
    if operator == "grammar_split_lift_stepback":
        return "split"
    if operator == "grammar_bar_notch_grade":
        return "grade"
    if operator == "grammar_overlap_shift_terrace":
        return "overlap"
    if operator == "grammar_branch_pinch_taper":
        return "branch"
    if operator == "grammar_podium_tower_offset":
        return "stepback_tower"
    if operator == "grammar_cave_inset_puncture":
        return "void_notch"
    if operator == "grammar_interlock_step_taper":
        return "interlock"
    if operator == "grammar_diagonal_step_connector":
        return "diagonal_connect"
    if operator == "grammar_terrace_ribbon_stepback":
        return "terrace_link"
    if operator == "grammar_sloped_roof_envelope":
        return "sloped_roof"
    if operator.startswith("grammar_bend"):
        return "bend"
    if operator.startswith("grammar_embed"):
        return "embed"
    if operator.startswith("grammar_extrude"):
        return "extrude"
    if operator.startswith("grammar_nest"):
        return "nest"
    if operator.startswith("grammar_"):
        return operator
    if operator.startswith("inset"):
        return "inset"
    return operator


CONCEPT_ORDER = [
    "legal_layered",
    "void_notch",
    "courtyard",
    "slender_bar",
    "offset",
    "array_cluster",
    "reflected_pair",
    "split",
    "branch",
    "pinch",
    "interlock",
    "overlap",
    "diagonal_connect",
    "terrace_link",
    "sloped_roof",
    "stepback_tower",
    "taper",
    "grade",
    "bend",
    "embed",
    "extrude",
    "nest",
    "inset",
    "bcr_fill",
    "legal_buildable",
]

SECTION_CONCEPTS = {"stepback_tower", "taper", "grade", "diagonal_connect", "terrace_link", "sloped_roof"}
MIN_GRAMMAR_CONCEPTS = 3
MIN_SECTION_DESIGN_CONCEPTS = 4
SECTION_CONNECTOR_VERBS = {"diagonal_connect", "terrace_link", "sloped_roof_mass"}
SECTION_PROFILE_KINDS = {
    "sloped_roof",
    "terrace_ribbon",
    "diagonal_connector",
    "diagonal_connect",
    "array_cluster",
    "offset_twin_bar",
    "reflected_court_pair",
    "cross_interlock",
    "split_bridge",
    "courtyard_atrium",
    "branch_taper",
    "overlap_slabs",
    "bar_notch_terrace",
    "notched_void",
    "pinched_waist",
    "stepped_tower",
    "bend_ribbon",
    "embedded_void",
    "extruded_fin",
    "nested_stack",
}
SECTION_CONNECTOR_SHAPE_TOKENS = (
    "diagonal_connect",
    "terrace_link",
    "sloped_roof",
    "step_connector",
    "ribbon_stepback",
)
RESEARCH_TARGET_FAMILIES = (
    "array_cluster",
    "offset",
    "reflected_pair",
    "slender_bar",
    "bend",
    "embed",
    "extrude",
    "nest",
    "diagonal_connect",
    "terrace_link",
)
SIGNATURE_PROPOSAL_PRIORITIES = {
    "agent_big_terrace_cascade": 4,
    "agent_vancouver_torque_stack": 4,
    "agent_oma_diagonal_plate": 3,
    "agent_trimaje_slender_pair": 3,
}
STEPBACK_DOMINANT_FAMILIES = {"stepback_tower", "terrace_link", "grade", "taper"}
TYPOLOGY_REVIEW_QUOTAS = (
    (("courtyard", "void_notch"), 2),
    (("array_cluster", "offset", "reflected_pair"), 2),
    (("split", "diagonal_connect"), 2),
    (("slender_bar", "bend", "interlock", "overlap"), 4),
    (("branch", "pinch", "embed", "extrude", "nest"), 2),
    (("sloped_roof",), 1),
)
TYPOLOGY_FIRST_FAMILIES = [
    "legal_layered",
    "interlock",
    "overlap",
    "split",
    "courtyard",
    "void_notch",
    "slender_bar",
    "branch",
    "pinch",
    "offset",
    "array_cluster",
    "reflected_pair",
    "stepback_tower",
    "terrace_link",
    "diagonal_connect",
    "sloped_roof",
    "bend",
    "embed",
    "extrude",
    "nest",
    "taper",
    "grade",
    "inset",
    "legal_buildable",
]

# Review-sheet policy, not candidate-specific filtering. These values gate the
# public 20-card architectural review surface; legal truth remains owned by the
# legal/parking solvers.
ARCHITECTURAL_ORDER_POLICY = {
    "min_orderliness_score": 0.74,
    "min_main_mass_area_ratio": 0.30,
    "max_source_surfaces": 28,
    "max_small_fragments": 1,
    "max_fragment_roles": 0,
    "max_visible_volumes": 4,
    "max_plan_components": 2,
    # A clean rectangular or podium/tower anchor may legitimately be only two
    # volumes.  Requiring three here was manufacturing a decorative fragment
    # solely to pass the review gate.
    "min_visible_volumes": 2,
    "min_review_bcr_pct": 8.0,
    "min_review_far_pct": 12.0,
    "min_review_far_utilization": 0.70,
}

def _feature_min_far_utilization(feature: dict[str, Any]) -> float:
    props = feature.get("properties") or {}
    capacity_policy = props.get("massing_capacity_policy") if isinstance(props.get("massing_capacity_policy"), dict) else {}
    return float(capacity_policy.get("min_far_utilization", ARCHITECTURAL_ORDER_POLICY["min_review_far_utilization"]))

CONCEPT_LABELS = {
    "legal_layered": "법규엔벨로프",
    "legal_buildable": "최대건폐",
    "bcr_fill": "건폐확장",
    "void_notch": "코너/오픈코트",
    "courtyard": "중정형",
    "slender_bar": "바형",
    "offset": "오프셋 동",
    "array_cluster": "군집 배열",
    "reflected_pair": "대칭 쌍동",
    "split": "분절/브릿지",
    "branch": "브랜치형",
    "pinch": "핀치형",
    "interlock": "인터락",
    "overlap": "오버랩",
    "diagonal_connect": "사선연결",
    "terrace_link": "테라스연결",
    "sloped_roof": "사선지붕형",
    "bend": "벤드형",
    "embed": "임베드형",
    "extrude": "익스트루드형",
    "nest": "네스트형",
    "stepback_tower": "포디움/타워",
    "taper": "테이퍼",
    "grade": "테라스",
    "inset": "인셋",
}


def _concept_label(operator: str) -> str:
    sequence_key = operator[:-8] if operator.endswith("_layered") else operator
    sequence_label = get_sequence_label(sequence_key)
    if sequence_label:
        return sequence_label
    return CONCEPT_LABELS.get(_operator_family(operator), _operator_family(operator))


def _is_section_connector(feature: dict[str, Any]) -> bool:
    props = feature.get("properties", {}) or {}
    mass_shape = str(props.get("mass_shape") or "")
    if any(token in mass_shape for token in SECTION_CONNECTOR_SHAPE_TOKENS):
        return True
    sequence = props.get("maas_verb_sequence")
    if not isinstance(sequence, list):
        model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
        sequence = model.get("verb_sequence")
    if not isinstance(sequence, list):
        return False
    return any(
        isinstance(call, dict) and call.get("verb") in SECTION_CONNECTOR_VERBS
        for call in sequence
    )


def _is_parking_repair_operator(operator: str) -> bool:
    return operator.startswith("parking_repair_")


def _is_typology_first_candidate(feature: dict[str, Any]) -> bool:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    operator = str(props.get("mass_shape") or "")
    if _is_parking_repair_operator(operator):
        return False
    if operator.startswith(("agent_", "llm_")):
        return _source_family(feature) in set(TYPOLOGY_FIRST_FAMILIES)
    return _operator_family(operator) in set(TYPOLOGY_FIRST_FAMILIES)


def _polygon_min_dimension(poly) -> float:
    try:
        minx, miny, maxx, maxy = poly.bounds
        return float(min(maxx - minx, maxy - miny))
    except Exception:
        return 0.0


def _upper_typology_is_viable(footprint_utm, upper_footprint_utm) -> bool:
    if upper_footprint_utm is None or upper_footprint_utm.is_empty:
        return False
    lower_area = float(getattr(footprint_utm, "area", 0.0) or 0.0)
    upper_area = float(getattr(upper_footprint_utm, "area", 0.0) or 0.0)
    if lower_area <= 0.0:
        return False
    if upper_area < max(8.0, lower_area * 0.12):
        return False
    if _polygon_min_dimension(upper_footprint_utm) < 3.0:
        return False
    return True


def _feature_plan_min_dimension(feature: dict[str, Any]) -> float:
    try:
        geom = wgs84_to_utm(geojson_to_polygon(feature.get("geometry")))
        return _polygon_min_dimension(geom)
    except Exception:
        return 0.0


def _feature_height_to_min_dimension(feature: dict[str, Any]) -> float:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    height = float(props.get("height") or 0.0)
    min_dim = _feature_plan_min_dimension(feature)
    if min_dim <= 0.0:
        return 999.0
    return height / min_dim


def _is_reviewable_architectural_mass(feature: dict[str, Any]) -> bool:
    """Gate the 20-card review sheet to real massing candidates.

    Parking-repair slivers and very thin towers are still useful diagnostic
    evidence, but they should not be presented as architectural mass options.
    """
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    operator = str(props.get("mass_shape") or "")
    if _is_parking_repair_operator(operator):
        return False
    precheck = props.get("parking_precheck") if isinstance(props.get("parking_precheck"), dict) else {}
    layout = precheck.get("layout_candidate") if isinstance(precheck.get("layout_candidate"), dict) else {}
    if layout.get("status") == "fail":
        return False
    far = float(props.get("far") or 0.0)
    far_utilization = float(props.get("far_utilization") or 0.0)
    bcr = float(props.get("bcr") or 0.0)
    shape = str(props.get("mass_shape") or "")
    if shape.startswith(("agent_", "llm_")) and (far < 20.0 or bcr < 8.0):
        return False
    if far_utilization and far_utilization < _feature_min_far_utilization(feature):
        return False
    if _is_agent_authored_candidate(feature) and _has_review_source_geometry(feature):
        min_dimension_limit = 1.5
        height_ratio_limit = 12.0
    else:
        min_dimension_limit = 3.0 if _has_review_source_geometry(feature) else 4.2
        height_ratio_limit = 8.0 if _has_review_source_geometry(feature) else 6.2
    if _feature_plan_min_dimension(feature) < min_dimension_limit:
        return False
    if _feature_height_to_min_dimension(feature) > height_ratio_limit:
        return False
    return True


def _is_plain_capacity_anchor(feature: dict[str, Any]) -> bool:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    family = _operator_family(str(props.get("mass_shape") or ""))
    return family in {"bcr_fill", "legal_buildable"}


def _is_clean_layered_anchor(feature: dict[str, Any]) -> bool:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    shape = str(props.get("mass_shape") or "")
    family = _source_family(feature) or _operator_family(shape)
    if shape == "legal_layered_max":
        return True
    return family == "stepback_tower" and shape in {
        "grammar_sunlight_multi_step_layered",
        "grammar_sunlight_multi_step",
        "terrace_stepback",
    }


def _is_plain_review_mass(feature: dict[str, Any]) -> bool:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    shape = str(props.get("mass_shape") or "")
    if shape == "legal_layered_max" or _is_grammar_candidate(feature):
        return False
    materialized = props.get("section_profile_materialized")
    if isinstance(materialized, dict) and materialized.get("design_synthesis"):
        return False
    if _is_section_connector(feature):
        return False
    return _visible_volume_count(feature) <= 1


def _is_grammar_candidate(feature: dict[str, Any]) -> bool:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    return str(props.get("mass_shape") or "").startswith("grammar_")


def _is_agent_authored_candidate(feature: dict[str, Any]) -> bool:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    return str(props.get("mass_shape") or "").startswith(("agent_", "llm_"))


def _is_llm_authored_candidate(feature: dict[str, Any]) -> bool:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    return str(props.get("mass_shape") or "").startswith("llm_")


def _is_llm_coverage_repair_candidate(feature: dict[str, Any]) -> bool:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    shape = str(props.get("mass_shape") or "").lower()
    return shape.startswith("llm_") and "coverage_repair" in shape


def _is_direct_openai_llm_candidate(feature: dict[str, Any]) -> bool:
    return _is_llm_authored_candidate(feature) and not _is_llm_coverage_repair_candidate(feature)


def _is_authored_mass_candidate(feature: dict[str, Any]) -> bool:
    return _is_grammar_candidate(feature) or _is_agent_authored_candidate(feature)


def _visible_volume_count(feature: dict[str, Any]) -> int:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    volumes = props.get("mass_volumes")
    if isinstance(volumes, list):
        return len(volumes)
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    model_volumes = model.get("volumes")
    return len(model_volumes) if isinstance(model_volumes, list) else 0


def _design_synthesis_rank(feature: dict[str, Any]) -> int:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    materialized = props.get("section_profile_materialized")
    if isinstance(materialized, dict) and materialized.get("design_synthesis"):
        return 3
    if _is_section_connector(feature):
        return 2
    family = _operator_family(str(props.get("mass_shape") or ""))
    if family in SECTION_CONCEPTS:
        return 1
    return 0


def _design_review_quality_key(feature: dict[str, Any]) -> tuple[float, ...]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    signature = _source_signature(feature)
    coherence = signature.get("coherence_evidence") if isinstance(signature.get("coherence_evidence"), dict) else {}
    visual = props.get("visual_diversity_evidence") if isinstance(props.get("visual_diversity_evidence"), dict) else {}
    ambition = props.get("architectural_ambition_evidence") if isinstance(props.get("architectural_ambition_evidence"), dict) else {}
    if not ambition and isinstance(signature.get("architectural_ambition_evidence"), dict):
        ambition = signature["architectural_ambition_evidence"]
    orderliness = props.get("orderliness_evidence") if isinstance(props.get("orderliness_evidence"), dict) else {}
    if not orderliness and isinstance(visual.get("orderliness_evidence"), dict):
        orderliness = visual["orderliness_evidence"]
    performance_proxy = props.get("performance_proxy_evidence") if isinstance(props.get("performance_proxy_evidence"), dict) else {}
    program = props.get("program_massing_evidence") if isinstance(props.get("program_massing_evidence"), dict) else {}
    if not performance_proxy:
        performance_proxy = early_massing_performance_proxy(feature)
        props["performance_proxy_evidence"] = performance_proxy
    parameter_default_count = float(signature.get("parameter_default_count") or 0.0)
    family = _source_family(feature)
    shape = str(props.get("mass_shape") or "").lower()
    sequence = props.get("maas_verb_sequence")
    if not isinstance(sequence, list):
        model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
        sequence = model.get("verb_sequence")
    verbs = {
        str(call.get("verb") or "").lower()
        for call in sequence or []
        if isinstance(call, dict)
    }
    visual_stair_penalty = (
        1.0
        if (
            family not in {"legal_layered", "sloped_roof", "nest"}
            and (
                "step_envelope" in verbs
                or "stepback" in shape
                or "stair" in shape
            )
        )
        else 0.0
    )
    surface_count = float(signature.get("effective_surface_count") or signature.get("surface_count") or 0.0)
    visible_volume_count = _visible_volume_count(feature)
    clean_mass_pass = (
        surface_count <= float(ARCHITECTURAL_ORDER_POLICY["max_source_surfaces"])
        and visible_volume_count <= int(ARCHITECTURAL_ORDER_POLICY["max_visible_volumes"])
        and int(orderliness.get("small_fragment_count") or 0) <= int(ARCHITECTURAL_ORDER_POLICY["max_small_fragments"])
    )
    return (
        1.0 if _architectural_order_gate(feature)[0] else 0.0,
        1.0 if _has_review_source_geometry(feature) else 0.0,
        1.0 if clean_mass_pass else 0.0,
        # Law, parking and capacity have already been hard-gated before this
        # review key. Image-backed design quality must therefore participate
        # before small differences in proxy program score; otherwise VLM runs
        # but cannot change the final order.
        1.0 if preference_vlm_scored(feature) else 0.0,
        preference_score(feature),
        1.0 if program.get("hard_pass", True) else 0.0,
        float(program.get("program_fit_score") or 0.0),
        1.0 if coherence.get("hard_pass", True) else 0.0,
        float(coherence.get("score") or 0.0),
        -max(0.0, surface_count - float(ARCHITECTURAL_ORDER_POLICY["max_source_surfaces"])) / 32.0,
        -max(0.0, float(visible_volume_count - 5)) / 3.0,
        1.0 if _is_llm_authored_candidate(feature) else 0.0,
        1.0 if _is_direct_openai_llm_candidate(feature) else 0.0,
        1.0 if _is_agent_authored_candidate(feature) else 0.0,
        1.0 if _is_authored_mass_candidate(feature) else 0.0,
        1.0 if ambition.get("architecture_grade_pass") else 0.0,
        _repair_retention(feature),
        _repair_retention(feature, source_volume=True),
        float(ambition.get("silhouette_strength") or 0.0),
        float(ambition.get("sectional_diagram_clarity") or 0.0),
        min(float(len(ambition.get("implemented_volume_roles") or ())), 6.0) / 6.0,
        float(orderliness.get("orderliness_score") or 0.0),
        float(performance_proxy.get("aggregate_performance_proxy") or 0.0),
        -min(float(orderliness.get("small_fragment_count") or 0.0), 6.0) / 6.0,
        -min(float(orderliness.get("fragment_role_count") or 0.0), 6.0) / 6.0,
        max(0.0, 1.0 - abs(float(visible_volume_count) - 3.5) / 3.5),
        -visual_stair_penalty,
        -1.0 if family in STEPBACK_DOMINANT_FAMILIES else 0.0,
        -min(parameter_default_count, 8.0) / 8.0,
        float(_design_synthesis_rank(feature)),
        -1.0 if _is_plain_capacity_anchor(feature) else 0.0,
        float(props.get("design_quality_score") or 0.0),
        float(props.get("diversity_score") or 0.0),
        float(props.get("maas_score") or 0.0),
        _feature_plan_min_dimension(feature),
    )


def _architectural_order_gate(feature: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Return whether a candidate is clean enough for the user-facing review set.

    This is intentionally evidence-based rather than shape-name based. A
    candidate can be legal and diverse while still being too cluttered for the
    architectural review sheet.
    """
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    signature = _source_signature(feature)
    coherence = signature.get("coherence_evidence") if isinstance(signature.get("coherence_evidence"), dict) else {}
    repair_delta = props.get("repair_delta") if isinstance(props.get("repair_delta"), dict) else {}
    source_repair = props.get("source_volume_repair_delta") if isinstance(props.get("source_volume_repair_delta"), dict) else {}
    visual = props.get("visual_diversity_evidence") if isinstance(props.get("visual_diversity_evidence"), dict) else {}
    orderliness = props.get("orderliness_evidence") if isinstance(props.get("orderliness_evidence"), dict) else {}
    if not orderliness and isinstance(visual.get("orderliness_evidence"), dict):
        orderliness = visual["orderliness_evidence"]
    ambition = props.get("architectural_ambition_evidence") if isinstance(props.get("architectural_ambition_evidence"), dict) else {}
    if not ambition and isinstance(signature.get("architectural_ambition_evidence"), dict):
        ambition = signature["architectural_ambition_evidence"]
    policy = ARCHITECTURAL_ORDER_POLICY
    issues: list[str] = []
    score = float(orderliness.get("orderliness_score") or 0.0)
    main_ratio = float(orderliness.get("main_mass_area_ratio") or 0.0)
    small_fragments = int(orderliness.get("small_fragment_count") or 0)
    fragment_roles = int(orderliness.get("fragment_role_count") or 0)
    plan_components = int(orderliness.get("plan_component_count") or 1)
    surface_count = int(signature.get("effective_surface_count") or signature.get("surface_count") or visual.get("source_primitive_count") or 0)
    volume_count = _visible_volume_count(feature)
    bcr = float(props.get("bcr") or 0.0)
    far = float(props.get("far") or 0.0)
    far_utilization = float(props.get("far_utilization") or 0.0)
    family = _source_family(feature)
    shape = str(props.get("mass_shape") or "")
    implemented_roles = ambition.get("implemented_volume_roles") if isinstance(ambition.get("implemented_volume_roles"), list) else []
    if not orderliness:
        issues.append("missing_orderliness_evidence")
    if not ambition:
        issues.append("missing_architectural_ambition_evidence")
    if not ambition.get("formal_principle"):
        issues.append("missing_formal_principle")
    if not ambition.get("dominant_gesture"):
        issues.append("missing_dominant_gesture")
    if not ambition.get("architecture_grade_pass"):
        issues.append("architecture_grade_not_implemented")
    if len(implemented_roles) < 2:
        issues.append("weak_formal_volume_roles")
    if float(ambition.get("silhouette_strength") or 0.0) < 0.72:
        issues.append("weak_silhouette_principle")
    if float(ambition.get("sectional_diagram_clarity") or 0.0) < 0.70:
        issues.append("weak_sectional_principle")
    if score < float(policy["min_orderliness_score"]):
        issues.append("low_orderliness_score")
    if main_ratio and main_ratio < float(policy["min_main_mass_area_ratio"]):
        issues.append("weak_main_support_hierarchy")
    if small_fragments > int(policy["max_small_fragments"]):
        issues.append("too_many_small_fragments")
    if fragment_roles > int(policy["max_fragment_roles"]):
        issues.append("fragment_role_names_present")
    if surface_count > int(policy["max_source_surfaces"]):
        issues.append("over_complex_source_surfaces")
    if volume_count > int(policy["max_visible_volumes"]):
        issues.append("too_many_visible_volumes")
    if plan_components > int(policy["max_plan_components"]):
        issues.append("disconnected_plan_fragments")
    if bcr < float(policy["min_review_bcr_pct"]) or far < float(policy["min_review_far_pct"]):
        issues.append("under_scaled_review_mass")
    if far_utilization and far_utilization < _feature_min_far_utilization(feature):
        issues.append("underused_legal_far_capacity")
    if coherence and not coherence.get("hard_pass"):
        issues.append("component_graph_coherence_failure")
    if repair_delta and float(repair_delta.get("area_retention") or 0.0) < 0.65:
        issues.append("severe_legal_repair_distortion")
    if source_repair and float(source_repair.get("volume_retention") or source_repair.get("area_retention") or 0.0) < 0.80:
        issues.append("source_language_lost_during_legal_projection")
    if volume_count < int(policy["min_visible_volumes"]) and family not in {"legal_layered", "slender_bar"}:
        issues.append("too_few_visible_volumes_for_language")
    if visual.get("unclear_language_mix") or orderliness.get("unclear_language_mix"):
        issues.append("unclear_language_mix")
    if shape == "legal_layered_max" and score < 0.70:
        issues.append("capacity_anchor_not_review_clean")
    if (
        family == "legal_layered"
        and ambition.get("formal_principle") == "legal_layered_envelope"
        and volume_count >= 3
        and small_fragments == 0
        and fragment_roles == 0
        and score >= 0.60
    ):
        issues = [
            issue for issue in issues
            if issue not in {
                "low_orderliness_score",
                "weak_main_support_hierarchy",
                "capacity_anchor_not_review_clean",
            }
        ]
    return (not issues, tuple(issues))


def _is_vlm_review_candidate(feature: dict[str, Any]) -> bool:
    """Match paid VLM evaluation to the later exact-selection eligibility."""
    return (
        _is_reviewable_architectural_mass(feature)
        and _architectural_order_gate(feature)[0]
        and float(_source_signature(feature).get("parameter_default_ratio") or 0.0) <= 0.50
    )


def _has_resolved_parking_requirement(feature: dict[str, Any]) -> bool:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    precheck = props.get("parking_precheck") if isinstance(props.get("parking_precheck"), dict) else {}
    required = precheck.get("required_count") if isinstance(precheck.get("required_count"), dict) else {}
    return isinstance(required.get("required_spaces"), int)


def _preserve_visible_section_connector(
    selected: list[dict[str, Any]],
    *,
    final_limit: int,
    preferred_operator: str | None = None,
) -> list[dict[str, Any]]:
    if preferred_operator or final_limit <= 1:
        return selected
    visible = selected[:final_limit]
    if any(_is_section_connector(feature) for feature in visible):
        return selected
    connector = next((feature for feature in selected if _is_section_connector(feature)), None)
    if connector is None:
        return selected
    has_parking_gate = any(_has_resolved_parking_requirement(feature) for feature in selected)
    if has_parking_gate and _parking_priority_key(connector) < _parking_priority_key(visible[-1]):
        return selected
    return visible[:-1] + [connector] + [
        feature for feature in selected[final_limit:]
        if feature is not connector
    ]


def _final_design_balanced_selection(
    selected: list[dict[str, Any]],
    *,
    final_limit: int,
    preferred_operator: str | None = None,
) -> list[dict[str, Any]]:
    return selection_final_design_balanced_selection(
        selected,
        final_limit=final_limit,
        preferred_operator=preferred_operator,
        deps=BalancedSelectionDeps(
            research_target_families=RESEARCH_TARGET_FAMILIES,
            signature_proposal_priorities=SIGNATURE_PROPOSAL_PRIORITIES,
            stepback_dominant_families=STEPBACK_DOMINANT_FAMILIES,
            typology_first_families=TYPOLOGY_FIRST_FAMILIES,
            typology_review_quotas=TYPOLOGY_REVIEW_QUOTAS,
            architectural_ambition=_architectural_ambition,
            architectural_order_gate=_architectural_order_gate,
            design_review_quality_key=_design_review_quality_key,
            design_synthesis_rank=_design_synthesis_rank,
            formal_principle=_formal_principle,
            has_review_source_geometry=_has_review_source_geometry,
            is_agent_authored_candidate=_is_agent_authored_candidate,
            is_authored_mass_candidate=_is_authored_mass_candidate,
            is_clean_layered_anchor=_is_clean_layered_anchor,
            is_direct_openai_llm_candidate=_is_direct_openai_llm_candidate,
            is_llm_authored_candidate=_is_llm_authored_candidate,
            is_llm_coverage_repair_candidate=_is_llm_coverage_repair_candidate,
            is_parking_repair_operator=_is_parking_repair_operator,
            is_plain_capacity_anchor=_is_plain_capacity_anchor,
            is_plain_review_mass=_is_plain_review_mass,
            is_reviewable_architectural_mass=_is_reviewable_architectural_mass,
            is_section_connector=_is_section_connector,
            is_typology_first_candidate=_is_typology_first_candidate,
            operator_family=_operator_family,
            repair_retention=_repair_retention,
            research_diversity_descriptor=_research_diversity_descriptor,
            research_mass_language=_research_mass_language,
            research_quota_group=_research_quota_group,
            research_role_pattern=_research_role_pattern,
            source_family=_source_family,
            source_signature=_source_signature,
            stair_like_risk=_stair_like_risk,
            vertical_strategy=_vertical_strategy,
            visible_volume_count=_visible_volume_count,
        ),
    )


def _volume_profile(feature: dict[str, Any]) -> tuple[tuple[float, float, float], ...]:
    props = feature.get("properties", {}) or {}
    volumes = props.get("mass_volumes") or props.get("maas_model", {}).get("volumes") or []
    profile: list[tuple[float, float, float]] = []
    for volume in volumes:
        try:
            geom = wgs84_to_utm(geojson_to_polygon(volume.get("geometry")))
            profile.append((
                round(float(volume.get("bottom_height") or 0.0), 1),
                round(float(volume.get("top_height") or 0.0), 1),
                round(float(geom.area), 1),
            ))
        except Exception:
            continue
    if profile:
        return tuple(profile)
    try:
        geom = wgs84_to_utm(geojson_to_polygon(feature.get("geometry")))
        return ((0.0, round(float(props.get("height") or 0.0), 1), round(float(geom.area), 1)),)
    except Exception:
        return ()


def _shape_signature_3d(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties", {}) or {}
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    floor_plates = props.get("floor_plates") or model.get("floor_plates") or []
    plate_areas = [
        round(float(plate.get("area") or plate.get("area_m2") or 0.0), 2)
        for plate in floor_plates
        if isinstance(plate, dict)
    ]
    return {
        "height_m": props.get("height"),
        "num_floors": props.get("num_floors"),
        "volume_count": len(_volume_profile(feature)),
        "volume_profile": [
            {"bottom_height": bottom, "top_height": top, "area_m2": area}
            for bottom, top, area in _volume_profile(feature)
        ],
        "floor_plate_count": len(plate_areas),
        "floor_plate_area_profile": plate_areas,
    }


def _diversity_class(feature: dict[str, Any]) -> str:
    props = feature.get("properties", {}) or {}
    footprint_diversity = float(props.get("diversity_score") or 0.0)
    signature = props.get("shape_signature_3d") if isinstance(props.get("shape_signature_3d"), dict) else {}
    volume_count = int(signature.get("volume_count") or 0)
    floor_plate_count = int(signature.get("floor_plate_count") or 0)
    if footprint_diversity >= 0.2:
        return "plan_diverse"
    if volume_count > 1 or floor_plate_count > 0:
        return "section_diverse"
    return "near_duplicate"


def _attach_3d_diversity(feature: dict[str, Any]) -> None:
    props = feature.setdefault("properties", {})
    signature = _shape_signature_3d(feature)
    props["shape_signature_3d"] = signature
    props["candidate_diversity"] = {
        "class": _diversity_class(feature),
        "footprint_diversity_score": props.get("diversity_score"),
        "source_iou": props.get("source_iou"),
        "shape_signature_3d": signature,
    }


def _attach_design_quality(feature: dict[str, Any], footprint_utm) -> None:
    attach_design_quality_evidence(
        feature,
        footprint_utm=footprint_utm,
        optimizer_backend=d4descent_design_evidence(enable_import=False),
    )


def _stack_has_meaningful_top(stack: FloorPlateStack) -> bool:
    if not stack.floor_plates:
        return False
    top_area = float(stack.floor_plates[-1].get("area") or 0.0)
    ground_area = float(stack.footprint.area or 0.0)
    return top_area >= max(8.0, ground_area * 0.08)


def _should_use_floor_plate_stack(operator: str, preferred_operator: str | None = None) -> bool:
    """Use the expensive legal stack only for genuinely vertical/sectional forms.

    Plan-shape operators such as notch, courtyard, bar, branch, pinch, interlock
    and overlap lose their architectural identity if every candidate is rebuilt
    as the same envelope-derived floor plate stack. Those should keep their
    repaired footprint and be checked by the normal legal repair/metric pass.
    """
    if operator == preferred_operator:
        return True
    if operator == "grammar_sunlight_multi_step":
        return True
    if operator.startswith("grammar_"):
        return False
    return _operator_family(operator) in {"legal_layered"}


def _capacity_score(props: dict[str, Any]) -> float:
    far = float(props.get("far_utilization") or 0.0)
    bcr = float(props.get("bcr_utilization") or 0.0)
    return far * 0.62 + bcr * 0.38


def _normalized_feature_vector(feature: dict[str, Any]) -> tuple[float, ...]:
    props = feature.get("properties", {}) or {}
    signature = props.get("shape_signature") if isinstance(props.get("shape_signature"), dict) else {}
    signature_3d = props.get("shape_signature_3d") if isinstance(props.get("shape_signature_3d"), dict) else {}
    source_signature = _source_signature(feature)
    return (
        float(props.get("bcr") or 0.0) / 100.0,
        float(props.get("far") or 0.0) / 300.0,
        float(props.get("height") or 0.0) / 60.0,
        float(signature.get("compactness") or 0.0) / 100.0,
        float(signature_3d.get("volume_count") or 0.0) / 6.0,
        float(signature_3d.get("floor_plate_count") or 0.0) / 20.0,
        float(source_signature.get("volume_count") or 0.0) / 6.0,
        float(source_signature.get("effective_surface_count") or source_signature.get("surface_count") or 0.0) / 32.0,
        float(source_signature.get("upper_to_ground_ratio") or 0.0),
    )


def _source_signature(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    signature = props.get("source_signature")
    if isinstance(signature, dict):
        return signature
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    signature = model.get("source_signature")
    return signature if isinstance(signature, dict) else {}


def _architectural_ambition(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    ambition = props.get("architectural_ambition_evidence")
    if isinstance(ambition, dict) and ambition:
        return ambition
    signature = _source_signature(feature)
    ambition = signature.get("architectural_ambition_evidence")
    return ambition if isinstance(ambition, dict) else {}


def _massing_genome(feature: dict[str, Any]) -> dict[str, Any]:
    signature = _source_signature(feature)
    genome = signature.get("massing_genome")
    return genome if isinstance(genome, dict) else {}


def _formal_principle(feature: dict[str, Any]) -> str:
    ambition = _architectural_ambition(feature)
    if ambition.get("formal_principle"):
        return str(ambition.get("formal_principle") or "")
    genome = _massing_genome(feature)
    return str(genome.get("formal_principle") or "")


def _vertical_strategy(feature: dict[str, Any]) -> str:
    ambition = _architectural_ambition(feature)
    strategy = ambition.get("vertical_strategy")
    if strategy:
        return str(strategy)
    genome = _massing_genome(feature)
    return str(genome.get("vertical_strategy") or "")


def _stair_like_risk(feature: dict[str, Any]) -> str:
    ambition = _architectural_ambition(feature)
    risk = ambition.get("stair_like_risk")
    if risk:
        return str(risk)
    genome = _massing_genome(feature)
    return str(genome.get("stair_like_risk") or "")


def _repair_retention(feature: dict[str, Any], *, source_volume: bool = False) -> float:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    key = "source_volume_repair_delta" if source_volume else "repair_delta"
    delta = props.get(key)
    if not isinstance(delta, dict):
        delta = model.get(key) if isinstance(model, dict) else {}
    if not isinstance(delta, dict):
        return 1.0
    try:
        return max(0.0, min(1.0, float(delta.get("area_retention", 1.0))))
    except (TypeError, ValueError):
        return 1.0


def _attach_repair_delta(
    feature: dict[str, Any],
    *,
    source_area_m2: float,
    repaired_area_m2: float,
    actions: tuple[str, ...] | list[str] = (),
    scope: str = "legal_footprint",
) -> None:
    props = feature.setdefault("properties", {})
    source_area = max(0.0, float(source_area_m2 or 0.0))
    repaired_area = max(0.0, float(repaired_area_m2 or 0.0))
    retention = repaired_area / source_area if source_area > 0 else 1.0
    delta = {
        "schema_version": "arr.maas.repair_delta.v1",
        "scope": scope,
        "source_area_m2": round(source_area, 2),
        "repaired_area_m2": round(repaired_area, 2),
        "area_delta_m2": round(source_area - repaired_area, 2),
        "area_retention": round(retention, 4),
        "severity": "severe" if retention < 0.65 else ("moderate" if retention < 0.85 else "minor"),
        "actions": [str(action) for action in actions if action],
    }
    props["repair_delta"] = delta
    model = props.get("maas_model")
    if isinstance(model, dict):
        model["repair_delta"] = delta


def _has_review_source_geometry(feature: dict[str, Any]) -> bool:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    resolution = props.get("geometry_resolution")
    if not isinstance(resolution, dict):
        resolution = model.get("geometry_resolution") if isinstance(model, dict) else {}
    materialized = props.get("section_profile_materialized")
    if not isinstance(materialized, dict):
        materialized = model.get("section_profile_materialized") if isinstance(model, dict) else {}
    return (
        props.get("source_geometry_status") == "compiled"
        or model.get("source_geometry_status") == "compiled"
        or (isinstance(resolution, dict) and resolution.get("status") == "source_geometry_used")
        or (isinstance(materialized, dict) and materialized.get("status") == "source_geometry_used")
    )


def _source_family(feature: dict[str, Any]) -> str:
    signature = _source_signature(feature)
    family = signature.get("family")
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    shape_name = str(props.get("mass_shape") or "")
    roles_text = " ".join(str(role) for role in (signature.get("surface_roles") or []) if role)
    if str(family or "") == "embed" and "reflected_court_pair" in shape_name:
        return "reflected_pair"
    if str(family or "") == "slender_bar" and "slender_bar_notch" in shape_name:
        return "courtyard"
    if str(family or "") == "slender_bar" and "bar_notch_terrace" in shape_name:
        return "void_notch"
    if str(family or "") == "overlap" and "tapered_tower" in roles_text:
        return "tapered_tower"
    if str(family or "") == "extrude" and "extruded_branching_fin" in shape_name and "__evo_param" in shape_name:
        return "branch_fin"
    if family:
        return str(family)
    return _operator_family(str(props.get("mass_shape") or ""))


def _research_diversity_descriptor(feature: dict[str, Any]) -> dict[str, Any]:
    signature = _source_signature(feature)
    rule_evidence = signature.get("rule_evidence") if isinstance(signature.get("rule_evidence"), dict) else {}
    descriptor = rule_evidence.get("research_diversity_descriptor") if isinstance(rule_evidence, dict) else {}
    family = _source_family(feature)
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    shape_name = str(props.get("mass_shape") or "")
    language_by_family = {
        "array_cluster": "array_cluster",
        "offset": "offset_twin_bar",
        "reflected_pair": "reflected_court_pair",
        "slender_bar": "bar_notch_terrace",
        "extrude": "extruded_fin",
        "branch_fin": "branching_fin",
        "courtyard": "courtyard_atrium",
        "void_notch": "notched_void",
        "pinch": "pinched_waist",
        "embed": "embedded_void",
        "nest": "nested_atrium_stack",
        "split": "split_bridge",
        "bend": "bend_ribbon",
        "interlock": "cross_interlock",
        "overlap": "overlap_slabs",
        "branch": "branch_taper",
        "tapered_tower": "tapered_tower",
        "diagonal_connect": "diagonal_connector",
        "sloped_roof": "sloped_roof",
        "terrace_link": "terrace_ribbon",
        "stepback_tower": "stepped_tower",
        "legal_layered": "legal_layered_anchor",
    }
    group_by_family = {
        "array_cluster": "additive",
        "offset": "additive",
        "reflected_pair": "additive",
        "slender_bar": "additive",
        "extrude": "additive",
        "branch_fin": "additive",
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
        "tapered_tower": "hybrid",
        "diagonal_connect": "sectional",
        "sloped_roof": "sectional",
        "stepback_tower": "sectional",
        "terrace_link": "sectional",
        "legal_layered": "legal_anchor",
    }
    group = group_by_family.get(family, "generic")
    if family == "stack" and "terrace" in shape_name:
        group = "sectional"
        language_by_family = {**language_by_family, "stack": "terrace_ribbon"}
    if family == "embed" and "reflected_court_pair" in shape_name:
        group = "additive"
        language_by_family = {**language_by_family, "embed": "reflected_court_pair"}
    if family == "void_notch" and "bar_notch_terrace" in shape_name:
        group = "subtractive"
        language_by_family = {**language_by_family, "void_notch": "notched_void"}
    if family == "courtyard" and "slender_bar_notch" in shape_name:
        group = "subtractive"
        language_by_family = {**language_by_family, "courtyard": "courtyard_atrium"}
    if family == "branch" and "atrium" in shape_name:
        group = "subtractive"
        language_by_family = {**language_by_family, "branch": "branch_atrium"}
    if family == "tapered_tower":
        group = "hybrid"
        language_by_family = {**language_by_family, "tapered_tower": "tapered_tower"}
    if family == "branch_fin":
        group = "additive"
        language_by_family = {**language_by_family, "branch_fin": "branching_fin"}
    if isinstance(descriptor, dict) and descriptor:
        normalized = dict(descriptor)
        if family and (
            not normalized.get("mass_language")
            or normalized.get("mass_language") == family
            or (family == "stack" and "terrace" in shape_name)
            or (family == "embed" and "reflected_court_pair" in shape_name)
            or (family == "void_notch" and "bar_notch_terrace" in shape_name)
            or (family == "courtyard" and "slender_bar_notch" in shape_name)
            or (family == "branch" and "atrium" in shape_name)
            or family == "tapered_tower"
            or family == "branch_fin"
        ):
            normalized["mass_language"] = language_by_family.get(family, family)
        if group != "generic" and (
            not normalized.get("quota_group")
            or normalized.get("quota_group") == "generic"
            or (family == "stack" and "terrace" in shape_name)
            or (family == "embed" and "reflected_court_pair" in shape_name)
            or (family == "void_notch" and "bar_notch_terrace" in shape_name)
            or (family == "courtyard" and "slender_bar_notch" in shape_name)
            or (family == "branch" and "atrium" in shape_name)
            or family == "tapered_tower"
            or family == "branch_fin"
        ):
            normalized["quota_group"] = group
            normalized["generator_mode"] = group
        if family == "void_notch" and "bar_notch_terrace" in shape_name:
            normalized["role_pattern"] = "notched_void_bar|primary_podium_slab|secondary_void_notch_court_liner"
        if family == "courtyard" and "slender_bar_notch" in shape_name:
            normalized["role_pattern"] = "courtyard_notched_bar|primary_slender_tower|secondary_court_liner"
        if family == "branch_fin":
            normalized["role_pattern"] = "branching_fin|primary_extruded_fin|secondary_branch_ordered_bar"
        return normalized
    roles = [
        str(role)
        for role in (signature.get("surface_roles") or [])
        if role
    ]
    return {
        "schema_version": "arr.maas.research_diversity_descriptor.v1",
        "generator_mode": group,
        "mass_language": language_by_family.get(family, family or "generic"),
        "quota_group": group,
        "primitive_types": [],
        "topology_tags": [family] if family else [],
        "volume_count": int(signature.get("volume_count") or _visible_volume_count(feature)),
        "role_pattern": "|".join(roles),
        "rectilinear_template": int(signature.get("volume_count") or 0) == 3,
    }


def _research_quota_group(feature: dict[str, Any]) -> str:
    family = _source_family(feature)
    group_by_family = {
        "array_cluster": "additive",
        "offset": "additive",
        "reflected_pair": "additive",
        "slender_bar": "additive",
        "extrude": "additive",
        "branch_fin": "additive",
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
        "tapered_tower": "hybrid",
        "diagonal_connect": "sectional",
        "sloped_roof": "sectional",
        "stepback_tower": "sectional",
        "terrace_link": "sectional",
        "legal_layered": "legal_anchor",
    }
    family_group = group_by_family.get(family)
    descriptor_group = str(_research_diversity_descriptor(feature).get("quota_group") or "")
    if family_group and (not descriptor_group or descriptor_group == "generic"):
        return family_group
    return descriptor_group or family_group or "generic"


def _research_mass_language(feature: dict[str, Any]) -> str:
    return str(_research_diversity_descriptor(feature).get("mass_language") or _source_family(feature) or "generic")


def _projection_visual_language(feature: dict[str, Any]) -> str:
    """Return the language actually visible on the final review card.

    Research language is deliberately broad and useful for provenance, but it
    grouped a notched bar, twin bar and terrace bar together while allowing
    three visibly identical terrace-ribbon cards. The integer projection must
    cap the materialized synthesis users compare, not the upstream label.
    """
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    materialized = props.get("section_profile_materialized") if isinstance(props.get("section_profile_materialized"), dict) else {}
    profile = props.get("section_profile") if isinstance(props.get("section_profile"), dict) else {}
    family_language = {
        "bend": "bend_ribbon",
        "pinch": "pinched_waist",
        "sloped_roof": "sloped_roof",
        "terrace_link": "terrace_ribbon",
        "array_cluster": "array_cluster",
        "offset": "offset_twin_bar",
        "reflected_pair": "reflected_court_pair",
        "slender_bar": "slender_bar",
        "stepback_tower": "stepped_tower",
        "legal_layered": "stepped_tower",
        "diagonal_connect": "diagonal_connector",
        "split": "split_bridge",
        "courtyard": "courtyard_atrium",
        "embed": "embedded_void",
        "nest": "nested_stack",
        "interlock": "cross_interlock",
        "overlap": "overlap_slabs",
        "branch": "branch_taper",
        "extrude": "extruded_fin",
        "void_notch": "notched_void",
    }.get(_source_family(feature), "")
    return str(
        family_language
        or materialized.get("kind")
        or profile.get("kind")
        or _research_mass_language(feature)
        or "generic"
    )


def _research_role_pattern(feature: dict[str, Any]) -> str:
    descriptor = _research_diversity_descriptor(feature)
    pattern = descriptor.get("role_pattern")
    if pattern:
        return str(pattern)
    return "|".join(_source_signature(feature).get("verb_profile") or [])


def _research_review_floors(variant, repaired_floors: int, floor_height: float, height_limit: float) -> int:
    """Spread review heights by research island without exceeding legal repair floors."""
    max_by_height = max(1, int(height_limit / max(floor_height, 0.1)))
    max_legal = max(1, min(int(repaired_floors or 1), max_by_height))
    signature = getattr(variant, "source_signature", None)
    family = ""
    if isinstance(signature, dict):
        family = str(signature.get("family") or "")
        evidence = signature.get("rule_evidence") if isinstance(signature.get("rule_evidence"), dict) else {}
        descriptor = evidence.get("research_diversity_descriptor") if isinstance(evidence.get("research_diversity_descriptor"), dict) else {}
        group = str(descriptor.get("quota_group") or "")
        mass_language = str(descriptor.get("mass_language") or "")
    else:
        group = ""
        mass_language = ""
    if not group:
        group = {
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
            "sloped_roof": "sectional",
        }.get(family, "generic")
    language_target = {
        "courtyard_atrium": 4,
        "notched_void": 4,
        "pinched_waist": 2,
        "embedded_void": 3,
        "nested_atrium_stack": 2,
        "array_cluster": 2,
        "offset_twin_bar": 2,
        "reflected_court_pair": 2,
        "bar_notch_terrace": 2,
        "extruded_fin": 2,
        "split_bridge": 3,
        "bend_ribbon": 2,
        "cross_interlock": 2,
        "overlap_slabs": 2,
        "branch_taper": 2,
        "diagonal_connector": 3,
        "sloped_roof": 2,
        "terrace_ribbon": 2,
    }.get(mass_language)
    if language_target is not None:
        return max(1, min(max_legal, language_target))
    target = {
        "additive": 2,
        "subtractive": 3,
        "hybrid": 3,
        "sectional": 4,
    }.get(group, max_legal)
    if family in {"array_cluster", "slender_bar"}:
        target = 2
    elif family in {"nest", "courtyard", "void_notch"}:
        target = 3
    elif family in {"sloped_roof", "terrace_link"}:
        target = 2
    elif family in {"diagonal_connect"}:
        target = 3
    return max(1, min(max_legal, target))


def _capacity_projected_floors(
    footprint,
    upper_footprint,
    *,
    lower_floor_fraction: float | None,
    site_area_m2: float,
    far_limit: float,
    floor_height: float,
    height_limit: float,
) -> int:
    """Choose the highest legal floor count below the FAR/height envelope.

    Architectural language controls plan/section relationships; it must not
    silently turn a legal-capacity ALT into a two-floor research maquette.
    """
    max_by_height = max(1, int(float(height_limit) / max(float(floor_height), 0.1)))
    target_floor_area = max(0.0, float(site_area_m2) * float(far_limit) / 100.0)
    ground_area = float(getattr(footprint, "area", 0.0) or 0.0)
    upper_area = float(getattr(upper_footprint, "area", 0.0) or 0.0) if upper_footprint is not None else 0.0
    fraction = float(lower_floor_fraction if lower_floor_fraction is not None else 0.5)
    best_floors = 1
    best_area = 0.0
    for floors in range(1, max_by_height + 1):
        if upper_footprint is not None and floors >= 2:
            lower_floors = max(1, min(floors - 1, int(round(floors * fraction))))
            floor_area = ground_area * lower_floors + upper_area * (floors - lower_floors)
        else:
            floor_area = ground_area * floors
        if target_floor_area > 0 and floor_area > target_floor_area * 1.001:
            continue
        if floor_area >= best_area:
            best_area = floor_area
            best_floors = floors
    return best_floors


def _capacity_projected_floor_area(
    footprint,
    upper_footprint,
    *,
    floors: int,
    lower_floor_fraction: float | None,
) -> float:
    """Cheap capacity estimate used before constructing full 3D evidence."""
    ground_area = float(getattr(footprint, "area", 0.0) or 0.0)
    upper_area = float(getattr(upper_footprint, "area", 0.0) or 0.0) if upper_footprint is not None else 0.0
    if upper_footprint is None or floors < 2:
        return ground_area * max(1, int(floors))
    fraction = float(lower_floor_fraction if lower_floor_fraction is not None else 0.5)
    lower_floors = max(1, min(int(floors) - 1, int(round(int(floors) * fraction))))
    return ground_area * lower_floors + upper_area * (int(floors) - lower_floors)


def _llm_loop_config(parking_options: dict[str, Any] | None) -> dict[str, Any]:
    options = parking_options or {}
    raw = options.get("maas_llm_loop") if isinstance(options.get("maas_llm_loop"), dict) else {}
    enabled = bool(raw.get("enabled") or raw.get("required"))
    return {
        "enabled": enabled,
        "required": bool(raw.get("required")),
        "target_count": int(raw.get("target_count") or 120),
        "compile_limit": int(raw.get("compile_limit") or 90),
        "model": raw.get("model") if isinstance(raw.get("model"), str) else None,
        "timeout": float(raw.get("timeout") or 90.0),
        "batch_size": int(raw.get("batch_size") or 30),
        "batch_retries": int(raw.get("batch_retries") or 3),
        "batch_workers": max(1, int(raw.get("batch_workers") or os.getenv("MAAS_LLM_BATCH_WORKERS") or 1)),
        "batch_cache_path": raw.get("batch_cache_path") if isinstance(raw.get("batch_cache_path"), str) else os.getenv("MAAS_LLM_BATCH_CACHE_PATH", ""),
        "max_openai_batches": int(raw.get("max_openai_batches") or os.getenv("MAAS_LLM_MAX_OPENAI_BATCHES") or 0),
        "max_output_tokens": int(raw.get("max_output_tokens") or 12000),
        "overgenerate_count": int(raw.get("overgenerate_count") or os.getenv("MAAS_LLM_OVERGENERATE_COUNT") or 0),
        "generation_feedback": raw.get("generation_feedback") if isinstance(raw.get("generation_feedback"), dict) else None,
        "generation_feedback_path": (
            raw.get("generation_feedback_path")
            if isinstance(raw.get("generation_feedback_path"), str)
            else os.getenv("MAAS_LLM_GENERATION_FEEDBACK_JSON", "")
        ),
    }


def _load_generation_feedback(config: dict[str, Any]) -> dict[str, Any] | None:
    inline = config.get("generation_feedback")
    if isinstance(inline, dict):
        return inline
    path = str(config.get("generation_feedback_path") or "").strip()
    if not path:
        return None
    requested_path = Path(path).expanduser()
    workspace_root = _design_paths.workspace_root()
    candidate_paths = [
        requested_path,
        Path.cwd() / requested_path,
        workspace_root / requested_path,
    ]
    resolved_path = next((candidate for candidate in candidate_paths if candidate.exists()), requested_path)
    try:
        with open(resolved_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError:
        return {
            "schema_version": "arr.maas.vlm_generation_feedback_load_error.v1",
            "source_path": path,
            "error": "file_not_found_or_unreadable",
        }
    if not isinstance(data, dict):
        return None
    data.setdefault("source_path", str(resolved_path))
    return data


def _llm_candidate_quality(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    far = float(props.get("far") or 0.0)
    bcr = float(props.get("bcr") or 0.0)
    signature = _source_signature(feature)
    parameter_default_count = int(signature.get("parameter_default_count") or 0)
    parameter_authored_count = int(signature.get("parameter_authored_count") or 0)
    parameter_default_ratio = float(signature.get("parameter_default_ratio") or 0.0)
    weak_default_dependency = (
        (parameter_default_count >= 8 and parameter_default_ratio > 0.70)
        or (parameter_default_count >= 5 and parameter_authored_count < 4)
    )
    weak = far < 20.0 or bcr < 8.0 or weak_default_dependency
    weak_reason = None
    if far < 20.0 or bcr < 8.0:
        weak_reason = "too_small_for_representative_review"
    elif weak_default_dependency:
        weak_reason = "too_many_compiler_default_parameters"
    return {
        "schema_version": "arr.maas.llm_candidate_quality.v1",
        "status": "reject_final_review" if weak else "reviewable",
        "far": round(far, 2),
        "bcr": round(bcr, 2),
        "parameter_default_count": parameter_default_count,
        "parameter_authored_count": parameter_authored_count,
        "parameter_default_ratio": round(parameter_default_ratio, 3),
        "weak_reason": weak_reason,
    }


def _source_area_profile(feature: dict[str, Any]) -> tuple[float, ...]:
    profile = _source_signature(feature).get("area_profile_m2")
    if not isinstance(profile, list):
        return ()
    result: list[float] = []
    for value in profile:
        try:
            result.append(round(float(value), 1))
        except (TypeError, ValueError):
            continue
    return tuple(result)


def _polygon_ring_count(geometry: dict[str, Any] | None) -> int:
    if not isinstance(geometry, dict):
        return 0
    coords = geometry.get("coordinates")
    if geometry.get("type") == "Polygon" and isinstance(coords, list):
        return max(0, len(coords) - 1)
    if geometry.get("type") == "MultiPolygon" and isinstance(coords, list):
        return sum(max(0, len(poly) - 1) for poly in coords if isinstance(poly, list))
    return 0


def _volume_centroid_shift(volumes: list[dict[str, Any]]) -> float:
    if len(volumes) < 2:
        return 0.0
    try:
        first = _largest_polygon_or_none(wgs84_to_utm(geojson_to_polygon(volumes[0].get("geometry"))))
        last = _largest_polygon_or_none(wgs84_to_utm(geojson_to_polygon(volumes[-1].get("geometry"))))
    except Exception:
        return 0.0
    if first is None or last is None:
        return 0.0
    return round(float(first.centroid.distance(last.centroid)), 3)


FRAGMENT_ROLE_RE = re.compile(
    r"(counterweight|side_lock|edge_lip|short_tail|secondary_link|hinge_court_edge|random|fragment)",
    re.IGNORECASE,
)


def _role_hierarchy_bucket(role: str) -> str:
    lowered = role.lower()
    if FRAGMENT_ROLE_RE.search(lowered):
        return "fragment"
    if any(token in lowered for token in ("void", "court", "atrium", "notch", "cut")):
        return "void"
    if any(token in lowered for token in ("primary", "main", "core", "trunk", "base", "plinth", "shell", "outer")):
        return "primary"
    if any(token in lowered for token in ("secondary", "bridge", "spine", "connector", "ribbon", "bar", "arm", "liner", "roof", "cap")):
        return "secondary"
    return "support"


def _orderliness_evidence(
    feature: dict[str, Any],
    volumes: list[dict[str, Any]],
    source_signature: dict[str, Any],
    family: str,
) -> dict[str, Any]:
    parsed: list[dict[str, Any]] = []
    for volume in volumes:
        if not isinstance(volume, dict):
            continue
        try:
            geom = _largest_polygon_or_none(wgs84_to_utm(geojson_to_polygon(volume.get("geometry"))))
        except Exception:
            geom = None
        if geom is None or geom.is_empty:
            continue
        minx, miny, maxx, maxy = geom.bounds
        parsed.append({
            "role": str(volume.get("role") or ""),
            "area": float(geom.area),
            "centroid": geom.centroid,
            "bounds": (minx, miny, maxx, maxy),
            "geom": geom,
        })
    if not parsed:
        return {
            "schema_version": "arr.maas.orderliness.v1",
            "status": "missing_geometry",
            "dominant_axis": "unknown",
            "orderliness_score": 0.0,
        }
    areas = [item["area"] for item in parsed]
    total_area = max(sum(areas), 1e-6)
    max_area = max(areas)
    main_index = areas.index(max_area)
    main = parsed[main_index]
    minx, miny, maxx, maxy = main["bounds"]
    main_width = max(maxx - minx, 1e-6)
    main_depth = max(maxy - miny, 1e-6)
    if main_width >= main_depth * 1.15:
        dominant_axis = "x"
    elif main_depth >= main_width * 1.15:
        dominant_axis = "y"
    else:
        dominant_axis = "balanced"

    aligned = 0
    for item in parsed:
        cx_delta = abs(float(item["centroid"].x - main["centroid"].x))
        cy_delta = abs(float(item["centroid"].y - main["centroid"].y))
        if dominant_axis == "x":
            aligned += 1 if cy_delta <= main_depth * 0.42 else 0
        elif dominant_axis == "y":
            aligned += 1 if cx_delta <= main_width * 0.42 else 0
        else:
            aligned += 1 if cx_delta <= main_width * 0.45 and cy_delta <= main_depth * 0.45 else 0
    aligned_role_ratio = aligned / max(1, len(parsed))

    roles = [item["role"] for item in parsed]
    role_buckets = [_role_hierarchy_bucket(role) for role in roles]
    hierarchy_core = {bucket for bucket in role_buckets if bucket in {"primary", "secondary", "void"}}
    role_hierarchy_depth = len(hierarchy_core)
    small_fragment_count = sum(1 for area in areas if area < max_area * 0.18 and area < total_area * 0.12)
    fragment_role_count = sum(1 for role in roles if FRAGMENT_ROLE_RE.search(role))
    main_mass_area_ratio = max_area / total_area
    primitive_count = int(source_signature.get("source_primitive_count") or 0)
    surface_count = int(source_signature.get("effective_surface_count") or source_signature.get("surface_count") or 0)
    visible_volume_count = len(parsed)
    composition_roles = source_signature.get("composition_layer_roles")
    composition_count = len(composition_roles) if isinstance(composition_roles, list) else 0
    connected_union = unary_union([item["geom"].buffer(0.12) for item in parsed])
    plan_component_count = len(getattr(connected_union, "geoms", (connected_union,)))
    unclear_language_mix = (
        (fragment_role_count > 2)
        or (small_fragment_count > 3)
        or (primitive_count > 0 and composition_count == 0 and len(parsed) > 3)
    )
    if family == "legal_layered" and len(parsed) >= 3:
        role_hierarchy_depth = max(role_hierarchy_depth, 2)
    if family in {"diagonal_connect", "split"} and len(parsed) >= 3:
        role_hierarchy_depth = max(role_hierarchy_depth, 2)
    hierarchy_score = min(max(role_hierarchy_depth, 1), 3) / 3.0
    fragment_penalty_score = max(0.0, 1.0 - (small_fragment_count * 0.18) - (fragment_role_count * 0.16))
    ambition = source_signature.get("architectural_ambition_evidence")
    ambition = ambition if isinstance(ambition, dict) else {}
    formal_principle = str(ambition.get("formal_principle") or "")
    formal_series_prefixes = {
        "torqued_stack": ("_torqued_plate_", "primary_torqued_plate_"),
        "stacked_shifted_platforms": ("_shifted_platform_", "primary_shifted_platform_"),
        "folded_section": ("_folded_", "primary_folded_"),
        "terraced_ribbon_section": ("_folded_", "primary_folded_"),
        "split_bridge_connector": (
            "source_geometry_primary_diagonal_connect_",
            "source_geometry_secondary_diagonal_connect_",
            "source_geometry_primary_split_",
            "source_geometry_secondary_split_",
            "primary_diagonal_bridge_",
            "secondary_diagonal_bridge_",
        ),
        "legal_layered_envelope": ("legal_floor_plate_band_", "primary_legal_", "secondary_legal_"),
    }.get(formal_principle, ())
    formal_series_mass_ratio = 0.0
    if formal_series_prefixes:
        formal_series_area = sum(
            item["area"]
            for item in parsed
            if any(
                prefix in str(item["role"])
                for prefix in formal_series_prefixes
            )
        )
        formal_series_mass_ratio = formal_series_area / total_area
    main_mass_score = min(main_mass_area_ratio / 0.62, 1.0)
    if formal_series_mass_ratio >= 0.72 and fragment_role_count == 0:
        main_mass_score = max(main_mass_score, min(formal_series_mass_ratio / 0.88, 1.0))
    formal_order_bonus = 0.08 if formal_series_mass_ratio >= 0.78 and small_fragment_count <= 1 and fragment_role_count == 0 else 0.0
    score = (
        0.36 * main_mass_score
        + 0.28 * aligned_role_ratio
        + 0.20 * hierarchy_score
        + 0.16 * fragment_penalty_score
        + formal_order_bonus
    )
    score -= min(0.30, max(0, surface_count - int(ARCHITECTURAL_ORDER_POLICY["max_source_surfaces"])) * 0.015)
    score -= min(0.24, max(0, visible_volume_count - 5) * 0.12)
    score -= min(0.30, max(0, plan_component_count - 1) * 0.15)
    if family in STEPBACK_DOMINANT_FAMILIES:
        score -= 0.12
    if unclear_language_mix:
        score -= 0.10
    return {
        "schema_version": "arr.maas.orderliness.v1",
        "status": "measured",
        "dominant_axis": dominant_axis,
        "main_role": main["role"],
        "main_mass_area_ratio": round(main_mass_area_ratio, 3),
        "aligned_role_ratio": round(aligned_role_ratio, 3),
        "small_fragment_count": int(small_fragment_count),
        "fragment_role_count": int(fragment_role_count),
        "plan_component_count": int(plan_component_count),
        "role_hierarchy_depth": int(role_hierarchy_depth),
        "unclear_language_mix": bool(unclear_language_mix),
        "role_hierarchy": dict(sorted(Counter(role_buckets).items())),
        "formal_series_mass_ratio": round(formal_series_mass_ratio, 3),
        "formal_order_bonus": round(formal_order_bonus, 3),
        "orderliness_score": round(max(0.0, min(1.0, score)), 3),
    }


def _visual_diversity_evidence(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    volumes = props.get("mass_volumes") if isinstance(props.get("mass_volumes"), list) else model.get("volumes")
    volumes = volumes if isinstance(volumes, list) else []
    profile = props.get("section_profile") if isinstance(props.get("section_profile"), dict) else model.get("section_profile")
    profile = profile if isinstance(profile, dict) else {}
    source_signature = _source_signature(feature)
    family = str(source_signature.get("family") or props.get("operator_family") or "")
    area_profile: list[float] = []
    ring_count = 0
    for volume in volumes:
        if not isinstance(volume, dict):
            continue
        ring_count += _polygon_ring_count(volume.get("geometry"))
        try:
            geom = _largest_polygon_or_none(wgs84_to_utm(geojson_to_polygon(volume.get("geometry"))))
        except Exception:
            geom = None
        if geom is not None:
            area_profile.append(round(float(geom.area), 1))
    unique_area_bands = len({round(area, 0) for area in area_profile})
    volume_count = len(volumes)
    stepback_like = (
        volume_count >= 4
        and unique_area_bands >= 3
        and ring_count == 0
        and (family in {"legal_layered", "stepback_tower"} or str(profile.get("kind") or "") == "stepped_tower")
    )
    stepback_dominant = stepback_like or family in STEPBACK_DOMINANT_FAMILIES
    research_descriptor = _research_diversity_descriptor(feature)
    volume_roles = [
        str(volume.get("role") or "")
        for volume in volumes
        if isinstance(volume, dict) and volume.get("role")
    ]
    composition_layer_roles = [
        role
        for role in volume_roles
        if role.startswith("secondary_") or role.startswith("source_geometry_secondary_")
    ]
    source_primitive_roles = source_signature.get("source_primitive_roles")
    if not isinstance(source_primitive_roles, dict):
        source_primitive_roles = {
            "polygonal": [role for role in volume_roles if "polygonal_" in role],
            "curvilinear": [role for role in volume_roles if "curvilinear_" in role],
            "freeform": [role for role in volume_roles if "freeform_" in role],
        }
    primitive_count = sum(
        len(roles)
        for roles in source_primitive_roles.values()
        if isinstance(roles, list)
    )
    primary_language = str(
        source_signature.get("primary_language")
        or research_descriptor.get("mass_language")
        or family
        or ""
    )
    secondary_language = str(source_signature.get("secondary_language") or "")
    composition_rule = str(source_signature.get("composition_rule") or "")
    if not composition_rule and primary_language and secondary_language and secondary_language != "legal_envelope_fit":
        composition_rule = f"{primary_language}+{secondary_language}"
    orderliness = _orderliness_evidence(feature, volumes, source_signature, family)
    return {
        "schema_version": "arr.maas.visual_diversity.v1",
        "visual_family": family or str(profile.get("kind") or ""),
        "section_profile_kind": profile.get("kind"),
        "research_diversity_descriptor": research_descriptor,
        "generator_mode": research_descriptor.get("generator_mode"),
        "mass_language": research_descriptor.get("mass_language"),
        "primary_language": primary_language,
        "secondary_language": secondary_language,
        "composition_rule": composition_rule,
        "composition_layer_roles": composition_layer_roles,
        "composition_layer_count": len(composition_layer_roles),
        "source_primitive_roles": source_primitive_roles,
        "source_primitive_count": primitive_count,
        "quota_group": research_descriptor.get("quota_group"),
        "topology_tags": research_descriptor.get("topology_tags", []),
        "role_pattern": research_descriptor.get("role_pattern"),
        "rectilinear_template": research_descriptor.get("rectilinear_template"),
        "volume_count": volume_count,
        "unique_area_bands": unique_area_bands,
        "hole_count": ring_count,
        "centroid_shift_m": _volume_centroid_shift(volumes),
        "stepback_like": stepback_like,
        "stepback_dominant": stepback_dominant,
        "orderliness_evidence": orderliness,
        "source_geometry_status": props.get("source_geometry_status") or model.get("source_geometry_status"),
    }


def _attach_visual_diversity_evidence(feature: dict[str, Any]) -> None:
    props = feature.setdefault("properties", {})
    evidence = _visual_diversity_evidence(feature)
    props["visual_diversity_evidence"] = evidence
    props["orderliness_evidence"] = evidence.get("orderliness_evidence")
    source_signature = _source_signature(feature)
    research_descriptor = evidence.get("research_diversity_descriptor")
    if isinstance(source_signature, dict) and isinstance(research_descriptor, dict):
        canonical_family = _source_family(feature)
        if canonical_family and source_signature.get("family") != canonical_family:
            source_signature.setdefault("raw_family", source_signature.get("family"))
            source_signature["family"] = canonical_family
        rule_evidence = source_signature.get("rule_evidence")
        if isinstance(rule_evidence, dict):
            rule_evidence["research_diversity_descriptor"] = dict(research_descriptor)
            rule_evidence["generator_mode"] = research_descriptor.get("generator_mode")
            rule_evidence["mass_language"] = research_descriptor.get("mass_language")
            rule_evidence["quota_group"] = research_descriptor.get("quota_group")
        source_signature["composition_rule"] = source_signature.get("composition_rule") or evidence.get("composition_rule")
    ambition = source_signature.get("architectural_ambition_evidence")
    if isinstance(ambition, dict):
        props["architectural_ambition_evidence"] = dict(ambition)
    model = props.get("maas_model")
    if isinstance(model, dict):
        model["visual_diversity_evidence"] = evidence
        model["orderliness_evidence"] = evidence.get("orderliness_evidence")
        if isinstance(ambition, dict):
            model["architectural_ambition_evidence"] = dict(ambition)


def _attach_geometry_resolution(
    feature: dict[str, Any],
    *,
    status: str,
    source: str,
    legal_action: str,
    fallback: str | None = None,
) -> None:
    props = feature.setdefault("properties", {})
    resolution = {
        "schema_version": "arr.maas.geometry_resolution.v1",
        "status": status,
        "source": source,
        "legal_action": legal_action,
    }
    if fallback:
        resolution["fallback"] = fallback
    props["geometry_resolution"] = resolution
    model = props.get("maas_model")
    if isinstance(model, dict):
        model["geometry_resolution"] = resolution


def _apply_source_volumes_as_mass_geometry(feature: dict[str, Any]) -> bool:
    props = feature.setdefault("properties", {})
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    source_volumes = props.get("source_volumes")
    if not isinstance(source_volumes, list):
        source_volumes = model.get("source_volumes") if isinstance(model, dict) else None
    if not isinstance(source_volumes, list) or not source_volumes:
        return False
    try:
        legal_footprint = _largest_polygon_or_none(wgs84_to_utm(geojson_to_polygon(feature.get("geometry"))))
    except Exception:
        legal_footprint = None
    if legal_footprint is None:
        return False
    total_height = float(props.get("height") or 0.0)
    if total_height <= 0.0:
        return False

    materialized: list[dict[str, Any]] = []
    materialized_utms: list[Any] = []
    source_area_total = 0.0
    clipped_area_total = 0.0
    source_volume_total = 0.0
    clipped_volume_total = 0.0
    weighted_iou_total = 0.0
    clipped_volume_count = 0
    for index, volume in enumerate(source_volumes):
        if not isinstance(volume, dict) or not isinstance(volume.get("geometry_utm"), dict):
            continue
        try:
            source_geom = _largest_polygon_or_none(shape(volume["geometry_utm"]))
            geom = _largest_polygon_or_none(source_geom.intersection(legal_footprint)) if source_geom is not None else None
        except Exception:
            source_geom = None
            geom = None
        if geom is None:
            continue
        source_area = float(getattr(source_geom, "area", 0.0) or 0.0)
        clipped_area = float(getattr(geom, "area", 0.0) or 0.0)
        source_area_total += source_area
        clipped_area_total += clipped_area
        if source_area > clipped_area + 0.1:
            clipped_volume_count += 1
        bottom_fraction = float(volume.get("bottom_fraction") or 0.0)
        top_fraction = float(volume.get("top_fraction") or 0.0)
        bottom_height = max(0.0, min(total_height, total_height * bottom_fraction))
        top_height = max(bottom_height, min(total_height, total_height * top_fraction))
        if top_height <= bottom_height:
            continue
        band_height = top_height - bottom_height
        source_volume_total += source_area * band_height
        clipped_volume_total += clipped_area * band_height
        weighted_iou_total += polygon_iou(source_geom, geom) * source_area * band_height
        materialized.append({
            "band": index,
            "bottom_height": round(bottom_height, 2),
            "top_height": round(top_height, 2),
            "geometry": mapping(utm_to_wgs84(geom)),
            "role": f"source_geometry_{volume.get('role') or index}",
            "source_geometry": {
                "basis": "massdsl_source_volume",
                "verb": volume.get("verb"),
                "legal_accounting": "candidate_metrics_remain_from_repaired_legal_mass",
            },
        })
        materialized_utms.append(geom)
    if not materialized:
        return False

    profile = props.get("section_profile") if isinstance(props.get("section_profile"), dict) else model.get("section_profile")
    kind = str((profile or {}).get("kind") or _source_family(feature) or "source_geometry")
    props["mass_volumes"] = materialized
    props["section_source_surfaces"] = _build_section_source_surfaces(
        kind=kind,
        profile=profile if isinstance(profile, dict) else {},
        materialized=materialized,
        materialized_utms=materialized_utms,
    )
    props["section_profile_materialized"] = {
        "status": "source_geometry_used",
        "kind": kind,
        "design_synthesis": True,
        "volume_count": len(materialized),
        "surface_count": len(props["section_source_surfaces"]),
        "legal_accounting": "floor_plates_or_repaired_mass_metrics",
        "basis": "massdsl_source_geometry",
    }
    props["source_volume_repair_delta"] = {
        "schema_version": "arr.maas.source_volume_repair_delta.v1",
        "source_area_m2": round(source_area_total, 2),
        "materialized_area_m2": round(clipped_area_total, 2),
        "area_retention": round(clipped_area_total / source_area_total, 4) if source_area_total > 0 else 1.0,
        "volume_retention": round(clipped_volume_total / source_volume_total, 4) if source_volume_total > 0 else 1.0,
        "weighted_plan_iou": round(weighted_iou_total / source_volume_total, 4) if source_volume_total > 0 else 1.0,
        "language_retention_pass": bool(source_volume_total <= 0 or clipped_volume_total / source_volume_total >= 0.80),
        "clipped_volume_count": clipped_volume_count,
    }
    if isinstance(model, dict):
        model["volumes"] = materialized
        model["section_source_surfaces"] = props["section_source_surfaces"]
        model["section_profile_materialized"] = props["section_profile_materialized"]
        model["source_volume_repair_delta"] = props["source_volume_repair_delta"]
    _attach_geometry_resolution(
        feature,
        status="source_geometry_used",
        source="massdsl_source_volume_geometry",
        legal_action="source_volume_intersected_with_repaired_legal_footprint",
    )
    _attach_visual_diversity_evidence(feature)
    return True


def _promote_legal_floor_stack_source_geometry(feature: dict[str, Any]) -> None:
    props = feature.setdefault("properties", {})
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    volumes = props.get("mass_volumes")
    if not isinstance(volumes, list):
        volumes = model.get("volumes") if isinstance(model, dict) else []
    source_volumes: list[dict[str, Any]] = []
    area_profile: list[float] = []
    surface_count = 0
    for index, volume in enumerate(volumes if isinstance(volumes, list) else []):
        geometry = volume.get("geometry") if isinstance(volume, dict) else None
        if not isinstance(geometry, dict):
            continue
        try:
            geom_utm = _largest_polygon_or_none(wgs84_to_utm(geojson_to_polygon(geometry)))
        except Exception:
            geom_utm = None
        if geom_utm is None:
            continue
        area_profile.append(round(float(geom_utm.area), 2))
        surface_count += max(1, len(list(geom_utm.exterior.coords)) - 1)
        role = "primary_legal_base" if index == 0 else f"secondary_legal_step_{index}"
        source_volumes.append({
            "role": role,
            "verb": "legal_envelope",
            "bottom_fraction": round(float(volume.get("bottom_height") or 0.0) / max(float(props.get("height") or 1.0), 1.0), 3),
            "top_fraction": round(float(volume.get("top_height") or 0.0) / max(float(props.get("height") or 1.0), 1.0), 3),
            "area_m2": round(float(geom_utm.area), 2),
            "geometry_utm": mapping(geom_utm),
            "geometry_crs": "EPSG:32652",
        })
    if not source_volumes:
        return
    source_volume_roles = [str(volume.get("role") or f"legal_floor_plate_band_{index}") for index, volume in enumerate(source_volumes)]
    research_descriptor = {
        "schema_version": "arr.maas.research_diversity_descriptor.v1",
        "generator_mode": "legal_anchor",
        "mass_language": "legal_layered_anchor",
        "quota_group": "legal_anchor",
        "primitive_types": ["legal_floor_plate"],
        "topology_tags": ["legal_layered", "stepback", "sunlight_envelope"],
        "volume_count": len(source_volumes),
        "role_pattern": "|".join(source_volume_roles),
        "rectilinear_template": False,
    }
    rule_evidence = {
        "schema_version": "arr.maas.rule_evidence.v1",
        "rule_name": "legal_envelope:floor_plate_stack",
        "family": "legal_layered",
        "generator_mode": "legal_anchor",
        "mass_language": "legal_layered_anchor",
        "quota_group": "legal_anchor",
        "rule_inputs": {
            "floor_count": len(source_volumes),
            "area_profile_m2": area_profile,
        },
        "geometry_actions": [
            "build_floor_plate_stack",
            "clip_floor_plates_to_legal_envelope",
            "preserve_sunlight_stepback_profile",
        ],
        "source_volume_roles": source_volume_roles,
        "research_diversity_descriptor": research_descriptor,
        "rule_prior_param_count": 0,
        "llm_authored_param_count": 0,
        "invalid_rule_param_count": 0,
        "rule_prior_param_ratio": 0.0,
    }
    ambition_evidence = {
        "schema_version": "arr.maas.architectural_ambition.v1",
        "formal_principle": "legal_layered_envelope",
        "dominant_gesture": "stepped legal envelope translated into readable floor-plate stack",
        "implemented_volume_roles": source_volume_roles,
        "architecture_grade_pass": True,
        "silhouette_strength": 0.78,
        "sectional_diagram_clarity": 0.92,
        "vertical_strategy": "legal_stepback_stack",
        "stair_like_risk": "managed",
    }
    typed_volumes = tuple(
        SourceVolume(
            role=str(volume["role"]),
            footprint=shape(volume["geometry_utm"]),
            bottom_fraction=float(volume["bottom_fraction"]),
            top_fraction=float(volume["top_fraction"]),
            verb=str(volume["verb"]),
        )
        for volume in source_volumes
    )
    coherence_evidence = evaluate_source_volume_coherence(typed_volumes)
    graph_sequence = VerbSequence(
        name="legal_layered_anchor",
        label="Legal layered anchor",
        calls=(VerbCall("base", {}),) + tuple(
            VerbCall("stack", {"band": index})
            for index in range(1, len(source_volumes))
        ),
        notes=("legal_envelope_source_of_truth",),
    )
    component_graph = graph_from_sequence(graph_sequence).to_dict()
    props["source_geometry_status"] = "compiled"
    props["source_volumes"] = source_volumes
    props["source_signature"] = {
        "schema_version": "arr.maas.source_geometry.signature.v1",
        "status": "compiled",
        "family": _operator_family(str(props.get("mass_shape") or "")),
        "volume_count": len(source_volumes),
        "surface_count": surface_count,
        "ground_area_m2": area_profile[0] if area_profile else None,
        "upper_area_m2": area_profile[-1] if len(area_profile) > 1 else None,
        "upper_to_ground_ratio": round(area_profile[-1] / area_profile[0], 4) if len(area_profile) > 1 and area_profile[0] else None,
        "area_profile_m2": area_profile,
        "verb_profile": ["legal_envelope"],
        "surface_roles": source_volume_roles,
        "source_volume_roles": source_volume_roles,
        "composition_layer_roles": source_volume_roles,
        "composition_rule": "legal_envelope_floor_plate_stack",
        "primary_language": "legal_layered_anchor",
        "secondary_language": "sunlight_stepback_profile",
        "rule_evidence": rule_evidence,
        "architectural_ambition_evidence": ambition_evidence,
        "formal_principle": "legal_layered_envelope",
        "dominant_gesture": "stepped legal envelope translated into readable floor-plate stack",
        "parameter_provenance": [],
        "parameter_default_count": 0,
        "parameter_authored_count": 0,
        "parameter_default_ratio": 0.0,
        "rule_prior_param_count": 0,
        "llm_authored_param_count": 0,
        "invalid_rule_param_count": 0,
        "rule_prior_param_ratio": 0.0,
        "asymmetry_hint": "legal_envelope_floor_plate_stack",
        "component_graph": component_graph,
        "coherence_evidence": coherence_evidence,
    }
    props["architectural_ambition_evidence"] = ambition_evidence
    props["research_basis"] = {
        "implemented_status": "arr_native_approximation",
        "optimization_mode": "legal_envelope_solver",
        "requires_llm_authoring": False,
        "legal_solver_role": "source_of_truth",
    }
    props["section_profile_materialized"] = {
        "status": "source_geometry_used",
        "kind": "stepped_tower",
        "design_synthesis": True,
        "volume_count": len(source_volumes),
        "surface_count": surface_count,
        "legal_accounting": "floor_plates",
        "basis": "legal_envelope_source_geometry",
    }
    if isinstance(model, dict):
        model["source_geometry_status"] = props["source_geometry_status"]
        model["source_volumes"] = source_volumes
        model["source_signature"] = props["source_signature"]
        model["section_profile_materialized"] = props["section_profile_materialized"]
        model["architectural_ambition_evidence"] = ambition_evidence
        model["research_basis"] = props["research_basis"]
    notes = props.get("notes")
    if not isinstance(notes, list):
        notes = []
    note_keys = {str(note).split("=", 1)[0] for note in notes if isinstance(note, str) and "=" in note}
    if "rule_name" not in note_keys:
        notes.append("rule_name=legal_envelope:floor_plate_stack")
    if "rule_inputs" not in note_keys:
        notes.append(f"rule_inputs={rule_evidence['rule_inputs']}")
    if "expected_geometry_actions" not in note_keys:
        notes.append(f"expected_geometry_actions={rule_evidence['geometry_actions']}")
    props["notes"] = notes
    if isinstance(model, dict):
        model["notes"] = notes
    _attach_geometry_resolution(
        feature,
        status="source_geometry_used",
        source="legal_envelope_floor_plate_geometry",
        legal_action="floor_plates_clipped_to_legal_envelope",
    )


def _rebind_projected_surfaces_after_piloti_void(
    feature: dict[str, Any],
    *,
    void_height: float,
) -> None:
    props = feature.get("properties")
    props = props if isinstance(props, dict) else {}
    records = props.get("source_surfaces")
    if not isinstance(records, list):
        return
    profiled_records = [
        record
        for record in records
        if (
            isinstance(record, dict)
            and str(record.get("surface_type") or "").startswith("profiled_")
        )
    ]
    if not profiled_records:
        return
    model = props.get("maas_model")
    model = model if isinstance(model, dict) else {}
    certificate = props.get("floorwise_visual_projection")
    if not isinstance(certificate, dict):
        certificate = model.get("floorwise_visual_projection")
    if (
        not isinstance(certificate, dict)
        or certificate.get("schema_version")
        != "arr.maas.floorwise_visual_projection.v1"
        or certificate.get("status") != "certified"
        or certificate.get("hard_pass") is not True
    ):
        raise ValueError("piloti authored visual projection is not certified")
    try:
        height = float(props.get("height"))
        if height <= 0.0:
            raise ValueError
        source_surfaces: list[SourceSurface] = []
        for record in profiled_records:
            raw_vertices = record.get("vertices_m")
            if not isinstance(raw_vertices, list) or len(raw_vertices) != 3:
                raise ValueError
            source_surfaces.append(SourceSurface(
                role=str(record.get("role") or ""),
                volume_role=str(record.get("volume_role") or ""),
                verb=str(record.get("verb") or ""),
                surface_type=str(record.get("surface_type") or ""),
                vertices_m=tuple(
                    tuple(float(value) for value in vertex)
                    for vertex in raw_vertices
                ),
                operator=str(record.get("operator") or "extrude"),
                semantic_patch_id=str(
                    record.get("semantic_patch_id") or ""
                ),
            ))
    except (TypeError, ValueError):
        raise ValueError("piloti authored visual projection is malformed") from None
    rebound = clip_and_certify_projected_piloti_visual(
        tuple(source_surfaces),
        certificate,
        void_height_fraction=float(void_height) / height,
    )
    if rebound is None:
        raise ValueError(
            "piloti authored visual projection could not be clipped and capped"
        )
    rebound_surfaces, rebound_certificate = rebound
    rebound_records: list[dict[str, Any]] = []
    for surface in rebound_surfaces:
        record = surface.signature()
        record["vertices_m"] = [
            [float(x), float(y), float(z)]
            for x, y, z in surface.vertices_m
        ]
        rebound_records.append(record)
    props["source_surfaces"] = rebound_records
    props["floorwise_visual_projection"] = rebound_certificate
    model["source_surfaces"] = copy.deepcopy(rebound_records)
    model["floorwise_visual_projection"] = copy.deepcopy(rebound_certificate)


def _apply_piloti_parking_void_in_place(feature: dict[str, Any]) -> None:
    props = feature.setdefault("properties", {})
    strategy = str(props.get("parking_strategy") or "")
    precheck = props.get("parking_precheck") if isinstance(props.get("parking_precheck"), dict) else {}
    layout = precheck.get("layout_candidate") if isinstance(precheck.get("layout_candidate"), dict) else {}
    if strategy != "piloti_ground":
        return
    if not isinstance(layout.get("stalls"), list) or not layout["stalls"]:
        return
    volumes = props.get("mass_volumes")
    if not isinstance(volumes, list) or not volumes:
        return
    floor_height = float(props.get("floor_height") or get_floor_height(str(props.get("building_type") or "")) or 0.0)
    if floor_height <= 0.0:
        return
    void_height = round(max(2.3, min(floor_height, floor_height * 0.92)), 2)
    updated: list[dict[str, Any]] = []
    changed = False
    for volume in volumes:
        if not isinstance(volume, dict):
            continue
        next_volume = dict(volume)
        bottom = float(next_volume.get("bottom_height") or 0.0)
        top = float(next_volume.get("top_height") or 0.0)
        if bottom < void_height and top > void_height:
            next_volume["bottom_height"] = void_height
            next_volume["parking_piloti_void"] = {
                "status": "reserved",
                "void_height_m": void_height,
                "strategy": "piloti_ground",
                "stall_count": len(layout["stalls"]),
                "legal_accounting": "parking void is a mass-stage geometry reservation; legal FAR/BCR metrics remain separately audited",
            }
            source_geometry = next_volume.get("source_geometry")
            if isinstance(source_geometry, dict):
                source_geometry = dict(source_geometry)
                source_geometry["parking_void_basis"] = "piloti_ground_reserved_void"
                next_volume["source_geometry"] = source_geometry
            changed = True
        updated.append(next_volume)
    if not changed:
        return
    grouped: dict[float, list[int]] = {}
    for index, volume in enumerate(updated):
        bottom = round(float(volume.get("bottom_height") or 0.0), 2)
        top = float(volume.get("top_height") or 0.0)
        if top > bottom + 0.8:
            grouped.setdefault(bottom, []).append(index)
    for indexes in grouped.values():
        if len(indexes) < 3:
            continue
        for order, index in enumerate(indexes):
            if order == 0:
                continue
            volume = updated[index]
            bottom = float(volume.get("bottom_height") or 0.0)
            top = float(volume.get("top_height") or 0.0)
            offset = min(0.42, 0.18 * order)
            if top - bottom > offset + 0.65:
                volume["bottom_height"] = round(bottom + offset, 2)
                source_geometry = volume.get("source_geometry")
                if isinstance(source_geometry, dict):
                    source_geometry = dict(source_geometry)
                    source_geometry["parking_void_tier_relief"] = "role_staggered_above_piloti_void"
                    volume["source_geometry"] = source_geometry
    props["mass_volumes"] = updated
    props["source_volumes"] = copy.deepcopy(updated)
    props["parking_piloti_void"] = {
        "status": "reserved",
        "void_height_m": void_height,
        "strategy": "piloti_ground",
        "stall_count": len(layout["stalls"]),
    }
    model = props.get("maas_model")
    if isinstance(model, dict):
        model["volumes"] = updated
        model["source_volumes"] = copy.deepcopy(updated)
        model["parking_piloti_void"] = props["parking_piloti_void"]
    _rebind_projected_surfaces_after_piloti_void(
        feature,
        void_height=void_height,
    )
    evidence = props.get("floorwise_legal_evidence")
    if isinstance(evidence, dict):
        subtractions = evidence.get("post_validation_subtractions")
        if not isinstance(subtractions, list):
            subtractions = []
        if "piloti_parking_void" not in subtractions:
            subtractions.append("piloti_parking_void")
        evidence["post_validation_subtractions"] = subtractions
        evidence["checked_mass_volume_count"] = len(updated)
        evidence["canonical_geometry_immutable_after_parking"] = True
        if isinstance(model, dict):
            model["floorwise_legal_evidence"] = evidence
    _attach_visual_diversity_evidence(feature)


def _apply_piloti_parking_void(feature: dict[str, Any]) -> None:
    """Commit parking volume and visual changes only after both validate."""

    props = (
        feature.get("properties")
        if isinstance(feature.get("properties"), dict)
        else {}
    )
    precheck = (
        props.get("parking_precheck")
        if isinstance(props.get("parking_precheck"), dict)
        else {}
    )
    layout = (
        precheck.get("layout_candidate")
        if isinstance(precheck.get("layout_candidate"), dict)
        else {}
    )
    if (
        str(props.get("parking_strategy") or "") != "piloti_ground"
        or not isinstance(layout.get("stalls"), list)
        or not layout["stalls"]
        or not isinstance(props.get("mass_volumes"), list)
        or not props["mass_volumes"]
    ):
        return
    candidate = copy.deepcopy(feature)
    _apply_piloti_parking_void_in_place(candidate)
    candidate_props = candidate.pop("properties")
    feature.clear()
    feature.update(candidate)
    props.clear()
    props.update(candidate_props)
    feature["properties"] = props


def _source_profile_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Distance between ARR-native source grammar signatures."""
    left = _source_signature(a)
    right = _source_signature(b)
    if not left and not right:
        return 0.0
    if not left or not right:
        return 0.65
    family_distance = 0.0 if str(left.get("family") or "") == str(right.get("family") or "") else 1.0
    verbs_distance = sequence_distance(
        [str(item) for item in left.get("verb_profile") or []],
        [str(item) for item in right.get("verb_profile") or []],
    )
    volume_distance = min(1.0, abs(float(left.get("volume_count") or 0.0) - float(right.get("volume_count") or 0.0)) / 4.0)
    surface_distance = min(1.0, abs(float(left.get("surface_count") or 0.0) - float(right.get("surface_count") or 0.0)) / 24.0)
    ratio_distance = min(1.0, abs(float(left.get("upper_to_ground_ratio") or 0.0) - float(right.get("upper_to_ground_ratio") or 0.0)))
    left_profile = _source_area_profile(a)
    right_profile = _source_area_profile(b)
    if left_profile and right_profile:
        pairs = zip(left_profile, right_profile)
        denom = max(max(left_profile), max(right_profile), 1.0)
        area_distance = min(1.0, sum(abs(x - y) for x, y in pairs) / (denom * max(len(left_profile), len(right_profile), 1)))
        area_distance = max(area_distance, min(1.0, abs(len(left_profile) - len(right_profile)) / 4.0))
    else:
        area_distance = 0.0
    return round(
        family_distance * 0.32
        + verbs_distance * 0.28
        + volume_distance * 0.10
        + surface_distance * 0.08
        + ratio_distance * 0.12
        + area_distance * 0.10,
        4,
    )


def _feature_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    """MAAS-style alt distance: geometry, 3D metrics, and verb sequence."""
    try:
        geom_distance = 1.0 - polygon_iou(geojson_to_polygon(a["geometry"]), geojson_to_polygon(b["geometry"]))
    except Exception:
        geom_distance = 0.0
    av = _normalized_feature_vector(a)
    bv = _normalized_feature_vector(b)
    metric_distance = sum(abs(x - y) for x, y in zip(av, bv)) / max(1, len(av))
    seq_distance = sequence_distance(
        sequence_verbs((a.get("properties") or {}).get("maas_verb_sequence")),
        sequence_verbs((b.get("properties") or {}).get("maas_verb_sequence")),
    )
    concept_distance = 0.0 if _operator_family((a.get("properties") or {}).get("mass_shape", "")) == _operator_family((b.get("properties") or {}).get("mass_shape", "")) else 1.0
    source_distance = _source_profile_distance(a, b)
    return round(
        geom_distance * 0.24
        + metric_distance * 0.18
        + seq_distance * 0.24
        + concept_distance * 0.10
        + source_distance * 0.24,
        4,
    )


def _kmedoid_representatives(
    candidates: list[dict[str, Any]],
    *,
    k: int,
    anchors: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Pick diverse representatives using the clone/MAAS diversity-kmedoids pattern.

    The clone uses mesh complexity + convexity + verb Jaccard. ARR does not
    depend on STL meshes at runtime, so the same idea is applied to legal
    GeoJSON features: footprint IoU, normalized mass metrics, and MAAS verb
    sequence distance.
    """
    if k <= 0 or not candidates:
        return []
    anchors = anchors or []
    picked: list[dict[str, Any]] = []
    distance_cache: dict[tuple[int, int], float] = {}

    def distance(a: dict[str, Any], b: dict[str, Any]) -> float:
        key = tuple(sorted((id(a), id(b))))
        if key not in distance_cache:
            distance_cache[key] = _feature_distance(a, b)
        return distance_cache[key]

    def min_distance_to_selection(feature: dict[str, Any]) -> float:
        selected = anchors + picked
        if not selected:
            return 1.0
        return min(distance(feature, item) for item in selected)

    first = max(
        candidates,
        key=lambda feature: (
            min_distance_to_selection(feature),
            _capacity_score(feature.get("properties", {}) or {}),
        ),
    )
    picked.append(first)

    while len(picked) < min(k, len(candidates)):
        remaining = [feature for feature in candidates if feature not in picked]
        if not remaining:
            break
        picked.append(max(
            remaining,
            key=lambda feature: (
                min_distance_to_selection(feature),
                _capacity_score(feature.get("properties", {}) or {}),
            ),
        ))

    return picked


def _critic_objective_vector(feature: dict[str, Any]) -> tuple[float, ...]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    order = props.get("orderliness_evidence") if isinstance(props.get("orderliness_evidence"), dict) else {}
    signature = _source_signature(feature)
    coherence = signature.get("coherence_evidence") if isinstance(signature.get("coherence_evidence"), dict) else {}
    performance = props.get("performance_proxy_evidence") if isinstance(props.get("performance_proxy_evidence"), dict) else {}
    return (
        1.0 if _architectural_order_gate(feature)[0] else 0.0,
        1.0 if final_mass_stage_parking_pass(feature) else 0.0,
        1.0 if coherence.get("hard_pass", True) else 0.0,
        float(coherence.get("score") or 0.0),
        preference_score(feature),
        float(order.get("orderliness_score") or 0.0),
        _repair_retention(feature),
        float(performance.get("aggregate_performance_proxy") or 0.0),
        -float(signature.get("effective_surface_count") or signature.get("surface_count") or 0.0) / float(ARCHITECTURAL_ORDER_POLICY["max_source_surfaces"]),
        -float(_visible_volume_count(feature)) / 4.0,
        -float(order.get("small_fragment_count") or 0.0),
        -float(order.get("plan_component_count") or 1.0),
    )


def _pareto_front(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    vectors = {id(feature): _critic_objective_vector(feature) for feature in candidates}

    def dominates(left: tuple[float, ...], right: tuple[float, ...]) -> bool:
        return all(a >= b for a, b in zip(left, right)) and any(a > b for a, b in zip(left, right))

    return [
        feature for feature in candidates
        if not any(
            other is not feature and dominates(vectors[id(other)], vectors[id(feature)])
            for other in candidates
        )
    ]


def _maas_verb_sequence(operator: str) -> list[dict[str, Any]]:
    """Architectural-language tags adapted from the MAAS verb grammar repo."""
    base = [{"verb": "base", "params": {"proportion": "1/1"}}]
    op = operator[:-8] if operator.endswith("_layered") else operator
    recipes: dict[str, list[dict[str, Any]]] = {
        "legal_layered_max": [{"verb": "taper", "params": {"top_ratio": 0.72}}],
        "legal_buildable_max": [{"verb": "taper", "params": {"top_ratio": 0.72}}],
        "notch_north_west": [{"verb": "notch", "params": {"corner": "-x+y"}}],
        "notch_north_east": [{"verb": "notch", "params": {"corner": "+x+y"}}],
        "notch_south_west": [{"verb": "notch", "params": {"corner": "-x-y"}}],
        "notch_south_east": [{"verb": "notch", "params": {"corner": "+x-y"}}],
        "court_open_north": [{"verb": "cave", "params": {"face": "+y"}}],
        "court_open_south": [{"verb": "cave", "params": {"face": "-y"}}],
        "court_open_east": [{"verb": "cave", "params": {"face": "+x"}}],
        "court_open_west": [{"verb": "cave", "params": {"face": "-x"}}],
        "courtyard_void": [{"verb": "puncture", "params": {"axis": "z"}}],
        "split_bridge_x": [{"verb": "split", "params": {"axis": "x"}}],
        "split_bridge_y": [{"verb": "split", "params": {"axis": "y"}}],
        "branch_y_soft": [{"verb": "branch", "params": {"angle": 28.0}}],
        "branch_y_wide": [{"verb": "branch", "params": {"angle": 42.0}}],
        "pinch_waist_x": [{"verb": "pinch", "params": {"axis": "x"}}],
        "pinch_waist_y": [{"verb": "pinch", "params": {"axis": "y"}}],
        "interlock_cross_soft": [{"verb": "interlock", "params": {"cross_axis": "z"}}, {"verb": "rotate_part", "params": {"axis": "z", "angle": 28.0}}],
        "interlock_cross_diagonal": [{"verb": "interlock", "params": {"cross_axis": "z"}}, {"verb": "rotate_part", "params": {"axis": "z", "angle": -34.0}}],
        "overlap_slabs_x": [{"verb": "overlap", "params": {"offset_vec": [0.5, 0.2, 0.0]}}],
        "overlap_slabs_y": [{"verb": "overlap", "params": {"offset_vec": [0.2, 0.5, 0.0]}}],
        "terrace_stepback": [{"verb": "grade", "params": {"axis": "+z"}}, {"verb": "taper", "params": {"top_ratio": 0.68}}],
        "shifted_tower": [{"verb": "lift", "params": {"other": "6/8"}}, {"verb": "shift", "params": {"axis": "x"}}],
        "tapered_slab": [{"verb": "taper", "params": {"top_ratio": 0.58}}],
        "grade_terrace_north": [{"verb": "grade", "params": {"axis": "+y"}}],
        "lift_overlap_slabs": [{"verb": "overlap", "params": {"offset_vec": [0.4, 0.2, 0.0]}}, {"verb": "lift", "params": {"other": "6/8"}}],
        "diagonal_connect_step_x": [{"verb": "diagonal_connect", "params": {"axis": "x", "upper_ratio": 0.72, "distance_ratio": 0.12}}],
        "diagonal_connect_step_y": [{"verb": "diagonal_connect", "params": {"axis": "y", "upper_ratio": 0.72, "distance_ratio": 0.12}}],
        "terrace_link_north": [{"verb": "terrace_link", "params": {"side": "north", "upper_ratio": 0.84}}],
        "sloped_roof_mass": [{"verb": "sloped_roof_mass", "params": {"upper_ratio": 0.90, "x_ratio": 0.70, "y_ratio": 0.92}}],
        "parking_repair_single_bar": [
            {"verb": "compress", "params": {"axis": "y", "factor": 0.72}},
            {"verb": "taper", "params": {"top_ratio": 0.86}},
        ],
        "parking_repair_tapered_slab": [
            {"verb": "lift", "params": {"upper_ratio": 0.72, "lower_floor_fraction": 0.30}},
            {"verb": "taper", "params": {"x_ratio": 0.72, "y_ratio": 0.80}},
        ],
        "parking_repair_split_bridge": [
            {"verb": "split", "params": {"axis": "x", "gap_ratio": 0.18, "bridge_ratio": 0.20}},
            {"verb": "lift", "params": {"upper_ratio": 0.76, "lower_floor_fraction": 0.32}},
            {"verb": "taper", "params": {"x_ratio": 0.82, "y_ratio": 0.86}},
        ],
        "parking_repair_diagonal_connector": [
            {"verb": "lift", "params": {"upper_ratio": 0.78, "lower_floor_fraction": 0.24}},
            {"verb": "diagonal_connect", "params": {"axis": "x", "upper_ratio": 0.86, "distance_ratio": 0.12, "lower_floor_fraction": 0.24}},
            {"verb": "taper", "params": {"x_ratio": 0.86, "y_ratio": 0.92}},
        ],
        "parking_repair_terrace_ribbon": [
            {"verb": "lift", "params": {"upper_ratio": 0.82, "lower_floor_fraction": 0.22}},
            {"verb": "terrace_link", "params": {"side": "north", "upper_ratio": 0.88, "width_ratio": 0.62, "depth_ratio": 0.20, "lower_floor_fraction": 0.22}},
            {"verb": "shift", "params": {"axis": "y", "distance_ratio": -0.04}},
        ],
        "parking_repair_sloped_roof_mass": [
            {"verb": "sloped_roof_mass", "params": {"upper_ratio": 0.90, "x_ratio": 0.70, "y_ratio": 0.92, "lower_floor_fraction": 0.28}},
            {"verb": "taper", "params": {"x_ratio": 0.88, "y_ratio": 0.94}},
        ],
    }
    if op.startswith("slender_bar"):
        return base + [{"verb": "compress", "params": {"axis": "x" if op.endswith(("east", "west")) else "y", "factor": 0.54}}]
    if op.startswith("bcr_fill"):
        return base + [{"verb": "expand", "params": {"face": "+x"}}, {"verb": "expand", "params": {"face": "+y"}}]
    if op.startswith("inset"):
        return base + [{"verb": "compress", "params": {"axis": "x", "factor": 0.92}}, {"verb": "compress", "params": {"axis": "y", "factor": 0.92}}]
    return base + recipes.get(op, [{"verb": op, "params": {}}])


def _compact_visual_volumes(floor_plates: list[dict[str, Any]], operator: str) -> list[dict[str, Any]]:
    """Build the MAAS volume representation from legal floor plates.

    The volume geometry is not a separate render-only artifact. It is the
    user-facing MAAS mass, and it is derived from floor plates that have already
    been clipped by the legal envelope. Using each band's top plate keeps the
    full volume inside the same legal envelope.
    """
    if not floor_plates:
        return []
    n = len(floor_plates)
    family = _operator_family(operator)
    areas = [float(plate.get("area") or 0.0) for plate in floor_plates]
    max_area = max(areas) if areas else 0.0
    min_area = min(areas) if areas else 0.0
    has_layered_envelope_steps = (
        family == "legal_layered"
        and n >= 3
        and max_area > 0.0
        and (max_area - min_area) / max_area >= 0.08
    )
    wants_stepped_display = (
        has_layered_envelope_steps
        or "step" in operator
        or "terrace" in operator
        or "grade" in operator
        or "diagonal_connect" in operator
        or "sloped_roof" in operator
        or family in {"stepback_tower", "grade"}
    )
    if has_layered_envelope_steps:
        # A legal floor stack may change at every floor, but exposing every
        # legal slice as a design volume produces the fragmented 6--7 piece
        # masses the visual critic is intended to reject. Preserve the legal
        # profile with at most four architectural bands: the top, bottom and
        # the strongest relative step changes in between.
        change_endpoints = list(range(n - 1))
        if len(change_endpoints) > 3:
            ranked_changes = sorted(
                range(1, n),
                key=lambda index: (
                    abs(areas[index] - areas[index - 1]) / max(areas[index - 1], 1e-9),
                    index,
                ),
                reverse=True,
            )
            selected = {n - 1}
            selected.update(index - 1 for index in ranked_changes[:3])
            change_endpoints = sorted(selected)[:4]
            if n - 1 not in change_endpoints:
                change_endpoints[-1] = n - 1
                change_endpoints.sort()
        cuts = []
        start = 0
        for end in change_endpoints:
            if start <= end:
                cuts.append((start, end))
                start = end + 1
        if start < n:
            cuts.append((start, n - 1))
    elif wants_stepped_display and n >= 4:
        raw_cuts = [
            (0, max(0, n // 4 - 1)),
            (max(0, n // 4), max(0, n // 2 - 1)),
            (max(0, n // 2), max(0, (n * 3) // 4 - 1)),
            (max(0, (n * 3) // 4), n - 1),
        ]
        cuts = []
        for start, end in raw_cuts:
            if start <= end and (not cuts or cuts[-1] != (start, end)):
                cuts.append((start, end))
    elif n <= 2:
        cuts = [(0, n - 1)]
    elif family in {"legal_layered", "stepback_tower", "taper", "grade"}:
        cuts = [(0, max(0, n // 3)), (max(0, n // 3 + 1), n - 1)]
    else:
        cuts = [(0, max(0, n // 2)), (max(0, n // 2 + 1), n - 1)]

    volumes: list[dict[str, Any]] = []
    previous_top = 0.0
    for band_index, (start, end) in enumerate(cuts):
        if start > end or end >= n:
            continue
        top_plate = floor_plates[end]
        top_height = float(top_plate.get("top_height") or 0.0)
        if top_height <= previous_top:
            continue
        volumes.append({
            "band": band_index,
            "bottom_height": round(previous_top, 2),
            "top_height": round(top_height, 2),
            "geometry": top_plate.get("geometry"),
            "role": "morphology_volume",
        })
        previous_top = top_height
    return volumes


def _maas_model(
    *,
    operator: str,
    floor_plates: list[dict[str, Any]],
    props: dict[str, Any],
    site_area_m2: float,
) -> dict[str, Any]:
    """Single integrated object for agents/frontend: morphology + legal audit."""
    return {
        "algorithm": "maas_legal_envelope",
        "operator": operator,
        "verb_sequence": _maas_verb_sequence(operator),
        "volumes": _compact_visual_volumes(floor_plates, operator),
        "floor_plates": floor_plates,
        "floor_groups": build_floor_groups(
            floor_plates,
            site_area_m2=site_area_m2,
            building_type=str(props.get("building_type") or ""),
        ),
        "legal_metrics": {
            "far": props.get("far"),
            "bcr": props.get("bcr"),
            "height": props.get("height"),
            "num_floors": props.get("num_floors"),
            "footprint_area": props.get("footprint_area"),
            "floor_area": props.get("floor_area"),
            "min_setback": props.get("min_setback"),
            "open_pct": props.get("open_pct"),
        },
    }


def _section_profile_from_sequence(
    *,
    operator: str,
    sequence: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    props: dict[str, Any],
) -> dict[str, Any] | None:
    """Expose section-design intent separately from legal volume accounting.

    FAR/BCR and legality still use volumes/floor plates. This profile is the
    canonical design/raster-render hint derived from the MAAS verb sequence, so
    diagonal/terrace/sloped candidates do not collapse visually into identical
    stacked boxes.
    """
    calls = [call for call in sequence or [] if isinstance(call, dict)]
    verb_params = {
        str(call.get("verb") or ""): call.get("params") if isinstance(call.get("params"), dict) else {}
        for call in calls
    }

    def profile_for(verb_name: str) -> dict[str, Any] | None:
        for candidate in calls:
            if str(candidate.get("verb") or "") == verb_name:
                params = candidate.get("params") if isinstance(candidate.get("params"), dict) else {}
                return params
        return None

    signature = props.get("source_signature")
    if not isinstance(signature, dict):
        model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
        signature = model.get("source_signature") if isinstance(model.get("source_signature"), dict) else {}
    declared_family = str(signature.get("family") or "")
    family_profile = {
        "courtyard": ("courtyard_atrium", "derive_courtyard_section_from_llm_declared_family"),
        "void_notch": ("notched_void", "derive_void_section_from_llm_declared_family"),
        "slender_bar": ("bar_notch_terrace", "derive_bar_section_from_llm_declared_family"),
        "offset": ("offset_twin_bar", "derive_offset_section_from_llm_declared_family"),
        "array_cluster": ("array_cluster", "derive_array_cluster_section_from_llm_declared_family"),
        "reflected_pair": ("reflected_court_pair", "derive_reflected_pair_section_from_llm_declared_family"),
        "split": ("split_bridge", "derive_split_section_from_llm_declared_family"),
        "branch": ("branch_taper", "derive_branch_section_from_llm_declared_family"),
        "pinch": ("pinched_waist", "derive_pinch_section_from_llm_declared_family"),
        "interlock": ("cross_interlock", "derive_interlock_section_from_llm_declared_family"),
        "overlap": ("overlap_slabs", "derive_overlap_section_from_llm_declared_family"),
        "diagonal_connect": ("diagonal_connector", "derive_diagonal_section_from_llm_declared_family"),
        "sloped_roof": ("sloped_roof", "derive_roof_section_from_llm_declared_family"),
        "bend": ("bend_ribbon", "derive_bend_section_from_llm_declared_family"),
        "embed": ("embedded_void", "derive_embed_section_from_llm_declared_family"),
        "extrude": ("extruded_fin", "derive_extrude_section_from_llm_declared_family"),
        "nest": ("nested_stack", "derive_nest_section_from_llm_declared_family"),
    }.get(declared_family)
    if operator.startswith("llm_") and family_profile is not None:
        profile_kind, render_hint = family_profile
        return {
            "kind": profile_kind,
            "source": "llm_declared_source_family",
            "operator": operator,
            "render_hint": render_hint,
        }

    # Section-defining verbs should win over generic cut/stack verbs even when
    # the sequence introduces the legal split or void first.
    diagonal_params = profile_for("diagonal_connect")
    if diagonal_params is not None:
        params = diagonal_params
        return {
            "kind": "diagonal_connector",
            "source": "maas_verb_sequence",
            "operator": operator,
            "axis": params.get("axis", "x"),
            "upper_ratio": float(params.get("upper_ratio", 0.72)),
            "distance_ratio": float(params.get("distance_ratio", 0.10)),
            "lower_floor_fraction": float(params.get("lower_floor_fraction", props.get("step_floor", 0.40) or 0.40)),
            "render_hint": "draw_inclined_connector_between_lower_and_upper_masses",
        }
    terrace_params = profile_for("terrace_link")
    if terrace_params is not None:
        params = terrace_params
        return {
            "kind": "terrace_ribbon",
            "source": "maas_verb_sequence",
            "operator": operator,
            "side": params.get("side", "north"),
            "upper_ratio": float(params.get("upper_ratio", 0.84)),
            "width_ratio": float(params.get("width_ratio", 0.62)),
            "depth_ratio": float(params.get("depth_ratio", 0.20)),
            "render_hint": "draw_continuous_terrace_bands_not_isolated_boxes",
        }
    sloped_params = profile_for("sloped_roof_mass")
    if sloped_params is not None:
        params = sloped_params
        return {
            "kind": "sloped_roof",
            "source": "maas_verb_sequence",
            "operator": operator,
            "upper_ratio": float(params.get("upper_ratio", 0.90)),
            "x_ratio": float(params.get("x_ratio", 0.70)),
            "y_ratio": float(params.get("y_ratio", 0.92)),
            "render_hint": "draw_sloped_envelope_plane_over_mass",
        }
    if operator.startswith(("agent_", "llm_")):
        offset_params = profile_for("offset")
        if offset_params is not None:
            return {
                "kind": "offset_twin_bar",
                "source": "authored_maas_verb_sequence",
                "operator": operator,
                "axis": offset_params.get("axis", "x"),
                "distance_ratio": float(offset_params.get("distance_ratio", 0.16)),
                "render_hint": "derive_offset_twin_bars_from_authored_arch_language",
            }
        reflect_params = profile_for("reflect")
        if reflect_params is not None:
            return {
                "kind": "reflected_court_pair",
                "source": "authored_maas_verb_sequence",
                "operator": operator,
                "axis": reflect_params.get("axis", "x"),
                "render_hint": "derive_reflected_court_pair_from_authored_arch_language",
            }
        array_params = profile_for("array")
        if array_params is not None:
            return {
                "kind": "array_cluster",
                "source": "authored_maas_verb_sequence",
                "operator": operator,
                "count": int(array_params.get("count", 3) or 3),
                "axis": array_params.get("axis", "x"),
                "spacing_ratio": float(array_params.get("spacing_ratio", 0.08)),
                "render_hint": "derive_clustered_multi_volume_array_from_authored_arch_language",
            }

    for call in calls:
        verb = str(call.get("verb") or "")
        params = call.get("params") if isinstance(call.get("params"), dict) else {}
        if verb == "diagonal_connect":
            return {
                "kind": "diagonal_connector",
                "source": "maas_verb_sequence",
                "operator": operator,
                "axis": params.get("axis", "x"),
                "upper_ratio": float(params.get("upper_ratio", 0.72)),
                "distance_ratio": float(params.get("distance_ratio", 0.10)),
                "lower_floor_fraction": float(params.get("lower_floor_fraction", props.get("step_floor", 0.40) or 0.40)),
                "render_hint": "draw_inclined_connector_between_lower_and_upper_masses",
            }
        if verb == "terrace_link":
            return {
                "kind": "terrace_ribbon",
                "source": "maas_verb_sequence",
                "operator": operator,
                "side": params.get("side", "north"),
                "upper_ratio": float(params.get("upper_ratio", 0.84)),
                "width_ratio": float(params.get("width_ratio", 0.62)),
                "depth_ratio": float(params.get("depth_ratio", 0.20)),
                "render_hint": "draw_continuous_terrace_bands_not_isolated_boxes",
            }
        if verb == "sloped_roof_mass":
            return {
                "kind": "sloped_roof",
                "source": "maas_verb_sequence",
                "operator": operator,
                "upper_ratio": float(params.get("upper_ratio", 0.90)),
                "x_ratio": float(params.get("x_ratio", 0.70)),
                "y_ratio": float(params.get("y_ratio", 0.92)),
                "render_hint": "draw_sloped_envelope_plane_over_mass",
            }
        if verb == "split":
            lift_params = verb_params.get("lift", {})
            return {
                "kind": "split_bridge",
                "source": "maas_verb_sequence",
                "operator": operator,
                "axis": params.get("axis", "x"),
                "gap_ratio": float(params.get("gap_ratio", 0.14)),
                "bridge_ratio": float(params.get("bridge_ratio", 0.18)),
                "upper_ratio": float(lift_params.get("upper_ratio", 0.76)),
                "lower_floor_fraction": float(lift_params.get("lower_floor_fraction", props.get("step_floor", 0.35) or 0.35)),
                "render_hint": "derive_split_bridge_from_maas_split_and_lift_params",
            }
        if verb == "overlap":
            offset_vec = params.get("offset_vec") if isinstance(params.get("offset_vec"), list) else [0.35, 0.18, 0.0]
            return {
                "kind": "overlap_slabs",
                "source": "maas_verb_sequence",
                "operator": operator,
                "offset_vec": [float(item or 0.0) for item in offset_vec[:3]],
                "render_hint": "derive_alternating_offsets_from_maas_overlap_vector",
            }
        if verb == "interlock":
            rotate_params = verb_params.get("rotate_part", {})
            return {
                "kind": "cross_interlock",
                "source": "maas_verb_sequence",
                "operator": operator,
                "cross_axis": params.get("cross_axis", "z"),
                "angle": float(rotate_params.get("angle", 24.0)),
                "render_hint": "derive_cross_interlock_from_interlock_and_rotate_part_verbs",
            }
        if verb == "branch":
            return {
                "kind": "branch_taper",
                "source": "maas_verb_sequence",
                "operator": operator,
                "angle": float(params.get("angle", 30.0)),
                "render_hint": "derive_branch_shift_from_maas_branch_angle",
            }
        if verb == "bend":
            return {
                "kind": "bend_ribbon",
                "source": "maas_verb_sequence",
                "operator": operator,
                "axis": params.get("axis", "y"),
                "angle": float(params.get("angle", 28.0)),
                "factor": float(params.get("factor", 0.58)),
                "render_hint": "derive_bent_ribbon_from_maas_bend_angle",
            }
        if verb == "embed":
            return {
                "kind": "embedded_void",
                "source": "maas_verb_sequence",
                "operator": operator,
                "guest_scale": float(params.get("guest_scale", 0.42)),
                "position": params.get("position") if isinstance(params.get("position"), list) else [0.0, 0.0, 0.0],
                "render_hint": "derive_inner_void_and_offset_upper_from_maas_embed",
            }
        if verb == "extrude":
            return {
                "kind": "extruded_fin",
                "source": "maas_verb_sequence",
                "operator": operator,
                "axis": params.get("axis", "x"),
                "length": float(params.get("length", 0.36)),
                "size": float(params.get("size", 0.34)),
                "render_hint": "derive_fin_like_extension_from_maas_extrude",
            }
        if verb in {"nest", "stack"}:
            nest_params = verb_params.get("nest", {})
            stack_params = verb_params.get("stack", {})
            return {
                "kind": "nested_stack",
                "source": "maas_verb_sequence",
                "operator": operator,
                "inner_scale": float(nest_params.get("inner_scale", 0.46)),
                "stack_count": int(stack_params.get("n", 3) or 3),
                "stack_gap": float(stack_params.get("gap", 0.04)),
                "upper_ratio": float(stack_params.get("upper_ratio", 0.76)),
                "render_hint": "derive_nested_atrium_stack_from_maas_nest_stack",
            }
        if verb == "pinch":
            return {
                "kind": "pinched_waist",
                "source": "maas_verb_sequence",
                "operator": operator,
                "axis": params.get("axis", "x"),
                "render_hint": "derive_upper_waist_from_maas_pinch_axis",
            }
        if verb == "taper":
            return {
                "kind": "stepped_tower",
                "source": "maas_verb_sequence",
                "operator": operator,
                "top_ratio": float(params.get("top_ratio", params.get("x_ratio", 0.72))),
                "x_ratio": float(params.get("x_ratio", params.get("top_ratio", 0.72))),
                "y_ratio": float(params.get("y_ratio", params.get("top_ratio", 0.72))),
                "render_hint": "derive_stepback_from_maas_taper_params",
            }
        if verb in {"notch", "cave", "puncture"}:
            return {
                "kind": "notched_void",
                "source": "maas_verb_sequence",
                "operator": operator,
                "face": params.get("face") or params.get("corner") or params.get("axis") or "+y",
                "render_hint": "derive_void_from_maas_notch_cave_or_puncture_verb",
            }
        if verb == "grade":
            taper_params = verb_params.get("taper", {})
            return {
                "kind": "bar_notch_terrace",
                "source": "maas_verb_sequence",
                "operator": operator,
                "axis": params.get("axis", "+z"),
                "top_ratio": float(taper_params.get("top_ratio", 0.72)),
                "render_hint": "derive_terrace_recession_from_maas_grade_axis",
            }
    family = _operator_family(operator)
    if family in {"diagonal_connect", "terrace_link", "sloped_roof"}:
        profile_kind = {
            "diagonal_connect": "diagonal_connector",
            "terrace_link": "terrace_ribbon",
            "sloped_roof": "sloped_roof",
        }[family]
        return {
            "kind": profile_kind,
            "source": "operator_family",
            "operator": operator,
            "render_hint": "derive_section_profile_from_operator_family",
        }
    family_profile = {
        "slender_bar": ("bar_notch_terrace", "derive_bar_recession_from_operator_family_when_sequence_has_only_compress"),
        "courtyard": ("courtyard_atrium", "derive_courtyard_upper_recession_from_operator_family_when_sequence_has_only_puncture"),
        "void_notch": ("notched_void", "derive_notch_from_operator_family_when_sequence_has_only_footprint_cut"),
        "bend": ("bend_ribbon", "derive_bend_ribbon_from_operator_family"),
        "embed": ("embedded_void", "derive_embedded_void_from_operator_family"),
        "extrude": ("extruded_fin", "derive_extruded_fin_from_operator_family"),
        "nest": ("nested_stack", "derive_nested_stack_from_operator_family"),
    }.get(family)
    if family_profile is not None:
        profile_kind, render_hint = family_profile
        return {
            "kind": profile_kind,
            "source": "operator_family",
            "operator": operator,
            "family": family,
            "render_hint": render_hint,
        }
    return None


def _attach_section_profile(feature: dict[str, Any]) -> None:
    props = feature.setdefault("properties", {})
    sequence = props.get("maas_verb_sequence")
    profile = _section_profile_from_sequence(
        operator=str(props.get("mass_shape") or ""),
        sequence=sequence,
        props=props,
    )
    if profile is None:
        return
    props["section_profile"] = profile
    model = props.get("maas_model")
    if isinstance(model, dict):
        model["section_profile"] = profile


def _largest_polygon_or_none(geometry) -> Any | None:
    if geometry is None or geometry.is_empty:
        return None
    if geometry.geom_type == "Polygon":
        return geometry if geometry.area >= 1.0 else None
    if geometry.geom_type == "MultiPolygon":
        try:
            poly = largest_polygon(geometry)
            return poly if poly.area >= 1.0 else None
        except Exception:
            return None
    polygons = [
        item for item in getattr(geometry, "geoms", [])
        if getattr(item, "geom_type", None) == "Polygon" and item.area >= 1.0
    ]
    if not polygons:
        return None
    return max(polygons, key=lambda item: item.area)


def _section_materialized_polygon(base_utm, *, profile: dict[str, Any], progress: float, bounds: tuple[float, float, float, float]):
    minx, miny, maxx, maxy = bounds
    span_x = maxx - minx
    span_y = maxy - miny
    kind = str(profile.get("kind") or "")
    def clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    if kind == "sloped_roof":
        x_ratio = max(0.42, 1.0 - (1.0 - float(profile.get("x_ratio") or 0.70)) * progress)
        y_ratio = max(0.58, 1.0 - (1.0 - float(profile.get("y_ratio") or 0.92)) * progress)
        shifted = shapely_translate(
            shapely_scale(base_utm, xfact=x_ratio, yfact=y_ratio, origin="centroid"),
            yoff=-span_y * 0.045 * progress,
        )
        return shifted.intersection(base_utm)

    if kind == "terrace_ribbon":
        side = str(profile.get("side") or "north")
        y_shift = -span_y * 0.085 * progress if side != "south" else span_y * 0.085 * progress
        x_shift = span_x * 0.025 * progress
        shaped = shapely_translate(
            shapely_scale(base_utm, xfact=max(0.78, 1.0 - 0.06 * progress), yfact=1.0, origin="centroid"),
            xoff=x_shift,
            yoff=y_shift,
        )
        return shaped.intersection(base_utm)

    if kind in {"diagonal_connector", "diagonal_connect"}:
        axis = str(profile.get("axis") or "x")
        distance = float(profile.get("distance_ratio") or 0.10)
        x_shift = span_x * distance * progress if axis == "x" else span_x * 0.035 * progress
        y_shift = span_y * distance * progress if axis == "y" else span_y * 0.055 * progress
        shaped = shapely_translate(
            shapely_scale(base_utm, xfact=max(0.76, 1.0 - 0.14 * progress), yfact=max(0.76, 1.0 - 0.14 * progress), origin="centroid"),
            xoff=x_shift,
            yoff=y_shift,
        )
        return shaped.intersection(base_utm)

    if kind == "cross_interlock":
        angle = clamp(float(profile.get("angle") or 0.0), -42.0, 42.0) * progress
        rotation_factor = min(1.0, abs(angle) / 42.0)
        shaped = shapely_rotate(
            shapely_scale(
                base_utm,
                xfact=clamp(1.0 - 0.18 * rotation_factor * progress, 0.70, 1.0),
                yfact=clamp(1.0 - 0.10 * rotation_factor * progress, 0.76, 1.0),
                origin="centroid",
            ),
            angle,
            origin="centroid",
        )
        shaped = shapely_translate(shaped, xoff=span_x * 0.025 * rotation_factor * progress, yoff=-span_y * 0.018 * rotation_factor * progress)
        return shaped.intersection(base_utm)

    if kind == "split_bridge":
        gap_ratio = clamp(float(profile.get("gap_ratio") or 0.14), 0.04, 0.28)
        bridge_ratio = clamp(float(profile.get("bridge_ratio") or 0.18), 0.08, 0.36)
        axis = str(profile.get("axis") or "x")
        direction = -1 if int(progress * 10) % 2 else 1
        x_shift = direction * span_x * gap_ratio * 0.25 * progress if axis == "x" else 0.0
        y_shift = direction * span_y * gap_ratio * 0.25 * progress if axis == "y" else span_y * bridge_ratio * 0.12 * progress
        shaped = shapely_translate(
            shapely_scale(
                base_utm,
                xfact=clamp(1.0 - (gap_ratio + bridge_ratio * 0.35) * progress, 0.64, 1.0) if axis == "x" else clamp(1.0 - bridge_ratio * 0.30 * progress, 0.78, 1.0),
                yfact=clamp(1.0 - (gap_ratio + bridge_ratio * 0.35) * progress, 0.64, 1.0) if axis == "y" else clamp(1.0 - bridge_ratio * 0.30 * progress, 0.78, 1.0),
                origin="centroid",
            ),
            xoff=x_shift,
            yoff=y_shift,
        )
        return shaped.intersection(base_utm)

    if kind == "courtyard_atrium":
        shaped = shapely_translate(
            shapely_scale(
                base_utm,
                xfact=max(0.72, 1.0 - 0.14 * progress),
                yfact=max(0.72, 1.0 - 0.14 * progress),
                origin="centroid",
            ),
            yoff=-span_y * 0.035 * progress,
        )
        return shaped.intersection(base_utm)

    if kind == "branch_taper":
        angle = clamp(float(profile.get("angle") or 0.0), -45.0, 45.0)
        angle_factor = min(1.0, abs(angle) / 45.0)
        shaped = shapely_rotate(
            shapely_scale(
                base_utm,
                xfact=clamp(1.0 - 0.24 * angle_factor * progress, 0.62, 1.0),
                yfact=clamp(1.0 - 0.10 * progress, 0.74, 1.0),
                origin="centroid",
            ),
            angle * 0.28 * progress,
            origin="centroid",
        )
        return shapely_translate(shaped, xoff=-span_x * 0.05 * angle_factor * progress, yoff=span_y * 0.05 * progress).intersection(base_utm)

    if kind == "bend_ribbon":
        angle = clamp(float(profile.get("angle") or 28.0), -42.0, 42.0)
        shaped = shapely_rotate(
            shapely_scale(
                base_utm,
                xfact=clamp(1.0 - 0.18 * progress, 0.70, 1.0),
                yfact=clamp(1.0 - 0.08 * progress, 0.80, 1.0),
                origin="centroid",
            ),
            angle * 0.22 * progress,
            origin="centroid",
        )
        return shapely_translate(shaped, xoff=span_x * 0.06 * progress, yoff=span_y * 0.03 * progress).intersection(base_utm)

    if kind == "embedded_void":
        guest_scale = clamp(float(profile.get("guest_scale") or 0.32), 0.12, 0.58)
        position = profile.get("position") if isinstance(profile.get("position"), list) else [0.0, 0.0, 0.0]
        px = clamp(float(position[0] if len(position) > 0 else 0.0), -0.35, 0.35)
        py = clamp(float(position[1] if len(position) > 1 else 0.0), -0.35, 0.35)
        shifted = shapely_translate(
            shapely_scale(
                base_utm,
                xfact=clamp(1.0 - guest_scale * 0.24 * progress, 0.78, 1.0),
                yfact=clamp(1.0 - guest_scale * 0.24 * progress, 0.78, 1.0),
                origin="centroid",
            ),
            xoff=span_x * px * 0.35 * progress,
            yoff=span_y * py * 0.35 * progress,
        ).intersection(base_utm)
        sx0, sy0, sx1, sy1 = shifted.bounds
        sdx = sx1 - sx0
        sdy = sy1 - sy0
        cx = shifted.centroid.x + sdx * px * 0.12
        cy = shifted.centroid.y + sdy * py * 0.12
        void_scale = clamp(guest_scale * (0.42 + 0.28 * progress), 0.10, 0.30)
        void = box(
            cx - sdx * void_scale / 2,
            cy - sdy * void_scale / 2,
            cx + sdx * void_scale / 2,
            cy + sdy * void_scale / 2,
        )
        return shifted.difference(void)

    if kind == "extruded_fin":
        axis = str(profile.get("axis") or "x")
        shaped = shapely_scale(
            base_utm,
            xfact=clamp(1.0 - 0.22 * progress, 0.66, 1.0) if axis == "x" else clamp(1.0 - 0.08 * progress, 0.82, 1.0),
            yfact=clamp(1.0 - 0.22 * progress, 0.66, 1.0) if axis == "y" else clamp(1.0 - 0.08 * progress, 0.82, 1.0),
            origin="centroid",
        )
        return shapely_translate(shaped, xoff=span_x * 0.08 * progress, yoff=span_y * 0.02 * progress).intersection(base_utm)

    if kind == "nested_stack":
        inner_scale = clamp(float(profile.get("inner_scale") or 0.38), 0.12, 0.58)
        upper_ratio = clamp(float(profile.get("upper_ratio") or 0.76), 0.50, 0.96)
        shaped = shapely_scale(
            base_utm,
            xfact=clamp(1.0 - (1.0 - upper_ratio) * progress, 0.60, 1.0),
            yfact=clamp(1.0 - (1.0 - upper_ratio) * progress, 0.60, 1.0),
            origin="centroid",
        )
        shaped = shapely_translate(shaped, yoff=-span_y * float(profile.get("stack_gap") or 0.04) * progress).intersection(base_utm)
        sx0, sy0, sx1, sy1 = shaped.bounds
        sdx = sx1 - sx0
        sdy = sy1 - sy0
        cx = shaped.centroid.x
        cy = shaped.centroid.y
        atrium_scale = clamp(inner_scale * (0.34 + 0.18 * progress), 0.10, 0.28)
        atrium = box(
            cx - sdx * atrium_scale / 2,
            cy - sdy * atrium_scale / 2,
            cx + sdx * atrium_scale / 2,
            cy + sdy * atrium_scale / 2,
        )
        return shaped.difference(atrium)

    if kind == "overlap_slabs":
        offset_vec = profile.get("offset_vec") if isinstance(profile.get("offset_vec"), list) else [0.35, 0.18, 0.0]
        ox = clamp(float(offset_vec[0] if len(offset_vec) > 0 else 0.0), -0.65, 0.65)
        oy = clamp(float(offset_vec[1] if len(offset_vec) > 1 else 0.0), -0.65, 0.65)
        direction = -1 if progress < 0.5 else 1
        shaped = shapely_translate(
            shapely_scale(
                base_utm,
                xfact=clamp(1.0 - abs(ox) * 0.18 * progress, 0.72, 1.0),
                yfact=clamp(1.0 - abs(oy) * 0.18 * progress, 0.72, 1.0),
                origin="centroid",
            ),
            xoff=direction * span_x * ox * 0.16 * progress,
            yoff=-direction * span_y * oy * 0.16 * progress,
        )
        return shaped.intersection(base_utm)

    if kind in {"bar_notch_terrace", "notched_void"}:
        top_ratio = clamp(float(profile.get("top_ratio") or 0.72), 0.50, 0.92)
        recession = (1.0 - top_ratio) * progress
        notch_depth = span_y * clamp(recession, 0.04, 0.26)
        notch_width = span_x * clamp(0.24 + recession, 0.24, 0.46)
        cut = box(
            minx + span_x * 0.50 - notch_width / 2,
            maxy - notch_depth,
            minx + span_x * 0.50 + notch_width / 2,
            maxy + span_y * 0.02,
        )
        shaped = base_utm.difference(cut)
        if kind == "bar_notch_terrace":
            shaped = shapely_translate(shapely_scale(shaped, xfact=clamp(1.0 - recession * 0.25, 0.78, 1.0), yfact=1.0, origin="centroid"), yoff=-span_y * recession * 0.28)
        else:
            shaped = shapely_scale(shaped, xfact=clamp(1.0 - recession * 0.24, 0.82, 1.0), yfact=clamp(1.0 - recession * 0.24, 0.82, 1.0), origin="centroid")
        return shaped.intersection(base_utm)

    if kind == "pinched_waist":
        axis = str(profile.get("axis") or "x")
        shaped = shapely_scale(
            base_utm,
            xfact=clamp(1.0 - 0.26 * progress, 0.58, 1.0) if axis == "x" else clamp(1.0 - 0.08 * progress, 0.82, 1.0),
            yfact=clamp(1.0 - 0.26 * progress, 0.58, 1.0) if axis == "y" else clamp(1.0 - 0.08 * progress, 0.82, 1.0),
            origin="centroid",
        )
        return shaped.intersection(base_utm)

    if kind == "stepped_tower":
        x_ratio = clamp(float(profile.get("x_ratio") or profile.get("top_ratio") or 0.72), 0.50, 0.96)
        y_ratio = clamp(float(profile.get("y_ratio") or profile.get("top_ratio") or 0.72), 0.50, 0.96)
        shaped = shapely_translate(
            shapely_scale(
                base_utm,
                xfact=clamp(1.0 - (1.0 - x_ratio) * progress, 0.50, 1.0),
                yfact=clamp(1.0 - (1.0 - y_ratio) * progress, 0.50, 1.0),
                origin="centroid",
            ),
            xoff=span_x * (1.0 - x_ratio) * 0.16 * progress,
            yoff=-span_y * (1.0 - y_ratio) * 0.16 * progress,
        )
        return shaped.intersection(base_utm)

    return base_utm


def _surface_point_wgs84(point: tuple[float, float, float]) -> list[float]:
    lng, lat = utm_to_wgs84(box(point[0], point[1], point[0] + 0.01, point[1] + 0.01)).centroid.coords[0]
    return [round(lng, 8), round(lat, 8), round(float(point[2]), 2)]


def _surface_from_bounds(
    *,
    role: str,
    kind: str,
    bounds: tuple[float, float, float, float],
    high_m: float,
    low_m: float,
    inset_ratio: float = 0.06,
) -> dict[str, Any]:
    minx, miny, maxx, maxy = bounds
    dx = (maxx - minx) * inset_ratio
    dy = (maxy - miny) * inset_ratio
    return {
        "role": role,
        "kind": kind,
        "surface_type": "quad",
        "vertices_wgs84_h": [
            _surface_point_wgs84((minx + dx, miny + dy, high_m)),
            _surface_point_wgs84((maxx - dx, miny + dy, high_m)),
            _surface_point_wgs84((maxx - dx, maxy - dy, low_m)),
            _surface_point_wgs84((minx + dx, maxy - dy, low_m)),
        ],
    }


def _surface_from_polygon(
    *,
    role: str,
    kind: str,
    polygon_utm,
    height_m: float,
) -> dict[str, Any] | None:
    poly = _largest_polygon_or_none(polygon_utm)
    if poly is None:
        return None
    coords = list(poly.exterior.coords)
    if len(coords) < 4:
        return None
    # Keep source surfaces compact for evidence/rendering.
    sampled = coords[:-1]
    if len(sampled) > 8:
        step = max(1, len(sampled) // 8)
        sampled = sampled[::step][:8]
    return {
        "role": role,
        "kind": kind,
        "surface_type": "polygon",
        "vertices_wgs84_h": [
            _surface_point_wgs84((float(x), float(y), height_m))
            for x, y in sampled
        ],
    }


def _sloped_surface_from_polygon(
    *,
    role: str,
    kind: str,
    polygon_utm,
    high_m: float,
    low_m: float,
) -> dict[str, Any] | None:
    poly = _largest_polygon_or_none(polygon_utm)
    if poly is None:
        return None
    coords = [(float(x), float(y)) for x, y in list(poly.exterior.coords)[:-1]]
    if len(coords) < 3:
        return None
    if len(coords) > 8:
        step = max(1, len(coords) // 8)
        coords = coords[::step][:8]
    miny = min(y for _, y in coords)
    maxy = max(y for _, y in coords)
    span = max(maxy - miny, 1e-6)
    vertices = []
    for x, y in coords:
        ratio = (y - miny) / span
        height = high_m + (low_m - high_m) * ratio
        vertices.append(_surface_point_wgs84((x, y, height)))
    return {
        "role": role,
        "kind": kind,
        "surface_type": "polygon",
        "vertices_wgs84_h": vertices,
    }


def _surface_between_polygons(
    *,
    role: str,
    kind: str,
    lower_utm,
    upper_utm,
    lower_height_m: float,
    upper_height_m: float,
    width_ratio: float = 0.18,
) -> dict[str, Any] | None:
    lower = _largest_polygon_or_none(lower_utm)
    upper = _largest_polygon_or_none(upper_utm)
    if lower is None or upper is None:
        return None
    lx, ly = lower.centroid.x, lower.centroid.y
    ux, uy = upper.centroid.x, upper.centroid.y
    dx = ux - lx
    dy = uy - ly
    length = (dx * dx + dy * dy) ** 0.5
    minx = min(lower.bounds[0], upper.bounds[0])
    miny = min(lower.bounds[1], upper.bounds[1])
    maxx = max(lower.bounds[2], upper.bounds[2])
    maxy = max(lower.bounds[3], upper.bounds[3])
    span = max(maxx - minx, maxy - miny, 1.0)
    width = max(1.0, span * width_ratio)
    if length <= 0.1:
        nx, ny = 0.0, width
    else:
        nx = -dy / length * width
        ny = dx / length * width
    vertices = [
        (lx + nx, ly + ny, lower_height_m),
        (lx - nx, ly - ny, lower_height_m),
        (ux - nx, uy - ny, upper_height_m),
        (ux + nx, uy + ny, upper_height_m),
    ]
    return {
        "role": role,
        "kind": kind,
        "surface_type": "quad",
        "vertices_wgs84_h": [_surface_point_wgs84(point) for point in vertices],
    }


def _surface_between_bounds_face(
    *,
    role: str,
    kind: str,
    lower_utm,
    upper_utm,
    lower_height_m: float,
    upper_height_m: float,
    face: str,
    inset_ratio: float = 0.04,
) -> dict[str, Any] | None:
    lower = _largest_polygon_or_none(lower_utm)
    upper = _largest_polygon_or_none(upper_utm)
    if lower is None or upper is None:
        return None
    def face_points(poly, target_face: str) -> tuple[tuple[float, float], tuple[float, float]] | None:
        coords = [(float(x), float(y)) for x, y in list(poly.exterior.coords)[:-1]]
        if len(coords) < 2:
            return None
        if target_face in {"north", "south"}:
            reverse = target_face == "north"
            ordered = sorted(coords, key=lambda point: point[1], reverse=reverse)
            candidates = ordered[:max(2, min(len(ordered), len(ordered) // 3 + 1))]
            left = min(candidates, key=lambda point: point[0])
            right = max(candidates, key=lambda point: point[0])
            if left == right:
                return None
            return (left, right) if target_face == "north" else (right, left)
        reverse = target_face == "east"
        ordered = sorted(coords, key=lambda point: point[0], reverse=reverse)
        candidates = ordered[:max(2, min(len(ordered), len(ordered) // 3 + 1))]
        low = min(candidates, key=lambda point: point[1])
        high = max(candidates, key=lambda point: point[1])
        if low == high:
            return None
        return (high, low) if target_face == "east" else (low, high)

    lower_edge = face_points(lower, face)
    upper_edge = face_points(upper, face)
    if lower_edge is None or upper_edge is None:
        return None
    lower_a, lower_b = lower_edge
    upper_a, upper_b = upper_edge
    vertices = [
        (lower_a[0], lower_a[1], lower_height_m),
        (lower_b[0], lower_b[1], lower_height_m),
        (upper_b[0], upper_b[1], upper_height_m),
        (upper_a[0], upper_a[1], upper_height_m),
    ]
    return {
        "role": role,
        "kind": kind,
        "surface_type": "quad",
        "vertices_wgs84_h": [_surface_point_wgs84(point) for point in vertices],
    }


def _build_section_source_surfaces(
    *,
    kind: str,
    profile: dict[str, Any],
    materialized: list[dict[str, Any]],
    materialized_utms: list[Any],
) -> list[dict[str, Any]]:
    if not materialized or not materialized_utms:
        return []
    minx = min(geom.bounds[0] for geom in materialized_utms)
    miny = min(geom.bounds[1] for geom in materialized_utms)
    maxx = max(geom.bounds[2] for geom in materialized_utms)
    maxy = max(geom.bounds[3] for geom in materialized_utms)
    top = max(float(volume.get("top_height") or 0.0) for volume in materialized)
    low = max(
        min(float(volume.get("top_height") or top) for volume in materialized),
        top * 0.58,
    )
    surfaces: list[dict[str, Any]] = []
    if kind == "sloped_roof":
        roof = _sloped_surface_from_polygon(
            role="section_surface_sloped_roof_plane",
            kind=kind,
            polygon_utm=materialized_utms[-1],
            high_m=top + 0.15,
            low_m=low + 0.15,
        )
        if roof:
            surfaces.append(roof)
    elif kind == "terrace_ribbon":
        for index in range(1, len(materialized_utms)):
            surface = _surface_between_polygons(
                role=f"section_surface_terrace_ribbon_link_{index}",
                kind=kind,
                lower_utm=materialized_utms[index - 1],
                upper_utm=materialized_utms[index],
                lower_height_m=float(materialized[index - 1].get("top_height") or 0.0) + 0.08,
                upper_height_m=float(materialized[index].get("top_height") or top) + 0.08,
                width_ratio=0.06,
            )
            if surface:
                surfaces.append(surface)
        for index, geom in enumerate(materialized_utms[1:], start=1):
            height = float(materialized[min(index, len(materialized) - 1)].get("top_height") or top)
            surface = _surface_from_polygon(
                role=f"section_surface_terrace_band_{index}",
                kind=kind,
                polygon_utm=geom.boundary.buffer(max(0.4, min(maxx - minx, maxy - miny) * 0.035)).intersection(geom),
                height_m=height + 0.1,
            )
            if surface:
                surfaces.append(surface)
    elif kind in {"diagonal_connector", "diagonal_connect"}:
        surface = _surface_between_polygons(
            role="section_surface_diagonal_connector_skin",
            kind=kind,
            lower_utm=materialized_utms[0],
            upper_utm=materialized_utms[-1],
            lower_height_m=float(materialized[0].get("top_height") or 0.0) + 0.12,
            upper_height_m=top + 0.12,
            width_ratio=0.08,
        )
        if surface:
            surfaces.append(surface)
        bridge = next(
            (
                (volume, geom)
                for volume, geom in zip(materialized, materialized_utms)
                if str(volume.get("role") or "").endswith("diagonal_connector_bridge")
            ),
            None,
        )
        if bridge:
            volume, geom = bridge
            surface = _surface_from_polygon(
                role="section_surface_diagonal_connector_deck",
                kind=kind,
                polygon_utm=geom,
                height_m=float(volume.get("top_height") or top) + 0.12,
            )
            if surface:
                surfaces.append(surface)
    return surfaces


def _materialize_section_profile_volumes(feature: dict[str, Any]) -> None:
    """Convert section profile intent into conservative source volume geometry.

    Legal accounting remains based on the original floor plates. The returned
    `mass_volumes` are still clipped inside each legal band, but their source
    geometry now expresses sloped, terrace, and diagonal design intent instead
    of relying on a separate pink overlay.
    """
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    profile = props.get("section_profile")
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    if not isinstance(profile, dict):
        profile = model.get("section_profile") if isinstance(model.get("section_profile"), dict) else None
    if not isinstance(profile, dict):
        return
    kind = str(profile.get("kind") or "")
    if kind not in SECTION_PROFILE_KINDS:
        return
    existing = props.get("section_profile_materialized")
    if isinstance(existing, dict) and existing.get("kind") == kind:
        return
    volumes = model.get("volumes") if isinstance(model.get("volumes"), list) else props.get("mass_volumes")
    if not isinstance(volumes, list) or len(volumes) < 2:
        return

    parsed: list[tuple[dict[str, Any], Any]] = []
    for volume in volumes:
        if not isinstance(volume, dict) or not isinstance(volume.get("geometry"), dict):
            continue
        try:
            geom = _largest_polygon_or_none(wgs84_to_utm(geojson_to_polygon(volume["geometry"])))
        except Exception:
            geom = None
        if geom is not None:
            parsed.append((volume, geom))
    if len(parsed) < 2:
        return

    if kind in {"bend_ribbon", "embedded_void", "extruded_fin", "nested_stack"} and len(parsed) > 5:
        mid = parsed[len(parsed) // 2]
        parsed = [parsed[0], parsed[1], mid, parsed[-2], parsed[-1]]

    # A diagonal connector is itself the fourth compositional gesture. Keep
    # three ordered source masses before adding it, rather than displaying a
    # fifth helper volume.
    if kind in {"diagonal_connector", "diagonal_connect"} and len(parsed) > 3:
        parsed = [parsed[0], parsed[len(parsed) // 2], parsed[-1]]

    minx = min(geom.bounds[0] for _, geom in parsed)
    miny = min(geom.bounds[1] for _, geom in parsed)
    maxx = max(geom.bounds[2] for _, geom in parsed)
    maxy = max(geom.bounds[3] for _, geom in parsed)
    count = max(1, len(parsed) - 1)
    materialized: list[dict[str, Any]] = []
    materialized_utms: list[Any] = []
    for index, (volume, geom) in enumerate(parsed):
        progress = index / count
        shaped = _section_materialized_polygon(geom, profile=profile, progress=progress, bounds=(minx, miny, maxx, maxy))
        shaped = _largest_polygon_or_none(shaped)
        if shaped is None:
            shaped = geom
        materialized_utms.append(shaped)
        next_volume = {
            **volume,
            "geometry": mapping(utm_to_wgs84(shaped)),
            "role": f"section_source_{kind}",
            "source_geometry": {
                "basis": "section_profile_materialized_inside_legal_floor_plate",
                "profile_kind": kind,
                "legal_accounting": "floor_plates_remain_conservative_source_for_far_bcr_height",
            },
        }
        materialized.append(next_volume)

    if kind in {"diagonal_connector", "diagonal_connect"} and len(materialized_utms) >= 2:
        lower = materialized_utms[0]
        upper = materialized_utms[-1]
        line = LineString([lower.centroid, upper.centroid])
        if line.length > 0.5:
            width = max(1.2, min(maxx - minx, maxy - miny) * 0.12)
            allowed = unary_union([geom for _, geom in parsed])
            connector = _largest_polygon_or_none(line.buffer(width, cap_style=2).intersection(allowed))
            if connector is not None:
                bottom_height = float(materialized[0].get("top_height") or materialized[0].get("bottom_height") or 0.0)
                top_height = float(materialized[-1].get("top_height") or bottom_height)
                if top_height > bottom_height + 0.5:
                    materialized.append({
                        "band": "diagonal_connector",
                        "bottom_height": round(bottom_height, 2),
                        "top_height": round(top_height, 2),
                        "geometry": mapping(utm_to_wgs84(connector)),
                        "role": "section_source_diagonal_connector_bridge",
                        "source_geometry": {
                            "basis": "maas_verb_sequence_diagonal_connect",
                            "profile_kind": kind,
                            "legal_accounting": "display_connector_inside_union_of_legal_floor_plates",
                        },
                    })
                    materialized_utms.append(connector)

    if len(materialized) != len(parsed):
        if not (kind in {"diagonal_connector", "diagonal_connect"} and len(materialized) == len(parsed) + 1):
            return
    section_surfaces = _build_section_source_surfaces(
        kind=kind,
        profile=profile,
        materialized=materialized,
        materialized_utms=materialized_utms,
    )
    props["mass_volumes"] = materialized
    props["section_source_surfaces"] = section_surfaces
    props["section_profile_materialized"] = {
        "status": "materialized_inside_legal_floor_plates",
        "kind": kind,
        "design_synthesis": True,
        "volume_count": len(materialized),
        "surface_count": len(section_surfaces),
        "legal_accounting": "floor_plates",
        "basis": "maas_section_synthesis_v1",
    }
    if isinstance(model, dict):
        model["volumes"] = materialized
        model["section_source_surfaces"] = section_surfaces
        model["section_profile_materialized"] = props["section_profile_materialized"]
    existing_resolution = props.get("geometry_resolution")
    if not isinstance(existing_resolution, dict):
        _attach_geometry_resolution(
            feature,
            status="clipped_to_legal_envelope",
            source="section_profile_materializer",
            legal_action="materialized_inside_legal_floor_plates",
            fallback="floor_plate_band_source",
        )
    _attach_visual_diversity_evidence(feature)


def _interpolated_upper_volumes(feature: dict[str, Any], *, steps: int = 4) -> list[dict[str, Any]]:
    props = feature.get("properties", {}) or {}
    if props.get("lower_height") is None or props.get("upper_geometry") is None:
        return []
    try:
        lower_height = float(props.get("lower_height") or 0.0)
        total_height = float(props.get("height") or lower_height)
        lower = _largest_polygon_or_none(wgs84_to_utm(geojson_to_polygon(feature.get("geometry"))))
        upper = _largest_polygon_or_none(wgs84_to_utm(geojson_to_polygon(props.get("upper_geometry"))))
    except Exception:
        return []
    if lower is None or upper is None or total_height <= lower_height <= 0:
        return []

    usable_steps = max(2, min(5, steps))
    upper_area_ratio = max(0.05, min(1.0, float(upper.area) / max(float(lower.area), 1e-9)))
    lower_centroid = lower.centroid
    upper_centroid = upper.centroid
    stage_height = (total_height - lower_height) / usable_steps
    volumes: list[dict[str, Any]] = [{
        "band": 0,
        "bottom_height": 0.0,
        "top_height": round(lower_height, 2),
        "geometry": feature.get("geometry"),
        "role": "morphology_volume",
    }]
    previous_top = lower_height
    for index in range(usable_steps):
        progress = (index + 1) / usable_steps
        if index == usable_steps - 1:
            shaped = upper
        else:
            area_ratio = 1.0 + (upper_area_ratio - 1.0) * progress
            factor = area_ratio ** 0.5
            shaped = shapely_scale(lower, xfact=factor, yfact=factor, origin="centroid")
            shaped = shapely_translate(
                shaped,
                xoff=(upper_centroid.x - lower_centroid.x) * progress,
                yoff=(upper_centroid.y - lower_centroid.y) * progress,
            )
            shaped = _largest_polygon_or_none(shaped.intersection(lower).union(upper).intersection(lower))
            if shaped is None:
                shaped = upper
        top_height = total_height if index == usable_steps - 1 else lower_height + stage_height * (index + 1)
        if top_height <= previous_top:
            continue
        volumes.append({
            "band": index + 1,
            "bottom_height": round(previous_top, 2),
            "top_height": round(top_height, 2),
            "geometry": mapping(utm_to_wgs84(shaped)),
            "role": "morphology_volume_interpolated",
        })
        previous_top = top_height
    return volumes


def _single_volume_model(operator: str, feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties", {}) or {}
    volumes = [{
        "band": 0,
        "bottom_height": 0.0,
        "top_height": props.get("height") or 0.0,
        "geometry": feature.get("geometry"),
        "role": "morphology_volume",
    }]
    interpolated = _interpolated_upper_volumes(feature)
    if interpolated:
        volumes = interpolated
    return {
        "algorithm": "maas_legal_envelope",
        "operator": operator,
        "verb_sequence": _maas_verb_sequence(operator),
        "volumes": volumes,
        "floor_plates": [],
        "legal_metrics": {
            "far": props.get("far"),
            "bcr": props.get("bcr"),
            "height": props.get("height"),
            "num_floors": props.get("num_floors"),
            "footprint_area": props.get("footprint_area"),
            "floor_area": props.get("floor_area"),
            "min_setback": props.get("min_setback"),
            "open_pct": props.get("open_pct"),
        },
    }


def _apply_variant_source_geometry(feature: dict[str, Any], variant) -> None:
    props = feature.setdefault("properties", {})
    status = getattr(variant, "source_geometry_status", None)
    trace = tuple(getattr(variant, "source_verb_trace", ()) or ())
    signature = getattr(variant, "source_signature", None)
    volumes = tuple(getattr(variant, "source_volumes", ()) or ())
    surfaces = tuple(getattr(variant, "source_surfaces", ()) or ())
    research_basis = getattr(variant, "research_basis", None)
    if not any((status, trace, signature, volumes, surfaces, research_basis)):
        return
    if status:
        props["source_geometry_status"] = status
    if trace:
        props["source_verb_trace"] = [dict(item) for item in trace if isinstance(item, dict)]
    if isinstance(signature, dict):
        props["source_signature"] = dict(signature)
    if volumes:
        props["source_volumes"] = [dict(item) for item in volumes if isinstance(item, dict)]
    if surfaces:
        props["source_surfaces"] = [dict(item) for item in surfaces if isinstance(item, dict)]
    if isinstance(research_basis, dict):
        props["research_basis"] = dict(research_basis)
    model = props.get("maas_model")
    if isinstance(model, dict):
        if status:
            model["source_geometry_status"] = status
        if trace:
            model["source_verb_trace"] = [dict(item) for item in trace if isinstance(item, dict)]
        if isinstance(signature, dict):
            model["source_signature"] = dict(signature)
        if volumes:
            model["source_volumes"] = [dict(item) for item in volumes if isinstance(item, dict)]
        if surfaces:
            model["source_surfaces"] = [dict(item) for item in surfaces if isinstance(item, dict)]
        if isinstance(research_basis, dict):
            model["research_basis"] = dict(research_basis)


def _apply_variant_verb_sequence(feature: dict[str, Any], variant) -> None:
    sequence = getattr(variant, "verb_sequence", ()) or ()
    _apply_variant_source_geometry(feature, variant)
    props = feature.get("properties", {}) or {}
    if not sequence:
        if props.get("source_geometry_status") == "compiled":
            _apply_source_volumes_as_mass_geometry(feature)
        _sync_rule_evidence_notes(feature)
        _attach_visual_diversity_evidence(feature)
        return
    sequence_list = [dict(item) for item in sequence]
    props["maas_verb_sequence"] = sequence_list
    model = props.get("maas_model")
    if isinstance(model, dict):
        model["verb_sequence"] = sequence_list
        model["grammar_sequence"] = variant.operator
        model["grammar_label"] = _concept_label(variant.operator)
        model.pop("section_profile", None)
        model.pop("section_source_surfaces", None)
    props.pop("section_profile", None)
    props.pop("section_source_surfaces", None)
    props.pop("section_profile_materialized", None)
    _attach_section_profile(feature)
    if not _apply_source_volumes_as_mass_geometry(feature):
        _materialize_section_profile_volumes(feature)
    _sync_rule_evidence_notes(feature)
    _attach_visual_diversity_evidence(feature)


def _sync_rule_evidence_notes(feature: dict[str, Any]) -> None:
    props = feature.setdefault("properties", {})
    signature = _source_signature(feature)
    rule_evidence = signature.get("rule_evidence") if isinstance(signature.get("rule_evidence"), dict) else {}
    if not rule_evidence:
        return
    notes = props.get("notes")
    if not isinstance(notes, list):
        notes = []
    existing = {str(note).split("=", 1)[0] for note in notes if isinstance(note, str) and "=" in note}
    additions: list[str] = []
    if rule_evidence.get("rule_name") and "rule_name" not in existing:
        additions.append(f"rule_name={rule_evidence.get('rule_name')}")
    if "rule_inputs" not in existing:
        additions.append(f"rule_inputs={rule_evidence.get('rule_inputs') or {}}")
    if rule_evidence.get("geometry_actions") and "expected_geometry_actions" not in existing:
        additions.append(f"expected_geometry_actions={rule_evidence.get('geometry_actions')}")
    if not additions:
        return
    props["notes"] = [*notes, *additions]
    model = props.get("maas_model")
    if isinstance(model, dict):
        model["notes"] = props["notes"]


def _constraints_agent_summary(envelope) -> dict[str, Any]:
    return {
        "bcr_limit": envelope.bcr_limit,
        "far_limit": envelope.far_limit,
        "height_limit": envelope.height_limit,
    }


def _attach_massdsl_agent_evidence(
    feature: dict[str, Any],
    *,
    operation_type: str,
    constraints: dict[str, Any],
    rejected: list[dict[str, Any]],
) -> None:
    props = feature.setdefault("properties", {})
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    if not isinstance(props.get("section_profile"), dict) and not isinstance(model.get("section_profile"), dict):
        _attach_section_profile(feature)
    # Evidence attachment runs after exact integer projection. Rebuilding
    # section volumes here changed the geometry after pairwise conflicts had
    # already been solved, so the PNG could contain a duplicate the MILP never
    # evaluated. Only materialize genuinely missing geometry; selected source
    # volumes are immutable at this stage.
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    if not (isinstance(props.get("mass_volumes"), list) and props["mass_volumes"]):
        if not (isinstance(model.get("volumes"), list) and model["volumes"]):
            _materialize_section_profile_volumes(feature)
    _attach_visual_diversity_evidence(feature)
    proposal = build_massdsl_proposal(
        feature,
        operation_type=operation_type,
        constraints=constraints,
    )
    grammar_review = build_grammar_review(feature, rejected=rejected)
    props["massdsl_proposal"] = proposal
    props["grammar_review"] = grammar_review
    model = props.get("maas_model")
    if isinstance(model, dict):
        model["massdsl_proposal"] = proposal
        model["grammar_review"] = grammar_review


def _select_diverse_features(
    features: list[dict[str, Any]],
    max_variants: int,
    preferred_operator: str | None = None,
) -> list[dict[str, Any]]:
    """Pick the best legal candidate per spatial concept, then fill by score.

    MAAS is useful here only if the user sees different architectural
    strategies, not eighteen tiny variations of the same sunlight stepback.
    The first pass therefore reserves one slot for each concept family.
    """
    limit = max(1, max_variants)
    if len(features) <= 1:
        return features

    by_score = sorted(features, key=lambda f: f["properties"].get("maas_score", 0), reverse=True)
    selected: list[dict[str, Any]] = []

    # Keep an explicit user/agent-preferred operator first. In live LLM/agent
    # design mode, avoid pinning the legal capacity anchor as the first visual
    # card; it is still available for legal evidence, but should not dominate
    # the creative massing set.
    anchor = None
    if preferred_operator:
        anchor = next((f for f in by_score if f["properties"].get("mass_shape") == preferred_operator), None)
    llm_design_count = sum(
        1 for feature in by_score
        if str(feature["properties"].get("mass_shape") or "").startswith(("llm_", "agent_"))
    )
    should_pin_legal_anchor = anchor is None
    if should_pin_legal_anchor:
        anchor = next((f for f in by_score if f["properties"].get("mass_shape") == "legal_layered_max"), None)
    if anchor is not None:
        selected.append(anchor)

    def is_near_duplicate(feature: dict[str, Any]) -> bool:
        if preferred_operator and feature["properties"].get("mass_shape") == preferred_operator:
            return False
        try:
            family = _operator_family(feature["properties"].get("mass_shape", ""))
            candidate = geojson_to_polygon(feature["geometry"])
            candidate_profile = _volume_profile(feature)
            candidate_is_connector = _is_section_connector(feature)
            candidate_verbs = sequence_verbs(feature["properties"].get("maas_verb_sequence"))
            candidate_source_family = _source_family(feature)
            candidate_source_profile = _source_area_profile(feature)
            for existing in selected:
                existing_family = _operator_family(existing["properties"].get("mass_shape", ""))
                existing_is_connector = _is_section_connector(existing)
                iou = polygon_iou(candidate, geojson_to_polygon(existing["geometry"]))
                existing_verbs = sequence_verbs(existing["properties"].get("maas_verb_sequence"))
                existing_source_family = _source_family(existing)
                existing_source_profile = _source_area_profile(existing)
                if iou >= 0.98 and candidate_profile == _volume_profile(existing):
                    return True
                if iou >= 0.94 and candidate_verbs == existing_verbs:
                    return True
                if (
                    candidate_source_family
                    and candidate_source_family == existing_source_family
                    and candidate_source_profile
                    and candidate_source_profile == existing_source_profile
                    and iou >= 0.88
                ):
                    return True
                if family in {"bcr_fill", "legal_buildable"} and iou >= 0.96:
                    return True
                # A podium/tower or taper can legitimately share the same
                # ground footprint with another concept while differing in
                # section. Treat only same-family high-IoU footprints as
                # duplicates; cross-family vertical typologies must survive.
                if family != existing_family:
                    continue
                if iou >= 0.96:
                    return True
            return False
        except Exception:
            return False

    by_family: dict[str, list[dict[str, Any]]] = {}
    for feature in by_score:
        family = _operator_family(feature["properties"].get("mass_shape", ""))
        by_family.setdefault(family, []).append(feature)

    def signature_pool_priority(feature: dict[str, Any]) -> int:
        shape = str((feature.get("properties") or {}).get("mass_shape") or "")
        return SIGNATURE_PROPOSAL_PRIORITIES.get(shape, 0)

    def selected_shape_set() -> set[str]:
        return {
            str((feature.get("properties") or {}).get("mass_shape") or "")
            for feature in selected
        }

    def preserve_signature_review_pool() -> None:
        if preferred_operator or limit < 12:
            return
        target_count = 4 if limit >= 20 else 2
        signature_candidates = [
            feature for feature in by_score
            if signature_pool_priority(feature) > 0
        ]
        signature_candidates.sort(
            key=lambda feature: (
                signature_pool_priority(feature),
                1 if _is_reviewable_architectural_mass(feature) else 0,
                1 if _has_review_source_geometry(feature) else 0,
                -float(_source_signature(feature).get("parameter_default_ratio") or 0.0),
                _design_review_quality_key(feature),
            ),
            reverse=True,
        )

        def protected_pool_item(feature: dict[str, Any]) -> bool:
            shape = str((feature.get("properties") or {}).get("mass_shape") or "")
            if shape == "legal_layered_max" or _is_clean_layered_anchor(feature):
                return True
            if signature_pool_priority(feature) > 0:
                return True
            group = _research_quota_group(feature)
            if group in {"legal_anchor", "additive", "subtractive", "hybrid", "sectional"}:
                counts = Counter(_research_quota_group(item) for item in selected)
                floor = 1 if group == "legal_anchor" else 3
                if counts.get(group, 0) <= floor:
                    return True
            return False

        def replacement_indexes() -> list[int]:
            return [
                index for index, feature in enumerate(selected)
                if not protected_pool_item(feature)
            ]

        for candidate in signature_candidates:
            if sum(1 for feature in selected if signature_pool_priority(feature) > 0) >= target_count:
                break
            candidate_shape = str((candidate.get("properties") or {}).get("mass_shape") or "")
            if candidate_shape in selected_shape_set():
                continue
            if len(selected) < limit:
                selected.append(candidate)
                continue
            indexes = replacement_indexes()
            if not indexes:
                continue
            family_counts = Counter(_source_family(feature) for feature in selected)
            language_counts = Counter(_research_mass_language(feature) for feature in selected)
            replace_index = min(
                indexes,
                key=lambda index: (
                    0 if _is_agent_authored_candidate(selected[index]) else -1,
                    -family_counts.get(_source_family(selected[index]), 0),
                    -language_counts.get(_research_mass_language(selected[index]), 0),
                    -float(_source_signature(selected[index]).get("parameter_default_ratio") or 0.0),
                    _design_review_quality_key(selected[index]),
                ),
            )
            selected[replace_index] = candidate

    if limit >= 8:
        capped_by_score = by_score[: max(limit + 12, 32)]
        medoid_pool = [
            feature for feature in capped_by_score
            if feature not in selected and not is_near_duplicate(feature)
        ]
        medoid_pool = medoid_pool[: max(limit + 8, 28)]
        medoids = _kmedoid_representatives(
            medoid_pool,
            k=limit - len(selected),
            anchors=selected,
        )
        for medoid_index, feature in enumerate(medoids, start=1):
            props = feature.setdefault("properties", {})
            trace = props.setdefault("selection_trace", [])
            if isinstance(trace, list):
                trace.append({
                    "schema_version": "arr.maas.selection_trace.v1",
                    "stage": "kmedoid_representative_selection",
                    "rank": medoid_index,
                    "pool_size": len(medoid_pool),
                    "anchor_count": len(selected),
                    "distance_basis": [
                        "footprint_iou",
                        "normalized_mass_metrics",
                        "verb_sequence_distance",
                        "operator_family_distance",
                        "source_profile_distance",
                    ],
                })
        selected.extend(medoids)
        min_section_design = min(MIN_SECTION_DESIGN_CONCEPTS, max(1, limit // 5))
        section_design_count = sum(1 for feature in selected if _is_section_connector(feature))
        if section_design_count < min_section_design:
            section_candidates = [
                feature for feature in by_score
                if feature not in selected and _is_section_connector(feature)
            ]
            for feature in section_candidates:
                if section_design_count >= min_section_design:
                    break
                candidate_verbs = sequence_verbs(feature["properties"].get("maas_verb_sequence"))
                selected_section_verbs = [
                    sequence_verbs(item["properties"].get("maas_verb_sequence"))
                    for item in selected
                    if _is_section_connector(item)
                ]
                if candidate_verbs in selected_section_verbs:
                    continue
                if len(selected) >= limit:
                    replace_index = min(
                        range(len(selected)),
                        key=lambda i: (
                            1 if _is_section_connector(selected[i]) else 0,
                            sequence_diversity_score(
                                sequence_verbs(selected[i]["properties"].get("maas_verb_sequence")),
                                [
                                    sequence_verbs(other["properties"].get("maas_verb_sequence"))
                                    for j, other in enumerate(selected)
                                    if j != i
                                ],
                            ),
                            _capacity_score(selected[i]["properties"]),
                        ),
                    )
                    selected.pop(replace_index)
                selected.append(feature)
                section_design_count += 1
        required_section_families = [
            "diagonal_connect",
            "terrace_link",
            "sloped_roof",
            "stepback_tower",
        ]
        for family in required_section_families:
            if any(_operator_family(item["properties"].get("mass_shape", "")) == family for item in selected):
                continue
            options = [
                feature for feature in by_family.get(family, [])
                if feature not in selected and not is_near_duplicate(feature)
            ]
            if not options:
                continue
            options.sort(
                key=lambda feature: (
                    _design_synthesis_rank(feature),
                    sequence_diversity_score(
                        sequence_verbs(feature["properties"].get("maas_verb_sequence")),
                        [
                            sequence_verbs(item["properties"].get("maas_verb_sequence"))
                            for item in selected
                        ],
                    ),
                    float(feature["properties"].get("diversity_score") or 0.0),
                    float(feature["properties"].get("maas_score") or 0.0),
                ),
                reverse=True,
            )
            if len(selected) < limit:
                selected.append(options[0])
                continue
            replace_index = min(
                range(len(selected)),
                key=lambda i: (
                    1 if str(selected[i]["properties"].get("mass_shape", "")) == "legal_layered_max" else 0,
                    1 if _operator_family(selected[i]["properties"].get("mass_shape", "")) in required_section_families else 0,
                    1 if _is_section_connector(selected[i]) else 0,
                    float(selected[i]["properties"].get("diversity_score") or 0.0),
                    float(selected[i]["properties"].get("maas_score") or 0.0),
                ),
            )
            selected[replace_index] = options[0]
        required_plan_families = [
            "interlock",
            "overlap",
            "split",
            "branch",
            "pinch",
            "courtyard",
            "void_notch",
            "slender_bar",
        ]
        for family in required_plan_families:
            if any(_operator_family(item["properties"].get("mass_shape", "")) == family for item in selected):
                continue
            options = [
                feature for feature in by_family.get(family, [])
                if feature not in selected and not is_near_duplicate(feature)
            ]
            if not options:
                continue
            options.sort(
                key=lambda feature: (
                    1 if _is_grammar_candidate(feature) else 0,
                    _visible_volume_count(feature),
                    float(feature["properties"].get("diversity_score") or 0.0),
                    float(feature["properties"].get("maas_score") or 0.0),
                ),
                reverse=True,
            )
            if len(selected) < limit:
                selected.append(options[0])
                continue
            replace_index = min(
                range(len(selected)),
                key=lambda i: (
                    1 if _is_section_connector(selected[i]) else 0,
                    1 if _operator_family(selected[i]["properties"].get("mass_shape", "")) in required_plan_families else 0,
                    float(selected[i]["properties"].get("diversity_score") or 0.0),
                    float(selected[i]["properties"].get("maas_score") or 0.0),
                ),
            )
            selected[replace_index] = options[0]
        for feature in by_score:
            if len(selected) >= limit:
                break
            if feature in selected or is_near_duplicate(feature):
                continue
            selected.append(feature)
        authored_count = sum(
            1 for feature in selected
            if str(feature["properties"].get("mass_shape") or "").startswith(("llm_", "agent_"))
        )
        preserve_signature_review_pool()
        authored_count = sum(
            1 for feature in selected
            if str(feature["properties"].get("mass_shape") or "").startswith(("llm_", "agent_"))
        )
        if authored_count >= max(4, limit // 2):
            legal_index = next(
                (
                    index for index, feature in enumerate(selected)
                    if str(feature["properties"].get("mass_shape") or "") == "legal_layered_max"
                ),
                None,
            )
            if legal_index == 0 and len(selected) > 5:
                legal_anchor = selected.pop(legal_index)
                selected.insert(min(5, len(selected)), legal_anchor)
        return selected[:limit]

    # Keep at least one sectional/stepback strategy when the parcel can support
    # it. The user still needs a legal terrace/step mass as an option; the
    # diversity pass below only prevents that family from dominating the list.
    if limit > len(selected) and not preferred_operator:
        has_section = any(
            _operator_family(s["properties"].get("mass_shape", "")) in SECTION_CONCEPTS
            for s in selected
        )
        if not has_section:
            section_candidates = [
                f for family in ("stepback_tower", "grade", "taper")
                for f in by_family.get(family, [])
            ]
            for feature in section_candidates:
                if feature in selected or is_near_duplicate(feature):
                    continue
                selected.append(feature)
                break

    # A stepped mass alone is not enough for MAAS design exploration. Preserve
    # at least one section connector option so the user can compare step-only
    # forms against diagonal/terrace/sloped linking masses in the default run.
    if limit > len(selected) and not preferred_operator:
        has_connector = any(_is_section_connector(feature) for feature in selected)
        if not has_connector:
            connector_candidates = [f for f in by_score if _is_section_connector(f)]
            for feature in connector_candidates:
                if feature in selected or is_near_duplicate(feature):
                    continue
                selected.append(feature)
                break

    ordered_families = CONCEPT_ORDER + [
        family for family in by_family
        if family not in CONCEPT_ORDER
    ]

    for family in ordered_families:
        if len(selected) >= limit:
            break
        if any(_operator_family(s["properties"].get("mass_shape", "")) == family for s in selected):
            continue
        for feature in by_family.get(family, []):
            if feature in selected or is_near_duplicate(feature):
                continue
            selected.append(feature)
            break

    if limit > len(selected) and not preferred_operator:
        grammar_candidates = [
            f for f in by_score
            if str(f["properties"].get("mass_shape", "")).startswith("grammar_")
        ]
        for feature in grammar_candidates:
            if len(selected) >= limit:
                break
            grammar_count = sum(
                1 for s in selected
                if str(s["properties"].get("mass_shape", "")).startswith("grammar_")
            )
            if grammar_count >= min(MIN_GRAMMAR_CONCEPTS, limit):
                break
            if feature in selected or is_near_duplicate(feature):
                continue
            selected.append(feature)

    # Only backfill same-family variants when the parcel yielded too few
    # concepts. For normal parcels, stop at one representative per spatial
    # concept so the UI does not become a list of near-identical stepbacks.
    min_required = limit
    while len(selected) < min_required:
        remaining = [f for f in by_score if f not in selected and not is_near_duplicate(f)]
        if not remaining:
            break
        selected_polys = [geojson_to_polygon(f["geometry"]) for f in selected]
        selected_sequences = [
            sequence_verbs(f["properties"].get("maas_verb_sequence"))
            for f in selected
        ]
        best = max(
            remaining,
            key=lambda f: (
                _capacity_score(f["properties"]) * 0.45
                + diversity_score(geojson_to_polygon(f["geometry"]), selected_polys, None) * 0.25
                + sequence_diversity_score(
                    sequence_verbs(f["properties"].get("maas_verb_sequence")),
                    selected_sequences,
                ) * 0.30
            ),
        )
        selected.append(best)

    if preferred_operator:
        return selected
    authored_count = sum(
        1 for feature in selected
        if str(feature["properties"].get("mass_shape") or "").startswith(("llm_", "agent_"))
    )
    if authored_count >= max(4, limit // 2):
        legal_index = next(
            (
                index for index, feature in enumerate(selected)
                if str(feature["properties"].get("mass_shape") or "") == "legal_layered_max"
            ),
            None,
        )
        if legal_index == 0 and len(selected) > 5:
            legal_anchor = selected.pop(legal_index)
            selected.insert(min(5, len(selected)), legal_anchor)
    return selected[:limit]


def _mass_feature(
    *,
    operator: str,
    footprint_utm,
    upper_footprint_utm,
    num_floors: int,
    lower_floor_fraction: float | None,
    site_utm,
    site_area_m2: float,
    building_type: str,
    notes: tuple[str, ...],
    diversity: float,
    source_iou: float,
) -> dict[str, Any]:
    floor_height = get_floor_height(building_type)
    height = num_floors * floor_height
    footprint_area = footprint_utm.area
    open_pct = max(0.0, 100.0 - (footprint_area / site_area_m2 * 100)) if site_area_m2 > 0 else 0.0

    lower_floors = num_floors
    upper_floors = 0
    lower_height = None
    if upper_footprint_utm is not None and num_floors >= 2:
        fraction = lower_floor_fraction if lower_floor_fraction is not None else 0.5
        lower_floors = max(1, min(num_floors - 1, int(round(num_floors * fraction))))
        upper_floors = num_floors - lower_floors
        lower_height = lower_floors * floor_height
        floor_area = footprint_area * lower_floors + upper_footprint_utm.area * upper_floors
    else:
        floor_area = footprint_area * num_floors

    props = {
        "algorithm": "maas_legal_envelope",
        "mass_shape": operator,
        "operator_family": _operator_family(operator),
        "typology_family": _operator_family(operator),
        "typology_source": "typology_first",
        "maas_concept": _concept_label(operator),
        "height": round(height, 2),
        "num_floors": num_floors,
        "floor_height": floor_height,
        "footprint_area": round(footprint_area, 2),
        "floor_area": round(floor_area, 2),
        "bcr": round(footprint_area / site_area_m2 * 100, 2) if site_area_m2 > 0 else 0,
        "far": round(floor_area / site_area_m2 * 100, 2) if site_area_m2 > 0 else 0,
        "min_setback": round(float(footprint_utm.distance(site_utm.boundary)), 2),
        "open_pct": round(open_pct, 2),
        "diversity_score": diversity,
        "source_iou": source_iou,
        "shape_signature": shape_signature(footprint_utm),
        "notes": list(notes),
    }
    if lower_height is not None and upper_footprint_utm is not None:
        props["lower_height"] = round(lower_height, 2)
        props["step_floor"] = lower_floors
        props["upper_geometry"] = mapping(utm_to_wgs84(upper_footprint_utm))
        props["typology_bands"] = [
            {
                "role": "lower",
                "from_floor": 1,
                "to_floor": lower_floors,
                "geometry": mapping(utm_to_wgs84(footprint_utm)),
            },
            {
                "role": "upper",
                "from_floor": lower_floors + 1,
                "to_floor": num_floors,
                "geometry": mapping(utm_to_wgs84(upper_footprint_utm)),
            },
        ]
    else:
        props["typology_bands"] = [
            {
                "role": "single",
                "from_floor": 1,
                "to_floor": num_floors,
                "geometry": mapping(utm_to_wgs84(footprint_utm)),
            }
        ]

    feature = {
        "type": "Feature",
        "geometry": mapping(utm_to_wgs84(footprint_utm)),
        "properties": props,
    }
    model = _single_volume_model(operator, feature)
    props["maas_model"] = model
    props["mass_volumes"] = model["volumes"]
    props["maas_verb_sequence"] = model["verb_sequence"]
    props["maas_sequence_verbs"] = sequence_verbs(model["verb_sequence"])
    _attach_geometry_resolution(
        feature,
        status="fallback_floor_plate_stack",
        source="legacy_operator",
        legal_action="single_or_interpolated_upper_mass",
    )
    _attach_section_profile(feature)
    _materialize_section_profile_volumes(feature)
    _attach_visual_diversity_evidence(feature)
    _attach_3d_diversity(feature)
    return feature


def _floor_plate_feature(
    *,
    stack: FloorPlateStack,
    site_utm,
    site_area_m2: float,
    building_type: str,
    diversity: float,
    source_iou: float,
) -> dict[str, Any]:
    floor_height = get_floor_height(building_type)
    footprint_area = stack.footprint.area
    open_pct = max(0.0, 100.0 - (footprint_area / site_area_m2 * 100)) if site_area_m2 > 0 else 0.0
    props = {
        "algorithm": "maas_legal_envelope",
        "mass_shape": stack.operator,
        "operator_family": _operator_family(stack.operator),
        "typology_family": _operator_family(stack.operator),
        "typology_source": "legal_floor_plate_anchor",
        "maas_concept": _concept_label(stack.operator),
        "building_type": building_type,
        "height": round(stack.height_m, 2),
        "num_floors": stack.num_floors,
        "floor_height": floor_height,
        "footprint_area": round(footprint_area, 2),
        "floor_area": round(stack.total_floor_area_m2, 2),
        "bcr": round(footprint_area / site_area_m2 * 100, 2) if site_area_m2 > 0 else 0,
        "far": round(stack.total_floor_area_m2 / site_area_m2 * 100, 2) if site_area_m2 > 0 else 0,
        "min_setback": round(float(stack.footprint.distance(site_utm.boundary)), 2),
        "open_pct": round(open_pct, 2),
        "diversity_score": diversity,
        "source_iou": source_iou,
        "shape_signature": shape_signature(stack.footprint),
        "notes": list(stack.notes),
    }
    model = _maas_model(
        operator=stack.operator,
        floor_plates=stack.floor_plates,
        props=props,
        site_area_m2=site_area_m2,
    )
    props["maas_model"] = model
    # Compatibility fields for existing UI/tests. The canonical source is
    # properties.maas_model, so agents should read that first.
    props["floor_plates"] = model["floor_plates"]
    props["floor_groups"] = model["floor_groups"]
    props["mass_volumes"] = model["volumes"]
    props["maas_verb_sequence"] = model["verb_sequence"]
    props["maas_sequence_verbs"] = sequence_verbs(model["verb_sequence"])
    feature = {
        "type": "Feature",
        "geometry": mapping(utm_to_wgs84(stack.footprint)),
        "properties": props,
    }
    _attach_section_profile(feature)
    _promote_legal_floor_stack_source_geometry(feature)
    _attach_visual_diversity_evidence(feature)
    _attach_3d_diversity(feature)
    return feature


_AUTHORED_SOURCE_IDENTITY_SCHEMA = "arr.maas.authored_source_identity.v1"


def _profiled_authored_visual(feature: dict[str, Any]) -> bool:
    props = (
        feature.get("properties")
        if isinstance(feature.get("properties"), dict)
        else {}
    )
    surfaces = props.get("source_surfaces")
    if any(
        isinstance(surface, dict)
        and str(surface.get("surface_type") or "").startswith("profiled_")
        for surface in surfaces or ()
    ):
        return True
    signature = (
        props.get("source_signature")
        if isinstance(props.get("source_signature"), dict)
        else {}
    )
    bridge = (
        signature.get("geometry_program_bridge_evidence")
        if isinstance(signature.get("geometry_program_bridge_evidence"), dict)
        else {}
    )
    return int(bridge.get("raw_mesh_triangle_count") or 0) > 0


def _source_identity(source: Any) -> dict[str, str] | None:
    metadata = (
        source.metadata
        if isinstance(getattr(source, "metadata", None), dict)
        else {}
    )
    bridge = metadata.get("geometry_program_bridge_evidence")
    bridge = bridge if isinstance(bridge, dict) else {}
    program_hash = str(bridge.get("program_hash") or "")
    geometry_hash = str(bridge.get("geometry_hash") or "")
    design_id = str(
        metadata.get("design_id")
        or metadata.get("candidate_id")
        or getattr(source, "name", "")
        or ""
    )
    if not (design_id and program_hash and geometry_hash):
        return None
    return {
        "schema_version": _AUTHORED_SOURCE_IDENTITY_SCHEMA,
        "design_id": design_id,
        "program_hash": program_hash,
        "geometry_hash": geometry_hash,
    }


def _feature_source_lineage(feature: dict[str, Any]) -> str:
    props = (
        feature.get("properties")
        if isinstance(feature.get("properties"), dict)
        else {}
    )
    identity = props.get("authored_source_identity")
    identity = identity if isinstance(identity, dict) else {}
    signature = (
        props.get("source_signature")
        if isinstance(props.get("source_signature"), dict)
        else {}
    )
    bridge = (
        signature.get("geometry_program_bridge_evidence")
        if isinstance(signature.get("geometry_program_bridge_evidence"), dict)
        else {}
    )
    design_id = str(identity.get("design_id") or "")
    program_hash = str(identity.get("program_hash") or "")
    geometry_hash = str(identity.get("geometry_hash") or "")
    if (
        identity.get("schema_version") != _AUTHORED_SOURCE_IDENTITY_SCHEMA
        or not (design_id and program_hash and geometry_hash)
        or program_hash != str(bridge.get("program_hash") or "")
        or geometry_hash != str(bridge.get("geometry_hash") or "")
    ):
        return ""
    return "|".join((design_id, program_hash, geometry_hash))


class _AuthoredSourceRegistry:
    """Keep immutable authored sources addressable across feature copies."""

    def __init__(self) -> None:
        self._by_feature_id: dict[int, tuple[str, Any]] = {}
        self._by_lineage: dict[str, Any] = {}
        self._ambiguous_lineages: set[str] = set()

    def remember(self, feature: dict[str, Any], source: Any) -> None:
        if source is None:
            return
        identity = _source_identity(source)
        if identity is None:
            return
        props = feature.setdefault("properties", {})
        props["authored_source_identity"] = dict(identity)
        model = props.get("maas_model")
        if isinstance(model, dict):
            model["authored_source_identity"] = dict(identity)
        lineage = _feature_source_lineage(feature)
        if not lineage:
            return
        self._by_feature_id[id(feature)] = (lineage, source)
        existing = self._by_lineage.get(lineage)
        if lineage in self._ambiguous_lineages:
            return
        if existing is not None and existing is not source:
            self._by_lineage.pop(lineage, None)
            self._ambiguous_lineages.add(lineage)
            return
        self._by_lineage[lineage] = source

    def source_for_revalidation(self, feature: dict[str, Any]) -> Any:
        lineage = _feature_source_lineage(feature)
        if _profiled_authored_visual(feature) and not lineage:
            return None
        registered = self._by_feature_id.get(id(feature))
        if registered is not None:
            registered_lineage, source = registered
            return source if registered_lineage == lineage else None
        if lineage in self._ambiguous_lineages:
            return None
        return self._by_lineage.get(lineage) if lineage else None


def generate_legal_mass_variants(
    *,
    mass_geojson: dict[str, Any],
    site_polygon_geojson: dict[str, Any],
    constraints: list[dict[str, Any]] | None = None,
    building_type: str = "공동주택",
    max_variants: int = 6,
    sunlight_envelope: dict[str, Any] | None = None,
    setback_geometries: dict[str, Any] | None = None,
    include_interactive_seed: bool = False,
    preferred_operator: str | None = None,
    pnu: str | None = None,
    parking_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return legal, diverse variants derived from a selected mass GeoJSON."""
    generation_trace = GenerationTrace.from_environment()

    if mass_geojson.get("type") != "Feature":
        raise ValueError("mass_geojson must be a GeoJSON Feature")

    source_wgs = largest_polygon(geojson_to_polygon(mass_geojson.get("geometry")))
    source_utm = wgs84_to_utm(source_wgs)
    site_wgs = geojson_to_polygon(site_polygon_geojson)
    site_utm = wgs84_to_utm(site_wgs)
    site_area_m2 = site_utm.area

    envelope = build_legal_envelope(
        site_utm=site_utm,
        constraints=constraints,
        building_type=building_type,
        sunlight_envelope=sunlight_envelope,
        setback_geometries=setback_geometries,
    )
    generation_trace.checkpoint("legal_envelope_ready")
    limits = envelope.limits
    max_seed_floors = envelope.max_seed_floors
    capacity_policy = _massing_capacity_policy(
        building_type=building_type,
        site_area_m2=site_area_m2,
        parking_options=parking_options,
    )

    repaired_source, repaired_floors, source_actions = repair_design(
        source_utm, site_utm, max_seed_floors, limits,
        sunlight_envelope=sunlight_envelope,
    )
    if repaired_source is None:
        raise ValueError("source mass cannot be repaired into the site/legal envelope")
    generation_trace.checkpoint("source_repair_ready")

    selected = []
    selected_polygons = []
    rejected = []
    llm_loop_artifact: dict[str, Any] | None = None
    llm_loop_config = _llm_loop_config(parking_options)
    preference_loop_artifact: dict[str, Any] | None = None
    final_vlm_completion_artifact: dict[str, Any] | None = None
    preference_loop_config = build_preference_loop_config(parking_options)
    preference_ranked_pool: list[dict[str, Any]] = []
    evolution_trace_artifact: dict[str, Any] | None = None
    critic_geometry_loop_artifact: dict[str, Any] | None = None
    mass_brain_shadow_artifact: dict[str, Any] = {
        "schema_version": "arr.maas.mass_brain_shadow.v1",
        "status": "not_requested",
    }
    mass_brain_proposals_by_operator: dict[str, dict[str, Any]] = {}
    mass_brain_shadow_features: dict[str, dict[str, Any]] = {}
    authored_source_registry = _AuthoredSourceRegistry()

    def revalidate_floorwise_candidates(
        features: list[dict[str, Any]],
        *,
        scope: str,
    ) -> list[dict[str, Any]]:
        validated: list[dict[str, Any]] = []
        for candidate in features:
            authored_source = authored_source_registry.source_for_revalidation(
                candidate
            )
            outcome = revalidate_final_floorwise_feature(
                candidate,
                envelope=envelope,
                sunlight_envelope=sunlight_envelope,
                building_type=building_type,
                authored_source=authored_source,
            )
            if outcome.feature is None:
                failed_checks = list(
                    outcome.evidence.get("failed_checks") or []
                )
                rejected.append({
                    "operator": str((candidate.get("properties") or {}).get("mass_shape") or "unknown"),
                    "reason": (
                        "authored_floorwise_visual_reprojection_failed"
                        if "authored_floorwise_visual_reprojection_failed"
                        in failed_checks
                        else "floorwise_legal_validation_failed"
                    ),
                    "scope": scope,
                    "failed_checks": failed_checks,
                    "floorwise_legal_evidence": outcome.evidence,
                })
                continue
            feature = outcome.feature
            authored_source_registry.remember(
                feature,
                outcome.authored_source or authored_source,
            )
            props = feature["properties"]
            measured_far_utilization = (
                float(props.get("far") or 0.0) / envelope.far_limit
                if envelope.far_limit > 0
                else 0.0
            )
            minimum_far_utilization = float(capacity_policy["min_far_utilization"])
            if measured_far_utilization < minimum_far_utilization:
                rejected.append({
                    "operator": str(props.get("mass_shape") or "unknown"),
                    "reason": "underused_floorwise_legal_far_capacity",
                    "scope": scope,
                    "measured_far_utilization": round(measured_far_utilization, 4),
                    "minimum_far_utilization": minimum_far_utilization,
                    "floorwise_legal_evidence": outcome.evidence,
                })
                continue
            props["far_utilization"] = (
                round(min(1.0, measured_far_utilization), 4)
                if envelope.far_limit > 0
                else 0.0
            )
            props["bcr_utilization"] = (
                round(min(1.0, float(props.get("bcr") or 0.0) / envelope.bcr_limit), 4)
                if envelope.bcr_limit > 0
                else 0.0
            )
            props["maas_score"] = round(
                props["far_utilization"] * 0.45
                + props["bcr_utilization"] * 0.35
                + float(props.get("diversity_score") or 0.0) * 0.20,
                4,
            )
            ground_utm = wgs84_to_utm(geojson_to_polygon(feature["geometry"]))
            _attach_design_quality(feature, ground_utm)
            attach_program_massing_evidence(feature, building_type=building_type)
            attach_parking_strategy(
                props,
                site_area_m2=site_area_m2,
                building_type=building_type,
                footprint_utm=ground_utm,
                site_utm=site_utm,
            )
            _attach_visual_diversity_evidence(feature)
            _attach_3d_diversity(feature)
            validated.append(feature)
        return validated

    layered_stack = build_floor_plate_stack(envelope, sunlight_envelope)
    generation_trace.checkpoint("floor_plate_stack_ready", available=layered_stack is not None)
    if layered_stack is not None:
        source_iou = round(1.0 - diversity_score(layered_stack.footprint, [], repaired_source), 4)
        diversity = diversity_score(layered_stack.footprint, selected_polygons, repaired_source)
        feature = _floor_plate_feature(
            stack=layered_stack,
            site_utm=site_utm,
            site_area_m2=site_area_m2,
            building_type=building_type,
            diversity=diversity,
            source_iou=source_iou,
        )
        props = feature["properties"]
        _attach_repair_delta(
            feature,
            source_area_m2=float(getattr(repaired_source, "area", 0.0) or 0.0),
            repaired_area_m2=float(getattr(layered_stack.footprint, "area", 0.0) or 0.0),
            actions=source_actions,
            scope="legal_floor_plate_stack",
        )
        failed_metrics = failed_constraint_metrics(props, envelope)
        if failed_metrics:
            rejected.append({
                "operator": layered_stack.operator,
                "reason": "legal_metric_failed_after_layering",
                "failed_metrics": failed_metrics,
            })
        else:
            far_utilization = min(1.0, props["far"] / envelope.far_limit) if envelope.far_limit > 0 else 0.0
            bcr_utilization = min(1.0, props["bcr"] / envelope.bcr_limit) if envelope.bcr_limit > 0 else 0.0
            props["far_utilization"] = round(far_utilization, 4)
            props["bcr_utilization"] = round(bcr_utilization, 4)
            props["massing_capacity_policy"] = dict(capacity_policy)
            props["maas_score"] = round(far_utilization * 0.52 + bcr_utilization * 0.30 + diversity * 0.18, 4)
            _attach_design_quality(feature, layered_stack.footprint)
            attach_program_massing_evidence(feature, building_type=building_type)
            selected.append(feature)
            selected_polygons.append(layered_stack.footprint)

    variants = generate_seed_variants(
        repaired_source,
        envelope,
        include_interactive_seed=include_interactive_seed,
        building_type=building_type,
    )
    generation_trace.checkpoint("seed_variants", count=len(variants))
    if llm_loop_config["enabled"] and not preferred_operator:
        generation_feedback = _load_generation_feedback(llm_loop_config)
        site_context = build_site_context(
            site_area_m2=site_area_m2,
            building_type=building_type,
            limits={
                "far": envelope.far_limit,
                "bcr": envelope.bcr_limit,
                "height": envelope.height_limit,
                "max_seed_floors": envelope.max_seed_floors,
            },
            max_variants=max_variants,
            site_polygon=site_utm,
            access_context=(parking_options or {}).get("road_context") or {},
        )
        try:
            llm_batch = LLMArchitectAgent().propose_population(
                site_context=site_context,
                target_count=int(llm_loop_config["target_count"]),
                model=llm_loop_config["model"],
                timeout=float(llm_loop_config["timeout"]),
                batch_size=int(llm_loop_config["batch_size"]),
                batch_retries=int(llm_loop_config["batch_retries"]),
                batch_workers=int(llm_loop_config.get("batch_workers") or 1),
                max_openai_batches=(
                    int(llm_loop_config["max_openai_batches"])
                    if int(llm_loop_config.get("max_openai_batches") or 0) > 0
                    else None
                ),
                max_output_tokens=int(llm_loop_config["max_output_tokens"]),
                overgenerate_count=int(llm_loop_config.get("overgenerate_count") or 0),
                cache_path=llm_loop_config.get("batch_cache_path") or None,
                generation_feedback=generation_feedback,
            )
            compile_limit = int(llm_loop_config.get("compile_limit") or 90)
            llm_variants = [
                variant
                for sequence in llm_batch.sequences[:compile_limit]
                for variant in [interpret_sequence(repaired_source, sequence)]
                if variant is not None
            ]
            llm_loop_artifact = dict(llm_batch.artifact)
            llm_loop_artifact["compiled_variant_count"] = len(llm_variants)
            llm_loop_artifact["status"] = "compiled"
            llm_loop_artifact["generation_feedback_enabled"] = bool(generation_feedback)
            evolution_result = evolve_massdsl_islands(
                base_footprint=repaired_source,
                seed_sequences=llm_batch.sequences[:compile_limit],
                interpret=interpret_sequence,
                max_children=max(12, min(48, compile_limit // 2)),
            )
            evolution_trace_artifact = evolution_result.trace
            if evolution_result.variants:
                llm_loop_artifact["evolved_variant_count"] = len(evolution_result.variants)
                variants = evolution_result.variants + llm_variants + variants
            else:
                variants = llm_variants + variants
        except (LlmProposalError, ValueError) as exc:
            llm_loop_artifact = {
                "schema_version": LLM_BATCH_SCHEMA_VERSION,
                "status": "failed",
                "provider": "openai",
                "error": str(exc),
                "required": bool(llm_loop_config["required"]),
            }
            if llm_loop_config["required"]:
                raise ValueError(f"required MAAS LLM proposal loop failed: {exc}") from exc

    if evolution_trace_artifact is None and not preferred_operator:
        seed_sequences = [
            sequence
            for variant in variants
            for sequence in [sequence_from_variant(variant)]
            if sequence is not None
        ]
        evolution_result = evolve_massdsl_islands(
            base_footprint=repaired_source,
            seed_sequences=seed_sequences,
            interpret=interpret_sequence,
            # Candidate work must scale with the requested review set. The
            # previous fixed 96-child expansion sent research debris through
            # every expensive 3D/graph/parking stage and made a 20-card service
            # call exceed ten minutes. Program seeds plus round-robin islands
            # preserve typology coverage within this bounded over-generation.
            max_children=max(24, min(48, int(max_variants) * 2)),
        )
        evolution_trace_artifact = evolution_result.trace
        if evolution_result.variants:
            variants = evolution_result.variants + variants

    if not preferred_operator:
        mass_brain_project_key = str(
            pnu
            or (mass_geojson.get("properties") or {}).get("project_key")
            or (mass_geojson.get("properties") or {}).get("variant_id")
            or "arr-mass-anonymous"
        )
        mass_brain_batch = request_shadow_variants(
            base_footprint=repaired_source,
            source_variants=variants,
            project_key=mass_brain_project_key,
            interpret=interpret_sequence,
            parking_options=parking_options,
            program_type=building_type,
        )
        mass_brain_shadow_artifact = dict(mass_brain_batch.artifact)
        mass_brain_proposals_by_operator = dict(mass_brain_batch.proposals_by_operator)
        if mass_brain_batch.variants:
            variants = list(mass_brain_batch.variants) + variants

    generation_trace.checkpoint("candidate_pool_ready", count=len(variants))
    for variant_index, variant in enumerate(variants, start=1):
        if variant_index == 1 or variant_index % 10 == 0:
            generation_trace.checkpoint("candidate_evaluation", index=variant_index, count=len(variants))
        repaired_fp, floors, actions = repair_design(
            variant.footprint,
            site_utm,
            max_seed_floors,
            limits,
            sunlight_envelope=sunlight_envelope,
        )
        if repaired_fp is None:
            rejected.append({"operator": variant.operator, "reason": "repair_failed"})
            continue

        upper = variant.upper_footprint
        if upper is not None:
            upper = upper.intersection(repaired_fp)
            if upper.is_empty or upper.area < 1.0:
                upper = None
            elif (
                not variant.operator.startswith(("agent_", "llm_"))
                and not _upper_typology_is_viable(repaired_fp, upper)
            ):
                rejected.append({
                    "operator": variant.operator,
                    "reason": "upper_typology_too_small_for_architectural_mass",
                    "upper_area_m2": round(float(upper.area), 2),
                    "lower_area_m2": round(float(repaired_fp.area), 2),
                })
                continue

        source_iou = round(1.0 - diversity_score(repaired_fp, [], repaired_source), 4)
        diversity = diversity_score(repaired_fp, selected_polygons, repaired_source)
        review_floors = _capacity_projected_floors(
            repaired_fp,
            upper,
            lower_floor_fraction=variant.lower_floor_fraction,
            site_area_m2=site_area_m2,
            far_limit=envelope.far_limit,
            floor_height=get_floor_height(building_type),
            height_limit=envelope.height_limit,
        )
        # Capacity ALT is not a research-maquette lane. Reject an underfilled
        # topology before building floor-by-floor geometry, graph evidence,
        # parking evidence and VLM payloads. This both prevents thin LEGO-like
        # fragments from reaching the selector and keeps the service bounded.
        projected_floor_area = _capacity_projected_floor_area(
            repaired_fp,
            upper,
            floors=review_floors,
            lower_floor_fraction=variant.lower_floor_fraction,
        )
        projected_far_utilization = (
            projected_floor_area / (site_area_m2 * envelope.far_limit / 100.0)
            if site_area_m2 > 0 and envelope.far_limit > 0
            else 0.0
        )
        if projected_far_utilization < float(capacity_policy["min_far_utilization"]):
            rejected.append({
                "operator": variant.operator,
                "reason": "underused_legal_far_capacity_precheck",
                "projected_far_utilization": round(projected_far_utilization, 4),
            })
            continue
        variant_stack = None
        if _should_use_floor_plate_stack(variant.operator, preferred_operator):
            variant_stack = build_floor_plate_stack(
                envelope,
                sunlight_envelope,
                operator=variant.operator if variant.operator == preferred_operator else f"{variant.operator}_layered",
                ground_footprint=repaired_fp,
                upper_footprint=upper,
                lower_floor_fraction=variant.lower_floor_fraction,
            )
        if (
            variant_stack is not None
            and variant_stack.total_floor_area_m2 >= repaired_fp.area
            and _stack_has_meaningful_top(variant_stack)
        ):
            feature = _floor_plate_feature(
                stack=variant_stack,
                site_utm=site_utm,
                site_area_m2=site_area_m2,
                building_type=building_type,
                diversity=diversity,
                source_iou=source_iou,
            )
            feature["properties"]["notes"].extend(list(variant.notes + tuple(actions)))
            _apply_variant_verb_sequence(feature, variant)
        else:
            feature = _mass_feature(
                operator=variant.operator,
                footprint_utm=repaired_fp,
                upper_footprint_utm=upper,
                num_floors=review_floors,
                lower_floor_fraction=variant.lower_floor_fraction,
                site_utm=site_utm,
                site_area_m2=site_area_m2,
                building_type=building_type,
                notes=variant.notes + tuple(actions),
                diversity=diversity,
                source_iou=source_iou,
            )
            _apply_variant_verb_sequence(feature, variant)
        authored_source_registry.remember(
            feature,
            getattr(variant, "source_mass", None),
        )
        props = feature["properties"]
        _attach_repair_delta(
            feature,
            source_area_m2=float(getattr(variant.footprint, "area", 0.0) or 0.0),
            repaired_area_m2=float(getattr(repaired_fp, "area", 0.0) or 0.0),
            actions=actions,
            scope="legal_footprint",
        )
        if (
            variant.operator == "grammar_sunlight_multi_step"
            and len(props.get("mass_volumes") or []) < 3
        ):
            rejected.append({
                "operator": variant.operator,
                "reason": "not_enough_floor_bands_for_multi_step",
            })
            continue
        failed_metrics = failed_constraint_metrics(props, envelope)
        if failed_metrics:
            rejected.append({
                "operator": variant.operator,
                "reason": "legal_metric_failed_after_repair",
                "failed_metrics": failed_metrics,
            })
            continue

        far_utilization = min(1.0, props["far"] / envelope.far_limit) if envelope.far_limit > 0 else 0.0
        bcr_utilization = min(1.0, props["bcr"] / envelope.bcr_limit) if envelope.bcr_limit > 0 else 0.0
        props["far_utilization"] = round(far_utilization, 4)
        props["bcr_utilization"] = round(bcr_utilization, 4)
        props["massing_capacity_policy"] = dict(capacity_policy)
        props["maas_score"] = round(far_utilization * 0.45 + bcr_utilization * 0.35 + diversity * 0.20, 4)
        if variant.operator.startswith("llm_"):
            props["llm_candidate_quality"] = _llm_candidate_quality(feature)
        _attach_design_quality(feature, repaired_fp)
        attach_program_massing_evidence(feature, building_type=building_type)
        if variant.operator in mass_brain_proposals_by_operator:
            proposal = mass_brain_proposals_by_operator[variant.operator]
            props["mass_brain_shadow"] = {
                "schema_version": "arr.maas.mass_brain_candidate.v1",
                "proposal_id": proposal.get("proposalId"),
                "lane": proposal.get("lane"),
                "source_node_ids": proposal.get("sourceNodeIds") or [],
                "evidence_ids": proposal.get("evidenceIds") or [],
                "score_breakdown": proposal.get("scoreBreakdown") or {},
                "relation_profile": proposal.get("relationProfile") or {},
                "behavior_cell": proposal.get("behaviorCell"),
                "selection_effect": "none_shadow_only",
            }
            mass_brain_shadow_features[variant.operator] = feature
            continue
        selected.append(feature)
        selected_polygons.append(repaired_fp)

    generation_trace.checkpoint("candidate_evaluation_complete", selected=len(selected), rejected=len(rejected))

    if mass_brain_proposals_by_operator:
        shadow_features = list(mass_brain_shadow_features.values())
        shadow_features = revalidate_floorwise_candidates(
            shadow_features,
            scope="mass_brain_shadow_pre_parking",
        )
        mass_brain_shadow_features = {
            str((feature.get("properties") or {}).get("mass_shape") or ""): feature
            for feature in shadow_features
        }
        if shadow_features:
            _attach_parking_requirements(
                shadow_features,
                pnu=pnu,
                building_type=building_type,
                site_utm=site_utm,
                site_area_m2=site_area_m2,
                parking_options=parking_options,
            )
        mass_brain_project_key = str(mass_brain_shadow_artifact.get("project_key") or pnu or "arr-mass-anonymous")
        mass_brain_shadow_artifact["outcomes"] = record_shadow_outcomes(
            project_key=mass_brain_project_key,
            proposals_by_operator=mass_brain_proposals_by_operator,
            features_by_operator=mass_brain_shadow_features,
            run_id=str(mass_brain_shadow_artifact.get("run_id") or "") or None,
        )
        mass_brain_shadow_artifact["evaluated_feature_count"] = len(shadow_features)
        mass_brain_shadow_artifact["feature_collection"] = {
            "type": "FeatureCollection",
            "features": shadow_features,
        }
        rollout = mass_brain_shadow_artifact.get("rollout") if isinstance(mass_brain_shadow_artifact.get("rollout"), dict) else {}
        active_slots = min(4, max(0, int(rollout.get("slots") or 0))) if rollout.get("mode") == "active" else 0
        if active_slots:
            promotable = [
                feature for feature in shadow_features
                if final_mass_stage_parking_pass(feature)
                and _architectural_order_gate(feature)[0]
                and _has_review_source_geometry(feature)
            ]
            promotable.sort(key=lambda feature: float((((feature.get("properties") or {}).get("mass_brain_shadow") or {}).get("score_breakdown") or {}).get("total") or 0.0), reverse=True)
            for feature in promotable[:active_slots]:
                feature["properties"]["mass_brain_shadow"]["selection_effect"] = "promotion_eligible_active_pool"
                selected.append(feature)
            mass_brain_shadow_artifact["promoted_pool_count"] = min(active_slots, len(promotable))

    selected = revalidate_floorwise_candidates(selected, scope="pre_parking_preference_pool")
    generation_trace.checkpoint(
        "floorwise_legal_boundary_complete",
        selected=len(selected),
        rejected=len(rejected),
    )
    selected.sort(key=lambda f: f["properties"].get("maas_score", 0), reverse=True)
    legal_candidate_pool = build_bounded_review_pool(
        selected,
        max_variants=max_variants,
        preferred_operator=preferred_operator,
        select_diverse=_select_diverse_features,
    )
    selected = list(legal_candidate_pool)
    if preferred_operator:
        preferred_index = next(
            (
                i for i, feature in enumerate(selected)
                if feature["properties"].get("mass_shape") == preferred_operator
            ),
            None,
        )
        if preferred_index is not None:
            selected.insert(0, selected.pop(preferred_index))
    selected = _select_diverse_features(selected, max(1, max_variants), preferred_operator=preferred_operator)
    generation_trace.checkpoint("initial_selection", selected=len(selected), pool=len(legal_candidate_pool))
    parking_scan_features = list(selected)
    if not preferred_operator:
        parking_scan_features.extend(
            feature for feature in legal_candidate_pool
            if feature not in parking_scan_features
        )
    _attach_parking_requirements(
        parking_scan_features,
        pnu=pnu,
        building_type=building_type,
        site_utm=site_utm,
        site_area_m2=site_area_m2,
        parking_options=parking_options,
    )
    generation_trace.checkpoint("parking_scan_complete", scanned=len(parking_scan_features))
    parking_viable_extras = [
        feature for feature in parking_scan_features
        if feature not in selected and _parking_priority_key(feature)[0] > 0
    ]
    parking_viable_extras.sort(key=_parking_priority_key, reverse=True)
    for feature in parking_viable_extras[:3]:
        selected.append(feature)
    parking_repairs = []
    # A PNU requests site/legal evaluation; it does not authorize an expensive
    # geometry rewrite. Opt into repair explicitly after the mass-stage layout
    # reports that a chosen design needs it.
    if (parking_options or {}).get("enable_parking_repair"):
        parking_repairs = _parking_repair_candidates(
            selected,
            envelope=envelope,
            site_utm=site_utm,
            site_area_m2=site_area_m2,
            building_type=building_type,
            parking_options=parking_options,
            max_results=parking_repair_budget(max_variants),
        )
    if parking_repairs:
        parking_repairs = revalidate_floorwise_candidates(
            parking_repairs,
            scope="parking_repair",
        )
    if parking_repairs:
        _attach_parking_requirements(
            parking_repairs,
            pnu=pnu,
            building_type=building_type,
            site_utm=site_utm,
            site_area_m2=site_area_m2,
            parking_options=parking_options,
        )
        _sync_parking_repair_metadata(parking_repairs)
        selected.extend(parking_repairs)
    generation_trace.checkpoint("parking_repairs_complete", repairs=len(parking_repairs), selected=len(selected))
    for feature in selected:
        attach_program_massing_evidence(feature, building_type=building_type)
    parking_visible = [
        feature for feature in selected
        if _parking_priority_key(feature)[1] > 0
    ]
    parking_visible.sort(key=_parking_priority_key, reverse=True)
    review_candidates = [
        feature for feature in selected
        if feature not in parking_visible
    ]
    review_candidates.sort(key=_review_diversity_priority_key, reverse=True)
    selected = parking_visible + review_candidates
    if not preferred_operator:
        supplemental_design_candidates = [
            feature for feature in legal_candidate_pool
            if feature not in selected
            and _is_reviewable_architectural_mass(feature)
            and not _is_plain_capacity_anchor(feature)
            and (
                _is_authored_mass_candidate(feature)
                or _design_synthesis_rank(feature) > 0
                or _visible_volume_count(feature) > 1
            )
        ]
        if supplemental_design_candidates:
            _attach_parking_requirements(
                supplemental_design_candidates,
                pnu=pnu,
                building_type=building_type,
                site_utm=site_utm,
                site_area_m2=site_area_m2,
                parking_options=parking_options,
            )
        supplemental_design_candidates.sort(key=_design_review_quality_key, reverse=True)
        for feature in supplemental_design_candidates:
            selected.append(feature)
            if len(selected) >= max_variants * 5:
                break
        research_family_reps: list[dict[str, Any]] = []
        for family in RESEARCH_TARGET_FAMILIES:
            options = [
                feature for feature in legal_candidate_pool
                if _source_family(feature) == family
                and _is_reviewable_architectural_mass(feature)
            ]
            options.sort(key=_design_review_quality_key, reverse=True)
            if options:
                research_family_reps.append(options[0])
        if research_family_reps:
            _attach_parking_requirements(
                research_family_reps,
                pnu=pnu,
                building_type=building_type,
                site_utm=site_utm,
                site_area_m2=site_area_m2,
                parking_options=parking_options,
            )
            pinned_ids = {id(feature) for feature in research_family_reps}
            selected = research_family_reps + [
                feature for feature in selected
                if id(feature) not in pinned_ids
            ]
        agent_reps = [
            feature for feature in legal_candidate_pool
            if _is_agent_authored_candidate(feature)
            and _has_review_source_geometry(feature)
            and feature not in selected
        ]
        agent_reps.sort(key=_design_review_quality_key, reverse=True)
        if agent_reps:
            _attach_parking_requirements(
                agent_reps,
                pnu=pnu,
                building_type=building_type,
                site_utm=site_utm,
                site_area_m2=site_area_m2,
                parking_options=parking_options,
            )
            selected.extend(agent_reps[:max_variants])
    piloti_seen_ids: set[int] = set()
    for feature in [*selected, *legal_candidate_pool]:
        if id(feature) in piloti_seen_ids:
            continue
        piloti_seen_ids.add(id(feature))
        _apply_piloti_parking_void(feature)
    generation_trace.checkpoint("parking_geometry_frozen_before_preference", count=len(piloti_seen_ids))
    if preferred_operator:
        preferred_index = next(
            (
                i for i, feature in enumerate(selected)
                if feature["properties"].get("mass_shape") == preferred_operator
            ),
            None,
        )
        if preferred_index is not None:
            selected.insert(0, selected.pop(preferred_index))
    elif max_variants >= 20:
        agent_pins = [
            feature for feature in legal_candidate_pool
            if _is_agent_authored_candidate(feature)
            and _has_review_source_geometry(feature)
            and (feature.get("properties", {}).get("llm_candidate_quality", {}).get("status") != "reject_final_review")
        ]
        agent_pins.sort(key=_design_review_quality_key, reverse=True)
        seen_agent_shapes: set[str] = set()
        unique_agent_pins: list[dict[str, Any]] = []
        for feature in agent_pins:
            shape = str((feature.get("properties") or {}).get("mass_shape") or "")
            if shape in seen_agent_shapes:
                continue
            seen_agent_shapes.add(shape)
            unique_agent_pins.append(feature)
        pinned_ids = {id(feature) for feature in unique_agent_pins}
        selected = unique_agent_pins + [
            feature for feature in selected
            if id(feature) not in pinned_ids
        ]
    if not preferred_operator and max_variants >= 20:
        selected_ids = {id(feature) for feature in selected}
        architecture_pass_pool = [
            feature for feature in legal_candidate_pool
            if id(feature) not in selected_ids
            and _has_review_source_geometry(feature)
            and _is_reviewable_architectural_mass(feature)
            and _architectural_order_gate(feature)[0]
            and not _is_plain_capacity_anchor(feature)
        ]
        architecture_pass_pool.sort(key=_design_review_quality_key, reverse=True)
        selected.extend(architecture_pass_pool)
    if not preferred_operator:
        preference_source_pool: list[dict[str, Any]] = []
        seen_preference_ids: set[int] = set()
        for feature in [*selected, *legal_candidate_pool]:
            if id(feature) in seen_preference_ids:
                continue
            seen_preference_ids.add(id(feature))
            preference_source_pool.append(feature)
        generation_trace.checkpoint("preference_loop_start", pool=len(preference_source_pool))
        preference_loop_artifact = apply_preference_loop(
            preference_source_pool,
            config=preference_loop_config,
            callbacks=PreferenceLoopCallbacks(
                design_review_quality_key=_design_review_quality_key,
                final_mass_stage_parking_pass=final_mass_stage_parking_pass,
                has_review_source_geometry=_has_review_source_geometry,
                is_plain_capacity_anchor=_is_plain_capacity_anchor,
                is_reviewable_architectural_mass=_is_vlm_review_candidate,
                source_family=_source_family,
            ),
        )
        generation_trace.checkpoint("preference_loop_complete", pool=len(preference_source_pool))
        preference_ranked_pool = list(preference_source_pool)
        selected_ids = {id(feature) for feature in selected}
        selected = [
            feature for feature in preference_source_pool
            if id(feature) in selected_ids
        ] + [
            feature for feature in preference_source_pool
            if id(feature) not in selected_ids
        ]
        actionable = [
            feature for feature in preference_source_pool
            if isinstance(((feature.get("properties") or {}).get("preference_distillation") or {}).get("critic_actions"), list)
            and ((feature.get("properties") or {}).get("preference_distillation") or {}).get("critic_actions")
        ]
        if actionable:
            def evaluate_critic_variant(variant) -> dict[str, Any] | None:
                repaired_fp, floors, actions = repair_design(
                    variant.footprint,
                    site_utm,
                    max_seed_floors,
                    limits,
                    sunlight_envelope=sunlight_envelope,
                )
                if repaired_fp is None:
                    return None
                upper = variant.upper_footprint
                if upper is not None:
                    upper = upper.intersection(repaired_fp)
                    if upper.is_empty or upper.area < 1.0:
                        upper = None
                review_floors = _capacity_projected_floors(
                    repaired_fp,
                    upper,
                    lower_floor_fraction=variant.lower_floor_fraction,
                    site_area_m2=site_area_m2,
                    far_limit=envelope.far_limit,
                    floor_height=get_floor_height(building_type),
                    height_limit=envelope.height_limit,
                )
                feature = _mass_feature(
                    operator=variant.operator,
                    footprint_utm=repaired_fp,
                    upper_footprint_utm=upper,
                    num_floors=review_floors,
                    lower_floor_fraction=variant.lower_floor_fraction,
                    site_utm=site_utm,
                    site_area_m2=site_area_m2,
                    building_type=building_type,
                    notes=variant.notes + tuple(actions),
                    diversity=diversity_score(repaired_fp, selected_polygons, repaired_source),
                    source_iou=round(1.0 - diversity_score(repaired_fp, [], repaired_source), 4),
                )
                _apply_variant_verb_sequence(feature, variant)
                authored_source_registry.remember(
                    feature,
                    getattr(variant, "source_mass", None),
                )
                _attach_repair_delta(
                    feature,
                    source_area_m2=float(getattr(variant.footprint, "area", 0.0) or 0.0),
                    repaired_area_m2=float(getattr(repaired_fp, "area", 0.0) or 0.0),
                    actions=actions,
                    scope="critic_legal_footprint",
                )
                validated_children = revalidate_floorwise_candidates(
                    [feature],
                    scope="critic_geometry_child",
                )
                if not validated_children:
                    return None
                feature = validated_children[0]
                props = feature["properties"]
                props["far_utilization"] = min(1.0, props["far"] / envelope.far_limit) if envelope.far_limit > 0 else 0.0
                props["bcr_utilization"] = min(1.0, props["bcr"] / envelope.bcr_limit) if envelope.bcr_limit > 0 else 0.0
                props["maas_score"] = round(props["far_utilization"] * 0.45 + props["bcr_utilization"] * 0.35, 4)
                _attach_design_quality(feature, repaired_fp)
                _attach_parking_requirements(
                    [feature],
                    pnu=pnu,
                    building_type=building_type,
                    site_utm=site_utm,
                    site_area_m2=site_area_m2,
                    parking_options=parking_options,
                )
                _apply_piloti_parking_void(feature)
                _attach_visual_diversity_evidence(feature)
                if not final_mass_stage_parking_pass(feature) or not _architectural_order_gate(feature)[0]:
                    return None
                return feature

            def rescore_critic_children(children: list[dict[str, Any]]) -> None:
                if not children:
                    return
                revision_config = {**preference_loop_config, "top_k": len(children)}
                apply_preference_loop(
                    children,
                    config=revision_config,
                    callbacks=PreferenceLoopCallbacks(
                        design_review_quality_key=_design_review_quality_key,
                        final_mass_stage_parking_pass=final_mass_stage_parking_pass,
                        has_review_source_geometry=_has_review_source_geometry,
                        is_plain_capacity_anchor=_is_plain_capacity_anchor,
                        is_reviewable_architectural_mass=_is_vlm_review_candidate,
                        source_family=_source_family,
                    ),
                )

            critic_result = run_critic_geometry_loop(
                base_footprint=repaired_source,
                scored_features=actionable,
                interpret=interpret_sequence,
                evaluate=evaluate_critic_variant,
                rescore=rescore_critic_children,
                quality_key=_design_review_quality_key,
                objective_vector=_critic_objective_vector,
                max_generations=2,
            )
            critic_geometry_loop_artifact = critic_result.trace
            if critic_result.accepted:
                accepted_ids = {id(feature) for feature in critic_result.accepted}
                legal_candidate_pool.extend(critic_result.accepted)
                pareto = _pareto_front(legal_candidate_pool)
                medoids = _kmedoid_representatives(
                    pareto,
                    k=min(max_variants * 2, len(pareto)),
                )
                medoid_ids = {id(feature) for feature in medoids}
                legal_candidate_pool = medoids + [
                    feature for feature in legal_candidate_pool
                    if id(feature) not in medoid_ids
                ]
                critic_geometry_loop_artifact["pareto_front_count"] = len(pareto)
                critic_geometry_loop_artifact["kmedoid_representative_count"] = len(medoids)
                critic_geometry_loop_artifact["kmedoid_representatives"] = [
                    str((feature.get("properties") or {}).get("mass_shape") or "")
                    for feature in medoids
                ]
                selected = critic_result.accepted + [feature for feature in selected if id(feature) not in accepted_ids]
                preference_ranked_pool.extend(critic_result.accepted)
    final_limit = max(1, max_variants)
    selected = _preserve_visible_section_connector(
        selected,
        final_limit=final_limit,
        preferred_operator=preferred_operator,
    )
    if not preferred_operator and max_variants >= 20:
        selected_ids = {id(feature) for feature in selected}
        selected = selected + [
            feature for feature in legal_candidate_pool
            if id(feature) not in selected_ids
            and _has_review_source_geometry(feature)
            and _is_reviewable_architectural_mass(feature)
            and final_mass_stage_parking_pass(feature)
        ]
    selected = _final_design_balanced_selection(
        selected,
        final_limit=final_limit,
        preferred_operator=preferred_operator,
    )
    selected = refine_final_review_set(
        selected,
        legal_candidate_pool=legal_candidate_pool,
        final_limit=final_limit,
        preferred_operator=preferred_operator,
        callbacks=FinalReviewRefinementCallbacks(
            design_review_quality_key=_design_review_quality_key,
            has_review_source_geometry=_has_review_source_geometry,
            is_agent_authored_candidate=_is_agent_authored_candidate,
            is_clean_layered_anchor=_is_clean_layered_anchor,
            is_direct_openai_llm_candidate=_is_direct_openai_llm_candidate,
            is_llm_authored_candidate=_is_llm_authored_candidate,
            is_plain_capacity_anchor=_is_plain_capacity_anchor,
            is_reviewable_architectural_mass=_is_reviewable_architectural_mass,
            research_mass_language=_research_mass_language,
            source_family=_source_family,
            source_signature=_source_signature,
        ),
    )
    if not preferred_operator:
        preference_guard_callbacks = PreferenceGuardCallbacks(
            architectural_order_gate=_architectural_order_gate,
            design_review_quality_key=_design_review_quality_key,
            final_mass_stage_parking_pass=final_mass_stage_parking_pass,
            formal_principle=_formal_principle,
            has_review_source_geometry=_has_review_source_geometry,
            is_direct_openai_llm_candidate=_is_direct_openai_llm_candidate,
            is_plain_capacity_anchor=_is_plain_capacity_anchor,
            is_reviewable_architectural_mass=_is_reviewable_architectural_mass,
            preference_vlm_scored=preference_vlm_scored,
            research_mass_language=_research_mass_language,
            source_family=_source_family,
        )
        selected = enforce_final_vlm_preference_minimum(
            selected,
            source_pool=legal_candidate_pool,
            final_limit=final_limit,
            min_count=min(14, int(preference_loop_config.get("min_final_vlm_scored") or 0)),
            callbacks=preference_guard_callbacks,
            preferred_operator=preferred_operator,
        )
        selected = enforce_final_direct_llm_minimum(
            selected,
            source_pool=legal_candidate_pool,
            final_limit=final_limit,
            callbacks=preference_guard_callbacks,
            min_count=16,
            preferred_operator=preferred_operator,
        )
        selected = recover_final_vlm_review_metrics(
            selected,
            source_pool=legal_candidate_pool,
            final_limit=final_limit,
            min_vlm_count=min(14, int(preference_loop_config.get("min_final_vlm_scored") or 0)),
            min_direct_count=16,
            callbacks=preference_guard_callbacks,
            preferred_operator=preferred_operator,
        )
        # Jointly recover canonical language/role repetition and island
        # coverage. Improvements may require two swaps, so do not require one
        # candidate to solve every deficit at once.
        visible = list(selected[:final_limit])
        tail = list(selected[final_limit:])
        for item in legal_candidate_pool:
            _attach_visual_diversity_evidence(item)
        island_targets = {"additive": 4, "subtractive": 4, "hybrid": 4, "sectional": 4}
        def final_projection_score(items: list[dict[str, Any]]) -> int:
            languages = Counter(_research_mass_language(item) for item in items if _research_mass_language(item))
            roles = Counter(_research_role_pattern(item) for item in items if _research_role_pattern(item))
            formal_principles = Counter(_formal_principle(item) for item in items if _formal_principle(item))
            islands = Counter(_research_quota_group(item) for item in items if _research_quota_group(item))
            heights = Counter(f"{float((item.get('properties') or {}).get('height') or 0.0):.2f}" for item in items)
            families = {_source_family(item) for item in items if _source_family(item)}
            shapes = [str((item.get("properties") or {}).get("mass_shape") or "").lower() for item in items]
            evolved_count = sum(1 for shape in shapes if "__evo_" in shape or "__critic_" in shape)
            crossover_count = sum(1 for shape in shapes if "__evo_cross_" in shape)
            weak_llm_count = sum(
                1 for item in items
                if (((item.get("properties") or {}).get("llm_candidate_quality") or {}).get("status") == "reject_final_review")
            )
            anchor_groups = {
                "rectangular": {"legal_layered", "slender_bar", "offset"},
                "stepped": {"terrace_link", "stack", "sloped_roof"},
                "podium_tower": {"tapered_tower", "slender_bar", "branch"},
                "courtyard": {"courtyard", "embed", "nest", "void_notch"},
                "sectional": {"diagonal_connect", "split", "sloped_roof", "terrace_link"},
            }
            anchor_deficit = sum(
                1 for allowed in anchor_groups.values()
                if not any(_source_family(item) in allowed for item in items)
            )
            clean_failures = 0
            for item in items:
                props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
                orderliness = props.get("orderliness_evidence") if isinstance(props.get("orderliness_evidence"), dict) else {}
                signature = _source_signature(item)
                coherence = signature.get("coherence_evidence") if isinstance(signature.get("coherence_evidence"), dict) else {}
                repair_delta = props.get("repair_delta") if isinstance(props.get("repair_delta"), dict) else {}
                volumes = props.get("mass_volumes") if isinstance(props.get("mass_volumes"), list) else []
                tiers = {
                    (
                        round(float(volume.get("bottom_height") or 0.0), 2),
                        round(float(volume.get("top_height") or 0.0), 2),
                    )
                    for volume in volumes
                    if isinstance(volume, dict)
                }
                clean_failures += max(0, int(orderliness.get("small_fragment_count") or 0) - 1)
                clean_failures += max(0, int(orderliness.get("plan_component_count") or 1) - 2)
                # Complexity is a liability, not a target.  Two coherent
                # masses/tiers are valid anchors; penalize only over-composed
                # results and disconnected fragments.
                clean_failures += max(0, len(volumes) - 4)
                clean_failures += max(0, len(tiers) - 4)
                clean_failures += 10 if coherence and not coherence.get("hard_pass") else 0
                clean_failures += 10 if repair_delta and float(repair_delta.get("area_retention") or 0.0) < 0.65 else 0
            return (
                clean_failures * 12000
                + max(0, 15 - len(families)) * 5000
                + sum(max(0, count - 2) for count in languages.values()) * 8000
                + sum(max(0, count - 2) for count in roles.values()) * 4000
                + sum(max(0, count - 4) for count in formal_principles.values()) * 3000
                + sum(max(0, target - islands.get(group, 0)) for group, target in island_targets.items()) * 7500
                + max(0, weak_llm_count - 1) * 9000
                + max(0, max(heights.values(), default=0) - 12) * 3600
                + anchor_deficit * 4500
                + max(0, evolved_count - 4) * 4200
                + max(0, crossover_count - 2) * 5000
            )

        for _ in range(final_limit * 3):
            current_score = final_projection_score(visible)
            if current_score <= 0:
                break
            current_heights = Counter(
                f"{float((item.get('properties') or {}).get('height') or 0.0):.2f}"
                for item in visible
            )
            current_languages = Counter(
                _research_mass_language(item)
                for item in visible
                if _research_mass_language(item)
            )
            selected_ids = {id(item) for item in visible}
            selected_shapes = {str((item.get("properties") or {}).get("mass_shape") or "") for item in visible}
            candidates = [
                item for item in legal_candidate_pool
                if id(item) not in selected_ids
                and str((item.get("properties") or {}).get("mass_shape") or "") not in selected_shapes
                and _architectural_order_gate(item)[0]
                and final_mass_stage_parking_pass(item)
            ]
            candidates.sort(key=_design_review_quality_key, reverse=True)
            best: tuple[int, int, dict[str, Any]] | None = None
            min_vlm = min(14, int(preference_loop_config.get("min_final_vlm_scored") or 0))
            for candidate in candidates[:160]:
                for index, old in enumerate(visible):
                    projected_vlm = sum(1 for item in visible if preference_vlm_scored(item)) - int(preference_vlm_scored(old)) + int(preference_vlm_scored(candidate))
                    projected_direct = sum(1 for item in visible if _is_direct_openai_llm_candidate(item)) - int(_is_direct_openai_llm_candidate(old)) + int(_is_direct_openai_llm_candidate(candidate))
                    if projected_vlm < min_vlm or projected_direct < 16:
                        continue
                    projected = list(visible)
                    projected[index] = candidate
                    projected_heights = Counter(
                        f"{float((item.get('properties') or {}).get('height') or 0.0):.2f}"
                        for item in projected
                    )
                    if max(projected_heights.values(), default=0) > max(12, max(current_heights.values(), default=0)):
                        continue
                    projected_languages = Counter(
                        _research_mass_language(item)
                        for item in projected
                        if _research_mass_language(item)
                    )
                    if max(projected_languages.values(), default=0) > max(2, max(current_languages.values(), default=0)):
                        continue
                    projected_score = final_projection_score(projected)
                    if projected_score >= current_score:
                        continue
                    rank = (projected_score, index, candidate)
                    if best is None or rank[0] < best[0]:
                        best = rank
            if best is None:
                # Some canonical-repeat repairs need a neutral bridge swap:
                # first create one surplus representative in the crowded
                # language's island, then replace the crowded member with a
                # candidate from the temporarily reduced island.
                visible_languages = Counter(_research_mass_language(item) for item in visible if _research_mass_language(item))
                visible_islands = Counter(_research_quota_group(item) for item in visible if _research_quota_group(item))
                crowded_languages = {key for key, count in visible_languages.items() if count > 2}
                crowded_islands = {
                    _research_quota_group(item)
                    for item in visible
                    if _research_mass_language(item) in crowded_languages
                }
                bridge_done = False
                for candidate in candidates[:160]:
                    candidate_group = _research_quota_group(candidate)
                    if candidate_group not in crowded_islands or _research_mass_language(candidate) in crowded_languages:
                        continue
                    for index, old in enumerate(visible):
                        old_group = _research_quota_group(old)
                        if old_group == candidate_group or visible_islands.get(old_group, 0) <= island_targets.get(old_group, 0):
                            continue
                        projected_vlm = sum(1 for item in visible if preference_vlm_scored(item)) - int(preference_vlm_scored(old)) + int(preference_vlm_scored(candidate))
                        projected_direct = sum(1 for item in visible if _is_direct_openai_llm_candidate(item)) - int(_is_direct_openai_llm_candidate(old)) + int(_is_direct_openai_llm_candidate(candidate))
                        if projected_vlm < min_vlm or projected_direct < 16:
                            continue
                        visible[index] = candidate
                        bridge_done = True
                        break
                    if bridge_done:
                        break
                if bridge_done:
                    continue
                break
            _, replace_index, candidate = best
            visible[replace_index] = candidate
        selected = visible + [item for item in tail if id(item) not in {id(feature) for feature in visible}]
        # Canonical evidence can collapse distinct raw labels after the joint
        # solver. Perform one exhaustive final repair against the exact values
        # consumed by the verifier, while preserving every hard gate.
        visible = list(selected[:final_limit])
        tail = list(selected[final_limit:])
        for _ in range(final_limit * 2):
            for item in [*visible, *legal_candidate_pool]:
                _attach_visual_diversity_evidence(item)
            language_counts = Counter(_research_mass_language(item) for item in visible if _research_mass_language(item))
            crowded = {language for language, count in language_counts.items() if count > 2}
            if not crowded:
                break
            selected_ids = {id(item) for item in visible}
            best_exact: tuple[int, int, dict[str, Any]] | None = None
            for candidate in legal_candidate_pool:
                if id(candidate) in selected_ids or _research_mass_language(candidate) in crowded:
                    continue
                if not _architectural_order_gate(candidate)[0] or not final_mass_stage_parking_pass(candidate):
                    continue
                for index, old in enumerate(visible):
                    if _research_mass_language(old) not in crowded:
                        continue
                    projected = list(visible)
                    projected[index] = candidate
                    projected_languages = Counter(_research_mass_language(item) for item in projected if _research_mass_language(item))
                    projected_roles = Counter(_research_role_pattern(item) for item in projected if _research_role_pattern(item))
                    projected_heights = Counter(f"{float((item.get('properties') or {}).get('height') or 0.0):.2f}" for item in projected)
                    projected_islands = Counter(_research_quota_group(item) for item in projected)
                    projected_families = {_source_family(item) for item in projected if _source_family(item)}
                    if max(projected_languages.values(), default=0) > 2:
                        continue
                    if max(projected_roles.values(), default=0) > 2 or max(projected_heights.values(), default=0) > 12:
                        continue
                    if len(projected_families) < 15 or any(projected_islands.get(group, 0) < 4 for group in island_targets):
                        continue
                    if sum(1 for item in projected if _is_direct_openai_llm_candidate(item)) < 16:
                        continue
                    if sum(1 for item in projected if preference_vlm_scored(item)) < min_vlm:
                        continue
                    rank = final_projection_score(projected)
                    if best_exact is None or rank < best_exact[0]:
                        best_exact = (rank, index, candidate)
            if best_exact is None:
                break
            _, index, candidate = best_exact
            visible[index] = candidate

        # A single-swap repair can be mathematically impossible when both a
        # crowded language and a minimum family/island quota are tight: the
        # first swap temporarily loses a quota and the second restores it.
        # Search a small beam of multi-swap states so the projection can cross
        # that neutral intermediate state instead of returning a verifier-only
        # near miss (for example 3/3 language repeats or a 13/7 height split).
        initial_projection_score = final_projection_score(visible)
        if initial_projection_score > 0:
            beam_pool = [
                item for item in legal_candidate_pool
                if _architectural_order_gate(item)[0]
                and final_mass_stage_parking_pass(item)
            ]
            beam_pool.sort(key=_design_review_quality_key, reverse=True)
            # The exact MILP below owns global feasibility.  Keep only a small
            # warm-start beam for ordering quality; do not spend minutes
            # approximating constraints that HiGHS solves exactly.
            beam_pool = beam_pool[:120]
            beam: list[list[dict[str, Any]]] = [list(visible)]
            best_state = list(visible)
            best_state_score = initial_projection_score
            for _depth in range(2):
                states: dict[tuple[str, ...], tuple[int, list[dict[str, Any]]]] = {}
                for state in beam:
                    state_ids = {id(item) for item in state}
                    state_shapes = {
                        str((item.get("properties") or {}).get("mass_shape") or "")
                        for item in state
                    }
                    for candidate in beam_pool:
                        candidate_shape = str((candidate.get("properties") or {}).get("mass_shape") or "")
                        if id(candidate) in state_ids or candidate_shape in state_shapes:
                            continue
                        for index in range(len(state)):
                            projected = list(state)
                            projected[index] = candidate
                            if sum(1 for item in projected if _is_direct_openai_llm_candidate(item)) < 16:
                                continue
                            if sum(1 for item in projected if preference_vlm_scored(item)) < min_vlm:
                                continue
                            score = final_projection_score(projected)
                            key = tuple(sorted(
                                str((item.get("properties") or {}).get("mass_shape") or "")
                                for item in projected
                            ))
                            previous = states.get(key)
                            if previous is None or score < previous[0]:
                                states[key] = (score, projected)
                            if score < best_state_score:
                                best_state_score = score
                                best_state = projected
                if best_state_score == 0 or not states:
                    break
                ranked_states = sorted(
                    states.values(),
                    key=lambda pair: (
                        pair[0],
                        -sum(preference_score(item) for item in pair[1]),
                    ),
                )
                beam = [state for _, state in ranked_states[:12]]
            if best_state_score < initial_projection_score:
                visible = best_state
        selected = visible + [item for item in tail if id(item) not in {id(feature) for feature in visible}]
    # Exact final projection.  Greedy/beam swaps are retained as a warm start,
    # but the review-set quotas are a binary selection problem and should be
    # solved globally rather than by ever-wider local search.
    integer_pool: list[dict[str, Any]] = []
    integer_seen_shapes: set[str] = set()
    for feature in [*selected, *legal_candidate_pool]:
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        shape_name = str(props.get("mass_shape") or "")
        if not shape_name or shape_name in integer_seen_shapes:
            continue
        if not _architectural_order_gate(feature)[0] or not final_mass_stage_parking_pass(feature):
            continue
        coherence = _source_signature(feature).get("coherence_evidence")
        if not isinstance(coherence, dict) or not coherence.get("hard_pass"):
            continue
        # In required-VLM mode the image score must influence selection, not be
        # attached after an unscored candidate has already won the MILP.
        if preference_loop_config.get("require_vlm") and not preference_vlm_scored(feature):
            continue
        # A candidate that mostly relies on compiler defaults is not authored
        # enough for the final review sheet, even when its geometry is clean.
        if float(_source_signature(feature).get("parameter_default_ratio") or 0.0) > 0.50:
            continue
        integer_seen_shapes.add(shape_name)
        integer_pool.append(feature)
    integer_pool.sort(key=_design_review_quality_key, reverse=True)
    integer_descriptors = [
        ProjectionDescriptor(
            feature=feature,
            cost=(rank / max(1, len(integer_pool)))
            + max(0.0, 0.72 - float((_source_signature(feature).get("coherence_evidence") or {}).get("score") or 0.0)) * 2.0,
            family=_source_family(feature),
            language=_projection_visual_language(feature),
            formal_principle=_formal_principle(feature),
            role_pattern=_research_role_pattern(feature),
            island=_research_quota_group(feature),
            height_band=f"{float((feature.get('properties') or {}).get('height') or 0.0):.2f}",
            direct_llm=_is_direct_openai_llm_candidate(feature),
            vlm_scored=preference_vlm_scored(feature),
            weak_llm=(((feature.get("properties") or {}).get("llm_candidate_quality") or {}).get("status") == "reject_final_review"),
            reference_ids=(visual_signature := visual_precedent_signature(feature))["references"],
            concept_vector=visual_signature["concepts"],
            visual_vector=tuple(visual_signature["visual_vector"]),
        )
        for rank, feature in enumerate(integer_pool)
    ]
    integer_selected: list[dict[str, Any]] = []
    integer_attempts: list[dict[str, Any]] = []
    final_integer_projection_artifact: dict[str, Any] = {}
    requested_vlm = min(14, int(preference_loop_config.get("min_final_vlm_scored") or 0))
    requested_direct_llm = 16 if llm_loop_config.get("enabled") else 0
    # Relax quotas as coherent policy profiles. A Cartesian product obscured
    # which contract was being attempted and needlessly solved hundreds of
    # dominated MILPs.
    projection_profiles = (
        (4, 15, min(requested_direct_llm, 16), requested_vlm, 0.82, 2, 3),
        (4, 13, min(requested_direct_llm, 14), min(requested_vlm, 12), 0.84, 2, 3),
        (5, 12, min(requested_direct_llm, 12), min(requested_vlm, 10), 0.86, 2, 3),
        (6, 10, min(requested_direct_llm, 10), min(requested_vlm, 10), 0.88, 2, 3),
        (8, 8, min(requested_direct_llm, 8), min(requested_vlm, 8), 0.90, 2, 3),
        (10, 8, min(requested_direct_llm, 8), min(requested_vlm, 8), 0.92, 3, 2),
        (10, 8, min(requested_direct_llm, 8), min(requested_vlm, 8), 0.96, 3, 2),
        # Keep visual separation hard while provenance/family/island counts
        # become soft objectives. This prevents quota conflicts from jumping
        # directly to the permissive service profile and admitting visibly
        # repeated silhouettes.
        (20, 1, 0, final_limit if preference_loop_config.get("require_vlm") else 0, 0.90, 2, 0),
        (20, 1, 0, final_limit if preference_loop_config.get("require_vlm") else 0, 0.92, 2, 0),
        (20, 1, 0, final_limit if preference_loop_config.get("require_vlm") else 0, 0.90, 3, 0),
        (20, 1, 0, final_limit if preference_loop_config.get("require_vlm") else 0, 0.92, 3, 0),
        # Guaranteed service-safe projection: only verified VLM candidates are
        # in this pool. Preserve legal/coherence and true duplicate exclusions,
        # while treating provenance/island/family counts as soft objectives.
        (20, 1, 0, final_limit if preference_loop_config.get("require_vlm") else 0, 0.96, 4, 0),
    )
    for formal_cap, family_minimum, direct_minimum, vlm_minimum, similarity_threshold, language_cap, island_minimum in projection_profiles:
        attempt_selected, attempt_trace = solve_final_integer_projection(
                        integer_descriptors,
                        final_count=final_limit,
                        min_family_count=family_minimum,
                        min_direct_llm=direct_minimum,
                        min_vlm_scored=vlm_minimum,
                        max_formal_repeat=formal_cap,
                        max_language_repeat=language_cap,
                        max_role_repeat=5,
                        max_height_repeat=12,
                        max_pairwise_similarity=similarity_threshold,
                        island_minimums={name: island_minimum for name in ("additive", "subtractive", "hybrid", "sectional")},
        )
        integer_attempts.append({
            "formal_cap": formal_cap,
            "family_minimum": family_minimum,
            "direct_llm_minimum": direct_minimum,
            "vlm_minimum": vlm_minimum,
            "pairwise_similarity_threshold": similarity_threshold,
            "language_repeat_cap": language_cap,
            "island_minimum": island_minimum,
            **attempt_trace,
        })
        if len(attempt_selected) == final_limit:
            integer_selected = attempt_selected
            final_integer_projection_artifact = {
                **attempt_trace,
                "requested_formal_cap": 4,
                "achieved_minimum_feasible_formal_cap": formal_cap,
                "requested_family_minimum": 15,
                "achieved_family_minimum": family_minimum,
                "requested_direct_llm_minimum": requested_direct_llm,
                "achieved_direct_llm_minimum": direct_minimum,
                "requested_vlm_minimum": requested_vlm,
                "achieved_vlm_minimum": vlm_minimum,
                "achieved_pairwise_similarity_threshold": similarity_threshold,
                "achieved_language_repeat_cap": language_cap,
                "achieved_island_minimum": island_minimum,
                "attempts": integer_attempts,
            }
            break
    if not integer_selected:
        final_integer_projection_artifact = {
            "status": "infeasible_after_relaxation",
            "requested_formal_cap": 4,
            "eligible_pool_family_count": len({item.family for item in integer_descriptors if item.family}),
            "eligible_pool_language_count": len({item.language for item in integer_descriptors if item.language}),
            "attempts": integer_attempts,
        }
    if len(integer_selected) == final_limit:
        integer_selected.sort(key=_design_review_quality_key, reverse=True)
        # The exact projection is the final review set. Appending the previous
        # heuristic tail leaked another ten candidates into a 20-card response
        # and invalidated the very quotas the MILP had just satisfied.
        selected = integer_selected

    # The pre-final VLM samples a diverse pool for tractable selection. Once
    # the exact set is known, complete image-backed scoring for every final
    # card so no proxy-only candidate can reach the user-facing sheet.
    if preference_loop_config.get("require_vlm") and len(selected) >= final_limit:
        final_vlm_completion_artifact = apply_preference_loop(
            selected[:final_limit],
            config={**preference_loop_config, "top_k": final_limit, "min_final_vlm_scored": final_limit},
            callbacks=PreferenceLoopCallbacks(
                design_review_quality_key=_design_review_quality_key,
                final_mass_stage_parking_pass=final_mass_stage_parking_pass,
                has_review_source_geometry=_has_review_source_geometry,
                is_plain_capacity_anchor=_is_plain_capacity_anchor,
                is_reviewable_architectural_mass=_is_vlm_review_candidate,
                source_family=_source_family,
            ),
        )
        completed_vlm_count = sum(1 for feature in selected[:final_limit] if preference_vlm_scored(feature))
        final_vlm_completion_artifact["final_vlm_scored_count"] = completed_vlm_count
        if completed_vlm_count != final_limit:
            raise ValueError(f"final MAAS VLM completion failed: {completed_vlm_count}/{final_limit}")

    for i, feature in enumerate(selected, start=1):
        feature["properties"]["variant_id"] = f"maas_{i:02d}"
    if isinstance(critic_geometry_loop_artifact, dict):
        accepted_shapes = {
            str(record.get("child_shape") or "")
            for generation in critic_geometry_loop_artifact.get("generations") or []
            for record in generation.get("records") or []
            if record.get("status") == "accepted_after_revalidation"
        }
        final_shapes = {
            str((feature.get("properties") or {}).get("mass_shape") or "")
            for feature in selected[:final_limit]
        }
        survivors = sorted(accepted_shapes & final_shapes)
        critic_geometry_loop_artifact["final_survivor_count"] = len(survivors)
        critic_geometry_loop_artifact["final_survivor_shapes"] = survivors

    agent_constraints = _constraints_agent_summary(envelope)
    selected_geometry_fingerprints = {
        id(feature): json.dumps(
            (feature.get("properties") or {}).get("mass_volumes") or [],
            sort_keys=True,
            separators=(",", ":"),
        )
        for feature in selected
    }
    for feature in selected:
        _attach_massdsl_agent_evidence(
            feature,
            operation_type="maas_legal_variants",
            constraints=agent_constraints,
            rejected=rejected,
        )
        attach_paper_alignment_and_preference_evidence(feature)
        current_geometry_fingerprint = json.dumps(
            (feature.get("properties") or {}).get("mass_volumes") or [],
            sort_keys=True,
            separators=(",", ":"),
        )
        if current_geometry_fingerprint != selected_geometry_fingerprints[id(feature)]:
            raise ValueError("post-selection evidence attachment mutated final MAAS geometry")

    top_feature = selected[0] if selected else {"type": "Feature", "properties": {}}
    agent_reviews = build_agent_reviews(
        operation_type="maas_legal_variants",
        feature=top_feature,
        constraints=agent_constraints,
        rejected=rejected,
        geometry_notes=[
            "legal envelope first",
            "MassDSL proposal compiled through ARR source geometry when sequence evidence exists",
        ],
    )
    a2ui_messages = build_agent_review_a2ui_messages(
        surface_id="maas-agent-review",
        operation_type="maas_legal_variants",
        feature=top_feature,
        agent_reviews=agent_reviews,
    )
    massdsl_proposals = [
        feature.get("properties", {}).get("massdsl_proposal")
        for feature in selected
        if isinstance(feature.get("properties", {}).get("massdsl_proposal"), dict)
    ]
    grammar_reviews = [
        feature.get("properties", {}).get("grammar_review")
        for feature in selected
        if isinstance(feature.get("properties", {}).get("grammar_review"), dict)
    ]
    agent_revision_trace = build_agent_revision_trace(
        selected=selected,
        legal_candidate_pool=legal_candidate_pool,
        agent_reviews=agent_reviews,
        order_gate=_architectural_order_gate,
        source_family=_source_family,
        formal_principle=_formal_principle,
        evolution_trace=evolution_trace_artifact,
        critic_geometry_loop=critic_geometry_loop_artifact,
    )
    for candidate_revision in agent_revision_trace.get("candidate_revisions", []):
        if not isinstance(candidate_revision, dict):
            continue
        variant_id = candidate_revision.get("variant_id")
        if not variant_id:
            continue
        for feature in selected:
            props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
            if props.get("variant_id") == variant_id:
                props["agent_revision_evidence"] = {
                    "schema_version": "arr.maas.agent_revision_evidence.v1",
                    "revision_trace_schema": agent_revision_trace["schema_version"],
                    "revision_type": agent_revision_trace["revision_type"],
                    "revision_decision": candidate_revision.get("revision_decision"),
                    "order_gate_pass": candidate_revision.get("order_gate_pass"),
                    "performance_proxy": candidate_revision.get("performance_proxy"),
                    "selection_trace_stages": candidate_revision.get("selection_trace_stages") or [],
                }
                model = props.get("maas_model")
                if isinstance(model, dict):
                    model["agent_revision_evidence"] = props["agent_revision_evidence"]
                break
    selection_debug = {
        "schema_version": "arr.maas.selection_debug.v1",
        "legal_candidate_pool_count": len(legal_candidate_pool),
        "pre_final_selected_count": len(parking_scan_features),
        "final_count": len(selected),
        "legal_pool_parking_mass_stage_pass": sum(
            1 for feature in legal_candidate_pool
            if (
                ((feature.get("properties") or {}).get("parking_precheck") or {})
                .get("layout_candidate", {})
                .get("mass_stage_parking", {})
                .get("status")
            ) == "pass"
            or (
                ((feature.get("properties") or {}).get("parking_precheck") or {})
                .get("layout_candidate", {})
                .get("status")
            ) == "pass"
        ),
        "legal_pool_source_reviewable": sum(
            1 for feature in legal_candidate_pool
            if _has_review_source_geometry(feature) and _is_reviewable_architectural_mass(feature)
        ),
        "legal_pool_architecture_order_pass": sum(
            1 for feature in legal_candidate_pool
            if _architectural_order_gate(feature)[0]
        ),
        "legal_pool_final_review_geometry_pass": sum(
            1 for feature in legal_candidate_pool
            if _architectural_order_gate(feature)[0]
            and not (
                ((feature.get("properties") or {}).get("research_basis") or {}).get("requires_llm_authoring") is True
                or ((((feature.get("properties") or {}).get("massdsl_proposal") or {}).get("design_parameters") or {}).get("requires_llm_authoring") is True)
            )
            and _visible_volume_count(feature) > 2
        ),
        "legal_pool_shape_prefixes": dict(Counter(
            str((feature.get("properties") or {}).get("mass_shape") or "").split("_", 1)[0]
            for feature in legal_candidate_pool
        )),
        "legal_pool_source_families": dict(Counter(
            _source_family(feature) or "unknown"
            for feature in legal_candidate_pool
        )),
        "final_source_families": dict(Counter(
            _source_family(feature) or "unknown"
            for feature in selected
        )),
        "priority_recovery_family_pool": {
            family: {
                "legal_pool": sum(1 for feature in legal_candidate_pool if (_source_family(feature) or "unknown") == family),
                "reviewable": sum(
                    1 for feature in legal_candidate_pool
                    if (_source_family(feature) or "unknown") == family
                    and _has_review_source_geometry(feature)
                    and _is_reviewable_architectural_mass(feature)
                ),
                "order_pass": sum(
                    1 for feature in legal_candidate_pool
                    if (_source_family(feature) or "unknown") == family
                    and _architectural_order_gate(feature)[0]
                ),
                "mass_stage_parking_pass": sum(
                    1 for feature in legal_candidate_pool
                    if (_source_family(feature) or "unknown") == family
                    and (
                        ((((feature.get("properties") or {}).get("parking_precheck") or {}).get("layout_candidate") or {}).get("mass_stage_parking") or {}).get("status") == "pass"
                    )
                ),
                "candidate_names": [
                    str((feature.get("properties") or {}).get("mass_shape") or "")
                    for feature in legal_candidate_pool
                    if (_source_family(feature) or "unknown") == family
                    and _has_review_source_geometry(feature)
                    and _is_reviewable_architectural_mass(feature)
                ][:5],
            }
            for family in ("courtyard", "diagonal_connect", "array_cluster", "offset", "reflected_pair")
        },
        "legal_pool_formal_principles": dict(Counter(
            _formal_principle(feature) or "unknown"
            for feature in legal_candidate_pool
        )),
        "final_formal_principles": dict(Counter(
            _formal_principle(feature) or "unknown"
            for feature in selected
        )),
        "legal_pool_vertical_strategies": dict(Counter(
            _vertical_strategy(feature) or "unknown"
            for feature in legal_candidate_pool
        )),
        "legal_pool_architecture_order_formal_principles": dict(Counter(
            _formal_principle(feature) or "unknown"
            for feature in legal_candidate_pool
            if _architectural_order_gate(feature)[0]
        )),
        "legal_pool_architecture_order_vertical_strategies": dict(Counter(
            _vertical_strategy(feature) or "unknown"
            for feature in legal_candidate_pool
            if _architectural_order_gate(feature)[0]
        )),
        "final_vertical_strategies": dict(Counter(
            _vertical_strategy(feature) or "unknown"
            for feature in selected
        )),
        "final_stair_like_risk": dict(Counter(
            _stair_like_risk(feature) or "unknown"
            for feature in selected
        )),
        "final_selection_trace_evidence": sum(
            1 for feature in selected
            if isinstance((feature.get("properties") or {}).get("selection_trace"), list)
        ),
        "preference_loop": preference_loop_artifact or {
            "schema_version": "arr.maas.preference_loop.v1",
            "enabled": False,
            "status": "not_requested",
        },
        "final_vlm_completion": final_vlm_completion_artifact,
        "mass_brain_shadow": mass_brain_shadow_artifact,
        "final_vlm_scored_count": sum(
            1 for feature in selected
            if preference_vlm_scored(feature)
        ),
        "final_preference_modes": dict(Counter(
            str((((feature.get("properties") or {}).get("preference_distillation") or {}).get("mode") or "none"))
            for feature in selected
        )),
        "final_kmedoid_representatives": sum(
            1 for feature in selected
            for event in ((feature.get("properties") or {}).get("selection_trace") or [])
            if isinstance(event, dict)
            and event.get("stage") == "kmedoid_representative_selection"
        ),
        "architecture_gate_failures_by_formal_principle": dict(Counter(
            f"{_formal_principle(feature) or 'unknown'}:{issue}"
            for feature in legal_candidate_pool
            for issue in _architectural_order_gate(feature)[1]
        )),
        "architecture_gate_failures": dict(Counter(
            issue
            for feature in legal_candidate_pool
            for issue in _architectural_order_gate(feature)[1]
        )),
        "final_integer_projection": final_integer_projection_artifact,
    }

    parking_pass_count = int(selection_debug["legal_pool_parking_mass_stage_pass"])
    order_pass_count = int(selection_debug["legal_pool_architecture_order_pass"])
    if selected:
        generation_status = "complete"
        infeasible_reason = None
    elif legal_candidate_pool and parking_pass_count == 0:
        generation_status = "infeasible"
        infeasible_reason = "no_candidate_passed_mass_stage_parking_hard_constraint"
    elif legal_candidate_pool and order_pass_count == 0:
        generation_status = "infeasible"
        infeasible_reason = "no_candidate_passed_architectural_order_hard_constraint"
    else:
        generation_status = "infeasible"
        infeasible_reason = "exact_projection_has_insufficient_clean_candidates"

    return {
        "mode": "maas_legal_variants",
        "algorithm": "maas_legal_envelope",
        "generation_status": generation_status,
        "infeasible_reason": infeasible_reason,
        "count": len(selected),
        "seed_library": seed_library_metadata(),
        "source_repair_actions": source_actions,
        "constraints": {
            "bcr_limit": envelope.bcr_limit,
            "far_limit": envelope.far_limit,
            "height_limit": envelope.height_limit,
            "max_seed_floors": envelope.max_seed_floors,
            "has_buildable_footprint": envelope.buildable_footprint is not None,
            "has_floor_plate_stack": layered_stack is not None,
        },
        "feature_collection": {
            "type": "FeatureCollection",
            "features": selected,
        },
        "rejected": rejected,
        "agent_reviews": agent_reviews,
        "agent_trace": agent_reviews,
        "agent_revision_trace": agent_revision_trace,
        "evolution_trace": evolution_trace_artifact,
        "critic_geometry_loop": critic_geometry_loop_artifact,
        "final_integer_projection": final_integer_projection_artifact,
        "a2ui_messages": a2ui_messages,
        "massdsl_proposals": massdsl_proposals,
        "grammar_review": grammar_reviews[0] if grammar_reviews else None,
        "grammar_reviews": grammar_reviews,
        "selection_debug": selection_debug,
        "llm_proposal_loop": llm_loop_artifact,
        "preference_loop": preference_loop_artifact,
        "final_vlm_completion": final_vlm_completion_artifact,
        "mass_brain_shadow": mass_brain_shadow_artifact,
        "notes": [
            "Legal envelope is the primary generator boundary.",
            "Layered MAAS candidates clip every floor plate by the legal envelope before FAR/BCR scoring.",
            "Selected ARR/legacy mass is treated as a seed for diversity, not as the capacity source.",
            "Each variant is repaired and checked against BCR/FAR/height/sunlight before return.",
            "Variants are ranked by legal FAR/BCR utilization plus geometric diversity.",
            "MassDSL agent evidence is attached after final legal selection so UI/PNG review can explain each candidate.",
        ],
    }


def _attach_parking_requirements(
    features: list[dict[str, Any]],
    *,
    pnu: str | None,
    building_type: str,
    site_utm,
    site_area_m2: float,
    parking_options: dict[str, Any] | None,
) -> None:
    options = parking_options or {}
    road_context = options.get("road_context") if isinstance(options.get("road_context"), dict) else None
    loaded_rules = load_parking_requirement_rules(options=options) if pnu else None
    rules = loaded_rules.get("rules") if isinstance(loaded_rules, dict) and loaded_rules.get("status") == "loaded" else None
    graph_unavailable = loaded_rules if isinstance(loaded_rules, dict) and loaded_rules.get("status") != "loaded" else None
    for feature in features:
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        if graph_unavailable:
            requirement = {
                "status": graph_unavailable.get("status"),
                "required_spaces": None,
                "accessible": {
                    "status": graph_unavailable.get("status"),
                    "accessible_min": None,
                    "accessible_max": None,
                },
                "reason": graph_unavailable.get("reason"),
            }
        else:
            feature_options = _parking_options_for_feature(options, props, building_type)
            requirement = resolve_candidate_parking_requirement(
                pnu=pnu,
                building_type=building_type,
                facility_area_m2=_float_or_none(props.get("floor_area")),
                options=feature_options,
                rules=rules,
            )
        apply_parking_requirement_to_props(props, requirement)
        try:
            footprint_utm = largest_polygon(wgs84_to_utm(geojson_to_polygon(feature.get("geometry"))))
        except Exception:
            footprint_utm = None
        attach_parking_strategy(
            props,
            site_area_m2=site_area_m2,
            building_type=building_type,
            footprint_utm=footprint_utm,
            site_utm=site_utm,
            road_context=road_context,
        )


def _parking_repair_candidates(
    features: list[dict[str, Any]],
    *,
    envelope,
    site_utm,
    site_area_m2: float,
    building_type: str,
    parking_options: dict[str, Any] | None,
    max_results: int,
) -> list[dict[str, Any]]:
    options = parking_options or {}
    road_context = options.get("road_context") if isinstance(options.get("road_context"), dict) else None
    repaired: list[dict[str, Any]] = []
    seen_signatures: set[tuple[float, float, float]] = set()
    repair_sources = sorted(
        [feature for feature in features if _needs_parking_repair(feature)],
        key=lambda feature: (
            _parking_priority_key(feature),
            _design_review_quality_key(feature),
        ),
        reverse=True,
    )[:1]
    for feature in repair_sources:
        if len(repaired) >= max_results:
            break
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        precheck = props.get("parking_precheck") if isinstance(props.get("parking_precheck"), dict) else {}
        layout = precheck.get("layout_candidate") if isinstance(precheck.get("layout_candidate"), dict) else {}
        required_count = precheck.get("required_count") if isinstance(precheck.get("required_count"), dict) else {}
        required = _int_or_none(required_count.get("required_spaces"))
        if required is None or required <= 0:
            required = _int_or_none(layout.get("required_spaces"))
        if required is None or required <= 0:
            required = _int_or_none(props.get("required_parking_spaces"))
        if required is None or required <= 0:
            continue
        if layout.get("status") == "pass" and int(layout.get("provided_spaces") or 0) >= required:
            continue
        try:
            footprint_utm = largest_polygon(wgs84_to_utm(geojson_to_polygon(feature.get("geometry"))))
        except Exception:
            continue
        repair = _find_parking_repair_footprint(
            footprint_utm,
            site_utm=site_utm,
            required_spaces=required,
            road_context=road_context,
            floors=int(float(props.get("num_floors") or 1)),
            building_type=building_type,
        )
        if repair is None:
            continue
        repaired_fp, repair_layout, repair_meta = repair
        repaired_fp = _strict_setback_footprint(repaired_fp, site_utm=site_utm, envelope=envelope)
        if repaired_fp.is_empty or repaired_fp.area < 8.0:
            continue
        signature = (
            round(float(repaired_fp.area), 1),
            round(float(repaired_fp.centroid.x), 1),
            round(float(repaired_fp.centroid.y), 1),
        )
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        floors = int(float(props.get("num_floors") or 1))
        source_score = float(props.get("maas_score") or 0.0)
        source_iou = round(1.0 - diversity_score(repaired_fp, [], footprint_utm), 4)
        diversity = float(props.get("diversity_score") or 0.0)
        candidate = _mass_feature(
            operator="parking_repair_shrink",
            footprint_utm=repaired_fp,
            upper_footprint_utm=None,
            num_floors=max(1, floors),
            lower_floor_fraction=None,
            site_utm=site_utm,
            site_area_m2=site_area_m2,
            building_type=building_type,
            notes=(
                "parking_repair: reshape/translate footprint to fit required small-lot parking",
                f"parking_repair_method={repair_meta.get('method')}",
                f"parking_repair_scale=({repair_meta.get('scale_x')},{repair_meta.get('scale_y')})",
                f"parking_repair_offset_m=({repair_meta.get('dx')},{repair_meta.get('dy')})",
                f"parking_repair_layout_status={repair_layout.get('status')}",
            ),
            diversity=diversity,
            source_iou=source_iou,
        )
        cprops = candidate["properties"]
        if failed_constraint_metrics(cprops, envelope):
            continue
        cprops["maas_score"] = round(max(0.0, source_score - 0.18), 4)
        _attach_design_quality(candidate, repaired_fp)
        cprops["parking_repair"] = {
            "source_variant_id": props.get("variant_id"),
            "source_mass_shape": props.get("mass_shape"),
            "method": repair_meta.get("method"),
            "scale_factor": repair_meta.get("scale_factor"),
            "scale": {"x": repair_meta.get("scale_x"), "y": repair_meta.get("scale_y")},
            "offset_m": {"x": repair_meta.get("dx"), "y": repair_meta.get("dy")},
            "area_retention": repair_meta.get("area_retention"),
            "target_required_spaces": repair_meta.get("candidate_required_spaces", required),
            "preview_layout_status": repair_layout.get("status"),
            "preview_layout_mode": repair_layout.get("placement_mode"),
            "preview_adjacency": repair_layout.get("adjacency"),
            "authority_review": repair_layout.get("status") != "pass",
        }
        repaired.append(candidate)
        remaining = max(0, max_results - len(repaired))
        for section_candidate in _parking_preserving_section_candidates(
            repaired_fp,
            source_feature=feature,
            repair_layout=repair_layout,
            repair_meta=repair_meta,
            envelope=envelope,
            site_utm=site_utm,
            site_area_m2=site_area_m2,
            building_type=building_type,
            floors=floors,
            source_score=source_score,
            diversity=diversity,
            source_iou=source_iou,
            max_results=remaining,
        ):
            repaired.append(section_candidate)
        if len(repaired) >= max_results:
            break
        if floors >= 2 and footprint_utm.area > repaired_fp.area * 1.2:
            lifted_candidate = _mass_feature(
                operator="parking_repair_ground_void",
                footprint_utm=repaired_fp,
                upper_footprint_utm=footprint_utm,
                num_floors=max(2, floors),
                lower_floor_fraction=1.0 / max(2, floors),
                site_utm=site_utm,
                site_area_m2=site_area_m2,
                building_type=building_type,
                notes=(
                    "parking_repair: keep upper mass while reducing ground footprint for parking",
                    f"parking_repair_method={repair_meta.get('method')}",
                    f"parking_repair_scale=({repair_meta.get('scale_x')},{repair_meta.get('scale_y')})",
                    f"parking_repair_offset_m=({repair_meta.get('dx')},{repair_meta.get('dy')})",
                    f"parking_repair_layout_status={repair_layout.get('status')}",
                ),
                diversity=diversity,
                source_iou=source_iou,
            )
            lifted_props = lifted_candidate["properties"]
            if failed_constraint_metrics(lifted_props, envelope):
                continue
            lifted_props["maas_score"] = round(max(0.0, source_score - 0.08), 4)
            _attach_design_quality(lifted_candidate, repaired_fp)
            lifted_props["parking_repair"] = {
                **cprops["parking_repair"],
                "method": "ground_void_upper_mass",
                "base_method": repair_meta.get("method"),
                "upper_mass_retained": True,
                "upper_source_mass_shape": props.get("mass_shape"),
                "upper_floor_start": lifted_props.get("step_floor"),
            }
            repaired.append(lifted_candidate)
        if len(repaired) >= max_results:
            break
        break
    return repaired[:max_results]


def _needs_parking_repair(feature: dict[str, Any]) -> bool:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    if _is_parking_repair_operator(str(props.get("mass_shape") or "")):
        return False
    precheck = props.get("parking_precheck") if isinstance(props.get("parking_precheck"), dict) else {}
    layout = precheck.get("layout_candidate") if isinstance(precheck.get("layout_candidate"), dict) else {}
    required_count = precheck.get("required_count") if isinstance(precheck.get("required_count"), dict) else {}
    required = _int_or_none(required_count.get("required_spaces"))
    if required is None or required <= 0:
        required = _int_or_none(layout.get("required_spaces"))
    if required is None or required <= 0:
        required = _int_or_none(props.get("required_parking_spaces"))
    if required is None or required <= 0:
        return False
    return not (layout.get("status") == "pass" and int(layout.get("provided_spaces") or 0) >= required)


def _strict_setback_footprint(footprint_utm, *, site_utm, envelope):
    min_setback = _strict_setback_limit_m(envelope)
    if min_setback <= 0:
        return footprint_utm
    if float(footprint_utm.distance(site_utm.boundary)) >= min_setback + 0.01:
        return footprint_utm
    strict_area = site_utm.buffer(-(min_setback + 0.02))
    if strict_area.is_empty:
        return footprint_utm
    adjusted = largest_polygon(footprint_utm.intersection(strict_area))
    return adjusted if not adjusted.is_empty else footprint_utm


def _strict_setback_limit_m(envelope) -> float:
    value = 0.0
    constraints = getattr(envelope, "constraint_values", {}) or {}
    for name in ("setback", "building_line_setback"):
        requirement, limit = constraints.get(name, ("", 0.0))
        if requirement == "Greater than":
            try:
                value = max(value, float(limit))
            except (TypeError, ValueError):
                pass
    return value


def _parking_preserving_section_candidates(
    parking_footprint_utm,
    *,
    source_feature: dict[str, Any],
    repair_layout: dict[str, Any],
    repair_meta: dict[str, Any],
    envelope,
    site_utm,
    site_area_m2: float,
    building_type: str,
    floors: int,
    source_score: float,
    diversity: float,
    source_iou: float,
    max_results: int,
) -> list[dict[str, Any]]:
    """Create section-diverse masses while keeping the proven parking footprint."""
    source_props = source_feature.get("properties") if isinstance(source_feature.get("properties"), dict) else {}
    upper_limit = getattr(envelope, "buildable_footprint", None)
    if upper_limit is None or upper_limit.is_empty:
        upper_limit = site_utm
    grammar_variants = [
        variant for variant in generate_grammar_variants(parking_footprint_utm, building_type=building_type)
        if variant.upper_footprint is not None
        or any(
            token in variant.operator
            for token in ("diagonal", "terrace", "sloped", "split", "bar", "podium", "overlap")
        )
    ]
    created: list[dict[str, Any]] = []
    seen: set[tuple[float, float, float]] = set()
    for variant in grammar_variants:
        if len(created) >= max_results:
            break
        operator = f"parking_repair_{variant.operator}"
        upper_source = variant.upper_footprint if variant.upper_footprint is not None else variant.footprint
        upper = _largest_polygon_or_none(upper_source.intersection(upper_limit).intersection(site_utm))
        if upper is None:
            continue
        if upper.is_empty or upper.area < 8.0:
            continue
        if not site_utm.buffer(1e-7).covers(upper):
            continue
        signature = (
            round(float(upper.area), 1),
            round(float(upper.centroid.x), 1),
            round(float(upper.centroid.y), 1),
        )
        if signature in seen:
            continue
        seen.add(signature)
        candidate = _mass_feature(
            operator=operator,
            footprint_utm=parking_footprint_utm,
            upper_footprint_utm=upper,
            num_floors=max(3, floors),
            lower_floor_fraction=variant.lower_floor_fraction,
            site_utm=site_utm,
            site_area_m2=site_area_m2,
            building_type=building_type,
            notes=(
                "parking_repair: preserve verified ground parking footprint while varying upper mass",
                f"parking_repair_method={repair_meta.get('method')}",
                f"parking_repair_layout_status={repair_layout.get('status')}",
                f"parking_preserve_operator={operator}",
                "parking_preserve_source=maas_grammar_sequence_library",
                *tuple(str(note) for note in variant.notes),
            ),
            diversity=diversity,
            source_iou=source_iou,
        )
        props = candidate["properties"]
        if failed_constraint_metrics(props, envelope):
            continue
        sequence_len = len(getattr(variant, "verb_sequence", ()) or ())
        score_penalty = min(0.14, 0.04 + max(0, sequence_len - 2) * 0.015)
        props["maas_score"] = round(max(0.0, source_score - score_penalty), 4)
        _apply_variant_verb_sequence(candidate, variant)
        _attach_design_quality(candidate, parking_footprint_utm)
        props["parking_repair"] = {
            "source_variant_id": source_props.get("variant_id"),
            "source_mass_shape": source_props.get("mass_shape"),
            "method": operator,
            "base_method": repair_meta.get("method"),
            "scale_factor": repair_meta.get("scale_factor"),
            "scale": {"x": repair_meta.get("scale_x"), "y": repair_meta.get("scale_y")},
            "offset_m": {"x": repair_meta.get("dx"), "y": repair_meta.get("dy")},
            "area_retention": repair_meta.get("area_retention"),
            "target_required_spaces": repair_meta.get("candidate_required_spaces"),
            "preview_layout_status": repair_layout.get("status"),
            "preview_layout_mode": repair_layout.get("placement_mode"),
            "preview_adjacency": repair_layout.get("adjacency"),
            "parking_footprint_preserved": True,
            "authority_review": repair_layout.get("status") != "pass",
        }
        created.append(candidate)
    return created


def _sync_parking_repair_metadata(features: list[dict[str, Any]]) -> None:
    for feature in features:
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        repair = props.get("parking_repair") if isinstance(props.get("parking_repair"), dict) else None
        precheck = props.get("parking_precheck") if isinstance(props.get("parking_precheck"), dict) else {}
        requirement = precheck.get("required_count") if isinstance(precheck.get("required_count"), dict) else {}
        layout = precheck.get("layout_candidate") if isinstance(precheck.get("layout_candidate"), dict) else {}
        if repair is None:
            continue
        final_required = _int_or_none(requirement.get("required_spaces"))
        final_provided = _int_or_none(layout.get("provided_spaces"))
        repair["final_required_spaces"] = final_required
        repair["final_provided_spaces"] = final_provided
        repair["final_layout_status"] = layout.get("status")
        repair["final_layout_mode"] = layout.get("placement_mode")
        repair["final_adjacency"] = layout.get("adjacency")
        repair["authority_review"] = bool(
            layout.get("turning_clearance", {}).get("authority_review")
            if isinstance(layout.get("turning_clearance"), dict)
            else layout.get("status") != "pass"
        )


def _find_parking_repair_footprint(
    footprint_utm,
    *,
    site_utm,
    required_spaces: int,
    road_context: dict[str, Any] | None,
    floors: int,
    building_type: str,
) -> tuple[Any, dict[str, Any], dict[str, Any]] | None:
    from backend.app.modules.design.generation.maas.parking_layout import generate_parking_layout_candidate
    from backend.app.modules.design.generation.maas.parking_strategy import _parking_drive_envelope, _parking_envelope

    best: tuple[tuple[Any, ...], Any, dict[str, Any], dict[str, Any]] | None = None
    source_area = float(footprint_utm.area or 0.0)
    repair_options = _iter_parking_repair_footprints(footprint_utm)
    repair_options.sort(key=lambda item: (
        float(item[1].get("movement_m") or 0.0),
        0 if item[1].get("method") in {"uniform_shrink", "axis_compress"} else 1,
        -float(item[0].area or 0.0),
    ))
    max_checks = 12 if required_spaces <= 4 else 16
    checked = 0
    for candidate_fp, meta in repair_options:
        # A difficult or impossible small lot previously ignored the budget
        # whenever no feasible repair had been found, then exhaustively tested
        # hundreds of layouts. The live stage is bounded even on failure.
        if checked >= max_checks:
            break
        checked += 1
        if candidate_fp.is_empty or candidate_fp.area < 8.0:
            continue
        if not site_utm.buffer(1e-7).covers(candidate_fp):
            continue
        envelope = _parking_envelope(
            "ground_surface",
            footprint_utm=candidate_fp,
            site_utm=site_utm,
        )
        drive_envelope = _parking_drive_envelope(
            "ground_surface",
            footprint_utm=candidate_fp,
            site_utm=site_utm,
        )
        candidate_required = _estimate_candidate_repair_required_spaces(
            candidate_fp,
            floors=floors,
            building_type=building_type,
            fallback_required_spaces=required_spaces,
        )
        layout = generate_parking_layout_candidate(
            envelope,
            drive_envelope=drive_envelope,
            required_spaces=candidate_required,
            strategy="ground_surface",
            road_context=road_context,
        )
        provided = int(layout.get("provided_spaces") or 0)
        if provided < candidate_required:
            continue
        adjacency = layout.get("adjacency") if isinstance(layout.get("adjacency"), dict) else {}
        status = str(layout.get("status") or "")
        area_retention = float(candidate_fp.area / source_area) if source_area > 0 else 0.0
        meta = {
            **meta,
            "area_retention": round(area_retention, 4),
            "candidate_required_spaces": candidate_required,
        }
        score = (
            3 if status == "pass" else 2 if status in {"needs_drive_connectivity_review", "needs_swept_path_review"} else 0,
            1 if adjacency.get("row_contiguous_ok") else 0,
            1 if adjacency.get("contiguous_ok") else 0,
            round(area_retention, 4),
            1 if meta.get("method") in {"edge_notch", "axis_compress"} else 0,
            -float(meta.get("movement_m") or 0.0),
        )
        if best is None or score > best[0]:
            best = (score, candidate_fp, layout, meta)
        if status == "pass" and area_retention >= 0.72 and adjacency.get("row_contiguous_ok"):
            break
    if best is None:
        return None
    _score, candidate_fp, layout, meta = best
    return candidate_fp, layout, meta


def _estimate_candidate_repair_required_spaces(
    footprint_utm,
    *,
    floors: int,
    building_type: str,
    fallback_required_spaces: int,
) -> int:
    if not _is_common_housing(building_type):
        return fallback_required_spaces
    floor_count = max(1, floors)
    footprint_area = float(getattr(footprint_utm, "area", 0.0) or 0.0)
    if footprint_area <= 0:
        return fallback_required_spaces
    exclusive_area_per_unit = footprint_area * 0.75
    total_exclusive_area = exclusive_area_per_unit * floor_count
    area_ratio_spaces = total_exclusive_area / 75.0
    if exclusive_area_per_unit <= 30.0:
        min_per_unit = 0.5
    elif exclusive_area_per_unit <= 60.0:
        min_per_unit = 0.8
    else:
        min_per_unit = 1.0
    household_min_spaces = floor_count * min_per_unit
    return max(1, int(__import__("math").ceil(max(area_ratio_spaces, household_min_spaces))))


def _iter_parking_repair_footprints(footprint_utm) -> list[tuple[Any, dict[str, Any]]]:
    candidates: list[tuple[Any, dict[str, Any]]] = []
    offsets = (0.0, -4.0, 4.0, -8.0, 8.0)

    def add_scaled(method: str, sx: float, sy: float) -> None:
        scaled = shapely_scale(footprint_utm, xfact=sx, yfact=sy, origin="centroid")
        for dx in offsets:
            for dy in offsets:
                moved = shapely_translate(scaled, xoff=dx, yoff=dy)
                candidates.append((moved, {
                    "method": method,
                    "scale_factor": round(min(sx, sy), 4),
                    "scale_x": sx,
                    "scale_y": sy,
                    "dx": dx,
                    "dy": dy,
                    "movement_m": abs(dx) + abs(dy),
                }))

    for factor in (0.74, 0.66, 0.58, 0.50):
        add_scaled("uniform_shrink", factor, factor)
    for factor in (0.82, 0.74, 0.66, 0.58):
        add_scaled("axis_compress", factor, 1.0)
        add_scaled("axis_compress", 1.0, factor)

    minx, miny, maxx, maxy = footprint_utm.bounds
    span_x = maxx - minx
    span_y = maxy - miny
    strip_specs = [
        ("west", minx, miny, minx + width, maxy)
        for width in (2.0, 3.5, 5.0, 6.5, 8.0)
        if width < span_x
    ] + [
        ("east", maxx - width, miny, maxx, maxy)
        for width in (2.0, 3.5, 5.0, 6.5, 8.0)
        if width < span_x
    ] + [
        ("south", minx, miny, maxx, miny + depth)
        for depth in (2.0, 3.5, 5.0, 6.5, 8.0)
        if depth < span_y
    ] + [
        ("north", minx, maxy - depth, maxx, maxy)
        for depth in (2.0, 3.5, 5.0, 6.5, 8.0)
        if depth < span_y
    ]
    for edge, a, b, c, d in strip_specs:
        cut = box(a, b, c, d)
        diff = footprint_utm.difference(cut)
        repaired = largest_polygon(diff)
        if repaired.is_empty:
            continue
        for dx in (0.0, -4.0, 4.0):
            for dy in (0.0, -4.0, 4.0):
                moved = shapely_translate(repaired, xoff=dx, yoff=dy)
                candidates.append((moved, {
                    "method": "edge_notch",
                    "edge": edge,
                    "scale_factor": None,
                    "scale_x": 1.0,
                    "scale_y": 1.0,
                    "dx": dx,
                    "dy": dy,
                    "movement_m": abs(dx) + abs(dy),
                }))
    return candidates


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _parking_options_for_feature(options: dict[str, Any], props: dict[str, Any], building_type: str) -> dict[str, Any]:
    result = dict(options)
    if result.get("housing_unit_schedule") or not _is_common_housing(building_type):
        return result
    schedule = _estimate_housing_unit_schedule(props)
    if schedule:
        result["housing_unit_schedule"] = schedule
        result.setdefault("jurisdiction_type", "special_city")
    return result


def _is_common_housing(building_type: str) -> bool:
    text = building_type or ""
    return any(token in text for token in ("공동주택", "아파트", "연립", "다세대"))


def _estimate_housing_unit_schedule(props: dict[str, Any]) -> list[dict[str, Any]]:
    plates = props.get("floor_plates")
    if not isinstance(plates, list) or not plates:
        model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
        plates = model.get("floor_plates") if isinstance(model.get("floor_plates"), list) else []
    if not isinstance(plates, list) or not plates:
        footprint_area = _float_or_none(props.get("footprint_area"))
        floor_area = _float_or_none(props.get("floor_area"))
        floors = int(_float_or_none(props.get("num_floors")) or 0)
        if floors > 0 and floor_area and floor_area > 0:
            average_floor_area = floor_area / floors
            plates = [{"floor": floor, "area_m2": average_floor_area} for floor in range(1, floors + 1)]
        elif footprint_area and footprint_area > 0 and floors > 0:
            plates = [{"floor": floor, "area_m2": footprint_area} for floor in range(1, floors + 1)]
    schedule: list[dict[str, Any]] = []
    exclusive_ratio = 0.75
    for plate in plates:
        if not isinstance(plate, dict):
            continue
        area = _float_or_none(plate.get("area") or plate.get("area_m2"))
        floor = int(_float_or_none(plate.get("floor")) or len(schedule) + 1)
        if area is None or area <= 0:
            continue
        schedule.append({
            "unit_type": f"F{floor:02d}",
            "count": 1,
            "exclusive_area_m2": round(area * exclusive_ratio, 2),
            "gross_floor_plate_area_m2": round(area, 2),
            "exclusive_area_ratio": exclusive_ratio,
            "source": "mass_stage_estimate",
        })
    return schedule


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parking_priority_key(feature: dict[str, Any]) -> tuple[int, int, int, float, float, float]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    precheck = props.get("parking_precheck") if isinstance(props.get("parking_precheck"), dict) else {}
    layout = precheck.get("layout_candidate") if isinstance(precheck.get("layout_candidate"), dict) else {}
    required = layout.get("required_spaces")
    provided = layout.get("provided_spaces")
    unmet = layout.get("unmet_spaces")
    status = layout.get("status")
    mass_stage = layout.get("mass_stage_parking") if isinstance(layout.get("mass_stage_parking"), dict) else {}
    if isinstance(required, int) and required > 0 and isinstance(provided, int):
        satisfied = int(provided >= required and (not isinstance(unmet, int) or unmet == 0))
    else:
        satisfied = 0
    status_rank = (
        3 if status == "pass" and isinstance(required, int) and required > 0
        else 2 if mass_stage.get("status") == "pass"
        else 1 if status in {
            "needs_drive_connectivity_review",
            "needs_aisle_review",
            "needs_swept_path_review",
            "needs_mechanical_parking_review",
        }
        else 0
    )
    repair = props.get("parking_repair") if isinstance(props.get("parking_repair"), dict) else None
    repair_rank = 0 if repair else 1
    floor_area = float(props.get("floor_area") or 0.0)
    footprint_area = float(props.get("footprint_area") or 0.0)
    return (
        satisfied,
        status_rank,
        repair_rank,
        float(props.get("maas_score") or 0.0),
        floor_area,
        footprint_area,
    )


def _review_diversity_priority_key(feature: dict[str, Any]) -> tuple[int, float, float, float]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    diversity = props.get("candidate_diversity") if isinstance(props.get("candidate_diversity"), dict) else {}
    class_rank = {
        "plan_diverse": 3,
        "near_duplicate": 2,
        "section_diverse": 1,
    }.get(diversity.get("class"), 0)
    return (
        class_rank,
        float(props.get("diversity_score") or 0.0),
        float(props.get("maas_score") or 0.0),
        float(props.get("floor_area") or 0.0),
    )


__all__ = ["generate_legal_mass_variants"]
