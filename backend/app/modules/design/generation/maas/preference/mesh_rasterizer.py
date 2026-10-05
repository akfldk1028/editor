"""Small deterministic z-buffer rasterizer for recursive MASS preview meshes.

The preference renderer intentionally has no OpenGL dependency.  A painter's
algorithm is sufficient for ordinary extruded polygons, but it cannot order
thousands of mutually overlapping triangles from a concave recursive solid.
This module provides the missing per-pixel depth test without taking geometry
or camera authority away from the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor
from typing import Iterable

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class RasterTriangle:
    points: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]
    depths: tuple[float, float, float]
    color: tuple[int, int, int, int]


def rasterize_depth_tested_triangles(
    image: Image.Image,
    triangles: Iterable[RasterTriangle],
    *,
    clip_box: tuple[int, int, int, int],
) -> int:
    """Rasterize triangles into ``image`` and return the covered pixel count.

    Larger depth values are nearer, matching the existing fixed orthographic
    MASS camera.  Pixel-centre barycentric interpolation supplies a true depth
    test, so rear tessellation cannot leak through a concave front surface.
    """

    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    height, width = rgba.shape[:2]
    clip_left = max(0, min(width, int(clip_box[0])))
    clip_top = max(0, min(height, int(clip_box[1])))
    clip_right = max(clip_left, min(width, int(clip_box[2])))
    clip_bottom = max(clip_top, min(height, int(clip_box[3])))
    depth_buffer = np.full((height, width), -np.inf, dtype=np.float64)
    covered = np.zeros((height, width), dtype=bool)

    for triangle in triangles:
        points = np.asarray(triangle.points, dtype=np.float64)
        depths = np.asarray(triangle.depths, dtype=np.float64)
        if points.shape != (3, 2) or depths.shape != (3,):
            continue
        x0, y0 = points[0]
        x1, y1 = points[1]
        x2, y2 = points[2]
        denominator = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(float(denominator)) <= 1e-10:
            continue
        left = max(clip_left, int(floor(float(points[:, 0].min()))))
        right = min(clip_right - 1, int(ceil(float(points[:, 0].max()))))
        top = max(clip_top, int(floor(float(points[:, 1].min()))))
        bottom = min(clip_bottom - 1, int(ceil(float(points[:, 1].max()))))
        if right < left or bottom < top:
            continue

        xs = np.arange(left, right + 1, dtype=np.float64) + 0.5
        ys = np.arange(top, bottom + 1, dtype=np.float64) + 0.5
        grid_x, grid_y = np.meshgrid(xs, ys)
        weight0 = (
            (y1 - y2) * (grid_x - x2) + (x2 - x1) * (grid_y - y2)
        ) / denominator
        weight1 = (
            (y2 - y0) * (grid_x - x2) + (x0 - x2) * (grid_y - y2)
        ) / denominator
        weight2 = 1.0 - weight0 - weight1
        inside = (
            (weight0 >= -1e-9)
            & (weight1 >= -1e-9)
            & (weight2 >= -1e-9)
        )
        if not bool(np.any(inside)):
            continue
        interpolated = weight0 * depths[0] + weight1 * depths[1] + weight2 * depths[2]
        local_depth = depth_buffer[top : bottom + 1, left : right + 1]
        visible = inside & (interpolated > local_depth)
        if not bool(np.any(visible)):
            continue
        local_depth[visible] = interpolated[visible]
        local_pixels = rgba[top : bottom + 1, left : right + 1]
        source = np.asarray(triangle.color, dtype=np.float64)
        alpha = max(0.0, min(1.0, float(source[3]) / 255.0))
        if alpha >= 1.0:
            local_pixels[visible] = source.astype(np.uint8)
        else:
            destination = local_pixels[visible].astype(np.float64)
            blended = source * alpha + destination * (1.0 - alpha)
            blended[:, 3] = 255.0
            local_pixels[visible] = np.clip(blended, 0.0, 255.0).astype(np.uint8)
        covered[top : bottom + 1, left : right + 1][visible] = True

    image.paste(Image.fromarray(rgba, mode="RGBA").convert(image.mode))
    return int(covered.sum())


__all__ = ["RasterTriangle", "rasterize_depth_tested_triangles"]
