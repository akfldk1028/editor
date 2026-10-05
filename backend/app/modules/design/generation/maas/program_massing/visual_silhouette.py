"""Pose-invariant orthographic silhouettes including profiled surfaces."""

from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass
from math import atan2, cos, degrees, radians, sin
from threading import RLock
from typing import TypeAlias
import weakref

from shapely.affinity import rotate, scale, translate
from shapely.geometry import Polygon, box
from shapely.wkb import loads as load_wkb

from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass
from backend.app.modules.design.generation.maas.program_massing.geometry_safety import safe_symmetric_difference_ratio, safe_unary_union


VolumeKey: TypeAlias = tuple[tuple[str, str, float, float], ...]
SurfaceVertices: TypeAlias = tuple[tuple[float, float, float], ...]
ProfiledSurface: TypeAlias = tuple[str, SurfaceVertices]
SurfaceKey: TypeAlias = tuple[ProfiledSurface, ...]
VisualSilhouetteKey: TypeAlias = tuple[VolumeKey, SurfaceKey]
LayeredFootprint: TypeAlias = tuple[str, Polygon, float, float]


ViewTriple: TypeAlias = tuple[Polygon, Polygon, Polygon]
ViewVariants: TypeAlias = tuple[ViewTriple, ...]


@dataclass(frozen=True)
class _SourceViewEntry:
    source_ref: weakref.ReferenceType[SourceMass]
    variants: ViewVariants


@dataclass(frozen=True)
class _PairDistanceEntry:
    left_ref: weakref.ReferenceType[SourceMass]
    right_ref: weakref.ReferenceType[SourceMass]
    distance: float


# Store compact unions, not thousands of triangle tuples. Weak references keep
# a replenishment cycle from retaining sources already released by MAP-Elites.
_SOURCE_VIEW_CACHE: OrderedDict[int, _SourceViewEntry] = OrderedDict()
_PAIR_DISTANCE_CACHE: OrderedDict[tuple[int, int], _PairDistanceEntry] = OrderedDict()
_SOURCE_VIEW_INFLIGHT: dict[tuple[int, int], Future[ViewVariants]] = {}
_PAIR_DISTANCE_INFLIGHT: dict[tuple[int, int, int], Future[float]] = {}
_SOURCE_VIEW_CACHE_LIMIT = 512
_PAIR_DISTANCE_CACHE_LIMIT = 32_768
_CACHE_LOCK = RLock()
_CACHE_EPOCH = 0
_CACHE_METRICS = {
    "source_view_build_count": 0,
    "source_view_cache_hit_count": 0,
    "exact_pair_evaluation_count": 0,
    "pair_cache_hit_count": 0,
}


def source_visual_silhouette_key(source: SourceMass) -> VisualSilhouetteKey:
    """Serialize mass solids and renderer-visible profiled surfaces locally."""
    center = source.footprint.centroid
    volumes = tuple(sorted(
        (
            volume.role,
            translate(volume.footprint, xoff=-center.x, yoff=-center.y).wkb_hex,
            round(float(volume.bottom_fraction), 6),
            round(float(volume.top_fraction), 6),
        )
        for volume in source.volumes
        if not volume.footprint.is_empty
    ))
    surfaces = tuple(sorted(
        (
            surface.volume_role,
            tuple(
                (
                    # vertices_m is already local to the source-footprint
                    # centroid; subtracting a world centroid again corrupts
                    # the surface-aware duplicate metric.
                    round(float(x), 6),
                    round(float(y), 6),
                    round(float(z), 6),
                )
                for x, y, z in surface.vertices_m
            ),
        )
        for surface in source.surfaces
        if surface.surface_type.startswith("profiled_") and len(surface.vertices_m) >= 3
    ))
    return volumes, surfaces


