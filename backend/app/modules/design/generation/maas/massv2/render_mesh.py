"""Exact BOOK mesh transport shared by rendering, plans and sections.

SourceSurface XY is relative to SourceMass.footprint.centroid; Z is a fraction
of authored_height_m. Datum is the ground plane, not another vertex offset.
"""
from math import cos, isfinite, sin

import numpy as np
from PIL import Image
from shapely.geometry import Polygon


def is_mesh_authoritative(source):
    meta = source.metadata or {}
    bridge = meta.get('geometry_program_bridge_evidence') or {}
    return bool(meta.get('book_height_certificate') or
                bridge.get('authoritative_visual_geometry') == 'manifold_compilation_mesh' or
                bridge.get('surface_coordinate_frame') == 'source_footprint_centroid_local')


def physical_triangles(source):
    """Complete world XYZ triangles; refuse missing authority/frame/vertices."""
    bridge = (source.metadata or {}).get('geometry_program_bridge_evidence') or {}
    surfaces = tuple(source.surfaces or ())
    if (bridge.get('surface_coordinate_frame') != 'source_footprint_centroid_local'
            or not bridge.get('surface_export_complete')
            or not surfaces or bridge.get('raw_mesh_triangle_count') != len(surfaces)
            or bridge.get('exported_surface_count') != len(surfaces)):
        raise ValueError('complete authoritative mesh surface export required')
    height = float(source.metadata.get('authored_height_m') or 0)
    if not isfinite(height) or height <= 0:
        raise ValueError('authoritative mesh requires positive physical height')
    origin = source.footprint.centroid
    result = []
    for surface in surfaces:
        points = surface.vertices_m
        if len(points) != 3 or any(len(p) != 3 or not all(isfinite(float(n)) for n in p) for p in points):
            raise ValueError('finite XYZ mesh triangles required')
        result.append(tuple((float(x)+origin.x, float(y)+origin.y, float(z)*height) for x, y, z in points))
    return tuple(result)


def actual_xy_projection(source):
    # The legal owner already checks and measures the complete exported mesh.
    physical_triangles(source)
    from backend.app.modules.design.generation.maas.massv2.parcel_policy import _projection_for_gate
    return _projection_for_gate(source)[0]


def mesh_section_at(source, *, axis='z', coordinate=0.0):
    """Exact kernel section: XY for z, XZ for y, YZ for x, all metres."""
    from backend.app.modules.design.generation.maas.geometry_language.source_bridge import mesh_section_solid, solid_section_polygon
    triangles = physical_triangles(source)
    vertices = [p for triangle in triangles for p in triangle]
    if axis == 'y':
        vertices = [(x, z, -y) for x, y, z in vertices]
        coordinate = -coordinate
    elif axis == 'x':
        vertices = [(y, z, x) for x, y, z in vertices]
    elif axis != 'z':
        raise ValueError('mesh section axis must be x, y or z')
    faces = [(i, i+1, i+2) for i in range(0, len(vertices), 3)]
    result = solid_section_polygon(mesh_section_solid(vertices, faces), coordinate)
    return result if result is not None else Polygon()


def mesh_plan_at(source, z):
    return mesh_section_at(source, axis='z', coordinate=z)


