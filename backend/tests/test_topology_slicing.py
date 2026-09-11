"""Where rooms go relative to the spine is decided by zone, not by which cell
happened to touch a corridor.  A double-loaded spine halves each room's depth:
25 m2 off a 9.3 m band is a 3.46 slab; off a 4.05 m band it is 1.52."""

import pytest

from backend.app.modules.topology_planner.slicing import plan_double_loaded_spine
from backend.tests.test_topology_graph import _office


BOUNDS = (0.0, 0.0, 37.0, 26.0)
CORE = (14.0, 18.0, 22.0, 26.0)  # rear-centre core on the north edge


def test_the_spine_runs_along_the_long_axis_and_touches_the_core():
    plan = plan_double_loaded_spine(BOUNDS, core_bounds=CORE, program=_office())

    x0, y0, x1, y1 = plan.spine
    assert plan.axis == "x"
    assert (x1 - x0) == pytest.approx(37.0)
    assert (y1 - y0) == pytest.approx(1.6)
    assert y1 == pytest.approx(18.0)  # spine's far edge is the core's near edge


def test_bands_sit_on_both_sides_of_the_spine_and_tile_the_plate_depth():
    plan = plan_double_loaded_spine(BOUNDS, core_bounds=CORE, program=_office())

    street_side, core_side = plan.bands
    assert street_side.y0 == pytest.approx(0.0)
    assert street_side.y1 == pytest.approx(plan.spine[1])
    assert core_side.y0 == pytest.approx(plan.spine[3])
    assert core_side.y1 == pytest.approx(26.0)


def test_service_rooms_share_the_core_side_and_public_rooms_the_other():
    plan = plan_double_loaded_spine(BOUNDS, core_bounds=CORE, program=_office())
    street_side, core_side = plan.bands

    assert {"restroom", "pantry", "it_storage"} <= set(core_side.room_ids)
    assert {"meeting", "reception"} <= set(street_side.room_ids)


def test_the_primary_room_is_present_in_both_bands_as_the_residual():
    plan = plan_double_loaded_spine(BOUNDS, core_bounds=CORE, program=_office())

    assert all("open_work" in band.room_ids for band in plan.bands)


def test_the_core_is_not_a_band_room():
    plan = plan_double_loaded_spine(BOUNDS, core_bounds=CORE, program=_office())

    assert all("core" not in band.room_ids for band in plan.bands)


def test_a_core_on_the_front_edge_flips_the_bands():
    plan = plan_double_loaded_spine(BOUNDS, core_bounds=(14.0, 0.0, 22.0, 8.0), program=_office())

    street_side, core_side = plan.bands
    assert core_side.y0 == pytest.approx(0.0) and core_side.y1 == pytest.approx(8.0)
    assert plan.spine[1] == pytest.approx(8.0)
    assert "restroom" in core_side.room_ids


def test_a_core_not_on_the_plate_edge_is_rejected():
    with pytest.raises(ValueError, match="core"):
        plan_double_loaded_spine(BOUNDS, core_bounds=(14.0, 10.0, 22.0, 18.0), program=_office())


def test_a_plate_deeper_than_it_is_long_is_rejected():
    with pytest.raises(ValueError, match="long axis"):
        plan_double_loaded_spine((0.0, 0.0, 20.0, 30.0), core_bounds=(6.0, 22.0, 14.0, 30.0), program=_office())


def test_band_length_and_depth_are_derived():
    plan = plan_double_loaded_spine(BOUNDS, core_bounds=CORE, program=_office())
    street_side, core_side = plan.bands

    assert street_side.length == pytest.approx(37.0)
    assert street_side.depth == pytest.approx(16.4)
    assert core_side.depth == pytest.approx(8.0)
