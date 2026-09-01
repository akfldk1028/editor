from dataclasses import replace

import pytest

from backend.app.modules.building_quality.egress import aggregate_egress_quality
from backend.app.modules.building_quality.vertical_stack import measure_vertical_quality
from backend.app.modules.generation_loop.service import run_building_generation
from backend.app.schemas.layout import BasicDesignFeatures, PlanElement, RoomPolygon
from backend.app.schemas.mass import MassInput
from backend.app.schemas.regulatory import RegulatoryCheck, RegulatoryScreening


def test_vertical_stack_uses_worst_adjacent_floor_overlap():
    building = _three_floor_building(
        core_offsets=((0, 0), (0, 0), (1, 0)),
        shaft_offsets=((0, 0), (0, 0), (0.5, 0)),
        restroom_offsets=((0, 0), (0.5, 0), (3, 0)),
    )

    measured = measure_vertical_quality(building)

    assert measured.core_stack_ratio < 1.0
    assert measured.shaft_stack_ratio < 1.0
    assert measured.wet_service_stack_ratio < measured.core_stack_ratio
    assert measured.maximum_service_centroid_shift_m == pytest.approx(2.5)


def test_missing_required_shaft_scores_zero():
    building = _building_with_missing_shaft_on_floor(2)

    assert measure_vertical_quality(building).shaft_stack_ratio == 0.0


def test_vertical_service_shift_uses_wet_services_not_shafts():
    building = _three_floor_building(
        core_offsets=((0, 0), (0, 0), (0, 0)),
        shaft_offsets=((0, 0), (10, 0), (20, 0)),
        restroom_offsets=((0, 0), (0, 0), (0, 0)),
    )

    measured = measure_vertical_quality(building)

    assert measured.maximum_service_centroid_shift_m == pytest.approx(0.0)


def test_one_floor_vertical_stack_is_vacuously_aligned():
    measured = measure_vertical_quality(_building(floors=1))

    assert measured.core_stack_ratio == 1.0
    assert measured.shaft_stack_ratio == 1.0
    assert measured.wet_service_stack_ratio == 1.0
    assert measured.maximum_service_centroid_shift_m is None


def test_vertical_stack_uses_global_minimum_distance_matching():
    building = _building_with_wet_service_offsets(
        ((0, 0), (5, 0)),
        ((4, 0), (6, 0)),
    )

    measured = measure_vertical_quality(building)

    assert measured.maximum_service_centroid_shift_m == pytest.approx(4.0)


def test_checked_egress_failure_is_preserved():
    building = _building_with_screening(
        checks=("pass", "fail", "pass"),
        unresolved=(),
    )

    measured = aggregate_egress_quality(building)

    assert measured.status == "fail"
    assert measured.failed_floor_indexes == (1,)


def test_not_checked_egress_remains_unresolved():
    building = _building_with_screening(
        checks=("pass", "not_checked", "not_checked"),
        unresolved=("jurisdiction", "measured_travel_distance"),
    )

    measured = aggregate_egress_quality(building)

    assert measured.status == "not_checked"
    assert measured.unresolved_facts == (
        "jurisdiction",
        "measured_travel_distance",
    )


def test_missing_egress_graph_is_unresolved():
    building = _building_with_screening(checks=("pass",), unresolved=())
    floor = replace(building.floor_results[0], egress_graph=None)

    measured = aggregate_egress_quality(
        replace(building, floor_results=(floor,), area_ledger=None)
    )

    assert measured.status == "not_checked"
    assert measured.unresolved_facts == ("measured_travel_distance",)


def test_not_checked_egress_graph_blocks_pass_and_preserves_facts():
    building = _building_with_screening(checks=("pass",), unresolved=())
    floor = building.floor_results[0]
    graph = replace(
        floor.egress_graph,
        status="not_checked",
        nodes=(),
        edges=(),
        room_results=(),
        governing_room_id=None,
        governing_distance_m=None,
        governing_exit_id=None,
        unresolved_facts=("route_connectivity",),
    )

    measured = aggregate_egress_quality(
        replace(building, floor_results=(replace(floor, egress_graph=graph),))
    )

    assert measured.status == "fail"
    assert measured.failed_floor_indexes == (1,)
    assert measured.hard_failure_facts == ((1, "route_connectivity"),)
    assert measured.unresolved_facts == ("route_connectivity",)


def test_adjacent_floors_without_wet_services_do_not_force_zero_ratio():
    building = _building(floors=2)

    measured = measure_vertical_quality(building)

    assert measured.wet_service_stack_ratio == 1.0


def test_egress_aggregation_sorts_unsorted_floor_results():
    building = _building(floors=2)
    floors = tuple(
        _floor_with_screening(floor, checks=("pass",), unresolved=())
        for floor in building.floor_results
    )

    measured = aggregate_egress_quality(
        replace(
            building,
            floor_results=tuple(reversed(floors)),
            area_ledger=None,
        )
    )

    assert measured.status == "pass"
    assert measured.checked_floor_indexes == (1, 2)


