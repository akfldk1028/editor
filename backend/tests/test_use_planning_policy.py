from __future__ import annotations

import json
import math
from dataclasses import replace

import pytest

from backend.app.core.serialization import to_jsonable
from backend.app.modules.validator.service import validate_layout
from backend.app.schemas.layout import RoomPolygon
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
