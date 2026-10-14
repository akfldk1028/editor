"""Sectional loft meshes that retain authored concave boundaries."""

from __future__ import annotations

from typing import Any

import numpy as np
from shapely.geometry import Polygon


def sectional_loft(raw_profiles: Any, kernel):
    if not isinstance(raw_profiles, list) or len(raw_profiles) < 2:
        raise ValueError("loft needs at least two profiles")
    profiles = []
    for index, raw in enumerate(raw_profiles):
        if isinstance(raw, dict):
            if raw.get("holes"):
                raise ValueError("loft profiles with holes are not supported")
            z, points = float(raw.get("z", index)), raw.get("points")
        else:
            z, points = float(index), raw
        ring = np.asarray(points, dtype=float)
        if (not np.isfinite(z) or ring.ndim != 2 or ring.shape[1] != 2
                or len(ring) < 3 or not np.isfinite(ring).all()):
            raise ValueError("loft profiles require finite z and at least three finite 2D points")
        if np.array_equal(ring[0], ring[-1]):
            ring = ring[:-1]
        if len(ring) < 3 or len(np.unique(ring, axis=0)) != len(ring):
            raise ValueError("loft profile vertices must be distinct")
        polygon = Polygon(ring)
        if not polygon.is_valid or polygon.area <= 0:
            raise ValueError("loft profile must be a simple positive-area polygon")
        if not polygon.exterior.is_ccw:
            # Keep the authored seam vertex when correcting cap orientation.
            ring = np.concatenate((ring[:1], ring[:0:-1]))
        profiles.append((z, ring))
    profiles.sort(key=lambda item: item[0])
    if any(upper[0] <= lower[0] for lower, upper in zip(profiles, profiles[1:])):
        raise ValueError("loft profile z values must strictly increase")

    rings = [ring for _, ring in profiles]
    if len({len(ring) for ring in rings}) != 1:
        rings = _match_perimeters(rings)
    count = len(rings[0])
    vertices = np.concatenate([
        np.column_stack((ring, np.full(count, z)))
        for (z, _), ring in zip(profiles, rings)
    ])
    faces = []
    for triangle in kernel.triangulate([rings[0]]):
        faces.append(tuple(int(value) for value in triangle[::-1]))
    offset = (len(rings) - 1) * count
    for triangle in kernel.triangulate([rings[-1]]):
        faces.append(tuple(offset + int(value) for value in triangle))
    for level, (lower, upper) in enumerate(zip(rings, rings[1:])):
        _validate_sides(lower, upper)
        low, high = level * count, (level + 1) * count
        for index in range(count):
            following = (index + 1) % count
            faces.extend(((low + index, low + following, high + following),
                          (low + index, high + following, high + index)))
    solid = kernel.Manifold(kernel.Mesh64(
        np.asarray(vertices, dtype=np.float64), np.asarray(faces, dtype=np.uint64)))
    if "NoError" not in str(solid.status()) or solid.is_empty() or solid.volume() <= 0:
        raise ValueError("loft mesh did not form an oriented positive-volume manifold")
    return solid


def _match_perimeters(rings: list[np.ndarray]) -> list[np.ndarray]:
    parameters = []
    for ring in rings:
        lengths = np.linalg.norm(np.roll(ring, -1, axis=0) - ring, axis=1)
        parameters.append(np.concatenate(([0.0], np.cumsum(lengths))) / lengths.sum())
    # Union the breakpoints so resampling cannot cut across an authored corner.
    shared = np.unique(np.concatenate([values[:-1] for values in parameters]))
    return [np.column_stack([
        np.interp(shared, values, np.concatenate((ring[:, axis], ring[:1, axis])))
        for axis in range(2)
    ]) for ring, values in zip(rings, parameters)]


def _validate_sides(lower: np.ndarray, upper: np.ndarray) -> None:
    # A horizontal slice of each triangulated quad contains its diagonal as
    # well as its vertical edges. Their moving 2D vertices are affine in t.
    start = np.repeat(lower, 2, axis=0)
    end = np.empty_like(start)
    end[::2], end[1::2] = upper, np.roll(upper, -1, axis=0)
    velocity = end - start
    events = {0.0, 1.0}
    size = len(start)

    def cross(a, b):
        return float(a[0] * b[1] - a[1] * b[0])

    def add_collinear_times(a, b, c):
        ab, ac = start[b] - start[a], start[c] - start[a]
        dab, dac = velocity[b] - velocity[a], velocity[c] - velocity[a]
        coefficients = (cross(dab, dac), cross(dab, ac) + cross(ab, dac), cross(ab, ac))
        for root in np.roots(np.trim_zeros(coefficients, "f")):
            if np.isreal(root) and 0 < float(root.real) < 1:
                events.add(float(root.real))

    for first in range(size):
        next_first = (first + 1) % size
        for second in range(first + 1, size):
            next_second = (second + 1) % size
            if next_first == second or next_second == first:
                continue
            add_collinear_times(first, next_first, second)
            add_collinear_times(first, next_first, next_second)
            add_collinear_times(second, next_second, first)
            add_collinear_times(second, next_second, next_first)
    ordered = sorted(events)
    probes = [value for value in ordered if 0 < value < 1]
    probes.extend(midpoint for left, right in zip(ordered, ordered[1:])
                  if left < (midpoint := left + (right - left) / 2) < right)
    for value in probes:
        polygon = Polygon((1.0 - value) * start + value * end)
        if not polygon.is_valid or polygon.area <= 0:
            raise ValueError("loft vertex correspondence creates crossing or collapsed sides")
