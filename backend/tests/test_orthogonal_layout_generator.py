from __future__ import annotations

from dataclasses import replace
import math

import pytest
from shapely import union_all
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.prepared import prep as prepare_geometry

import backend.app.modules.layout_generator.orthogonal as orthogonal_service
from backend.app.modules.basic_design.service import generate_basic_design
from backend.app.modules.circulation_planner.contracts import CirculationCandidate
from backend.app.modules.generation_loop.contracts import ExteriorAllocationRequest
from backend.app.modules.layout_generator.orthogonal import (
    generate_orthogonal_office_layout,
)
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.modules.validator.service import validate_layout
from backend.app.schemas.layout import RoomPolygon
from backend.app.schemas.mass import MassInput
from backend.app.schemas.program import ProgramNode


def test_exterior_allocation_request_requires_sorted_unique_room_ids() -> None:
    request = ExteriorAllocationRequest(
        floor_index=3,
        room_ids=("focus", "meeting"),
    )

    assert request.floor_index == 3
    assert request.room_ids == ("focus", "meeting")
    with pytest.raises(ValueError, match="sorted and unique"):
        ExteriorAllocationRequest(3, ("meeting", "focus"))
    with pytest.raises(ValueError, match="room_ids"):
        ExteriorAllocationRequest(3, ())
    with pytest.raises((TypeError, ValueError), match="floor_index"):
        ExteriorAllocationRequest(True, ("focus",))


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


def test_rectangle_adjacency_sweep_is_bounded_by_cells_and_contacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    width = 12
    height = 10
    bounds = tuple(
        (float(x), float(y), float(x + 1), float(y + 1))
        for x in range(width)
        for y in range(height)
    )
    expected_contacts = height * (width - 1) + width * (height - 1)
    comparisons = 0
    original_overlap = orthogonal_service._edge_overlap_length

    def counted_overlap(*args, **kwargs):
        nonlocal comparisons
        comparisons += 1
        return original_overlap(*args, **kwargs)

    def forbidden_intersection(*args, **kwargs):
        raise AssertionError("rectangle adjacency must not use Shapely intersection")

    monkeypatch.setattr(
        orthogonal_service,
        "_edge_overlap_length",
        counted_overlap,
    )
    monkeypatch.setattr(BaseGeometry, "intersection", forbidden_intersection)

    adjacencies = orthogonal_service._rectangle_adjacencies(bounds)

    assert len(adjacencies) == expected_contacts
    assert all(left_index < right_index for left_index, right_index, _ in adjacencies)
    assert comparisons <= 2 * (len(bounds) + expected_contacts)


def test_rectangle_cells_use_prepared_covers_on_high_vertex_polygon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    step_count = 24
    staircase = _staircase_polygon(step_count)
    prep_calls = 0
    covers_calls = 0

    def counted_prep(shape):
        nonlocal prep_calls
        prep_calls += 1
        prepared = prepare_geometry(shape)

        class CountedPrepared:
            def covers(self, candidate):
                nonlocal covers_calls
                covers_calls += 1
                return prepared.covers(candidate)

        return CountedPrepared()

    monkeypatch.setattr(
        orthogonal_service,
        "prep",
        counted_prep,
        raising=False,
    )

    cells = orthogonal_service._rectangle_cells(staircase)

    assert prep_calls == 1
    assert covers_calls == step_count**2
    assert len(cells) == step_count * (step_count + 1) // 2
    assert union_all([Polygon(cell) for cell in cells]).equals(staircase)


