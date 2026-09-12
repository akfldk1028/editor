"""The growth solver partitions the free region and passes the same gates as the topology solver."""

from dataclasses import replace

import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union

from backend.app.modules.growth_planner.service import generate_growth_layout
from backend.app.modules.topology_planner.dimensioning import TopologyInfeasible
from backend.engine.geometry import orthogonal_min_width, shared_boundary_segments
from backend.tests.test_topology_graph import _office
from backend.tests.test_topology_layout import BOUNDARY, _aspect, _segment_length
from backend.tests.test_topology_structure import CORE_AT_END, STAIR


def _layout(**kwargs):
    return generate_growth_layout(BOUNDARY, _office(), core_polygon=CORE_AT_END, stair_dimensions=STAIR, **kwargs)


def test_every_room_meets_its_gates_with_no_relaxation():
    program = _office()
    layout = generate_growth_layout(BOUNDARY, program, core_polygon=CORE_AT_END, stair_dimensions=STAIR)
    nodes = {n.node_id: n for n in program.nodes}

    assert {r.room_id for r in layout.rooms} == set(nodes)
    for room in layout.rooms:
        node = nodes[room.room_id]
        area = Polygon(room.polygon).area
        if node.space_type != "core":
            assert float(node.min_area) - 1e-6 <= area <= float(node.max_area) + 1e-6, room.room_id
            assert orthogonal_min_width(room.polygon) >= float(node.min_width) - 1e-6, room.room_id
        if node.max_aspect_ratio is not None and node.space_type not in ("open_work", "core"):
            assert _aspect(room.polygon) <= node.max_aspect_ratio + 1e-6, room.room_id


def test_every_room_shares_a_door_width_with_the_corridor_and_the_restroom_touches_the_core():
    layout = _layout()
    corridor = layout.circulation[0].polygon
    core = next(r.polygon for r in layout.rooms if r.room_id == "core")

    for room in layout.rooms:
        assert any(_segment_length(s) >= 0.9 for s in shared_boundary_segments(room.polygon, corridor)), room.room_id
    rest = next(r.polygon for r in layout.rooms if r.room_id == "restroom")
    assert any(_segment_length(s) >= 0.9 for s in shared_boundary_segments(rest, core))
    assert len(layout.openings) == len(layout.rooms)


def test_rooms_corridor_and_stair_do_not_overlap_and_stay_inside_the_plate():
    layout = _layout()
    parts = [Polygon(r.polygon) for r in layout.rooms] + [Polygon(c.polygon) for c in layout.circulation]
    parts.append(Polygon(layout.remote_stair_footprint))

    plate = Polygon(BOUNDARY).buffer(1e-6)
    for i, a in enumerate(parts):
        assert plate.covers(a)
        for b in parts[i + 1:]:
            assert a.intersection(b).area < 1e-6
    # Growth on a rectangular plate leaves at most the primary's eroded slivers unassigned.
    assert unary_union(parts).area >= 0.9 * Polygon(BOUNDARY).area


def test_the_primary_is_one_polygon_and_the_candidate_is_labelled_growth():
    layout = _layout()

    assert sum(1 for r in layout.rooms if r.room_id == "open_work") == 1
    assert layout.candidate_id.endswith("-growth")
    assert layout.remote_stair_footprint is not None


def test_the_same_seed_gives_the_same_layout():
    assert _layout(seed=4) == _layout(seed=4)


def test_an_impossible_program_raises_instead_of_relaxing():
    program = _office()
    tight = replace(program, nodes=[
        replace(n, max_aspect_ratio=1.01) if n.node_id == "restroom" else n for n in program.nodes
    ])

    with pytest.raises(TopologyInfeasible):
        generate_growth_layout(BOUNDARY, tight, core_polygon=CORE_AT_END, stair_dimensions=STAIR, trials=8)
