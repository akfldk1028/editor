# Task 3A Report - PNG Canvas Primitives

## Scope

- `engine/io/png.py`
- `backend/tests/test_png_canvas.py`

## RED

Command:

```text
python -m pytest -q backend/tests/test_png_canvas.py
```

Result: `7 failed`. Every test failed on a missing canvas method
(`draw_text`, `stroke_dashed_polyline`, or `stroke_polyline`), confirming the
new primitives were absent.

## Implementation

- Printable ASCII 5x7 bitmap font with `?` fallback, clipping, and scale 1-8
- Solid and dashed polylines with dash phase retained across segments
- Arrowheads defined by tip and tail
- Filled and stroked circles
- Existing raw RGB PNG encoding and deterministic bytes preserved

## Verification

- Focused: `7 passed`
- Full: `203 passed, 3 failed`
- Ruff: passed
- Compileall: passed
- Diff check: passed

## Stroke-Bounds Review Fix

RED command:

```text
python -m pytest -q backend/tests/test_png_canvas.py
```

Result: `5 failed, 22 passed`. Thick lines centered just outside the top,
bottom, left, or right canvas boundary were discarded even when their raster
offsets reached visible pixels. Solid and dashed polyline cases failed too.

Fix:

- Expand segment clipping bounds by the exact even/odd stroke raster offsets
- Apply the expanded bounds consistently to lines, polylines, and dashed lines
- Preserve canvas-clamped pixel painting after center-line clipping

Verification after the fix:

- Focused: `27 passed`
- Full: `238 passed, 2 failed`
- Ruff: passed
- Compileall: passed
- Diff check: passed

The two full-suite failures are concurrent renderer work in `test_cli.py`:
the SVG circulation text lookup and top-level boundary polygon lookup no longer
match the in-progress SVG DOM. No PNG canvas test failed.

The three full-suite failures are concurrent Task 2 validation/generation work:
`test_basic_design_validation.py` expects a sales-window ID, strict validation
wiring, and tuple-normalized manifest points. No PNG canvas test failed.

## Independent Review Fix

RED command:

```text
python -m pytest -q backend/tests/test_png_canvas.py
```

Result: `15 failed, 7 passed`. The `1e9` off-canvas subprocess timed out after
two seconds. Fourteen NaN/inf cases were silently ignored or leaked internal
`TypeError`, `ValueError`, or `OverflowError` messages.

Fix:

- Clip every rasterized line segment to the canvas before Bresenham traversal
- Rasterize dashed segments only across visible canvas pixels
- Clamp filled/stroked circle loops to canvas bounds
- Reject non-finite public geometry, size, dash, gap, thickness, and scale
  parameters with explicit `ValueError`

Verification after the fix:

- Focused: `22 passed`
- Full: `222 passed`
- Ruff: passed
- Compileall: passed
- Diff check: passed