def test_residual_cell_absorption_has_bounded_graph_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    step_count = 18
    staircase = _staircase_polygon(step_count)
    seed = box(-1.0, 0.0, 0.0, 1.0)
    free_shape = union_all((seed, staircase))
    residual_count = step_count * (step_count + 1) // 2
    residual_contacts = step_count * (step_count - 1)
    comparisons = 0
    heap_pushes = 0
    union_calls = 0
    original_overlap = orthogonal_service._edge_overlap_length
    original_heappush = orthogonal_service.heappush
    original_union = BaseGeometry.union

    def counted_overlap(*args, **kwargs):
        nonlocal comparisons
        comparisons += 1
        return original_overlap(*args, **kwargs)

    def counted_heappush(*args, **kwargs):
        nonlocal heap_pushes
        heap_pushes += 1
        return original_heappush(*args, **kwargs)

    def counted_union(self, other, *args, **kwargs):
        nonlocal union_calls
        union_calls += 1
        return original_union(self, other, *args, **kwargs)

    def forbidden_intersection(*args, **kwargs):
        raise AssertionError("residual adjacency must not use Shapely intersection")

    monkeypatch.setattr(
        orthogonal_service,
        "_edge_overlap_length",
        counted_overlap,
    )
    monkeypatch.setattr(orthogonal_service, "heappush", counted_heappush)
    monkeypatch.setattr(BaseGeometry, "union", counted_union)
    monkeypatch.setattr(BaseGeometry, "intersection", forbidden_intersection)
    node = ProgramNode("open-work", "open_work", 100.0)
    seed_ring = (
        (-1.0, 0.0),
        (0.0, 0.0),
        (0.0, 1.0),
        (-1.0, 1.0),
    )

    assignments = orthogonal_service._absorb_residual_cells(
        [(node, seed_ring)],
        free_shape=free_shape,
    )

    assert union_calls == 0
    assert heap_pushes <= residual_contacts + 1
    assert comparisons <= 2 * (
        residual_count + residual_contacts + 2
    )
    assert Polygon(assignments[0][1]).equals(free_shape)


def test_residual_frontier_gives_surplus_to_far_primary_over_near_full_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    support_seed = box(-2.0, 0.0, 0.0, 1.0)
    primary_seed = box(4.0, 0.0, 5.0, 1.0)
    residual = tuple(
        orthogonal_service._canonical_rectangle((x, 0.0, x + 1.0, 1.0))
        for x in range(4)
    )
    free_shape = union_all(
        (support_seed, primary_seed, *(Polygon(cell) for cell in residual))
    )
    monkeypatch.setattr(
        orthogonal_service,
        "_rectangle_cells",
        lambda *args, **kwargs: residual,
    )
    support = ProgramNode(
        "meeting",
        "meeting",
        1.0,
        min_area=0.85,
        max_area=1.15,
    )
    primary = ProgramNode(
        "open-work",
        "open_work",
        5.0,
        min_area=4.25,
        max_area=5.75,
    )

    assignments = orthogonal_service._absorb_residual_cells(
        [
            (support, orthogonal_service._polygon_ring(support_seed)),
            (primary, orthogonal_service._polygon_ring(primary_seed)),
        ],
        free_shape=free_shape,
    )

    areas = {
        node.node_id: Polygon(polygon).area for node, polygon in assignments
    }
    assert areas == {"meeting": 2.0, "open-work": 5.0}


def test_polygon_ring_removes_collinear_residual_strip_breakpoints() -> None:
    strips = union_all(tuple(box(x, 0.0, x + 1.0, 1.0) for x in range(100)))

    ring = orthogonal_service._polygon_ring(strips)

    assert len(ring) == 4
    assert Polygon(ring).symmetric_difference(strips).area <= 1e-8
    assert all(
        math.isclose(start[0], end[0]) or math.isclose(start[1], end[1])
        for start, end in zip(ring, (*ring[1:], ring[0]))
    )


def test_primary_hole_rollback_drops_one_small_frontier_cell_per_support() -> None:
    primary = ProgramNode("open", "open_work", 13.0, max_area=15.0)
    meeting = ProgramNode("meeting", "meeting", 1.0, max_area=1.15)
    reception = ProgramNode("reception", "reception", 1.0, max_area=1.15)

    assignments = orthogonal_service._absorb_residual_cells(
        [
            (primary, orthogonal_service._polygon_ring(box(0, 1, 1, 2))),
            (meeting, orthogonal_service._polygon_ring(box(1, 1, 2, 2))),
            (reception, orthogonal_service._polygon_ring(box(3, 1, 4, 2))),
        ],
        free_shape=box(0, 0, 5, 3),
    )

    areas = {
        node.node_id: Polygon(polygon).area for node, polygon in assignments
    }
    assert areas == {"open": 11.0, "meeting": 1.0, "reception": 1.0}
    assert all(
        Polygon(polygon).is_valid and not Polygon(polygon).interiors
        for _, polygon in assignments
    )


