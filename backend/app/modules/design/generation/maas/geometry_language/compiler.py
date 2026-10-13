"""Manifold-backed compiler for recursive architectural geometry programs."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from math import atan2, ceil, cos, degrees, hypot, isfinite, pi, radians, sin
from typing import Any, Callable

import numpy as np

from backend.app.modules.design.generation.maas.book_language.base_volume_contract import oriented_book_base_volume_cells

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryIssue, GeometryNode, GeometryProgram, MACRO_VERTICAL_ANCHORS
from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import kernel_matrix3x4, matrix4_for_transform, matrix4_to_lists
from backend.app.modules.design.generation.maas.geometry_language.book_parameter_projection import BOOK_KERNEL_PARAMETER_PROJECTIONS
from backend.app.modules.design.generation.maas.geometry_language.gate import GeometryGatePolicy, compilation_gate
from backend.app.modules.design.generation.maas.geometry_language.export_mesh import EXPORT_DECIMAL_PLACES, repair_export_collinearity
from backend.app.modules.design.generation.maas.geometry_language.host_face_relations import resolve_face_attachment
from backend.app.modules.design.generation.maas.geometry_language.section_profiles import section_profile_controls
from backend.app.modules.design.generation.maas.geometry_language.unitbox_normalization import normalize_unitbox_program


_SHIFT_DISTANCE_BOUNDS = BOOK_KERNEL_PARAMETER_PROJECTIONS[
    ("shift", "distance_ratio")
].kernel_bounds
_INTERLOCK_BAR_BOUNDS = BOOK_KERNEL_PARAMETER_PROJECTIONS[
    ("interlock", "bar_ratio")
].kernel_bounds
_INTERLOCK_DISTANCE_BOUNDS = BOOK_KERNEL_PARAMETER_PROJECTIONS[
    ("interlock", "distance_ratio")
].kernel_bounds

try:
    import manifold3d as m3d
except ImportError:  # pragma: no cover - exercised as an explicit compile failure
    m3d = None


@dataclass(frozen=True)
class CompilationResult:
    program: GeometryProgram
    status: str
    vertices: tuple[tuple[float, float, float], ...] = ()
    triangles: tuple[tuple[int, int, int], ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)
    trace: tuple[dict[str, Any], ...] = ()
    issues: tuple[GeometryIssue, ...] = ()
    geometry_hash: str = ""
    _solid: Any = field(default=None, repr=False, compare=False)

    def to_dict(self, *, include_mesh: bool = True) -> dict[str, Any]:
        # Imported lazily so the evidence layer can depend on the compiler gate
        # without making compilation itself depend on UI/persistence concerns.
        from backend.app.modules.design.generation.maas.geometry_language.execution_passport import build_mass_execution_passport

        payload: dict[str, Any] = {
            "schema_version": "arr.maas.geometry_compilation.v1",
            "status": self.status,
            "program_hash": self.program.program_hash() if not self.issues else "",
            "geometry_hash": self.geometry_hash,
            "metrics": self.metrics,
            "trace": list(self.trace),
            "issues": [issue.to_dict() for issue in self.issues],
            "execution_passport": build_mass_execution_passport(self),
        }
        if include_mesh:
            payload["mesh"] = {
                "vertices": [list(vertex) for vertex in self.vertices],
                "triangles": [list(face) for face in self.triangles],
            }
        return payload


class GeometryCompileError(RuntimeError):
    def __init__(self, code: str, message: str, node_id: str = "") -> None:
        super().__init__(message)
        self.issue = GeometryIssue(code, message, node_id)


def _canonicalize_export_mesh(
    raw_vertices: Any,
    raw_triangles: Any,
) -> tuple[
    tuple[tuple[float, float, float], ...],
    tuple[tuple[int, int, int], ...],
]:
    """Weld export duplicates and repair exact collinearity before zero cleanup."""

    vertices: list[tuple[float, float, float]] = []
    canonical_index: dict[tuple[float, float, float], int] = {}
    old_to_welded: list[int] = []
    for raw_vertex in raw_vertices:
        try:
            if len(raw_vertex) < 3:
                raise ValueError
            vertex = tuple(
                round(float(raw_vertex[axis]), EXPORT_DECIMAL_PLACES)
                for axis in range(3)
            )
        except (TypeError, ValueError, IndexError) as exc:
            raise GeometryCompileError(
                "invalid_mesh_export_vertex",
                "export mesh vertex must contain three finite coordinates",
            ) from exc
        if not all(isfinite(value) for value in vertex):
            raise GeometryCompileError(
                "invalid_mesh_export_vertex",
                "export mesh vertex must contain three finite coordinates",
            )
        welded_index = canonical_index.get(vertex)
        if welded_index is None:
            welded_index = len(vertices)
            canonical_index[vertex] = welded_index
            vertices.append(vertex)
        old_to_welded.append(welded_index)

    triangles: list[tuple[int, int, int]] = []
    for raw_triangle in raw_triangles:
        try:
            if len(raw_triangle) != 3:
                raise ValueError
            source_indices = tuple(int(value) for value in raw_triangle)
        except (TypeError, ValueError) as exc:
            raise GeometryCompileError(
                "invalid_mesh_export_triangle",
                "export mesh triangle must contain three indices",
            ) from exc
        if any(
            index < 0 or index >= len(old_to_welded)
            for index in source_indices
        ):
            raise GeometryCompileError(
                "invalid_mesh_export_index",
                "export mesh triangle references an invalid vertex",
            )
        triangle = tuple(old_to_welded[index] for index in source_indices)
        if len(set(triangle)) < 3:
            continue
        triangles.append(triangle)
    triangles = repair_export_collinearity(vertices, triangles)
    if not triangles:
        raise GeometryCompileError(
            "empty_mesh_export",
            "export mesh contains no non-degenerate triangles",
        )

    used = {
        vertex_index
        for triangle in triangles
        for vertex_index in triangle
    }
    compact_index = {
        old_index: new_index
        for new_index, old_index in enumerate(
            index for index in range(len(vertices))
            if index in used
        )
    }
    compact_vertices = tuple(
        vertex
        for index, vertex in enumerate(vertices)
        if index in used
    )
    compact_triangles = tuple(
        tuple(compact_index[index] for index in triangle)
        for triangle in triangles
    )
    return compact_vertices, compact_triangles


def compile_geometry_program(program: GeometryProgram) -> CompilationResult:
    program = normalize_unitbox_program(program)
    issues = tuple(issue for issue in program.validate() if issue.severity == "error")
    if issues:
        return CompilationResult(program, "invalid_program", issues=issues)
    if m3d is None:
        return CompilationResult(
            program,
            "kernel_unavailable",
            issues=(GeometryIssue("kernel_unavailable", "manifold3d>=3.4 is required"),),
        )
    cache: dict[str, Any] = {}
    trace: list[dict[str, Any]] = []
    node_map = program.node_map

    def evaluate(node_id: str):
        if node_id in cache:
            return cache[node_id]
        node = node_map[node_id]
        inputs = [evaluate(input_id) for input_id in node.inputs]
        try:
            solid, expansion = _evaluate_node(
                node,
                inputs,
                node_map=node_map,
            )
        except GeometryCompileError:
            raise
        except Exception as exc:
            raise GeometryCompileError("operator_exception", f"{type(exc).__name__}: {exc}", node.id) from exc
        if solid is None or solid.is_empty():
            raise GeometryCompileError("empty_operator_result", f"{node.operator} returned an empty solid", node.id)
        status = str(solid.status())
        if "NoError" not in status:
            raise GeometryCompileError("kernel_error", status, node.id)
        cache[node_id] = solid
        trace_row = {
            "node_id": node.id,
            "kind": node.kind,
            "operator": node.operator,
            "input_ids": list(node.inputs),
            "triangle_count": int(solid.num_tri()),
            "volume": round(float(solid.volume()), 6),
            "macro_expansion": expansion,
        }
        if node.kind == "transform" and inputs:
            trace_row["matrix4"] = matrix4_to_lists(_transform_matrix4(node, inputs[0]))
        if node.kind == "modifier" and node.operator == "taper":
            start = _scale_pair(node.parameters.get("start_scale", (1.0, 1.0)))
            end = _scale_pair(node.parameters.get("end_scale", node.parameters.get("scale_top", (.6, .6))))
            if start == end:
                axis = {"x": 0, "y": 1, "z": 2}[str(node.parameters.get("axis") or "z").lower()]
                scales = list(start)
                scales.insert(axis, 1.0)
                # Constant taper is affine. Translation about its pivot does
                # not affect sampling density; the actual warp remains owner.
                trace_row["sampling_linear_matrix4"] = matrix4_to_lists(
                    matrix4_for_transform("scale", {"vector": scales}))
        if node.kind == "pattern" and node.operator == "matrix_array":
            trace_row["matrix_entries"] = [
                {
                    "matrix_index": index,
                    "matrix4": matrix4_to_lists(matrix),
                }
                for index, matrix in enumerate(node.parameters.get("matrices") or ())
            ]
        if node.kind == "modifier" and node.operator == "profile_sweep_3d":
            path = [
                tuple(float(value) for value in point)
                for point in node.parameters.get("path") or ()
            ]
            trace_row["operator_metrics"] = {
                "path_length": round(sum(
                    float(np.linalg.norm(
                        np.asarray(end, dtype=float)
                        - np.asarray(start, dtype=float)
                    ))
                    for start, end in zip(path, path[1:])
                ), 6),
                "frame_count": len(path),
            }
        macro_matrix = _macro_affine_matrix4(node)
        if macro_matrix is not None:
            trace_row["matrix4"] = matrix4_to_lists(macro_matrix)
            trace_row["matrix_role"] = "macro_affine_expansion"
        if node.kind == "composition" and node.operator == "attach" and len(inputs) >= 2:
            try:
                trace_row["host_relation_resolution"] = resolve_face_attachment(
                    _bounds(inputs[0]),
                    _bounds(inputs[1]),
                    node.parameters,
                ).to_dict()
            except (TypeError, ValueError):
                # Invalid relations are raised by the operator itself. This
                # branch only keeps trace serialization from masking that
                # authoritative compiler error.
                pass
        trace.append(trace_row)
        return solid

    try:
        solid = evaluate(program.root_id)
        from backend.app.modules.design.generation.maas.geometry_language.surface_bounds import surface_sampling_issue

        sampling_issue = surface_sampling_issue(program, cache, trace)
        if sampling_issue:
            code, message, node_id = sampling_issue
            raise GeometryCompileError(code, message, node_id)
        mesh = solid.to_mesh64()
        raw_vertices = np.asarray(mesh.vert_properties, dtype=float)[:, :3]
        raw_triangles = np.asarray(mesh.tri_verts, dtype=np.int64)
        vertices, triangles = _canonicalize_export_mesh(
            raw_vertices,
            raw_triangles,
        )
        payload_vertices = np.asarray(vertices, dtype=float)
        payload_triangles = np.asarray(triangles, dtype=np.int64)
        metrics = _measured_solid_metrics(
            solid,
            raw_vertices=payload_vertices,
            raw_triangles=payload_triangles,
        )
        geometry_hash = _mesh_hash(vertices, triangles)
        transport_contract = (
            program.execution_contract.get(
                "capacity_replay_numeric_transport"
            )
            if program.execution_contract
            else None
        )
        if isinstance(transport_contract, dict):
            raw_result = CompilationResult(
                program=program,
                status="compiled",
                vertices=vertices,
                triangles=triangles,
                metrics=metrics,
                trace=tuple(trace),
                geometry_hash=geometry_hash,
                _solid=solid,
            )
            raw_issue_codes = [
                issue.code
                for issue in compilation_gate(
                    raw_result,
                    GeometryGatePolicy(maximum_components=1),
                )
            ]
            transport_evidence: dict[str, Any] = {
                "schema_version": (
                    "arr.maas.capacity_replay_numeric_transport.v1"
                ),
                "contract_hash_bound": True,
                "raw_gate_failure_codes": raw_issue_codes,
                "repair_attempted": False,
                "clean_gate_failure_codes": [],
                "clean_gate_hard_pass": False,
            }
            if raw_issue_codes == ["tiny_edge"]:
                from backend.app.modules.design.generation.maas.geometry_language.capacity_replay_numeric_transport import repair_capacity_replay_mesh

                repair = repair_capacity_replay_mesh(
                    program,
                    vertices,
                    triangles,
                )
                transport_evidence["repair_attempted"] = True
                if repair is not None:
                    clean_vertices = repair.vertices
                    clean_triangles = repair.triangles
                    clean_metrics = _measured_solid_metrics(
                        solid,
                        raw_vertices=np.asarray(
                            clean_vertices,
                            dtype=float,
                        ),
                        raw_triangles=np.asarray(
                            clean_triangles,
                            dtype=np.int64,
                        ),
                    )
                    clean_hash = _mesh_hash(
                        clean_vertices,
                        clean_triangles,
                    )
                    clean_result = CompilationResult(
                        program=program,
                        status="compiled",
                        vertices=clean_vertices,
                        triangles=clean_triangles,
                        metrics=clean_metrics,
                        trace=tuple(trace),
                        geometry_hash=clean_hash,
                        _solid=solid,
                    )
                    clean_issue_codes = [
                        issue.code
                        for issue in compilation_gate(
                            clean_result,
                            GeometryGatePolicy(maximum_components=1),
                        )
                    ]
                    transport_evidence.update(repair.evidence)
                    transport_evidence.update({
                        "raw_gate_failure_codes": raw_issue_codes,
                        "clean_gate_failure_codes": clean_issue_codes,
                        "clean_gate_hard_pass": not clean_issue_codes,
                    })
                    if not clean_issue_codes:
                        vertices = clean_vertices
                        triangles = clean_triangles
                        metrics = clean_metrics
                        geometry_hash = clean_hash
            metrics = {
                **metrics,
                "capacity_replay_numeric_transport": (
                    transport_evidence
                ),
            }
        return CompilationResult(
            program=program,
            status="compiled",
            vertices=vertices,
            triangles=triangles,
            metrics=metrics,
            trace=tuple(trace),
            geometry_hash=geometry_hash,
            _solid=solid,
        )
    except GeometryCompileError as exc:
        return CompilationResult(program, "compile_failed", trace=tuple(trace), issues=(exc.issue,))


def revalidate_compilation_mesh(
    compilation: CompilationResult,
) -> CompilationResult:
    """Measure the exact transported mesh instead of trusting prior metrics."""

    preserved = {
        key: compilation.metrics[key]
        for key in (
            "geometry_authority",
            "exact_payload_hash",
            "capacity_geometry_hash",
            "capacity_replay_metrics",
            "capacity_replay_identity",
            "capacity_replay_numeric_transport",
            "coordinate_space",
        )
        if key in (compilation.metrics or {})
    }
    if m3d is None:
        issue = GeometryIssue(
            "kernel_unavailable",
            "manifold3d>=3.4 is required to certify transported geometry",
        )
        return replace(
            compilation,
            status="kernel_unavailable",
            metrics=preserved,
            issues=(*tuple(compilation.issues or ()), issue),
            _solid=None,
        )
    try:
        raw_vertices = np.asarray(compilation.vertices, dtype=np.float64)
        raw_triangles = np.asarray(compilation.triangles, dtype=np.int64)
        if (
            raw_vertices.ndim != 2
            or raw_vertices.shape[1:] != (3,)
            or not len(raw_vertices)
            or not np.isfinite(raw_vertices).all()
            or raw_triangles.ndim != 2
            or raw_triangles.shape[1:] != (3,)
            or not len(raw_triangles)
            or raw_triangles.min() < 0
            or raw_triangles.max() >= len(raw_vertices)
        ):
            raise ValueError("invalid triangle mesh arrays")
        mesh = m3d.Mesh(
            raw_vertices,
            raw_triangles.astype(np.uint32, copy=False),
        )
        mesh.merge()
        solid = m3d.Manifold(mesh)
        kernel_status = str(solid.status())
        if "NoError" not in kernel_status or solid.is_empty():
            issue = GeometryIssue(
                "certified_mesh_not_manifold",
                "certified projected visual mesh failed manifold kernel validation",
            )
            return replace(
                compilation,
                status="compile_failed",
                metrics={
                    **preserved,
                    "kernel": "manifold3d",
                    "kernel_status": kernel_status,
                    "watertight": False,
                    "manifold": False,
                    "closed_solid": False,
                    "self_intersection_checked_by_kernel": True,
                    "outward_normals": False,
                    "vertex_count": len(raw_vertices),
                    "triangle_count": len(raw_triangles),
                },
                issues=(*tuple(compilation.issues or ()), issue),
                _solid=None,
            )
        metrics = _measured_solid_metrics(
            solid,
            raw_vertices=raw_vertices,
            raw_triangles=raw_triangles,
        )
        metrics.update({
            **preserved,
            "input_vertex_count": len(raw_vertices),
            "input_triangle_count": len(raw_triangles),
            "certified_mesh_revalidated": True,
        })
        return replace(
            compilation,
            status="compiled",
            metrics=metrics,
            issues=(),
            _solid=solid,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        issue = GeometryIssue(
            "certified_mesh_invalid",
            f"certified projected visual mesh is invalid: {exc}",
        )
        return replace(
            compilation,
            status="compile_failed",
            metrics=preserved,
            issues=(*tuple(compilation.issues or ()), issue),
            _solid=None,
        )


def _measured_solid_metrics(
    solid: Any,
    *,
    raw_vertices: np.ndarray,
    raw_triangles: np.ndarray,
) -> dict[str, Any]:
    signed_mesh_volume = float(np.einsum(
        "ij,ij->i",
        raw_vertices[raw_triangles[:, 0]],
        np.cross(
            raw_vertices[raw_triangles[:, 1]],
            raw_vertices[raw_triangles[:, 2]],
        ),
    ).sum() / 6.0)
    bounds = tuple(float(value) for value in solid.bounding_box())
    components = tuple(solid.decompose())
    component_volumes = tuple(sorted(
        (max(0.0, float(component.volume())) for component in components),
        reverse=True,
    ))
    total_component_volume = max(sum(component_volumes), 1e-12)
    component_volume_ratios = tuple(
        round(value / total_component_volume, 6)
        for value in component_volumes
    )
    return {
        "kernel": "manifold3d",
        "kernel_status": str(solid.status()),
        "watertight": True,
        "manifold": True,
        "closed_solid": True,
        "self_intersection_checked_by_kernel": True,
        "outward_normals": signed_mesh_volume > 0.0,
        "signed_mesh_volume": round(signed_mesh_volume, 6),
        "volume": round(float(solid.volume()), 6),
        "surface_area": round(float(solid.surface_area()), 6),
        "vertex_count": int(len(raw_vertices)),
        "triangle_count": int(len(raw_triangles)),
        "component_count": len(components),
        "component_volume_ratios": list(component_volume_ratios),
        "minimum_component_volume_ratio": min(
            component_volume_ratios,
            default=1.0,
        ),
        "genus": int(solid.genus()),
        "bounds": [
            [round(bounds[0], 6), round(bounds[1], 6), round(bounds[2], 6)],
            [round(bounds[3], 6), round(bounds[4], 6), round(bounds[5], 6)],
        ],
    }


def _evaluate_node(
    node: GeometryNode,
    inputs: list[Any],
    *,
    node_map: dict[str, GeometryNode],
) -> tuple[Any, list[str]]:
    if node.kind == "primitive":
        return _primitive(node), []
    if node.kind == "transform":
        return _transform(node, inputs[0]), []
    if node.kind == "modifier":
        if node.operator == "ellipsoidize":
            return _ellipsoidize(inputs[0], node.parameters, node.id), [
                "live_bounds", "bounded_ellipsoid", "unitbox_consumed",
            ]
        if node.operator == "tetrahedralize":
            return _tetrahedralize(inputs[0], node.id), [
                "live_bounds", "regular_tetrahedral_hull", "unitbox_consumed",
            ]
        if node.operator == "circularize":
            return _circularize(inputs[0], node.parameters, node.id), [
                "live_bounds",
                "bounded_circular_section",
                "extrude",
                "unitbox_consumed",
            ]
        if node.operator == "profile_sweep_3d":
            return _profile_sweep_3d(inputs[0], node.parameters, node.id), [
                "live_bounds",
                "parallel_transport_frames",
                "section_hulls",
                "union",
                "unitbox_consumed",
            ]
        return _modifier(node, inputs[0]), []
    if node.kind == "boolean":
        return _boolean(node, inputs, node_map=node_map), []
    if node.kind == "pattern":
        return _pattern(node, inputs[0]), []
    if node.kind == "composition":
        return _composition(node, inputs), []
    if node.kind == "macro":
        solid, expansion = _macro(node, inputs)
        return solid, expansion
    raise GeometryCompileError("unknown_node_kind", node.kind, node.id)


def _primitive(node: GeometryNode):
    p = node.parameters
    if node.operator == "box":
        return m3d.Manifold.cube((_number(p, "width"), _number(p, "depth"), _number(p, "height")), center=bool(p.get("center", False)))
    if node.operator == "cylinder":
        return m3d.Manifold.cylinder(
            _number(p, "height"),
            _number(p, "radius", p.get("radius_low", 1.0)),
            _number(p, "radius_high", p.get("radius", p.get("radius_low", 1.0))),
            circular_segments=max(8, min(96, int(p.get("segments", 24)))),
            center=bool(p.get("center", False)),
        )
    if node.operator == "extruded_polygon":
        points = _points(p.get("points"), dimensions=2, minimum=3, node_id=node.id)
        contours = [points]
        for hole in p.get("holes") or []:
            contours.append(_points(hole, dimensions=2, minimum=3, node_id=node.id))
        section = m3d.CrossSection(contours)
        return section.extrude(_number(p, "height"), n_divisions=max(0, min(16, int(p.get("divisions", 0)))))
    if node.operator == "wedge":
        width, depth = _number(p, "width"), _number(p, "depth")
        h0, h1 = _number(p, "start_height"), _number(p, "end_height")
        points = [(0, 0, 0), (width, 0, 0), (width, depth, 0), (0, depth, 0)]
        points += [(0, 0, h0), (0, depth, h0), (width, 0, h1), (width, depth, h1)]
        return m3d.Manifold.hull_points(points)
    if node.operator == "sweep":
        path = _points(p.get("path"), dimensions=None, minimum=2, node_id=node.id)
        path3 = [(point[0], point[1], point[2] if len(point) > 2 else 0.0) for point in path]
        return _sweep_path(
            path3,
            width=_number(p, "profile_width", p.get("width", 2.0)),
            height=_number(p, "profile_height", p.get("height", 3.0)),
        )
    if node.operator == "loft":
        return _loft_profiles(p.get("profiles"), node_id=node.id)
    raise GeometryCompileError("unsupported_primitive", node.operator, node.id)


def _transform(node: GeometryNode, solid):
    return solid.transform(kernel_matrix3x4(_transform_matrix4(node, solid)))


def _transform_matrix4(node: GeometryNode, solid):
    parameters = dict(node.parameters)
    pivot_raw = parameters.get("pivot", (0.0, 0.0, 0.0))
    if str(pivot_raw).lower() in {"center", "centroid"}:
        parameters["pivot"] = _center(solid)
    try:
        return matrix4_for_transform(node.operator, parameters)
    except (TypeError, ValueError) as exc:
        code = "invalid_matrix4" if node.operator == "matrix4" else "invalid_affine_transform"
        raise GeometryCompileError(code, str(exc), node.id) from exc


def _macro_affine_matrix4(node: GeometryNode):
    if node.kind != "macro" or node.operator != "leaning_tower":
        return None
    direction = str(node.parameters.get("direction") or "x").lower()
    return matrix4_for_transform("shear", {
        "axis": direction,
        "direction": "z",
        "amount": float(node.parameters.get("amount", 0.18)),
    })


def _modifier(node: GeometryNode, solid):
    p = node.parameters
    if node.operator == "bound_surfaces":
        from backend.app.modules.design.generation.maas.geometry_language.surface_bounds import intersect_surface_bounds

        try:
            return intersect_surface_bounds(solid, p)
        except ValueError as exc:
            raise GeometryCompileError("invalid_surface_envelope", str(exc), node.id) from exc
    if node.operator == "taper":
        return _warp_taper(solid, p, node.id)
    if node.operator == "twist":
        return _warp_twist(solid, p, node.id)
    if node.operator == "bend":
        return _warp_bend(solid, p, node.id)
    if node.operator == "pinch":
        return _warp_mid_profile(solid, p, node.id, mode="pinch")
    if node.operator == "inflate":
        return _warp_mid_profile(solid, p, node.id, mode="inflate")
    if node.operator in {"slice", "clip"}:
        normal = np.asarray(_vector(p.get("normal"), 3, node.id), dtype=float)
        normal /= max(float(np.linalg.norm(normal)), 1e-12)
        keep_negative = str(p.get("keep_side") or "positive").lower() in {"negative", "below", "back"}
        offset = float(p.get("offset", 0.0))
        if keep_negative:
            normal = -normal
            offset = -offset
        if p.get("offset_ratio") is not None:
            # Agent-authored cuts operate in normalized live-solid space. An
            # absolute plane offset made the same graph erase most of a slab
            # while barely touching a block.  After orienting the kept side,
            # trim a bounded fraction from the negative projection extreme.
            cut_ratio = max(0.02, min(0.45, float(p.get("offset_ratio"))))
            minx, miny, minz, maxx, maxy, maxz = _bounds(solid)
            projections = [
                float(np.dot(normal, np.asarray((x, y, z), dtype=float)))
                for x in (minx, maxx)
                for y in (miny, maxy)
                for z in (minz, maxz)
            ]
            offset = min(projections) + (max(projections) - min(projections)) * cut_ratio
        return solid.trim_by_plane(tuple(normal.tolist()), offset)
    if node.operator == "clip_fraction":
        return _clip_fraction(solid, p, node.id)
    if node.operator == "book_base_volume":
        return _book_base_volume(solid, p, node.id)
    if node.operator == "cut_corner":
        return _cut_corner(solid, p, node.id)
    if node.operator == "legal_section_clip":
        exterior = _points(
            p.get("exterior"),
            dimensions=2,
            minimum=3,
            node_id=node.id,
        )
        holes = [
            _points(
                hole,
                dimensions=2,
                minimum=3,
                node_id=node.id,
            )
            for hole in p.get("holes") or ()
        ]
        try:
            lower_z = float(p.get("lower_z"))
            upper_z = float(p.get("upper_z"))
        except (TypeError, ValueError) as exc:
            raise GeometryCompileError(
                "invalid_legal_section_band",
                "legal section clip z bounds must be finite numbers",
                node.id,
            ) from exc
        if not np.isfinite((lower_z, upper_z)).all():
            raise GeometryCompileError(
                "invalid_legal_section_band",
                "legal section clip z bounds must be finite numbers",
                node.id,
            )
        if upper_z - lower_z <= 1e-9:
            raise GeometryCompileError(
                "invalid_legal_section_band",
                "legal section clip upper_z must exceed lower_z",
                node.id,
            )
        legal_solid = (
            m3d.CrossSection([exterior, *holes])
            .extrude(upper_z - lower_z)
            .translate((0.0, 0.0, lower_z))
        )
        return m3d.Manifold.batch_boolean(
            [solid, legal_solid],
            m3d.OpType.Intersect,
        )
    raise GeometryCompileError("unsupported_modifier", node.operator, node.id)


def _circularize(solid, params: dict[str, Any], node_id: str):
    minx, miny, minz, maxx, maxy, maxz = _bounds(solid)
    radius_x = (maxx - minx) / 2.0
    radius_y = (maxy - miny) / 2.0
    height = maxz - minz
    if min(radius_x, radius_y, height) <= 1e-9:
        raise GeometryCompileError(
            "degenerate_circularize_bounds",
            "circularize requires positive live input bounds",
            node_id,
        )
    try:
        segments = max(8, min(96, int(params.get("segments", 24))))
    except (TypeError, ValueError) as exc:
        raise GeometryCompileError(
            "invalid_circularize_segments",
            "circularize segments must be an integer",
            node_id,
        ) from exc
    center_x = (minx + maxx) / 2.0
    center_y = (miny + maxy) / 2.0
    return (
        m3d.Manifold.cylinder(
            height,
            1.0,
            circular_segments=segments,
        )
        .scale((radius_x, radius_y, 1.0))
        .translate((center_x, center_y, minz))
    )


def _ellipsoidize(solid, params: dict[str, Any], node_id: str):
    minx, miny, minz, maxx, maxy, maxz = _bounds(solid)
    width, depth, height = maxx - minx, maxy - miny, maxz - minz
    if min(width, depth, height) <= 1e-9:
        raise GeometryCompileError(
            "degenerate_ellipsoidize_bounds",
            "ellipsoidize requires positive live input bounds",
            node_id,
        )
    try:
        segments = max(8, min(96, int(params.get("segments", 24))))
    except (TypeError, ValueError) as exc:
        raise GeometryCompileError(
            "invalid_ellipsoidize_segments",
            "ellipsoidize segments must be an integer",
            node_id,
        ) from exc
    center = (
        (minx + maxx) / 2.0,
        (miny + maxy) / 2.0,
        (minz + maxz) / 2.0,
    )
    return (
        m3d.Manifold.sphere(0.5, circular_segments=segments)
        .scale((width, depth, height))
        .translate(center)
    )


def _tetrahedralize(solid, node_id: str):
    minx, miny, minz, maxx, maxy, maxz = _bounds(solid)
    if min(maxx - minx, maxy - miny, maxz - minz) <= 1e-9:
        raise GeometryCompileError(
            "degenerate_tetrahedralize_bounds",
            "tetrahedralize requires positive live input bounds",
            node_id,
        )
    return m3d.Manifold.hull_points((
        (minx, miny, minz),
        (maxx, maxy, minz),
        (maxx, miny, maxz),
        (minx, maxy, maxz),
    ))


def _boolean(
    node: GeometryNode,
    inputs: list[Any],
    *,
    node_map: dict[str, GeometryNode],
):
    if (
        node.operator == "union"
        and str((node.provenance or {}).get("set_identity") or "")
        == "host_union_subsets_equals_host"
        and _valid_host_subset_union(node, node_map)
    ):
        # Every remaining input is an intersection with the first input, so
        # P union (P intersection F1) ... is exactly P. The evidence inputs
        # are still compiled and traced before this typed CSG normalization.
        return inputs[0]
    op = {
        "union": m3d.OpType.Add,
        "difference": m3d.OpType.Subtract,
        "intersection": m3d.OpType.Intersect,
    }[node.operator]
    result = m3d.Manifold.batch_boolean(inputs, op)
    if (
        node.operator == "union"
        and str((node.provenance or {}).get("book_verb") or "")
        == "recompose_book_scope"
    ):
        for _pass in range(3):
            parts = list(result.decompose())
            if len(parts) <= 1:
                break
            # A local p.3 mutation must remain physically engaged with the
            # unselected host. Connect the actual nearest exposed descendants
            # at the recomposition boundary; ordinary unions are untouched.
            connectors = [
                _bridge_between(
                    left,
                    right,
                    {"width_ratio": 0.24, "height_ratio": 0.72},
                    node.id,
                )
                for left, right in _nearest_component_tree(parts)
            ]
            result = m3d.Manifold.batch_boolean(
                [*parts, *connectors], m3d.OpType.Add
            )
    return result


def _valid_host_subset_union(
    node: GeometryNode,
    node_map: dict[str, GeometryNode],
) -> bool:
    if len(node.inputs) < 2:
        return False
    host_id = node.inputs[0]
    for subset_id in node.inputs[1:]:
        subset = node_map.get(subset_id)
        if (
            subset is None
            or subset.kind != "boolean"
            or subset.operator != "intersection"
            or host_id not in subset.inputs
        ):
            return False
    return True


def _pattern(node: GeometryNode, solid):
    p = node.parameters
    if node.operator == "matrix_array":
        matrices = p.get("matrices")
        if not isinstance(matrices, list) or not 2 <= len(matrices) <= 24:
            raise GeometryCompileError(
                "matrix_array_count_out_of_bounds",
                "matrix_array requires 2..24 explicit matrices",
                node.id,
            )
        copies: list[Any] = []
        for matrix in matrices:
            try:
                transformed = solid.transform(kernel_matrix3x4(matrix))
            except (TypeError, ValueError) as exc:
                raise GeometryCompileError(
                    "invalid_matrix_array_matrix",
                    str(exc),
                    node.id,
                ) from exc
            if transformed.is_empty():
                raise GeometryCompileError(
                    "empty_matrix_array",
                    "matrix_array transform returned an empty solid",
                    node.id,
                )
            copies.append(transformed)
        result = copies[0]
        for copy in copies[1:]:
            result = m3d.Manifold.batch_boolean(
                [result, copy],
                m3d.OpType.Add,
            )
        if result.is_empty():
            raise GeometryCompileError(
                "empty_matrix_array",
                "matrix_array union returned an empty solid",
                node.id,
            )
        if bool(p.get("require_connected", False)) and len(result.decompose()) != 1:
            raise GeometryCompileError(
                "disconnected_matrix_array",
                "matrix_array must produce one connected component",
                node.id,
            )
        return result
    count = max(1, min(24, int(p.get("count", 2))))
    copies: list[Any] = []
    if node.operator in {"duplicate", "linear_array"}:
        vector = _vector(p.get("vector", (p.get("spacing", 2.0), 0.0, 0.0)), 3, node.id)
        copies = [solid.translate(tuple(value * index for value in vector)) for index in range(count)]
    elif node.operator == "stack":
        spacing = float(p.get("spacing", _bounds(solid)[5] - _bounds(solid)[2]))
        shift = _vector(p.get("shift_per_level", (0.0, 0.0, 0.0)), 3, node.id)
        copies = [solid.translate((shift[0] * index, shift[1] * index, spacing * index + shift[2] * index)) for index in range(count)]
    elif node.operator == "radial_array":
        total = float(p.get("total_angle_degrees", p.get("angle_degrees", 180.0)))
        pivot_raw = p.get("pivot", (0.0, 0.0, 0.0))
        pivot = _center(solid) if str(pivot_raw).lower() in {"center", "centroid"} else _vector(pivot_raw, 3, node.id)
        step = total / max(count - 1, 1)
        copies = [_around_pivot(solid, pivot, lambda item, angle=step * index: item.rotate((0.0, 0.0, angle))) for index in range(count)]
    elif node.operator == "mirror_array":
        normal = _vector(p.get("normal", (1.0, 0.0, 0.0)), 3, node.id)
        pivot_raw = p.get("pivot", (0.0, 0.0, 0.0))
        pivot = _center(solid) if str(pivot_raw).lower() in {"center", "centroid"} else _vector(pivot_raw, 3, node.id)
        copies = [solid, _around_pivot(solid, pivot, lambda item: item.mirror(normal))]
    else:
        raise GeometryCompileError("unsupported_pattern", node.operator, node.id)
    return m3d.Manifold.batch_boolean(copies, m3d.OpType.Add)


def _composition(node: GeometryNode, inputs: list[Any]):
    if node.operator == "attach":
        result = inputs[0]
        for guest in inputs[1:]:
            placed = _attach_to_host_face(result, guest, node.parameters, node.id)
            result = m3d.Manifold.batch_boolean([result, placed], m3d.OpType.Add)
        return result
    if node.operator == "bridge":
        bridge = _bridge_between(inputs[0], inputs[1], node.parameters, node.id)
        return m3d.Manifold.batch_boolean([*inputs, bridge], m3d.OpType.Add)
    raise GeometryCompileError("unsupported_composition", node.operator, node.id)


def _attach_to_host_face(host, guest, params: dict[str, Any], node_id: str):
    """Scale and place a guest in one normalized face frame of ``host``.

    ``anchor_u``/``anchor_v`` are local face coordinates in ``[-1, 1]``.
    A small positive embed keeps the Boolean result connected and makes the
    attachment a volumetric architectural relation rather than a coincident
    surface or a floating component.
    """

    host_bounds = _bounds(host)
    guest_bounds = _bounds(guest)
    try:
        resolution = resolve_face_attachment(host_bounds, guest_bounds, params)
    except (TypeError, ValueError) as exc:
        raise GeometryCompileError("invalid_attach_parameters", str(exc), node_id) from exc
    guest_span = [
        max(guest_bounds[i + 3] - guest_bounds[i], 1e-7)
        for i in range(3)
    ]
    scaled = _around_pivot(
        guest,
        _center(guest),
        lambda item: item.scale(tuple(resolution.target_span[i] / guest_span[i] for i in range(3))),
    )
    if abs(resolution.rotation_degrees) > 1e-7:
        angles = [0.0, 0.0, 0.0]
        angles[resolution.normal_axis] = resolution.rotation_degrees
        scaled = _around_pivot(scaled, _center(scaled), lambda item: item.rotate(tuple(angles)))
    current_center = _center(scaled)
    placed = scaled.translate(tuple(
        resolution.target_center[i] - current_center[i] for i in range(3)
    ))
    union = m3d.Manifold.batch_boolean([host, placed], m3d.OpType.Add)
    if union.is_empty() or len(union.decompose()) != 1:
        raise GeometryCompileError(
            "disconnected_attach",
            "attached guest must retain volumetric overlap with its host face",
            node_id,
        )
    return placed


def _macro(node: GeometryNode, inputs: list[Any]) -> tuple[Any, list[str]]:
    p = node.parameters
    base = inputs[0]
    operator = node.operator
    if operator in {"courtyard", "carve_void"}:
        if len(inputs) >= 2:
            cutter = inputs[1]
        else:
            minx, miny, minz, maxx, maxy, maxz = _bounds(base)
            margin = max(0.08, min(0.45, float(p.get("margin_ratio", p.get("margin", 0.22)))))
            inner_minx = minx + (maxx - minx) * margin
            inner_miny = miny + (maxy - miny) * margin
            inner_maxx = maxx - (maxx - minx) * margin
            inner_maxy = maxy - (maxy - miny) * margin
            open_side = str(p.get("open_side") or "closed").strip().lower()
            side_aliases = {
                "long_positive": "east", "+long": "east", "x+": "east",
                "long_negative": "west", "-long": "west", "x-": "west",
                "short_positive": "north", "+short": "north", "y+": "north",
                "short_negative": "south", "-short": "south", "y-": "south",
            }
            open_side = side_aliases.get(open_side, open_side)
            # A closed court subtracts only the inner box. An open court
            # extends the same normalized cutter through one envelope edge,
            # producing a continuous U-shaped public threshold. This is a
            # semantic side relation, never a stored parcel coordinate.
            if open_side == "east":
                inner_maxx = maxx + 1.0
            elif open_side == "west":
                inner_minx = minx - 1.0
            elif open_side == "north":
                inner_maxy = maxy + 1.0
            elif open_side == "south":
                inner_miny = miny - 1.0
            cutter = m3d.Manifold.cube((
                inner_maxx - inner_minx,
                inner_maxy - inner_miny,
                maxz - minz + 2.0,
            )).translate((inner_minx, inner_miny, minz - 1.0))
        return base - cutter, ["difference", "open_side_box_cutter" if p.get("open_side") not in (None, "", "closed") else "box_cutter"]
    if operator == "notch":
        minx, miny, minz, maxx, maxy, maxz = _bounds(base)
        ratio = max(0.08, min(0.48, float(p.get("ratio", 0.25))))
        side = str(p.get("side") or "").strip().lower()
        side = {
            "long_positive": "east", "+long": "east", "x+": "east",
            "long_negative": "west", "-long": "west", "x-": "west",
            "short_positive": "north", "+short": "north", "y+": "north",
            "short_negative": "south", "-short": "south", "y-": "south",
        }.get(side, side)
        if side in {"east", "west", "north", "south"}:
            x_span, y_span = maxx - minx, maxy - miny
            opening = max(0.14, min(0.62, float(p.get("width_ratio", ratio * 1.65))))
            height = (maxz - minz) * max(0.1, min(1.2, float(p.get("height_ratio", 0.62))))
            if side in {"east", "west"}:
                width, depth = x_span * ratio, y_span * opening
                x = maxx - width if side == "east" else minx
                y = (miny + maxy - depth) / 2.0
            else:
                width, depth = x_span * opening, y_span * ratio
                x = (minx + maxx - width) / 2.0
                y = maxy - depth if side == "north" else miny
            cutter = m3d.Manifold.cube((width, depth, height + 0.5)).translate((x, y, minz - 0.25))
            return base - cutter, ["difference", "frontage_side_entry_cutter"]
        corner = str(p.get("corner") or "ne").lower()
        width, depth, height = (maxx - minx) * ratio, (maxy - miny) * ratio, (maxz - minz) * max(0.1, min(1.2, float(p.get("height_ratio", 1.0))))
        x = maxx - width if "e" in corner else minx
        y = maxy - depth if "n" in corner else miny
        cutter = m3d.Manifold.cube((width, depth, height + 1.0)).translate((x, y, minz - 0.5))
        return base - cutter, ["difference", "corner_box_cutter"]
    if operator in {"setback", "stepped_mass", "terrace"}:
        return _stepped_macro(base, p, terrace=operator == "terrace"), ["slice", "scale", "translate", "union"]
    if operator == "profiled_hall":
        return _profiled_hall_macro(base, p, node.id), ["normalized_section_profile", "strip_wedge_array", "union"]
    if operator == "cantilever":
        minx, miny, minz, maxx, maxy, maxz = _bounds(base)
        cut = minz + (maxz - minz) * max(0.1, min(0.9, float(p.get("start_ratio", 0.55))))
        vector = _vector(p.get("vector", (0.22, 0.0, 0.0)), 3, node.id)
        if abs(vector[2]) > 1e-7:
            raise GeometryCompileError(
                "cantilever_requires_horizontal_vector",
                "cantilever vector z must be zero; use lift for a vertical relation",
                node.id,
            )
        span_x = max(maxx - minx, 1e-7)
        span_y = max(maxy - miny, 1e-7)
        translation = (
            max(-span_x * 0.45, min(span_x * 0.45, vector[0])),
            max(-span_y * 0.45, min(span_y * 0.45, vector[1])),
            0.0,
        )
        overlap = max(maxz - minz, span_x, span_y, 1.0) * 1e-4
        upper = base.trim_by_plane((0.0, 0.0, 1.0), cut - overlap).translate(translation)
        lower = base.trim_by_plane((0.0, 0.0, -1.0), -(cut + overlap))
        return lower + upper, ["split_by_plane", "translate", "union"]
    if operator == "bridge":
        if len(inputs) < 2:
            raise GeometryCompileError("macro_requires_two_inputs", "bridge macro needs two wings", node.id)
        bridge = _bridge_between(inputs[0], inputs[1], p, node.id)
        return m3d.Manifold.batch_boolean([inputs[0], inputs[1], bridge], m3d.OpType.Add), ["beam_between", "union"]
    if operator == "book_branch":
        return _book_branch_macro(base, p, node.id), ["end_scope", "paired_arm_rotate", "union"]
    if operator == "book_stack":
        return _book_stack_macro(base, p, node.id), ["level_copies", "per_level_transform", "union"]
    if operator == "book_array":
        return _book_array_macro(base, p, node.id), ["identical_copies", "translate", "union"]
    if operator == "book_split":
        return _book_terminal_split_macro(base, p, node.id), [
            "terminal_child_scope", "hinged_displacement", "union", "retained_trunk",
        ]
    if operator == "boundary_expand":
        return _boundary_expand_macro(base, p, node.id), ["end_scope", "one_face_scale", "union"]
    if operator == "shift_related":
        return _shift_related_macro(base, p, node.id), [
            "plan_partition", "translate_related_child", "shared_edge_overlap",
            "union",
        ]
    if operator == "offset_related":
        return _offset_related_macro(base, p, node.id), ["scale_related_unit", "live_span_translate", "union"]
    if operator == "nested_related":
        return _nested_related_macro(base, p, node.id), ["scale_inner_volume", "bounded_internal_offset", "roof_reveal", "union"]
    if operator == "interlock_related":
        return _interlock_related_macro(base, p, node.id), [
            "notched_l_module", "duplicate", "rotate", "live_span_translate",
            "shared_interlock_zone", "union",
        ]
    if operator == "intersect_related":
        return _intersect_related_macro(base, p, node.id), [
            "primary_bar", "scaled_related_bar", "orthogonal_angle_deviation",
            "intersection_overlap", "union",
        ]
    if operator == "embed_void":
        return _embed_void_macro(base, p, node.id), ["scaled_guest_cutter", "partial_embed", "difference"]
    if operator == "related_array":
        return _related_array_macro(base, p, node.id), ["scale_unit", "relational_distribution", "union"]
    if operator == "join_related":
        parts = list(base.decompose())
        if len(parts) < 2:
            return base, ["already_connected"]
        # BOOK join states its bridge as `bridge_ratio`; the bridge reads
        # `width_ratio`. Without this the word's variation never reached the
        # geometry (both default to 0.24, so an unstated ratio is unchanged).
        bridge_params = dict(p)
        if "bridge_ratio" in p and "width_ratio" not in p:
            bridge_params["width_ratio"] = float(p["bridge_ratio"])
        bridges = [
            _bridge_between(left, right, bridge_params, node.id)
            for left, right in _nearest_component_tree(parts)
        ]
        return m3d.Manifold.batch_boolean([base, *bridges], m3d.OpType.Add), ["nearest_component_tree", "bridge", "union"]
    if operator == "merge_related":
        minx, miny, minz, maxx, maxy, maxz = _bounds(base)
        spans = (maxx - minx, maxy - miny, maxz - minz)
        axis = {"x": 0, "y": 1, "z": 2}.get(str(p.get("axis") or "x").lower(), 0)
        unit_scale = max(0.42, min(0.82, float(p.get("unit_scale", 0.42)) + 0.24))
        gap = max(0.04, min(0.48, float(p.get("gap_ratio", 0.22))))
        related = _around_pivot(
            base,
            _center(base),
            lambda item: item.scale((unit_scale, unit_scale, unit_scale)),
        )
        # Move just beyond the scaled copy's retracted terminal face. This
        # exposes the merge while retaining a robust intersection with base.
        offset = spans[axis] * ((1.0 - unit_scale) / 2.0 + 0.035 + gap * 0.10)
        vector = [0.0, 0.0, 0.0]
        vector[axis] = offset
        related = related.translate(tuple(vector))
        return m3d.Manifold.batch_boolean([base, related], m3d.OpType.Add), [
            "scale_related_unit", "live_span_overlap", "union",
        ]
    if operator == "overlap_related":
        return _overlap_related_macro(base, p, node.id), [
            "primary_bar", "orthogonal_related_bar", "terminal_plan_overlap",
            "translate", "union",
        ]
    if operator == "cross_mass":
        pivot = _center(base)
        other = _around_pivot(base, pivot, lambda item: item.rotate((0.0, 0.0, float(p.get("angle_degrees", 90.0)))))
        return base + other, ["rotate", "union"]
    if operator == "grid_mass":
        minx, miny, _minz, maxx, maxy, _maxz = _bounds(base)
        pivot = _center(base)
        depth = max(maxy - miny, 1e-7)
        width = max(maxx - minx, 1e-7)
        row_shift = depth * max(1.05, min(1.8, float(p.get("row_spacing_ratio", 1.28))))
        column_shift = width * max(0.12, min(0.38, float(p.get("column_offset_ratio", 0.26))))
        rows = [base.translate((0.0, shift, 0.0)) for shift in (-row_shift, 0.0, row_shift)]
        vertical = _around_pivot(base, pivot, lambda item: item.rotate((0.0, 0.0, 90.0)))
        columns = [vertical.translate((shift, 0.0, 0.0)) for shift in (-column_shift, column_shift)]
        return m3d.Manifold.batch_boolean([*rows, *columns], m3d.OpType.Add), ["parallel_rows", "rotated_columns", "union"]
    if operator == "bent_bar":
        return _warp_bend(base, p, node.id), ["refine", "bend_warp"]
    if operator == "split_wing":
        minx, miny, minz, maxx, maxy, maxz = _bounds(base)
        axis = str(p.get("axis") or "x").lower()
        gap = max(0.05, min(0.5, float(p.get("gap_ratio", 0.18))))
        if str(p.get("layout") or "split").lower() == "parallel":
            span_x = max(maxx - minx, 1e-7)
            span_y = max(maxy - miny, 1e-7)
            span_z = max(maxz - minz, 1e-7)
            separation = span_y * (1.0 + gap)
            first = base.translate((0.0, -separation / 2.0, 0.0))
            second = base.translate((0.0, separation / 2.0, 0.0))
            first_center, second_center = _center(first), _center(second)
            connector = _beam_between(
                (first_center[0], first_center[1], minz),
                (second_center[0], second_center[1], minz),
                width=span_x * max(0.14, min(0.32, float(p.get("connector_width_ratio", 0.20)))),
                height=span_z * max(0.42, min(1.0, float(p.get("height_ratio", 0.72)))),
                node_id=node.id,
            )
            return m3d.Manifold.batch_boolean([first, second, connector], m3d.OpType.Add), [
                "parallel_wings", "transverse_spine", "union",
            ]
        if axis == "y":
            size = (maxx - minx + 2, (maxy - miny) * gap, maxz - minz + 2)
            origin = (minx - 1, (miny + maxy - size[1]) / 2, minz - 1)
        else:
            size = ((maxx - minx) * gap, maxy - miny + 2, maxz - minz + 2)
            origin = ((minx + maxx - size[0]) / 2, miny - 1, minz - 1)
        split = base - m3d.Manifold.cube(size).translate(origin)
        parts = split.decompose()
        additions = []
        expansion = ["difference", "decompose"]
        if bool(p.get("ground_spine", False)) and len(parts) >= 2:
            # A long-span wing pair needs an occupiable service/entry spine,
            # not two almost-disconnected bars held together only by a small
            # roof bridge.  The relation stays normalized to the live solid
            # bounds and is therefore transferable across parcels.  Upper
            # wings remain visually split while the low spine improves role
            # coverage, coherence and downstream geometry retention.
            short_span = (maxy - miny) if axis == "x" else (maxx - minx)
            height_span = max(maxz - minz, 1e-7)
            spine_width = short_span * max(0.18, min(0.72, float(p.get("ground_spine_width_ratio", 0.38))))
            spine_height = height_span * max(0.10, min(0.42, float(p.get("ground_spine_height_ratio", 0.22))))
            for left, right in _nearest_component_tree(parts):
                left_center, right_center = _center(left), _center(right)
                additions.append(_beam_between(
                    (left_center[0], left_center[1], minz),
                    (right_center[0], right_center[1], minz),
                    width=spine_width,
                    height=spine_height,
                    node_id=node.id,
                ))
            expansion.append("ground_service_spine_tree")
        if (
            bool(p.get("bridge", False))
            and not bool(p.get("ground_spine", False))
            and len(parts) >= 2
        ):
            additions.extend(
                _bridge_between(left, right, p, node.id)
                for left, right in _nearest_component_tree(parts)
            )
            expansion.append("upper_bridge_tree")
        if additions:
            split = m3d.Manifold.batch_boolean([split, *additions], m3d.OpType.Add)
            return split, [*expansion, "union"]
        return split, ["difference", "gap_cutter"]
    if operator == "attach_volume":
        return m3d.Manifold.batch_boolean(inputs, m3d.OpType.Add), ["union"]
    if operator == "tapered_tower":
        return _warp_taper(base, p, node.id), ["taper_warp"]
    if operator == "leaning_tower":
        return base.transform(kernel_matrix3x4(_macro_affine_matrix4(node))), ["shear"]
    if operator == "lift":
        from backend.app.modules.design.generation.maas.geometry_language.lift_parts import lift_parts
        lifted, supports, expansion, _ = lift_parts(base, p)
        return m3d.Manifold.batch_boolean([lifted, *supports], m3d.OpType.Add), expansion
    if operator == "book_lift":
        return _book_lift_related_macro(base, p, node.id), [
            "scaled_guest_volume", "oriented_displacement", "shared_host_overlap",
            "union",
        ]
    if operator == "book_lodge":
        return _book_lodge_macro(base, p, node.id), [
            "paired_host_volumes", "scaled_lodged_guest", "dual_host_overlap",
            "union",
        ]
    if operator == "book_rotate":
        return _book_rotate_macro(base, p, node.id), [
            "paired_bar_partition", "shared_edge_hinge", "rotate_related_bar",
            "union",
        ]
    if operator == "book_carve":
        return _book_carve_macro(base, p, node.id), [
            "selected_face_frame", "bounded_rectangular_recess", "difference",
        ]
    if operator == "book_fracture":
        return _book_fracture_macro(base, p, node.id), [
            "selected_face_frame", "bent_fissure_channel",
            "retained_back_layer", "difference",
        ]
    if operator == "book_grade":
        return _book_grade_macro(base, p, node.id), [
            "selected_face_frame", "successive_depth_bands", "difference",
        ]
    if operator == "book_notch":
        return _book_notch_macro(base, p, node.id), [
            "selected_face_frame", "triangular_wedge_cutter", "difference",
        ]
    if operator == "book_extract":
        return _book_extract_macro(base, p, node.id), [
            "internal_guest_cutter", "overlapping_extraction_path",
            "exterior_mouth", "difference",
        ]
    if operator == "puncture":
        minx, miny, minz, maxx, maxy, maxz = _bounds(base)
        axis = str(p.get("axis") or "x").lower()
        count = max(1, min(3, int(p.get("count", p.get("n", 2)))))
        ratio = max(0.06, min(0.26, float(p.get("ratio", 0.14))))
        # Hole centres along the cut axis. BOOK puncture states their spacing
        # (`spacing_ratio`, centre to centre as a share of the span); it used to
        # be ignored and the holes always sat at (i+1)/(n+1).
        if "spacing_ratio" in p and count > 1:
            spacing = max(ratio + 0.02, min(0.45, float(p["spacing_ratio"])))
            edge = ratio / 2.0 + 0.02
            positions = [
                max(edge, min(1.0 - edge, 0.5 + (index - (count - 1) / 2.0) * spacing))
                for index in range(count)
            ]
        else:
            positions = [(index + 1) / (count + 1) for index in range(count)]
        cutters = []
        if axis == "y":
            width = (maxx - minx) * ratio
            height = (maxz - minz) * ratio
            for index in range(count):
                t = positions[index]
                cutters.append(m3d.Manifold.cube((width, maxy - miny + 2.0, height)).translate((
                    minx + (maxx - minx) * t - width / 2.0, miny - 1.0,
                    minz + (maxz - minz) * 0.5 - height / 2.0,
                )))
        else:
            depth = (maxy - miny) * ratio
            height = (maxz - minz) * ratio
            for index in range(count):
                t = positions[index]
                cutters.append(m3d.Manifold.cube((maxx - minx + 2.0, depth, height)).translate((
                    minx - 1.0, miny + (maxy - miny) * t - depth / 2.0,
                    minz + (maxz - minz) * 0.5 - height / 2.0,
                )))
        cutter = m3d.Manifold.batch_boolean(cutters, m3d.OpType.Add)
        return base - cutter, ["cutter_array", "difference"]
    if operator == "cut_corner":
        return _cut_corner(base, p, node.id), ["half_space_intersection"]
    raise GeometryCompileError("unsupported_macro", operator, node.id)


def _warp_taper(solid, params: dict[str, Any], node_id: str):
    axis = str(params.get("axis") or "z").lower()
    axis_index = {"x": 0, "y": 1, "z": 2}.get(axis)
    if axis_index is None:
        raise GeometryCompileError("invalid_axis", axis, node_id)
    bounds = _bounds(solid)
    low, high = bounds[axis_index], bounds[axis_index + 3]
    length = max(high - low, 1e-9)
    start = params.get("start_scale", (1.0, 1.0))
    end = params.get("end_scale", params.get("scale_top", (0.6, 0.6)))
    start2 = _scale_pair(start)
    end2 = _scale_pair(end)
    center = _center(solid)
    pivot_raw = params.get("pivot")
    pivot = _vector(pivot_raw, 3, node_id) if pivot_raw is not None else center
    other = [index for index in range(3) if index != axis_index]
    refined = solid.refine(max(2, min(6, int(params.get("subdivisions", 3)))))

    def warp(points):
        result = np.asarray(points, dtype=float).copy()
        t = np.clip((result[:, axis_index] - low) / length, 0.0, 1.0)
        lower_floor_fraction = max(
            0.0,
            min(0.8, float(params.get("lower_floor_fraction", 0.0))),
        )
        if lower_floor_fraction > 0.0:
            t = np.clip(
                (t - lower_floor_fraction) / (1.0 - lower_floor_fraction),
                0.0,
                1.0,
            )
        for pair_index, coordinate_index in enumerate(other):
            scale = start2[pair_index] + (end2[pair_index] - start2[pair_index]) * t
            result[:, coordinate_index] = pivot[coordinate_index] + (result[:, coordinate_index] - pivot[coordinate_index]) * scale
        return result

    return refined.warp_batch(warp)


def _warp_mid_profile(solid, params: dict[str, Any], node_id: str, *, mode: str):
    """Contract or swell the middle of one solid without changing topology."""
    axis = str(params.get("axis") or "x").lower()
    axis_index = {"x": 0, "y": 1, "z": 2}.get(axis)
    if axis_index is None:
        raise GeometryCompileError("invalid_axis", axis, node_id)
    bounds = _bounds(solid)
    low, high = bounds[axis_index], bounds[axis_index + 3]
    length = max(high - low, 1e-9)
    center = _center(solid)
    refined = solid.refine(max(2, min(6, int(params.get("subdivisions", 4)))))
    if mode == "pinch":
        middle_scale = max(0.28, min(0.92, float(params.get("waist_scale", params.get("waist_ratio", 0.62)))))
    else:
        middle_scale = max(1.04, min(1.45, float(params.get("middle_scale", params.get("factor", 1.18)))))
    power = max(1.0, min(4.0, float(params.get("profile_power", 2.0))))
    other = [index for index in range(3) if index != axis_index]

    def warp(points):
        result = np.asarray(points, dtype=float).copy()
        t = np.clip((result[:, axis_index] - low) / length, 0.0, 1.0)
        weight = np.sin(np.pi * t) ** power
        scale = 1.0 + (middle_scale - 1.0) * weight
        for coordinate_index in other:
            result[:, coordinate_index] = center[coordinate_index] + (
                result[:, coordinate_index] - center[coordinate_index]
            ) * scale
        return result

    return refined.warp_batch(warp)


def _warp_twist(solid, params: dict[str, Any], node_id: str):
    axis = str(params.get("axis") or "z").lower()
    axis_index = {"x": 0, "y": 1, "z": 2}.get(axis)
    if axis_index is None:
        raise GeometryCompileError("unsupported_twist_axis", axis, node_id)
    minx, miny, minz, maxx, maxy, maxz = _bounds(solid)
    lower = (minx, miny, minz)
    upper = (maxx, maxy, maxz)
    length = max(upper[axis_index] - lower[axis_index], 1e-9)
    transverse = tuple(index for index in range(3) if index != axis_index)
    pivot = params.get("pivot")
    center = (
        _vector(pivot, 3, node_id)
        if pivot is not None
        else tuple((lower[index] + upper[index]) / 2.0 for index in range(3))
    )
    angle = radians(float(params.get("angle_degrees", params.get("angle", 25.0))))
    refined = solid.refine(max(2, min(6, int(params.get("subdivisions", 3)))))

    def warp(points):
        result = np.asarray(points, dtype=float).copy()
        t = np.clip(
            (result[:, axis_index] - lower[axis_index]) / length,
            0.0,
            1.0,
        )
        theta = angle * t
        first, second = transverse
        u = result[:, first] - center[first]
        v = result[:, second] - center[second]
        result[:, first] = center[first] + u * np.cos(theta) - v * np.sin(theta)
        result[:, second] = center[second] + u * np.sin(theta) + v * np.cos(theta)
        return result

    return refined.warp_batch(warp)


def _warp_bend(solid, params: dict[str, Any], node_id: str):
    axis = str(params.get("axis") or "x").lower()
    angle = radians(float(params.get("angle_degrees", params.get("angle", 35.0))))
    if abs(angle) < 1e-5:
        return solid
    minx, miny, minz, maxx, maxy, maxz = _bounds(solid)
    refined = solid.refine(max(2, min(7, int(params.get("subdivisions", 4)))))
    center = _center(solid)

    def warp(points):
        result = np.asarray(points, dtype=float).copy()
        if axis == "x":
            length = max(maxx - minx, 1e-9)
            theta = angle * np.clip((result[:, 0] - minx) / length, 0.0, 1.0)
            radius = length / angle
            local = result[:, 1] - center[1]
            result[:, 0] = minx + radius * np.sin(theta) - local * np.sin(theta)
            result[:, 1] = center[1] + radius * (1.0 - np.cos(theta)) + local * np.cos(theta)
        elif axis == "y":
            length = max(maxy - miny, 1e-9)
            theta = angle * np.clip((result[:, 1] - miny) / length, 0.0, 1.0)
            radius = length / angle
            local = result[:, 0] - center[0]
            result[:, 1] = miny + radius * np.sin(theta) - local * np.sin(theta)
            result[:, 0] = center[0] + radius * (1.0 - np.cos(theta)) + local * np.cos(theta)
        elif axis == "z":
            length = max(maxz - minz, 1e-9)
            theta = angle * np.clip((result[:, 2] - minz) / length, 0.0, 1.0)
            radius = length / angle
            local = result[:, 0] - center[0]
            result[:, 2] = minz + radius * np.sin(theta) - local * np.sin(theta)
            result[:, 0] = center[0] + radius * (1.0 - np.cos(theta)) + local * np.cos(theta)
        else:
            raise GeometryCompileError("invalid_axis", axis, node_id)
        return result

    return refined.warp_batch(warp)


def _cut_corner(solid, params: dict[str, Any], node_id: str):
    minx, miny, _minz, maxx, maxy, _maxz = _bounds(solid)
    distance = max(1e-4, float(params.get("distance", min(maxx - minx, maxy - miny) * float(params.get("ratio", 0.2)))))
    corner = str(params.get("corner") or "ne").lower()
    normals = {"ne": (-1.0, -1.0, 0.0), "nw": (1.0, -1.0, 0.0), "se": (-1.0, 1.0, 0.0), "sw": (1.0, 1.0, 0.0)}
    normal = np.asarray(normals.get(corner), dtype=float) if corner in normals else None
    if normal is None:
        raise GeometryCompileError("invalid_corner", corner, node_id)
    normal /= np.linalg.norm(normal)
    point = {
        "ne": (maxx - distance, maxy - distance, 0.0),
        "nw": (minx + distance, maxy - distance, 0.0),
        "se": (maxx - distance, miny + distance, 0.0),
        "sw": (minx + distance, miny + distance, 0.0),
    }[corner]
    offset = float(np.dot(normal, np.asarray(point)))
    return solid.trim_by_plane(tuple(normal.tolist()), offset)


def _clip_fraction(solid, params: dict[str, Any], node_id: str):
    """Select a normalized occupied-solid fraction along its live bounds."""
    fraction = max(0.01, min(1.0, float(params.get("fraction", 1.0))))
    if fraction >= 1.0 - 1e-9:
        return solid
    minx, miny, minz, maxx, maxy, maxz = _bounds(solid)
    lengths = [maxx - minx, maxy - miny, maxz - minz]
    raw_axis = str(params.get("axis") or "long").lower()
    if raw_axis == "long":
        axis = 0 if lengths[0] >= lengths[1] else 1
    elif raw_axis == "short":
        axis = 1 if lengths[0] >= lengths[1] else 0
    else:
        axis = {"x": 0, "y": 1, "z": 2, "vertical": 2}.get(raw_axis, -1)
    if axis < 0 or lengths[axis] <= 1e-9:
        raise GeometryCompileError("invalid_scope_axis", raw_axis, node_id)
    anchor = str(params.get("anchor") or "end").lower()
    selected_length = lengths[axis] * fraction
    lower = [minx, miny, minz]
    upper = [maxx, maxy, maxz]
    if anchor in {"start", "low", "negative"}:
        upper[axis] = lower[axis] + selected_length
    elif anchor in {"center", "middle"}:
        center = (lower[axis] + upper[axis]) / 2.0
        lower[axis] = center - selected_length / 2.0
        upper[axis] = center + selected_length / 2.0
    else:
        lower[axis] = upper[axis] - selected_length
    epsilon = max(max(lengths), 1.0) * 1e-5
    for index in range(3):
        if index != axis:
            lower[index] -= epsilon
            upper[index] += epsilon
    size = tuple(max(1e-7, upper[index] - lower[index]) for index in range(3))
    cutter = m3d.Manifold.cube(size).translate(tuple(lower))
    return m3d.Manifold.batch_boolean([solid, cutter], m3d.OpType.Intersect)


def _book_base_volume(solid, params: dict[str, Any], node_id: str):
    """Select the exact connected normalized cell grammar from BOOK p.3."""

    label = str(params.get("label") or "")
    orientation = str(params.get("orientation") or "")
    try:
        cells = oriented_book_base_volume_cells(label, orientation)
    except KeyError as exc:
        raise GeometryCompileError("invalid_book_base_volume", str(exc), node_id) from exc
    minx, miny, minz, maxx, maxy, maxz = _bounds(solid)
    lower = (minx, miny, minz)
    lengths = (maxx - minx, maxy - miny, maxz - minz)
    if min(lengths) <= 1e-9:
        raise GeometryCompileError("invalid_book_base_host", label, node_id)
    cutters = []
    for cell in cells:
        cell_lower = tuple(
            lower[index] + lengths[index] * cell.minimum[index]
            for index in range(3)
        )
        size = tuple(
            lengths[index] * (cell.maximum[index] - cell.minimum[index])
            for index in range(3)
        )
        cutters.append(m3d.Manifold.cube(size).translate(cell_lower))
    cutter = cutters[0] if len(cutters) == 1 else m3d.Manifold.batch_boolean(cutters, m3d.OpType.Add)
    return m3d.Manifold.batch_boolean([solid, cutter], m3d.OpType.Intersect)


def _book_array_macro(base, params: dict[str, Any], node_id: str):
    """Repeat the body side by side - BOOK pp.50-58 array (a row) and pack (a grid).

    `related_array` is massv2's diminishing array: copies shrunk to 0.66-0.82,
    a cross stagger, a gap along the axis. The book repeats the same body at
    its own size: array is T_k = translate(k * span) along one axis, pack is
    the same on a grid, and copies meet face to face so the row is one body.
    Mathematically the union of a body under a translation group, nothing more.
    """

    mode = str(params.get("mode") or "array").lower()
    count = max(2, min(4, int(round(float(params.get("count", 3) or 3)))))
    axis = str(params.get("axis") or "x")
    # The pitch as a fraction of the body's extent: 1.0 is copies meeting
    # face to face (array), less is overlapping copies - BOOK p.12 offset is
    # the body and one copy displaced by a fraction of itself.
    pitch_ratio = max(0.15, min(1.0, float(params.get("pitch_ratio", 1.0) or 1.0)))
    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    span_x, span_y = maxx - minx, maxy - miny
    if min(span_x, span_y) <= 1e-9 or base.is_empty():
        raise GeometryCompileError("empty_book_array", "no body to repeat", node_id)
    copies = []
    if mode == "offset":
        # BOOK p.12: the body and one copy displaced diagonally by a fraction
        # of itself, so the union reads as two offset volumes in plan.
        for index in range(count):
            copies.append(base.translate((index * span_x * pitch_ratio, index * span_y * pitch_ratio, 0.0)))
    elif mode == "pack":
        # A grid: count along the axis, two across it. Packed means dense:
        # the pitch is 92% of the body's extent, so bodies that do not fill
        # their box (a bulge, a skew, a branch) still meet their neighbours
        # and the grid is one body; a box grid simply overlaps a little.
        across = 2
        pitch_x, pitch_y = span_x * 0.92, span_y * 0.92
        for index in range(count):
            for row in range(across):
                dx = index * pitch_x if axis == "x" else row * pitch_x
                dy = row * pitch_y if axis == "x" else index * pitch_y
                copies.append(base.translate((dx, dy, 0.0)))
    else:
        for index in range(count):
            copies.append(base.translate((index * span_x * pitch_ratio, 0.0, 0.0) if axis == "x"
                                         else (0.0, index * span_y * pitch_ratio, 0.0)))
    row = m3d.Manifold.batch_boolean(copies, m3d.OpType.Add)
    if row.is_empty():
        raise GeometryCompileError("empty_book_array", "array union is empty", node_id)
    # Back to the body's own centre so the pose search sees the same frame.
    rminx, rminy, _rz, rmaxx, rmaxy, _rzt = _bounds(row)
    return row.translate((((minx + maxx) - (rminx + rmaxx)) / 2.0, ((miny + maxy) - (rminy + rmaxy)) / 2.0, 0.0))


def _book_stack_macro(base, params: dict[str, Any], node_id: str):
    """Stack the body in levels, each level carried one step further - BOOK pp.53-55.

    `stack` was lowered to `stepped_mass`, a setback terrace of one body, and
    the word paired with it (rotate, shift) then acted once on the whole. The
    book's stack is the base volume repeated upward with the pairing applied
    per level: p.55 is a pile of boxes each turned a little more, and the
    same rule with a shift is a pile stepping sideways. Every level keeps its
    full plan; the pile's height is the body's height.
    """

    levels = max(2, min(5, int(round(float(params.get("levels", 3) or 3)))))
    mode = str(params.get("mode") or "none")
    axis = str(params.get("axis") or "x")
    step_degrees = float(params.get("step_degrees", 12.0) or 0.0)
    shift_ratio = float(params.get("shift_ratio", 0.15) or 0.0)
    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    height = maxz - minz
    if height <= 1e-9 or base.is_empty():
        raise GeometryCompileError("empty_book_stack", "no body to stack", node_id)
    centre_x, centre_y = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    extent = (maxx - minx) if axis == "x" else (maxy - miny)
    level_height = height / levels
    # One level: the body at its own plan, a level tall, its bottom at z = 0.
    unit = base.translate((0.0, 0.0, -minz)).scale((1.0, 1.0, 1.0 / levels))
    pieces = []
    for index in range(levels):
        piece = unit
        if index and mode == "rotate":
            piece = (piece.translate((-centre_x, -centre_y, 0.0))
                     .rotate((0.0, 0.0, step_degrees * index))
                     .translate((centre_x, centre_y, 0.0)))
        elif index and mode == "shift":
            offset = shift_ratio * extent * index
            piece = piece.translate((offset, 0.0, 0.0) if axis == "x" else (0.0, offset, 0.0))
        if index:
            # Levels meet face to face; the copies are of one flat-topped body
            # (the pairing is applied per level, never as a hinge before the
            # pile), so the union merges the shared plane exactly.
            piece = piece.translate((0.0, 0.0, minz + index * level_height))
        else:
            piece = piece.translate((0.0, 0.0, minz))
        pieces.append(piece)
    pile = m3d.Manifold.batch_boolean(pieces, m3d.OpType.Add)
    if pile.is_empty():
        raise GeometryCompileError("empty_book_stack", "stack union is empty", node_id)
    return pile


def _book_branch_macro(base, params: dict[str, Any], node_id: str):
    """Grow two arms from one end of the live trunk.

    A radial array rotates the complete body about its centre and therefore
    produces a bow-tie.  BOOK branch instead selects only the terminal part of
    the actual input solid, cuts the trunk at the shoulder, and rotates paired
    descendants about it, so the volume above the shoulder exists only as the
    two arms and the junction between them is a neck.  All dimensions come from live
    bounds, so the relation transfers across seeds and parcels.
    """

    anchor = _macro_vertical_anchor(params, node_id)
    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    span_x = max(maxx - minx, 1e-7)
    span_y = max(maxy - miny, 1e-7)
    span_z = max(maxz - minz, 1e-7)
    along_x = span_x >= span_y
    span = span_x if along_x else span_y
    branch_ratio = max(0.32, min(0.62, float(params.get("trunk_ratio", 0.42))))
    shoulder = (minx if along_x else miny) + span * branch_ratio
    overlap = max(span, span_z, 1.0) * 0.035
    if along_x:
        arm_source = base.trim_by_plane((1.0, 0.0, 0.0), shoulder - overlap)
        pivot = (shoulder, (miny + maxy) / 2.0, (minz + maxz) / 2.0)
    else:
        arm_source = base.trim_by_plane((0.0, 1.0, 0.0), shoulder - overlap)
        pivot = ((minx + maxx) / 2.0, shoulder, (minz + maxz) / 2.0)
    if arm_source.is_empty():
        raise GeometryCompileError("empty_book_branch_arm", "terminal input scope is empty", node_id)
    if anchor == "input_base":
        pivot = (pivot[0], pivot[1], minz)
    arm_ratio = max(0.10, min(0.90, float(params.get("arm_ratio", 0.28))))
    transverse_scale = 0.54 + arm_ratio * 0.38
    scale_vector = (
        (1.0, transverse_scale, 0.92)
        if along_x
        else (transverse_scale, 1.0, 0.92)
    )
    arm_source = _around_pivot(
        arm_source,
        pivot,
        lambda item: item.scale(scale_vector),
    )
    angle = max(18.0, min(52.0, abs(float(params.get("angle_degrees", 32.0)))))
    arms = [
        _around_pivot(
            arm_source,
            pivot,
            lambda item, signed=signed: item.rotate((0.0, 0.0, signed)),
        )
        for signed in (-angle, angle)
    ]
    # The trunk is cut at the shoulder before the arms are added. Keeping the
    # whole input and unioning arms beside it left the original terminal mass
    # sitting between them, so the result read as a fan: the arms were there but
    # nothing separated them and no neck existed to separate at. Measured across
    # the operatives, only `puncture` articulated at all; branch, notch, carve
    # and fracture produced no lobes.
    #
    # Cutting at the same shoulder the arms pivot about is what makes it a
    # branch - the volume above the shoulder exists only as the two rotated
    # arms, so the junction narrows and the space between them is void.
    trunk = (
        base.trim_by_plane((-1.0, 0.0, 0.0), -(shoulder + overlap))
        if along_x
        else base.trim_by_plane((0.0, -1.0, 0.0), -(shoulder + overlap))
    )
    if trunk.is_empty():
        raise GeometryCompileError(
            "empty_book_branch_trunk",
            "trunk scope below the shoulder is empty",
            node_id,
        )
    result = m3d.Manifold.batch_boolean([trunk, *arms], m3d.OpType.Add)
    if result.is_empty():
        raise GeometryCompileError("empty_book_branch", "branch union is empty", node_id)
    return result


def _book_terminal_split_macro(base, params: dict[str, Any], node_id: str):
    """Displace one terminal child while retaining a shared trunk (p.16).

    Split partitions the live terminal volume, keeps one child in place, and
    rotates the other around an overlapping shoulder. Repeating it recursively
    selects one half-width descendant, producing the three-prong relation on
    p.40. This is distinct from program-level ``split_wing``, which separates
    complete parallel wings and may require a separate service connector.
    """

    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    spans = [
        max(maxx - minx, 1e-7),
        max(maxy - miny, 1e-7),
        max(maxz - minz, 1e-7),
    ]
    axis_name = str(params.get("axis") or "x").lower()
    if axis_name not in {"x", "y"}:
        raise GeometryCompileError("invalid_axis", axis_name, node_id)
    axis = 0 if axis_name == "x" else 1
    transverse_axis = 1 - axis
    access_side = str(params.get("access_side") or "closed").lower()
    outward_sign = -1.0 if float(params.get("outward_sign", 1.0)) < 0.0 else 1.0
    if axis_name == "x" and access_side in {"east", "west"}:
        outward_sign = 1.0 if access_side == "east" else -1.0
    elif axis_name == "y" and access_side in {"north", "south"}:
        outward_sign = 1.0 if access_side == "north" else -1.0

    terminal_ratio = max(0.28, min(0.76, float(params.get("terminal_ratio", 0.58))))
    gap_ratio = max(0.06, min(0.42, float(params.get("gap_ratio", 0.18))))
    split_generation = max(0, min(6, int(params.get("split_generation", 0))))
    branch_sign = -1.0 if float(params.get("branch_sign", 1.0)) < 0.0 else 1.0
    angle = max(
        8.0,
        min(38.0, abs(float(params.get("angle_degrees", gap_ratio * 72.0)))),
    )
    epsilon = max(*spans, 1.0) * 1e-4
    lower = [minx - epsilon, miny - epsilon, minz - epsilon]
    upper = [maxx + epsilon, maxy + epsilon, maxz + epsilon]
    center = [
        (minx + maxx) / 2.0,
        (miny + maxy) / 2.0,
        (minz + maxz) / 2.0,
    ]
    shoulder = (
        upper[axis] - spans[axis] * terminal_ratio
        if outward_sign > 0.0
        else lower[axis] + spans[axis] * terminal_ratio
    )
    hinge_overlap = max(spans[axis], spans[2], 1.0) * 0.035

    def scoped_cube(bounds_low, bounds_high):
        size = tuple(
            max(epsilon, bounds_high[index] - bounds_low[index])
            for index in range(3)
        )
        return m3d.Manifold.cube(size).translate(tuple(bounds_low))

    # Clean recursive child prisms avoid re-cutting a previously rotated mesh
    # into triangular shards. Widths follow exact halves: 1/2, 1/4, 1/8...
    child_fraction = 1.0 / (2.0 ** (split_generation + 1))
    center_fraction = 0.5 - child_fraction / 2.0
    child_center = center[transverse_axis] + (
        branch_sign * spans[transverse_axis] * center_fraction
    )
    child_half = spans[transverse_axis] * child_fraction / 2.0
    child_lower = list(lower)
    child_upper = list(upper)
    child_lower[transverse_axis] = child_center - child_half
    child_upper[transverse_axis] = child_center + child_half
    if outward_sign > 0.0:
        child_lower[axis] = shoulder - hinge_overlap
    else:
        child_upper[axis] = shoulder + hinge_overlap
    moving_child = scoped_cube(child_lower, child_upper)

    pivot = list(center)
    pivot[axis] = shoulder
    pivot[transverse_axis] = child_center - branch_sign * child_half
    axis_orientation = 1.0 if axis_name == "x" else -1.0
    signed_angle = angle * outward_sign * branch_sign * axis_orientation

    displaced_child = _around_pivot(
        moving_child,
        tuple(pivot),
        lambda item: item.rotate((0.0, 0.0, signed_angle)),
    )

    if split_generation == 0:
        trunk_lower = list(lower)
        trunk_upper = list(upper)
        if outward_sign > 0.0:
            trunk_upper[axis] = shoulder + hinge_overlap
        else:
            trunk_lower[axis] = shoulder - hinge_overlap
        trunk = m3d.Manifold.batch_boolean(
            [base, scoped_cube(trunk_lower, trunk_upper)], m3d.OpType.Intersect
        )
        fixed_lower = list(child_lower)
        fixed_upper = list(child_upper)
        if branch_sign > 0.0:
            fixed_lower[transverse_axis] = lower[transverse_axis]
            fixed_upper[transverse_axis] = center[transverse_axis]
        else:
            fixed_lower[transverse_axis] = center[transverse_axis]
            fixed_upper[transverse_axis] = upper[transverse_axis]
        fixed_child = scoped_cube(fixed_lower, fixed_upper)
        result = m3d.Manifold.batch_boolean(
            [trunk, fixed_child, displaced_child], m3d.OpType.Add
        )
    else:
        # Repetition keeps the existing fork and grows one further descendant,
        # matching p.40 instead of replacing it with another two-way split.
        result = m3d.Manifold.batch_boolean(
            [base, displaced_child], m3d.OpType.Add
        )
    result_parts = list(result.decompose())
    if len(result_parts) != 1:
        # Rotated/intersected parents can leave only a zero-area pivot contact.
        # Materialize the thick common junction drawn on p.16/p.40 from the
        # nearest actual child faces, then run the same connectivity check.
        hinge_parameters = {
            "width_ratio": max(0.12, min(0.36, child_fraction * 0.72)),
            "height_ratio": 0.72,
        }
        shared_hinges = [
            _bridge_between(left, right, hinge_parameters, node_id)
            for left, right in _nearest_component_tree(result_parts)
        ]
        result = m3d.Manifold.batch_boolean(
            [*result_parts, *shared_hinges], m3d.OpType.Add
        )
    if result.is_empty():
        raise GeometryCompileError("empty_book_split", "terminal split removed the host", node_id)
    if len(result.decompose()) != 1:
        raise GeometryCompileError(
            "disconnected_book_split",
            "displaced child lost its shared terminal trunk",
            node_id,
        )
    return result


def _nearest_component_tree(parts: list[Any]) -> list[tuple[Any, Any]]:
    """Connect every related component once using a deterministic short tree."""

    if len(parts) < 2:
        return []
    connected = [0]
    remaining = set(range(1, len(parts)))
    pairs: list[tuple[Any, Any]] = []
    centers = [_center(part) for part in parts]
    while remaining:
        left_index, right_index = min(
            (
                (left, right)
                for left in connected
                for right in remaining
            ),
            key=lambda pair: (
                (centers[pair[0]][0] - centers[pair[1]][0]) ** 2
                + (centers[pair[0]][1] - centers[pair[1]][1]) ** 2,
                pair,
            ),
        )
        pairs.append((parts[left_index], parts[right_index]))
        connected.append(right_index)
        remaining.remove(right_index)
    return pairs


def _boundary_expand_macro(base, params: dict[str, Any], node_id: str):
    """Extend one terminal face while retaining the upstream body."""

    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    spans = [max(maxx - minx, 1e-7), max(maxy - miny, 1e-7), max(maxz - minz, 1e-7)]
    axis_name = str(params.get("axis") or "x").lower()
    axis = {"x": 0, "y": 1, "z": 2}.get(axis_name)
    if axis is None:
        raise GeometryCompileError("invalid_axis", axis_name, node_id)
    shoulder_fraction = max(0.24, min(0.58, float(params.get("shoulder_fraction", 0.38))))
    lower_bounds = (minx, miny, minz)
    shoulder = lower_bounds[axis] + spans[axis] * (1.0 - shoulder_fraction)
    normal = [0.0, 0.0, 0.0]
    normal[axis] = 1.0
    overlap = max(spans) * 1e-4
    terminal = base.trim_by_plane(tuple(normal), shoulder - overlap)
    if terminal.is_empty():
        raise GeometryCompileError("empty_boundary_expand_scope", "terminal input scope is empty", node_id)
    amount = max(0.12, min(0.90, abs(float(params.get("amount", 0.45)))))
    scale_vector = [1.0, 1.0, 1.0]
    if axis == 0:
        scale_vector[0] = 1.0 + 0.28 * amount
        scale_vector[1] = 1.0 + 0.72 * amount
    elif axis == 1:
        scale_vector[0] = 1.0 + 0.72 * amount
        scale_vector[1] = 1.0 + 0.28 * amount
    else:
        scale_vector[0] = 1.0 + 0.56 * amount
        scale_vector[1] = 1.0 + 0.56 * amount
        scale_vector[2] = 1.0 + 0.24 * amount
    pivot = [(minx + maxx) / 2.0, (miny + maxy) / 2.0, (minz + maxz) / 2.0]
    pivot[axis] = shoulder
    expanded = _around_pivot(
        terminal,
        tuple(pivot),
        lambda item: item.scale(tuple(scale_vector)),
    )
    result = m3d.Manifold.batch_boolean([base, expanded], m3d.OpType.Add)
    if result.is_empty():
        raise GeometryCompileError("empty_boundary_expand", "expanded boundary union is empty", node_id)
    return result


def _shift_related_macro(base, params: dict[str, Any], node_id: str):
    """Shift one of two plan-adjacent volumes along its live axis (p.24)."""

    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    span_x = max(maxx - minx, 1e-7)
    span_y = max(maxy - miny, 1e-7)
    span_z = max(maxz - minz, 1e-7)
    axis_name = str(params.get("axis") or "x").lower()
    if axis_name not in {"x", "y"}:
        raise GeometryCompileError("invalid_axis", axis_name, node_id)
    axis = 0 if axis_name == "x" else 1
    transverse_axis = 1 - axis
    lower_bounds = [minx, miny, minz]
    upper_bounds = [maxx, maxy, maxz]
    spans = [span_x, span_y, span_z]
    split_ratio = max(0.28, min(0.72, float(params.get("split_ratio", 0.50))))
    boundary = lower_bounds[transverse_axis] + spans[transverse_axis] * split_ratio
    overlap = spans[transverse_axis] * 0.025

    primary_size = list(spans)
    primary_size[transverse_axis] = (
        boundary - lower_bounds[transverse_axis] + overlap
    )
    primary = m3d.Manifold.cube(tuple(primary_size)).translate(tuple(lower_bounds))
    related_lower = list(lower_bounds)
    related_lower[transverse_axis] = boundary - overlap
    related_size = list(spans)
    related_size[transverse_axis] = (
        upper_bounds[transverse_axis] - boundary + overlap
    )
    related = m3d.Manifold.cube(tuple(related_size)).translate(tuple(related_lower))
    raw_distance = float(params.get("distance_ratio", 0.18))
    direction = -1.0 if float(params.get("outward_sign", 1.0)) < 0.0 else 1.0
    magnitude = max(
        _SHIFT_DISTANCE_BOUNDS[0],
        min(_SHIFT_DISTANCE_BOUNDS[1], abs(raw_distance)),
    )
    vector = [0.0, 0.0, 0.0]
    vector[axis] = direction * spans[axis] * magnitude
    shifted = related.translate(tuple(vector))
    result = m3d.Manifold.batch_boolean([primary, shifted], m3d.OpType.Add)
    if result.is_empty() or len(result.decompose()) != 1:
        raise GeometryCompileError(
            "disconnected_shift_related",
            "shifted plan child lost its shared edge overlap",
            node_id,
        )
    return result


def _offset_related_macro(base, params: dict[str, Any], node_id: str):
    """Offset a scaled related copy by a ratio of the live input span."""

    minx, miny, _minz, maxx, maxy, _maxz = _bounds(base)
    spans = (max(maxx - minx, 1e-7), max(maxy - miny, 1e-7))
    axis_name = str(params.get("axis") or "x").lower()
    if axis_name not in {"x", "y"}:
        raise GeometryCompileError("invalid_axis", axis_name, node_id)
    axis = 0 if axis_name == "x" else 1
    unit_scale = max(0.12, min(0.90, float(params.get("unit_scale", 0.42))))
    related = _around_pivot(
        base,
        _center(base),
        lambda item: item.scale((unit_scale, unit_scale, max(0.42, unit_scale))),
    )
    distance_ratio = max(-0.34, min(0.34, float(params.get("distance_ratio", 0.18))))
    # A smaller related unit translated only by the raw ratio can remain
    # completely buried inside its host.  Start at the host terminal face,
    # then expose a scale-aware portion while preserving a measured overlap.
    direction = -1.0 if float(params.get("outward_sign", 1.0)) < 0.0 else 1.0
    distance_unit = (distance_ratio + 0.34) / 0.68
    terminal_offset = (1.0 - unit_scale) / 2.0
    exposure = 0.04 + max(0.02, unit_scale - 0.08) * (0.25 + 0.65 * distance_unit)
    magnitude = terminal_offset + exposure
    vector = [0.0, 0.0, 0.0]
    vector[axis] = spans[axis] * direction * magnitude
    result = None
    # A prior carve can remove the nominal overlap zone. Pull the related
    # volume back along its measured live-span vector until the actual solids
    # intersect; do not hide the failure with an arbitrary connector.
    for pullback in (1.0, 0.85, 0.70, 0.55, 0.40, 0.25, 0.0):
        moved = related.translate(tuple(value * pullback for value in vector))
        candidate = m3d.Manifold.batch_boolean([base, moved], m3d.OpType.Add)
        if len(candidate.decompose()) == 1:
            result = candidate
            break
    if result is None:
        raise GeometryCompileError(
            "disconnected_offset_related",
            "offset relation could not retain live overlap",
            node_id,
        )
    if result.is_empty():
        raise GeometryCompileError("empty_offset_related", "offset relation is empty", node_id)
    return result


def _nested_related_macro(base, params: dict[str, Any], node_id: str):
    """Keep a related volume inside the host plan and reveal its roof datum."""

    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    spans = (
        max(maxx - minx, 1e-7),
        max(maxy - miny, 1e-7),
        max(maxz - minz, 1e-7),
    )
    axis_name = str(params.get("axis") or "x").lower()
    if axis_name not in {"x", "y"}:
        raise GeometryCompileError("invalid_axis", axis_name, node_id)
    axis = 0 if axis_name == "x" else 1
    unit_scale = max(0.12, min(0.80, float(params.get("unit_scale", 0.50))))
    # BOOK p.11 nest: the inner volume is read through the roof; at the old
    # 8-13% reveal it was a knob on a box, so the reveal is a fifth of the
    # host's height plus a fifth of the inner volume's own.
    height_scale = 0.62 + unit_scale * 0.24
    related = _around_pivot(
        base,
        _center(base),
        lambda item: item.scale((unit_scale, unit_scale, height_scale)),
    )
    distance_ratio = max(-0.34, min(0.34, float(params.get("distance_ratio", 0.0))))
    plan_shift = spans[axis] * (1.0 - unit_scale) * 0.42 * (distance_ratio / 0.34)
    roof_reveal = spans[2] * (0.20 + 0.20 * unit_scale)
    vertical_shift = spans[2] * (1.0 - height_scale) / 2.0 + roof_reveal
    vector = [0.0, 0.0, vertical_shift]
    vector[axis] = plan_shift
    related = related.translate(tuple(vector))
    result = m3d.Manifold.batch_boolean([base, related], m3d.OpType.Add)
    if result.is_empty() or len(result.decompose()) != 1:
        raise GeometryCompileError(
            "disconnected_nested_related", "nested core lost contact with its host", node_id
        )
    return result


def _overlap_related_macro(base, params: dict[str, Any], node_id: str):
    """Partially overlap two co-level orthogonal bars (BOOK p.22)."""

    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    spans = [
        max(maxx - minx, 1e-7),
        max(maxy - miny, 1e-7),
        max(maxz - minz, 1e-7),
    ]
    center = list(_center(base))
    axis_name = str(params.get("axis") or "x").lower()
    if axis_name not in {"x", "y"}:
        raise GeometryCompileError("invalid_axis", axis_name, node_id)
    axis = 0 if axis_name == "x" else 1
    transverse_axis = 1 - axis
    slab_ratio = max(0.36, min(0.78, float(params.get("slab_ratio", 0.56))))
    vertical_overlap = max(
        0.0, min(0.34, float(params.get("vertical_overlap", 0.18)))
    )
    shift_ratio = max(-0.34, min(0.34, float(params.get("shift_ratio", 0.0))))
    direction = -1.0 if float(params.get("outward_sign", 1.0)) < 0.0 else 1.0

    primary_size = [spans[0], spans[1], spans[2]]
    primary_size[transverse_axis] = spans[transverse_axis] * slab_ratio
    primary_lower = [minx, miny, minz]
    primary_lower[transverse_axis] = (
        center[transverse_axis] - primary_size[transverse_axis] / 2.0
    )
    primary = m3d.Manifold.cube(tuple(primary_size)).translate(tuple(primary_lower))
    related = _around_pivot(
        primary,
        tuple(center),
        lambda item: item.rotate((0.0, 0.0, 90.0)),
    )
    # Put the crossing near a terminal third rather than at the centre. The
    # overlap parameter controls engagement; shift moves it along that edge.
    engagement = slab_ratio * (0.30 + 0.45 * (vertical_overlap / 0.34))
    vector = [0.0, 0.0, 0.0]
    vector[axis] = direction * spans[axis] * (0.50 - engagement / 2.0)
    vector[transverse_axis] = spans[transverse_axis] * shift_ratio * 0.45
    related = related.translate(tuple(vector))
    result = m3d.Manifold.batch_boolean([primary, related], m3d.OpType.Add)
    if result.is_empty() or len(result.decompose()) != 1:
        raise GeometryCompileError(
            "disconnected_overlap_related",
            "orthogonal bars do not retain a terminal overlap",
            node_id,
        )
    return result


def _book_carve_macro(base, params: dict[str, Any], node_id: str):
    """Carve a bounded recess normal to one selected face (BOOK p.26).

    Width is measured on both transverse face spans and depth on the face
    normal.  Unlike ``notch``, the cutter is centred on the face and never
    reaches the opposite face, so CARVE remains a single recessed host.
    """

    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    lower = [minx, miny, minz]
    spans = [
        max(maxx - minx, 1e-7),
        max(maxy - miny, 1e-7),
        max(maxz - minz, 1e-7),
    ]
    center = [(minx + maxx) / 2.0, (miny + maxy) / 2.0, (minz + maxz) / 2.0]
    axis_name = str(params.get("axis") or "x").lower()
    axis = {"x": 0, "y": 1, "z": 2}.get(axis_name)
    if axis is None:
        raise GeometryCompileError("invalid_axis", axis_name, node_id)
    direction = -1.0 if float(params.get("outward_sign", 1.0)) < 0.0 else 1.0
    face_side = str(params.get("face_side") or "east").lower()
    if face_side not in {"east", "west", "north", "south"}:
        raise GeometryCompileError("invalid_face_side", face_side, node_id)
    width_ratio = max(0.18, min(0.62, float(params.get("width_ratio", 0.42))))
    depth_ratio = max(0.12, min(0.52, float(params.get("depth_ratio", 0.28))))
    cutter_size = [span * width_ratio for span in spans]
    cutter_size[axis] = spans[axis] * depth_ratio
    cutter_lower = [
        center[index] - cutter_size[index] / 2.0
        for index in range(3)
    ]
    transverse_axes = [index for index in range(3) if index != axis]
    local_axis = transverse_axes[0] if face_side in {"east", "west"} else transverse_axes[1]
    local_sign = 1.0 if face_side in {"east", "north"} else -1.0
    available_margin = (spans[local_axis] - cutter_size[local_axis]) / 2.0
    cutter_lower[local_axis] += local_sign * available_margin * 0.68
    epsilon = max(spans[axis] * 0.002, 1e-6)
    cutter_size[axis] += epsilon
    if direction > 0.0:
        cutter_lower[axis] = lower[axis] + spans[axis] - spans[axis] * depth_ratio
    else:
        cutter_lower[axis] = lower[axis] - epsilon
    cutter = m3d.Manifold.cube(tuple(cutter_size)).translate(tuple(cutter_lower))
    result = base - cutter
    if result.is_empty():
        raise GeometryCompileError("empty_book_carve", "face recess removed the host", node_id)
    if len(result.decompose()) != 1:
        raise GeometryCompileError(
            "disconnected_book_carve",
            "face recess split the selected host instead of carving it",
            node_id,
        )
    return result


def _book_fracture_macro(base, params: dict[str, Any], node_id: str):
    """Subtract a bent face fissure while retaining one connected host (p.28)."""

    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    lower = [minx, miny, minz]
    spans = [
        max(maxx - minx, 1e-7),
        max(maxy - miny, 1e-7),
        max(maxz - minz, 1e-7),
    ]
    center = [(minx + maxx) / 2.0, (miny + maxy) / 2.0, (minz + maxz) / 2.0]
    axis_name = str(params.get("axis") or "z").lower()
    axis = {"x": 0, "y": 1, "z": 2}.get(axis_name)
    if axis is None:
        raise GeometryCompileError("invalid_axis", axis_name, node_id)
    direction = -1.0 if float(params.get("outward_sign", 1.0)) < 0.0 else 1.0
    gap_ratio = max(0.04, min(0.14, float(params.get("gap_ratio", 0.08))))
    angle = max(12.0, min(55.0, abs(float(params.get("angle_degrees", 28.0)))))
    retained_back = max(
        0.20,
        min(0.48, float(params.get("retained_back_ratio", 0.32))),
    )
    transverse_axes = [index for index in range(3) if index != axis]
    u_axis, v_axis = transverse_axes
    channel_width = min(spans[u_axis], spans[v_axis]) * gap_ratio
    cut_depth = spans[axis] * (1.0 - retained_back)
    epsilon = max(spans[axis] * 0.002, 1e-6)

    def segment(length_ratio: float, start_ratio: float):
        size = [channel_width, channel_width, channel_width]
        size[axis] = cut_depth + epsilon
        size[u_axis] = spans[u_axis] * length_ratio
        segment_lower = [center[index] - size[index] / 2.0 for index in range(3)]
        segment_lower[u_axis] = center[u_axis] + spans[u_axis] * start_ratio
        if direction > 0.0:
            segment_lower[axis] = lower[axis] + spans[axis] - cut_depth
        else:
            segment_lower[axis] = lower[axis] - epsilon
        return m3d.Manifold.cube(tuple(size)).translate(tuple(segment_lower))

    first = segment(0.58, -0.52)
    second = segment(0.55, -0.03)
    euler = [0.0, 0.0, 0.0]
    euler[axis] = angle
    second = _around_pivot(
        second,
        tuple(center),
        lambda item: item.rotate(tuple(euler)),
    )
    cutter = m3d.Manifold.batch_boolean([first, second], m3d.OpType.Add)
    result = base - cutter
    if result.is_empty():
        raise GeometryCompileError("empty_book_fracture", "fissure removed the host", node_id)
    if len(result.decompose()) != 1:
        raise GeometryCompileError(
            "disconnected_book_fracture",
            "fissure became detached wings instead of one fractured host",
            node_id,
        )
    return result


def _book_grade_macro(base, params: dict[str, Any], node_id: str):
    """Subtract successive face bands to form the four-step p.29 grade."""

    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    lower = [minx, miny, minz]
    spans = [
        max(maxx - minx, 1e-7),
        max(maxy - miny, 1e-7),
        max(maxz - minz, 1e-7),
    ]
    center = [(minx + maxx) / 2.0, (miny + maxy) / 2.0, (minz + maxz) / 2.0]
    axis_name = str(params.get("axis") or "z").lower()
    axis = {"x": 0, "y": 1, "z": 2}.get(axis_name)
    if axis is None:
        raise GeometryCompileError("invalid_axis", axis_name, node_id)
    direction = -1.0 if float(params.get("outward_sign", 1.0)) < 0.0 else 1.0
    face_side = str(params.get("face_side") or "east").lower()
    if face_side not in {"east", "west", "north", "south"}:
        raise GeometryCompileError("invalid_face_side", face_side, node_id)
    levels = max(2, min(5, int(params.get("levels", 4))))
    width_ratio = max(0.38, min(0.90, float(params.get("width_ratio", 0.62))))
    depth_ratio = max(0.18, min(0.62, float(params.get("depth_ratio", 0.40))))
    u_axis, v_axis = [index for index in range(3) if index != axis]
    graded_span = spans[v_axis] * 0.82
    band_span = graded_span / levels
    opening_width = spans[u_axis] * width_ratio
    u_margin = (spans[u_axis] - opening_width) / 2.0
    u_shift = 0.0
    if face_side in {"east", "west"}:
        u_shift = (1.0 if face_side == "east" else -1.0) * u_margin * 0.68
    reverse = face_side in {"west", "south"}
    epsilon = max(spans[axis] * 0.002, 1e-6)
    cutters = []
    v_start = center[v_axis] - graded_span / 2.0
    for index in range(levels):
        progression = (levels - index) if reverse else (index + 1)
        cut_depth = spans[axis] * depth_ratio * progression / levels
        size = [opening_width, band_span + epsilon, opening_width]
        size[axis] = cut_depth + epsilon
        size[u_axis] = opening_width
        size[v_axis] = band_span + epsilon
        cutter_lower = [center[item] - size[item] / 2.0 for item in range(3)]
        cutter_lower[u_axis] += u_shift
        cutter_lower[v_axis] = v_start + index * band_span
        if direction > 0.0:
            cutter_lower[axis] = lower[axis] + spans[axis] - cut_depth
        else:
            cutter_lower[axis] = lower[axis] - epsilon
        cutters.append(
            m3d.Manifold.cube(tuple(size)).translate(tuple(cutter_lower))
        )
    cutter = m3d.Manifold.batch_boolean(cutters, m3d.OpType.Add)
    result = base - cutter
    if result.is_empty():
        raise GeometryCompileError("empty_book_grade", "grade removed the host", node_id)
    if len(result.decompose()) != 1:
        raise GeometryCompileError(
            "disconnected_book_grade",
            "grade separated the selected host instead of stepping one face",
            node_id,
        )
    return result


def _book_notch_macro(base, params: dict[str, Any], node_id: str):
    """Subtract the face-oriented triangular wedge drawn on BOOK p.30."""

    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    lower = [minx, miny, minz]
    spans = [
        max(maxx - minx, 1e-7),
        max(maxy - miny, 1e-7),
        max(maxz - minz, 1e-7),
    ]
    center = [(minx + maxx) / 2.0, (miny + maxy) / 2.0, (minz + maxz) / 2.0]
    axis_name = str(params.get("axis") or "z").lower()
    axis = {"x": 0, "y": 1, "z": 2}.get(axis_name)
    if axis is None:
        raise GeometryCompileError("invalid_axis", axis_name, node_id)
    direction = -1.0 if float(params.get("outward_sign", 1.0)) < 0.0 else 1.0
    corner = str(params.get("corner") or "ne").lower()
    if corner not in {"ne", "nw", "se", "sw"}:
        raise GeometryCompileError("invalid_corner", corner, node_id)
    ratio = max(0.12, min(0.42, float(params.get("ratio", 0.24))))
    u_axis, v_axis = [index for index in range(3) if index != axis]
    opening_u = spans[u_axis] * min(0.68, 0.30 + ratio * 0.82)
    opening_v = spans[v_axis] * min(0.68, 0.28 + ratio * 0.86)
    depth = spans[axis] * ratio
    u_margin = max(0.0, (spans[u_axis] - opening_u) / 2.0)
    v_margin = max(0.0, (spans[v_axis] - opening_v) / 2.0)
    u_sign = 1.0 if "e" in corner else -1.0
    v_sign = 1.0 if "n" in corner else -1.0
    u_center = center[u_axis] + u_sign * u_margin * 0.60
    v_center = center[v_axis] + v_sign * v_margin * 0.60
    face = lower[axis] + spans[axis] if direction > 0.0 else lower[axis]
    inward = face - direction * depth
    epsilon = max(spans[axis] * 0.002, 1e-6)
    face += direction * epsilon
    tip_v = v_center + v_sign * opening_v * 0.16
    points = []
    for u in (u_center - opening_u / 2.0, u_center + opening_u / 2.0):
        for normal, v in (
            (face, v_center - opening_v / 2.0),
            (face, v_center + opening_v / 2.0),
            (inward, tip_v),
        ):
            point = [0.0, 0.0, 0.0]
            point[axis] = normal
            point[u_axis] = u
            point[v_axis] = v
            points.append(tuple(point))
    cutter = m3d.Manifold.hull_points(points)
    result = base - cutter
    if result.is_empty():
        raise GeometryCompileError("empty_book_notch", "wedge removed the host", node_id)
    if len(result.decompose()) != 1:
        raise GeometryCompileError(
            "disconnected_book_notch",
            "wedge severed the selected host instead of notching one face",
            node_id,
        )
    return result


def _book_extract_macro(base, params: dict[str, Any], node_id: str):
    """Subtract the continuous guest-extraction path shown on BOOK p.35."""

    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    lower = [minx, miny, minz]
    spans = [
        max(maxx - minx, 1e-7),
        max(maxy - miny, 1e-7),
        max(maxz - minz, 1e-7),
    ]
    center = [(minx + maxx) / 2.0, (miny + maxy) / 2.0, (minz + maxz) / 2.0]
    axis_name = str(params.get("axis") or "z").lower()
    axis = {"x": 0, "y": 1, "z": 2}.get(axis_name)
    if axis is None:
        raise GeometryCompileError("invalid_axis", axis_name, node_id)
    direction = -1.0 if float(params.get("outward_sign", 1.0)) < 0.0 else 1.0
    face_side = str(params.get("face_side") or "east").lower()
    if face_side not in {"east", "west", "north", "south"}:
        raise GeometryCompileError("invalid_face_side", face_side, node_id)
    guest_scale = max(0.24, min(0.56, float(params.get("guest_scale", 0.38))))
    distance_ratio = max(0.18, min(0.34, float(params.get("distance_ratio", 0.24))))
    u_axis, v_axis = [index for index in range(3) if index != axis]
    size = [span * guest_scale for span in spans]
    size[axis] = spans[axis] * guest_scale * 0.75
    cutter_lower = [center[index] - size[index] / 2.0 for index in range(3)]
    u_margin = (spans[u_axis] - size[u_axis]) / 2.0
    v_margin = (spans[v_axis] - size[v_axis]) / 2.0
    if face_side == "east":
        cutter_lower[u_axis] += u_margin * 0.68
    elif face_side == "west":
        cutter_lower[u_axis] -= u_margin * 0.68
    elif face_side == "north":
        cutter_lower[v_axis] += v_margin * 0.68
    else:
        cutter_lower[v_axis] -= v_margin * 0.68
    travel = spans[axis] * distance_ratio
    face = lower[axis] + spans[axis] if direction > 0.0 else lower[axis]
    if direction > 0.0:
        cutter_lower[axis] = face - travel * 0.55 - size[axis]
    else:
        cutter_lower[axis] = face + travel * 0.55
    initial = m3d.Manifold.cube(tuple(size)).translate(tuple(cutter_lower))
    step_count = max(2, min(5, int(ceil(travel / max(size[axis] * 0.72, 1e-7))) + 1))
    cutters = [
        initial.translate(tuple(
            direction * travel * index / (step_count - 1) if coordinate == axis else 0.0
            for coordinate in range(3)
        ))
        for index in range(step_count)
    ]
    extraction_path = m3d.Manifold.batch_boolean(cutters, m3d.OpType.Add)
    result = base - extraction_path
    if result.is_empty():
        raise GeometryCompileError("empty_book_extract", "extraction path removed the host", node_id)
    if len(result.decompose()) != 1:
        raise GeometryCompileError(
            "disconnected_book_extract",
            "extraction path severed the host instead of opening one mouth",
            node_id,
        )
    return result


def _book_lift_related_macro(base, params: dict[str, Any], node_id: str):
    """Lift one smaller related volume from a larger host (BOOK p.20).

    This is intentionally separate from the program-level ``lift`` undercroft
    macro. BOOK Lift establishes a host/guest displacement first; a use- and
    access-specific threshold may be projected later as a terminal relation.
    """

    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    spans = (
        max(maxx - minx, 1e-7),
        max(maxy - miny, 1e-7),
        max(maxz - minz, 1e-7),
    )
    center = _center(base)
    axis_name = str(params.get("axis") or "x").lower()
    axis = {"x": 0, "y": 1, "z": 2}.get(axis_name)
    if axis is None:
        raise GeometryCompileError("invalid_axis", axis_name, node_id)
    direction = -1.0 if float(params.get("outward_sign", 1.0)) < 0.0 else 1.0
    guest_scale = max(0.30, min(0.84, float(params.get("guest_scale", 0.55))))
    distance_ratio = max(0.08, min(0.30, float(params.get("distance_ratio", 0.18))))
    height_scale = 0.68 + guest_scale * 0.24
    size = [spans[0] * guest_scale, spans[1] * guest_scale, spans[2] * height_scale]
    guest_lower = [
        center[index] - size[index] / 2.0
        for index in range(3)
    ]
    # Shift the smaller child beyond one host face while retaining a broad
    # volumetric engagement. Vertical orientation naturally places it above.
    guest_lower[axis] += direction * spans[axis] * (
        (1.0 - guest_scale) / 2.0 + distance_ratio
    )
    guest = m3d.Manifold.cube(tuple(size)).translate(tuple(guest_lower))
    result = m3d.Manifold.batch_boolean([base, guest], m3d.OpType.Add)
    if result.is_empty() or len(result.decompose()) != 1:
        raise GeometryCompileError(
            "disconnected_book_lift",
            "lifted guest does not retain a shared host overlap",
            node_id,
        )
    return result


def _book_lodge_macro(base, params: dict[str, Any], node_id: str):
    """Lodge one smaller guest between two related hosts (BOOK p.21)."""

    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    spans = [
        max(maxx - minx, 1e-7),
        max(maxy - miny, 1e-7),
        max(maxz - minz, 1e-7),
    ]
    center = list(_center(base))
    axis_name = str(params.get("axis") or "x").lower()
    if axis_name not in {"x", "y"}:
        raise GeometryCompileError("invalid_axis", axis_name, node_id)
    axis = 0 if axis_name == "x" else 1
    transverse_axis = 1 - axis
    guest_scale = max(0.22, min(0.70, float(params.get("guest_scale", 0.42))))
    distance_ratio = max(-0.34, min(0.34, float(params.get("distance_ratio", 0.0))))
    direction = -1.0 if float(params.get("outward_sign", 1.0)) < 0.0 else 1.0

    # Host A is the actual selected solid, so a local p.3 projection retains
    # its connection to the unselected remainder. Host B is the related outer
    # body; the smaller guest spans their intentional gap.
    related_axis_ratio = 0.82 + 0.08 * (1.0 - guest_scale)
    related_transverse_ratio = 0.88 + 0.08 * guest_scale
    related_height_ratio = 0.88 + 0.08 * guest_scale
    related_size = [
        spans[0] * related_transverse_ratio,
        spans[1] * related_transverse_ratio,
        spans[2] * related_height_ratio,
    ]
    related_size[axis] = spans[axis] * related_axis_ratio
    gap = spans[axis] * (0.08 + 0.18 * abs(distance_ratio))
    related_center = list(center)
    related_center[axis] += direction * (
        spans[axis] / 2.0 + gap + related_size[axis] / 2.0
    )
    related_lower = [
        related_center[index] - related_size[index] / 2.0
        for index in range(3)
    ]
    related_host = m3d.Manifold.cube(tuple(related_size)).translate(
        tuple(related_lower)
    )

    guest_size = [
        spans[0] * guest_scale,
        spans[1] * guest_scale,
        spans[2] * (0.55 + 0.35 * guest_scale),
    ]
    guest_size[axis] = gap + spans[axis] * 0.20
    guest_center = list(center)
    guest_center[axis] += direction * (spans[axis] / 2.0 + gap / 2.0)
    guest_center[transverse_axis] += (
        direction * distance_ratio * spans[transverse_axis] * 0.40
    )
    guest_lower = [
        guest_center[index] - guest_size[index] / 2.0
        for index in range(3)
    ]
    guest = m3d.Manifold.cube(tuple(guest_size)).translate(tuple(guest_lower))
    result = m3d.Manifold.batch_boolean(
        [base, related_host, guest], m3d.OpType.Add
    )
    if result.is_empty() or len(result.decompose()) != 1:
        raise GeometryCompileError(
            "disconnected_book_lodge",
            "lodged guest does not overlap both related hosts",
            node_id,
        )
    return result


def _book_rotate_macro(base, params: dict[str, Any], node_id: str):
    """Rotate one partitioned bar about the pair's shared edge (BOOK p.23)."""

    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    lower = [minx, miny, minz]
    upper = [maxx, maxy, maxz]
    spans = [
        max(maxx - minx, 1e-7),
        max(maxy - miny, 1e-7),
        max(maxz - minz, 1e-7),
    ]
    center = list(_center(base))
    axis_name = str(params.get("axis") or "x").lower()
    longitudinal_axis = {"x": 0, "y": 1, "z": 2}.get(axis_name)
    if longitudinal_axis is None:
        raise GeometryCompileError("invalid_axis", axis_name, node_id)
    transverse_axis = 1 if longitudinal_axis == 0 else 0
    rotation_axis = next(
        index for index in range(3)
        if index not in {longitudinal_axis, transverse_axis}
    )
    related_ratio = max(0.28, min(0.78, float(params.get("related_ratio", 0.50))))
    primary_ratio = 1.0 - related_ratio
    hinge_overlap = spans[transverse_axis] * 0.035

    primary_size = list(spans)
    primary_size[transverse_axis] = spans[transverse_axis] * primary_ratio + hinge_overlap
    primary_lower = list(lower)
    primary = m3d.Manifold.cube(tuple(primary_size)).translate(tuple(primary_lower))

    related_size = list(spans)
    related_size[transverse_axis] = spans[transverse_axis] * related_ratio + hinge_overlap
    related_lower = list(lower)
    boundary = lower[transverse_axis] + spans[transverse_axis] * primary_ratio
    related_lower[transverse_axis] = boundary - hinge_overlap
    related = m3d.Manifold.cube(tuple(related_size)).translate(tuple(related_lower))

    pivot = list(center)
    direction = -1.0 if float(params.get("outward_sign", 1.0)) < 0.0 else 1.0
    pivot[longitudinal_axis] = (
        upper[longitudinal_axis]
        if direction > 0.0
        else lower[longitudinal_axis]
    )
    pivot[transverse_axis] = boundary
    angle = max(-52.0, min(52.0, float(params.get("angle_degrees", 28.0))))

    def swung(turn: float):
        rotation = [0.0, 0.0, 0.0]
        rotation[rotation_axis] = turn
        return _around_pivot(
            related, tuple(pivot), lambda item: item.rotate(tuple(rotation)))

    # A hinge opens. It does not close into the bar it is hinged to.
    #
    # The sign was taken from `angle_degrees` alone, and which way that swings
    # depends on which end of the shared edge `outward_sign` put the pivot at -
    # two choices nothing reconciled. Half the time the related bar swept
    # diagonally across the primary and the union quietly absorbed the
    # collision: measured on a 20x12x8 host at +28 degrees, an intersection of
    # 82.4 m2 in plan, 658.9 m3 of the two bars delivered as one, a mass 27.3%
    # smaller than the host it was partitioned from. A rotation cannot lose
    # volume; a door swinging into its own frame can.
    #
    # So the angle's magnitude is the author's and its sign is the geometry's:
    # the swing that carries the related bar away from its partner is the one
    # taken. Where the two are symmetric the author's sign stands.
    away = swung(angle)
    into = swung(-angle)
    gap_away = _center(away)[transverse_axis] - _center(primary)[transverse_axis]
    gap_into = _center(into)[transverse_axis] - _center(primary)[transverse_axis]
    if abs(gap_into) > abs(gap_away) + 1e-9:
        away = into
    related = away
    result = m3d.Manifold.batch_boolean([primary, related], m3d.OpType.Add)
    if result.is_empty() or len(result.decompose()) != 1:
        raise GeometryCompileError(
            "disconnected_book_rotate",
            "rotated related bar lost its shared hinge edge",
            node_id,
        )
    return result


