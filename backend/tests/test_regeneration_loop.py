"""Generate, score, propose, regenerate; keep the best; never relax."""

import pytest

from backend.app.modules.generation_loop.regeneration import regenerate
from backend.app.modules.generation_loop.repair import (
    PrioritizeExterior,
    RescaleTarget,
    RuleRepairProposer,
)
from backend.tests.test_generation_loop import _long_edge_fixture_inputs
from backend.tests.test_layout_evaluator import _building
from backend.tests.test_program_form_relaxation import _graph


class _ScriptedGenerator:
    """Stands in for run_building_generation: returns canned buildings."""

    def __init__(self, buildings):
        self.buildings = list(buildings)
        self.calls = []

    def __call__(self, mass, **kwargs):
        self.calls.append(kwargs)
        return self.buildings.pop(0)


class _ScriptedProposer:
    source = "scripted"

    def __init__(self, proposals):
        self.proposals = list(proposals)

    def propose(self, request, score):
        return self.proposals.pop(0) if self.proposals else None


def _mass():
    return _long_edge_fixture_inputs()[0]


BASELINE = {1: _graph()}


def test_a_first_round_with_no_shortfall_returns_immediately():
    generator = _ScriptedGenerator([_building(25.0)])

    outcome = regenerate(_mass(), proposer=RuleRepairProposer(), max_rounds=3,
                         generator=generator, baseline_programs_override=BASELINE)

    assert outcome.trace.best_round_index == 0
    assert len(outcome.trace.rounds) == 1
    assert len(generator.calls) == 1


def test_the_best_round_is_kept_even_if_a_later_round_is_worse():
    generator = _ScriptedGenerator([_building(19.68), _building(25.0), _building(10.0)])
    proposer = _ScriptedProposer([PrioritizeExterior(1, "restroom"), RescaleTarget(1, "restroom", 0.9)])

    outcome = regenerate(_mass(), proposer=proposer, max_rounds=3, generator=generator,
                         baseline_programs_override=BASELINE)

    assert outcome.trace.best_round_index == 1
    assert outcome.score.area_shortfall == pytest.approx(0.0)


def test_proposals_are_applied_to_the_next_generation_call():
    generator = _ScriptedGenerator([_building(19.68), _building(25.0)])
    proposer = _ScriptedProposer([PrioritizeExterior(1, "restroom")])

    regenerate(_mass(), proposer=proposer, max_rounds=2, generator=generator,
               baseline_programs_override=BASELINE)

    second = generator.calls[1]
    assert [r.room_ids for r in second["exterior_allocation_requests"]] == [("restroom",)]


def test_a_generator_error_is_recorded_as_a_failed_round_not_raised():
    def flaky(mass, **kwargs):
        if kwargs.get("exterior_allocation_requests"):
            raise ValueError("orthogonal layout cannot reserve exterior allocation for restroom")
        return _building(19.68)

    outcome = regenerate(_mass(), proposer=_ScriptedProposer([PrioritizeExterior(1, "restroom")]),
                         max_rounds=2, generator=flaky, baseline_programs_override=BASELINE)

    assert outcome.trace.rounds[1].error.startswith("orthogonal layout cannot")
    assert outcome.trace.best_round_index == 0


def test_the_loop_stops_when_the_proposer_has_nothing_left():
    generator = _ScriptedGenerator([_building(19.68), _building(19.68), _building(19.68)])

    outcome = regenerate(_mass(), proposer=_ScriptedProposer([]), max_rounds=3,
                         generator=generator, baseline_programs_override=BASELINE)

    assert len(outcome.trace.rounds) == 1


def test_the_proposal_source_is_recorded_on_the_round_it_produced():
    generator = _ScriptedGenerator([_building(19.68), _building(25.0)])

    outcome = regenerate(_mass(), proposer=_ScriptedProposer([PrioritizeExterior(1, "restroom")]),
                         max_rounds=2, generator=generator, baseline_programs_override=BASELINE)

    assert outcome.trace.rounds[0].proposal_source is None
    assert outcome.trace.rounds[1].proposal_source == "scripted"


def test_max_rounds_must_be_positive():
    with pytest.raises(ValueError):
        regenerate(_mass(), proposer=RuleRepairProposer(), max_rounds=0)