def test_primary_hole_rollback_uses_shared_minimum_slit_through_thick_ring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = ProgramNode("open", "open_work", 32.0, max_area=36.0)
    meeting = ProgramNode("meeting", "meeting", 1.0, max_area=1.15)
    reception = ProgramNode("reception", "reception", 1.0, max_area=1.15)
    heap_pops = 0
    original_heappop = orthogonal_service.heappop

    def counted_heappop(*args, **kwargs):
        nonlocal heap_pops
        heap_pops += 1
        return original_heappop(*args, **kwargs)

    monkeypatch.setattr(orthogonal_service, "heappop", counted_heappop)

    assignments = orthogonal_service._absorb_residual_cells(
        [
            (primary, orthogonal_service._polygon_ring(box(0, 2, 1, 3))),
            (meeting, orthogonal_service._polygon_ring(box(2, 2, 3, 3))),
            (reception, orthogonal_service._polygon_ring(box(4, 2, 5, 3))),
        ],
        free_shape=box(0, 0, 7, 5),
    )

    areas = {
        node.node_id: Polygon(polygon).area for node, polygon in assignments
    }
    assert areas == {"open": 30.0, "meeting": 1.0, "reception": 1.0}
    assert all(
        Polygon(polygon).is_valid and not Polygon(polygon).interiors
        for _, polygon in assignments
    )
    assert heap_pops <= 8 * 35


def test_primary_seed_prefers_reachable_area_after_support_cutset() -> None:
    primary = ProgramNode("open", "open_work", 20.0, max_area=23.0)
    support = ProgramNode("meeting", "meeting", 3.0, max_area=3.45)
    left_seed = orthogonal_service._canonical_rectangle((0, 1, 1, 2))
    support_cutset = orthogonal_service._canonical_rectangle((1, 0, 2, 3))
    right_seed = orthogonal_service._canonical_rectangle((2, 1, 3, 2))

    assignments = orthogonal_service._assign_rectangles(
        [primary, support],
        [left_seed, support_cutset, right_seed],
        free_shape=box(0, 0, 10, 3),
    )

    polygons = {node.node_id: Polygon(polygon) for node, polygon in assignments}
    assert polygons["meeting"].bounds == (1.0, 0.0, 2.0, 3.0)
    assert polygons["open"].bounds == (2.0, 1.0, 3.0, 2.0)


def test_commercial_frontage_seed_is_reserved_for_frontage_required_primary() -> None:
    sales = ProgramNode(
        "sales",
        "sales",
        6.0,
        max_area=6.9,
        frontage_required=True,
    )
    restroom = ProgramNode("restroom", "restroom", 6.0, max_area=6.9)
    frontage_seed = orthogonal_service._canonical_rectangle((0, 0, 3, 2))
    rear_seed = orthogonal_service._canonical_rectangle((0, 2, 3, 4))

    assignments = orthogonal_service._assign_rectangles(
        [sales, restroom],
        [frontage_seed, rear_seed],
        free_shape=box(0, 0, 3, 4),
        frontage_segments=(((0.0, 0.0), (3.0, 0.0)),),
    )

    polygons = {node.node_id: Polygon(polygon) for node, polygon in assignments}
    assert polygons["sales"].bounds == (0.0, 0.0, 3.0, 2.0)
    assert polygons["restroom"].bounds == (0.0, 2.0, 3.0, 4.0)


def test_exterior_priority_rooms_receive_window_bearing_boundary_cells() -> None:
    nodes = [
        ProgramNode("meeting", "meeting", 8.0, max_area=10.0, min_width=2.0),
        ProgramNode("focus", "focus", 8.0, max_area=10.0, min_width=2.0),
        ProgramNode("reception", "reception", 8.0, max_area=10.0, min_width=2.0),
    ]
    rectangles = [
        orthogonal_service._canonical_rectangle((0, 0, 4, 2)),
        orthogonal_service._canonical_rectangle((4, 0, 8, 2)),
        orthogonal_service._canonical_rectangle((0, 2, 4, 4)),
    ]
    exterior_segments = (((0.0, 0.0), (8.0, 0.0)),)

    assigned = orthogonal_service._assign_rectangles(
        nodes,
        rectangles,
        exterior_segments=exterior_segments,
        exterior_priority_room_ids=("focus", "meeting"),
    )
    polygons = {node.node_id: Polygon(points) for node, points in assigned}
    exterior = LineString(exterior_segments[0])

    assert polygons["focus"].boundary.intersection(exterior).length >= 0.6
    assert polygons["meeting"].boundary.intersection(exterior).length >= 0.6
    assert polygons["reception"].boundary.intersection(exterior).length == 0.0

    first = orthogonal_service._assign_rectangles(
        nodes,
        rectangles,
        exterior_segments=exterior_segments,
        exterior_priority_room_ids=("focus", "meeting"),
    )
    second = orthogonal_service._assign_rectangles(
        nodes,
        rectangles,
        exterior_segments=tuple(reversed(exterior_segments)),
        exterior_priority_room_ids=("focus", "meeting"),
    )
    assert first == second


