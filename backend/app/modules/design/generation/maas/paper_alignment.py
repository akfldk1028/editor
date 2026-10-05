"""Paper-alignment evidence for MAAS candidates."""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.performance_objectives import early_massing_performance_proxy
from backend.app.modules.design.generation.maas.preference import build_preference_distillation


def paper_alignment_evidence(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    source_signature = props.get("source_signature") if isinstance(props.get("source_signature"), dict) else {}
    if not source_signature and isinstance(model.get("source_signature"), dict):
        source_signature = model["source_signature"]
    visual = props.get("visual_diversity_evidence") if isinstance(props.get("visual_diversity_evidence"), dict) else {}
    ambition = props.get("architectural_ambition_evidence") if isinstance(props.get("architectural_ambition_evidence"), dict) else {}
    repair = props.get("repair_delta") if isinstance(props.get("repair_delta"), dict) else {}
    massdsl = props.get("massdsl_proposal") if isinstance(props.get("massdsl_proposal"), dict) else {}
    design_params = massdsl.get("design_parameters") if isinstance(massdsl.get("design_parameters"), dict) else {}
    performance_proxy = early_massing_performance_proxy(feature)
    objective_vector = {
        "far_utilization": round(float(props.get("far_utilization") or 0.0), 4),
        "bcr_utilization": round(float(props.get("bcr_utilization") or 0.0), 4),
        "diversity_score": round(float(props.get("diversity_score") or 0.0), 4),
        "orderliness_score": round(float((props.get("orderliness_evidence") or {}).get("orderliness_score") or 0.0), 4)
        if isinstance(props.get("orderliness_evidence"), dict)
        else 0.0,
        "daylight_perimeter_proxy": performance_proxy.get("daylight_perimeter_proxy", 0.0),
        "south_solar_access_proxy": performance_proxy.get("south_solar_access_proxy", 0.0),
        "view_openness_proxy": performance_proxy.get("view_openness_proxy", 0.0),
        "mass_distribution_balance": performance_proxy.get("mass_distribution_balance", 0.0),
        "aggregate_performance_proxy": performance_proxy.get("aggregate_performance_proxy", 0.0),
    }
    source_family = str(source_signature.get("family") or props.get("operator_family") or "")
    generator_mode = str(visual.get("generator_mode") or source_signature.get("generator_mode") or "")
    formal_principle = str(ambition.get("formal_principle") or source_signature.get("formal_principle") or "")
    return {
        "schema_version": "arr.maas.paper_alignment.v1",
        "method_status": "paper_inspired_arr_native",
        "typology_generator": "llm_massdsl" if str(props.get("mass_shape") or "").startswith("llm_") else "grammar_or_seed_massdsl",
        "source_family": source_family,
        "generator_mode": generator_mode,
        "source_geometry_lineage": {
            "mass_shape": props.get("mass_shape"),
            "massdsl_source": massdsl.get("proposal_source") or "",
            "parameter_source": design_params.get("parameter_source") or "",
            "geometry_resolution": (props.get("geometry_resolution") or {}).get("status")
            if isinstance(props.get("geometry_resolution"), dict)
            else "",
        },
        "formal_variation_stage": {
            "formal_principle": formal_principle,
            "dominant_gesture": ambition.get("dominant_gesture") or source_signature.get("dominant_gesture") or "",
            "volume_based_variation": bool(formal_principle),
            "boundary_based_variation": bool(source_signature.get("rule_evidence") or visual.get("source_primitive_count")),
        },
        "objective_vector": objective_vector,
        "performance_proxy": performance_proxy,
        "legal_repair_delta": {
            "schema_version": repair.get("schema_version") or "",
            "area_retention": repair.get("area_retention"),
            "scope": repair.get("scope") or "",
        },
        "selection_reason": "final_review_candidate_after_legal_parking_diversity_gates",
        "limitations": [
            "Not a literal EvoMass clone.",
            "Environmental objectives are early massing proxies, not simulation-grade daylight/solar metrics.",
            "Second-stage preference cannot hide first-stage generator weakness.",
        ],
    }


def attach_paper_alignment_and_preference_evidence(feature: dict[str, Any]) -> None:
    props = feature.setdefault("properties", {})
    paper_alignment = paper_alignment_evidence(feature)
    props["paper_alignment_evidence"] = paper_alignment
    preference = props.get("preference_distillation")
    if not isinstance(preference, dict) or preference.get("schema_version") != "arr.maas.preference_distill.v1":
        preference = build_preference_distillation(feature)
        props["preference_distillation"] = preference
    model = props.get("maas_model")
    if isinstance(model, dict):
        model["paper_alignment_evidence"] = paper_alignment
        model["preference_distillation"] = preference


__all__ = [
    "attach_paper_alignment_and_preference_evidence",
    "paper_alignment_evidence",
]
