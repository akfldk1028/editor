"""Widths come from a linear program with the gates as constraints.

Shekhawat et al. (1910.00081): given adjacencies, dimension the rooms by LP
with minimum width and aspect range per room. Infeasible means the band and
the program disagree and the caller must change one of them -- the LP never
widens a gate to make itself feasible."""

import pytest

from backend.app.modules.topology_planner.dimensioning import (
    TopologyInfeasible,
    dimension_band,
)
from backend.app.modules.topology_planner.slicing import Band
from backend.app.schemas.program import ProgramNode


def _node(node_id, target, *, min_width=1.8, aspect=2.5):
    return ProgramNode(node_id=node_id, space_type=node_id, target_area=target,
                       min_area=target * 0.85, max_area=target * 1.15,
                       min_width=min_width, max_aspect_ratio=aspect)


BAND = Band("b", 0.0, 0.0, 37.0, 4.05, ("restroom", "pantry", "open_work"))


def test_widths_realise_targets_within_the_gates():
    widths = dimension_band(BAND, [_node("restroom", 25.0), _node("pantry", 27.0, aspect=2.0),
                                   _node("open_work", 300.0, min_width=6.0)],
                            residual_room_id="open_work")
    by_id = {w.room_id: w.width for w in widths}

    assert by_id["restroom"] * BAND.depth == pytest.approx(25.0, rel=0.02)
    assert max(by_id["restroom"] / BAND.depth, BAND.depth / by_id["restroom"]) <= 2.5
    assert by_id["pantry"] * BAND.depth == pytest.approx(27.0, rel=0.02)
    assert sum(by_id.values()) == pytest.approx(BAND.length)


def test_the_residual_room_absorbs_the_rest_of_the_band():
    widths = dimension_band(BAND, [_node("restroom", 25.0), _node("open_work", 300.0, min_width=6.0)],
                            residual_room_id="open_work")
    by_id = {w.room_id: w.width for w in widths}

    assert by_id["open_work"] == pytest.approx(BAND.length - by_id["restroom"])


def test_an_aspect_limit_that_the_band_depth_cannot_meet_is_infeasible_not_relaxed():
    # 25 m2 at depth 4.05 needs width 6.17 -> aspect 1.52. Demand 1.2 instead.
    with pytest.raises(TopologyInfeasible) as info:
        dimension_band(BAND, [_node("restroom", 25.0, aspect=1.2), _node("open_work", 300.0, min_width=6.0)],
                       residual_room_id="open_work")

    assert any("restroom" in c and "aspect" in c for c in info.value.constraints)


def test_a_band_too_short_for_the_program_is_infeasible():
    short = Band("s", 0.0, 0.0, 8.0, 4.05, ("restroom", "pantry"))

    with pytest.raises(TopologyInfeasible):
        dimension_band(short, [_node("restroom", 25.0), _node("pantry", 27.0)], residual_room_id=None)


def test_without_a_residual_the_widths_may_leave_band_length_unused():
    long_band = Band("l", 0.0, 0.0, 37.0, 4.05, ("restroom", "pantry"))

    widths = dimension_band(long_band, [_node("restroom", 25.0), _node("pantry", 27.0, aspect=2.0)],
                            residual_room_id=None)

    assert sum(w.width for w in widths) < long_band.length


def test_dimensioning_is_deterministic():
    nodes = [_node("restroom", 25.0), _node("pantry", 27.0, aspect=2.0), _node("open_work", 300.0, min_width=6.0)]

    first = dimension_band(BAND, nodes, residual_room_id="open_work")
    second = dimension_band(BAND, nodes, residual_room_id="open_work")

    assert first == second


def test_the_single_loaded_slab_the_lp_replaces_would_have_failed():
    """The closed form: aspect = depth^2 / area. 9.3 m band, 25 m2 -> 3.46 > 2.5."""
    deep = Band("d", 0.0, 0.0, 37.0, 9.3, ("restroom", "open_work"))

    with pytest.raises(TopologyInfeasible):
        dimension_band(deep, [_node("restroom", 25.0), _node("open_work", 300.0, min_width=6.0)],
                       residual_room_id="open_work")


def test_result_order_follows_the_input_order():
    nodes = [_node("pantry", 27.0, aspect=2.0), _node("restroom", 25.0), _node("open_work", 300.0, min_width=6.0)]

    widths = dimension_band(BAND, nodes, residual_room_id="open_work")

    assert [w.room_id for w in widths] == ["pantry", "restroom", "open_work"]


def test_fill_stretches_rooms_within_their_bands_to_span_the_band_exactly():
    band = Band("f", 0.0, 0.0, 14.0, 4.05, ("restroom", "pantry"))

    widths = dimension_band(band, [_node("restroom", 25.0), _node("pantry", 27.0, aspect=2.0)],
                            residual_room_id=None, fill=True)

    assert sum(w.width for w in widths) == pytest.approx(14.0)
    for w, target in zip(widths, (25.0, 27.0)):
        assert target * 0.85 - 1e-6 <= w.width * band.depth <= target * 1.15 + 1e-6


def test_fill_is_infeasible_when_the_bands_cannot_reach_the_length():
    band = Band("f", 0.0, 0.0, 30.0, 4.05, ("restroom", "pantry"))

    with pytest.raises(TopologyInfeasible):
        dimension_band(band, [_node("restroom", 25.0), _node("pantry", 27.0, aspect=2.0)],
                       residual_room_id=None, fill=True)
