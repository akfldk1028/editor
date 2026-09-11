"""The evaluator ranks buildings on data the pipeline already records.

Area shortfall is measured against the *baseline* program, because the
layout fit rewrites every target onto the rectangle the room received --
comparing against the fitted program would report zero shortfall for a
restroom sized at 25.0 m2 and handed 19.68.
"""

from dataclasses import replace

import pytest

from backend.app.modules.generation_loop.evaluator import LayoutScore, score_building
from backend.app.schemas.layout import LayoutCandidate, RoomPolygon
from backend.app.schemas.program import FormRelaxation
from backend.tests.test_program_form_relaxation import _graph  # restroom 25.0 m2 fixture


class _Validation:
    def __init__(self, hard: int) -> None:
        self.hard_violation_count = hard
        self.accepted = hard == 0


class _Floor:
    def __init__(self, layout, program, validation) -> None:
        self.layout, self.program, self.validation = layout, program, validation


class _Building:
    def __init__(self, *floors) -> None:
        self.floor_results = tuple(floors)


def _building(room_area: float, *, hard: int = 0, relaxations=()):
    """A one-floor building whose only room got `room_area` m2."""
    side = room_area ** 0.5
    layout = LayoutCandidate(
        project_id="eval", floor_index=1, candidate_id="c",
        rooms=[RoomPolygon("restroom", "restroom",
                           [(0, 0), (side, 0), (side, side), (0, side)])],
        circulation=[], score=0.0,
    )
    program = replace(_graph(), form_relaxations=tuple(relaxations))
    return _Building(_Floor(layout, program, _Validation(hard)))


def test_a_room_at_its_target_has_no_shortfall():
    score = score_building(_building(25.0), baseline_programs={1: _graph()})

    assert score.area_shortfall == pytest.approx(0.0)
    assert score.worst_shortfall is None


def test_shortfall_is_measured_against_the_baseline_not_the_fit():
    score = score_building(_building(19.68), baseline_programs={1: _graph()})

    assert score.area_shortfall == pytest.approx(0.2128, abs=1e-3)
    assert score.worst_shortfall[0] == "restroom"
    assert score.worst_shortfall[1] == pytest.approx(0.2128, abs=1e-3)


def test_within_band_movement_is_not_shortfall():
    # 24.0 is inside the declared [21.25, 28.75] band.
    score = score_building(_building(24.0), baseline_programs={1: _graph()})

    assert score.area_shortfall == 0.0


def test_ranking_prefers_accepted_then_fewer_hard_violations_then_area():
    good = score_building(_building(25.0), baseline_programs={1: _graph()})
    short = score_building(_building(19.68), baseline_programs={1: _graph()})
    broken = score_building(_building(25.0, hard=2), baseline_programs={1: _graph()})

    assert sorted([broken, short, good], key=LayoutScore.key) == [good, short, broken]


def test_relaxations_count_against_a_building():
    relaxed = score_building(
        _building(25.0, relaxations=[FormRelaxation("restroom", "max_aspect_ratio", 2.5, 8.5, "fit")]),
        baseline_programs={1: _graph()},
    )
    clean = score_building(_building(25.0), baseline_programs={1: _graph()})

    assert relaxed.relaxations == 1
    assert LayoutScore.key(clean) < LayoutScore.key(relaxed)


def test_a_floor_without_a_baseline_is_an_error():
    with pytest.raises(KeyError):
        score_building(_building(25.0), baseline_programs={})
