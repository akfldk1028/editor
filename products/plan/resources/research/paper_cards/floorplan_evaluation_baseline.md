# Floorplan Evaluation Baseline

## Scope

V1 is a deterministic, non-ML evaluation baseline. It validates a finite,
simple, positive-area polygon ring and writes review artifacts before model
integration. Shapely is isolated behind `backend.engine.geometry`; schemas and
application services exchange only Python coordinates, booleans, and numbers.

Hard validity is not a quality score. Room identity and per-room area,
contained valid geometry, positive-area overlap, and connected circulation with
shared-wall access decide acceptance. Adjacency, frontage, coverage,
efficiency, and compactness are soft quality metrics. A run preserves one
`best_so_far` candidate per rendered iteration with structured violations,
deterministic SHA-256 fingerprint, lineage, ranking inputs, and an explicit
termination reason; `evaluation_count` covers broader evaluated/deduplicated
search work without claiming per-candidate artifacts.

Current limitations are intentional: no holes, multipolygons, doors, or
minimum corridor width; concave-aware partition operators are pending. The
concave manifest tests that the bounding-rectangle operators do not receive a
false hard-valid result.

## Research Conditioning And Evaluation

### Graph2Plan

Graph2Plan conditions on a boundary plus room count, room locations, and graph
adjacency. V1 maps that idea to a validated footprint, program graph, and
explicit hard boundary/access checks before future vector-plan alignment.

Primary source: https://arxiv.org/abs/2004.13204

### HouseDiffusion

HouseDiffusion represents rooms and doors as polygon loops and accounts for
incidence such as shared corners and parallel edges. V1 keeps room polygons as
loops and measures overlap/shared boundaries exactly; door semantics and richer
incidence are deferred.

Primary source: https://arxiv.org/abs/2211.13287

### House-GAN++

House-GAN++ treats graph compatibility as graph edit distance and applies
iterative layout refinement against an objective. V1 retains a deterministic
analogue: structured graph/geometry violations direct operators, while stable
ranking and lineage make each rendered best-so-far refinement auditable.

Primary source: https://openaccess.thecvf.com/content/CVPR2021/html/Nauata_House-GAN_Generative_Adversarial_Layout_Refinement_Network_towards_Intelligent_Computational_Agent_CVPR_2021_paper.html

### DiffPlanner

DiffPlanner operates directly in vector space and follows an iterative design
trajectory. V1 likewise stores vector candidates, iteration records, and score
deltas, but does not claim a learned trajectory or diffusion quality.

Primary source: https://arxiv.org/abs/2508.13738

### FMLM

FMLM evaluates boundary-conditioned generation with region IoU and
graph-conditioned generation with graph edit distance. These measures are
useful experimental proxies once a dataset exists; the exact V1 hard gates are
the product-safety baseline.

Primary source: https://arxiv.org/abs/2604.04859

## Dataset Caveat

The cited residential benchmarks and their metrics are research proxies, not
office/commercial product truth. Product claims require representative
commercial drawings, domain-specific program constraints, doors, and corridor
width validation before learned-model comparisons are credible.
