# PLAN Input Envelope

Approval requires two accepted alternatives. A mass that produces fewer is
returned as `retryable` with `insufficient_accepted_alternatives`, and the
approval route answers `409`. This page records which masses reach two, so the
boundary is measured rather than discovered at approval time.

Regenerate with:

```powershell
python resources/scripts/sweep_alternatives.py logs/runs/sweep
python resources/scripts/sweep_alternatives.py logs/runs/sweep --summarize-only
```

The sweep writes `sweep-summary.json` beside the per-case run directories. The
CLI exits non-zero for any run short of two accepted alternatives, so the report
file, not the exit code, is the authority on the outcome.

## Measured result, 2026-08-11

96 cases: 6 footprints x floor counts 1/3/5/8 x commercial share 0/20/34/100 %.
**80 reached two accepted alternatives, 16 did not.** Neither floor count nor
commercial share changes an outcome. Plate shape decides it.

| Footprint | Reached two | Alternatives produced |
| --- | --- | --- |
| 20x10, 30x12, 40x24, 24x24, 60x20 | 16 / 16 | 2 |
| L-shaped 36x26 with an 18x12 notch | 0 / 16 | 1 in 6 cases, 0 in 10 |

Every rectangular plate measured is inside the envelope. Concave plates produce
valid alternatives but not always two.

The retained 12-vertex irregular setback fixture does reach two:

```powershell
python -m backend.app.cli alternatives-review --input resources/datasets/manifests/sample_mass_irregular_12v_setback_office.json --output-dir logs/runs/irregular
```

## Rectangular plates: fixed

An earlier run of this sweep lost 28 cases to room proportion. A square plate
stretched the core to 2.571 against its 2.000 limit and the pantry to 8.569
against 8.500; a 3:1 plate left the open work area at 6.675 against 6.500. Each
loss cost the run its second alternative.

The cause was the generator, not the limits. Each strategy picked one dimension
from the plate and let the other fall out of the area, which produces a sliver
once the plate is extreme. The dimensions now derive from the limit itself: a
core height stops at sqrt(limit * area), a service room widens to at least
sqrt(area / limit), and the rear band leaves the open work area the depth its
limit needs. The core and the rear band stack across floors, so both are sized
once from the tightest floor. No gate moved.

## Concave plates: refused, not supported

`docs/architecture/module_map.md` states that the deterministic office path
supports L and U plates, and
`resources/datasets/manifests/sample_mass_l_setback_office.json` is the retained
evidence. That holds on the single-building path and not on the alternatives
path the product API uses.

Every alternative strategy lays rooms across the bounding rectangle of the plate
while validation measures them against the real footprint. On a concave outline
the two disagree over the notch, so the path used to return layouts whose rooms
stood outside the building. It now rejects the family up front and says why.

The structural composer does place cores inside the actual polygon, and it
produces a valid alternative for a concave mass:

```powershell
# accepted alternative on an L plate, strategy long_edge_adjacent
python -m backend.app.cli irregular-alternatives-review --input <L mass> --output-dir logs/runs/l-irregular
```

## What holds concave plates to one alternative

Measured on the L plate, best core family, three floors:

```text
plate 720.0 m2 | rooms 411.8 + circulation 37.6 = 449.4 | coverage 0.6242
leftover 270.6 m2 in two pieces, the larger 256.8 m2 filling the left arm
```

`notch_adjacent` clears every hard gate and is turned down on the quality
threshold alone, `floor_coverage 0.4646 / 0.600`.

Residual absorption is not the problem. Instrumented on a single floor it grows
the seeded rooms from 105.9 to 464.1 m2, absorbing 358 m2. What it absorbs
swings between 106 and 358 m2 across core families, because the core, stair, and
corridor are shared by every floor and a placement that suits one floor starves
another.

The corridor is the lever, and two things stand in the way:

- Both topologies, `_legacy_corridor_rectangles` and
  `_long_edge_corridor_networks`, are two rectangles anchored to the core. On a
  concave plate they stay in the arm that holds the core, so the far arm has no
  corridor to seed rooms against.
- `_select_network_and_stair` ranks candidates by `(corridor.area, -separation)`
  and takes the minimum, so a branch that reaches the far arm is always beaten
  by the compact network that does not.

Reaching the far arm therefore needs a branch topology **and** a selection that
values plate reach. The second changes the corridor chosen for every mass, so it
churns the geometry fingerprint of existing output and needs the full suite and
a fresh sweep behind it.

Widening the core search closed part of this. Each strategy ranks several
rectangles and used to send only its leader; the composer now asks for the
runners-up when the leaders come up short, which found a better core and lifted
coverage from 0.6242 to 0.6685. The plate still returns one alternative, and the
reason moved: a second valid building now exists and is dropped for being too
alike.

Measured on the two survivors, both from `long_edge_adjacent`:

```text
core 0.0283   circulation 0.4667   topology 0.0000   area 0.0852
total 0.1422 against the 0.25 minimum, material components 3 of 4
```

The gate is right to refuse them. Their cores sit in nearly the same place and
their room graphs are identical; only the corridor differs. Two drawings that
share a core and an adjacency graph are one scheme, not two, so the threshold
stays where it is. A genuine second scheme needs a different core, which returns
to the corridor reach above.

Two attempts that did not work, so they are not repeated:

- Seeding the primary room before the support rooms. The support seeds are meant
  to form a cut-set that the primary then picks the largest reachable component
  from, which `test_primary_seed_prefers_reachable_area_after_support_cutset`
  pins. Inverting it moved `open_work` from 39 to 70 m2, left coverage at
  0.6242, and broke seven tests.
- Routing the product path through the composer. That did land, and it is why
  concave plates produce valid alternatives at all now, but the composer offers
  three core families and only one clears every gate on this plate.

## Reading a failure

```text
GET /api/v1/planm/runs/{run_id}
  status: retryable
  violations: [{ code: insufficient_accepted_alternatives, ... }]

alternatives.json
  alternatives[].internal_validation  hard geometry gates
  alternatives[].render_validation    drawing legibility gates
```

Per-floor `*.review.json` carries `checks` plus `validation.violations` with the
offending room and its measured value.
