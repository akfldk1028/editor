from __future__ import annotations

import json
import math
from dataclasses import replace

import pytest

from backend.app.core.serialization import to_jsonable
from backend.app.modules.generation_loop.service import run_building_generation
from backend.app.modules.validator.service import validate_layout
from backend.app.schemas import layout as layout_schema
from backend.app.schemas.layout import RoomPolygon
from backend.app.schemas.mass import MassInput
from backend.app.schemas.metrics import PolicyCheck
from backend.tests.test_basic_design_validation import (
    BOUNDARY,
    STREET,
    _commercial_candidate,
    _office_candidate,
)


def test_remote_exit_policy_uses_one_third_of_floor_plate_diagonal() -> None:
    layout, program = _office_candidate()

    report = validate_layout(
        layout,
        program,
        BOUNDARY,
        street_segments=STREET,
        require_basic_design=True,
    )

    assert not report.accepted
    assert "remote_exit_unfit" in {violation.code for violation in report.violations}
    assert report.basic_design is not None
    check = report.basic_design.policy_checks["remote_exit_separation"]
    assert check["value"] == pytest.approx(4.1)
    assert check["threshold"] == pytest.approx(
        math.hypot(18.0, 10.0) / 3.0
    )
    assert check["pass"] is False
    assert "project policy" in str(check["reason"])
    json.dumps(to_jsonable(report))


def test_commercial_without_tenant_metadata_is_unknown_and_rejected() -> None:
    layout, program = _commercial_candidate()

    report = validate_layout(
        layout,
        program,
        BOUNDARY,
        street_segments=STREET,
        require_basic_design=True,
    )

    assert not report.accepted
    assert "use_planning_metadata_missing" in {
        violation.code for violation in report.violations
    }
    assert report.basic_design is not None
    for name in (
        "tenant_count",
        "tenant_independent_access",
        "common_core_access",
    ):
        check = report.basic_design.policy_checks[name]
        assert check["value"] is None
        assert check["pass"] is False
        assert "unknown" in str(check["reason"])
    json.dumps(to_jsonable(report))


def test_office_without_planning_metadata_records_unmet_policy_checks() -> None:
    layout, program = _office_candidate()

    report = validate_layout(
        layout,
        program,
        BOUNDARY,
        street_segments=STREET,
        require_basic_design=True,
    )

    assert not report.accepted
    assert "use_planning_metadata_missing" in {
        violation.code for violation in report.violations
    }
    assert report.basic_design is not None
    checks = report.basic_design.policy_checks
    assert checks["reception_to_lobby"]["value"] is None
    assert checks["reception_to_lobby"]["pass"] is False
    assert checks["support_clustering"]["value"] is None
    assert checks["support_clustering"]["pass"] is False
    assert checks["workpoint_count"]["value"] == 1
    assert checks["workpoint_count"]["threshold"] == "5..6"
    assert checks["workpoint_count"]["pass"] is False
    json.dumps(to_jsonable(report))


def test_remote_floor_stair_uses_circulation_exit_without_core_lobby_door() -> None:
    remote_layout, program, boundary = _remote_floor_stair_candidate()

    report = validate_layout(
        remote_layout,
        program,
        boundary,
        street_segments=STREET,
        require_basic_design=True,
    )

    codes = {violation.code for violation in report.violations}
    assert not codes & {
        "basic_design_reference",
        "core_subspace_containment",
        "protected_exit_reference",
        "protected_exit_geometry",
        "stair_door_missing",
        "stair_door_reference",
        "lobby_route_missing",
        "lobby_route_reference",
        "lobby_route_geometry",
        "remote_exit_unfit",
    }


def test_reception_route_to_remote_stair_does_not_satisfy_lobby_policy() -> None:
    layout, program, boundary = _remote_floor_stair_candidate()
    assert layout.basic_design is not None
    reception_room = replace(
        layout.rooms[0],
        room_id="reception",
        space_type="reception",
    )
    features = layout.basic_design
    reception_features = replace(
        features,
        elements=tuple(
            replace(
                element,
                kind="reception_desk",
                host_id="reception",
            )
            if element.kind == "workstation"
            else element
            for element in features.elements
        ),
        lines=tuple(
            replace(line, host_id="reception")
            if line.host_id == "open_work"
            else line
            for line in features.lines
        ),
        planning=layout_schema.UsePlanningMetadata(
            reception_to_lobby_route_line_id="route-2",
            support_room_ids=(),
        ),
    )
    reception_layout = replace(
        layout,
        rooms=[reception_room, *layout.rooms[1:]],
        openings=[
            replace(
                layout.openings[0],
                connects=("reception", "corridor"),
            ),
            *layout.openings[1:],
        ],
        basic_design=reception_features,
    )
    reception_program = replace(
        program,
        nodes=[
            replace(
                program.nodes[0],
                node_id="reception",
                space_type="reception",
            ),
            *program.nodes[1:],
        ],
    )

    report = validate_layout(
        reception_layout,
        reception_program,
        boundary,
        street_segments=STREET,
        require_basic_design=True,
    )

    assert "reception_to_lobby_unmet" in {
        violation.code for violation in report.violations
    }