def _interlock_related_macro(base, params: dict[str, Any], node_id: str):
    """Engage two notched L volumes through one shared zone (BOOK p.18)."""

    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    spans = (
        max(maxx - minx, 1e-7),
        max(maxy - miny, 1e-7),
        max(maxz - minz, 1e-7),
    )
    axis_name = str(params.get("axis") or "x").lower()
    if axis_name not in {"x", "y"}:
        raise GeometryCompileError("invalid_axis", axis_name, node_id)
    axis = 0 if axis_name == "x" else 1
    bar_ratio = max(
        _INTERLOCK_BAR_BOUNDS[0],
        min(_INTERLOCK_BAR_BOUNDS[1], float(params.get("bar_ratio", 0.58))),
    )
    center = ((minx + maxx) / 2.0, (miny + maxy) / 2.0, (minz + maxz) / 2.0)
    # ``bar_ratio`` is the retained leg thickness. Removing the complementary
    # corner produces the L-shaped base volume shown in the source rather than
    # disguising a thin rotated tab as an interlock.
    direction = -1.0 if float(params.get("outward_sign", 1.0)) < 0.0 else 1.0
    cut_x = spans[0] * (1.0 - bar_ratio)
    cut_y = spans[1] * (1.0 - bar_ratio)
    cutter_lower = [
        maxx - cut_x if direction > 0.0 else minx,
        maxy - cut_y if direction > 0.0 else miny,
        minz - spans[2] * 1e-4,
    ]
    cutter = m3d.Manifold.cube((
        cut_x,
        cut_y,
        spans[2] * 1.0002,
    )).translate(tuple(cutter_lower))
    primary = base - cutter
    if primary.is_empty() or len(primary.decompose()) != 1:
        raise GeometryCompileError(
            "invalid_interlock_l_module", "corner subtraction did not retain one L module", node_id
        )
    related = primary
    angle = max(-52.0, min(52.0, float(params.get("angle_degrees", 28.0))))
    related = _around_pivot(related, center, lambda item: item.rotate((0.0, 0.0, angle)))
    distance_ratio = max(
        _INTERLOCK_DISTANCE_BOUNDS[0],
        min(_INTERLOCK_DISTANCE_BOUNDS[1], float(params.get("distance_ratio", 0.16))),
    )
    vector = [0.0, 0.0, 0.0]
    vector[axis] = spans[axis] * direction * distance_ratio
    transverse_axis = 1 - axis
    vector[transverse_axis] = spans[transverse_axis] * direction * distance_ratio
    related = related.translate(tuple(vector))
    result = m3d.Manifold.batch_boolean([primary, related], m3d.OpType.Add)
    if result.is_empty() or len(result.decompose()) != 1:
        raise GeometryCompileError(
            "disconnected_interlock_related",
            "paired L modules do not retain a shared interlock zone",
            node_id,
        )
    return result


