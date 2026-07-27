# V1 Research Loop

## Goal

Build a practical research scaffold for neighborhood commercial and office mass-to-plan automation.

## Loop

1. Analyze JSON mass geometry.
2. Generate a baseline program graph by use type.
3. Retrieve similar precedents when dataset cases exist.
4. Generate a vector layout candidate.
5. Validate area, overlap, boundary adherence, circulation, and efficiency.
6. Render SVG, PNG, HTML, and JSON review artifacts.
7. Repeat generation and review until checks pass or the iteration budget is exhausted.

## Research Tracks

- Floorplan generation: Graph2Plan, HouseDiffusion, DiffPlanner, FMLM.
- Precedent retrieval: graph similarity and case-based retrieval.
- Shape grammar: master architect and typology priors.
- Chip/facility floorplanning: GNN and RL placement strategies.
- RLVR constraints: verifiable rewards for area and topology adherence.

## Practical Direction

Do not hardcode final office/commercial ratios as product truth. Use the baseline prior only as a fallback until real drawings produce empirical program distributions.

## Visual Acceptance

Numerical validation is not enough for practical floor planning. Every candidate should be reviewed through the visual artifact loop before it is treated as useful output.
