"""Quantitative program-fit evidence for legal MAAS candidates."""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.program_massing.profiles import resolve_program_profile
from backend.app.modules.design.generation.maas.program_massing.spatial_evaluation import attach_program_spatial_evidence


def _component_failure_reasons(payload: dict[str, Any], fallback: str) -> list[Any]:
    for key in ("failure_reasons", "failures"):
        reasons = payload.get(key)
        if isinstance(reasons, (list, tuple)) and reasons:
            return list(reasons)
    reason = payload.get("failure_reason")
    if reason not in (None, ""):
        return [reason]
    return [fallback]


def _semantic_volume_count(
    volumes: list[Any],
    *,
    fallback: int,
) -> int:
    """Count typed masses, not repeated legal floor-band proxies."""

    if not volumes:
        return max(1, int(fallback or 1))
    if all(
        isinstance(volume, dict)
        and str(volume.get("role") or "").strip()
        for volume in volumes
    ):
        return len({
            str(volume["role"]).strip()
            for volume in volumes
        })
    return len(volumes)


def attach_program_massing_evidence(feature: dict[str, Any], *, building_type: str) -> dict[str, Any]:
    props = feature.setdefault("properties", {})
    profile = resolve_program_profile(building_type)
    signature = props.get("source_signature") if isinstance(props.get("source_signature"), dict) else {}
    family = str(signature.get("family") or props.get("operator_family") or props.get("typology_family") or "")
    volumes = props.get("mass_volumes") if isinstance(props.get("mass_volumes"), list) else []
    volume_count = _semantic_volume_count(
        volumes,
        fallback=int(signature.get("volume_count") or 1),
    )
    floors = int(props.get("num_floors") or 1)
    volume_min, volume_max = [int(value) for value in profile.get("target_volume_range", [1, 4])]
    floor_min, floor_max = [int(value) for value in profile.get("target_floor_range", [1, 40])]
    # Keep the documented hard boundary stable at exact decimal values. For
    # example, a five-volume gym candidate is 1 - 2*0.28 == 0.44 by policy,
    # but binary floating point can produce 0.439999... and reject it despite
    # the global clean-mass contract allowing <= 5 visible volumes.
    volume_fit = round(
        1.0 if volume_min <= volume_count <= volume_max
        else max(0.0, 1.0 - min(abs(volume_count - volume_min), abs(volume_count - volume_max)) * 0.28),
        6,
    )
    floor_fit = round(
        1.0 if floor_min <= floors <= floor_max
        else max(0.0, 1.0 - min(abs(floors - floor_min), abs(floors - floor_max)) * 0.12),
        6,
    )
    preferred = [str(item) for item in profile.get("preferred_families") or []]
    family_fit = 1.0 if any(token in family for token in preferred) else (0.55 if preferred else 0.75)
    coherence = signature.get("coherence_evidence") if isinstance(signature.get("coherence_evidence"), dict) else {}
    coherence_fit = float(coherence.get("score") or 0.65)
    spatial = attach_program_spatial_evidence(
        feature,
        building_type=building_type,
        site_area_m2=props.get("benchmark_site_area_m2"),
    )
    spatial_fit = float(spatial.get("architectural_score") or 0.0)
    score = volume_fit * 0.14 + floor_fit * 0.14 + family_fit * 0.18 + coherence_fit * 0.16 + spatial_fit * 0.38
    volume_hard_pass = volume_fit >= 0.44
    floor_hard_pass = floor_fit >= 0.40
    coherence_hard_pass = bool(coherence.get("hard_pass", coherence_fit >= 0.70))
    spatial_hard_pass = bool(spatial.get("hard_pass"))
    component_failure_reasons = {
        "volume": [] if volume_hard_pass else ["volume_fit_below_hard_pass_threshold"],
        "floor": [] if floor_hard_pass else ["floor_fit_below_hard_pass_threshold"],
        "coherence": (
            []
            if coherence_hard_pass
            else _component_failure_reasons(coherence, "coherence_hard_pass_false")
        ),
        "spatial": (
            []
            if spatial_hard_pass
            else _component_failure_reasons(spatial, "spatial_hard_pass_false")
        ),
    }
    evidence = {
        "schema_version": "arr.maas.program_massing_evidence.v1",
        "profile_id": profile["id"],
        "building_type": building_type,
        "design_intent": profile["design_intent"],
        "family": family,
        "preferred_families": preferred,
        "volume_count": volume_count,
        "floor_count": floors,
        "volume_fit": round(volume_fit, 3),
        "floor_fit": round(floor_fit, 3),
        "family_fit": round(family_fit, 3),
        "coherence_fit": round(coherence_fit, 3),
        "spatial_fit": round(spatial_fit, 3),
        "program_fit_score": round(max(0.0, min(1.0, score)), 3),
        "volume_hard_pass": volume_hard_pass,
        "floor_hard_pass": floor_hard_pass,
        "coherence_hard_pass": coherence_hard_pass,
        "spatial_hard_pass": spatial_hard_pass,
        "component_failure_reasons": component_failure_reasons,
        "failure_reasons": [
            reason
            for component in ("volume", "floor", "coherence", "spatial")
            for reason in component_failure_reasons[component]
        ],
        "hard_pass": bool(
            volume_hard_pass
            and floor_hard_pass
            and coherence_hard_pass
            and spatial_hard_pass
        ),
    }
    props["program_massing_evidence"] = evidence
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else None
    if model is not None:
        model["program_massing_evidence"] = evidence
    return evidence


__all__ = ["attach_program_massing_evidence"]