def _intersect_related_macro(base, params: dict[str, Any], node_id: str):
    """Cross two volumes while preserving both bodies, as on BOOK p.19."""

    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    spans = (
        max(maxx - minx, 1e-7),
        max(maxy - miny, 1e-7),
        max(maxz - minz, 1e-7),
    )
    center = _center(base)
    axis_name = str(params.get("axis") or "x").lower()
    if axis_name not in {"x", "y"}:
        raise GeometryCompileError("invalid_axis", axis_name, node_id)
    axis = 0 if axis_name == "x" else 1
    transverse_axis = 1 - axis
    bar_ratio = max(0.18, min(0.52, float(params.get("bar_ratio", 0.32))))
    primary_size = [spans[0], spans[1], spans[2]]
    primary_size[transverse_axis] = spans[transverse_axis] * bar_ratio
    primary_lower = [minx, miny, minz]
    primary_lower[transverse_axis] = (
        center[transverse_axis] - primary_size[transverse_axis] / 2.0
    )
    primary = m3d.Manifold.cube(tuple(primary_size)).translate(tuple(primary_lower))
    unit_scale = max(0.86, min(1.0, float(params.get("unit_scale", 0.92))))
    related = _around_pivot(
        primary,
        center,
        lambda item: item.scale((unit_scale, unit_scale, 1.0)),
    )
    angle_deviation = max(
        -35.0, min(35.0, float(params.get("angle_degrees", 0.0)))
    )
    angle = 90.0 + angle_deviation
    related = _around_pivot(
        related,
        center,
        lambda item: item.rotate((0.0, 0.0, angle)),
    )
    result = m3d.Manifold.batch_boolean([primary, related], m3d.OpType.Add)
    if result.is_empty() or len(result.decompose()) != 1:
        raise GeometryCompileError(
            "disconnected_intersect_related", "crossing volumes do not intersect", node_id
        )
    return result


