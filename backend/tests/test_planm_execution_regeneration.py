"""The alternatives stage runs the loop and reports every round."""

import json

from backend.app.modules.generation_loop.evaluator import LayoutScore
from backend.app.modules.generation_loop.regeneration import (
    RegenerationRound,
    RegenerationTrace,
)
from backend.app.modules.generation_loop.repair import PrioritizeExterior
from backend.app.modules.planm_execution.service import (
    alternatives_regeneration_block,
    planm_config_value,
)


def test_trace_is_serialised_with_every_round_and_the_winner():
    trace = RegenerationTrace(
        rounds=(
            RegenerationRound(0, None, None, LayoutScore(True, 0, 0.8, 3, ("meeting", 0.8)), None),
            RegenerationRound(1, PrioritizeExterior(1, "meeting"), "rule",
                              LayoutScore(True, 0, 0.1, 1, ("meeting", 0.1)), None),
            RegenerationRound(2, PrioritizeExterior(1, "focus"), "rule", None, "seed area exceeds bound"),
        ),
        best_round_index=1,
    )

    block = alternatives_regeneration_block(trace, proposer_name="rule")

    assert block["best_round_index"] == 1
    assert block["proposer"] == "rule"
    assert block["rounds"][1]["proposal"] == {
        "action": "prioritize_exterior", "floor_index": 1, "room_id": "meeting",
    }
    assert block["rounds"][1]["score"]["area_shortfall"] == 0.1
    assert block["rounds"][2]["error"] == "seed area exceeds bound"
    assert block["rounds"][2]["score"] is None
    json.dumps(block)  # must be plain JSON


def test_max_rounds_comes_from_the_agent_config():
    # agents/planm/config/default.yaml declares maximum_stage_attempts: 3
    assert planm_config_value("maximum_stage_attempts", default=99) == 3


def test_a_missing_config_key_yields_the_default():
    assert planm_config_value("no_such_key", default=7) == 7
