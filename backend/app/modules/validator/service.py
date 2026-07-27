from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable

from backend.app.schemas.layout import LayoutCandidate, RoomPolygon
from backend.app.schemas.metrics import RoomAreaMetric, ValidationReport, ValidationViolation
from backend.app.schemas.program import ProgramGraph
from engine.geometry import orthogonal_min_width, shared_boundary_segments
from engine.geometry.polygon import (
    Segment,
    contains_polygon,
    polygon_area,
    polygon_overlap_area,
    shared_boundary_length,
    shared_boundary_with_segments_length,
    union_intersection_area,
    validate_boundary_segments,
    validate_polygon,
)

_EPSILON = 1e-9
_POLICY_VERSION = "exact-v1"
_HARD_VIOLATION_CODES = (
    "invalid_geometry",
    "room_identity",
    "room_area",
    "boundary",
    "overlap",
    "circulation_missing",
    "circulation_identity",
    "circulation_disconnected",
    "room_inaccessible",
    "opening_identity",
    "opening_reference",
    "door_geometry",
    "door_width",
    "door_missing",
    "circulation_too_narrow",
)
_EXTERNAL_PROGRAM_ENDPOINTS = {"street"}


def validate_layout(
    layout: LayoutCandidate,
    program: ProgramGraph,
    boundary: list[tuple[float, float]],
    *,
    street_segments: list[Segment] | None = None,
    require_openings: bool = False,
    min_door_width: float = 0.8,
    min_circulation_width: float | None = None,
) -> ValidationReport:
    if not math.isfinite(min_door_width) or min_door_width <= 0:
        raise ValueError("min_door_width must be finite and positive")
    if min_circulation_width is not None and (
        not math.isfinite(min_circulation_width) or min_circulation_width <= 0
    ):
        raise ValueError("min_circulation_width must be finite and positive")
    _validate_program(program)
    validate_polygon(boundary, label="boundary")
    streets = street_segments or []
    validate_boundary_segments(boundary, streets, label="street segments")

    violations: list[ValidationViolation] = []
    penalties: dict[tuple[str, str], float] = {}

    def add_violation(code: str, subject: str, message: str, penalty: float = 1.0) -> None:
        violations.append(ValidationViolation(code=code, subject=subject, message=message))
        key = (code, subject)
        penalties[key] = max(penalties.get(key, 0.0), max(0.0, penalty))

    expected_ids = [node.node_id for node in program.nodes]
    room_counts = Counter(room.room_id for room in layout.rooms)
    expected_set = set(expected_ids)
    for room_id in expected_ids:
        count = room_counts[room_id]
        if count == 0:
            add_violation("room_identity", room_id, f"required room '{room_id}' is missing")
        elif count > 1:
            add_violation("room_identity", room_id, f"room '{room_id}' appears {count} times")
    for room_id in sorted(room_counts.keys() - expected_set):
        add_violation("room_identity", room_id, f"unexpected room '{room_id}' is present")
    circulation_counts = Counter(path.room_id for path in layout.circulation)
    for path_id, count in circulation_counts.items():
        if not path_id or count > 1:
            add_violation(
                "circulation_identity",
                path_id or "circulation",
                "circulation IDs must be non-empty and unique",
            )

    valid_rooms = _valid_shapes(layout.rooms, "room", add_violation)
    valid_circulation = _valid_shapes(layout.circulation, "circulation", add_violation)
    valid_room_ids = {id(room) for room in valid_rooms}

    room_areas, area_scores = _room_area_metrics(
        layout.rooms,
        valid_room_ids,
        program,
        add_violation,
    )
    area_score = _mean(area_scores)

    boundary_ok = True
    for kind, shapes in (("room", valid_rooms), ("circulation", valid_circulation)):
        for shape in shapes:
            if not contains_polygon(boundary, shape.polygon):
                boundary_ok = False
                add_violation(
                    "boundary",
                    shape.room_id,
                    f"{kind} '{shape.room_id}' escapes the boundary",
                )
    if len(valid_rooms) != len(layout.rooms) or len(valid_circulation) != len(layout.circulation):
        boundary_ok = False

    overlap_ok = _check_overlaps(valid_rooms, valid_circulation, add_violation)
    if len(valid_rooms) != len(layout.rooms) or len(valid_circulation) != len(layout.circulation):
        overlap_ok = False

    circulation_exists = bool(layout.circulation)
    circulation_connected = bool(valid_circulation) and _is_connected(valid_circulation)
    accessible_count = 0
    accessible_room_count = 0
    if not circulation_exists:
        add_violation(
            "circulation_missing",
            "circulation",
            "layout has no circulation polygon",
        )
    elif len(valid_circulation) > 1 and not circulation_connected:
        add_violation(
            "circulation_disconnected",
            "circulation",
            "circulation polygons are disconnected",
        )

    if valid_circulation:
        for room in valid_rooms:
            if room.room_id not in expected_set or room_counts[room.room_id] != 1:
                continue
            accessible_room_count += 1
            if any(
                shared_boundary_length(room.polygon, path.polygon) > _EPSILON
                for path in valid_circulation
            ):
                accessible_count += 1
            else:
                add_violation(
                    "room_inaccessible",
                    room.room_id,
                    f"room '{room.room_id}' has no shared wall with circulation",
                )

    if require_openings:
        _validate_openings(
            layout,
            valid_rooms,
            valid_circulation,
            expected_set,
            min_door_width,
            add_violation,
        )

    if min_circulation_width is not None:
        for path in valid_circulation:
            try:
                measured_width = orthogonal_min_width(path.polygon)
            except ValueError as error:
                add_violation("circulation_too_narrow", path.room_id, str(error))
            else:
                if measured_width + _EPSILON < min_circulation_width:
                    add_violation(
                        "circulation_too_narrow",
                        path.room_id,
                        (
                            f"circulation '{path.room_id}' width {measured_width:.3f} "
                            f"is below {min_circulation_width:.3f}"
                        ),
                    )
        if (
            len(valid_circulation) > 1
            and not _is_connected_with_minimum_junction(
                valid_circulation,
                min_circulation_width,
            )
        ):
            add_violation(
                "circulation_too_narrow",
                "circulation",
                (
                    "circulation polygons are not connected by junctions "
                    f"at least {min_circulation_width:.3f} wide"
                ),
            )

    circulation_score = _circulation_score(
        circulation_exists,
        circulation_connected,
        accessible_count,
        accessible_room_count,
    )
    adjacency_score = _adjacency_score(valid_rooms, room_counts, program, streets)
    frontage_score = _frontage_score(valid_rooms, room_counts, program, streets)
    coverage_score = _coverage_score(valid_rooms, valid_circulation, boundary)
    compactness_score = _compactness_score(valid_rooms)
    efficiency_score = _efficiency_score(valid_rooms, program)
    boundary_score = 1.0 if boundary_ok else 0.0
    overlap_score = 1.0 if overlap_ok else 0.0

    scores = [
        area_score,
        overlap_score,
        boundary_score,
        circulation_score,
        efficiency_score,
        adjacency_score,
        frontage_score,
        coverage_score,
        compactness_score,
    ]
    total_score = round(_mean(scores), 4)
    accepted = not violations
    hard_violation_count = len({violation.code for violation in violations})
    violation_score = _normalized_violation_score(
        violations,
        penalties,
        expected_room_count=len(program.nodes),
    )

    return ValidationReport(
        is_valid=accepted,
        accepted=accepted,
        hard_violation_count=hard_violation_count,
        violation_score=violation_score,
        violations=violations,
        room_areas=room_areas,
        area_score=area_score,
        overlap_score=overlap_score,
        boundary_score=boundary_score,
        circulation_score=circulation_score,
        efficiency_score=efficiency_score,
        adjacency_score=adjacency_score,
        frontage_score=frontage_score,
        coverage_score=coverage_score,
        compactness_score=compactness_score,
        total_score=total_score,
        messages=[violation.message for violation in violations],
        policy_version=_POLICY_VERSION,
        openings_checked=require_openings,
        corridor_width_checked=min_circulation_width is not None,
    )


