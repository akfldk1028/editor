"""Select facade intentions from evaluated MASS geometry.

This module deliberately emits material and opening intent only.  It never
authors vertices, world coordinates, parcel coordinates, or replacement mass
dimensions.
"""

from __future__ import annotations

from typing import Any, Mapping


def select_facade_strategy(program: Any, compilation: Any) -> dict[str, Any]:
    """Return one deterministic, geometry-preserving facade strategy."""

    metrics = dict(getattr(compilation, "metrics", {}) or {})
    bounds = metrics.get("bounds")
    if not isinstance(bounds, list) or len(bounds) != 2:
        raise ValueError("facade strategy requires evaluated MASS bounds")
    minimum, maximum = bounds
    spans = [
        max(1e-9, float(maximum[index]) - float(minimum[index]))
        for index in range(3)
    ]
    width, depth, height = spans
    plan_long = max(width, depth)
    plan_short = max(1e-9, min(width, depth))
    slenderness = height / plan_short
    elongation = plan_long / plan_short
    height_to_long_side = height / max(plan_long, 1e-9)
    operators = tuple(
        str(getattr(node, "operator", "") or "").lower()
        for node in getattr(program, "nodes", ()) or ()
    )
    metadata = getattr(program, "metadata", {}) or {}
    family = str(metadata.get("family") or getattr(program, "name", "")).lower()
    cues = set(operators)
    cue_text = " ".join((family, *operators))

    if {"taper", "twist"} & cues or "tower" in cue_text or slenderness >= 1.6:
        strategy_id = "vertical-fins-glass"
        primary_system = "high-performance glass with vertical metal fins"
        rhythm = "vertical floor-to-floor bays with denser solar-control fins"
        opening_logic = "continuous vision zones aligned to measured floor guides"
    elif {"carve_void", "difference", "inscribe"} & cues or "courtyard" in cue_text:
        strategy_id = "mineral-reveal-courtyard"
        primary_system = "deep mineral reveals with recessed courtyard glazing"
        rhythm = "calm punched openings outside and more transparent court-facing bays"
        opening_logic = "protect solid corners and intensify openings toward internal voids"
    elif {"bend", "sweep"} & cues or "curved" in cue_text:
        strategy_id = "curved-unitized-glass"
        primary_system = "unitized glazing with slim curved metal fins"
        rhythm = "continuous bays following the evaluated curved silhouette"
        opening_logic = "tangent-aligned modules with consistent corner returns"
    elif {"stack", "setback", "terrace"} & cues or "stepped" in cue_text:
        strategy_id = "horizontal-shading-terrace"
        primary_system = "terracotta spandrels with horizontal shading"
        rhythm = "floor-banded bays that terminate cleanly at every setback"
        opening_logic = "recessed glazing below terrace slabs and solid parapet zones"
    elif {"lodge", "attach", "attach_volume"} & cues or "attachment" in cue_text:
        strategy_id = "perforated-metal-attachment"
        primary_system = "perforated metal screens over a glazed secondary skin"
        rhythm = "host bays remain regular while attached volumes receive finer modules"
        opening_logic = "align attachment openings to host floor guides"
    elif {"split", "bridge"} & cues or "split" in cue_text or "bridge" in cue_text:
        strategy_id = "hybrid-bridge-facade"
        primary_system = "exposed concrete frames with high-performance bridge glazing"
        rhythm = "distinct wing grids tied by a lighter transparent connector"
        opening_logic = "retain solid transfer zones at bridge bearings"
    elif {"shear", "slice", "clip", "cut_corner"} & cues or "diagonal" in cue_text:
        strategy_id = "oblique-precast-metal"
        primary_system = "precast panels with folded metal at oblique edges"
        rhythm = "orthogonal window bays clipped only by the evaluated diagonal boundary"
        opening_logic = "keep cut edges solid and step glazing away from acute corners"
    elif "profile" in cue_text or elongation >= 2.2:
        strategy_id = "linear-translucent-span"
        primary_system = "translucent panels with expressed long-span metal frames"
        rhythm = "long-axis structural bays with controlled daylight strips"
        opening_logic = "continuous clerestories between measured frame lines"
    else:
        strategy_id = "balanced-hybrid"
        primary_system = "exposed concrete and high-performance punched glazing"
        rhythm = "balanced horizontal floor datums and vertical structural bays"
        opening_logic = "recessed openings sized from facade aspect ratios"

    height_profile = (
        "single_storey_low"
        if height_to_long_side < 0.35
        else "mid_rise"
        if height_to_long_side < 1.2
        else "tower"
    )
    return {
        "schema_version": "arr.elevation_agent.facade_strategy.v1",
        "strategy_id": strategy_id,
        "primary_system": primary_system,
        "rhythm": rhythm,
        "opening_logic": opening_logic,
        "measured_features": {
            "plan_elongation": round(elongation, 6),
            "height_to_short_side": round(slenderness, 6),
            "height_to_long_side": round(height_to_long_side, 6),
            "height_profile": height_profile,
            "surface_area": round(float(metrics.get("surface_area") or 0.0), 6),
            "component_count": int(metrics.get("component_count") or 0),
        },
        "operator_path": list(operators),
        "parameter_space": "evaluated_mass_metrics_and_face_local_coordinates",
        "geometry_mutation_allowed": False,
    }


__all__ = ["select_facade_strategy"]
