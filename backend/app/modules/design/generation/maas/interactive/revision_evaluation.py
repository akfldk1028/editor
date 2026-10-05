"""Quantitative before/after evaluation for reference-conditioned MAAS edits."""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import tempfile
from pathlib import Path
from typing import Any

from backend.app.modules.design.generation.maas.preference.loop import openai_preview_preference_scorer


REVISION_EVALUATION_SCHEMA_VERSION = "arr.maas.revision_evaluation.v1"
DEFAULT_MIN_INTENT_CONFIDENCE = 0.60
DEFAULT_MIN_REFERENCE_DELTA = 0.01
DEFAULT_MIN_QUALITY_DELTA = -0.02


def evaluate_reference_revision(
    *,
    before_feature: dict[str, Any],
    after_feature: dict[str, Any],
    references: list[dict[str, Any]],
    intent_confidence: float,
    model: str | None = None,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Score both states against the same references and compute an improvement gate."""
    if not references:
        raise ValueError("reference revision evaluation requires reference images")
    cache_root = cache_dir or (
        _design_paths.workspace_root()
        / "docs" / "ai-session-memory" / "reference-corpus" / "revision-vlm-cache"
    )
    with tempfile.TemporaryDirectory(prefix="maas-reference-revision-") as temporary:
        scorer = openai_preview_preference_scorer(preview_dir=Path(temporary), cache_dir=cache_root)
        before = scorer(feature=before_feature, reference_matches=references, model=model)
        after = scorer(feature=after_feature, reference_matches=references, model=model)
    before_metrics = _metrics(before)
    after_metrics = _metrics(after)
    reference_delta = round(after_metrics["reference_adherence"] - before_metrics["reference_adherence"], 4)
    quality_delta = round(after_metrics["mass_quality"] - before_metrics["mass_quality"], 4)
    confidence_pass = float(intent_confidence) >= DEFAULT_MIN_INTENT_CONFIDENCE
    reference_pass = reference_delta >= DEFAULT_MIN_REFERENCE_DELTA
    quality_pass = quality_delta >= DEFAULT_MIN_QUALITY_DELTA
    improved = bool(confidence_pass and reference_pass and quality_pass)
    failures: list[str] = []
    if not confidence_pass:
        failures.append("reference_intent_confidence_too_low")
    if not reference_pass:
        failures.append("reference_adherence_did_not_improve")
    if not quality_pass:
        failures.append("visible_mass_quality_regressed")
    return {
        "schema_version": REVISION_EVALUATION_SCHEMA_VERSION,
        "status": "improved" if improved else "not_improved",
        "improvement_gate_pass": improved,
        "thresholds": {
            "min_intent_confidence": DEFAULT_MIN_INTENT_CONFIDENCE,
            "min_reference_delta": DEFAULT_MIN_REFERENCE_DELTA,
            "min_quality_delta": DEFAULT_MIN_QUALITY_DELTA,
        },
        "intent_confidence": round(float(intent_confidence), 3),
        "before": before_metrics,
        "after": after_metrics,
        "reference_adherence_delta": reference_delta,
        "mass_quality_delta": quality_delta,
        "cache_hit_count": int(bool(before.get("cache_hit"))) + int(bool(after.get("cache_hit"))),
        "vlm_call_count": 2 - int(bool(before.get("cache_hit"))) - int(bool(after.get("cache_hit"))),
        "failures": failures,
    }


def _metrics(result: dict[str, Any]) -> dict[str, Any]:
    scores = result.get("concept_scores") if isinstance(result.get("concept_scores"), dict) else {}
    def score(name: str) -> float:
        return max(0.0, min(1.0, float(scores.get(name) or 0.0)))
    quality = (
        score("gesture_clarity") * 0.30
        + score("hierarchy") * 0.28
        + score("repair_integrity") * 0.22
        + score("non_stair_silhouette") * 0.10
        + score("void_publicness") * 0.10
    )
    return {
        "reference_adherence": round(score("precedent_resonance"), 4),
        "mass_quality": round(quality, 4),
        "concept_scores": {key: round(score(key), 4) for key in (
            "gesture_clarity", "hierarchy", "non_stair_silhouette",
            "void_publicness", "repair_integrity", "precedent_resonance",
        )},
        "model": str(result.get("model") or ""),
        "response_id": str(result.get("response_id") or ""),
        "cache_hit": bool(result.get("cache_hit")),
    }


__all__ = ["REVISION_EVALUATION_SCHEMA_VERSION", "evaluate_reference_revision"]
