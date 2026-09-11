"""Generate → evaluate → propose → regenerate, keeping the best.

GreenPlanner took RPLAN from 60% invalid to 0% by regenerating whatever its
evaluator rejected instead of loosening the criteria.  This loop does the
same with the deterministic evaluator in evaluator.py and the closed repair
vocabulary in repair.py.  A proposer may be the rule proposer or an LLM; either
way the engine applies the proposal and re-validates, and a round that raises
is recorded as a failed round rather than aborting the loop.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from backend.app.modules.generation_loop.evaluator import LayoutScore, score_building
from backend.app.modules.generation_loop.repair import (
    GenerationRequest,
    RepairProposal,
    apply_proposal,
)
from backend.app.modules.generation_loop.service import (
    assign_floors_from_use_mix,
    run_building_generation,
)
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.schemas.llm import FloorAssignment
from backend.app.schemas.mass import MassInput
from backend.app.schemas.program import ProgramGraph


@dataclass(frozen=True)
class RegenerationRound:
    round_index: int
    proposal: RepairProposal | None
    proposal_source: str | None
    score: LayoutScore | None
    error: str | None


@dataclass(frozen=True)
class RegenerationTrace:
    rounds: tuple[RegenerationRound, ...]
    best_round_index: int


@dataclass(frozen=True)
class RegenerationOutcome:
    building: object
    request: GenerationRequest
    score: LayoutScore
    trace: RegenerationTrace


def regenerate(
    mass: MassInput,
    *,
    proposer,
    max_rounds: int,
    floor_assignments: Iterable[FloorAssignment] | None = None,
    layout_strategy: str = "orthogonal",
    generator: Callable = run_building_generation,
    baseline_programs_override: Mapping[int, ProgramGraph] | None = None,
) -> RegenerationOutcome:
    if not isinstance(max_rounds, int) or isinstance(max_rounds, bool) or max_rounds < 1:
        raise ValueError("max_rounds must be a positive integer")
    assignments = (
        tuple(floor_assignments)
        if floor_assignments is not None
        else assign_floors_from_use_mix(mass)
    )
    if baseline_programs_override is not None:
        baselines = dict(baseline_programs_override)
    else:
        analysis = analyze_mass(mass)
        baselines = {
            assignment.floor_index: generate_program_graph(
                analysis,
                floor_index=assignment.floor_index,
                use_type=assignment.use_type,
            )
            for assignment in assignments
        }
    request = GenerationRequest(
        floor_assignments=assignments,
        baseline_programs=baselines,
        layout_strategy=layout_strategy,
    )

    rounds: list[RegenerationRound] = []
    best: tuple[LayoutScore, object, GenerationRequest, int] | None = None
    proposal: RepairProposal | None = None
    source: str | None = None
    for index in range(max_rounds):
        if index > 0:
            if proposal is None:
                break
            request = apply_proposal(request, proposal)
        try:
            building = generator(mass, **_generator_kwargs(request))
        except (ValueError, TypeError) as error:
            rounds.append(RegenerationRound(index, proposal, source, None, str(error)))
            proposal, source = _next(proposer, request, best[0] if best else None)
            continue
        score = score_building(building, baseline_programs=request.baseline_programs)
        rounds.append(RegenerationRound(index, proposal, source, score, None))
        if best is None or score.key() < best[0].key():
            best = (score, building, request, index)
        if (
            score.area_shortfall == 0.0
            and score.hard_violations == 0
            and score.relaxations == 0
        ):
            break
        proposal, source = _next(proposer, request, score)
    if best is None:
        raise RuntimeError(
            "every regeneration round failed: "
            + "; ".join(item.error or "" for item in rounds)
        )
    score, building, request, best_index = best
    return RegenerationOutcome(
        building=building,
        request=request,
        score=score,
        trace=RegenerationTrace(rounds=tuple(rounds), best_round_index=best_index),
    )


def _generator_kwargs(request: GenerationRequest) -> dict:
    kwargs = {
        "floor_assignments": request.floor_assignments,
        "program_overrides": request.program_overrides or None,
        "exterior_allocation_requests": request.exterior_allocation_requests(),
    }
    # The orthogonal strategy is the generator's default; naming it would be
    # noise, and a generator that predates the strategy switch still works.
    if request.layout_strategy != "orthogonal":
        kwargs["layout_strategy"] = request.layout_strategy
    return kwargs


def _next(proposer, request, score):
    if score is None:
        return None, None
    proposal = proposer.propose(request, score)
    if proposal is None:
        return None, None
    return proposal, getattr(proposer, "source", type(proposer).__name__)
