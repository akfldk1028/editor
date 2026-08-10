---
name: compare-drawings
description: Use when a user needs read-only, evidence-backed differences between two already opened DWG or DXF drawings.
---

# Compare Drawings

Purpose: report deterministic additions, removals, and changed CAD evidence between two opened drawings. Read only.

1. Supply the two drawing IDs already opened by the host.
2. Run the declared comparison capability once.
3. Report every returned entity with handle, type, layer, and bbox when available; preserve the reported changed fields.

Model geometry inference is forbidden. Do not describe visual differences not returned by the comparison capability. Report unsupported objects from either drawing before claiming a complete comparison.

Failure codes: `INPUT_SCHEMA_INVALID`, `CAPABILITY_EXECUTION_FAILED`, `OUTPUT_SCHEMA_INVALID`.

Limits: `NO_MODEL_GEOMETRY_INFERENCE`; `UNSUPPORTED_OBJECTS_REPORTED`; comparisons are bounded to deterministic indexed evidence.
