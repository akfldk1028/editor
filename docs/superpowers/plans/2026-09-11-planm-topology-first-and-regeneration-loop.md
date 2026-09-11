# PLANM Topology-First Layout + Regeneration Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace symptom patching with (B) a deterministic evaluate→regenerate loop that accepts optional LLM repair proposals, and (A) a topology-first layout strategy whose room dimensions come from a linear program, so floor plans meet their normative areas and form gates instead of having the gates widened.

**Architecture:** Part B wraps the existing `run_building_generation` in a scored loop: a `LayoutScore` computed from existing validation data ranks candidates, a `RepairProposer` (rule-based always; LLM optional) emits closed-vocabulary proposals that mutate a `GenerationRequest`, and the best building after ≤ N rounds is returned with a trace. Part A adds a new layout strategy: program → adjacency graph (spanning circulation) → slicing plan (double-loaded spine, zone-driven bands) → `scipy.optimize.linprog` dimensioning → `LayoutCandidate`, raising on infeasibility instead of relaxing.

**Tech Stack:** Python 3.11, shapely 2.1, scipy 1.17 (`linprog`), pytest, existing `StructuredPlannerClient` protocol for the optional LLM.

**Spec:** `docs/superpowers/specs/2026-09-11-planm-topology-first-and-regeneration-loop-design.md`

## Global Constraints

- Run every command from `C:/DK/Editor/editor` (the `pyproject.toml` root); tests are `python -m pytest backend/tests/...`.
- No form gate (`min_width`, `max_aspect_ratio`) may be widened by any new code. Widening is detected automatically by `_with_program_adjustment`; a test asserting `form_relaxations == ()` on new-generator output is mandatory.
- Determinism: no randomness, no wall-clock in outputs, LLM off unless a client is passed.
- Metric gate per task that touches generation: `python -m backend.tools.regenerate_plans --label <task>` must not increase `area_deviations` (baseline 41) or `form_relaxations` (baseline 20) in `report.json`.
- Full suite gate before each commit that touches `generation_loop`, `layout_generator`, or `circulation_planner`: `python -m pytest backend/tests -q` — baseline `1034 passed, 2 skipped`. Any regression is fixed or the task is reverted; never skipped.
- New dependency allowed: `scipy>=1.17,<2` only.
- Commit attribution trailer (exact):
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01EhVE6bh7zsCVZL2py8a9yj
  ```

---

## File map

| File | Responsibility |
|---|---|
| `backend/app/modules/generation_loop/evaluator.py` (new) | `LayoutScore`, `score_building` — deterministic ranking from existing data |
| `backend/app/modules/generation_loop/repair.py` (new) | `GenerationRequest`, closed proposal vocabulary, `apply_proposal`, `RuleRepairProposer` |
| `backend/app/modules/generation_loop/llm_repair.py` (new) | `LLMRepairProposer` — wraps `StructuredPlannerClient`, validates, falls back |
| `backend/app/modules/generation_loop/regeneration.py` (new) | `regenerate` loop + `RegenerationTrace` |
| `backend/app/modules/llm_planner/openai_client.py` (modify) | `complete_json(..., response_schema=None)` so callers can pass their own schema |
| `backend/app/modules/planm_execution/service.py` (modify `alternatives`) | run the loop, write trace into `alternatives.json` |
| `backend/tools/regenerate_plans.py` (modify) | `--rounds`, `--llm` flags; trace into `report.json` |
| `backend/app/modules/topology_planner/__init__.py` (new) | package |
| `backend/app/modules/topology_planner/graph.py` (new) | `AdjacencyGraph`, `build_adjacency_graph` |
| `backend/app/modules/topology_planner/slicing.py` (new) | `SlicingPlan`, `plan_double_loaded_spine` |
| `backend/app/modules/topology_planner/dimensioning.py` (new) | `dimension_band` (LP), `TopologyInfeasible` |
| `backend/app/modules/topology_planner/service.py` (new) | `generate_topology_layout` → `LayoutCandidate` |
| `backend/app/modules/generation_loop/service.py` (modify) | `layout_strategy` dispatch in `run_building_generation` |
| `pyproject.toml` (modify) | add scipy |

---

### Task 1: Deterministic layout evaluator

**Files:**
- Create: `backend/app/modules/generation_loop/evaluator.py`
- Test: `backend/tests/test_layout_evaluator.py`

**Interfaces:**
- Consumes: `BuildingGenerationResult` (`backend/app/schemas/result.py:73`) with `.floor_results: tuple[GenerationResult]`; `GenerationResult.layout.rooms`, `.validation.hard_violation_count`, `.validation.accepted`, `.program.form_relaxations`; `ProgramGraph` baseline per floor.
- Produces: `LayoutScore` dataclass with `accepted: bool`, `hard_violations: int`, `area_shortfall: float`, `relaxations: int`, `worst_shortfall: tuple[str, float] | None`, method `key() -> tuple`; function `score_building(building, *, baseline_programs: Mapping[int, ProgramGraph]) -> LayoutScore`.

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_layout_evaluator.py
"""The evaluator ranks buildings on data the pipeline already records.

Area shortfall is measured against the *baseline* program, because the
layout fit rewrites every target onto the rectangle the room received --
comparing against the fitted program would report zero shortfall for a
restroom sized at 25.0 m2 and handed 19.68.
"""

from dataclasses import replace

import pytest

from backend.app.modules.generation_loop.evaluator import LayoutScore, score_building
from backend.app.schemas.program import ProgramGraph, ProgramNode
from backend.tests.test_program_form_relaxation import _graph  # restroom 25.0 m2 fixture


def _building(room_area: float, *, hard: int = 0, relaxations=()):
    """A one-floor building whose only room got `room_area` m2."""
    from backend.app.schemas.layout import LayoutCandidate, RoomPolygon
    from backend.app.schemas.metrics import ValidationReport

    side = room_area ** 0.5
    layout = LayoutCandidate(
        project_id="eval", floor_index=1, candidate_id="c",
        rooms=[RoomPolygon("restroom", "restroom",
                           [(0, 0), (side, 0), (side, side), (0, side)])],
        circulation=[], score=0.0,
    )
    program = replace(_graph(), form_relaxations=tuple(relaxations))
    validation = ValidationReport.__new__(ValidationReport)
    object.__setattr__(validation, "hard_violation_count", hard)
    object.__setattr__(validation, "accepted", hard == 0)
    floor = type("Floor", (), {})()
    floor.layout, floor.program, floor.validation = layout, program, validation
    floor.mass = None
    building = type("Building", (), {})()
    building.floor_results = (floor,)
    return building


def test_a_room_at_its_target_has_no_shortfall():
    score = score_building(_building(25.0), baseline_programs={1: _graph()})

    assert score.area_shortfall == pytest.approx(0.0)
    assert score.worst_shortfall is None


def test_shortfall_is_measured_against_the_baseline_not_the_fit():
    score = score_building(_building(19.68), baseline_programs={1: _graph()})

    assert score.area_shortfall == pytest.approx(0.2128, abs=1e-3)
    assert score.worst_shortfall == ("restroom", pytest.approx(0.2128, abs=1e-3))


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
    from backend.app.schemas.program import FormRelaxation

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
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_layout_evaluator.py -q`
Expected: `ImportError: cannot import name 'LayoutScore'`

- [x] **Step 3: Write minimal implementation**

```python
# backend/app/modules/generation_loop/evaluator.py
"""Rank generated buildings on what the pipeline already measures.

GreenPlanner (2025) and the AiC 2025 accessibility work both put a
deterministic evaluator between the generator and the output and regenerate
whatever fails it.  This is that evaluator.  It computes nothing new: hard
violations come from the validator, form relaxations from the program
adjustment record, and area shortfall from room polygons measured against the
*baseline* program -- the fitted program has had its targets rewritten onto
whatever the rooms received and would report zero shortfall for everything.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from backend.app.schemas.program import ProgramGraph
from backend.engine.geometry import polygon_area


@dataclass(frozen=True)
class LayoutScore:
    accepted: bool
    hard_violations: int
    area_shortfall: float
    relaxations: int
    worst_shortfall: tuple[str, float] | None

    def key(self) -> tuple[bool, int, float, int]:
        """Sort key; lower is better."""
        return (not self.accepted, self.hard_violations, self.area_shortfall, self.relaxations)


def score_building(
    building,
    *,
    baseline_programs: Mapping[int, ProgramGraph],
) -> LayoutScore:
    accepted = True
    hard = 0
    shortfall_total = 0.0
    relaxations = 0
    worst: tuple[str, float] | None = None
    for floor in building.floor_results:
        floor_index = floor.program.floor_index
        baseline = baseline_programs[floor_index]  # KeyError is the contract
        accepted = accepted and bool(floor.validation.accepted)
        hard += int(floor.validation.hard_violation_count)
        relaxations += len(getattr(floor.program, "form_relaxations", ()))
        areas = {room.room_id: polygon_area(room.polygon) for room in floor.layout.rooms}
        for node in baseline.nodes:
            got = areas.get(node.node_id)
            if got is None:
                continue
            target = float(node.target_area)
            low = float(node.min_area) if node.min_area else target * 0.85
            high = float(node.max_area) if node.max_area else target * 1.15
            if low - 1e-9 <= got <= high + 1e-9:
                continue
            ratio = (target - got) / target
            shortfall_total += abs(ratio)
            if worst is None or abs(ratio) > abs(worst[1]):
                worst = (node.node_id, ratio)
    return LayoutScore(
        accepted=accepted,
        hard_violations=hard,
        area_shortfall=shortfall_total,
        relaxations=relaxations,
        worst_shortfall=worst,
    )
```

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_layout_evaluator.py -q`
Expected: `6 passed`

- [x] **Step 5: Commit**

```bash
git add backend/app/modules/generation_loop/evaluator.py backend/tests/test_layout_evaluator.py
git commit -m "Score generated buildings against the baseline program