def _embed_void_macro(base, params: dict[str, Any], node_id: str):
    """Subtract the overlap of a guest entering one selected face (p.34)."""

    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    lower = [minx, miny, minz]
    spans = [
        max(maxx - minx, 1e-7),
        max(maxy - miny, 1e-7),
        max(maxz - minz, 1e-7),
    ]
    center = [(minx + maxx) / 2.0, (miny + maxy) / 2.0, (minz + maxz) / 2.0]
    axis_name = str(params.get("axis") or "z").lower()
    axis = {"x": 0, "y": 1, "z": 2}.get(axis_name)
    if axis is None:
        raise GeometryCompileError("invalid_axis", axis_name, node_id)
    direction = -1.0 if float(params.get("outward_sign", 1.0)) < 0.0 else 1.0
    scale = max(0.16, min(0.68, float(params.get("guest_scale", 0.34))))
    position = str(params.get("position") or "center").lower()
    if position not in {"center", "east", "west", "north", "south"}:
        raise GeometryCompileError("invalid_position", position, node_id)
    u_axis, v_axis = [index for index in range(3) if index != axis]
    size = [span * scale for span in spans]
    embedded_ratio = max(0.46, min(0.76, float(params.get("embedded_ratio", 0.60))))
    size[axis] = spans[axis] * embedded_ratio + spans[axis] * 0.08
    cutter_lower = [center[index] - size[index] / 2.0 for index in range(3)]
    u_margin = (spans[u_axis] - size[u_axis]) / 2.0
    v_margin = (spans[v_axis] - size[v_axis]) / 2.0
    if position == "east":
        cutter_lower[u_axis] += u_margin * 0.72
    elif position == "west":
        cutter_lower[u_axis] -= u_margin * 0.72
    elif position == "north":
        cutter_lower[v_axis] += v_margin * 0.72
    elif position == "south":
        cutter_lower[v_axis] -= v_margin * 0.72
    if direction > 0.0:
        cutter_lower[axis] = lower[axis] + spans[axis] * (1.0 - embedded_ratio)
    else:
        cutter_lower[axis] = lower[axis] - spans[axis] * 0.08
    cutter = m3d.Manifold.cube(tuple(size)).translate(tuple(cutter_lower))
    result = base - cutter
    if result.is_empty():
        raise GeometryCompileError("empty_embed_void", "embedded guest removed the complete host", node_id)
    if len(result.decompose()) != 1:
        raise GeometryCompileError(
            "disconnected_embed_void",
            "embedded guest severed the host instead of subtracting its overlap",
            node_id,
        )
    return result


