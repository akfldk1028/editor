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

The three full-suite failures are concurrent Task 2 validation/generation work:
`test_basic_design_validation.py` expects a sales-window ID, strict validation
wiring, and tuple-normalized manifest points. No PNG canvas test failed.
