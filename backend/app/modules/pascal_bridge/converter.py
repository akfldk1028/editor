"""Convert a PLANM floor-geometry artifact into a Pascal `apply_floor_plan` plan.

PLANM describes an opening as a world-space segment shared by two rooms; Pascal
places one by naming a wall (a polygon edge index) and a position `t` along it.
The bulk of this module is that translation — projecting each opening onto the
owning room's edges and reporting the ones that do not land on any.

Pure functions only: no filesystem, no network. The adapter and the router own
those.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

Point = tuple[float, float]

#: PLANM space types that map onto a Pascal room type the furnishing pass knows.
#: Anything absent stays untyped, which means Pascal builds the room but places
#: no furniture in it — better than mislabelling a retail floor as a bedroom.
SPACE_TYPE_TO_PASCAL: dict[str, str] = {
    "corridor": "hallway",
    "hallway": "hallway",
    "lobby": "entry",
    "entry": "entry",
    "entrance": "entry",
    "toilet": "bathroom",
    "restroom": "bathroom",
    "bathroom": "bathroom",
    "wc": "bathroom",
    "kitchen": "kitchen",
    "pantry": "kitchen",
    "storage": "storage",
    "store": "storage",
    "warehouse": "storage",
    "bedroom": "bedroom",
    "living": "living",
    "lounge": "living",
    "dining": "dining",
    "laundry": "laundry",
}

#: Circulation is never furnished — corridors carry travel routes, not sofas.
_UNFURNISHED_CATEGORIES = {"circulation"}

_EDGE_TOLERANCE_M = 0.35


@dataclass
class ConversionResult:
    plan: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    #: Openings that could not be attached to any wall, by opening id.
    unplaced_openings: list[str] = field(default_factory=list)


def _midpoint(start: Sequence[float], end: Sequence[float]) -> Point:
    return ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)


def _project_onto_edge(point: Point, a: Point, b: Point) -> tuple[float, float]:
    """Return (t, distance) of `point` against segment a→b, t clamped to 0..1."""
    dx = b[0] - a[0]
    dz = b[1] - a[1]
    length_sq = dx * dx + dz * dz
    if length_sq == 0:
        return 0.0, ((point[0] - a[0]) ** 2 + (point[1] - a[1]) ** 2) ** 0.5
    raw_t = ((point[0] - a[0]) * dx + (point[1] - a[1]) * dz) / length_sq
    t = min(1.0, max(0.0, raw_t))
    nearest = (a[0] + dx * t, a[1] + dz * t)
    distance = ((point[0] - nearest[0]) ** 2 + (point[1] - nearest[1]) ** 2) ** 0.5
    return t, distance


def assign_opening_to_edge(
    polygon: Sequence[Sequence[float]],
    start: Sequence[float],
    end: Sequence[float],
    *,
    tolerance: float = _EDGE_TOLERANCE_M,
) -> tuple[int, float] | None:
    """Find which polygon edge an opening sits on.

    Returns `(edge_index, t)` for the closest edge within `tolerance`, or None
    when the opening does not lie on this room's outline at all — which happens
    for openings recorded against the neighbouring room.
    """
    midpoint = _midpoint(start, end)
    best: tuple[int, float] | None = None
    best_distance = tolerance
    count = len(polygon)
    for index in range(count):
        a = (float(polygon[index][0]), float(polygon[index][1]))
        b = (
            float(polygon[(index + 1) % count][0]),
            float(polygon[(index + 1) % count][1]),
        )
        t, distance = _project_onto_edge(midpoint, a, b)
        if distance < best_distance:
            best_distance = distance
            best = (index, t)
    return best


def _polygon(points: Any) -> list[list[float]]:
    """Coerce a polygon, dropping any point that is not a finite pair.

    Geometry written by `layout_geometry` is already clean, but this also takes
    plans handed in by a caller, so a bad coordinate must cost one point rather
    than raise out of the whole conversion.
    """
    result: list[list[float]] = []
    for value in points or ():
        try:
            x, z = value
            x = float(x)
            z = float(z)
        except (TypeError, ValueError):
            continue
        if math.isfinite(x) and math.isfinite(z):
            result.append([x, z])
    return result


def _pascal_room_type(space_type: str) -> str | None:
    return SPACE_TYPE_TO_PASCAL.get(space_type.lower())


def _room_name(room: dict[str, Any]) -> str:
    room_id = str(room.get("room_id", "room"))
    return room_id.replace("_", " ").strip() or room_id


def convert_floor_geometry(
    geometry: dict[str, Any],
    *,
    level_id: str | None = None,
    furnish: bool = True,
    level_height: float | None = None,
    plan_name: str | None = None,
) -> ConversionResult:
    """Convert one floor-geometry artifact into a single-level Pascal plan."""
    return convert_floors(
        [geometry],
        level_ids=[level_id] if level_id else None,
        furnish=furnish,
        level_height=level_height,
        plan_name=plan_name,
    )


def convert_floors(
    geometries: Iterable[dict[str, Any]],
    *,
    level_ids: Sequence[str | None] | None = None,
    furnish: bool = True,
    level_height: float | None = None,
    plan_name: str | None = None,
) -> ConversionResult:
    """Convert several floors, lowest first, into one Pascal plan."""
    warnings: list[str] = []
    unplaced: list[str] = []
    levels: list[dict[str, Any]] = []

    ordered = sorted(geometries, key=lambda g: int(g.get("floor_index", 0)))
    for position, geometry in enumerate(ordered):
        floor_index = int(geometry.get("floor_index", position + 1))
        rooms_payload: list[dict[str, Any]] = []

        # Openings are shared between two rooms; attach each to whichever room's
        # outline it actually lies on, so it is cut exactly once.
        openings = list(geometry.get("openings", []))
        claimed: set[str] = set()

        for room in geometry.get("rooms", []):
            polygon = _polygon(room.get("polygon"))
            if len(polygon) < 3:
                warnings.append(
                    f"floor {floor_index}: room {room.get('room_id')} skipped — "
                    f"{len(polygon)} points, need at least 3."
                )
                continue

            category = str(room.get("category", "room"))
            space_type = str(room.get("space_type", ""))
            room_type = _pascal_room_type(space_type)

            room_openings: list[dict[str, Any]] = []
            for index, opening in enumerate(openings):
                # Key on position as well as id: geometry with blank ids would
                # otherwise have its first opening claim every later one.
                opening_key = f"{index}:{opening.get('opening_id', '')}"
                if opening_key in claimed:
                    continue
                connects = [str(c) for c in opening.get("connects", ())]
                if connects and str(room.get("room_id")) not in connects:
                    continue
                placed = assign_opening_to_edge(
                    polygon, opening.get("start", (0, 0)), opening.get("end", (0, 0))
                )
                if placed is None:
                    continue
                edge_index, t = placed
                claimed.add(opening_key)
                kind = "door" if str(opening.get("kind", "door")) != "window" else "window"
                entry: dict[str, Any] = {
                    "kind": kind,
                    "wall": edge_index,
                    "t": round(t, 4),
                }
                clear_width = opening.get("clear_width")
                if clear_width:
                    entry["width"] = float(clear_width)
                room_openings.append(entry)

            payload: dict[str, Any] = {
                "name": _room_name(room),
                "polygon": polygon,
                "openings": room_openings,
            }
            if room_type is not None:
                payload["type"] = room_type
                payload["furnish"] = furnish and category not in _UNFURNISHED_CATEGORIES
            rooms_payload.append(payload)

        for index, opening in enumerate(openings):
            opening_id = str(opening.get("opening_id", ""))
            if f"{index}:{opening.get('opening_id', '')}" not in claimed:
                unplaced.append(opening_id)
                warnings.append(
                    f"floor {floor_index}: opening {opening_id} did not land on any "
                    f"room outline and was dropped."
                )

        if not rooms_payload:
            warnings.append(f"floor {floor_index}: no usable rooms, level skipped.")
            continue

        level: dict[str, Any] = {"rooms": rooms_payload, "label": f"Floor {floor_index}"}
        if level_ids is not None and position < len(level_ids) and level_ids[position]:
            level["levelId"] = level_ids[position]
        if level_height is not None:
            level["height"] = level_height
        levels.append(level)

    plan: dict[str, Any] = {"levels": levels}
    name = plan_name or _default_plan_name(ordered)
    if name:
        plan["name"] = name
    return ConversionResult(plan=plan, warnings=warnings, unplaced_openings=unplaced)


def _default_plan_name(geometries: Sequence[dict[str, Any]]) -> str | None:
    for geometry in geometries:
        project = geometry.get("project_id")
        candidate = geometry.get("candidate_id")
        if project or candidate:
            return " / ".join(str(part) for part in (project, candidate) if part)
    return None


__all__ = [
    "ConversionResult",
    "SPACE_TYPE_TO_PASCAL",
    "assign_opening_to_edge",
    "convert_floor_geometry",
    "convert_floors",
]
