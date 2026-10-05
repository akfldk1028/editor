"""Generator-independent geometric coherence objective for MAAS masses."""

from __future__ import annotations

from math import sqrt
from typing import Any

from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.source_geometry.ir import SourceVolume
from backend.app.modules.design.generation.maas.source_geometry.polygon_quality import evaluate_polygon_quality


COHERENCE_SCHEMA_VERSION = "arr.maas.mass_coherence.v2"


def evaluate_source_volume_coherence(volumes: tuple[SourceVolume, ...]) -> dict[str, Any]:
    if not volumes:
        return {"schema_version": COHERENCE_SCHEMA_VERSION, "status": "missing", "score": 0.0, "hard_pass": False}
    source_volumes = volumes
    floorwise_quality = all(
        str(volume.verb) == "floorwise_legal_matrix4"
        for volume in source_volumes
    )
    volumes = _typed_components(source_volumes)
    quality_volumes = source_volumes if floorwise_quality else volumes
    areas = [max(float(volume.footprint.area), 1e-9) for volume in volumes]
    continuous_field = all(
        "continuous_ribbon_lane" in str(volume.role) or "branched_ribbon" in str(volume.role)
        for volume in volumes
    )
    unit_volumes = tuple(
        volume for volume in volumes if "_unit_" in str(volume.role).lower()
    )
    # A graph-authored array is allowed to be a field of separate buildings,
    # but only when every visible component is one of 3--4 comparable typed
    # units.  This cannot excuse a small detached annex or an arbitrary Lego
    # fragment because mixed roles, a fifth body, or a weak area hierarchy all
    # disable the exception.
    intentional_cluster = (
        3 <= len(volumes) <= 4
        and len(unit_volumes) == len(volumes)
        and min(areas) / max(areas) >= 0.45
        and max(volume.bottom_fraction for volume in volumes)
            - min(volume.bottom_fraction for volume in volumes) <= 0.02
        and max(volume.top_fraction for volume in volumes)
            - min(volume.top_fraction for volume in volumes) <= 0.30
    )
    component_allowance = 4 if intentional_cluster else (3 if continuous_field else 2)

    def is_linear_architectural_role(volume: SourceVolume) -> bool:
        role = str(volume.role).lower()
        return any(token in role for token in (
            "ribbon", "bridge", "connector", "spine", "ramp", "program_section_band",
        ))

    polygon_evidence = []
    for volume in quality_volumes:
        quality_polygon, normalization = _coherence_quality_polygon(volume)
        evidence = evaluate_polygon_quality(
            quality_polygon,
            # A bridge or ribbon is intentionally linear; judging it with the
            # compact-monolith perimeter limit rejects even a clean rectangle.
            # Hairline width and overlap remain independent hard gates.
            linear_field=is_linear_architectural_role(volume),
        )
        evidence["proxy_tessellation_normalization"] = normalization
        polygon_evidence.append(evidence)
    polygon_failure_count = sum(1 for evidence in polygon_evidence if not evidence["hard_pass"])
    total_area = max(sum(areas), 1e-9)
    main_ratio = max(areas) / total_area
    redundant_pairs = 0
    collision_energy = 0.0
    for index, left in enumerate(volumes):
        left_height = max(float(left.top_fraction - left.bottom_fraction), 1e-9)
        for right in volumes[:index]:
            vertical = max(
                0.0,
                min(left.top_fraction, right.top_fraction) - max(left.bottom_fraction, right.bottom_fraction),
            ) / min(left_height, max(float(right.top_fraction - right.bottom_fraction), 1e-9))
            if vertical <= 0.0:
                continue
            planar = float(left.footprint.intersection(right.footprint).area) / min(
                max(float(left.footprint.area), 1e-9), max(float(right.footprint.area), 1e-9)
            )
            occupancy = vertical * planar
            collision_energy += max(0.0, occupancy - 0.28)
            if occupancy >= 0.58:
                redundant_pairs += 1
    connected = unary_union([volume.footprint.buffer(0.12) for volume in volumes])
    component_count = len(getattr(connected, "geoms", (connected,)))
    spatial_connectivity = _spatial_connectivity(volumes)
    spatial_component_count = int(spatial_connectivity["component_count"])
    fragment_count = sum(1 for area in areas if area < max(areas) * 0.16 and area < total_area * 0.10)
    complexity = max(0, len(volumes) - 5)
    hierarchy_penalty = max(0.0, 0.26 - main_ratio) * 2.0
    effective_spatial_component_count = 1 if intentional_cluster else spatial_component_count
    energy = (
        collision_energy * 0.42
        + redundant_pairs * 0.18
        + max(0, component_count - component_allowance) * 0.22
        + max(0, effective_spatial_component_count - 1) * 0.35
        + fragment_count * 0.16
        + complexity * 0.20
        + hierarchy_penalty
        + polygon_failure_count * 0.30
    )
    score = max(0.0, min(1.0, 1.0 - energy))
    hard_pass = (
        len(volumes) <= 5
        and redundant_pairs <= 1
        and component_count <= component_allowance
        and effective_spatial_component_count == 1
        and fragment_count <= 1
        and polygon_failure_count == 0
        and score >= 0.62
    )
    return {
        "schema_version": COHERENCE_SCHEMA_VERSION,
        "status": "measured",
        "score": round(score, 3),
        "hard_pass": hard_pass,
        "volume_count": len(volumes),
        "main_mass_area_ratio": round(main_ratio, 3),
        "redundant_overlap_pair_count": redundant_pairs,
        "collision_energy": round(collision_energy, 3),
        "plan_component_count": component_count,
        "spatial_component_count": spatial_component_count,
        "spatial_connectivity": spatial_connectivity,
        "small_fragment_count": fragment_count,
        "polygon_quality_hard_pass": polygon_failure_count == 0,
        "polygon_quality_failure_count": polygon_failure_count,
        "polygon_quality": polygon_evidence,
        "floorwise_quality_plate_count": (
            len(quality_volumes) if floorwise_quality else 0
        ),
        "floorwise_quality_uses_occupied_plates": floorwise_quality,
        "continuous_field_exception": continuous_field,
        "intentional_cluster_exception": intentional_cluster,
        "effective_spatial_component_count": effective_spatial_component_count,
        "plan_component_allowance": component_allowance,
    }


