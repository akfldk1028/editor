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
    SwitchStrategy,
    GenerationRequest,
    RepairProposal,
    apply_proposal,
)
from backend.app.modules.circulation_planner.contracts import CirculationCandidate
from backend.app.modules.circulation_planner.service import circulation_geometry_fingerprint
from backend.app.modules.core_planner.contracts import CoreCandidate
from backend.app.modules.core_planner.service import core_geometry_fingerprint
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
    core_override: CoreCandidate | None = None,
    circulation_overrides: Mapping[int, CirculationCandidate] | None = None,
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
    fixed_kwargs: dict = {}
    if core_override is not None:
        fixed_kwargs["core_override"] = core_override
    if circulation_overrides:
        fixed_kwargs["circulation_overrides"] = dict(circulation_overrides)

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
            building = generator(mass, **_generator_kwargs(request), **_structure_kwargs(request, fixed_kwargs))
        except (ValueError, TypeError) as error:
            rounds.append(RegenerationRound(index, proposal, source, None, str(error)))
            proposal, source = _escalate_after_error(request) or _next(proposer, request, best[0] if best else None)
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


def seed_core_from_alternatives(result) -> CoreCandidate | None:
    """The core the composer actually drew, so the loop refines that building.

    Without it run_building_generation sizes the core from the program's
    ratio -- 175 m2 on the sample office against the 72 m2 core every drawing
    shows -- and the topology strategy is handed a core that sits on no edge.
    """
    alternatives = list(getattr(result, "alternatives", ()))
    if not alternatives:
        return None
    ranked = sorted(alternatives, key=lambda item: (not item.accepted, item.rank))
    best = ranked[0]
    floors = best.building.floor_results
    core = next(
        (room for room in floors[0].layout.rooms if room.space_type == "core"), None
    )
    if core is None:
        return None
    polygon = tuple((float(x), float(y)) for x, y in core.polygon)
    return CoreCandidate(
        strategy=best.strategy,
        polygon=polygon,
        fingerprint=core_geometry_fingerprint(polygon),
        # run_building_generation expects the 0-based identity of every floor.
        contained_floor_indices=tuple(range(len(floors))),
    )


def seed_circulation_from_alternatives(
    result, core: CoreCandidate | None
) -> dict[int, CirculationCandidate] | None:
    """The composer's corridors and remote stair, floor by floor, bound to its core.

    run_building_generation needs both overrides to reproduce a composed
    building: with the core alone the orthogonal path has no circulation to
    lay rooms against.  Every floor must carry a corridor and a stair or the
    seed is withheld.
    """
    if core is None:
        return None
    alternatives = list(getattr(result, "alternatives", ()))
    if not alternatives:
        return None
    best = sorted(alternatives, key=lambda item: (not item.accepted, item.rank))[0]
    overrides: dict[int, CirculationCandidate] = {}
    for floor in best.building.floor_results:
        layout = floor.layout
        stair = layout.remote_stair_footprint
        if not layout.circulation or stair is None:
            return None
        polygons = tuple(
            tuple((float(x), float(y)) for x, y in path.polygon) for path in layout.circulation
        )
        stair_ring = tuple((float(x), float(y)) for x, y in stair)
        overrides[floor.program.floor_index] = CirculationCandidate(
            strategy=best.strategy,
            polygons=polygons,
            remote_stair_polygon=stair_ring,
            fingerprint=circulation_geometry_fingerprint(
                strategy=best.strategy,
                core_fingerprint=core.fingerprint,
                polygons=polygons,
                remote_stair=stair_ring,
            ),
            entrance_connected=True,
            core_connected=True,
            stair_connected=True,
            core_fingerprint=core.fingerprint,
        )
    return overrides


_STRUCTURE_FIRST = ("topology", "growth")


def _escalate_after_error(request: GenerationRequest):
    """A structure-first strategy that could not place its rooms hands the
    same structure to the next solver instead of asking the proposer."""
    if request.layout_strategy == "topology":
        return SwitchStrategy("growth"), "rule"
    return None


def _structure_kwargs(request: GenerationRequest, fixed: dict) -> dict:
    """The structure-first strategies plan their own corridor and core position,
    so the composer's structural overrides become a dimensions hint for them
    rather than a constraint the generator would then fail to reproduce."""
    if request.layout_strategy not in _STRUCTURE_FIRST:
        return fixed
    hint = fixed.get("core_override")
    return {"topology_core_hint": hint} if hint is not None else {}


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
    if request.layout_strategy in _STRUCTURE_FIRST:
        # Exterior priority is a repair aimed at the orthogonal cell layout.
        # The topology strategy places rooms from the adjacency graph and the
        # zone plan, so a request carried over from an earlier round would only
        # fail its daylight check against a room the graph put inside.
        kwargs["exterior_allocation_requests"] = ()
    return kwargs


def _next(proposer, request, score):
    if score is None:
        return None, None
    proposal = proposer.propose(request, score)
    if proposal is None:
        return None, None
    return proposal, getattr(proposer, "source", type(proposer).__name__)
