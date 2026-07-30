from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import pairwise
import math

from shapely.geometry import Polygon

from backend.app.modules.building_quality.contracts import VerticalQualityMetrics
from backend.app.schemas.layout import PlanElement, RoomPolygon
from backend.app.schemas.result import BuildingGenerationResult, GenerationResult


_WET_SERVICE_TYPES = frozenset({"restroom", "utility", "pantry"})


@dataclass(frozen=True)
class _StackItem:
    space_type: str
    polygon: Polygon


def measure_vertical_quality(building: BuildingGenerationResult) -> VerticalQualityMetrics:
    """Measure the worst adjacent-floor overlap for vertically repeated services."""
    floors = tuple(sorted(building.floor_results, key=lambda floor: floor.program.floor_index))
    core_ratio, _ = _measure_adjacent_stack(
        tuple(_core_items(floor) for floor in floors)
    )
    shaft_ratio, shaft_shift = _measure_adjacent_stack(
        tuple(_shaft_items(floor) for floor in floors)
    )
    wet_ratio, wet_shift = _measure_adjacent_stack(
        tuple(_wet_service_items(floor) for floor in floors)
    )
    shifts = tuple(shift for shift in (shaft_shift, wet_shift) if shift is not None)
    return VerticalQualityMetrics(
        core_stack_ratio=core_ratio,
        shaft_stack_ratio=shaft_ratio,
        wet_service_stack_ratio=wet_ratio,
        maximum_service_centroid_shift_m=max(shifts, default=None),
    )


def _core_items(floor: GenerationResult) -> tuple[_StackItem, ...]:
    return _room_items(floor, frozenset({"core"}))


def _wet_service_items(floor: GenerationResult) -> tuple[_StackItem, ...]:
    return _room_items(floor, _WET_SERVICE_TYPES)


def _room_items(
    floor: GenerationResult, space_types: frozenset[str]
) -> tuple[_StackItem, ...]:
    return tuple(
        item
        for room in floor.layout.rooms
        if room.space_type in space_types
        for item in (_item_from_room(room),)
        if item is not None
    )


def _shaft_items(floor: GenerationResult) -> tuple[_StackItem, ...]:
    features = floor.layout.basic_design
    if features is None:
        return ()
    return tuple(
        item
        for element in features.elements
        if element.kind == "shaft"
        for item in (_item_from_element(element),)
        if item is not None
    )


def _item_from_room(room: RoomPolygon) -> _StackItem | None:
    return _item_from_points(room.space_type, room.polygon)


def _item_from_element(element: PlanElement) -> _StackItem | None:
    return _item_from_points("shaft", element.footprint)


def _item_from_points(
    space_type: str, points: tuple[tuple[float, float], ...] | list[tuple[float, float]]
) -> _StackItem | None:
    polygon = Polygon(points)
    if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
        return None
    return _StackItem(space_type=space_type, polygon=polygon)


def _measure_adjacent_stack(
    floor_items: tuple[tuple[_StackItem, ...], ...],
) -> tuple[float, float | None]:
    if len(floor_items) < 2:
        return 0.0, None

    ratios: list[float] = []
    shifts: list[float] = []
    for first, second in pairwise(floor_items):
        pair_ratios, pair_shifts, has_unmatched_items = _match_adjacent_items(
            first, second
        )
        if not pair_ratios or has_unmatched_items:
            ratios.append(0.0)
        else:
            ratios.append(min(pair_ratios))
        shifts.extend(pair_shifts)
    return min(ratios, default=0.0), max(shifts, default=None)


def _match_adjacent_items(
    first: tuple[_StackItem, ...], second: tuple[_StackItem, ...]
) -> tuple[list[float], list[float], bool]:
    first_by_type = _items_by_type(first)
    second_by_type = _items_by_type(second)
    ratios: list[float] = []
    shifts: list[float] = []
    has_unmatched_items = set(first_by_type) != set(second_by_type)
    for space_type in sorted(set(first_by_type) | set(second_by_type)):
        first_items = first_by_type.get(space_type, ())
        second_items = second_by_type.get(space_type, ())
        if len(first_items) != len(second_items):
            has_unmatched_items = True
        for left, right in _minimum_distance_pairs(first_items, second_items):
            overlap = left.polygon.intersection(right.polygon).area
            denominator = min(left.polygon.area, right.polygon.area)
            ratios.append(overlap / denominator if denominator > 0 else 0.0)
            shifts.append(left.polygon.centroid.distance(right.polygon.centroid))
    return ratios, shifts, has_unmatched_items


def _items_by_type(
    items: tuple[_StackItem, ...]
) -> dict[str, tuple[_StackItem, ...]]:
    grouped: defaultdict[str, list[_StackItem]] = defaultdict(list)
    for item in items:
        grouped[item.space_type].append(item)
    return {
        space_type: tuple(values)
        for space_type, values in grouped.items()
    }


def _minimum_distance_pairs(
    first: tuple[_StackItem, ...], second: tuple[_StackItem, ...]
) -> tuple[tuple[_StackItem, _StackItem], ...]:
    unmatched_first = set(range(len(first)))
    unmatched_second = set(range(len(second)))
    pairs: list[tuple[_StackItem, _StackItem]] = []
    while unmatched_first and unmatched_second:
        distance, first_index, second_index = min(
            (
                first[first_index].polygon.centroid.distance(
                    second[second_index].polygon.centroid
                ),
                first_index,
                second_index,
            )
            for first_index in unmatched_first
            for second_index in unmatched_second
        )
        if not math.isfinite(distance):
            break
        pairs.append((first[first_index], second[second_index]))
        unmatched_first.remove(first_index)
        unmatched_second.remove(second_index)
    return tuple(pairs)
