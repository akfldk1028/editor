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

## Measured result, 2026-09-01

48 of 48 cases reach at least two accepted, quality-distinct alternatives. The
matrix remains twelve footprint families x floor counts 3/5 x commercial share
0/34 %. The eight mixed-use shortfalls recorded below now pass without reducing
the two-tenant program or weakening internal, render, or diversity gates.

| Shape | Office only | Mixed use |
| --- | --- | --- |
| rect 20x10, 30x12, 40x24, square 24, long 60x20 | two | two |
| T 44x30 | two | two |
| U 44x28 | three | two |
| notched 40x26 | two | three |
| L 36x26 | two | three |
| L 48x40 | two | two |
| chamfered octagon | two | two |
| sloped pentagon | two | two |

The root cause was the circulation planner selecting one corridor/stair pair
per core even though it had already enumerated viable runners-up. On the four
affected shape families, that single pair left only one corridor door into the
street-facing commercial band. Splitting the band could not give both required
tenants frontage and a door, so the layout stopped at `sales_b`.

`generate_circulation_candidates` now exposes a deterministic ranked, bounded
set of corridor/stair pairs. The structural composer searches up to 24 pairs
only when a building has a `neighborhood_commercial` floor, stops at the first
accepted pair for each core/variant, and retains the existing single-candidate
path for office-only buildings. The original single-candidate API delegates to
the new search with `limit=1`, preserving its result and contract.

Fresh evidence is retained outside the repository at
`C:\DK\PLAN-local-archive-20260901\verification-c034-multicandidate-20260901-131508\sweep`:

- 48 `alternatives.review.json` reports;
- 102 accepted alternatives, with zero accepted alternatives failing an
  internal or render gate;
- 429 PNGs;
- distinct representative PNG hashes and direct visual inspection for L 36x26,
  L 48x40, chamfered, and sloped mixed-use floors.

## Measured result, 2026-08-19

40 of 48, up from 34. Every rectangular plate reaches two, every office-only
plate reaches two, and every remaining shortfall is a non-rectangular plate on
the mixed-use mix.

| Shape | Office only | Mixed use |
| --- | --- | --- |
| rect 20x10, 30x12, 40x24, square 24, long 60x20 | two | two |
| T 44x30 | two | two |
| U 44x28 | three | two |
| notched 40x26 | two | two |
| L 36x26 | two | one |
| L 48x40 | two | one |
| chamfered octagon | two | one |
| sloped pentagon | two | one |

Floor count changes nothing on this matrix.

### What moved it

The composer decides it has enough by counting acceptances, and it was counting
the wrong thing. A plate whose only workable core family produces three
near-identical alternatives has three acceptances and one plan; `len(accepted)
< 2` was false, so neither fallback core request ran on exactly the plates they
exist for. They now gate on what survives
`_select_quality_distinct_alternatives`, which is what the caller receives.

The core minimums were hardcoded at 7.6 by 5.2. The 5.2 is one stair depth plus
the lobby, which is what the core needs *across* the edge the protected exits
sit on. *Along* that edge it needs two stairs and the central bank, 6.8 at the
default height. So a family meeting the core on its short edge was refused
after the fact for a core never sized for the job: the same 72 m2 core at
13.85 by 5.2 fitted 60 times for `long_edge_adjacent` and failed 8 times for
`central` and `notch_adjacent` — identical rectangle, different edge.
`minimum_core_edge` derives the larger requirement from the stair enclosure and
a third fallback asks for cores that satisfy either edge, after the cheaper
shapes come up short so nothing that works today is taken away.

Recovered: L 36x26 office at both floor counts, U 44x28 mixed use, notched
mixed use. Nothing regressed.

## Measured result, 2026-08-16, kept for the deltas below

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

## Historical: where the eight shortfalls stopped before 2026-09-01

Before the bounded circulation-search fix described in the 2026-09-01 result,
L 36x26, L 48x40, chamfered, and sloped failed on mixed use at both floor
counts. Every one stopped on the same honest sentence:

    orthogonal layout cannot leave a street-facing seed for sales_b after sales_a

