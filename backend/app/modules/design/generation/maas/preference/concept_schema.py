"""Preference distillation schema for MAAS second-stage review."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PREFERENCE_SCHEMA_VERSION = "arr.maas.preference_distill.v1"
WEIGHTS_SCHEMA_VERSION = "arr.maas.preference_weights.v1"


def _load_weights() -> dict[str, float]:
    path = Path(__file__).with_name("architecture_massing_weights.v1.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        data = {}
    weights = data.get("weights") if isinstance(data.get("weights"), dict) else {}
    return {
        "gesture_clarity": float(weights.get("gesture_clarity", 0.22)),
        "hierarchy": float(weights.get("hierarchy", 0.18)),
        "non_stair_silhouette": float(weights.get("non_stair_silhouette", 0.18)),
        "void_publicness": float(weights.get("void_publicness", 0.12)),
        "repair_integrity": float(weights.get("repair_integrity", 0.14)),
        "precedent_resonance": float(weights.get("precedent_resonance", 0.16)),
    }


def _load_reference_signal_config() -> dict[str, float]:
    path = Path(__file__).with_name("architecture_massing_weights.v1.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        data = {}
    config = data.get("reference_signal") if isinstance(data.get("reference_signal"), dict) else {}
    return {
        "matched_score_unit": float(config.get("matched_score_unit", 0.04)),
        "matched_count_unit": float(config.get("matched_count_unit", 0.015)),
        "image_backed_unit": float(config.get("image_backed_unit", 0.02)),
        "cap": float(config.get("cap", 0.18)),
    }


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _concept_scores_from_geometry(feature: dict[str, Any]) -> dict[str, float]:
    """Return a deterministic proxy score until real VLM scores are attached."""
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    visual = props.get("visual_diversity_evidence") if isinstance(props.get("visual_diversity_evidence"), dict) else {}
    order = props.get("orderliness_evidence") if isinstance(props.get("orderliness_evidence"), dict) else {}
    ambition = props.get("architectural_ambition_evidence") if isinstance(props.get("architectural_ambition_evidence"), dict) else {}
    repair = props.get("repair_delta") if isinstance(props.get("repair_delta"), dict) else {}
    volume_count = float(visual.get("volume_count") or len(props.get("mass_volumes") or []) or 0)
    orderliness = float(order.get("orderliness_score") or 0)
    repair_retention = float(repair.get("area_retention") or 1.0)
    formal = 1.0 if ambition.get("architecture_grade_pass") else 0.55
    stair_penalty = 0.22 if visual.get("stepback_dominant") else 0.0
    concept = {
        "gesture_clarity": _clamp(orderliness * 0.72 + formal * 0.28),
        "hierarchy": _clamp(float(order.get("main_mass_area_ratio") or 0) * 0.52 + orderliness * 0.48),
        "non_stair_silhouette": _clamp(0.86 - stair_penalty + min(volume_count, 5.0) * 0.015),
        "void_publicness": _clamp(0.42 + (0.18 if visual.get("hole_count") else 0.0) + (0.16 if "court" in str(visual.get("mass_language") or "") else 0.0)),
        "repair_integrity": _clamp(repair_retention),
        "precedent_resonance": _clamp(float(ambition.get("silhouette_strength") or 0.68) * 0.5 + float(ambition.get("sectional_diagram_clarity") or 0.68) * 0.5),
    }
    return {key: round(value, 3) for key, value in concept.items()}


def build_preference_distillation(
    feature: dict[str, Any],
    *,
    image_uri: str | None = None,
    vlm_model: str | None = None,
    vlm_scores: dict[str, Any] | None = None,
    reference_matches: list[dict[str, Any]] | None = None,
    human_pairwise_wins: int = 0,
    vlm_status: str = "not_requested",
    vlm_error: str = "",
) -> dict[str, Any]:
    """Build second-stage preference evidence without weakening hard gates."""
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    parking = props.get("parking_precheck") if isinstance(props.get("parking_precheck"), dict) else {}
    layout = parking.get("layout_candidate") if isinstance(parking.get("layout_candidate"), dict) else {}
    mass_stage = layout.get("mass_stage_parking") if isinstance(layout.get("mass_stage_parking"), dict) else {}
    legal_gate = bool(props.get("legal_pass", True))
    parking_gate = str(mass_stage.get("status") or layout.get("status") or "") in {
        "pass",
        "needs_mechanical_parking_review",
        "needs_drive_connectivity_review",
    }
    scores = _normalize_scores(vlm_scores) if vlm_scores else _concept_scores_from_geometry(feature)
    reference_signal = _reference_signal(reference_matches or [])
    scores = _apply_reference_signal(scores, reference_signal)
    weights = _load_weights()
    weighted = sum(
        scores[key] * weights.get(key, 0.0)
        for key in scores
    )
    if human_pairwise_wins:
        weighted += min(0.12, human_pairwise_wins * 0.025)
    return {
        "schema_version": PREFERENCE_SCHEMA_VERSION,
        "stage": "second_distillation",
        "mode": "vlm_scored" if vlm_scores and vlm_model else ("geometry_proxy_fallback" if vlm_status == "failed" else "vlm_ready_geometry_proxy"),
        "hard_gates": {
            "legal_gate_preserved": legal_gate,
            "parking_mass_stage_gate_preserved": parking_gate,
            "cannot_override_law_or_parking": True,
        },
        "image_uri": image_uri or "",
        "vlm_model": vlm_model or "",
        "vlm_status": vlm_status,
        "vlm_error": vlm_error,
        "qa_schema": "arr.maas.preference_qa.v1",
        "weight_schema": WEIGHTS_SCHEMA_VERSION,
        "weight_source": "architecture_massing_weights.v1.json",
        "concept_scores": scores,
        "reference_signal": reference_signal,
        "reference_matches": reference_matches or [],
        "human_pairwise_wins": int(human_pairwise_wins),
        "distilled_preference_score": round(_clamp(weighted), 3),
        "notes": [
            "VLM may score rendered PNG concept quality only.",
            "Preference score is applied after legal and parking hard gates.",
            "Geometry proxy mode is not a claim that VLM inference has run.",
        ],
    }


def _normalize_scores(scores: dict[str, Any] | None) -> dict[str, float]:
    raw = scores or {}
    return {
        key: round(_clamp(float(raw.get(key, 0.0))), 3)
        for key in (
            "gesture_clarity",
            "hierarchy",
            "non_stair_silhouette",
            "void_publicness",
            "repair_integrity",
            "precedent_resonance",
        )
    }


def _reference_signal(reference_matches: list[dict[str, Any]]) -> dict[str, Any]:
    config = _load_reference_signal_config()
    score_sum = 0.0
    image_backed = 0
    for match in reference_matches:
        if not isinstance(match, dict):
            continue
        score_sum += float(match.get("score") or 0.0)
        if match.get("local_path") or match.get("image_url"):
            image_backed += 1
    raw_delta = (
        score_sum * config["matched_score_unit"]
        + len(reference_matches) * config["matched_count_unit"]
        + image_backed * config["image_backed_unit"]
    )
    return {
        "schema_version": "arr.maas.reference_signal.v1",
        "matched_reference_count": len(reference_matches),
        "matched_score_sum": round(score_sum, 3),
        "image_backed_reference_count": image_backed,
        "precedent_resonance_delta": round(_clamp(raw_delta, 0.0, config["cap"]), 3),
        "config": config,
    }


def _apply_reference_signal(scores: dict[str, float], reference_signal: dict[str, Any]) -> dict[str, float]:
    updated = dict(scores)
    updated["precedent_resonance"] = round(_clamp(
        float(updated.get("precedent_resonance") or 0.0)
        + float(reference_signal.get("precedent_resonance_delta") or 0.0)
    ), 3)
    return updated


__all__ = ["PREFERENCE_SCHEMA_VERSION", "build_preference_distillation"]
