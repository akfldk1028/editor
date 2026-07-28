from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from backend.app.modules.generation_loop.service import run_building_generation
from backend.app.modules.validator.service import validate_layout
from backend.app.schemas.layout import (
    BasicDesignFeatures,
    LayoutCandidate,
    OpeningSegment,
    PlanElement,
    PlanLine,
    RoomPolygon,
    UsePlanningMetadata,
)
from backend.app.schemas.mass import MassInput
from backend.app.schemas.program import ProgramGraph, ProgramNode


BOUNDARY = [(0.0, 0.0), (18.0, 0.0), (18.0, 10.0), (0.0, 10.0)]
STREET = [((0.0, 0.0), (18.0, 0.0))]


def test_basic_design_validation_is_opt_in() -> None:
    layout, program = _office_candidate()

    report = validate_layout(layout, program, BOUNDARY, street_segments=STREET)

    assert report.accepted
    assert report.basic_design_checked is False
    assert report.basic_design is None


def test_strict_validation_requires_feature_bundle() -> None:
    layout, program = _office_candidate()

    report = validate_layout(
        replace(layout, basic_design=None),
        program,
        BOUNDARY,
        street_segments=STREET,
        require_basic_design=True,
    )

    assert report.basic_design_checked is True
    assert report.basic_design is not None
    assert report.basic_design.policy_version == "missing"
    assert _codes(report) == {"basic_design_missing"}


def test_strict_validation_rejects_legacy_nonremote_second_exit() -> None:
    layout, program = _office_candidate()

    report = _strict(layout, replace(program, use_type="generic"))

    assert not report.accepted
    assert {violation.code for violation in report.violations} == {
        "protected_exit_separation",
        "remote_exit_unfit",
    }
    metric = report.basic_design
    assert metric is not None
    assert metric.policy_version == "concept-basic-v1"
    assert (
        metric.stair_count,
        metric.elevator_count,
        metric.lobby_count,
        metric.shaft_count,
    ) == (2, 1, 1, 1)
    assert metric.exit_count == 2
    assert metric.route_count == 2
    assert metric.grid_line_count == 2
    assert metric.column_count == 1
    assert metric.window_count == 1
    assert metric.entrance_count == 0
    assert metric.furniture_count == 1
    assert metric.fixture_count == 0
    assert metric.dimension_count == 3
    assert metric.min_exit_width == pytest.approx(0.9)
    assert metric.exit_separation == pytest.approx(4.1)
    assert metric.min_routes_per_room == 2
    assert metric.missing_required_kinds == ()


@pytest.mark.parametrize(
    ("features", "code"),
    [
        (
            lambda base: replace(
                base,
                elements=(
                    *base.elements,
                    replace(base.elements[0], category="furniture"),
                ),
            ),
            "basic_design_identity",
        ),
        (
            lambda base: replace(
                base,
                elements=(
                    replace(base.elements[0], host_id="missing-room"),
                    *base.elements[1:],
                ),
            ),
            "basic_design_reference",
        ),
        (
            lambda base: replace(
                base,
                lines=(
                    replace(_line(base, "grid-x"), points=((3.0, 1.0), (3.0, 1.0))),
                    *[line for line in base.lines if line.line_id != "grid-x"],
                ),
            ),
            "basic_design_geometry",
        ),
    ],
)
def test_strict_validation_rejects_identity_reference_and_line_geometry(
    features,
    code,
) -> None:
    layout, program = _office_candidate()

    report = _strict(replace(layout, basic_design=features(layout.basic_design)), program)

    assert code in _codes(report)


@pytest.mark.parametrize(
    ("line_id", "expected_code"),
    [
        ("exit-1", "protected_exit_geometry"),
        ("open-work-window", "window_geometry"),
        ("grid-x", "basic_design_geometry"),
        ("overall-width", "basic_design_geometry"),
        ("street", "basic_design_geometry"),
        ("north", "basic_design_geometry"),
        ("scale", "basic_design_geometry"),
    ],
)
def test_semantic_segments_reject_bent_three_point_geometry(
    line_id,
    expected_code,
) -> None:
    layout, program = _office_candidate()
    features = layout.basic_design
    assert features is not None
    line = _line(features, line_id)
    bent = replace(
        line,
        points=(line.points[0], (8.0, -10.0), line.points[-1]),
        clear_width=21.9 if line.kind == "protected_exit" else line.clear_width,
    )

    report = _strict(
        replace(layout, basic_design=_replace_line(features, bent)),
        program,
    )

    assert expected_code in _codes(report)


