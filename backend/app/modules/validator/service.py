from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable

from backend.app.schemas.layout import (
    BasicDesignFeatures,
    LayoutCandidate,
    PlanElement,
    PlanLine,
    RoomPolygon,
)
from backend.app.schemas.metrics import (
    BasicDesignMetric,
    RoomAreaMetric,
    RoomShapeMetric,
    ValidationReport,
    ValidationViolation,
)
from backend.app.schemas.program import ProgramGraph
from engine.geometry import (
    bounding_box_aspect_ratio,
    orthogonal_min_width,
    shared_boundary_segments,
)
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
    "room_min_width",
    "room_aspect_ratio",
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
    "basic_design_missing",
    "basic_design_identity",
    "basic_design_reference",
    "basic_design_geometry",
    "core_geometry",
    "core_subspace_containment",
    "core_subspace_overlap",
    "vertical_missing",
    "protected_exit_count",
    "protected_exit_reference",
    "protected_exit_geometry",
    "protected_exit_width",
    "protected_exit_separation",
    "egress_route_missing",
    "egress_route_reference",
    "egress_route_geometry",
    "column_boundary",
    "column_conflict",
    "structure_missing",
    "window_reference",
    "window_geometry",
    "window_conflict",
    "window_missing",
    "entrance_missing",
    "entrance_geometry",
    "placed_object_reference",
    "placed_object_containment",
    "placed_object_overlap",
    "placed_object_missing",
    "dimension_reference",
    "dimension_value",
    "dimension_missing",
    "site_missing",
    "site_geometry",
)
_EXTERNAL_PROGRAM_ENDPOINTS = {"street"}
_BASIC_DESIGN_POLICY = "concept-basic-v1"
_ELEMENT_KINDS = {
    "vertical": {"stair", "elevator", "lobby", "shaft"},
    "structure": {"column"},
    "furniture": {
        "workstation",
        "meeting_table",
        "reception_desk",
        "focus_desk",
        "sales_shelf",
        "checkout_counter",
        "stock_rack",
        "staff_table",
    },
    "fixture": {
        "pantry_counter",
        "sink",
        "wc",
        "lavatory",
        "it_rack",
        "utility_equipment",
    },
}
_LINE_KINDS = {
    "egress": {"protected_exit", "egress_route"},
    "envelope": {"entrance", "window"},
    "structure": {"grid"},
    "dimension": {"overall_width", "overall_depth", "circulation_width"},
    "site": {"street", "north_arrow", "scale_line"},
}
_REQUIRED_OBJECT_KINDS = {
    "open_work": {"workstation"},
    "meeting": {"meeting_table"},
    "reception": {"reception_desk"},
    "focus": {"focus_desk"},
    "pantry": {"pantry_counter", "sink"},
    "restroom": {"wc", "lavatory"},
    "it_storage": {"it_rack"},
    "sales": {"sales_shelf"},
    "checkout": {"checkout_counter"},
    "stock": {"stock_rack"},
    "staff": {"staff_table"},
    "utility": {"utility_equipment"},
}