def test_common_core_access_requires_connected_circulation_topology() -> None:
    mass = MassInput(
        project_id="disconnected-core-entry",
        floors=1,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"neighborhood_commercial": 1.0},
    )
    commercial = run_building_generation(mass).floor_results[0]
    assert commercial.layout.basic_design is not None
    entry_pocket = RoomPolygon(
        "entry-pocket",
        "circulation",
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
    )
    disconnected = replace(
        commercial.layout,
        circulation=[*commercial.layout.circulation, entry_pocket],
        basic_design=replace(
            commercial.layout.basic_design,
            lines=tuple(
                replace(
                    line,
                    points=((0.05, 0.0), (0.95, 0.0)),
                    target_id="entry-pocket",
                )
                if line.line_id == "core-public-entrance"
                else line
                for line in commercial.layout.basic_design.lines
            ),
        ),
    )

    report = validate_layout(
        disconnected,
        commercial.program,
        mass.footprint_polygon,
        street_segments=[((0, 0), (30, 0))],
        require_basic_design=True,
    )

    assert report.basic_design is not None
    check = report.basic_design.policy_checks["common_core_access"]
    assert check["value"] == 0
    assert check["threshold"] == 1
    assert check["pass"] is False
    assert "common_core_access_unmet" in {
        violation.code for violation in report.violations
    }


def test_generated_commercial_common_entry_reaches_validated_core_exit() -> None:
    mass, commercial = _generated_commercial_result("connected-core-entry")

    report = validate_layout(
        commercial.layout,
        commercial.program,
        mass.footprint_polygon,
        street_segments=[((0, 0), (30, 0))],
        require_basic_design=True,
    )

    assert report.basic_design is not None
    check = report.basic_design.policy_checks["common_core_access"]
    assert check["value"] == 1
    assert check["threshold"] == 1
    assert check["pass"] is True


def test_common_core_access_requires_entry_component_to_contain_core_exit() -> None:
    mass, commercial = _generated_commercial_result("split-core-access")
    assert commercial.layout.basic_design is not None
    entry_component = RoomPolygon(
        "entry-core-pocket",
        "circulation",
        [(22.0, 0.0), (23.9, 0.0), (23.9, 6.0), (22.0, 6.0)],
    )
    exit_component = RoomPolygon(
        "exit-core-pocket",
        "circulation",
        [(25.5, 4.8), (30.0, 4.8), (30.0, 6.0), (25.5, 6.0)],
    )
    split = replace(
        commercial.layout,
        circulation=[entry_component, exit_component],
        basic_design=replace(
            commercial.layout.basic_design,
            lines=tuple(
                replace(
                    line,
                    points=((22.5, 0.0), (23.4, 0.0)),
                    target_id="entry-core-pocket",
                )
                if line.line_id == "core-public-entrance"
                else line
                for line in commercial.layout.basic_design.lines
            ),
        ),
    )

    report = validate_layout(
        split,
        commercial.program,
        mass.footprint_polygon,
        street_segments=[((0, 0), (30, 0))],
        require_basic_design=True,
    )

    assert report.basic_design is not None
    check = report.basic_design.policy_checks["common_core_access"]
    assert check["value"] == 0
    assert check["threshold"] == 1
    assert check["pass"] is False


def test_workpoint_upper_bound_uses_floor_for_eight_square_meters() -> None:
    layout, program = _office_candidate()
    assert layout.basic_design is not None
    work_room = replace(
        layout.rooms[0],
        polygon=[(0.0, 0.0), (5.875, 0.0), (5.875, 8.0), (0.0, 8.0)],
    )
    workstation = next(
        element
        for element in layout.basic_design.elements
        if element.kind == "workstation"
    )
    workstations = tuple(
        replace(
            workstation,
            element_id=f"workstation-{index}",
            footprint=(
                (0.2 + index * 0.8, 2.0),
                (0.8 + index * 0.8, 2.0),
                (0.8 + index * 0.8, 2.5),
                (0.2 + index * 0.8, 2.5),
            ),
        )
        for index in range(6)
    )
    dense = replace(
        layout,
        rooms=[work_room, *layout.rooms[1:]],
        basic_design=replace(
            layout.basic_design,
            elements=(
                *(
                    element
                    for element in layout.basic_design.elements
                    if element.kind != "workstation"
                ),
                *workstations,
            ),
        ),
    )

    report = validate_layout(
        dense,
        program,
        BOUNDARY,
        street_segments=STREET,
        require_basic_design=True,
    )

    assert report.basic_design is not None
    check = report.basic_design.policy_checks["workpoint_count"]
    assert check["value"] == 6
    assert check["threshold"] == "5..5"
    assert check["pass"] is False


