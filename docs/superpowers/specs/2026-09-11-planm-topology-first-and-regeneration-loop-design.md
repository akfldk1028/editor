# PLANM Topology-First Layout and Regeneration Loop Design

## Decision

PLANM stops patching symptoms of a corridor-first layout and adopts the two
structures every 2025–2026 floor-plan paper we read converges on:

1. **Topology before geometry** (GFLAN 2026-07 two-stage decomposition;
   Shiksha/Shekhawat AI EDAM 2025 circulation derived from the adjacency
   graph; DPLAN 2026-06 graph-theoretic pipeline). Room relationships and
   the corridor that serves them are decided first; coordinates come from a
   linear program afterwards (Shekhawat 1910.00081 dimensioning).
2. **Evaluate, then regenerate — never relax** (GreenPlanner 2025-11:
   invalid 60% → 0% by regenerating non-compliant layouts under a
   deterministic evaluator; AiC 2025-06 rule-based checker with iterative
   refinement). Violations are inputs to another round, not limits to widen.

Both are implemented as deterministic algorithms. An LLM participates only as
an *optional proposer* of structured repair actions, which the deterministic
engine applies and re-validates. This is exactly what `agents/planm/agent.yaml`
already declares: `execution_mode: deterministic`,
`optional_repair_mode: llm_proposal`.

## Why the current structure cannot be patched

Measured on `sample_mass_irregular_12v_setback_office.json` (see
`backend.tools.regenerate_plans`, run `20260911-110731-area-deviation`):

| quantity | value |
|---|---|
| free plate area (core excluded) | 1070 m² |
| corridor area chosen | 22 m² |
| cells sharing ≥ 0.9 m edge with corridor (only these become rooms) | 80 m² (8 %) |
| program minimum for non-primary rooms | 329 m² |
| area deviations recorded | 41 |
| form-gate relaxations recorded | 20 (open_work min width 6.0 m → 1.08 m) |

Every observed defect — the 60–72 % open-work blob, meeting 84 % short,
restroom slabs, labels on corridors — is downstream of *rooms may only be
cells that touch a corridor chosen before the rooms existed*. Three
symptom-level fixes were attempted and reverted this week (aspect-aware
splitting: 12 regressions; holding gates: 0 accepted alternatives; frontage
ranking: corridors a billion units long). The structure, not the constants,
is the defect.

## Part B — Evaluate → Regenerate loop (built first: it is the safety net)

```
GenerationRequest ──▶ run_building_generation ──▶ BuildingGenerationResult
        ▲                                                   │
        │                                            score_building
        │                                                   │
   apply proposal ◀── RepairProposer (rule | llm) ◀── LayoutScore + report
```

- `LayoutScore` is computed only from data that already exists:
  `ValidationReport.hard_violation_count`, room polygon areas against the
  **baseline** normative program (not the post-fit program, which has been
  rewritten), and `ProgramGraph.form_relaxations`.
- Ordering: `(not accepted, hard_violations, area_shortfall, relaxations)`.
  Lower is better. Deterministic.
- `RepairProposal` vocabulary is closed and validated:
  `PrioritizeExterior(floor_index, room_id)`,
  `SwitchStrategy(layout_strategy)`,
  `RescaleTarget(floor_index, room_id, factor ∈ [0.5, 1.5])`.
  Nothing in the vocabulary can widen a form gate.
- `RuleRepairProposer` is the always-available algorithm.
  `LLMRepairProposer` wraps any `StructuredPlannerClient`; an invalid or
  out-of-vocabulary answer falls back to the rule proposer and is recorded as
  such. The LLM never emits geometry.
- `regenerate(mass, *, proposer, max_rounds)` runs at most
  `config.planm.maximum_stage_attempts` rounds (already 3 in
  `agents/planm/config/default.yaml`), keeps the best-scoring building, and
  returns a `RegenerationTrace` that goes into `alternatives.json`.

## Part A — Topology-first layout

```
ProgramGraph ─▶ AdjacencyGraph ─▶ SlicingPlan ─▶ LP dimensioning ─▶ LayoutCandidate
  (rooms,          (+ corridor         (spine +        (widths s.t.        (+ adjacency
   edges)           node, required      two bands,      area∈[min,max],     verified,
                    edges)              zone → band)    w≥min, aspect≤r)    else raise)
```

- **AdjacencyGraph**: nodes = program rooms + `corridor`. Required edges:
  every non-core room ↔ `corridor` (the paper's *spanning circulation*:
  direct access for every room), every `service_adjacent` program edge
  (restroom ↔ core), core ↔ corridor. `functional_adjacency` edges are soft.
- **SlicingPlan**: a double-loaded spine along the plate's long axis at the
  depth the core dictates, two room bands. Band membership is decided from
  `zone`: `service` and `core` on the core's side, `public` on the frontage
  side, `workplace` as the residual on both. This is the topology decision;
  no coordinates yet.
- **Dimensioning** (`scipy.optimize.linprog`): per band the depth `d` is
  fixed by the plate; each room gets a width `w_i` with
  `min_area_i ≤ w_i·d ≤ max_area_i`, `w_i ≥ min_width_i`,
  `d/r_i ≤ w_i ≤ r_i·d`, `Σ w_i ≤ band length`; objective
  `min Σ |w_i·d − target_i|` via slack variables. **Infeasible raises
  `TopologyInfeasible` naming the constraint**; nothing is relaxed. The
  regeneration loop treats that as a failed candidate.
- Closed-form consequence: a double-loaded 9.3 m band gives each side
  `d ≈ 4.05 m`, so a 25 m² restroom is 6.17 m wide at aspect 1.52 — inside
  its 2.5 limit — where the single-loaded band forced 3.46.
- The new generator is one more strategy (`topology-first-double-loaded`)
  beside the three existing ones; the orthogonal generator is not removed.

## Non-negotiables

- No new gate relaxation anywhere. `FormRelaxation` and
  `ProgramAreaDeviation` records stay the source of truth.
- Every change is judged by `python -m backend.tools.regenerate_plans`
  metrics against run `20260911-110731-area-deviation` (41 deviations,
  20 relaxations, 80 m² servable) and by the full backend suite
  (1034 passed baseline).
- Determinism: same input → same output, LLM off by default.
- `scipy>=1.17,<2` is the only new dependency (already installed).