def _spatial_connectivity(volumes: tuple[SourceVolume, ...]) -> dict[str, Any]:
    """Measure whether every visible typed volume is physically attached.

    Plan union alone cannot distinguish a supported upper mass from a plate
    floating above the same footprint.  Two volumes therefore share an edge
    only when their plan regions touch and their normalized height intervals
    overlap or meet.  The small tolerances absorb kernel dust, not authored
    architectural gaps.
    """
    count = len(volumes)
    if count <= 1:
        return {
            "component_count": count,
            "edge_count": 0,
            "hard_pass": count == 1,
            "plan_contact_tolerance_m": 0.0,
            "vertical_contact_tolerance_fraction": 0.015,
            "weak_contact_count": 0,
            "weak_contacts": [],
        }
    plan_scale = sqrt(max(max(float(volume.footprint.area), 1e-9) for volume in volumes))
    plan_tolerance = max(0.03, min(0.18, plan_scale * 0.01))
    vertical_tolerance = 0.015
    adjacency: list[set[int]] = [set() for _ in volumes]
    edges: list[dict[str, Any]] = []
    weak_contacts: list[dict[str, Any]] = []
    for left_index, left in enumerate(volumes):
        for right_index in range(left_index):
            right = volumes[right_index]
            plan_gap = float(left.footprint.distance(right.footprint))
            vertical_gap = max(
                0.0,
                max(float(left.bottom_fraction), float(right.bottom_fraction))
                - min(float(left.top_fraction), float(right.top_fraction)),
            )
            if plan_gap > plan_tolerance or vertical_gap > vertical_tolerance:
                continue
            plan_intersection = float(left.footprint.intersection(right.footprint).area)
            minimum_plan_area = max(
                min(float(left.footprint.area), float(right.footprint.area)),
                1e-9,
            )
            vertical_overlap = (
                min(float(left.top_fraction), float(right.top_fraction))
                - max(float(left.bottom_fraction), float(right.bottom_fraction))
            )
            connector_contact = any(
                token in str(volume.role).lower()
                for volume in (left, right)
                for token in ("bridge", "connector")
            )
            if vertical_overlap <= vertical_tolerance:
                # Vertically stacked plates need a load-path-sized bearing
                # area. A single point or hairline wall touching a broad plate
                # is topologically connected but still reads as floating.
                contact_mode = "vertical_bearing"
                contact_strength = plan_intersection / minimum_plan_area
                minimum_contact_strength = 0.08
            else:
                # Side-by-side masses may meet along a real shared wall; an
                # area intersection is not required. Normalize shared wall
                # length by the smaller component's plan scale.
                contact_mode = "overlapping_height_or_shared_wall"
                shared_length = float(left.footprint.boundary.intersection(right.footprint.boundary).length)
                contact_strength = max(
                    plan_intersection / minimum_plan_area,
                    shared_length / max(sqrt(minimum_plan_area), 1e-9),
                )
                # A typed bridge is intentionally narrow at its landing. It
                # remains valid only if the graph connects it at both ends;
                # the component traversal below proves that relation. Keep
                # the ordinary shared-wall threshold for every non-connector
                # mass so point-contact plates remain rejected.
                minimum_contact_strength = 0.035 if connector_contact else 0.06
            contact_record = {
                "left_role": str(left.role),
                "right_role": str(right.role),
                "plan_gap_m": round(plan_gap, 4),
                "vertical_gap_fraction": round(vertical_gap, 4),
                "contact_mode": contact_mode,
                "contact_strength": round(contact_strength, 4),
                "minimum_contact_strength": minimum_contact_strength,
            }
            if contact_strength + 1e-9 < minimum_contact_strength:
                weak_contacts.append(contact_record)
                continue
            adjacency[left_index].add(right_index)
            adjacency[right_index].add(left_index)
            edges.append(contact_record)
    unseen = set(range(count))
    components: list[list[int]] = []
    while unseen:
        root = min(unseen)
        unseen.remove(root)
        component = [root]
        frontier = [root]
        while frontier:
            current = frontier.pop()
            for neighbour in adjacency[current]:
                if neighbour not in unseen:
                    continue
                unseen.remove(neighbour)
                component.append(neighbour)
                frontier.append(neighbour)
        components.append(component)
    return {
        "component_count": len(components),
        "edge_count": len(edges),
        "hard_pass": len(components) == 1,
        "plan_contact_tolerance_m": round(plan_tolerance, 4),
        "vertical_contact_tolerance_fraction": vertical_tolerance,
        "weak_contact_count": len(weak_contacts),
        "weak_contacts": weak_contacts,
        "components": [
            [str(volumes[index].role) for index in component]
            for component in components
        ],
        "contact_edges": edges,
    }


