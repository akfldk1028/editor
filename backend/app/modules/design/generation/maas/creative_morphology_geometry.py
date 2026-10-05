"""Deterministic scale-invariant mesh feature extraction."""

from __future__ import annotations

from math import atan2, floor, isfinite, pi, sqrt
from typing import Iterable, Sequence

from scipy.spatial import ConvexHull, QhullError


_EPSILON = 1e-12


def extract_morphology_features(
    *,
    vertices: Sequence[Sequence[float]],
    triangles: Sequence[Sequence[int]],
    floor_areas: Sequence[float],
) -> dict[str, tuple[float, ...] | float]:
    points = _validated_vertices(vertices)
    faces = _validated_triangles(triangles, len(points))
    if not points or not faces:
        raise ValueError("morphology descriptor requires a non-empty mesh")
    normalized = _normalize_vertices(points)
    spans = tuple(
        max(point[axis] for point in normalized)
        - min(point[axis] for point in normalized)
        for axis in range(3)
    )
    evidence = _triangle_evidence(normalized, faces)
    mesh_volume = _mesh_volume(normalized, faces)
    hull_volume = _convex_hull_volume(normalized)
    box_volume = spans[0] * spans[1] * spans[2]
    convexity = mesh_volume / hull_volume if hull_volume > _EPSILON else 0.0
    void_fraction = (
        1.0 - mesh_volume / box_volume if box_volume > _EPSILON else 1.0
    )
    return {
        "axis_ratios": _rounded_tuple(spans),
        "z_slice_occupancies": _histogram(
            (
                (centroid[2] + 0.5, area)
                for centroid, area, _normal in evidence
            ),
            bins=8,
        ),
        "floor_area_profile": _resample_profile(floor_areas, length=8),
        "convexity": _rounded_unit(convexity),
        "void_fraction": _rounded_unit(void_fraction),
        "normal_bins": _normal_histogram(evidence),
        "radial_bins": _radial_histogram(evidence),
        "silhouette_front": _silhouette(normalized, faces, "front"),
        "silhouette_side": _silhouette(normalized, faces, "side"),
        "silhouette_isometric": _silhouette(
            normalized, faces, "isometric"
        ),
    }


def _validated_vertices(
    values: Sequence[Sequence[float]],
) -> tuple[tuple[float, float, float], ...]:
    points: list[tuple[float, float, float]] = []
    for raw in values:
        if len(raw) != 3:
            raise ValueError("mesh vertices must be XYZ triples")
        point = tuple(float(coordinate) for coordinate in raw)
        if not all(isfinite(coordinate) for coordinate in point):
            raise ValueError("mesh vertices must be finite")
        points.append(point)
    return tuple(points)


def _validated_triangles(
    values: Sequence[Sequence[int]],
    vertex_count: int,
) -> tuple[tuple[int, int, int], ...]:
    faces: list[tuple[int, int, int]] = []
    for raw in values:
        if len(raw) != 3:
            raise ValueError("mesh triangles must have three indices")
        face = tuple(int(index) for index in raw)
        if len(set(face)) != 3 or any(
            index < 0 or index >= vertex_count for index in face
        ):
            raise ValueError("mesh triangle indices are invalid")
        faces.append(face)
    return tuple(faces)


def _normalize_vertices(
    points: Sequence[tuple[float, float, float]],
) -> tuple[tuple[float, float, float], ...]:
    centroid = tuple(
        sum(point[axis] for point in points) / len(points)
        for axis in range(3)
    )
    spans = tuple(
        max(point[axis] for point in points)
        - min(point[axis] for point in points)
        for axis in range(3)
    )
    diagonal = sqrt(sum(span * span for span in spans))
    if diagonal <= _EPSILON:
        raise ValueError("morphology mesh diagonal must be positive")
    return tuple(
        tuple(
            (point[axis] - centroid[axis]) / diagonal
            for axis in range(3)
        )
        for point in points
    )


def _triangle_evidence(
    points: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
) -> tuple[
    tuple[tuple[float, float, float], float, tuple[float, float, float]], ...
]:
    evidence = []
    for i0, i1, i2 in faces:
        a, b, c = points[i0], points[i1], points[i2]
        ab = tuple(b[axis] - a[axis] for axis in range(3))
        ac = tuple(c[axis] - a[axis] for axis in range(3))
        cross = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        magnitude = sqrt(sum(value * value for value in cross))
        if magnitude <= _EPSILON:
            continue
        evidence.append((
            tuple((a[axis] + b[axis] + c[axis]) / 3.0 for axis in range(3)),
            magnitude / 2.0,
            tuple(value / magnitude for value in cross),
        ))
    if not evidence:
        raise ValueError("morphology mesh requires non-degenerate triangles")
    return tuple(evidence)


def _mesh_volume(
    points: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
) -> float:
    signed = 0.0
    for i0, i1, i2 in faces:
        a, b, c = points[i0], points[i1], points[i2]
        signed += (
            a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0])
        ) / 6.0
    return abs(signed)


def _convex_hull_volume(
    points: Sequence[tuple[float, float, float]],
) -> float:
    try:
        return float(ConvexHull(points).volume)
    except (QhullError, ValueError):
        return 0.0


