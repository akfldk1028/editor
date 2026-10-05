"""Proof-bounded polygon normalization for executable replay transport.

The legal/capacity SourceMass remains authoritative. This module only removes
duplicate or forward, near-collinear breakpoints that would create a
sub-tolerance edge when an already-certified plan is serialized to the solid
compiler. Any topology, occupied-subset, or area proof failure is fail-closed.
"""

from __future__ import annotations

from math import hypot

from shapely.affinity import translate
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient


MAXIMUM_AREA_DELTA_M2 = 1e-6
MAXIMUM_SYMMETRIC_DIFFERENCE_M2 = 1e-6
MAXIMUM_BREAKPOINT_OFFSET_M = 1e-6
MAXIMUM_FORWARD_TURN_SINE = 0.25
MINIMUM_REPLAY_EDGE_LENGTH_M = 1e-5
TRANSPORT_DUPLICATE_DISTANCE_M = 5e-8

Point2 = tuple[float, float]


def replay_polygon_origin(polygon: Polygon) -> Point2:
    """Return a cyclic-start-independent common replay origin."""

    centroid = _canonical_polygon(polygon).centroid
    return (float(centroid.x), float(centroid.y))


def normalize_replay_polygon(
    polygon: Polygon,
    *,
    allowed_envelope: Polygon | None = None,
    maximum_area_delta_m2: float = MAXIMUM_AREA_DELTA_M2,
    maximum_symmetric_difference_m2: float = (
        MAXIMUM_SYMMETRIC_DIFFERENCE_M2
    ),
) -> Polygon:
    """Remove only deterministic breakpoints proven inside the envelope."""

    canonical = _canonical_polygon(polygon)
    if canonical.is_empty or not canonical.is_valid:
        return canonical
    envelope = (
        _canonical_polygon(allowed_envelope)
        if allowed_envelope is not None
        else canonical
    )
    rings = _polygon_rings(canonical)
    while True:
        accepted: Polygon | None = None
        for ring_index, ring in enumerate(rings):
            if len(ring) <= 3:
                continue
            for point_index, current in enumerate(ring):
                previous = ring[point_index - 1]
                following = ring[(point_index + 1) % len(ring)]
                if not _is_removable_breakpoint(
                    previous,
                    current,
                    following,
                ):
                    continue
                candidate_rings = list(rings)
                candidate_rings[ring_index] = (
                    ring[:point_index] + ring[point_index + 1:]
                )
                candidate = _canonical_polygon(
                    _polygon_from_rings(candidate_rings)
                )
                if _proves_transport_equivalence(
                    candidate,
                    reference=canonical,
                    envelope=envelope,
                    maximum_area_delta_m2=maximum_area_delta_m2,
                    maximum_symmetric_difference_m2=(
                        maximum_symmetric_difference_m2
                    ),
                ):
                    accepted = candidate
                    break
            if accepted is not None:
                break
        if accepted is None:
            return _canonical_polygon(_polygon_from_rings(rings))
        rings = _polygon_rings(accepted)


def replay_polygon_point_payload(
    polygon: Polygon,
    *,
    xoff: float,
    yoff: float,
    allowed_envelope: Polygon | None = None,
    maximum_area_delta_m2: float = MAXIMUM_AREA_DELTA_M2,
    maximum_symmetric_difference_m2: float = (
        MAXIMUM_SYMMETRIC_DIFFERENCE_M2
    ),
) -> tuple[list[list[float]], list[list[list[float]]], str]:
    """Return a reconstructed-and-proven replay payload.

    Seven-decimal transport remains the preferred representation. If nearest
    rounding would expand outside the occupied source, retain the normalized
    full-precision local coordinates instead of inventing an inward buffer.
    """

    canonical = _canonical_polygon(polygon)
    envelope = (
        _canonical_polygon(allowed_envelope)
        if allowed_envelope is not None
        else canonical
    )
    normalized = normalize_replay_polygon(
        canonical,
        allowed_envelope=envelope,
        maximum_area_delta_m2=maximum_area_delta_m2,
        maximum_symmetric_difference_m2=(
            maximum_symmetric_difference_m2
        ),
    )
    reference_local = translate(
        canonical,
        xoff=-float(xoff),
        yoff=-float(yoff),
    )
    envelope_local = translate(
        envelope,
        xoff=-float(xoff),
        yoff=-float(yoff),
    )
    normalized_local = translate(
        normalized,
        xoff=-float(xoff),
        yoff=-float(yoff),
    )
    for precision_mode, decimal_places in (
        ("decimal_7", 7),
        ("full_precision_fallback", None),
    ):
        points = _local_ring(
            normalized_local.exterior.coords,
            decimal_places=decimal_places,
        )
        holes = tuple(
            _local_ring(
                interior.coords,
                decimal_places=decimal_places,
            )
            for interior in normalized_local.interiors
        )
        reconstructed_local = Polygon(points, holes=holes)
        if (
            reconstructed_local.exterior.is_ccw
            and not any(
                interior.is_ccw
                for interior in reconstructed_local.interiors
            )
            and _proves_transport_equivalence(
                reconstructed_local,
                reference=reference_local,
                envelope=envelope_local,
                maximum_area_delta_m2=maximum_area_delta_m2,
                maximum_symmetric_difference_m2=(
                    maximum_symmetric_difference_m2
                ),
            )
        ):
            return (
                [[float(x), float(y)] for x, y in points],
                [
                    [[float(x), float(y)] for x, y in hole]
                    for hole in holes
                ],
                precision_mode,
            )
    raise ValueError("replay_polygon_transport_proof_failed")


