"""Prompt builders for MAAS facade/material image generation."""

from __future__ import annotations

from typing import Any


BUILDING_TYPE_STYLE_HINTS = {
    "공동주택": "award-quality contemporary Korean residential architecture, elegant masonry and metal detailing, deep-set windows, refined balcony rhythm",
    "근린생활시설": "award-quality small urban mixed-use architecture, active transparent ground floor, refined retail frontage, calm upper facade",
    "업무시설": "quiet premium contemporary office architecture, precise curtain wall rhythm, restrained stone and metal details",
    "판매시설": "urban retail architecture with a transparent podium, strong pedestrian frontage, elegant signage zone without text",
    "숙박시설": "compact boutique hotel architecture, warm facade lighting, regular guestroom grid, refined material transitions",
}


def build_facade_prompt(evidence: dict[str, Any], *, style: str | None = None) -> dict[str, Any]:
    candidate = evidence.get("candidate") or {}
    intended_use = candidate.get("intended_use") or {}
    geometry = evidence.get("geometry") or {}
    metrics = geometry.get("geometry_metrics") or {}
    building_type = intended_use.get("building_type") or evidence.get("program", {}).get("building_type") or "unknown"
    style_hint = style or BUILDING_TYPE_STYLE_HINTS.get(str(building_type), "contemporary architecture")

    prompt = (
        f"{style_hint}; architect-designed facade composition for a legal massing model; "
        f"preserve the exact building silhouette, height, floor count, massing steps, setbacks, and roofline; "
        f"do not add extra towers, wings, floors, balconies outside the envelope, or change the footprint; "
        f"create a coherent base-middle-top elevation strategy, street-level entrance clarity, aligned floor datums, "
        f"deep window reveals, real-scale mullions, balcony/guardrail details where appropriate, corner-return continuity, "
        f"subtle shadow gaps, parapet coping, and material hierarchy; avoid generic pasted windows; "
        f"the result should look like a photorealistic finished building material study, not a diagram, "
        f"orthographic elevation board, illustration, line drawing, or texture sample."
    )
    negative_prompt = (
        "changed massing, extra floors, extra towers, different footprint, distorted perspective, "
        "floating elements, impossible structure, facade outside silhouette, illegal overhangs, text labels, watermark, "
        "cartoon render, flat wallpaper texture, repeated identical window stickers, collage, orange massing diagram, "
        "white margins, sheet borders, panel labels, elevation drawing, architectural presentation board"
    )
    return {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "style_hint": style_hint,
        "constraints": {
            "lock_silhouette": True,
            "lock_height_m": metrics.get("height_m"),
            "lock_num_floors": metrics.get("num_floors"),
            "lock_mass_shape": candidate.get("mass_shape"),
        },
    }


__all__ = ["BUILDING_TYPE_STYLE_HINTS", "build_facade_prompt"]
