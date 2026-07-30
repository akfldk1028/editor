from __future__ import annotations

from collections.abc import Iterable
from hashlib import sha256
import json
import math

from shapely.geometry import GeometryCollection, Polygon
from shapely.ops import unary_union

from backend.app.modules.building_quality.constants import (
    DIVERSITY_COMPONENT_WEIGHTS,
    MATERIAL_DIVERSITY_DISTANCE,
)
from backend.app.modules.building_quality.contracts import (
    AlternativeDiversityReport,
    QualityPolicy,
)
from backend.app.modules.building_quality.policy import DEFAULT_QUALITY_POLICY
from backend.app.schemas.layout import RoomPolygon
from backend.app.schemas.result import BuildingGenerationResult, GenerationResult

_FINGERPRINT_DECIMALS = 6


def compare_building_diversity(
    first: BuildingGenerationResult,
    second: BuildingGenerationResult,
    *,
    policy: QualityPolicy = DEFAULT_QUALITY_POLICY,
) -> AlternativeDiversityReport:
    """Compare two generated buildings using coordinate-order-invariant semantics."""
    first_features = _building_features(first)
    second_features = _building_features(second)

    core_distance = _core_distance(first_features, second_features)
    circulation_distance = _circulation_distance(first_features, second_features)
    topology_distance = _jaccard_distance(
        first_features.topology_edges,
        second_features.topology_edges,
    )
    area_distribution_distance = _total_variation_distance(
        first_features.area_distribution,
        second_features.area_distribution,
    )
    components = (
        core_distance,
        circulation_distance,
        topology_distance,
        area_distribution_distance,
    )
    total_distance = sum(
        weight * component
        for weight, component in zip(DIVERSITY_COMPONENT_WEIGHTS, components, strict=True)
    )
    nonzero_component_count = sum(
        component > 0.0 for component in components
    )
    quality_distinct = (
        total_distance >= policy.minimum_pairwise_diversity
        and sum(component > MATERIAL_DIVERSITY_DISTANCE for component in components) >= 2
    )

    return AlternativeDiversityReport(
        first_fingerprint=first_features.fingerprint,
        second_fingerprint=second_features.fingerprint,
        core_distance=_normalized(core_distance),
        circulation_distance=_normalized(circulation_distance),
        topology_distance=_normalized(topology_distance),
        area_distribution_distance=_normalized(area_distribution_distance),
        total_distance=_normalized(total_distance),
        nonzero_component_count=nonzero_component_count,
        quality_distinct=quality_distinct,
    )


class _BuildingFeatures:
    def __init__(
        self,
        *,
        cores: dict[int, object],
        floor_diagonals: dict[int, float],
        circulation_edges: frozenset[tuple[object, ...]],
        circulation_orientations: tuple[tuple[int, str], ...],
        topology_edges: frozenset[tuple[object, ...]],
        area_distribution: dict[str, float],
        fingerprint: str,
    ) -> None:
        self.cores = cores
        self.floor_diagonals = floor_diagonals
        self.circulation_edges = circulation_edges
        self.circulation_orientations = circulation_orientations
        self.topology_edges = topology_edges
        self.area_distribution = area_distribution
        self.fingerprint = fingerprint


