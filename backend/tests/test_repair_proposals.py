"""Repairs are structured edits to the request, never edits to the gates."""

from dataclasses import replace

import pytest

from backend.app.modules.generation_loop.evaluator import LayoutScore
from backend.app.modules.generation_loop.repair import (
    GenerationRequest,
    PrioritizeExterior,
    RescaleTarget,
    RuleRepairProposer,
    SwitchStrategy,
    apply_proposal,
)
from backend.app.schemas.llm import FloorAssignment
from backend.app.schemas.program import ProgramNode
from backend.tests.test_program_form_relaxation import _graph


def _office_graph():
    """The restroom fixture plus an open_work primary, so the proposer has a residual."""
    graph = _graph()
    primary = ProgramNode(
        node_id="open_work", space_type="open_work", target_area=500.0,
        min_area=425.0, max_area=575.0, min_width=6.0, max_aspect_ratio=2.5,
        zone="workplace",
    )
    return replace(graph, nodes=[*graph.nodes, primary])


def _request(**overrides) -> GenerationRequest:
    base = GenerationRequest(
        floor_assignments=(FloorAssignment(1, "office"),),
        baseline_programs={1: _office_graph()},
        program_overrides={},
        exterior_room_ids={},
        layout_strategy="orthogonal",
    )
    return replace(base, **overrides)


def test_prioritize_exterior_adds_a_request_for_that_floor():
    updated = apply_proposal(_request(), PrioritizeExterior(1, "restroom"))

    assert updated.exterior_room_ids == {1: ("restroom",)}
    assert [r.room_ids for r in updated.exterior_allocation_requests()] == [("restroom",)]


def test_prioritize_exterior_is_idempotent_and_sorted():
    once = apply_proposal(_request(), PrioritizeExterior(1, "restroom"))
    twice = apply_proposal(once, PrioritizeExterior(1, "restroom"))
    added = apply_proposal(twice, PrioritizeExterior(1, "meeting"))

    assert twice == once
    assert added.exterior_room_ids[1] == ("meeting", "restroom")


def test_switch_strategy_rejects_unknown_strategies():
    with pytest.raises(ValueError, match="layout strategy"):
        SwitchStrategy("diffusion")


def test_rescale_target_changes_the_override_not_the_baseline():
    updated = apply_proposal(_request(), RescaleTarget(1, "restroom", 0.8))

    assert updated.baseline_programs[1].nodes[0].target_area == 25.0
    node = updated.program_overrides[1].nodes[0]
    assert node.target_area == pytest.approx(20.0)
    assert node.min_area == pytest.approx(17.0)
    assert node.max_area == pytest.approx(23.0)
    # Form gates are untouchable by the vocabulary.
    assert node.min_width == 1.8 and node.max_aspect_ratio == 2.5


@pytest.mark.parametrize("factor", [0.49, 1.51, float("nan")])
def test_rescale_factor_is_bounded(factor):
    with pytest.raises(ValueError, match="factor"):
        RescaleTarget(1, "restroom", factor)


def test_apply_proposal_never_mutates_its_input():
    request = _request()
    apply_proposal(request, PrioritizeExterior(1, "restroom"))

    assert request.exterior_room_ids == {}


def test_rule_proposer_prioritizes_the_worst_starved_room_first():
    score = LayoutScore(accepted=True, hard_violations=0, area_shortfall=0.8,
                        relaxations=3, worst_shortfall=("restroom", 0.8))

    proposal = RuleRepairProposer().propose(_request(), score)

    assert proposal == PrioritizeExterior(1, "restroom")


def test_rule_proposer_switches_strategy_once_exterior_is_already_requested():
    score = LayoutScore(True, 0, 0.8, 3, ("restroom", 0.8))
    request = apply_proposal(_request(), PrioritizeExterior(1, "restroom"))

    assert RuleRepairProposer().propose(request, score) == SwitchStrategy("topology")


def test_rule_proposer_releases_primary_area_as_a_last_resort():
    score = LayoutScore(True, 0, 0.8, 3, ("restroom", 0.8))
    request = apply_proposal(
        apply_proposal(_request(), PrioritizeExterior(1, "restroom")),
        SwitchStrategy("topology"),
    )

    assert RuleRepairProposer().propose(request, score) == RescaleTarget(1, "open_work", 0.9)


def test_rule_proposer_stops_when_nothing_is_short():
    score = LayoutScore(True, 0, 0.0, 0, None)

    assert RuleRepairProposer().propose(_request(), score) is None


def test_rule_proposer_has_a_source_name_for_the_trace():
    assert RuleRepairProposer().source == "rule"


def test_a_starved_primary_room_goes_straight_to_the_strategy_switch():
    """Exterior priority for the residual room changes nothing about its size."""
    score = LayoutScore(True, 0, 0.9, 3, ("open_work", 0.9))

    assert RuleRepairProposer().propose(_request(), score) == SwitchStrategy("topology")
