"""Constraint predicates for MAAS review selection."""

from __future__ import annotations

from typing import Callable

from backend.app.modules.design.generation.maas.selection.types import Feature, FeatureBool, ReviewSetConstraintCallbacks


def final_shape(feature: Feature) -> str:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    return str(props.get("mass_shape") or "")


def final_mass_stage_parking_pass(feature: Feature) -> bool:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    precheck = props.get("parking_precheck") if isinstance(props.get("parking_precheck"), dict) else {}
    layout = precheck.get("layout_candidate") if isinstance(precheck.get("layout_candidate"), dict) else {}
    mass_stage = layout.get("mass_stage_parking") if isinstance(layout.get("mass_stage_parking"), dict) else {}
    status = str(mass_stage.get("status") or layout.get("status") or "")
    return status in {"pass", "needs_mechanical_parking_review", "needs_drive_connectivity_review"}


def layout_status(feature: Feature) -> str:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    precheck = props.get("parking_precheck") if isinstance(props.get("parking_precheck"), dict) else {}
    layout = precheck.get("layout_candidate") if isinstance(precheck.get("layout_candidate"), dict) else {}
    return str(layout.get("status") or "")


def source_reviewable(
    feature: Feature,
    *,
    has_review_source_geometry: FeatureBool,
    is_reviewable_architectural_mass: FeatureBool,
) -> bool:
    return has_review_source_geometry(feature) and is_reviewable_architectural_mass(feature)


def unresolved_llm_authoring(feature: Feature) -> bool:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    research = props.get("research_basis") if isinstance(props.get("research_basis"), dict) else {}
    proposal = props.get("massdsl_proposal") if isinstance(props.get("massdsl_proposal"), dict) else {}
    parameters = proposal.get("design_parameters") if isinstance(proposal.get("design_parameters"), dict) else {}
    return research.get("requires_llm_authoring") is True or parameters.get("requires_llm_authoring") is True


def visible_tier_count(feature: Feature) -> int:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    volumes = props.get("mass_volumes") if isinstance(props.get("mass_volumes"), list) else model.get("volumes")
    if not isinstance(volumes, list):
        return 0
    tiers = {
        (
            str(volume.get("bottom_height", volume.get("bottom_fraction", ""))),
            str(volume.get("top_height", volume.get("top_fraction", ""))),
        )
        for volume in volumes
        if isinstance(volume, dict)
    }
    return len(tiers)


def review_set_geometry_ok(
    feature: Feature,
    *,
    final_limit: int,
    has_source_geometry_pool: bool,
    callbacks: ReviewSetConstraintCallbacks,
) -> bool:
    if final_limit < 20 or not has_source_geometry_pool:
        return True
    if not callbacks.architectural_order_gate(feature)[0]:
        return False
    if unresolved_llm_authoring(feature):
        return False
    if callbacks.visible_volume_count(feature) <= 2:
        return False
    if visible_tier_count(feature) <= 2:
        return False
    return True


def review_set_constraints_ok(
    items: list[Feature],
    *,
    max_weak_llm_review_masses: int,
    max_stepback_dominant: int,
    max_plain_review_masses: int,
    max_same_source_family: int,
    max_language_repeat: int,
    stepback_dominant_families: set[str],
    review_geometry_ok: Callable[[Feature], bool],
    callbacks: ReviewSetConstraintCallbacks,
) -> bool:
    ids = [id(item) for item in items]
    if len(ids) != len(set(ids)):
        return False
    shapes = [
        str((item.get("properties") or {}).get("mass_shape") or "")
        for item in items
        if str((item.get("properties") or {}).get("mass_shape") or "")
    ]
    if len(shapes) != len(set(shapes)):
        return False
    if sum(1 for item in items if (((item.get("properties") or {}).get("llm_candidate_quality") or {}).get("status") == "reject_final_review")) > max_weak_llm_review_masses:
        return False
    if sum(1 for item in items if callbacks.source_family(item) in stepback_dominant_families) > max_stepback_dominant:
        return False
    if sum(1 for item in items if callbacks.is_plain_review_mass(item)) > max_plain_review_masses:
        return False
    if any(not final_mass_stage_parking_pass(item) for item in items):
        return False
    if any(not review_geometry_ok(item) for item in items):
        return False
    family_counts: dict[str, int] = {}
    language_counts: dict[str, int] = {}
    for item in items:
        family = callbacks.source_family(item)
        if family:
            family_counts[family] = family_counts.get(family, 0) + 1
        language = callbacks.research_mass_language(item)
        if language:
            language_counts[language] = language_counts.get(language, 0) + 1
    if any(count > max_language_repeat for language, count in language_counts.items() if language not in {"legal_layered_anchor"}):
        return False
    return all(
        count <= max_same_source_family
        for family, count in family_counts.items()
        if family not in {"legal_layered", "legal_buildable", "bcr_fill"}
    )
