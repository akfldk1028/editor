"""Build image-generation job records from MAAS evidence."""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.aesthetic.prompts import build_facade_prompt
from backend.app.modules.design.generation.maas.aesthetic.reference_render import build_reference_render_spec


def build_aesthetic_image_job(
    evidence: dict[str, Any],
    *,
    provider: str = "gpt-image",
    style: str | None = None,
) -> dict[str, Any]:
    candidate = evidence.get("candidate") or {}
    prompt = build_facade_prompt(evidence, style=style)
    render_spec = build_reference_render_spec(evidence)
    geometry = evidence.get("geometry") or {}
    return {
        "schema_version": "arr.maas.aesthetic_image_job.v0",
        "job_id": f"aesthetic:{evidence.get('bundle_id')}",
        "source_bundle_id": evidence.get("bundle_id"),
        "candidate_id": candidate.get("candidate_id"),
        "provider": provider,
        "mode": "reference_image_to_image",
        "prompt": prompt,
        "reference_render": render_spec,
        "locked_geometry": {
            "mass_geojson": geometry.get("mass_geojson"),
            "floor_plates": geometry.get("floor_plates") or [],
            "mass_volumes": geometry.get("mass_volumes") or [],
            "geometry_metrics": geometry.get("geometry_metrics") or {},
        },
        "required_outputs": [
            "reference_mass_render",
            "generated_facade_image",
            "silhouette_validation",
        ],
        "evidence_policy": {
            "may_change": ["facade_materials", "window_pattern", "surface_detail", "lighting", "presentation_style"],
            "must_not_change": ["mass_geojson", "height", "floor_count", "setbacks", "legal_envelope", "roofline"],
            "legal_status_effect": "none",
        },
    }


__all__ = ["build_aesthetic_image_job"]
