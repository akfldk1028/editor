"""Geometry-native quality evidence for distinct architectural languages.

The image critic may call every rectilinear proposal a box, while a coherent
stepped section or a two-wing bridge is legitimately rectilinear.  Conversely,
an architectural label must not rescue arbitrary cuboids.  These evaluators
measure the executable source geometry and expose why a language is legible.
They contain no parcel coordinates and no named-building templates.
"""

from __future__ import annotations

from math import sqrt
from statistics import mean
from typing import Any

from backend.app.modules.design.generation.maas.program_massing.geometry_safety import safe_unary_union


def assess_language_geometry(source: Any, feature: dict[str, Any], language_group: str) -> dict[str, Any]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    signature = props.get("source_signature") if isinstance(props.get("source_signature"), dict) else {}
    coherence = signature.get("coherence_evidence") if isinstance(signature.get("coherence_evidence"), dict) else {}
    spatial = props.get("program_spatial_evidence") if isinstance(props.get("program_spatial_evidence"), dict) else {}
    projection = spatial.get("spatial_role_projection") if isinstance(spatial.get("spatial_role_projection"), dict) else {}
    volumes = list(getattr(source, "volumes", ()) or ())
    common_pass = (
        bool(coherence.get("hard_pass"))
        and int(coherence.get("small_fragment_count") or 0) <= 1
        and int(coherence.get("redundant_overlap_pair_count") or 0) == 0
        and float(coherence.get("collision_energy") or 0.0) <= 0.08
        and 1 <= len(volumes) <= 4
    )
    evidence: dict[str, Any] = {
        "schema_version": "arr.maas.language_geometry_quality.v1",
        "language_group": language_group,
        "common_clean_pass": common_pass,
        "volume_count": len(volumes),
        "geometry_pass": False,
        "quality_score": 0.0,
    }
    if not common_pass:
        evidence["failure"] = "common_clean_mass_gate"
        return evidence

    if language_group == "continuous_field":
        surface = signature.get("continuous_surface_evidence") if isinstance(signature.get("continuous_surface_evidence"), dict) else {}
        passed = bool(surface.get("hard_pass")) and int(surface.get("profiled_volume_count") or 0) >= 1
        evidence.update({
            "profiled_volume_count": int(surface.get("profiled_volume_count") or 0),
            "geometry_pass": passed,
            "quality_score": 0.92 if passed else 0.0,
        })
        return evidence

    if language_group == "folded_section":
        surface = signature.get("continuous_surface_evidence") if isinstance(signature.get("continuous_surface_evidence"), dict) else {}
        profiled = bool(projection.get("profiled_roof_present")) or bool(surface.get("hard_pass"))
        section_levels = int(projection.get("section_level_count") or projection.get("height_level_count") or 0)
        section_field = surface.get("section_field") if isinstance(surface.get("section_field"), dict) else {}
        section_height_range = float(section_field.get("section_height_range") or 0.0)
        profile_total_variation = float(section_field.get("profile_total_variation") or 0.0)
        max_segment_slope = float(section_field.get("max_normalized_segment_slope") or 0.0)
        agent_loft_pass = (
            surface.get("representation") == "agent_section_loft_quad_mesh"
            and int(section_field.get("section_control_point_count") or 0) >= 4
            and section_height_range >= 0.18
            and profile_total_variation <= 2.40
            and max_segment_slope <= 4.50
            and int(surface.get("surface_count") or 0) <= 48
        )
        oblique_field = surface.get("oblique_field") if isinstance(surface.get("oblique_field"), dict) else {}
        agent_oblique_pass = (
            surface.get("representation") == "agent_oblique_envelope_mesh"
            and 3 <= int(oblique_field.get("plan_control_point_count") or 0) <= 8
            and float(oblique_field.get("oblique_displacement") or 0.0) >= 0.08
            and 0.18 <= float(oblique_field.get("proxy_area_ratio") or 0.0) <= 1.0
            and int(surface.get("surface_count") or 0) <= 48
        )
        passed = profiled and (section_levels >= 2 or agent_loft_pass or agent_oblique_pass)
        evidence.update({
            "profiled_surface": profiled,
            "section_level_count": section_levels,
            "agent_section_loft_pass": agent_loft_pass,
            "agent_oblique_envelope_pass": agent_oblique_pass,
            "oblique_displacement": round(float(oblique_field.get("oblique_displacement") or 0.0), 4),
            "section_height_range": round(section_height_range, 4),
            "profile_total_variation": round(profile_total_variation, 4),
            "max_normalized_segment_slope": round(max_segment_slope, 4),
            "geometry_pass": passed,
            "quality_score": 0.90 if passed else 0.0,
        })
        return evidence

    if language_group == "stepped_capacity":
        return _assess_stepped(volumes, evidence)

    if language_group == "bridge_interlock":
        return _assess_bridge(volumes, evidence)

    if language_group == "carved_void":
        hole_count = sum(len(volume.footprint.interiors) for volume in volumes)
        void_ratio = float(projection.get("envelope_void_ratio") or 0.0)
        dominant_ratio = float(spatial.get("dominant_component_ratio") or 0.0)
        passed = (hole_count >= 1 or void_ratio >= 0.10) and dominant_ratio >= 0.34
        evidence.update({
            "hole_count": hole_count,
            "envelope_void_ratio": round(void_ratio, 4),
            "dominant_component_ratio": round(dominant_ratio, 4),
            "geometry_pass": passed,
            "quality_score": round(min(0.90, 0.62 + void_ratio * 0.9 + min(hole_count, 1) * 0.12), 4) if passed else 0.0,
        })
        return evidence

    if language_group == "cluster_field":
        union = safe_unary_union([volume.footprint for volume in volumes])
        component_count = len(getattr(union, "geoms", (union,))) if union is not None else 0
        areas = [float(volume.footprint.area) for volume in volumes]
        dominant = max(areas, default=0.0) / max(sum(areas), 1e-9)
        mean_area = mean(areas) if areas else 0.0
        area_spread = (
            (max(areas) - min(areas)) / max(mean_area, 1e-9)
            if len(areas) >= 2
            else 0.0
        )
        envelope_area = float(union.envelope.area) if union is not None and not union.is_empty else 0.0
        open_space_ratio = 1.0 - float(union.area) / max(envelope_area, 1e-9) if union is not None else 0.0
        nearest_gaps: list[float] = []
        normalization = max(sqrt(sum(areas)), 1e-9)
        for index, volume in enumerate(volumes):
            other_distances = [
                float(volume.footprint.distance(other.footprint))
                for other_index, other in enumerate(volumes)
                if other_index != index
            ]
            if other_distances:
                nearest_gaps.append(min(other_distances) / normalization)
        mean_nearest_gap = mean(nearest_gaps) if nearest_gaps else 1.0
        # A field is not merely three detached equal boxes.  It needs a
        # readable shared open-space figure, local adjacency, and at least a
        # small hierarchy between its pieces.  This implements the authored
        # reference brief's explicit rejection of uniform repetition.
        passed = (
            3 <= len(volumes) <= 4
            and component_count >= 3
            and 0.22 <= dominant <= 0.58
            and 0.16 <= open_space_ratio <= 0.78
            and mean_nearest_gap <= 0.32
            and area_spread >= 0.08
        )
        evidence.update({
            "plan_component_count": component_count,
            "dominant_volume_ratio": round(dominant, 4),
            "open_space_ratio": round(open_space_ratio, 4),
            "mean_normalized_nearest_gap": round(mean_nearest_gap, 4),
            "normalized_component_area_spread": round(area_spread, 4),
            "geometry_pass": passed,
            "quality_score": 0.82 if passed else 0.0,
        })
        return evidence

    evidence.update({"geometry_pass": True, "quality_score": 0.68, "calm_anchor": True})
    return evidence