def test_commercial_entrance_rejects_bent_geometry_and_width_mismatch() -> None:
    layout, program = _commercial_candidate()
    features = layout.basic_design
    assert features is not None
    entrance = _line(features, "commercial-entrance")
    bent = replace(
        entrance,
        points=(entrance.points[0], (2.9, -5.0), entrance.points[-1]),
        clear_width=12.0,
    )
    wrong_width = replace(entrance, clear_width=2.0)

    bent_report = _strict(
        replace(layout, basic_design=_replace_line(features, bent)),
        program,
    )
    width_report = _strict(
        replace(layout, basic_design=_replace_line(features, wrong_width)),
        program,
    )

    assert "entrance_geometry" in _codes(bent_report)
    assert "entrance_geometry" in _codes(width_report)


def test_program_space_type_is_trusted_for_identity_and_required_objects() -> None:
    layout, program = _office_candidate()
    features = layout.basic_design
    assert features is not None
    disguised_room = replace(layout.rooms[0], space_type="sales")
    disguised_object = replace(
        _element(features, "workstation-1"),
        kind="sales_shelf",
    )

    report = _strict(
        replace(
            layout,
            rooms=[disguised_room, layout.rooms[1]],
            basic_design=_replace_element(features, disguised_object),
        ),
        program,
    )

    assert report.accepted is False
    assert "open_work" in _subjects(report, "room_identity")
    assert "open_work" in _subjects(report, "placed_object_missing")


def test_strict_validation_rejects_core_contract_failures() -> None:
    layout, program = _office_candidate()
    features = layout.basic_design
    assert features is not None
    outside_stair = replace(
        _element(features, "stair-1"),
        footprint=((7.8, 0.0), (9.0, 0.0), (9.0, 2.0), (7.8, 2.0)),
    )
    overlapping_stair = replace(
        _element(features, "stair-2"),
        footprint=_element(features, "stair-1").footprint,
    )

    outside = _strict(
        replace(layout, basic_design=_replace_element(features, outside_stair)),
        program,
    )
    overlap = _strict(
        replace(layout, basic_design=_replace_element(features, overlapping_stair)),
        program,
    )
    missing = _strict(
        replace(
            layout,
            basic_design=replace(
                features,
                elements=tuple(
                    element for element in features.elements if element.kind != "shaft"
                ),
            ),
        ),
        program,
    )
    nonrectangular_core = replace(
        layout.rooms[1],
        polygon=[
            (8.0, 0.0),
            (12.0, 0.0),
            (12.0, 6.0),
            (10.0, 6.0),
            (10.0, 4.0),
            (8.0, 4.0),
        ],
    )
    malformed = _strict(
        replace(layout, rooms=[layout.rooms[0], nonrectangular_core]),
        program,
    )

    assert "core_subspace_containment" in _codes(outside)
    assert "core_subspace_overlap" in _codes(overlap)
    assert "vertical_missing" in _codes(missing)
    assert "core_geometry" in _codes(malformed)


def test_strict_validation_rejects_small_or_touching_representative_stairs() -> None:
    layout, program = _office_candidate()
    features = layout.basic_design
    assert features is not None
    undersized = _replace_element(
        features,
        replace(
            _element(features, "stair-1"),
            footprint=((13.2, 0.0), (15.0, 0.0), (15.0, 2.0), (13.2, 2.0)),
        ),
    )
    touching = _replace_element(
        features,
        replace(
            _element(features, "stair-2"),
            footprint=((13.2, 2.8), (18.0, 2.8), (18.0, 5.6), (13.2, 5.6)),
        ),
    )

    assert "stair_geometry" in _codes(
        _strict(replace(layout, basic_design=undersized), program)
    )
    assert "stair_geometry" in _codes(
        _strict(replace(layout, basic_design=touching), program)
    )


