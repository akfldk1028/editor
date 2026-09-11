"""What a repair is allowed to be.

The only edits a repair may make are to the *request*: which rooms get
exterior priority, which layout strategy runs, and how large a target is.
None of them can touch min_width or max_aspect_ratio -- those are the gates
the loop exists to satisfy, and widening them is the failure this replaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import math

from backend.app.modules.generation_loop.contracts import ExteriorAllocationRequest
from backend.app.modules.generation_loop.evaluator import LayoutScore
from backend.app.schemas.llm import FloorAssignment
from backend.app.schemas.program import ProgramGraph


LAYOUT_STRATEGIES = ("orthogonal", "topology")
_PRIMARY_ROOM_IDS = ("open_work", "sales")


@dataclass(frozen=True)
class GenerationRequest:
    floor_assignments: tuple[FloorAssignment, ...]
    baseline_programs: dict[int, ProgramGraph]
    program_overrides: dict[int, ProgramGraph] = field(default_factory=dict)
    exterior_room_ids: dict[int, tuple[str, ...]] = field(default_factory=dict)
    layout_strategy: str = "orthogonal"

    def exterior_allocation_requests(self) -> tuple[ExteriorAllocationRequest, ...]:
        return tuple(
            ExteriorAllocationRequest(floor_index, room_ids)
            for floor_index, room_ids in sorted(self.exterior_room_ids.items())
            if room_ids
        )

    def program_for(self, floor_index: int) -> ProgramGraph:
        return self.program_overrides.get(
            floor_index, self.baseline_programs[floor_index]
        )


@dataclass(frozen=True)
class PrioritizeExterior:
    floor_index: int
    room_id: str


@dataclass(frozen=True)
class SwitchStrategy:
    layout_strategy: str

    def __post_init__(self) -> None:
        if self.layout_strategy not in LAYOUT_STRATEGIES:
            raise ValueError(f"unknown layout strategy: {self.layout_strategy}")


@dataclass(frozen=True)
class RescaleTarget:
    floor_index: int
    room_id: str
    factor: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.factor) or not 0.5 <= self.factor <= 1.5:
            raise ValueError("rescale factor must be finite and within [0.5, 1.5]")


RepairProposal = PrioritizeExterior | SwitchStrategy | RescaleTarget


def apply_proposal(
    request: GenerationRequest, proposal: RepairProposal
) -> GenerationRequest:
    if isinstance(proposal, PrioritizeExterior):
        current = set(request.exterior_room_ids.get(proposal.floor_index, ()))
        current.add(proposal.room_id)
        updated = dict(request.exterior_room_ids)
        updated[proposal.floor_index] = tuple(sorted(current))
        return replace(request, exterior_room_ids=updated)
    if isinstance(proposal, SwitchStrategy):
        return replace(request, layout_strategy=proposal.layout_strategy)
    if isinstance(proposal, RescaleTarget):
        program = request.program_for(proposal.floor_index)
        nodes = []
        for node in program.nodes:
            if node.node_id != proposal.room_id:
                nodes.append(node)
                continue
            target = float(node.target_area) * proposal.factor
            nodes.append(
                replace(
                    node,
                    target_area=target,
                    min_area=target * 0.85,
                    max_area=target * 1.15,
                )
            )
        overrides = dict(request.program_overrides)
        overrides[proposal.floor_index] = replace(program, nodes=nodes)
        return replace(request, program_overrides=overrides)
    raise TypeError(f"unsupported proposal: {proposal!r}")


class RuleRepairProposer:
    """The always-available proposer.  Explainable, ordered, terminating."""

    source = "rule"

    def propose(
        self, request: GenerationRequest, score: LayoutScore
    ) -> RepairProposal | None:
        if score.worst_shortfall is None:
            return None
        room_id, ratio = score.worst_shortfall
        if ratio <= 0:
            # An oversized room is the residual absorbing what others lost;
            # the starved rooms are what the loop acts on.
            return None
        floor_index = _floor_of(request, room_id)
        if room_id not in request.exterior_room_ids.get(floor_index, ()):
            return PrioritizeExterior(floor_index, room_id)
        if request.layout_strategy != "topology":
            return SwitchStrategy("topology")
        primary = next(
            (
                node.node_id
                for node in request.program_for(floor_index).nodes
                if node.node_id in _PRIMARY_ROOM_IDS
            ),
            None,
        )
        if primary is None:
            return None
        override = request.program_overrides.get(floor_index)
        if override is not None:
            current = next(n for n in override.nodes if n.node_id == primary).target_area
            baseline = next(
                n
                for n in request.baseline_programs[floor_index].nodes
                if n.node_id == primary
            ).target_area
            if float(current) <= float(baseline) * 0.81:  # two 0.9 steps taken
                return None
        return RescaleTarget(floor_index, primary, 0.9)


def _floor_of(request: GenerationRequest, room_id: str) -> int:
    for floor_index, program in sorted(request.baseline_programs.items()):
        if any(node.node_id == room_id for node in program.nodes):
            return floor_index
    raise KeyError(f"room {room_id} is on no floor")
