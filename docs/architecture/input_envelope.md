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

## Measured result, 2026-08-16

48 cases: twelve shape families x floor counts 3/5 x commercial share 0/34 %.
An earlier 96-case run over four floor counts and four use mixes found neither
ever changed an outcome, so that budget now buys shape variety instead.

34 of 48 reach two, up from 33 before the rear-primary and label-search fixes
below, and from 26 before the coordinate-grid fix. No shape family returns none
any more: every mass on this matrix now produces at least one alternative that
passes every hard gate.

| Shape | Office only | Mixed use |
| --- | --- | --- |
| rect 20x10, 30x12, 40x24, square 24, long 60x20 | two | two |
| T 44x30 | two | two |
| U 44x28 | three | one |
| notched 40x26 | two | one |
| L 48x40 | two | one |
| chamfered octagon | two | one |
| sloped pentagon | two | one |
| L 36x26 | one | one |

Floor count changes nothing on this matrix.

## What the rear-primary fix changed

Only a primary room may grow past its target area to take the floor no seed
claimed. An office floor carries two of them, because
`_zone_orthogonal_office_program` re-types `focus` to `open_work` on a
non-rectangular plate, so a region the main room cannot reach still has an
owner. A commercial floor carried none but its shop tenants, and those are
pinned to the street band.

On a U plate that was the whole difference. Same core, same corridor:

| | office floor | commercial floor |
| --- | --- | --- |
| residual cells touching a primary seed | 79 m2 | **0 m2** |
| coverage | 0.985 | 0.456 |

Both tenants finished at 39 m2 against a 279 m2 target, every support room
stopped at its own target, and 482 m2 of 912 belonged to nobody.

A shop cannot occupy that depth — it has no frontage — but back of house can,
and already sits there. `_rear_primary_room_ids` nominates the commercial
`stock` node, and `generate_orthogonal_office_layout` takes the nomination
through `rear_primary_room_ids`, which is how the generator now decides who is
primary: by room, not by space type. Coverage on the commercial floor of U,
notched, sloped, and L 48x40 went from 0.37-0.55 to 0.92-0.99, and each of those
families went from none to one.

## What the label-search fix changed

Every render rejection on this matrix was one label the placement search gave up
on: the entrance and elevator callouts of a commercial floor. The search steps
outward from the anchor, and its ladder jumped 16 px to 28 px. On a street line
carrying three shop entrances above a row of grid bubbles, the only opening was
20 px straight down, 2 px wide between the bubbles and the sheet edge — a brute
force count found 3478 free positions the ladder never landed on. The step is
now 2 px (`_ARCHITECTURAL_LABEL_SEARCH_STEP_PX`), which recovered T 44x30 at
three floors and cleared the render rejections from L 48x40.

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

## What the misdiagnosis fixes changed, 2026-08-19

The count did not move. 34 of 48 before, 34 of 48 after. What moved is the
reason each shortfall gives, which was wrong.

`orthogonal footprint leaves too few accessible room rectangles` was the
headline refusal on `central` and `notch_adjacent` across every short plate.
It appeared about twenty times in one four-case probe; it now appears once.
Two defects were producing it.

### The frontage guard refused every split once the band was short

`_subdivide_accessible_rectangles` may not spend a frontage seat on a seed that
cannot use it, so a split is dropped when it would leave frontage capacity below
the requirement. Compared against the requirement rather than against the
capacity the band already holds, the guard refuses *every* split the moment
capacity is short of one, including splits that touch no frontage at all. A
core that puts the whole accessible band off the street starts at zero, so the
family never subdivided and died counting rectangles.

The guard now protects what the band holds: a split may not lower capacity
below `min(required, current)`. Where capacity meets the requirement the
behaviour is unchanged, which
`test_accessible_subdivision_still_refuses_a_split_that_spends_frontage` pins.

### The decomposition dropped the street edge one grid step wide