def test_strict_validation_rejects_invalid_stair_door_and_lobby_route() -> None:
    layout, program = _office_candidate()
    features = layout.basic_design
    assert features is not None
    off_boundary_door = _replace_line(
        features,
        replace(
            _line(features, "stair-door-1"),
            points=((14.0, 0.5), (14.0, 1.4)),
        ),
    )
    wrong_route_start = _replace_line(
        features,
        replace(
            _line(features, "lobby-route-1"),
            points=((8.0, 1.2), (13.2, 1.2), (13.2, 0.95)),
        ),
    )
    duplicate_target = _replace_line(
        features,
        replace(
            _line(features, "lobby-route-2"),
            target_id="stair-door-1",
        ),
    )

    assert "stair_door_geometry" in _codes(
        _strict(replace(layout, basic_design=off_boundary_door), program)
    )
    assert "lobby_route_geometry" in _codes(
        _strict(replace(layout, basic_design=wrong_route_start), program)
    )
    assert "lobby_route_reference" in _codes(
        _strict(replace(layout, basic_design=duplicate_target), program)
    )


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda features: replace(
                features,
                lines=tuple(
                    line for line in features.lines if line.line_id != "exit-2"
                ),
            ),
            "protected_exit_count",
        ),
        (
            lambda features: _replace_line(
                features,
                replace(_line(features, "exit-1"), clear_width=0.7),
            ),
            "protected_exit_width",
        ),
        (
            lambda features: _replace_line(
                features,
                replace(
                    _line(features, "exit-2"),
                    points=((8.0, 1.6), (8.0, 2.5)),
                ),
            ),
            "protected_exit_separation",
        ),
        (
            lambda features: _replace_line(
                features,
                replace(
                    _line(features, "exit-1"),
                    points=((7.0, 0.5), (7.0, 1.4)),
                ),
            ),
            "protected_exit_geometry",
        ),
    ],
)
def test_strict_validation_rejects_protected_exit_failures(mutate, code) -> None:
    layout, program = _office_candidate()
    assert layout.basic_design is not None

    report = _strict(
        replace(layout, basic_design=mutate(layout.basic_design)),
        program,
    )

    assert code in _codes(report)


def test_protected_exits_reference_two_distinct_stairs() -> None:
    layout, program = _office_candidate()
    features = layout.basic_design
    assert features is not None
    duplicate_target = _replace_line(
        features,
        replace(_line(features, "exit-2"), target_id="stair-1"),
    )

    valid = _strict(layout, program)
    duplicate = _strict(replace(layout, basic_design=duplicate_target), program)

    assert "protected_exit_reference" not in _codes(valid)
    assert "protected_exit_reference" in _codes(duplicate)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda features: replace(
                features,
                lines=tuple(
                    line for line in features.lines if line.line_id != "route-2"
                ),
            ),
            "egress_route_missing",
        ),
        (
            lambda features: _replace_line(
                features,
                replace(_line(features, "route-2"), target_id="exit-1"),
            ),
            "egress_route_missing",
        ),
        (
            lambda features: _replace_line(
                features,
                replace(
                    _line(features, "route-1"),
                    points=((5.0, 5.0), (8.0, 0.95)),
                ),
            ),
            "egress_route_geometry",
        ),
        (
            lambda features: _replace_line(
                features,
                replace(
                    _line(features, "route-1"),
                    points=((6.0, 3.55), (8.0, 0.95)),
                ),
            ),
            "egress_route_geometry",
        ),
        (
            lambda features: _replace_line(
                features,
                replace(
                    _line(features, "route-1"),
                    points=(
                        (6.0, 3.55),
                        (5.0, 3.55),
                        (5.0, 0.95),
                        (8.0, 0.95),
                    ),
                ),
            ),
            "egress_route_geometry",
        ),
        (
            lambda features: _replace_line(
                features,
                replace(_line(features, "route-1"), target_id="missing-exit"),
            ),
            "egress_route_reference",
        ),
    ],
)
def test_strict_validation_rejects_route_failures(mutate, code) -> None:
    layout, program = _office_candidate()
    assert layout.basic_design is not None

    report = _strict(
        replace(layout, basic_design=mutate(layout.basic_design)),
        program,
    )

    assert code in _codes(report)


