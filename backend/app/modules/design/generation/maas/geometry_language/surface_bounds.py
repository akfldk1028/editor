"""Adapt shared typed height surfaces to an intersection of a live BOOK solid.

Records use [0, 1] plan coordinates and height shares of the input's current
axis-aligned bounds. Later transforms carry the resulting mesh. Earlier
transforms define that live frame; no original/local frame is inferred.
The bounding box defines only the cutting envelope, never replacement mass.
"""
from __future__ import annotations

from math import isfinite

import numpy as np
from shapely.geometry import box

from backend.app.modules.design.generation.maas.source_geometry.ir import SourceVolume
from backend.app.modules.design.generation.maas.source_geometry.solid import AffineSurface, PolynomialSurface, CURVE_GRID_DIVISIONS, CURVE_MINIMUM_STEP_M, GEOMETRY_EPSILON, surface_bounds, surface_from_record, thickness_bounds


SURFACE_PARAMETERS = frozenset({"top_surface", "bottom_surface"})
# BOOK admission forbids ignored fields; this is not a second surface parser.
# Parsing, bounds, evaluation, folds and triangulation remain source-owned.
_RECORD_KEYS = {
    "constant": {"type", "height"},
    "polynomial": {"type", "terms"},
    "profile": {"type", "points", "axis", "span"},
    "affine": {"type", "surface", "world_to_authored", "scale", "offset"},
}


def _check_record_keys(record, depth=0):
    if not isinstance(record, dict) or depth > 8:
        raise ValueError("surface must be a bounded typed record")
    allowed = _RECORD_KEYS.get(record.get("type"))
    if allowed is None or set(record) - allowed:
        raise ValueError("unsupported surface type or record fields")
    if record.get("type") == "affine":
        _check_record_keys(record.get("surface"), depth + 1)


def parse_surface_bounds(parameters):
    """Use the source geometry owner's parser and conservative admission proof."""
    if not parameters or set(parameters) - SURFACE_PARAMETERS:
        raise ValueError("bound_surfaces requires top_surface and/or bottom_surface only")
    records = (
        parameters.get("top_surface", {"type": "constant", "height": 1}),
        parameters.get("bottom_surface", {"type": "constant", "height": 0}),
    )
    for record in records:
        _check_record_keys(record)
    top, bottom = (surface_from_record(record) for record in records)
    domain = (0.0, 0.0, 1.0, 1.0)
    for surface in (top, bottom):
        low, high = surface_bounds(surface, domain)
        if (not all(isfinite(v) for v in (low, high))
                or low < -GEOMETRY_EPSILON or high > 1 + GEOMETRY_EPSILON):
            raise ValueError("surface must be provably within the normalized height band [0, 1]")
    low, high = thickness_bounds(top, bottom, domain)
    if low < -GEOMETRY_EPSILON or high <= GEOMETRY_EPSILON:
        raise ValueError("top must be provably above bottom with nonzero occupied thickness")
    return top, bottom


