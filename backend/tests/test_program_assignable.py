"""The program sizes on what the plate can assign to rooms, not on its gross area."""

import math

import pytest

from backend.app.modules.program_prior.assignable import (
    CORRIDOR_WIDTH_M,
    assignable_area,
    rectilinear_cover,
)
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.schemas.mass import FloorPlateAnalysis, MassAnalysis
from shapely.geometry import Polygon

# 40 x 30 with a 4 m chamfer on two front corners and a 4-deep V notch at the back.
CHAMFERED = [
    (0.0, 0.0), (36.0, 0.0), (40.0, 4.0), (40.0, 30.0), (24.0, 30.0),
    (20.0, 26.0), (16.0, 30.0), (0.0, 30.0),
]


def test_rectilinear_cover_drops_chamfers_and_notches():
    plate = Polygon(CHAMFERED)
    cover = rectilinear_cover(plate)

    assert cover.geom_type == "Polygon"
    # Chamfer triangle 8 m2, notch triangle 16 m2.
    assert cover.area == pytest.approx(plate.area - 8.0 - 16.0)
    assert plate.buffer(1e-9).covers(cover)


def test_assignable_area_takes_corner_loss_and_a_spine_across_the_long_side():
    result = assignable_area(CHAMFERED)

    assert result.gross_m2 == pytest.approx(Polygon(CHAMFERED).area)
    assert result.corridor_m2 == pytest.approx(CORRIDOR_WIDTH_M * 40.0)
    assert result.assignable_m2 == pytest.approx(result.cover_m2 - CORRIDOR_WIDTH_M * 40.0)
    assert result.allowance_m2 == pytest.approx(24.0 + CORRIDOR_WIDTH_M * 40.0)


def test_a_plate_without_a_footprint_is_its_bounding_rectangle():
    result = assignable_area((), gross_m2=300.0, bounds=(0.0, 0.0, 30.0, 10.0))

    assert result.cover_m2 == 300.0
    assert result.corridor_m2 == pytest.approx(CORRIDOR_WIDTH_M * 30.0)
    with pytest.raises(ValueError):
        assignable_area(())


def test_office_program_sums_to_the_plate_less_its_allowance():
    plate = FloorPlateAnalysis(
        floor_index=1,
        area=Polygon(CHAMFERED).area,
        edge_count=len(CHAMFERED),
        bounds=Polygon(CHAMFERED).bounds,
        footprint_polygon=tuple(CHAMFERED),
        source="test",
    )
    analysis = MassAnalysis(
        project_id="chamfered",
        area=plate.area,
        floor_area=plate.area,
        floors=1,
        edge_count=plate.edge_count,
        street_edge_indices=[0],
        access_edge_indices=[0],
        bounds=plate.bounds,
        floor_plates=(plate,),
    )

    graph = generate_program_graph(analysis, floor_index=1, use_type="office")

    expected_allowance = 24.0 + CORRIDOR_WIDTH_M * 40.0
    assert graph.net_area_allowance_m2 == pytest.approx(expected_allowance)
    assert math.isclose(
        sum(node.target_area for node in graph.nodes),
        plate.area - expected_allowance,
        rel_tol=1e-9,
    )