def _related_array_macro(base, params: dict[str, Any], node_id: str):
    """Distribute scaled descendants instead of overlapping whole bodies."""

    anchor = _macro_vertical_anchor(params, node_id)
    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    spans = (max(maxx - minx, 1e-7), max(maxy - miny, 1e-7))
    center = _center(base)
    axis = str(params.get("axis") or "x").lower()
    if axis not in {"x", "y"}:
        raise GeometryCompileError("invalid_axis", axis, node_id)
    requested_axis_index = 0 if axis == "x" else 1
    long_index = 0 if spans[0] >= spans[1] else 1
    # Long seeds become parallel wings instead of a train of tiny bars.  For
    # near-square inputs the typed axis remains authoritative.
    axis_index = (
        1 - long_index
        if max(spans) / max(min(spans), 1e-7) >= 1.35
        else requested_axis_index
    )
    cross_index = 1 - axis_index
    mode = str(params.get("mode") or "array").lower()
    if mode not in {"array", "pack"}:
        raise GeometryCompileError("invalid_related_array_mode", mode, node_id)
    count = max(2, min(4, int(params.get("count", 3))))
    unit_scale = max(
        0.60,
        min(
            0.94 if mode == "pack" else 0.82,
            float(params.get("unit_scale", 0.66)),
        ),
    )
    scale_vector = [unit_scale, unit_scale, 0.88 + unit_scale * 0.12]
    unit = _around_pivot(
        base,
        (center[0], center[1], minz) if anchor == "input_base" else center,
        lambda item: item.scale(tuple(scale_vector)),
    )
    spacing = max(0.08, min(0.50, float(params.get("spacing_ratio", 0.18))))
    unit_span = spans[axis_index] * unit_scale
    step = (
        unit_span * (0.82 + spacing * 0.25)
        if mode == "pack"
        else unit_span * (1.0 + spacing * 0.50)
    )
    stagger = (
        spans[cross_index]
        * max(0.0, min(0.28, float(params.get("stagger_ratio", 0.08))))
        if mode == "pack"
        else 0.0
    )
    copies = []
    for index in range(count):
        offset = (index - (count - 1) / 2.0) * step
        cross_offset = ((index % 2) - 0.5) * stagger
        vector = [0.0, 0.0, 0.0]
        vector[axis_index] = offset
        vector[cross_index] = cross_offset
        copies.append(unit.translate(tuple(vector)))
    connectors = []
    if mode in {"array", "pack"}:
        connector_width = max(
            spans[cross_index] * (0.08 if mode == "pack" else 0.10),
            spans[axis_index] * (0.10 if mode == "pack" else 0.16),
        )
        connector_height = max(maxz - minz, 1e-7) * (
            0.68 if mode == "pack" else 0.94
        )
        for left, right in zip(copies, copies[1:]):
            # A bbox centre can sit in the void of a U/courtyard descendant.
            # Joining centre-to-centre therefore drew a beam through empty air
            # and left the nominal array as disconnected sculpture.  Reuse the
            # surface-aware connector so every repetition physically embeds in
            # both neighbouring solids.
            connector_builder = _input_base_array_connector if anchor == "input_base" else _bridge_between
            connectors.append(connector_builder(
                left,
                right,
                {"width": connector_width, "height": connector_height},
                node_id,
            ))
    result = m3d.Manifold.batch_boolean([*copies, *connectors], m3d.OpType.Add)
    if result.is_empty():
        raise GeometryCompileError("empty_related_array", "no related units survived", node_id)
    return result


