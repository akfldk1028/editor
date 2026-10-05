"""Coordinate-free design-relation descriptors shared with Mass-Brain.

The profile intentionally records architectural behaviour (preserve, carve,
step, bend, bridge, cluster, fold), not precedent coordinates or parcel-sized
templates. It is therefore safe to retrieve and learn across sites.
"""

from __future__ import annotations

from typing import Any, Iterable


STRATEGY_VERBS: tuple[tuple[str, frozenset[str]], ...] = (
    ("bridge", frozenset({"bridge", "diagonal_connect", "interlock", "intersect", "join", "terrace_link", "overlap"})),
    ("cluster", frozenset({"array", "branch", "embed", "merge", "nest", "pack", "reflect", "split"})),
    ("fold", frozenset({"inflate", "sloped_roof_mass", "grade", "taper"})),
    ("step", frozenset({"stack", "step_envelope", "lift"})),
    ("bend", frozenset({"bar", "bend", "lodge", "offset", "rotate", "shear", "shift", "skew", "twist"})),
    ("carve", frozenset({"carve", "cave", "compress", "courtyard", "extract", "fracture", "inscribe", "inset", "notch", "pinch", "puncture"})),
)


def relation_profile_from_sequence(
    calls: Iterable[Any],
    *,
    source_signature: dict[str, Any] | None = None,
) -> dict[str, Any]:
    signature = source_signature if isinstance(source_signature, dict) else {}
    normalized = [_call_parts(call) for call in calls]
    verbs = [verb for verb, _params in normalized if verb and verb != "base"]
    void_calls = [(verb, params) for verb, params in normalized if verb in {"carve", "courtyard", "cave", "extract", "inscribe", "notch", "pinch", "puncture", "inset"}]
    lift_calls = [(verb, params) for verb, params in normalized if verb in {"lift", "bridge", "diagonal_connect"}]
    void_ratio = max((_first_ratio(params, ("void_ratio", "ratio", "depth_ratio", "distance_ratio"), 0.2) for _verb, params in void_calls), default=0.0)
    ground_opening = max((_first_ratio(params, ("lower_floor_fraction", "opening_ratio", "lift_ratio", "ratio"), 0.18) for _verb, params in lift_calls), default=0.0)
    destructive_count = sum(verb in {"carve", "cave", "compress", "courtyard", "extract", "fracture", "inscribe", "inset", "notch", "pinch", "puncture", "split"} for verb in verbs)
    volume_count = _integer(signature.get("visible_volume_count") or signature.get("volume_count"), max(1, len(verbs)))
    surface_count = _integer(signature.get("effective_surface_count") or signature.get("surface_count"), 0)
    primary_retention = _ratio(
        signature.get("main_mass_area_ratio")
        or (signature.get("orderliness_evidence") or {}).get("main_mass_area_ratio"),
        0.78 if destructive_count else 0.92,
    )
    return {
        # In a flat sequence the first non-base call is the primary operation.
        # Later calls are modifiers and must not relabel an array as a fold just
        # because it also contains grade, or a roof field as a bridge because a
        # terrace connector follows it.
        "formalStrategy": _strategy(verbs, signature, primary_verb=verbs[0] if verbs else ""),
        "primaryEnvelopeRetention": primary_retention,
        "dominantOperationCount": max(1, min(4, len(verbs))),
        "voidRatio": _ratio(signature.get("void_ratio"), void_ratio),
        "groundOpeningRatio": _ratio(signature.get("ground_opening_ratio"), ground_opening),
        "groundContactRatio": _ratio(signature.get("ground_contact_ratio"), 1.0 - ground_opening * 0.6),
        "componentCount": max(1, min(12, volume_count)),
        "smallFragmentCount": max(0, _integer(signature.get("small_fragment_count"), 0)),
        "surfaceCount": max(0, surface_count),
        "heightWidthRatio": _positive(signature.get("height_width_ratio"), 0.6),
        "compactness": _ratio(signature.get("compactness") or signature.get("rectangle_compactness"), 0.8),
    }


