# Paper Conformance Review

## Current Verdict

| Pipeline | Execution | Paper-complete | PLAN candidate |
|---|---:|---:|---:|
| Deterministic concept-basic | yes | not applicable | yes, after internal validation |
| Graph2Plan | raw forward only | no | no |
| HouseDiffusion | checkpoint load only | no | no |

The L/U-shaped, sloped-polygon, and floor-setback implementation in PLAN is not
a claim that Graph2Plan or HouseDiffusion is paper-complete. It is a separate
deterministic concept-basic path using exact orthogonal decomposition or an
axis-aligned planning region inside a diagonal boundary, per-floor boundaries,
an all-floor shared core/stair intersection, explicit program adjustments, and
the existing validator/render loop. The retained
`sample_mass_l_setback_office.json` and
`sample_mass_polygon_setback_office.json` runs pass internal and render
validation. Diagonal fringe outside the planning region may remain unassigned,
and regulatory screening remains `not_checked`.

Graph2Plan record 0 ran the official repository's lower-level model path with
`generate=True`, `refine=True`, and strict checkpoint loading in a bounded
subprocess. The worker retains exact tensors consumed by the model and the
parent accepts only JSON and non-pickle NPZ exchange files.

The result is not a usable plan. Both predicted and refined room boxes contain
7 intersecting pairs out of 21 possible pairs. The documented MATLAB
`align`/`decorate` post-processing, conversion to PLAN polygons/openings, and
PLAN validation were not run. The source dataset is RPLAN residential data,
not the supplied commercial/office mass.

## Review Files

- `graph2plan-record-0000/graph2plan-raw-preview.png`: learned class raster,
  predicted boxes in blue dots, refined boxes in red.
- `graph2plan-record-0000/graph2plan-raw-forward.npz`: derived forward outputs.
- `graph2plan-record-0000/graph2plan-input-condition.npz`: exact consumed
  boundary raster, inside box, room types, attributes, and triples, plus raw
  boundary and transferred graph evidence.
- `graph2plan-record-0000/graph2plan-raw-metadata.json`: source/checkpoint/data
  provenance, environment, hashes, timing, and explicit unrun stages.
- `graph2plan-record-0000/repeat-verification.json`: independent two-run CPU
  comparison; input NPZ, derived output NPZ, and PNG hashes were identical.
- `concept-basic-loop.png`: current deterministic commercial baseline.
- `concept-basic-loop/index.html`: direct-open review index with its linked
  SVG, PNG, HTML, and JSON artifacts.

## Loop Evidence

The concept-basic review now evaluates only distinct fingerprints and records
all alternatives as siblings of the baseline. It preserves explicit or LLM
floor assignments and separates floor acceptance from whole-building
acceptance.

The 30 m by 12 m sample passed on iteration 1. The 18 m by 12 m sample was
rejected before generation because it is below the current 20 m minimum width,
so it correctly records zero evaluated candidates. A natural fixture that
generates successfully, fails validation, and then improves on iteration 2 or
3 is still missing.

Regulatory `not_checked` is reported separately. Internal acceptance is not a
permit, code-compliance, construction-document, or architect-quality claim.

## Primary Sources

- Graph2Plan paper and official code:
  https://arxiv.org/abs/2004.13204
  https://github.com/HanHan55/Graph2plan
- HouseDiffusion paper and official code:
  https://arxiv.org/abs/2211.13287
  https://github.com/aminshabani/house_diffusion
