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
**52 reached two accepted alternatives, 44 did not.** Floor count never changed
an outcome. Commercial share changed one footprint only.

| Footprint | Reached two | Failing alternative |
| --- | --- | --- |
| 20x10, 30x12, 40x24 | 16 / 16 | none |
| 60x20 (3:1 elongated) | 4 / 16 | `alternative-a` on every office floor |
| 24x24 (square) | 0 / 16 | `alternative-c` |
| L-shaped 36x26 with an 18x12 notch | 0 / 16 | both alternatives |

Every failure is `internal_validation`. Rendering passes throughout.

## Two distinct causes

### Room proportion on extreme rectangles, a generator limit

The validator rejects a room whose proportions exceed its hard limit. The
measured overruns:

| Case | Violation |
| --- | --- |
| 24x24 | `core` aspect ratio 2.469-2.571 over the 2.000 limit; `pantry` 8.569 over 8.500 |
| 60x20, office floors | `open_work` aspect ratio 6.675 over 6.500 |

60x20 reaches two accepted alternatives at 100 % commercial, because that
program carries no deep `open_work` room.

These are the limits the validator exists to enforce, and `RULES.md` forbids
overriding a geometry gate. Widening them would buy a second alternative by
shipping a room the product already judges unusable. The gap belongs to the
generator: on a square plate `side-mid-core-longitudinal-spine` stretches the
core, and on a 3:1 plate `rear-right-core-single-spine` stretches the open work
area. Both need plate-proportion-aware sizing.

### Concave plates on the alternatives path, a defect

`docs/architecture/module_map.md` states that the deterministic office path
supports L and U plates, and the retained fixture
`resources/datasets/manifests/sample_mass_l_setback_office.json` is the evidence
for it. Both claims hold on the single-alternative path and fail on the path the
product API actually uses:

```powershell
# accepted = true, every floor passes every check
python -m backend.app.cli building-review --input resources/datasets/manifests/sample_mass_l_setback_office.json --output-dir logs/runs/l-building-check

# accepted_count = 0 on the same fixture
python -m backend.app.cli alternatives-review --input resources/datasets/manifests/sample_mass_l_setback_office.json --output-dir logs/runs/l-alternatives-check
```

The alternatives path reports an axis-aligned `circulation_bounds` rectangle
over the concave outline, then places rooms in it. The violations follow from
that: `boundary` failures where rooms escape the notch, and `room_identity`
where a required room no longer fits. Every L case in the sweep fails both
alternatives for this reason.

This one is not an envelope limit. A documented, fixture-backed capability works
in one code path and is broken in the product path.

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