def _normal_histogram(
    evidence: Sequence[
        tuple[tuple[float, float, float], float, tuple[float, float, float]]
    ],
) -> tuple[float, ...]:
    bins = [0.0] * 12
    for _centroid, area, normal in evidence:
        nz = abs(normal[2])
        elevation_band = min(2, int(nz * 3.0))
        azimuth = (atan2(normal[1], normal[0]) + 2.0 * pi) % (2.0 * pi)
        azimuth_band = min(3, int(azimuth / (pi / 2.0)))
        bins[elevation_band * 4 + azimuth_band] += area
    return _normalized_bins(bins)


def _radial_histogram(
    evidence: Sequence[
        tuple[tuple[float, float, float], float, tuple[float, float, float]]
    ],
) -> tuple[float, ...]:
    radii = [
        sqrt(sum(coordinate * coordinate for coordinate in centroid))
        for centroid, _area, _normal in evidence
    ]
    maximum = max(radii, default=0.0)
    if maximum <= _EPSILON:
        return (0.0,) * 8
    return _histogram(
        (
            (radius / maximum, evidence[index][1])
            for index, radius in enumerate(radii)
        ),
        bins=8,
    )


def _histogram(
    values: Iterable[tuple[float, float]],
    *,
    bins: int,
) -> tuple[float, ...]:
    totals = [0.0] * bins
    for value, weight in values:
        index = min(bins - 1, max(0, int(floor(_unit_value(value) * bins))))
        totals[index] += max(0.0, float(weight))
    return _normalized_bins(totals)


def _resample_profile(
    values: Sequence[float],
    *,
    length: int,
) -> tuple[float, ...]:
    source = tuple(max(0.0, float(value)) for value in values)
    if not source or sum(source) <= _EPSILON:
        return (0.0,) * length
    if len(source) == 1:
        sampled = (source[0],) * length
    else:
        sampled_values = []
        for index in range(length):
            position = index * (len(source) - 1) / (length - 1)
            lower = int(floor(position))
            upper = min(len(source) - 1, lower + 1)
            fraction = position - lower
            sampled_values.append(
                source[lower] * (1.0 - fraction)
                + source[upper] * fraction
            )
        sampled = tuple(sampled_values)
    return _normalized_bins(sampled)


def _silhouette(
    points: Sequence[tuple[float, float, float]],
    faces: Sequence[tuple[int, int, int]],
    view: str,
) -> tuple[float, ...]:
    projected = tuple(_project(point, view) for point in points)
    minimum_u = min(point[0] for point in projected)
    maximum_u = max(point[0] for point in projected)
    minimum_v = min(point[1] for point in projected)
    maximum_v = max(point[1] for point in projected)
    span_u = maximum_u - minimum_u
    span_v = maximum_v - minimum_v
    if span_u <= _EPSILON or span_v <= _EPSILON:
        return (0.0,) * 16
    normalized = tuple(
        (
            (point[0] - minimum_u) / span_u,
            (point[1] - minimum_v) / span_v,
        )
        for point in projected
    )
    triangles_2d = tuple(
        (normalized[i0], normalized[i1], normalized[i2])
        for i0, i1, i2 in faces
    )
    occupancy = []
    sample_offsets = (1.0 / 6.0, 0.5, 5.0 / 6.0)
    for row in range(4):
        for column in range(4):
            covered = 0
            for offset_v in sample_offsets:
                for offset_u in sample_offsets:
                    point = (
                        (column + offset_u) / 4.0,
                        (row + offset_v) / 4.0,
                    )
                    if any(
                        _point_in_triangle(point, triangle)
                        for triangle in triangles_2d
                    ):
                        covered += 1
            occupancy.append(covered / 9.0)
    return _rounded_tuple(occupancy)


def _project(
    point: tuple[float, float, float],
    view: str,
) -> tuple[float, float]:
    x, y, z = point
    if view == "front":
        return x, z
    if view == "side":
        return y, z
    return (x - y) / sqrt(2.0), z + (x + y) / sqrt(6.0)


def _point_in_triangle(
    point: tuple[float, float],
    triangle: tuple[
        tuple[float, float], tuple[float, float], tuple[float, float]
    ],
) -> bool:
    (px, py), (a, b, c) = point, triangle
    denominator = (
        (b[1] - c[1]) * (a[0] - c[0])
        + (c[0] - b[0]) * (a[1] - c[1])
    )
    if abs(denominator) <= _EPSILON:
        return False
    alpha = (
        (b[1] - c[1]) * (px - c[0])
        + (c[0] - b[0]) * (py - c[1])
    ) / denominator
    beta = (
        (c[1] - a[1]) * (px - c[0])
        + (a[0] - c[0]) * (py - c[1])
    ) / denominator
    gamma = 1.0 - alpha - beta
    return alpha >= -_EPSILON and beta >= -_EPSILON and gamma >= -_EPSILON


def _normalized_bins(values: Sequence[float]) -> tuple[float, ...]:
    total = sum(max(0.0, float(value)) for value in values)
    if total <= _EPSILON:
        return (0.0,) * len(values)
    return _rounded_tuple(max(0.0, float(value)) / total for value in values)


def _rounded_tuple(values: Iterable[float]) -> tuple[float, ...]:
    return tuple(round(float(value), 12) for value in values)


def _unit_value(value: float) -> float:
    numeric = float(value or 0.0)
    if not isfinite(numeric):
        return 0.0
    return min(1.0, max(0.0, numeric))


def _rounded_unit(value: float) -> float:
    return round(_unit_value(value), 12)


__all__ = ["extract_morphology_features"]
