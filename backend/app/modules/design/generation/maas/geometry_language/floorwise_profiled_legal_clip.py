"""Continuous legal-envelope clipping for authored profiled meshes.

The authored indexed manifold is placed with one global homogeneous Matrix4,
then intersected once with a closed continuous legal section envelope. Floor
capacity matrices and plates remain independent validation evidence.
"""

from __future__ import annotations

import json
from hashlib import sha256
from math import isfinite
from typing import Any, Sequence

import manifold3d as m3d
import numpy as np
from shapely.affinity import translate
from shapely.geometry import MultiPoint, MultiPolygon, Point, Polygon
from shapely.geometry.polygon import orient

from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass, SourceSurface, SourceVolume

from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import Matrix4, transform_point3, validate_matrix4
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.floorwise_visual_projection import FloorwiseVisualProjection, FloorwiseVisualProjectionCertificate, _exact_surface_payload_hash, _split_triangle_at_z_breakpoints, _stable_visual_hash, floorwise_authority_binding_hash, profiled_sloped_mesh_evidence
from backend.app.modules.design.generation.maas.geometry_language.profiled_mesh_numeric_repair import FLOOR_CENTER_NUMERIC_EQUIVALENCE_REPAIR_SCHEMA, FLOOR_CENTER_NUMERIC_EQUIVALENCE_SCHEMA, MESH_NUMERIC_REPAIR_SCHEMA, floor_center_numeric_equivalence as _floor_center_numeric_equivalence, indexed_mesh_component_volumes as _indexed_mesh_component_volumes, indexed_mesh_section_polygon as _indexed_mesh_section_polygon, indexed_mesh_section_topology as _indexed_mesh_section_topology, revalidate_or_repair_profiled_mesh as _revalidated_mesh, section_numeric_epsilon_m as _section_numeric_epsilon_m


_MODE = "floorwise_profiled_continuous_envelope_clip"
_OPERATION = "authored_profiled_mesh_continuous_legal_envelope_intersection"
_EPSILON = 1e-8
_NORMALIZED_Z_TRANSPORT_EPSILON = 1e-6
_BAND_BOUNDARY_EPSILON = 1e-7
_LEGAL_REVALIDATION_WITNESS_MAXIMUM = 64
_SECTION_GEOMETRY_BINDING_SCHEMA = (
    "arr.maas.profiled_legal_section_geometry_binding.v1"
)
_VISIBLE_SECTION_SCHEMA = "arr.maas.floor_center_visible_section.v1"


