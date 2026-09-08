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

    def test_a_shared_boundary_keeps_one_wall_and_one_opening(self) -> None:
        """Two rooms describing the same boundary must not build it twice.

        Both rooms declare the edge they share, so before merging the 3D model
        carried two coincident walls at every boundary. One room now omits it,
        and the single opening is cut into the wall that survives.
        """
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

        omitted = sum(len(room.get("omitWalls", [])) for room in rooms)
        assert omitted == 1, "exactly one side of the shared boundary is dropped"
        cut = sum(len(room["openings"]) for room in rooms)
        assert cut == 1, "the surviving wall carries the door"

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


class TestOpeningsCutThroughEveryCoveringWall:
    """A long corridor wall alongside short room walls is the real-world case."""

    CORRIDOR = [[0.0, 4.0], [12.0, 4.0], [12.0, 6.0], [0.0, 6.0]]
    ROOM_A = [[0.0, 0.0], [6.0, 0.0], [6.0, 4.0], [0.0, 4.0]]
    ROOM_B = [[6.0, 0.0], [12.0, 0.0], [12.0, 4.0], [6.0, 4.0]]

    def _plan(self):
        geometry = {
            "floor_index": 1,
            "rooms": [
                {"room_id": "room_a", "space_type": "sales", "category": "room",
                 "polygon": self.ROOM_A},
                {"room_id": "room_b", "space_type": "sales", "category": "room",
                 "polygon": self.ROOM_B},
                {"room_id": "corridor_1", "space_type": "corridor",
                 "category": "circulation", "polygon": self.CORRIDOR},
            ],
            "openings": [
                {"opening_id": "a-door", "kind": "door",
                 "connects": ["room_a", "corridor_1"],
                 "start": [2.55, 4.0], "end": [3.45, 4.0], "clear_width": 0.9},
                {"opening_id": "b-door", "kind": "door",
                 "connects": ["room_b", "corridor_1"],
                 "start": [8.55, 4.0], "end": [9.45, 4.0], "clear_width": 0.9},
            ],
        }
        return convert_floor_geometry(geometry).plan

    def test_the_corridor_keeps_the_wall_and_the_rooms_drop_theirs(self) -> None:
        """The longer wall wins, so the boundary is built once."""
        rooms = {r["name"]: r for r in self._plan()["levels"][0]["rooms"]}

        # Each room's north edge is covered by the corridor's south wall...
        assert 2 in rooms["room a"]["omitWalls"]
        assert 2 in rooms["room b"]["omitWalls"]
        # ...and room b also drops the edge it shares with room a, which is the
        # same length, so the tie is broken by room order.
        assert rooms["room b"]["omitWalls"] == [2, 3]
        assert "omitWalls" not in rooms["corridor 1"]

        # Every boundary is still built exactly once.
        built = sum(
            len(r["polygon"]) - len(r.get("omitWalls", []))
            for r in self._plan()["levels"][0]["rooms"]
        )
        assert built == 9, "12 edges minus the 3 shared ones"

    def test_both_doors_end_up_on_the_corridor_wall(self) -> None:
        rooms = {r["name"]: r for r in self._plan()["levels"][0]["rooms"]}

        assert rooms["room a"]["openings"] == []
        assert rooms["room b"]["openings"] == []
        assert len(rooms["corridor 1"]["openings"]) == 2

    def test_every_opening_is_cut_somewhere(self) -> None:
        plan = self._plan()
        total = sum(len(r["openings"]) for r in plan["levels"][0]["rooms"])

        assert total == 2, "one cut per door, on the wall that survives"

    def test_the_corridor_door_position_is_measured_along_the_corridor_wall(self) -> None:
        rooms = {r["name"]: r for r in self._plan()["levels"][0]["rooms"]}
        corridor_ts = [o["t"] for o in rooms["corridor 1"]["openings"]]

        # Corridor edge 0 runs (0,4) -> (12,4); the room_a door centres at x=3.
        assert any(abs(t - 0.25) < 0.01 for t in corridor_ts)


class TestNonOrthogonalOutlines:
    """Diagonal, curved and non-convex rooms must survive unchanged.

    PLANM sites can be angled, and its own irregular sample carries diagonal
    room edges, so the conversion must not assume axis-aligned rectangles.
    """

    DIAMOND = [[6.0, 0.0], [12.0, 6.0], [6.0, 12.0], [0.0, 6.0]]

    def _convert(self, polygon, openings=()):
        return convert_floor_geometry(
            {
                "floor_index": 1,
                "rooms": [
                    {
                        "room_id": "r",
                        "space_type": "sales",
                        "category": "room",
                        "polygon": polygon,
                    }
                ],
                "openings": list(openings),
            }
        )

    def test_a_diagonal_outline_is_passed_through_unchanged(self) -> None:
        room = self._convert(self.DIAMOND).plan["levels"][0]["rooms"][0]

        assert room["polygon"] == self.DIAMOND

    def test_an_opening_lands_on_a_diagonal_wall(self) -> None:
        import math

        half = 0.45 / math.sqrt(2)
        opening = {
            "opening_id": "diag",
            "kind": "door",
            "connects": ["r"],
            # Centred on edge 0, which runs (6,0) -> (12,6).
            "start": [9.0 - half, 3.0 - half],
            "end": [9.0 + half, 3.0 + half],
            "clear_width": 0.9,
        }
        result = self._convert(self.DIAMOND, [opening])
        room = result.plan["levels"][0]["rooms"][0]

        assert room["openings"] == [{"kind": "door", "wall": 0, "t": 0.5, "width": 0.9}]
        assert result.unplaced_openings == []

    def test_a_curve_approximation_keeps_every_segment(self) -> None:
        import math

        arc = [[0.0, 0.0]]
        arc += [
            [8.0 * math.cos((math.pi / 2) * i / 24), 8.0 * math.sin((math.pi / 2) * i / 24)]
            for i in range(25)
        ]
        room = self._convert(arc).plan["levels"][0]["rooms"][0]

        # One wall per segment; dropping any would open the outline.
        assert len(room["polygon"]) == len(arc)

    def test_a_non_convex_outline_is_kept(self) -> None:
        ell = [[0.0, 0.0], [10.0, 0.0], [10.0, 4.0], [4.0, 4.0], [4.0, 10.0], [0.0, 10.0]]
        result = self._convert(ell)

        assert result.plan["levels"][0]["rooms"][0]["polygon"] == ell
        assert result.warnings == []