def visual_silhouette_distance(left: SourceMass, right: SourceMass) -> float:
    if left is right:
        return 0.0
    if id(right) < id(left):
        left, right = right, left
    pair_key = (id(left), id(right))
    with _CACHE_LOCK:
        generation = _CACHE_EPOCH
        cached = _PAIR_DISTANCE_CACHE.get(pair_key)
        if (
            cached is not None
            and cached.left_ref() is left
            and cached.right_ref() is right
        ):
            _PAIR_DISTANCE_CACHE.move_to_end(pair_key)
            _CACHE_METRICS["pair_cache_hit_count"] += 1
            return cached.distance
        if cached is not None:
            _PAIR_DISTANCE_CACHE.pop(pair_key, None)
        inflight_key = (generation, *pair_key)
        future = _PAIR_DISTANCE_INFLIGHT.get(inflight_key)
        owner = future is None
        if owner:
            future = Future()
            _PAIR_DISTANCE_INFLIGHT[inflight_key] = future
    assert future is not None
    if not owner:
        distance = float(future.result())
        with _CACHE_LOCK:
            if generation == _CACHE_EPOCH:
                _CACHE_METRICS["pair_cache_hit_count"] += 1
        return distance

    try:
        left_variants = _source_view_variants(left, generation=generation)
        right_variants = _source_view_variants(right, generation=generation)
        best = 1.0
        if left_variants and right_variants:
            left_views = left_variants[0]
            for right_views in right_variants:
                distances = tuple(
                    safe_symmetric_difference_ratio(a, b)
                    for a, b in zip(left_views, right_views)
                )
                best = min(
                    best,
                    distances[0] * 0.40
                    + distances[1] * 0.30
                    + distances[2] * 0.30,
                )
        distance = min(1.0, best)
        left_ref = weakref.ref(left)
        right_ref = weakref.ref(right)
        with _CACHE_LOCK:
            if generation == _CACHE_EPOCH:
                _CACHE_METRICS["exact_pair_evaluation_count"] += 1
                _PAIR_DISTANCE_CACHE[pair_key] = _PairDistanceEntry(
                    left_ref,
                    right_ref,
                    distance,
                )
                _PAIR_DISTANCE_CACHE.move_to_end(pair_key)
                while len(_PAIR_DISTANCE_CACHE) > _PAIR_DISTANCE_CACHE_LIMIT:
                    _PAIR_DISTANCE_CACHE.popitem(last=False)
            future.set_result(distance)
            _PAIR_DISTANCE_INFLIGHT.pop(inflight_key, None)
        return distance
    except BaseException as exc:
        with _CACHE_LOCK:
            future.set_exception(exc)
            _PAIR_DISTANCE_INFLIGHT.pop(inflight_key, None)
        raise


def visual_silhouette_distance_from_keys(
    left_key: VisualSilhouetteKey,
    right_key: VisualSilhouetteKey,
) -> float:
    left_views = _cached_views(left_key, angle=0.0, mirror_x=False)
    if left_views is None:
        return 1.0
    best = 1.0
    for angle in (0.0, 90.0, 180.0, 270.0):
        for mirror_x in (False, True):
            right_views = _cached_views(right_key, angle=angle, mirror_x=mirror_x)
            if right_views is None:
                continue
            distances = tuple(
                safe_symmetric_difference_ratio(a, b)
                for a, b in zip(left_views, right_views)
            )
            best = min(best, distances[0] * 0.40 + distances[1] * 0.30 + distances[2] * 0.30)
    return min(1.0, best)


def visual_silhouette_view_variants(source: SourceMass) -> ViewVariants:
    """Return the cached normalized top/front/side views for ``source``.

    Competition gestalt measurement needs the same certified-mesh
    projections as the historical silhouette gate.  Exposing the already
    cached variants keeps that measurement from rebuilding thousands of
    triangle unions or drifting to a second projection implementation.
    """

    with _CACHE_LOCK:
        generation = _CACHE_EPOCH
    return _source_view_variants(source, generation=generation)


