# Irregular Mass Alternative Design

## Goal

Generate and visually compare genuinely different concept-basic floor-plan
families for a difficult non-orthogonal, concave, multi-floor mass. A candidate
is not distinct when it only swaps room labels inside fixed core and corridor
geometry.

## Test Mass

Add one deterministic three-floor manifest:

- Floor 1: concave 12-vertex footprint with diagonal edges, a deep notch, and
  unequal wings.
- Floor 2: setback version that preserves only part of the floor-1 boundary.
- Floor 3: reduced footprint with a shifted notch and a shorter diagonal wing.
- The common region must still fit one shared vertical core and the required
  protected stair geometry.
- Street and access evidence must be mapped to each floor boundary explicitly.

The fixture must be large enough for the existing office program and concept
furniture, but difficult enough that bounding-box zoning leaves measurable
unused area.

## Module Boundaries

### `core_planner`

Owns shared vertical-core candidate generation and selection.

Input:

- floor boundaries
- required core area and minimum dimensions
- stair enclosure dimensions
- optional strategy id

Output:

- immutable `CoreCandidate`
- polygon
- strategy: `central`, `notch_adjacent`, or `long_edge_adjacent`
- per-floor containment evidence
- geometry fingerprint

It does not place rooms or render drawings.

### `circulation_planner`

Owns corridor and remote-stair topology for one selected core.

Input:

- floor boundary
- `CoreCandidate`
- frontage/access segments
- minimum corridor width

Output:

- immutable `CirculationCandidate`
- corridor polygons
- remote-stair polygon
- entrance-to-core connectivity evidence
- topology fingerprint

It does not resize the program.

### `space_planner`

Uses the existing orthogonal/rear-center generators through a narrow adapter.
It assigns program nodes to the residual cells produced by one core and
circulation candidate.

Output contains a room-assignment fingerprint separate from the structural
fingerprints.

### `alternative_composer`

Builds a bounded set of alternatives:

1. central core + connected corridor family
2. notch-adjacent core + connected corridor family
3. long-edge-adjacent core + connected corridor family

It rejects duplicate triples:

`(core fingerprint, circulation fingerprint, room fingerprint)`.

The first implementation produces at most three validated families. It does
not generate a Cartesian explosion.

## Data Flow

1. Analyze every floor-specific polygon.
2. Compute the common feasible core region.
3. Produce up to three core strategies.
4. Produce one valid circulation/stair candidate for each core.
5. Fit the deterministic program into each residual floor region.
6. Run existing area, overlap, access, egress, basic-design, and render
   validation.
7. Keep only structurally distinct accepted candidates.
8. Write per-candidate PNG/SVG/HTML/JSON and one before/after comparison PNG.

The local LLM may rank or reorder program relationships, but it cannot assert
geometry or bypass deterministic validation.

## Failure Handling

- A core strategy that cannot fit all floors is rejected with typed evidence.
- A circulation candidate without entrance-to-core and stair connectivity is
  rejected.
- A floor with inaccessible residual cells is rejected instead of silently
  leaving large areas unclassified.
- Fewer than two accepted structural families makes the irregular-mass review
  command exit nonzero.
- Regulatory checks remain `not_checked` unless jurisdiction, effective date,
  occupancy, and travel facts are typed.

## Validation

Automated tests must prove:

- all three floor polygons are valid and non-orthogonal;
- every accepted core is inside every floor;
- at least two core fingerprints differ;
- at least two circulation fingerprints differ;
- room polygons remain inside their exact floor boundary;
- overlap is zero;
- frontage-required rooms touch the supplied street;
- core and stair routes are connected;
- duplicate room-label swaps do not count as structural alternatives;
- the review command writes at least two distinct PNG files.

## Visual Evidence

Save final evidence under:

`docs/irregular-mass-alternative-review-2026-07-29/`

Required files:

- `index.html`
- `comparison.png`
- `alternative-1.png`
- `alternative-2.png`
- optional `alternative-3.png`
- `alternatives.review.json`

The comparison page uses a white background and labels core strategy,
circulation fingerprint, validation score, and remaining limitations.

## Explicit Limits

- This is concept-basic planning, not construction documentation.
- Initial room geometry may remain axis-aligned inside the non-orthogonal
  envelope, but unused envelope area must be measured and reported.
- The first pass supports office use. Commercial follows after office produces
  at least two structurally distinct accepted families.
