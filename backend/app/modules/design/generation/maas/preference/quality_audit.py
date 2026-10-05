"""Quality audit for MAAS preference-distilled mass candidates."""

from __future__ import annotations

from typing import Any


QUALITY_AUDIT_SCHEMA_VERSION = "arr.maas.preference_quality_audit.v1"


def audit_preference_output(payload: dict[str, Any], *, top_n: int = 8) -> dict[str, Any]:
    response = payload.get("response") if isinstance(payload.get("response"), dict) else payload
    collection = response.get("feature_collection") if isinstance(response.get("feature_collection"), dict) else {}
    features = collection.get("features") if isinstance(collection.get("features"), list) else []
    top = features[: max(1, int(top_n))]
    failures: list[str] = []
    reference_covered = sum(1 for feature in top if _reference_count(feature) > 0)
    hard_gate_pass = sum(1 for feature in features if _hard_gate_pass(feature))
    stepback_like = sum(1 for feature in top if _is_stepback_like(feature))
    avg_orderliness = _avg(_orderliness(feature) for feature in top)
    avg_preference = _avg(_preference_score(feature) for feature in top)
    avg_reference_delta = _avg(_reference_delta(feature) for feature in top)
    vlm_scored = sum(1 for feature in features if _vlm_status(feature) == "scored")
    top_vlm_scored = sum(1 for feature in top if _vlm_status(feature) == "scored")
    reference_deltas = [_reference_delta(feature) for feature in features]
    top_reference_deltas = [_reference_delta(feature) for feature in top]
    saturated_reference_delta = sum(1 for value in top_reference_deltas if value >= 0.18)
    score_values = [_preference_score(feature) for feature in features]
    warnings: list[str] = []
    if len(features) < 10:
        failures.append("candidate_count_too_low")
    if hard_gate_pass != len(features):
        failures.append("hard_gate_failure_present")
    if reference_covered < max(1, int(len(top) * 0.75)):
        failures.append("top_reference_coverage_too_low")
    if stepback_like > max(1, int(len(top) * 0.25)):
        failures.append("top_stepback_overrepresented")
    if avg_orderliness < 0.84:
        failures.append("top_orderliness_too_low")
    if avg_preference < 0.72:
        failures.append("top_preference_score_too_low")
    if avg_reference_delta <= 0:
        failures.append("reference_signal_not_applied")
    if vlm_scored and vlm_scored != len(features):
        failures.append("partial_vlm_scoring")
    if saturated_reference_delta > max(2, int(len(top) * 0.5)):
        warnings.append("reference_signal_saturated_for_top_candidates")
    if _range(score_values) < 0.12 and vlm_scored:
        warnings.append("vlm_score_spread_too_narrow_for_visible_rerank")
    return {
        "schema_version": QUALITY_AUDIT_SCHEMA_VERSION,
        "status": "pass" if not failures else "fail",
        "top_n": len(top),
        "candidate_count": len(features),
        "hard_gate_pass_count": hard_gate_pass,
        "top_reference_covered_count": reference_covered,
        "top_stepback_like_count": stepback_like,
        "top_avg_orderliness": round(avg_orderliness, 4),
        "top_avg_preference_score": round(avg_preference, 4),
        "top_avg_reference_delta": round(avg_reference_delta, 4),
        "vlm_scored_count": vlm_scored,
        "top_vlm_scored_count": top_vlm_scored,
        "preference_score_range": round(_range(score_values), 4),
        "reference_delta_unique_count": len(set(round(value, 4) for value in reference_deltas)),
        "top_reference_delta_saturated_count": saturated_reference_delta,
        "warnings": warnings,
        "failures": failures,
    }


def _pref(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    return props.get("preference_distillation") if isinstance(props.get("preference_distillation"), dict) else {}


def _reference_count(feature: dict[str, Any]) -> int:
    refs = _pref(feature).get("reference_matches")
    return len(refs) if isinstance(refs, list) else 0


def _reference_delta(feature: dict[str, Any]) -> float:
    signal = _pref(feature).get("reference_signal")
    if not isinstance(signal, dict):
        return 0.0
    return float(signal.get("precedent_resonance_delta") or 0.0)


def _preference_score(feature: dict[str, Any]) -> float:
    return float(_pref(feature).get("distilled_preference_score") or 0.0)


def _vlm_status(feature: dict[str, Any]) -> str:
    return str(_pref(feature).get("vlm_status") or "")


def _hard_gate_pass(feature: dict[str, Any]) -> bool:
    hard = _pref(feature).get("hard_gates")
    if not isinstance(hard, dict):
        return False
    return hard.get("legal_gate_preserved") is True and hard.get("parking_mass_stage_gate_preserved") is True


def _orderliness(feature: dict[str, Any]) -> float:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    evidence = props.get("orderliness_evidence") if isinstance(props.get("orderliness_evidence"), dict) else {}
    return float(evidence.get("orderliness_score") or 0.0)


def _is_stepback_like(feature: dict[str, Any]) -> bool:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    visual = props.get("visual_diversity_evidence") if isinstance(props.get("visual_diversity_evidence"), dict) else {}
    mass_shape = str(props.get("mass_shape") or "").lower()
    mass_language = str(visual.get("mass_language") or "").lower()
    return bool(visual.get("stepback_dominant")) or "stepback" in mass_shape or "stepped" in mass_language


def _avg(values: Any) -> float:
    vals = [float(value) for value in values]
    return sum(vals) / len(vals) if vals else 0.0


def _range(values: Any) -> float:
    vals = [float(value) for value in values]
    return max(vals) - min(vals) if vals else 0.0


__all__ = ["QUALITY_AUDIT_SCHEMA_VERSION", "audit_preference_output"]
