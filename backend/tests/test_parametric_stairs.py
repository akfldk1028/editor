from __future__ import annotations

from dataclasses import replace

import pytest
from PIL import Image

from backend.app.modules.basic_design.stair import create_stair_geometry
from backend.app.modules.generation_loop.service import (
    run_building_alternatives,
    run_building_generation,
)
from backend.app.modules.validator.service import validate_layout
from backend.app.modules.validator.service import _stair_door_swing_is_valid
from backend.app.modules.visual_review.service import create_building_visual_review_artifacts
from backend.app.schemas.mass import BuildingCodeContext, MassInput
from backend.app.schemas.layout import DoorSwing, PlanLine


def _mass(height: float | None) -> MassInput:
    context = (
        BuildingCodeContext(
            jurisdiction="KR",
            effective_date="2025-10-31",
            sprinklered=True,
            floor_to_floor_height_m=height,
        )
        if height is not None
        else None
    )
    return MassInput(
        project_id=f"parametric-stair-{height}",
        floors=2,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 0.5, "office": 0.5},
        building_code_context=context,
    )


@pytest.mark.parametrize(
    ("height", "expected_risers", "expected_treads"),
    [(3.0, 17, 15), (3.6, 20, 18)],
)
def test_building_stairs_are_derived_from_project_floor_height(
    height: float,
    expected_risers: int,
    expected_treads: int,
) -> None:
    result = run_building_generation(_mass(height))

    for floor in result.floor_results:
        stairs = [
            element
            for element in floor.layout.basic_design.elements
            if element.kind == "stair"
        ]
        assert len(stairs) == 2
        for stair in stairs:
            geometry = stair.stair_geometry
            assert geometry is not None
            assert geometry.height_source == "project-fact"
            assert geometry.floor_to_floor_height_m == pytest.approx(height)
            assert geometry.riser_count == expected_risers
            assert sum(flight.riser_count for flight in geometry.flights) == expected_risers
            assert sum(flight.tread_count for flight in geometry.flights) == expected_treads
            assert geometry.riser_height_m * geometry.riser_count == pytest.approx(height)
            assert len(geometry.flights) == 2
            assert [landing.role for landing in geometry.landings] == [
                "floor_lower",
                "intermediate",
                "floor_upper",
            ]
            assert [landing.elevation_m for landing in geometry.landings] == pytest.approx(
                [0.0, geometry.flights[0].end_elevation_m, height]
            )


def test_missing_floor_height_is_explicit_concept_default() -> None:
    result = run_building_generation(_mass(None))

    stair = next(
        element
        for element in result.floor_results[0].layout.basic_design.elements
        if element.kind == "stair"
    )
    assert stair.stair_geometry is not None
    assert stair.stair_geometry.height_source == "concept-default"


@pytest.mark.parametrize("height", [4.2, 4.4, 4.5, 4.8])
def test_tall_floor_heights_generate_without_unhandled_geometry_errors(
    height: float,
) -> None:
    result = run_building_generation(_mass(height))

    assert result.floor_results
    for floor in result.floor_results:
        for stair in (
            element
            for element in floor.layout.basic_design.elements
            if element.kind == "stair"
        ):
            geometry = stair.stair_geometry
            assert geometry is not None
            assert geometry.floor_to_floor_height_m == pytest.approx(height)
            assert geometry.required_enclosure_length_m <= max(
                max(x for x, _ in stair.footprint)
                - min(x for x, _ in stair.footprint),
                max(y for _, y in stair.footprint)
                - min(y for _, y in stair.footprint),
            )


def test_oversized_stair_host_contains_centered_derived_enclosure() -> None:
    geometry = create_stair_geometry(
        ((0.0, 0.0), (8.0, 0.0), (8.0, 4.0), (0.0, 4.0)),
        floor_to_floor_height_m=3.6,
        height_source="project-fact",
    )

    assert geometry.enclosure_footprint != (
        (0.0, 0.0),
        (8.0, 0.0),
        (8.0, 4.0),
        (0.0, 4.0),
    )
    xs = [point[0] for point in geometry.enclosure_footprint]
    ys = [point[1] for point in geometry.enclosure_footprint]
    assert max(xs) - min(xs) == pytest.approx(4.92)
    assert max(ys) - min(ys) == pytest.approx(2.8)
    assert (min(xs) + max(xs)) / 2 == pytest.approx(4.0)
    assert (min(ys) + max(ys)) / 2 == pytest.approx(2.0)

    reversed_geometry = create_stair_geometry(
        ((0.0, 0.0), (8.0, 0.0), (8.0, 4.0), (0.0, 4.0)),
        floor_to_floor_height_m=3.6,
        height_source="project-fact",
        entry_points=((8.0, 1.0), (8.0, 1.9)),
    )
    assert [flight.direction for flight in reversed_geometry.flights] == [
        "-x",
        "+x",
    ]


