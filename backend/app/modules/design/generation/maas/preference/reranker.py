"""Constrained reranker for MAAS preference-distilled candidates."""

from __future__ import annotations

from typing import Any


RERANK_SCHEMA_VERSION = "arr.maas.preference_rerank.v1"


def rerank_candidates(
    features: list[dict[str, Any]],
    *,
    pairwise_wins: dict[str, int] | None = None,
    diversity_reserve: int = 4,
) -> list[dict[str, Any]]:
    """Return candidates sorted by preference while preserving hard gates."""
    wins = pairwise_wins or {}
    eligible = [feature for feature in features if _hard_gate_pass(feature)]
    ranked = sorted(
        eligible,
        key=lambda feature: _rank_key(feature, wins),
        reverse=True,
    )
    if diversity_reserve > 0:
        ranked = _reserve_formal_diversity(ranked, diversity_reserve)
    for rank, feature in enumerate(ranked, start=1):
        props = feature.setdefault("properties", {})
        props["preference_rerank"] = {
            "schema_version": RERANK_SCHEMA_VERSION,
            "rank": rank,
            "score": round(_score(feature, wins), 4),
            "hard_gate_pass": True,
        }
    return ranked


def _rank_key(feature: dict[str, Any], wins: dict[str, int]) -> tuple[float, float, float, str]:
    return (
        _score(feature, wins),
        _orderliness(feature),
        _repair_integrity(feature),
        str((feature.get("properties") or {}).get("variant_id") or ""),
    )


def _score(feature: dict[str, Any], wins: dict[str, int]) -> float:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    pref = props.get("preference_distillation") if isinstance(props.get("preference_distillation"), dict) else {}
    variant_id = str(props.get("variant_id") or "")
    base = float(pref.get("distilled_preference_score") or 0.0)
    pairwise_bonus = min(0.15, wins.get(variant_id, 0) * 0.03)
    return max(0.0, min(1.0, base + pairwise_bonus))


def _reserve_formal_diversity(features: list[dict[str, Any]], minimum_formals: int) -> list[dict[str, Any]]:
    if len(features) <= 1:
        return features
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for feature in features:
        formal = _formal_principle(feature)
        if formal and formal not in seen:
            selected.append(feature)
            seen.add(formal)
        if len(seen) >= minimum_formals:
            break
    for feature in features:
        if feature not in selected:
            selected.append(feature)
    return selected


def _hard_gate_pass(feature: dict[str, Any]) -> bool:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    pref = props.get("preference_distillation") if isinstance(props.get("preference_distillation"), dict) else {}
    hard = pref.get("hard_gates") if isinstance(pref.get("hard_gates"), dict) else {}
    if hard:
        return hard.get("legal_gate_preserved") is True and hard.get("parking_mass_stage_gate_preserved") is True
    return True


def _formal_principle(feature: dict[str, Any]) -> str:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    ambition = props.get("architectural_ambition_evidence") if isinstance(props.get("architectural_ambition_evidence"), dict) else {}
    source = props.get("source_signature") if isinstance(props.get("source_signature"), dict) else {}
    return str(ambition.get("formal_principle") or source.get("formal_principle") or "")


def _orderliness(feature: dict[str, Any]) -> float:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    order = props.get("orderliness_evidence") if isinstance(props.get("orderliness_evidence"), dict) else {}
    return float(order.get("orderliness_score") or 0.0)


def _repair_integrity(feature: dict[str, Any]) -> float:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    repair = props.get("repair_delta") if isinstance(props.get("repair_delta"), dict) else {}
    return float(repair.get("area_retention") or 1.0)


__all__ = ["RERANK_SCHEMA_VERSION", "rerank_candidates"]