def surface_sampling_issue(program, solids, trace):
    """Return a surface node whose downstream affine pose needs finer sampling.

Use the actual executed matrices per consumer path, composed before checking:
canceling scales and rigid poses must not change admission. Do not retessellate
after physical GFA sizing, which would silently change its measured authority.
"""
    rows = {row["node_id"]: row for row in trace}
    if not any(row["operator"] == "bound_surfaces" for row in trace):
        return None

    def nonlinear(surface):
        if isinstance(surface, AffineSurface):
            return nonlinear(surface.surface)
        return isinstance(surface, PolynomialSurface) and any(
            i + j > 1 and coefficient != 0 for i, j, coefficient in surface.terms
        )

    visited = set()
    pending = [(program.root_id, np.eye(4), "")]
    while pending:
        node_id, downstream, unsupported = pending.pop()
        key = (node_id, tuple(downstream.flat), unsupported)
        if key in visited:
            continue
        visited.add(key)
        node = program.node_map[node_id]
        if node.operator == "bound_surfaces" and any(
                nonlinear(surface) for surface in parse_surface_bounds(node.parameters)):
            if unsupported:
                return ("surface_sampling_unsupported_transform",
                    f"Apply {unsupported} before bound_surfaces; its downstream sampling transport is not proven.", node_id)
            x0, y0, _, x1, y1, _ = solids[node.inputs[0]].bounding_box()
            width, depth = x1 - x0, y1 - y0
            step = max(CURVE_MINIMUM_STEP_M, max(width, depth) / CURVE_GRID_DIVISIONS)
            sx, sy = (float(np.linalg.norm(downstream[:3, axis])) for axis in (0, 1))
            final_step = max(CURVE_MINIMUM_STEP_M,
                max(width * sx, depth * sy) / CURVE_GRID_DIVISIONS)
            if step * max(sx, sy) > final_step + GEOMETRY_EPSILON:
                return ("surface_sampling_requires_prior_sizing",
                    "Size the body before bound_surfaces; downstream enlargement requires finer shared "
                    "sampling and cannot preserve the already measured dimensional authority.", node_id)
        row = rows[node_id]
        if node.kind == "composition" and node.operator == "attach":
            from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import matrix4_for_transform

            resolution = row.get("host_relation_resolution")
            if resolution is None:
                pending.extend((input_id, downstream, "attach") for input_id in node.inputs)
                continue
            guest_bounds = solids[node.inputs[1]].bounding_box()
            span = [guest_bounds[i + 3] - guest_bounds[i] for i in range(3)]
            scales = [resolution["target_span"][i] / span[i] for i in range(3)]
            angles = [0.0, 0.0, 0.0]
            angles[resolution["normal_axis"]] = resolution["rotation_degrees"]
            rotation = np.asarray(matrix4_for_transform("rotate", {"angles": angles}))
            scale = np.asarray(matrix4_for_transform("scale", {"vector": scales}))
            pending.append((node.inputs[0], downstream, unsupported))
            pending.append((node.inputs[1], downstream @ rotation @ scale, unsupported))
            continue
        if node.kind == "modifier" and node.operator in {
                "bend", "taper", "twist", "pinch", "inflate", "profile_sweep_3d",
                "ellipsoidize", "circularize", "tetrahedralize"}:
            if "sampling_linear_matrix4" not in row:
                unsupported = unsupported or node.operator
        if node.kind == "pattern" and node.operator == "stack":
            unsupported = unsupported or node.operator
        # book_base_volume only intersects live material with normalized cell
        # cutters. Like other CSG selections, it transports surviving samples
        # unchanged; continue through it so later enlargement is still checked.
        # Matrix arrays create distinct consumer poses of the same live input.
        local_matrices = ([entry["matrix4"] for entry in row["matrix_entries"]]
                          if row.get("matrix_entries") else [row.get("sampling_linear_matrix4",
                              row.get("matrix4", np.eye(4)))])
        for matrix in local_matrices:
            composed = downstream @ np.asarray(matrix, dtype=float)
            pending.extend((input_id, composed, unsupported) for input_id in node.inputs)
    return None


def intersect_surface_bounds(solid, parameters):
    """Tessellate at live model scale, close the shared mesh and intersect input."""
    import manifold3d as m3d

    top, bottom = parse_surface_bounds(parameters)
    x0, y0, z0, x1, y1, z1 = map(float, solid.bounding_box())
    width, depth, height = x1 - x0, y1 - y0, z1 - z0
    if (not all(isfinite(v) for v in (x0, y0, z0, x1, y1, z1))
            or min(width, depth, height) <= GEOMETRY_EPSILON):
        raise ValueError("bound_surfaces requires finite nondegenerate live XYZ bounds")
    inverse = (1 / width, 0, 0, 1 / depth, -x0 / width, -y0 / depth)
    domain = box(x0, y0, x1, y1)
    envelope = SourceVolume(
        role="surface_bounds_envelope", footprint=domain, bottom_fraction=0,
        top_fraction=1, verb="bound_surfaces", authored_domain=domain,
        top_surface=AffineSurface(top, inverse),
        bottom_surface=AffineSurface(bottom, inverse),
    )
    vertices, faces, indices, edges = [], [], {}, {}

    def vertex_id(point):
        point = tuple(float(v) for v in point)
        if point not in indices:
            indices[point] = len(vertices)
            vertices.append(point)
        return indices[point]

    def face(indices):
        if len(set(indices)) == 3:
            faces.append(tuple(indices))

    for raw in envelope.surface_mesh:
        a, b, c = raw
        if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) < 0:
            raw = (a, c, b)
        lo = [vertex_id((x, y, z0 + height * bottom)) for x, y, bottom, top in raw]
        hi = [vertex_id((x, y, z0 + height * top)) for x, y, bottom, top in raw]
        face(hi)
        face(tuple(reversed(lo)))
        for j in range(3):
            k = (j + 1) % 3
            key = tuple(sorted((lo[j], lo[k])))
            edges.setdefault(key, []).append((lo[j], lo[k], hi[j], hi[k]))
    for incident in edges.values():
        if len(incident) == 1:
            a, b, at, bt = incident[0]
            face((a, b, bt))
            face((a, bt, at))
        elif len(incident) != 2:
            raise ValueError("shared surface envelope has a non-manifold plan edge")
    envelope_solid = m3d.Manifold(m3d.Mesh64(
        np.asarray(vertices, dtype=np.float64), np.asarray(faces, dtype=np.uint64),
    ))
    if envelope_solid.status() != m3d.Error.NoError or envelope_solid.is_empty():
        raise ValueError(f"shared surface envelope is not a closed occupied solid: {envelope_solid.status()}")
    return m3d.Manifold.batch_boolean([solid, envelope_solid], m3d.OpType.Intersect)