def test_exterior_priority_matching_reserves_frontage_cell_for_hall_conflict() -> None:
    alpha = ProgramNode("alpha", "meeting", 8.0, min_width=2.0)
    bravo = ProgramNode(
        "bravo",
        "meeting",
        8.0,
        min_width=2.0,
        frontage_required=True,
    )
    frontage_cell = orthogonal_service._canonical_rectangle((0, 0, 4, 2))
    exterior_only_cell = orthogonal_service._canonical_rectangle((4, 0, 8, 2))
    exterior_segments = (((0.0, 0.0), (8.0, 0.0)),)

    assignments = orthogonal_service._assign_rectangles(
        [alpha, bravo],
        [frontage_cell, exterior_only_cell],
        frontage_segments=(((0.0, 0.0), (4.0, 0.0)),),
        exterior_segments=exterior_segments,
        exterior_priority_room_ids=("alpha", "bravo"),
    )

    polygons = {node.node_id: Polygon(points) for node, points in assignments}
    assert polygons["alpha"].bounds == (4.0, 0.0, 8.0, 2.0)
    assert polygons["bravo"].bounds == (0.0, 0.0, 4.0, 2.0)


def test_exterior_priority_matching_reassigns_an_occupied_later_room_cell() -> None:
    alpha = ProgramNode("alpha", "meeting", 20.0, min_width=2.0)
    bravo = ProgramNode("bravo", "meeting", 100.0, min_width=2.0)
    charlie = ProgramNode("charlie", "meeting", 1.0, max_area=1.0)
    delta = ProgramNode("delta", "meeting", 100.0, min_width=2.0)
    alpha_seed = orthogonal_service._canonical_rectangle((0, 0, 10, 2))
    first = orthogonal_service._canonical_rectangle((10, 0, 16, 2))
    second = orthogonal_service._canonical_rectangle((16, 0, 18, 2))
    third = orthogonal_service._canonical_rectangle((18, 0, 20, 1))
    exterior_segments = (((0.0, 0.0), (20.0, 0.0)),)
    remaining = [first, second, third]
    exterior_contact_lengths = {
        rectangle: orthogonal_service._exterior_contact_length(
            rectangle,
            exterior_segments,
        )
        for rectangle in remaining
    }

    greedy_remaining = list(remaining)
    greedy_failed = False
    for node in (bravo, charlie, delta):
        candidates = orthogonal_service._exterior_assignment_options(
            node,
            greedy_remaining,
            exterior_contact_lengths=exterior_contact_lengths,
            frontage_segments=(),
            free_shape=box(0, 0, 20, 2),
        )
        if not candidates:
            greedy_failed = True
            break
        greedy_remaining.remove(candidates[0])
    assert greedy_failed

    assignments = orthogonal_service._assign_rectangles(
        [alpha, bravo, charlie, delta],
        [alpha_seed, *remaining],
        free_shape=box(0, 0, 20, 2),
        exterior_segments=exterior_segments,
        exterior_priority_room_ids=("alpha", "bravo", "charlie", "delta"),
    )

    polygons = {node.node_id: Polygon(points) for node, points in assignments}
    assert polygons["alpha"].bounds == (0.0, 0.0, 10.0, 2.0)
    assert polygons["bravo"].bounds == (10.0, 0.0, 16.0, 2.0)
    assert polygons["charlie"].bounds == (18.0, 0.0, 20.0, 1.0)
    assert polygons["delta"].bounds == (16.0, 0.0, 18.0, 2.0)