def _building_features(building: BuildingGenerationResult) -> _BuildingFeatures:
    floors = _floors_by_index(building.floor_results)
    cores: dict[int, object] = {}
    floor_diagonals: dict[int, float] = {}
    circulation_edges: set[tuple[object, ...]] = set()
    circulation_orientations: list[tuple[int, str]] = []
    topology_edges: set[tuple[object, ...]] = set()
    areas_by_type: dict[str, float] = {}
    fingerprint_floors: list[dict[str, object]] = []

    for floor_index, floor in floors.items():
        layout = floor.layout
        core_polygons = [
            _polygon(room.polygon)
            for room in layout.rooms
            if room.space_type == "core"
        ]
        cores[floor_index] = _combined_geometry(core_polygons)
        floor_diagonals[floor_index] = _floor_diagonal(building, floor)

        floor_edges = _circulation_edges(layout.circulation, floor_index)
        circulation_edges.update(floor_edges)
        orientation = _circulation_orientation(layout.circulation)
        circulation_orientations.append((floor_index, orientation))

        floor_topology = _topology_edges(floor, floor_index)
        topology_edges.update(floor_topology)

        for shape in [*layout.rooms, *layout.circulation]:
            areas_by_type[shape.space_type] = (
                areas_by_type.get(shape.space_type, 0.0) + _polygon(shape.polygon).area
            )

        fingerprint_floors.append(
            {
                "floor_index": floor_index,
                "cores": sorted(
                    _canonical_polygon(room.polygon)
                    for room in layout.rooms
                    if room.space_type == "core"
                ),
                "circulation_edges": sorted(floor_edges),
                "circulation_orientation": orientation,
                "topology_edges": sorted(floor_topology),
            }
        )

    area_distribution = _area_distribution(areas_by_type)
    fingerprint = sha256(
        json.dumps(
            {
                "floors": fingerprint_floors,
                "area_distribution": sorted(area_distribution.items()),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return _BuildingFeatures(
        cores=cores,
        floor_diagonals=floor_diagonals,
        circulation_edges=frozenset(circulation_edges),
        circulation_orientations=tuple(circulation_orientations),
        topology_edges=frozenset(topology_edges),
        area_distribution=area_distribution,
        fingerprint=fingerprint,
    )


def _floors_by_index(
    floors: tuple[GenerationResult, ...],
) -> dict[int, GenerationResult]:
    return {floor.program.floor_index: floor for floor in floors}


def _core_distance(first: _BuildingFeatures, second: _BuildingFeatures) -> float:
    floor_indexes = sorted(set(first.cores) | set(second.cores))
    if not floor_indexes:
        return 0.0
    distances = [
        _floor_core_distance(
            first.cores.get(floor_index),
            second.cores.get(floor_index),
            max(
                first.floor_diagonals.get(floor_index, 0.0),
                second.floor_diagonals.get(floor_index, 0.0),
            ),
        )
        for floor_index in floor_indexes
    ]
    return sum(distances) / len(distances)


def _floor_core_distance(first: object | None, second: object | None, diagonal: float) -> float:
    first_is_empty = first is None or first.is_empty
    second_is_empty = second is None or second.is_empty
    if first_is_empty and second_is_empty:
        return 0.0
    if first_is_empty or second_is_empty:
        return 1.0

    centroid_distance = first.centroid.distance(second.centroid) / max(diagonal, 1e-9)
    symmetric_difference_area = first.symmetric_difference(second).area
    union_area = first.union(second).area
    area_distance = symmetric_difference_area / union_area if union_area else 0.0
    return _normalized((centroid_distance + area_distance) / 2.0)


def _circulation_distance(first: _BuildingFeatures, second: _BuildingFeatures) -> float:
    graph_distance = _jaccard_distance(
        first.circulation_edges,
        second.circulation_edges,
    )
    orientation_distance = float(
        first.circulation_orientations != second.circulation_orientations
    )
    return (graph_distance + orientation_distance) / 2.0


def _circulation_edges(
    circulation: Iterable[RoomPolygon],
    floor_index: int,
) -> set[tuple[object, ...]]:
    return {
        (floor_index, *edge)
        for path in circulation
        for edge in _polygon_edges(path.polygon)
    }


def _polygon_edges(
    points: list[tuple[float, float]],
) -> set[tuple[tuple[float, float], tuple[float, float]]]:
    rounded = tuple(_rounded_point(point) for point in points)
    if len(rounded) > 1 and rounded[0] == rounded[-1]:
        rounded = rounded[:-1]
    return {
        tuple(sorted((start, end)))
        for start, end in zip(rounded, rounded[1:] + rounded[:1], strict=True)
        if start != end
    }


def _circulation_orientation(circulation: Iterable[RoomPolygon]) -> str:
    horizontal = 0.0
    vertical = 0.0
    for path in circulation:
        points = path.polygon
        if len(points) > 1 and points[0] == points[-1]:
            points = points[:-1]
        for start, end in zip(points, points[1:] + points[:1], strict=True):
            horizontal += abs(end[0] - start[0])
            vertical += abs(end[1] - start[1])
    if horizontal == 0.0 and vertical == 0.0:
        return "none"
    if math.isclose(horizontal, vertical, rel_tol=0.0, abs_tol=1e-9):
        return "mixed"
    return "horizontal" if horizontal > vertical else "vertical"


def _topology_edges(
    floor: GenerationResult,
    floor_index: int,
) -> set[tuple[object, ...]]:
    types_by_id = {node.node_id: node.space_type for node in floor.program.nodes}
    return {
        (floor_index, *sorted((types_by_id[edge.source], types_by_id[edge.target])))
        for edge in floor.program.edges
        if edge.source in types_by_id and edge.target in types_by_id
    }


def _area_distribution(areas_by_type: dict[str, float]) -> dict[str, float]:
    total_area = sum(areas_by_type.values())
    if total_area <= 0.0:
        return {}
    return {
        space_type: area / total_area
        for space_type, area in sorted(areas_by_type.items())
        if area > 0.0
    }


def _total_variation_distance(
    first: dict[str, float],
    second: dict[str, float],
) -> float:
    return sum(
        abs(first.get(space_type, 0.0) - second.get(space_type, 0.0))
        for space_type in set(first) | set(second)
    ) / 2.0


def _jaccard_distance(first: frozenset[tuple[object, ...]], second: frozenset[tuple[object, ...]]) -> float:
    if not first and not second:
        return 0.0
    return 1.0 - len(first & second) / len(first | second)


def _floor_diagonal(building: BuildingGenerationResult, floor: GenerationResult) -> float:
    bounds = building.mass.bounds_for_floor(floor.program.floor_index)
    diagonal = math.dist((bounds[0], bounds[1]), (bounds[2], bounds[3]))
    if diagonal > 0.0:
        return diagonal
    shapes = [*floor.layout.rooms, *floor.layout.circulation]
    if not shapes:
        return 0.0
    min_x = min(point[0] for shape in shapes for point in shape.polygon)
    min_y = min(point[1] for shape in shapes for point in shape.polygon)
    max_x = max(point[0] for shape in shapes for point in shape.polygon)
    max_y = max(point[1] for shape in shapes for point in shape.polygon)
    return math.dist((min_x, min_y), (max_x, max_y))


def _combined_geometry(polygons: Iterable[Polygon]) -> object:
    values = tuple(polygons)
    return unary_union(values) if values else GeometryCollection()


def _polygon(points: list[tuple[float, float]]) -> Polygon:
    return Polygon(points)


def _canonical_polygon(points: list[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    ring = tuple(_rounded_point(point) for point in points)
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    rotations = [ring[index:] + ring[:index] for index in range(len(ring))]
    reversed_ring = tuple(reversed(ring))
    rotations.extend(
        reversed_ring[index:] + reversed_ring[:index]
        for index in range(len(reversed_ring))
    )
    return min(rotations) if rotations else ()


def _rounded_point(point: tuple[float, float]) -> tuple[float, float]:
    return (
        round(float(point[0]), _FINGERPRINT_DECIMALS),
        round(float(point[1]), _FINGERPRINT_DECIMALS),
    )


def _normalized(value: float) -> float:
    return min(1.0, max(0.0, value))