def relation_profile_from_feature(feature: dict[str, Any] | None) -> dict[str, Any]:
    props = feature.get("properties") if isinstance(feature, dict) and isinstance(feature.get("properties"), dict) else {}
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    signature = props.get("source_signature") if isinstance(props.get("source_signature"), dict) else model.get("source_signature")
    signature = dict(signature) if isinstance(signature, dict) else {}
    order = props.get("orderliness_evidence") if isinstance(props.get("orderliness_evidence"), dict) else {}
    visual = props.get("visual_diversity_evidence") if isinstance(props.get("visual_diversity_evidence"), dict) else {}
    volumes = props.get("mass_volumes") if isinstance(props.get("mass_volumes"), list) else model.get("volumes")
    volumes = volumes if isinstance(volumes, list) else []
    signature.update({
        "main_mass_area_ratio": order.get("main_mass_area_ratio"),
        "small_fragment_count": order.get("small_fragment_count"),
        "visible_volume_count": len(volumes) or visual.get("volume_count"),
    })
    calls = signature.get("component_graph", {}).get("nodes") if isinstance(signature.get("component_graph"), dict) else None
    if isinstance(calls, list):
        operations = [item.get("operation") for item in calls if isinstance(item, dict) and isinstance(item.get("operation"), dict)]
    else:
        operations = [{"verb": verb, "params": {}} for verb in signature.get("verb_profile") or []]
    profile = relation_profile_from_sequence(operations, source_signature=signature)
    profile["primaryEnvelopeRetention"] = _ratio(order.get("main_mass_area_ratio"), profile["primaryEnvelopeRetention"])
    profile["smallFragmentCount"] = max(0, _integer(order.get("small_fragment_count"), profile["smallFragmentCount"]))
    profile["componentCount"] = max(1, min(12, _integer(visual.get("volume_count"), profile["componentCount"])))
    return profile


def site_aspect_bucket(footprint: Any) -> str:
    try:
        minx, miny, maxx, maxy = footprint.bounds
        width, depth = maxx - minx, maxy - miny
        ratio = max(width, depth) / max(min(width, depth), 1e-6)
    except (AttributeError, TypeError, ValueError):
        return "unknown"
    if ratio < 1.25:
        return "balanced"
    if ratio < 1.8:
        return "elongated"
    return "slender"


def _strategy(verbs: list[str], signature: dict[str, Any], *, primary_verb: str = "") -> str:
    formal = str(signature.get("formal_principle") or (signature.get("architectural_ambition_evidence") or {}).get("formal_principle") or "").lower()
    # Explicit measured source evidence is authoritative. Otherwise classify
    # the primary operation first and use the remaining verbs only as a legacy
    # fallback for a base-only/unknown graph.
    combined = [formal] if formal else ([primary_verb] if primary_verb else verbs)
    for strategy, vocabulary in STRATEGY_VERBS:
        if any(any(token in value for token in vocabulary) for value in combined):
            return strategy
    return "preserve"


def _call_parts(call: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(call, dict):
        operation = call.get("operation") if isinstance(call.get("operation"), dict) else call
        return str(operation.get("verb") or ""), dict(operation.get("params") or {})
    return str(getattr(call, "verb", "")), dict(getattr(call, "params", {}) or {})


def _first_ratio(params: dict[str, Any], keys: tuple[str, ...], fallback: float) -> float:
    for key in keys:
        if key in params:
            return _ratio(params.get(key), fallback)
    return fallback


def _ratio(value: Any, fallback: float) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 4)
    except (TypeError, ValueError):
        return round(max(0.0, min(1.0, fallback)), 4)


def _positive(value: Any, fallback: float) -> float:
    try:
        return round(max(0.02, min(20.0, float(value))), 4)
    except (TypeError, ValueError):
        return fallback


def _integer(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


__all__ = ["relation_profile_from_feature", "relation_profile_from_sequence", "site_aspect_bucket"]
