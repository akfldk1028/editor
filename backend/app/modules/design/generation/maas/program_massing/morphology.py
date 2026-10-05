"""Pose-invariant morphology metrics for MAAS archive diversity.

This module is intentionally independent from the search/selection policy so
the representation can later be replaced by voxel, mesh-embedding or learned
metrics without rewriting the archive loop.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from math import atan2, cos, degrees, isfinite, radians, sin

from shapely.affinity import rotate, scale, translate
from shapely.geometry import MultiPoint, Polygon, box
from shapely.wkb import loads as load_wkb

from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass
from backend.app.modules.design.generation.maas.program_massing.geometry_safety import safe_unary_union
from backend.app.modules.design.generation.maas.program_massing.visual_silhouette import visual_silhouette_distance


LayeredFootprint = tuple[Polygon, float, float]
MorphologyKey = tuple[tuple[str, float, float], ...]
SectionProfileKey = tuple[tuple[tuple[float, float], ...], ...]




@dataclass(frozen=True)
class MorphologyNoveltyPolicy:
    """Replaceable archive thresholds, separated by semantic relationship."""

    generic_duplicate: float = 0.20
    same_principle_repeat: float = 0.28
    same_topology_repeat: float = 0.30
    graph_audit_neighbor: float = 0.35
    # Surface-aware top/front/side distance has a different scale from the
    # former proxy-volume-only metric. 0.10 still rejects exact/twin box
    # collapses (~0.00-0.03) while retaining genuinely different folded and
    # profiled sections (>0.12 in the audited author population).
    visual_silhouette_repeat: float = 0.10

    def repeat_kind(
        self,
        distance: float,
        *,
        same_principle: bool,
        same_topology: bool,
    ) -> str | None:
        if distance < self.generic_duplicate:
            return "intrinsic_geometry_duplicate"
        if same_topology and distance < self.same_topology_repeat:
            return "same_topology_morphology_repeat"
        if same_principle and distance < self.same_principle_repeat:
            return "same_principle_morphology_repeat"
        return None


DEFAULT_NOVELTY_POLICY = MorphologyNoveltyPolicy()


def authoritative_surface_morphology(source: SourceMass) -> dict[str, object]:
    """Measure visual identity exclusively from renderer-authoritative surfaces."""

    normalized = _normalized_authoritative_surface_triangles(source)
    if normalized is None:
        return {
            "hard_pass": False,
            "phenotype": "",
            "visible_stepped": False,
            "pyramidal_like": False,
        }
    triangles, views = normalized
    horizontal_levels: set[int] = set()
    horizontal_area = sloped_area = total_area = 0.0
    for triangle in triangles:
        a, b, c = triangle
        ux, uy, uz = (b[index] - a[index] for index in range(3))
        vx, vy, vz = (c[index] - a[index] for index in range(3))
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        magnitude = (nx * nx + ny * ny + nz * nz) ** 0.5
        if magnitude <= 1e-12:
            # Closed CSG meshes may retain zero-area transport facets after
            # splitting. They preserve topology but carry no visible area.
            continue
        area = magnitude / 2.0
        total_area += area
        absolute_z = abs(nz / magnitude)
        triangle_z_span = max(point[2] for point in triangle) - min(
            point[2] for point in triangle
        )
        if triangle_z_span <= 1e-8:
            horizontal_area += area
            horizontal_levels.add(round(sum(point[2] for point in triangle) / 3.0 * 50))
        elif absolute_z >= 0.90:
            # A shallow continuous slope contributes to the near-horizontal
            # area ratio, but its triangle centroid is not a terrace datum.
            horizontal_area += area
        elif absolute_z > 0.12:
            sloped_area += area
    denominator = max(total_area, 1e-9)
    vertices = [point for triangle in triangles for point in triangle]
    measured_z_min = min(point[2] for point in vertices)
    measured_z_span = max(point[2] for point in vertices) - measured_z_min
    low = [point for point in vertices if point[2] <= measured_z_min + measured_z_span * 0.15]
    high = [point for point in vertices if point[2] >= measured_z_min + measured_z_span * 0.85]

    def span_area(points: list[tuple[float, float, float]]) -> float:
        if not points:
            return 0.0
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return max(max(xs) - min(xs), 0.0) * max(max(ys) - min(ys), 0.0)

    upper_ratio = span_area(high) / max(span_area(low), 1e-9)
    sloped_ratio = sloped_area / denominator
    pyramidal = bool(sloped_ratio >= 0.20 and upper_ratio <= 0.35)
    stepped = bool(not pyramidal and len(horizontal_levels) >= 4)
    top = views[0]
    convexity = float(top.area) / max(float(top.convex_hull.area), 1e-9)
    if pyramidal:
        phenotype = "pyramidal"
    elif stepped:
        phenotype = "stepped"
    elif any(isinstance(item, Polygon) and item.interiors for item in getattr(top, "geoms", (top,))):
        phenotype = "voided"
    elif convexity <= 0.84:
        phenotype = "winged"
    elif sloped_ratio >= 0.08:
        phenotype = "oblique"
    else:
        phenotype = "prismatic"
    return {
        "hard_pass": True,
        "phenotype": phenotype,
        "visible_stepped": stepped,
        "pyramidal_like": pyramidal,
        "horizontal_level_count": len(horizontal_levels),
        "horizontal_surface_ratio": round(horizontal_area / denominator, 6),
        "sloped_surface_ratio": round(sloped_ratio, 6),
    }


def authoritative_surface_silhouette_distance(left: SourceMass, right: SourceMass) -> float:
    """Return pose-invariant 3-view distance without reading proxy volumes."""

    left_payload = _normalized_authoritative_surface_triangles(left)
    right_payload = _normalized_authoritative_surface_triangles(right)
    if left_payload is None or right_payload is None:
        return 1.0
    left_views = left_payload[1]
    right_triangles = right_payload[0]
    best = 1.0
    for angle in (0.0, 90.0, 180.0, 270.0):
        theta = radians(angle)
        for mirror_x in (False, True):
            transformed = tuple(tuple(
                (
                    ((-x if mirror_x else x) * cos(theta) - y * sin(theta)),
                    ((-x if mirror_x else x) * sin(theta) + y * cos(theta)),
                    z,
                )
                for x, y, z in triangle
            ) for triangle in right_triangles)
            right_views = _surface_views(transformed)
            distances = tuple(
                float(a.symmetric_difference(b).area) / max(float(a.union(b).area), 1e-9)
                for a, b in zip(left_views, right_views)
            )
            best = min(best, distances[0] * 0.40 + distances[1] * 0.30 + distances[2] * 0.30)
    return min(1.0, best)


def _normalized_authoritative_surface_triangles(source: SourceMass):
    surfaces = tuple(getattr(source, "surfaces", ()) or ())
    if not surfaces:
        return None
    triangles: list[tuple[tuple[float, float, float], ...]] = []
    for surface in surfaces:
        vertices = tuple(getattr(surface, "vertices_m", ()) or ())
        if not str(getattr(surface, "surface_type", "")).startswith("profiled_") or len(vertices) != 3:
            return None
        try:
            triangle = tuple(tuple(float(value) for value in point) for point in vertices)
        except (TypeError, ValueError):
            return None
        if any(len(point) != 3 or not all(isfinite(value) for value in point) for point in triangle):
            return None
        triangles.append(triangle)
    points = [point for triangle in triangles for point in triangle]
    coordinate_span = max(
        max(point[index] for point in points) - min(point[index] for point in points)
        for index in range(3)
    )
    if coordinate_span <= 1e-9:
        return None
    def vertex_key(point):
        # Keep this identity exactly aligned with the renderer-authoritative
        # completeness gate.  A scale-relative tolerance coarsened valid CSG
        # split edges on building-sized meshes and made morphology reject a
        # surface payload that the projection gate had already certified.
        return tuple(round(value, 8) for value in point)

    edge_counts: Counter[tuple[tuple[int, ...], tuple[int, ...]]] = Counter()
    edge_incidents: dict[
        tuple[tuple[int, ...], tuple[int, ...]],
        list[tuple[int, tuple[tuple[int, ...], tuple[int, ...]]]],
    ] = {}
    vertex_faces: dict[tuple[int, ...], set[int]] = {}
    for face_index, triangle in enumerate(triangles):
        keys = tuple(vertex_key(point) for point in triangle)
        if len(set(keys)) != 3:
            return None
        for key in keys:
            vertex_faces.setdefault(key, set()).add(face_index)
        for left, right in ((keys[0], keys[1]), (keys[1], keys[2]), (keys[2], keys[0])):
            edge_key = tuple(sorted((left, right)))
            edge_counts[edge_key] += 1
            edge_incidents.setdefault(edge_key, []).append(
                (face_index, (left, right))
            )
    directed_topology = bool(edge_counts) and all(
        count == 2 and len(edge_incidents.get(edge, ())) == 2
        for edge, count in edge_counts.items()
    )
    vertex_face_adjacency: dict[
        tuple[int, ...], dict[int, set[int]]
    ] = {
        vertex: {face: set() for face in faces}
        for vertex, faces in vertex_faces.items()
    }
    if directed_topology:
        for edge, incidents in edge_incidents.items():
            (left_face, left_direction), (right_face, right_direction) = incidents
            if left_direction != tuple(reversed(right_direction)):
                directed_topology = False
                break
            for vertex in edge:
                vertex_face_adjacency[vertex][left_face].add(right_face)
                vertex_face_adjacency[vertex][right_face].add(left_face)
    if directed_topology:
        for vertex, incident_faces in vertex_faces.items():
            pending = [next(iter(incident_faces))]
            visited: set[int] = set()
            while pending:
                face = pending.pop()
                if face in visited:
                    continue
                visited.add(face)
                pending.extend(vertex_face_adjacency[vertex][face] - visited)
            if visited != incident_faces:
                directed_topology = False
                break
    if not directed_topology:
        # Boolean kernels may retain redundant coplanar transport facets.
        # The visual metric can safely union those triangles only when the
        # same complete payload is independently certified as a closed
        # manifold; open legacy triangle soups remain rejected.
        from backend.app.modules.design.generation.maas.geometry_language.floorwise_visual_projection import _kernel_certifies_complete_surface_mesh

        if not _kernel_certifies_complete_surface_mesh(surfaces):
            return None
    hull = MultiPoint([(point[0], point[1]) for point in points]).convex_hull
    if hull.is_empty or float(hull.area) <= 1e-12:
        return None
    rectangle = hull.minimum_rotated_rectangle
    coordinates = list(rectangle.exterior.coords)
    edges = [
        (((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5, atan2(y2 - y1, x2 - x1))
        for (x1, y1), (x2, y2) in zip(coordinates, coordinates[1:])
    ]
    major, angle = max(edges, key=lambda item: item[0])
    z_min = min(point[2] for point in points)
    z_span = max(point[2] for point in points) - z_min
    if major <= 1e-9 or z_span <= 1e-9:
        return None
    center = hull.centroid
    theta = -angle
    normalized = tuple(tuple(
        (
            ((point[0] - center.x) * cos(theta) - (point[1] - center.y) * sin(theta)) / major,
            ((point[0] - center.x) * sin(theta) + (point[1] - center.y) * cos(theta)) / major,
            (point[2] - z_min) / z_span,
        )
        for point in triangle
    ) for triangle in triangles)
    views = _surface_views(normalized)
    if any(view.is_empty or float(view.area) <= 1e-12 for view in views):
        return None
    return normalized, views


def _surface_views(triangles):
    def projected(indices):
        polygons = []
        for triangle in triangles:
            polygon = Polygon([(point[indices[0]], point[indices[1]]) for point in triangle])
            if polygon.is_valid and not polygon.is_empty and float(polygon.area) > 1e-12:
                polygons.append(polygon)
        return safe_unary_union(polygons) or Polygon()
    return projected((0, 1)), projected((0, 2)), projected((1, 2))


def intrinsic_shape_distance(left: SourceMass, right: SourceMass) -> tuple[float, float]:
    """Return rotation/reflection/translation/scale-invariant 3D and plan distance.

    The normalization removes pose and overall size while retaining plan
    proportion, voids, relative component placement and vertical band logic.
    Site fit is intentionally evaluated by a separate channel.
    """
    left_key = source_morphology_key(left)
    right_key = source_morphology_key(right)
    if right_key < left_key:
        left_key, right_key = right_key, left_key
    return intrinsic_shape_distance_from_keys(left_key, right_key)


def intrinsic_silhouette_distance(left: SourceMass, right: SourceMass) -> float:
    """Compare pose-invariant top/front/side mass silhouettes.

    Legal proxy volumes can have different roles or internal partitions while
    reading as the same building in a review board. This metric deliberately
    ignores labels and compares the three dominant orthographic figures.
    """
    return visual_silhouette_distance(left, right)


def intrinsic_section_profile_distance(left: SourceMass, right: SourceMass) -> float:
    """Compare executable normalized roof/section genotypes independent of plan.

    Orthographic union silhouettes can underweight a one-direction shed or
    barrel because the unchanged top view dominates the mean.  This channel
    measures the actual compiled section polygon and its mirrored equivalent;
    it is geometry evidence, not an operator-label bonus.
    """
    left_key = source_section_profile_key(left)
    right_key = source_section_profile_key(right)
    if right_key < left_key:
        left_key, right_key = right_key, left_key
    return _section_profile_distance_from_keys(left_key, right_key)


@lru_cache(maxsize=131_072)
def _section_profile_distance_from_keys(
    left_key: SectionProfileKey,
    right_key: SectionProfileKey,
) -> float:
    left_profiles = _section_profile_polygons(left_key)
    right_profiles = _section_profile_polygons(right_key)
    if not left_profiles and not right_profiles:
        return 0.0
    if not left_profiles or not right_profiles:
        return 1.0
    left_profile = max(left_profiles, key=lambda profile: profile.area)
    best = 1.0
    for right_profile in right_profiles:
        for candidate in (
            right_profile,
            scale(right_profile, xfact=-1.0, yfact=1.0, origin=(0.5, 0.0)),
        ):
            union = left_profile.union(candidate)
            distance = float(left_profile.symmetric_difference(candidate).area) / max(float(union.area), 1e-9)
            best = min(best, distance)
    return min(1.0, best)


def source_section_profile_key(source: SourceMass) -> SectionProfileKey:
    evidence = source.metadata.get("program_section_graph_evidence") or {}
    profiles: list[tuple[tuple[float, float], ...]] = []
    for node in (evidence.get("materialized_nodes") or ()) if isinstance(evidence, dict) else ():
        controls = node.get("section_controls") if isinstance(node, dict) else None
        if not isinstance(controls, list) or len(controls) < 3:
            continue
        try:
            profiles.append(tuple(
                (round(float(item[0]), 6), round(float(item[1]), 6))
                for item in controls
            ))
        except (TypeError, ValueError, IndexError):
            continue
    return tuple(sorted(profiles))


@lru_cache(maxsize=8192)
def _section_profile_polygons(key: SectionProfileKey) -> tuple[Polygon, ...]:
    profiles: list[Polygon] = []
    for points in key:
        profile = Polygon([(0.0, 0.0), *points, (1.0, 0.0)])
        if profile.is_valid and not profile.is_empty and profile.area > 1e-9:
            profiles.append(profile)
    return tuple(profiles)


@lru_cache(maxsize=131_072)
def intrinsic_silhouette_distance_from_keys(
    left_key: MorphologyKey,
    right_key: MorphologyKey,
) -> float:
    left_volumes = _principal_frame_from_key(left_key)
    right_variants = _symmetry_variants_from_key(right_key)
    if not left_volumes or not right_variants:
        return 1.0
    left_views = _orthographic_silhouettes(left_volumes)
    best = 1.0
    for transformed in right_variants:
        right_views = _orthographic_silhouettes(transformed)
        distances = [
            float(left.symmetric_difference(right).area) / max(float(left.union(right).area), 1e-9)
            for left, right in zip(left_views, right_views)
        ]
        best = min(best, distances[0] * 0.40 + distances[1] * 0.30 + distances[2] * 0.30)
    return min(1.0, best)


@lru_cache(maxsize=131_072)
def intrinsic_shape_distance_from_keys(
    left_key: MorphologyKey,
    right_key: MorphologyKey,
) -> tuple[float, float]:
    """Cached pair distance; selectors revisit the same pairs many times."""
    left_volumes = _principal_frame_from_key(left_key)
    right_variants = _symmetry_variants_from_key(right_key)
    if not left_volumes or not right_variants:
        return 1.0, 1.0
    left_plan = safe_unary_union([footprint for footprint, _, _ in left_volumes])
    if left_plan is None:
        return 1.0, 1.0
    best_volume = best_plan = 1.0
    best_joint = float("inf")
    for transformed in right_variants:
        right_plan = safe_unary_union([footprint for footprint, _, _ in transformed])
        if right_plan is None:
            continue
        plan_union = left_plan.union(right_plan)
        plan_distance = float(left_plan.symmetric_difference(right_plan).area) / max(
            float(plan_union.area),
            1e-9,
        )
        volume_distance = layered_volume_distance(left_volumes, transformed)
        joint = volume_distance * 0.7 + plan_distance * 0.3
        if joint < best_joint:
            best_joint = joint
            best_volume = volume_distance
            best_plan = plan_distance
    return min(1.0, best_volume), min(1.0, best_plan)


def principal_frame_volumes(source: SourceMass) -> list[LayeredFootprint]:
    return list(_principal_frame_from_key(source_morphology_key(source)))


def source_morphology_key(source: SourceMass) -> MorphologyKey:
    return tuple(sorted(
        (
            volume.footprint.wkb_hex,
            round(float(volume.bottom_fraction), 6),
            round(float(volume.top_fraction), 6),
        )
        for volume in source.volumes
        if not volume.footprint.is_empty
    ))


@lru_cache(maxsize=8192)
def _principal_frame_from_key(key: MorphologyKey) -> tuple[LayeredFootprint, ...]:
    volumes = tuple(
        (load_wkb(bytes.fromhex(wkb_hex)), bottom, top)
        for wkb_hex, bottom, top in key
    )
    footprints = [footprint for footprint, _, _ in volumes]
    if not footprints:
        return ()
    union = safe_unary_union(footprints)
    if union is None or union.is_empty:
        return ()
    rectangle = union.minimum_rotated_rectangle
    coordinates = list(rectangle.exterior.coords)
    edges = [
        (
            ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5,
            degrees(atan2(y2 - y1, x2 - x1)),
        )
        for (x1, y1), (x2, y2) in zip(coordinates, coordinates[1:])
    ]
    major_length, major_angle = max(edges, key=lambda item: item[0])
    if major_length <= 1e-9:
        return ()
    center = union.centroid
    normalized: list[LayeredFootprint] = []
    for volume_footprint, bottom, top in volumes:
        footprint = translate(volume_footprint, xoff=-center.x, yoff=-center.y)
        footprint = rotate(footprint, -major_angle, origin=(0.0, 0.0), use_radians=False)
        footprint = scale(
            footprint,
            xfact=1.0 / major_length,
            yfact=1.0 / major_length,
            origin=(0.0, 0.0),
        )
        normalized.append((footprint, bottom, top))
    return tuple(normalized)


@lru_cache(maxsize=8192)
def _symmetry_variants_from_key(
    key: MorphologyKey,
) -> tuple[tuple[LayeredFootprint, ...], ...]:
    volumes = _principal_frame_from_key(key)
    return tuple(
        tuple(
            (dihedral_transform(footprint, angle=angle, mirror_x=mirror_x), bottom, top)
            for footprint, bottom, top in volumes
        )
        for angle in (0.0, 90.0, 180.0, 270.0)
        for mirror_x in (False, True)
    )


def dihedral_transform(footprint: Polygon, *, angle: float, mirror_x: bool) -> Polygon:
    transformed = footprint
    if mirror_x:
        transformed = scale(transformed, xfact=-1.0, yfact=1.0, origin=(0.0, 0.0))
    if angle:
        transformed = rotate(transformed, angle, origin=(0.0, 0.0), use_radians=False)
    return transformed


def _orthographic_silhouettes(
    volumes: tuple[LayeredFootprint, ...] | list[LayeredFootprint],
) -> tuple[Polygon, Polygon, Polygon]:
    top = safe_unary_union([footprint for footprint, _, _ in volumes]) or Polygon()
    front = safe_unary_union([
        box(footprint.bounds[0], bottom, footprint.bounds[2], top_fraction)
        for footprint, bottom, top_fraction in volumes
    ]) or Polygon()
    side = safe_unary_union([
        box(footprint.bounds[1], bottom, footprint.bounds[3], top_fraction)
        for footprint, bottom, top_fraction in volumes
    ]) or Polygon()
    return top, front, side


def layered_volume_distance(left: list[LayeredFootprint], right: list[LayeredFootprint]) -> float:
    levels = sorted({
        round(value, 6)
        for volumes in (left, right)
        for _, bottom, top in volumes
        for value in (bottom, top)
    })
    union_volume = difference_volume = 0.0
    for lower, upper in zip(levels, levels[1:]):
        thickness = upper - lower
        if thickness <= 1e-9:
            continue
        middle = (lower + upper) / 2.0
        left_active = [footprint for footprint, bottom, top in left if bottom <= middle < top]
        right_active = [footprint for footprint, bottom, top in right if bottom <= middle < top]
        left_slice = safe_unary_union(left_active)
        right_slice = safe_unary_union(right_active)
        if left_slice is None and right_slice is None:
            continue
        if left_slice is None:
            slice_union = slice_difference = float(right_slice.area)
        elif right_slice is None:
            slice_union = slice_difference = float(left_slice.area)
        else:
            slice_union = float(left_slice.union(right_slice).area)
            slice_difference = float(left_slice.symmetric_difference(right_slice).area)
        union_volume += slice_union * thickness
        difference_volume += slice_difference * thickness
    return min(1.0, difference_volume / max(union_volume, 1e-9))


__all__ = [
    "DEFAULT_NOVELTY_POLICY",
    "MorphologyNoveltyPolicy",
    "authoritative_surface_morphology",
    "authoritative_surface_silhouette_distance",
    "intrinsic_shape_distance",
    "intrinsic_shape_distance_from_keys",
    "intrinsic_silhouette_distance",
    "intrinsic_section_profile_distance",
    "intrinsic_silhouette_distance_from_keys",
    "principal_frame_volumes",
    "source_morphology_key",
    "source_section_profile_key",
]