def test_exterior_priority_matching_reserves_bounded_seed_for_later_room() -> None:
    alpha = ProgramNode("alpha", "meeting", 8.0, min_width=2.0)
    bravo = ProgramNode(
        "bravo",
        "meeting",
        1.0,
        max_area=1.0,
        min_width=2.0,
    )
    bounded_seed = orthogonal_service._canonical_rectangle((0, 0, 4, 2))
    oversized_seed = orthogonal_service._canonical_rectangle((4, 0, 10, 2))
    exterior_segments = (((0.0, 0.0), (10.0, 0.0)),)

    assignments = orthogonal_service._assign_rectangles(
        [alpha, bravo],
        [bounded_seed, oversized_seed],
        free_shape=box(0, 0, 10, 2),
        exterior_segments=exterior_segments,
        exterior_priority_room_ids=("alpha", "bravo"),
    )

    polygons = {node.node_id: Polygon(points) for node, points in assignments}
    assert polygons["alpha"].bounds == (4.0, 0.0, 10.0, 2.0)
    assert polygons["bravo"].bounds == (0.0, 0.0, 4.0, 2.0)


def test_exterior_priority_subdivision_splits_target_seed_and_preserves_residual() -> None:
    meeting = ProgramNode(
        "meeting",
        "meeting",
        8.0,
        max_area=10.0,
        min_width=2.0,
    )
    oversized = orthogonal_service._canonical_rectangle((0, 0, 10, 2))
    circulation = [
        RoomPolygon(
            room_id="corridor",
            space_type="circulation",
            polygon=[(0, -1), (10, -1), (10, 0), (0, 0)],
        )
    ]

    subdivided = orthogonal_service._subdivide_accessible_rectangles(
        [oversized],
        circulation,
        required_count=1,
        exterior_priority_nodes=(meeting,),
        exterior_segments=(((0.0, 2.0), (10.0, 2.0)),),
    )

    shapes = [Polygon(rectangle) for rectangle in subdivided]
    target_seed, = [
        shape
        for shape in shapes
        if shape.area == pytest.approx(8.0)
        and shape.boundary.intersection(LineString(((0, 2), (10, 2)))).length
        >= 0.6
    ]
    assert min(
        target_seed.bounds[2] - target_seed.bounds[0],
        target_seed.bounds[3] - target_seed.bounds[1],
    ) >= 2.0
    assert union_all(shapes).equals(Polygon(oversized))
    assert sum(shape.area for shape in shapes) == pytest.approx(20.0)


def test_exterior_priority_room_ids_fail_in_sorted_order_when_unknown() -> None:
    node = ProgramNode("known", "meeting", 4.0)
    rectangle = orthogonal_service._canonical_rectangle((0, 0, 2, 2))

    with pytest.raises(
        ValueError,
        match="exterior priority room ids are absent from program: missing-a, missing-z",
    ):
        orthogonal_service._assign_rectangles(
            [node],
            [rectangle],
            exterior_priority_room_ids=("missing-a", "missing-z"),
        )


def test_full_layout_retains_requested_exterior_contact_after_absorption() -> None:
    _, boundary, core, _ = CASES[0]
    program = _program("exterior-absorption", boundary)
    baseline = generate_orthogonal_office_layout(
        boundary,
        program,
        core_polygon=core,
    )
    circulation_candidate = CirculationCandidate(
        strategy="test",
        polygons=tuple(tuple(path.polygon) for path in baseline.circulation),
        remote_stair_polygon=tuple(baseline.remote_stair_footprint or ()),
        fingerprint="test",
        entrance_connected=True,
        core_connected=True,
        stair_connected=True,
    )

    layout = generate_orthogonal_office_layout(
        boundary,
        program,
        core_polygon=core,
        circulation_candidate=circulation_candidate,
        exterior_priority_room_ids=("focus", "meeting"),
    )
    floor_exterior = Polygon(boundary).boundary
    rooms = {room.room_id: Polygon(room.polygon) for room in layout.rooms}

    assert rooms["focus"].boundary.intersection(floor_exterior).length >= 0.6
    assert rooms["meeting"].boundary.intersection(floor_exterior).length >= 0.6


