# Task 8: Real Irregular-Mass Evaluation and Phase Boundary

## Result

Refreshed against commit `d095f4a` after the Task 9 scoring and rejection-JSON
changes. `irregular-alternatives-review` exited `1` after 205.4 seconds. This is the
expected phase-boundary result: only one quality-distinct hard-pass alternative
was produced (`accepted_count=1`), so the command did not return success with
fewer than two alternatives.

Input: `datasets/manifests/sample_mass_irregular_12v_setback_office.json`.
Source run: `logs/runs/building_quality_irregular_refresh_d095f4a`.

## Focused And Repository Verification

| Command | Result |
| --- | --- |
| `python -m pytest -q backend/tests/test_building_quality_contracts.py backend/tests/test_building_quality_floor.py backend/tests/test_building_quality_building.py backend/tests/test_building_quality_service.py backend/tests/test_building_quality_diversity.py` | 46 passed in 24.07s |
| `python -m pytest -q backend/tests/test_alternative_composer.py` | 26 passed in 820.73s |
| `python -m pytest -q backend/tests/test_cli.py` | 22 passed in 244.38s |
| `python -m pytest -q backend/tests/test_visual_review.py` | 59 passed in 46.58s |
| `python -m pytest -q` | 801 passed, 2 skipped in 1490.18s |

All pytest invocations emitted the pre-existing `requests` urllib3/charset
dependency compatibility warning. No test failed.

Those suites are the initial Task 8 verification. The `d095f4a` refresh reran
the requested real irregular CLI, retained-artifact hash checks, PNG inspection,
Playwright layer flow, and Git diff checks; production code and tests were not
changed or rerun for this docs-only refresh.

`python -m ruff check backend` and the required working-tree `git diff --check`
were run after this report and the measured-failure plan were added; both
passed. The retained generated `source-run/alternative-01/index.html` contains
four source trailing-whitespace lines (30, 35, 40, and 45). A scoped baseline
`.gitattributes` entry applies `-whitespace` only to that retained file, so its
bytes remain exact while both `git diff --cached --check` and `git diff --check`
pass. No global whitespace setting was changed and no authored report or plan
whitespace issue remains.

## Retained Exact Evidence

`docs/building-quality-baseline-2026-07-30/source-run/` contains all 19 files
emitted by the CLI, with their original relative paths: aggregate review JSON,
comparison index HTML, accepted-alternative review/index files, three retained
floor HTML/SVG/review JSON/PNG sets, and the three top-level candidate PNGs.

`docs/building-quality-baseline-2026-07-30/sha256-manifest.json` records every
source and retained SHA-256. All 19 source/retained pairs matched.
It also records the narrowly scoped Git whitespace qualification for the one
immutable generated HTML file.

The refreshed aggregate JSON SHA-256 is
`1a1b0390d7ed01e6293b31af786d60207ec2e6028fb2bd3c09c1e574ca5bff69`.

The CLI did not emit a comparison PNG. The manifest records this explicitly;
no synthetic comparison image was created.

Top-level candidate PNG hashes:

| Retained file | SHA-256 |
| --- | --- |
| `source-run/alternative-01-floor-001.png` | `cb14068aa65b5871d113501da9ad470d1b84b96aeffff3ec0324008283657ec9` |
| `source-run/alternative-01-floor-002.png` | `77c4f118e0ff5d5ddb3188e1e9fe4678fd95401b34cc74338277c45d44a04003` |
| `source-run/alternative-01-floor-003.png` | `1763b4747d7c1b29a40c1160b4198913af497468fe5da762dcae99a2f43b9337` |

## Measured Quality Evidence

The accepted `notch_adjacent` alternative is hard-pass quality-accepted with
score `0.7935`. Component scores: daylight `0.9227`, room form `1.0`, vertical
stacking `0.6667`, egress `0.5`, and coverage/efficiency `0.8632`.

| Floor | Coverage | Primary daylight ratio | Room form pass ratio | Worst aspect ratio | Narrowest width |
| --- | --- | --- | --- | --- |
| 1 | 0.7563 | 0.9423614866510824 | 1.0 | 3.4760319589025093 | 2.676562500000001m |
| 2 | 0.7311 | 0.911026869081252 | 1.0 | 3.8390991267569334 | 2.0m |
| 3 | 0.7913 | 0.9146022582464355 | 1.0 | 3.4760319589025093 | 2.676562500000001m |

Confirmed quality issues:

- `long_edge_adjacent` was rejected by `primary_daylight_ratio:0.662530965716/0.7`.
  Its retained structured rejection report identifies hard issue
  `primary_daylight_ratio`, floor `3`, subject `floor-3`, measured value
  `0.6625309657157782`, and threshold `0.7`. The rejected candidate score is
  `0.77`; component scores are daylight `0.8716`, room form `1.0`, vertical
  stacking `0.6667`, egress `0.5`, and coverage/efficiency `0.792`.
- The accepted alternative reports `wet_service_stack_ratio=0.0` against `0.7` (soft issue); core and shaft stack ratios are both `1.0`, with maximum service centroid shift `3.9999999999999964m`.
- `egress_unresolved` subjects are `effective_date`, `floor_code_context`, `jurisdiction`, `measured_travel_distance`, `non_axis_aligned_polygon`, and `travel_limit_classification`. This is unresolved screening, not a checked egress failure.
- No room-form failure code or subject was reported; all three room-form ratios are `1.0`.
- `central` also produced protected/remote exit rejection and a governing-separation circulation-planning failure. `notch_adjacent` also produced one feasibility rejection: the core was too small for two height-derived separated stairs, a central bank, and lobby.
- Pairwise diversity could not be established: structural/core/circulation/candidate PNG distinct counts are each `1` and no pairwise comparison exists.

## Visual Inspection

Viewed all three unique retained floor PNG hashes at original resolution (the
three nested PNG copies have matching hashes):

- Floors 1-3 have explicit, heavy irregular exterior boundaries and readable
  room labels.
- Each accepted primary open-work space visibly reaches a windowed exterior
  edge; this matches the reported primary-daylight ratios above.
- No reported room-form failures exist, and the visual room forms are consistent
  with the all-pass room-form measurements rather than visibly narrow or
  elongated failures.
- The core, elevator/shaft, and stairs are visibly located in the same central
  band on all floors, matching the `1.0` core/shaft stack ratios. The restroom/
  service arrangement is not a stable stack, consistent with the measured wet
  service stack failure.

## Interactive HTML Verification

Served retained `alternative-01/floor_001/...-f1.html` locally and used
Playwright with the stable `all-off`, layer, `isolate`, and `all-on` controls.

- all-off: `[]`
- enable rooms/core/envelope: `[rooms, core, envelope]`
- isolate core: `[core]`
- restore all: 12 SVG layers restored
- console errors: `0`; page errors: `0`

## Next Phase

The measured-failure implementation plan is
`docs/superpowers/plans/2026-07-30-building-quality-generator-feedback.md`.
It starts with deterministic primary-daylight feedback and retains all current
quality thresholds. BIM/IFC work remains deferred until `BuildingQualityReport`
field names are stable.
