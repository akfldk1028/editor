# Task 3 Report

## RED

- Command:
  `pytest -q backend/tests/test_visual_review.py -k "strict_review_renders_complete or strict_review_fails_basic or unchecked_review_does_not"`
- Result: `3 failed`
- Intended failures:
  - SVG had only the four legacy layers instead of the fixed 12-layer order.
  - A non-renderable strict basic-design feature left the review accepted.
  - Unchecked layouts had no `basic_design` review check or absent-layer
    control policy.

## Implementation

- One normalized feature sequence now drives both SVG and PNG.
- SVG features expose escaped stable `data-id`, `data-kind`, and `data-layer`.
- Render evidence records modeled, SVG, PNG, skipped, and missing IDs by
  layer/kind, plus per-layer completeness counts.
- Strict checked layouts fail the artifact review when either renderer misses
  a modeled basic-design ID.
- SVG and PNG render all 12 layers in a stable technical-drawing order.
- The HTML exposes 12 synchronized layer controls; unavailable basic-design
  layers are disabled when `basic_design` is absent.
- Controls were verified across delayed iframe load, repeated toggles, reload,
  F1-to-F2 navigation, and a 390x844 viewport.
- The building index separator is now an ASCII `|`.
- `engine/io/png.py` was not modified; commit `0311168` primitives are consumed
  through their public API.

## Verification

- Focused:
  - `pytest -q backend/tests/test_visual_review.py`
  - `36 passed`
- Full:
  - `pytest -q`
  - Task 3 checkpoint before concurrent Task 4 RED: `241 passed`
  - Current shared-tree run: `241 passed, 3 failed`
  - All three failures are concurrent Task 4 RED cases in
    `backend/tests/test_basic_design.py`: rectilinear circulation egress,
    primary-room furniture density, and explicit non-axis-aligned circulation
    rejection.
- Browser:
  - `npx playwright test browser_tests/visual_review.spec.js`
  - `1 passed`
- Ruff:
  - `ruff check backend/app/modules/visual_review/service.py backend/tests/test_visual_review.py`
  - passed
- Compile:
  - `python -m compileall -q backend engine`
  - passed
- Diff:
  - `git diff --check`
  - passed with existing LF-to-CRLF working-copy warnings only

## Visual Inspection

- Opened generated F1 commercial and F2 office PNGs at original resolution.
- Grid labels, rooms, circulation, core subdivision, columns, envelope,
  doors/exits, furniture, fixtures, egress, dimensions/site, and bitmap labels
  are visible.
- Removed repeated `EGRESS` text and duplicate room role labels after the first
  inspection; door-width labels now render once and offset toward host rooms.
- Re-inspected both PNGs after centering protected-exit labels, separating the
  bottom annotation lanes, and reducing multiple circulation labels to one
  representative label.

## Remaining Renderer Limits

- Egress routes are schematic straight segments, so several routes converge
  visually near the protected exits; this does not claim legal travel-distance
  compliance.
- PNG text is deterministic 5x7 ASCII and intentionally compact.
