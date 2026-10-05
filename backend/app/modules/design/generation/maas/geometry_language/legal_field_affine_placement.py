"""Bounded whole-legal-field affine placement for one authored MASS solid.

The solver authors exactly one site-placement Matrix4.  It screens a small,
deterministic set of principal-frame/anisotropy/z-shear alternatives in 2D,
then compiles only the best few.  An unchanged authored solid is certified
first; exact floorwise legal CSG is available only to an explicitly authored
stepped body.  Floor capacity vectors remain provenance; only their aggregate
is a hard placement constraint.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import os
from math import atan2, degrees, isfinite, sqrt
from typing import Any

import numpy as np
import shapely
from shapely.affinity import affine_transform
from shapely.errors import GEOSException
from shapely.geometry import MultiPoint, Polygon
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import Matrix4, compose_matrix4, inverse_matrix4, rotation_matrix4, scale_matrix4, transform_point3, translation_matrix4
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.authored_legal_preservation import AuthoredLegalPreservationResult, certify_authored_affine_program
from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult, compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.floorwise_legal_program import FloorwiseLegalProgramResult, is_intentional_floorwise_stepped_program, _mesh_section_polygon
from backend.app.modules.design.generation.maas.geometry_language.gate import GeometryGatePolicy, compilation_gate
from backend.app.modules.design.generation.maas.geometry_language.source_bridge import HostFitTransform, append_site_placement_matrix


# Pose screening is GEOS/NumPy bound and releases the GIL, so threads help
# without process overhead. Held below the core count so a benchmark run
# does not starve the rest of the pipeline.
_POSE_WORKERS = max(1, min(8, (os.cpu_count() or 2) - 1))


@dataclass(frozen=True)
class LegalFieldAffineSelection:
    fit: HostFitTransform
    projection: (
        AuthoredLegalPreservationResult
        | FloorwiseLegalProgramResult
    )
    evidence: dict[str, Any]


@dataclass(frozen=True)
class _ScreenedAlternative:
    matrix4: Matrix4
    matrix_hash: str
    preclip_areas_m2: tuple[float, ...]
    clipped_areas_m2: tuple[float, ...]
    profile_distortion: float
    aggregate_retention: float
    minimum_floor_retention: float
    aggregate_area_m2: float
    orientation_degrees: int
    anisotropy: float
    area_factor: float
    shear_factor: float


def select_legal_field_affine_projection(
    program: GeometryProgram,
    *,
    legal_sections: tuple[Polygon, ...],
    target_floor_areas_m2: tuple[float, ...],
    floor_capacity_plan_hash: str,
    aggregate_target_area_m2: float | None = None,
    coverage_capacity_m2: float | None = None,
    maximum_exact_candidates: int = 4,
    minimum_aggregate_target_ratio: float = 0.995,
) -> LegalFieldAffineSelection | None:
    """Select one capacity-valid affine pose against the complete legal field."""

    if (
        not legal_sections
        or len(legal_sections) != len(target_floor_areas_m2)
        or not floor_capacity_plan_hash.strip()
        or any(
            not isinstance(section, Polygon)
            or section.is_empty
            or not section.is_valid
            or not isfinite(float(section.area))
            or float(section.area) <= 1e-9
            for section in legal_sections
        )
    ):
        return None
    aggregate_target = (
        float(aggregate_target_area_m2)
        if aggregate_target_area_m2 is not None
        else sum(float(value) for value in target_floor_areas_m2)
    )
    if not isfinite(aggregate_target) or aggregate_target <= 1e-9:
        return None
    minimum_target_ratio = max(
        0.05,
        min(0.995, float(minimum_aggregate_target_ratio)),
    )
    compilation = compile_geometry_program(program)
    if (
        compilation.status != "compiled"
        or compilation_gate(
            compilation,
            GeometryGatePolicy(maximum_components=1),
        )
    ):
        return None
    source_sections = _source_floor_sections(
        compilation,
        floor_count=len(legal_sections),
    )
    if source_sections is None:
        return None
    source_band_meshes = _source_closed_band_meshes(
        compilation,
        floor_count=len(legal_sections),
    )
    if source_band_meshes is None:
        return None
    alternatives = _screen_affine_alternatives(
        compilation,
        source_sections=source_sections,
        source_band_meshes=source_band_meshes,
        legal_sections=legal_sections,
        aggregate_target=aggregate_target,
        minimum_aggregate_target_ratio=minimum_target_ratio,
        coverage_capacity=(
            float(coverage_capacity_m2)
            if coverage_capacity_m2 is not None
            and isfinite(float(coverage_capacity_m2))
            and float(coverage_capacity_m2) > 1e-9
            else None
        ),
    )
    if not alternatives:
        return None

    exact_limit = max(1, min(4, int(maximum_exact_candidates)))
    exact_shortlist = _exact_shortlist(
        alternatives,
        limit=exact_limit,
    )
    exact_records: list[
        tuple[
            tuple[float, float, float, float, str],
            HostFitTransform,
            (
                AuthoredLegalPreservationResult
                | FloorwiseLegalProgramResult
            ),
            _ScreenedAlternative,
            tuple[float, ...],
            float,
        ]
    ] = []
    for alternative in exact_shortlist:
        world_vertices = tuple(
            transform_point3(alternative.matrix4, vertex)
            for vertex in compilation.vertices
        )
        fit = HostFitTransform(
            matrix4=alternative.matrix4,
            inverse_matrix4=inverse_matrix4(alternative.matrix4),
            world_vertices=world_vertices,
            achieved_plan_area_m2=float(
                MultiPoint([
                    (vertex[0], vertex[1])
                    for vertex in world_vertices
                ]).convex_hull.area
            ),
        )
        placed = append_site_placement_matrix(program, fit)
        projected = certify_authored_affine_program(
            placed,
            legal_sections=legal_sections,
            target_floor_areas_m2=target_floor_areas_m2,
            floor_capacity_plan_hash=floor_capacity_plan_hash,
            minimum_aggregate_target_ratio=minimum_target_ratio,
        )
        if projected is None:
            continue
        certificate = projected.certificate
        achieved = tuple(
            float(value)
            for value in projected.achieved_floor_areas_m2
        )
        achieved_total = sum(achieved)
        if (
            achieved_total + 1e-7
            < aggregate_target * minimum_target_ratio
            or certificate.get("hard_pass") is not True
            or certificate.get("manifold") is not True
            or certificate.get("watertight") is not True
            or certificate.get("all_sections_contained") is not True
        ):
            continue
        distortion = _profile_distortion(
            alternative.preclip_areas_m2,
            achieved,
        )
        band_profile = _conservative_band_profile(
            compilation,
            alternative.matrix4,
            projected.final_compilation,
            floor_count=len(legal_sections),
        )
        if band_profile is None:
            continue
        band_preclip, band_final = band_profile
        distortion = _profile_distortion(band_preclip, band_final)
        retention_by_floor = tuple(
            final_area / max(preclip_area, 1e-9)
            for final_area, preclip_area in zip(
                band_final,
                band_preclip,
            )
        )
        exact_records.append((
            _exact_affine_selection_rank(
                distortion=distortion,
                achieved_total=achieved_total,
                minimum_retention=min(retention_by_floor),
                aggregate_retention=(
                    sum(band_final) / max(sum(band_preclip), 1e-9)
                ),
                program_hash=projected.program.program_hash(),
            ),
            fit,
            projected,
            alternative,
            achieved,
            distortion,
        ))
    if not exact_records:
        return None
    exact_records.sort(key=lambda record: record[0])
    _rank, fit, projection, selected, achieved, selected_distortion = (
        exact_records[0]
    )
    evidence = {
        "schema_version": "arr.maas.legal_field_affine_placement.v1",
        "authority": "whole_legal_section_field",
        "screening_mode": (
            "bounded_2d_then_exact_authored_preservation"
        ),
        "containment_screening_authority": (
            "closed_z_band_projected_mesh"
        ),
        "maximum_containment_solver": (
            "convex_legal_container_halfspace_vertex_batch"
            if _convex_legal_halfspaces(legal_sections) is not None
            else "general_polygon_vectorized_triangle_coverage"
        ),
        "projection_mode": projection.certificate["projection_mode"],
        "screened_candidate_count": len(alternatives),
        "exact_candidate_limit": exact_limit,
        "exact_compiled_candidate_count": min(
            exact_limit,
            len(exact_shortlist),
        ),
        "exact_feasible_candidate_count": len(exact_records),
        "aggregate_target_area_m2": round(aggregate_target, 8),
        "minimum_aggregate_target_ratio": minimum_target_ratio,
        "achieved_aggregate_area_m2": round(sum(achieved), 8),
        "profile_distortion": round(
            selected_distortion,
            10,
        ),
        "preclip_floor_areas_m2": [
            round(value, 8)
            for value in selected.preclip_areas_m2
        ],
        "achieved_floor_areas_m2": [
            round(value, 8)
            for value in achieved
        ],
        "selected_matrix_hash": selected.matrix_hash,
        "orientation_degrees": selected.orientation_degrees,
        "anisotropy": selected.anisotropy,
        "area_factor": selected.area_factor,
        "shear_factor": selected.shear_factor,
        "floor_target_vector_authors_geometry": False,
        "single_site_placement_matrix": True,
    }
    return LegalFieldAffineSelection(
        fit=fit,
        projection=projection,
        evidence=evidence,
    )


def _exact_affine_selection_rank(
    *,
    distortion: float,
    achieved_total: float,
    minimum_retention: float,
    aggregate_retention: float,
    program_hash: str,
) -> tuple[float, float, float, float, str]:
    """Prefer capacity among numerically equivalent identity-preserving fits."""

    return (
        round(float(distortion), 6),
        -float(achieved_total),
        -float(minimum_retention),
        -float(aggregate_retention),
        str(program_hash),
    )


def _source_floor_sections(
    compilation: CompilationResult,
    *,
    floor_count: int,
) -> tuple[Any, ...] | None:
    bounds = (compilation.metrics or {}).get("bounds") or ()
    if len(bounds) != 2 or len(bounds[0]) != 3 or len(bounds[1]) != 3:
        return None
    min_z = float(bounds[0][2])
    max_z = float(bounds[1][2])
    z_span = max_z - min_z
    if not isfinite(z_span) or z_span <= 1e-9:
        return None
    sections = tuple(
        _mesh_section_polygon(
            compilation,
            min_z + z_span * (index + 0.5) / floor_count,
        )
        for index in range(floor_count)
    )
    if any(
        section is None
        or section.is_empty
        or not isfinite(float(section.area))
        or float(section.area) <= 1e-9
        for section in sections
    ):
        return None
    return sections


def _source_closed_band_meshes(
    compilation: CompilationResult,
    *,
    floor_count: int,
) -> tuple[Any, ...] | None:
    """Freeze exact source-band meshes for conservative 2D containment."""

    bounds = (compilation.metrics or {}).get("bounds") or ()
    solid = getattr(compilation, "_solid", None)
    if solid is None or len(bounds) != 2 or floor_count <= 0:
        return None
    min_z = float(bounds[0][2])
    max_z = float(bounds[1][2])
    floor_height = (max_z - min_z) / floor_count
    if not isfinite(floor_height) or floor_height <= 1e-9:
        return None
    result = []
    for floor_index in range(floor_count):
        lower_z = min_z + floor_height * floor_index
        upper_z = (
            max_z
            if floor_index == floor_count - 1
            else lower_z + floor_height
        )
        band = solid.trim_by_plane(
            (0.0, 0.0, 1.0),
            lower_z,
        ).trim_by_plane(
            (0.0, 0.0, -1.0),
            -upper_z,
        )
        if band.is_empty():
            return None
        mesh = band.to_mesh64()
        vertices = tuple(
            tuple(float(value) for value in row[:3])
            for row in mesh.vert_properties
        )
        triangles = tuple(
            tuple(int(index) for index in row[:3])
            for row in mesh.tri_verts
        )
        if not vertices or not triangles:
            return None
        result.append((vertices, triangles))
    return tuple(result)


def _screen_affine_alternatives(
    compilation: CompilationResult,
    *,
    source_sections: tuple[Any, ...],
    source_band_meshes: tuple[Any, ...],
    legal_sections: tuple[Polygon, ...],
    aggregate_target: float,
    minimum_aggregate_target_ratio: float,
    coverage_capacity: float | None = None,
) -> tuple[_ScreenedAlternative, ...]:
    bounds = (compilation.metrics or {}).get("bounds") or ()
    min_z = float(bounds[0][2])
    max_z = float(bounds[1][2])
    z_span = max_z - min_z
    source_plan = unary_union(source_sections).convex_hull
    source_angle, source_long, source_short = _principal_frame(source_plan)
    legal_frame = unary_union(legal_sections).convex_hull
    legal_angle, legal_long, legal_short = _principal_frame(legal_frame)
    if min(source_long, source_short, legal_long, legal_short) <= 1e-9:
        return ()
    source_reference_area = sum(
        float(section.area)
        for section in source_sections
    ) / len(source_sections)
    desired_plan_area = _waterfill_plan_area(
        tuple(float(section.area) for section in legal_sections),
        aggregate_target,
    )
    if desired_plan_area <= 1e-9 or source_reference_area <= 1e-9:
        return ()
    uniform_scale = sqrt(desired_plan_area / source_reference_area)
    source_aspect = source_long / source_short
    legal_aspect = legal_long / legal_short
    # The site-placement Matrix4 must be able to undo an upstream affine BOOK
    # scale.  The old 0.67..1.28 clamp made an otherwise identical compressed
    # solid unreachable even though no topology or section relation changed.
    # Keep the search bounded, but derive the primary candidate from the real
    # source/legal principal-frame ratio.
    frame_anisotropy = max(
        0.20,
        min(5.0, sqrt(legal_aspect / max(source_aspect, 1e-9))),
    )
    swapped_frame_anisotropy = max(
        0.20,
        min(
            5.0,
            sqrt(1.0 / max(legal_aspect * source_aspect, 1e-9)),
        ),
    )
    anisotropies = _unique_floats((
        frame_anisotropy,
        swapped_frame_anisotropy,
        0.78,
        1.0,
    ))
    # The legal prisms have piecewise-constant centroids inside each floor
    # band.  Include the unsheared and half-path poses so a linear z shear is
    # not forced to keep translating a solid after it has entered the upper
    # legal prism.
    shear_factors = (0.0, 0.5, 1.0)
    legal_centroids = tuple(section.centroid for section in legal_sections)
    alternatives: list[_ScreenedAlternative] = []
    seen_hashes: set[str] = set()

    # Each pose is independent and touches nothing shared, and the work inside
    # it is GEOS and NumPy, which drop the GIL. Evaluating the poses on a thread
    # pool therefore costs nothing in correctness: results are consumed in the
    # original iteration order below, so the deduplication and the returned set
    # are identical to the sequential version.
    pose_grid = tuple(
        (orientation_degrees, anisotropy, shear_factor)
        for orientation_degrees in (0, 90, 180, 270)
        for anisotropy in anisotropies
        for shear_factor in shear_factors
    )

    def _evaluate_pose(
        pose: tuple[int, float, float],
    ) -> tuple[str, Any] | None:
        orientation_degrees, anisotropy, shear_factor = pose
        target_angle = legal_angle + float(orientation_degrees)
        if True:
            if True:
                def matrix_at(scale_multiplier: float) -> Matrix4:
                    return _pose_matrix(
                        source_sections=source_sections,
                        legal_centroids=legal_centroids,
                        source_plan=source_plan,
                        source_angle=source_angle,
                        target_angle=target_angle,
                        source_min_z=min_z,
                        source_max_z=max_z,
                        uniform_scale=uniform_scale,
                        anisotropy=anisotropy,
                        shear_factor=shear_factor,
                        scale_multiplier=scale_multiplier,
                    )

                seed_sections = _placed_sections(
                    matrix_at(1.0),
                    source_sections=source_sections,
                    source_min_z=min_z,
                    source_z_span=z_span,
                )
                if seed_sections is None:
                    return None
                seed_union = unary_union(seed_sections)
                _seed_angle, seed_long, seed_short = _principal_frame(
                    seed_union.convex_hull
                )
                if min(seed_long, seed_short) <= 1e-9:
                    return None
                scale_upper = max(
                    1.0,
                    legal_long / seed_long,
                    legal_short / seed_short,
                )
                # 건축면적 is the building's horizontal projection (건축법 시행령
                # 제119조 제1항 제2호) and the coverage limit bounds it. The pose
                # scales the body in plan and only translates it otherwise, so
                # that projection is exactly quadratic in the multiplier and the
                # bound is closed form. Without it the search aims only at the
                # sunlight envelope - measured on PNU 4115011300106840001, 23 of
                # 28 archived masses covered more than the 499.938 m2 limit, up
                # to 1.94x, and the downstream `bcr_limit_exceeded` gate threw
                # them away after a full legal materialization each.
                if coverage_capacity is not None:
                    seed_coverage = float(seed_union.area)
                    if seed_coverage <= 1e-9:
                        return None
                    scale_upper = min(
                        scale_upper,
                        sqrt(coverage_capacity / seed_coverage),
                    )
                    if scale_upper <= 1e-9:
                        return None
                maximum_contained = _maximum_contained_scale_multiplier(
                    matrix_at,
                    source_band_meshes=source_band_meshes,
                    legal_sections=legal_sections,
                    scale_upper=scale_upper,
                )
                if maximum_contained is None:
                    return None
                if minimum_aggregate_target_ratio >= 0.985:
                    minimum_required = _minimum_scale_multiplier(
                        matrix_at,
                        source_sections=source_sections,
                        legal_sections=legal_sections,
                        aggregate_target=aggregate_target,
                        source_min_z=min_z,
                        source_z_span=z_span,
                        scale_upper=scale_upper,
                    )
                    if (
                        minimum_required is None
                        or minimum_required > maximum_contained + 1e-7
                    ):
                        return None
                    scale_multiplier = minimum_required
                else:
                    scale_multiplier = maximum_contained
                if scale_multiplier <= 1e-9:
                    return None
                matrix = matrix_at(scale_multiplier)
                area_factor = scale_multiplier * scale_multiplier
                matrix_hash = _matrix_hash(matrix)
                screened = _screen_matrix(
                    matrix,
                    source_sections=source_sections,
                    source_band_meshes=source_band_meshes,
                    legal_sections=legal_sections,
                    aggregate_target=aggregate_target,
                    minimum_aggregate_target_ratio=(
                        minimum_aggregate_target_ratio
                    ),
                    source_min_z=min_z,
                    source_z_span=z_span,
                    orientation_degrees=orientation_degrees,
                    anisotropy=anisotropy,
                    area_factor=area_factor,
                    shear_factor=shear_factor,
                    matrix_hash=matrix_hash,
                )
                return (matrix_hash, screened)

    if len(pose_grid) > 1:
        with ThreadPoolExecutor(
            max_workers=min(len(pose_grid), _POSE_WORKERS)
        ) as pool:
            pose_results = list(pool.map(_evaluate_pose, pose_grid))
    else:
        pose_results = [_evaluate_pose(pose) for pose in pose_grid]

    for result in pose_results:
        if result is None:
            continue
        matrix_hash, screened = result
        if matrix_hash in seen_hashes:
            continue
        seen_hashes.add(matrix_hash)
        if screened is not None:
            alternatives.append(screened)
    alternatives.sort(key=lambda item: (
        item.profile_distortion,
        -item.minimum_floor_retention,
        -item.aggregate_retention,
        abs(item.aggregate_area_m2 - aggregate_target),
        item.matrix_hash,
    ))
    return tuple(alternatives)


def _pose_matrix(
    *,
    source_sections: tuple[Any, ...],
    legal_centroids: tuple[Any, ...],
    source_plan: Any,
    source_angle: float,
    target_angle: float,
    source_min_z: float,
    source_max_z: float,
    uniform_scale: float,
    anisotropy: float,
    shear_factor: float,
    scale_multiplier: float,
) -> Matrix4:
    source_z_span = source_max_z - source_min_z
    base = compose_matrix4(
        translation_matrix4((
            -source_plan.centroid.x,
            -source_plan.centroid.y,
            -source_min_z,
        )),
        rotation_matrix4((0.0, 0.0, -source_angle)),
        scale_matrix4((
            uniform_scale * anisotropy * scale_multiplier,
            uniform_scale / anisotropy * scale_multiplier,
            1.0 / source_z_span,
        )),
        rotation_matrix4((0.0, 0.0, target_angle)),
    )
    source_first = source_sections[0].centroid
    source_last = source_sections[-1].centroid
    base_first = transform_point3(
        base,
        (source_first.x, source_first.y, source_min_z),
    )
    base_last = transform_point3(
        base,
        (source_last.x, source_last.y, source_max_z),
    )
    source_delta = (
        base_last[0] - base_first[0],
        base_last[1] - base_first[1],
    )
    legal_delta = (
        legal_centroids[-1].x - legal_centroids[0].x,
        legal_centroids[-1].y - legal_centroids[0].y,
    )
    correction = (
        legal_delta[0] * shear_factor - source_delta[0],
        legal_delta[1] * shear_factor - source_delta[1],
    )
    shear = (
        (1.0, 0.0, correction[0], 0.0),
        (0.0, 1.0, correction[1], 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )
    residuals: list[tuple[float, float]] = []
    for floor_index, (source_section, legal_centroid) in enumerate(zip(
        source_sections,
        legal_centroids,
    )):
        normalized_z = (floor_index + 0.5) / len(legal_centroids)
        source_z = source_min_z + source_z_span * normalized_z
        source_centroid = source_section.centroid
        placed_centroid = transform_point3(
            base,
            (source_centroid.x, source_centroid.y, source_z),
        )
        residuals.append((
            legal_centroid.x
            - placed_centroid[0]
            - correction[0] * normalized_z,
            legal_centroid.y
            - placed_centroid[1]
            - correction[1] * normalized_z,
        ))
    centroid_residual = (
        sum(value[0] for value in residuals) / len(residuals),
        sum(value[1] for value in residuals) / len(residuals),
    )
    return compose_matrix4(
        base,
        shear,
        translation_matrix4((
            centroid_residual[0],
            centroid_residual[1],
            0.0,
        )),
    )


def _placed_sections(
    matrix: Matrix4,
    *,
    source_sections: tuple[Any, ...],
    source_min_z: float,
    source_z_span: float,
) -> tuple[Any, ...] | None:
    placed = []
    floor_count = len(source_sections)
    for index, source_section in enumerate(source_sections):
        source_z = (
            source_min_z
            + source_z_span * (index + 0.5) / floor_count
        )
        transformed = affine_transform(
            source_section,
            (
                matrix[0][0],
                matrix[0][1],
                matrix[1][0],
                matrix[1][1],
                matrix[0][2] * source_z + matrix[0][3],
                matrix[1][2] * source_z + matrix[1][3],
            ),
        )
        if transformed.is_empty or float(transformed.area) <= 1e-9:
            return None
        placed.append(transformed)
    return tuple(placed)


def _placed_closed_band_projections(
    matrix: Matrix4,
    *,
    source_band_meshes: tuple[Any, ...],
) -> tuple[Any, ...] | None:
    """Project every transformed triangle in each closed source z-band."""

    projected_bands = []
    for vertices, triangles in source_band_meshes:
        transformed = tuple(
            transform_point3(matrix, vertex)
            for vertex in vertices
        )
        projected_triangles = []
        for triangle in triangles:
            polygon = Polygon(tuple(
                (transformed[index][0], transformed[index][1])
                for index in triangle
            ))
            if polygon.is_valid and float(polygon.area) > 1e-12:
                projected_triangles.append(polygon)
        if not projected_triangles:
            return None
        try:
            projection = unary_union(projected_triangles)
        except GEOSException:
            # One numerically non-noded triangle soup is an invalid affine
            # alternative, not a reason to abort the entire portfolio run.
            # The caller will reject this matrix/candidate fail-closed.
            return None
        if projection.is_empty or not projection.is_valid:
            return None
        projected_bands.append(projection)
    return tuple(projected_bands)


def _convex_legal_halfspaces(
    legal_sections: tuple[Polygon, ...],
) -> tuple[Any, ...] | None:
    """Compile convex legal containers once into vectorized edge predicates."""

    compiled = []
    for polygon in legal_sections:
        if polygon.interiors:
            return None
        hull = polygon.convex_hull
        tolerance = max(1e-9, float(hull.area) * 1e-10)
        if abs(float(hull.area) - float(polygon.area)) > tolerance:
            return None
        coordinates = [
            (float(x), float(y))
            for x, y in list(polygon.exterior.coords)[:-1]
        ]
        if len(coordinates) < 3:
            return None
        signed_twice_area = sum(
            x0 * y1 - x1 * y0
            for (x0, y0), (x1, y1) in zip(
                coordinates,
                (*coordinates[1:], coordinates[0]),
            )
        )
        if signed_twice_area < 0.0:
            coordinates.reverse()
        rows = []
        for (x0, y0), (x1, y1) in zip(
            coordinates,
            (*coordinates[1:], coordinates[0]),
        ):
            dx = x1 - x0
            dy = y1 - y0
            length = sqrt(dx * dx + dy * dy)
            if length <= 1e-12:
                continue
            # CCW polygon interior is left of every directed edge:
            # -dy*x + dx*y + dy*x0 - dx*y0 >= 0.
            rows.append((
                -dy / length,
                dx / length,
                (dy * x0 - dx * y0) / length,
            ))
        if len(rows) < 3:
            return None
        compiled.append(np.asarray(rows, dtype=np.float64))
    return tuple(compiled)


def _convex_bands_contained(
    matrix: Matrix4,
    *,
    source_band_meshes: tuple[Any, ...],
    legal_halfspaces: tuple[Any, ...],
) -> bool:
    """Exact convex containment without rebuilding triangle polygons/unions."""

    if len(source_band_meshes) != len(legal_halfspaces):
        return False
    projection_matrix = np.asarray((
        (matrix[0][0], matrix[1][0]),
        (matrix[0][1], matrix[1][1]),
        (matrix[0][2], matrix[1][2]),
    ), dtype=np.float64)
    translation = np.asarray(
        (matrix[0][3], matrix[1][3]),
        dtype=np.float64,
    )
    for (vertices, _triangles), halfspaces in zip(
        source_band_meshes,
        legal_halfspaces,
    ):
        source = np.asarray(vertices, dtype=np.float64)
        if source.ndim != 2 or source.shape[1] < 3 or source.shape[0] == 0:
            return False
        projected = source[:, :3] @ projection_matrix + translation
        signed_distances = (
            projected @ halfspaces[:, :2].T
            + halfspaces[:, 2]
        )
        coordinate_scale = max(
            1.0,
            float(np.max(np.abs(projected))),
        )
        if float(np.min(signed_distances)) < -1e-8 * coordinate_scale:
            return False
    return True


def _general_bands_contained(
    matrix: Matrix4,
    *,
    source_band_meshes: tuple[Any, ...],
    legal_sections: tuple[Polygon, ...],
) -> bool:
    """Test concave legal containers in GEOS batches without unary unions."""

    if len(source_band_meshes) != len(legal_sections):
        return False
    projection_matrix = np.asarray((
        (matrix[0][0], matrix[1][0]),
        (matrix[0][1], matrix[1][1]),
        (matrix[0][2], matrix[1][2]),
    ), dtype=np.float64)
    translation = np.asarray(
        (matrix[0][3], matrix[1][3]),
        dtype=np.float64,
    )
    for (vertices, triangles), legal in zip(
        source_band_meshes,
        legal_sections,
    ):
        source = np.asarray(vertices, dtype=np.float64)
        triangle_indices = np.asarray(triangles, dtype=np.int64)
        if (
            source.ndim != 2
            or source.shape[1] < 3
            or triangle_indices.ndim != 2
            or triangle_indices.shape[1] != 3
            or triangle_indices.shape[0] == 0
        ):
            return False
        projected = source[:, :3] @ projection_matrix + translation
        triangle_coordinates = projected[triangle_indices]
        triangle_polygons = shapely.polygons(triangle_coordinates)
        # A ring of three finite points cannot self-intersect, so the only way
        # such a polygon is invalid is degeneracy, which the area floor already
        # removes. Dropping the validity pass removes one whole GEOS traversal
        # from the innermost containment bisection.
        usable = shapely.area(triangle_polygons) > 1e-12
        if not bool(np.any(usable)):
            return False
        if not bool(np.all(shapely.covers(
            legal,
            triangle_polygons[usable],
        ))):
            return False
    return True


def _minimum_scale_multiplier(
    matrix_at: Any,
    *,
    source_sections: tuple[Any, ...],
    legal_sections: tuple[Polygon, ...],
    aggregate_target: float,
    source_min_z: float,
    source_z_span: float,
    scale_upper: float,
) -> float | None:
    """Solve one aggregate-only 2D pose scale before bounded exact CSG."""

    required = min(
        sum(float(section.area) for section in legal_sections),
        aggregate_target / 0.985,
    )

    placement_valid = True

    def achieved(scale_multiplier: float) -> float:
        nonlocal placement_valid
        placed = _placed_sections(
            matrix_at(scale_multiplier),
            source_sections=source_sections,
            source_min_z=source_min_z,
            source_z_span=source_z_span,
        )
        if placed is None:
            placement_valid = False
            return 0.0
        placement_valid = True
        return sum(
            float(source.intersection(legal).area)
            for source, legal in zip(placed, legal_sections)
        )

    # The intersected area only grows with scale, so if the largest pose in the
    # search range still falls short, nothing smaller can reach the target. The
    # sweep below would spend twelve evaluations discovering that, and on this
    # parcel 85% of poses take exactly that path. Check the top once instead.
    # `achieved` reports 0.0 for a failed placement rather than a small area, so
    # only conclude from a pose that actually placed; the rest fall through to
    # the unchanged sweep.
    if achieved(scale_upper) + 1e-7 < required and placement_valid:
        return None

    sample_count = 12
    lower = 0.0
    upper = None
    for sample_index in range(1, sample_count + 1):
        probe = scale_upper * sample_index / sample_count
        if achieved(probe) + 1e-7 >= required:
            upper = probe
            break
        lower = probe
    if upper is None:
        return None
    for _iteration in range(12):
        probe = (lower + upper) / 2.0
        if achieved(probe) + 1e-7 >= required:
            upper = probe
        else:
            lower = probe
    return upper


def _maximum_contained_scale_multiplier(
    matrix_at: Any,
    *,
    source_band_meshes: tuple[Any, ...],
    legal_sections: tuple[Polygon, ...],
    scale_upper: float,
) -> float | None:
    """Maximize one unchanged affine body inside every legal floor section."""

    legal_halfspaces = _convex_legal_halfspaces(legal_sections)

    def contained(scale_multiplier: float) -> bool:
        matrix = matrix_at(scale_multiplier)
        if legal_halfspaces is not None:
            return _convex_bands_contained(
                matrix,
                source_band_meshes=source_band_meshes,
                legal_halfspaces=legal_halfspaces,
            )
        return _general_bands_contained(
            matrix,
            source_band_meshes=source_band_meshes,
            legal_sections=legal_sections,
        )

    sample_count = 24
    best = None
    first_invalid_after_best = None
    for sample_index in range(1, sample_count + 1):
        probe = scale_upper * sample_index / sample_count
        if contained(probe):
            best = probe
        elif best is not None:
            first_invalid_after_best = probe
            break
    if best is None:
        return None
    if first_invalid_after_best is None:
        return best * (1.0 - 1e-5)
    lower = best
    upper = first_invalid_after_best
    for _iteration in range(14):
        probe = (lower + upper) / 2.0
        if contained(probe):
            lower = probe
        else:
            upper = probe
    return lower * (1.0 - 1e-5)


def _screen_matrix(
    matrix: Matrix4,
    *,
    source_sections: tuple[Any, ...],
    source_band_meshes: tuple[Any, ...],
    legal_sections: tuple[Polygon, ...],
    aggregate_target: float,
    minimum_aggregate_target_ratio: float,
    source_min_z: float,
    source_z_span: float,
    orientation_degrees: int,
    anisotropy: float,
    area_factor: float,
    shear_factor: float,
    matrix_hash: str,
) -> _ScreenedAlternative | None:
    band_projections = _placed_closed_band_projections(
        matrix,
        source_band_meshes=source_band_meshes,
    )
    if (
        band_projections is None
        or len(band_projections) != len(legal_sections)
        or not all(
            legal.covers(projection)
            for projection, legal in zip(
                band_projections,
                legal_sections,
            )
        )
    ):
        return None
    preclip: list[float] = []
    clipped: list[float] = []
    retentions: list[float] = []
    floor_count = len(legal_sections)
    for index, (source_section, legal_section) in enumerate(zip(
        source_sections,
        legal_sections,
    )):
        normalized_z = (index + 0.5) / floor_count
        source_z = source_min_z + source_z_span * normalized_z
        transformed = affine_transform(
            source_section,
            (
                matrix[0][0],
                matrix[0][1],
                matrix[1][0],
                matrix[1][1],
                matrix[0][2] * source_z + matrix[0][3],
                matrix[1][2] * source_z + matrix[1][3],
            ),
        )
        clipped_section = transformed.intersection(legal_section)
        before = float(transformed.area)
        after = float(clipped_section.area)
        if (
            not isfinite(before)
            or not isfinite(after)
            or before <= 1e-9
            or after <= 1e-9
        ):
            return None
        preclip.append(before)
        clipped.append(after)
        retentions.append(after / before)
    aggregate = sum(clipped)
    if (
        aggregate + 1e-7
        < aggregate_target * minimum_aggregate_target_ratio
    ):
        return None
    return _ScreenedAlternative(
        matrix4=matrix,
        matrix_hash=matrix_hash,
        preclip_areas_m2=tuple(preclip),
        clipped_areas_m2=tuple(clipped),
        profile_distortion=_profile_distortion(preclip, clipped),
        aggregate_retention=sum(clipped) / max(sum(preclip), 1e-9),
        minimum_floor_retention=min(retentions),
        aggregate_area_m2=aggregate,
        orientation_degrees=orientation_degrees,
        anisotropy=round(anisotropy, 8),
        area_factor=area_factor,
        shear_factor=shear_factor,
    )


def _waterfill_plan_area(
    legal_caps: tuple[float, ...],
    aggregate_target: float,
) -> float:
    lower = 0.0
    upper = max(legal_caps)
    for _iteration in range(48):
        probe = (lower + upper) / 2.0
        achieved = sum(min(probe, cap) for cap in legal_caps)
        if achieved < aggregate_target:
            lower = probe
        else:
            upper = probe
    return upper


def _conservative_band_profile(
    authored: CompilationResult,
    matrix: Matrix4,
    final: CompilationResult,
    *,
    floor_count: int,
) -> tuple[tuple[float, ...], tuple[float, ...]] | None:
    """Measure the full band silhouettes used by the downstream source proxy."""

    bounds = (authored.metrics or {}).get("bounds") or ()
    if len(bounds) != 2:
        return None
    source_min_z = float(bounds[0][2])
    source_span = float(bounds[1][2]) - source_min_z
    if source_span <= 1e-9:
        return None
    preclip: list[float] = []
    clipped: list[float] = []
    for floor_index in range(floor_count):
        source_polygons = []
        final_polygons = []
        for offset in (0.03, 0.5, 0.97):
            normalized_z = (floor_index + offset) / floor_count
            source_z = source_min_z + source_span * normalized_z
            source_section = _mesh_section_polygon(authored, source_z)
            final_section = _mesh_section_polygon(final, normalized_z)
            if source_section is None or final_section is None:
                return None
            source_polygons.append(affine_transform(
                source_section,
                (
                    matrix[0][0],
                    matrix[0][1],
                    matrix[1][0],
                    matrix[1][1],
                    matrix[0][2] * source_z + matrix[0][3],
                    matrix[1][2] * source_z + matrix[1][3],
                ),
            ))
            final_polygons.append(final_section)
        source_union = unary_union(source_polygons)
        final_union = unary_union(final_polygons)
        before = float(source_union.area)
        after = float(final_union.area)
        if min(before, after) <= 1e-9:
            return None
        preclip.append(before)
        clipped.append(after)
    return tuple(preclip), tuple(clipped)


def _profile_distortion(
    authored_areas: Any,
    final_areas: Any,
) -> float:
    authored = tuple(float(value) for value in authored_areas)
    final = tuple(float(value) for value in final_areas)
    authored_total = max(sum(authored), 1e-9)
    final_total = max(sum(final), 1e-9)
    return sum(
        abs(
            authored_area / authored_total
            - final_area / final_total
        )
        for authored_area, final_area in zip(authored, final)
    )


def _principal_frame(polygon: Any) -> tuple[float, float, float]:
    rectangle = polygon.minimum_rotated_rectangle
    coordinates = list(rectangle.exterior.coords)[:4]
    edges = [
        (
            sqrt(
                (coordinates[(index + 1) % 4][0] - coordinates[index][0]) ** 2
                + (coordinates[(index + 1) % 4][1] - coordinates[index][1]) ** 2
            ),
            coordinates[index],
            coordinates[(index + 1) % 4],
        )
        for index in range(4)
    ]
    longest = max(edges, key=lambda edge: edge[0])
    shortest = min(edge[0] for edge in edges)
    angle = degrees(atan2(
        longest[2][1] - longest[1][1],
        longest[2][0] - longest[1][0],
    ))
    return angle, longest[0], shortest


def _matrix_hash(matrix: Matrix4) -> str:
    payload = [
        [round(float(value), 12) for value in row]
        for row in matrix
    ]
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _unique_floats(values: tuple[float, ...]) -> tuple[float, ...]:
    result: list[float] = []
    for value in values:
        if not any(abs(value - existing) <= 1e-8 for existing in result):
            result.append(value)
    return tuple(result)


def _exact_shortlist(
    alternatives: tuple[_ScreenedAlternative, ...],
    *,
    limit: int,
) -> tuple[_ScreenedAlternative, ...]:
    """Cover distinct axis responses without compiling 180-degree twins."""

    groups: dict[float, list[_ScreenedAlternative]] = {}
    for alternative in alternatives:
        group = groups.setdefault(alternative.anisotropy, [])
        if any(
            existing.shear_factor == alternative.shear_factor
            for existing in group
        ):
            continue
        group.append(alternative)
    selected: list[_ScreenedAlternative] = []
    for records in groups.values():
        selected.append(records[0])
        if len(selected) >= limit:
            return tuple(selected)
    for anisotropy in sorted(groups):
        records = groups[anisotropy]
        if len(records) > 1:
            # Spend the second exact slot on the next-best screened response,
            # beginning with the strongest distinct axis response rather than
            # a numerically different 180-degree twin of the same pose.
            selected.append(records[1])
        if len(selected) >= limit:
            return tuple(selected)
    for records in groups.values():
        for record in records[2:]:
            selected.append(record)
            if len(selected) >= limit:
                return tuple(selected)
    return tuple(selected)


__all__ = [
    "LegalFieldAffineSelection",
    "is_intentional_floorwise_stepped_program",
    "select_legal_field_affine_projection",
]
