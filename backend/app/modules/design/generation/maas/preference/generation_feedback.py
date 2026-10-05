"""Turn VLM preference evidence into the next MAAS generation brief."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


GENERATION_FEEDBACK_SCHEMA_VERSION = "arr.maas.vlm_generation_feedback.v1"

DEFAULT_FORMAL_TARGETS = (
    "undercut_tapered_tower",
    "torqued_stack",
    "stacked_shifted_platforms",
    "folded_section",
    "carved_atrium",
    "split_bridge_connector",
    "carved_monolith",
    "slender_podium_tower",
)


def build_vlm_generation_feedback(
    payload: dict[str, Any],
    *,
    top_n: int = 5,
    bottom_n: int = 5,
) -> dict[str, Any]:
    """Build a compact feedback contract for the next LLM MassDSL batch."""
    response = payload.get("response") if isinstance(payload.get("response"), dict) else payload
    features = ((response.get("feature_collection") or {}).get("features") or []) if isinstance(response, dict) else []
    features = [feature for feature in features if isinstance(feature, dict)]
    top = features[: max(1, int(top_n))]
    bottom = features[-max(1, int(bottom_n)) :] if features else []
    vlm_scored = sum(1 for feature in features if _pref(feature).get("vlm_status") == "scored")
    top_terms = _terms(top)
    bottom_terms = _terms(bottom)
    must_use = _ranked_terms(top_terms, subtract=bottom_terms, limit=12)
    audit = response.get("preference_quality_audit") if isinstance(response.get("preference_quality_audit"), dict) else {}
    saturated = int(audit.get("top_reference_delta_saturated_count") or 0)
    return {
        "schema_version": GENERATION_FEEDBACK_SCHEMA_VERSION,
        "source": "vlm_preference_distillation",
        "candidate_count": len(features),
        "vlm_scored_count": vlm_scored,
        "top_n": len(top),
        "bottom_n": len(bottom),
        "must_use": must_use,
        "avoid": _avoid_terms(bottom),
        "quota": _language_quotas(must_use),
        "formal_principle_targets": _formal_targets(top),
        "reference_precedent_targets": _reference_targets(top),
        "top_candidate_brief": [_candidate_brief(feature) for feature in top],
        "bottom_candidate_brief": [_candidate_brief(feature) for feature in bottom],
        "critic_actions": _critic_actions(features),
        "reference_signal_diagnosis": {
            "top_reference_delta_saturated_count": saturated,
            "reference_delta_unique_count": audit.get("reference_delta_unique_count"),
            "action": "reduce broad tag bonuses; prefer formal/program/image-backed evidence"
            if saturated > max(2, len(top) // 2)
            else "reference signal usable",
        },
        "next_generation_instruction": (
            "Generate new MassDSL candidates, not a rerank of the same 20. "
            "Use top VLM massing languages as principles, avoid bottom/stepback/legal-layered patterns, "
            "and produce visibly new legal candidates for another VLM pass."
        ),
    }


def write_vlm_generation_feedback(path: Path, feedback: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(feedback, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _pref(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    return props.get("preference_distillation") if isinstance(props.get("preference_distillation"), dict) else {}


def _props(feature: dict[str, Any]) -> dict[str, Any]:
    return feature.get("properties") if isinstance(feature.get("properties"), dict) else {}


def _source(feature: dict[str, Any]) -> dict[str, Any]:
    props = _props(feature)
    source = props.get("source_signature")
    if isinstance(source, dict):
        return source
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    return model.get("source_signature") if isinstance(model.get("source_signature"), dict) else {}


def _ambition(feature: dict[str, Any]) -> dict[str, Any]:
    props = _props(feature)
    evidence = props.get("architectural_ambition_evidence")
    if isinstance(evidence, dict):
        return evidence
    nested = _source(feature).get("architectural_ambition_evidence")
    return nested if isinstance(nested, dict) else {}


def _visual(feature: dict[str, Any]) -> dict[str, Any]:
    props = _props(feature)
    evidence = props.get("visual_diversity_evidence")
    if isinstance(evidence, dict):
        return evidence
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    nested = model.get("visual_diversity_evidence")
    return nested if isinstance(nested, dict) else {}


def _terms(features: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for feature in features:
        props = _props(feature)
        source = _source(feature)
        ambition = _ambition(feature)
        visual = _visual(feature)
        values = [
            props.get("mass_shape"),
            props.get("operator_family"),
            source.get("family"),
            source.get("primary_language"),
            source.get("secondary_language"),
            source.get("formal_principle"),
            ambition.get("formal_principle"),
            ambition.get("dominant_gesture"),
            visual.get("mass_language"),
        ]
        for value in values:
            for token in _tokens(value):
                counts[token] += 1
    return counts


def _tokens(value: Any) -> list[str]:
    raw = str(value or "").lower().replace("-", "_").replace(" ", "_")
    known = (
        "undercut",
        "tapered",
        "diagonal",
        "bridge",
        "split",
        "interlock",
        "embedded_void",
        "courtyard",
        "atrium",
        "folded",
        "sloped_roof",
        "bend",
        "ribbon",
        "offset",
        "array_cluster",
        "reflected",
        "pinched",
        "branch",
        "nested",
        "extruded",
        "slender",
    )
    return sorted({term for term in known if term in raw})


def _ranked_terms(positive: Counter[str], *, subtract: Counter[str], limit: int) -> list[str]:
    scored = []
    for term, count in positive.items():
        score = count - subtract.get(term, 0) * 0.75
        if score > 0:
            scored.append((score, term))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [term for _, term in scored[:limit]]


def _avoid_terms(bottom: list[dict[str, Any]]) -> list[str]:
    avoid = {"generic_box", "legal_layered", "stair", "stepback", "taper_only"}
    for feature in bottom:
        props = _props(feature)
        visual = _visual(feature)
        scores = _pref(feature).get("concept_scores") if isinstance(_pref(feature).get("concept_scores"), dict) else {}
        shape = str(props.get("mass_shape") or "").lower()
        if "legal_layered" in shape:
            avoid.add("legal_layered_max")
        if "step" in shape or visual.get("stepback_dominant"):
            avoid.add("stepback_dominant")
        if float(scores.get("void_publicness") or 0.0) < 0.45:
            avoid.add("no_public_void")
        if float(scores.get("gesture_clarity") or 0.0) < 0.72:
            avoid.add("unclear_primary_gesture")
    return sorted(avoid)


def _language_quotas(must_use: list[str]) -> dict[str, int]:
    quotas = {
        "undercut_or_taper": 3,
        "diagonal_or_split_bridge": 4,
        "void_or_courtyard": 4,
        "folded_or_sloped_section": 3,
        "interlock_or_overlap": 3,
        "non_stepback_anchor": 18,
    }
    if "array_cluster" in must_use or "offset" in must_use:
        quotas["array_or_offset_cluster"] = 3
    if "nested" in must_use or "atrium" in must_use:
        quotas["nested_atrium_or_public_void"] = 3
    return quotas


def _formal_targets(top: list[dict[str, Any]]) -> list[str]:
    found = []
    for feature in top:
        principle = str(_ambition(feature).get("formal_principle") or _source(feature).get("formal_principle") or "")
        if principle and principle not in found:
            found.append(principle)
    result = []
    for item in [*found, *DEFAULT_FORMAL_TARGETS]:
        if item and item not in result:
            result.append(item)
    return result[:10]


def _candidate_brief(feature: dict[str, Any]) -> dict[str, Any]:
    props = _props(feature)
    pref = _pref(feature)
    source = _source(feature)
    return {
        "variant_id": props.get("variant_id"),
        "mass_shape": props.get("mass_shape"),
        "score": pref.get("distilled_preference_score"),
        "vlm_status": pref.get("vlm_status"),
        "family": source.get("family") or props.get("operator_family"),
        "primary_language": source.get("primary_language"),
        "secondary_language": source.get("secondary_language"),
        "formal_principle": _ambition(feature).get("formal_principle") or source.get("formal_principle"),
        "reference_matches": [
            {
                "title": match.get("title"),
                "source": match.get("source"),
                "matched_tags": match.get("matched_tags") or [],
                "score": match.get("score"),
            }
            for match in (pref.get("reference_matches") or [])[:3]
            if isinstance(match, dict)
        ],
    }


def _critic_actions(features: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for feature in features:
        actions = _pref(feature).get("critic_actions")
        if isinstance(actions, list):
            counts.update(str(action) for action in actions)
    return dict(sorted(counts.items()))


def _reference_targets(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str]] = Counter()
    tags: dict[tuple[str, str], Counter[str]] = {}
    for feature in features:
        pref = _pref(feature)
        for match in pref.get("reference_matches") or []:
            if not isinstance(match, dict):
                continue
            title = str(match.get("title") or "")
            source_id = str(match.get("source_id") or title)
            if not title:
                continue
            key = (source_id, title)
            counts[key] += max(1, int(float(match.get("score") or 1)))
            tag_counter = tags.setdefault(key, Counter())
            for tag in match.get("matched_tags") or []:
                tag_counter[str(tag)] += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0][1]))
    return [
        {
            "source_id": source_id,
            "title": title,
            "weight": weight,
            "massing_tags": [tag for tag, _ in tags.get((source_id, title), Counter()).most_common(8)],
        }
        for (source_id, title), weight in ranked[:8]
    ]


__all__ = [
    "GENERATION_FEEDBACK_SCHEMA_VERSION",
    "build_vlm_generation_feedback",
    "write_vlm_generation_feedback",
]