def _assess_stepped(volumes: list[Any], evidence: dict[str, Any]) -> dict[str, Any]:
    ordered = sorted(volumes, key=lambda item: (float(item.bottom_fraction), float(item.top_fraction)))
    level_count = len({round(float(item.top_fraction), 2) for item in ordered})
    overlaps: list[float] = []
    upward_area_checks: list[bool] = []
    area_changes: list[float] = []
    shifts: list[float] = []
    for lower, upper in zip(ordered, ordered[1:]):
        lower_area = max(float(lower.footprint.area), 1e-9)
        upper_area = max(float(upper.footprint.area), 1e-9)
        overlaps.append(float(lower.footprint.intersection(upper.footprint).area) / min(lower_area, upper_area))
        upward_area_checks.append(upper_area <= lower_area * 1.18)
        area_changes.append(abs(upper_area - lower_area) / max(lower_area, upper_area))
        scale = max(sqrt(lower_area), 1e-9)
        shifts.append(float(lower.footprint.centroid.distance(upper.footprint.centroid)) / scale)
    overlap_mean = mean(overlaps) if overlaps else 0.0
    monotonic_ratio = mean(1.0 if value else 0.0 for value in upward_area_checks) if upward_area_checks else 0.0
    max_shift = max(shifts, default=0.0)
    max_area_change = max(area_changes, default=0.0)
    sectional_progression = max_shift >= 0.045 or max_area_change >= 0.10
    passed = (
        level_count >= 2
        and overlap_mean >= 0.48
        and monotonic_ratio >= 0.50
        and max_shift <= 0.72
        and sectional_progression
    )
    score = min(0.92, 0.45 + overlap_mean * 0.25 + monotonic_ratio * 0.15 + min(level_count, 3) * 0.04) if passed else 0.0
    evidence.update({
        "height_level_count": level_count,
        "adjacent_plan_overlap_mean": round(overlap_mean, 4),
        "upward_area_monotonic_ratio": round(monotonic_ratio, 4),
        "maximum_normalized_centroid_shift": round(max_shift, 4),
        "maximum_normalized_area_change": round(max_area_change, 4),
        "sectional_progression": sectional_progression,
        "geometry_pass": passed,
        "quality_score": round(score, 4),
    })
    return evidence


