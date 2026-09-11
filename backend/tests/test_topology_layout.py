"""The whole chain: graph -> slicing -> LP -> polygons, verified against the graph."""

from dataclasses import replace

import pytest
from shapely.geometry import Polygon

from backend.app.modules.topology_planner.dimensioning import TopologyInfeasible
from backend.app.modules.topology_planner.service import generate_topology_layout
from backend.engine.geometry import orthogonal_min_width, shared_boundary_segments
from backend.tests.test_topology_graph import _office


BOUNDARY = [(0.0, 0.0), (37.0, 0.0), (37.0, 26.0), (0.0, 26.0)]
CORE = [(14.0, 18.0), (22.0, 18.0), (22.0, 26.0), (14.0, 26.0)]


def _aspect(polygon):
    xs = [x for x, _ in polygon]
    ys = [y for _, y in polygon]
    w, d = max(xs) - min(xs), max(ys) - min(ys)
    return max(w / d, d / w)


def _segment_length(segment):
    (ax, ay), (bx, by) = segment
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def test_every_room_meets_its_gates_with_no_relaxation():
    program = _office()
    layout = generate_topology_layout(BOUNDARY, program, core_polygon=CORE)
    nodes = {n.node_id: n for n in program.nodes}

    for room in layout.rooms:
        node = nodes[room.room_id.split("::")[0]]
        if node.max_aspect_ratio is not None and node.space_type != "open_work":
            assert _aspect(room.polygon) <= node.max_aspect_ratio + 1e-6, room.room_id
        if node.min_width is not None:
            assert orthogonal_min_width(room.polygon) >= node.min_width - 1e-6, room.room_id


def test_every_room_shares_a_door_width_with_the_corridor():
    layout = generate_topology_layout(BOUNDARY, _office(), core_polygon=CORE)
    corridor = layout.circulation[0].polygon

    for room in layout.rooms:
        shared = shared_boundary_segments(room.polygon, corridor)
        assert any(_segment_length(s) >= 0.9 for s in shared), room.room_id


def test_the_restroom_touches_the_core():
    layout = generate_topology_layout(BOUNDARY, _office(), core_polygon=CORE)
    rest = next(r.polygon for r in layout.rooms if r.room_id == "restroom")
    core = next(r.polygon for r in layout.rooms if r.room_id == "core")

    assert any(_segment_length(s) >= 0.9 for s in shared_boundary_segments(rest, core))


def test_rooms_and_corridor_tile_the_plate_without_overlap():
    layout = generate_topology_layout(BOUNDARY, _office(), core_polygon=CORE)
    parts = [Polygon(r.polygon) for r in layout.rooms] + [Polygon(c.polygon) for c in layout.circulation]

    assert sum(p.area for p in parts) == pytest.approx(37.0 * 26.0, rel=1e-6)
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            assert a.intersection(b).area < 1e-6


def test_restroom_area_is_its_normative_target_not_a_slab():
    program = _office()
    layout = generate_topology_layout(BOUNDARY, program, core_polygon=CORE)
    rest = next(r for r in layout.rooms if r.room_id == "restroom")
    node = next(n for n in program.nodes if n.node_id == "restroom")

    # The LP lands on the smallest width the 2.5 aspect gate allows at the
    # core's depth (8 m / 2.5 = 3.2 m -> 25.6 m2); that is inside the band the
    # program declares, which is the requirement.  Baseline slab: 3.46.
    area = Polygon(rest.polygon).area
    assert float(node.min_area) - 1e-6 <= area <= float(node.max_area) + 1e-6
    assert _aspect(rest.polygon) <= 2.5 + 1e-6


def test_the_candidate_is_labelled_as_topology_first():
    layout = generate_topology_layout(BOUNDARY, _office(), core_polygon=CORE)

    assert layout.candidate_id.endswith("-topology")


def test_an_impossible_program_raises_instead_of_relaxing():
    program = _office()
    tight = replace(program, nodes=[
        replace(n, max_aspect_ratio=1.01) if n.node_id == "restroom" else n for n in program.nodes
    ])

    with pytest.raises(TopologyInfeasible):
        generate_topology_layout(BOUNDARY, tight, core_polygon=CORE)


def test_a_sliver_beside_the_core_becomes_a_corridor_spur_not_a_squeezed_room():
    """A 2 m strip between the core and the plate edge holds no room and is too
    narrow for the primary; the corridor takes it and the core gains a second face."""
    core = [(2.0, 18.0), (10.0, 18.0), (10.0, 26.0), (2.0, 26.0)]

    layout = generate_topology_layout(BOUNDARY, _office(), core_polygon=core)

    corridor = Polygon(layout.circulation[0].polygon)
    assert corridor.area > 37.0 * 1.6 + 1.0
    assert all(r.space_type != "circulation" for r in layout.rooms)
    core_poly = Polygon(next(r.polygon for r in layout.rooms if r.room_id == "core"))
    assert corridor.boundary.intersection(core_poly.boundary).length > 8.0 + 2.0


def test_the_primary_room_is_one_polygon_wrapping_the_corridor_ends():
    layout = generate_topology_layout(BOUNDARY, _office(), core_polygon=CORE)

    ids = [r.room_id for r in layout.rooms]
    assert ids.count("open_work") == 1
    assert all("::" not in room_id for room_id in ids)
    corridor = Polygon(layout.circulation[0].polygon)
    assert corridor.bounds[2] - corridor.bounds[0] < 37.0  # the spine stops at the last room
