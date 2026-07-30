from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import pairwise

from shapely.geometry import Polygon

from backend.app.modules.building_quality.contracts import VerticalQualityMetrics
from backend.app.schemas.layout import PlanElement, RoomPolygon
from backend.app.schemas.result import BuildingGenerationResult, GenerationResult


_WET_SERVICE_TYPES = frozenset({"restroom", "utility", "pantry"})


@dataclass(frozen=True)
class _StackItem:
    space_type: str
    item_id: str
    polygon: Polygon


def measure_vertical_quality(
    building: BuildingGenerationResult,
) -> VerticalQualityMetrics:
    """Measure the worst adjacent-floor overlap for vertically repeated services."""
    floors = tuple(
        sorted(building.floor_results, key=lambda floor: floor.program.floor_index)
    )
    core_ratio, _ = _measure_adjacent_stack(
        tuple(_core_items(floor) for floor in floors)
    )
    shaft_ratio, _ = _measure_adjacent_stack(
        tuple(_shaft_items(floor) for floor in floors)
    )
    wet_ratio, wet_shift = _measure_adjacent_stack(
        tuple(_wet_service_items(floor) for floor in floors),
        exclude_when_absent=True,
    )
    return VerticalQualityMetrics(
        core_stack_ratio=core_ratio,
        shaft_stack_ratio=shaft_ratio,
        wet_service_stack_ratio=wet_ratio,
        maximum_service_centroid_shift_m=wet_shift,
        unmeasurable_geometry=_unmeasurable_geometry(floors),
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
    return _item_from_points(room.space_type, room.room_id, room.polygon)


def _item_from_element(element: PlanElement) -> _StackItem | None:
    return _item_from_points("shaft", element.element_id, element.footprint)


def _item_from_points(
    space_type: str,
    item_id: str,
    points: tuple[tuple[float, float], ...] | list[tuple[float, float]],
) -> _StackItem | None:
    try:
        polygon = Polygon(points)
    except (TypeError, ValueError):
        return None
    if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
        return None
    return _StackItem(space_type=space_type, item_id=item_id, polygon=polygon)


def _measure_adjacent_stack(
    floor_items: tuple[tuple[_StackItem, ...], ...],
    *,
    exclude_when_absent: bool = False,
) -> tuple[float, float | None]:
    if not floor_items:
        return 0.0, None
    if len(floor_items) == 1:
        return 1.0, None

    ratios: list[float] = []
    shifts: list[float] = []
    for first, second in pairwise(floor_items):
        if exclude_when_absent and not first and not second:
            continue
        pair_ratios, pair_shifts, has_unmatched_items = _match_adjacent_items(
            first, second
        )
        if not pair_ratios or has_unmatched_items:
            ratios.append(0.0)
        else:
            ratios.append(min(pair_ratios))
        shifts.extend(pair_shifts)
    return min(ratios, default=1.0 if exclude_when_absent else 0.0), max(
        shifts, default=None
    )


def _unmeasurable_geometry(
    floors: tuple[GenerationResult, ...],
) -> tuple[tuple[int, str], ...]:
    invalid: set[tuple[int, str]] = set()
    for floor in floors:
        floor_index = floor.program.floor_index
        for room in floor.layout.rooms:
            if (
                room.space_type in _WET_SERVICE_TYPES | {"core"}
                and _item_from_room(room) is None
            ):
                invalid.add((floor_index, f"{room.space_type}:{room.room_id}"))
        features = floor.layout.basic_design
        if features is not None:
            for element in features.elements:
                if element.kind == "shaft" and _item_from_element(element) is None:
                    invalid.add((floor_index, f"shaft:{element.element_id}"))
    return tuple(sorted(invalid))


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


def _items_by_type(items: tuple[_StackItem, ...]) -> dict[str, tuple[_StackItem, ...]]:
    grouped: defaultdict[str, list[_StackItem]] = defaultdict(list)
    for item in items:
        grouped[item.space_type].append(item)
    return {
        space_type: tuple(sorted(values, key=_stack_item_sort_key))
        for space_type, values in grouped.items()
    }


def _minimum_distance_pairs(
    first: tuple[_StackItem, ...], second: tuple[_StackItem, ...]
) -> tuple[tuple[_StackItem, _StackItem], ...]:
    if len(first) <= len(second):
        assignments = _minimum_cost_assignment(first, second)
        return tuple((first[index], second[match]) for index, match in assignments)
    assignments = _minimum_cost_assignment(second, first)
    return tuple((first[match], second[index]) for index, match in assignments)


def _minimum_cost_assignment(
    rows: tuple[_StackItem, ...], columns: tuple[_StackItem, ...]
) -> tuple[tuple[int, int], ...]:
    """Return a deterministic minimum-total-distance rectangular assignment."""
    row_count = len(rows)
    column_count = len(columns)
    if not row_count:
        return ()

    costs = tuple(
        tuple(
            row.polygon.centroid.distance(column.polygon.centroid) for column in columns
        )
        for row in rows
    )
    potentials_by_row = [0.0] * (row_count + 1)
    potentials_by_column = [0.0] * (column_count + 1)
    matched_row_by_column = [0] * (column_count + 1)
    path = [0] * (column_count + 1)

    for row_index in range(1, row_count + 1):
        matched_row_by_column[0] = row_index
        current_column = 0
        minimums = [float("inf")] * (column_count + 1)
        used = [False] * (column_count + 1)
        while True:
            used[current_column] = True
            current_row = matched_row_by_column[current_column]
            delta = float("inf")
            next_column = 0
            for column_index in range(1, column_count + 1):
                if used[column_index]:
                    continue
                reduced_cost = (
                    costs[current_row - 1][column_index - 1]
                    - potentials_by_row[current_row]
                    - potentials_by_column[column_index]
                )
                if reduced_cost < minimums[column_index]:
                    minimums[column_index] = reduced_cost
                    path[column_index] = current_column
                if minimums[column_index] < delta:
                    delta = minimums[column_index]
                    next_column = column_index
            for column_index in range(column_count + 1):
                if used[column_index]:
                    potentials_by_row[matched_row_by_column[column_index]] += delta
                    potentials_by_column[column_index] -= delta
                else:
                    minimums[column_index] -= delta
            current_column = next_column
            if matched_row_by_column[current_column] == 0:
                break
        while True:
            previous_column = path[current_column]
            matched_row_by_column[current_column] = matched_row_by_column[
                previous_column
            ]
            current_column = previous_column
            if current_column == 0:
                break

    matched_column_by_row = [0] * row_count
    for column_index in range(1, column_count + 1):
        row_index = matched_row_by_column[column_index]
        if row_index:
            matched_column_by_row[row_index - 1] = column_index - 1
    return tuple(enumerate(matched_column_by_row))


def _stack_item_sort_key(item: _StackItem) -> tuple[str, str]:
    return item.item_id, item.polygon.wkb_hex