def test_door_closed_leaf_endpoint_must_remain_in_lower_landing() -> None:
    geometry = create_stair_geometry(
        ((0.0, 0.0), (8.0, 0.0), (8.0, 4.0), (0.0, 4.0)),
        floor_to_floor_height_m=3.6,
        height_source="project-fact",
    )
    lower = next(
        landing for landing in geometry.landings if landing.role == "floor_lower"
    )
    hinge = (1.54, 3.3)
    line = PlanLine(
        "outside-closed-leaf",
        "egress",
        "stair_door",
        (hinge, (1.54, 4.2)),
        clear_width=0.9,
    )
    swing = DoorSwing(
        hinge=hinge,
        leaf_end=(2.44, 3.3),
        angle_degrees=90.0,
        direction="clockwise",
        target_landing_role="floor_lower",
    )

    assert not _stair_door_swing_is_valid(line, swing, geometry, lower)


def test_tall_floor_height_building_alternatives_return_structured_results() -> None:
    alternatives = run_building_alternatives(_mass(4.8))

    assert len(alternatives.alternatives) == 2
    assert all(alternative.building.floor_results for alternative in alternatives.alternatives)


def test_stair_mutation_is_rejected_and_svg_uses_modeled_tread_count(tmp_path) -> None:
    mass = _mass(3.6)
    result = run_building_generation(mass)
    floor = result.floor_results[0]
    features = floor.layout.basic_design
    stair = next(element for element in features.elements if element.kind == "stair")
    geometry = stair.stair_geometry
    assert geometry is not None
    first_flight = geometry.flights[0]
    broken_flight = replace(first_flight, tread_count=first_flight.tread_count - 1)
    broken_geometry = replace(
        geometry,
        flights=(broken_flight, geometry.flights[1]),
    )
    broken_stair = replace(stair, stair_geometry=broken_geometry)
    broken_features = replace(
        features,
        elements=tuple(
            broken_stair if element.element_id == stair.element_id else element
            for element in features.elements
        ),
    )
    report = validate_layout(
        replace(floor.layout, basic_design=broken_features),
        floor.program,
        boundary=mass.footprint_polygon,
        street_segments=[((0, 0), (30, 0))],
        require_openings=True,
        require_basic_design=True,
        building_code_context=mass.building_code_context,
    )
    assert "stair_tread_count" in {violation.code for violation in report.violations}

    short_flight = replace(
        first_flight,
        end_elevation_m=first_flight.end_elevation_m - 0.1,
    )
    short_geometry = replace(
        geometry,
        flights=(short_flight, geometry.flights[1]),
    )
    short_stair = replace(stair, stair_geometry=short_geometry)
    short_features = replace(
        features,
        elements=tuple(
            short_stair if element.element_id == stair.element_id else element
            for element in features.elements
        ),
    )
    short_report = validate_layout(
        replace(floor.layout, basic_design=short_features),
        floor.program,
        boundary=mass.footprint_polygon,
        street_segments=[((0, 0), (30, 0))],
        require_openings=True,
        require_basic_design=True,
        building_code_context=mass.building_code_context,
    )
    assert "stair_rise_sum" in {
        violation.code for violation in short_report.violations
    }

    artifacts = create_building_visual_review_artifacts(
        result,
        mass.footprint_polygon,
        tmp_path,
        render_style="architectural",
    )
    svg = artifacts.floor_artifacts[0].svg_path.read_text(encoding="utf-8")
    modeled_treads = sum(
        flight.tread_count
        for element in features.elements
        if element.kind == "stair" and element.stair_geometry is not None
        for flight in element.stair_geometry.flights
    )
    assert svg.count('data-symbol="stair-tread"') == modeled_treads
    assert 'data-review-status="internal=' in svg
    assert 'viewBox="0 0 960 570"' in svg
    with Image.open(artifacts.floor_artifacts[0].png_path) as image:
        assert image.size == (960, 540)
    report = artifacts.floor_artifacts[0].report_path.read_text(encoding="utf-8")
    assert '"png": "unavailable"' in report
    assert '"stair_geometry"' in report
    assert '"headroom_status": "not_checked"' in report


