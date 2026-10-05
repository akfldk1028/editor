"""Project anonymous source geometry into program-relevant spatial roles.

The source compiler deliberately describes formal operations (bend, court,
fold, terrace).  Program evaluation must not require those volumes to carry a
small, pre-agreed list of role names: that collapses an open language archive
back onto a few hand-authored seeds.  This module derives roles from geometry
and section relations, so reference/VLM-authored graphs remain evaluable.
"""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.program_massing.geometry_safety import repaired_volume_records, safe_unary_union


def _sectioned_plan_void_ratio(records, geometries) -> float:
    """Open share of the plan, averaged over the building's own level bands.

    At each band the section is the union of the volumes that span it, and the
    open share is measured against that section's own minimum rotated rectangle
    - the tightest rectangle rather than the axis-aligned one, so a rotated
    solid reads 0.000 at every angle instead of rising with orientation alone.
    """

    levels = sorted(
        {
            round(float(item.get(key) or 0.0), 2)
            for item in records
            for key in ("bottom_height", "top_height")
        }
    )
    if len(levels) < 2:
        return 0.0

    weighted = 0.0
    thickness_total = 0.0
    for lower, upper in zip(levels, levels[1:]):
        thickness = upper - lower
        if thickness <= 1e-9:
            continue
        middle = (lower + upper) / 2.0
        section = safe_unary_union([
            geometry
            for item, geometry in zip(records, geometries)
            if float(item.get("bottom_height") or 0.0) - 1e-9 <= middle
            <= float(item.get("top_height") or 0.0) + 1e-9
        ])
        if section is None or section.is_empty:
            continue
        tightest = section.minimum_rotated_rectangle
        if tightest is None or float(tightest.area) <= 0.0:
            continue
        weighted += thickness * max(
            0.0, 1.0 - float(section.area) / float(tightest.area)
        )
        thickness_total += thickness

    return weighted / thickness_total if thickness_total > 0.0 else 0.0


def project_spatial_roles(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    repaired = repaired_volume_records(feature)
    records = [record for record, _ in repaired]
    geometries = [geometry for _, geometry in repaired]
    areas = [float(geometry.area) for geometry in geometries]
    total = sum(areas)
    primary_index = max(range(len(areas)), key=areas.__getitem__) if areas else None
    grounded = [
        index for index, item in enumerate(records)
        if float(item.get("bottom_height") or 0.0) <= 0.02
    ]
    significant_grounded = [index for index in grounded if areas[index] / max(total, 1e-9) >= 0.10]
    top_levels = {round(float(item.get("top_height") or 0.0), 2) for item in records}
    bottom_levels = {round(float(item.get("bottom_height") or 0.0), 2) for item in records}
    union = safe_unary_union(geometries)
    envelope_void_ratio = 0.0
    plan_void_ratio = 0.0
    if union is not None and not union.is_empty and union.envelope.area > 0:
        envelope_void_ratio = max(0.0, 1.0 - float(union.area) / float(union.envelope.area))
    # `envelope` is the axis-aligned bounding box, so the ratio above rises with
    # rotation alone: a solid box with no void at all reads 0.351 at 15 degrees,
    # 0.484 at 30 and 0.520 at 45. Measured across one archive the values sat
    # between 0.377 and 0.674 with a median of 0.487 - which is what a rotated
    # rectangle gives, not what a courtyard gives. It was measuring orientation.
    #
    # The tightest rectangle around the mass removes that: a rotated solid reads
    # 0.000 at every angle, and what remains is the share of its own figure the
    # building leaves open. Kept as a separate field because the two thresholds
    # that already consume envelope_void_ratio were calibrated against the
    # contaminated number, and silently re-pointing them would change gate
    # behaviour that has not been measured.
    # Measured section by section rather than as one flattened union. Unioning
    # every volume regardless of height is the same mistake as unioning every
    # triangle of a mesh: whatever sits above an opening closes it again. On a
    # 40x24x18 reference solid at their strongest settings, carve, grade, notch,
    # fracture and extract all read 0.000 flattened - the axis could not see
    # five of the ten operatives - while their sections read 0.322, 0.555,
    # 0.245, 0.144 and 0.314. The bands come from the volumes' own level
    # boundaries, so nothing is sampled at a guessed height, and each band's
    # share is weighted by its thickness so a thin one cannot dominate.
    plan_void_ratio = _sectioned_plan_void_ratio(records, geometries)
    non_rectilinear = sum(
        1 for geometry in geometries
        if hasattr(geometry, "exterior") and len(list(geometry.exterior.coords)) - 1 > 5
    )
    surface_summary = (
        props.get("source_surface_summary")
        if isinstance(props.get("source_surface_summary"), dict)
        else {}
    )
    profiled_roof = any(
        isinstance(item, dict) and "roof" in str(item.get("surface_type") or "")
        and str(item.get("surface_type") or "").startswith("profiled_")
        for item in props.get("source_surfaces") or []
    ) or int(surface_summary.get("profiled_roof_count") or 0) > 0
    # A public spatial gesture is measurable as a court/canyon in plan, a
    # legible sectional hierarchy, or a deliberately profiled/non-rectilinear
    # envelope.  No topology or volume-name whitelist is involved.
    public_gesture = bool(
        envelope_void_ratio >= 0.12
        or len(top_levels) >= 2
        or len(bottom_levels) >= 2
        or profiled_roof
        or non_rectilinear > 0
    )
    return {
        "schema_version": "arr.maas.spatial_role_projection.v1",
        "method": "geometry_relations_not_role_names",
        "primary_component_index": primary_index,
        "primary_mass_present": primary_index is not None,
        "grounded_component_indices": grounded,
        "active_ground_mass_present": bool(significant_grounded),
        "secondary_mass_present": len(records) >= 2,
        "public_spatial_gesture_present": public_gesture,
        "envelope_void_ratio": round(envelope_void_ratio, 3),
        "plan_void_ratio": round(plan_void_ratio, 3),
        "plan_void_ratio_basis": "open_share_of_minimum_rotated_rectangle",
        "height_level_count": len(top_levels),
        "section_level_count": len(bottom_levels),
        "non_rectilinear_component_count": non_rectilinear,
        "profiled_roof_present": profiled_roof,
    }


__all__ = ["project_spatial_roles"]