def _coherence_quality_polygon(volume: SourceVolume) -> tuple[Any, dict[str, Any]]:
    """Remove mesh-section subdivisions only from coherence measurement.

    The recursive compiler's legal proxy is cut from a manifold triangle
    mesh. A perfectly straight or smooth section therefore contains vertices
    at triangle boundaries that are not architectural corners. The exact
    proxy remains untouched for containment, BCR, FAR and parking; only this
    cloned polygon is simplified before short-edge/tortuosity scoring.
    """
    polygon = volume.footprint
    source_vertex_count = max(0, len(polygon.exterior.coords) - 1)
    quality_proxy_verb = str(volume.verb) in {
        "geometry_program",
        "floorwise_legal_matrix4",
    }
    if not quality_proxy_verb or source_vertex_count <= 12:
        return polygon, {
            "applied": False,
            "reason": "not_numeric_mesh_proxy_or_already_compact",
            "source_vertex_count": source_vertex_count,
            "evaluated_vertex_count": source_vertex_count,
            "source_geometry_unchanged": True,
        }
    scale = sqrt(max(float(polygon.area), 1e-9))
    simplified = polygon.simplify(scale * 0.006, preserve_topology=True)
    if simplified.is_empty or simplified.geom_type != "Polygon" or not simplified.is_valid:
        return polygon, {
            "applied": False,
            "reason": "topology_preserving_simplification_invalid",
            "source_vertex_count": source_vertex_count,
            "evaluated_vertex_count": source_vertex_count,
            "source_geometry_unchanged": True,
        }
    area_ratio = float(simplified.area) / max(float(polygon.area), 1e-9)
    if not 0.97 <= area_ratio <= 1.03:
        return polygon, {
            "applied": False,
            "reason": "quality_proxy_area_retention_below_97_percent",
            "source_vertex_count": source_vertex_count,
            "evaluated_vertex_count": source_vertex_count,
            "area_ratio": round(area_ratio, 6),
            "source_geometry_unchanged": True,
        }
    evaluated_vertex_count = max(0, len(simplified.exterior.coords) - 1)
    return simplified, {
        "applied": evaluated_vertex_count < source_vertex_count,
        "reason": "numeric_mesh_section_subdivision_removed",
        "source_vertex_count": source_vertex_count,
        "evaluated_vertex_count": evaluated_vertex_count,
        "area_ratio": round(area_ratio, 6),
        "source_geometry_unchanged": True,
    }


def _typed_components(volumes: tuple[SourceVolume, ...]) -> tuple[SourceVolume, ...]:
    """Aggregate legal height bands that belong to one typed component.

    A tapered/lofted solid can require multiple 2.5D proxy bands. Treating
    those bands as separate buildings corrupts hierarchy and fragment counts;
    their union still retains holes and disconnected plan parts for the normal
    geometric checks below.
    """
    grouped: dict[str, list[SourceVolume]] = {}
    order: list[str] = []
    for volume in volumes:
        if volume.role not in grouped:
            grouped[volume.role] = []
            order.append(volume.role)
        grouped[volume.role].append(volume)
    components: list[SourceVolume] = []
    for role in order:
        members = grouped[role]
        merged = unary_union([volume.footprint for volume in members])
        parts = (merged,) if merged.geom_type == "Polygon" else tuple(getattr(merged, "geoms", ()))
        if not parts:
            parts = tuple(volume.footprint for volume in members)
        components.extend(
            SourceVolume(
                role=role,
                footprint=part,
                bottom_fraction=min(volume.bottom_fraction for volume in members),
                top_fraction=max(volume.top_fraction for volume in members),
                verb=members[0].verb,
            )
            for part in parts
            if getattr(part, "geom_type", "") == "Polygon" and not part.is_empty
        )
    return tuple(components)


__all__ = ["COHERENCE_SCHEMA_VERSION", "evaluate_source_volume_coherence"]