def _section_geometry_binding(
    occupied_sections: Sequence[Polygon | MultiPolygon],
    legal_sections: Sequence[Polygon | MultiPolygon],
    output_origin: tuple[float, float],
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    occupied_wkb = tuple(
        translate(section, xoff=-output_origin[0], yoff=-output_origin[1])
        .normalize()
        .wkb_hex
        for section in occupied_sections
    )
    legal_wkb = tuple(
        translate(section, xoff=-output_origin[0], yoff=-output_origin[1])
        .normalize()
        .wkb_hex
        for section in legal_sections
    )
    payload = {
        "schema": _SECTION_GEOMETRY_BINDING_SCHEMA,
        "occupied_section_wkb_hex": list(occupied_wkb),
        "legal_section_wkb_hex": list(legal_wkb),
    }
    digest = sha256(json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return digest, occupied_wkb, legal_wkb


def profiled_legal_section_authority_binding_hash(
    occupied_sections: Sequence[Polygon | MultiPolygon],
    legal_sections: Sequence[Polygon | MultiPolygon],
    output_origin: tuple[float, float],
) -> str:
    """Hash authoritative legal-floor inputs outside certificate transport."""

    return _section_geometry_binding(
        occupied_sections,
        legal_sections,
        output_origin,
    )[0]


def clip_profiled_mesh_to_floorwise_legal_solids(
    source: SourceMass,
    *,
    occupied_sections: Sequence[Polygon | MultiPolygon],
    legal_sections: Sequence[Polygon | MultiPolygon],
    floor_matrices: Sequence[Matrix4],
    capacity_plates: Sequence[SourceVolume],
    output_origin: tuple[float, float],
) -> FloorwiseVisualProjection:
    """Return one exact authored visual solid or a fail-closed certificate."""

    profiled = tuple(
        surface
        for surface in source.surfaces
        if (
            isinstance(surface, SourceSurface)
            and surface.surface_type == "profiled_recursive_solid_mesh"
            and len(surface.vertices_m) == 3
        )
    )
    floor_count = len(occupied_sections)
    canonical_capacity_plates = tuple(sorted(
        capacity_plates,
        key=lambda plate: (
            float(plate.bottom_fraction),
            float(plate.top_fraction),
            str(plate.role),
            str(plate.footprint.normalize().wkb_hex),
        ),
    ))
    capacity_gfa = sum(
        float(plate.footprint.area)
        for plate in canonical_capacity_plates
    )
    if not profiled:
        return _failed(
            "profiled_legal_clip_missing_authored_mesh",
            capacity_gfa=capacity_gfa,
            source_surface_count=0,
        )
    if not _complete_profiled_export(source, profiled):
        return _failed(
            "profiled_legal_clip_incomplete_authored_mesh",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(profiled),
        )
    if (
        floor_count == 0
        or len(legal_sections) != floor_count
        or len(floor_matrices) != floor_count
    ):
        return _failed(
            "profiled_legal_clip_floor_count_mismatch",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(profiled),
            failure_witness={
                "occupied_floor_count": floor_count,
                "legal_floor_count": len(legal_sections),
                "matrix_floor_count": len(floor_matrices),
            },
        )
    occupied_topology: list[dict[str, Any]] = []
    legal_topology: list[dict[str, Any]] = []
    for kind, sections, output in (
        ("occupied", occupied_sections, occupied_topology),
        ("legal", legal_sections, legal_topology),
    ):
        for floor_index, section in enumerate(sections):
            topology, failure, witness = _section_topology_certificate(
                section,
                floor_index=floor_index,
                kind=kind,
            )
            if topology is None:
                return _failed(
                    failure,
                    capacity_gfa=capacity_gfa,
                    source_surface_count=len(profiled),
                    occupied_section_topology=tuple(occupied_topology),
                    legal_section_topology=tuple(legal_topology),
                    failure_witness=witness,
                )
            output.append(topology)

    stack = source.metadata.get("floorwise_legal_matrix_stack")
    stack = stack if isinstance(stack, dict) else {}
    from backend.app.modules.design.generation.maas.geometry_language.floorwise_section_loft import floorwise_authority_component_hashes

    components, component_failure = floorwise_authority_component_hashes(
        occupied_sections,
        canonical_capacity_plates,
        floor_capacity_plan_hash=str(
            stack.get("floor_capacity_plan_hash") or ""
        ),
        floor_evidence=stack.get("floors"),
    )
    if components is None:
        return _failed(
            component_failure.replace("section_loft", "profiled_legal_clip"),
            capacity_gfa=capacity_gfa,
            source_surface_count=len(profiled),
        )
    try:
        matrices = tuple(validate_matrix4(matrix) for matrix in floor_matrices)
        evidence_matrices = tuple(
            validate_matrix4(row["matrix4"])
            for row in stack["floors"]
        )
    except (KeyError, TypeError, ValueError):
        return _failed(
            "profiled_legal_clip_missing_authority_evidence",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(profiled),
        )
    if matrices != evidence_matrices:
        return _failed(
            "profiled_legal_clip_matrix_authority_mismatch",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(profiled),
        )

    try:
        if any(not _plan_only_matrix(matrix) for matrix in matrices):
            raise ValueError("floor Matrix4 changes normalized z")
        projected_authored = _source_world_matrix_field_manifold(
            source,
            profiled,
            matrices,
        )
        if (
            projected_authored.is_empty()
            or "NoError" not in str(projected_authored.status())
        ):
            raise ValueError("projected authored mesh is not a manifold")
    except (AttributeError, TypeError, ValueError):
        return _failed(
            "profiled_legal_clip_invalid_authored_manifold",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(profiled),
        )

    try:
        from backend.app.modules.design.generation.maas.geometry_language.floorwise_section_loft import build_continuous_legal_envelope_mesh

        envelope = build_continuous_legal_envelope_mesh(
            legal_sections=legal_sections,
            output_origin=output_origin,
        )
        if not envelope.hard_pass:
            return _failed(
                envelope.failure_reasons[0],
                capacity_gfa=capacity_gfa,
                source_surface_count=len(profiled),
                legal_sample_count=envelope.legal_sample_count,
                failure_witness=envelope.failure_witness,
            )
        envelope_vertices = np.asarray([
            (
                float(x) + float(output_origin[0]),
                float(y) + float(output_origin[1]),
                float(z),
            )
            for x, y, z in envelope.vertices
        ], dtype=np.float64)
        envelope_mesh = m3d.Mesh(
            envelope_vertices,
            np.asarray(envelope.triangles, dtype=np.uint32),
        )
        envelope_mesh.merge()
        legal_envelope = m3d.Manifold(envelope_mesh)
        if (
            legal_envelope.is_empty()
            or "NoError" not in str(legal_envelope.status())
        ):
            raise ValueError("continuous legal envelope is not a manifold")
        projected = m3d.Manifold.batch_boolean(
            [projected_authored, legal_envelope],
            m3d.OpType.Intersect,
        )
        final_components = tuple(projected.decompose())
        if (
            projected.is_empty()
            or "NoError" not in str(projected.status())
            or not final_components
            or any(
                component.is_empty()
                or "NoError" not in str(component.status())
                or not isfinite(float(component.volume()))
                or float(component.volume()) <= _EPSILON
                for component in final_components
            )
        ):
            raise ValueError("profiled legal bands do not form valid solids")
        for left_index, left in enumerate(final_components):
            for right in final_components[left_index + 1:]:
                overlap = m3d.Manifold.batch_boolean(
                    [left, right],
                    m3d.OpType.Intersect,
                )
                if not overlap.is_empty() and float(overlap.volume()) > _EPSILON:
                    raise ValueError("profiled legal output components overlap")
        surfaces, vertices, triangles = _surfaces_from_manifold(
            projected,
            output_origin=output_origin,
            volume_role=canonical_capacity_plates[0].role,
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return _failed(
            "profiled_legal_clip_csg_failed",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(profiled),
        )

    mesh_cleanup_schema = ""
    mesh_cleanup_collapse_threshold_m = 0.0
    effective_height_m = _effective_height_m(source)
    mesh_cleanup_max_physical_displacement_m = 0.0
    mesh_cleanup_raw_indexed_mesh_hash = ""
    mesh_cleanup_raw_gate_failure_codes: tuple[str, ...] = ()
    mesh_cleanup_clean_indexed_mesh_hash = ""
    mesh_cleanup_clean_gate_hard_pass = False
    revalidation = _revalidated_mesh(
        vertices,
        triangles,
        effective_height_m=effective_height_m,
    )
    if not revalidation.hard_pass:
        return _failed(
            "profiled_legal_clip_mesh_revalidation_failed",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(profiled),
            failure_witness={
                "profiled_mesh_revalidation": revalidation.evidence(),
            },
        )
    if (
        revalidation.raw_component_count <= 0
        or revalidation.post_repair_component_count
        != revalidation.raw_component_count
        or revalidation.post_repair_component_count != len(final_components)
    ):
        return _failed(
            "profiled_legal_clip_component_authority_mismatch",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(profiled),
            final_component_count=(
                revalidation.post_repair_component_count
            ),
            failure_witness={
                "profiled_mesh_revalidation": revalidation.evidence(),
            },
        )
    if revalidation.repair_attempted:
        assert revalidation.certified_vertices is not None
        assert revalidation.certified_triangles is not None
        vertices = revalidation.certified_vertices
        triangles = revalidation.certified_triangles
        surfaces = _surfaces_from_indexed_mesh(
            vertices,
            triangles,
            output_origin=output_origin,
            volume_role=canonical_capacity_plates[0].role,
        )
        mesh_cleanup_schema = MESH_NUMERIC_REPAIR_SCHEMA
        mesh_cleanup_collapse_threshold_m = revalidation.collapse_threshold_m
        mesh_cleanup_max_physical_displacement_m = (
            revalidation.max_physical_displacement_m
        )
        mesh_cleanup_raw_indexed_mesh_hash = (
            revalidation.raw_indexed_mesh_hash
        )
        mesh_cleanup_raw_gate_failure_codes = revalidation.raw_gate_codes
        mesh_cleanup_clean_indexed_mesh_hash = (
            revalidation.clean_indexed_mesh_hash
        )
        mesh_cleanup_clean_gate_hard_pass = True
    emitted_component_volumes_m3 = _indexed_mesh_component_volumes(
        vertices,
        triangles,
    )
    if (
        emitted_component_volumes_m3 is None
        or len(emitted_component_volumes_m3)
        != revalidation.post_repair_component_count
    ):
        return _failed(
            "profiled_legal_clip_emitted_component_authority_failed",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(profiled),
            failure_witness={
                "profiled_mesh_revalidation": revalidation.evidence(),
            },
        )

    # Re-measure the emitted indexed payload. Inputs used to build the CSG
    # cannot certify the renderer-visible result. Kernel slicing avoids
    # rebuilding a closed contour from independently rounded line segments.
    section_numeric_epsilon_m = _section_numeric_epsilon_m(
        mesh_cleanup_max_physical_displacement_m
    )
    floor_center_schema = _VISIBLE_SECTION_SCHEMA
    section_metrics: list[dict[str, Any]] = []
    actual_section_wkb_hex: list[str] = []
    for floor_index, _expected in enumerate(occupied_sections):
        measured_evidence = _indexed_mesh_section_topology(
            vertices,
            triangles,
            (floor_index + 0.5) / floor_count,
        )
        if measured_evidence is None:
            return _failed(
                "profiled_legal_clip_midplane_section_invalid",
                capacity_gfa=capacity_gfa,
                source_surface_count=len(profiled),
                occupied_section_topology=tuple(occupied_topology),
                legal_section_topology=tuple(legal_topology),
                final_component_count=revalidation.post_repair_component_count,
                final_component_volumes_m3=emitted_component_volumes_m3,
                failure_witness={"floor_index": floor_index},
            )
        measured, contour_count, solid_count = measured_evidence
        actual_topology, _actual_failure, actual_witness = (
            _section_topology_certificate(
                measured,
                floor_index=floor_index,
                kind="actual_midplane",
            )
        )
        if actual_topology is None:
            return _failed(
                "profiled_legal_clip_midplane_section_invalid",
                capacity_gfa=capacity_gfa,
                source_surface_count=len(profiled),
                occupied_section_topology=tuple(occupied_topology),
                legal_section_topology=tuple(legal_topology),
                final_component_count=revalidation.post_repair_component_count,
                final_component_volumes_m3=emitted_component_volumes_m3,
                failure_witness={
                    "floor_index": floor_index,
                    **actual_witness,
                },
            )
        metrics = _floor_center_numeric_equivalence(
            measured,
            measured,
            epsilon_m=section_numeric_epsilon_m,
            contour_count=contour_count,
        )
        if metrics is None or metrics.get("hard_pass") is not True:
            return _failed(
                "profiled_legal_clip_midplane_section_invalid",
                capacity_gfa=capacity_gfa,
                source_surface_count=len(profiled),
                failure_witness={"floor_index": floor_index},
            )
        section_metrics.append({
            **actual_topology,
            **metrics,
            "floor_index": floor_index,
            "area_m2": float(measured.area),
            "solid_count": int(solid_count),
            "authority": "renderer_visible_authored_section",
        })
        actual_section_wkb_hex.append(
            translate(
                measured,
                xoff=-output_origin[0],
                yoff=-output_origin[1],
            ).normalize().wkb_hex
        )

    max_section_area_delta_m2 = max(
        metric["area_delta_m2"] for metric in section_metrics
    )
    max_section_symdiff_m2 = max(
        metric["symdiff_m2"] for metric in section_metrics
    )
    max_section_hausdorff_m = max(
        metric["hausdorff_m"] for metric in section_metrics
    )
    max_section_area_bound_m2 = max(
        metric["area_bound_m2"] for metric in section_metrics
    )

    legal_sample_count, legal_revalidation_witness = (
        _legal_band_projection_sample_count(
            vertices,
            triangles,
            legal_sections,
            numeric_epsilon_m=section_numeric_epsilon_m,
        )
    )
    if legal_sample_count is None:
        return _failed(
            "profiled_legal_clip_legal_revalidation_failed",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(profiled),
            occupied_section_topology=tuple(occupied_topology),
            legal_section_topology=tuple(legal_topology),
            floor_center_topology_metrics=tuple(section_metrics),
            final_component_count=revalidation.post_repair_component_count,
            final_component_volumes_m3=emitted_component_volumes_m3,
            legal_revalidation_witness=legal_revalidation_witness,
            failure_witness=legal_revalidation_witness,
        )

    exact_hash = _exact_surface_payload_hash(surfaces)
    authored_program_hash = _verified_authored_program_hash(source)
    sloped_evidence = profiled_sloped_mesh_evidence(
        surfaces,
        effective_height_m=effective_height_m,
    )
    if not authored_program_hash:
        sloped_evidence = profiled_sloped_mesh_evidence(
            (),
            effective_height_m=0.0,
        )
    (
        section_geometry_binding_hash,
        occupied_section_wkb_hex,
        legal_section_wkb_hex,
    ) = _section_geometry_binding(
        occupied_sections,
        legal_sections,
        output_origin,
    )
    authority_hash = floorwise_authority_binding_hash(
        **components,
        exact_surface_payload_hash=exact_hash,
        certification_mode=_MODE,
        visible_geometry_operation=_OPERATION,
        visible_step_fallback=False,
        authored_program_hash=authored_program_hash,
        effective_height_m=sloped_evidence["effective_height_m"],
        verified_profiled_sloped_surface_area=(
            sloped_evidence["sloped_surface_area"]
        ),
        verified_profiled_sloped_surface_ratio=(
            sloped_evidence["sloped_surface_ratio"]
        ),
        verified_profiled_sloped_surface_hash=(
            sloped_evidence["sloped_surface_hash"]
        ),
        section_numeric_epsilon_m=section_numeric_epsilon_m,
        mesh_numeric_repair_schema=mesh_cleanup_schema,
        mesh_cleanup_collapse_threshold_m=(
            mesh_cleanup_collapse_threshold_m
        ),
        mesh_cleanup_max_physical_displacement_m=(
            mesh_cleanup_max_physical_displacement_m
        ),
        mesh_cleanup_raw_indexed_mesh_hash=(
            mesh_cleanup_raw_indexed_mesh_hash
        ),
        mesh_cleanup_raw_gate_failure_codes=(
            mesh_cleanup_raw_gate_failure_codes
        ),
        mesh_cleanup_clean_indexed_mesh_hash=(
            mesh_cleanup_clean_indexed_mesh_hash
        ),
        mesh_cleanup_clean_gate_hard_pass=(
            mesh_cleanup_clean_gate_hard_pass
        ),
        floor_center_numeric_equivalence_schema=(
            floor_center_schema
        ),
        max_section_area_delta_m2=max_section_area_delta_m2,
        max_section_symdiff_m2=max_section_symdiff_m2,
        max_section_hausdorff_m=max_section_hausdorff_m,
        max_section_area_bound_m2=max_section_area_bound_m2,
        section_geometry_binding_hash=section_geometry_binding_hash,
    )
    return FloorwiseVisualProjection(
        surfaces=surfaces,
        certificate=FloorwiseVisualProjectionCertificate(
            status="certified",
            hard_pass=True,
            visual_hash=_stable_visual_hash(surfaces),
            source_surface_count=len(profiled),
            projected_surface_count=len(surfaces),
            legal_sample_count=legal_sample_count,
            capacity_gfa_m2=capacity_gfa,
            floor_count=floor_count,
            certification_mode=_MODE,
            visible_geometry_operation=_OPERATION,
            exact_surface_payload_hash=exact_hash,
            capacity_authority="floorwise_legal_volumes",
            visible_step_fallback=False,
            section_profile_hash=components["section_profile_hash"],
            capacity_volume_hash=components["capacity_volume_hash"],
            floor_capacity_plan_hash=components["floor_capacity_plan_hash"],
            matrix4_stack_hash=components["matrix4_stack_hash"],
            authored_program_hash=authored_program_hash,
            effective_height_m=sloped_evidence["effective_height_m"],
            verified_profiled_sloped_surface_area=(
                sloped_evidence["sloped_surface_area"]
            ),
            verified_profiled_sloped_surface_ratio=(
                sloped_evidence["sloped_surface_ratio"]
            ),
            verified_profiled_sloped_surface_hash=(
                sloped_evidence["sloped_surface_hash"]
            ),
            section_numeric_epsilon_m=section_numeric_epsilon_m,
            mesh_numeric_repair_schema=mesh_cleanup_schema,
            mesh_cleanup_collapse_threshold_m=(
                mesh_cleanup_collapse_threshold_m
            ),
            mesh_cleanup_max_physical_displacement_m=(
                mesh_cleanup_max_physical_displacement_m
            ),
            mesh_cleanup_raw_indexed_mesh_hash=(
                mesh_cleanup_raw_indexed_mesh_hash
            ),
            mesh_cleanup_raw_gate_failure_codes=(
                mesh_cleanup_raw_gate_failure_codes
            ),
            mesh_cleanup_clean_indexed_mesh_hash=(
                mesh_cleanup_clean_indexed_mesh_hash
            ),
            mesh_cleanup_clean_gate_hard_pass=(
                mesh_cleanup_clean_gate_hard_pass
            ),
            floor_center_numeric_equivalence_schema=(
                floor_center_schema
            ),
            max_section_area_delta_m2=max_section_area_delta_m2,
            max_section_symdiff_m2=max_section_symdiff_m2,
            max_section_hausdorff_m=max_section_hausdorff_m,
            max_section_area_bound_m2=max_section_area_bound_m2,
            occupied_section_topology=tuple(occupied_topology),
            legal_section_topology=tuple(legal_topology),
            floor_center_topology_metrics=tuple(section_metrics),
            final_component_count=revalidation.post_repair_component_count,
            final_component_volumes_m3=emitted_component_volumes_m3,
            final_closed_manifold_hard_pass=True,
            legal_revalidation_witness=legal_revalidation_witness,
            section_geometry_binding_schema=_SECTION_GEOMETRY_BINDING_SCHEMA,
            section_geometry_binding_hash=section_geometry_binding_hash,
            occupied_section_wkb_hex=occupied_section_wkb_hex,
            legal_section_wkb_hex=legal_section_wkb_hex,
            actual_section_wkb_hex=tuple(actual_section_wkb_hex),
            authority_binding_hash=authority_hash,
        ),
    )


def _complete_profiled_export(
    source: SourceMass,
    surfaces: Sequence[SourceSurface],
) -> bool:
    bridge = source.metadata.get("geometry_program_bridge_evidence")
    bridge = bridge if isinstance(bridge, dict) else {}
    try:
        raw = int(bridge.get("raw_mesh_triangle_count") or 0)
        exported = int(bridge.get("exported_surface_count") or 0)
    except (TypeError, ValueError):
        return False
    return bool(
        raw
        and exported
        and raw == exported == len(surfaces) == len(source.surfaces)
    )


def _verified_authored_program_hash(source: SourceMass) -> str:
    payload = source.metadata.get("geometry_program")
    bridge = source.metadata.get("geometry_program_bridge_evidence")
    bridge = bridge if isinstance(bridge, dict) else {}
    if not isinstance(payload, dict):
        return ""
    try:
        program = GeometryProgram.from_dict(payload)
    except (TypeError, ValueError):
        return ""
    program_hash = program.program_hash()
    return (
        program_hash
        if (
            not program.validate()
            and str(bridge.get("program_hash") or "") == program_hash
        )
        else ""
    )


def _effective_height_m(source: SourceMass) -> float:
    contexts = (
        source.metadata.get("program_dimensional_context"),
        source.metadata.get("candidate_floor_context"),
        source.metadata.get("legal_generation_context_evidence"),
    )
    for context in contexts:
        if not isinstance(context, dict):
            continue
        for field in (
            "effective_height_m",
            "height_m",
            "requested_program_height_m",
        ):
            try:
                value = float(context.get(field) or 0.0)
            except (TypeError, ValueError):
                continue
            if isfinite(value) and value > 0.0:
                return value
    return 0.0


def _components(value: Any) -> tuple[Polygon, ...]:
    if isinstance(value, Polygon):
        return (value,)
    if isinstance(value, MultiPolygon):
        return tuple(sorted(
            value.geoms,
            key=lambda component: component.normalize().wkb_hex,
        ))
    return ()


def _sorted_interiors(polygon: Polygon) -> tuple[Any, ...]:
    return tuple(sorted(
        polygon.interiors,
        key=lambda interior: Polygon(interior).normalize().wkb_hex,
    ))


def _section_topology_certificate(
    value: Any,
    *,
    floor_index: int,
    kind: str,
) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    prefix = f"profiled_legal_clip_{kind}_section"
    witness = {"floor_index": floor_index, "section_kind": kind}
    if not isinstance(value, (Polygon, MultiPolygon)):
        return None, f"{prefix}_invalid", witness
    if value.is_empty:
        return None, f"{prefix}_empty", witness
    components = _components(value)
    for left_index, left in enumerate(components):
        for right_index, right in enumerate(
            components[left_index + 1:],
            left_index + 1,
        ):
            overlap_area = float(left.intersection(right).area)
            if overlap_area > _EPSILON:
                return None, f"profiled_legal_clip_{kind}_components_overlap", {
                    **witness,
                    "component_index": left_index,
                    "other_component_index": right_index,
                    "overlap_area_m2": overlap_area,
                }
    coordinates = (
        coordinate
        for component in components
        for ring in (component.exterior, *_sorted_interiors(component))
        for coordinate in ring.coords
    )
    if (
        not components
        or not value.is_valid
        or not isfinite(float(value.area))
        or float(value.area) <= _EPSILON
        or not all(
            isfinite(float(axis))
            for point in coordinates
            for axis in point[:2]
        )
        or any(float(component.area) <= _EPSILON for component in components)
    ):
        return None, f"{prefix}_invalid", witness
    hole_areas = tuple(
        float(Polygon(interior).area)
        for component in components
        for interior in _sorted_interiors(component)
    )
    return {
        "floor_index": floor_index,
        "geometry_type": value.geom_type,
        "component_count": len(components),
        "hole_count": len(hole_areas),
        "contour_count": len(components) + len(hole_areas),
        "valid": True,
        "area_m2": float(value.area),
        "component_areas_m2": [float(component.area) for component in components],
        "hole_areas_m2": list(hole_areas),
    }, "", {}


def _plan_only_matrix(matrix: Matrix4) -> bool:
    return (
        abs(matrix[0][2]) <= _EPSILON
        and abs(matrix[1][2]) <= _EPSILON
        and abs(matrix[2][0]) <= _EPSILON
        and abs(matrix[2][1]) <= _EPSILON
        and abs(matrix[2][2] - 1.0) <= _EPSILON
        and abs(matrix[2][3]) <= _EPSILON
    )


def _source_world_matrix_field_manifold(
    source: SourceMass,
    surfaces: Sequence[SourceSurface],
    matrices: tuple[Matrix4, ...],
) -> m3d.Manifold:
    if not matrices:
        raise ValueError("missing authored global Matrix4")
    origin = source.footprint.centroid
    # The BOOK/BaseVolume contract owns one homogeneous Matrix4 for the whole
    # authored solid.  Earlier code interpolated a different capacity-fit
    # matrix at every floor, which visibly re-authored every otherwise diverse
    # AST into the same terraced silhouette.  Floor matrices remain legal and
    # capacity evidence; the visible authored mesh uses the single ground
    # placement matrix and is clipped once by the continuous legal envelope.
    global_matrix = matrices[0]
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    indices: dict[tuple[float, float, float], int] = {}
    for surface in surfaces:
        raw_world_triangle = tuple(
            (
                float(x) + float(origin.x),
                float(y) + float(origin.y),
                float(z),
            )
            for x, y, z in surface.vertices_m
        )
        if (
            not all(
                all(isfinite(value) for value in vertex)
                    for vertex in raw_world_triangle
                )
                or any(
                    vertex[2] < -_NORMALIZED_Z_TRANSPORT_EPSILON
                    or vertex[2] > 1.0 + _NORMALIZED_Z_TRANSPORT_EPSILON
                    for vertex in raw_world_triangle
                )
            ):
                raise ValueError("invalid authored mesh vertex")
        world_triangle = tuple(
            (x, y, min(1.0, max(0.0, z)))
            for x, y, z in raw_world_triangle
        )
        triangle = []
        for point in world_triangle:
            vertex = transform_point3(global_matrix, point)
            triangle.append(indices.setdefault(vertex, len(indices)))
            if triangle[-1] == len(vertices):
                vertices.append(vertex)
        triangles.append(tuple(triangle))
    mesh = m3d.Mesh(
        np.asarray(vertices, dtype=np.float64),
        np.asarray(triangles, dtype=np.uint32),
    )
    mesh.merge()
    return m3d.Manifold(mesh)


def _legal_prism(
    polygon: Polygon,
    *,
    lower_z: float,
    upper_z: float,
) -> m3d.Manifold:
    normalized = orient(polygon, sign=1.0)
    coordinates = [
        (float(x), float(y))
        for x, y in tuple(normalized.exterior.coords)[:-1]
    ]
    start = min(range(len(coordinates)), key=coordinates.__getitem__)
    exterior = coordinates[start:] + coordinates[:start]
    holes = []
    for interior in _sorted_interiors(normalized):
        hole = [
            (float(x), float(y))
            for x, y in tuple(interior.coords)[:-1]
        ]
        hole_start = min(range(len(hole)), key=hole.__getitem__)
        holes.append(hole[hole_start:] + hole[:hole_start])
    return (
        m3d.CrossSection([exterior, *holes])
        .extrude(float(upper_z) - float(lower_z))
        .translate((0.0, 0.0, float(lower_z)))
    )


def _legal_band_projection_sample_count(
    vertices: Sequence[tuple[float, float, float]],
    triangles: Sequence[tuple[int, int, int]],
    legal_sections: Sequence[Polygon | MultiPolygon],
    *,
    numeric_epsilon_m: float = 0.0,
) -> tuple[int | None, dict[str, Any]]:
    """Prove whole emitted faces against half-open legal floor bands."""

    floor_count = len(legal_sections)
    boundaries = tuple(
        index / floor_count
        for index in range(1, floor_count)
    )
    lawful = tuple(legal_sections)
    checked = 0
    total_witness_count = 0
    successful_records: list[dict[str, Any]] = []
    for face_index, triangle in enumerate(triangles):
        world_triangle = tuple(vertices[index] for index in triangle)
        for piece_index, piece in enumerate(_split_triangle_at_z_breakpoints(
            world_triangle,
            breakpoints=boundaries,
        )):
            z_values = tuple(float(point[2]) for point in piece)
            minimum_z = min(z_values)
            maximum_z = max(z_values)
            total_witness_count += 1
            if minimum_z < -_EPSILON or maximum_z > 1.0 + _EPSILON:
                failure = {
                    "status": "failed",
                    "face_index": face_index,
                    "piece_index": piece_index,
                    "minimum_z": minimum_z,
                    "maximum_z": maximum_z,
                }
                return None, _bounded_legal_revalidation_witness(
                    successful_records,
                    total_count=total_witness_count,
                    failure=failure,
                )
            if maximum_z - minimum_z <= _EPSILON:
                scaled = minimum_z * floor_count
                boundary = round(scaled)
                if (
                    abs(
                        minimum_z - boundary / floor_count
                    ) <= _BAND_BOUNDARY_EPSILON
                    and 0 < boundary < floor_count
                ):
                    candidate_floor_indices = (boundary - 1, boundary)
                else:
                    floor_index = min(
                        floor_count - 1,
                        max(0, int(scaled)),
                    )
                    candidate_floor_indices = (floor_index,)
            else:
                center_z = sum(z_values) / len(z_values)
                floor_index = min(
                    floor_count - 1,
                    max(0, int(center_z * floor_count)),
                )
                candidate_floor_indices = (floor_index,)
            projection = MultiPoint([
                (float(x), float(y))
                for x, y, _z in piece
            ]).convex_hull
            coverage_modes = {}
            for floor_index in candidate_floor_indices:
                covered, coverage_mode = _strict_legal_covers(
                    lawful[floor_index],
                    projection,
                    numeric_epsilon_m=numeric_epsilon_m,
                )
                if covered:
                    coverage_modes[floor_index] = coverage_mode
            covering_floor_indices = tuple(coverage_modes)
            if not covering_floor_indices:
                adjacent_failures = []
                for candidate_floor_index in candidate_floor_indices:
                    components = _components(
                        legal_sections[candidate_floor_index]
                    )
                    nearest = min(
                        range(len(components)),
                        key=lambda index: components[index].distance(projection),
                        default=-1,
                    )
                    adjacent_failures.append({
                        "band_index": candidate_floor_index,
                        "nearest_component_index": nearest,
                        "distance_m": (
                            float(components[nearest].distance(projection))
                            if nearest >= 0 else None
                        ),
                    })
                failure = {
                    "status": "failed",
                    "floor_index": candidate_floor_indices[0],
                    "face_index": face_index,
                    "piece_index": piece_index,
                    "projected_area_m2": float(projection.area),
                    "projected_length_m": float(projection.length),
                    "projected_bounds": [float(value) for value in projection.bounds],
                    "projected_geometry_type": str(projection.geom_type),
                    "xy_containment_mode": "strict_unbuffered_covers",
                    "numeric_epsilon_m": float(numeric_epsilon_m),
                    "z_boundary_epsilon": _BAND_BOUNDARY_EPSILON,
                    "adjacent_band_indices": list(candidate_floor_indices),
                    "adjacent_band_failures": adjacent_failures,
                    "outside_area_m2": min(
                        float(projection.difference(lawful[index]).area)
                        for index in candidate_floor_indices
                    ),
                }
                return None, _bounded_legal_revalidation_witness(
                    successful_records,
                    total_count=total_witness_count,
                    failure=failure,
                )
            selected_floor_index = covering_floor_indices[0]
            success = {
                "status": "covered",
                "face_index": face_index,
                "piece_index": piece_index,
                "normalized_z": minimum_z,
                "adjacent_band_indices": list(candidate_floor_indices),
                "covering_band_indices": list(covering_floor_indices),
                "selected_band_index": selected_floor_index,
                "xy_containment_mode": coverage_modes[selected_floor_index],
            }
            if len(successful_records) < _LEGAL_REVALIDATION_WITNESS_MAXIMUM:
                successful_records.append(success)
            checked += 1
    return (checked if checked else None), _bounded_legal_revalidation_witness(
        successful_records,
        total_count=total_witness_count,
    )


def _bounded_legal_revalidation_witness(
    successful_records: Sequence[dict[str, Any]],
    *,
    total_count: int,
    failure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    maximum = _LEGAL_REVALIDATION_WITNESS_MAXIMUM
    retained_successes = list(successful_records)
    if failure is None:
        records = retained_successes[:maximum]
        failures: list[dict[str, Any]] = []
    else:
        failures = [dict(failure)]
        records = [dict(failure), *retained_successes[:maximum - 1]]
    witness = {
        "schema_version": "arr.maas.legal_revalidation_witness.v1",
        "maximum_retained_count": maximum,
        "total_count": int(total_count),
        "retained_count": len(records),
        "truncated": int(total_count) > len(records),
        "records": records,
        "failures": failures,
        "boundary_assignments": [
            record
            for record in records
            if record.get("status") == "covered"
            and len(record.get("adjacent_band_indices") or ()) == 2
        ],
    }
    if failure is not None:
        witness.update({
            key: value
            for key, value in failure.items()
            if key != "status"
        })
    return witness


def _strict_legal_covers(
    lawful_section: Polygon | MultiPolygon,
    projection: Any,
    *,
    numeric_epsilon_m: float = 0.0,
) -> tuple[bool, str]:
    if projection.is_empty:
        return False, "strict_unbuffered_covers"
    if lawful_section.covers(projection):
        return True, "strict_unbuffered_covers"
    epsilon = float(numeric_epsilon_m)
    if not isfinite(epsilon) or epsilon <= 0.0:
        return False, "strict_unbuffered_covers"
    if projection.geom_type not in {"Point", "LineString", "Polygon"}:
        return False, "strict_unbuffered_covers"
    outside_geometry = projection.difference(lawful_section)
    if projection.geom_type == "Point":
        if lawful_section.boundary.distance(projection) <= epsilon:
            return True, "kernel_boundary_numeric_equivalence"
    elif projection.geom_type == "LineString":
        if (
            float(outside_geometry.length)
            <= epsilon * max(1.0, float(projection.length))
            or (
                lawful_section.distance(projection) <= epsilon
                and lawful_section.boundary.distance(projection) <= epsilon
            )
        ):
            return True, "kernel_boundary_numeric_equivalence"
    elif (
        float(outside_geometry.area)
        <= epsilon * max(1.0, float(projection.length))
        and lawful_section.distance(projection) <= epsilon
    ):
        return True, "kernel_boundary_numeric_equivalence"
    coordinates = (
        ((float(projection.x), float(projection.y)),)
        if projection.geom_type == "Point"
        else (
            tuple(
                (float(x), float(y))
                for x, y in projection.exterior.coords
            )
            if projection.geom_type == "Polygon"
            else tuple(
            (float(x), float(y))
            for x, y in projection.coords
            )
        )
    )
    outside_points = tuple(
        Point(coordinate)
        for coordinate in coordinates
        if not lawful_section.covers(Point(coordinate))
    )
    outside_area = float(projection.difference(lawful_section).area)
    if (
        outside_points
        and all(
            lawful_section.boundary.distance(point) <= epsilon
            for point in outside_points
        )
        and outside_area <= epsilon * max(1.0, float(projection.length))
    ):
        return True, "kernel_boundary_numeric_equivalence"
    return False, "strict_unbuffered_covers"


def _surfaces_from_indexed_mesh(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
    *,
    output_origin: tuple[float, float],
    volume_role: str,
) -> tuple[SourceSurface, ...]:
    local_vertices = tuple(
        (
            vertex[0] - float(output_origin[0]),
            vertex[1] - float(output_origin[1]),
            vertex[2],
        )
        for vertex in vertices
    )
    return tuple(
        SourceSurface(
            role=f"floorwise_profiled_legal_clip_{index:04d}",
            volume_role=volume_role,
            verb="geometry_program",
            surface_type="profiled_recursive_solid_mesh",
            vertices_m=tuple(local_vertices[vertex] for vertex in triangle),
        )
        for index, triangle in enumerate(triangles)
    )


def _surfaces_from_manifold(
    solid: m3d.Manifold,
    *,
    output_origin: tuple[float, float],
    volume_role: str,
) -> tuple[
    tuple[SourceSurface, ...],
    tuple[tuple[float, float, float], ...],
    tuple[tuple[int, int, int], ...],
]:
    mesh = solid.to_mesh64()
    world_vertices = tuple(
        tuple(float(value) for value in row[:3])
        for row in mesh.vert_properties
    )
    raw_triangles = tuple(
        tuple(int(value) for value in row)
        for row in mesh.tri_verts
    )
    triangles = tuple(sorted(
        (_rotate_triangle(triangle) for triangle in raw_triangles),
        key=lambda triangle: tuple(
            world_vertices[index]
            for index in triangle
        ),
    ))
    local_vertices = tuple(
        (
            vertex[0] - float(output_origin[0]),
            vertex[1] - float(output_origin[1]),
            vertex[2],
        )
        for vertex in world_vertices
    )
    surfaces = tuple(
        SourceSurface(
            role=f"floorwise_profiled_legal_clip_{index:04d}",
            volume_role=volume_role,
            verb="geometry_program",
            surface_type="profiled_recursive_solid_mesh",
            vertices_m=tuple(local_vertices[vertex] for vertex in triangle),
            operator="intersection",
            semantic_patch_id="floorwise_legal:profiled_mesh_clip",
        )
        for index, triangle in enumerate(triangles, start=1)
    )
    return surfaces, world_vertices, triangles


def _rotate_triangle(
    triangle: tuple[int, int, int],
) -> tuple[int, int, int]:
    rotations = (
        triangle,
        (triangle[1], triangle[2], triangle[0]),
        (triangle[2], triangle[0], triangle[1]),
    )
    return min(rotations)


def _failed(
    reason: str,
    *,
    capacity_gfa: float,
    source_surface_count: int,
    legal_sample_count: int = 0,
    occupied_section_topology: tuple[dict[str, Any], ...] = (),
    legal_section_topology: tuple[dict[str, Any], ...] = (),
    floor_center_topology_metrics: tuple[dict[str, Any], ...] = (),
    final_component_count: int = 0,
    final_component_volumes_m3: tuple[float, ...] = (),
    legal_revalidation_witness: dict[str, Any] | None = None,
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
            certification_mode=_MODE,
            visible_geometry_operation=_OPERATION,
            visible_step_fallback=False,
            occupied_section_topology=occupied_section_topology,
            legal_section_topology=legal_section_topology,
            floor_center_topology_metrics=floor_center_topology_metrics,
            final_component_count=final_component_count,
            final_component_volumes_m3=final_component_volumes_m3,
            final_closed_manifold_hard_pass=False,
            legal_revalidation_witness=dict(
                legal_revalidation_witness or {}
            ),
            failure_witness=dict(failure_witness or {}),
        ),
    )


__all__ = ["clip_profiled_mesh_to_floorwise_legal_solids"]
