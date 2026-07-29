from __future__ import annotations

from dataclasses import replace
import math

import pytest
from shapely import union_all
from shapely.geometry import Polygon, box

from backend.app.modules.basic_design.service import generate_basic_design
from backend.app.modules.layout_generator.orthogonal import (
    generate_orthogonal_office_layout,
)
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.modules.validator.service import validate_layout
from backend.app.schemas.mass import MassInput


CASES = (
    (
        "l",
        [
            (0, 0),
            (30, 0),
            (30, 12),
            (14, 12),
            (14, 24),
            (0, 24),
        ],
        [(22, 0), (30, 0), (30, 7), (22, 7)],
        box(14, 12, 30, 24),
    ),
    (
        "u",
        [
            (0, 0),
            (32, 0),
            (32, 24),
            (22, 24),
            (22, 10),
            (10, 10),
            (10, 24),
            (0, 24),
        ],
        [(12, 1), (20, 1), (20, 8), (12, 8)],
        box(10, 10, 22, 24),
    ),
)


def _program(case: str, boundary):
    mass = MassInput(
        project_id=f"orthogonal-{case}",
        floors=1,
        footprint_polygon=boundary,
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"office": 1.0},
    )
    return generate_program_graph(
        analyze_mass(mass),
        floor_index=1,
        use_type="office",
    )


@pytest.mark.parametrize(
    ("case", "boundary", "core", "notch"),
    CASES,
)
def test_orthogonal_office_layout_stays_inside_l_and_u_footprints(
    case,
    boundary,
    core,
    notch,
) -> None:
    program = _program(case, boundary)

    layout = generate_orthogonal_office_layout(
        boundary,
        program,
        core_polygon=core,
    )
    repeated = generate_orthogonal_office_layout(
        boundary,
        program,
        core_polygon=core,
    )

    assert layout == repeated
    assert len(layout.rooms) == len(program.nodes)
    assert len(layout.openings) == len(layout.rooms)
    assert layout.remote_stair_footprint is not None
    room_by_type = {room.space_type: room for room in layout.rooms}
    assert room_by_type["core"].polygon == core

    boundary_shape = Polygon(boundary)
    occupied = [
        *[Polygon(room.polygon) for room in layout.rooms],
        *[Polygon(path.polygon) for path in layout.circulation],
        Polygon(layout.remote_stair_footprint),
    ]
    assert all(boundary_shape.covers(shape) for shape in occupied)
    assert all(_is_orthogonal_polygon(shape) for shape in occupied)
    merged = union_all(occupied)
    assert merged.difference(boundary_shape).area == pytest.approx(0)
    assert merged.intersection(notch).area == pytest.approx(0)
    assert sum(shape.area for shape in occupied) == pytest.approx(merged.area)

    circulation = union_all([Polygon(path.polygon) for path in layout.circulation])
    assert isinstance(circulation, Polygon)
    assert circulation.is_valid
    assert all(
        math.dist(opening.start, opening.end) == pytest.approx(0.9)
        for opening in layout.openings
    )
    assert {opening.connects[0] for opening in layout.openings} == {
        room.room_id for room in layout.rooms
    }


@pytest.mark.parametrize(
    ("case", "boundary", "core", "_notch"),
    CASES,
)
def test_orthogonal_layout_is_consumable_by_validator_and_basic_design(
    case,
    boundary,
    core,
    _notch,
) -> None:
    program = _program(case, boundary)
    layout = generate_orthogonal_office_layout(
        boundary,
        program,
        core_polygon=core,
    )

    report = validate_layout(
        layout,
        program,
        boundary=boundary,
        min_circulation_width=1.2,
    )
    features = generate_basic_design(
        layout,
        boundary=boundary,
        street_segments=[(boundary[0], boundary[1])],
    )

    assert isinstance(report.accepted, bool)
    assert report.room_areas
    assert features.elements
    assert features.lines


def test_orthogonal_layout_rejects_core_outside_notched_boundary() -> None:
    boundary = CASES[0][1]
    program = _program("invalid-core", boundary)

    with pytest.raises(ValueError, match="core must be inside"):
        generate_orthogonal_office_layout(
            boundary,
            program,
            core_polygon=[
                (20, 16),
                (28, 16),
                (28, 22),
                (20, 22),
            ],
        )


def test_orthogonal_layout_can_respect_learned_program_order() -> None:
    _, boundary, core, _ = CASES[0]
    program = _program("learned-order", boundary)
    core_nodes = [node for node in program.nodes if node.space_type == "core"]
    non_core = [node for node in program.nodes if node.space_type != "core"]
    reversed_program = replace(
        program,
        nodes=[*reversed(non_core), *core_nodes],
    )

    original = generate_orthogonal_office_layout(
        boundary,
        program,
        core_polygon=core,
        respect_program_order=True,
    )
    reversed_layout = generate_orthogonal_office_layout(
        boundary,
        reversed_program,
        core_polygon=core,
        respect_program_order=True,
    )

    original_rooms = {
        room.room_id: tuple(room.polygon)
        for room in original.rooms
        if room.space_type != "core"
    }
    reversed_rooms = {
        room.room_id: tuple(room.polygon)
        for room in reversed_layout.rooms
        if room.space_type != "core"
    }
    assert original_rooms != reversed_rooms
    boundary_shape = Polygon(boundary)
    assert all(
        boundary_shape.covers(Polygon(room.polygon))
        for room in reversed_layout.rooms
    )


def _is_orthogonal_polygon(shape: Polygon) -> bool:
    coordinates = tuple(shape.exterior.coords)
    return (
        shape.is_valid
        and not shape.interiors
        and all(
            math.isclose(start[0], end[0]) or math.isclose(start[1], end[1])
            for start, end in zip(coordinates, coordinates[1:])
        )
    )