@pytest.mark.parametrize(
    ("footprint", "code"),
    [
        (((17.8, 9.0), (18.2, 9.0), (18.2, 9.4), (17.8, 9.4)), "column_boundary"),
        (((8.5, 3.0), (8.9, 3.0), (8.9, 3.4), (8.5, 3.4)), "column_conflict"),
        (((5.8, 3.2), (6.2, 3.2), (6.2, 3.6), (5.8, 3.6)), "column_conflict"),
    ],
)
def test_strict_validation_rejects_column_failures(footprint, code) -> None:
    layout, program = _office_candidate()
    features = layout.basic_design
    assert features is not None
    invalid = replace(_element(features, "column-1"), footprint=footprint)

    report = _strict(
        replace(layout, basic_design=_replace_element(features, invalid)),
        program,
    )

    assert code in _codes(report)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda features: replace(
                features,
                lines=tuple(line for line in features.lines if line.kind != "window"),
            ),
            "window_missing",
        ),
        (
            lambda features: _replace_line(
                features,
                replace(_line(features, "open-work-window"), host_id="missing-room"),
            ),
            "window_reference",
        ),
        (
            lambda features: _replace_line(
                features,
                replace(
                    _line(features, "open-work-window"),
                    points=((1.0, 1.0), (2.0, 1.0)),
                ),
            ),
            "window_geometry",
        ),
    ],
)
def test_strict_validation_rejects_window_failures(mutate, code) -> None:
    layout, program = _office_candidate()
    assert layout.basic_design is not None

    report = _strict(
        replace(layout, basic_design=mutate(layout.basic_design)),
        program,
    )

    assert code in _codes(report)


def test_commercial_entrance_must_be_on_sales_and_street_without_window_overlap() -> None:
    layout, program = _commercial_candidate()
    features = layout.basic_design
    assert features is not None
    entrance = _line(features, "commercial-entrance")
    missing = _strict(
        replace(
            layout,
            basic_design=replace(
                features,
                lines=tuple(line for line in features.lines if line.kind != "entrance"),
            ),
        ),
        program,
    )
    off_street = _strict(
        replace(
            layout,
            basic_design=_replace_line(
                features,
                replace(entrance, points=((6.0, 1.0), (6.0, 2.8))),
            ),
        ),
        program,
    )
    overlap = _strict(
        replace(
            layout,
            basic_design=_replace_line(
                features,
                replace(_line(features, "sales-window"), points=entrance.points),
            ),
        ),
        program,
    )

    assert "entrance_missing" in _codes(missing)
    assert "entrance_geometry" in _codes(off_street)
    assert "window_conflict" in _codes(overlap)


def test_strict_validation_rejects_object_reference_containment_overlap_and_missing() -> None:
    layout, program = _office_candidate()
    features = layout.basic_design
    assert features is not None
    workstation = _element(features, "workstation-1")
    unknown_host = _strict(
        replace(
            layout,
            basic_design=_replace_element(
                features,
                replace(workstation, host_id="missing-room"),
            ),
        ),
        program,
    )
    outside = _strict(
        replace(
            layout,
            basic_design=_replace_element(
                features,
                replace(
                    workstation,
                    footprint=((5.5, 7.5), (6.5, 7.5), (6.5, 8.5), (5.5, 8.5)),
                ),
            ),
        ),
        program,
    )
    duplicate = replace(workstation, element_id="workstation-2")
    overlap = _strict(
        replace(
            layout,
            basic_design=replace(features, elements=(*features.elements, duplicate)),
        ),
        program,
    )
    missing = _strict(
        replace(
            layout,
            basic_design=replace(
                features,
                elements=tuple(
                    element for element in features.elements if element.kind != "workstation"
                ),
            ),
        ),
        program,
    )

    assert "placed_object_reference" in _codes(unknown_host)
    assert "placed_object_containment" in _codes(outside)
    assert "placed_object_overlap" in _codes(overlap)
    assert "placed_object_missing" in _codes(missing)


def test_strict_validation_rejects_sales_shelf_on_room_door_clearance() -> None:
    layout, program = _commercial_candidate()
    features = layout.basic_design
    assert features is not None
    shelf = _element(features, "sales-shelf-1")
    blocking_shelf = replace(
        shelf,
        footprint=((5.7, 3.2), (6.0, 3.2), (6.0, 3.9), (5.7, 3.9)),
    )

    report = _strict(
        replace(
            layout,
            basic_design=_replace_element(features, blocking_shelf),
        ),
        program,
    )

    assert "placed_object_clearance" in _codes(report)
    assert report.basic_design is not None
    assert report.basic_design.object_clearance_violation_count >= 1


