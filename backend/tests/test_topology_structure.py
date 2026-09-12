"""The floor structure -- cover, spine, core, stacked stair -- planned once, shared by every room solver."""

import pytest
from shapely.geometry import Polygon, box

from backend.app.modules.topology_planner.dimensioning import TopologyInfeasible
from backend.app.modules.topology_planner.service import _half_diameter
from backend.app.modules.topology_planner.structure import FloorStructure, plan_floor_structure
from backend.tests.test_topology_graph import _office
from backend.tests.test_topology_layout import BOUNDARY, CORE

STAIR = (4.92, 2.8)
# The remote stair has to sit half the plate's diameter from the core's door,
# which a core in the middle of a 37 m plate cannot give; the core goes to one
# end of the rear edge, as the loop places it.
CORE_AT_END = [(0.0, 20.0), (8.0, 20.0), (8.0, 26.0), (0.0, 26.0)]  # 8 x 6, the loop's proportions


def test_the_spine_hugs_the_core_and_runs_the_full_cover():
    structure = plan_floor_structure(BOUNDARY, _office(), core_polygon=CORE)

    assert isinstance(structure, FloorStructure)
    sx0, sy0, sx1, sy1 = structure.spine
    assert sy1 == pytest.approx(18.0)  # the core's inner edge (core at the rear)
    assert sy1 - sy0 == pytest.approx(1.6)
    assert (sx0, sx1) == pytest.approx((0.0, 37.0))
    assert structure.cover.equals(Polygon(BOUNDARY))


def test_the_remote_stair_sits_on_the_spine_inside_the_cover_and_clears_the_exit_separation():
    structure = plan_floor_structure(BOUNDARY, _office(), core_polygon=CORE_AT_END, stair_dimensions=STAIR)

    assert structure.stair is not None
    x0, y0, x1, y1 = structure.stair
    assert (x1 - x0, y1 - y0) == pytest.approx(STAIR)
    assert y1 == pytest.approx(structure.spine[1])  # against the spine, street side
    assert structure.cover.buffer(1e-6).covers(box(*structure.stair))
    assert structure.exit_separation == pytest.approx(_half_diameter(Polygon(BOUNDARY)))


def test_a_fixed_stair_footprint_is_returned_as_given():
    fixed = (30.0, 15.6, 34.92, 18.4)
    structure = plan_floor_structure(
        BOUNDARY, _office(), core_polygon=CORE_AT_END, stair_dimensions=STAIR, stair_footprint=fixed
    )

    assert structure.stair == fixed


def test_the_free_region_excludes_core_corridor_and_stair():
    structure = plan_floor_structure(BOUNDARY, _office(), core_polygon=CORE_AT_END, stair_dimensions=STAIR)

    free = structure.free_region
    assert free.geom_type in ("Polygon", "MultiPolygon")  # one piece each side of the spine
    assert free.intersection(Polygon(CORE_AT_END)).area == pytest.approx(0.0)
    assert free.intersection(box(*structure.spine)).area == pytest.approx(0.0)
    assert free.intersection(box(*structure.stair)).area == pytest.approx(0.0)
    expected = 37 * 26 - 8 * 6 - 37 * 1.6 - STAIR[0] * STAIR[1]
    assert free.area == pytest.approx(expected)


def test_no_stair_when_no_dimensions_are_given():
    structure = plan_floor_structure(BOUNDARY, _office(), core_polygon=CORE)

    assert structure.stair is None


def test_a_centred_core_leaves_the_stair_nowhere_to_clear_the_separation():
    with pytest.raises(TopologyInfeasible):
        plan_floor_structure(BOUNDARY, _office(), core_polygon=CORE, stair_dimensions=STAIR)


def test_a_core_off_the_front_or_rear_edge_is_rejected():
    floating = [(14.0, 10.0), (22.0, 10.0), (22.0, 18.0), (14.0, 18.0)]

    with pytest.raises((ValueError, TopologyInfeasible)):
        plan_floor_structure(BOUNDARY, _office(), core_polygon=floating)