def _stepped_macro(base, params: dict[str, Any], *, terrace: bool):
    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    levels = max(2, min(10, int(params.get("levels", 4))))
    level_height = (maxz - minz) / levels
    setback = max(0.0, min(0.32, float(params.get("setback_ratio", 0.08))))
    direction = str(params.get("direction") or "x").lower()
    shift_raw = params.get("shift_per_level", (0.0, 0.0, 0.0))
    shift = _vector(shift_raw, 3, "stepped_mass")
    # The author expresses step motion in normalized live-solid space.  The
    # old compiler accepted this typed parameter but ignored it, collapsing
    # many nominally different ASTs to the same centered cake-tier geometry.
    # Convert x/y to plan-span fractions and z to a level-height fraction.
    shift_world = (
        max(-0.24, min(0.24, shift[0])) * (maxx - minx),
        max(-0.24, min(0.24, shift[1])) * (maxy - miny),
        max(-0.35, min(0.35, shift[2])) * level_height,
    )
    solids = []
    center = _center(base)
    epsilon = max(
        max(maxz - minz, maxx - minx, maxy - miny, 1.0) * 1e-5,
        abs(shift_world[2]) * 0.55,
        # Aggregated/rotated modules need a real shared floor band between
        # adjacent stack levels. A near-zero kernel epsilon leaves each level
        # as a separate component even when the BOOK diagram is contiguous.
        level_height * 0.02,
    )
    for index in range(levels):
        ratio = max(0.18, 1.0 - setback * index)
        lower = minz + index * level_height
        upper = minz + (index + 1) * level_height
        # Recursive-language invariant: a modifier must transform the actual
        # input solid.  The old implementation rebuilt every level from its
        # bounding box, erasing upstream courtyards, bends and notches and
        # collapsing unrelated programs into the same cake/pyramid family.
        band = base.trim_by_plane((0.0, 0.0, 1.0), lower - epsilon)
        band = band.trim_by_plane((0.0, 0.0, -1.0), -(upper + epsilon))
        if band.is_empty():
            continue
        if terrace:
            scale_vector = (
                (1.0, ratio, 1.0)
                if direction == "x"
                else (ratio, 1.0, 1.0)
            )
        else:
            scale_vector = (ratio, ratio, 1.0)
        band = _around_pivot(
            band,
            center,
            lambda item, value=scale_vector: item.scale(value),
        )
        # Direction expresses a one-sided architectural section, while the
        # optional normalized shift field remains the agent's bounded extra
        # mutation.  This avoids turning every setback into a centred pyramid.
        direction_sign = -1.0 if float(params.get("direction_sign", 1.0)) < 0.0 else 1.0
        directional_shift = [0.0, 0.0, 0.0]
        if direction == "x":
            directional_shift[0] = direction_sign * (maxx - minx) * (1.0 - scale_vector[0]) * 0.5
        elif direction == "y":
            directional_shift[1] = direction_sign * (maxy - miny) * (1.0 - scale_vector[1]) * 0.5
        band = band.translate((
            directional_shift[0] + shift_world[0] * index,
            directional_shift[1] + shift_world[1] * index,
            shift_world[2] * index,
        ))
        solids.append(band)
    podium_scale = max(1.0, min(2.4, float(params.get("podium_scale", 1.0))))
    podium_height_ratio = max(0.0, min(0.45, float(params.get("podium_height_ratio", 0.0))))
    if podium_scale > 1.0 + 1e-9 and podium_height_ratio > 0.02:
        podium_top = minz + (maxz - minz) * podium_height_ratio
        podium = base.trim_by_plane((0.0, 0.0, -1.0), -(podium_top + epsilon))
        if not podium.is_empty():
            podium = _around_pivot(
                podium,
                center,
                lambda item: item.scale((podium_scale, podium_scale, 1.0)),
            )
            solids.append(podium)
    if not solids:
        raise GeometryCompileError("empty_stepped_mass", "no input solid bands survived", "stepped_mass")
    result = m3d.Manifold.batch_boolean(solids, m3d.OpType.Add)
    parts = list(result.decompose())
    if len(parts) > 1:
        volumes = [max(0.0, float(part.volume())) for part in parts]
        largest = max(volumes, default=0.0)
        substantive = [
            part for part, volume in zip(parts, volumes)
            if volume >= max(1e-12, largest * 0.02)
        ]
        # Plane trims through already-rotated/packed branches can leave tiny
        # clipped islands. They are not BOOK descendants and are exactly the
        # detached fragments the clean-mass gate is intended to eliminate.
        # Any second component at or above 2% remains substantive and is not
        # hidden by this cleanup.
        if substantive and len(substantive) < len(parts):
            result = m3d.Manifold.batch_boolean(substantive, m3d.OpType.Add)
    return result


