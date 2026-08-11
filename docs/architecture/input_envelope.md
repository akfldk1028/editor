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

| Footprint | Reached two |
| --- | --- |
| 20x10, 30x12, 40x24, 24x24, 60x20 | 16 / 16 |
| L-shaped 36x26 with an 18x12 notch | 0 / 16 |

Every rectangular plate measured is inside the envelope. Concave plates are not.

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

Routing the product path through that composer is what would bring concave
plates inside the envelope. It assigns one use type to every floor today, so it
has to learn the floor use mix before it can stand in for the current path.

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
