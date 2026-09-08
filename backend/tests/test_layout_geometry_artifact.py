from __future__ import annotations

import json
from pathlib import Path

from backend.app.modules.visual_review.layout_geometry import (
    LAYOUT_GEOMETRY_CONTRACT,
    build_floor_geometry,
    write_floor_geometry,
)
from backend.app.schemas.layout import LayoutCandidate, OpeningSegment, RoomPolygon


def _candidate() -> LayoutCandidate:
    return LayoutCandidate(
        candidate_id="cand-1",
        project_id="proj-1",
        floor_index=2,
        rooms=[
            RoomPolygon(
                room_id="sales_a",
                space_type="sales",
                polygon=[(0.0, 0.0), (6.0, 0.0), (6.0, 4.0), (0.0, 4.0)],
            )
        ],
        circulation=[
            RoomPolygon(
                room_id="corridor_1",
                space_type="corridor",
                polygon=[(6.0, 0.0), (7.5, 0.0), (7.5, 4.0), (6.0, 4.0)],
            )
        ],
        score=0.9,
        openings=[
            OpeningSegment(
                opening_id="door_1",
                kind="door",
                connects=("sales_a", "corridor_1"),
                start=(6.0, 1.0),
                end=(6.0, 1.9),
                clear_width=0.9,
            )
        ],
    )


def test_geometry_payload_carries_rooms_circulation_and_openings() -> None:
    payload = build_floor_geometry(_candidate(), use_type="neighbourhood")

    assert payload["contract_version"] == LAYOUT_GEOMETRY_CONTRACT
    assert payload["units"] == "m"
    assert payload["floor_index"] == 2
    assert payload["project_id"] == "proj-1"
    assert payload["candidate_id"] == "cand-1"
    assert payload["use_type"] == "neighbourhood"

    by_id = {room["room_id"]: room for room in payload["rooms"]}
    assert by_id["sales_a"]["category"] == "room"
    assert by_id["sales_a"]["space_type"] == "sales"
    assert by_id["sales_a"]["polygon"] == [[0.0, 0.0], [6.0, 0.0], [6.0, 4.0], [0.0, 4.0]]
    assert by_id["corridor_1"]["category"] == "circulation"

    opening = payload["openings"][0]
    assert opening["kind"] == "door"
    assert opening["connects"] == ["sales_a", "corridor_1"]
    assert opening["start"] == [6.0, 1.0]
    assert opening["clear_width"] == 0.9


def test_geometry_payload_is_json_serialisable_and_written_to_disk(tmp_path: Path) -> None:
    target = write_floor_geometry(
        _candidate(),
        tmp_path / "floor_002" / "plan.geometry.json",
        boundary=[(0.0, 0.0), (7.5, 0.0), (7.5, 4.0), (0.0, 4.0)],
    )

    assert target.is_file()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["boundary"] == [[0.0, 0.0], [7.5, 0.0], [7.5, 4.0], [0.0, 4.0]]
    # Round-trips without loss so a consumer sees the same coordinates.
    assert payload == build_floor_geometry(
        _candidate(), boundary=[(0.0, 0.0), (7.5, 0.0), (7.5, 4.0), (0.0, 4.0)]
    )


def test_geometry_omits_optional_sections_when_absent() -> None:
    payload = build_floor_geometry(_candidate())

    assert "boundary" not in payload
    assert "use_type" not in payload
    assert "remote_stair_footprint" not in payload


def test_a_malformed_opening_is_dropped_rather_than_raising() -> None:
    """The renderer skips bad openings and still emits artifacts; so must this.

    Regression: an unparseable coordinate used to raise out of
    `create_visual_review_artifacts`, so one bad opening blocked a whole floor's
    review instead of costing it a single door.
    """
    candidate = _candidate()
    broken = LayoutCandidate(
        candidate_id=candidate.candidate_id,
        project_id=candidate.project_id,
        floor_index=candidate.floor_index,
        rooms=candidate.rooms,
        circulation=candidate.circulation,
        score=candidate.score,
        openings=[
            OpeningSegment(
                opening_id="broken",
                kind="door",
                connects=("sales_a", "corridor_1"),
                start=("not-a-coordinate", 0.0),
                end=(6.0, 1.9),
                clear_width=0.9,
            ),
            candidate.openings[0],
        ],
    )

    payload = build_floor_geometry(broken)

    assert [o["opening_id"] for o in payload["openings"]] == ["door_1"]


def test_a_non_finite_coordinate_is_dropped() -> None:
    candidate = _candidate()
    broken = LayoutCandidate(
        candidate_id=candidate.candidate_id,
        project_id=candidate.project_id,
        floor_index=candidate.floor_index,
        rooms=candidate.rooms,
        circulation=candidate.circulation,
        score=candidate.score,
        openings=[
            OpeningSegment(
                opening_id="infinite",
                kind="door",
                connects=("sales_a", "corridor_1"),
                start=(float("inf"), 0.0),
                end=(6.0, 1.9),
                clear_width=0.9,
            )
        ],
    )

    assert build_floor_geometry(broken)["openings"] == []
