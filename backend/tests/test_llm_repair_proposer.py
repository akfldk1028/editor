"""The LLM may only speak the repair vocabulary; anything else is ignored."""

import json

from backend.app.modules.generation_loop.evaluator import LayoutScore
from backend.app.modules.generation_loop.llm_repair import LLMRepairProposer
from backend.app.modules.generation_loop.repair import (
    GenerationRequest,
    PrioritizeExterior,
    SwitchStrategy,
)
from backend.app.schemas.llm import FloorAssignment
from backend.tests.test_repair_proposals import _office_graph


class _Client:
    def __init__(self, answer):
        self.answer = answer
        self.payloads = []

    def complete_json(self, *, system_prompt, user_payload, **kwargs):
        self.payloads.append(user_payload)
        return self.answer


def _request():
    return GenerationRequest((FloorAssignment(1, "office"),), {1: _office_graph()})


SCORE = LayoutScore(True, 0, 0.6, 0, ("restroom", 0.6))


def test_a_valid_answer_becomes_a_proposal_and_is_marked_llm():
    proposer = LLMRepairProposer(_Client(json.dumps(
        {"action": "prioritize_exterior", "floor_index": 1, "room_id": "restroom", "reason": "starved"}
    )))

    assert proposer.propose(_request(), SCORE) == PrioritizeExterior(1, "restroom")
    assert proposer.source == "llm"


def test_the_payload_given_to_the_llm_is_the_score_and_the_vocabulary_only():
    client = _Client(json.dumps({"action": "switch_strategy", "layout_strategy": "topology", "reason": "r"}))
    LLMRepairProposer(client).propose(_request(), SCORE)

    payload = client.payloads[0]
    assert payload["worst_shortfall"] == {"room_id": "restroom", "ratio": 0.6}
    assert set(payload["allowed_actions"]) == {"prioritize_exterior", "switch_strategy", "rescale_target"}
    assert "polygon" not in json.dumps(payload)


def test_an_out_of_vocabulary_answer_falls_back_to_the_rule_proposer():
    proposer = LLMRepairProposer(_Client(json.dumps({"action": "widen_aspect_limit", "room_id": "restroom"})))

    assert proposer.propose(_request(), SCORE) == PrioritizeExterior(1, "restroom")
    assert proposer.source == "rule_fallback"


def test_malformed_json_falls_back():
    proposer = LLMRepairProposer(_Client("not json"))

    assert proposer.propose(_request(), SCORE) == PrioritizeExterior(1, "restroom")
    assert proposer.source == "rule_fallback"


def test_a_room_the_floor_does_not_have_falls_back():
    proposer = LLMRepairProposer(_Client(json.dumps(
        {"action": "prioritize_exterior", "floor_index": 1, "room_id": "helipad", "reason": "x"}
    )))

    assert proposer.propose(_request(), SCORE) == PrioritizeExterior(1, "restroom")
    assert proposer.source == "rule_fallback"


def test_a_client_exception_falls_back():
    class Boom:
        def complete_json(self, **kwargs):
            raise RuntimeError("network")

    proposer = LLMRepairProposer(Boom())

    assert proposer.propose(_request(), SCORE) == PrioritizeExterior(1, "restroom")
    assert proposer.source == "rule_fallback"


def test_an_explicit_no_change_answer_returns_none_and_is_marked_llm():
    proposer = LLMRepairProposer(_Client(json.dumps({"action": "none", "reason": "acceptable"})))

    assert proposer.propose(_request(), SCORE) is None
    assert proposer.source == "llm"


def test_a_switch_to_topology_is_accepted_from_the_llm():
    proposer = LLMRepairProposer(_Client(json.dumps(
        {"action": "switch_strategy", "layout_strategy": "topology", "reason": "starved rooms"}
    )))

    assert proposer.propose(_request(), SCORE) == SwitchStrategy("topology")
