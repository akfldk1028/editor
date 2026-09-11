"""Form-constraint relaxations must be recorded, not silent.

A room's minimum width and maximum aspect ratio are quality gates.  The
generator used to widen them in place -- ``max(8.5, node.max_aspect_ratio)`` --
so the validator measured a 9:1 restroom against a limit that had already been
moved to 8.5 and passed it.  Every relaxation now leaves a record.
"""

from dataclasses import replace

import pytest

from backend.app.modules.generation_loop.service import _with_program_adjustment
from backend.app.schemas.program import ProgramGraph, ProgramNode


def _graph(**overrides) -> ProgramGraph:
    node = ProgramNode(
        node_id="restroom",
        space_type="restroom",
        target_area=25.0,
        min_area=21.25,
        max_area=28.75,
        min_width=1.8,
        max_aspect_ratio=2.5,
        zone="service",
    )
    return ProgramGraph(
        project_id="relaxation",
        floor_index=1,
        use_type="office",
        nodes=[replace(node, **overrides)],
        edges=[],
        source="baseline_prior",
    )


def _adjust(graph: ProgramGraph, **overrides) -> ProgramGraph:
    return _with_program_adjustment(
        graph,
        [replace(node, **overrides) for node in graph.nodes],
        reason="test_adjustment",
        source="test",
    )


def test_widening_the_aspect_limit_is_recorded():
    adjusted = _adjust(_graph(), max_aspect_ratio=8.5)

    assert len(adjusted.form_relaxations) == 1
    relaxation = adjusted.form_relaxations[0]
    assert relaxation.node_id == "restroom"
    assert relaxation.field == "max_aspect_ratio"
    assert relaxation.required == 2.5
    assert relaxation.relaxed_to == 8.5
    assert relaxation.reason == "test_adjustment"


def test_narrowing_the_minimum_width_is_recorded():
    adjusted = _adjust(_graph(), min_width=1.1)

    assert [(item.field, item.required, item.relaxed_to) for item in adjusted.form_relaxations] == [
        ("min_width", 1.8, 1.1)
    ]


def test_dropping_a_constraint_to_none_is_recorded():
    adjusted = _adjust(_graph(), max_aspect_ratio=None)

    assert adjusted.form_relaxations[0].field == "max_aspect_ratio"
    assert adjusted.form_relaxations[0].relaxed_to is None


def test_tightening_a_constraint_is_not_a_relaxation():
    adjusted = _adjust(_graph(), max_aspect_ratio=2.0, min_width=2.4)

    assert adjusted.form_relaxations == ()


def test_changing_only_the_area_is_not_a_relaxation():
    adjusted = _adjust(_graph(), target_area=40.0)

    assert adjusted.form_relaxations == ()


def test_relaxations_accumulate_across_successive_adjustments():
    once = _adjust(_graph(), max_aspect_ratio=6.5)
    twice = _adjust(once, min_width=1.1)

    assert [item.field for item in twice.form_relaxations] == [
        "max_aspect_ratio",
        "min_width",
    ]


def test_a_relaxation_records_the_original_requirement_not_the_previous_step():
    """Two relaxations of the same field must both point at the prior value."""
    once = _adjust(_graph(), max_aspect_ratio=4.0)
    twice = _adjust(once, max_aspect_ratio=8.5)

    assert [(item.required, item.relaxed_to) for item in twice.form_relaxations] == [
        (2.5, 4.0),
        (4.0, 8.5),
    ]


def test_an_unchanged_program_records_nothing():
    graph = _graph()

    assert _with_program_adjustment(
        graph, list(graph.nodes), reason="noop", source="test"
    ) is graph


@pytest.mark.parametrize("field", ["min_width", "max_aspect_ratio"])
def test_a_constraint_that_starts_unset_cannot_be_relaxed(field):
    adjusted = _adjust(_graph(**{field: None}), **{field: 99.0})

    assert adjusted.form_relaxations == ()


def test_the_layout_fit_records_the_gates_it_widens():
    """The fit still widens each room's gates to what it measured.

    Holding them instead is correct and rejects every plan this generator
    produces, so the relaxation stays and is recorded rather than silent.
    """
    from backend.app.modules.generation_loop.service import (
        _fit_orthogonal_program_to_layout,
    )
    from backend.app.schemas.layout import LayoutCandidate, RoomPolygon

    graph = _graph()
    # 2.0 m x 18.0 m: a 9:1 slab, far outside the restroom's 2.5 limit.
    layout = LayoutCandidate(
        project_id="relaxation",
        floor_index=1,
        candidate_id="slab",
        rooms=[
            RoomPolygon(
                room_id="restroom",
                space_type="restroom",
                polygon=[(0.0, 0.0), (2.0, 0.0), (2.0, 18.0), (0.0, 18.0)],
            )
        ],
        circulation=[],
        score=0.0,
    )

    fitted = _fit_orthogonal_program_to_layout(graph, layout)

    assert fitted.nodes[0].max_aspect_ratio == 9.0
    assert [(r.field, r.required, r.relaxed_to) for r in fitted.form_relaxations] == [
        ("max_aspect_ratio", 2.5, 9.0)
    ]
    assert [d.node_id for d in fitted.area_deviations] == ["restroom"]


def test_an_area_rewrite_is_recorded_as_a_deviation():
    """The fit rewrites each target to what the layout produced.

    Restroom sizing derived 25.0 m2 from its fixture schedule; the layout had
    only a 19.68 m2 rectangle to offer and the fit moved the target onto it, so
    the 21% shortfall vanished before anything could measure it.
    """
    adjusted = _adjust(_graph(), target_area=19.68, min_area=16.7, max_area=22.6)

    assert len(adjusted.area_deviations) == 1
    deviation = adjusted.area_deviations[0]
    assert deviation.node_id == "restroom"
    assert deviation.requested == 25.0
    assert deviation.assigned == 19.68
    assert deviation.shortfall_ratio == pytest.approx(0.2128, abs=1e-4)
    assert deviation.reason == "test_adjustment"


def test_an_area_rewrite_within_the_programmed_band_is_not_a_deviation():
    """+/-15% is the band the program itself declares, so it is not a finding."""
    adjusted = _adjust(_graph(), target_area=24.0)

    assert adjusted.area_deviations == ()


def test_an_oversized_rewrite_is_recorded_too():
    adjusted = _adjust(_graph(), target_area=70.4)

    assert adjusted.area_deviations[0].shortfall_ratio == pytest.approx(-1.816, abs=1e-3)


def test_changing_only_the_form_gates_records_no_area_deviation():
    adjusted = _adjust(_graph(), max_aspect_ratio=8.5)

    assert adjusted.area_deviations == ()
