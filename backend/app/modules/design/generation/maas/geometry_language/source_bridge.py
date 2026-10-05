"""Project recursive solid programs into the real parcel/program SourceMass lane.

The manifold solid remains the visual authority.  A small set of measured
horizontal sections becomes the conservative 2.5D proxy used by existing
program, FAR, sunlight and parking hard gates.  No parcel coordinate or
completed building is stored in a geometry program.
"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, replace
import hashlib
import json
from math import atan2, cos, degrees, hypot, isfinite, pi, sin, sqrt
from typing import Any, Sequence

from shapely import make_valid, set_precision
from shapely.affinity import affine_transform, rotate, translate
from shapely.errors import GEOSException
from shapely.geometry import LineString, MultiPoint, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import nearest_points, polygonize, unary_union
from shapely.validation import explain_validity

from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass, SourceSurface, SourceVolume
from backend.app.modules.design.generation.maas.source_geometry.coherence import evaluate_source_volume_coherence
from backend.app.modules.design.generation.maas.source_geometry.polygon_quality import repair_source_polygon

from backend.app.modules.design.generation.maas.geometry_language.ast import FLOORWISE_CAPACITY_REPLAY_TRANSPORT_CONTRACT, GeometryNode, GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import Matrix4, compose_matrix4, inverse_matrix4, matrix4_to_lists, rotation_matrix4, scale_matrix4, transform_point3, translation_matrix4
from backend.app.modules.design.generation.maas.geometry_language.base_seeds import BASE_SEED_SPECS
from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult, compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.gate import GeometryGatePolicy, compilation_gate
from backend.app.modules.design.generation.maas.geometry_language.replay_ring_transport import replay_polygon_origin, replay_polygon_point_payload


_COMPILATION_CACHE: "OrderedDict[str, CompilationResult]" = OrderedDict()
_COMPILATION_CACHE_LIMIT = 512


Point3 = tuple[float, float, float]
_TERMINAL_FAILURE_EVIDENCE_LIMIT = 32
_TERMINAL_FAILURE_WITNESS_LIMIT = 48


def _append_terminal_failure(
    sink: list[dict[str, Any]] | None,
    stage: str,
    **evidence: Any,
) -> None:
    """Emit one bounded, serializable terminal failure record."""

    if sink is None:
        return
    bounded_evidence: dict[str, Any] = {}
    for key, value in evidence.items():
        if len(bounded_evidence) >= _TERMINAL_FAILURE_EVIDENCE_LIMIT:
            break
        if isinstance(value, str):
            bounded_evidence[str(key)] = value[:160]
        elif isinstance(value, (bool, int, float)) or value is None:
            bounded_evidence[str(key)] = value
        elif (
            str(key) in {
                "failure_reasons",
                "certificate_causes",
                "certificate_modes",
            }
            and isinstance(value, (list, tuple))
        ):
            bounded_evidence[str(key)] = list(dict.fromkeys(
                str(item)[:160]
                for item in value[:12]
                if str(item)
            ))
        elif str(key) == "failure_witness" and isinstance(value, dict):
            bounded_witness: dict[str, Any] = {}
            for witness_key, witness_value in value.items():
                if len(bounded_witness) >= _TERMINAL_FAILURE_WITNESS_LIMIT:
                    break
                if isinstance(witness_value, str):
                    bounded_witness[str(witness_key)] = witness_value[:160]
                elif (
                    isinstance(witness_value, (bool, int, float))
                    or witness_value is None
                ):
                    bounded_witness[str(witness_key)] = witness_value
                elif (
                    str(witness_key) == "failed_predicates"
                    and isinstance(witness_value, (list, tuple))
                ):
                    bounded_witness[str(witness_key)] = list(dict.fromkeys(
                        str(item)[:160]
                        for item in witness_value[:12]
                        if str(item)
                    ))
                elif (
                    str(witness_key) == "profiled_mesh_revalidation"
                    and isinstance(witness_value, dict)
                ):
                    typed_revalidation: dict[str, Any] = {}
                    for typed_key in (
                        "repair_attempted",
                        "max_physical_displacement_m",
                        "raw_component_count",
                        "post_repair_component_count",
                    ):
                        typed_value = witness_value.get(typed_key)
                        if isinstance(typed_value, (bool, int, float)):
                            typed_revalidation[typed_key] = typed_value
                    for typed_key in (
                        "raw_gate_codes",
                        "post_repair_gate_codes",
                    ):
                        typed_value = witness_value.get(typed_key)
                        if isinstance(typed_value, (list, tuple)):
                            typed_revalidation[typed_key] = list(dict.fromkeys(
                                str(item)[:160]
                                for item in typed_value[:12]
                                if str(item)
                            ))
                    numeric = witness_value.get("numeric_measurements")
                    if isinstance(numeric, dict):
                        typed_revalidation["numeric_measurements"] = {
                            str(name): value
                            for name, value in list(numeric.items())[:8]
                            if isinstance(value, (int, float))
                        }
                    attempts = witness_value.get("attempt_records")
                    if isinstance(attempts, list):
                        bounded_attempts = []
                        required_numeric = (
                            "threshold_m",
                            "max_chain_displacement_m",
                            "minimum_surviving_edge_physical_m",
                            "minimum_surviving_edge_coordinate",
                        )
                        for attempt in attempts[:5]:
                            if not isinstance(attempt, dict):
                                continue
                            numeric_values = {
                                key: attempt.get(key) for key in required_numeric
                            }
                            if not all(
                                isinstance(value, (int, float))
                                and value == value
                                and abs(float(value)) != float("inf")
                                for value in numeric_values.values()
                            ):
                                continue
                            reason = attempt.get("termination_reason")
                            endpoints = attempt.get(
                                "minimum_edge_endpoint_indices"
                            )
                            delta = attempt.get("minimum_edge_delta_xyz")
                            post_codes = attempt.get("post_gate_codes")
                            structural = attempt.get("structural_evidence")
                            if (
                                reason not in {
                                    "no_eligible_edge",
                                    "chain_displacement_exceeded",
                                    "invalid_effective_height",
                                    "completed",
                                }
                                or not isinstance(
                                    attempt.get("collapse_count"), int
                                )
                                or not isinstance(
                                    attempt.get("raw_component_count"), int
                                )
                                or not isinstance(
                                    attempt.get("post_component_count"), int
                                )
                                or not isinstance(
                                    attempt.get("selected_as_final"), bool
                                )
                                or not isinstance(endpoints, list)
                                or len(endpoints) > 2
                                or not all(isinstance(index, int) for index in endpoints)
                                or not isinstance(delta, list)
                                or len(delta) != 3
                                or not all(
                                    isinstance(value, (int, float))
                                    and value == value
                                    and abs(float(value)) != float("inf")
                                    for value in delta
                                )
                                or not isinstance(post_codes, list)
                                or not all(isinstance(code, str) for code in post_codes[:12])
                                or not isinstance(structural, dict)
                                or not all(
                                    isinstance(name, str)
                                    and isinstance(flag, bool)
                                    for name, flag in structural.items()
                                )
                            ):
                                continue
                            bounded_attempts.append({
                                **numeric_values,
                                "collapse_count": attempt["collapse_count"],
                                "termination_reason": reason,
                                "minimum_edge_endpoint_indices": endpoints[:2],
                                "minimum_edge_delta_xyz": list(delta),
                                "post_gate_codes": list(dict.fromkeys(
                                    post_codes[:12]
                                )),
                                "raw_component_count": attempt[
                                    "raw_component_count"
                                ],
                                "post_component_count": attempt[
                                    "post_component_count"
                                ],
                                "structural_evidence": dict(
                                    list(structural.items())[:5]
                                ),
                                "selected_as_final": attempt[
                                    "selected_as_final"
                                ],
                            })
                        typed_revalidation["attempt_records"] = bounded_attempts
                    bounded_witness[str(witness_key)] = typed_revalidation
            bounded_evidence[str(key)] = bounded_witness
    sink.append({"stage": stage, "evidence": bounded_evidence})


@dataclass(frozen=True)
class HostFitTransform:
    matrix4: Matrix4
    inverse_matrix4: Matrix4
    world_vertices: tuple[Point3, ...]
    achieved_plan_area_m2: float


def derive_host_fit_transform(
    compilation: CompilationResult,
    host: Polygon,
    *,
    target_plan_area: float | None = None,
    minimum_plan_area: float | None = None,
) -> HostFitTransform | None:
    """Derive one explicit affine placement for a compiled authored solid."""

    repaired_host = repair_source_polygon(host, minimum_area=1.0)
    if repaired_host is None:
        return None
    return _fit_vertices_to_host(
        compilation,
        repaired_host,
        target_plan_area=target_plan_area,
        minimum_plan_area=minimum_plan_area,
    )


def append_site_placement_matrix(
    program: GeometryProgram,
    fit: HostFitTransform,
) -> GeometryProgram:
    """Append one root Matrix4 while retaining the authored graph unchanged."""

    upstream_program_hash = program.program_hash()
    existing_ids = {node.id for node in program.nodes}
    node_id = "site_placement_matrix4"
    suffix = 2
    while node_id in existing_ids:
        node_id = f"site_placement_matrix4_{suffix}"
        suffix += 1
    placement = GeometryNode(
        id=node_id,
        kind="transform",
        operator="matrix4",
        inputs=(program.root_id,),
        parameters={"matrix4": matrix4_to_lists(fit.matrix4)},
        semantic_role="site_placement",
        provenance={
            "source": "principal_frame_host_fit",
            "upstream_program_hash": upstream_program_hash,
        },
    )
    metadata = deepcopy(program.metadata)
    metadata["site_placement"] = {
        "schema_version": "arr.maas.site_placement.v1",
        "matrix_node_id": node_id,
        "upstream_program_hash": upstream_program_hash,
        "matrix4": matrix4_to_lists(fit.matrix4),
        "inverse_matrix4": matrix4_to_lists(fit.inverse_matrix4),
        "achieved_plan_area_m2": round(fit.achieved_plan_area_m2, 8),
    }
    return replace(
        program,
        nodes=tuple(deepcopy(program.nodes)) + (placement,),
        root_id=node_id,
        metadata=metadata,
    )


def _allocate_profiled_floor_targets(
    *,
    planned_floor_areas_m2: tuple[float, ...],
    legal_floor_caps_m2: tuple[float, ...],
    authored_profile_ratios: tuple[float, ...],
    ground_design_cap_m2: float | None = None,
) -> tuple[float, ...]:
    """Validate and preserve the law-derived per-floor capacity vector.

    ``planned_floor_areas_m2`` already contains the live legal-section
    contraction and the requested capacity-band reserve.  Multiplying that
    vector by the authored section ratios a second time double-applies the
    vertical profile and can collapse one correct loft to less than half of
    its lawful GFA.  Geometry is measured against this vector; it does not own
    authority to redistribute it.  The authored profile remains authoritative
    in the single global Matrix4 fit and may underfill, but may not rewrite the
    floor targets used to certify that fit.
    """

    count = min(
        len(planned_floor_areas_m2),
        len(legal_floor_caps_m2),
        len(authored_profile_ratios),
    )
    if count <= 0:
        return ()
    planned = tuple(
        max(0.0, float(value))
        for value in planned_floor_areas_m2[:count]
    )
    caps = [
        max(0.0, float(value))
        for value in legal_floor_caps_m2[:count]
    ]
    if ground_design_cap_m2 is not None:
        try:
            ground_design_cap = float(ground_design_cap_m2)
        except (TypeError, ValueError):
            return ()
        if not isfinite(ground_design_cap) or ground_design_cap < 0.0:
            return ()
        caps[0] = min(caps[0], ground_design_cap)
        if sum(caps) + 1e-7 < sum(planned):
            return ()
    if any(
        planned[index] > caps[index] + 1e-7
        for index in range(count)
    ):
        return ()
    return planned


def _global_capacity_area_scale_product(
    *,
    planned_floor_areas_m2: tuple[float, ...],
    source_floor_areas_m2: tuple[float, ...],
) -> float:
    """Size one global plan transform from the whole-building GFA budget.

    The planned vector distributes a design-capacity objective; the live
    legal sections remain the per-floor statutory caps. Taking the smallest
    planned/source ratio turns one mismatched upper profile into a global
    shrink command and underfills every other floor.
    """

    count = min(
        len(planned_floor_areas_m2),
        len(source_floor_areas_m2),
    )
    if count <= 0:
        return 0.0
    planned = tuple(float(value) for value in planned_floor_areas_m2[:count])
    source = tuple(float(value) for value in source_floor_areas_m2[:count])
    if (
        any(not isfinite(value) or value < 0.0 for value in planned)
        or any(not isfinite(value) or value <= 0.0 for value in source)
    ):
        return 0.0
    source_total = sum(source)
    planned_total = sum(planned)
    if source_total <= 1e-9 or planned_total <= 1e-9:
        return 0.0
    return planned_total / source_total


def _capacity_compensated_global_target_area(
    *,
    current_ground_target_area_m2: float,
    requested_total_area_m2: float,
    achieved_total_area_m2: float,
    maximum_ground_target_area_m2: float | None = None,
) -> float:
    """Increase one global target only by measured legal-clip loss.

    Whole-building compensation must not consume the ground-level design
    reserve. The caller may therefore bind the global scale to the same live
    ground cap used by the floor allocation policy.
    """

    current = float(current_ground_target_area_m2)
    requested = float(requested_total_area_m2)
    achieved = float(achieved_total_area_m2)
    maximum = (
        float(maximum_ground_target_area_m2)
        if maximum_ground_target_area_m2 is not None
        else None
    )
    if (
        not all(isfinite(value) for value in (current, requested, achieved))
        or maximum is not None and not isfinite(maximum)
        or min(current, requested, achieved) <= 0.0
        or achieved >= requested
    ):
        return min(current, maximum) if maximum is not None else current
    compensated = current * min(1.5, requested / achieved)
    return min(compensated, maximum) if maximum is not None else compensated


def _requested_plan_axis_scales(
    source: Any,
    host: Polygon,
    *,
    target_area: float,
    target_angle_offset_degrees: float = 0.0,
) -> tuple[float, float] | None:
    """Return the least-anisotropic affine scales that can reach one target."""

    source_parts = _polygon_parts(source)
    if not source_parts:
        return None
    source_union = unary_union(source_parts)
    if source_union.is_empty or float(source_union.area) <= 1e-9:
        return None
    source_frame = source_union.convex_hull
    if not isinstance(source_frame, Polygon):
        return None
    source_angle, _source_width, _source_depth = _principal_frame(
        source_frame
    )
    target_angle = source_angle + float(target_angle_offset_degrees)
    source_width, source_depth = _frame_dimensions_at_angle(
        source_frame,
        source_angle,
    )
    host_width, host_depth = _frame_dimensions_at_angle(
        host,
        target_angle,
    )
    if min(source_width, source_depth, host_width, host_depth) <= 1e-9:
        return None
    requested_product = max(0.2, float(target_area)) / max(
        float(source_union.area),
        1e-9,
    )
    maximum_x = host_width / source_width * 0.995
    maximum_y = host_depth / source_depth * 0.995
    requested_product = min(requested_product, maximum_x * maximum_y)
    uniform = requested_product ** 0.5
    if uniform <= maximum_x and uniform <= maximum_y:
        return uniform, uniform
    x_scale = min(uniform, maximum_x)
    y_scale = requested_product / max(x_scale, 1e-9)
    if y_scale > maximum_y:
        y_scale = maximum_y
        x_scale = requested_product / max(y_scale, 1e-9)
    if min(x_scale, y_scale) <= 1e-9:
        return None
    return x_scale, y_scale


def _frame_dimensions_at_angle(
    polygon: Polygon,
    angle_degrees: float,
) -> tuple[float, float]:
    """Measure x/y extents in one explicit architectural frame."""

    aligned = rotate(
        polygon,
        -float(angle_degrees),
        origin=polygon.centroid,
        use_radians=False,
    )
    min_x, min_y, max_x, max_y = aligned.bounds
    return float(max_x - min_x), float(max_y - min_y)


def _exact_authored_mesh_section(
    source: SourceMass,
    *,
    height_fraction: float,
) -> Any | None:
    """Measure one horizontal section from the complete authored mesh.

    ``SourceVolume`` bands are conservative legal proxies. They intentionally
    union several mesh slices and therefore cannot be the geometry source for
    a later floor plate: doing so erases shear, twist, cuts and curved plans.
    """

    bridge = source.metadata.get("geometry_program_bridge_evidence")
    bridge = bridge if isinstance(bridge, dict) else {}
    raw_triangle_count = int(bridge.get("raw_mesh_triangle_count") or 0)
    exported_surface_count = int(bridge.get("exported_surface_count") or 0)
    if (
        raw_triangle_count > 0
        and exported_surface_count > 0
        and exported_surface_count < raw_triangle_count
    ):
        return None
    mesh_surfaces = tuple(
        surface
        for surface in source.surfaces
        if (
            surface.surface_type == "profiled_recursive_solid_mesh"
            and len(surface.vertices_m) == 3
        )
    )
    if not mesh_surfaces:
        return None
    origin = source.footprint.centroid
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    for surface in mesh_surfaces:
        offset = len(vertices)
        vertices.extend(
            (
                float(x) + float(origin.x),
                float(y) + float(origin.y),
                float(z),
            )
            for x, y, z in surface.vertices_m
        )
        triangles.append((offset, offset + 1, offset + 2))
    section_z = max(1e-5, min(1.0 - 1e-5, float(height_fraction)))
    # Use the same closed-solid section convention as the downstream legal
    # CSG. Segment polygonization is ambiguous when a floor centre is
    # coplanar with an authored terrace/cut face: it can union the footprints
    # on both sides of the plane even though Manifold's emitted solid selects
    # one side. That manufactures a capacity plate which the exact visual
    # mesh cannot reproduce at the certified midplane.
    try:
        import manifold3d as m3d
        import numpy as np

        mesh = m3d.Mesh(
            np.asarray(vertices, dtype=np.float64),
            np.asarray(triangles, dtype=np.uint32),
        )
        mesh.merge()
        solid = m3d.Manifold(mesh)
        contours = tuple(solid.slice(section_z).to_polygons())
        section = None
        if not solid.is_empty() and "NoError" in str(solid.status()):
            for contour in contours:
                polygon = Polygon(tuple(
                    (float(point[0]), float(point[1]))
                    for point in contour
                ))
                if (
                    polygon.is_empty
                    or not polygon.is_valid
                    or float(polygon.area) <= 1e-10
                ):
                    continue
                section = (
                    polygon
                    if section is None
                    else section.symmetric_difference(polygon)
                )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        section = None
    if section is None or section.is_empty or float(section.area) <= 1e-9:
        return None
    return section


def _floor_target_fit_is_legal(
    *,
    achieved_area_m2: float,
    maximum_legal_area_m2: float,
) -> bool:
    achieved = float(achieved_area_m2)
    legal_maximum = float(maximum_legal_area_m2)
    return (
        isfinite(achieved)
        and isfinite(legal_maximum)
        and achieved > 1e-9
        and achieved <= legal_maximum + 1e-6
    )


def _floor_visual_section_matches_occupied(
    *,
    measured_area_m2: float,
    occupied_area_m2: float,
) -> bool:
    return abs(
        round(float(measured_area_m2), 6)
        - round(float(occupied_area_m2), 6)
    ) <= 1e-4


def materialize_floorwise_legal_source(
    source: SourceMass,
    *,
    legal_sections: tuple[Polygon, ...],
    target_plan_coverage: float,
    coverage_capacity_m2: float | None = None,
    site_access_side: str = "closed",
    floor_capacity_plan_hash: str = "",
    legal_floor_field_hash: str = "",
    target_floor_areas_m2: tuple[float, ...] = (),
    component_layout: tuple[tuple[str, Any, float, float], ...] = (),
    terminal_failure_sink: list[dict[str, Any]] | None = None,
) -> SourceMass | None:
    """Refit one authored AST body into one affine legal plate per floor.

    The input mesh/AST remains the design authority.  Each requested floor
    samples that body's existing vertical profile, then receives a derived
    homogeneous transform into the corresponding live legal section.  No
    parcel coordinate or completed form is stored in the reusable program.
    """

    def _record_terminal_failure(
        sink: list[dict[str, Any]] | None,
        stage: str,
        **evidence: Any,
    ) -> None:
        """Bind every terminal branch to this legal-field context."""

        evidence["legal_floor_field_hash"] = str(
            legal_floor_field_hash or ""
        )
        _append_terminal_failure(sink, stage, **evidence)

    if not source.volumes or not legal_sections:
        _record_terminal_failure(
            terminal_failure_sink,
            "source_floor_section",
            source_volume_count=len(source.volumes),
            legal_section_count=len(legal_sections),
        )
        return None
    coverage = max(0.05, min(0.95, float(target_plan_coverage or 0.0)))
    floor_count = len(legal_sections)
    primary_role = max(
        source.volumes,
        key=lambda volume: (
            float(volume.footprint.area)
            * max(0.0, float(volume.top_fraction) - float(volume.bottom_fraction))
        ),
    ).role
    active_by_floor: list[Any] = []
    exact_mesh_section_count = 0
    for floor_index in range(floor_count):
        fraction = (floor_index + 0.5) / floor_count
        exact_section = _exact_authored_mesh_section(
            source,
            height_fraction=fraction,
        )
        if exact_section is not None:
            active_by_floor.append(exact_section)
            exact_mesh_section_count += 1
            continue
        active = [
            volume.footprint
            for volume in source.volumes
            if float(volume.bottom_fraction) <= fraction < float(volume.top_fraction)
        ]
        active_by_floor.append(unary_union(active) if active else None)
    viable_source_sections = tuple(
        geometry
        for geometry in active_by_floor
        if geometry is not None
        and not geometry.is_empty
        and float(geometry.area) > 1e-9
    )
    ground_source = (
        max(
            viable_source_sections,
            key=lambda geometry: float(geometry.area),
        )
        if viable_source_sections
        else None
    )
    if ground_source is None or float(ground_source.area) <= 1e-9:
        _record_terminal_failure(
            terminal_failure_sink,
            "source_floor_section",
            floor_count=floor_count,
            viable_section_count=len(viable_source_sections),
        )
        return None
    ground_source_area = float(ground_source.area)
    visual_fit_parts = _polygon_parts(source.footprint)
    visual_fit_source = (
        unary_union(visual_fit_parts)
        if visual_fit_parts
        else None
    )
    if (
        visual_fit_source is None
        or visual_fit_source.is_empty
        or float(visual_fit_source.area) <= 1e-9
    ):
        _record_terminal_failure(
            terminal_failure_sink,
            "source_floor_section",
            footprint_part_count=len(visual_fit_parts),
        )
        return None
    ground_legal = repair_source_polygon(legal_sections[0], minimum_area=1.0)
    if ground_legal is None or ground_legal.is_empty:
        _record_terminal_failure(
            terminal_failure_sink,
            "source_floor_section",
            floor_index=0,
        )
        return None
    source_reference_angle, _source_width, _source_depth = _principal_frame(
        visual_fit_source.convex_hull
    )
    target_reference_angle, _target_width, _target_depth = _principal_frame(
        ground_legal
    )
    pose_rotation_degrees = target_reference_angle - source_reference_angle
    source_reference_center = visual_fit_source.centroid
    prepared_floors: list[tuple[Any, Polygon, float, float]] = []
    for floor_index, (raw_source, raw_legal) in enumerate(zip(
        active_by_floor,
        legal_sections,
    )):
        legal = repair_source_polygon(raw_legal, minimum_area=1.0)
        if (
            raw_source is None
            or raw_source.is_empty
            or legal is None
            or legal.is_empty
        ):
            _record_terminal_failure(
                terminal_failure_sink,
                "source_floor_section",
                floor_index=floor_index,
                source_present=raw_source is not None,
                legal_present=legal is not None,
            )
            return None
        source_parts = _polygon_parts(raw_source)
        source_plan = unary_union(source_parts)
        if source_plan.is_empty or float(source_plan.area) <= 1e-9:
            _record_terminal_failure(
                terminal_failure_sink,
                "source_floor_section",
                floor_index=floor_index,
                source_part_count=len(source_parts),
            )
            return None
        vertical_profile_ratio = max(
            0.05,
            min(1.25, float(source_plan.area) / ground_source_area),
        )
        planned_floor_area = (
            max(0.0, float(target_floor_areas_m2[floor_index]))
            if floor_index < len(target_floor_areas_m2)
            else 0.0
        )
        prepared_floors.append((
            source_plan,
            legal,
            vertical_profile_ratio,
            (
                planned_floor_area
                if planned_floor_area > 0.0
                else float(legal.area) * coverage
            ),
        ))

    target_reference_center = _access_reserve_target_center(
        ground_legal,
        site_access_side,
    )

    planned_floor_targets = tuple(
        planned_area
        for _source_plan, _legal, _profile_ratio, planned_area
        in prepared_floors
    )
    # 건축면적 is the building's horizontal projection (건축법 시행령 제119조
    # 제1항 제2호), so the coverage limit bounds every plate. Without it here
    # the plate cap is the legal section - the sunlight envelope, 1922 m2 on
    # PNU 4115011300106840001 against a 499.938 m2 coverage capacity - and the
    # ground design cap below could reach `legal.area * coverage`, i.e. 1826.
    # The affine placement path was bounded in 289084c; this is the repair path
    # that serves every candidate whose placement fails.
    plate_capacity = (
        float(coverage_capacity_m2)
        if coverage_capacity_m2 is not None
        and isfinite(float(coverage_capacity_m2))
        and float(coverage_capacity_m2) > 1e-9
        else None
    )
    legal_floor_caps = tuple(
            # The caller's planned target already carries its utilization
            # band. Retry targets may use the remaining legal plate; exact
            # polygon containment below remains the geometric authority.
            float(legal.area)
            if plate_capacity is None
            else min(float(legal.area), plate_capacity)
            for _source_plan, legal, _profile_ratio, _planned_area
            in prepared_floors
    )
    # `viable_source_sections` samples the source once per floor, at each
    # floor's mid-height. Anything that exists only between those heights -
    # which is what the volume-adding operatives produce - never appears in
    # them, so using them as the coverage denominator understates the body and
    # leaves the bound loose. Measured on PNU 4115011300106840001 after the
    # capacity loop was bounded: lodge still projected 599.9 m2 against a
    # 499.938 m2 cap, inflate 565.9, branch 540.5, while every mass built from
    # sampled-and-nothing-else sections landed exactly on the cap.
    #
    # 건축면적 is the projection of the whole body, so the denominator has to be
    # an upper bound on it. Both representations contribute: the volume
    # footprints span every height band, and the sampled sections carry the
    # exact authored mesh where one exists.
    #
    # Both are proxies for the body, and the thing finally measured is neither:
    # it is the mesh. A body that bulges between its proxy footprints and its
    # sampled sections - which is what `inflate` and `shift+notch` produce -
    # is understated by both, and an understated denominator is a loose bound.
    # `_source_surface_plan_projection_area` is 건축면적 by its definition, the
    # union of the delivered triangles projected onto XY, so it is the measure
    # the bound belongs on. Take the largest of the three: they all measure one
    # body's projection, so the largest is the honest upper bound, and a
    # denominator that is too large only costs floor area.
    source_projection_area = max(
        float(
            unary_union([
                *(
                    volume.footprint
                    for volume in source.volumes
                    if volume.footprint is not None
                    and not volume.footprint.is_empty
                ),
                *viable_source_sections,
            ]).area
        ),
        _source_surface_plan_projection_area(source),
    )
    if source_projection_area <= 1e-9:
        _record_terminal_failure(
            terminal_failure_sink,
            "floor_affine_fit",
            failure_reason="empty_source_plan_projection",
        )
        return None
    ground_design_cap = min(
        legal_floor_caps[0],
        max(
            planned_floor_targets[0],
            legal_floor_caps[0] * coverage,
        ),
    )
    # Every floor rides the same global plan-linear transform, so the
    # building's horizontal projection is the transformed union of the source
    # sections - and that union, not any single plate, is what 건축면적 means
    # (건축법 시행령 제119조 제1항 제2호). Laterally offset plates each fit under
    # a per-plate cap while their union does not: measured on PNU
    # 4115011300106840001, two plates sitting exactly on the 499.938 m2 cap
    # projected 587.6 m2 together, and the capacity record still reported
    # 2 x 499.938 because it samples one section per floor.
    #
    # The union scales with the same transform as the ground plate, so the cap
    # converts into ground-plate units in closed form. It bounds the geometry,
    # never the floor target vector: those targets are the certification
    # vector, and the authored fit is allowed to underfill them.
    coverage_ground_target_cap = (
        ground_source_area * plate_capacity / source_projection_area
        if plate_capacity is not None
        else None
    )
    allocated_floor_targets = _allocate_profiled_floor_targets(
        planned_floor_areas_m2=planned_floor_targets,
        legal_floor_caps_m2=legal_floor_caps,
        authored_profile_ratios=tuple(
            profile_ratio
            for _source_plan, _legal, profile_ratio, _planned_area
            in prepared_floors
        ),
        ground_design_cap_m2=ground_design_cap,
    )
    if (
        not allocated_floor_targets
        or abs(
            sum(allocated_floor_targets) - sum(planned_floor_targets)
        ) > 1e-6
    ):
        _record_terminal_failure(
            terminal_failure_sink,
            "floor_affine_fit",
            floor_count=floor_count,
            requested_floor_count=len(planned_floor_targets),
        )
        return None
    global_axis_scales = _requested_plan_axis_scales(
        ground_source,
        ground_legal,
        target_area=(
            allocated_floor_targets[0]
            if allocated_floor_targets
            else float(ground_legal.area) * coverage
        ),
        target_angle_offset_degrees=pose_rotation_degrees,
    )
    if global_axis_scales is None:
        _record_terminal_failure(
            terminal_failure_sink,
            "floor_affine_fit",
            floor_index=0,
        )
        return None
    _requested_global_x_scale, _requested_global_y_scale = global_axis_scales
    global_anisotropy_ratio = (
        _requested_global_x_scale
        / max(_requested_global_y_scale, 1e-9)
    )
    # One authored body has one plan-linear transform.  Select the largest
    # global scale that respects every floor target before legal clipping;
    # upper legal contraction may reduce the achieved area further, but may
    # never authorize a per-floor angle/aspect rewrite to recover FAR.
    global_area_scale_product = _global_capacity_area_scale_product(
        planned_floor_areas_m2=allocated_floor_targets,
        source_floor_areas_m2=tuple(
            float(source_plan.area)
            for source_plan, _legal, _profile, _planned in prepared_floors
        ),
    )
    if plate_capacity is not None:
        # 건축면적 is the projection of the whole building - the union of the
        # plates, not any one of them. Capping each plate does not cap their
        # union: this path places floors that are laterally shifted relative
        # to one another, so three 400 m2 plates project to well over 800, and
        # capping plates alone left 17 of 30 masses over the limit with the
        # numbers byte-identical.
        #
        # One global plan-linear transform serves the whole body here, so the
        # projected union is exactly linear in this area scale product and the
        # bound is closed form, the same way it is in the affine placement
        # path.
        global_area_scale_product = min(
            global_area_scale_product,
            plate_capacity / source_projection_area,
        )
    if global_area_scale_product <= 0.0:
        _record_terminal_failure(
            terminal_failure_sink,
            "floor_affine_fit",
            failure_reason="invalid_global_capacity_area_scale",
        )
        return None
    requested_total = sum(allocated_floor_targets)
    global_ground_target_area = (
        float(ground_source.area) * global_area_scale_product
    )
    global_fit_evidence: dict[str, Any] = {}
    global_fit = _matrix_fit_polygon_to_host(
        ground_source,
        ground_legal,
        target_area=global_ground_target_area,
        target_center=(
            float(target_reference_center.x),
            float(target_reference_center.y),
        ),
        target_angle_offset_degrees=pose_rotation_degrees,
        anisotropy_ratio=global_anisotropy_ratio,
        allow_legal_csg_projection=True,
        allow_pose_reflow=False,
        fit_evidence=global_fit_evidence,
    )
    if global_fit is None:
        _record_terminal_failure(
            terminal_failure_sink,
            "floor_affine_fit",
            **_floor_affine_terminal_evidence(
                source=source,
                floor_index=0,
                legal=ground_legal,
                target_area_m2=(
                    global_ground_target_area
                ),
                fit_evidence=global_fit_evidence,
            ),
        )
        return None

    def optimize_stack_translation(
        fit_result: tuple[
            Any,
            tuple[tuple[float, float, float, float], ...],
        ],
    ) -> tuple[Any, tuple[tuple[float, float, float, float], ...]]:
        optimized_matrix = _optimize_floorwise_matrix_translation(
            fit_result[1],
            source_sections=tuple(
                source_plan
                for source_plan, _legal, _profile, _planned in prepared_floors
            ),
            legal_sections=tuple(
                legal
                for _source, legal, _profile, _planned in prepared_floors
            ),
            site_access_side=site_access_side,
            minimum_total_area_m2=requested_total,
        )
        transformed_ground = affine_transform(
            ground_source,
            [
                optimized_matrix[0][0],
                optimized_matrix[0][1],
                optimized_matrix[1][0],
                optimized_matrix[1][1],
                optimized_matrix[0][3],
                optimized_matrix[1][3],
            ],
        )
        occupied_parts = _polygon_parts(
            transformed_ground.intersection(ground_legal)
        )
        return (
            unary_union(occupied_parts) if occupied_parts else transformed_ground,
            optimized_matrix,
        )

    global_fit = optimize_stack_translation(global_fit)

    capacity_compensation_iterations = 0
    for _iteration in range(4):
        _occupied, candidate_matrix = global_fit
        achieved_total = 0.0
        for source_plan, legal, _profile, _planned in prepared_floors:
            transformed = affine_transform(
                source_plan,
                [
                    candidate_matrix[0][0],
                    candidate_matrix[0][1],
                    candidate_matrix[1][0],
                    candidate_matrix[1][1],
                    candidate_matrix[0][3],
                    candidate_matrix[1][3],
                ],
            )
            achieved_total += float(transformed.intersection(legal).area)
        if achieved_total + 1e-6 >= requested_total:
            break
        compensated_target = _capacity_compensated_global_target_area(
            current_ground_target_area_m2=global_ground_target_area,
            requested_total_area_m2=requested_total,
            achieved_total_area_m2=achieved_total,
            maximum_ground_target_area_m2=(
                ground_design_cap
                if coverage_ground_target_cap is None
                else min(ground_design_cap, coverage_ground_target_cap)
            ),
        )
        if compensated_target <= global_ground_target_area + 1e-7:
            break
        next_evidence: dict[str, Any] = {}
        next_fit = _matrix_fit_polygon_to_host(
            ground_source,
            ground_legal,
            target_area=compensated_target,
            target_center=(
                float(target_reference_center.x),
                float(target_reference_center.y),
            ),
            target_angle_offset_degrees=pose_rotation_degrees,
            anisotropy_ratio=global_anisotropy_ratio,
            allow_legal_csg_projection=True,
            allow_pose_reflow=False,
            fit_evidence=next_evidence,
        )
        if next_fit is None:
            break
        next_fit = optimize_stack_translation(next_fit)
        previous_area = float(global_fit[0].area)
        next_area = float(next_fit[0].area)
        if next_area <= previous_area + 1e-7:
            break
        global_fit = next_fit
        global_fit_evidence = next_evidence
        global_ground_target_area = compensated_target
        capacity_compensation_iterations += 1
    _global_occupied, global_matrix = global_fit
    global_matrix_area_scale = abs(
        float(global_matrix[0][0]) * float(global_matrix[1][1])
        - float(global_matrix[0][1]) * float(global_matrix[1][0])
    )
    global_x_scale = (
        global_matrix_area_scale * global_anisotropy_ratio
    ) ** 0.5
    global_y_scale = (
        global_matrix_area_scale / global_anisotropy_ratio
    ) ** 0.5

    fitted_floor_results: list[
        tuple[Any, tuple[tuple[float, float, float, float], ...]] | None
    ] = []
    floor_anisotropy_ratios: list[float] = []
    floor_fit_evidence: list[dict[str, Any]] = []
    for floor_index, (
        source_plan,
        legal,
        _vertical_profile_ratio,
        _planned_floor_area,
    ) in enumerate(prepared_floors):
        target_area = allocated_floor_targets[floor_index]
        floor_anisotropy_ratios.append(global_anisotropy_ratio)
        transformed = affine_transform(
            source_plan,
            [
                global_matrix[0][0],
                global_matrix[0][1],
                global_matrix[1][0],
                global_matrix[1][1],
                global_matrix[0][3],
                global_matrix[1][3],
            ],
        )
        occupied_parts = _polygon_parts(transformed.intersection(legal))
        occupied = unary_union(occupied_parts) if occupied_parts else None
        fit_evidence: dict[str, Any] = {
            "fit_mode": "single_global_matrix4_with_legal_csg",
            "target_area_m2": float(target_area),
            "achieved_area_m2": (
                float(occupied.area) if occupied is not None else 0.0
            ),
            "anisotropy_ratio": float(global_anisotropy_ratio),
            "frame_angle_degrees": float(target_reference_angle),
        }
        floor_fit_evidence.append(fit_evidence)
        fitted_floor_results.append(
            (occupied, global_matrix)
            if occupied is not None and not occupied.is_empty
            else None
        )

    strict_total = sum(
        float(fitted[0].area)
        for fitted in fitted_floor_results
        if fitted is not None
    )
    pose_fit_mode = (
        "single_global_rotation_translation_with_floor_relative_pose_preserved"
    )
    pose_fallback_used = False
    if any(fitted is None for fitted in fitted_floor_results):
        failed_floor_index = next(
            index
            for index, fitted in enumerate(fitted_floor_results)
            if fitted is None
        )
        _record_terminal_failure(
            terminal_failure_sink,
            "floor_affine_fit",
            **_floor_affine_terminal_evidence(
                source=source,
                floor_index=failed_floor_index,
                legal=prepared_floors[failed_floor_index][1],
                target_area_m2=allocated_floor_targets[failed_floor_index],
                fit_evidence=floor_fit_evidence[failed_floor_index],
            ),
            fitted_floor_count=sum(
                fitted is not None for fitted in fitted_floor_results
            ),
        )
        return None

    volumes: list[SourceVolume] = []
    floor_evidence: list[dict[str, Any]] = []
    floor_unions: list[Any] = []
    for floor_index, (
        source_plan,
        legal,
        vertical_profile_ratio,
        planned_floor_area,
    ) in enumerate(prepared_floors):
        target_area = (
            allocated_floor_targets[floor_index]
            if floor_index < len(allocated_floor_targets)
            else 0.0
        )
        fitted = fitted_floor_results[floor_index]
        if fitted is None:
            _record_terminal_failure(
                terminal_failure_sink,
                "floor_affine_fit",
                floor_index=floor_index,
            )
            return None
        visual_fit, matrix = fitted
        # The floor Matrix4 result is the only geometry/GFA authority.  The
        # former path discarded this authored fit and manufactured a separate
        # uniformly scaled legal plate, so FAR passed on one polygon while the
        # renderer-visible mesh remained smaller.  Reject an infeasible pose
        # here and transport the exact contained visual section as the volume.
        if not _floor_target_fit_is_legal(
            achieved_area_m2=float(visual_fit.area),
            maximum_legal_area_m2=float(legal.area),
        ):
            _record_terminal_failure(
                terminal_failure_sink,
                "floor_affine_fit",
                **_floor_affine_terminal_evidence(
                    source=source,
                    floor_index=floor_index,
                    legal=legal,
                    target_area_m2=target_area,
                    achieved_area_m2=float(visual_fit.area),
                    fit_evidence=floor_fit_evidence[floor_index],
                ),
            )
            return None
        occupied = visual_fit
        if not legal.buffer(1e-7).covers(occupied):
            _record_terminal_failure(
                terminal_failure_sink,
                "floor_affine_fit",
                floor_index=floor_index,
                containment="failed",
            )
            return None
        occupied_parts = _polygon_parts(occupied)
        if not occupied_parts:
            _record_terminal_failure(
                terminal_failure_sink,
                "floor_affine_fit",
                floor_index=floor_index,
                occupied_part_count=0,
            )
            return None
        bottom = floor_index / floor_count
        top = (floor_index + 1) / floor_count
        # Height bands of one authored AST are one typed component: a unique
        # role per floor makes program hierarchy misread one building as five
        # unrelated siblings. Lateral lobes are the opposite case and were
        # swept up by the same rule - the authored program is a composition of
        # named components, and stamping one role on everything discarded it.
        # Measured: all 128 delivered masses carried one role at share 1.000,
        # while the sources they came from carried three or four at 0.43-0.67.
        component_regions = _component_regions_for_plan(
            component_layout,
            occupied,
            bottom_fraction=bottom,
            top_fraction=top,
        )
        for part in occupied_parts:
            for role, piece in _articulated_component_parts(
                part,
                component_regions,
                fallback_role=primary_role,
            ):
                volumes.append(SourceVolume(
                    role=role,
                    footprint=piece,
                    bottom_fraction=bottom,
                    top_fraction=top,
                    verb="floorwise_legal_matrix4",
                ))
        floor_union = unary_union(occupied_parts)
        floor_unions.append(floor_union)
        matrix_plan_determinant = abs(
            float(matrix[0][0]) * float(matrix[1][1])
            - float(matrix[0][1]) * float(matrix[1][0])
        )
        pre_csg_area = (
            float(source_plan.area) * matrix_plan_determinant
        )
        legal_csg_clip_area = max(
            0.0,
            pre_csg_area - float(floor_union.area),
        )
        floor_evidence.append({
            "floor": floor_index + 1,
            "matrix4": matrix4_to_lists(matrix),
            "source_plan_area_m2": round(float(source_plan.area), 4),
            "legal_plan_area_m2": round(float(legal.area), 4),
            "planned_floor_area_m2": round(planned_floor_area, 4),
            "target_plan_area_m2": round(target_area, 4),
            "achieved_plan_area_m2": round(float(floor_union.area), 4),
            "target_plan_coverage": round(coverage, 4),
            "vertical_profile_ratio": round(vertical_profile_ratio, 4),
            "plan_anisotropy_ratio": round(
                floor_anisotropy_ratios[floor_index],
                6,
            ),
            "floor_capacity_plan_hash": str(floor_capacity_plan_hash or ""),
            "legal_csg_clip_area_m2": round(
                legal_csg_clip_area,
                6,
            ),
            "legal_csg_projection_used": bool(
                legal_csg_clip_area > 1e-7
            ),
        })

    ground_diagnostics: dict[str, Any] = {}
    ground, _ = _repair_polygonal_floor_union(
        floor_unions[0],
        minimum_area=1.0,
        diagnostics=ground_diagnostics,
    )
    upper_diagnostics: dict[str, Any] = {}
    upper, _ = _repair_polygonal_floor_union(
        floor_unions[-1],
        minimum_area=0.0,
        diagnostics=upper_diagnostics,
    )
    if ground is None or upper is None:
        _record_terminal_failure(
            terminal_failure_sink,
            "authored_visual_authority",
            repair_reason="authored_visual_projection_revalidation_failed",
            failure_reason="revalidation_floor_union_invalid",
            failure_reasons=("revalidation_floor_union_invalid",),
            certificate_causes=("revalidation_floor_union_invalid",),
            certificate_modes=("post_projection_section_revalidation",),
            legal_floor_field_hash=str(legal_floor_field_hash or ""),
            floor_union_count=len(floor_unions),
            **{
                f"ground_{key}": value
                for key, value in ground_diagnostics.items()
            },
            **{
                f"upper_{key}": value
                for key, value in upper_diagnostics.items()
            },
        )
        return None
    # Law-derived floor plates remain the sole GFA authority.  A complete
    # authored triangle skin is carried separately through the same Matrix4
    # evidence so renderer/VLM diversity survives capacity materialization.
    from backend.app.modules.design.generation.maas.geometry_language.floorwise_visual_projection import project_floorwise_visual_mesh

    visual_projection = project_floorwise_visual_mesh(
        source,
        legal_sections=legal_sections,
        floor_matrices=tuple(
            fitted[1]
            for fitted in fitted_floor_results
            if fitted is not None
        ),
        capacity_plates=tuple(volumes),
        output_origin=(
            float(ground.centroid.x),
            float(ground.centroid.y),
        ),
    )
    profiled_clip_attempted = False
    section_loft_attempted = False
    internal_tread_area_ratio = 0.0
    if (
        not visual_projection.certificate.hard_pass
        and visual_projection.certificate.failure_reasons
        == ("projected_visual_mesh_outside_legal_section",)
    ):
        fallback_source = replace(
            source,
            metadata={
                **deepcopy(source.metadata),
                "floorwise_legal_matrix_stack": {
                    "status": "materialized",
                    "matrix_convention": "row_major_column_vector",
                    "floor_capacity_plan_hash": str(
                        floor_capacity_plan_hash or ""
                    ),
                    "floors": floor_evidence,
                },
            },
        )
        # Preserve the LLM-authored continuous skin first.  Rebuilding the
        # legal floor sections as a loft can certify the legal plates while
        # silently replacing a taper/shear/void with a visible cake-step mass.
        # The profiled CSG path clips the authored mesh itself and therefore
        # owns first refusal whenever the direct Matrix4 projection exits the
        # legal field.
        profiled_clip_attempted = True
        from backend.app.modules.design.generation.maas.geometry_language.floorwise_profiled_legal_clip import clip_profiled_mesh_to_floorwise_legal_solids, profiled_legal_section_authority_binding_hash

        profiled_projection = clip_profiled_mesh_to_floorwise_legal_solids(
            fallback_source,
            occupied_sections=tuple(floor_unions),
            legal_sections=legal_sections,
            floor_matrices=tuple(
                fitted[1]
                for fitted in fitted_floor_results
                if fitted is not None
            ),
            capacity_plates=tuple(volumes),
            output_origin=(
                float(ground.centroid.x),
                float(ground.centroid.y),
            ),
        )
        if (
            profiled_projection.certificate.hard_pass
            and profiled_projection.surfaces
        ):
            internal_tread_area_ratio = (
                _internal_horizontal_tread_area_ratio(
                    profiled_projection.surfaces
                )
            )
            if (
                internal_tread_area_ratio
                > INTERNAL_TREAD_COLLAPSE_AREA_RATIO
            ):
                # Floor-band CSG is a legal analysis operation.  Only when its
                # certified skin has collapsed into treads does replacing the
                # visible skin with the exact-section loft help.  The loft
                # independently proves every occupied mid-floor section, legal
                # containment and manifold closure; the original floor plates
                # remain GFA/parking authority.  Below that share the authored
                # clip stays: rebuilding from legal sections alone would trade
                # one small tread for a fully terraced legal body.
                from backend.app.modules.design.generation.maas.geometry_language.floorwise_section_loft import loft_floorwise_legal_sections

                section_loft_attempted = True
                visual_projection = loft_floorwise_legal_sections(
                    fallback_source,
                    occupied_sections=tuple(floor_unions),
                    legal_sections=legal_sections,
                    capacity_plates=tuple(volumes),
                    output_origin=(
                        float(ground.centroid.x),
                        float(ground.centroid.y),
                    ),
                )
            else:
                visual_projection = profiled_projection
        else:
            # No authored-mesh fallback is allowed to reconstruct a new
            # section-loft body.  That path can turn a failed taper/shear/void
            # into a legally certified but visually unrelated staircase.
            visual_projection = profiled_projection
    if (
        visual_projection.certificate.hard_pass
        and not visual_projection.surfaces
    ):
        _record_terminal_failure(
            terminal_failure_sink,
            "authored_visual_authority",
            repair_reason="authored_visual_projection_empty_surface_payload",
            failure_reason="authored_visual_projection_empty_surface_payload",
            failure_reasons=("authored_visual_projection_empty_surface_payload",),
            certificate_causes=("authored_visual_projection_empty_surface_payload",),
            certificate_modes=tuple(filter(None, (
                str(getattr(visual_projection.certificate, "status", "") or ""),
                str(getattr(visual_projection.certificate, "certification_mode", "") or ""),
            ))),
            legal_floor_field_hash=str(legal_floor_field_hash or ""),
        )
        return None
    if not visual_projection.certificate.hard_pass:
        certificate_to_dict = getattr(
            visual_projection.certificate,
            "to_dict",
            None,
        )
        projection_certificate = (
            certificate_to_dict()
            if callable(certificate_to_dict)
            else {}
        )
        failure_reasons = (
            getattr(visual_projection.certificate, "failure_reasons", ())
            or ("uncertified_visual_projection",)
        )
        _record_terminal_failure(
            terminal_failure_sink,
            "authored_visual_authority",
            repair_reason=(
                "authored_continuous_section_loft_failed"
                if section_loft_attempted
                else (
                    "authored_profiled_legal_clip_failed"
                    if profiled_clip_attempted
                    else "authored_matrix4_projection_failed"
                )
            ),
            failure_reason=str(failure_reasons[0]),
            failure_reasons=tuple(str(reason) for reason in failure_reasons),
            certificate_causes=tuple(str(reason) for reason in failure_reasons),
            certificate_modes=tuple(filter(None, (
                str(getattr(visual_projection.certificate, "status", "") or ""),
                str(getattr(visual_projection.certificate, "certification_mode", "") or ""),
            ))),
            legal_floor_field_hash=str(legal_floor_field_hash or ""),
            failure_witness=projection_certificate.get("failure_witness") or {},
            occupied_section_topology=(
                projection_certificate.get("occupied_section_topology") or []
            ),
            legal_section_topology=(
                projection_certificate.get("legal_section_topology") or []
            ),
            floor_center_topology_metrics=(
                projection_certificate.get("floor_center_topology_metrics") or []
            ),
        )
        return None
    measured_visual_source = replace(
        source,
        footprint=ground,
        upper_footprint=upper,
        volumes=tuple(volumes),
        surfaces=visual_projection.surfaces,
    )
    profiled_section_mode = (
        visual_projection.certificate.hard_pass
        and visual_projection.certificate.status == "certified"
        and visual_projection.certificate.certification_mode in {
            "floorwise_csg_section_loft",
            "floorwise_profiled_continuous_envelope_clip",
            "floorwise_profiled_legal_clip",
        }
    )
    capacity_section_equivalence_mode = bool(
        profiled_section_mode
        and visual_projection.certificate.certification_mode in {
            "floorwise_csg_section_loft",
            "floorwise_profiled_legal_clip",
        }
    )
    for floor_index, occupied_floor in enumerate(floor_unions):
        height_fraction = (floor_index + 0.5) / floor_count
        if profiled_section_mode:
            from backend.app.modules.design.generation.maas.geometry_language.profiled_mesh_numeric_repair import profiled_surface_section_polygon

            measured_section = profiled_surface_section_polygon(
                measured_visual_source.surfaces,
                origin_xy=(
                    float(ground.centroid.x),
                    float(ground.centroid.y),
                ),
                z=height_fraction,
            )
        else:
            measured_section = _exact_authored_mesh_section(
                measured_visual_source,
                height_fraction=height_fraction,
            )
        if measured_section is None and not measured_visual_source.surfaces:
            active_volume_sections = tuple(
                volume.footprint
                for volume in measured_visual_source.volumes
                if (
                    float(volume.bottom_fraction)
                    <= height_fraction
                    < float(volume.top_fraction)
                )
            )
            if active_volume_sections:
                measured_section = unary_union(active_volume_sections)
        topology_metrics = None
        if capacity_section_equivalence_mode and measured_section is not None:
            from backend.app.modules.design.generation.maas.geometry_language.profiled_mesh_numeric_repair import floor_center_numeric_equivalence

            topology_metrics = floor_center_numeric_equivalence(
                measured_section,
                occupied_floor,
                epsilon_m=float(
                    visual_projection.certificate.section_numeric_epsilon_m
                    or 1e-6
                ),
            )
        if (
            profiled_section_mode
            and not capacity_section_equivalence_mode
            and measured_section is not None
        ):
            certified_rows = (
                visual_projection.certificate
                .floor_center_topology_metrics
            )
            certified_row = (
                certified_rows[floor_index]
                if floor_index < len(certified_rows)
                else {}
            )
            section_matches = bool(
                measured_section.is_valid
                and not measured_section.is_empty
                and float(measured_section.area) > 1e-8
                and legal_sections[floor_index].buffer(max(
                    1e-7,
                    float(
                        visual_projection.certificate
                        .section_numeric_epsilon_m
                        or 1e-6
                    ),
                )).covers(measured_section)
                and certified_row.get("hard_pass") is True
                and abs(
                    float(certified_row.get("area_m2") or 0.0)
                    - float(measured_section.area)
                )
                <= max(
                    1e-7,
                    float(
                        visual_projection.certificate
                        .section_numeric_epsilon_m
                        or 1e-6
                    )
                    * max(1.0, float(measured_section.length)),
                )
            )
        else:
            section_matches = (
            topology_metrics is not None
            and topology_metrics.get("hard_pass") is True
            if capacity_section_equivalence_mode
            else measured_section is not None
            and _floor_visual_section_matches_occupied(
                measured_area_m2=float(measured_section.area),
                occupied_area_m2=float(occupied_floor.area),
            )
            )
        if not section_matches:
            topology_failure = (
                capacity_section_equivalence_mode
                and measured_section is not None
                and topology_metrics is not None
            )
            failure_code = (
                "revalidation_floor_section_missing"
                if measured_section is None
                else (
                    "revalidation_floor_section_topology_mismatch"
                    if topology_failure
                    else "revalidation_floor_section_area_mismatch"
                )
            )
            _record_terminal_failure(
                terminal_failure_sink,
                "authored_visual_authority",
                repair_reason="authored_visual_projection_revalidation_failed",
                failure_reason=failure_code,
                failure_reasons=(failure_code,),
                certificate_causes=(failure_code,),
                certificate_modes=("post_projection_section_revalidation",),
                legal_floor_field_hash=str(legal_floor_field_hash or ""),
                floor_index=floor_index,
                measured_section_present=measured_section is not None,
                failure_witness={
                    "floor_index": floor_index,
                    "certification_mode": (
                        visual_projection.certificate.certification_mode
                    ),
                    "profiled_section_mode": profiled_section_mode,
                    "capacity_section_equivalence_mode": (
                        capacity_section_equivalence_mode
                    ),
                    "measured_area_m2": (
                        float(measured_section.area)
                        if measured_section is not None
                        else None
                    ),
                    "certified_visible_area_m2": (
                        float(certified_row.get("area_m2") or 0.0)
                        if (
                            profiled_section_mode
                            and not capacity_section_equivalence_mode
                            and measured_section is not None
                        )
                        else None
                    ),
                    "occupied_area_m2": float(occupied_floor.area),
                    "legal_covers_measured": (
                        legal_sections[floor_index].buffer(max(
                            1e-7,
                            float(
                                visual_projection.certificate
                                .section_numeric_epsilon_m
                                or 1e-6
                            ),
                        )).covers(measured_section)
                        if measured_section is not None
                        else False
                    ),
                    **(topology_metrics or {}),
                },
            )
            return None
    metadata = deepcopy(source.metadata)
    bridge = metadata.get("geometry_program_bridge_evidence")
    bridge = bridge if isinstance(bridge, dict) else {}
    authored_program_payload = metadata.get("authored_geometry_program")
    if not isinstance(authored_program_payload, dict):
        authored_program_payload = metadata.get("geometry_program")
    if isinstance(authored_program_payload, dict):
        try:
            authored_program = GeometryProgram.from_dict(
                authored_program_payload
            )
            authored_program_hash = authored_program.program_hash()
        except (TypeError, ValueError):
            authored_program = None
            authored_program_hash = ""
        if (
            authored_program is not None
            and not authored_program.validate()
            and str(bridge.get("program_hash") or "")
            == authored_program_hash
        ):
            metadata["authored_geometry_program"] = (
                authored_program.to_dict()
            )
            bridge = deepcopy(bridge)
            bridge["upstream_authored_program_hash"] = (
                authored_program_hash
            )
            metadata["geometry_program_bridge_evidence"] = bridge
    metadata["floorwise_legal_matrix_stack"] = {
        "schema_version": "arr.maas.floorwise_legal_matrix_stack.v1",
        "status": "materialized",
        "floor_count": floor_count,
        "target_plan_coverage": round(coverage, 4),
        "matrix_convention": "row_major_column_vector",
        "pose_fit": pose_fit_mode,
        "pose_fallback_used": pose_fallback_used,
        "strict_pose_achieved_total_area_m2": round(strict_total, 4),
        "global_capacity_compensation_iterations": (
            capacity_compensation_iterations
        ),
        "global_capacity_compensated_ground_target_area_m2": round(
            global_ground_target_area,
            4,
        ),
        "strict_pose_required_total_area_m2": round(
            requested_total * 0.78,
            4,
        ),
        "global_pose_rotation_degrees": round(pose_rotation_degrees, 6),
        "global_plan_axis_scales": [
            round(global_x_scale, 6),
            round(global_y_scale, 6),
        ],
        "global_plan_anisotropy_ratio": round(global_anisotropy_ratio, 6),
        "geometry_program_hash": str(bridge.get("program_hash") or ""),
        "geometry_hash": str(bridge.get("geometry_hash") or ""),
        "floor_capacity_plan_hash": str(floor_capacity_plan_hash or ""),
        "target_floor_areas_m2": [
            round(max(0.0, float(value)), 4)
            for value in target_floor_areas_m2[:floor_count]
        ],
        "floor_area_allocation": (
            "whole_building_capacity_budget_with_live_legal_floor_caps"
        ),
        "floor_section_source": (
            "exact_authored_manifold_mesh"
            if exact_mesh_section_count == floor_count
            else "conservative_source_volume_proxy"
        ),
        "exact_authored_mesh_section_count": exact_mesh_section_count,
        "allocated_floor_areas_m2": [
            round(max(0.0, float(value)), 4)
            for value in allocated_floor_targets
        ],
        "source_authority": "same_authored_geometry_program_ast",
        "primary_component_role": primary_role,
        "legal_section_source": "live_pnu_generation_context",
        "csg_role": "legal_containment_only",
        "completed_building_template": False,
        "parcel_coordinates_stored_in_geometry_program": False,
        "floors": floor_evidence,
    }
    metadata["continuous_surface_evidence"] = {
        "schema_version": "arr.maas.continuous_surface_evidence.v1",
        "status": "superseded_by_floorwise_legal_matrix_stack",
        "hard_pass": False,
        "source_geometry_program_preserved": True,
    }
    metadata["floorwise_visual_projection"] = (
        visual_projection.certificate.to_dict()
    )
    # The final authority certificate is rebuilt downstream and drops the
    # upstream mode, so name the producer of the visible skin here.  Without
    # it a legal-section loft is indistinguishable from an authored body in
    # every persisted artifact.
    metadata["floorwise_visual_projection"]["visible_surface_producer"] = (
        _visible_surface_producer(
            visual_projection.certificate.certification_mode
        )
    )
    metadata["floorwise_visual_projection"][
        "visible_internal_tread_area_ratio"
    ] = round(float(internal_tread_area_ratio), 6)
    if (
        profiled_section_mode
        and visual_projection.certificate.certification_mode in {
            "floorwise_profiled_continuous_envelope_clip",
            "floorwise_profiled_legal_clip",
        }
    ):
        metadata["profiled_legal_section_authority_binding_hash"] = (
            profiled_legal_section_authority_binding_hash(
                tuple(floor_unions),
                legal_sections,
                (
                    float(ground.centroid.x),
                    float(ground.centroid.y),
                ),
            )
        )
    # Materialization changes the occupied plan on every level. Never retain
    # coherence evidence measured on the pre-fit BOOK body; downstream
    # program gates must judge the exact legal floor bands they will render.
    metadata["coherence_evidence"] = evaluate_source_volume_coherence(
        tuple(volumes)
    )
    return replace(
        source,
        footprint=ground,
        upper_footprint=upper,
        volumes=tuple(volumes),
        surfaces=visual_projection.surfaces,
        metadata=metadata,
    )


def floorwise_source_to_geometry_program(
    source: SourceMass,
    *,
    height_m: float,
    name: str | None = None,
    allow_tiny_footprint: bool = False,
) -> GeometryProgram:
    """Serialize legal floor plates for bounded analysis diagnostics only.

    This program may support isolated legal/GFA/parking transport diagnostics.
    It is never a candidate render, VLM, elevation, or final-geometry authority;
    the authored projected surface payload remains authoritative.
    """

    total_height = float(height_m)
    if total_height <= 0.0:
        raise ValueError("height_m must be positive")
    if not source.volumes:
        raise ValueError("floorwise source must contain at least one volume")
    stack = source.metadata.get("floorwise_legal_matrix_stack")
    if not isinstance(stack, dict) or stack.get("status") != "materialized":
        raise ValueError("source has no materialized floorwise legal matrix stack")

    origin = Point(*replay_polygon_origin(source.footprint))
    nodes: list[GeometryNode] = []
    solid_ids: list[str] = []
    bands: set[tuple[float, float]] = set()
    ordered_volumes = sorted(
        source.volumes,
        key=lambda volume: (
            float(volume.bottom_fraction),
            float(volume.top_fraction),
            volume.role,
            round(float(volume.footprint.centroid.x), 8),
            round(float(volume.footprint.centroid.y), 8),
        ),
    )
    minimum_replay_footprint_area = 0.0 if allow_tiny_footprint else 0.01

    for index, volume in enumerate(ordered_volumes, start=1):
        bottom = float(volume.bottom_fraction)
        top = float(volume.top_fraction)
        bottom_z = round(bottom * total_height, 8)
        top_z = round(top * total_height, 8)
        # Derive every extrusion from the same serialized z boundaries.
        # Rounding each 1/N height independently made a 1e-8 m gap between
        # the second and third bands of a three-floor stack.
        band_height = top_z - bottom_z
        if band_height <= 1e-8:
            raise ValueError("floorwise volume has a non-positive height band")
        footprint = repair_source_polygon(
            volume.footprint,
            minimum_area=minimum_replay_footprint_area,
        )
        if footprint is None:
            raise ValueError("floorwise volume has no replayable footprint")
        # Manifold CrossSection uses winding to distinguish material from
        # void. Live PNU/GEOS operations may return either exterior winding;
        # normalize the transport contract before serializing the AST.
        footprint = orient(footprint, sign=1.0)
        replay_points, replay_holes, replay_precision = (
            replay_polygon_point_payload(
                footprint,
                xoff=origin.x,
                yoff=origin.y,
            )
        )
        bands.add((round(bottom, 8), round(top, 8)))
        primitive_id = f"floor_plate_{index:02d}"
        translated_id = f"floor_position_{index:02d}"
        nodes.append(GeometryNode(
            id=primitive_id,
            kind="primitive",
            operator="extruded_polygon",
            parameters={
                "points": replay_points,
                "holes": replay_holes,
                "height": band_height,
            },
            semantic_role=volume.role or "floor_plate",
            provenance={
                "source": "floorwise_legal_matrix_stack",
                "volume_index": index,
                "verb": volume.verb,
                "bottom_fraction": round(bottom, 8),
                "top_fraction": round(top, 8),
                "ring_transport_precision": replay_precision,
            },
        ))
        nodes.append(GeometryNode(
            id=translated_id,
            kind="transform",
            operator="translate",
            inputs=(primitive_id,),
            parameters={"vector": [0.0, 0.0, bottom_z]},
            semantic_role=volume.role or "floor_plate",
            provenance={
                "source": "floorwise_legal_matrix_stack",
                "matrix_convention": stack.get("matrix_convention"),
            },
        ))
        solid_ids.append(translated_id)

    if len(solid_ids) == 1:
        root_id = solid_ids[0]
    else:
        root_id = "final_floorwise_union"
        nodes.append(GeometryNode(
            id=root_id,
            kind="boolean",
            operator="union",
            inputs=tuple(solid_ids),
            semantic_role="final_legal_mass",
            provenance={
                "source": "floorwise_legal_matrix_stack",
                "operation": "recompose_exact_floor_bands",
            },
        ))

    bridge = source.metadata.get("geometry_program_bridge_evidence")
    bridge = bridge if isinstance(bridge, dict) else {}
    authored_program = source.metadata.get("geometry_program")
    authored_program = authored_program if isinstance(authored_program, dict) else {}
    capacity_alternative = source.metadata.get("capacity_alternative_projection")
    capacity_alternative = (
        capacity_alternative if isinstance(capacity_alternative, dict) else {}
    )
    # Every floorwise replay serializes the same certified occupied polygons
    # into an executable AST. GEOS/manifold triangulation can introduce only
    # sub-1e-8 m duplicate edges regardless of which certified visual mode
    # supplied those polygons. Enable the proof-bounded transport for every
    # materialized stack: it runs only when ``tiny_edge`` is the sole failure
    # and rejects unless every repaired floor-center section is equivalent.
    replay_execution_contract = deepcopy(
        FLOORWISE_CAPACITY_REPLAY_TRANSPORT_CONTRACT
    )
    return GeometryProgram(
        nodes=tuple(nodes),
        root_id=root_id,
        name=name or f"{source.name}_floorwise_legal_projection",
        metadata={
            "family": "materialized_floorwise_legal_projection",
            "language_layer": "legal_analysis_proxy_diagnostic",
            "floorwise_projection": {
                "schema_version": "arr.maas.floorwise_geometry_program.v1",
                "status": "diagnostic_only",
                "floor_count": len(bands),
                "volume_count": len(ordered_volumes),
                "height_m": round(total_height, 6),
                "local_origin_utm": [
                    round(float(origin.x), 6),
                    round(float(origin.y), 6),
                ],
                "upstream_program_hash": str(
                    stack.get("geometry_program_hash")
                    or bridge.get("program_hash")
                    or ""
                ),
                "upstream_geometry_hash": str(
                    stack.get("geometry_hash")
                    or bridge.get("geometry_hash")
                    or ""
                ),
                "floor_capacity_plan_hash": str(
                    stack.get("floor_capacity_plan_hash") or ""
                ),
                "target_floor_areas_m2": [
                    round(max(0.0, float(value)), 4)
                    for value in (stack.get("target_floor_areas_m2") or ())
                ],
                "requested_capacity_alternative_id": str(
                    capacity_alternative.get("requested_capacity_alternative_id")
                    or capacity_alternative.get("alternative_id")
                    or ""
                ),
                "requested_target_utilization": float(
                    capacity_alternative.get("requested_target_utilization")
                    or capacity_alternative.get("target_utilization")
                    or 0.0
                ),
                "selectable_capacity_alternative_id": str(
                    capacity_alternative.get("selectable_capacity_alternative_id")
                    or ""
                ),
                "selectable_capacity_target_utilization": float(
                    capacity_alternative.get(
                        "selectable_capacity_target_utilization"
                    )
                    or 0.0
                ),
                "authored_program_name": str(authored_program.get("name") or ""),
                "matrix_convention": str(
                    stack.get("matrix_convention") or "row_major_column_vector"
                ),
                "source_authority": "legal_analysis_proxy_only",
                "render_authority": False,
                "vlm_authority": False,
                "final_geometry_authority": False,
                "completed_building_template": False,
                "parcel_coordinates_are_execution_only": True,
            },
        },
        execution_contract=replay_execution_contract,
    )


def _matrix_fit_polygon_to_host(
    source: Any,
    host: Polygon,
    *,
    target_area: float,
    target_center: tuple[float, float] | None = None,
    target_angle_offset_degrees: float = 0.0,
    anisotropy_ratio: float = 1.0,
    allow_legal_csg_projection: bool = False,
    allow_pose_reflow: bool = True,
    minimum_contained_area_ratio: float = 0.78,
    fit_evidence: dict[str, Any] | None = None,
) -> tuple[Any, tuple[tuple[float, float, float, float], ...]] | None:
    """Return the largest fixed-pose affine fit that stays inside ``host``.

    The old fixed shrink ladder returned the first contained scale, so a jump
    from 0.97 to 0.95 could silently discard several square metres. Search the
    exact target first, then use deterministic bisection at the supplied angle
    and anisotropy. A capacity target never authorizes a different pose.
    """

    evidence = fit_evidence if fit_evidence is not None else {}
    evidence["target_area_m2"] = float(target_area)
    source_parts = _polygon_parts(source)
    if not source_parts:
        evidence["failure_reason"] = "no_positive_lower_projection"
        return None
    source_union = unary_union(source_parts)
    if source_union.is_empty or float(source_union.area) <= 1e-9:
        evidence["failure_reason"] = "no_positive_lower_projection"
        return None
    source_frame_polygon = source_union.convex_hull
    if not isinstance(source_frame_polygon, Polygon):
        evidence["failure_reason"] = "no_positive_lower_projection"
        return None
    source_angle, source_width, source_depth = _principal_frame(source_frame_polygon)
    _host_angle, target_width, target_depth = _principal_frame(host)
    if min(source_width, source_depth, target_width, target_depth) <= 1e-9:
        evidence["failure_reason"] = "no_positive_lower_projection"
        return None
    source_center = source_union.centroid
    # The recursive source is already in the live site's coordinate frame.
    # Keep that authored centroid and angle through every floor. Re-centering
    # and independently aligning each plate to the legal host erased shift,
    # shear, twist and asymmetric setback relations before selection.
    resolved_target_center = (
        Point(float(target_center[0]), float(target_center[1]))
        if target_center is not None
        else source_center
    )
    representative_center = host.representative_point()
    evidence.update({
        "requested_center_x": float(resolved_target_center.x),
        "requested_center_y": float(resolved_target_center.y),
        "representative_center_x": float(representative_center.x),
        "representative_center_y": float(representative_center.y),
    })
    target_centers = [resolved_target_center]
    if (
        representative_center.distance(resolved_target_center) > 1e-7
        and (
            (allow_legal_csg_projection and not allow_pose_reflow)
            or target_center is None
            or not host.buffer(1e-7).covers(resolved_target_center)
        )
    ):
        # An access-reserve point can be inside the legal polygon while being
        # too close to its boundary for the requested building footprint.
        # The old point-only test then shrank a feasible 68 m2 plate to 4 m2.
        # A representative-point fallback changes only the one global
        # translation; the authored Matrix4 linear block and all relative
        # floor poses remain intact.
        target_centers.append(representative_center)
    target_angle = source_angle + float(target_angle_offset_degrees)
    requested_area_scale_product = (
        max(0.2, float(target_area)) / max(float(source_union.area), 1e-9)
    )
    if requested_area_scale_product <= 1e-9:
        evidence["failure_reason"] = "no_positive_lower_projection"
        return None
    ratio = max(0.25, min(4.0, float(anisotropy_ratio or 1.0)))
    evidence.update({
        "frame_angle_degrees": float(target_angle),
        "anisotropy_ratio": float(ratio),
    })

    def fit(
        ratio: float,
        angle: float,
        uniform_factor: float,
        center: Point = resolved_target_center,
    ) -> tuple[Any, tuple[tuple[float, float, float, float], ...]]:
        x_scale = (requested_area_scale_product * ratio) ** 0.5 * uniform_factor
        y_scale = (requested_area_scale_product / ratio) ** 0.5 * uniform_factor
        matrix = compose_matrix4(
            translation_matrix4((-source_center.x, -source_center.y, 0.0)),
            rotation_matrix4((0.0, 0.0, -source_angle)),
            scale_matrix4((x_scale, y_scale, 1.0)),
            rotation_matrix4((0.0, 0.0, angle)),
            translation_matrix4((
                center.x,
                center.y,
                0.0,
            )),
        )
        fitted = affine_transform(
            source_union,
            [
                matrix[0][0],
                matrix[0][1],
                matrix[1][0],
                matrix[1][1],
                matrix[0][3],
                matrix[1][3],
            ],
        )
        return fitted, matrix

    containment_host = host.buffer(1e-7)
    candidate = None
    selected_center = resolved_target_center
    for center in target_centers:
        fitted, matrix = fit(ratio, target_angle, 1.0, center)
        if containment_host.covers(fitted):
            evidence.update({
                "fit_mode": "affine_exact_target",
                "selected_center_x": float(center.x),
                "selected_center_y": float(center.y),
                "scale_factor": 1.0,
                "achieved_area_m2": float(fitted.area),
                "lower_scale": 1.0,
                "upper_scale": 1.0,
                "lower_area_m2": float(fitted.area),
                "upper_area_m2": float(fitted.area),
            })
            return fitted, matrix

        lower = 0.0
        upper = 1.0
        center_candidate = None
        for _iteration in range(12):
            probe = (lower + upper) / 2.0
            fitted, matrix = fit(ratio, target_angle, probe, center)
            if containment_host.covers(fitted):
                lower = probe
                center_candidate = (fitted, matrix)
            else:
                upper = probe
        if (
            center_candidate is not None
            and (
                candidate is None
                or float(center_candidate[0].area)
                > float(candidate[0].area) + 1e-7
            )
        ):
            candidate = center_candidate
            selected_center = center

    # Before paying for legal CSG, restore the bounded committed reflow that
    # searches nearby pose/aspect variants of the same authored polygon.  Each
    # result remains one homogeneous affine image, so holes, concavities and
    # the authored silhouette survive; this path cannot manufacture a stepped
    # floor-plate recipe.
    selected_ratio = ratio
    selected_angle = target_angle
    if allow_legal_csg_projection and allow_pose_reflow:
        alternate_poses = tuple(
            (
                max(0.125, min(8.0, ratio * ratio_multiplier)),
                target_angle + angle_delta,
                center,
            )
            for ratio_multiplier in (
                1.20,
                1.0 / 1.20,
                1.44,
                1.0 / 1.44,
            )
            for angle_delta in (0.0, 6.0, -6.0)
            for center in target_centers
        )
        for alternate_ratio, alternate_angle, center in alternate_poses:
            alternate = fit(
                alternate_ratio,
                alternate_angle,
                1.0,
                center,
            )
            if containment_host.covers(alternate[0]):
                evidence.update({
                    "fit_mode": "affine_exact_target",
                    "selected_center_x": float(center.x),
                    "selected_center_y": float(center.y),
                    "scale_factor": 1.0,
                    "achieved_area_m2": float(alternate[0].area),
                    "lower_scale": 1.0,
                    "upper_scale": 1.0,
                    "lower_area_m2": float(alternate[0].area),
                    "upper_area_m2": float(alternate[0].area),
                })
                return alternate

        scored_poses: list[
            tuple[
                float,
                int,
                float,
                float,
                float,
                float,
                Point,
                tuple[
                    Any,
                    tuple[tuple[float, float, float, float], ...],
                ] | None,
            ]
        ] = []
        for pose_index, (
            alternate_ratio,
            alternate_angle,
            center,
        ) in enumerate(alternate_poses):
            alternate_lower = 0.0
            alternate_upper = 1.0
            alternate_candidate = None
            for _iteration in range(4):
                probe = (alternate_lower + alternate_upper) / 2.0
                fitted, matrix = fit(
                    alternate_ratio,
                    alternate_angle,
                    probe,
                    center,
                )
                if containment_host.covers(fitted):
                    alternate_lower = probe
                    alternate_candidate = (fitted, matrix)
                else:
                    alternate_upper = probe
            scored_poses.append((
                alternate_lower,
                pose_index,
                alternate_ratio,
                alternate_angle,
                alternate_lower,
                alternate_upper,
                center,
                alternate_candidate,
            ))

        best_area = float(candidate[0].area) if candidate is not None else 0.0
        for (
            _score,
            _pose_index,
            alternate_ratio,
            alternate_angle,
            alternate_lower,
            alternate_upper,
            center,
            alternate_candidate,
        ) in sorted(
            scored_poses,
            key=lambda item: (-item[0], item[1]),
        )[:2]:
            for _iteration in range(8):
                probe = (alternate_lower + alternate_upper) / 2.0
                fitted, matrix = fit(
                    alternate_ratio,
                    alternate_angle,
                    probe,
                    center,
                )
                if containment_host.covers(fitted):
                    alternate_lower = probe
                    alternate_candidate = (fitted, matrix)
                else:
                    alternate_upper = probe
            if alternate_candidate is None:
                continue
            alternate = fit(
                alternate_ratio,
                alternate_angle,
                alternate_lower,
                center,
            )
            alternate_area = float(alternate[0].area)
            if alternate_area > best_area + 1e-7:
                candidate = alternate
                best_area = alternate_area
                selected_ratio = alternate_ratio
                selected_angle = alternate_angle
                selected_center = center
    if not allow_legal_csg_projection:
        if candidate is None or float(candidate[0].area) <= 1e-9:
            evidence["failure_reason"] = "no_positive_lower_projection"
        else:
            evidence.update({
                "fit_mode": "affine_maximum_contained_lower",
                "achieved_area_m2": float(candidate[0].area),
            })
        return candidate

    # The legal placement contract is Matrix4 + typed CSG.  A near-fit
    # authored body may therefore grow in its fixed pose and be intersected
    # with the legal floor plate.  This closes a small irregular-boundary
    # shortfall without replacing the authored pose or accepting a low-
    # retention form.  The returned matrix remains the pre-CSG transform;
    # callers persist the clipped area as separate legal-projection evidence.
    minimum_projection_retention = max(
        0.0,
        min(1.0, float(minimum_contained_area_ratio)),
    )

    def projected_fit(
        uniform_factor: float,
    ) -> tuple[Any, tuple[tuple[float, float, float, float], ...]] | None:
        raw, projected_matrix = fit(
            selected_ratio,
            selected_angle,
            uniform_factor,
            selected_center,
        )
        projected_parts = _polygon_parts(
            raw.intersection(host)
        )
        if not projected_parts:
            return None
        projected = unary_union(projected_parts)
        # CSG is a bounded near-fit repair, not a license to grow a cross,
        # court or wing until its intersection becomes the legal host itself.
        # The parameter existed in the public contract but was previously
        # unused, allowing 20-30% retention to pass as authored geometry.
        if (
            float(projected.area) / max(float(raw.area), 1e-9)
            + 1e-9
            < minimum_projection_retention
        ):
            return None
        return projected, projected_matrix

    projection_lower = 0.0
    projection_upper = 1.0
    lower_projected = None
    upper_projected = None

    # First bracket either the requested area or the retention boundary.  A
    # rejected upper sample is still a useful bound: the requested target can
    # lie between the last retained sample and that first low-retention sample.
    # The previous loop skipped that interval and incorrectly rejected a
    # near-fit notch whose target was reachable at 85% retention.
    while projection_upper <= 8.0 + 1e-9:
        projected = projected_fit(projection_upper)
        if projected is None:
            if lower_projected is not None:
                break
        else:
            projected_area = float(projected[0].area)
            if projected_area + 1e-9 >= float(target_area):
                upper_projected = projected
                break
            if (
                projected_area > 0.0
                and (
                    lower_projected is None
                    or projected_area
                    > float(lower_projected[0].area) + 1e-9
                )
            ):
                projection_lower = projection_upper
                lower_projected = projected
        if projection_upper >= 8.0:
            break
        projection_upper = min(8.0, projection_upper * 1.25)

    # Refine both ordinary area brackets and a bracket capped by the retention
    # boundary.  ``None`` moves the upper bound down; it does not prove that
    # every smaller scale also violates retention.
    if lower_projected is not None or upper_projected is not None:
        for _iteration in range(24):
            probe = (projection_lower + projection_upper) / 2.0
            probe_projection = projected_fit(probe)
            if probe_projection is None:
                projection_upper = probe
                continue
            probe_area = float(probe_projection[0].area)
            if probe_area + 1e-9 >= float(target_area):
                projection_upper = probe
                upper_projected = probe_projection
            else:
                projection_lower = probe
                if (
                    lower_projected is None
                    or probe_area > float(lower_projected[0].area) + 1e-9
                ):
                    lower_projected = probe_projection

    if upper_projected is not None:
        # Use the closest under-target sample when bisection produced one; it
        # preserves the historical never-overfill contract to numerical
        # precision.  Otherwise the upper sample is already target-close.
        if lower_projected is None:
            lower_projected = upper_projected
            projection_lower = projection_upper
    if lower_projected is None or float(lower_projected[0].area) <= 1e-9:
        if candidate is None or float(candidate[0].area) <= 1e-9:
            evidence.update({
                "failure_reason": "no_positive_lower_projection",
                "lower_scale": float(projection_lower),
                "upper_scale": float(projection_upper),
                "upper_area_m2": (
                    float(upper_projected[0].area)
                    if upper_projected is not None
                    else 0.0
                ),
            })
            return None
        evidence.update({
            "fit_mode": "affine_maximum_contained_lower",
            "achieved_area_m2": float(candidate[0].area),
            "minimum_projection_retention": minimum_projection_retention,
        })
        return candidate
    evidence.update({
        "fit_mode": "legal_csg_maximum_lower",
        "selected_center_x": float(selected_center.x),
        "selected_center_y": float(selected_center.y),
        "scale_factor": float(projection_lower),
        "achieved_area_m2": float(lower_projected[0].area),
        "lower_scale": float(projection_lower),
        "upper_scale": float(projection_upper),
        "lower_area_m2": float(lower_projected[0].area),
        "best_sampled_lower_area_m2": float(lower_projected[0].area),
        "upper_area_m2": (
            float(upper_projected[0].area)
            if upper_projected is not None
            else 0.0
        ),
    })
    return lower_projected


def _floor_affine_terminal_evidence(
    *,
    source: SourceMass,
    floor_index: int,
    legal: Polygon,
    target_area_m2: float,
    fit_evidence: dict[str, Any],
    achieved_area_m2: float | None = None,
) -> dict[str, Any]:
    bridge = source.metadata.get("geometry_program_bridge_evidence")
    bridge = bridge if isinstance(bridge, dict) else {}
    legal_hash = hashlib.sha256(
        json.dumps(
            _canonical_polygon_payload(legal),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    evidence = {
        "failure_reason": str(
            fit_evidence.get("failure_reason") or "floor_target_fit_failed"
        ),
        "program_hash": str(bridge.get("program_hash") or ""),
        "geometry_family": str(
            bridge.get("geometry_family")
            or source.metadata.get("geometry_family")
            or ""
        ),
        "book_scope": str(source.metadata.get("book_scope") or ""),
        "floor_index": int(floor_index),
        "legal_section_hash": legal_hash,
        "target_area_m2": float(target_area_m2),
        "achieved_area_m2": float(
            achieved_area_m2
            if achieved_area_m2 is not None
            else fit_evidence.get("achieved_area_m2") or 0.0
        ),
    }
    for key in (
        "requested_center_x",
        "requested_center_y",
        "representative_center_x",
        "representative_center_y",
        "frame_angle_degrees",
        "anisotropy_ratio",
        "scale_factor",
        "lower_scale",
        "upper_scale",
        "lower_area_m2",
        "upper_area_m2",
    ):
        if key in fit_evidence:
            evidence[key] = fit_evidence[key]
    claimed_legal_section_hash = str(
        fit_evidence.get("legal_section_hash") or ""
    )
    if claimed_legal_section_hash:
        evidence["claimed_legal_section_hash"] = claimed_legal_section_hash
    return evidence


def compile_geometry_program_to_source_mass(
    program: GeometryProgram,
    host: Polygon,
    *,
    upper_host: Polygon | None = None,
    upper_fit_strength: float = 0.0,
    target_plan_area: float | None = None,
    minimum_plan_area: float | None = None,
    name: str | None = None,
    volume_role: str = "recursive_solid_primary",
    placement_policy: str | None = None,
    max_volume_bands: int = 3,
    max_raw_surfaces: int | None = None,
    gate_policy: GeometryGatePolicy | None = None,
    height_m: float | None = None,
    clip_to_host: bool = False,
    clip_sections: tuple | None = None,
    facing_angle_deg: float | None = None,
    impose_fit: bool = False,
) -> SourceMass | None:
    """Fit one compiled solid into a normalized host and preserve its mesh.

    `height_m` is how tall this parcel lets the mass stand, and it comes from
    the law - the storey cap and the storey height the legal site carries, not
    from the drawing. The fit normalizes Z to 1.0 so the bands can be
    fractions, so without it every mass the BOOK builds is one metre tall and
    measures its plan area. On 의정부 4115011300106840001 that is five storeys
    of 3.8 m: 19 m, and the same sentence read 1,747.2 m3 through massv2 and
    103.5 through here.

    The fit is derived from the host's principal frame.  Legal clipping is not
    performed here; callers should supply the legal generation host and send
    the returned source through the unchanged downstream hard gates.
    """

    return _compile_geometry_program_to_source_mass(
        program,
        host,
        upper_host=upper_host,
        upper_fit_strength=upper_fit_strength,
        target_plan_area=target_plan_area,
        minimum_plan_area=minimum_plan_area,
        name=name,
        volume_role=volume_role,
        placement_policy=placement_policy,
        max_volume_bands=max_volume_bands,
        max_raw_surfaces=max_raw_surfaces,
        gate_policy=gate_policy,
        height_m=height_m,
        clip_to_host=clip_to_host,
        clip_sections=clip_sections,
        facing_angle_deg=facing_angle_deg,
        impose_fit=impose_fit,
    )


def _compile_geometry_program_to_source_mass(
    program: GeometryProgram,
    host: Polygon,
    *,
    upper_host: Polygon | None = None,
    upper_fit_strength: float = 0.0,
    height_m: float | None = None,
    clip_to_host: bool = False,
    clip_sections: tuple | None = None,
    facing_angle_deg: float | None = None,
    impose_fit: bool = False,
    target_plan_area: float | None = None,
    minimum_plan_area: float | None = None,
    name: str | None = None,
    volume_role: str = "recursive_solid_primary",
    placement_policy: str | None = None,
    max_volume_bands: int = 3,
    max_raw_surfaces: int | None = None,
    gate_policy: GeometryGatePolicy | None = None,
    _site_bound_compilation: CompilationResult | None = None,
    _normalized_compilation: CompilationResult | None = None,
) -> SourceMass | None:
    """Materialize either a host-fitted or already site-bound compilation."""
    if (
        _site_bound_compilation is not None
        and _normalized_compilation is not None
    ):
        return None
    from backend.app.modules.design.generation.maas.dimensional_intent import POLICY
    if placement_policy not in (None, POLICY):
        raise ValueError("unsupported source placement policy")
    normalized_export = _normalized_compilation is not None
    host = repair_source_polygon(
        host,
        minimum_area=(1e-9 if normalized_export else 1.0),
    )
    if host is None:
        return None
    site_bound_export = _site_bound_compilation is not None
    identity_export = site_bound_export or normalized_export
    compilation = (
        _site_bound_compilation
        or _normalized_compilation
        or _compile_geometry_program_cached(program)
    )
    # Compiler probes may study a bounded multi-solid relation, but an object
    # promoted into the program/legal/VLM lane must already be one connected
    # architectural body.  This prevents tiny detached pieces from surviving
    # long enough to be mistaken for a creative finished mass.
    source_gate_policy = gate_policy or GeometryGatePolicy(maximum_components=1)
    if compilation.status != "compiled" or compilation_gate(compilation, source_gate_policy):
        return None
    base_seed_plan_fraction = _base_seed_plan_occupancy_fraction(program)
    if identity_export:
        effective_target_plan_area = None
        # Both identity exports normalize Z. The certificate layer compares a
        # `normalized_source_surface_payload_hash` against the source, and the
        # metric payload recovers metres by multiplying by the physical height;
        # a source whose Z was already metres makes those two payloads
        # identical and the comparison meaningless. The site-bound path used to
        # pass the compiled vertices through, which only stayed invisible while
        # every affine placement failed and this export never reached
        # certification. XY is re-based to the footprint centroid downstream in
        # both cases, so this makes the two exports one frame.
        bounds = (compilation.metrics or {}).get("bounds") or ()
        if len(bounds) != 2:
            return None
        minimum_z = float(bounds[0][2])
        vertical_span = float(bounds[1][2]) - minimum_z
        if not isfinite(vertical_span) or vertical_span <= 1e-9:
            return None
        host_fit_matrix4 = compose_matrix4(
            translation_matrix4((0.0, 0.0, -minimum_z)),
            scale_matrix4((1.0, 1.0, 1.0 / vertical_span)),
        )
        world_vertices = tuple(
            transform_point3(host_fit_matrix4, vertex)
            for vertex in compilation.vertices
        )
        host_fit_matrix4_exact = True
        legal_fit_mode = (
            "site_bound_matrix4"
            if site_bound_export
            else "normalized_authored_identity"
        )
        fit_strength = 0.0
    else:
        effective_target_plan_area = target_plan_area
        if base_seed_plan_fraction is not None and target_plan_area is None:
            base_seed_area_cap = float(host.area) * base_seed_plan_fraction
            effective_target_plan_area = base_seed_area_cap
        transformed = (_pose_metric_vertices_to_host(
                compilation, host, clip_to_host=clip_to_host,
                clip_sections=clip_sections, facing_angle_deg=facing_angle_deg,
                impose_fit=impose_fit)
            if placement_policy == POLICY else _fit_vertices_to_host(
                compilation, host, target_plan_area=effective_target_plan_area,
                minimum_plan_area=minimum_plan_area,
                clip_to_host=clip_to_host, facing_angle_deg=facing_angle_deg))
        if transformed is None:
            return None
        world_vertices = transformed.world_vertices
        host_fit_matrix4 = transformed.matrix4
        host_fit_matrix4_exact = True
        legal_fit_mode = POLICY if placement_policy == POLICY else "principal_frame_bounded"
        fit_strength = 0.0 if placement_policy == POLICY else max(0.0, min(1.0, float(upper_fit_strength)))
        if upper_host is not None and fit_strength > 1e-6:
            repaired_upper_host = repair_source_polygon(upper_host, minimum_area=1.0)
            upper_transformed = (
                _fit_vertices_to_host(
                    compilation,
                    repaired_upper_host,
                    facing_angle_deg=facing_angle_deg,
                    target_plan_area=effective_target_plan_area,
                    minimum_plan_area=minimum_plan_area,
                )
                if repaired_upper_host is not None
                else None
            )
            if upper_transformed is not None:
                upper_vertices = upper_transformed.world_vertices
                world_vertices = tuple(
                    (
                        lower[0] + (upper[0] - lower[0]) * lower[2] * fit_strength,
                        lower[1] + (upper[1] - lower[1]) * lower[2] * fit_strength,
                        lower[2],
                    )
                    for lower, upper in zip(world_vertices, upper_vertices)
                )
                legal_fit_mode = "height_interpolated_lower_upper_principal_frames"
                host_fit_matrix4_exact = False
    if clip_to_host:
        # The cut itself. The bands were already clipped to the host and the
        # plan measured through it, but the mesh that gets drawn, judged and
        # sectioned still stood past the boundary, and the delivered floor
        # evidence read "mesh area missing from proxy" on every FAR-sized
        # intent. The posed mesh is intersected with the host prism here,
        # so everything downstream - surfaces, sections, certificate - is
        # the building the law leaves.
        clipped = _clip_world_mesh_to_host(world_vertices, compilation.triangles, host,
                                           sections=clip_sections)
        if clipped is None:
            return None
        world_vertices, clipped_triangles = clipped
        compilation = replace(compilation, triangles=clipped_triangles)
    achieved_plan_area = _mesh_plan_projection_area(
        world_vertices,
        compilation.triangles,
    )
    if clip_to_host:
        # What gets built, not what the mesh projects: the boundary has already
        # taken the rest.
        achieved_plan_area = _mesh_plan_projection_area(
            world_vertices, compilation.triangles, host)
    minimum_plan_area_target = (
        max(0.2, float(minimum_plan_area))
        if minimum_plan_area is not None
        else None
    )
    minimum_plan_area_target_satisfied = (
        achieved_plan_area + 1e-7 >= minimum_plan_area_target
        if minimum_plan_area_target is not None
        else None
    )
    minimum_plan_area_shortfall_ratio = (
        max(0.0, (minimum_plan_area_target - achieved_plan_area) / minimum_plan_area_target)
        if minimum_plan_area_target is not None
        else None
    )
    floorwise_projection = (
        program.metadata.get("floorwise_legal_projection")
        if isinstance(
            program.metadata.get("floorwise_legal_projection"),
            dict,
        )
        else {}
    )
    preserve_site_bound_bands = bool(identity_export)
    try:
        requested_band_count = int(max_volume_bands)
    except (TypeError, ValueError, OverflowError):
        return None
    if preserve_site_bound_bands:
        if requested_band_count < 1:
            return None
        band_count = requested_band_count
    else:
        band_count = max(1, min(64, requested_band_count))
    band_boundaries = tuple(index / band_count for index in range(band_count + 1))
    # Measure the complete exported mesh with the solid kernel. Polygonizing
    # triangle/plane edges includes coplanar caps at some authored floor
    # centers and can turn a void into occupied area.
    try:
        section_solid = mesh_section_solid(world_vertices, compilation.triangles)
    except ValueError:
        return None
    volume_records: list[SourceVolume] = []
    proxy_band_part_counts: list[int] = []
    site_bound_legal = host.buffer(1e-7) if preserve_site_bound_bands else None
    for band_index, (bottom, top) in enumerate(zip(band_boundaries, band_boundaries[1:])):
        # A single mid-height slice under-reports an undercut, setback or
        # lifted body.  The proxy is the conservative vertical occupancy of
        # each band: union of lower/middle/upper measured mesh sections.
        epsilon = max(1e-5, (top - bottom) * 0.03)
        sections = tuple(
            solid_section_polygon(section_solid, sample)
            for sample in (
                bottom + epsilon,
                (bottom + top) / 2.0,
                top - epsilon,
            )
        )
        if preserve_site_bound_bands and any(
            section is not None
            and not _valid_positive_polygon_payload(section)
            for section in sections
        ):
            return None
        sections = tuple(
            section
            for section in sections
            if section is not None
        )
        if preserve_site_bound_bands and not sections:
            return None
        section = unary_union(sections) if sections else None
        if section is None:
            if preserve_site_bound_bands:
                return None
            continue
        parts = _polygon_parts(section)
        if preserve_site_bound_bands and (
            not parts
            or any(
                not _valid_positive_polygon_payload(part)
                or (
                    site_bound_export
                    and (
                        site_bound_legal is None
                        or not site_bound_legal.covers(part)
                    )
                )
                for part in parts
            )
        ):
            return None
        # A height-band limit is not a polygon-component limit. One connected
        # solid can have several disjoint sections above its connecting base.
        retained_parts = parts
        band_part_count = 0
        for part_index, part in enumerate(retained_parts):
            # The complete mesh has already passed host containment. Do not
            # simplify away occupied slivers or discard small connected parts.
            # The cut, not the shrink. A band is an arbitrary polygon here, so
            # what stands past the boundary is removed and what stands inside
            # keeps its own figure - the reading massv2's compiler already
            # takes band by band.
            #
            # A cut can leave more than one piece, and the first version of
            # this took `intersection` and kept it only when it came back a
            # single Polygon. On a concave parcel - the shape most of them are
            # - a bar crossing a notch comes back a MultiPolygon and the whole
            # band was dropped, which is a silent loss of exactly the kind the
            # rest of this file exists to prevent. `_polygon_parts` is what the
            # section above already uses to split one.
            pieces = (
                [piece for piece in _polygon_parts(part.intersection(
                    _clip_host_for_band(host, clip_sections, bottom, top)))
                 if not piece.is_empty and piece.area > 1e-9]
                if clip_to_host else [part]
            )
            if not pieces:
                if preserve_site_bound_bands:
                    return None
                continue
            for clipped in pieces:
                volume_records.append(SourceVolume(
                    # Height bands are legal proxies of one typed component,
                    # not separate architectural fragments. Keep component
                    # identity stable; bottom/top fractions still distinguish
                    # the bands.
                    role=volume_role,
                    footprint=clipped,
                    bottom_fraction=bottom,
                    top_fraction=top,
                    verb="geometry_program",
                ))
            band_part_count += 1
        if preserve_site_bound_bands:
            if band_part_count != len(parts) or band_part_count < 1:
                return None
        proxy_band_part_counts.append(band_part_count)
    if (
        preserve_site_bound_bands
        and len(proxy_band_part_counts) != band_count
    ):
        return None
    volumes = tuple(volume_records)
    if not volumes:
        if preserve_site_bound_bands:
            return None
        plan = repair_source_polygon(MultiPoint([(x, y) for x, y, _z in world_vertices]).convex_hull, minimum_area=0.2)
        if plan is None:
            return None
        clipped_plan = repair_source_polygon(plan.intersection(host), minimum_area=0.2)
        if clipped_plan is None:
            return None
        volumes = (SourceVolume(volume_role, clipped_plan, 0.0, 1.0, "geometry_program"),)
    footprint_union = unary_union([volume.footprint for volume in volumes if volume.bottom_fraction <= 1e-6])
    footprint = repair_source_polygon(footprint_union, minimum_area=0.2)
    if footprint is None:
        footprint = repair_source_polygon(unary_union([volume.footprint for volume in volumes]), minimum_area=0.2)
    if footprint is None:
        return None
    # SourceSurface vertices are local to SourceMass.footprint.centroid.  The
    # bridge host and the measured ground section can have different centres
    # (taper, shear, void and oblique cuts all cause this), so localise only
    # after the authoritative proxy footprint is known.
    surface_origin = footprint.centroid
    local_vertices = tuple(
        (x - surface_origin.x, y - surface_origin.y, z)
        for x, y, z in world_vertices
    )
    surfaces = _mesh_surfaces(
        local_vertices,
        compilation,
        volume_role=volume_role,
        max_raw_surfaces=max_raw_surfaces,
    )
    surface_export_complete = bool(
        surfaces
        and len(surfaces) == len(compilation.triangles)
    )
    if not surface_export_complete:
        return None
    surface_payload_hash = source_surface_payload_hash(surfaces)
    try:
        proxy_volume_payload_hash = source_volume_payload_hash(volumes)
    except (TypeError, ValueError):
        return None
    exported_proxy_band_count = len({
        (
            float(volume.bottom_fraction),
            float(volume.top_fraction),
        )
        for volume in volumes
    })
    if preserve_site_bound_bands and (
        exported_proxy_band_count != band_count
        or len(volumes) != sum(proxy_band_part_counts)
    ):
        return None
    upper_candidates = [volume.footprint for volume in volumes if volume.top_fraction >= 1.0 - 1e-6]
    upper = repair_source_polygon(unary_union(upper_candidates), minimum_area=0.2) if upper_candidates else None
    operator_path = [node.operator for node in program.topological_nodes()]
    # Imported lazily to keep the compiler/adapter dependency one-way.
    from backend.app.modules.design.generation.maas.geometry_language.vlm_adapter import build_geometry_graph_notes, build_geometry_graph_snapshot

    compilation_payload = compilation.to_dict(include_mesh=False)
    metadata = {
        "family": str(program.metadata.get("family") or program.name),
        "primary_language": str(program.metadata.get("family") or program.name),
        "formal_principle": str(program.metadata.get("family") or program.name),
        "dominant_gesture": str(program.metadata.get("family") or program.root_id),
        "reference_basis": str(program.metadata.get("reference_language") or "recursive_geometry_program"),
        "geometry_program": program.to_dict(),
        "geometry_program_compilation": compilation_payload,
        "mass_execution_passport": deepcopy(compilation_payload.get("execution_passport") or {}),
        "geometry_graph_notes": build_geometry_graph_notes(program, compilation),
        "geometry_graph_snapshot": build_geometry_graph_snapshot(program, compilation),
        "geometry_program_bridge_evidence": {
            "schema_version": "arr.maas.geometry_program_source_bridge.v1",
            "status": "materialized",
            "authoritative_visual_geometry": "manifold_compilation_mesh",
            "hard_gate_proxy": "measured_horizontal_mesh_sections",
            "proxy_section_mode": "conservative_band_vertical_occupancy_union",
            "geometry_hash": compilation.geometry_hash,
            "program_hash": program.program_hash(),
            "operator_path": operator_path,
            "proxy_volume_count": len(volumes),
            "requested_proxy_band_count": band_count,
            "exported_proxy_band_count": exported_proxy_band_count,
            "exported_proxy_part_count": len(volumes),
            "proxy_band_part_counts": list(proxy_band_part_counts),
            "proxy_volume_payload_hash": proxy_volume_payload_hash,
            "raw_mesh_triangle_count": len(compilation.triangles),
            "exported_surface_count": len(surfaces),
            "surface_export_complete": surface_export_complete,
            "surface_payload_hash": surface_payload_hash,
            "surface_coordinate_frame": "source_footprint_centroid_local",
            "host_fit_matrix4": matrix4_to_lists(host_fit_matrix4),
            "host_fit_matrix4_exact": host_fit_matrix4_exact,
            "host_contains_all_proxy_volumes": all(host.covers(volume.footprint) for volume in volumes),
            "parcel_coordinates_in_program": site_bound_export,
            "legal_fit_mode": legal_fit_mode,
            "legal_fit_strength": round(fit_strength, 4),
            "base_seed_plan_occupancy_fraction": (
                round(base_seed_plan_fraction, 4)
                if base_seed_plan_fraction is not None
                else None
            ),
            "effective_target_plan_area": (
                round(float(effective_target_plan_area), 4)
                if effective_target_plan_area is not None
                else None
            ),
            "explicit_target_plan_area_overrides_seed_occupancy_prior": bool(
                target_plan_area is not None
            ),
            # This is an authoring target, not a source-materialization gate.
            # Exact usable capacity and program fit remain downstream hard
            # gates, where a non-convex language can be measured honestly.
            "minimum_plan_area_target": (
                round(minimum_plan_area_target, 4)
                if minimum_plan_area_target is not None
                else None
            ),
            "achieved_mesh_plan_projection_area": round(achieved_plan_area, 4),
            "minimum_plan_area_target_satisfied": minimum_plan_area_target_satisfied,
            "minimum_plan_area_shortfall_ratio": (
                round(minimum_plan_area_shortfall_ratio, 4)
                if minimum_plan_area_shortfall_ratio is not None
                else None
            ),
        },
        "continuous_surface_evidence": {
            "schema_version": "arr.maas.continuous_surface.v1",
            "status": "materialized",
            "hard_pass": bool(surfaces),
            "principle": str(program.metadata.get("family") or program.name),
            "profiled_volume_count": 1,
            "surface_count": len(surfaces),
            "profiled_roles": [volume_role],
        },
        # How tall the thing this bridge just built actually is.
        #
        # A `SourceVolume` carries its band as a FRACTION of the whole, so every
        # consumer turns fractions into metres through
        # `metadata["authored_height_m"]` - `SourceMass.mass_properties`,
        # `plan_at`, `contains_point`, `body_height_m`, the parcel policy. Only
        # massv2's compiler was setting it, so a mass built on the BOOK's
        # executor came back measuring 0.0 m3 however correct its mesh was: one
        # sentence run both ways read 1,747.2 on one side and zero on the other,
        # and it was the ruler that was missing, not the building.
        #
        # Taken from the exported mesh's own vertices, which is the same solid
        # every band above was sectioned out of.
        "authored_height_m": round(
            float(height_m)
            if height_m is not None and float(height_m) > 1e-9
            else (
                max((float(z) for _x, _y, z in world_vertices), default=0.0)
                - min((float(z) for _x, _y, z in world_vertices), default=0.0)
            ),
            3,
        ),
        "datum_m": round(
            min((float(z) for _x, _y, z in world_vertices), default=0.0), 3),
        # The polygon the legal line cut this mass at, in the same world
        # frame as the fit matrix. A measurement that rebuilds the authored
        # solid to compare it with the delivery clips it to this first.
        **({"legal_host_clip": {
            "exterior": [[float(x), float(y)] for x, y in list(orient(host, sign=1.0).exterior.coords)[:-1]],
            "holes": [[[float(x), float(y)] for x, y in list(hole.coords)[:-1]]
                      for hole in orient(host, sign=1.0).interiors],
            # Floor by floor, in the same normalized z as the fit matrix: the
            # law's plan shrinks with height (정북일조), and a measurement that
            # rebuilds the authored solid clips each floor to its own section.
            "sections": [{
                "lo": float(lo), "hi": float(hi),
                "exterior": [[float(x), float(y)] for x, y in list(orient(poly, sign=1.0).exterior.coords)[:-1]],
                "holes": [[[float(x), float(y)] for x, y in list(hole.coords)[:-1]]
                          for hole in orient(poly, sign=1.0).interiors],
            } for lo, hi, poly in (clip_sections or ())],
            # The uniform plan scale the impose fit chose (1.0 = only cut).
            "impose_scale": (abs(host_fit_matrix4[0][0] * host_fit_matrix4[1][1]
                                 - host_fit_matrix4[0][1] * host_fit_matrix4[1][0]) ** 0.5
                             if impose_fit else 1.0),
        }} if clip_to_host else {}),
    }
    return SourceMass(
        name=name or f"geometry_program__{program.name}",
        footprint=footprint,
        upper_footprint=upper,
        volumes=volumes,
        surfaces=surfaces,
        notes=(
            "source=recursive_geometry_program",
            (
                "site_fit=site_bound_matrix4"
                if site_bound_export
                else (
                    "site_fit=normalized_authored_identity"
                    if normalized_export
                    else "site_fit=principal_frame_bounded"
                )
            ),
            f"legal_fit={legal_fit_mode}",
            "legal_proxy=measured_mesh_sections",
        ),
        metadata=metadata,
    )


def compile_normalized_geometry_program_to_source_mass(
    program: GeometryProgram,
    *,
    name: str | None = None,
    volume_role: str = "recursive_solid_primary",
    max_volume_bands: int = 3,
    max_raw_surfaces: int | None = None,
    gate_policy: GeometryGatePolicy | None = None,
) -> SourceMass | None:
    """Export the authored mesh in its normalized frame without a site fit."""

    compilation = _compile_geometry_program_cached(program)
    source_gate_policy = gate_policy or GeometryGatePolicy(maximum_components=1)
    if (
        compilation.status != "compiled"
        or compilation_gate(compilation, source_gate_policy)
        or not compilation.vertices
    ):
        return None
    authored_plan = MultiPoint(tuple(
        (float(x), float(y))
        for x, y, _z in compilation.vertices
    )).convex_hull
    if (
        not isinstance(authored_plan, Polygon)
        or authored_plan.is_empty
        or not authored_plan.is_valid
        or float(authored_plan.area) <= 1e-9
    ):
        return None
    return _compile_geometry_program_to_source_mass(
        program,
        authored_plan,
        name=name,
        volume_role=volume_role,
        max_volume_bands=max_volume_bands,
        max_raw_surfaces=max_raw_surfaces,
        gate_policy=source_gate_policy,
        _normalized_compilation=compilation,
    )


def compile_site_bound_geometry_program_to_source_mass(
    program: GeometryProgram,
    legal_host: Polygon,
    *,
    name: str | None = None,
    volume_role: str = "recursive_solid_primary",
    floor_count: int | None = None,
) -> SourceMass | None:
    """Export an already placed program from its exact compiled world mesh.

    ``floor_count`` is the caller's certified legal-field band count.  It is
    explicit because an unchanged-affine certificate is a result object, not
    hidden mutable program metadata.
    """

    if not _has_single_canonical_unitbox_authority(program):
        return None
    repaired_host = repair_source_polygon(legal_host, minimum_area=1.0)
    if repaired_host is None:
        return None
    compilation = _compile_geometry_program_cached(program)
    floorwise_projection = (
        program.metadata.get("floorwise_legal_projection")
        if isinstance(
            program.metadata.get("floorwise_legal_projection"),
            dict,
        )
        else {}
    )
    metadata_floor_count = int(floorwise_projection.get("floor_count") or 0)
    try:
        requested_floor_count = int(floor_count or metadata_floor_count)
    except (TypeError, ValueError):
        return None
    if requested_floor_count < 0:
        return None
    source_gate_policy = GeometryGatePolicy(maximum_components=1)
    if (
        compilation.status != "compiled"
        or compilation_gate(compilation, source_gate_policy)
        or (
            floorwise_projection
            and (
                floorwise_projection.get("hard_pass") is not True
                or str(
                    floorwise_projection.get("final_program_hash") or ""
                )
                != program.program_hash()
                or str(
                    floorwise_projection.get("final_geometry_hash") or ""
                )
                != compilation.geometry_hash
            )
        )
        or not _mesh_plan_projection_inside_host(
            compilation.vertices,
            compilation.triangles,
            repaired_host,
        )
    ):
        return None
    source = _compile_geometry_program_to_source_mass(
        program,
        repaired_host,
        name=name,
        volume_role=volume_role,
        max_volume_bands=max(1, requested_floor_count or 3),
        _site_bound_compilation=compilation,
    )
    if source is None:
        return None
    metadata = deepcopy(source.metadata)
    bridge = deepcopy(metadata.get("geometry_program_bridge_evidence") or {})
    actual_surface_hash = source_surface_payload_hash(tuple(source.surfaces or ()))
    try:
        actual_volume_hash = source_volume_payload_hash(
            tuple(source.volumes or ())
        )
    except (TypeError, ValueError):
        return None
    try:
        requested_proxy_band_count = int(
            bridge.get("requested_proxy_band_count") or 0
        )
        exported_proxy_band_count = int(
            bridge.get("exported_proxy_band_count") or 0
        )
        exported_proxy_part_count = int(
            bridge.get("exported_proxy_part_count") or 0
        )
        proxy_volume_count = int(bridge.get("proxy_volume_count") or 0)
        proxy_band_part_counts = tuple(
            int(value)
            for value in (bridge.get("proxy_band_part_counts") or ())
        )
    except (TypeError, ValueError):
        return None
    if (
        not source.volumes
        or requested_proxy_band_count < 1
        or exported_proxy_band_count != requested_proxy_band_count
        or exported_proxy_part_count != len(source.volumes)
        or proxy_volume_count != len(source.volumes)
        or len(proxy_band_part_counts) != requested_proxy_band_count
        or any(value < 1 for value in proxy_band_part_counts)
        or sum(proxy_band_part_counts) != len(source.volumes)
        or str(bridge.get("proxy_volume_payload_hash") or "")
        != actual_volume_hash
    ):
        return None
    if (
        floorwise_projection
        and (
            not source.surfaces
            or bridge.get("surface_export_complete") is not True
            or int(bridge.get("raw_mesh_triangle_count") or 0)
            != len(source.surfaces)
            or int(bridge.get("exported_surface_count") or 0)
            != len(source.surfaces)
            or str(bridge.get("surface_payload_hash") or "")
            != actual_surface_hash
        )
    ):
        return None
    bridge["geometry_authority"] = (
        "legal_analysis_proxy_only"
        if floorwise_projection
        else "site_bound_geometry_program"
    )
    metadata["geometry_program_bridge_evidence"] = bridge
    if floorwise_projection:
        metadata.update({
            "geometry_authority": "legal_analysis_proxy_only",
            "render_geometry_authority": False,
            "vlm_geometry_authority": False,
            "final_geometry_authority": False,
            "legal_proxy_role": "analysis_only_gfa_parking_containment",
            "final_program_hash": program.program_hash(),
            "final_geometry_hash": compilation.geometry_hash,
            "final_surface_payload_hash": actual_surface_hash,
            "final_proxy_volume_payload_hash": actual_volume_hash,
            "floorwise_legal_projection": deepcopy(floorwise_projection),
        })
    return replace(source, metadata=metadata)


def _has_single_canonical_unitbox_authority(program: GeometryProgram) -> bool:
    canonical_unitboxes = tuple(
        node
        for node in program.nodes
        if (
            node.kind == "primitive"
            and node.operator == "box"
            and node.parameters
            == {"width": 1.0, "depth": 1.0, "height": 1.0}
        )
    )
    # Typed cutters/profile primitives are legitimate operands in the same
    # authored DAG.  The canonical authority contract is exactly one UnitBox,
    # not exactly one primitive of any kind.  Keep this aligned with the
    # unchanged-affine legal certificate.
    return len(canonical_unitboxes) == 1


def _base_seed_plan_occupancy_fraction(program: GeometryProgram) -> float | None:
    """Convert normalized base proportions into a bounded plan-occupancy prior.

    This does not prescribe a completed footprint.  It only prevents a tower,
    compact block and low slab from all expanding to the same host-filling box.
    The value is derived from the catalog's plan-area-to-height proportion, so
    new catalog seeds participate without a parcel-specific lookup table.
    """
    raw_seed = program.metadata.get("base_seed")
    seed_id = str(
        raw_seed.get("seed_id") or raw_seed.get("id") or ""
        if isinstance(raw_seed, dict)
        else raw_seed or ""
    )
    spec = next((item for item in BASE_SEED_SPECS if item.seed_id == seed_id), None)
    if spec is None:
        return None
    proportions = [
        (item.normalized_scale[0] * item.normalized_scale[1])
        / max(item.normalized_scale[2], 0.2)
        for item in BASE_SEED_SPECS
    ]
    plan_to_height = (
        spec.normalized_scale[0] * spec.normalized_scale[1]
    ) / max(spec.normalized_scale[2], 0.2)
    normalized = max(0.0, min(1.0, plan_to_height / max(proportions)))
    return max(0.3, min(0.9, 0.25 + 0.65 * normalized ** 0.5))


def _compile_geometry_program_cached(program: GeometryProgram) -> CompilationResult:
    """Reuse host-independent manifold compilation by canonical AST hash."""
    key = program.program_hash()
    cached = _COMPILATION_CACHE.get(key)
    if cached is not None:
        _COMPILATION_CACHE.move_to_end(key)
        # Metadata/provenance is not part of the canonical geometry hash. Keep
        # the caller's exact program attached to otherwise identical geometry.
        return replace(cached, program=program)
    result = compile_geometry_program(program)
    _COMPILATION_CACHE[key] = result
    _COMPILATION_CACHE.move_to_end(key)
    while len(_COMPILATION_CACHE) > _COMPILATION_CACHE_LIMIT:
        _COMPILATION_CACHE.popitem(last=False)
    return result


def replace_source_dominant_with_geometry_program(
    source: SourceMass,
    program: GeometryProgram,
    *,
    max_total_volumes: int = 5,
    containment_host: Polygon | None = None,
    upper_containment_host: Polygon | None = None,
    upper_fit_strength: float = 0.0,
    minimum_host_plan_coverage: float = 0.0,
    failure_sink: list[dict[str, Any]] | None = None,
) -> SourceMass | None:
    """Compose a recursive primary solid with an existing program role graph."""
    def fail(reason: str, **evidence: Any) -> None:
        if failure_sink is None:
            return
        failure_sink.append({
            "schema_version": "arr.maas.source_dominant_replacement_failure.v1",
            "stage": "replace_source_dominant_with_geometry_program",
            "reason": reason,
            "evidence": deepcopy(evidence),
        })

    if not source.volumes:
        fail(
            "source_has_no_volumes",
            source_name=str(source.name),
            source_volume_count=0,
            program_name=str(program.name),
            program_hash=program.program_hash(),
        )
        return None
    dominant = max(source.volumes, key=lambda volume: volume.footprint.area * (volume.top_fraction - volume.bottom_fraction))
    subordinate = tuple(volume for volume in source.volumes if volume is not dominant)
    # The recursive manifold is the physical mass authority. Every remaining
    # legacy component rectangle is a normalized program-role zone inside it,
    # not an orange Lego box attached beside it. Supports, bridges and annexes
    # that must be physical are authored explicitly in the GeometryProgram.
    program_zone_volumes = subordinate
    physical_subordinate: tuple[SourceVolume, ...] = ()
    upper_dominant_host = None
    if upper_containment_host is not None:
        upper_dominant_host = repair_source_polygon(
            upper_containment_host,
            minimum_area=1.0,
        )
    # The old data-backed component rectangle is a program area prior, not a
    # second legal boundary.  Fitting a curved/U/winged graph inside that box
    # punished its empty convex-hull space and made only compact wedges pass.
    # Fit inside the real legal host, then absorb the original physical
    # component union into the new dominant envelope.  Subordinate service/
    # entry rectangles become spatial zones below; targeting only the old
    # dominant area erased their occupied plan and made every calm recursive
    # solid fail program coverage.  The downstream BCR/retention gate remains
    # authoritative, so this target cannot bypass the legal envelope.
    recursive_host = containment_host or dominant.footprint
    original_program_union = unary_union([
        volume.footprint for volume in source.volumes
        if not volume.footprint.is_empty
    ])
    coverage_floor = max(0.0, min(0.95, float(minimum_host_plan_coverage or 0.0)))
    program_target_plan_area = min(
        float(recursive_host.area),
        max(
            float(original_program_union.area),
            float(recursive_host.area) * coverage_floor,
        ),
    )
    recursive = compile_geometry_program_to_source_mass(
        program,
        recursive_host,
        upper_host=upper_dominant_host,
        upper_fit_strength=upper_fit_strength,
        target_plan_area=program_target_plan_area,
        minimum_plan_area=(
            float(recursive_host.area) * coverage_floor
            if coverage_floor > 1e-9
            else None
        ),
        name=f"{source.name}__geometry_{program.name}",
        volume_role=dominant.role,
        max_volume_bands=max(1, min(3, max_total_volumes - len(physical_subordinate))),
    )
    if recursive is None:
        replacement_compilation = (
            _compile_geometry_program_cached(program)
            if failure_sink is not None
            else None
        )
        replacement_gate_issues = (
            compilation_gate(
                replacement_compilation,
                GeometryGatePolicy(maximum_components=1),
            )
            if replacement_compilation is not None
            else ()
        )
        compilation_issue_codes = sorted({
            str(issue.code or "unknown")
            for issue in (
                replacement_compilation.issues
                if replacement_compilation is not None
                else ()
            )
        })[:16]
        compilation_gate_issue_codes = sorted({
            str(issue.code or "unknown")
            for issue in replacement_gate_issues
        })[:16]
        fail(
            "recursive_geometry_materialization_failed",
            source_name=str(source.name),
            program_name=str(program.name),
            program_hash=program.program_hash(),
            compilation_status=str(
                replacement_compilation.status
                if replacement_compilation is not None
                else "not_collected"
            ),
            compilation_geometry_hash=str(
                replacement_compilation.geometry_hash or ""
                if replacement_compilation is not None
                else ""
            ),
            compilation_issue_count=(
                len(replacement_compilation.issues)
                if replacement_compilation is not None
                else 0
            ),
            compilation_issue_codes=compilation_issue_codes,
            compilation_gate_issue_count=len(replacement_gate_issues),
            compilation_gate_issue_codes=compilation_gate_issue_codes,
            recursive_host_geom_type=str(recursive_host.geom_type),
            recursive_host_valid=bool(recursive_host.is_valid),
            recursive_host_empty=bool(recursive_host.is_empty),
            recursive_host_area_m2=float(recursive_host.area),
            upper_host_requested=upper_containment_host is not None,
            upper_host_repaired=upper_dominant_host is not None,
            upper_host_area_m2=(
                float(upper_dominant_host.area)
                if upper_dominant_host is not None
                else None
            ),
            upper_fit_strength=float(upper_fit_strength),
            target_plan_area_m2=float(program_target_plan_area),
            minimum_plan_area_m2=(
                float(recursive_host.area) * coverage_floor
                if coverage_floor > 1e-9
                else None
            ),
            maximum_components=1,
            maximum_volume_bands=max(
                1,
                min(3, max_total_volumes - len(physical_subordinate)),
            ),
        )
        return None
    program_space_zones = _normalized_program_space_zones(
        program_zone_volumes,
        original_dominant=dominant,
    )
    physical_subordinate, subordinate_offsets = _reattach_subordinate_volumes(
        recursive.volumes,
        physical_subordinate,
        original_dominant=dominant,
        containment_host=containment_host,
    )
    volumes = tuple((*recursive.volumes, *physical_subordinate))
    if len(volumes) > max_total_volumes:
        fail(
            "total_volume_budget_exceeded",
            source_name=str(source.name),
            program_name=str(program.name),
            program_hash=program.program_hash(),
            recursive_volume_count=len(recursive.volumes),
            physical_subordinate_volume_count=len(physical_subordinate),
            total_volume_count=len(volumes),
            max_total_volumes=int(max_total_volumes),
            volume_roles=[str(volume.role) for volume in volumes],
        )
        return None
    dominant_surface_roles = {
        dominant.role,
        *(
            surface.volume_role
            for surface in source.surfaces
            if surface.volume_role == dominant.role
        ),
    }
    union = unary_union([volume.footprint for volume in volumes])
    footprint = repair_source_polygon(union, minimum_area=1.0)
    if footprint is None:
        fail(
            "composed_footprint_invalid",
            source_name=str(source.name),
            program_name=str(program.name),
            program_hash=program.program_hash(),
            aggregate_geom_type=str(union.geom_type),
            aggregate_valid=bool(union.is_valid),
            aggregate_empty=bool(union.is_empty),
            aggregate_area_m2=float(union.area),
            component_count=len(volumes),
            minimum_area_m2=1.0,
        )
        return None
    recursive_surfaces = _rebase_surfaces(
        recursive.surfaces,
        from_origin=recursive.footprint.centroid,
        to_origin=footprint.centroid,
    )
    subordinate_surfaces = _rebase_surfaces(
        tuple(
        surface for surface in source.surfaces
        if surface.volume_role not in dominant_surface_roles
        and surface.volume_role not in {volume.role for volume in program_zone_volumes}
        ),
        from_origin=source.footprint.centroid,
        to_origin=footprint.centroid,
        role_offsets=subordinate_offsets,
    )
    surfaces = tuple((*recursive_surfaces, *subordinate_surfaces))
    metadata = dict(source.metadata)
    metadata.update({
        "family": recursive.metadata.get("family"),
        "primary_language": recursive.metadata.get("primary_language"),
        "formal_principle": recursive.metadata.get("formal_principle"),
        "dominant_gesture": recursive.metadata.get("dominant_gesture"),
        "reference_basis": recursive.metadata.get("reference_basis"),
        "geometry_program": recursive.metadata.get("geometry_program"),
        "geometry_program_compilation": recursive.metadata.get("geometry_program_compilation"),
        "geometry_graph_notes": recursive.metadata.get("geometry_graph_notes"),
        "geometry_graph_snapshot": recursive.metadata.get("geometry_graph_snapshot"),
        "geometry_program_bridge_evidence": recursive.metadata.get("geometry_program_bridge_evidence"),
        "continuous_surface_evidence": recursive.metadata.get("continuous_surface_evidence"),
        "program_space_zones": program_space_zones,
        "program_role_integration_evidence": {
            "schema_version": "arr.maas.program_role_integration.v1",
            "status": "materialized" if program_space_zones else "not_required",
            "mode": "normalized_spatial_zones_inside_dominant_envelope",
            "zone_count": len(program_space_zones),
            "external_program_box_count_removed": len(program_zone_volumes),
            "physical_subordinate_volume_count": len(physical_subordinate),
            "original_component_union_area_m2": round(float(original_program_union.area), 4),
            "recursive_target_plan_area_m2": round(program_target_plan_area, 4),
            "minimum_host_plan_coverage": round(coverage_floor, 4),
            "role_graph_preserved": True,
            "parcel_coordinates_stored": False,
        },
        # The dominant body's plan/section changed, so inherited coherence is
        # stale evidence. Re-measure the exact composed role volumes.
        "coherence_evidence": evaluate_source_volume_coherence(volumes),
    })
    return replace(
        source,
        name=recursive.name,
        footprint=footprint,
        upper_footprint=recursive.upper_footprint,
        volumes=volumes,
        surfaces=surfaces,
        notes=tuple((*source.notes, *recursive.notes)),
        metadata=metadata,
    )


def _is_internal_program_zone_role(role: str) -> bool:
    normalized = str(role).lower()
    return any(token in normalized for token in ("service", "entry", "canopy", "daylight", "monitor"))


def _normalized_program_space_zones(
    volumes: tuple[SourceVolume, ...],
    *,
    original_dominant: SourceVolume,
) -> list[dict[str, Any]]:
    if not volumes:
        return []
    angle, width, depth = _principal_frame(original_dominant.footprint)
    width = max(width, 1e-9)
    depth = max(depth, 1e-9)
    theta = angle * 3.141592653589793 / 180.0
    origin = original_dominant.footprint.centroid
    dominant_area = max(float(original_dominant.footprint.area), 1e-9)
    zones: list[dict[str, Any]] = []
    for volume in volumes:
        center = volume.footprint.centroid
        dx, dy = center.x - origin.x, center.y - origin.y
        normalized_long = max(0.0, min(1.0, 0.5 + (dx * cos(theta) + dy * sin(theta)) / width))
        normalized_short = max(0.0, min(1.0, 0.5 + (-dx * sin(theta) + dy * cos(theta)) / depth))
        nearest_side = min(
            (
                (normalized_long, "west"),
                (1.0 - normalized_long, "east"),
                (normalized_short, "south"),
                (1.0 - normalized_short, "north"),
            ),
            key=lambda item: item[0],
        )[1]
        zones.append({
            "zone_id": f"zone:{volume.role}",
            "role": volume.role,
            "relation": "embedded_in_dominant_envelope",
            "normalized_center": [
                round(normalized_long, 4),
                round(normalized_short, 4),
            ],
            "normalized_frame": "dominant_mass_principal_long_short_axes",
            "nearest_envelope_side": nearest_side,
            "plan_area_ratio": round(min(0.45, float(volume.footprint.area) / dominant_area), 4),
            "bottom_fraction": round(float(volume.bottom_fraction), 4),
            "top_fraction": round(float(volume.top_fraction), 4),
            "physical_envelope_owner_role": original_dominant.role,
        })
    return zones


def _clip_host_for_band(host, sections, bottom, top):
    """The legal section this band stands in; the ground host when none given."""
    if not sections:
        return host
    z = (float(bottom) + float(top)) / 2.0
    for lo, hi, poly in sections:
        if float(lo) - 1e-9 <= z < float(hi) + 1e-9:
            return poly
    return min(sections, key=lambda item: min(abs(z - float(item[0])), abs(z - float(item[1]))))[2]


def _clip_world_mesh_to_host(vertices, triangles, host, sections=None):
    """Intersect a posed mesh with the host prism; keep the largest piece.

    Returns (vertices, triangles) in the same world frame, or None when the
    kernel cannot make a solid of it or nothing is left inside. A cut can
    leave more than one piece (a wing severed at the boundary); the largest
    is the building and the rest is what the law took.
    """
    import numpy as np
    import manifold3d as m3d
    raw_vertices = np.asarray(vertices, dtype=float)
    raw_triangles = np.asarray(triangles, dtype=np.int64)
    if raw_vertices.ndim != 2 or raw_vertices.shape[1] != 3 or not len(raw_triangles):
        return None
    # Double precision: the reference this cut is later measured against is
    # the authored solid clipped in float64, and a float32 mesh in parcel
    # metres differs from it by ~5e-5 m2 per floor, past the export tolerance.
    mesh_type = getattr(m3d, "Mesh64", None) or m3d.Mesh
    mesh = mesh_type(raw_vertices, raw_triangles.astype(np.uint32, copy=False))
    mesh.merge()
    solid = m3d.Manifold(mesh)
    if "NoError" not in str(solid.status()) or solid.is_empty():
        return None
    z_low = float(raw_vertices[:, 2].min())
    z_high = float(raw_vertices[:, 2].max())

    def prism_of(polygon, lo, hi):
        ring = orient(polygon, sign=1.0)
        exterior = np.asarray(list(ring.exterior.coords)[:-1], dtype=float)
        holes = [np.asarray(list(hole.coords)[:-1], dtype=float) for hole in ring.interiors]
        return (
            m3d.CrossSection([exterior, *holes])
            .extrude(max(hi - lo, 1e-6))
            .translate((0.0, 0.0, lo))
        )

    if sections:
        # The legal envelope: one prism per floor section, the bottom one
        # reaching below the mesh and the top one above it. Adjacent prisms
        # overlap by a hair: stacked exactly, the kernel's union kept the
        # coincident face between two bands with the same plan as an internal
        # seam, the cut inherited it, decompose() split the building there,
        # and the largest-piece rule below threw the ground floor away
        # (comp21: 18 of 24 sentences refused for "no delivered occupied
        # section" on floor 1, whose legal section was the whole parcel).
        ordered = sorted(sections, key=lambda item: float(item[0]))
        overlap = max(1e-9, (z_high - z_low) * 1e-7)
        prisms = []
        for index, (lo, hi, poly) in enumerate(ordered):
            lo = float(lo) - overlap; hi = float(hi) + overlap
            if index == 0:
                lo = min(lo, z_low - 1.0)
            if index == len(ordered) - 1:
                hi = max(hi, z_high + 1.0)
            prisms.append(prism_of(poly, lo, hi))
        envelope = m3d.Manifold.batch_boolean(prisms, m3d.OpType.Add) if len(prisms) > 1 else prisms[0]
    else:
        envelope = prism_of(host, z_low - 1.0, z_high + 1.0)
    cut = m3d.Manifold.batch_boolean([solid, envelope], m3d.OpType.Intersect)
    if cut.is_empty():
        return None
    pieces = cut.decompose() or [cut]
    if len(pieces) > 1:
        # Pieces that touch are one building: the kernel's decompose splits
        # a composition of bars meeting face to face (comp24: an array of
        # three, the upper two dropped and floors 3-5 read at half their
        # reference). Touching pieces - bounding boxes meeting within a
        # hair - are clustered, and the cluster with the most volume is
        # kept; only what stands apart in space is what the law severed.
        def _size(piece):
            try:
                return float(piece.volume())
            except Exception:  # older kernels: bounding box stands in
                lo, hi = piece.bounding_box()
                return float((hi[0] - lo[0]) * (hi[1] - lo[1]) * (hi[2] - lo[2]))
        boxes = [np.asarray(piece.bounding_box(), dtype=float).reshape(2, 3) for piece in pieces]
        eps = max(1e-9, (z_high - z_low) * 1e-6)
        parent = list(range(len(pieces)))
        def _find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for i in range(len(pieces)):
            for j in range(i + 1, len(pieces)):
                if all(boxes[i][0][k] <= boxes[j][1][k] + eps and boxes[j][0][k] <= boxes[i][1][k] + eps
                       for k in range(3)):
                    parent[_find(i)] = _find(j)
        clusters: dict[int, list] = {}
        for index, piece in enumerate(pieces):
            clusters.setdefault(_find(index), []).append(piece)
        kept = max(clusters.values(), key=lambda group: sum(_size(piece) for piece in group))
        cut = kept[0] if len(kept) == 1 else m3d.Manifold.batch_boolean(kept, m3d.OpType.Add)
    out = cut.to_mesh64()
    out_vertices = np.asarray(out.vert_properties, dtype=float)[:, :3]
    out_triangles = np.asarray(out.tri_verts, dtype=np.int64)
    if not len(out_triangles):
        return None
    return (
        tuple((float(x), float(y), float(z)) for x, y, z in out_vertices),
        tuple((int(a), int(b), int(c)) for a, b, c in out_triangles),
    )


def _ground_contact_area(vertices, triangles, host=None) -> float:
    """Area of the faces that stand on the lowest plane, inside `host` if given."""
    if not vertices or not triangles:
        return 0.0
    z_low = min(v[2] for v in vertices)
    span = max(v[2] for v in vertices) - z_low
    eps = max(1e-6, span * 1e-4)
    faces = []
    for a, b, c in triangles:
        pa, pb, pc = vertices[a], vertices[b], vertices[c]
        if all(abs(pt[2] - z_low) <= eps for pt in (pa, pb, pc)):
            poly = Polygon([(pa[0], pa[1]), (pb[0], pb[1]), (pc[0], pc[1])])
            if poly.area > 1e-9:
                faces.append(poly)
    if not faces:
        return 0.0
    ground = unary_union(faces)
    if host is not None:
        ground = ground.intersection(host)
    return float(ground.area)


IMPOSED_RETENTION = 0.92   # massv2 legal_fit._IMPOSED_RETENTION
IMPOSE_STEPS = 14          # massv2 legal_fit._IMPOSE_STEPS: 1.0, 0.94, ... 0.22


def _pose_metric_vertices_to_host(compilation, host, *, clip_to_host: bool = False,
                                  clip_sections: tuple | None = None,
                                  facing_angle_deg: float | None = None,
                                  impose_fit: bool = False):
    """Finite rigid pose search; inability to place is a refusal, never a resize.

    `clip_to_host` does not break that contract - a cut is not a resize. It is
    the same reading massv2 takes and the one this file's fit was just taught:
    the legal line removes what stands past it and leaves the rest its own
    size. Without it a seed authored in the parcel's own metres can never be
    placed at all, because a mass the size of the parcel does not fit inside
    an irregular parcel; the four seeds measured 0%, 0%, 2% and 24% of the
    building-area cap trying.
    """
    vertices = compilation.vertices
    plan = MultiPoint([(x, y) for x, y, _z in vertices]).convex_hull
    if not isinstance(plan, Polygon) or plan.area <= 1e-9:
        return None
    source_angle, _, _ = _principal_frame(plan)
    target_angle, _, _ = _principal_frame(host)
    minimum_z = min(v[2] for v in vertices)
    span = max(v[2] for v in vertices) - minimum_z
    if span <= 1e-9:
        return None
    # An authored angle is a constraint. Search only translation/allowed fit
    # at that angle; legacy unrequested poses still maximize ground contact.
    angles = ([float(facing_angle_deg)] if facing_angle_deg is not None else
              [target_angle - source_angle, target_angle - source_angle + 90.0, 0.0])
    ground_section = clip_sections[0][2] if clip_sections else host
    # massv2's plot modes, ported (legal_fit._drawn_inside): a scheme that
    # imposes its own figure is brought *inside* the parcel - scanned down
    # 6% a step until at least 92% of its plan is legal - and the cut then
    # removes a trim rather than the design. Cutting every BOOK sentence to
    # the parcel made comp26's tiles casts of the parcel outline; the
    # figures the client liked in massv2 were all fitted this way. A scheme
    # that takes the plot's outline (a 1/1 split, a stack) still inherits it.
    factors = ([1.0 - step * 0.06 for step in range(IMPOSE_STEPS)]
               if (clip_to_host and impose_fit) else [1.0])
    best = None
    for center in (host.centroid, host.representative_point()):
        for angle in angles:
            chosen = None
            for factor in factors:
                matrix = compose_matrix4(
                    translation_matrix4((-plan.centroid.x, -plan.centroid.y, -minimum_z)),
                    rotation_matrix4((0.0, 0.0, angle)),
                    scale_matrix4((factor, factor, 1.0 / span)),
                    translation_matrix4((center.x, center.y, 0.0)))
                world = tuple(transform_point3(matrix, vertex) for vertex in vertices)
                if len(factors) == 1:
                    chosen = (matrix, world)
                    break
                whole = _mesh_plan_projection_area(world, compilation.triangles)
                if whole <= 1e-9:
                    continue
                kept = _mesh_plan_projection_area(world, compilation.triangles, host)
                chosen = (matrix, world)
                if kept / whole >= IMPOSED_RETENTION:
                    break
            if chosen is None:
                continue
            matrix, world = chosen
            if not clip_to_host:
                if _mesh_plan_projection_inside_host(world, compilation.triangles, host):
                    return HostFitTransform(matrix4=matrix, inverse_matrix4=inverse_matrix4(matrix),
                        world_vertices=world, achieved_plan_area_m2=_mesh_plan_projection_area(world, compilation.triangles))
                continue
            clipped = _clip_world_mesh_to_host(world, compilation.triangles, host, sections=clip_sections)
            if clipped is None:
                continue
            score = _ground_contact_area(clipped[0], clipped[1], ground_section)
            if best is None or score > best[0] + 1e-6:
                best = (score, matrix, world)
    if best is None:
        return None
    _score, matrix, world = best
    return HostFitTransform(matrix4=matrix, inverse_matrix4=inverse_matrix4(matrix),
        world_vertices=world, achieved_plan_area_m2=_mesh_plan_projection_area(world, compilation.triangles))


def _fit_vertices_to_host(
    compilation: CompilationResult,
    host: Polygon,
    *,
    target_plan_area: float | None = None,
    minimum_plan_area: float | None = None,
    clip_to_host: bool = False,
    facing_angle_deg: float | None = None,
) -> HostFitTransform | None:
    """Fit the compiled solid into the host plan.

    `clip_to_host` decides which of the two readings of a legal boundary this
    fit takes, and they are not close. Requiring the whole projection INSIDE
    the host puts the ceiling on ground take at the largest rectangle
    inscribed in it, which on 의정부 4115011300106840001 is 427.7 m2 - a
    1,922.2 m2 buildable polygon sitting inside a 3,706.7 m2 bounding box.
    massv2's compiler carries the other reading, and the same parcel and the
    same numbers are written beside it: the legal line CUTS the building, it
    does not shrink it. This path had never been taught that, so a BOOK mass
    delivered 664 m2 against a 1,497.9 m2 building-area cap.
    """
    vertices = compilation.vertices
    if not vertices:
        return None
    plan = MultiPoint([(x, y) for x, y, _z in vertices]).convex_hull
    if not isinstance(plan, Polygon) or plan.area <= 1e-9:
        return None
    source_angle, source_width, source_depth = _principal_frame(plan)
    target_angle, target_width, target_depth = _principal_frame(host)
    if facing_angle_deg is not None:
        # Measure available space in the authored orientation. A uniform fit
        # below preserves every local side, including oblique base geometry.
        from shapely.affinity import rotate
        target_angle = source_angle + float(facing_angle_deg)
        oriented_host = rotate(host, -target_angle, origin='centroid')
        left, bottom, right, top = oriented_host.bounds
        target_width, target_depth = right - left, top - bottom

    if min(source_width, source_depth, target_width, target_depth) <= 1e-9:
        return None
    source_center = plan.centroid
    target_center = host.centroid
    requested_long_scale = target_width / source_width * 0.95
    requested_short_scale = target_depth / source_depth * 0.95
    # A uniform fit preserves the authored solid proportion while a fully
    # independent fit erases it.  The former implementation allowed a 3x
    # relative axis stretch; on the real benchmark parcel that mapped BLOCK,
    # SLAB, BAR and PROFILED_PRISM to the same ~1.5 plan aspect ratio.  In other
    # words the AST retained the base-seed label while the materialized geometry
    # lost the base language.  Keep a small, aspect-conditioned host response:
    # compact seeds remain compact, intermediate plates may follow the parcel a
    # little more, and long bars retain a visibly long plan.
    minimum_axis_scale = min(requested_long_scale, requested_short_scale)
    source_aspect = max(source_width, source_depth) / max(min(source_width, source_depth), 1e-9)
    if source_aspect <= 1.25:
        maximum_relative_stretch = 1.25
    elif source_aspect <= 2.2:
        maximum_relative_stretch = 1.4
    else:
        maximum_relative_stretch = 1.5
    long_scale = min(requested_long_scale, minimum_axis_scale * maximum_relative_stretch)
    short_scale = min(requested_short_scale, minimum_axis_scale * maximum_relative_stretch)
    if facing_angle_deg is not None:
        long_scale = short_scale = minimum_axis_scale
    min_z = min(vertex[2] for vertex in vertices)
    max_z = max(vertex[2] for vertex in vertices)
    z_span = max(max_z - min_z, 1e-9)
    source_projection_area = _mesh_plan_projection_area(vertices, compilation.triangles)
    for factor in (1.0, 0.94, 0.88, 0.82, 0.76, 0.68, 0.58, 0.48):
        matrix = compose_matrix4(
            translation_matrix4((-source_center.x, -source_center.y, -min_z)),
            rotation_matrix4((0.0, 0.0, -source_angle)),
            scale_matrix4((
                long_scale * factor,
                short_scale * factor,
                1.0 / z_span,
            )),
            rotation_matrix4((0.0, 0.0, target_angle)),
            translation_matrix4((target_center.x, target_center.y, 0.0)),
        )
        world = tuple(transform_point3(matrix, vertex) for vertex in vertices)
        if clip_to_host or _mesh_plan_projection_inside_host(
            world,
            compilation.triangles,
            host,
        ):
            area_factor = 1.0
            if target_plan_area is not None and source_projection_area > 1e-9:
                fitted_projection_area = (
                    source_projection_area * long_scale * short_scale * factor * factor
                )
                area_factor = min(
                    1.0,
                    (max(0.2, float(target_plan_area)) / max(fitted_projection_area, 1e-9)) ** 0.5,
                )
                if area_factor < 1.0 - 1e-9:
                    target_area_matrix = compose_matrix4(
                        translation_matrix4((-target_center.x, -target_center.y, 0.0)),
                        scale_matrix4((area_factor, area_factor, 1.0)),
                        translation_matrix4((target_center.x, target_center.y, 0.0)),
                    )
                    matrix = compose_matrix4(matrix, target_area_matrix)
                    world = tuple(
                        transform_point3(matrix, vertex)
                        for vertex in vertices
                    )
            # ``minimum_plan_area`` is an authoring target supplied by the
            # feasible-capacity contract. ``target_plan_area`` retains its older
            # independent meaning as a shrink target for direct bridge callers.
            # A thin curved wall can have a host-filling convex hull while its
            # real mesh projection occupies only a small fraction of the site.
            # Widen it as far as the legal host permits, but do not delete the
            # language here: exact capacity and VLM stages own that hard verdict.
            actual_projection_area = _mesh_plan_projection_area(
                tuple(world),
                compilation.triangles,
            )
            if (
                facing_angle_deg is None
                and minimum_plan_area is not None
                and actual_projection_area + 1e-7 < max(0.2, float(minimum_plan_area))
            ):
                target_area = max(0.2, float(minimum_plan_area))
                required_short_growth = target_area / max(actual_projection_area, 1e-9)
                available_short_growth = requested_short_scale / max(
                    short_scale * area_factor,
                    1e-9,
                )
                short_growth = min(required_short_growth, available_short_growth)
                widening_matrix = _short_axis_widening_matrix(
                    center=target_center,
                    target_angle=target_angle,
                    growth=short_growth,
                )
                widened = tuple(
                    transform_point3(
                        compose_matrix4(matrix, widening_matrix),
                        vertex,
                    )
                    for vertex in vertices
                )
                if not _mesh_plan_projection_inside_host(
                    widened,
                    compilation.triangles,
                    host,
                ):
                    # An irregular host can prevent the rectangular-frame
                    # estimate from fitting. Find the widest contained result
                    # without converting this design target into a rejection.
                    lower_growth, upper_growth = 1.0, short_growth
                    for _iteration in range(10):
                        probe_growth = (lower_growth + upper_growth) / 2.0
                        probe_matrix = _short_axis_widening_matrix(
                            center=target_center,
                            target_angle=target_angle,
                            growth=probe_growth,
                        )
                        probe = tuple(
                            transform_point3(
                                compose_matrix4(matrix, probe_matrix),
                                vertex,
                            )
                            for vertex in vertices
                        )
                        if _mesh_plan_projection_inside_host(
                            probe,
                            compilation.triangles,
                            host,
                        ):
                            lower_growth = probe_growth
                            widened = probe
                        else:
                            upper_growth = probe_growth
                    short_growth = lower_growth
                    widening_matrix = _short_axis_widening_matrix(
                        center=target_center,
                        target_angle=target_angle,
                        growth=short_growth,
                    )
                matrix = compose_matrix4(matrix, widening_matrix)
                world = tuple(
                    transform_point3(matrix, vertex)
                    for vertex in vertices
                )
            return HostFitTransform(
                matrix4=matrix,
                inverse_matrix4=inverse_matrix4(matrix),
                world_vertices=world,
                achieved_plan_area_m2=_mesh_plan_projection_area(
                    world,
                    compilation.triangles,
                ),
            )
    return None


def _short_axis_widening_matrix(
    *,
    center,
    target_angle: float,
    growth: float,
) -> Matrix4:
    """Scale only the host-short axis around the host principal-frame centre."""

    return compose_matrix4(
        translation_matrix4((-center.x, -center.y, 0.0)),
        rotation_matrix4((0.0, 0.0, -target_angle)),
        scale_matrix4((1.0, growth, 1.0)),
        rotation_matrix4((0.0, 0.0, target_angle)),
        translation_matrix4((center.x, center.y, 0.0)),
    )


# A waist is narrow against the lobes it joins. Both quantities below are
# isotropic erosion radii, so the ratio is scale-free and rotation-invariant -
# the same rigid body scores the same at any angle on the parcel.
_NECK_TO_LOBE_RATIO = 0.35
_EROSION_STEP_FRACTION = 0.01
_EROSION_STEP_LIMIT = 60
_CORE_MINIMUM_SHARE = 0.02


def _articulation_cores(part: Any) -> tuple[tuple[Any, ...], float]:
    """Return the lobes a plan actually has, found by eroding it.

    Splitting a delivered plan where an author drew a boundary is relabelling:
    any polygon can be cut anywhere. The only honest question is whether the
    *form* comes apart, so erode it and see. A convex plate never separates at
    any radius; neither does a bar, however long. A body with a waist does, and
    the radius at which it does is half that waist.

    The waist alone is not enough - two 20 m halls joined by a 0.2 m saw kerf
    6 m deep separate too, having lost a quarter of one percent of their plan.
    So the waist is compared with the radius at which the lobes themselves
    disappear, their inscribed radius. A real neck scores about a quarter; the
    kerf scores two thirds; a 10 m opening between 20 m halls scores one.
    """

    if part.is_empty or part.area <= 1e-9:
        return (), 0.0
    scale = float(part.area) ** 0.5
    for step in range(1, _EROSION_STEP_LIMIT + 1):
        radius = scale * _EROSION_STEP_FRACTION * step
        eroded = part.buffer(-radius)
        if eroded.is_empty:
            return (), 0.0
        cores = tuple(
            piece
            for piece in _polygon_parts(eroded)
            if piece.area > part.area * _CORE_MINIMUM_SHARE
        )
        if len(cores) < 2:
            continue
        inscribed = min(
            _vanishing_radius(core, scale=scale)
            for core in cores
        )
        if inscribed <= 1e-9:
            return (), 0.0
        return cores, radius / inscribed
    return (), 0.0


def _vanishing_radius(core: Any, *, scale: float) -> float:
    """Return how far a lobe can be eroded before it disappears."""

    step = scale * _EROSION_STEP_FRACTION
    for index in range(1, _EROSION_STEP_LIMIT * 2 + 1):
        if core.buffer(-step * index).is_empty:
            return step * index
    return step * _EROSION_STEP_LIMIT * 2


def normalized_component_layout(
    source: SourceMass,
) -> tuple[tuple[str, Any, float, float], ...]:
    """Describe a program's components as proportions of its own plan.

    A component's place in a building is proportional, not metric: the west
    gallery occupies the western part of the plan whatever the parcel does to
    the plan's size, angle or aspect. The program templates are authored that
    way already - normalized polygons in [0,1] squared with a height band - and
    normalizing here recovers the same description from a compiled seed.

    That is what lets the composition survive the AST round trip. The authored
    program carries one body and one role by contract, so a component layout
    read off the compiled body would be one component; read off the seed it is
    the three or four the program actually has.
    """

    plan = getattr(source, "footprint", None)
    if plan is None or plan.is_empty or plan.area <= 1e-9:
        return ()
    min_x, min_y, max_x, max_y = plan.bounds
    span_x = max(max_x - min_x, 1e-9)
    span_y = max(max_y - min_y, 1e-9)
    layout = []
    for volume in source.volumes:
        footprint = volume.footprint
        if footprint is None or footprint.is_empty or footprint.area <= 1e-9:
            continue
        unit = affine_transform(
            footprint,
            [1.0 / span_x, 0.0, 0.0, 1.0 / span_y,
             -min_x / span_x, -min_y / span_y],
        )
        unit = unit if unit.is_valid else make_valid(unit)
        for piece in _polygon_parts(unit):
            if piece.area > 1e-9:
                layout.append((
                    str(volume.role),
                    piece,
                    float(volume.bottom_fraction),
                    float(volume.top_fraction),
                ))
    return tuple(layout)


def _component_regions_for_plan(
    layout: tuple[tuple[str, Any, float, float], ...],
    plan: Any,
    *,
    bottom_fraction: float,
    top_fraction: float,
) -> tuple[tuple[str, Any], ...]:
    """Place a proportional layout onto one delivered floor plan."""

    if not layout or plan is None or plan.is_empty or plan.area <= 1e-9:
        return ()
    min_x, min_y, max_x, max_y = plan.bounds
    span_x = max(max_x - min_x, 1e-9)
    span_y = max(max_y - min_y, 1e-9)
    regions = []
    for role, unit, bottom, top in layout:
        if (
            top <= bottom_fraction + 1e-6
            or bottom >= top_fraction - 1e-6
        ):
            continue
        placed = affine_transform(
            unit,
            [span_x, 0.0, 0.0, span_y, min_x, min_y],
        )
        placed = placed if placed.is_valid else make_valid(placed)
        for piece in _polygon_parts(placed):
            if piece.area > 1e-9:
                regions.append((role, piece))
    return tuple(regions)


def _articulated_component_parts(
    part: Any,
    regions: tuple[tuple[str, Any], ...],
    *,
    fallback_role: str,
) -> tuple[tuple[str, Any], ...]:
    """Label the lobes a delivered plan has with the components they carry.

    The lobes come from the form (`_articulation_cores`); the authored regions
    only supply their names. A plan with no lobes keeps one role and goes on
    failing the hierarchy gate, which is the honest reading of a box.
    """

    single = ((fallback_role, part),)
    if len(regions) < 2:
        return single
    cores, neck_ratio = _articulation_cores(part)
    if len(cores) < 2 or neck_ratio > _NECK_TO_LOBE_RATIO:
        return single
    named: list[list[Any]] = []
    for core in cores:
        overlaps = sorted(
            (
                (float(core.intersection(region).area), role)
                for role, region in regions
            ),
            key=lambda item: (-item[0], item[1]),
        )
        if not overlaps or overlaps[0][0] <= 0.0:
            return single
        named.append([overlaps[0][1], core])
    if len({role for role, _core in named}) < 2:
        return single
    # Every lobe is named; the rest of the plan is the waist and the skin the
    # erosion took off. Give each leftover to the lobe it touches most, with
    # ties broken by role name so one parcel orientation cannot decide it.
    remainder = part.difference(unary_union([core for _role, core in named]))
    for fragment in _polygon_parts(remainder):
        if fragment.area <= 1e-9:
            continue
        nearest = min(
            named,
            key=lambda item: (
                -float(
                    item[1].buffer(1e-6).intersection(
                        fragment.buffer(1e-6)
                    ).area
                ),
                item[0],
            ),
        )
        nearest[1] = unary_union([nearest[1], fragment])
    merged: dict[str, Any] = {}
    for role, piece in named:
        merged[role] = (
            piece if role not in merged
            else unary_union([merged[role], piece])
        )
    # One role can end up holding two disjoint pieces - a hall on both sides of
    # a court, say - and `SourceVolume.footprint` is a Polygon everywhere
    # downstream, so emit one volume per piece and let the role group them
    # again. Handing a MultiPolygon on killed a run in `_coherence_quality_polygon`.
    return tuple(
        (role, piece)
        for role in sorted(merged)
        for piece in _polygon_parts(merged[role])
        if not piece.is_empty and piece.area > 1e-9
    )


def _source_surface_plan_projection_area(source: SourceMass) -> float:
    """Return 건축면적 of an authored mesh: its triangles projected onto XY.

    건축면적 is the horizontal projection of the building (건축법 시행령 제119조
    제1항 제2호), so on a source that already carries surfaces this is the
    measurement, not an approximation of it. Sources without surfaces - the
    proxy-only ones - return 0.0 and leave their callers on the proxy measures.
    """

    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    for surface in tuple(getattr(source, "surfaces", ()) or ()):
        points = tuple(getattr(surface, "vertices_m", ()) or ())
        if len(points) != 3 or any(len(point) != 3 for point in points):
            continue
        base = len(vertices)
        vertices.extend(
            (float(point[0]), float(point[1]), float(point[2]))
            for point in points
        )
        triangles.append((base, base + 1, base + 2))
    if not triangles:
        return 0.0
    return _mesh_plan_projection_area(tuple(vertices), tuple(triangles))


def _mesh_plan_projection_area(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
    clip: Polygon | None = None,
) -> float:
    """Top-view solid area without replacing a non-convex graph by its hull.

    `clip` reports the area that survives a boundary. What a mesh projects is
    not what gets built once the legal line cuts it, and read off the unclipped
    projection an authoring target certified 1,497.877 m2 satisfied on 의정부
    4115011300106840001 while the delivered ground plan was 1,444.7 - a target
    met on material the line had already removed.
    """
    projected: list[Polygon] = []
    for triangle in triangles:
        coordinates = [
            (float(vertices[index][0]), float(vertices[index][1]))
            for index in triangle
        ]
        if not all(isfinite(value) for coordinate in coordinates for value in coordinate):
            continue
        polygon = Polygon(coordinates)
        if polygon.is_empty or polygon.area <= 1e-10:
            continue
        for part in _polygon_parts(make_valid(polygon)):
            if not part.is_empty and part.area > 1e-10:
                projected.append(part)
    if not projected:
        return 0.0

    # GEOS can occasionally report ``Ring edge missing`` when many mesh
    # triangles share nearly-identical projected edges.  Retry on successively
    # coarser metric grids; this changes coordinates by at most 0.01 mm while
    # retaining courts, notches and courtyards at architectural scale.
    for grid_size in (0.0, 1e-9, 1e-7, 1e-5):
        try:
            candidates = (
                projected
                if grid_size == 0.0
                else [
                    part
                    for polygon in projected
                    for part in _polygon_parts(set_precision(polygon, grid_size))
                    if not part.is_empty and part.area > 1e-10
                ]
            )
            if candidates:
                merged = unary_union(candidates)
                if clip is not None:
                    merged = merged.intersection(clip)
                area = float(merged.area)
                if isfinite(area) and area >= 0.0:
                    return area
        except GEOSException:
            continue

    # A numerically pathological candidate must not abort an entire portfolio
    # run.  The largest valid projected triangle is a conservative lower bound,
    # so capacity gates can reject the candidate instead of receiving a false
    # positive from a convex-hull or summed-area fallback.
    if clip is None:
        return max(float(polygon.area) for polygon in projected)
    return max(
        float(polygon.intersection(clip).area) for polygon in projected
    )


def _mesh_plan_projection_inside_host(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
    host: Polygon,
) -> bool:
    """Test the occupied mesh plan, not the empty space in its convex hull."""

    legal = host.buffer(1e-7)
    occupied_triangle_found = False
    for triangle in triangles:
        coordinates = [
            (float(vertices[index][0]), float(vertices[index][1]))
            for index in triangle
        ]
        if not all(isfinite(value) for coordinate in coordinates for value in coordinate):
            return False
        polygon = Polygon(coordinates)
        if polygon.is_empty or polygon.area <= 1e-10:
            continue
        occupied_triangle_found = True
        if not legal.covers(polygon):
            return False
    return occupied_triangle_found


def _rebase_surfaces(
    surfaces: tuple[SourceSurface, ...],
    *,
    from_origin: Any,
    to_origin: Any,
    role_offsets: dict[str, tuple[float, float]] | None = None,
) -> tuple[SourceSurface, ...]:
    """Preserve world coordinates while changing SourceMass local origin."""
    xoff = float(from_origin.x) - float(to_origin.x)
    yoff = float(from_origin.y) - float(to_origin.y)
    offsets = role_offsets or {}
    return tuple(
        replace(
            surface,
            vertices_m=tuple(
                (
                    x + xoff + offsets.get(surface.volume_role, (0.0, 0.0))[0],
                    y + yoff + offsets.get(surface.volume_role, (0.0, 0.0))[1],
                    z,
                )
                for x, y, z in surface.vertices_m
            ),
        )
        for surface in surfaces
    )


def _reattach_subordinate_volumes(
    recursive_volumes: tuple[SourceVolume, ...],
    subordinate: tuple[SourceVolume, ...],
    *,
    original_dominant: SourceVolume,
    containment_host: Polygon | None = None,
) -> tuple[tuple[SourceVolume, ...], dict[str, tuple[float, float]]]:
    """Re-materialize ``attach`` relations around a replaced primary solid.

    The source role graph is preserved, but the old attachment coordinates are
    not: each subordinate is placed against the new primary boundary using its
    original normalized direction. This avoids both disconnected LEGO pieces
    and large accidental collisions after a cube, taper or sweep replacement.
    """
    main = unary_union([volume.footprint for volume in recursive_volumes])
    if main.is_empty:
        return subordinate, {}
    main_center = main.centroid
    old_center = original_dominant.footprint.centroid
    moved: list[SourceVolume] = []
    offsets: dict[str, tuple[float, float]] = {}
    boundary_points = [
        point
        for polygon in _polygon_parts(main)
        for point in list(polygon.exterior.coords)[:-1]
    ]
    for volume in subordinate:
        center = volume.footprint.centroid
        dx0, dy0 = center.x - old_center.x, center.y - old_center.y
        length = hypot(dx0, dy0)
        if length <= 1e-9 or not boundary_points:
            moved.append(volume)
            continue
        ux, uy = dx0 / length, dy0 / length
        support = max(boundary_points, key=lambda point: (point[0] - main_center.x) * ux + (point[1] - main_center.y) * uy)
        subordinate_points = list(volume.footprint.exterior.coords)[:-1]
        half_extent = max(
            abs((point[0] - center.x) * ux + (point[1] - center.y) * uy)
            for point in subordinate_points
        ) if subordinate_points else 0.0
        # Fifteen percent embed gives a legible architectural joint without
        # turning the service/entry body into a redundant overlapping solid.
        desired_x = support[0] + ux * half_extent * 0.85
        desired_y = support[1] + uy * half_extent * 0.85
        xoff, yoff = desired_x - center.x, desired_y - center.y
        geometry = translate(volume.footprint, xoff=xoff, yoff=yoff)
        # Non-convex primaries can put the support vertex beside a re-entrant
        # corner. Close any residual gap by the exact nearest-point vector.
        if geometry.distance(main) > 0.12:
            target, current = nearest_points(main, geometry)
            correction_x = target.x - current.x
            correction_y = target.y - current.y
            geometry = translate(geometry, xoff=correction_x, yoff=correction_y)
            xoff += correction_x
            yoff += correction_y
        if containment_host is not None and not containment_host.buffer(1e-7).covers(geometry):
            # Search the same typed attachment vector for the furthest legal
            # placement. Never clip a service/entry body into debris.
            legal_choice: tuple[Any, float, float] | None = None
            for fraction in (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0):
                candidate = translate(volume.footprint, xoff=xoff * fraction, yoff=yoff * fraction)
                if containment_host.buffer(1e-7).covers(candidate) and candidate.distance(main) <= 0.12:
                    legal_choice = candidate, xoff * fraction, yoff * fraction
                    break
            if legal_choice is None:
                searched = _search_legal_attachment(
                    volume,
                    main,
                    containment_host,
                    preferred_direction=(ux, uy),
                )
                if searched is None:
                    geometry, xoff, yoff = volume.footprint, 0.0, 0.0
                else:
                    geometry, xoff, yoff = searched
            else:
                geometry, xoff, yoff = legal_choice
        moved.append(replace(volume, footprint=geometry))
        offsets[volume.role] = (xoff, yoff)
    return tuple(moved), offsets


def _search_legal_attachment(
    volume: SourceVolume,
    main: Any,
    host: Polygon,
    *,
    preferred_direction: tuple[float, float],
) -> tuple[Any, float, float] | None:
    """Find a bounded, host-contained attachment without clipping geometry."""
    center = volume.footprint.centroid
    main_center = main.centroid
    boundary: list[tuple[float, float]] = []
    for polygon in _polygon_parts(main):
        coordinates = list(polygon.exterior.coords)
        for left, right in zip(coordinates, coordinates[1:]):
            boundary.extend((left, ((left[0] + right[0]) / 2.0, (left[1] + right[1]) / 2.0)))
    candidates: list[tuple[float, Any, float, float]] = []
    host_buffer = host.buffer(1e-7)
    preferred_x, preferred_y = preferred_direction
    scale_ref = max(host.area ** 0.5, 1e-9)
    for scale_factor in (1.0,):
        body = volume.footprint
        body_center = body.centroid
        points = list(body.exterior.coords)[:-1]
        for point in boundary:
            vx, vy = point[0] - main_center.x, point[1] - main_center.y
            length = hypot(vx, vy)
            if length <= 1e-9:
                continue
            ux, uy = vx / length, vy / length
            half_extent = max(
                abs((vertex[0] - body_center.x) * ux + (vertex[1] - body_center.y) * uy)
                for vertex in points
            ) if points else 0.0
            target_x = point[0] + ux * half_extent * 0.86
            target_y = point[1] + uy * half_extent * 0.86
            xoff, yoff = target_x - body_center.x, target_y - body_center.y
            placed = translate(body, xoff=xoff, yoff=yoff)
            if not host_buffer.covers(placed) or placed.distance(main) > 0.12:
                continue
            overlap = float(placed.intersection(main).area) / max(float(placed.area), 1e-9)
            if overlap > 0.46:
                continue
            direction_fit = ux * preferred_x + uy * preferred_y
            movement = hypot(target_x - center.x, target_y - center.y) / scale_ref
            score = direction_fit * 1.6 - movement - abs(overlap - 0.14) * 0.5 + scale_factor * 0.2
            candidates.append((score, placed, target_x - center.x, target_y - center.y))
    if not candidates:
        return None
    _score, geometry, xoff, yoff = max(candidates, key=lambda item: item[0])
    return geometry, xoff, yoff


def mesh_section_solid(vertices, triangles):
    """Recover a closed kernel solid from the exact delivered triangle mesh."""
    import manifold3d as m3d
    import numpy as np
    points, lookup, faces = [], {}, []
    for triangle in triangles:
        face = []
        for index in triangle:
            point = tuple(float(x) for x in vertices[index])
            if point not in lookup:
                lookup[point] = len(points)
                points.append(point)
            face.append(lookup[point])
        faces.append(face)
    solid = m3d.Manifold(m3d.Mesh64(np.array(points, dtype=np.float64),
                                  np.array(faces, dtype=np.uint64)))
    if solid.status() != m3d.Error.NoError or solid.is_empty():
        raise ValueError(f'delivered mesh cannot be sectioned: {solid.status()}')
    return solid


def solid_section_polygon(solid, z):
    """Kernel section with all nested contours, including holes and islands."""
    contours = solid.slice(float(z)).to_polygons()
    region = None
    for contour in contours:
        ring = Polygon(contour)
        if ring.is_empty or ring.area <= 0:
            continue
        region = ring if region is None else region.symmetric_difference(ring)
    return region


def section_export_area_resolution(section, matrix):
    """Area comparison resolution derived from the compiler's export grid.

    This never changes a mesh or sampling plane. A larger mismatch refuses
    the floor certificate, including discontinuous slices at rounded steps.
    """
    from backend.app.modules.design.generation.maas.geometry_language.export_mesh import EXPORT_DECIMAL_PLACES
    quantum = 10.0 ** -EXPORT_DECIMAL_PLACES
    axis_scale = max(hypot(matrix[0][i], matrix[1][i]) for i in (0, 1))
    displacement = quantum * max(1.0, axis_scale)
    return float(section.length) * displacement + pi * displacement ** 2


def section_coplanar_skin_area(vertices, triangles, z, matrix):
    """Area of a horizontal skin coincident with a floor at export resolution.

    At this discontinuity tiny export rounding can choose either side of the
    floor. Report ambiguity instead of moving the authored measurement plane.
    """
    from backend.app.modules.design.generation.maas.geometry_language.export_mesh import EXPORT_DECIMAL_PLACES
    z_resolution = 10.0 ** -EXPORT_DECIMAL_PLACES * abs(matrix[2][2])
    return sum(Polygon([(vertices[i][0], vertices[i][1]) for i in face]).area
               for face in triangles
               if all(abs(vertices[i][2] - z) <= z_resolution for i in face))


def _mesh_section_polygon(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
    z: float,
) -> Polygon | Any | None:
    segments: list[LineString] = []
    epsilon = 1e-7
    for triangle in triangles:
        points = [vertices[index] for index in triangle]
        intersections: list[tuple[float, float]] = []
        for left, right in zip(points, (*points[1:], points[0])):
            lz, rz = left[2] - z, right[2] - z
            if abs(lz) <= epsilon:
                intersections.append((left[0], left[1]))
            if lz * rz < -epsilon * epsilon:
                amount = (z - left[2]) / (right[2] - left[2])
                intersections.append((
                    left[0] + (right[0] - left[0]) * amount,
                    left[1] + (right[1] - left[1]) * amount,
                ))
        unique: list[tuple[float, float]] = []
        for point in intersections:
            if not any(hypot(point[0] - other[0], point[1] - other[1]) <= 1e-6 for other in unique):
                unique.append(point)
        if len(unique) >= 2:
            # Adjacent manifold triangles calculate the same plane/edge
            # intersection independently.  Their coordinates can differ by
            # ~1e-12 even though the kernel mesh is watertight.  GEOS
            # polygonize requires bit-identical endpoints; without this
            # metric-scale normalization, bent/split wing lower bands vanish
            # and the legal proxy contains only an arbitrary upper slice.
            # 1e-8 m is far below the tiny-edge gate and does not alter design
            # geometry, but it closes the section graph deterministically.
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


def _mesh_surfaces(
    local_vertices: tuple[tuple[float, float, float], ...],
    compilation: CompilationResult,
    *,
    volume_role: str,
    max_raw_surfaces: int | None,
) -> tuple[SourceSurface, ...]:
    records: list[tuple[float, tuple[int, int, int], tuple[int, int, int]]] = []
    for triangle in compilation.triangles:
        a, b, c = (local_vertices[index] for index in triangle)
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        magnitude = max(hypot(hypot(nx, ny), nz), 1e-12)
        area = magnitude / 2.0
        normal_bucket = (
            int(round(nx / magnitude * 2.0)),
            int(round(ny / magnitude * 2.0)),
            int(round(nz / magnitude * 2.0)),
        )
        records.append((area, triangle, normal_bucket))
    records.sort(key=lambda item: item[0], reverse=True)
    # Do not make the review/VLM geometry a lossy subset of the solid that
    # passed the manifold gate. Dropping all but the largest triangles made
    # bends, arrays and sweeps render as open fragments even though the
    # compiler's authoritative mesh was watertight. Kernel triangles are a
    # transport detail; clean-mass complexity is measured by semantic normal
    # patches (``effective_surface_count``), not triangulation count.
    limit = (
        len(records)
        if max_raw_surfaces is None
        else max(8, min(4096, int(max_raw_surfaces)))
    )
    root_operator = compilation.program.node_map[compilation.program.root_id].operator
    return tuple(
        SourceSurface(
            role=f"recursive_mesh_{index}",
            volume_role=volume_role,
            verb="geometry_program",
            surface_type="profiled_recursive_solid_mesh",
            vertices_m=tuple(local_vertices[vertex_index] for vertex_index in triangle),
            operator=root_operator,
            semantic_patch_id=f"{volume_role}:recursive_normal:{bucket[0]}:{bucket[1]}:{bucket[2]}",
        )
        for index, (_area, triangle, bucket) in enumerate(records[:limit])
    )


def source_surface_payload_hash(
    surfaces: tuple[SourceSurface, ...],
) -> str:
    """Hash the complete, exact SourceSurface payload independent of ordering."""

    records = tuple(
        json.dumps(
            {
                "operator": surface.operator,
                "role": surface.role,
                "semantic_patch_id": surface.semantic_patch_id,
                "surface_type": surface.surface_type,
                "verb": surface.verb,
                "vertices_m": [
                    [float(x), float(y), float(z)]
                    for x, y, z in surface.vertices_m
                ],
                "volume_role": surface.volume_role,
            },
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        for surface in surfaces
    )
    payload = f"[{','.join(sorted(records))}]".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def source_volume_payload_hash(
    volumes: tuple[SourceVolume, ...],
) -> str:
    """Hash every exact proxy-volume field and every polygon ring."""

    records = tuple(
        json.dumps(
            {
                "bottom_fraction": float(volume.bottom_fraction),
                "footprint": _canonical_polygon_payload(volume.footprint),
                "role": volume.role,
                "top_fraction": float(volume.top_fraction),
                "verb": volume.verb,
            },
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        for volume in volumes
    )
    payload = f"[{','.join(sorted(records))}]".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonical_polygon_payload(geometry: Any) -> dict[str, Any]:
    if not _valid_positive_polygon_payload(geometry):
        raise ValueError("invalid_source_volume_polygon")
    polygons = tuple(
        {
            "exterior": _canonical_ring_payload(polygon.exterior.coords),
            "interiors": sorted(
                _canonical_ring_payload(interior.coords)
                for interior in polygon.interiors
            ),
        }
        for polygon in _polygon_parts(geometry)
    )
    if not polygons:
        raise ValueError("missing_source_volume_polygon")
    return {
        "polygons": sorted(
            polygons,
            key=lambda value: json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
        ),
    }


def _canonical_ring_payload(
    coordinates: Any,
) -> list[list[float]]:
    points = [
        (float(coordinate[0]), float(coordinate[1]))
        for coordinate in coordinates
    ]
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if len(points) < 3 or any(
        not isfinite(value)
        for point in points
        for value in point
    ):
        raise ValueError("invalid_source_volume_ring")
    forward = tuple(points)
    reverse = tuple(reversed(points))
    canonical = min(
        tuple(sequence[index:] + sequence[:index])
        for sequence in (forward, reverse)
        for index in range(len(sequence))
    )
    closed = (*canonical, canonical[0])
    return [[float(x), float(y)] for x, y in closed]


def _valid_positive_polygon_payload(geometry: Any) -> bool:
    if (
        geometry is None
        or getattr(geometry, "is_empty", True)
        or getattr(geometry, "is_valid", False) is not True
    ):
        return False
    parts = _polygon_parts(geometry)
    return bool(parts) and all(
        part.is_valid
        and not part.is_empty
        and isfinite(float(part.area))
        and float(part.area) > 0.0
        for part in parts
    )


def _merge_equal_band_footprints(volumes: tuple[SourceVolume, ...]) -> tuple[SourceVolume, ...]:
    merged: list[SourceVolume] = []
    for volume in sorted(volumes, key=lambda item: (item.bottom_fraction, -item.footprint.area)):
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and abs(previous.top_fraction - volume.bottom_fraction) <= 1e-8
            and previous.footprint.symmetric_difference(volume.footprint).area
            <= max(0.02, previous.footprint.area * 0.005)
        ):
            merged[-1] = replace(previous, top_fraction=volume.top_fraction)
        else:
            merged.append(volume)
    return tuple(merged)


def _polygon_parts(geometry: Any) -> tuple[Polygon, ...]:
    if geometry is None or geometry.is_empty:
        return ()
    if isinstance(geometry, Polygon):
        return (geometry,)
    return tuple(sorted(
        (
            part
            for child in getattr(geometry, "geoms", ())
            for part in _polygon_parts(child)
        ),
        key=lambda part: part.area,
        reverse=True,
    ))


def _repair_polygonal_floor_union(
    geometry: Any,
    *,
    minimum_area: float,
    diagnostics: dict[str, Any] | None = None,
) -> tuple[Any | None, dict[str, Any]]:
    """Repair and retain the complete polygonal endpoint-floor aggregate."""

    if diagnostics is None:
        diagnostics = {}

    geom_type = str(getattr(geometry, "geom_type", type(geometry).__name__))
    is_empty = bool(getattr(geometry, "is_empty", True))
    is_valid = bool(getattr(geometry, "is_valid", False))
    try:
        validity_reason = (
            explain_validity(geometry)
            if geometry is not None
            else "missing geometry"
        )
    except (GEOSException, TypeError, ValueError):
        validity_reason = "validity unavailable"

    aggregate = None
    repaired_parts: tuple[Polygon, ...] = ()
    repair_failed = False
    if geometry is not None and not is_empty:
        try:
            repaired = geometry if is_valid else make_valid(geometry)
            repaired_parts = tuple(
                part
                for part in _polygon_parts(repaired)
                if (
                    not part.is_empty
                    and part.is_valid
                    and isfinite(float(part.area))
                    and float(part.area) > 0.0
                )
            )
            if repaired_parts:
                aggregate = unary_union(repaired_parts)
                if not aggregate.is_valid:
                    aggregate = unary_union(_polygon_parts(make_valid(aggregate)))
                repaired_parts = _polygon_parts(aggregate)
        except (GEOSException, TypeError, ValueError):
            aggregate = None
            repaired_parts = ()
            repair_failed = True

    aggregate_area = (
        float(aggregate.area)
        if aggregate is not None
        and not aggregate.is_empty
        and isfinite(float(aggregate.area))
        else 0.0
    )
    if geometry is None:
        failure_branch = "missing_geometry"
    elif is_empty:
        failure_branch = "input_empty"
    elif repair_failed:
        failure_branch = "repair_exception"
    elif aggregate is None:
        failure_branch = "aggregate_missing"
    elif aggregate.is_empty:
        failure_branch = "aggregate_empty"
    elif not aggregate.is_valid:
        failure_branch = "aggregate_invalid"
    elif not repaired_parts:
        failure_branch = "no_polygon_components"
    elif aggregate_area < float(minimum_area):
        failure_branch = "aggregate_below_minimum_area"
    else:
        failure_branch = ""

    diagnostics.update({
        "geom_type": geom_type,
        "is_valid": is_valid,
        "validity_reason": str(validity_reason),
        "is_empty": is_empty,
        "aggregate_area_m2": round(aggregate_area, 8),
        "component_count": len(repaired_parts),
        "polygon_count": len(repaired_parts),
        "largest_polygon_area_m2": round(
            max((float(part.area) for part in repaired_parts), default=0.0),
            8,
        ),
        "post_repair_geom_type": str(
            getattr(aggregate, "geom_type", "None")
        ),
        "failure_branch": failure_branch,
    })
    if (
        aggregate is None
        or aggregate.is_empty
        or not aggregate.is_valid
        or not repaired_parts
        or aggregate_area < float(minimum_area)
    ):
        return None, diagnostics
    return aggregate, diagnostics


def _principal_frame(poly: Polygon) -> tuple[float, float, float]:
    coordinates = list(poly.minimum_rotated_rectangle.exterior.coords)
    edges = [
        (hypot(x2 - x1, y2 - y1), degrees(atan2(y2 - y1, x2 - x1)))
        for (x1, y1), (x2, y2) in zip(coordinates, coordinates[1:])
    ]
    edges.sort(reverse=True)
    width = edges[0][0] if edges else 0.0
    depth = edges[-1][0] if edges else 0.0
    return (edges[0][1] if edges else 0.0), width, depth


def _access_reserve_target_center(
    legal: Polygon,
    site_access_side: str,
    *,
    reserve_fraction: float = 0.4,
) -> Point:
    """Bias one whole-solid placement away from the live road frontage.

    The authored linear Matrix4 block remains unchanged.  Only its single
    site translation moves, and the point is backed off until it lies in the
    legal ground section.  ``closed`` preserves the historical centroid.
    """

    side = str(site_access_side or "closed").lower()
    center = legal.centroid
    if not legal.covers(center):
        center = legal.representative_point()
    if side not in {"east", "west", "north", "south"}:
        return center
    angle_degrees, width, depth = _principal_frame(legal)
    angle = angle_degrees * pi / 180.0
    along = (cos(angle), sin(angle))
    across = (-sin(angle), cos(angle))
    if side in {"east", "west"}:
        axis = along
        span = width
        direction = -1.0 if side == "east" else 1.0
    else:
        axis = across
        span = depth
        direction = -1.0 if side == "north" else 1.0
    requested = max(0.0, min(0.4, float(reserve_fraction)))
    for fraction in (
        requested,
        requested * 0.75,
        requested * 0.5,
        requested * 0.25,
    ):
        candidate = Point(
            float(center.x) + direction * axis[0] * span * fraction,
            float(center.y) + direction * axis[1] * span * fraction,
        )
        if legal.covers(candidate):
            return candidate
    return center


def _shared_legal_target_center(
    legal_sections: Sequence[Polygon],
    site_access_side: str,
) -> Point:
    """Choose one access-aware Matrix4 target inside every legal floor.

    Floor-one placement can sit outside a narrower or shifted upper envelope.
    Projecting that pose floor by floor then carves the authored solid into the
    same setback silhouette.  The shared legal core supplies a site-generic
    placement domain while preserving the road-side reserve convention.
    """

    usable = tuple(
        repaired
        for section in legal_sections
        if (repaired := repair_source_polygon(section, minimum_area=1e-6))
        is not None
        and not repaired.is_empty
    )
    if not usable:
        raise ValueError("legal_sections must contain a usable polygon")

    fallback = _access_reserve_target_center(usable[0], site_access_side)
    shared: Any = usable[0]
    try:
        for section in usable[1:]:
            shared = shared.intersection(section)
            parts = _polygon_parts(shared)
            if not parts:
                return fallback
            shared = unary_union(parts)
    except GEOSException:
        return fallback

    if shared.is_empty or float(shared.area) <= 1e-6:
        return fallback
    return _access_reserve_target_center(shared, site_access_side)


def _optimize_floorwise_matrix_translation(
    matrix: tuple[tuple[float, float, float, float], ...],
    *,
    source_sections: Sequence[Any],
    legal_sections: Sequence[Polygon],
    site_access_side: str,
    minimum_total_area_m2: float = 0.0,
) -> tuple[tuple[float, float, float, float], ...]:
    """Move one Matrix4 to retain the authored section stack as a whole.

    The linear block is immutable: only the global x/y translation is
    searched.  This keeps the authored axis, aspect, taper and relative floor
    offsets while avoiding the old floor-one placement that made upper legal
    sections carve every language into the same setback body.
    """

    pairs = tuple(zip(source_sections, legal_sections))
    if not pairs:
        return matrix
    transformed = tuple(
        affine_transform(source, [
            matrix[0][0], matrix[0][1],
            matrix[1][0], matrix[1][1],
            matrix[0][3], matrix[1][3],
        ])
        for source, _legal in pairs
    )
    if any(section.is_empty or float(section.area) <= 1e-9 for section in transformed):
        return matrix
    if all(
        legal.buffer(1e-7).covers(section)
        for section, (_source, legal) in zip(transformed, pairs)
    ):
        return matrix

    ground_center = transformed[0].centroid
    preferred = _access_reserve_target_center(
        pairs[0][1],
        site_access_side,
    )
    candidate_points: list[Point] = [preferred]

    repaired_legal = tuple(
        repaired
        for _source, legal in pairs
        if (repaired := repair_source_polygon(legal, minimum_area=1e-6))
        is not None
        and not repaired.is_empty
    )
    shared: Any | None = repaired_legal[0] if repaired_legal else None
    fractions = tuple(index / 8.0 for index in range(9))
    if repaired_legal:
        ground_legal = repaired_legal[0]
        min_x, min_y, max_x, max_y = ground_legal.bounds
        candidate_points.extend(
            point
            for x_fraction in fractions
            for y_fraction in fractions
            if ground_legal.covers(point := Point(
                min_x + (max_x - min_x) * x_fraction,
                min_y + (max_y - min_y) * y_fraction,
            ))
        )
    try:
        for legal in repaired_legal[1:]:
            shared = shared.intersection(legal) if shared is not None else None
            parts = _polygon_parts(shared) if shared is not None else ()
            if not parts:
                shared = None
                break
            shared = unary_union(parts)
    except GEOSException:
        shared = None

    if shared is not None and not shared.is_empty and float(shared.area) > 1e-6:
        candidate_points.extend((
            _access_reserve_target_center(shared, site_access_side),
            shared.centroid,
            shared.representative_point(),
        ))
        min_x, min_y, max_x, max_y = shared.bounds
        candidate_points.extend(
            point
            for x_fraction in fractions
            for y_fraction in fractions
            if shared.covers(point := Point(
                min_x + (max_x - min_x) * x_fraction,
                min_y + (max_y - min_y) * y_fraction,
            ))
        )

    # Aligning any authored floor centroid with its legal host centroid gives
    # useful candidates when the authored stack itself shifts or branches.
    for transformed_section, (_source, legal) in zip(transformed, pairs):
        relative_x = float(transformed_section.centroid.x - ground_center.x)
        relative_y = float(transformed_section.centroid.y - ground_center.y)
        candidate_points.append(Point(
            float(legal.centroid.x) - relative_x,
            float(legal.centroid.y) - relative_y,
        ))

    raw_total = sum(float(section.area) for section in transformed)
    best_matrix = matrix
    minimum_total = max(0.0, float(minimum_total_area_m2))
    best_score: tuple[float, float, float, float, float] | None = None
    seen: set[tuple[float, float]] = set()
    for point in candidate_points:
        key = (round(float(point.x), 7), round(float(point.y), 7))
        if key in seen:
            continue
        seen.add(key)
        delta_x = float(point.x - ground_center.x)
        delta_y = float(point.y - ground_center.y)
        moved = tuple(
            translate(section, xoff=delta_x, yoff=delta_y)
            for section in transformed
        )
        retained_areas = tuple(
            float(section.intersection(legal).area)
            for section, (_source, legal) in zip(moved, pairs)
        )
        retention_ratios = tuple(
            retained / max(float(section.area), 1e-9)
            for retained, section in zip(retained_areas, moved)
        )
        retained_total = sum(retained_areas)
        retained_ratio = retained_total / max(raw_total, 1e-9)
        minimum_retention = min(retention_ratios)
        capacity_pass = retained_total + 1e-7 >= minimum_total
        score = (
            1.0 if capacity_pass else 0.0,
            minimum_retention if capacity_pass else retained_ratio,
            retained_ratio if capacity_pass else minimum_retention,
            retained_total,
            -float(point.distance(preferred)),
        )
        if best_score is not None and score <= best_score:
            continue
        rows = [list(row) for row in matrix]
        rows[0][3] = float(rows[0][3]) + delta_x
        rows[1][3] = float(rows[1][3]) + delta_y
        best_matrix = tuple(tuple(float(value) for value in row) for row in rows)
        best_score = score
    return best_matrix


INTERNAL_TREAD_COLLAPSE_AREA_RATIO = 0.15

VISIBLE_SURFACE_PRODUCERS = {
    "floorwise_capacity_projection": "authored_matrix4_projection",
    "authored_visual_legal_validation": "authored_matrix4_projection",
    "floorwise_profiled_continuous_envelope_clip": (
        "authored_continuous_envelope_clip"
    ),
    "floorwise_profiled_legal_clip": "authored_continuous_envelope_clip",
    "floorwise_csg_section_loft": "legal_section_loft",
}


def _visible_surface_producer(certification_mode: str) -> str:
    """Name what actually built the visible skin, not what certified it."""

    mode = str(certification_mode or "")
    return VISIBLE_SURFACE_PRODUCERS.get(mode, mode or "unknown")


def _triangle_area_m2(triangle: Sequence[Sequence[float]]) -> float:
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = triangle
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    return 0.5 * sqrt(nx * nx + ny * ny + nz * nz)


def _internal_horizontal_tread_area_ratio(
    surfaces: Sequence[SourceSurface],
    *,
    z_tolerance: float = 1e-8,
) -> float:
    """Return the share of visible skin area formed by interior floor treads.

    Clipping an authored body against a contracting legal field leaves a small
    tread wherever the body meets a band boundary.  Discarding the whole
    authored skin for that is worse than the tread: the replacement is rebuilt
    from legal sections alone and reads as a terraced cake.  Only a tread that
    dominates the visible skin is a real step collapse, so this reports the
    magnitude instead of mere presence.
    """

    triangles: list[tuple[tuple[float, float, float], ...]] = []
    for surface in surfaces:
        vertices = tuple(surface.vertices_m or ())
        if len(vertices) != 3:
            continue
        try:
            triangle = tuple(
                (float(vertex[0]), float(vertex[1]), float(vertex[2]))
                for vertex in vertices
            )
        except (IndexError, TypeError, ValueError):
            continue
        if any(not isfinite(value) for point in triangle for value in point):
            continue
        triangles.append(triangle)
    if not triangles:
        return 0.0
    z_values = [point[2] for triangle in triangles for point in triangle]
    z_floor = min(z_values)
    z_ceiling = max(z_values)
    total_area = 0.0
    tread_area = 0.0
    for triangle in triangles:
        area = _triangle_area_m2(triangle)
        if area <= 0.0:
            continue
        total_area += area
        triangle_z = [point[2] for point in triangle]
        if max(triangle_z) - min(triangle_z) > z_tolerance:
            continue
        level = sum(triangle_z) / 3.0
        if (
            level - z_floor > z_tolerance
            and z_ceiling - level > z_tolerance
        ):
            tread_area += area
    if total_area <= 0.0:
        return 0.0
    return tread_area / total_area


__all__ = [
    "HostFitTransform",
    "append_site_placement_matrix",
    "compile_geometry_program_to_source_mass",
    "compile_normalized_geometry_program_to_source_mass",
    "compile_site_bound_geometry_program_to_source_mass",
    "derive_host_fit_transform",
    "floorwise_source_to_geometry_program",
    "materialize_floorwise_legal_source",
    "replace_source_dominant_with_geometry_program",
]