def test_non_primary_seed_rejects_only_candidate_above_original_area_bound() -> None:
    meeting = ProgramNode("meeting", "meeting", 10.0, max_area=11.5)

    with pytest.raises(ValueError, match="seed area"):
        orthogonal_service._assign_rectangles(
            [meeting],
            [orthogonal_service._canonical_rectangle((0, 0, 11, 2))],
            free_shape=box(0, 0, 11, 2),
        )


def test_non_primary_seed_accepts_candidate_at_original_area_bound() -> None:
    meeting = ProgramNode("meeting", "meeting", 10.0, max_area=11.5)
    exact_bound = orthogonal_service._canonical_rectangle((0, 0, 10.75, 2))

    assignments = orthogonal_service._assign_rectangles(
        [meeting],
        [exact_bound],
        free_shape=box(0, 0, 10.75, 2),
    )

    assert assignments == [(meeting, exact_bound)]


def test_legacy_non_primary_seed_keeps_pre_fixed_circulation_area_path() -> None:
    meeting = ProgramNode("meeting", "meeting", 10.0, max_area=11.5)
    oversized = orthogonal_service._canonical_rectangle((0, 0, 11, 2))

    assignments = orthogonal_service._assign_rectangles(
        [meeting],
        [oversized],
    )

    assert assignments == [(meeting, oversized)]


def test_accessible_subdivision_rejects_explosive_area_bounds_at_hard_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = 24
    width = float(2**30)
    rectangle = orthogonal_service._canonical_rectangle((0, 0, width, 100))
    circulation = [
        RoomPolygon(
            room_id="corridor",
            space_type="circulation",
            polygon=[(0, -1), (width, -1), (width, 0), (0, 0)],
        )
    ]
    capacity_scan_sizes = []
    original_capacity = orthogonal_service._has_bounded_seed_capacity

    def counted_capacity(rectangles, area_limits):
        capacity_scan_sizes.append(len(rectangles))
        if len(rectangles) > cap:
            raise AssertionError("subdivision exceeded the deterministic cap")
        return original_capacity(rectangles, area_limits)

    monkeypatch.setattr(
        orthogonal_service,
        "_MAX_ACCESSIBLE_RECTANGLE_COUNT",
        cap,
        raising=False,
    )
    monkeypatch.setattr(
        orthogonal_service,
        "_has_bounded_seed_capacity",
        counted_capacity,
    )

    with pytest.raises(
        ValueError,
        match="accessible room subdivision exceeds bounded rectangle count",
    ):
        orthogonal_service._subdivide_accessible_rectangles(
            [rectangle],
            circulation,
            required_count=1,
            bounded_area_limits=(1e-12,),
        )

    assert capacity_scan_sizes == list(range(1, cap + 1))


def test_accessible_subdivision_preserves_normal_bounded_fixture() -> None:
    rectangle = orthogonal_service._canonical_rectangle((0, 0, 8, 4))
    circulation = [
        RoomPolygon(
            room_id="corridor",
            space_type="circulation",
            polygon=[(0, -1), (8, -1), (8, 0), (0, 0)],
        )
    ]

    result = orthogonal_service._subdivide_accessible_rectangles(
        [rectangle],
        circulation,
        required_count=2,
        bounded_area_limits=(16.0,),
    )

    assert result == [
        orthogonal_service._canonical_rectangle((0, 0, 4, 4)),
        orthogonal_service._canonical_rectangle((4, 0, 8, 4)),
    ]


def test_polygon_ring_uses_authoritative_axes_independent_of_ring_order() -> None:
    x = 13.323437499999999
    y = 16.50381679389313
    bad_x = math.nextafter(x, math.inf)
    raw = (
        (0.0, 0.0),
        (20.0, 0.0),
        (20.0, y),
        (x, y),
        (bad_x, 22.0),
        (0.0, 22.0),
    )
    outward_first = (*raw[4:], *raw[:4])
    reversed_outward_first = (raw[4], *reversed(raw[:4]), raw[5])
    free_shape = union_all((box(0.0, 0.0, 20.0, y), box(0.0, y, x, 22.0)))
    fixed_rectangle = box(x, y, 20.0, 22.0)
    authoritative_axes = orthogonal_service._geometry_axes(free_shape)

    rings = [
        orthogonal_service._polygon_ring(
            Polygon(points),
            authoritative_axes=authoritative_axes,
        )
        for points in (outward_first, reversed_outward_first)
    ]

    canonical = Polygon(rings[0])
    assert all(Polygon(ring).equals(canonical) for ring in rings)
    assert all((x, y) in ring and (x, 22.0) in ring for ring in rings)
    assert all(
        start[0] == end[0] or start[1] == end[1]
        for ring in rings
        for start, end in zip(ring, (*ring[1:], ring[0]))
    )
    assert free_shape.covers(canonical)
    assert canonical.intersection(fixed_rectangle).area <= 1e-12