def _validate_openings(
    layout: LayoutCandidate,
    valid_rooms: list[RoomPolygon],
    valid_circulation: list[RoomPolygon],
    expected_room_ids: set[str],
    min_door_width: float,
    add_violation,
) -> None:
    opening_counts = Counter(opening.opening_id for opening in layout.openings)
    rooms: dict[str, list[RoomPolygon]] = {}
    circulation: dict[str, list[RoomPolygon]] = {}
    for room in valid_rooms:
        rooms.setdefault(room.room_id, []).append(room)
    for path in valid_circulation:
        circulation.setdefault(path.room_id, []).append(path)
    valid_door_rooms: set[str] = set()

    for opening in layout.openings:
        if (
            not opening.opening_id
            or opening_counts[opening.opening_id] > 1
        ):
            add_violation(
                "opening_identity",
                opening.opening_id or "opening",
                "opening IDs must be non-empty and unique",
            )
            continue
        connected_rooms = [
            item
            for item in opening.connects
            if len(rooms.get(item, [])) == 1
        ]
        connected_paths = [
            item
            for item in opening.connects
            if len(circulation.get(item, [])) == 1
        ]
        if (
            opening.kind != "door"
            or len(set(opening.connects)) != 2
            or len(connected_rooms) != 1
            or len(connected_paths) != 1
        ):
            add_violation(
                "opening_reference",
                opening.opening_id,
                "door must connect one room and one circulation polygon",
            )
            continue

        room_id = connected_rooms[0]
        path_id = connected_paths[0]
        numeric_geometry = (
            _is_finite_point(opening.start)
            and _is_finite_point(opening.end)
            and _is_finite_number(opening.clear_width)
        )
        if not numeric_geometry:
            add_violation(
                "door_geometry",
                opening.opening_id,
                "door endpoints and clear width must be finite numeric values",
            )
            continue
        actual_width = math.dist(opening.start, opening.end)
        geometry_ok = (
            actual_width > _EPSILON
            and abs(actual_width - opening.clear_width) <= 1e-7
            and any(
                _segment_contains(segment, (opening.start, opening.end))
                for segment in shared_boundary_segments(
                    rooms[room_id][0].polygon,
                    circulation[path_id][0].polygon,
                )
            )
        )
        if not geometry_ok:
            add_violation(
                "door_geometry",
                opening.opening_id,
                "door geometry must match and lie within the connected shared boundary",
            )
            continue
        if opening.clear_width + _EPSILON < min_door_width:
            add_violation(
                "door_width",
                opening.opening_id,
                (
                    f"door '{opening.opening_id}' width {opening.clear_width:.3f} "
                    f"is below {min_door_width:.3f}"
                ),
            )
            continue
        valid_door_rooms.add(room_id)

    for room_id in sorted(expected_room_ids - valid_door_rooms):
        add_violation(
            "door_missing",
            room_id,
            f"room '{room_id}' has no valid circulation door",
        )