def _assess_bridge(volumes: list[Any], evidence: dict[str, Any]) -> dict[str, Any]:
    connectors = [
        volume for volume in volumes
        if "connector" in str(volume.role).lower()
        or "bridge" in str(volume.role).lower()
        or str(getattr(volume, "verb", "")).lower() in {"bridge", "diagonal_connect"}
    ]
    bodies = [volume for volume in volumes if volume not in connectors]
    elevated = [volume for volume in connectors if float(volume.bottom_fraction) >= 0.30]
    body_union = safe_unary_union([volume.footprint for volume in bodies])
    body_components = len(getattr(body_union, "geoms", (body_union,))) if body_union is not None else 0
    connector_touch_count = 0
    if connectors and bodies:
        connector_touch_count = max(
            sum(1 for body in bodies if connector.footprint.buffer(0.05).intersects(body.footprint))
            for connector in connectors
        )
    interlock_pairs = 0
    for index, left in enumerate(bodies):
        for right in bodies[:index]:
            overlap = float(left.footprint.intersection(right.footprint).area) / max(
                min(float(left.footprint.area), float(right.footprint.area)), 1e-9
            )
            vertically_related = (
                float(left.bottom_fraction) <= float(right.top_fraction) + 0.08
                and float(right.bottom_fraction) <= float(left.top_fraction) + 0.08
            )
            if 0.08 <= overlap <= 0.82 and vertically_related:
                interlock_pairs += 1
    explicit_bridge_pass = bool(elevated) and len(bodies) >= 2 and (body_components >= 2 or connector_touch_count >= 2)
    authored_interlock = any(str(getattr(volume, "verb", "")).lower() == "interlock" for volume in bodies)
    passed = explicit_bridge_pass or (authored_interlock and len(bodies) >= 2 and interlock_pairs >= 1)
    evidence.update({
        "connector_count": len(connectors),
        "elevated_connector_count": len(elevated),
        "body_count": len(bodies),
        "body_plan_component_count": body_components,
        "connector_touch_count": connector_touch_count,
        "interlock_pair_count": interlock_pairs,
        "explicit_bridge_pass": explicit_bridge_pass,
        "geometry_pass": passed,
        "quality_score": 0.86 if passed else 0.0,
    })
    return evidence


__all__ = ["assess_language_geometry"]