@pytest.mark.parametrize(
    "footprint",
    [
        ((2.3, 0.0), (3.0, 0.0), (3.0, 0.4), (2.3, 0.4)),
        ((0.5, 0.0), (1.2, 0.0), (1.2, 0.4), (0.5, 0.4)),
    ],
)
def test_strict_validation_rejects_sales_objects_at_entrance_or_window(
    footprint,
) -> None:
    layout, program = _commercial_candidate()
    features = layout.basic_design
    assert features is not None
    blocking = replace(
        _element(features, "sales-shelf-1"),
        footprint=footprint,
    )

    report = _strict(
        replace(layout, basic_design=_replace_element(features, blocking)),
        program,
    )

    assert "placed_object_clearance" in _codes(report)


def test_strict_validation_recomputes_dimensions_and_requires_site_and_structure() -> None:
    layout, program = _office_candidate()
    features = layout.basic_design
    assert features is not None
    wrong_width = _strict(
        replace(
            layout,
            basic_design=_replace_line(
                features,
                replace(_line(features, "overall-width"), measured_value=999.0),
            ),
        ),
        program,
    )
    missing_dimension = _strict(
        replace(
            layout,
            basic_design=replace(
                features,
                lines=tuple(
                    line for line in features.lines if line.kind != "circulation_width"
                ),
            ),
        ),
        program,
    )
    missing_site = _strict(
        replace(
            layout,
            basic_design=replace(
                features,
                lines=tuple(line for line in features.lines if line.kind != "north_arrow"),
            ),
        ),
        program,
    )
    missing_grid = _strict(
        replace(
            layout,
            basic_design=replace(
                features,
                lines=tuple(line for line in features.lines if line.kind != "grid"),
            ),
        ),
        program,
    )
    wrong_street = _strict(
        replace(
            layout,
            basic_design=_replace_line(
                features,
                replace(_line(features, "street"), points=((0.0, 10.0), (12.0, 10.0))),
            ),
        ),
        program,
    )

    assert "dimension_value" in _codes(wrong_width)
    assert "dimension_missing" in _codes(missing_dimension)
    assert "site_missing" in _codes(missing_site)
    assert "structure_missing" in _codes(missing_grid)
    assert "site_geometry" in _codes(wrong_street)


def test_building_generation_enables_strict_validation_and_aligns_structure() -> None:
    mass = MassInput(
        project_id="strict-building",
        floors=2,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 0.5, "office": 0.5},
    )

    result = run_building_generation(mass)

    assert result.accepted
    assert all(floor.validation.basic_design_checked for floor in result.floor_results)
    first, second = (floor.layout.basic_design for floor in result.floor_results)
    assert first is not None and second is not None
    assert _structure_geometry(first) == _structure_geometry(second)


def test_json_manifest_list_points_run_through_building_generation() -> None:
    manifest_path = (
        Path(__file__).parents[2]
        / "datasets"
        / "manifests"
        / "sample_mass_office_commercial.json"
    )
    with manifest_path.open(encoding="utf-8") as handle:
        mass = MassInput(**json.load(handle))

    result = run_building_generation(mass)

    assert result.accepted
    assert len(result.floor_results) == 5


def _strict(layout: LayoutCandidate, program: ProgramGraph):
    return validate_layout(
        layout,
        program,
        BOUNDARY,
        street_segments=STREET,
        require_basic_design=True,
    )


def _office_candidate() -> tuple[LayoutCandidate, ProgramGraph]:
    rooms = [
        RoomPolygon(
            "open_work",
            "open_work",
            [(0.0, 0.0), (6.0, 0.0), (6.0, 8.0), (0.0, 8.0)],
        ),
        RoomPolygon(
            "core",
            "core",
            [(8.0, 0.0), (18.0, 0.0), (18.0, 6.0), (8.0, 6.0)],
        ),
    ]
    layout = LayoutCandidate(
        candidate_id="independent-office",
        project_id="strict-test",
        floor_index=1,
        rooms=rooms,
        circulation=[
            RoomPolygon(
                "corridor",
                "circulation",
                [(6.0, 0.0), (8.0, 0.0), (8.0, 10.0), (6.0, 10.0)],
            )
        ],
        score=0.0,
        openings=[
            OpeningSegment(
                "open-work-door",
                "door",
                ("open_work", "corridor"),
                (6.0, 3.1),
                (6.0, 4.0),
                0.9,
            ),
            OpeningSegment(
                "core-door",
                "door",
                ("core", "corridor"),
                (8.0, 3.1),
                (8.0, 4.0),
                0.9,
            ),
        ],
        basic_design=_office_features(),
    )
    return layout, ProgramGraph(
        project_id="strict-test",
        floor_index=1,
        use_type="office",
        nodes=[
            ProgramNode("open_work", "open_work", 48.0),
            ProgramNode("core", "core", 60.0),
        ],
        edges=[],
        source="independent-test",
    )