def _segment_contains(container: Segment, candidate: Segment) -> bool:
    (ax, ay), (bx, by) = container
    return all(
        abs((bx - ax) * (point[1] - ay) - (by - ay) * (point[0] - ax))
        <= _EPSILON
        and min(ax, bx) - _EPSILON <= point[0] <= max(ax, bx) + _EPSILON
        and min(ay, by) - _EPSILON <= point[1] <= max(ay, by) + _EPSILON
        for point in candidate
    )


def _is_finite_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _is_finite_point(value) -> bool:
    return (
        isinstance(value, (tuple, list))
        and len(value) == 2
        and all(_is_finite_number(coordinate) for coordinate in value)
    )


def _validate_program(program: ProgramGraph) -> None:
    node_ids = [node.node_id for node in program.nodes]
    if not node_ids:
        raise ValueError("program must contain at least one node")
    if any(not node_id for node_id in node_ids):
        raise ValueError("program node IDs must be non-empty")
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("program node IDs must be unique")

    for node in program.nodes:
        target = float(node.target_area)
        minimum = float(node.min_area) if node.min_area is not None else None
        maximum = float(node.max_area) if node.max_area is not None else None
        values = [value for value in (target, minimum, maximum) if value is not None]
        if not all(math.isfinite(value) and value > 0 for value in values):
            raise ValueError(f"program room '{node.node_id}' areas must be finite and positive")
        if minimum is not None and minimum > target:
            raise ValueError(f"program room '{node.node_id}' minimum area exceeds target")
        if maximum is not None and maximum < target:
            raise ValueError(f"program room '{node.node_id}' maximum area is below target")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError(f"program room '{node.node_id}' area range is inverted")

    allowed_endpoints = set(node_ids) | _EXTERNAL_PROGRAM_ENDPOINTS
    for edge in program.edges:
        if edge.source not in allowed_endpoints or edge.target not in allowed_endpoints:
            raise ValueError(
                f"program edge '{edge.source}->{edge.target}' has an unknown endpoint"
            )
        if edge.source == edge.target:
            raise ValueError(f"program edge '{edge.source}->{edge.target}' is a self-edge")
        weight = float(edge.weight)
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError(
                f"program edge '{edge.source}->{edge.target}' weight must be finite and positive"
            )


def _valid_shapes(
    shapes: Iterable[RoomPolygon],
    kind: str,
    add_violation,
) -> list[RoomPolygon]:
    valid: list[RoomPolygon] = []
    for shape in shapes:
        try:
            validate_polygon(shape.polygon, label=f"{kind} '{shape.room_id}'")
        except ValueError as error:
            add_violation("invalid_geometry", shape.room_id, str(error))
        else:
            valid.append(shape)
    return valid