def _profiled_hall_macro(base, params: dict[str, Any], node_id: str):
    """Compile a normalized roof/section graph over the live solid bounds.

    Controls are [transverse position, roof-height ratio] pairs.  Each adjacent
    pair becomes one watertight strip wedge extending along the span axis. The
    union therefore supports concave folded/sawtooth profiles that a single
    convex hull would erase.  No parcel coordinate or finished building is
    encoded in this operator.
    """
    minx, miny, minz, maxx, maxy, maxz = _bounds(base)
    controls = params.get("section_controls") or section_profile_controls(str(params.get("section_family") or ""))
    if not isinstance(controls, list) or not 2 <= len(controls) <= 12:
        raise GeometryCompileError("invalid_section_controls", "profiled_hall needs 2..12 normalized controls", node_id)
    normalized: list[tuple[float, float]] = []
    for raw in controls:
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            raise GeometryCompileError("invalid_section_control", "each control must be [u, height_ratio]", node_id)
        u = max(0.0, min(1.0, float(raw[0])))
        height_ratio = max(0.18, min(1.35, float(raw[1])))
        normalized.append((u, height_ratio))
    normalized.sort(key=lambda item: item[0])
    if normalized[0][0] > 1e-6 or normalized[-1][0] < 1.0 - 1e-6:
        raise GeometryCompileError("open_section_domain", "section controls must start at 0 and end at 1", node_id)
    if any(right[0] - left[0] <= 1e-5 for left, right in zip(normalized, normalized[1:])):
        raise GeometryCompileError("non_monotonic_section", "section control positions must strictly increase", node_id)
    span_axis = str(params.get("span_axis") or "x").lower()
    height = max(maxz - minz, 1e-7)
    strips = []
    for (u0, h0), (u1, h1) in zip(normalized, normalized[1:]):
        if span_axis == "y":
            x0, x1 = minx + (maxx - minx) * u0, minx + (maxx - minx) * u1
            points = [
                (x0, miny, minz), (x1, miny, minz), (x0, maxy, minz), (x1, maxy, minz),
                (x0, miny, minz + height * h0), (x1, miny, minz + height * h1),
                (x0, maxy, minz + height * h0), (x1, maxy, minz + height * h1),
            ]
        else:
            y0, y1 = miny + (maxy - miny) * u0, miny + (maxy - miny) * u1
            points = [
                (minx, y0, minz), (minx, y1, minz), (maxx, y0, minz), (maxx, y1, minz),
                (minx, y0, minz + height * h0), (minx, y1, minz + height * h1),
                (maxx, y0, minz + height * h0), (maxx, y1, minz + height * h1),
            ]
        strip = m3d.Manifold.hull_points(points)
        if strip.is_empty():
            raise GeometryCompileError("empty_section_strip", "profiled hall strip is empty", node_id)
        strips.append(strip)
    envelope = m3d.Manifold.batch_boolean(strips, m3d.OpType.Add)
    result = m3d.Manifold.batch_boolean([base, envelope], m3d.OpType.Intersect)
    if result.is_empty():
        raise GeometryCompileError("empty_profiled_hall", "section envelope does not intersect the input solid", node_id)
    return result