def _commercial_candidate() -> tuple[LayoutCandidate, ProgramGraph]:
    office, _ = _office_candidate()
    sales = replace(office.rooms[0], room_id="sales", space_type="sales")
    features = office.basic_design
    assert features is not None
    sales_features = replace(
        features,
        elements=tuple(
            replace(element, host_id="sales")
            if element.host_id == "open_work"
            else element
            for element in features.elements
            if element.kind != "workstation"
        )
        + (
            PlanElement(
                "sales-shelf-1",
                "furniture",
                "sales_shelf",
                "sales",
                "SHELF",
                ((1.0, 2.0), (2.0, 2.0), (2.0, 2.8), (1.0, 2.8)),
            ),
        ),
        lines=tuple(
            replace(line, host_id="sales")
            if line.host_id == "open_work"
            else line
            for line in features.lines
        )
        + (
            PlanLine(
                "commercial-entrance",
                "envelope",
                "entrance",
                ((2.0, 0.0), (3.8, 0.0)),
                host_id="sales",
                label="ENTRANCE",
                clear_width=1.8,
            ),
        ),
    )
    sales_features = replace(
        sales_features,
        lines=tuple(
            replace(
                line,
                line_id="sales-window",
                host_id="sales",
                points=((0.2, 0.0), (1.5, 0.0)),
            )
            if line.line_id == "open-work-window"
            else line
            for line in sales_features.lines
        ),
    )
    return replace(
        office,
        candidate_id="independent-commercial",
        rooms=[sales, office.rooms[1]],
        openings=[
            replace(
                office.openings[0],
                opening_id="sales-door",
                connects=("sales", "corridor"),
            ),
            office.openings[1],
        ],
        basic_design=sales_features,
    ), ProgramGraph(
        project_id="strict-test",
        floor_index=1,
        use_type="neighborhood_commercial",
        nodes=[
            ProgramNode("sales", "sales", 48.0),
            ProgramNode("core", "core", 24.0),
        ],
        edges=[],
        source="independent-test",
    )