def _room_area_metrics(
    rooms: list[RoomPolygon],
    valid_room_ids: set[int],
    program: ProgramGraph,
    add_violation,
) -> tuple[list[RoomAreaMetric], list[float]]:
    metrics: list[RoomAreaMetric] = []
    scores: list[float] = []
    for node in program.nodes:
        matching = [room for room in rooms if room.room_id == node.node_id]
        valid_matching = [room for room in matching if id(room) in valid_room_ids]
        actual_area = sum(polygon_area(room.polygon) for room in valid_matching)
        minimum = float(node.min_area) if node.min_area is not None else float(node.target_area) * 0.99
        maximum = float(node.max_area) if node.max_area is not None else float(node.target_area) * 1.01
        within_range = (
            len(matching) == 1
            and len(valid_matching) == 1
            and minimum - _EPSILON <= actual_area <= maximum + _EPSILON
        )
        metrics.append(
            RoomAreaMetric(
                room_id=node.node_id,
                target_area=float(node.target_area),
                actual_area=float(actual_area),
                min_area=minimum,
                max_area=maximum,
                within_range=within_range,
            )
        )
        target = max(abs(float(node.target_area)), 1.0)
        scores.append(round(max(0.0, 1.0 - abs(actual_area - float(node.target_area)) / target), 4))
        if len(matching) == 1 and len(valid_matching) == 1 and not within_range:
            nearest = minimum if actual_area < minimum else maximum
            add_violation(
                "room_area",
                node.node_id,
                (
                    f"room '{node.node_id}' area {actual_area:g} is outside "
                    f"[{minimum:g}, {maximum:g}]"
                ),
                abs(actual_area - nearest) / target,
            )
    return metrics, scores


def _check_overlaps(
    rooms: list[RoomPolygon],
    circulation: list[RoomPolygon],
    add_violation,
) -> bool:
    overlap_ok = True
    groups = (rooms, circulation)
    for shapes in groups:
        for left_index, left in enumerate(shapes):
            for right in shapes[left_index + 1 :]:
                area = polygon_overlap_area(left.polygon, right.polygon)
                if area > 0:
                    overlap_ok = False
                    add_violation(
                        "overlap",
                        f"{left.room_id}|{right.room_id}",
                        f"'{left.room_id}' overlaps '{right.room_id}'",
                        area / max(polygon_area(left.polygon), polygon_area(right.polygon), 1.0),
                    )
    for room in rooms:
        for path in circulation:
            area = polygon_overlap_area(room.polygon, path.polygon)
            if area > 0:
                overlap_ok = False
                add_violation(
                    "overlap",
                    f"{room.room_id}|{path.room_id}",
                    f"room '{room.room_id}' overlaps circulation '{path.room_id}'",
                    area / max(polygon_area(room.polygon), polygon_area(path.polygon), 1.0),
                )
    return overlap_ok


def _is_connected(shapes: list[RoomPolygon]) -> bool:
    reached = {0}
    pending = [0]
    while pending:
        current = pending.pop()
        for index, candidate in enumerate(shapes):
            if index in reached:
                continue
            if (
                shared_boundary_length(shapes[current].polygon, candidate.polygon) > _EPSILON
                or polygon_overlap_area(shapes[current].polygon, candidate.polygon) > _EPSILON
            ):
                reached.add(index)
                pending.append(index)
    return len(reached) == len(shapes)


def _is_connected_with_minimum_junction(
    shapes: list[RoomPolygon],
    minimum_width: float,
) -> bool:
    reached = {0}
    pending = [0]
    while pending:
        current = pending.pop()
        for index, candidate in enumerate(shapes):
            if index in reached:
                continue
            if (
                shared_boundary_length(
                    shapes[current].polygon,
                    candidate.polygon,
                )
                + _EPSILON
                >= minimum_width
            ):
                reached.add(index)
                pending.append(index)
    return len(reached) == len(shapes)


def _circulation_score(
    exists: bool,
    connected: bool,
    accessible_count: int,
    room_count: int,
) -> float:
    if not exists:
        return 0.0
    access_score = accessible_count / room_count if room_count else 0.0
    return round((1.0 + float(connected) + access_score) / 3, 4)


