from dataclasses import replace

import pytest

from backend.app.modules.building_quality.daylight import measure_primary_daylight
from backend.app.modules.building_quality.room_form import measure_room_form
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.validator.service import validate_layout
from backend.app.schemas.layout import (
    BasicDesignFeatures,
    LayoutCandidate,
    PlanLine,
    RoomPolygon,
)
from backend.app.schemas.mass import MassInput
from backend.app.schemas.program import ProgramGraph, ProgramNode
from backend.app.schemas.result import GenerationResult


_BOUNDARY = [(0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0)]


def test_daylight_proxy_is_area_weighted_and_requires_valid_exterior_window():
    floor = _office_floor(
        primary_areas={"open_work": 70, "meeting": 20, "focus": 10},
        exterior_windows={"open_work", "focus"},
    )

    measured = measure_primary_daylight(floor)

    assert measured.total_primary_area == pytest.approx(100)
    assert measured.served_primary_area == pytest.approx(80)
    assert measured.ratio == pytest.approx(0.80)
    assert measured.unserved_room_ids == ("meeting",)


def test_interior_window_does_not_serve_primary_room():
    floor = _office_floor(
        primary_areas={"open_work": 70, "meeting": 20, "focus": 10},
        exterior_windows={"open_work"},
        invalid_windows={"meeting"},
    )

    measured = measure_primary_daylight(floor)

    assert measured.ratio == pytest.approx(0.70)
    assert measured.unserved_room_ids == ("focus", "meeting")


def test_mis_hosted_exterior_window_does_not_serve_primary_room():
    floor = _office_floor(
        primary_areas={"open_work": 70, "meeting": 20, "focus": 10},
        exterior_windows={"focus"},
        mis_hosted_windows={"open_work": "focus"},
    )

    measured = measure_primary_daylight(floor)

    assert measured.served_room_ids == ("focus",)
    assert measured.ratio == pytest.approx(0.10)
    assert measured.unserved_room_ids == ("meeting", "open_work")


def test_missing_primary_program_area_is_rejected():
    with pytest.raises(ValueError, match="primary"):
        measure_primary_daylight(_floor_without_primary_rooms())


def test_room_form_ratio_uses_actual_room_area_weighting():
    floor = _floor_with_shape_metrics(
        rooms={"open_work": 80, "meeting": 20},
        passing={"open_work"},
    )

    measured = measure_room_form(floor)

    assert measured.measured_area == pytest.approx(100)
    assert measured.passing_area == pytest.approx(80)
    assert measured.ratio == pytest.approx(0.80)
    assert measured.worst_aspect_ratio == pytest.approx(5.0)
    assert measured.narrowest_width_m == pytest.approx(2.0)
    assert measured.failing_room_ids == ("meeting",)


def test_unmeasurable_non_core_room_fails_room_form_measurement():
    floor = _floor_with_unmeasurable_shape("meeting")

    measured = measure_room_form(floor)

    assert measured.ratio < 1.0
    assert measured.unmeasurable_room_ids == ("meeting",)


def _office_floor(
    *,
    primary_areas: dict[str, float],
    exterior_windows: set[str] | None = None,
    invalid_windows: set[str] | None = None,
    mis_hosted_windows: dict[str, str] | None = None,
) -> GenerationResult:
    rooms = _rooms(primary_areas)
    lines = [_window(room_id, valid=True) for room_id in sorted(exterior_windows or ())]
    lines.extend(
        _window(room_id, valid=False) for room_id in sorted(invalid_windows or ())
    )
    lines.extend(
        _window(exterior_room_id, valid=True, host_id=host_id)
        for exterior_room_id, host_id in sorted((mis_hosted_windows or {}).items())
    )
    return _generation_result(rooms, lines)


def _floor_without_primary_rooms() -> GenerationResult:
    return _generation_result(
        [
            RoomPolygon(
                "core", "core", [(10.0, 0.0), (15.0, 0.0), (15.0, 2.0), (10.0, 2.0)]
            ),
            RoomPolygon(
                "pantry", "pantry", [(15.0, 0.0), (20.0, 0.0), (20.0, 2.0), (15.0, 2.0)]
            ),
        ],
        [],
    )