def _office_features() -> BasicDesignFeatures:
    elements = (
        PlanElement(
            "stair-1",
            "vertical",
            "stair",
            "core",
            "UP",
            ((13.2, 0.0), (18.0, 0.0), (18.0, 2.8), (13.2, 2.8)),
        ),
        PlanElement(
            "stair-2",
            "vertical",
            "stair",
            "core",
            "UP",
            ((13.2, 3.2), (18.0, 3.2), (18.0, 6.0), (13.2, 6.0)),
        ),
        PlanElement(
            "elevator-1",
            "vertical",
            "elevator",
            "core",
            "ELEV",
            ((10.8, 1.8), (12.0, 1.8), (12.0, 4.2), (10.8, 4.2)),
        ),
        PlanElement(
            "shaft-1",
            "vertical",
            "shaft",
            "core",
            "SHAFT",
            ((12.0, 1.8), (13.2, 1.8), (13.2, 4.2), (12.0, 4.2)),
        ),
        PlanElement(
            "lobby-1",
            "vertical",
            "lobby",
            "core",
            "LOBBY",
            (
                (8.0, 0.0),
                (13.2, 0.0),
                (13.2, 1.8),
                (10.8, 1.8),
                (10.8, 4.2),
                (13.2, 4.2),
                (13.2, 6.0),
                (8.0, 6.0),
            ),
        ),
        PlanElement(
            "column-1",
            "structure",
            "column",
            "floor",
            "COL",
            ((10.0, 8.0), (10.4, 8.0), (10.4, 8.4), (10.0, 8.4)),
        ),
        PlanElement(
            "workstation-1",
            "furniture",
            "workstation",
            "open_work",
            "DESK",
            ((1.0, 2.0), (2.0, 2.0), (2.0, 2.8), (1.0, 2.8)),
        ),
    )
    lines = (
        PlanLine(
            "exit-1",
            "egress",
            "protected_exit",
            ((8.0, 0.5), (8.0, 1.4)),
            host_id="core",
            target_id="stair-1",
            clear_width=0.9,
        ),
        PlanLine(
            "exit-2",
            "egress",
            "protected_exit",
            ((8.0, 4.6), (8.0, 5.5)),
            host_id="core",
            target_id="stair-2",
            clear_width=0.9,
        ),
        PlanLine(
            "route-1",
            "egress",
            "egress_route",
            ((6.0, 3.55), (7.0, 3.55), (7.0, 0.95), (8.0, 0.95)),
            host_id="open_work",
            target_id="exit-1",
        ),
        PlanLine(
            "route-2",
            "egress",
            "egress_route",
            ((6.0, 3.55), (7.0, 3.55), (7.0, 5.05), (8.0, 5.05)),
            host_id="open_work",
            target_id="exit-2",
        ),
        PlanLine(
            "stair-door-1",
            "egress",
            "stair_door",
            ((13.2, 0.5), (13.2, 1.4)),
            host_id="lobby-1",
            target_id="stair-1",
            clear_width=0.9,
        ),
        PlanLine(
            "stair-door-2",
            "egress",
            "stair_door",
            ((13.2, 4.6), (13.2, 5.5)),
            host_id="lobby-1",
            target_id="stair-2",
            clear_width=0.9,
        ),
        PlanLine(
            "lobby-route-1",
            "egress",
            "lobby_route",
            ((8.0, 0.95), (13.2, 0.95)),
            host_id="lobby-1",
            target_id="stair-door-1",
        ),
        PlanLine(
            "lobby-route-2",
            "egress",
            "lobby_route",
            ((8.0, 5.05), (13.2, 5.05)),
            host_id="lobby-1",
            target_id="stair-door-2",
        ),
        PlanLine("grid-x", "structure", "grid", ((3.0, 0.0), (3.0, 10.0))),
        PlanLine("grid-y", "structure", "grid", ((0.0, 5.0), (18.0, 5.0))),
        PlanLine(
            "open-work-window",
            "envelope",
            "window",
            ((2.0, 0.0), (4.0, 0.0)),
            host_id="open_work",
        ),
        PlanLine(
            "overall-width",
            "dimension",
            "overall_width",
            ((0.0, 0.0), (18.0, 0.0)),
            measured_value=18.0,
        ),
        PlanLine(
            "overall-depth",
            "dimension",
            "overall_depth",
            ((0.0, 0.0), (0.0, 10.0)),
            measured_value=10.0,
        ),
        PlanLine(
            "corridor-width",
            "dimension",
            "circulation_width",
            ((0.0, 10.0), (2.0, 10.0)),
            measured_value=2.0,
        ),
        PlanLine(
            "street",
            "site",
            "street",
            ((0.0, 0.0), (18.0, 0.0)),
            label="STREET",
        ),
        PlanLine(
            "north",
            "site",
            "north_arrow",
            ((11.0, 8.0), (11.0, 9.0)),
            label="N",
        ),
        PlanLine(
            "scale",
            "site",
            "scale_line",
            ((0.5, 0.5), (5.5, 0.5)),
            label="5m",
            measured_value=5.0,
        ),
    )
    return BasicDesignFeatures(
        elements,
        lines,
        planning=UsePlanningMetadata(),
    )


def _replace_element(
    features: BasicDesignFeatures,
    replacement: PlanElement,
) -> BasicDesignFeatures:
    return replace(
        features,
        elements=tuple(
            replacement if element.element_id == replacement.element_id else element
            for element in features.elements
        ),
    )


def _replace_line(
    features: BasicDesignFeatures,
    replacement: PlanLine,
) -> BasicDesignFeatures:
    return replace(
        features,
        lines=tuple(
            replacement if line.line_id == replacement.line_id else line
            for line in features.lines
        ),
    )


def _element(features: BasicDesignFeatures, element_id: str) -> PlanElement:
    return next(element for element in features.elements if element.element_id == element_id)


def _line(features: BasicDesignFeatures, line_id: str) -> PlanLine:
    return next(line for line in features.lines if line.line_id == line_id)


def _codes(report) -> set[str]:
    return {violation.code for violation in report.violations}


def _subjects(report, code: str) -> set[str]:
    return {
        violation.subject
        for violation in report.violations
        if violation.code == code
    }


def _structure_geometry(features: BasicDesignFeatures):
    return (
        tuple(
            (element.element_id, element.footprint)
            for element in features.elements
            if element.category == "structure"
        ),
        tuple(
            (line.line_id, line.points)
            for line in features.lines
            if line.category == "structure"
        ),
    )