def _three_floor_building(
    *,
    core_offsets: tuple[tuple[float, float], ...],
    shaft_offsets: tuple[tuple[float, float], ...],
    restroom_offsets: tuple[tuple[float, float], ...],
):
    building = _building(floors=3)
    floors = tuple(
        replace(
            floor,
            layout=replace(
                floor.layout,
                rooms=[
                    *_non_service_rooms(floor.layout.rooms),
                    _room("core", "core", core_offset),
                    _room("restroom", "restroom", restroom_offset),
                ],
                basic_design=BasicDesignFeatures(
                    elements=(_shaft(shaft_offset),),
                    lines=(),
                ),
            ),
        )
        for floor, core_offset, shaft_offset, restroom_offset in zip(
            building.floor_results,
            core_offsets,
            shaft_offsets,
            restroom_offsets,
            strict=True,
        )
    )
    return replace(building, floor_results=floors)


def _building_with_wet_service_offsets(
    *floor_offsets: tuple[tuple[float, float], ...],
):
    building = _building(floors=len(floor_offsets))
    floors = tuple(
        replace(
            floor,
            layout=replace(
                floor.layout,
                rooms=[
                    *_non_service_rooms(floor.layout.rooms),
                    _room("core", "core", (0, 0)),
                    *(
                        _room(f"restroom-{index}", "restroom", offset)
                        for index, offset in enumerate(offsets)
                    ),
                ],
            ),
        )
        for floor, offsets in zip(
            building.floor_results,
            floor_offsets,
            strict=True,
        )
    )
    return replace(building, floor_results=floors)


def _building_with_missing_shaft_on_floor(floor_index: int):
    building = _three_floor_building(
        core_offsets=((0, 0), (0, 0), (0, 0)),
        shaft_offsets=((0, 0), (0, 0), (0, 0)),
        restroom_offsets=((0, 0), (0, 0), (0, 0)),
    )
    floors = tuple(
        replace(
            floor,
            layout=replace(
                floor.layout,
                basic_design=BasicDesignFeatures(elements=(), lines=()),
            ),
        )
        if floor.program.floor_index == floor_index
        else floor
        for floor in building.floor_results
    )
    return replace(building, floor_results=floors)


def _building_with_screening(*, checks: tuple[str, ...], unresolved: tuple[str, ...]):
    building = _building(floors=1)
    floor = building.floor_results[0]
    return replace(
        building,
        floor_results=(
            _floor_with_screening(floor, checks=checks, unresolved=unresolved),
        ),
    )


def _floor_with_screening(
    floor, *, checks: tuple[str, ...], unresolved: tuple[str, ...]
):
    graph = floor.egress_graph
    assert graph is not None
    screening = RegulatoryScreening(
        ruleset_id="test-ruleset",
        status=(
            "fail"
            if "fail" in checks
            else "not_checked"
            if "not_checked" in checks or unresolved
            else "pass"
        ),
        checks=tuple(_check(index, status) for index, status in enumerate(checks)),
        unresolved_facts=unresolved,
        floor_index=floor.program.floor_index,
    )
    return replace(
        floor,
        validation=replace(floor.validation, regulatory_screening=screening),
        egress_graph=replace(graph, unresolved_facts=()),
    )


def _building(*, floors: int):
    return run_building_generation(
        MassInput(
            project_id="building-quality",
            floors=floors,
            footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
            site_edges=[{"edge_index": 0, "kind": "street"}],
            access_candidates=[{"edge_index": 0, "position": 0.5}],
            use_mix={"office": 1.0},
        )
    )


def _non_service_rooms(rooms: list[RoomPolygon]) -> list[RoomPolygon]:
    return [room for room in rooms if room.space_type not in {"core", "restroom"}]


def _room(room_id: str, space_type: str, offset: tuple[float, float]) -> RoomPolygon:
    x, y = offset
    return RoomPolygon(
        room_id,
        space_type,
        [(x, y), (x + 2, y), (x + 2, y + 2), (x, y + 2)],
    )


def _shaft(offset: tuple[float, float]) -> PlanElement:
    x, y = offset
    return PlanElement(
        element_id="shaft",
        category="service",
        kind="shaft",
        host_id="core",
        label="shaft",
        footprint=((x, y), (x + 2, y), (x + 2, y + 2), (x, y + 2)),
    )


def _check(index: int, status: str) -> RegulatoryCheck:
    return RegulatoryCheck(
        rule_id=f"test-rule-{index}",
        status=status,  # type: ignore[arg-type]
        source_url="https://example.test/rule",
        effective_date="2026-07-30",
        measured_value=None,
        threshold=None,
        applicability=True,
        assumptions=(),
    )