Area shortfall is measured against the normative program, not the fitted
one, because the fit rewrites every target onto the area the room received.
Ranking is (accepted, hard violations, area shortfall, relaxations)."
```

---

### Task 2: Generation request and closed repair vocabulary

**Files:**
- Create: `backend/app/modules/generation_loop/repair.py`
- Test: `backend/tests/test_repair_proposals.py`

**Interfaces:**
- Consumes: `ExteriorAllocationRequest` (`backend/app/modules/generation_loop/contracts.py`), `ProgramGraph`, `ProgramNode`, `FloorAssignment`, `LayoutScore` (Task 1).
- Produces:
  - `GenerationRequest(floor_assignments, baseline_programs: dict[int, ProgramGraph], program_overrides: dict[int, ProgramGraph], exterior_room_ids: dict[int, tuple[str, ...]], layout_strategy: str)` with `.exterior_allocation_requests() -> tuple[ExteriorAllocationRequest, ...]`.
  - Proposals: `PrioritizeExterior(floor_index, room_id)`, `SwitchStrategy(layout_strategy)`, `RescaleTarget(floor_index, room_id, factor)`; union alias `RepairProposal`.
  - `apply_proposal(request, proposal) -> GenerationRequest` (pure).
  - `RuleRepairProposer.propose(request, score) -> RepairProposal | None`.
  - `LAYOUT_STRATEGIES = ("orthogonal", "topology")`.

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_repair_proposals.py
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
from backend.tests.test_program_form_relaxation import _graph


def _request(**overrides) -> GenerationRequest:
    base = GenerationRequest(
        floor_assignments=(FloorAssignment(1, "office"),),
        baseline_programs={1: _graph()},
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
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_repair_proposals.py -q`
Expected: `ImportError ... repair`

- [x] **Step 3: Write minimal implementation**

```python
# backend/app/modules/generation_loop/repair.py
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
        return self.program_overrides.get(floor_index, self.baseline_programs[floor_index])


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


def apply_proposal(request: GenerationRequest, proposal: RepairProposal) -> GenerationRequest:
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
                replace(node, target_area=target, min_area=target * 0.85, max_area=target * 1.15)
            )
        overrides = dict(request.program_overrides)
        overrides[proposal.floor_index] = replace(program, nodes=nodes)
        return replace(request, program_overrides=overrides)
    raise TypeError(f"unsupported proposal: {proposal!r}")


class RuleRepairProposer:
    """The always-available proposer.  Explainable, ordered, terminating."""

    def propose(self, request: GenerationRequest, score: LayoutScore) -> RepairProposal | None:
        if score.worst_shortfall is None:
            return None
        room_id, ratio = score.worst_shortfall
        if ratio <= 0:  # oversized rooms are the primary absorbing area; handled below
            return None
        floor_index = _floor_of(request, room_id)
        if room_id not in request.exterior_room_ids.get(floor_index, ()):
            return PrioritizeExterior(floor_index, room_id)
        if request.layout_strategy != "topology":
            return SwitchStrategy("topology")
        primary = next(
            (n.node_id for n in request.program_for(floor_index).nodes if n.node_id in _PRIMARY_ROOM_IDS),
            None,
        )
        if primary is None:
            return None
        already = request.program_overrides.get(floor_index)
        if already is not None:
            current = next(n for n in already.nodes if n.node_id == primary).target_area
            baseline = next(n for n in request.baseline_programs[floor_index].nodes if n.node_id == primary).target_area
            if float(current) <= float(baseline) * 0.81:  # two 0.9 steps already taken
                return None
        return RescaleTarget(floor_index, primary, 0.9)


def _floor_of(request: GenerationRequest, room_id: str) -> int:
    for floor_index, program in sorted(request.baseline_programs.items()):
        if any(node.node_id == room_id for node in program.nodes):
            return floor_index
    raise KeyError(f"room {room_id} is on no floor")
```

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_repair_proposals.py -q`
Expected: `11 passed`

- [x] **Step 5: Commit**

```bash
git add backend/app/modules/generation_loop/repair.py backend/tests/test_repair_proposals.py
git commit -m "Define the closed repair vocabulary and the rule proposer

A repair may add exterior priority, switch layout strategy, or rescale a
target within [0.5, 1.5]. It cannot touch a form gate. The rule proposer
tries those three in order for the worst-starved room and then stops."
```

---

### Task 3: The regeneration loop

**Files:**
- Create: `backend/app/modules/generation_loop/regeneration.py`
- Test: `backend/tests/test_regeneration_loop.py`

**Interfaces:**
- Consumes: `run_building_generation(mass, *, floor_assignments, program_overrides, exterior_allocation_requests, ...)` (`generation_loop/service.py:290`), `generate_program_graph(analysis, floor_index=, use_type=)`, `analyze_mass`, Task 1 `score_building`, Task 2 request/proposals.
- Produces: `RegenerationRound(round_index, proposal, proposal_source, score, error)`, `RegenerationTrace(rounds, best_round_index)`, `RegenerationOutcome(building, request, score, trace)`, and `regenerate(mass, *, proposer, max_rounds, floor_assignments=None, layout_strategy="orthogonal", generator=run_building_generation) -> RegenerationOutcome`. `proposer` has `.propose(request, score) -> RepairProposal | None` and attribute `.source: str`.

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_regeneration_loop.py
"""Generate, score, propose, regenerate; keep the best; never relax."""

import pytest

from backend.app.modules.generation_loop.evaluator import LayoutScore
from backend.app.modules.generation_loop.regeneration import regenerate
from backend.app.modules.generation_loop.repair import (
    PrioritizeExterior,
    RescaleTarget,
    RuleRepairProposer,
)


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
    from backend.tests.test_generation_loop import _long_edge_fixture_inputs
    return _long_edge_fixture_inputs()[0]


def _building(area):
    from backend.tests.test_layout_evaluator import _building as make
    return make(area)


def _score_of(outcome):
    return outcome.score


def test_a_first_round_with_no_shortfall_returns_immediately():
    generator = _ScriptedGenerator([_building(25.0)])

    outcome = regenerate(_mass(), proposer=RuleRepairProposer(), max_rounds=3,
                         generator=generator, baseline_programs_override={1: __import__("backend.tests.test_program_form_relaxation", fromlist=["_graph"])._graph()})

    assert outcome.trace.best_round_index == 0
    assert len(outcome.trace.rounds) == 1
    assert len(generator.calls) == 1


def test_the_best_round_is_kept_even_if_a_later_round_is_worse():
    from backend.tests.test_program_form_relaxation import _graph
    generator = _ScriptedGenerator([_building(19.68), _building(25.0), _building(10.0)])
    proposer = _ScriptedProposer([PrioritizeExterior(1, "restroom"), RescaleTarget(1, "restroom", 0.9)])

    outcome = regenerate(_mass(), proposer=proposer, max_rounds=3, generator=generator,
                         baseline_programs_override={1: _graph()})

    assert outcome.trace.best_round_index == 1
    assert outcome.score.area_shortfall == pytest.approx(0.0)


def test_proposals_are_applied_to_the_next_generation_call():
    from backend.tests.test_program_form_relaxation import _graph
    generator = _ScriptedGenerator([_building(19.68), _building(25.0)])
    proposer = _ScriptedProposer([PrioritizeExterior(1, "restroom")])

    regenerate(_mass(), proposer=proposer, max_rounds=2, generator=generator,
               baseline_programs_override={1: _graph()})

    second = generator.calls[1]
    assert [r.room_ids for r in second["exterior_allocation_requests"]] == [("restroom",)]


def test_a_generator_error_is_recorded_as_a_failed_round_not_raised():
    from backend.tests.test_program_form_relaxation import _graph

    def flaky(mass, **kwargs):
        if kwargs.get("exterior_allocation_requests"):
            raise ValueError("orthogonal layout cannot reserve exterior allocation for restroom")
        return _building(19.68)

    outcome = regenerate(_mass(), proposer=_ScriptedProposer([PrioritizeExterior(1, "restroom")]),
                         max_rounds=2, generator=flaky, baseline_programs_override={1: _graph()})

    assert outcome.trace.rounds[1].error.startswith("orthogonal layout cannot")
    assert outcome.trace.best_round_index == 0


def test_the_loop_stops_when_the_proposer_has_nothing_left():
    from backend.tests.test_program_form_relaxation import _graph
    generator = _ScriptedGenerator([_building(19.68), _building(19.68), _building(19.68)])

    outcome = regenerate(_mass(), proposer=_ScriptedProposer([]), max_rounds=3,
                         generator=generator, baseline_programs_override={1: _graph()})

    assert len(outcome.trace.rounds) == 1


def test_max_rounds_must_be_positive():
    with pytest.raises(ValueError):
        regenerate(_mass(), proposer=RuleRepairProposer(), max_rounds=0)
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_regeneration_loop.py -q`
Expected: `ImportError ... regeneration`

