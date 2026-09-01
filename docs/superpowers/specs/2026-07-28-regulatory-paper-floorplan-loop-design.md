# Regulatory And Paper Floorplan Loop

## Goal

Turn PLAN's current `concept-basic-v1` drawing into an evidence-bearing
preliminary-design loop. A result must distinguish deterministic internal
checks from Korean regulatory screening, contain buildable stair parameters
instead of decorative symbols, and compare alternative generators through one
canonical geometry and validation contract.

## Truth Boundary

PLAN does not issue a permit opinion. Every regulatory result has one of three
states: `pass`, `fail`, or `not_checked`. Missing project facts never imply
compliance. Internal geometry acceptance and regulatory screening are separate
top-level results and separate labels in JSON, HTML, SVG, and PNG.

The first supported ruleset is `KR-egress-2025-10-31`. Each check records its
rule ID, effective date, source URL, measured value, threshold, applicability,
status, and assumptions.

## Project Facts

`MassInput` gains an optional immutable building-code context:

- jurisdiction and effective date;
- floor-to-floor height;
- sprinkler protection state;
- fire-resistant main-structure state;
- detailed occupancy/use facts by floor;
- occupant load when supplied;
- above/below-grade floor position.

Old manifests remain loadable. Omitted facts produce `not_checked`.

## Korean Egress Screening

The engine separates these questions:

1. whether more than one direct stair is required;
2. the required separation of two direct stairs when applicable;
3. the minimum clear width of flights and landings;
4. whether the travel path can be measured;
5. whether stair geometry is internally feasible.

For two stairs, the default separation threshold is half the plan diagonal.
One third is used only when the manifest explicitly establishes qualifying
automatic extinguishing protection. An unknown sprinkler state uses the
conservative half-diagonal geometry target but remains `not_checked`.

The existing two-stair output stays available as a conservative alternative;
it is no longer described as the legally required count without the required
use, floor, area, and construction facts. Legal travel distance remains
`not_checked` until routes are measured from the farthest occupied points
along traversable geometry.

## Parametric Stair Model

A stair is represented by explicit parameters and derived geometry:

- clear flight width;
- floor-to-floor height;
- riser count and actual riser height;
- tread depth and tread count;
- flight count and direction;
- landing depth and width;
- stair enclosure footprint;
- headroom screening value;
- door clear width and swing.

Rendering consumes these parameters. Fixed decorative tread counts are
removed. Validation recomputes the derived values and rejects inconsistent or
unrenderable stairs.

## Program, Area, And Alternatives

Gross, core, circulation, service, and net usable areas are reported
independently. Targets are ranges with provenance rather than unexplained fixed
percentages. A legally minimal core and a redundant-egress core are distinct
alternatives where applicability permits; they are not silently normalized
into the same two-stair template.

Every building alternative preserves vertical core continuity, supports all
floors of the supplied mass, and reports floor-by-floor use, area, egress, and
unresolved facts.

## Generator Adapter Contract

All generators exchange canonical JSON containing boundary, entrances, use
program, adjacency graph, fixed core constraints, seed, and project facts.
Outputs are normalized into PLAN polygons, openings, routes, and basic-design
features before validation.

Adapters:

- `deterministic`: the current A/B/C baseline;
- `graph2plan`: official Graph2Plan inference isolated behind a subprocess
  boundary and its residential RPLAN domain recorded;
- `house_diffusion`: official vector denoising inference isolated behind the
  same boundary;
- `rlvr`: structured proposal generation plus deterministic verification;
- `mansion`: downstream multi-floor/3D evaluation only, never the authority
  for Korean 2D regulatory compliance.

Unavailable checkpoints, datasets, licenses, model size, or hardware produce
an explicit `unavailable` benchmark record. Paper concepts alone are never
labeled as paper-code execution.

## Review Loop

For each mass and seed:

1. generate at least three geometrically distinct alternatives;
2. normalize and validate all floors;
3. run regulatory screening with evidence;
4. render CAD-layered SVG, PNG, and direct-open HTML;
5. inspect metrics and visual evidence;
6. mutate only failed constraints and repeat within the iteration budget;
7. retain every iteration and a comparison index.

Selection cannot rank an unchecked regulatory result above a checked passing
result without showing the unresolved-fact penalty.

## Acceptance

- The sample manifest remains backward compatible and is visibly labeled
  `regulatory screening: not checked`.
- Unknown sprinkler state never receives the one-third separation exception.
- Explicit sprinkler true/false cases exercise one-third/one-half thresholds.
- Stair drawings match computed risers, treads, flights, landings, and width.
- All floors of a multi-floor mass are generated and reviewed.
- Alternatives differ in core, circulation, or tenant topology, not only
  labels.
- Each configured paper adapter either executes official code and records its
  environment or reports why it is unavailable.
- Full pytest, browser tests, loop-review, and original-resolution PNG
  inspection pass before completion is claimed.

## Primary Sources

- Korean Building Rule, Article 8:
  https://law.go.kr/LSW/lumLsLinkPop.do?chrClsCd=010202&lspttninfSeq=104954
- Korean Building Decree, Article 34 interpretation:
  https://www.law.go.kr/LSW/expcInfoP.do?expcSeq=329211&mode=2
- Korean stair-dimension interpretation:
  https://opinion.lawmaking.go.kr/nl4li/save/pdf/414174
- Graph2Plan official repository:
  https://github.com/HanHan55/Graph2plan
- HouseDiffusion paper:
  https://arxiv.org/abs/2211.13287
- RLVR floorplan paper:
  https://arxiv.org/abs/2605.14117
- MANSION paper:
  https://arxiv.org/abs/2603.11554