def test_remote_exit_policy_keeps_absolute_three_meter_floor() -> None:
    layout, program = _office_candidate()
    small_boundary = [
        (0.0, 0.0),
        (6.0, 0.0),
        (6.0, 6.0),
        (0.0, 6.0),
    ]

    report = validate_layout(
        layout,
        program,
        small_boundary,
        require_basic_design=True,
        min_exit_separation=1.0,
    )

    assert report.basic_design is not None
    assert (
        report.basic_design.policy_checks["remote_exit_separation"]["threshold"]
        == pytest.approx(3.0)
    )


def test_planning_and_policy_records_are_frozen_and_json_safe() -> None:
    metadata_type = getattr(layout_schema, "UsePlanningMetadata", None)
    assert metadata_type is not None
    with pytest.raises(TypeError):
        metadata_type(
            reception_to_lobby_route_line_id="route-1",
            support_room_ids={"restroom"},
        )
    layout, _ = _office_candidate()
    assert layout.basic_design is not None
    with pytest.raises(TypeError):
        replace(
            layout.basic_design,
            planning={"support_room_ids": {"restroom"}},
        )
    with pytest.raises(TypeError):
        PolicyCheck({"not-json-safe"}, True, False, "invalid value")

    _, program = _office_candidate()
    report = validate_layout(
        layout,
        program,
        BOUNDARY,
        street_segments=STREET,
        require_basic_design=True,
    )
    assert report.basic_design is not None
    check = report.basic_design.policy_checks["workpoint_count"]
    with pytest.raises(TypeError):
        check["pass"] = True
    with pytest.raises(TypeError):
        report.basic_design.policy_checks["extra"] = check
    with pytest.raises(TypeError):
        replace(
            report.basic_design,
            policy_checks={"workpoint_count": dict(check)},
        )
    json.dumps(to_jsonable(report))


def test_empty_typed_office_planning_is_unknown_and_rejected() -> None:
    layout, program = _office_candidate()
    assert layout.basic_design is not None
    empty_planning = replace(
        layout,
        basic_design=replace(
            layout.basic_design,
            planning=layout_schema.UsePlanningMetadata(),
        ),
    )

    report = validate_layout(
        empty_planning,
        program,
        BOUNDARY,
        street_segments=STREET,
        require_basic_design=True,
    )

    assert "use_planning_metadata_missing" in {
        violation.code for violation in report.violations
    }
    assert report.basic_design is not None
    assert report.basic_design.policy_checks["reception_to_lobby"]["value"] is None
    assert report.basic_design.policy_checks["support_clustering"]["value"] is None


def _remote_floor_stair_candidate():
    layout, program = _office_candidate()
    assert layout.basic_design is not None
    features = layout.basic_design
    remote_stair = replace(
        next(element for element in features.elements if element.element_id == "stair-2"),
        host_id="floor",
        footprint=((0.0, 8.0), (4.8, 8.0), (4.8, 10.8), (0.0, 10.8)),
    )
    remote_exit = replace(
        next(line for line in features.lines if line.line_id == "exit-2"),
        points=((4.8, 8.9), (4.8, 9.8)),
        host_id="corridor",
        target_id="stair-2",
    )
    remote_route = replace(
        next(line for line in features.lines if line.line_id == "route-2"),
        points=((6.0, 3.55), (7.0, 3.55), (7.0, 9.35), (4.8, 9.35)),
    )
    remote_layout = replace(
        layout,
        circulation=[
            RoomPolygon(
                "corridor",
                "circulation",
                [
                    (6.0, 0.0),
                    (8.0, 0.0),
                    (8.0, 10.8),
                    (4.8, 10.8),
                    (4.8, 8.0),
                    (6.0, 8.0),
                ],
            )
        ],
        basic_design=replace(
            features,
            elements=tuple(
                remote_stair if element.element_id == "stair-2" else element
                for element in features.elements
            ),
            lines=tuple(
                remote_exit
                if line.line_id == "exit-2"
                else remote_route
                if line.line_id == "route-2"
                else line
                for line in features.lines
                if line.line_id not in {"stair-door-2", "lobby-route-2"}
            ),
        ),
    )
    boundary = [(0.0, 0.0), (18.0, 0.0), (18.0, 12.0), (0.0, 12.0)]
    return remote_layout, program, boundary


def _generated_commercial_result(project_id: str):
    mass = MassInput(
        project_id=project_id,
        floors=1,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"neighborhood_commercial": 1.0},
    )
    return mass, run_building_generation(mass).floor_results[0]
