---
name: inspect-drawing
description: Use when a user needs read-only facts about a DWG or DXF drawing, its layers, unsupported objects, or entities.
---

# Inspect Drawing

Purpose: return deterministic drawing evidence for one requested layer. Read only.

1. Open the supplied relative DWG or DXF path.
2. Describe the opened drawing; report every unsupported item from that result.
3. List layers, then query the requested layer.
4. Report only capability output. Every entity report includes handle, type, layer, and bbox when available.

Model geometry inference is forbidden. Do not guess missing geometry, entity identity, or unsupported-object behavior.

Failure codes: `INPUT_SCHEMA_INVALID`, `CAPABILITY_EXECUTION_FAILED`, `OUTPUT_SCHEMA_INVALID`.

Limits: `NO_MODEL_GEOMETRY_INFERENCE`; `UNSUPPORTED_OBJECTS_REPORTED`; results are limited to the indexed drawing and the requested layer.