def test_residual_ring_uses_free_shape_axes_without_fixed_overlap() -> None:
    x = 13.323437499999999
    bad_x = math.nextafter(x, math.inf)
    free_shape = box(0.0, 0.0, x, 4.0)
    fixed_rectangle = box(x, 0.0, 20.0, 4.0)
    primary = ProgramNode("open", "open_work", 4.0, max_area=4.6)

    assignments = orthogonal_service._absorb_residual_cells(
        [
            (
                primary,
                (
                    (bad_x, 4.0),
                    (x, 0.0),
                    (0.0, 0.0),
                    (0.0, 4.0),
                ),
            )
        ],
        free_shape=free_shape,
        fixed_shape=fixed_rectangle,
    )

    result = Polygon(assignments[0][1])
    assert free_shape.covers(result)
    assert result.intersection(fixed_rectangle).area <= 1e-12


def test_residual_absorption_rejects_cell_count_above_hard_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cell = orthogonal_service._canonical_rectangle((1, 0, 2, 1))
    monkeypatch.setattr(
        orthogonal_service,
        "_rectangle_cells",
        lambda *args, **kwargs: (
            cell,
        )
        * (orthogonal_service._MAX_RESIDUAL_CELL_COUNT + 1),
    )
    primary = ProgramNode("open", "open_work", 1.0, max_area=1.15)

    with pytest.raises(ValueError, match="bounded cell count"):
        orthogonal_service._absorb_residual_cells(
            [(primary, orthogonal_service._canonical_rectangle((0, 0, 1, 1)))],
            free_shape=box(0, 0, 2, 1),
        )


def _staircase_polygon(step_count: int) -> Polygon:
    points = [(0.0, 0.0), (float(step_count), 0.0)]
    for step in range(step_count):
        x = float(step_count - step)
        y = float(step + 1)
        points.extend(((x, y), (x - 1.0, y)))
    return Polygon(points)


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


def test_legacy_layout_preserves_literal_room_geometry_and_unbounded_subdivision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, boundary, core, _ = CASES[0]
    observed_limits = []
    original_subdivide = orthogonal_service._subdivide_accessible_rectangles

    def capture_limits(*args, **kwargs):
        observed_limits.append(kwargs.get("bounded_area_limits"))
        return original_subdivide(*args, **kwargs)

    monkeypatch.setattr(
        orthogonal_service,
        "_subdivide_accessible_rectangles",
        capture_limits,
    )

    layout = generate_orthogonal_office_layout(
        boundary,
        _program("legacy-literal", boundary),
        core_polygon=core,
    )

    assert observed_limits == [None]
    assert {
        room.room_id: tuple(room.polygon)
        for room in layout.rooms
    } == {
        "core": ((22.0, 0.0), (30.0, 0.0), (30.0, 7.0), (22.0, 7.0)),
        "focus": ((14.0, 8.2), (20.8, 8.2), (20.8, 12.0), (14.0, 12.0)),
        "it_storage": ((7.0, 8.2), (14.0, 8.2), (14.0, 12.0), (7.0, 12.0)),
        "meeting": ((14.0, 0.0), (20.8, 0.0), (20.8, 7.0), (14.0, 7.0)),
        "open_work": ((0.0, 0.0), (7.0, 0.0), (7.0, 7.0), (0.0, 7.0)),
        "pantry": ((7.0, 0.0), (10.5, 0.0), (10.5, 7.0), (7.0, 7.0)),
        "reception": ((10.5, 0.0), (14.0, 0.0), (14.0, 7.0), (10.5, 7.0)),
        "restroom": ((4.92, 8.2), (7.0, 8.2), (7.0, 12.0), (4.92, 12.0)),
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