def _polygon_rings(polygon: Polygon) -> list[tuple[Point2, ...]]:
    return [
        _canonical_ring(polygon.exterior.coords),
        *(
            _canonical_ring(interior.coords)
            for interior in polygon.interiors
        ),
    ]


def _polygon_from_rings(rings: list[tuple[Point2, ...]]) -> Polygon:
    if not rings:
        return Polygon()
    return Polygon(rings[0], holes=rings[1:])


def _proves_transport_equivalence(
    candidate: Polygon,
    *,
    reference: Polygon,
    envelope: Polygon,
    maximum_area_delta_m2: float,
    maximum_symmetric_difference_m2: float,
) -> bool:
    return bool(
        not candidate.is_empty
        and candidate.is_valid
        and len(candidate.interiors) == len(reference.interiors)
        and envelope.covers(candidate)
        and abs(float(candidate.area) - float(reference.area))
        <= float(maximum_area_delta_m2)
        and float(candidate.symmetric_difference(reference).area)
        <= float(maximum_symmetric_difference_m2)
    )


def _canonical_polygon(polygon: Polygon) -> Polygon:
    canonical = orient(polygon, sign=1.0)
    exterior = _canonical_ring(canonical.exterior.coords)
    holes = sorted(
        (
            _canonical_ring(interior.coords)
            for interior in canonical.interiors
        ),
        key=lambda ring: ring,
    )
    return Polygon(exterior, holes=holes)


def _canonical_ring(coordinates) -> tuple[Point2, ...]:
    points = tuple(
        (float(coordinate[0]), float(coordinate[1]))
        for coordinate in coordinates
    )
    if len(points) >= 2 and points[0] == points[-1]:
        points = points[:-1]
    if len(points) <= 1:
        return points
    return min(
        points[index:] + points[:index]
        for index in range(len(points))
    )


def _local_ring(
    coordinates,
    *,
    decimal_places: int | None = None,
) -> tuple[Point2, ...]:
    return tuple(
        (
            (
                round(float(point[0]), decimal_places)
                if decimal_places is not None
                else float(point[0])
            ),
            (
                round(float(point[1]), decimal_places)
                if decimal_places is not None
                else float(point[1])
            ),
        )
        for point in _canonical_ring(coordinates)
    )


def _is_removable_breakpoint(
    previous: Point2,
    current: Point2,
    following: Point2,
) -> bool:
    if (
        _distance(previous, current)
        <= TRANSPORT_DUPLICATE_DISTANCE_M
        or _distance(current, following)
        <= TRANSPORT_DUPLICATE_DISTANCE_M
    ):
        return True
    return _is_removable_forward_breakpoint(
        previous,
        current,
        following,
    )


def _is_removable_forward_breakpoint(
    previous: Point2,
    current: Point2,
    following: Point2,
) -> bool:
    incoming = (
        current[0] - previous[0],
        current[1] - previous[1],
    )
    outgoing = (
        following[0] - current[0],
        following[1] - current[1],
    )
    incoming_length = hypot(*incoming)
    outgoing_length = hypot(*outgoing)
    if (
        min(incoming_length, outgoing_length)
        >= MINIMUM_REPLAY_EDGE_LENGTH_M
        or incoming_length <= TRANSPORT_DUPLICATE_DISTANCE_M
        or outgoing_length <= TRANSPORT_DUPLICATE_DISTANCE_M
    ):
        return False
    forward_dot = incoming[0] * outgoing[0] + incoming[1] * outgoing[1]
    if forward_dot <= 0.0:
        return False
    span = (
        following[0] - previous[0],
        following[1] - previous[1],
    )
    span_squared = span[0] * span[0] + span[1] * span[1]
    if span_squared <= TRANSPORT_DUPLICATE_DISTANCE_M ** 2:
        return False
    projection = (
        (current[0] - previous[0]) * span[0]
        + (current[1] - previous[1]) * span[1]
    ) / span_squared
    if projection < 0.0 or projection > 1.0:
        return False
    cross = incoming[0] * outgoing[1] - incoming[1] * outgoing[0]
    turn_sine = abs(cross) / (incoming_length * outgoing_length)
    if turn_sine > MAXIMUM_FORWARD_TURN_SINE:
        return False
    offset = abs(
        span[0] * (previous[1] - current[1])
        - (previous[0] - current[0]) * span[1]
    ) / hypot(*span)
    return offset <= MAXIMUM_BREAKPOINT_OFFSET_M


def _distance(left: Point2, right: Point2) -> float:
    return hypot(right[0] - left[0], right[1] - left[1])


__all__ = [
    "MAXIMUM_AREA_DELTA_M2",
    "MAXIMUM_SYMMETRIC_DIFFERENCE_M2",
    "normalize_replay_polygon",
    "replay_polygon_origin",
    "replay_polygon_point_payload",
]