def test_stair_enclosure_landing_and_door_swing_mutations_are_rejected() -> None:
    mass = _mass(3.6)
    result = run_building_generation(mass)
    floor = result.floor_results[0]
    features = floor.layout.basic_design
    stair = next(element for element in features.elements if element.kind == "stair")
    geometry = stair.stair_geometry
    assert geometry is not None
    stair_door = next(
        line
        for line in features.lines
        if line.kind == "stair_door" and line.target_id == stair.element_id
    )
    assert stair_door.door_swing is not None

    def codes(mutated_features):
        report = validate_layout(
            replace(floor.layout, basic_design=mutated_features),
            floor.program,
            boundary=mass.footprint_polygon,
            street_segments=[((0, 0), (30, 0))],
            require_openings=True,
            require_basic_design=True,
            building_code_context=mass.building_code_context,
        )
        return {violation.code for violation in report.violations}

    bad_enclosure = replace(
        stair,
        stair_geometry=replace(
            geometry,
            required_enclosure_length_m=geometry.required_enclosure_length_m - 0.2,
        ),
    )
    assert "stair_geometry" in codes(
        replace(
            features,
            elements=tuple(
                bad_enclosure if element.element_id == stair.element_id else element
                for element in features.elements
            ),
        )
    )

    landing = geometry.landings[1]
    bad_landing = replace(
        landing,
        footprint=tuple((x + 20, y) for x, y in landing.footprint),
    )
    bad_landing_stair = replace(
        stair,
        stair_geometry=replace(
            geometry,
            landings=(geometry.landings[0], bad_landing, geometry.landings[2]),
        ),
    )
    assert "stair_landing_geometry" in codes(
        replace(
            features,
            elements=tuple(
                bad_landing_stair if element.element_id == stair.element_id else element
                for element in features.elements
            ),
        )
    )
    for invalid_landing in (
        replace(landing, role="floor_lower"),
        replace(landing, elevation_m=landing.elevation_m - 0.1),
    ):
        invalid_stair = replace(
            stair,
            stair_geometry=replace(
                geometry,
                landings=(
                    geometry.landings[0],
                    invalid_landing,
                    geometry.landings[2],
                ),
            ),
        )
        assert "stair_landing_geometry" in codes(
            replace(
                features,
                elements=tuple(
                    invalid_stair
                    if element.element_id == stair.element_id
                    else element
                    for element in features.elements
                ),
            )
        )

    bad_swing_line = replace(
        stair_door,
        door_swing=replace(stair_door.door_swing, leaf_end=(999.0, 999.0)),
    )
    assert "stair_door_swing" in codes(
        replace(
            features,
            lines=tuple(
                bad_swing_line if line.line_id == stair_door.line_id else line
                for line in features.lines
            ),
        )
    )
    for bad_swing in (
        replace(
            stair_door.door_swing,
            leaf_end=(
                stair_door.door_swing.hinge[0],
                stair_door.door_swing.hinge[1] + 0.3,
            ),
        ),
        replace(stair_door.door_swing, angle_degrees=45.0),
        replace(
            stair_door.door_swing,
            direction=(
                "clockwise"
                if stair_door.door_swing.direction == "counterclockwise"
                else "counterclockwise"
            ),
        ),
    ):
        invalid_line = replace(stair_door, door_swing=bad_swing)
        assert "stair_door_swing" in codes(
            replace(
                features,
                lines=tuple(
                    invalid_line if line.line_id == stair_door.line_id else line
                    for line in features.lines
                ),
            )
        )

    reversed_direction = (
        "-x"
        if geometry.flights[0].direction == "+x"
        else "+x"
        if geometry.flights[0].direction == "-x"
        else "-y"
        if geometry.flights[0].direction == "+y"
        else "+y"
    )
    bad_direction_stair = replace(
        stair,
        stair_geometry=replace(
            geometry,
            flights=(
                replace(geometry.flights[0], direction=reversed_direction),
                geometry.flights[1],
            ),
        ),
    )
    assert "stair_flight_direction" in codes(
        replace(
            features,
            elements=tuple(
                bad_direction_stair
                if element.element_id == stair.element_id
                else element
                for element in features.elements
            ),
        )
    )


def test_validator_rejects_project_height_mismatch() -> None:
    mass = _mass(3.6)
    result = run_building_generation(mass)
    floor = result.floor_results[0]
    features = floor.layout.basic_design
    stair = next(element for element in features.elements if element.kind == "stair")
    geometry = stair.stair_geometry
    assert geometry is not None
    mismatched = replace(
        stair,
        stair_geometry=replace(geometry, floor_to_floor_height_m=3.5),
    )
    report = validate_layout(
        replace(
            floor.layout,
            basic_design=replace(
                features,
                elements=tuple(
                    mismatched if element.element_id == stair.element_id else element
                    for element in features.elements
                ),
            ),
        ),
        floor.program,
        boundary=mass.footprint_polygon,
        street_segments=[((0, 0), (30, 0))],
        require_openings=True,
        require_basic_design=True,
        building_code_context=mass.building_code_context,
    )
    assert "stair_height_context" in {
        violation.code for violation in report.violations
    }
