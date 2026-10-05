"""Build one certified visual skin from exact legal floor sections."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Sequence

from shapely.geometry import Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass, SourceSurface, SourceVolume

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import validate_matrix4
from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult, revalidate_compilation_mesh
from backend.app.modules.design.generation.maas.geometry_language.floorwise_visual_projection import FloorwiseVisualProjection, FloorwiseVisualProjectionCertificate, _BufferedLegalSections, _boundary_intersection_sample_count, _exact_surface_payload_hash, _has_closed_directed_edge_topology, _legal_section_indices_for_triangle, _legal_sections_cover_point, _legal_sections_cover_triangle, _section_evidence_points, _stable_visual_hash, _validated_output_origin, floorwise_authority_binding_hash


Point2 = tuple[float, float]
Point3 = tuple[float, float, float]
_SECTION_LOFT_NUMERIC_BOUNDARY_EPSILON_M = 1e-5


@dataclass(frozen=True)
class ContinuousLegalEnvelopeMesh:
    status: str
    hard_pass: bool
    failure_reasons: tuple[str, ...] = ()
    vertices: tuple[Point3, ...] = ()
    triangles: tuple[tuple[int, int, int], ...] = ()
    legal_sample_count: int = 0
    failure_witness: dict[str, Any] | None = None


def build_continuous_legal_envelope_mesh(
    *,
    legal_sections: Sequence[Any],
    output_origin: Sequence[float],
) -> ContinuousLegalEnvelopeMesh:
    """Build one closed continuous legal mask without floor-band terraces."""

    origin = _validated_output_origin(output_origin)
    legal = tuple(_single_ring_polygon(item) for item in legal_sections)
    if origin is None or not legal or any(item is None for item in legal):
        return _continuous_envelope_failure(
            "continuous_legal_envelope_topology_incompatible"
        )
    legal_polygons = tuple(item for item in legal if item is not None)
    profile_polygons = tuple(
        _conservative_continuous_profile(item)
        for item in legal_polygons
    )
    seams: list[Polygon] = []
    for index in range(len(profile_polygons) - 1):
        seam = _single_ring_polygon(
            profile_polygons[index].intersection(profile_polygons[index + 1])
        )
        if seam is None:
            return _continuous_envelope_failure(
                "continuous_legal_envelope_disjoint_seam"
            )
        seams.append(seam)

    floor_count = len(legal_polygons)
    # Keep one profile per legal band boundary.  Repeating each floor profile
    # at its midpoint made the envelope alternate between a vertical half
    # storey and a sloped half storey.  It was manifold and technically had
    # no horizontal terrace faces, but the rendered silhouette still read as
    # the same cake-step mass.  Boundary-to-boundary interpolation preserves
    # the conservative seam proof while producing one continuous taper.
    raw_profiles: list[tuple[float, tuple[Point2, ...]]] = [
        (0.0, _ring(profile_polygons[0])),
    ]
    for index, seam in enumerate(seams):
        raw_profiles.append(
            ((index + 1.0) / floor_count, _ring(seam))
        )
    raw_profiles.append((1.0, _ring(profile_polygons[-1])))

    aligned_rings: list[tuple[Point2, ...]] = [raw_profiles[0][1]]
    for _level, ring in raw_profiles[1:]:
        aligned_rings.append(_align_ring(aligned_rings[-1], ring))
    fractions = sorted({
        round(fraction, 12)
        for ring in aligned_rings
        for fraction in _corner_fractions(ring)
    })
    if len(fractions) < 3:
        return _continuous_envelope_failure(
            "continuous_legal_envelope_degenerate_profile"
        )
    profiles = tuple(
        tuple((
            *_point_at_fraction(ring, fraction),
            float(level),
        ) for fraction in fractions)
        for (level, _raw_ring), ring in zip(raw_profiles, aligned_rings)
    )
    vertices: tuple[Point3, ...] = tuple(
        (
            point[0] - origin[0],
            point[1] - origin[1],
            point[2],
        )
        for profile in profiles
        for point in profile
    )
    ring_size = len(fractions)
    triangles: list[tuple[int, int, int]] = []
    for profile_index in range(len(profiles) - 1):
        lower = profile_index * ring_size
        upper = (profile_index + 1) * ring_size
        for index in range(ring_size):
            following = (index + 1) % ring_size
            triangles.extend((
                (lower + index, lower + following, upper + following),
                (lower + index, upper + following, upper + index),
            ))
    bottom_cap = _ear_clip(profiles[0])
    top_cap = _ear_clip(profiles[-1])
    if bottom_cap is None or top_cap is None:
        return _continuous_envelope_failure(
            "continuous_legal_envelope_degenerate_cap"
        )
    triangles.extend(
        (triangle[0], triangle[2], triangle[1])
        for triangle in bottom_cap
    )
    top_offset = (len(profiles) - 1) * ring_size
    triangles.extend(
        tuple(top_offset + index for index in triangle)
        for triangle in top_cap
    )

    buffered_legal = _BufferedLegalSections(legal_polygons)
    legal_sample_count = 0
    for triangle_index, triangle in enumerate(triangles):
        world_triangle = tuple((
            vertices[index][0] + origin[0],
            vertices[index][1] + origin[1],
            vertices[index][2],
        ) for index in triangle)
        indices = _legal_section_indices_for_triangle(
            world_triangle,
            section_count=floor_count,
        )
        if not _legal_sections_cover_triangle(
            world_triangle,
            legal_sections=buffered_legal,
            legal_indices=indices,
        ):
            return _continuous_envelope_failure(
                "continuous_legal_envelope_outside_legal_field",
                legal_sample_count=legal_sample_count + len(indices),
                failure_witness={
                    "stage": "triangle_coverage",
                    "triangle_index": triangle_index,
                    "legal_indices": list(indices),
                    "world_triangle": [list(point) for point in world_triangle],
                },
            )
        for point in _section_evidence_points(
            world_triangle,
            floor_count=floor_count,
        ):
            if not _legal_sections_cover_point(
                point,
                legal_sections=buffered_legal,
            ):
                return _continuous_envelope_failure(
                    "continuous_legal_envelope_outside_legal_field",
                    legal_sample_count=legal_sample_count + 1,
                    failure_witness={
                        "stage": "section_evidence_point",
                        "triangle_index": triangle_index,
                        "point": list(point),
                    },
                )
            legal_sample_count += 1
        boundary_count = _boundary_intersection_sample_count(
            world_triangle,
            legal_sections=buffered_legal,
        )
        if boundary_count is None:
            return _continuous_envelope_failure(
                "continuous_legal_envelope_outside_legal_field",
                legal_sample_count=legal_sample_count + 1,
                failure_witness={
                    "stage": "boundary_intersection",
                    "triangle_index": triangle_index,
                    "world_triangle": [list(point) for point in world_triangle],
                },
            )
        legal_sample_count += len(indices) + boundary_count

    triangle_tuple = tuple(triangles)
    revalidated = revalidate_compilation_mesh(CompilationResult(
        program=GeometryProgram(
            nodes=(),
            root_id="",
            name="continuous_legal_envelope",
        ),
        status="compiled",
        vertices=vertices,
        triangles=triangle_tuple,
    ))
    if (
        revalidated.status != "compiled"
        or revalidated.metrics.get("closed_solid") is not True
        or revalidated.metrics.get("manifold") is not True
    ):
        return _continuous_envelope_failure(
            "continuous_legal_envelope_mesh_revalidation_failed",
            legal_sample_count=legal_sample_count,
        )
    return ContinuousLegalEnvelopeMesh(
        status="certified",
        hard_pass=True,
        vertices=vertices,
        triangles=triangle_tuple,
        legal_sample_count=legal_sample_count,
    )


def _continuous_envelope_failure(
    reason: str,
    *,
    legal_sample_count: int = 0,
    failure_witness: dict[str, Any] | None = None,
) -> ContinuousLegalEnvelopeMesh:
    return ContinuousLegalEnvelopeMesh(
        status="failed",
        hard_pass=False,
        failure_reasons=(reason,),
        legal_sample_count=legal_sample_count,
        failure_witness=dict(failure_witness or {}),
    )


def _conservative_continuous_profile(polygon: Polygon) -> Polygon:
    """Remove only microscopic reflex noise without expanding legal area."""

    hull = polygon.convex_hull
    convex_gap = max(0.0, float(hull.area) - float(polygon.area))
    numeric_gap_limit = max(1e-4, float(polygon.area) * 1e-6)
    if convex_gap <= 1e-12 or convex_gap > numeric_gap_limit:
        return polygon
    min_x, min_y, max_x, max_y = polygon.bounds
    span = max(float(max_x - min_x), float(max_y - min_y), 1.0)
    for factor in (1e-9, 3e-9, 1e-8, 3e-8, 1e-7, 3e-7, 1e-6, 3e-6, 1e-5):
        inset = polygon.buffer(-span * factor, join_style=2)
        if inset.is_empty or not isinstance(inset, Polygon):
            continue
        candidate = inset.convex_hull
        if (
            polygon.covers(candidate)
            and float(candidate.area) >= float(polygon.area) * 0.9999
        ):
            return orient(candidate, sign=1.0)
    return polygon


def loft_floorwise_legal_sections(
    source: SourceMass,
    occupied_sections: Sequence[Any],
    legal_sections: Sequence[Any],
    capacity_plates: Sequence[SourceVolume],
    output_origin: Sequence[float],
) -> FloorwiseVisualProjection:
    """Loft exact mid-floor profiles through compatible legal boundary seams."""

    capacity_gfa = sum(
        max(0.0, float(plate.footprint.area))
        for plate in capacity_plates
    )
    origin = _validated_output_origin(output_origin)
    occupied = tuple(_single_ring_polygon(item) for item in occupied_sections)
    legal = tuple(_single_ring_polygon(item) for item in legal_sections)
    if (
        origin is None
        or not occupied
        or len(occupied) != len(legal)
        or any(item is None for item in (*occupied, *legal))
    ):
        return _failure(
            "section_loft_topology_incompatible",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(source.surfaces),
        )
    occupied_polygons = tuple(item for item in occupied if item is not None)
    legal_polygons = tuple(item for item in legal if item is not None)
    if any(
        not legal_polygons[index].buffer(1e-7).covers(section)
        for index, section in enumerate(occupied_polygons)
    ):
        return _failure(
            "section_loft_occupied_outside_legal_section",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(source.surfaces),
        )
    stack = source.metadata.get("floorwise_legal_matrix_stack")
    stack = stack if isinstance(stack, dict) else {}
    components, component_failure = floorwise_authority_component_hashes(
        occupied_polygons,
        capacity_plates,
        floor_capacity_plan_hash=str(
            stack.get("floor_capacity_plan_hash") or ""
        ),
        floor_evidence=stack.get("floors"),
    )
    if components is None:
        return _failure(
            component_failure,
            capacity_gfa=capacity_gfa,
            source_surface_count=len(source.surfaces),
        )

    seams: list[Polygon] = []
    for index in range(len(occupied_polygons) - 1):
        seam = _single_ring_polygon(
            occupied_polygons[index]
            .intersection(occupied_polygons[index + 1])
            .intersection(legal_polygons[index])
            .intersection(legal_polygons[index + 1])
        )
        if seam is None:
            return _failure(
                "section_loft_topology_incompatible",
                capacity_gfa=capacity_gfa,
                source_surface_count=len(source.surfaces),
            )
        seams.append(seam)

    floor_count = len(occupied_polygons)
    raw_profiles: list[tuple[float, tuple[Point2, ...]]] = [
        (0.0, _ring(occupied_polygons[0])),
        (0.5 / floor_count, _ring(occupied_polygons[0])),
    ]
    for index, seam in enumerate(seams):
        raw_profiles.extend((
            ((index + 1.0) / floor_count, _ring(seam)),
            ((index + 1.5) / floor_count, _ring(occupied_polygons[index + 1])),
        ))
    raw_profiles.append((1.0, _ring(occupied_polygons[-1])))

    aligned_rings: list[tuple[Point2, ...]] = [raw_profiles[0][1]]
    for _level, ring in raw_profiles[1:]:
        aligned_rings.append(_align_ring(aligned_rings[-1], ring))
    fractions = sorted({
        round(fraction, 12)
        for ring in aligned_rings
        for fraction in _corner_fractions(ring)
    })
    if len(fractions) < 3:
        return _failure(
            "section_loft_degenerate_profile",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(source.surfaces),
        )
    profiles = tuple(
        tuple(
            (
                *_point_at_fraction(ring, fraction),
                float(level),
            )
            for fraction in fractions
        )
        for (level, _raw_ring), ring in zip(raw_profiles, aligned_rings)
    )

    vertices: list[Point3] = [
        (
            point[0] - origin[0],
            point[1] - origin[1],
            point[2],
        )
        for profile in profiles
        for point in profile
    ]
    ring_size = len(fractions)
    triangles: list[tuple[int, int, int]] = []
    for profile_index in range(len(profiles) - 1):
        lower = profile_index * ring_size
        upper = (profile_index + 1) * ring_size
        for index in range(ring_size):
            following = (index + 1) % ring_size
            triangles.extend((
                (lower + index, lower + following, upper + following),
                (lower + index, upper + following, upper + index),
            ))
    bottom_cap = _ear_clip(profiles[0])
    top_cap = _ear_clip(profiles[-1])
    if bottom_cap is None or top_cap is None:
        return _failure(
            "section_loft_degenerate_profile",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(source.surfaces),
        )
    triangles.extend(
        (triangle[0], triangle[2], triangle[1])
        for triangle in bottom_cap
    )
    top_offset = (len(profiles) - 1) * ring_size
    triangles.extend(
        tuple(top_offset + index for index in triangle)
        for triangle in top_cap
    )

    buffered_legal = _BufferedLegalSections(
        legal_polygons,
        buffer_distance_m=_SECTION_LOFT_NUMERIC_BOUNDARY_EPSILON_M,
    )
    legal_sample_count = 0
    for triangle_index, triangle in enumerate(triangles):
        world_triangle = tuple(
            (
                vertices[index][0] + origin[0],
                vertices[index][1] + origin[1],
                vertices[index][2],
            )
            for index in triangle
        )
        indices = _legal_section_indices_for_triangle(
            world_triangle,
            section_count=floor_count,
        )
        if not _legal_sections_cover_triangle(
            world_triangle,
            legal_sections=buffered_legal,
            legal_indices=indices,
        ):
            projected_triangle = Polygon([
                (float(x), float(y))
                for x, y, _z in world_triangle
            ])
            excess = tuple(
                projected_triangle.difference(buffered_legal[index])
                for index in indices
            )
            return _failure(
                "section_loft_outside_legal_envelope",
                capacity_gfa=capacity_gfa,
                source_surface_count=len(source.surfaces),
                legal_sample_count=legal_sample_count + len(indices),
                failure_witness={
                    "stage": "triangle_coverage",
                    "triangle_index": triangle_index,
                    "legal_indices": list(indices),
                    "world_triangle": [list(point) for point in world_triangle],
                    "maximum_outside_area_m2": max(
                        (float(item.area) for item in excess),
                        default=0.0,
                    ),
                    "maximum_outside_boundary_length_m": max(
                        (float(item.length) for item in excess),
                        default=0.0,
                    ),
                },
            )
        for point in _section_evidence_points(
            world_triangle,
            floor_count=floor_count,
        ):
            if not _legal_sections_cover_point(
                point,
                legal_sections=buffered_legal,
            ):
                return _failure(
                    "section_loft_outside_legal_envelope",
                    capacity_gfa=capacity_gfa,
                    source_surface_count=len(source.surfaces),
                    legal_sample_count=legal_sample_count + 1,
                    failure_witness={
                        "stage": "section_evidence_point",
                        "triangle_index": triangle_index,
                        "point": list(point),
                    },
                )
            legal_sample_count += 1
        boundary_count = _boundary_intersection_sample_count(
            world_triangle,
            legal_sections=buffered_legal,
        )
        if boundary_count is None:
            return _failure(
                "section_loft_outside_legal_envelope",
                capacity_gfa=capacity_gfa,
                source_surface_count=len(source.surfaces),
                legal_sample_count=legal_sample_count + 1,
                failure_witness={
                    "stage": "boundary_intersection",
                    "triangle_index": triangle_index,
                    "world_triangle": [list(point) for point in world_triangle],
                },
            )
        legal_sample_count += len(indices) + boundary_count

    surfaces = tuple(
        SourceSurface(
            role=f"floorwise_section_loft_{index:04d}",
            volume_role=(
                capacity_plates[0].role
                if capacity_plates
                else "recursive_primary"
            ),
            verb="exact_legal_section_profile_loft",
            surface_type="profiled_recursive_solid_mesh",
            vertices_m=tuple(vertices[vertex] for vertex in triangle),
            operator="loft",
            semantic_patch_id="floorwise_legal:section_profile_loft",
        )
        for index, triangle in enumerate(triangles, start=1)
    )
    if not _has_closed_directed_edge_topology(surfaces):
        return _failure(
            "section_loft_mesh_revalidation_failed",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(source.surfaces),
            legal_sample_count=legal_sample_count,
        )
    revalidated = revalidate_compilation_mesh(CompilationResult(
        program=GeometryProgram(nodes=(), root_id="", name="section_profile_loft"),
        status="compiled",
        vertices=tuple(vertices),
        triangles=tuple(triangles),
    ))
    if (
        revalidated.status != "compiled"
        or revalidated.metrics.get("closed_solid") is not True
        or revalidated.metrics.get("manifold") is not True
    ):
        return _failure(
            "section_loft_mesh_revalidation_failed",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(source.surfaces),
            legal_sample_count=legal_sample_count,
        )

    # Reuse the bridge's exact horizontal mesh-section measurement rather
    # than inferring success from the input rings used to construct the skin.
    from backend.app.modules.design.generation.maas.geometry_language.source_bridge import _mesh_section_polygon

    world_vertices = tuple(
        (x + origin[0], y + origin[1], z)
        for x, y, z in vertices
    )
    for index, expected in enumerate(occupied_polygons):
        measured = _mesh_section_polygon(
            world_vertices,
            tuple(triangles),
            (index + 0.5) / floor_count,
        )
        if (
            measured is None
            or measured.is_empty
            or abs(float(measured.area) - float(expected.area)) > 1e-6
            or float(measured.symmetric_difference(expected).area) > 1e-6
        ):
            return _failure(
                "section_loft_midplane_mismatch",
                capacity_gfa=capacity_gfa,
                source_surface_count=len(source.surfaces),
                legal_sample_count=legal_sample_count,
            )

    section_hash = components["section_profile_hash"]
    capacity_hash = components["capacity_volume_hash"]
    plan_hash = components["floor_capacity_plan_hash"]
    matrix_hash = components["matrix4_stack_hash"]
    exact_hash = _exact_surface_payload_hash(surfaces)
    authority_hash = floorwise_authority_binding_hash(
        section_profile_hash=section_hash,
        capacity_volume_hash=capacity_hash,
        floor_capacity_plan_hash=plan_hash,
        matrix4_stack_hash=matrix_hash,
        exact_surface_payload_hash=exact_hash,
        certification_mode="floorwise_csg_section_loft",
        visible_geometry_operation="exact_legal_section_profile_loft",
        visible_step_fallback=False,
    )
    return FloorwiseVisualProjection(
        surfaces=surfaces,
        certificate=FloorwiseVisualProjectionCertificate(
            status="certified",
            hard_pass=True,
            visual_hash=_stable_visual_hash(surfaces),
            source_surface_count=len(source.surfaces),
            projected_surface_count=len(surfaces),
            legal_sample_count=legal_sample_count,
            capacity_gfa_m2=capacity_gfa,
            floor_count=floor_count,
            certification_mode="floorwise_csg_section_loft",
            visible_geometry_operation="exact_legal_section_profile_loft",
            exact_surface_payload_hash=exact_hash,
            capacity_authority="floorwise_legal_volumes",
            visible_step_fallback=False,
            section_profile_hash=section_hash,
            capacity_volume_hash=capacity_hash,
            floor_capacity_plan_hash=plan_hash,
            matrix4_stack_hash=matrix_hash,
            authority_binding_hash=authority_hash,
            section_numeric_epsilon_m=(
                _SECTION_LOFT_NUMERIC_BOUNDARY_EPSILON_M
            ),
        ),
    )


def _single_ring_polygon(value: Any) -> Polygon | None:
    if (
        not isinstance(value, Polygon)
        or value.is_empty
        or not value.is_valid
        or len(value.interiors) != 0
        or not isfinite(float(value.area))
        or float(value.area) <= 1e-8
    ):
        return None
    normalized = orient(value, sign=1.0)
    return normalized if len(normalized.exterior.coords) >= 4 else None


def _ring(polygon: Polygon) -> tuple[Point2, ...]:
    original = tuple(
        (float(x), float(y))
        for x, y in tuple(polygon.exterior.coords)[:-1]
    )
    if len(original) <= 3:
        return original
    minimum_x, minimum_y, maximum_x, maximum_y = polygon.bounds
    scale = max(
        float(maximum_x) - float(minimum_x),
        float(maximum_y) - float(minimum_y),
        1e-9,
    )
    compacted = original
    while len(compacted) > 3:
        redundant: set[int] = set()
        for index, current in enumerate(compacted):
            previous = compacted[index - 1]
            following = compacted[(index + 1) % len(compacted)]
            incoming = (
                current[0] - previous[0],
                current[1] - previous[1],
            )
            outgoing = (
                following[0] - current[0],
                following[1] - current[1],
            )
            incoming_length = (
                incoming[0] * incoming[0]
                + incoming[1] * incoming[1]
            ) ** 0.5
            outgoing_length = (
                outgoing[0] * outgoing[0]
                + outgoing[1] * outgoing[1]
            ) ** 0.5
            tolerance = max(
                1e-24,
                scale
                * max(incoming_length, outgoing_length)
                * 1e-12,
            )
            cross = (
                incoming[0] * outgoing[1]
                - incoming[1] * outgoing[0]
            )
            dot = (
                incoming[0] * outgoing[0]
                + incoming[1] * outgoing[1]
            )
            if abs(cross) <= tolerance and dot >= -tolerance:
                redundant.add(index)
        if not redundant or len(compacted) - len(redundant) < 3:
            break
        next_ring = tuple(
            point
            for index, point in enumerate(compacted)
            if index not in redundant
        )
        if next_ring == compacted:
            break
        compacted = next_ring
    candidate_rings: list[tuple[Point2, ...]] = []
    if compacted != original:
        candidate_rings.append(compacted)
    simplified = polygon.simplify(
        scale * 1e-9,
        preserve_topology=True,
    )
    if (
        isinstance(simplified, Polygon)
        and not simplified.is_empty
        and simplified.is_valid
        and len(simplified.interiors) == 0
    ):
        simplified_ring = tuple(
            (float(x), float(y))
            for x, y in tuple(simplified.exterior.coords)[:-1]
        )
        if (
            len(simplified_ring) >= 3
            and simplified_ring != original
            and simplified_ring not in candidate_rings
        ):
            candidate_rings.append(simplified_ring)
    for candidate in sorted(candidate_rings, key=len):
        rebuilt = orient(Polygon(candidate), sign=1.0)
        if (
            rebuilt.is_empty
            or not rebuilt.is_valid
            or len(rebuilt.interiors) != 0
            or abs(float(rebuilt.area) - float(polygon.area)) > 1e-6
            or float(rebuilt.symmetric_difference(polygon).area) > 1e-6
        ):
            continue
        return tuple(
            (float(x), float(y))
            for x, y in tuple(rebuilt.exterior.coords)[:-1]
        )
    return original


def _corner_fractions(ring: tuple[Point2, ...]) -> tuple[float, ...]:
    lengths = _edge_lengths(ring)
    perimeter = sum(lengths)
    if perimeter <= 1e-10:
        return ()
    cumulative = 0.0
    fractions = []
    for length in lengths:
        fractions.append(cumulative / perimeter)
        cumulative += length
    return tuple(fractions)


def _edge_lengths(ring: tuple[Point2, ...]) -> tuple[float, ...]:
    return tuple(
        ((right[0] - left[0]) ** 2 + (right[1] - left[1]) ** 2) ** 0.5
        for left, right in zip(ring, (*ring[1:], ring[0]))
    )


def _point_at_fraction(ring: tuple[Point2, ...], fraction: float) -> Point2:
    lengths = _edge_lengths(ring)
    perimeter = sum(lengths)
    distance = (float(fraction) % 1.0) * perimeter
    traversed = 0.0
    for index, length in enumerate(lengths):
        if distance <= traversed + length + 1e-12:
            amount = (distance - traversed) / max(length, 1e-12)
            following = (index + 1) % len(ring)
            return (
                ring[index][0] + (ring[following][0] - ring[index][0]) * amount,
                ring[index][1] + (ring[following][1] - ring[index][1]) * amount,
            )
        traversed += length
    return ring[0]


def _align_ring(
    reference: tuple[Point2, ...],
    candidate: tuple[Point2, ...],
) -> tuple[Point2, ...]:
    sample_count = max(24, len(reference), len(candidate))
    reference_samples = tuple(
        _point_at_fraction(reference, index / sample_count)
        for index in range(sample_count)
    )
    best_shift = min(
        range(sample_count),
        key=lambda shift: sum(
            (
                reference_samples[index][0]
                - _point_at_fraction(
                    candidate,
                    ((index + shift) % sample_count) / sample_count,
                )[0]
            ) ** 2
            + (
                reference_samples[index][1]
                - _point_at_fraction(
                    candidate,
                    ((index + shift) % sample_count) / sample_count,
                )[1]
            ) ** 2
            for index in range(sample_count)
        ),
    )
    start = best_shift / sample_count
    fractions = sorted({
        0.0,
        *(
            (fraction - start) % 1.0
            for fraction in _corner_fractions(candidate)
        ),
    })
    return tuple(
        _point_at_fraction(candidate, (fraction + start) % 1.0)
        for fraction in fractions
    )


def _ear_clip(
    profile: tuple[Point3, ...],
) -> tuple[tuple[int, int, int], ...] | None:
    polygon = Polygon([(x, y) for x, y, _z in profile])
    if polygon.is_empty or not polygon.is_valid or polygon.area <= 1e-9:
        return None
    indices = tuple(range(len(profile)))
    direct = _strict_ear_clip(
        profile,
        polygon,
        indices,
    )
    if direct is not None:
        return direct
    for shift in range(1, len(indices)):
        rotated = (*indices[shift:], *indices[:shift])
        retried = _strict_ear_clip(profile, polygon, rotated)
        if retried is not None:
            return retried
    core = list(range(len(profile)))
    while len(core) > 3:
        removed = False
        for cursor, current in enumerate(core):
            previous = core[cursor - 1]
            following = core[(cursor + 1) % len(core)]
            left = profile[previous]
            middle = profile[current]
            right = profile[following]
            incoming = (
                middle[0] - left[0],
                middle[1] - left[1],
            )
            outgoing = (
                right[0] - middle[0],
                right[1] - middle[1],
            )
            cross = (
                incoming[0] * outgoing[1]
                - incoming[1] * outgoing[0]
            )
            dot = (
                incoming[0] * outgoing[0]
                + incoming[1] * outgoing[1]
            )
            if abs(cross) <= 1e-12 and dot >= 0.0:
                core.pop(cursor)
                removed = True
                break
        if not removed:
            break
    core_polygon = Polygon([
        (profile[index][0], profile[index][1])
        for index in core
    ])
    if (
        core_polygon.is_empty
        or not core_polygon.is_valid
        or core_polygon.area <= 1e-9
        or abs(float(core_polygon.area) - float(polygon.area)) > 1e-9
        or float(core_polygon.symmetric_difference(polygon).area) > 1e-9
    ):
        return None
    triangulated = _strict_ear_clip(profile, polygon, tuple(core))
    if triangulated is None:
        return None
    output = list(triangulated)
    for start, end in zip(core, (*core[1:], core[0])):
        chain = [start]
        cursor = (start + 1) % len(profile)
        while cursor != end and len(chain) <= len(profile):
            chain.append(cursor)
            cursor = (cursor + 1) % len(profile)
        if cursor != end:
            return None
        chain.append(end)
        if len(chain) == 2:
            continue
        adjacent_triangle = None
        apex = None
        for triangle_index, triangle in enumerate(output):
            for edge_index in range(3):
                if (
                    triangle[edge_index] == start
                    and triangle[(edge_index + 1) % 3] == end
                ):
                    adjacent_triangle = triangle_index
                    apex = triangle[(edge_index + 2) % 3]
                    break
            if adjacent_triangle is not None:
                break
        if adjacent_triangle is None or apex is None:
            return None
        replacements = [
            (left, right, apex)
            for left, right in zip(chain, chain[1:])
        ]
        if any(
            Polygon([
                profile[left][:2],
                profile[middle][:2],
                profile[right][:2],
            ]).area <= 1e-12
            for left, middle, right in replacements
        ):
            return None
        output[adjacent_triangle:adjacent_triangle + 1] = replacements
    return tuple(output)


def _strict_ear_clip(
    profile: tuple[Point3, ...],
    polygon: Polygon,
    indices: tuple[int, ...],
) -> tuple[tuple[int, int, int], ...] | None:
    remaining = list(indices)
    output: list[tuple[int, int, int]] = []
    guard = 0
    while len(remaining) > 3 and guard < len(indices) ** 2:
        guard += 1
        clipped = False
        for cursor, current in enumerate(remaining):
            previous = remaining[cursor - 1]
            following = remaining[(cursor + 1) % len(remaining)]
            left = profile[previous]
            middle = profile[current]
            right = profile[following]
            cross = (
                (middle[0] - left[0]) * (right[1] - middle[1])
                - (middle[1] - left[1]) * (right[0] - middle[0])
            )
            triangle = Polygon([
                (left[0], left[1]),
                (middle[0], middle[1]),
                (right[0], right[1]),
            ])
            if cross <= 1e-12 or not polygon.buffer(1e-9).covers(triangle):
                continue
            if any(
                triangle.contains(Point(profile[index][0], profile[index][1]))
                for index in remaining
                if index not in {previous, current, following}
            ):
                continue
            output.append((previous, current, following))
            remaining.pop(cursor)
            clipped = True
            break
        if not clipped:
            return None
    if len(remaining) != 3:
        return None
    left = profile[remaining[0]]
    middle = profile[remaining[1]]
    right = profile[remaining[2]]
    cross = (
        (middle[0] - left[0]) * (right[1] - middle[1])
        - (middle[1] - left[1]) * (right[0] - middle[0])
    )
    triangle = Polygon([
        (left[0], left[1]),
        (middle[0], middle[1]),
        (right[0], right[1]),
    ])
    if cross <= 1e-12 or not polygon.buffer(1e-9).covers(triangle):
        return None
    output.append(tuple(remaining))
    return tuple(output)


def _polygon_payload(polygon: Any) -> Any:
    normalized = _single_ring_polygon(polygon)
    if normalized is not None:
        return [[round(x, 9), round(y, 9)] for x, y in _ring(normalized)]
    if (
        getattr(polygon, "geom_type", "") in {"Polygon", "MultiPolygon"}
        and not getattr(polygon, "is_empty", True)
        and getattr(polygon, "is_valid", False)
        and float(getattr(polygon, "area", 0.0)) > 1e-8
    ):
        canonical = polygon.normalize()
        return {
            "geometry_type": canonical.geom_type,
            "normalized_wkb_hex": canonical.wkb_hex,
        }
    return None


def floorwise_authority_component_hashes(
    occupied_sections: Sequence[Any],
    capacity_plates: Sequence[SourceVolume],
    *,
    floor_capacity_plan_hash: str,
    floor_evidence: Any,
) -> tuple[dict[str, str] | None, str]:
    """Validate and hash one exact floorwise legal/capacity authority product."""

    occupied = tuple(occupied_sections)
    floor_count = len(occupied)
    if (
        not floor_count
        or not str(floor_capacity_plan_hash or "").strip()
        or not isinstance(floor_evidence, (list, tuple))
        or len(floor_evidence) != floor_count
        or not capacity_plates
    ):
        return None, "section_loft_missing_authority_evidence"
    matrices = []
    try:
        for row in floor_evidence:
            if not isinstance(row, dict) or "matrix4" not in row:
                raise ValueError("missing Matrix4")
            matrices.append(validate_matrix4(row["matrix4"]))
    except (TypeError, ValueError):
        return None, "section_loft_missing_authority_evidence"

    assigned_plate_ids: set[int] = set()
    for floor_index, expected in enumerate(occupied):
        if (
            expected is None
            or getattr(expected, "is_empty", True)
            or not getattr(expected, "is_valid", False)
            or float(getattr(expected, "area", 0.0)) <= 1e-8
        ):
            return None, "section_loft_topology_incompatible"
        bottom = floor_index / floor_count
        top = (floor_index + 1) / floor_count
        floor_plates = tuple(
            plate
            for plate in capacity_plates
            if (
                abs(float(plate.bottom_fraction) - bottom) <= 1e-8
                and abs(float(plate.top_fraction) - top) <= 1e-8
            )
        )
        if not floor_plates:
            return None, "section_loft_capacity_section_mismatch"
        assigned_plate_ids.update(id(plate) for plate in floor_plates)
        actual = unary_union([
            plate.footprint
            for plate in floor_plates
        ])
        try:
            mismatch_area = float(actual.symmetric_difference(expected).area)
            summed_plate_area = sum(
                float(plate.footprint.area)
                for plate in floor_plates
            )
            union_area = float(actual.area)
            expected_area = float(expected.area)
        except (TypeError, ValueError):
            return None, "section_loft_capacity_section_mismatch"
        if (
            mismatch_area > 1e-6
            or abs(summed_plate_area - union_area) > 1e-6
            or abs(summed_plate_area - expected_area) > 1e-6
        ):
            return None, "section_loft_capacity_section_mismatch"
    if len(assigned_plate_ids) != len(capacity_plates):
        return None, "section_loft_capacity_section_mismatch"

    components = {
        "section_profile_hash": _hash_json([
            _geometry_payload(section)
            for section in occupied
        ]),
        "capacity_volume_hash": _hash_json([
            {
                "role": plate.role,
                "bottom": float(plate.bottom_fraction),
                "top": float(plate.top_fraction),
                "footprint": _geometry_payload(plate.footprint),
            }
            for plate in capacity_plates
        ]),
        "floor_capacity_plan_hash": str(
            floor_capacity_plan_hash
        ).strip(),
        "matrix4_stack_hash": _hash_json([
            [
                [float(value) for value in matrix_row]
                for matrix_row in matrix
            ]
            for matrix in matrices
        ]),
    }
    return components, ""


def _geometry_payload(geometry: Any) -> Any:
    try:
        normalized = geometry.normalize()
        return {
            "geometry_type": str(normalized.geom_type),
            "wkb_hex": str(normalized.wkb_hex),
        }
    except (AttributeError, TypeError, ValueError):
        return None


def _hash_json(value: Any) -> str:
    return sha256(json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _failure(
    reason: str,
    *,
    capacity_gfa: float,
    source_surface_count: int,
    legal_sample_count: int = 0,
    failure_witness: dict[str, Any] | None = None,
) -> FloorwiseVisualProjection:
    return FloorwiseVisualProjection(
        surfaces=(),
        certificate=FloorwiseVisualProjectionCertificate(
            status="failed",
            hard_pass=False,
            failure_reasons=(reason,),
            source_surface_count=source_surface_count,
            legal_sample_count=legal_sample_count,
            capacity_gfa_m2=capacity_gfa,
            certification_mode="floorwise_csg_section_loft",
            visible_geometry_operation="exact_legal_section_profile_loft",
            visible_step_fallback=False,
            section_numeric_epsilon_m=(
                _SECTION_LOFT_NUMERIC_BOUNDARY_EPSILON_M
            ),
            failure_witness=dict(failure_witness or {}),
        ),
    )


__all__ = [
    "ContinuousLegalEnvelopeMesh",
    "build_continuous_legal_envelope_mesh",
    "floorwise_authority_component_hashes",
    "loft_floorwise_legal_sections",
]
