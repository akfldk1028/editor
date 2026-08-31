from __future__ import annotations

from dataclasses import dataclass
import math

from backend.app.schemas.metrics import RoomShapeMetric
from backend.app.schemas.result import GenerationResult


@dataclass(frozen=True)
class RoomFormMeasurement:
    measured_area: float
    passing_area: float
    ratio: float
    worst_aspect_ratio: float | None
    narrowest_width_m: float | None
    failing_room_ids: tuple[str, ...]
    unmeasurable_room_ids: tuple[str, ...]


def measure_room_form(floor: GenerationResult) -> RoomFormMeasurement:
    room_ids = sorted(
        {room.room_id for room in floor.layout.rooms if room.space_type != "core"}
    )
    if not room_ids:
        raise ValueError("floor has no non-core rooms to measure")

    areas_by_room_id = {
        metric.room_id: float(metric.actual_area)
        for metric in floor.validation.room_areas
    }
    missing_areas = [room_id for room_id in room_ids if room_id not in areas_by_room_id]
    if missing_areas:
        raise ValueError("missing room form area: " + ", ".join(missing_areas))
    areas = {room_id: areas_by_room_id[room_id] for room_id in room_ids}
    if any(not math.isfinite(area) or area < 0 for area in areas.values()):
        raise ValueError("room form areas must be finite and non-negative")
    measured_area = sum(areas.values())
    if measured_area <= 0:
        raise ValueError("room form area must be positive")

    shapes_by_room_id = {
        metric.room_id: metric for metric in floor.validation.room_shapes
    }
    passing_room_ids: list[str] = []
    failing_room_ids: list[str] = []
    unmeasurable_room_ids: list[str] = []
    aspect_ratios: list[float] = []
    widths: list[float] = []
    for room_id in room_ids:
        shape = shapes_by_room_id.get(room_id)
        if shape is not None:
            if _is_finite(shape.measured_aspect_ratio):
                aspect_ratios.append(float(shape.measured_aspect_ratio))
            if _is_finite(shape.measured_min_width):
                widths.append(float(shape.measured_min_width))
        if shape is None or not _has_finite_applicable_measurements(shape):
            failing_room_ids.append(room_id)
            unmeasurable_room_ids.append(room_id)
            continue
        if shape.minimum_width_passed and shape.aspect_ratio_passed:
            passing_room_ids.append(room_id)
        else:
            failing_room_ids.append(room_id)

    passing_area = sum(areas[room_id] for room_id in passing_room_ids)
    return RoomFormMeasurement(
        measured_area=measured_area,
        passing_area=passing_area,
        ratio=passing_area / measured_area,
        worst_aspect_ratio=max(aspect_ratios, default=None),
        narrowest_width_m=min(widths, default=None),
        failing_room_ids=tuple(failing_room_ids),
        unmeasurable_room_ids=tuple(unmeasurable_room_ids),
    )


def _has_finite_applicable_measurements(shape: RoomShapeMetric) -> bool:
    measurements = (
        shape.measured_min_width,
        shape.required_min_width,
        shape.measured_aspect_ratio,
        shape.maximum_aspect_ratio,
    )
    if any(value is not None and not math.isfinite(value) for value in measurements):
        return False
    return not (
        shape.required_min_width is not None and shape.measured_min_width is None
    ) and not (
        shape.maximum_aspect_ratio is not None and shape.measured_aspect_ratio is None
    )


def _is_finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value)