- [x] **Step 3: Write minimal implementation**

```python
# backend/app/modules/generation_loop/regeneration.py
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
    if not isinstance(max_rounds, int) or max_rounds < 1:
        raise ValueError("max_rounds must be a positive integer")
    assignments = tuple(floor_assignments) if floor_assignments is not None else assign_floors_from_use_mix(mass)
    if baseline_programs_override is not None:
        baselines = dict(baseline_programs_override)
    else:
        analysis = analyze_mass(mass)
        baselines = {
            a.floor_index: generate_program_graph(analysis, floor_index=a.floor_index, use_type=a.use_type)
            for a in assignments
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
            building = generator(
                mass,
                floor_assignments=request.floor_assignments,
                program_overrides=request.program_overrides or None,
                exterior_allocation_requests=request.exterior_allocation_requests(),
                layout_strategy=request.layout_strategy,
            )
        except (ValueError, TypeError) as error:
            rounds.append(RegenerationRound(index, proposal, source, None, str(error)))
            proposal, source = _next(proposer, request, best[0] if best else None)
            continue
        score = score_building(building, baseline_programs=request.baseline_programs)
        rounds.append(RegenerationRound(index, proposal, source, score, None))
        if best is None or score.key() < best[0].key():
            best = (score, building, request, index)
        if score.area_shortfall == 0.0 and score.hard_violations == 0 and score.relaxations == 0:
            break
        proposal, source = _next(proposer, request, score)
    if best is None:
        raise RuntimeError("every regeneration round failed: " + "; ".join(r.error or "" for r in rounds))
    score, building, request, best_index = best
    return RegenerationOutcome(
        building=building,
        request=request,
        score=score,
        trace=RegenerationTrace(rounds=tuple(rounds), best_round_index=best_index),
    )


def _next(proposer, request, score):
    if score is None:
        return None, None
    proposal = proposer.propose(request, score)
    return proposal, (getattr(proposer, "source", type(proposer).__name__) if proposal else None)
```

Note: `run_building_generation` does not yet accept `layout_strategy`; Task 10 adds it. Until then the test generator is scripted, and Task 5's wiring passes only the kwargs that exist. Add `source = "rule"` as a class attribute to `RuleRepairProposer` in `repair.py` as part of this task.

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_regeneration_loop.py backend/tests/test_repair_proposals.py -q`
Expected: `17 passed`

- [x] **Step 5: Commit**

```bash
git add backend/app/modules/generation_loop/regeneration.py backend/app/modules/generation_loop/repair.py backend/tests/test_regeneration_loop.py
git commit -m "Add the evaluate-and-regenerate loop

Each round generates, scores against the baseline program, and asks the
proposer for one repair. The best-scoring round is kept; a round that raises
is recorded, not fatal. Nothing in the loop can widen a gate."
```

---

### Task 4: Optional LLM proposer

**Files:**
- Create: `backend/app/modules/generation_loop/llm_repair.py`
- Modify: `backend/app/modules/llm_planner/openai_client.py:52-80` (`complete_json` gains `response_schema: dict | None = None`, `schema_name: str = "building_floor_assignments"`)
- Test: `backend/tests/test_llm_repair_proposer.py`

**Interfaces:**
- Consumes: `StructuredPlannerClient.complete_json(*, system_prompt, user_payload) -> str` (`llm_planner/service.py:19`), Task 2 vocabulary, Task 1 `LayoutScore`.
- Produces: `LLMRepairProposer(client, *, fallback=RuleRepairProposer())` with `.source` = `"llm"` or `"rule_fallback"` after each `.propose`, `REPAIR_PROPOSAL_SCHEMA` (strict JSON schema), `REPAIR_SYSTEM_PROMPT`.

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_llm_repair_proposer.py
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
from backend.tests.test_program_form_relaxation import _graph


class _Client:
    def __init__(self, answer):
        self.answer = answer
        self.payloads = []

    def complete_json(self, *, system_prompt, user_payload, **kwargs):
        self.payloads.append(user_payload)
        return self.answer


def _request():
    return GenerationRequest((FloorAssignment(1, "office"),), {1: _graph()})


SCORE = LayoutScore(True, 0, 0.6, 2, ("restroom", 0.6))


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
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_llm_repair_proposer.py -q`
Expected: `ImportError ... llm_repair`

- [x] **Step 3: Write minimal implementation**

```python
# backend/app/modules/generation_loop/llm_repair.py
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
        "action": {"enum": ["prioritize_exterior", "switch_strategy", "rescale_target", "none"]},
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

    def propose(self, request: GenerationRequest, score: LayoutScore) -> RepairProposal | None:
        try:
            raw = self._client.complete_json(
                system_prompt=REPAIR_SYSTEM_PROMPT,
                user_payload=_payload(request, score),
                response_schema=REPAIR_PROPOSAL_SCHEMA,
                schema_name="planm_repair_proposal",
            )
            proposal = _parse(json.loads(raw), request)
        except Exception:  # any failure of the optional path is a fallback, not an error
            self.source = "rule_fallback"
            return self._fallback.propose(request, score)
        self.source = "llm"
        return proposal


def _payload(request: GenerationRequest, score: LayoutScore) -> dict[str, Any]:
    rooms = {
        floor_index: [n.node_id for n in program.nodes]
        for floor_index, program in sorted(request.baseline_programs.items())
    }
    return {
        "accepted": score.accepted,
        "hard_violations": score.hard_violations,
        "area_shortfall": round(score.area_shortfall, 4),
        "relaxations": score.relaxations,
        "worst_shortfall": (
            {"room_id": score.worst_shortfall[0], "ratio": round(score.worst_shortfall[1], 4)}
            if score.worst_shortfall else None
        ),
        "layout_strategy": request.layout_strategy,
        "exterior_room_ids": {str(k): list(v) for k, v in request.exterior_room_ids.items()},
        "rooms_by_floor": {str(k): v for k, v in rooms.items()},
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
    if program is None or all(n.node_id != room_id for n in program.nodes):
        raise _Reject(f"no room {room_id!r} on floor {floor_index}")
```

And in `backend/app/modules/llm_planner/openai_client.py`, change the signature and the schema block:

```python
    def complete_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_schema: dict[str, Any] | None = None,
        schema_name: str = "building_floor_assignments",
    ) -> str:
        ...
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": response_schema or FLOOR_ASSIGNMENT_SCHEMA,
                }
            },
```

Also widen the `StructuredPlannerClient` protocol in `llm_planner/service.py:19-25` to accept `**kwargs: Any` so existing fakes keep working.

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_llm_repair_proposer.py backend/tests/test_llm_planner*.py -q`
Expected: all pass (the existing llm_planner tests must be unaffected by the kwargs widening).

- [x] **Step 5: Commit**

```bash
git add backend/app/modules/generation_loop/llm_repair.py backend/app/modules/llm_planner/openai_client.py backend/app/modules/llm_planner/service.py backend/tests/test_llm_repair_proposer.py
git commit -m "Let an LLM propose repairs inside the closed vocabulary

The model sees the score and the allowed actions, answers in a strict
schema, and the engine applies and re-validates. Anything outside the
vocabulary falls back to the rule proposer and is recorded as such."
```

---

### Task 5: Wire the loop into the PLANM alternatives stage and the plans tool

**Files:**
- Modify: `backend/app/modules/planm_execution/service.py:191-243` (`alternatives`)
- Modify: `backend/tools/regenerate_plans.py`
- Test: `backend/tests/test_planm_execution_regeneration.py`

**Interfaces:**
- Consumes: Task 3 `regenerate`, Task 2 `RuleRepairProposer`, Task 4 `LLMRepairProposer`, `agents/planm/config/default.yaml` `planm.maximum_stage_attempts` (currently `3`).
- Produces: `alternatives.json` gains `"regeneration": {"rounds": [...], "best_round_index": int, "proposer": "rule"|"llm"}`; `regenerate_plans` gains `--rounds N` (default 3) and `--llm` (uses `OpenAIResponsesPlannerClient`, requires `OPENAI_API_KEY`); `report.json` gains the same `regeneration` block and a top-level `score`.

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_planm_execution_regeneration.py
"""The alternatives stage runs the loop and reports every round."""

import json
from pathlib import Path

from backend.app.modules.planm_execution.service import alternatives_regeneration_block


def test_trace_is_serialised_with_every_round_and_the_winner():
    from backend.app.modules.generation_loop.evaluator import LayoutScore
    from backend.app.modules.generation_loop.regeneration import RegenerationRound, RegenerationTrace
    from backend.app.modules.generation_loop.repair import PrioritizeExterior

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
    assert block["rounds"][1]["proposal"] == {"action": "prioritize_exterior", "floor_index": 1, "room_id": "meeting"}
    assert block["rounds"][1]["score"]["area_shortfall"] == 0.1
    assert block["rounds"][2]["error"] == "seed area exceeds bound"
    json.dumps(block)  # must be plain JSON
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_planm_execution_regeneration.py -q`
Expected: `ImportError: cannot import name 'alternatives_regeneration_block'`

