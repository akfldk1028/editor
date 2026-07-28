from __future__ import annotations

from dataclasses import FrozenInstanceError
import math

import pytest

from backend.app.modules.generation_loop.service import run_building_generation
from backend.app.schemas.layout import BasicDesignFeatures, PlanElement, PlanLine
from backend.app.schemas.mass import MassInput
from engine.geometry.polygon import polygon_overlap_area


def test_basic_design_records_are_typed_frozen_and_reject_non_finite_values() -> None:
    element = PlanElement(
        element_id="core-stair-1",
        category="vertical",
        kind="stair",
        host_id="core",
        label="UP",
        footprint=((1.0, 2.0), (2.2, 2.0), (2.2, 4.4), (1.0, 4.4)),
    )
    line = PlanLine(
        line_id="exit-1",
        category="egress",
        kind="protected_exit",
        points=((1.0, 2.0), (1.9, 2.0)),
        clear_width=0.9,
    )
    features = BasicDesignFeatures(elements=(element,), lines=(line,))

    assert features.elements == (element,)
    assert features.lines == (line,)
    with pytest.raises(FrozenInstanceError):
        element.kind = "elevator"  # type: ignore[misc]
    with pytest.raises(ValueError, match="finite"):
        PlanLine(
            line_id="bad-exit",
            category="egress",
            kind="protected_exit",
            points=((float("nan"), 0.0), (1.0, 0.0)),
        )


def test_building_generation_adds_complete_deterministic_basic_design_features() -> None:
    mass = MassInput(
        project_id="basic-design-contract",
        floors=5,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 0.2, "office": 0.8},
    )

    result = run_building_generation(mass)

    first = result.floor_results[0].layout.basic_design
    assert first is not None
    for floor in result.floor_results:
        layout = floor.layout
        features = layout.basic_design
        assert features is not None
        assert features.policy_version == "concept-basic-v1"
        assert all(
            math.isfinite(value)
            for feature in (*features.elements, *features.lines)
            for point in (feature.footprint if isinstance(feature, PlanElement) else feature.points)
            for value in point
        )
        vertical = [element for element in features.elements if element.category == "vertical"]
        assert {element.kind for element in vertical} == {"stair", "elevator", "lobby", "shaft"}
        assert sum(element.kind == "stair" for element in vertical) == 2
        assert all(
            polygon_overlap_area(left.footprint, right.footprint) == pytest.approx(0.0)
            for index, left in enumerate(features.elements)
            for right in features.elements[index + 1 :]
        )
        exits = [line for line in features.lines if line.kind == "protected_exit"]
        assert len(exits) == 2
        assert {line.clear_width for line in exits} == {0.9}
        assert exits[0].points != exits[1].points
        door_midpoints = {
            opening.connects[0]: tuple(
                (opening.start[index] + opening.end[index]) / 2 for index in range(2)
            )
            for opening in layout.openings
        }
        non_core_rooms = [room for room in layout.rooms if room.space_type != "core"]
        routes = [line for line in features.lines if line.kind == "egress_route"]
        for room in non_core_rooms:
            room_routes = [route for route in routes if route.host_id == room.room_id]
            assert len(room_routes) == 2
            assert {route.target_id for route in room_routes} == {line.line_id for line in exits}
            assert all(route.points[0] == pytest.approx(door_midpoints[room.room_id]) for route in room_routes)
        grids = [line for line in features.lines if line.kind == "grid"]
        columns = [element for element in features.elements if element.kind == "column"]
        assert grids and columns
        assert all(
            abs(element.footprint[1][0] - element.footprint[0][0]) == pytest.approx(0.4)
            and abs(element.footprint[2][1] - element.footprint[1][1]) == pytest.approx(0.4)
            for element in columns
        )
        assert {line.kind for line in features.lines if line.category == "dimension"} == {
            "overall_width", "overall_depth", "circulation_width"
        }
        assert {"street", "north_arrow", "scale_line"} <= {
            line.kind for line in features.lines if line.category == "site"
        }
        if floor.program.use_type == "office":
            required = {
                "open_work": {"workstation"}, "meeting": {"meeting_table"},
                "reception": {"reception_desk"}, "focus": {"focus_desk"},
                "pantry": {"pantry_counter", "sink"}, "restroom": {"wc", "lavatory"},
                "it_storage": {"it_rack"},
            }
        else:
            required = {
                "sales": {"sales_shelf"}, "checkout": {"checkout_counter"},
                "stock": {"stock_rack"}, "staff": {"staff_table"},
                "restroom": {"wc", "lavatory"}, "utility": {"utility_equipment"},
            }
            assert len([line for line in features.lines if line.kind == "entrance"]) == 1
        for room_id, kinds in required.items():
            assert kinds <= {
                element.kind for element in features.elements if element.host_id == room_id
            }
        assert [
            (element.element_id, element.footprint) for element in features.elements
            if element.category in {"vertical", "structure"}
        ] == [
            (element.element_id, element.footprint) for element in first.elements
            if element.category in {"vertical", "structure"}
        ]
