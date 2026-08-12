# PLAN Input Envelope

Approval requires two accepted alternatives. A mass that produces fewer is
returned as `retryable` with `insufficient_accepted_alternatives`, and the
approval route answers `409`. This page records which masses reach two, so the
boundary is measured rather than discovered at approval time.

Regenerate with:

```powershell
python resources/scripts/sweep_alternatives.py logs/runs/shapes
python resources/scripts/sweep_alternatives.py logs/runs/shapes --summarize-only
```

The sweep writes `sweep-summary.json` beside the per-case run directories. The
CLI exits non-zero for any run short of two accepted alternatives, so the report
file, not the exit code, is the authority on the outcome.

## Measured result, 2026-08-12

48 cases: twelve shape families x floor counts 3/5 x commercial share 0/34 %.
An earlier 96-case run over four floor counts and four use mixes found neither
ever changed an outcome, so that budget now buys shape variety instead.

33 of 48 reach two, up from 26 before the coordinate-grid fix below.

| Shape | Office only | Mixed use |
| --- | --- | --- |
| rect 20x10, 30x12, 40x24, square 24, long 60x20 | two | two |
| T 44x30 | two | two at five floors, one at three |
| U 44x28 | three | none |
| notched 40x26 | two | none |
| L 48x40 | two | none |
| chamfered octagon | two | one |
| sloped pentagon | two | none |
| L 36x26 | one | one |

Floor count changed nothing except on T mixed use.

## What the grid fix changed

Every module that emits plan geometry now rounds its vertices to
`GEOMETRY_DECIMALS` (`backend/engine/geometry/polygon.py`). Before that, a
corridor rectangle built along one path carried full float precision while its
neighbour, built along a path that already rounded, sat a nanometre away. Every
contact test in this product is an exact Shapely intersection, so those two
walls read as sharing no boundary.

The consequence was not subtle. On a T plate the corridor trunk and the cells
directly above it missed each other by 2e-9, so the entire north half of the
floor — 345 m2 of 872 — had no corridor to open onto. It was never seeded, no
room could grow into it, and the floor failed on coverage at 0.47 against a
0.60 policy. Rooms that should have run to the facade stopped at their seed
cell, which is also why floor 3 of the irregular office fixture used to need
the exterior-allocation repair to pass its daylight gate and now passes on its
own.

Three things came out of that:

- **L 48x40, chamfered, and sloped now reach two on office floors.** L 48x40
  reached none before.
- **A non-rectangular plate with a commercial floor is no longer a dead end.**
  T at five floors reaches two; T at three, L 36x26, and chamfered reach one.
- The suite runs in half the time, because the same fix stopped the placement
  search from rebuilding Shapely geometry it did not need.

## What still falls short

### Mixed use on U, notched, sloped, and L 48x40

These return zero. The chain ends in floor coverage between 0.47 and 0.55
against the 0.60 policy: a shop program is seven small rooms, and once they are
seeded along the street the residual behind them belongs to no one. Office
floors do not have this problem because `open_work` is one primary room that
absorbs the whole plate.

### L 36x26 reaches one, both mixes

Its second alternative is turned down for structural diversity rather than for
geometry. Worth confirming against `compare_building_diversity` before treating
it as a generator problem.

### Render validation on L 48x40

`alternative-01:render_validation` on the mixed-use runs and
`alternative-03:render_validation` on the office runs. The office runs still
reach two, so this is a third alternative being dropped, not a blocker.

## What was fixed getting here

- Every emitting module snaps to one coordinate grid, as above.
- Subdivision protected frontage cells at 2.8 m while the assignment lookahead
  demanded each frontage room's own `min_width`, so subdivision cut away the
  seed the assigner then asked for. Both now use the room's width.
- The legacy corridor strip was a precondition rather than an option. Its
  failure raised out of the candidate search, hiding the long-edge networks and
  branches from any plate whose core left no room beside it. That was the real
  meaning of `floor does not admit a connected corridor network`.
- `_maximum_doorway_separation` reduced an empty sequence when a shared edge was
  too short for a doorway, which the sibling `None` branch already answered
  with zero. Reaching more topologies exposed it.
- Corridor reach became a constraint rather than a preference, and a network
  that strands a limb now loses to one that does not.
- Each core strategy ranks several rectangles and sent only its leader. The
  composer now asks for the runners-up when the leaders come up short.
- `primary_daylight_ratio` could land a hair above one by float summation and
  fail its own `[0, 1]` contract, discarding the floor that lit every room.

## Attempts that were reverted, so they are not repeated

- Seeding the primary room before the support rooms. The support seeds form a
  cut-set the primary then picks the largest reachable component from, which
  `test_primary_seed_prefers_reachable_area_after_support_cutset` pins. It moved
  `open_work` from 39 to 70 m2, left coverage unchanged, and broke seven tests.
- Requesting a core the size the program asks for rather than the 72 m2 cap.
  The candidate count was identical at both areas.
- Served-street length as a corridor selection constraint. It changed no
  outcome and broke the coordinate-scale bound in
  `test_optional_separation_candidate_search_is_coordinate_scale_bounded`.
- Snapping only the circulation planner's emitted rings. Its own connectivity
  checks still compared the raw corridor against the snapped stair, so every
  candidate reported `circulation topology is disconnected`. The snap has to
  cover the core planner, the emitted rings, and the checks together.
- Snapping inside `shared_boundary_segments`. It fixed contact but returned
  snapped points, which then mixed with unsnapped room vertices and produced
  `room route polyline must be orthogonal`.

## Reading a failure

```text
GET /api/v1/planm/runs/{run_id}
  status: retryable
  violations: [{ code: insufficient_accepted_alternatives, ... }]

alternatives.json
  alternatives[].internal_validation  hard geometry gates
  alternatives[].render_validation    drawing legibility gates
  rejected_families[].reasons         why each core family was turned down
```

Per-floor `*.review.json` carries `checks` plus `validation.violations` with the
offending room and its measured value.