- [x] **Step 3: Write minimal implementation**

Add to `backend/app/modules/planm_execution/service.py` (module level, near `_result`):

```python
def alternatives_regeneration_block(trace, *, proposer_name: str) -> dict:
    """Plain-JSON view of a RegenerationTrace for alternatives.json."""
    from dataclasses import asdict, is_dataclass

    def proposal_json(proposal):
        if proposal is None:
            return None
        payload = asdict(proposal)
        payload["action"] = {
            "PrioritizeExterior": "prioritize_exterior",
            "SwitchStrategy": "switch_strategy",
            "RescaleTarget": "rescale_target",
        }[type(proposal).__name__]
        return payload

    def score_json(score):
        if score is None:
            return None
        return {
            "accepted": score.accepted,
            "hard_violations": score.hard_violations,
            "area_shortfall": round(score.area_shortfall, 4),
            "relaxations": score.relaxations,
            "worst_shortfall": (
                {"room_id": score.worst_shortfall[0], "ratio": round(score.worst_shortfall[1], 4)}
                if score.worst_shortfall else None
            ),
        }

    return {
        "proposer": proposer_name,
        "best_round_index": trace.best_round_index,
        "rounds": [
            {
                "round_index": r.round_index,
                "proposal": proposal_json(r.proposal),
                "proposal_source": r.proposal_source,
                "score": score_json(r.score),
                "error": r.error,
            }
            for r in trace.rounds
        ],
    }
```

Then in `alternatives(...)`, after `generated = run_building_alternatives(mass)` (line 195), add the loop for the **best accepted alternative's building** so both products exist side by side (alternatives are still produced by the composer; the loop refines the winner and its trace is published):

```python
    from backend.app.modules.generation_loop.regeneration import regenerate
    from backend.app.modules.generation_loop.repair import RuleRepairProposer
    max_rounds = int(_config_value("maximum_stage_attempts", default=3))
    regeneration = regenerate(mass, proposer=RuleRepairProposer(), max_rounds=max_rounds)
    regeneration_block = alternatives_regeneration_block(regeneration.trace, proposer_name="rule")
```

and include `"regeneration": regeneration_block` in the `summary` dict. Add `_config_value(key, *, default)` that reads `agents/planm/config/default.yaml` via `yaml.safe_load` (pyyaml is already a dependency) from `PRODUCT_ROOT / "agents" / "planm" / "config" / "default.yaml"`, returning `default` if the file or key is missing.

In `backend/tools/regenerate_plans.py`: add `--rounds` (int, default 3) and `--llm` (store_true); build `proposer = LLMRepairProposer(OpenAIResponsesPlannerClient()) if args.llm else RuleRepairProposer()`; call `regenerate(mass, proposer=proposer, max_rounds=args.rounds)`; render the outcome building into `run_dir / "regenerated"` with `create_building_visual_review_artifacts`; write `report["regeneration"] = alternatives_regeneration_block(outcome.trace, proposer_name=proposer.source if hasattr(proposer, "source") else "rule")` and `report["score"]` from `outcome.score` (same shape as `score_json`).

- [x] **Step 4: Run tests and the metric gate**

Run: `python -m pytest backend/tests/test_planm_execution_regeneration.py backend/tests/test_planm_bridge.py -q`
Expected: pass.
Run: `python -m backend.tools.regenerate_plans --label task5-loop`
Expected: a `regenerated/` folder with 3 PNGs and `report.json["regeneration"]["rounds"]` with ≥ 1 round; `report.json["score"]["area_shortfall"]` **≤** the round-0 score (the loop never returns something worse than its first round).

- [x] **Step 5: Full suite, then commit**

Run: `python -m pytest backend/tests -q` → expected `≥ 1034 passed, 0 failed`.

```bash
git add backend/app/modules/planm_execution/service.py backend/tools/regenerate_plans.py backend/tests/test_planm_execution_regeneration.py
git commit -m "Run the regeneration loop in the PLANM alternatives stage

Rounds are bounded by planm.maximum_stage_attempts and every round --
proposal, source, score, error -- is written to alternatives.json. The
plans tool gains --rounds and --llm and renders the regenerated winner."
```

---

### Task 6: Adjacency graph with spanning circulation

**Files:**
- Create: `backend/app/modules/topology_planner/__init__.py` (empty)
- Create: `backend/app/modules/topology_planner/graph.py`
- Test: `backend/tests/test_topology_graph.py`

**Interfaces:**
- Consumes: `ProgramGraph.nodes` (`ProgramNode.node_id`, `.space_type`, `.zone`), `ProgramGraph.edges` (`ProgramEdge.source/target/relation`; relations `service_adjacent`, `functional_adjacency`, `public_access`).
- Produces: `AdjacencyGraph(nodes: tuple[str,...], required: frozenset[frozenset[str]], soft: frozenset[frozenset[str]])`, `CORRIDOR = "corridor"`, `build_adjacency_graph(program) -> AdjacencyGraph`, `AdjacencyGraph.missing_required(pairs_present: Iterable[tuple[str,str]]) -> tuple[tuple[str,str],...]`.

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_topology_graph.py
"""Topology first: which rooms must touch which, before any coordinates.

Spanning circulation (Shiksha et al. 2025) means every room opens directly
onto the corridor.  service_adjacent program edges are hard; functional ones
are soft.
"""

from backend.app.modules.topology_planner.graph import CORRIDOR, build_adjacency_graph
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.schemas.mass import MassAnalysis


def _office():
    analysis = MassAnalysis(project_id="t", area=900, floor_area=900, floors=1,
                            edge_count=4, street_edge_indices=[0], access_edge_indices=[0],
                            bounds=(0, 0, 37, 26))
    return generate_program_graph(analysis, floor_index=1, use_type="office")


def test_every_non_core_room_must_touch_the_corridor():
    graph = build_adjacency_graph(_office())

    for room in graph.nodes:
        if room in (CORRIDOR, "core"):
            continue
        assert frozenset({room, CORRIDOR}) in graph.required, room


def test_core_touches_the_corridor_and_the_restroom_touches_the_core():
    graph = build_adjacency_graph(_office())

    assert frozenset({"core", CORRIDOR}) in graph.required
    assert frozenset({"restroom", "core"}) in graph.required


def test_functional_adjacency_is_soft():
    graph = build_adjacency_graph(_office())

    assert frozenset({"open_work", "meeting"}) in graph.soft
    assert frozenset({"open_work", "meeting"}) not in graph.required


