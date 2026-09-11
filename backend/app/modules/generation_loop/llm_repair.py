"""An LLM as a repair *proposer*, never as a generator.

RMIT (arXiv 2607.00015, 2026) uses an LLM to translate rules into executable
checks and leaves judgement to a deterministic engine; this is the same
division of labour one step earlier.  The model sees the score and the
allowed actions, answers in a strict schema, and the engine applies and
re-validates.  Anything outside the vocabulary -- including the one action a
model is likeliest to invent, widening a limit -- falls back to the rule
proposer and is recorded as a fallback.
"""

from __future__ import annotations

import json
from typing import Any

from backend.app.modules.generation_loop.evaluator import LayoutScore
from backend.app.modules.generation_loop.repair import (
    LAYOUT_STRATEGIES,
    GenerationRequest,
    PrioritizeExterior,
    RepairProposal,
    RescaleTarget,
    RuleRepairProposer,
    SwitchStrategy,
)


REPAIR_SYSTEM_PROMPT = """\
You repair a building floor plan by proposing exactly one structured action.
You never produce geometry and you cannot change minimum widths or aspect
limits. Choose the action most likely to give the worst-starved room its
target area. Answer only with the JSON schema provided.
"""

REPAIR_PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "reason"],
    "properties": {
        "action": {
            "enum": ["prioritize_exterior", "switch_strategy", "rescale_target", "none"]
        },
        "floor_index": {"type": "integer", "minimum": 1},
        "room_id": {"type": "string"},
        "layout_strategy": {"enum": list(LAYOUT_STRATEGIES)},
        "factor": {"type": "number", "minimum": 0.5, "maximum": 1.5},
        "reason": {"type": "string"},
    },
}


class LLMRepairProposer:
    def __init__(self, client, *, fallback=None) -> None:
        self._client = client
        self._fallback = fallback or RuleRepairProposer()
        self.source = "llm"

    def propose(
        self, request: GenerationRequest, score: LayoutScore
    ) -> RepairProposal | None:
        try:
            raw = self._client.complete_json(
                system_prompt=REPAIR_SYSTEM_PROMPT,
                user_payload=_payload(request, score),
                response_schema=REPAIR_PROPOSAL_SCHEMA,
                schema_name="planm_repair_proposal",
            )
            proposal = _parse(json.loads(raw), request)
        except Exception:
            # Any failure of the optional path is a fallback, not an error.
            self.source = "rule_fallback"
            return self._fallback.propose(request, score)
        self.source = "llm"
        return proposal


def _payload(request: GenerationRequest, score: LayoutScore) -> dict[str, Any]:
    rooms = {
        str(floor_index): [node.node_id for node in program.nodes]
        for floor_index, program in sorted(request.baseline_programs.items())
    }
    return {
        "accepted": score.accepted,
        "hard_violations": score.hard_violations,
        "area_shortfall": round(score.area_shortfall, 4),
        "relaxations": score.relaxations,
        "worst_shortfall": (
            {
                "room_id": score.worst_shortfall[0],
                "ratio": round(score.worst_shortfall[1], 4),
            }
            if score.worst_shortfall
            else None
        ),
        "layout_strategy": request.layout_strategy,
        "exterior_room_ids": {
            str(floor_index): list(room_ids)
            for floor_index, room_ids in request.exterior_room_ids.items()
        },
        "rooms_by_floor": rooms,
        "allowed_actions": ["prioritize_exterior", "switch_strategy", "rescale_target"],
    }


class _Reject(Exception):
    pass


def _parse(answer: dict[str, Any], request: GenerationRequest) -> RepairProposal | None:
    action = answer.get("action")
    if action == "none":
        return None
    if action == "prioritize_exterior":
        floor_index, room_id = int(answer["floor_index"]), str(answer["room_id"])
        _require_room(request, floor_index, room_id)
        return PrioritizeExterior(floor_index, room_id)
    if action == "switch_strategy":
        return SwitchStrategy(str(answer["layout_strategy"]))
    if action == "rescale_target":
        floor_index, room_id = int(answer["floor_index"]), str(answer["room_id"])
        _require_room(request, floor_index, room_id)
        return RescaleTarget(floor_index, room_id, float(answer["factor"]))
    raise _Reject(f"action outside vocabulary: {action!r}")


def _require_room(request: GenerationRequest, floor_index: int, room_id: str) -> None:
    program = request.baseline_programs.get(floor_index)
    if program is None or all(node.node_id != room_id for node in program.nodes):
        raise _Reject(f"no room {room_id!r} on floor {floor_index}")
