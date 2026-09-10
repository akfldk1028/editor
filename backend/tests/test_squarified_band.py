"""Packing a service band as a treemap instead of equal-depth slabs.

Slicing a band into full-depth strips makes every room's depth the band depth,
so area is bought entirely with width: a 25 m2 restroom in a 9.3 m deep band
comes out 2.69 m x 9.30 m, a 3.46 aspect ratio against a 2.5 limit.  The
squarified treemap picks the split direction from the resulting aspect ratio
instead, and hits the same areas at 1.42.
"""

import pytest

from backend.app.modules.layout_generator.squarified import (
    Band,
    SpaceRequest,
    pack_squarified,
)


OFFICE_BAND = Band(x=0.0, y=0.0, width=24.0, height=9.3)
OFFICE_SPACES = (
    SpaceRequest("focus", "focus", 54.0, min_width=1.8, max_aspect_ratio=1.8),
    SpaceRequest("reception", "reception", 45.0, min_width=2.4, max_aspect_ratio=2.5),
    SpaceRequest("it_storage", "it_storage", 45.0, min_width=1.5, max_aspect_ratio=2.5),
    SpaceRequest("pantry", "pantry", 27.0, min_width=1.8, max_aspect_ratio=2.0),
    SpaceRequest("restroom", "restroom", 25.0, min_width=1.8, max_aspect_ratio=2.5),
)


def test_every_room_lands_inside_its_aspect_limit():
    result = pack_squarified(OFFICE_SPACES, OFFICE_BAND)

    assert result.violations == ()
    assert result.worst_aspect_ratio < 1.8


def test_areas_match_their_targets():
    result = pack_squarified(OFFICE_SPACES, OFFICE_BAND)

    for space in OFFICE_SPACES:
        placed = result.by_id[space.space_id]
        assert placed.area_m2 == pytest.approx(space.target_area_m2, rel=0.02)


def test_the_restroom_beats_the_slab_it_replaces():
    result = pack_squarified(OFFICE_SPACES, OFFICE_BAND)
    restroom = result.by_id["restroom"]

    slab_aspect = OFFICE_BAND.height / (25.0 / OFFICE_BAND.height)
    assert slab_aspect > 3.4  # what the current generator produces, against a 2.5 limit
    assert restroom.aspect_ratio <= 2.5  # the limit the slab had to be widened past
    assert restroom.aspect_ratio < slab_aspect / 2


def test_leftover_band_area_stays_leftover_instead_of_inflating_rooms():
    """Filling the band by scaling the program up is how areas got lost before."""
    result = pack_squarified(OFFICE_SPACES, OFFICE_BAND)
    programmed = sum(space.target_area_m2 for space in OFFICE_SPACES)

    assert programmed < OFFICE_BAND.width * OFFICE_BAND.height
    assert sum(item.area_m2 for item in result.placements) == pytest.approx(
        programmed, rel=1e-6
    )


def test_rooms_do_not_overlap():
    result = pack_squarified(OFFICE_SPACES, OFFICE_BAND)

    for a in result.placements:
        for b in result.placements:
            if a.space_id < b.space_id:
                assert not _overlaps(a, b), f"{a.space_id} overlaps {b.space_id}"


def test_every_room_keeps_a_face_on_the_band_edge():
    """A landlocked room cannot be reached from the corridor."""
    result = pack_squarified(OFFICE_SPACES, OFFICE_BAND)

    for item in result.placements:
        assert item.touches_band_edge


def test_a_violation_is_reported_rather_than_the_limit_widened():
    tight = (
        SpaceRequest("restroom", "restroom", 25.0, min_width=1.8, max_aspect_ratio=1.05),
        SpaceRequest("pantry", "pantry", 27.0, min_width=1.8, max_aspect_ratio=2.0),
    )

    result = pack_squarified(tight, Band(0.0, 0.0, 24.0, 9.3))

    codes = {violation.code for violation in result.violations}
    assert "room_aspect_ratio" in codes
    assert result.by_id["restroom"].max_aspect_ratio == 1.05


def test_a_room_narrower_than_its_minimum_width_is_reported():
    # 6.0 m2 in a band this shape cannot be 4 m across whichever way it is cut.
    narrow = (
        SpaceRequest("restroom", "restroom", 6.0, min_width=4.0, max_aspect_ratio=2.5),
        SpaceRequest("pantry", "pantry", 200.0, min_width=1.8, max_aspect_ratio=8.0),
    )

    result = pack_squarified(narrow, Band(0.0, 0.0, 24.0, 9.3))

    assert "room_min_width" in {violation.code for violation in result.violations}


def test_placements_come_back_in_the_requested_order():
    result = pack_squarified(OFFICE_SPACES, OFFICE_BAND)

    assert [item.space_id for item in result.placements] == [
        space.space_id for space in OFFICE_SPACES
    ]


def test_an_empty_request_packs_nothing():
    result = pack_squarified((), OFFICE_BAND)

    assert result.placements == ()
    assert result.violations == ()


def test_a_band_smaller_than_the_program_is_rejected():
    with pytest.raises(ValueError, match="exceeds"):
        pack_squarified(OFFICE_SPACES, Band(0.0, 0.0, 5.0, 5.0))


def test_polygons_are_closed_axis_aligned_rectangles():
    result = pack_squarified(OFFICE_SPACES, OFFICE_BAND)

    for item in result.placements:
        assert len(item.polygon) == 4
        xs = {round(x, 9) for x, _ in item.polygon}
        ys = {round(y, 9) for _, y in item.polygon}
        assert len(xs) == 2 and len(ys) == 2


def _overlaps(a, b) -> bool:
    ax1, ay1, ax2, ay2 = a.bounds
    bx1, by1, bx2, by2 = b.bounds
    return ax1 < bx2 - 1e-9 and bx1 < ax2 - 1e-9 and ay1 < by2 - 1e-9 and by1 < ay2 - 1e-9


def test_a_single_corridor_edge_exposes_the_landlocked_room():
    """The check this module got wrong first time round.

    Touching any band edge was treated as reachable, so a pantry sitting on the
    far side of the band from the only corridor was reported as fine.
    """
    result = pack_squarified(OFFICE_SPACES, OFFICE_BAND, served_edges=("top",))

    landlocked = {
        violation.space_id
        for violation in result.violations
        if violation.code == "room_no_corridor_access"
    }
    assert landlocked == {"pantry"}


def test_serving_both_long_edges_reaches_every_room():
    result = pack_squarified(
        OFFICE_SPACES, OFFICE_BAND, served_edges=("top", "bottom")
    )

    assert result.violations == ()


def test_an_unknown_served_edge_is_rejected():
    with pytest.raises(ValueError, match="unknown served edges"):
        pack_squarified(OFFICE_SPACES, OFFICE_BAND, served_edges=("north",))
