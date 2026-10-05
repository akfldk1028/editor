"""Program-neutral creative mass seeds and form-quality evidence."""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.grammar.sequence_library import SEQUENCES
from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbSequence

from backend.app.modules.design.generation.maas.program_massing.graph_composer import composed_creative_graphs
from backend.app.modules.design.generation.maas.program_massing.geometry_safety import repaired_volume_records, safe_unary_union


def creative_seed_sequences() -> tuple[VerbSequence, ...]:
    """Return program-neutral operation graphs, never renamed housing assemblies.

    The former implementation copied ``program_housing_*`` component templates.
    That made a nominally creative search mutate coordinates of the same family of
    rectangular assemblies.  The neutral archive now starts from the formal MassDSL
    operation graphs (cut, court, bend, bridge, terrace, section and roof operations).
    """
    seeds: list[VerbSequence] = []
    for sequence in SEQUENCES:
        seeds.append(VerbSequence(
            name=sequence.name.replace("grammar_", "creative_graph_", 1),
            label=sequence.label,
            calls=sequence.calls,
            notes=(
                "stage=creative_form_exploration",
                "program_projection=pending",
                "legal_parking_projection=pending",
                "parameter_source=formal_massdsl_operation_graph",
                f"source_sequence={sequence.name}",
            ),
        ))
    seeds.extend(composed_creative_graphs())
    return tuple(seeds)


