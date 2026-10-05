"""Orchestrate direct manipulation, legal repair, and agent reviews."""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas import generate_legal_mass_variants
from backend.app.modules.design.generation.maas.agents import build_agent_review_a2ui_messages, build_agent_reviews
from backend.app.modules.design.generation.maas.interactive.geometry_ops import mutate_seed, trim_floor_plates
from backend.app.modules.design.generation.maas.interactive.schemas import append_operation_history, normalize_operation, operation_to_dict
from backend.app.modules.design.generation.services.site_geometry import geojson_to_polygon, wgs84_to_utm


def apply_interactive_mass_operation(
    *,
    mass_geojson: dict[str, Any],
    site_polygon_geojson: dict[str, Any],
    operation: dict[str, Any],
    constraints: list[dict[str, Any]] | None = None,
    building_type: str = "공동주택",
    sunlight_envelope: dict[str, Any] | None = None,
    setback_geometries: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if mass_geojson.get("type") != "Feature":
        raise ValueError("mass_geojson must be a Feature")

    normalized = normalize_operation(operation)
    site_area_m2 = wgs84_to_utm(geojson_to_polygon(site_polygon_geojson)).area

    trimmed = None
    if normalized.type == "push_pull_face":
        trimmed = trim_floor_plates(mass_geojson, normalized, site_area_m2)
    if trimmed is not None:
        feature, geometry_notes = trimmed
        feature = append_operation_history(feature, normalized, geometry_notes)
        constraints_summary = {
            "far_limit": next((c.get("val") for c in constraints or [] if c.get("name") == "far"), None),
            "bcr_limit": next((c.get("val") for c in constraints or [] if c.get("name") == "bcr"), None),
            "height_limit": next((c.get("val") for c in constraints or [] if c.get("name") == "height"), None),
        }
        agent_reviews = build_agent_reviews(
            operation_type=normalized.type,
            feature=feature,
            constraints=constraints_summary,
            geometry_notes=geometry_notes,
        )
        a2ui_messages = build_agent_review_a2ui_messages(
            surface_id="maas-agent-review",
            operation_type=normalized.type,
            feature=feature,
            agent_reviews=agent_reviews,
        )
        return {
            "mode": "interactive_operation",
            "operation": normalized.raw,
            "normalized_operation": operation_to_dict(normalized),
            "feature": feature,
            "metrics": feature.get("properties") or {},
            "agent_reviews": agent_reviews,
            "a2ui_messages": a2ui_messages,
            "notes": geometry_notes + ["law_agent: trimmed legal floor plate stack kept inside prior envelope"],
        }

    seed, geometry_notes = mutate_seed(mass_geojson, normalized)
    result = generate_legal_mass_variants(
        mass_geojson=seed,
        site_polygon_geojson=site_polygon_geojson,
        constraints=constraints or [],
        building_type=building_type,
        max_variants=8,
        sunlight_envelope=sunlight_envelope,
        setback_geometries=setback_geometries,
        include_interactive_seed=normalized.type in {"offset_edge", "scale_footprint", "reshape_floor_plate"},
        preferred_operator="interactive_seed_repaired"
        if normalized.type in {"offset_edge", "scale_footprint", "reshape_floor_plate"}
        else None,
    )
    features = result.get("feature_collection", {}).get("features") or []
    if not features:
        raise ValueError("operation produced no legal mass candidate")

    if normalized.type in {"offset_edge", "scale_footprint", "reshape_floor_plate"}:
        feature = next(
            (f for f in features if (f.get("properties") or {}).get("mass_shape") == "interactive_seed_repaired"),
            features[0],
        )
    else:
        feature = features[0]
    feature = append_operation_history(feature, normalized, geometry_notes)
    agent_reviews = build_agent_reviews(
        operation_type=normalized.type,
        feature=feature,
        constraints=result.get("constraints"),
        rejected=result.get("rejected"),
        geometry_notes=geometry_notes,
    )
    a2ui_messages = build_agent_review_a2ui_messages(
        surface_id="maas-agent-review",
        operation_type=normalized.type,
        feature=feature,
        agent_reviews=agent_reviews,
    )
    return {
        "mode": "interactive_operation",
        "operation": normalized.raw,
        "normalized_operation": operation_to_dict(normalized),
        "feature": feature,
        "metrics": feature.get("properties") or {},
        "agent_reviews": agent_reviews,
        "a2ui_messages": a2ui_messages,
        "notes": geometry_notes + result.get("notes", []),
    }


__all__ = ["apply_interactive_mass_operation"]