def validate_layout(
    layout: LayoutCandidate,
    program: ProgramGraph,
    boundary: list[tuple[float, float]],
    *,
    street_segments: list[Segment] | None = None,
    require_openings: bool = False,
    min_door_width: float = 0.8,
    min_circulation_width: float | None = None,
    require_basic_design: bool = False,
    min_protected_exit_width: float = 0.9,
    min_exit_separation: float = 3.0,
) -> ValidationReport:
    if not math.isfinite(min_door_width) or min_door_width <= 0:
        raise ValueError("min_door_width must be finite and positive")
    if min_circulation_width is not None and (
        not math.isfinite(min_circulation_width) or min_circulation_width <= 0
    ):
        raise ValueError("min_circulation_width must be finite and positive")
    for name, value in (
        ("min_protected_exit_width", min_protected_exit_width),
        ("min_exit_separation", min_exit_separation),
    ):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
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
        else:
            room = next(item for item in layout.rooms if item.room_id == room_id)
            expected_type = next(
                node.space_type for node in program.nodes if node.node_id == room_id
            )
            if room.space_type != expected_type:
                add_violation(
                    "room_identity",
                    room_id,
                    (
                        f"room '{room_id}' space type '{room.space_type}' does not match "
                        f"program type '{expected_type}'"
                    ),
                )
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
    room_shapes = _room_shape_metrics(
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

    basic_design_metric: BasicDesignMetric | None = None
    if require_basic_design:
        basic_design_metric = _validate_basic_design(
            layout,
            boundary,
            streets,
            program,
            min_protected_exit_width,
            min_exit_separation,
            add_violation,
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
        room_shapes=room_shapes,
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
        basic_design_checked=require_basic_design,
        basic_design=basic_design_metric,
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


def _validate_basic_design(
    layout: LayoutCandidate,
    boundary: list[tuple[float, float]],
    streets: list[Segment],
    program: ProgramGraph,
    min_exit_width: float,
    min_exit_separation: float,
    add_violation,
) -> BasicDesignMetric:
    features = layout.basic_design
    program_space_types = {
        node.node_id: node.space_type
        for node in program.nodes
    }
    occupied_rooms = {
        room.room_id: room
        for room in layout.rooms
        if (
            room.room_id in program_space_types
            and program_space_types[room.room_id] != "core"
        )
    }
    geometric_occupied_rooms = {
        room_id: room
        for room_id, room in occupied_rooms.items()
        if _is_valid_polygon(room.polygon)
    }
    geometric_circulation = [
        path for path in layout.circulation if _is_valid_polygon(path.polygon)
    ]
    if features is None:
        add_violation(
            "basic_design_missing",
            layout.candidate_id,
            "strict concept basic-design validation requires a feature bundle",
        )
        return _basic_design_metric(
            None,
            occupied_rooms,
            missing_required_kinds=("basic_design",),
        )

    missing_kinds: set[str] = set()
    if features.policy_version != _BASIC_DESIGN_POLICY:
        add_violation(
            "basic_design_identity",
            layout.candidate_id,
            f"unsupported basic-design policy '{features.policy_version}'",
        )

    all_ids = [
        *(element.element_id for element in features.elements),
        *(line.line_id for line in features.lines),
    ]
    id_counts = Counter(all_ids)
    for feature_id, count in id_counts.items():
        if not feature_id or count != 1:
            add_violation(
                "basic_design_identity",
                feature_id or "basic-design-feature",
                "basic-design feature IDs must be non-empty and unique across all collections",
            )

    valid_elements: dict[str, PlanElement] = {}
    for element in features.elements:
        if element.kind not in _ELEMENT_KINDS.get(element.category, set()):
            add_violation(
                "basic_design_identity",
                element.element_id,
                f"invalid element category/kind '{element.category}/{element.kind}'",
            )
        try:
            validate_polygon(element.footprint, label=f"element '{element.element_id}'")
        except ValueError as error:
            add_violation("basic_design_geometry", element.element_id, str(error))
        else:
            if id_counts[element.element_id] == 1:
                valid_elements[element.element_id] = element

    valid_lines: dict[str, PlanLine] = {}
    for line in features.lines:
        if line.kind not in _LINE_KINDS.get(line.category, set()):
            add_violation(
                "basic_design_identity",
                line.line_id,
                f"invalid line category/kind '{line.category}/{line.kind}'",
            )
        geometry_code = _semantic_line_geometry_violation(line)
        if geometry_code is not None:
            add_violation(
                geometry_code,
                line.line_id,
                (
                    "semantic segment lines require exactly two finite, "
                    "positive-length points and matching clear width"
                ),
            )
            if line.kind == "protected_exit" and (
                not _is_finite_number(line.clear_width)
                or line.clear_width + _EPSILON < min_exit_width
            ):
                add_violation(
                    "protected_exit_width",
                    line.line_id,
                    f"protected exit clear width must be at least {min_exit_width:.3f}",
                )
        elif id_counts[line.line_id] == 1:
            valid_lines[line.line_id] = line

    cores = [
        room
        for room in layout.rooms
        if program_space_types.get(room.room_id) == "core"
    ]
    core = cores[0] if len(cores) == 1 and _is_axis_aligned_rectangle(cores[0].polygon) else None
    if core is None:
        add_violation(
            "core_geometry",
            "core",
            "strict basic design requires exactly one rectangular core room",
        )
    core_id = core.room_id if core is not None else None

    for element in features.elements:
        if element.category == "vertical":
            expected = core_id is not None and element.host_id == core_id
        elif element.category == "structure":
            expected = element.host_id == "floor"
        elif element.category in {"furniture", "fixture"}:
            expected = element.host_id in occupied_rooms
        else:
            expected = False
        if not expected:
            code = (
                "placed_object_reference"
                if element.category in {"furniture", "fixture"}
                else "basic_design_reference"
            )
            add_violation(code, element.element_id, "element host does not resolve to its expected owner")

    for line in features.lines:
        if line.kind == "protected_exit":
            target = valid_elements.get(line.target_id or "")
            valid_reference = (
                core_id is not None
                and line.host_id == core_id
                and target is not None
                and target.category == "vertical"
                and target.kind == "stair"
                and target.host_id == core_id
            )
            code = "protected_exit_reference"
        elif line.kind == "egress_route":
            valid_reference = (
                line.host_id in occupied_rooms
                and line.target_id in valid_lines
                and valid_lines[line.target_id].kind == "protected_exit"
            )
            code = "egress_route_reference"
        elif line.kind in {"window", "entrance"}:
            valid_reference = line.host_id in occupied_rooms and line.target_id is None
            code = "window_reference" if line.kind == "window" else "entrance_geometry"
        else:
            valid_reference = line.host_id is None and line.target_id is None
            code = "basic_design_reference"
        if not valid_reference:
            add_violation(code, line.line_id, "line references do not resolve to the expected owner or target")

    vertical = [
        element
        for element in valid_elements.values()
        if element.category == "vertical"
    ]
    vertical_counts = Counter(element.kind for element in vertical)
    expected_vertical = {"stair": 2, "elevator": 1, "lobby": 1, "shaft": 1}
    if any(vertical_counts[kind] != count for kind, count in expected_vertical.items()):
        add_violation(
            "vertical_missing",
            "core",
            "core requires exactly two stairs and one elevator, lobby, and shaft",
        )
        missing_kinds.update(
            f"vertical:{kind}"
            for kind, count in expected_vertical.items()
            if vertical_counts[kind] < count
        )
    if core is not None:
        for element in vertical:
            if element.host_id == core.room_id and not contains_polygon(
                core.polygon,
                element.footprint,
            ):
                add_violation(
                    "core_subspace_containment",
                    element.element_id,
                    "vertical footprint must remain inside the core",
                )
        for index, left in enumerate(vertical):
            for right in vertical[index + 1 :]:
                if polygon_overlap_area(left.footprint, right.footprint) > 0:
                    add_violation(
                        "core_subspace_overlap",
                        f"{left.element_id}|{right.element_id}",
                        "vertical core footprints cannot positively overlap",
                    )

    exits = [
        line
        for line in valid_lines.values()
        if line.category == "egress" and line.kind == "protected_exit"
    ]
    if len(exits) != 2:
        add_violation(
            "protected_exit_count",
            "core",
            f"strict basic design requires exactly two protected exits, found {len(exits)}",
        )
        if len(exits) < 2:
            missing_kinds.add("egress:protected_exit")
    if len(exits) == 2 and len({line.target_id for line in exits}) != 2:
        add_violation(
            "protected_exit_reference",
            "core",
            "protected exits must reference two distinct stair elements",
        )
    shared_core_boundaries = (
        [
            segment
            for path in geometric_circulation
            for segment in shared_boundary_segments(core.polygon, path.polygon)
        ]
        if core is not None
        else []
    )
    for exit_line in exits:
        if exit_line.host_id != core_id:
            continue
        actual_width = _polyline_length(exit_line.points)
        if not any(
            _segment_contains(segment, (exit_line.points[0], exit_line.points[-1]))
            for segment in shared_core_boundaries
        ) or abs(actual_width - (exit_line.clear_width or 0.0)) > 1e-7:
            add_violation(
                "protected_exit_geometry",
                exit_line.line_id,
                "protected exit must match its width on a real core/circulation shared boundary",
            )
        if (
            not _is_finite_number(exit_line.clear_width)
            or exit_line.clear_width + _EPSILON < min_exit_width
        ):
            add_violation(
                "protected_exit_width",
                exit_line.line_id,
                f"protected exit clear width must be at least {min_exit_width:.3f}",
            )
    exit_separation = _exit_separation(exits)
    if len(exits) == 2 and (
        exit_separation is None or exit_separation + _EPSILON < min_exit_separation
    ):
        add_violation(
            "protected_exit_separation",
            "core",
            f"protected exit midpoints must be separated by at least {min_exit_separation:.3f}",
        )

    doors_by_room = _door_midpoints(layout, geometric_circulation)
    routes = [
        line
        for line in valid_lines.values()
        if line.category == "egress" and line.kind == "egress_route"
    ]
    valid_exit_ids = {line.line_id for line in exits}
    route_targets_by_room: dict[str, set[str]] = {}
    for route in routes:
        if route.host_id not in occupied_rooms or route.target_id not in valid_exit_ids:
            continue
        route_targets_by_room.setdefault(route.host_id, set()).add(route.target_id)
        door_midpoint = doors_by_room.get(route.host_id)
        exit_midpoint = _line_midpoint(valid_lines[route.target_id])
        if (
            door_midpoint is None
            or not _points_equal(route.points[0], door_midpoint)
            or not _points_equal(route.points[-1], exit_midpoint)
            or not _egress_route_in_circulation(
                route.points,
                geometric_circulation,
            )
        ):
            add_violation(
                "egress_route_geometry",
                route.line_id,
                (
                    "egress route must be an orthogonal polyline from the real "
                    "room-door midpoint to its referenced exit midpoint, with "
                    "every segment inside the circulation union"
                ),
            )
    for room_id in occupied_rooms:
        if len(route_targets_by_room.get(room_id, set())) < 2:
            add_violation(
                "egress_route_missing",
                room_id,
                "occupied room requires routes to two distinct protected exits",
            )
            missing_kinds.add(f"egress:route:{room_id}")

    columns = [
        element
        for element in valid_elements.values()
        if element.category == "structure" and element.kind == "column"
    ]
    grids = [
        line
        for line in valid_lines.values()
        if line.category == "structure" and line.kind == "grid"
    ]
    if not columns or not _has_orthogonal_grid(grids):
        add_violation(
            "structure_missing",
            "structure",
            "at least one column and orthogonal grid lines are required",
        )
        if not columns:
            missing_kinds.add("structure:column")
        if not _has_orthogonal_grid(grids):
            missing_kinds.add("structure:grid")
    protected_segments = [
        (line.points[0], line.points[-1])
        for line in exits
    ]
    door_segments = [(opening.start, opening.end) for opening in layout.openings]
    for column in columns:
        if not contains_polygon(boundary, column.footprint):
            add_violation(
                "column_boundary",
                column.element_id,
                "column footprint must remain inside the floor boundary",
            )
        conflicts_space = (
            core is not None
            and polygon_overlap_area(column.footprint, core.polygon) > 0
        ) or any(
            polygon_overlap_area(column.footprint, path.polygon) > 0
            for path in geometric_circulation
        )
        conflicts_opening = any(
            _polygon_intersects_segment(column.footprint, segment)
            for segment in (*door_segments, *protected_segments)
        )
        if conflicts_space or conflicts_opening:
            add_violation(
                "column_conflict",
                column.element_id,
                "column conflicts with core, circulation, a room door, or a protected exit",
            )

    windows = [
        line
        for line in valid_lines.values()
        if line.category == "envelope" and line.kind == "window"
    ]
    entrances = [
        line
        for line in valid_lines.values()
        if line.category == "envelope" and line.kind == "entrance"
    ]
    perimeter_rooms = {
        room_id
        for room_id, room in geometric_occupied_rooms.items()
        if _exterior_segments(room.polygon, boundary)
    }
    valid_window_hosts: set[str] = set()
    for window in windows:
        room = geometric_occupied_rooms.get(window.host_id or "")
        if room is None:
            continue
        segment = (window.points[0], window.points[-1])
        if not any(
            _segment_contains(exterior, segment)
            for exterior in _exterior_segments(room.polygon, boundary)
        ):
            add_violation(
                "window_geometry",
                window.line_id,
                "window must lie on the referenced room's real exterior boundary",
            )
            continue
        valid_window_hosts.add(room.room_id)
        if any(_collinear_overlap_length(segment, (item.points[0], item.points[-1])) > 0 for item in entrances):
            add_violation(
                "window_conflict",
                window.line_id,
                "window cannot overlap a commercial entrance",
            )
    for room_id in sorted(perimeter_rooms - valid_window_hosts):
        add_violation(
            "window_missing",
            room_id,
            "occupied perimeter room requires a valid exterior window",
        )
        missing_kinds.add(f"envelope:window:{room_id}")

    if program.use_type == "neighborhood_commercial":
        if len(entrances) != 1:
            add_violation(
                "entrance_missing",
                "sales",
                f"commercial floor requires exactly one entrance, found {len(entrances)}",
            )
            missing_kinds.add("envelope:entrance")
        sales = next(
            (
                room
                for room in geometric_occupied_rooms.values()
                if program_space_types.get(room.room_id) == "sales"
            ),
            None,
        )
        for entrance in entrances:
            segment = (entrance.points[0], entrance.points[-1])
            if (
                sales is None
                or entrance.host_id != sales.room_id
                or not _segment_on_polygon_boundary(segment, sales.polygon)
                or not any(_segment_contains(street, segment) for street in streets)
            ):
                add_violation(
                    "entrance_geometry",
                    entrance.line_id,
                    "commercial entrance must lie on both the sales-room and supplied street boundary",
                )

    placed = [
        element
        for element in valid_elements.values()
        if element.category in {"furniture", "fixture"}
    ]
    for element in placed:
        room = geometric_occupied_rooms.get(element.host_id)
        if room is None:
            continue
        if not contains_polygon(room.polygon, element.footprint):
            add_violation(
                "placed_object_containment",
                element.element_id,
                "placed object must remain inside its host room",
            )
    for index, left in enumerate(placed):
        for right in placed[index + 1 :]:
            if (
                left.host_id == right.host_id
                and polygon_overlap_area(left.footprint, right.footprint) > 0
            ):
                add_violation(
                    "placed_object_overlap",
                    f"{left.element_id}|{right.element_id}",
                    "placed objects in the same room cannot positively overlap",
                )
    for room_id, room in occupied_rooms.items():
        actual_kinds = {
            element.kind for element in placed if element.host_id == room_id
        }
        required_kinds = _REQUIRED_OBJECT_KINDS.get(
            program_space_types[room_id],
            set(),
        )
        for kind in sorted(required_kinds - actual_kinds):
            add_violation(
                "placed_object_missing",
                room_id,
                f"room '{room_id}' requires placed object kind '{kind}'",
            )
            missing_kinds.add(f"object:{room_id}:{kind}")

    _validate_dimensions_and_site(
        valid_lines,
        boundary,
        geometric_circulation,
        streets,
        missing_kinds,
        add_violation,
    )
    return _basic_design_metric(
        features,
        occupied_rooms,
        missing_required_kinds=tuple(sorted(missing_kinds)),
    )


def _validate_dimensions_and_site(
    valid_lines: dict[str, PlanLine],
    boundary: list[tuple[float, float]],
    circulation: list[RoomPolygon],
    streets: list[Segment],
    missing_kinds: set[str],
    add_violation,
) -> None:
    min_x, min_y, max_x, max_y = _bounds(boundary)
    expected_values = {
        "overall_width": max_x - min_x,
        "overall_depth": max_y - min_y,
    }
    try:
        expected_values["circulation_width"] = min(
            orthogonal_min_width(path.polygon)
            for path in circulation
        )
    except (ValueError, TypeError):
        expected_values["circulation_width"] = math.nan
    dimension_lines = [
        line
        for line in valid_lines.values()
        if line.category == "dimension"
    ]
    for kind, expected in expected_values.items():
        matching = [line for line in dimension_lines if line.kind == kind]
        if len(matching) != 1:
            add_violation(
                "dimension_missing",
                kind,
                f"exactly one '{kind}' dimension is required",
            )
            missing_kinds.add(f"dimension:{kind}")
            continue
        measured = matching[0].measured_value
        if (
            not _is_finite_number(measured)
            or not math.isfinite(expected)
            or abs(measured - expected) > 1e-7
        ):
            add_violation(
                "dimension_value",
                matching[0].line_id,
                f"stored '{kind}' value does not match recomputed geometry",
            )

    site_lines = [
        line for line in valid_lines.values() if line.category == "site"
    ]
    for kind in ("street", "north_arrow", "scale_line"):
        matching = [line for line in site_lines if line.kind == kind]
        if len(matching) != 1:
            add_violation(
                "site_missing",
                kind,
                f"exactly one site '{kind}' line is required",
            )
            missing_kinds.add(f"site:{kind}")
            continue
        line = matching[0]
        if kind == "street":
            segment = (line.points[0], line.points[-1])
            if len(streets) != 1 or not _same_segment(segment, streets[0]):
                add_violation(
                    "site_geometry",
                    line.line_id,
                    "site street line must equal the supplied street edge",
                )
        elif kind == "scale_line":
            actual = _polyline_length(line.points)
            if (
                not _is_finite_number(line.measured_value)
                or abs(actual - line.measured_value) > 1e-7
            ):
                add_violation(
                    "site_geometry",
                    line.line_id,
                    "scale-line stored value must match its geometry",
                )

    known_dimension_kinds = set(expected_values)
    for line in dimension_lines:
        if line.kind not in known_dimension_kinds or line.measured_value is None:
            add_violation(
                "dimension_reference",
                line.line_id,
                "dimension line must have a known kind and measured value",
            )


def _basic_design_metric(
    features: BasicDesignFeatures | None,
    occupied_rooms: dict[str, RoomPolygon],
    *,
    missing_required_kinds: tuple[str, ...],
) -> BasicDesignMetric:
    elements = features.elements if features is not None else ()
    lines = features.lines if features is not None else ()
    exits = [line for line in lines if line.kind == "protected_exit"]
    exit_ids = {line.line_id for line in exits}
    routes = [line for line in lines if line.kind == "egress_route"]
    route_counts = [
        len(
            {
                line.target_id
                for line in routes
                if line.host_id == room_id and line.target_id in exit_ids
            }
        )
        for room_id in occupied_rooms
    ]
    widths = [
        float(line.clear_width)
        for line in exits
        if _is_finite_number(line.clear_width)
    ]
    return BasicDesignMetric(
        policy_version=features.policy_version if features is not None else "missing",
        stair_count=sum(element.kind == "stair" for element in elements),
        elevator_count=sum(element.kind == "elevator" for element in elements),
        lobby_count=sum(element.kind == "lobby" for element in elements),
        shaft_count=sum(element.kind == "shaft" for element in elements),
        exit_count=len(exits),
        route_count=len(routes),
        grid_line_count=sum(line.kind == "grid" for line in lines),
        column_count=sum(element.kind == "column" for element in elements),
        window_count=sum(line.kind == "window" for line in lines),
        entrance_count=sum(line.kind == "entrance" for line in lines),
        furniture_count=sum(element.category == "furniture" for element in elements),
        fixture_count=sum(element.category == "fixture" for element in elements),
        dimension_count=sum(line.category == "dimension" for line in lines),
        min_exit_width=min(widths) if widths else None,
        exit_separation=_exit_separation(exits),
        min_routes_per_room=min(route_counts) if route_counts else 0,
        missing_required_kinds=missing_required_kinds,
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


def _semantic_line_geometry_violation(line: PlanLine) -> str | None:
    if line.kind == "protected_exit":
        code = "protected_exit_geometry"
    elif line.kind == "window":
        code = "window_geometry"
    elif line.kind == "entrance":
        code = "entrance_geometry"
    else:
        code = "basic_design_geometry"

    if (
        len(line.points) < 2
        or not all(_is_finite_point(point) for point in line.points)
        or _polyline_length(line.points) <= _EPSILON
    ):
        return code

    semantic_segment_kinds = {
        kind
        for kinds in _LINE_KINDS.values()
        for kind in kinds
        if kind != "egress_route"
    }
    if line.kind in semantic_segment_kinds and len(line.points) != 2:
        return code

    if line.kind in {"protected_exit", "entrance"}:
        if (
            not _is_finite_number(line.clear_width)
            or line.clear_width <= _EPSILON
            or abs(math.dist(line.points[0], line.points[1]) - line.clear_width) > 1e-7
        ):
            return code
    elif line.clear_width is not None:
        return code
    return None


def _polyline_length(points) -> float:
    return sum(math.dist(start, end) for start, end in zip(points, points[1:]))


def _line_midpoint(line: PlanLine) -> tuple[float, float]:
    return (
        (line.points[0][0] + line.points[-1][0]) / 2,
        (line.points[0][1] + line.points[-1][1]) / 2,
    )


def _exit_separation(exits: list[PlanLine]) -> float | None:
    if len(exits) != 2:
        return None
    return math.dist(_line_midpoint(exits[0]), _line_midpoint(exits[1]))


def _door_midpoints(
    layout: LayoutCandidate,
    circulation: list[RoomPolygon],
) -> dict[str, tuple[float, float]]:
    rooms = {
        room.room_id: room
        for room in layout.rooms
        if _is_valid_polygon(room.polygon)
    }
    paths = {path.room_id: path for path in circulation}
    candidates: dict[str, list[tuple[float, float]]] = {}
    result: dict[str, tuple[float, float]] = {}
    for opening in layout.openings:
        room_ids = [
            endpoint
            for endpoint in opening.connects
            if endpoint in rooms
        ]
        path_ids = [endpoint for endpoint in opening.connects if endpoint in paths]
        if opening.kind != "door" or len(room_ids) != 1 or len(path_ids) != 1:
            continue
        room = rooms[room_ids[0]]
        path = paths[path_ids[0]]
        if (
            not _is_finite_point(opening.start)
            or not _is_finite_point(opening.end)
            or not _is_finite_number(opening.clear_width)
        ):
            continue
        segment = (opening.start, opening.end)
        actual_width = math.dist(*segment)
        if (
            actual_width <= _EPSILON
            or abs(actual_width - opening.clear_width) > 1e-7
            or not any(
                _segment_contains(shared, segment)
                for shared in shared_boundary_segments(room.polygon, path.polygon)
            )
        ):
            continue
        candidates.setdefault(room.room_id, []).append(
            (
                (opening.start[0] + opening.end[0]) / 2,
                (opening.start[1] + opening.end[1]) / 2,
            )
        )
    for room_id, midpoints in candidates.items():
        if len(midpoints) == 1:
            result[room_id] = midpoints[0]
    return result


def _points_equal(left, right) -> bool:
    return math.dist(left, right) <= 1e-6


def _egress_route_in_circulation(
    points,
    circulation: list[RoomPolygon],
) -> bool:
    if len(points) < 2 or not all(_is_finite_point(point) for point in points):
        return False
    for start, end in zip(points, points[1:]):
        if math.dist(start, end) <= _EPSILON:
            return False
        if (
            abs(start[0] - end[0]) > _EPSILON
            and abs(start[1] - end[1]) > _EPSILON
        ):
            return False
        if not _axis_segment_in_polygon_union(start, end, circulation):
            return False
    return True


def _axis_segment_in_polygon_union(
    start,
    end,
    circulation: list[RoomPolygon],
) -> bool:
    vertical = abs(start[0] - end[0]) <= _EPSILON
    breakpoints = [start[1], end[1]] if vertical else [start[0], end[0]]
    lower, upper = min(breakpoints), max(breakpoints)
    for path in circulation:
        for point in path.polygon:
            coordinate = point[1] if vertical else point[0]
            if lower + _EPSILON < coordinate < upper - _EPSILON:
                breakpoints.append(coordinate)
    ordered = sorted(set(breakpoints))
    samples = [*ordered, *((left + right) / 2 for left, right in zip(ordered, ordered[1:]))]
    return all(
        any(
            _point_in_polygon_or_boundary(
                (start[0], coordinate) if vertical else (coordinate, start[1]),
                path.polygon,
            )
            for path in circulation
        )
        for coordinate in samples
    )


def _point_in_polygon_or_boundary(point, polygon) -> bool:
    x, y = point
    inside = False
    for start, end in _polygon_edges(polygon):
        cross = (end[0] - start[0]) * (y - start[1]) - (
            end[1] - start[1]
        ) * (x - start[0])
        if (
            abs(cross) <= _EPSILON
            and min(start[0], end[0]) - _EPSILON
            <= x
            <= max(start[0], end[0]) + _EPSILON
            and min(start[1], end[1]) - _EPSILON
            <= y
            <= max(start[1], end[1]) + _EPSILON
        ):
            return True
        if (start[1] > y) != (end[1] > y):
            intersection_x = start[0] + (y - start[1]) * (
                end[0] - start[0]
            ) / (end[1] - start[1])
            if x < intersection_x:
                inside = not inside
    return inside


def _is_axis_aligned_rectangle(points) -> bool:
    if (
        len(points) != 4
        or not all(_is_finite_point(point) for point in points)
        or not _is_valid_polygon(points)
    ):
        return False
    min_x, min_y, max_x, max_y = _bounds(points)
    return (
        min_x < max_x
        and min_y < max_y
        and set(map(tuple, points))
        == {(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)}
    )


def _bounds(points) -> tuple[float, float, float, float]:
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def _is_valid_polygon(points) -> bool:
    try:
        validate_polygon(points, label="geometry")
    except ValueError:
        return False
    return True


def _polygon_edges(points) -> list[Segment]:
    return list(zip(points, [*points[1:], points[0]]))


def _segment_on_polygon_boundary(segment: Segment, polygon) -> bool:
    return any(_segment_contains(edge, segment) for edge in _polygon_edges(polygon))


def _exterior_segments(room, boundary) -> list[Segment]:
    return [
        edge
        for edge in _polygon_edges(room)
        if any(_segment_contains(boundary_edge, edge) for boundary_edge in _polygon_edges(boundary))
    ]


def _same_segment(left: Segment, right: Segment) -> bool:
    return (
        _points_equal(left[0], right[0])
        and _points_equal(left[1], right[1])
    ) or (
        _points_equal(left[0], right[1])
        and _points_equal(left[1], right[0])
    )


def _collinear_overlap_length(left: Segment, right: Segment) -> float:
    (ax, ay), (bx, by) = left
    (cx, cy), (dx, dy) = right
    if abs(ax - bx) <= _EPSILON and abs(cx - dx) <= _EPSILON and abs(ax - cx) <= _EPSILON:
        return max(0.0, min(max(ay, by), max(cy, dy)) - max(min(ay, by), min(cy, dy)))
    if abs(ay - by) <= _EPSILON and abs(cy - dy) <= _EPSILON and abs(ay - cy) <= _EPSILON:
        return max(0.0, min(max(ax, bx), max(cx, dx)) - max(min(ax, bx), min(cx, dx)))
    return 0.0


def _polygon_intersects_segment(polygon, segment: Segment) -> bool:
    min_x, min_y, max_x, max_y = _bounds(polygon)
    (ax, ay), (bx, by) = segment
    if abs(ax - bx) <= _EPSILON:
        return (
            min_x - _EPSILON <= ax <= max_x + _EPSILON
            and max(min_y, min(ay, by)) <= min(max_y, max(ay, by)) + _EPSILON
        )
    if abs(ay - by) <= _EPSILON:
        return (
            min_y - _EPSILON <= ay <= max_y + _EPSILON
            and max(min_x, min(ax, bx)) <= min(max_x, max(ax, bx)) + _EPSILON
        )
    return any(
        _segments_intersect(segment, edge)
        for edge in _polygon_edges(polygon)
    ) or (
        min_x <= ax <= max_x
        and min_y <= ay <= max_y
    )


def _segments_intersect(left: Segment, right: Segment) -> bool:
    def orientation(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    first = orientation(left[0], left[1], right[0])
    second = orientation(left[0], left[1], right[1])
    third = orientation(right[0], right[1], left[0])
    fourth = orientation(right[0], right[1], left[1])
    return first * second <= _EPSILON and third * fourth <= _EPSILON


def _has_orthogonal_grid(lines: list[PlanLine]) -> bool:
    vertical = any(
        abs(line.points[0][0] - line.points[-1][0]) <= _EPSILON
        for line in lines
    )
    horizontal = any(
        abs(line.points[0][1] - line.points[-1][1]) <= _EPSILON
        for line in lines
    )
    return vertical and horizontal


def _is_finite_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _is_finite_limit(value, *, minimum: float) -> bool:
    if isinstance(value, bool):
        return False
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(numeric) and numeric >= minimum and (
        minimum != 0 or numeric > 0
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
        if node.min_width is not None and not _is_finite_limit(node.min_width, minimum=0):
            raise ValueError(
                f"program room '{node.node_id}' minimum width must be finite and positive"
            )
        if node.max_aspect_ratio is not None and not _is_finite_limit(
            node.max_aspect_ratio,
            minimum=1,
        ):
            raise ValueError(
                f"program room '{node.node_id}' maximum aspect ratio must be finite and at least 1"
            )

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


def _room_shape_metrics(
    rooms: list[RoomPolygon],
    valid_room_ids: set[int],
    program: ProgramGraph,
    add_violation,
) -> list[RoomShapeMetric]:
    metrics: list[RoomShapeMetric] = []
    for node in program.nodes:
        matching = [room for room in rooms if room.room_id == node.node_id]
        valid_matching = [room for room in matching if id(room) in valid_room_ids]
        required_width = float(node.min_width) if node.min_width is not None else None
        maximum_aspect = (
            float(node.max_aspect_ratio)
            if node.max_aspect_ratio is not None
            else None
        )
        measured_width: float | None = None
        measured_aspect: float | None = None
        width_passed = required_width is None
        aspect_passed = maximum_aspect is None

        if len(matching) == 1 and len(valid_matching) == 1:
            room = valid_matching[0]
            try:
                measured_width = orthogonal_min_width(room.polygon)
            except ValueError as error:
                if required_width is not None:
                    add_violation(
                        "room_min_width",
                        node.node_id,
                        f"room '{node.node_id}' minimum width cannot be measured: {error}",
                    )
            else:
                if required_width is not None:
                    width_passed = measured_width + _EPSILON >= required_width
                    if not width_passed:
                        add_violation(
                            "room_min_width",
                            node.node_id,
                            (
                                f"room '{node.node_id}' minimum width {measured_width:.3f} "
                                f"is below {required_width:.3f}"
                            ),
                        )

            try:
                measured_aspect = bounding_box_aspect_ratio(room.polygon)
            except ValueError as error:
                if maximum_aspect is not None:
                    add_violation(
                        "room_aspect_ratio",
                        node.node_id,
                        f"room '{node.node_id}' aspect ratio cannot be measured: {error}",
                    )
            else:
                if maximum_aspect is not None:
                    aspect_passed = measured_aspect <= maximum_aspect + _EPSILON
                    if not aspect_passed:
                        add_violation(
                            "room_aspect_ratio",
                            node.node_id,
                            (
                                f"room '{node.node_id}' aspect ratio {measured_aspect:.3f} "
                                f"exceeds {maximum_aspect:.3f}"
                            ),
                        )

        metrics.append(
            RoomShapeMetric(
                room_id=node.node_id,
                measured_min_width=measured_width,
                required_min_width=required_width,
                measured_aspect_ratio=measured_aspect,
                maximum_aspect_ratio=maximum_aspect,
                minimum_width_passed=width_passed,
                aspect_ratio_passed=aspect_passed,
            )
        )
    return metrics


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
    if program.use_type == "office":
        rentable_types = {"open_work", "meeting", "reception", "focus"}
        target = 0.73
    elif program.use_type == "neighborhood_commercial":
        rentable_types = {"sales", "checkout"}
        target = 0.61
    else:
        rentable_types = {"shop_unit", "office_area"}
        target = 0.72
    total = sum(polygon_area(room.polygon) for room in rooms)
    rentable = sum(
        polygon_area(room.polygon)
        for room in rooms
        if room.space_type in rentable_types
    )
    if total <= 0:
        return 0.0
    ratio = rentable / total
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