def attach_creative_mass_evidence(feature: dict[str, Any], *, site_area_m2: float) -> dict[str, Any]:
    """Score form coherence and legibility before any building-use projection."""
    props = feature.setdefault("properties", {})
    repaired = repaired_volume_records(feature)
    records = [record for record, _ in repaired]
    geometries = [geometry for _, geometry in repaired]
    areas = [float(item.area) for item in geometries]
    total_area = sum(areas)
    union = safe_unary_union(geometries)
    union_area = float(union.area) if union is not None and not union.is_empty else 0.0
    coverage = union_area / max(float(site_area_m2), 1e-9)
    dominant = max(areas, default=0.0) / max(total_area, 1e-9)
    top_levels = {round(float(item.get("top_height") or 0.0), 2) for item in records}
    bottom_levels = {round(float(item.get("bottom_height") or 0.0), 2) for item in records}

    signature = props.get("source_signature") if isinstance(props.get("source_signature"), dict) else {}
    coherence = signature.get("coherence_evidence") if isinstance(signature.get("coherence_evidence"), dict) else {}
    ambition = signature.get("architectural_ambition_evidence") if isinstance(signature.get("architectural_ambition_evidence"), dict) else {}
    coherence_score = float(coherence.get("score") or 0.0)
    hierarchy_score = min(1.0, max(0.0, (len(top_levels) - 1) * 0.38 + (0.24 if len(bottom_levels) > 1 else 0.0)))
    dominance_score = _range_score(dominant, (0.24, 0.68))
    coverage_score = _range_score(coverage, (0.18, 0.76))
    silhouette_score = max(0.0, min(1.0, float(ambition.get("silhouette_strength") or 0.65)))
    surface_count = int(signature.get("surface_count") or 0)
    volume_count = len(records)
    roles = [str(item.get("role") or "") for item in records]
    uses_buffered_path = any("ribbon" in role for role in roles)
    effective_surface_count = int(signature.get("effective_surface_count") or (min(surface_count, volume_count * 6) if uses_buffered_path else surface_count))
    economy_score = max(0.0, min(1.0, 1.0 - max(0, effective_surface_count - 24) / 48.0))
    surface_summary = (
        props.get("source_surface_summary")
        if isinstance(props.get("source_surface_summary"), dict)
        else {}
    )
    profiled_roof_count = sum(
        1 for item in props.get("source_surfaces") or []
        if isinstance(item, dict) and str(item.get("surface_type") or "").startswith("profiled_")
        and "roof" in str(item.get("surface_type") or "")
    )
    if not isinstance(props.get("source_surfaces"), list):
        profiled_roof_count = int(
            surface_summary.get("profiled_roof_count") or 0
        )
    non_rectilinear_volume_count = sum(
        1
        for geometry in geometries
        if hasattr(geometry, "exterior") and len(list(geometry.exterior.coords)) - 1 > 5
    )
    # A clipped rectangle can acquire six or more vertices, so vertex count is
    # diagnostic only.  Do not call that sculptural.  This stricter archive
    # signal requires an authored continuous/branching/folded family or an
    # explicit profiled surface.
    continuous = signature.get("continuous_surface_evidence") if isinstance(signature.get("continuous_surface_evidence"), dict) else {}
    continuous_principle = str(continuous.get("principle") or "")
    sculptural_geometry = bool(
        continuous.get("hard_pass")
        and profiled_roof_count > 0
        and continuous_principle in {
            "continuous_ribbon_field",
            "folded_section",
            "terraced_ribbon_section",
            # A torqued stack is emitted as multiple authored profiled roof
            # plates, not as clipped rectangular proxy noise. It is one of
            # the explicit rotated/overlapping architectural mass languages
            # and must contribute to the sculptural archive supply.
            "torqued_stack",
        }
    )
    interlock_pair_count = 0
    for left_index, left in enumerate(records):
        left_geometry = geometries[left_index]
        left_bottom = float(left.get("bottom_height") or 0.0)
        left_top = float(left.get("top_height") or 0.0)
        for right_index in range(left_index + 1, len(records)):
            right = records[right_index]
            right_geometry = geometries[right_index]
            right_bottom = float(right.get("bottom_height") or 0.0)
            right_top = float(right.get("top_height") or 0.0)
            plan_touch = left_geometry.buffer(0.15).intersects(right_geometry.buffer(0.15))
            section_touch = min(left_top, right_top) >= max(left_bottom, right_bottom) - 0.25
            if plan_touch and section_touch:
                interlock_pair_count += 1
    reference_expression_score = (
        min(1.0, profiled_roof_count / 8.0) if uses_buffered_path else (
            min(1.0, interlock_pair_count / 4.0) if any("voxel" in role for role in roles) else 0.65
        )
    )
    score = (
        coherence_score * 0.30
        + hierarchy_score * 0.19
        + dominance_score * 0.17
        + coverage_score * 0.13
        + silhouette_score * 0.13
        + economy_score * 0.05
        + reference_expression_score * 0.03
    )
    small_fragments = int(coherence.get("small_fragment_count") or 0)
    plan_components = int(coherence.get("plan_component_count") or 0)
    hard_pass = bool(
        coherence.get("hard_pass", False)
        and 2 <= volume_count <= 5
        and effective_surface_count <= 48
        and small_fragments <= 1
        and plan_components <= 3
        and hierarchy_score >= 0.35
        and coverage >= 0.08
        and coverage <= 0.88
    )
    evidence = {
        "schema_version": "arr.maas.creative_mass_evidence.v1",
        "stage": "creative_form_exploration",
        "program_conditioned": False,
        "legal_parking_checked": False,
        "creative_score": round(max(0.0, min(1.0, score)), 3),
        "hard_pass": hard_pass,
        "volume_count": volume_count,
        "surface_count": surface_count,
        "effective_surface_count": effective_surface_count,
        "surface_complexity_basis": "logical_buffered_path" if uses_buffered_path else "raw_mesh",
        "small_fragment_count": small_fragments,
        "plan_component_count": plan_components,
        "dominant_component_ratio": round(dominant, 3),
        "dominance_score": round(dominance_score, 3),
        "site_coverage_ratio": round(coverage, 3),
        "coverage_score": round(coverage_score, 3),
        "height_level_count": len(top_levels),
        "section_level_count": len(bottom_levels),
        "hierarchy_score": round(hierarchy_score, 3),
        "coherence_score": round(coherence_score, 3),
        "silhouette_score": round(silhouette_score, 3),
        "surface_economy_score": round(economy_score, 3),
        "profiled_roof_strip_count": profiled_roof_count,
        "non_rectilinear_volume_count": non_rectilinear_volume_count,
        "sculptural_geometry": sculptural_geometry,
        "interlock_pair_count": interlock_pair_count,
        "reference_expression_score": round(reference_expression_score, 3),
    }
    props["creative_mass_evidence"] = evidence
    return evidence


def _range_score(value: float, target: tuple[float, float]) -> float:
    low, high = target
    if low <= value <= high:
        center = (low + high) / 2.0
        half = max((high - low) / 2.0, 1e-9)
        return max(0.72, 1.0 - abs(value - center) / half * 0.28)
    distance = low - value if value < low else value - high
    return max(0.0, 0.72 - distance * 3.0)


__all__ = ["attach_creative_mass_evidence", "creative_seed_sequences"]
