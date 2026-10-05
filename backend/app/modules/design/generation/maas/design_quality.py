"""ARR-native MAAS design quality evidence.

This module absorbs the useful part of ``clone/MAAS`` evaluation philosophy:
verb sequences are first-class evidence, and candidates should expose compact
sequence/shape metrics instead of hiding architectural ranking behind a single
score.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from shapely.geometry import Polygon

from backend.app.modules.design.generation.maas.grammar.vocab import DESIGN_SECTION_VERBS, PLAN_VERBS, SECTION_VERBS


def _sequence_verbs(sequence: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None) -> list[str]:
    verbs: list[str] = []
    for item in sequence or []:
        if isinstance(item, dict) and isinstance(item.get("verb"), str):
            verbs.append(item["verb"])
    return verbs


def parsimony(sequence: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None) -> int:
    """Return verb count excluding ``base``."""
    return max(0, len([verb for verb in _sequence_verbs(sequence) if verb != "base"]))


def verb_set_jaccard(
    pred: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    gold: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> float:
    p = {verb for verb in _sequence_verbs(pred) if verb != "base"}
    g = {verb for verb in _sequence_verbs(gold) if verb != "base"}
    if not p and not g:
        return 1.0
    union = p | g
    return round(len(p & g) / len(union), 4) if union else 0.0


def token_f1(
    pred: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    gold: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> float:
    p = Counter(verb for verb in _sequence_verbs(pred) if verb != "base")
    g = Counter(verb for verb in _sequence_verbs(gold) if verb != "base")
    if not p and not g:
        return 1.0
    overlap = sum((p & g).values())
    if overlap <= 0:
        return 0.0
    precision = overlap / sum(p.values()) if p else 0.0
    recall = overlap / sum(g.values()) if g else 0.0
    return round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0


def ordered_lcs(
    pred: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    gold: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> int:
    a = [verb for verb in _sequence_verbs(pred) if verb != "base"]
    b = [verb for verb in _sequence_verbs(gold) if verb != "base"]
    if not a or not b:
        return 0
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, va in enumerate(a):
        for j, vb in enumerate(b):
            if va == vb:
                dp[i + 1][j + 1] = dp[i][j] + 1
            else:
                dp[i + 1][j + 1] = max(dp[i][j + 1], dp[i + 1][j])
    return dp[len(a)][len(b)]


def sequence_metrics(
    sequence: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    reference: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> dict[str, Any]:
    verbs = [verb for verb in _sequence_verbs(sequence) if verb != "base"]
    unique = sorted(set(verbs))
    plan_verbs = sorted(set(verbs) & PLAN_VERBS)
    section_verbs = sorted(set(verbs) & (SECTION_VERBS | DESIGN_SECTION_VERBS))
    result: dict[str, Any] = {
        "source": "arr.maas.sequence_metrics.v1",
        "parsimony": len(verbs),
        "unique_verb_count": len(unique),
        "verb_set": unique,
        "plan_verbs": plan_verbs,
        "section_verbs": section_verbs,
        "has_plan_operation": bool(plan_verbs),
        "has_section_operation": bool(section_verbs),
    }
    if reference is not None:
        lcs = ordered_lcs(sequence, reference)
        denom = max(parsimony(sequence), parsimony(reference))
        result["reference_comparison"] = {
            "jaccard": verb_set_jaccard(sequence, reference),
            "token_f1": token_f1(sequence, reference),
            "ordered_lcs": lcs,
            "lcs_score": round(lcs / denom, 4) if denom else 1.0,
        }
    return result


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _compactness_quality(footprint: Polygon | None) -> float:
    if footprint is None or footprint.is_empty or footprint.area <= 0:
        return 0.0
    # Square compactness is 16; circles are lower. Very jagged shapes climb.
    compactness = (footprint.length ** 2) / footprint.area
    return round(_clamp01(1.0 - max(0.0, compactness - 16.0) / 84.0), 4)


def _plate_profile_quality(props: dict[str, Any]) -> float:
    signature = props.get("shape_signature_3d") if isinstance(props.get("shape_signature_3d"), dict) else {}
    areas = signature.get("floor_plate_area_profile") or []
    areas = [float(area) for area in areas if isinstance(area, (int, float)) and area > 0]
    if len(areas) < 2:
        return 0.45
    top_ratio = areas[-1] / areas[0] if areas[0] > 0 else 0.0
    monotonic_steps = sum(1 for a, b in zip(areas, areas[1:]) if b <= a * 1.02)
    monotonic_quality = monotonic_steps / max(1, len(areas) - 1)
    usable_top = _clamp01((top_ratio - 0.08) / 0.72)
    return round(monotonic_quality * 0.65 + usable_top * 0.35, 4)


def build_design_quality_evidence(
    *,
    feature: dict[str, Any],
    footprint_utm: Polygon | None,
    reference_sequence: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    optimizer_backend: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return explainable design-quality evidence for a legal candidate."""
    props = feature.get("properties", {}) or {}
    sequence = props.get("maas_verb_sequence") or (props.get("maas_model") or {}).get("verb_sequence") or []
    seq_metrics = sequence_metrics(sequence, reference_sequence)

    capacity = _clamp01(float(props.get("far_utilization") or 0.0) * 0.62 + float(props.get("bcr_utilization") or 0.0) * 0.38)
    diversity = _clamp01(float(props.get("diversity_score") or 0.0))
    compactness = _compactness_quality(footprint_utm)
    plate_profile = _plate_profile_quality(props)
    sequence_richness = _clamp01(
        (min(seq_metrics["unique_verb_count"], 4) / 4.0) * 0.55
        + (0.25 if seq_metrics["has_plan_operation"] else 0.0)
        + (0.20 if seq_metrics["has_section_operation"] else 0.0)
    )

    score = round(
        capacity * 0.34
        + diversity * 0.18
        + compactness * 0.16
        + plate_profile * 0.16
        + sequence_richness * 0.16,
        4,
    )
    return {
        "source": "arr.maas.design_quality.v1",
        "score": score,
        "components": {
            "capacity": round(capacity, 4),
            "diversity": round(diversity, 4),
            "compactness": compactness,
            "plate_profile": plate_profile,
            "sequence_richness": round(sequence_richness, 4),
        },
        "sequence_metrics": seq_metrics,
        "optimizer_backend": optimizer_backend or {"name": "arr_native", "status": "not_requested"},
        "legal_truth": "ARR repair/evaluation remains authoritative; this is ranking evidence only.",
    }


def attach_design_quality_evidence(
    feature: dict[str, Any],
    *,
    footprint_utm: Polygon | None,
    reference_sequence: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    optimizer_backend: dict[str, Any] | None = None,
) -> None:
    props = feature.setdefault("properties", {})
    evidence = build_design_quality_evidence(
        feature=feature,
        footprint_utm=footprint_utm,
        reference_sequence=reference_sequence,
        optimizer_backend=optimizer_backend,
    )
    props["design_quality"] = evidence
    props["design_quality_score"] = evidence["score"]
    model = props.get("maas_model")
    if isinstance(model, dict):
        model["design_quality"] = evidence


__all__ = [
    "attach_design_quality_evidence",
    "build_design_quality_evidence",
    "ordered_lcs",
    "parsimony",
    "sequence_metrics",
    "token_f1",
    "verb_set_jaccard",
]