def paint_mesh(panel, triangles, *, project, to_screen, yaw, pitch, palette, smooth_turn_cos):
    """Orthographic triangle rasterization with depth-tested fills and edges.

    No band reconstruction, convex hull, coordinate snapping or face dropping.
    Triangle interiors stay seamless; silhouettes and actual sharp folds show.
    """
    width, height = panel.size
    from backend.app.modules.design.generation.maas.geometry_language.export_mesh import EXPORT_DECIMAL_PLACES

    screen_origin = np.asarray(to_screen(project(0, 0, 0)), dtype=float)
    screen_axes = np.column_stack([
        np.asarray(to_screen(project(*axis)), dtype=float)-screen_origin
        for axis in np.eye(3)
    ])
    # Orthographic ray separation for one screen pixel, in world units.
    # This is a render visibility policy, not a surface-continuity certificate.
    world_per_pixel = np.linalg.pinv(screen_axes)
    mesh_low, mesh_high = np.full(3, np.inf), np.full(3, -np.inf)
    pixels = np.array(panel, dtype=np.uint8)
    depth = np.full((height, width), -np.inf)
    normals = np.zeros((height, width, 3))
    depth_gradient = np.zeros((height, width, 2))
    camera = np.array((sin(yaw)*cos(pitch), cos(yaw)*cos(pitch), sin(pitch)))
    light = np.array((-.25, -.35, 1.0)); light /= np.linalg.norm(light)
    for triangle in triangles:
        world = np.asarray(triangle, dtype=float)
        mesh_low = np.minimum(mesh_low, world.min(axis=0))
        mesh_high = np.maximum(mesh_high, world.max(axis=0))
        normal = np.cross(world[1]-world[0], world[2]-world[0])
        length = np.linalg.norm(normal)
        if length == 0:
            continue
        normal /= length
        projected = np.asarray([to_screen(project(*point)) for point in triangle])
        xs, ys = projected[:, 0], projected[:, 1]
        left, right = max(0, int(np.floor(xs.min()))), min(width-1, int(np.ceil(xs.max())))
        top, bottom = max(0, int(np.floor(ys.min()))), min(height-1, int(np.ceil(ys.max())))
        if right < left or bottom < top:
            continue
        denominator = (ys[1]-ys[2])*(xs[0]-xs[2]) + (xs[2]-xs[1])*(ys[0]-ys[2])
        if denominator == 0:
            continue
        xx, yy = np.meshgrid(np.arange(left, right+1)+.5, np.arange(top, bottom+1)+.5)
        a = ((ys[1]-ys[2])*(xx-xs[2]) + (xs[2]-xs[1])*(yy-ys[2])) / denominator
        b = ((ys[2]-ys[0])*(xx-xs[2]) + (xs[0]-xs[2])*(yy-ys[2])) / denominator
        c = 1-a-b
        z = world @ camera
        interpolated = a*z[0]+b*z[1]+c*z[2]
        target = depth[top:bottom+1, left:right+1]
        visible = (a >= 0) & (b >= 0) & (c >= 0) & (interpolated > target)
        target[visible] = interpolated[visible]
        normals[top:bottom+1, left:right+1][visible] = normal
        # Exact depth slope per screen pixel on this triangle's plane.
        gradient = np.array((
            ((ys[1]-ys[2])*(z[0]-z[2]) + (ys[2]-ys[0])*(z[1]-z[2])) / denominator,
            ((xs[2]-xs[1])*(z[0]-z[2]) + (xs[0]-xs[2])*(z[1]-z[2])) / denominator,
        ))
        depth_gradient[top:bottom+1, left:right+1][visible] = gradient
        base = np.asarray(palette.roof if normal[2] > .5 else palette.wall)
        shade = .88 + .12 * max(0, float(normal @ light))
        pixels[top:bottom+1, left:right+1][visible] = np.clip(base*shade, 0, 255).astype(np.uint8)
    occupied = np.isfinite(depth)
    edges = np.zeros_like(occupied)
    finite_depth = np.where(occupied, depth, 0.0)
    # Exported normalized coordinates carry this existing decimal precision;
    # transport its uncertainty at mesh scale rather than adding a metre cutoff.
    export_noise = (10.0**-EXPORT_DECIMAL_PLACES * float(np.max(mesh_high-mesh_low))
                    * float(np.abs(camera).sum())) if occupied.any() else 0.0
    for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        adjacent = np.roll(occupied, (dy, dx), axis=(0, 1))
        adjacent_normals = np.roll(normals, (dy, dx), axis=(0, 1))
        sharp = np.sum(normals*adjacent_normals, axis=2) < smooth_turn_cos
        # Subtract the endpoint planes' expected one-pixel depth increment.
        # Intervening facets need not stay within their gradient interval, so
        # only residuals resolved beyond a pixel's ray separation become edges.
        # Use finite substitutes outside the mesh to avoid inf-inf arithmetic.
        adjacent_depth = np.roll(finite_depth, (dy, dx), axis=(0, 1))
        increment = finite_depth - adjacent_depth
        slope = depth_gradient[:, :, 0]*dx + depth_gradient[:, :, 1]*dy
        adjacent_slope = np.roll(slope, (dy, dx), axis=(0, 1))
        # Roundoff allowance for interpolation/subtraction; scales with the
        # actual depth arithmetic, not a world-unit or visual distance cutoff.
        roundoff = 16*np.finfo(float).eps*(
            np.abs(finite_depth) + np.abs(adjacent_depth) + np.abs(slope) + np.abs(adjacent_slope))
        visibility = np.linalg.norm(world_per_pixel @ np.array((dx, dy))) + export_noise + roundoff
        discontinuous = ((increment < np.minimum(slope, adjacent_slope)-visibility) |
                         (increment > np.maximum(slope, adjacent_slope)+visibility))
        edges |= occupied & (~adjacent | sharp | (adjacent & discontinuous))
    pixels[edges] = palette.edge
    panel.paste(Image.fromarray(pixels))
