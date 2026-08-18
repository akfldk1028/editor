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

`backend/app/api/` holds only that router. Four modules named `routes_*` that
were plain functions no route ever called are gone; a module with no route
belongs under `backend/app/modules`.

## What the product surface shows

The brief submits rectangle, L, T, and U plates. `footprintPolygon` in
`frontend/src/features/planm-planning/api.ts` walks every family
counter-clockwise from the origin, so edge 0 is always the full-width street
frontage and the pinned `site_edges` and `access_candidates` keep their meaning
on every shape. Coordinates snap to 0.1 m.

Code facts are asserted, never assumed. The brief sends only the fields it was
given, so an unstated fact reaches the screening as unresolved rather than as an
assumption. `PlanmRunService.execute` records the normalize stage's
`unresolved_facts` on the run record and the board names them. Asserting
jurisdiction, analysis date, and travel limit takes the list from four entries
to one: `floor_code_context`.

Nothing derives per-floor code facts yet. Doing it in the frontend would
duplicate `assign_floors_from_use_mix`; doing it in the backend would have the
system assert regulatory facts nobody supplied (habitable area, evacuation
floor). That is a product decision, not a bug, and it is why
`floor_code_context` is still unresolved.

The aggregate `regulatory_screening` cannot read `pass`. `validator/service.py`
computes it as fail-if-any-check-fails else `not_checked`, so the design never
claims compliance. Individual checks do resolve; they live in each alternative's
`building.review.json`, not in `alternatives.json`.

A run that halts now carries its evidence. `retryable`, `blocked`, and
`needs_input` render the stopped stage, the violations, and the
`rejected_families` reasons, and the accepted alternatives load too, since
`alternatives.json` is written before the retryable return. Approval stays
disabled until the run is `delivered`.

## Where the generator stands

`docs/architecture/input_envelope.md` holds the measured envelope, the two
fixes still outstanding, and the attempts already reverted. Read it before
touching the generator; it exists so the same dead ends are not retried.

Short version, from a 48-case sweep over twelve shape families, 34 of 48
reaching two:

- Every rectangular plate reaches the two accepted alternatives approval needs,
  and so does T 44x30 on both mixes.
- No mass on the matrix returns none any more. Every remaining shortfall is a
  plate that reaches exactly one.
- Every one of those stops the same way: further alternatives pass every hard
  gate and `_select_quality_distinct_alternatives` refuses them at 0.128 to 0.17
  for distinctness. The field is narrow because the other core strategies are
  refused earlier with `too few accessible room rectangles`, so look there
  before touching the threshold.

Only a primary room grows past its target to take unclaimed floor. Office floors
get a second one from `_zone_orthogonal_office_program`; commercial floors have
only their street-pinned tenants, so `_rear_primary_room_ids` nominates `stock`
and the generator decides primary by room id, not space type. Anything that adds
a use needs to answer who owns the depth behind its corridor.

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