That message was new at the time and replaced a false one. Two lookaheads share
the block that raises it — an area budget and a frontage seat — and both were
reported as the area budget. The measurement said otherwise: at the give-up
point on sloped the assigner held 8 seeds for 4 bounded rooms with every seed
smaller than every limit, so the area budget was never in question. Counting
the two refusals apart, and naming the frontage one, is the whole of that
change.

Subdivision also drove frontage capacity up to the seat count rather than
stopping as soon as it had enough rectangles overall: two shops need two
street-facing seeds, and one wide seat is one seat. That removed all eleven
area-capacity give-ups on sloped. It did not move the count, because on these
four plates the street band still cannot be cut into two seats of the 4.0 m the
shops ask for while both halves keep their corridor door.

The measurement answered the geometry question, and the answer was no, not by
splitting. On sloped 40x26 the band is 14.53 by 6.75 with its corridor contact
on the 6.75 end. Sixty-six cuts would give two 4.0 m seats; none of them leaves
both halves a door, and stacking two 4.0 m rooms needs 8 m of depth the band
does not have. Every room needs a circulation door — `validator/service.py`
refuses one without — so a shop cannot be seated on street access alone.

Two ways out were considered at that stage, both design decisions rather than
defects:

- A corridor that runs along the street instead of into it. Tried, measured,
  reverted; see below. It could not land while the planner returned one network
  per core and ranked on area.
- A program that asks for the tenants the plate can seat.
  `_split_commercial_tenants` splits the sales area into exactly two, always,
  and a one-tenant neighbourhood-commercial floor is a normal plan. Deciding
  that needs the seatable frontage, which is only known inside the layout
  generator, so it belongs in the repair path beside the daylight retry rather
  than in the program prior.

## Historical shortfalls before 2026-09-01

### The distinctness threshold is no longer the thing in the way

The question this section used to pose — whether `too few accessible room
rectangles` was hiding a core that would give a genuinely different plan — is
answered. It was. Four defects were the reason and all four are fixed above,
which is where the six recovered cases came from.

In the 2026-08-19 result, the eight that remained stopped downstream of
distinctness because a shop could not be seated. Distinctness was not the cause.
That historical result remains evidence against weakening the threshold:
clearing a 0.107 pair would have shipped two drawings of the same plan.

### The commercial floor's areas skew hard

The room that owns the rear takes most of the plate: `stock` reaches 552 m2 of
912 on T 44x30 while `checkout` holds 5 m2. This is the same skew a rectangular
plate has always had, where one tenant takes 727 m2 and the other 17 m2, so it
is not new and it is not what the rear-primary fix introduced. It is what
`_absorb_residual_cells` does by design: the primary takes whatever is left.
Room proportions are advisory, so no gate reads it, but a reviewer will.

## Historical fixes leading to the 2026-09-01 result

- The composer gates its fallback core requests on the distinct count, as
  above, so they fire on the plates they exist for.
- Core minimums come from the stair enclosure rather than two constants that
  assumed which edge the corridor arrives on, as above.
- Subdivision drives frontage capacity up to the seat count, and the assigner
  names a frontage shortage as one instead of reporting it as an area budget.
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

- A corridor spine parallel to the street, offered as an extra network
  candidate. The reasoning holds: a network anchored to the core meets the
  frontage band end-on, so the band has one door at one end, and the measurement
  agrees — on sloped 40x26 mixed use the shop band is 14.53 by 6.75 with its
  corridor contact on the 6.75 end. Of the 66 cuts that would give the band two
  4.0 m seats, none leaves both halves a door. A street-parallel spine fixes
  that in principle, and in practice it cut the bands short of a seat from 12 to
  8. It still cost four cases: 36 of 48, losing U 44x28 and notched 40x26 on
  mixed use at both floor counts. `_select_network_and_stair` returns one
  network per core and ranks on corridor area, so a spine is chosen only where
  it happens to be small — 3 selections out of 21 — and where it is chosen it
  displaces a network that was serving the floor better. Nothing here works
  until the planner can offer more than one circulation per core and let the
  layout generator pick the one its program fits.

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
