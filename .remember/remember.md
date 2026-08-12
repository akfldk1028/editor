# Handoff

## State

PLAN is an integrated product repository. Mass input runs through alternative
generation, validation, visual review, approval, DXF handoff, and post-approval
DWG inspection as one flow.

Structure:

- `frontend/` — calls the Backend HTTP API only
- `backend/app/` — api, schemas, modules (20), adapters (planm_agent, dwg_client, planm_engine)
- `backend/engine/` — geometry, graph, constraints, metrics; the sole Shapely boundary
- `agents/planm/` — SOUL, RULES, agent.yaml, 3 contracts, 5 skills, workflow, memory
- `agents/runtimes/gitagent/` — generic runtime
- `agents/dwg/` — vendored independent DWG product
- `infra/docker`, `infra/dev`, `infra/e2e`, `resources/*`, `docs/`

Code folders are exactly frontend, backend, agents, infra. `docs/` and
`resources/` hold documentation and research assets, not code.

Product API routes (`PLANM API v1.0.0`): `/api/v1/planm/runs`, `.../{run_id}`,
`.../alternatives`, `.../alternatives/{id}/preview`, `.../approval`,
`.../dwg/handoff`, `.../dwg/inspection`, `.../artifacts/{path}`.

## Where the generator stands

`docs/architecture/input_envelope.md` holds the measured envelope, the two
fixes still outstanding, and the attempts already reverted. Read it before
touching the generator; it exists so the same dead ends are not retried.

Short version, from a 48-case sweep over twelve shape families, 33 of 48
reaching two:

- Every rectangular plate reaches the two accepted alternatives approval needs.
- Every shape family now reaches two when every floor is office, except
  L 36x26, which reaches one on a diversity rejection rather than on geometry.
- Mixed use on a non-rectangular plate works but is not settled: T at five
  floors reaches two, T at three plus L 36x26 and the chamfered octagon reach
  one, and U, notched, sloped, and L 48x40 still return none. All of those end
  on floor coverage between 0.47 and 0.55 against a 0.60 policy, because a shop
  program is seven small rooms and the residual behind them belongs to no one.

Geometry that crosses a module boundary is snapped to `GEOMETRY_DECIMALS`
(`backend/engine/geometry/polygon.py`). Contact tests here are exact Shapely
intersections, so a wall a nanometre out of place reads as no wall at all.
Anything new that emits plan geometry has to snap the same way.

## Verify

```powershell
python -m pytest -q                    # 914 passed, 2 skipped, ~6 min
npm run test:agent                     # GitAgent runtime + PLANM contracts
npm run test:dev                       # launcher, structure, compose invariants
npm --prefix frontend run build
npm run test:frontend                  # Playwright frontend
npm run test:product                   # Playwright live product flow
npm --prefix agents/dwg run verify:all # node + .NET parser/CAD I/O + E2E
python resources/scripts/sweep_alternatives.py logs/runs/shapes --summarize-only
```

The full pytest run takes about six minutes. Run the affected test files first
and keep the full run for just before a commit.

## Context

This is practical automation, not image generation. Do not hardcode area ratios
as product truth. Render and look at the PNG artifacts each loop. Keep hard
validity separate from soft quality, and never widen a gate to make a mass pass;
change the generator so it chooses dimensions inside the gate instead.

Goals, module boundaries, and the verification commands are in the root
`CLAUDE.md` and `docs/architecture/repository_layout.md`.