def test_missing_required_reports_exactly_what_is_absent():
    graph = build_adjacency_graph(_office())
    present = [(room, CORRIDOR) for room in graph.nodes if room not in (CORRIDOR,)]
    present.remove(("restroom", CORRIDOR))

    missing = graph.missing_required(present)

    assert ("restroom", CORRIDOR) in {tuple(sorted(p)) for p in missing}
    assert ("restroom", "core") in {tuple(sorted(p)) for p in missing}
    assert len(missing) == 2
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_topology_graph.py -q`
Expected: `ModuleNotFoundError: backend.app.modules.topology_planner`

- [x] **Step 3: Write minimal implementation**

```python
# backend/app/modules/topology_planner/graph.py
"""The adjacency graph a floor has to satisfy, decided before geometry.

GFLAN (2026) and the AI EDAM circulation paper (2025) both fix topology --
which rooms touch which, and that every room reaches the corridor -- before
placing anything.  The corridor is a node here, not a rectangle drawn first.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from backend.app.schemas.program import ProgramGraph


CORRIDOR = "corridor"
_HARD_RELATIONS = frozenset({"service_adjacent"})
_SOFT_RELATIONS = frozenset({"functional_adjacency"})


@dataclass(frozen=True)
class AdjacencyGraph:
    nodes: tuple[str, ...]
    required: frozenset[frozenset[str]]
    soft: frozenset[frozenset[str]]

    def missing_required(self, pairs_present: Iterable[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
        present = {frozenset(pair) for pair in pairs_present}
        return tuple(
            tuple(sorted(pair)) for pair in sorted(self.required, key=lambda p: tuple(sorted(p)))
            if pair not in present
        )


def build_adjacency_graph(program: ProgramGraph) -> AdjacencyGraph:
    room_ids = tuple(node.node_id for node in program.nodes)
    required: set[frozenset[str]] = set()
    soft: set[frozenset[str]] = set()
    for room in room_ids:
        # Spanning circulation: every room, the core included, opens onto the corridor.
        required.add(frozenset({room, CORRIDOR}))
    known = set(room_ids)
    for edge in program.edges:
        if edge.source not in known or edge.target not in known:
            continue  # "street" and other external endpoints are not rooms
        pair = frozenset({edge.source, edge.target})
        if edge.relation in _HARD_RELATIONS:
            required.add(pair)
        elif edge.relation in _SOFT_RELATIONS:
            soft.add(pair)
    return AdjacencyGraph(
        nodes=(*room_ids, CORRIDOR),
        required=frozenset(required),
        soft=frozenset(soft - required),
    )
```

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_topology_graph.py -q`
Expected: `4 passed`

- [x] **Step 5: Commit**

```bash
git add backend/app/modules/topology_planner/ backend/tests/test_topology_graph.py
git commit -m "Build the adjacency graph a floor must satisfy before geometry

Every room must open onto the corridor (spanning circulation) and
service_adjacent program edges are hard; functional adjacency is soft."
```

---

### Task 7: Slicing plan — double-loaded spine, zone-driven bands

**Files:**
- Create: `backend/app/modules/topology_planner/slicing.py`
- Test: `backend/tests/test_topology_slicing.py`

**Interfaces:**
- Consumes: plate bounds `(min_x, min_y, max_x, max_y)`, core polygon bounds, `ProgramGraph` nodes with `.zone` (`workplace|public|service|core|frontage`), corridor width (default `1.6`).
- Produces: `Band(name: str, x0, y0, x1, y1, room_ids: tuple[str,...])`, `SlicingPlan(spine: tuple[float,float,float,float], bands: tuple[Band, Band], axis: str)`, `plan_double_loaded_spine(bounds, *, core_bounds, program, corridor_width=1.6) -> SlicingPlan`.

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_topology_slicing.py
"""Where rooms go relative to the spine is decided by zone, not by which cell
happened to touch a corridor.  A double-loaded spine halves each room's depth:
25 m2 off a 9.3 m band is a 3.46 slab; off a 4.05 m band it is 1.52."""

import pytest

from backend.app.modules.topology_planner.slicing import plan_double_loaded_spine
from backend.tests.test_topology_graph import _office


BOUNDS = (0.0, 0.0, 37.0, 26.0)
CORE = (14.0, 18.0, 22.0, 26.0)  # rear-centre core


def test_the_spine_runs_along_the_long_axis_and_touches_the_core():
    plan = plan_double_loaded_spine(BOUNDS, core_bounds=CORE, program=_office())

    x0, y0, x1, y1 = plan.spine
    assert plan.axis == "x"
    assert (x1 - x0) == pytest.approx(37.0) and (y1 - y0) == pytest.approx(1.6)
    assert y1 == pytest.approx(18.0)  # spine's far edge is the core's near edge


def test_bands_sit_on_both_sides_of_the_spine_and_tile_the_plate_depth():
    plan = plan_double_loaded_spine(BOUNDS, core_bounds=CORE, program=_office())

    near, far = plan.bands
    assert near.y1 == pytest.approx(plan.spine[1]) and near.y0 == pytest.approx(0.0)
    assert far.y0 == pytest.approx(plan.spine[3]) and far.y1 == pytest.approx(26.0)


def test_service_rooms_share_the_core_side_and_public_rooms_the_other():
    plan = plan_double_loaded_spine(BOUNDS, core_bounds=CORE, program=_office())
    core_side = next(b for b in plan.bands if b.y0 == pytest.approx(18.0))
    other = next(b for b in plan.bands if b is not core_side)

    assert {"restroom", "pantry", "it_storage"} <= set(core_side.room_ids)
    assert {"meeting", "reception"} <= set(other.room_ids)


def test_the_primary_room_is_present_in_both_bands_as_the_residual():
    plan = plan_double_loaded_spine(BOUNDS, core_bounds=CORE, program=_office())

    assert all("open_work" in band.room_ids for band in plan.bands)


def test_the_core_is_not_a_band_room():
    plan = plan_double_loaded_spine(BOUNDS, core_bounds=CORE, program=_office())

    assert all("core" not in band.room_ids for band in plan.bands)


def test_a_core_not_on_the_plate_edge_is_rejected():
    with pytest.raises(ValueError, match="core"):
        plan_double_loaded_spine(BOUNDS, core_bounds=(14.0, 10.0, 22.0, 18.0), program=_office())
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_topology_slicing.py -q`
Expected: `ImportError ... slicing`

- [x] **Step 3: Write minimal implementation**

```python
# backend/app/modules/topology_planner/slicing.py
"""The topology decision: a spine and two bands, rooms assigned by zone.

Nothing here has room widths.  It says which side of the corridor each room
is on and that the corridor runs the length of the plate, which is the
double-loaded arrangement that halves every room's depth.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.schemas.program import ProgramGraph


_PRIMARY = frozenset({"open_work", "sales"})
_CORE_SIDE_ZONES = frozenset({"service", "core"})
_TOLERANCE = 1e-6


@dataclass(frozen=True)
class Band:
    name: str
    x0: float
    y0: float
    x1: float
    y1: float
    room_ids: tuple[str, ...]

    @property
    def length(self) -> float:
        return self.x1 - self.x0

    @property
    def depth(self) -> float:
        return self.y1 - self.y0


@dataclass(frozen=True)
class SlicingPlan:
    spine: tuple[float, float, float, float]
    bands: tuple[Band, Band]
    axis: str


def plan_double_loaded_spine(
    bounds: tuple[float, float, float, float],
    *,
    core_bounds: tuple[float, float, float, float],
    program: ProgramGraph,
    corridor_width: float = 1.6,
) -> SlicingPlan:
    min_x, min_y, max_x, max_y = bounds
    cx0, cy0, cx1, cy1 = core_bounds
    width, depth = max_x - min_x, max_y - min_y
    if width < depth:
        raise ValueError("double-loaded spine expects the plate's long axis along x")
    if abs(cy1 - max_y) > _TOLERANCE and abs(cy0 - min_y) > _TOLERANCE:
        raise ValueError("core must sit on the plate's rear or front edge")
    core_at_rear = abs(cy1 - max_y) <= _TOLERANCE
    # The spine hugs the core's inner edge so the core opens onto it.
    spine_y1 = cy0 if core_at_rear else cy1 + corridor_width
    spine_y0 = spine_y1 - corridor_width
    spine = (min_x, spine_y0, max_x, spine_y1)

    rooms = [n for n in program.nodes if n.space_type != "core"]
    primary = tuple(n.node_id for n in rooms if n.node_id in _PRIMARY)
    core_side_ids = tuple(n.node_id for n in rooms if (n.zone or "") in _CORE_SIDE_ZONES and n.node_id not in _PRIMARY)
    other_ids = tuple(n.node_id for n in rooms if n.node_id not in core_side_ids and n.node_id not in _PRIMARY)

    core_band = Band("core_side", min_x, spine_y1, max_x, max_y, (*core_side_ids, *primary)) if core_at_rear \
        else Band("core_side", min_x, min_y, max_x, spine_y0, (*core_side_ids, *primary))
    other_band = Band("street_side", min_x, min_y, max_x, spine_y0, (*other_ids, *primary)) if core_at_rear \
        else Band("street_side", min_x, spine_y1, max_x, max_y, (*other_ids, *primary))
    return SlicingPlan(spine=spine, bands=(other_band, core_band), axis="x")
```

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_topology_slicing.py -q`
Expected: `6 passed`

- [x] **Step 5: Commit**

```bash
git add backend/app/modules/topology_planner/slicing.py backend/tests/test_topology_slicing.py
git commit -m "Plan a double-loaded spine with rooms assigned to bands by zone

Service rooms share the core's side, public rooms the other, and the
primary room is the residual on both. No coordinates for rooms yet."
```

---

### Task 8: LP dimensioning of a band

**Files:**
- Create: `backend/app/modules/topology_planner/dimensioning.py`
- Modify: `pyproject.toml:10-19` (add `"scipy>=1.17,<2",`)
- Test: `backend/tests/test_topology_dimensioning.py`

**Interfaces:**
- Consumes: `Band` (Task 7), `ProgramNode` fields `target_area, min_area, max_area, min_width, max_aspect_ratio`.
- Produces: `RoomWidth(room_id, width)`, `TopologyInfeasible(ValueError)` with `.constraints: tuple[str,...]`, `dimension_band(band, nodes: Sequence[ProgramNode], *, residual_room_id: str | None) -> tuple[RoomWidth, ...]`.

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_topology_dimensioning.py
"""Widths come from a linear program with the gates as constraints.

Shekhawat et al. (1910.00081): given adjacencies, dimension the rooms by LP
with minimum width and aspect range per room. Infeasible means the band and
the program disagree and the caller must change one of them -- the LP never
widens a gate to make itself feasible."""

