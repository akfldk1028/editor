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
- `infra/runtimes/gitagent/` — generic runtime
- `infra/services/dwg/` — independent DWG service
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

The brief reproduces every footprint the sweep measures. Six families —
rectangle, L, T, U, sloped, chamfered — cover all twelve, because U also
describes the notched plate and sloped is the diagonal form of L. The cut is two
lengths in metres, the material removed from the top of the plate, so a
reviewer can put a measured case in front of the generator to the coordinate.
`footprintPolygon` in `frontend/src/features/planm-planning/api.ts` walks every
family counter-clockwise from the origin, so edge 0 is always the street
frontage the pinned `site_edges` and `access_candidates` refer to. Coordinates
snap to 0.1 m.

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

40 of 48 as of 2026-08-19, up from 34. Every rectangular plate reaches two and
so does every office-only plate. The eight that remain are L 36x26, L 48x40,
chamfered, and sloped, all on mixed use, at both floor counts.

Four defects came out of that, all of them reporting the wrong cause, which is
why the same dead ends kept being retried:

- The composer gated its fallback core requests on the raw acceptance count. A
  plate whose one workable core family produces three near-identical
  alternatives had three acceptances and one plan, so the fallbacks never fired
  where they were needed. They gate on the distinct count now.
- Core minimums were hardcoded 7.6 by 5.2. The 5.2 is one stair depth plus the
  lobby, which is what the core needs *across* the exit edge; *along* it two
  stairs and the bank need 6.8. The same 72 m2 core fitted 60 times for
  `long_edge_adjacent` and failed 8 for `central` — same rectangle, other edge.
- The frontage split guard compared against the requirement, so it refused every
  split once the band was short of a seat.
- The decomposition dropped the 0.25 m grid-step strip along the street, and
  frontage contact is exact, so the whole shop program lost its frontage.

All eight remaining shortfalls now stop on one sentence: `orthogonal layout
cannot leave a street-facing seed for sales_b after sales_a`. That reduces to
one geometry question — can the street band on these plates carry two 4.0 m shop
frontages at all, and if so what split produces them. The midpoint cut is the
only one subdivision knows. Do not move the distinctness threshold; on these
plates it is downstream of a shop that cannot be seated.

The full pytest run is about eight and a half minutes now, up from six. The
extra time is the composer's third core pass, and it is what bought the six
recovered cases.

Short version, from a 48-case sweep over twelve shape families:

- Every rectangular plate reaches the two accepted alternatives approval needs,
  and so does every plate on the office-only mix.
- T 44x30, U 44x28, and notched 40x26 reach two on both mixes.
- No mass on the matrix returns none. Every shortfall is a plate reaching one,
  and all eight are the mixed-use mix on L 36x26, L 48x40, chamfered, sloped.

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
python -m pytest -q                    # 925 passed, 2 skipped, ~8.5 min
npm run test:agent                     # GitAgent runtime + PLANM contracts
npm run test:dev                       # launcher, structure, compose invariants
npm --prefix frontend run build
npm run test:frontend                  # Playwright frontend
npm run test:product                   # Playwright live product flow
npm --prefix infra/services/dwg run verify:all # node + .NET parser/CAD I/O + E2E
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
