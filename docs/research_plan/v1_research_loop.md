# V1 Research Loop

## Goal

Build a practical research scaffold for neighborhood commercial and office mass-to-plan automation.

## Loop

1. Analyze JSON mass geometry.
2. Generate a baseline program graph by use type.
3. Retrieve similar precedents when dataset cases exist.
4. Generate a vector layout candidate.
5. Reject invalid geometry and validate room identity, per-room area, overlap,
   boundary adherence, and circulation independently from soft quality.
6. Render SVG, PNG, HTML, and JSON review artifacts.
7. Rank deterministic candidates, preserve lineage and fingerprints, then repeat
   generation and review until hard validity passes or a truthful termination
   condition is reached.

## Research Tracks

- Floorplan generation: Graph2Plan boundary/room/adjacency conditioning;
  HouseDiffusion polygon loops and incidence; House-GAN++ graph compatibility
  and iterative refinement; DiffPlanner direct-vector iterative trajectories;
  FMLM boundary IoU and graph edit distance.
- Precedent retrieval: graph similarity and case-based retrieval.
- Shape grammar: master architect and typology priors.
- Chip/facility floorplanning: GNN and RL placement strategies.
- RLVR constraints: verifiable rewards for area and topology adherence.

## Practical Direction

Do not hardcode final office/commercial ratios as product truth. Use the baseline prior only as a fallback until real drawings produce empirical program distributions.

## Visual Acceptance

Numerical validation is not enough for practical floor planning. Every candidate should be reviewed through the visual artifact loop before it is treated as useful output.

## Evaluation Baseline

Exact simple-polygon predicates are isolated in `engine.geometry`; Shapely is
not an application or schema dependency. The V1 evaluator rejects non-finite,
self-intersecting, zero-area, hole, and multipolygon inputs. It intentionally
does not yet model holes, doors, minimum corridor widths, or concave-aware
partition operators.

`ValidationReport.accepted` is a hard-validity result, not a score threshold.
Hard failures are structured by code and subject so refinement can use them;
human-readable messages are presentation only. Area, overlap, boundary,
circulation, adjacency, frontage, coverage, efficiency, and compactness scores
remain separately serializable to support comparison without masking invalid
layouts.

The research literature uses predominantly residential data and evaluation.
Its boundary IoU, graph edit distance, and related metrics are therefore
research proxies for office/commercial work, not product truth. V1 uses them
to frame future experiments only after a representative commercial dataset,
door model, and corridor rules exist.