Both planners snap to `_GRID_STEP = 0.25`. A core or corridor landing one step
off the street leaves a 0.25 m strip along the whole frontage, the
decomposition cuts it into its own row of cells, and the minimum-width filter
discards them. On U 44x28 mixed use that was 41 of the 100 cells sitting on the
free shape's bottom edge, every one exactly 0.25 m deep. What survived started
at y = 0.25, and since frontage contact is an exact intersection, a quarter of a
metre reads the same as a mile: the shop program had no frontage at all.

`_absorb_frontage_slivers` folds a street-edge sliver into the seed it shares a
full edge with. On U 44x28 mixed use:

| | before | after |
| --- | --- | --- |
| assignments with no street-facing seed | 10 of 24 | 3 of 25 |
| deepest street-facing seed, minimum dimension | 3.8 m | 6.8 m |

Shops on that plate ask for 4.0 m, so the band went from short everywhere to
clear of the requirement.

Only frontage slivers fold. Merging the same strip inland was measured and
reverted, see below.

## Where the fourteen shortfalls actually stop

Every shortfall is a plate reaching one, and the set is exactly the twelve
non-rectangular mixed-use cases plus L 36x26 on both mixes. Three distinct
causes, none of them the rectangle count any more:

- **L 36x26, both mixes.** `central` and `notch_adjacent` refuse with `core is
  too small for two height-derived separated stairs, a central bank, and lobby`.
  A core-sizing question, unrelated to the plate decomposition.
- **Non-rectangular mixed use.** `central` and `notch_adjacent` refuse with
  `orthogonal layout cannot place frontage room sales_a` or `cannot preserve
  bounded seed capacity after sales_a`. A shop wants street frontage and a
  budgeted seed; these cores offer one or the other.
- **All of them, finally.** `long_edge_adjacent` is the only family left
  offering candidates, and `_select_quality_distinct_alternatives` refuses its
  runners-up at 0.107 to 0.17. The field is narrow because the field is one
  family, which is now a measured fact rather than an inference.

## What still falls short

### The distinctness threshold now meets an honest one-family field

The question this section used to pose — whether `too few accessible room
rectangles` was hiding a core that would give a genuinely different plan — is
answered. It was, and two defects were the reason; both are fixed above. What
remains is a `central` core that a shop program genuinely cannot use on these
plates, so `long_edge_adjacent` really is the only family offering candidates
and its runners-up really do resemble each other.

That makes the threshold question live rather than premature: 0.107 to 0.17 is
what one core family produces on a plate that admits one core family. Do not
move the threshold to clear it. Either the shop program has to become placeable
against a central core, or a plate with one workable core family has to be
reported as such instead of counted as a shortfall.

### The commercial floor's areas skew hard

The room that owns the rear takes most of the plate: `stock` reaches 552 m2 of
912 on T 44x30 while `checkout` holds 5 m2. This is the same skew a rectangular
plate has always had, where one tenant takes 727 m2 and the other 17 m2, so it
is not new and it is not what the rear-primary fix introduced. It is what
`_absorb_residual_cells` does by design: the primary takes whatever is left.
Room proportions are advisory, so no gate reads it, but a reviewer will.

## What was fixed getting here

- The frontage split guard protects the capacity the band holds rather than the
  requirement, as above, so a band that starts short can still subdivide.
- A street-edge sliver folds into its neighbour instead of being dropped, as
  above, so the plate edge stops moving inward by a grid step.
- A commercial floor names a rear primary, as above, so the depth behind the
  corridor has an owner. Primary is now a set of room ids the caller may add to,
  not a space-type test.
- The label placement ladder steps in 2 px, as above, so it cannot stride over
  the gap it is looking for.
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

- Folding a too-thin cell into its neighbour anywhere on the plate, not just on
  the frontage. It is tempting because it did unlock something real: `central`
  produced its first accepted alternative on U 44x28 mixed use. It also cost
  more than it bought. T 44x30 at three floors on mixed use fell from two to one
  with `cannot preserve bounded seed capacity after sales_a`, and the
  long-edge winner on U 44x28 started failing render with one unresolved label
  collision. 33 of 48, down one. Merging inland moves seed areas the assignment
  lookahead has already budgeted against, so anything in this direction has to
  answer the seed-capacity budget first.

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