def _floor_with_shape_metrics(
    *,
    rooms: dict[str, float],
    passing: set[str],
) -> GenerationResult:
    result = _generation_result(_rooms(rooms, include_support=False), [])
    shape_metrics = [
        replace(
            metric,
            minimum_width_passed=metric.room_id in passing,
            aspect_ratio_passed=metric.room_id in passing,
        )
        for metric in result.validation.room_shapes
    ]
    return replace(
        result, validation=replace(result.validation, room_shapes=shape_metrics)
    )


def _floor_with_unmeasurable_shape(room_id: str) -> GenerationResult:
    result = _generation_result(
        _rooms({"open_work": 80, "meeting": 20}, include_support=False),
        [],
    )
    shape_metrics = [
        replace(
            metric,
            measured_min_width=None
            if metric.room_id == room_id
            else metric.measured_min_width,
        )
        for metric in result.validation.room_shapes
    ]
    return replace(
        result, validation=replace(result.validation, room_shapes=shape_metrics)
    )


def _rooms(
    primary_areas: dict[str, float], *, include_support: bool = True
) -> list[RoomPolygon]:
    rooms: list[RoomPolygon] = []
    y = 0.0
    for room_id in ("open_work", "meeting", "focus"):
        area = primary_areas.get(room_id)
        if area is None:
            continue
        height = area / 10.0
        rooms.append(
            RoomPolygon(
                room_id,
                room_id,
                [(0.0, y), (10.0, y), (10.0, y + height), (0.0, y + height)],
            )
        )
        y += height
    core = RoomPolygon(
        "core",
        "core",
        [(10.0, 0.0), (15.0, 0.0), (15.0, 2.0), (10.0, 2.0)],
    )
    if not include_support:
        return rooms + [core]
    return rooms + [
        core,
        RoomPolygon(
            "pantry", "pantry", [(15.0, 0.0), (20.0, 0.0), (20.0, 2.0), (15.0, 2.0)]
        ),
    ]


def _window(room_id: str, *, valid: bool, host_id: str | None = None) -> PlanLine:
    valid_segments = {
        "open_work": ((0.0, 2.0), (0.0, 4.0)),
        "meeting": ((0.0, 7.25), (0.0, 8.75)),
        "focus": ((2.0, 10.0), (8.0, 10.0)),
    }
    segment = valid_segments[room_id] if valid else ((2.0, 8.0), (8.0, 8.0))
    return PlanLine(
        line_id=f"{room_id}-window-for-{host_id or room_id}",
        category="envelope",
        kind="window",
        points=segment,
        host_id=host_id or room_id,
    )


def _generation_result(
    rooms: list[RoomPolygon], lines: list[PlanLine]
) -> GenerationResult:
    nodes = [
        ProgramNode(
            room.room_id,
            room.space_type,
            _polygon_area(room.polygon),
            min_width=1.0,
            max_aspect_ratio=20.0,
        )
        for room in rooms
    ]
    program = ProgramGraph("quality-floor", 1, "office", nodes, [], "test")
    layout = LayoutCandidate(
        "quality-floor",
        "quality-floor",
        1,
        rooms,
        [],
        0.0,
        basic_design=BasicDesignFeatures(elements=(), lines=tuple(lines)),
    )
    mass_input = MassInput(
        "quality-floor",
        1,
        _BOUNDARY,
        [],
        [],
        {"office": 1.0},
    )
    return GenerationResult(
        mass=analyze_mass(mass_input),
        program=program,
        layout=layout,
        validation=validate_layout(layout, program, boundary=_BOUNDARY),
    )


def _polygon_area(points: list[tuple[float, float]]) -> float:
    return abs(
        sum(
            x1 * y2 - x2 * y1
            for (x1, y1), (x2, y2) in zip(points, [*points[1:], points[0]])
        )
        / 2.0
    )
