"""The topology generator satisfies the validator's exit-separation rule by construction."""

import math

import pytest
from shapely.geometry import Polygon

from backend.app.modules.topology_planner.dimensioning import TopologyInfeasible
from backend.app.modules.topology_planner.service import (
    _half_diameter,
    _open_rectilinear,
    front_edge_core_x,
    generate_topology_layout,
)
from backend.tests.test_topology_graph import _office

# Three setback floors of the sample office; the front edge shrinks upward.
FLOORS = (
    [(0.0, 0.0), (38.0, 0.0), (42.0, 4.0), (42.0, 24.0), (36.0, 30.0), (4.0, 30.0), (-2.0, 24.0), (-2.0, 6.0), (-1.0, 2.0)],
    [(2.0, 0.0), (36.0, 0.0), (40.0, 4.0), (40.0, 22.0), (34.0, 28.0), (6.0, 28.0), (0.0, 22.0), (0.0, 6.0), (1.0, 2.0)],
    [(3.0, 0.0), (34.0, 0.0), (38.0, 4.0), (38.0, 20.0), (33.0, 26.0), (7.0, 26.0), (1.0, 20.0), (1.0, 6.0), (2.0, 2.0)],
)
DOOR = 0.9


def _door_pairs_max_distance(core, stair, corridor_y):
    """Best pair of 0.9 m door openings, measured edge to edge like the basic design."""
    cx0, _, cx1, cy1 = Polygon(core).bounds
    sx0, sy0, sx1, _ = Polygon(stair).bounds
    dy = abs(sy0 - cy1)
    best = 0.0
    for a0, a1 in ((cx0, cx0 + DOOR), (cx1 - DOOR, cx1)):
        for b0, b1 in ((sx0, sx0 + DOOR), (sx1 - DOOR, sx1)):
            best = max(best, math.hypot(max(0.0, b0 - a1, a0 - b1), dy))
    return best


def test_the_core_goes_to_the_end_of_the_run_every_floor_shares():
    x0 = front_edge_core_x(FLOORS, width=12.0, depth=6.0, min_y=0.0)

    # The narrowest front edge (floor 3) starts at x=3; the longer spine lies to the right.
    assert x0 == pytest.approx(3.0)


def test_a_core_wider_than_the_shared_front_edge_is_infeasible():
    with pytest.raises(TopologyInfeasible):
        front_edge_core_x(FLOORS, width=40.0, depth=6.0, min_y=0.0)


@pytest.mark.parametrize("boundary", FLOORS)
def test_the_remote_stair_door_clears_half_the_plate_diameter(boundary):
    core = [(3.0, 0.0), (15.0, 0.0), (15.0, 6.0), (3.0, 6.0)]
    layout = generate_topology_layout(
        boundary, _office(), core_polygon=core, stair_dimensions=(4.92, 2.8)
    )

    stair = layout.remote_stair_footprint
    assert stair is not None
    corridor_y = Polygon(layout.circulation[0].polygon).bounds[3]
    target = _half_diameter(Polygon(boundary))
    assert _door_pairs_max_distance(core, stair, corridor_y) + 1e-6 >= target


def test_opening_keeps_a_part_exactly_the_minimum_width_and_drops_a_thinner_arm():
    # A 6 m deep block with a 2 m wide arm hanging off it.
    shape = Polygon([(0, 0), (20, 0), (20, 6), (12, 6), (12, 10), (10, 10), (10, 6), (0, 6)])

    opened = _open_rectilinear(shape, 6.0)

    assert opened.geom_type == "Polygon"
    assert opened.area == pytest.approx(120.0)
    assert opened.bounds == pytest.approx((0.0, 0.0, 20.0, 6.0))


def test_half_diameter_is_the_longest_vertex_pair_over_two():
    assert _half_diameter(Polygon([(0, 0), (30, 0), (30, 18), (0, 18)])) == pytest.approx(
        math.hypot(30, 18) / 2
    )
