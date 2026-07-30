from __future__ import annotations

from dataclasses import dataclass
import math

from shapely.geometry import LineString, Polygon

from backend.app.schemas.result import GenerationResult


_PRIMARY_TYPES = {
    "office": frozenset({"open_work", "meeting", "focus"}),
    "neighborhood_commercial": frozenset({"sales"}),
}
_TOLERANCE = 1e-6


@dataclass(frozen=True)
class PrimaryDaylightMeasurement:
    total_primary_area: float
    served_primary_area: float
    ratio: float
    served_room_ids: tuple[str, ...]
    unserved_room_ids: tuple[str, ...]


def measure_primary_daylight(floor: GenerationResult) -> PrimaryDaylightMeasurement:
    primary_types = _PRIMARY_TYPES.get(floor.program.use_type, frozenset())
    primary_room_ids = tuple(
        node.node_id for node in floor.program.nodes if node.space_type in primary_types
    )
    if not primary_room_ids:
        raise ValueError("floor has no primary program area to measure")

    areas_by_room_id = {
        metric.room_id: float(metric.actual_area)
        for metric in floor.validation.room_areas
    }
    missing_areas = sorted(set(primary_room_ids) - areas_by_room_id.keys())
    if missing_areas:
        raise ValueError("missing primary room area: " + ", ".join(missing_areas))

    primary_areas = {room_id: areas_by_room_id[room_id] for room_id in primary_room_ids}
    if any(not math.isfinite(area) or area < 0 for area in primary_areas.values()):
        raise ValueError("primary room areas must be finite and non-negative")
    total_primary_area = sum(primary_areas.values())
    if total_primary_area <= 0:
        raise ValueError("primary program area must be positive")

    rooms_by_id = {room.room_id: room for room in floor.layout.rooms}
    floor_boundary = Polygon(
        floor.floor_boundary
        if floor.floor_boundary is not None
        else floor.mass.boundary_for_floor(floor.program.floor_index)
    )
    served_ids = sorted(
        room_id
        for room_id in primary_room_ids
        if _room_has_exterior_window(
            room=rooms_by_id.get(room_id),
            floor_boundary=floor_boundary,
            floor=floor,
        )
    )
    served_room_ids = tuple(served_ids)
    served_primary_area = sum(primary_areas[room_id] for room_id in served_room_ids)
    unserved_room_ids = tuple(sorted(set(primary_room_ids) - set(served_room_ids)))
    return PrimaryDaylightMeasurement(
        total_primary_area=total_primary_area,
        served_primary_area=served_primary_area,
        ratio=served_primary_area / total_primary_area,
        served_room_ids=served_room_ids,
        unserved_room_ids=unserved_room_ids,
    )


def _room_has_exterior_window(
    *, room, floor_boundary: Polygon, floor: GenerationResult
) -> bool:
    if room is None:
        return False
    room_polygon = Polygon(room.polygon)
    if (
        not room_polygon.is_valid
        or room_polygon.is_empty
        or room_polygon.area <= _TOLERANCE
        or not floor_boundary.is_valid
        or floor_boundary.is_empty
    ):
        return False
    exterior_boundary = room_polygon.boundary.intersection(floor_boundary.boundary)
    features = floor.layout.basic_design
    if features is None:
        return False
    for line in features.lines:
        if line.kind != "window" or line.host_id != room.room_id:
            continue
        window = LineString(line.points)
        if window.is_empty or window.length <= _TOLERANCE:
            continue
        if exterior_boundary.buffer(_TOLERANCE).covers(window):
            return True
    return False