def _macro_vertical_anchor(params: dict[str, Any], node_id: str) -> str:
    anchor = params.get("vertical_anchor", "center")
    if anchor not in MACRO_VERTICAL_ANCHORS:
        raise GeometryCompileError("invalid_vertical_anchor",
            "vertical_anchor must be center or input_base", node_id)
    return anchor


def _input_base_array_connector(left, right, params: dict[str, Any], node_id: str):
    """Connect actual material without inventing a lower datum or ground pier.

    Bounds only limit the search interval. Positive-volume kernel intersections
    with both inputs and a single connected union prove the actual contact.
    Other bridge operators and legacy arrays do not use this opt-in contract.
    """
    lb, rb = _bounds(left), _bounds(right)
    lower, upper = max(lb[2], rb[2]), min(lb[5], rb[5])
    if upper <= lower:
        raise GeometryCompileError("array_connector_no_common_height",
            "input-base neighbours have no common occupied height interval", node_id)

    def clipped(solid, lo, hi):
        return solid.trim_by_plane((0.0, 0.0, 1.0), lo).trim_by_plane(
            (0.0, 0.0, -1.0), -hi)

    # A shared bbox interval can contain alternating, disjoint material bands.
    # Between actual mesh vertex heights, certify both neighbours have volume.
    heights = {lower, upper}
    for solid in (left, right):
        heights.update(float(row[2]) for row in solid.to_mesh64().vert_properties
            if lower < float(row[2]) < upper)
    heights = sorted(heights)
    common = []
    for lo, hi in zip(heights, heights[1:]):
        if clipped(left, lo, hi).volume() > 0.0 and clipped(right, lo, hi).volume() > 0.0:
            if common and common[-1][1] == lo:
                common[-1] = (common[-1][0], hi)
            else:
                common.append((lo, hi))
    if not common:
        raise GeometryCompileError("array_connector_no_common_material",
            "neighbour bounds overlap but occupied height intervals do not", node_id)
    lower, upper = max(common, key=lambda interval: (interval[1] - interval[0], -interval[0]))

    def in_interval(solid):
        return clipped(solid, lower, upper)

    left_slice, right_slice = in_interval(left), in_interval(right)
    if left_slice.is_empty() or right_slice.is_empty():
        raise GeometryCompileError("array_connector_no_common_material",
            "input-base neighbours have no material in the common interval", node_id)
    connector = in_interval(_bridge_between(left_slice, right_slice, params, node_id))
    if (connector.is_empty() or (connector ^ left).volume() <= 0.0
            or (connector ^ right).volume() <= 0.0
            or len((left + connector + right).decompose()) != 1):
        raise GeometryCompileError("array_connector_missing_material_contact",
            "input-base connector must embed in both actual neighbours", node_id)
    return connector


def _bridge_between(left, right, params: dict[str, Any], node_id: str):
    lc, rc = _nearest_surface_points(left, right)
    lb, rb = _bounds(left), _bounds(right)
    minimum_height = min(lb[5] - lb[2], rb[5] - rb[2])
    minimum_plan_span = min(
        lb[3] - lb[0], lb[4] - lb[1],
        rb[3] - rb[0], rb[4] - rb[1],
    )
    height = max(0.02, float(params.get(
        "height",
        minimum_height * float(params.get("height_ratio", 0.14)),
    )))
    width = max(0.02, float(params.get(
        "width",
        minimum_plan_span * float(params.get("width_ratio", 0.24)),
    )))
    delta = np.asarray(rc, dtype=float) - np.asarray(lc, dtype=float)
    distance = float(np.linalg.norm(delta))
    if distance <= 1e-8:
        return m3d.Manifold.cube((width, width, height), center=True).translate(lc)

    # Extend the connector past both measured surface points.  Merely ending
    # on a surface is a tangent contact and does not make one manifold; the
    # bounded embed creates a real shared volume at both ends.
    direction = delta / distance
    embed = max(0.01, min(distance * 0.18, max(width, height) * 0.55))
    start = np.asarray(lc, dtype=float) - direction * embed
    end = np.asarray(rc, dtype=float) + direction * embed
    half = np.asarray((width / 2.0, width / 2.0, height / 2.0), dtype=float)
    corners = np.asarray([
        (sx, sy, sz)
        for sx in (-1.0, 1.0)
        for sy in (-1.0, 1.0)
        for sz in (-1.0, 1.0)
    ])
    points = [tuple(point + corners[index] * half) for point in (start, end) for index in range(8)]
    connector = m3d.Manifold.hull_points(points)
    if connector.is_empty():
        raise GeometryCompileError("empty_bridge", "surface connector hull is empty", node_id)
    return connector


def _nearest_surface_points(left, right) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return deterministic 3D surface endpoints for a physical connector.

    Component bounding-box centres are not guaranteed to lie inside non-convex
    architectural solids. Mesh vertices are materialized kernel evidence, so
    the closest 3D pair gives the bridge an endpoint on each real component. A
    bounded deterministic sample keeps the repair cheap for dense meshes.
    """

    try:
        left_vertices = np.asarray(left.to_mesh64().vert_properties, dtype=float)[:, :3]
        right_vertices = np.asarray(right.to_mesh64().vert_properties, dtype=float)[:, :3]
    except (AttributeError, IndexError, TypeError, ValueError):
        return _center(left), _center(right)
    if not len(left_vertices) or not len(right_vertices):
        return _center(left), _center(right)

    def bounded(values: np.ndarray, maximum: int = 512) -> np.ndarray:
        if len(values) <= maximum:
            return values
        indices = np.linspace(0, len(values) - 1, maximum, dtype=np.int64)
        return values[indices]

    left_sample = bounded(left_vertices)
    right_sample = bounded(right_vertices)
    best_distance = float("inf")
    best_pair = (left_sample[0], right_sample[0])
    for left_point in left_sample:
        deltas = right_sample - left_point
        distances = np.einsum("ij,ij->i", deltas, deltas)
        right_index = int(np.argmin(distances))
        distance = float(distances[right_index])
        if distance < best_distance:
            best_distance = distance
            best_pair = (left_point, right_sample[right_index])
    return tuple(float(value) for value in best_pair[0]), tuple(float(value) for value in best_pair[1])


def _sweep_path(path: list[tuple[float, float, float]], *, width: float, height: float):
    solids = [
        _beam_between(start, end, width=width, height=height, node_id="sweep")
        for start, end in zip(path, path[1:])
        if hypot(end[0] - start[0], end[1] - start[1]) > 1e-7
    ]
    if not solids:
        raise GeometryCompileError("degenerate_sweep_path", "sweep path has no measurable segments")
    return m3d.Manifold.batch_boolean(solids, m3d.OpType.Add)


def _profile_sweep_3d(solid, params: dict[str, Any], node_id: str):
    path = _points(
        params.get("path"),
        dimensions=3,
        minimum=2,
        node_id=node_id,
    )
    points = [np.asarray(point, dtype=float) for point in path]
    if not all(np.isfinite(point).all() for point in points):
        raise GeometryCompileError(
            "invalid_profile_sweep_path",
            "profile_sweep_3d path points must contain finite coordinates",
            node_id,
        )
    segments = [
        end - start
        for start, end in zip(points, points[1:])
    ]
    lengths = [float(np.linalg.norm(segment)) for segment in segments]
    if any(length <= 1e-9 for length in lengths):
        raise GeometryCompileError(
            "zero_length_profile_sweep_path",
            "profile_sweep_3d path contains a zero-length segment",
            node_id,
        )
    if any(
        float(np.linalg.norm(right - left)) <= 1e-9
        for index, left in enumerate(points)
        for right in points[index + 1:]
    ):
        raise GeometryCompileError(
            "repeated_profile_sweep_point",
            "profile_sweep_3d path points must be unique",
            node_id,
        )

    segment_tangents = [
        segment / length
        for segment, length in zip(segments, lengths)
    ]
    point_tangents = [segment_tangents[0]]
    for previous, following in zip(segment_tangents, segment_tangents[1:]):
        blended = previous + following
        norm = float(np.linalg.norm(blended))
        point_tangents.append(
            following if norm <= 1e-9 else blended / norm
        )
    point_tangents.append(segment_tangents[-1])

    frames: list[tuple[np.ndarray, np.ndarray]] = []
    tangent = point_tangents[0]
    axes = (
        np.asarray((1.0, 0.0, 0.0), dtype=float),
        np.asarray((0.0, 1.0, 0.0), dtype=float),
        np.asarray((0.0, 0.0, 1.0), dtype=float),
    )
    reference = min(axes, key=lambda axis: abs(float(np.dot(axis, tangent))))
    frame_u = reference - float(np.dot(reference, tangent)) * tangent
    frame_u /= float(np.linalg.norm(frame_u))
    frame_v = np.cross(tangent, frame_u)
    frame_v /= float(np.linalg.norm(frame_v))
    frames.append((frame_u, frame_v))

    for tangent in point_tangents[1:]:
        transported = frame_u - float(np.dot(frame_u, tangent)) * tangent
        norm = float(np.linalg.norm(transported))
        if norm <= 1e-9:
            reference = min(
                axes,
                key=lambda axis: abs(float(np.dot(axis, tangent))),
            )
            transported = (
                reference
                - float(np.dot(reference, tangent)) * tangent
            )
            norm = float(np.linalg.norm(transported))
        frame_u = transported / norm
        if float(np.dot(frame_u, frames[-1][0])) < 0.0:
            frame_u = -frame_u
        frame_v = np.cross(tangent, frame_u)
        frame_v /= float(np.linalg.norm(frame_v))
        frames.append((frame_u, frame_v))

    minx, miny, minz, maxx, maxy, maxz = _bounds(solid)
    half_extents = np.asarray((
        (maxx - minx) / 2.0,
        (maxy - miny) / 2.0,
        (maxz - minz) / 2.0,
    ))
    if float(np.min(half_extents)) <= 1e-9:
        raise GeometryCompileError(
            "degenerate_profile_sweep_bounds",
            "profile_sweep_3d requires positive live input bounds",
            node_id,
        )
    profile_u = float(np.dot(np.abs(frames[0][0]), half_extents))
    profile_v = float(np.dot(np.abs(frames[0][1]), half_extents))

    sections: list[list[tuple[float, float, float]]] = []
    for point, (frame_u, frame_v) in zip(points, frames):
        sections.append([
            tuple(float(value) for value in (
                point + sign_u * profile_u * frame_u
                + sign_v * profile_v * frame_v
            ))
            for sign_u, sign_v in (
                (-1.0, -1.0),
                (1.0, -1.0),
                (1.0, 1.0),
                (-1.0, 1.0),
            )
        ])

    swept_segments = [
        m3d.Manifold.hull_points([*start, *end])
        for start, end in zip(sections, sections[1:])
    ]
    if not swept_segments or any(segment.is_empty() for segment in swept_segments):
        raise GeometryCompileError(
            "empty_profile_sweep_3d",
            "profile_sweep_3d produced a degenerate section hull",
            node_id,
        )
    result = swept_segments[0]
    for segment in swept_segments[1:]:
        result = m3d.Manifold.batch_boolean(
            [result, segment],
            m3d.OpType.Add,
        )
    if result.is_empty():
        raise GeometryCompileError(
            "empty_profile_sweep_3d",
            "profile_sweep_3d produced an empty solid",
            node_id,
        )
    if bool(params.get("require_connected", True)) and len(result.decompose()) != 1:
        raise GeometryCompileError(
            "disconnected_profile_sweep_3d",
            "profile_sweep_3d must produce one connected component",
            node_id,
        )
    return result


def _beam_between(start, end, *, width: float, height: float, node_id: str):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = hypot(dx, dy)
    if length <= 1e-7:
        raise GeometryCompileError("degenerate_bridge", "bridge endpoints coincide", node_id)
    angle = degrees(atan2(dy, dx))
    overlap = min(width * 0.35, length * 0.08)
    beam = m3d.Manifold.cube((length + overlap * 2, width, height), center=True)
    beam = beam.rotate((0.0, 0.0, angle))
    return beam.translate(((start[0] + end[0]) / 2, (start[1] + end[1]) / 2, min(start[2], end[2]) + height / 2))


def _loft_profiles(raw_profiles: Any, *, node_id: str):
    if not isinstance(raw_profiles, list) or len(raw_profiles) < 2:
        raise GeometryCompileError("missing_profile", "loft needs at least two profiles", node_id)
    profiles: list[tuple[float, list[tuple[float, float]]]] = []
    for index, raw in enumerate(raw_profiles):
        if isinstance(raw, dict):
            z = float(raw.get("z", index))
            points = _points(raw.get("points"), dimensions=2, minimum=3, node_id=node_id)
        else:
            z = float(index)
            points = _points(raw, dimensions=2, minimum=3, node_id=node_id)
        profiles.append((z, [(point[0], point[1]) for point in points]))
    profiles.sort(key=lambda item: item[0])
    solids = []
    for (z0, lower), (z1, upper) in zip(profiles, profiles[1:]):
        if z1 <= z0:
            raise GeometryCompileError("non_monotonic_loft", "loft profile z values must increase", node_id)
        points3 = [(x, y, z0) for x, y in lower] + [(x, y, z1) for x, y in upper]
        segment = m3d.Manifold.hull_points(points3)
        if segment.is_empty():
            raise GeometryCompileError("invalid_loft_segment", "loft profiles are degenerate", node_id)
        solids.append(segment)
    return m3d.Manifold.batch_boolean(solids, m3d.OpType.Add)


def _around_pivot(solid, pivot: tuple[float, float, float], operation: Callable[[Any], Any]):
    return operation(solid.translate(tuple(-value for value in pivot))).translate(pivot)


def _bounds(solid) -> tuple[float, float, float, float, float, float]:
    return tuple(float(value) for value in solid.bounding_box())


def _center(solid) -> tuple[float, float, float]:
    minx, miny, minz, maxx, maxy, maxz = _bounds(solid)
    return ((minx + maxx) / 2, (miny + maxy) / 2, (minz + maxz) / 2)


def _number(params: dict[str, Any], key: str, default: Any = None) -> float:
    value = params.get(key, default)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise GeometryCompileError("invalid_parameter_type", f"{key} must be numeric") from exc
    if result <= 0:
        raise GeometryCompileError("non_positive_dimension", f"{key} must be positive")
    return result


def _vector(value: Any, length: int, node_id: str) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise GeometryCompileError("invalid_vector", f"expected vector length {length}", node_id)
    try:
        return tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise GeometryCompileError("invalid_vector", "vector values must be numeric", node_id) from exc


def _points(value: Any, *, dimensions: int | None, minimum: int, node_id: str) -> list[tuple[float, ...]]:
    if not isinstance(value, list) or len(value) < minimum:
        raise GeometryCompileError("invalid_points", f"at least {minimum} points are required", node_id)
    result: list[tuple[float, ...]] = []
    for raw in value:
        if not isinstance(raw, (list, tuple)) or (dimensions is not None and len(raw) != dimensions) or len(raw) not in {2, 3}:
            raise GeometryCompileError("invalid_points", "point dimensions are invalid", node_id)
        result.append(tuple(float(item) for item in raw))
    return result


def _scale_pair(value: Any) -> tuple[float, float]:
    if isinstance(value, (int, float)):
        result = (float(value), float(value))
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        result = (float(value[0]), float(value[1]))
    else:
        raise GeometryCompileError("invalid_scale", "taper scale must be scalar or a two-vector")
    if min(result) <= 0.02 or max(result) > 4.0:
        raise GeometryCompileError("taper_scale_out_of_bounds", "taper scale must remain in 0.02..4")
    return result


def _mesh_hash(vertices: tuple[tuple[float, float, float], ...], triangles: tuple[tuple[int, int, int], ...]) -> str:
    canonical = []
    for face in triangles:
        points = sorted(tuple(round(value, 5) for value in vertices[index]) for index in face)
        canonical.append(points)
    canonical.sort()
    return hashlib.sha256(json.dumps(canonical, separators=(",", ":")).encode("utf-8")).hexdigest()


__all__ = [
    "CompilationResult",
    "GeometryCompileError",
    "compile_geometry_program",
    "revalidate_compilation_mesh",
]
