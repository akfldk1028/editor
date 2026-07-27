# Credible Floorplan Review Loop Design

## Goal

Replace the current self-passing stripe baseline with a deterministic search
loop whose geometry checks, program checks, and review artifacts can expose
real layout failures and demonstrate measurable improvement between
iterations.

The first milestone is a trustworthy non-ML baseline. Training and model
integration remain out of scope until the evaluator and dataset contracts are
credible.

## Findings

The current implementation has four load-bearing defects:

1. Polygon containment and overlap use bounding boxes.
2. Area scoring compares only aggregate area, so room-level errors cancel.
3. Circulation always receives a score of `1.0` even when no circulation
   geometry exists.
4. `loop-review` calls the same deterministic generator repeatedly and does
   not feed validation failures into the next generation.

The sample vertical-stripe plan therefore receives a perfect score even though
it has no circulation and does not satisfy meaningful program relationships.
PNG output also draws room bounding boxes rather than room polygons.

## Research Basis

The design uses the following ideas without attempting to reproduce the
training architectures:

- Graph2Plan treats boundary, room count, location, and adjacency as explicit
  conditions, then aligns the generated rooms into a valid vector plan.
- HouseDiffusion represents rooms and doors as polygon loops and explicitly
  models geometric incidence such as shared corners and parallel edges.
- House-GAN++ measures condition compatibility with graph edit distance and
  uses iterative refinement to optimize a chosen metric.
- FMLM evaluates boundary-conditioned generation with region IoU and
  graph-conditioned generation with graph edit distance.
- DiffPlanner operates directly in vector space and aligns generation with an
  iterative design trajectory.

For this repository, these ideas become exact polygon predicates, room-level
area checks, graph-edge compatibility, boundary coverage, deterministic
candidate refinement, and explicit iteration lineage. FID and learned
perceptual metrics are deferred until a real dataset exists.

Primary sources:

- https://arxiv.org/abs/2004.13204
- https://arxiv.org/abs/2211.13287
- https://openaccess.thecvf.com/content/CVPR2021/html/Nauata_House-GAN_Generative_Adversarial_Layout_Refinement_Network_towards_Intelligent_Computational_Agent_CVPR_2021_paper.html
- https://arxiv.org/abs/2508.13738
- https://arxiv.org/abs/2604.04859

## Chosen Approach

Use Shapely behind the `engine.geometry` boundary for reliable simple-polygon
operations, and keep the application layer independent of Shapely types.
Generate multiple deterministic slicing layouts, validate each candidate, keep
the best candidates with a stable ranking, and apply violation-directed
operators in later iterations.

Two alternatives were rejected:

- A dependency-free polygon kernel would duplicate difficult topology and
  intersection-area logic while remaining less reliable on concave inputs.
- Model-first integration would optimize against the evaluator that currently
  awards false perfect scores.

## Architecture

### Geometry

`engine.geometry.polygon` accepts and returns only Python point lists and
numbers. It validates finite, simple, positive-area polygons; implements
containment with boundary sharing allowed; distinguishes positive-area overlap
from wall or point contact; and measures shared boundary length and union
coverage.

Holes and multipolygons are rejected in this milestone.

### Validation

Validation separates hard validity from soft quality.

Hard gates:

- all expected room IDs exist exactly once and no extra rooms exist;
- every room and circulation polygon is valid and covered by the footprint;
- room-room and circulation-circulation interiors do not overlap;
- room areas are within each program node's min/max range;
- circulation exists, is connected, and shares a non-zero wall segment with
  every required room.

Soft metrics:

- program adjacency edge satisfaction;
- frontage satisfaction for nodes marked `frontage_required`;
- footprint coverage;
- rentable efficiency;
- room compactness.

The report contains structured violation codes and subjects. Human-readable
messages remain presentation data and never drive search behavior.

### Candidate Search

The generator creates deterministic candidates from:

- X and Y stripes;
- original, reversed, frontage-first, and service-grouped room orders;
- balanced recursive guillotine partitions;
- pair swaps, split-axis rotation, and service grouping operators.

Each candidate has a canonical geometry fingerprint and lineage:
`iteration`, `parent_id`, `operator`, and `operator_params`.

Candidates are ranked lexicographically by:

1. accepted candidates first;
2. fewer hard violations;
3. lower normalized violation penalty;
4. higher total score;
5. fingerprint as a stable tie-break.

The next iteration receives the previous frontier and its structured
violations. Duplicate fingerprints are not evaluated twice.

Termination reasons are `accepted`, `search_exhausted`, `stagnated`,
`evaluation_budget_exhausted`, `iteration_budget_exhausted`, and `failed`.
Budget termination returns the best candidate but never labels it accepted.

### Review Artifacts

Each iteration writes SVG, PNG, HTML, and canonical review JSON from the same
polygon model. The PNG renderer fills real polygons with a scanline algorithm.
All text is escaped, identifiers are slugged for filenames, and artifact links
are relative to the run root.

The run root also contains `review.index.json` and `index.html` with candidate
lineage, hard-failure count, metric values, deltas, and termination reason.
`needs_iteration` is derived only from hard gates.

## Data Contracts

`ValidationReport` retains the existing score fields for compatibility and
adds:

- `accepted: bool`;
- `hard_violation_count: int`;
- `violation_score: float`;
- `violations: list[ValidationViolation]`;
- `room_areas: list[RoomAreaMetric]`;
- `adjacency_score`, `frontage_score`, `coverage_score`, and
  `compactness_score`;
- `policy_version: str`.

`LoopConfig` defines deterministic search budgets and seed.
`CandidateRecord`, `IterationRecord`, and `LoopResult` make the search state
serializable. No timestamp participates in fingerprints, ranking, or tests.

## Error Handling

Invalid mass or program input raises `ValueError` before search starts.
Invalid candidate geometry becomes a rejected validation report so other
candidates can continue. An unexpected validator or operator exception
terminates the run as `failed`; it is not silently converted into a weak
candidate.

Output dimensions, polygon counts, vertex counts, finite coordinates, slugged
paths, and output-root containment are checked before artifact creation.

## Testing

All production behavior is developed test-first.

Geometry tests cover concave containment, disjoint polygons with overlapping
bounding boxes, shared-wall contact, positive-area overlap, self-intersection,
zero area, closed rings, winding order, and non-finite coordinates.

Validator tests cover room-level area cancellation, room identity, missing
circulation, disconnected circulation, room access, adjacency, frontage,
coverage, and the rejection of the existing stripe baseline.

Search tests prove stable ranking, fingerprint deduplication, differing
geometry across failed iterations, monotonic best-so-far ranking, every
termination reason, and identical results across repeated runs.

Artifact tests inspect pixels outside an L-shaped polygon but inside its
bounding box, validate escaped content and relative paths, and verify index
deltas and links. The full CLI sample must finish with a non-false-positive
report and reproducible JSON.

## Delivery Boundaries

Work is split into independently reviewed changes:

1. geometry and validator;
2. polygon artifact rendering and artifact safety;
3. candidate generation and deterministic search;
4. visual loop integration, run index, and CLI;
5. research documentation and end-to-end verification.

