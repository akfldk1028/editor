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

| Shape | Office only | Mixed use |
| --- | --- | --- |
| rect 20x10, 30x12, 40x24, square 24, long 60x20 | two | two |
| T, U, notched | two | **none** |
| L 36x26, chamfered octagon, sloped pentagon | one | **none** |
| L 48x40 | none | none |

Floor count changed nothing anywhere.

## The two findings that matter

### A non-rectangular plate with a commercial floor returns nothing

This holds for every concave and every non-orthogonal family, and it predates
the corridor work: reverting `circulation_planner` to its earlier state
reproduces it. Concave plates are not the problem on their own, since T, U, and
notched all reach two alternatives when every floor is office.

The chain ends at `orthogonal layout cannot place frontage room sales_a`. A shop
carries `frontage_required`, so it needs a cell that touches the street, and a
cell only survives seeding if it also touches the corridor. Instrumenting a T
plate shows the count of cells meeting both swinging between zero and four
depending on where the core lands. The corridor is chosen once for the whole
stack while the frontage requirement belongs to the commercial floor alone, so
nothing in the choice protects the shop frontage.

Adding served-street length as a selection constraint was tried and reverted: it
changed no outcome and broke the coordinate-scale bound in
`test_optional_separation_candidate_search_is_coordinate_scale_bounded`.

### Rectangles are clean

All twenty rectangular cases reach two. The square and the 3:1 plate were
failing on room proportion until the generator started deriving the free
dimension from the aspect limit rather than from the plate.

## What was fixed getting here

- The legacy corridor strip was a precondition rather than an option. Its
  failure raised out of the candidate search, hiding the long-edge networks and
  branches from any plate whose core left no room beside it. That was the real
  meaning of `floor does not admit a connected corridor network`.
- `_maximum_doorway_separation` reduced an empty sequence when a shared edge was
  too short for a doorway, which the sibling `None` branch already answered
  with zero. Reaching more topologies exposed it.
- Corridor reach became a constraint rather than a preference, and a network
  that strands a limb now loses to one that does not. Among those that reach,
  the compact network still wins, so a rectangular plate keeps its old choice.
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
- Served-street length as a corridor selection constraint, as above.

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
