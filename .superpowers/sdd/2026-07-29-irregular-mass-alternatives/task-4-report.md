# Task 4 Report: Irregular Structural Alternatives Review

## Scope

- Base commit: `f4ebc2e`
- Fixture: `datasets/manifests/sample_mass_irregular_12v_setback_office.json`
- Command: `python -m backend.app.cli irregular-alternatives-review --input datasets/manifests/sample_mass_irregular_12v_setback_office.json --output-dir logs/runs/irregular_structural_alternatives --limit 3`
- Retained review: `docs/irregular-mass-alternative-review-2026-07-29/`

## Implementation

- Added the `irregular-alternatives-review` CLI command.
- Composed and rendered structural alternatives at 1920 x 1080 in architectural style.
- Regenerated baseline office program priors and checked actual open-work share against 75% of the baseline prior.
- Required the open-work zone to remain the largest non-core program zone.
- Recorded per-floor coverage, unallocated ratio, label collision count, output size, PNG SHA-256, and office-space evidence.
- Recorded candidate structural, core, circulation, room, and ordered-PNG fingerprints.
- Returned a non-zero exit unless at least two quality-accepted candidates remained distinct across structural, core, circulation, and PNG evidence.
- Made architectural PNG label placement avoid furniture and fixture bounds with 8 px clearance.

## TDD Evidence

1. Command test failed because the argparse command did not exist; implementation made it pass.
2. Quality threshold assertion failed because threshold evidence was absent; implementation added it.
3. Office-ratio assertion failed because the baseline-relative requirement was absent; implementation added the baseline, minimum, actual, largest-zone, and pass evidence.
4. Output-size assertion failed at 1440 x 1080; implementation changed retained review output to 1920 x 1080.
5. Adjacent narrow-room regression failed because labels only avoided other labels; furniture/fixture obstacle bounds and clearance made it pass.

## Real Run

- Exit: `0`
- Duration: 212.7 s
- Accepted alternatives: `2`
- Distinct structural/core/circulation/candidate-PNG counts: `2 / 2 / 2 / 2`
- Thresholds: coverage `>= 0.60`; unallocated `<= 0.40`; unresolved label collisions `= 0`; open-work share `>= 0.75 x baseline`.
- Baseline open-work share: `0.604651`; minimum accepted share: `0.453488`.

| Alternative | Floor | Coverage | Unallocated | Open-work share | Largest non-core | Label collisions |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| 01 notch adjacent | 1 | 0.7563 | 0.2437 | 0.700597 | yes | 0 |
| 01 notch adjacent | 2 | 0.7311 | 0.2689 | 0.742185 | yes | 0 |
| 01 notch adjacent | 3 | 0.7913 | 0.2087 | 0.614614 | yes | 0 |
| 02 long-edge adjacent | 1 | 0.6596 | 0.3404 | 0.555805 | yes | 0 |
| 02 long-edge adjacent | 2 | 0.6821 | 0.3179 | 0.526683 | yes | 0 |
| 02 long-edge adjacent | 3 | 0.6278 | 0.3722 | 0.474366 | yes | 0 |

Candidate PNG fingerprints:

- Alternative 01: `a6dbb5a3459ed9e47ed854b1233d3c316a203c171cee592e06c5d678cca8bcb2`
- Alternative 02: `a21e404b7f98857ac3ce093512ff632dc100f921aaf064824d0cbdf5c5553325`

Floor PNG SHA-256:

- Alternative 01 F1: `cb14068aa65b5871d113501da9ad470d1b84b96aeffff3ec0324008283657ec9`
- Alternative 01 F2: `77c4f118e0ff5d5ddb3188e1e9fe4678fd95401b34cc74338277c45d44a04003`
- Alternative 01 F3: `1763b4747d7c1b29a40c1160b4198913af497468fe5da762dcae99a2f43b9337`
- Alternative 02 F1: `d127a2af17ce06f91e5226b44d3e2deac464b5b0a61a49c8eaecfb4c4dbc2cf7`
- Alternative 02 F2: `d5fc45679abb152613a73f04ec83cafd1388e39928c7f10502c655d3b3ca9f34`
- Alternative 02 F3: `ff64327a8a849824eb7debf8196b66b4a81b62c96fa974c7ef75dda2b8301635`

All six retained PNGs and `alternatives.review.json` match the real-run copies byte-for-byte by SHA-256.

## Visual Review

- Inspected all six final PNGs at the generated resolution and the full comparison page.
- Irregular floor boundaries, structural grids, cores, corridors, doors, room partitions, dimensions, and furniture remain visible.
- Korean room labels are readable and no label obscures the adjacent focus/reception furniture in Alternative 02 Floor 2.
- The comparison page uses a white background and shows three floors per alternative in one row.
- Alternative 01 Floor 1 open-work text is close to a circulation boundary but remains readable and does not conceal geometry.

## Regulatory Limits

Regulatory screening remains `not_checked`. The run explicitly retains these unresolved facts:

- `effective_date`
- `floor_code_context`
- `jurisdiction`
- `measured_travel_distance`
- `travel_limit_classification`

The rejected central strategy records legacy protected-exit separation/remote-exit failure and a governing-separation circulation topology failure.

## Verification

- `python -m pytest -q backend/tests/test_cli.py`: `21 passed in 243.28s`
- `python -m pytest -q backend/tests/test_alternative_composer.py`: `19 passed in 331.30s`
- `python -m pytest -q backend/tests/test_visual_review.py`: `59 passed in 40.29s`
- `python -m ruff check backend`: passed
- `git diff --check`: passed

Pytest emitted the existing `requests` dependency warning for the installed `urllib3`/character-detection versions; no test failed.