import pytest

from backend.app.modules.topology_planner.dimensioning import (
    TopologyInfeasible,
    dimension_band,
)
from backend.app.modules.topology_planner.slicing import Band
from backend.app.schemas.program import ProgramNode


def _node(node_id, target, *, min_width=1.8, aspect=2.5):
    return ProgramNode(node_id=node_id, space_type=node_id, target_area=target,
                       min_area=target * 0.85, max_area=target * 1.15,
                       min_width=min_width, max_aspect_ratio=aspect)


BAND = Band("b", 0.0, 0.0, 37.0, 4.05, ("restroom", "pantry", "open_work"))


def test_widths_realise_targets_within_the_gates():
    widths = dimension_band(BAND, [_node("restroom", 25.0), _node("pantry", 27.0, aspect=2.0),
                                   _node("open_work", 300.0, min_width=6.0)],
                            residual_room_id="open_work")
    by_id = {w.room_id: w.width for w in widths}

    assert by_id["restroom"] * BAND.depth == pytest.approx(25.0, rel=0.02)
    assert max(by_id["restroom"] / BAND.depth, BAND.depth / by_id["restroom"]) <= 2.5
    assert by_id["pantry"] * BAND.depth == pytest.approx(27.0, rel=0.02)
    assert sum(by_id.values()) == pytest.approx(BAND.length)


def test_the_residual_room_absorbs_the_rest_of_the_band():
    widths = dimension_band(BAND, [_node("restroom", 25.0), _node("open_work", 300.0, min_width=6.0)],
                            residual_room_id="open_work")
    by_id = {w.room_id: w.width for w in widths}

    assert by_id["open_work"] == pytest.approx(BAND.length - by_id["restroom"])


def test_an_aspect_limit_that_the_band_depth_cannot_meet_is_infeasible_not_relaxed():
    # 25 m2 at depth 4.05 needs width 6.17 -> aspect 1.52. Demand 1.2 instead.
    with pytest.raises(TopologyInfeasible) as info:
        dimension_band(BAND, [_node("restroom", 25.0, aspect=1.2), _node("open_work", 300.0, min_width=6.0)],
                       residual_room_id="open_work")

    assert any("restroom" in c and "aspect" in c for c in info.value.constraints)


def test_a_band_too_short_for_the_program_is_infeasible():
    short = Band("s", 0.0, 0.0, 8.0, 4.05, ("restroom", "pantry"))

    with pytest.raises(TopologyInfeasible):
        dimension_band(short, [_node("restroom", 25.0), _node("pantry", 27.0)], residual_room_id=None)


def test_dimensioning_is_deterministic():
    nodes = [_node("restroom", 25.0), _node("pantry", 27.0, aspect=2.0), _node("open_work", 300.0, min_width=6.0)]

    first = dimension_band(BAND, nodes, residual_room_id="open_work")
    second = dimension_band(BAND, nodes, residual_room_id="open_work")

    assert first == second


def test_the_single_loaded_slab_the_lp_replaces_would_have_failed():
    """The closed form: aspect = depth^2 / area. 9.3 m band, 25 m2 -> 3.46 > 2.5."""
    deep = Band("d", 0.0, 0.0, 37.0, 9.3, ("restroom", "open_work"))

    with pytest.raises(TopologyInfeasible):
        dimension_band(deep, [_node("restroom", 25.0), _node("open_work", 300.0, min_width=6.0)],
                       residual_room_id="open_work")
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_topology_dimensioning.py -q`
Expected: `ImportError ... dimensioning`

- [x] **Step 3: Write minimal implementation**

Add `"scipy>=1.17,<2",` to `pyproject.toml` dependencies (alphabetically after `pyyaml`). Then:

```python
# backend/app/modules/topology_planner/dimensioning.py
"""Room widths along a band from a linear program.

Per room i in a band of fixed depth d:
    min_area_i <= w_i * d <= max_area_i
    w_i >= min_width_i
    d / r_i <= w_i <= r_i * d          (aspect ratio <= r_i, both orientations)
    sum w_i (+ residual) == band length
minimising sum |w_i * d - target_i| through slack variables.  The residual room,
if any, takes whatever length remains and is bounded only by its min_width.
Infeasibility is reported with the offending constraints and is the caller's
problem to solve by changing the band or the program -- never by widening a
gate here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math

import numpy as np
from scipy.optimize import linprog

from backend.app.modules.topology_planner.slicing import Band
from backend.app.schemas.program import ProgramNode


_EPS = 1e-9


class TopologyInfeasible(ValueError):
    def __init__(self, constraints: Sequence[str]) -> None:
        self.constraints = tuple(constraints)
        super().__init__("band cannot be dimensioned: " + "; ".join(self.constraints))


@dataclass(frozen=True)
class RoomWidth:
    room_id: str
    width: float


def dimension_band(
    band: Band,
    nodes: Sequence[ProgramNode],
    *,
    residual_room_id: str | None,
) -> tuple[RoomWidth, ...]:
    d = band.depth
    fixed = [n for n in nodes if n.node_id != residual_room_id]
    residual = next((n for n in nodes if n.node_id == residual_room_id), None)
    n = len(fixed)
    # Variables: w_0..w_{n-1}, s_0..s_{n-1} (|w_i d - t_i| <= s_i), w_res
    has_res = residual is not None
    m = 2 * n + (1 if has_res else 0)
    c = np.zeros(m)
    c[n:2 * n] = 1.0  # minimise total absolute deviation
    bounds = []
    labels: list[str] = []
    for i, node in enumerate(fixed):
        lo, hi = _width_bounds(node, d, labels)
        bounds.append((lo, hi))
    bounds.extend([(0.0, None)] * n)
    if has_res:
        bounds.append((float(residual.min_width or 0.0), None))
    # |w_i d - t_i| <= s_i  ->  w_i d - s_i <= t_i  and  -w_i d - s_i <= -t_i
    a_ub, b_ub = [], []
    for i, node in enumerate(fixed):
        t = float(node.target_area)
        row = np.zeros(m); row[i] = d; row[n + i] = -1.0; a_ub.append(row); b_ub.append(t)
        row = np.zeros(m); row[i] = -d; row[n + i] = -1.0; a_ub.append(row); b_ub.append(-t)
    # Sum of widths == band length (with residual) or <= band length (without)
    row = np.zeros(m); row[:n] = 1.0
    if has_res:
        row[-1] = 1.0
        a_eq, b_eq = [row], [band.length]
        a_ub_final, b_ub_final = (np.array(a_ub), np.array(b_ub)) if a_ub else (None, None)
    else:
        a_ub.append(row); b_ub.append(band.length)
        a_eq, b_eq = None, None
        a_ub_final, b_ub_final = np.array(a_ub), np.array(b_ub)
    for lo, hi in bounds[:n]:
        if hi is not None and lo > hi + _EPS:
            raise TopologyInfeasible(labels or ["contradictory width bounds"])
    result = linprog(c, A_ub=a_ub_final, b_ub=b_ub_final, A_eq=a_eq, b_eq=b_eq,
                     bounds=bounds, method="highs")
    if not result.success:
        raise TopologyInfeasible(labels + [f"band length {band.length:.2f} m cannot hold the program: {result.message}"])
    widths = [RoomWidth(node.node_id, float(round(result.x[i], 6))) for i, node in enumerate(fixed)]
    if has_res:
        widths.append(RoomWidth(residual.node_id, float(round(result.x[-1], 6))))
    return tuple(widths)


def _width_bounds(node: ProgramNode, d: float, labels: list[str]) -> tuple[float, float | None]:
    target = float(node.target_area)
    min_area = float(node.min_area) if node.min_area else target * 0.85
    max_area = float(node.max_area) if node.max_area else target * 1.15
    lo = max(min_area / d, float(node.min_width or 0.0))
    hi: float | None = max_area / d
    r = float(node.max_aspect_ratio) if node.max_aspect_ratio else math.inf
    if math.isfinite(r):
        lo = max(lo, d / r)
        hi = min(hi, r * d)
        if lo > hi + _EPS:
            labels.append(
                f"{node.node_id}: aspect <= {r:g} at depth {d:.2f} m needs width in "
                f"[{d / r:.2f}, {r * d:.2f}] but area band needs [{min_area / d:.2f}, {max_area / d:.2f}]"
            )
    if float(node.min_width or 0.0) > (hi if hi is not None else math.inf) + _EPS:
        labels.append(f"{node.node_id}: min width {float(node.min_width):.2f} m exceeds max width {hi:.2f} m")
    return lo, hi
```

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_topology_dimensioning.py -q`
Expected: `6 passed`

- [x] **Step 5: Commit**

```bash
git add backend/app/modules/topology_planner/dimensioning.py backend/tests/test_topology_dimensioning.py pyproject.toml
git commit -m "Dimension band rooms with a linear program under the form gates

Widths satisfy area band, min width and aspect limit simultaneously;
infeasibility names the constraint and is never resolved by widening it."
```

---

### Task 9: Topology layout generator → `LayoutCandidate`

**Files:**
- Create: `backend/app/modules/topology_planner/service.py`
- Test: `backend/tests/test_topology_layout.py`

**Interfaces:**
- Consumes: Tasks 6–8; `LayoutCandidate(candidate_id, project_id, floor_index, rooms, circulation, score, openings=[])`, `RoomPolygon(room_id, space_type, polygon)` (`backend/app/schemas/layout.py:220-236`); `CirculationCandidate.polygons` optional.
- Produces: `generate_topology_layout(boundary, program, *, core_polygon, corridor_width=1.6) -> LayoutCandidate` whose `circulation` is one `RoomPolygon("corridor", "circulation", spine)`; raises `TopologyInfeasible` or `ValueError("missing required adjacency: ...")`.

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_topology_layout.py
"""The whole chain: graph -> slicing -> LP -> polygons, verified against the graph."""

import pytest
from shapely.geometry import Polygon

from backend.app.modules.topology_planner.dimensioning import TopologyInfeasible
from backend.app.modules.topology_planner.service import generate_topology_layout
from backend.engine.geometry import orthogonal_min_width, shared_boundary_segments
from backend.tests.test_topology_graph import _office


BOUNDARY = [(0.0, 0.0), (37.0, 0.0), (37.0, 26.0), (0.0, 26.0)]
CORE = [(14.0, 18.0), (22.0, 18.0), (22.0, 26.0), (14.0, 26.0)]


def _aspect(polygon):
    xs = [x for x, _ in polygon]; ys = [y for _, y in polygon]
    w, d = max(xs) - min(xs), max(ys) - min(ys)
    return max(w / d, d / w)


def test_every_room_meets_its_gates_with_no_relaxation():
    layout = generate_topology_layout(BOUNDARY, _office(), core_polygon=CORE)
    nodes = {n.node_id: n for n in _office().nodes}

    for room in layout.rooms:
        node = nodes[room.room_id]
        if node.max_aspect_ratio is not None:
            assert _aspect(room.polygon) <= node.max_aspect_ratio + 1e-6, room.room_id
        if node.min_width is not None:
            assert orthogonal_min_width(room.polygon) >= node.min_width - 1e-6, room.room_id


def test_every_room_shares_a_door_width_with_the_corridor():
    layout = generate_topology_layout(BOUNDARY, _office(), core_polygon=CORE)
    corridor = layout.circulation[0].polygon

    for room in layout.rooms:
        shared = shared_boundary_segments(room.polygon, corridor)
        assert any(((a[0]-b[0])**2 + (a[1]-b[1])**2) ** 0.5 >= 0.9 for a, b in shared), room.room_id


def test_the_restroom_touches_the_core():
    layout = generate_topology_layout(BOUNDARY, _office(), core_polygon=CORE)
    rest = next(r.polygon for r in layout.rooms if r.room_id == "restroom")
    core = next(r.polygon for r in layout.rooms if r.room_id == "core")

    assert Polygon(rest).buffer(1e-6).intersects(Polygon(core))


def test_rooms_and_corridor_tile_the_plate_without_overlap():
    layout = generate_topology_layout(BOUNDARY, _office(), core_polygon=CORE)
    parts = [Polygon(r.polygon) for r in layout.rooms] + [Polygon(c.polygon) for c in layout.circulation]

    assert sum(p.area for p in parts) == pytest.approx(37.0 * 26.0, rel=1e-6)
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            assert a.intersection(b).area < 1e-6


def test_restroom_area_is_its_normative_target_not_a_slab():
    layout = generate_topology_layout(BOUNDARY, _office(), core_polygon=CORE)
    rest = next(r for r in layout.rooms if r.room_id == "restroom")
    target = next(n.target_area for n in _office().nodes if n.node_id == "restroom")

    assert Polygon(rest.polygon).area == pytest.approx(target, rel=0.02)
    assert _aspect(rest.polygon) < 2.0


def test_an_impossible_program_raises_instead_of_relaxing():
    from dataclasses import replace
    program = _office()
    tight = replace(program, nodes=[replace(n, max_aspect_ratio=1.01) if n.node_id == "restroom" else n
                                    for n in program.nodes])

    with pytest.raises(TopologyInfeasible):
        generate_topology_layout(BOUNDARY, tight, core_polygon=CORE)
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_topology_layout.py -q`
Expected: `ImportError ... topology_planner.service`

- [x] **Step 3: Write minimal implementation**

```python
# backend/app/modules/topology_planner/service.py
"""Topology-first layout: graph -> slicing plan -> LP widths -> polygons.