def _adjacency_score(
    rooms: list[RoomPolygon],
    room_counts: Counter,
    program: ProgramGraph,
    street_segments: list[Segment],
) -> float:
    room_by_id = {
        room.room_id: room
        for room in rooms
        if room_counts[room.room_id] == 1
    }
    weighted_checks: list[tuple[float, bool]] = []
    program_ids = {node.node_id for node in program.nodes}
    for edge in program.edges:
        weight = max(0.0, float(edge.weight))
        if edge.source in room_by_id and edge.target in room_by_id:
            satisfied = (
                shared_boundary_length(
                    room_by_id[edge.source].polygon,
                    room_by_id[edge.target].polygon,
                )
                > _EPSILON
            )
            weighted_checks.append((weight, satisfied))
        elif edge.source in room_by_id and edge.target == "street":
            satisfied = (
                shared_boundary_with_segments_length(
                    room_by_id[edge.source].polygon,
                    street_segments,
                )
                > _EPSILON
            )
            weighted_checks.append((weight, satisfied))
        elif edge.target in room_by_id and edge.source == "street":
            satisfied = (
                shared_boundary_with_segments_length(
                    room_by_id[edge.target].polygon,
                    street_segments,
                )
                > _EPSILON
            )
            weighted_checks.append((weight, satisfied))
        elif edge.source in program_ids and edge.target in program_ids:
            weighted_checks.append((weight, False))
    return _weighted_score(weighted_checks)


def _frontage_score(
    rooms: list[RoomPolygon],
    room_counts: Counter,
    program: ProgramGraph,
    street_segments: list[Segment],
) -> float:
    rooms_by_id = {
        room.room_id: room
        for room in rooms
        if room_counts[room.room_id] == 1
    }
    required = [node for node in program.nodes if node.frontage_required]
    if not required:
        return 1.0
    satisfied = sum(
        1
        for node in required
        if node.node_id in rooms_by_id
        and shared_boundary_with_segments_length(
            rooms_by_id[node.node_id].polygon,
            street_segments,
        )
        > _EPSILON
    )
    return round(satisfied / len(required), 4)


def _coverage_score(
    rooms: list[RoomPolygon],
    circulation: list[RoomPolygon],
    boundary: list[tuple[float, float]],
) -> float:
    boundary_area = polygon_area(boundary)
    if boundary_area <= 0:
        return 0.0
    covered_area = union_intersection_area(
        boundary,
        [shape.polygon for shape in [*rooms, *circulation]],
    )
    return round(min(1.0, covered_area / boundary_area), 4)


def _compactness_score(rooms: list[RoomPolygon]) -> float:
    scores: list[float] = []
    for room in rooms:
        vertices = room.polygon[:-1] if room.polygon[:1] == room.polygon[-1:] else room.polygon
        perimeter = sum(
            math.hypot(
                vertices[(index + 1) % len(vertices)][0] - point[0],
                vertices[(index + 1) % len(vertices)][1] - point[1],
            )
            for index, point in enumerate(vertices)
        )
        score = 4 * math.pi * polygon_area(room.polygon) / (perimeter * perimeter)
        scores.append(min(1.0, score))
    return round(_mean(scores), 4)


def _efficiency_score(rooms: list[RoomPolygon], program: ProgramGraph) -> float:
    rentable_types = {"shop_unit", "office_area"}
    total = sum(polygon_area(room.polygon) for room in rooms)
    rentable = sum(
        polygon_area(room.polygon)
        for room in rooms
        if room.space_type in rentable_types
    )
    if total <= 0:
        return 0.0
    ratio = rentable / total
    target = 0.72 if program.use_type == "neighborhood_commercial" else 0.78
    return round(max(0.0, 1.0 - abs(target - ratio)), 4)


def _weighted_score(checks: list[tuple[float, bool]]) -> float:
    total_weight = sum(weight for weight, _ in checks)
    if total_weight <= 0:
        return 1.0
    satisfied = sum(weight for weight, result in checks if result)
    return round(satisfied / total_weight, 4)


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _normalized_violation_score(
    violations: list[ValidationViolation],
    penalties: dict[tuple[str, str], float],
    *,
    expected_room_count: int,
) -> float:
    subjects_by_code: dict[str, set[str]] = {
        code: {
            violation.subject
            for violation in violations
            if violation.code == code
        }
        for code in _HARD_VIOLATION_CODES
    }
    room_denominator = max(1, expected_room_count)
    gate_penalties: list[float] = []
    for code in _HARD_VIOLATION_CODES:
        subjects = subjects_by_code[code]
        if not subjects:
            gate_penalties.append(0.0)
        elif code in {"room_identity", "room_inaccessible"}:
            gate_penalties.append(min(1.0, len(subjects) / room_denominator))
        elif code == "room_area":
            penalty = sum(penalties[(code, subject)] for subject in subjects)
            gate_penalties.append(min(1.0, penalty / room_denominator))
        else:
            gate_penalties.append(1.0)
    return round(sum(gate_penalties) / len(_HARD_VIOLATION_CODES), 4)