def _principal_frame(
    key: VisualSilhouetteKey,
) -> tuple[tuple[LayeredFootprint, ...], SurfaceKey] | None:
    volume_key, surfaces = key
    volumes = tuple(
        (role, load_wkb(bytes.fromhex(wkb_hex)), bottom, top)
        for role, wkb_hex, bottom, top in volume_key
    )
    if not volumes:
        return None
    union = safe_unary_union([footprint for _, footprint, _, _ in volumes])
    if union is None or union.is_empty:
        return None
    rectangle = union.minimum_rotated_rectangle
    coordinates = list(rectangle.exterior.coords)
    edges = [
        (
            ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5,
            degrees(atan2(y2 - y1, x2 - x1)),
        )
        for (x1, y1), (x2, y2) in zip(coordinates, coordinates[1:])
    ]
    major_length, major_angle = max(edges, key=lambda item: item[0])
    if major_length <= 1e-9:
        return None
    normalized_volumes = tuple(
        (
            role,
            scale(
                rotate(footprint, -major_angle, origin=(0.0, 0.0)),
                xfact=1.0 / major_length,
                yfact=1.0 / major_length,
                origin=(0.0, 0.0),
            ),
            bottom,
            top,
        )
        for role, footprint, bottom, top in volumes
    )
    angle = radians(-major_angle)
    normalized_surfaces = tuple(
        (volume_role, tuple(
            (
                (x * cos(angle) - y * sin(angle)) / major_length,
                (x * sin(angle) + y * cos(angle)) / major_length,
                z,
            )
            for x, y, z in vertices
        ))
        for volume_role, vertices in surfaces
    )
    return normalized_volumes, normalized_surfaces


def _cached_views(
    key: VisualSilhouetteKey,
    *,
    angle: float,
    mirror_x: bool,
) -> tuple[Polygon, Polygon, Polygon] | None:
    frame = _principal_frame(key)
    if frame is None:
        return None
    if angle or mirror_x:
        frame = _transform_geometry(*frame, angle=angle, mirror_x=mirror_x)
    return _views(*frame)


def _source_view_variants(
    source: SourceMass,
    *,
    generation: int,
) -> ViewVariants:
    cache_id = id(source)
    with _CACHE_LOCK:
        cached = (
            _SOURCE_VIEW_CACHE.get(cache_id)
            if generation == _CACHE_EPOCH
            else None
        )
        if cached is not None and cached.source_ref() is source:
            _SOURCE_VIEW_CACHE.move_to_end(cache_id)
            _CACHE_METRICS["source_view_cache_hit_count"] += 1
            return cached.variants
        if cached is not None:
            _SOURCE_VIEW_CACHE.pop(cache_id, None)
        inflight_key = (generation, cache_id)
        future = _SOURCE_VIEW_INFLIGHT.get(inflight_key)
        owner = future is None
        if owner:
            future = Future()
            _SOURCE_VIEW_INFLIGHT[inflight_key] = future
    assert future is not None
    if not owner:
        variants = future.result()
        with _CACHE_LOCK:
            if generation == _CACHE_EPOCH:
                _CACHE_METRICS["source_view_cache_hit_count"] += 1
        return variants

    try:
        frame = _principal_frame(source_visual_silhouette_key(source))
        if frame is None:
            variants: ViewVariants = ()
        else:
            computed: list[ViewTriple] = []
            for angle in (0.0, 90.0, 180.0, 270.0):
                for mirror_x in (False, True):
                    transformed = (
                        frame
                        if angle == 0.0 and not mirror_x
                        else _transform_geometry(
                            *frame,
                            angle=angle,
                            mirror_x=mirror_x,
                        )
                    )
                    computed.append(_views(*transformed))
            variants = tuple(computed)

        def release(reference: weakref.ReferenceType[SourceMass]) -> None:
            with _CACHE_LOCK:
                current = _SOURCE_VIEW_CACHE.get(cache_id)
                if current is not None and current.source_ref is reference:
                    _SOURCE_VIEW_CACHE.pop(cache_id, None)

        reference = weakref.ref(source, release)
        with _CACHE_LOCK:
            if generation == _CACHE_EPOCH:
                _CACHE_METRICS["source_view_build_count"] += 1
                _SOURCE_VIEW_CACHE[cache_id] = _SourceViewEntry(
                    reference,
                    variants,
                )
                _SOURCE_VIEW_CACHE.move_to_end(cache_id)
                while len(_SOURCE_VIEW_CACHE) > _SOURCE_VIEW_CACHE_LIMIT:
                    _SOURCE_VIEW_CACHE.popitem(last=False)
            future.set_result(variants)
            _SOURCE_VIEW_INFLIGHT.pop(inflight_key, None)
        return variants
    except BaseException as exc:
        with _CACHE_LOCK:
            future.set_exception(exc)
            _SOURCE_VIEW_INFLIGHT.pop(inflight_key, None)
        raise


