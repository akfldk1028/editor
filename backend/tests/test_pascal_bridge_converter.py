from __future__ import annotations

from backend.app.modules.pascal_bridge import (
    assign_opening_to_edge,
    convert_floor_geometry,
    convert_floors,
)

SQUARE = [[0.0, 0.0], [6.0, 0.0], [6.0, 4.0], [0.0, 4.0]]


def _geometry(**overrides):
    payload = {
        "contract_version": "planm-floor-geometry/v1",
        "project_id": "proj-1",
        "candidate_id": "cand-1",
        "floor_index": 1,
        "units": "m",
        "rooms": [
            {
                "room_id": "sales_a",
                "space_type": "sales",
                "category": "room",
                "polygon": SQUARE,
            }
        ],
        "openings": [],
    }
    payload.update(overrides)
    return payload


class TestEdgeAssignment:
    def test_opening_on_the_first_edge_reports_that_edge_and_position(self) -> None:
        # Midpoint (3, 0) sits halfway along edge 0 -> (0,0)..(6,0).
        assert assign_opening_to_edge(SQUARE, (2.55, 0.0), (3.45, 0.0)) == (0, 0.5)

    def test_position_reflects_where_along_the_wall_the_opening_sits(self) -> None:
        edge, t = assign_opening_to_edge(SQUARE, (1.05, 0.0), (1.95, 0.0))
        assert edge == 0
        assert t == 0.25

    def test_opening_on_a_later_edge_is_found(self) -> None:
        # Midpoint (6, 2) is the middle of edge 1 -> (6,0)..(6,4).
        assert assign_opening_to_edge(SQUARE, (6.0, 1.55), (6.0, 2.45)) == (1, 0.5)

    def test_opening_far_from_every_edge_is_unassigned(self) -> None:
        assert assign_opening_to_edge(SQUARE, (3.0, 2.0), (3.9, 2.0)) is None


class TestConversion:
    def test_a_room_becomes_a_pascal_room_with_its_polygon(self) -> None:
        result = convert_floor_geometry(_geometry())

        assert result.warnings == []
        level = result.plan["levels"][0]
        assert level["label"] == "Floor 1"
        room = level["rooms"][0]
        assert room["name"] == "sales a"
        assert room["polygon"] == SQUARE
        assert room["openings"] == []

    def test_known_space_types_map_to_a_pascal_room_type(self) -> None:
        geometry = _geometry(
            rooms=[
                {
                    "room_id": "corridor_1",
                    "space_type": "corridor",
                    "category": "circulation",
                    "polygon": SQUARE,
                },
                {
                    "room_id": "wc_1",
                    "space_type": "toilet",
                    "category": "room",
                    "polygon": SQUARE,
                },
            ]
        )
        rooms = {r["name"]: r for r in convert_floor_geometry(geometry).plan["levels"][0]["rooms"]}

        assert rooms["corridor 1"]["type"] == "hallway"
        # Circulation is never furnished even when it maps to a known type.
        assert rooms["corridor 1"]["furnish"] is False
        assert rooms["wc 1"]["type"] == "bathroom"
        assert rooms["wc 1"]["furnish"] is True

    def test_an_unknown_space_type_builds_the_room_but_stays_untyped(self) -> None:
        room = convert_floor_geometry(_geometry()).plan["levels"][0]["rooms"][0]

        assert "type" not in room
        assert "furnish" not in room

    def test_an_opening_is_attached_to_the_room_whose_outline_it_lies_on(self) -> None:
        geometry = _geometry(
            openings=[
                {
                    "opening_id": "sales_a-door",
                    "kind": "door",
                    "connects": ["sales_a", "corridor_1"],
                    "start": [2.55, 0.0],
                    "end": [3.45, 0.0],
                    "clear_width": 0.9,
                }
            ]
        )
        result = convert_floor_geometry(geometry)

        opening = result.plan["levels"][0]["rooms"][0]["openings"][0]
        assert opening == {"kind": "door", "wall": 0, "t": 0.5, "width": 0.9}
        assert result.unplaced_openings == []

    def test_an_opening_is_claimed_once_even_when_two_rooms_share_it(self) -> None:
        geometry = _geometry(
            rooms=[
                {
                    "room_id": "sales_a",
                    "space_type": "sales",
                    "category": "room",
                    "polygon": SQUARE,
                },
                {
                    "room_id": "sales_b",
                    "space_type": "sales",
                    "category": "room",
                    # Shares the x=6 edge with sales_a.
                    "polygon": [[6.0, 0.0], [12.0, 0.0], [12.0, 4.0], [6.0, 4.0]],
                },
            ],
            openings=[
                {
                    "opening_id": "shared-door",
                    "kind": "door",
                    "connects": ["sales_a", "sales_b"],
                    "start": [6.0, 1.55],
                    "end": [6.0, 2.45],
                    "clear_width": 0.9,
                }
            ],
        )
        rooms = convert_floor_geometry(geometry).plan["levels"][0]["rooms"]

        cut = [len(room["openings"]) for room in rooms]
        assert sum(cut) == 1, "the shared door must be cut exactly once"

    def test_an_opening_that_lands_nowhere_is_reported_not_silently_dropped(self) -> None:
        geometry = _geometry(
            openings=[
                {
                    "opening_id": "floating-door",
                    "kind": "door",
                    "connects": ["sales_a", "elsewhere"],
                    "start": [3.0, 2.0],
                    "end": [3.9, 2.0],
                    "clear_width": 0.9,
                }
            ]
        )
        result = convert_floor_geometry(geometry)

        assert result.unplaced_openings == ["floating-door"]
        assert "floating-door" in result.warnings[0]

    def test_a_degenerate_room_is_skipped_with_a_warning(self) -> None:
        geometry = _geometry(
            rooms=[
                {
                    "room_id": "sliver",
                    "space_type": "sales",
                    "category": "room",
                    "polygon": [[0.0, 0.0], [1.0, 0.0]],
                }
            ]
        )
        result = convert_floor_geometry(geometry)

        assert result.plan["levels"] == []
        assert "sliver" in result.warnings[0]

    def test_floors_are_ordered_lowest_first(self) -> None:
        third = _geometry(floor_index=3)
        first = _geometry(floor_index=1)
        result = convert_floors([third, first])

        assert [level["label"] for level in result.plan["levels"]] == [
            "Floor 1",
            "Floor 3",
        ]

    def test_the_first_level_can_target_an_existing_pascal_level(self) -> None:
        result = convert_floors([_geometry()], level_ids=["level_abc"])

        assert result.plan["levels"][0]["levelId"] == "level_abc"

    def test_furnish_can_be_turned_off_for_the_whole_plan(self) -> None:
        geometry = _geometry(
            rooms=[
                {
                    "room_id": "wc_1",
                    "space_type": "toilet",
                    "category": "room",
                    "polygon": SQUARE,
                }
            ]
        )
        room = convert_floor_geometry(geometry, furnish=False).plan["levels"][0]["rooms"][0]

        assert room["type"] == "bathroom"
        assert room["furnish"] is False

    def test_plan_name_defaults_to_the_project_and_candidate(self) -> None:
        assert convert_floor_geometry(_geometry()).plan["name"] == "proj-1 / cand-1"
