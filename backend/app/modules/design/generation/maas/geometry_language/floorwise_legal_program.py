"""Append floorwise legal CSG projection to one authored GeometryProgram.

The authored, site-placed root remains in the same DAG.  Horizontal floor
bands are Matrix4 instances of its existing canonical UnitBox.  Each band
isolates the authored root and is intersected with its exact legal prism
before the bands are unioned.  Capacity targets remain advisory evidence;
they never rescale an authored floor.  No sibling mesh or interpolated matrix
field is created.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from math import hypot, isfinite
from typing import Any

from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, unary_union

from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import Matrix4, identity_matrix4, matrix4_to_lists
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult, compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.gate import GeometryGatePolicy, compilation_gate


_LEGAL_CLIP_INSET_M = GeometryGatePolicy().minimum_edge_length * 2.0
_INTENTIONAL_FLOORWISE_STEP_OPERATORS = frozenset({
    "setback",
    "stepped_mass",
    "terrace",
})


@dataclass(frozen=True)
class FloorwiseLegalProgramResult:
    program: GeometryProgram
    floor_matrices: tuple[Matrix4, ...]
    achieved_floor_areas_m2: tuple[float, ...]
    certificate: dict[str, Any]
    final_compilation: CompilationResult


def is_intentional_floorwise_stepped_program(
    program: GeometryProgram,
) -> bool:
    """Whether a live ancestor of the executable root authors a step verb."""

    nodes_by_id = {node.id: node for node in program.nodes}
    pending = [program.root_id]
    visited: set[str] = set()
    while pending:
        node_id = pending.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        node = nodes_by_id.get(node_id)
        if node is None:
            return False
        if node.operator in _INTENTIONAL_FLOORWISE_STEP_OPERATORS:
            return True
        pending.extend(node.inputs)
    return False


def append_floorwise_legal_projection(
    program: GeometryProgram,
    *,
    legal_sections: tuple[Polygon, ...],
    target_floor_areas_m2: tuple[float, ...],
    floor_capacity_plan_hash: str,
) -> FloorwiseLegalProgramResult | None:
    """Return one final floorwise legal solid, or ``None`` when uncertifiable."""

    if not _valid_request(
        program,
        legal_sections=legal_sections,
        target_floor_areas_m2=target_floor_areas_m2,
        floor_capacity_plan_hash=floor_capacity_plan_hash,
    ):
        return None
    if not is_intentional_floorwise_stepped_program(program):
        return None
    authored = compile_geometry_program(program)
    if not _compiled_manifold(authored):
        return None
    bounds = (authored.metrics or {}).get("bounds") or ()
    if (
        len(bounds) != 2
        or len(bounds[0]) != 3
        or len(bounds[1]) != 3
    ):
        return None
    min_x, min_y, min_z = (float(value) for value in bounds[0])
    max_x, max_y, max_z = (float(value) for value in bounds[1])
    floor_count = len(legal_sections)
    floor_height = (max_z - min_z) / floor_count
    if (
        not all(isfinite(value) for value in (
            min_x, min_y, min_z, max_x, max_y, max_z, floor_height,
        ))
        or min(max_x - min_x, max_y - min_y, floor_height) <= 1e-9
    ):
        return None
    plan_padding = max(
        1e-4,
        max(max_x - min_x, max_y - min_y) * 1e-7,
    )

    unit_id = next(
        node.id
        for node in program.nodes
        if node.kind == "primitive"
    )
    occupied_ids = {node.id for node in program.nodes}
    appended: list[GeometryNode] = []
    floor_matrices: list[Matrix4] = []
    clip_ids: list[str] = []
    clip_node_ids: list[str] = []
    floor_ranges: list[tuple[float, float]] = []

    for floor_index, (legal_section, target_area) in enumerate(
        zip(legal_sections, target_floor_areas_m2)
    ):
        lower_z = min_z + floor_height * floor_index
        upper_z = (
            max_z
            if floor_index == floor_count - 1
            else min_z + floor_height * (floor_index + 1)
        )
        # The floor-capacity vector is advisory provenance, not a geometry
        # author.  Identity is retained in the public floor-matrix contract so
        # every downstream consumer applies the same already-authored pose.
        matrix = identity_matrix4()
        floor_matrices.append(matrix)
        floor_ranges.append((lower_z, upper_z))

        common = {
            "floor_index": floor_index,
        }
        band_id = _unique_id(
            f"floor_{floor_index:02d}_band_matrix4",
            occupied_ids,
        )
        appended.append(GeometryNode(
            band_id,
            "transform",
            "matrix4",
            inputs=(unit_id,),
            parameters={
                "matrix4": matrix4_to_lists((
                    (
                        max_x - min_x + plan_padding * 2.0,
                        0.0,
                        0.0,
                        min_x - plan_padding,
                    ),
                    (
                        0.0,
                        max_y - min_y + plan_padding * 2.0,
                        0.0,
                        min_y - plan_padding,
                    ),
                    (0.0, 0.0, upper_z - lower_z, lower_z),
                    (0.0, 0.0, 0.0, 1.0),
                )),
                "lower_z": lower_z,
                "upper_z": upper_z,
                **common,
            },
            semantic_role="floorwise_horizontal_band",
            provenance={"source": "canonical_unitbox_floor_band"},
        ))
        isolated_id = _unique_id(
            f"floor_{floor_index:02d}_authored_intersection",
            occupied_ids,
        )
        appended.append(GeometryNode(
            isolated_id,
            "boolean",
            "intersection",
            inputs=(program.root_id, band_id),
            parameters=dict(common),
            semantic_role="floorwise_authored_band",
            provenance={"source": "authored_site_root"},
        ))
        clip_id = _unique_id(
            f"floor_{floor_index:02d}_legal_section_clip",
            occupied_ids,
        )
        clip_node_ids.append(clip_id)
        clip_ids.append(clip_id)
        # Manifold CSG can leave a sub-micrometre boundary sliver outside an
        # otherwise identical GEOS legal polygon.  Build the final solid
        # against a tiny interior kernel margin so the exported mesh and its
        # measured SourceVolume proxies satisfy the original, unbuffered legal
        # section used by every downstream gate.
        legal_clip_inset_m = _LEGAL_CLIP_INSET_M
        legal_clip_section = legal_section.buffer(
            -legal_clip_inset_m,
            join_style=2,
        )
        if (
            not isinstance(legal_clip_section, Polygon)
            or legal_clip_section.is_empty
            or not legal_clip_section.is_valid
            or float(legal_clip_section.area) <= 1e-9
        ):
            return None
        legal_parameters = _legal_section_parameters(legal_clip_section)
        appended.append(GeometryNode(
            clip_id,
            "modifier",
            "legal_section_clip",
            inputs=(isolated_id,),
            parameters={
                **legal_parameters,
                "lower_z": lower_z,
                "upper_z": upper_z,
                "matrix_mode": "authored_identity_legal_csg",
                "achieved_floor_area_m2": 0.0,
                "legal_clip_inset_m": legal_clip_inset_m,
                **common,
            },
            semantic_role="floorwise_legal_section",
            provenance={"source": "floorwise_legal_csg_projection"},
        ))

    union_id = _unique_id("floorwise_legal_union", occupied_ids)
    union_inputs = tuple(clip_ids) if len(clip_ids) > 1 else (clip_ids[0], clip_ids[0])
    appended.append(GeometryNode(
        union_id,
        "boolean",
        "union",
        inputs=union_inputs,
        parameters={
            "floor_count": floor_count,
            "matrix_interpolation": False,
        },
        semantic_role="final_floorwise_legal_solid",
        provenance={
            "source": "authored_band_legal_csg",
            "authored_program_hash": program.program_hash(),
        },
    ))
    projected = replace(
        program,
        nodes=tuple(deepcopy(program.nodes)) + tuple(appended),
        root_id=union_id,
        metadata={
            **deepcopy(program.metadata),
            "floorwise_legal_projection": {
                "schema_version": "arr.maas.floorwise_legal_program.v1",
                "authored_program_hash": program.program_hash(),
                "floor_capacity_plan_hash": floor_capacity_plan_hash,
                "projection_mode": "intentional_floorwise_stepped",
                "target_floor_areas_m2": [
                    round(float(value), 8)
                    for value in target_floor_areas_m2
                ],
                "matrix_interpolation": False,
                "projected_surface_only": False,
                "matrix_mode": "authored_identity_legal_csg",
            },
        },
    )

    preliminary = compile_geometry_program(projected)
    measured = _measure_floor_evidence(
        preliminary,
        legal_sections=legal_sections,
        floor_ranges=tuple(floor_ranges),
        floor_matrices=tuple(floor_matrices),
        target_floor_areas_m2=target_floor_areas_m2,
    )
    if measured is None:
        return None
    achieved, _preliminary_evidence = measured
    achieved_by_id = {
        node_id: round(achieved[index], 8)
        for index in range(floor_count)
        for node_id in (clip_node_ids[index],)
    }
    finalized_nodes = tuple(
        replace(
            node,
            parameters={
                **node.parameters,
                "achieved_floor_area_m2": achieved_by_id[node.id],
            },
        )
        if node.id in achieved_by_id
        else node
        for node in projected.nodes
    )
    finalized = replace(projected, nodes=finalized_nodes)
    final_compilation = compile_geometry_program(finalized)
    if compilation_gate(
        final_compilation,
        GeometryGatePolicy(maximum_components=1),
    ):
        return None
    final_measured = _measure_floor_evidence(
        final_compilation,
        legal_sections=legal_sections,
        floor_ranges=tuple(floor_ranges),
        floor_matrices=tuple(floor_matrices),
        target_floor_areas_m2=target_floor_areas_m2,
    )
    if final_measured is None:
        return None
    final_achieved, floor_evidence = final_measured
    aggregate_target = sum(
        float(value) for value in target_floor_areas_m2
    )
    achieved_total = sum(final_achieved)
    if achieved_total + 1e-7 < aggregate_target * 0.995:
        return None
    finite_coordinates = all(
        isfinite(value)
        for vertex in final_compilation.vertices
        for value in vertex
    )
    certificate = {
        "schema_version": "arr.maas.floorwise_legal_program.v1",
        "status": "certified",
        "hard_pass": True,
        "authored_program_hash": program.program_hash(),
        "final_program_hash": finalized.program_hash(),
        "final_geometry_hash": final_compilation.geometry_hash,
        "floor_capacity_plan_hash": floor_capacity_plan_hash,
        "floor_count": floor_count,
        "projection_mode": "intentional_floorwise_stepped",
        "matrix_interpolation": False,
        "projected_surface_only": False,
        "matrix_mode": "authored_identity_legal_csg",
        "legal_clip_inset_m": _LEGAL_CLIP_INSET_M,
        "finite_coordinates": finite_coordinates,
        "manifold": bool(final_compilation.metrics.get("manifold")),
        "watertight": bool(final_compilation.metrics.get("watertight")),
        "all_sections_contained": all(
            evidence["contained"] for evidence in floor_evidence
        ),
        "capacity_threshold_ratio": 0.995,
        "aggregate_target_area_m2": round(aggregate_target, 8),
        "achieved_aggregate_area_m2": round(achieved_total, 8),
        "achieved_floor_areas_m2": [
            round(value, 8) for value in final_achieved
        ],
        "target_floor_areas_m2": [
            round(float(value), 8)
            for value in target_floor_areas_m2
        ],
        "floor_evidence": list(floor_evidence),
    }
    finalized = replace(
        finalized,
        metadata={
            **deepcopy(finalized.metadata),
            "floorwise_legal_projection": deepcopy(certificate),
        },
    )
    return FloorwiseLegalProgramResult(
        program=finalized,
        floor_matrices=tuple(floor_matrices),
        achieved_floor_areas_m2=final_achieved,
        certificate=certificate,
        final_compilation=final_compilation,
    )


def _valid_request(
    program: GeometryProgram,
    *,
    legal_sections: tuple[Polygon, ...],
    target_floor_areas_m2: tuple[float, ...],
    floor_capacity_plan_hash: str,
) -> bool:
    primitives = tuple(node for node in program.nodes if node.kind == "primitive")
    return bool(
        _valid_legal_context(
            program,
            legal_sections=legal_sections,
            target_floor_areas_m2=target_floor_areas_m2,
            floor_capacity_plan_hash=floor_capacity_plan_hash,
        )
        and len(primitives) == 1
        and primitives[0].operator == "box"
        and primitives[0].parameters
        == {"width": 1.0, "depth": 1.0, "height": 1.0}
    )


def _valid_legal_context(
    program: GeometryProgram,
    *,
    legal_sections: tuple[Polygon, ...],
    target_floor_areas_m2: tuple[float, ...],
    floor_capacity_plan_hash: str,
) -> bool:
    """Validate law/placement inputs without constraining authored topology."""

    return bool(
        floor_capacity_plan_hash.strip()
        and legal_sections
        and len(legal_sections) == len(target_floor_areas_m2)
        and isinstance(program.metadata.get("site_placement"), dict)
        and all(
            isinstance(section, Polygon)
            and not section.is_empty
            and section.is_valid
            and isfinite(float(section.area))
            and float(section.area) > 1e-9
            and _finite_polygon(section)
            for section in legal_sections
        )
        and all(
            isfinite(float(value)) and float(value) > 1e-9
            for value in target_floor_areas_m2
        )
    )


def _compiled_manifold(compilation: CompilationResult) -> bool:
    return bool(
        compilation.status == "compiled"
        and compilation.vertices
        and compilation.triangles
        and compilation.metrics.get("manifold")
        and compilation.metrics.get("watertight")
        and all(
            isfinite(value)
            for vertex in compilation.vertices
            for value in vertex
        )
    )


def _legal_section_parameters(section: Polygon) -> dict[str, Any]:
    normalized = orient(section, sign=1.0)
    return {
        "exterior": [
            [float(x), float(y)]
            for x, y in list(normalized.exterior.coords)[:-1]
        ],
        "holes": [
            [
                [float(x), float(y)]
                for x, y in list(interior.coords)[:-1]
            ]
            for interior in normalized.interiors
        ],
    }


def _measure_floor_evidence(
    compilation: CompilationResult,
    *,
    legal_sections: tuple[Polygon, ...],
    floor_ranges: tuple[tuple[float, float], ...],
    floor_matrices: tuple[Matrix4, ...],
    target_floor_areas_m2: tuple[float, ...],
    matrix_mode: str = "authored_identity_legal_csg",
) -> tuple[tuple[float, ...], tuple[dict[str, Any], ...]] | None:
    if not _compiled_manifold(compilation):
        return None
    achieved: list[float] = []
    evidence_rows: list[dict[str, Any]] = []
    for floor_index, (
        legal_section,
        (lower_z, upper_z),
        matrix,
        target_area,
    ) in enumerate(zip(
        legal_sections,
        floor_ranges,
        floor_matrices,
        target_floor_areas_m2,
    )):
        height = upper_z - lower_z
        inset = max(1e-7, min(height * 1e-4, 1e-4))
        sample_z = (
            lower_z + inset,
            (lower_z + upper_z) / 2.0,
            upper_z - inset,
        )
        sections = tuple(
            _mesh_section_polygon(compilation, z)
            for z in sample_z
        )
        if any(
            section is None
            or section.is_empty
            or not isfinite(float(section.area))
            or float(section.area) <= 1e-9
            for section in sections
        ):
            return None
        sample_areas = tuple(float(section.area) for section in sections)
        sample_sections_contained = all(
            section.within(legal_section) or legal_section.covers(section)
            for section in sections
        )
        projected_band = _project_mesh_closed_z_band(
            compilation,
            lower_z=lower_z,
            upper_z=upper_z,
        )
        if projected_band is None or projected_band.is_empty:
            return None
        contained = bool(
            projected_band.within(legal_section)
            or legal_section.covers(projected_band)
        )
        if not contained:
            return None
        containment_margin = float(
            legal_section.boundary.distance(projected_band)
        )
        mid_area = sample_areas[1]
        achieved.append(mid_area)
        evidence_rows.append({
            "floor_index": floor_index,
            "lower_z_m": lower_z,
            "upper_z_m": upper_z,
            "sample_z_m": list(sample_z),
            "sample_areas_m2": [round(value, 8) for value in sample_areas],
            "target_floor_area_m2": round(float(target_area), 8),
            "achieved_floor_area_m2": round(mid_area, 8),
            "contained": contained,
            "sample_sections_contained": sample_sections_contained,
            "containment_authority": "closed_z_band_projected_mesh",
            "projected_band_area_m2": round(
                float(projected_band.area),
                8,
            ),
            "containment_margin_m": round(containment_margin, 8),
            "matrix_mode": matrix_mode,
            "matrix4": matrix4_to_lists(matrix),
        })
    return tuple(achieved), tuple(evidence_rows)


def _project_mesh_closed_z_band(
    compilation: CompilationResult,
    *,
    lower_z: float,
    upper_z: float,
):
    solid = getattr(compilation, "_solid", None)
    if solid is None:
        return None
    band_solid = solid.trim_by_plane(
        (0.0, 0.0, 1.0),
        float(lower_z),
    ).trim_by_plane(
        (0.0, 0.0, -1.0),
        -float(upper_z),
    )
    if band_solid.is_empty():
        return None
    band_volume = float(band_solid.volume())
    if not isfinite(band_volume) or band_volume <= 1e-12:
        return None
    mesh = band_solid.to_mesh64()
    vertices = tuple(
        tuple(float(value) for value in row[:3])
        for row in mesh.vert_properties
    )
    projected = []
    for triangle in mesh.tri_verts:
        xy = tuple(
            (vertices[int(index)][0], vertices[int(index)][1])
            for index in triangle
        )
        polygon = Polygon(xy)
        if polygon.is_valid and float(polygon.area) > 1e-12:
            projected.append(polygon)
    if not projected:
        return None
    authority = unary_union(projected)
    if authority.is_empty or float(authority.area) <= 1e-12:
        return None
    return authority


def _mesh_section_polygon(
    compilation: CompilationResult,
    z: float,
):
    solid = getattr(compilation, "_solid", None)
    if solid is not None:
        contours = tuple(solid.slice(float(z)).to_polygons())
        section = None
        for contour in contours:
            polygon = Polygon(tuple(
                (float(point[0]), float(point[1]))
                for point in contour
            ))
            if polygon.is_empty or not polygon.is_valid or polygon.area <= 1e-10:
                continue
            section = (
                polygon
                if section is None
                else section.symmetric_difference(polygon)
            )
        if section is not None and not section.is_empty:
            return section

    segments: list[LineString] = []
    epsilon = 1e-7
    for triangle in compilation.triangles:
        points = [compilation.vertices[index] for index in triangle]
        intersections: list[tuple[float, float]] = []
        for left, right in zip(points, (*points[1:], points[0])):
            left_z, right_z = left[2] - z, right[2] - z
            if abs(left_z) <= epsilon:
                intersections.append((left[0], left[1]))
            if left_z * right_z < -(epsilon * epsilon):
                amount = (z - left[2]) / (right[2] - left[2])
                intersections.append((
                    left[0] + (right[0] - left[0]) * amount,
                    left[1] + (right[1] - left[1]) * amount,
                ))
        unique: list[tuple[float, float]] = []
        for point in intersections:
            if not any(
                hypot(point[0] - other[0], point[1] - other[1]) <= 1e-6
                for other in unique
            ):
                unique.append(point)
        if len(unique) >= 2:
            segment = tuple(
                (round(float(point[0]), 8), round(float(point[1]), 8))
                for point in unique[:2]
            )
            if segment[0] != segment[1]:
                segments.append(LineString(segment))
    if not segments:
        return None
    polygons = tuple(polygonize(unary_union(segments)))
    if not polygons:
        return None
    hole_regions = tuple(
        Polygon(interior)
        for polygon in polygons
        for interior in polygon.interiors
    )
    retained = tuple(
        polygon
        for polygon in polygons
        if not any(
            hole.covers(polygon.representative_point())
            for hole in hole_regions
        )
    )
    return unary_union(retained or polygons)


def _finite_polygon(section: Polygon) -> bool:
    return all(
        isfinite(value)
        for ring in (section.exterior, *section.interiors)
        for coordinate in ring.coords
        for value in coordinate[:2]
    )


def _unique_id(base: str, occupied: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in occupied:
        candidate = f"{base}_{suffix}"
        suffix += 1
    occupied.add(candidate)
    return candidate


__all__ = [
    "FloorwiseLegalProgramResult",
    "append_floorwise_legal_projection",
    "is_intentional_floorwise_stepped_program",
]