def reset_visual_silhouette_cache_metrics() -> None:
    """Reset bounded runtime caches and counters for benchmark instrumentation."""

    global _CACHE_EPOCH
    with _CACHE_LOCK:
        _CACHE_EPOCH += 1
        _SOURCE_VIEW_CACHE.clear()
        _PAIR_DISTANCE_CACHE.clear()
        for key in _CACHE_METRICS:
            _CACHE_METRICS[key] = 0


def visual_silhouette_cache_metrics() -> dict[str, int]:
    """Expose cache reuse without retaining source geometry in diagnostics."""

    with _CACHE_LOCK:
        return {
            **_CACHE_METRICS,
            "source_view_cache_size": len(_SOURCE_VIEW_CACHE),
            "pair_cache_size": len(_PAIR_DISTANCE_CACHE),
        }


def _transform_geometry(
    volumes: tuple[LayeredFootprint, ...],
    surfaces: SurfaceKey,
    *,
    angle: float,
    mirror_x: bool,
) -> tuple[tuple[LayeredFootprint, ...], SurfaceKey]:
    transformed_volumes = tuple(
        (
            role,
            rotate(
                scale(footprint, xfact=-1.0 if mirror_x else 1.0, yfact=1.0, origin=(0.0, 0.0)),
                angle,
                origin=(0.0, 0.0),
            ),
            bottom,
            top,
        )
        for role, footprint, bottom, top in volumes
    )
    theta = radians(angle)
    transformed_surfaces: list[ProfiledSurface] = []
    for volume_role, vertices in surfaces:
        transformed: list[tuple[float, float, float]] = []
        for x, y, z in vertices:
            mirrored_x = -x if mirror_x else x
            transformed.append((
                mirrored_x * cos(theta) - y * sin(theta),
                mirrored_x * sin(theta) + y * cos(theta),
                z,
            ))
        transformed_surfaces.append((volume_role, tuple(transformed)))
    return transformed_volumes, tuple(transformed_surfaces)


def _projection_polygon(vertices: SurfaceVertices, axes: tuple[int, int]) -> Polygon | None:
    coordinates = [(vertex[axes[0]], vertex[axes[1]]) for vertex in vertices]
    candidate = Polygon(coordinates)
    if candidate.is_empty or candidate.area <= 1e-9:
        return None
    if not candidate.is_valid:
        candidate = candidate.buffer(0)
    return candidate if isinstance(candidate, Polygon) and not candidate.is_empty else None


def _views(
    volumes: tuple[LayeredFootprint, ...],
    surfaces: SurfaceKey,
) -> tuple[Polygon, Polygon, Polygon]:
    profiled_roles = {volume_role for volume_role, _ in surfaces}
    volume_top = [footprint for _, footprint, _, _ in volumes]
    volume_front = [
        box(footprint.bounds[0], bottom, footprint.bounds[2], top)
        for role, footprint, bottom, top in volumes
        if role not in profiled_roles
    ]
    volume_side = [
        box(footprint.bounds[1], bottom, footprint.bounds[3], top)
        for role, footprint, bottom, top in volumes
        if role not in profiled_roles
    ]
    projected_top = [polygon for _, vertices in surfaces if (polygon := _projection_polygon(vertices, (0, 1))) is not None]
    projected_front = [polygon for _, vertices in surfaces if (polygon := _projection_polygon(vertices, (0, 2))) is not None]
    projected_side = [polygon for _, vertices in surfaces if (polygon := _projection_polygon(vertices, (1, 2))) is not None]
    return (
        safe_unary_union([*volume_top, *projected_top]) or Polygon(),
        safe_unary_union([*volume_front, *projected_front]) or Polygon(),
        safe_unary_union([*volume_side, *projected_side]) or Polygon(),
    )


__all__ = [
    "source_visual_silhouette_key",
    "reset_visual_silhouette_cache_metrics",
    "visual_silhouette_distance",
    "visual_silhouette_distance_from_keys",
    "visual_silhouette_cache_metrics",
    "visual_silhouette_view_variants",
]