The result is checked against the adjacency graph it was built from.  A room
that does not reach the corridor, or a restroom that does not touch the core,
is a bug here and raises; it is not a metric to be averaged away.
"""

from __future__ import annotations

from collections.abc import Iterable

from shapely.geometry import Polygon

from backend.app.modules.topology_planner.dimensioning import dimension_band
from backend.app.modules.topology_planner.graph import CORRIDOR, build_adjacency_graph
from backend.app.modules.topology_planner.slicing import Band, plan_double_loaded_spine
from backend.app.schemas.layout import LayoutCandidate, Point, RoomPolygon
from backend.app.schemas.program import ProgramGraph


_PRIMARY = frozenset({"open_work", "sales"})
_DOOR = 0.9
_EPS = 1e-6


def generate_topology_layout(
    boundary: Iterable[Point],
    program: ProgramGraph,
    *,
    core_polygon: Iterable[Point],
    corridor_width: float = 1.6,
) -> LayoutCandidate:
    plate = Polygon(list(boundary))
    core = Polygon(list(core_polygon))
    graph = build_adjacency_graph(program)
    plan = plan_double_loaded_spine(plate.bounds, core_bounds=core.bounds, program=program, corridor_width=corridor_width)
    nodes = {n.node_id: n for n in program.nodes}
    core_node = next(n for n in program.nodes if n.space_type == "core")

    rooms: list[RoomPolygon] = [RoomPolygon(core_node.node_id, core_node.space_type, list(core.exterior.coords)[:-1])]
    # Split the primary room's target across the two bands by band area share.
    primary_id = next((n.node_id for n in program.nodes if n.node_id in _PRIMARY), None)
    for band in plan.bands:
        usable = _band_minus_core(band, core)
        band_nodes = [nodes[r] for r in band.room_ids]
        widths = dimension_band(usable, band_nodes, residual_room_id=primary_id)
        # Lay rooms along x from the band's left edge; the core-side band starts after the core if the core sits inside it.
        x = usable.x0
        for w in widths:
            node = nodes[w.room_id]
            ring = [(x, usable.y0), (x + w.width, usable.y0), (x + w.width, usable.y1), (x, usable.y1)]
            rooms.append(RoomPolygon(node.node_id if node.node_id != primary_id else f"{primary_id}::{band.name}",
                                     node.space_type, ring))
            x += w.width
    rooms = _merge_primary(rooms, primary_id)
    sx0, sy0, sx1, sy1 = plan.spine
    corridor = RoomPolygon(CORRIDOR, "circulation", [(sx0, sy0), (sx1, sy0), (sx1, sy1), (sx0, sy1)])

    _verify_adjacency(graph, rooms, corridor)
    return LayoutCandidate(
        candidate_id=f"{program.project_id}-f{program.floor_index}-topology",
        project_id=program.project_id,
        floor_index=program.floor_index,
        rooms=rooms,
        circulation=[corridor],
        score=0.0,
    )


def _band_minus_core(band: Band, core: Polygon) -> Band:
    """The core occupies part of its band; rooms take what is left, to the core's left.

    The core-side band's usable length is reduced by the core's width, and the
    restroom is placed first so it lands against the core (service_adjacent)."""
    cx0, _, cx1, _ = core.bounds
    if band.y0 <= core.bounds[1] + _EPS and core.bounds[3] <= band.y1 + _EPS:
        ordered = tuple(sorted(band.room_ids, key=lambda r: (r != "restroom", r)))
        # rooms run from band.x0 to cx0 (left of core); the remainder to the right of the core
        # is folded into the residual by the LP through the reduced length.
        return Band(band.name, band.x0, band.y0, band.x1 - (cx1 - cx0), band.y1, ordered)
    return band


def _merge_primary(rooms: list[RoomPolygon], primary_id: str | None) -> list[RoomPolygon]:
    if primary_id is None:
        return rooms
    from shapely.ops import unary_union
    parts = [Polygon(r.polygon) for r in rooms if r.room_id.startswith(f"{primary_id}::")]
    others = [r for r in rooms if not r.room_id.startswith(f"{primary_id}::")]
    if not parts:
        return rooms
    merged = unary_union(parts)
    # Two disjoint bands stay two polygons; keep them as one room id per band for the validator.
    if merged.geom_type == "Polygon":
        return others + [RoomPolygon(primary_id, "open_work", list(merged.exterior.coords)[:-1])]
    return others + [RoomPolygon(primary_id if i == 0 else f"{primary_id}_{i}", "open_work", list(g.exterior.coords)[:-1])
                     for i, g in enumerate(merged.geoms)]


def _verify_adjacency(graph, rooms: list[RoomPolygon], corridor: RoomPolygon) -> None:
    from backend.engine.geometry import shared_boundary_segments

    present: list[tuple[str, str]] = []
    polys = {r.room_id.split("_")[0] if r.room_id.startswith("open_work_") else r.room_id: Polygon(r.polygon) for r in rooms}
    corridor_poly = Polygon(corridor.polygon)
    for room_id, poly in polys.items():
        if _shares_door(poly, corridor_poly):
            present.append((room_id, CORRIDOR))
    ids = list(polys)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if _shares_door(polys[a], polys[b]):
                present.append((a, b))
    missing = graph.missing_required(present)
    if missing:
        raise ValueError("missing required adjacency: " + ", ".join(f"{a}-{b}" for a, b in missing))


def _shares_door(a: Polygon, b: Polygon) -> bool:
    shared = a.boundary.intersection(b.boundary)
    return shared.length + _EPS >= _DOOR
```

Note for the implementer: `_band_minus_core` reduces the core-side band length by the core width so the LP never places a room under the core; if `test_rooms_and_corridor_tile_the_plate_without_overlap` fails because the strip to the right of the core is unclaimed, extend the residual primary polygon in that band to `band.x1` after dimensioning (the LP's residual width plus the core width equals the leftover). Keep the adjacency verification strict; do not loosen `_DOOR`.

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_topology_layout.py -q`
Expected: `6 passed`

- [x] **Step 5: Commit**

```bash
git add backend/app/modules/topology_planner/service.py backend/tests/test_topology_layout.py
git commit -m "Generate a topology-first layout and verify it against its graph

Rooms are dimensioned by LP along a double-loaded spine; every room shares a
door width with the corridor and the restroom touches the core, or the
generator raises."
```

---

### Task 10: `layout_strategy` dispatch and the end-to-end gate

**Files:**
- Modify: `backend/app/modules/generation_loop/service.py:290-299` (signature) and the per-floor call at `:673` (`generate_orthogonal_office_layout(...)`)
- Modify: `backend/app/modules/generation_loop/regeneration.py` (remove the Task 3 note; pass `layout_strategy` for real)
- Test: `backend/tests/test_layout_strategy_dispatch.py`

**Interfaces:**
- Consumes: Task 9 `generate_topology_layout`, Task 2 `LAYOUT_STRATEGIES`.
- Produces: `run_building_generation(..., layout_strategy: str = "orthogonal")`; `"topology"` routes each office floor through `generate_topology_layout(boundary, program, core_polygon=core.polygon)`; unknown strategy → `ValueError("unknown layout strategy")`.

- [x] **Step 1: Write the failing test**

```python
# backend/tests/test_layout_strategy_dispatch.py
import pytest

from backend.app.modules.generation_loop.service import run_building_generation
from backend.tests.test_generation_loop import _long_edge_fixture_inputs


def test_unknown_strategy_is_rejected_before_any_work():
    mass, assignments, programs, core, circulation = _long_edge_fixture_inputs()

    with pytest.raises(ValueError, match="unknown layout strategy"):
        run_building_generation(mass, floor_assignments=assignments, program_overrides=programs,
                                core_override=core, layout_strategy="diffusion")


def test_topology_strategy_produces_no_relaxations_on_the_sample_office():
    mass, assignments, programs, core, circulation = _long_edge_fixture_inputs()

    building = run_building_generation(mass, floor_assignments=assignments, program_overrides=programs,
                                       core_override=core, layout_strategy="topology")

    for floor in building.floor_results:
        assert floor.program.form_relaxations == (), floor.program.floor_index
        assert floor.layout.candidate_id.endswith("-topology")


def test_topology_strategy_gives_the_restroom_its_target_on_every_floor():
    mass, assignments, programs, core, circulation = _long_edge_fixture_inputs()
    from backend.engine.geometry import polygon_area

    building = run_building_generation(mass, floor_assignments=assignments, program_overrides=programs,
                                       core_override=core, layout_strategy="topology")

    for floor in building.floor_results:
        target = next(n.target_area for n in programs[floor.program.floor_index].nodes if n.node_id == "restroom")
        got = polygon_area(next(r.polygon for r in floor.layout.rooms if r.room_id == "restroom"))
        assert got == pytest.approx(target, rel=0.02)
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_layout_strategy_dispatch.py -q`
Expected: `TypeError: run_building_generation() got an unexpected keyword argument 'layout_strategy'`

- [x] **Step 3: Write minimal implementation**

In `run_building_generation` add `layout_strategy: str = "orthogonal"` to the signature and, first thing in the body:

```python
    from backend.app.modules.generation_loop.repair import LAYOUT_STRATEGIES
    if layout_strategy not in LAYOUT_STRATEGIES:
        raise ValueError(f"unknown layout strategy: {layout_strategy}")
```

At the per-floor layout call (`generation_loop/service.py:673`, the `generate_orthogonal_office_layout(...)` inside the office branch), wrap:

```python
            if layout_strategy == "topology":
                from backend.app.modules.topology_planner.service import generate_topology_layout
                layout = generate_topology_layout(
                    floor_boundary, program, core_polygon=core_polygon
                )
            else:
                layout = generate_orthogonal_office_layout(
                    ...existing arguments unchanged...
                )
```

(`floor_boundary`, `program`, `core_polygon` are the same locals the orthogonal call already receives; read the surrounding 30 lines and use the exact names.) Thread `layout_strategy` through any intermediate helper between `run_building_generation` and that call (grep `generate_orthogonal_office_layout(` — there is one call site in this file). The topology path skips `_fit_orthogonal_program_to_layout`; the program returned for the floor is the input program unchanged, so `form_relaxations == ()` holds by construction.

In `regeneration.py`, delete the Task 3 note; the `layout_strategy=` kwarg now exists.

- [x] **Step 4: Run tests and the metric gate**

Run: `python -m pytest backend/tests/test_layout_strategy_dispatch.py backend/tests/test_regeneration_loop.py backend/tests/test_generation_loop.py -q`
Expected: pass.
Run: `python -m backend.tools.regenerate_plans --label task10-topology --rounds 3`
Expected in `report.json`: `regeneration.rounds` contains a `switch_strategy → topology` proposal, and the `score` block shows `relaxations == 0` and `area_shortfall` **strictly below** the baseline run `20260911-110731-area-deviation` (41 deviations, shortfalls up to 84 %). Send `regenerated/floor_00*/*.png` to the user.

- [x] **Step 5: Full suite, then commit**

Run: `python -m pytest backend/tests -q` → expected `≥ 1034 passed, 0 failed`. If the orthogonal path's tests regress, the dispatch is wrong — the `else` branch must be byte-for-byte the previous call.

```bash
git add backend/app/modules/generation_loop/service.py backend/app/modules/generation_loop/regeneration.py backend/tests/test_layout_strategy_dispatch.py
git commit -m "Dispatch layout generation by strategy and let the loop choose topology

The topology-first generator runs beside the orthogonal one. The rule
proposer switches to it when exterior priority alone leaves a room starved;
its output carries no form relaxations by construction."
```

---

## Self-review

**Spec coverage.** Part B: evaluator (T1), vocabulary + rule proposer (T2), loop (T3), LLM proposer with fallback (T4), stage wiring + `maximum_stage_attempts` + trace in `alternatives.json` + tool flags (T5). Part A: adjacency graph with spanning circulation and hard `service_adjacent` (T6), zone-driven double-loaded slicing (T7), LP dimensioning raising on infeasibility (T8), assembled generator verified against its graph (T9), strategy dispatch + end-to-end metric gate (T10). Non-negotiables: no relaxation (T8/T9/T10 tests assert it), determinism (T8 test), metric gate (T5/T10 steps), scipy only new dep (T8).

**Placeholders.** None: every code step carries the code. Task 10's "read the surrounding 30 lines" is a locating instruction with the exact grep, not a design gap.

**Type consistency.** `LayoutScore.key()` (T1) used by T3 sorting and T4 payload; `GenerationRequest.exterior_allocation_requests()` (T2) used by T3; `RepairProposal` union (T2) used by T3/T4/T5; `LAYOUT_STRATEGIES` (T2) used by T4 schema and T10 validation; `Band.length/depth` (T7) used by T8; `TopologyInfeasible.constraints` (T8) used by T9 test; `generate_topology_layout` signature (T9) matches the T10 call; `RegenerationTrace/Round` field names (T3) match `alternatives_regeneration_block` (T5).

**Known limitation stated up front.** T7/T9 implement a double-loaded slicing topology, not a full rectangular dual. That satisfies spanning circulation and `service_adjacent` for the office profile; a general rectangular-dual placer is a follow-on plan once this one's metrics hold.
