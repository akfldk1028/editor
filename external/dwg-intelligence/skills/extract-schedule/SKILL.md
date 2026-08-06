---
name: extract-schedule
description: Use when a user needs a read-only schedule or text-row extraction from an already opened DWG or DXF drawing.
---

# Extract Schedule

Purpose: extract deterministic text evidence and row grouping from one opened drawing. Read only.

1. Search the requested text to preserve grounded entity evidence.
2. Extract rows using the supplied positive Y tolerance.
3. Report source handles, layer, and bbox for each returned row when available.

Model geometry inference is forbidden. Do not invent table cells, columns, rows, or geometry. Report unsupported objects from the drawing description when they affect the requested schedule.

Failure codes: `INPUT_SCHEMA_INVALID`, `CAPABILITY_EXECUTION_FAILED`, `OUTPUT_SCHEMA_INVALID`.

Limits: `NO_MODEL_GEOMETRY_INFERENCE`; `NO_TABLE_CELL_INFERENCE`; `UNSUPPORTED_OBJECTS_REPORTED`; only positioned TEXT and MTEXT evidence can form rows.
