# PLAN Module Map

PLAN is organized around a replaceable `Mass -> Program -> Precedent -> Layout -> Validation` loop.

## Runtime Boundary

- `backend/app/schemas`: stable data contracts.
- `backend/app/modules`: application services that orchestrate one capability each.
- `engine`: reusable geometry, graph, constraint, metric, and IO primitives.
- `backend/app/api`: thin route wrappers. V1 keeps them framework-neutral.
- `backend/app/cli.py`: CLI entrypoint for running the V1 loop.
- `backend/app/modules/generation_loop`: deterministic candidate operators, canonical geometry fingerprints, lexicographic ranking, lineage, and budget-aware termination.
- `backend/app/modules/visual_review`: writes SVG, PNG, HTML, per-iteration review JSON, and a run-level index for human-in-the-loop checking.
- `engine/geometry`: the sole Shapely boundary. Application code passes Python point lists and scalar measurements, never Shapely objects.

## Research Boundary

- `research/papers`: grouped paper sources and notes.
- `datasets/raw`: untouched inputs.
- `datasets/processed`: normalized images, vectors, graphs, and program data.
- `experiments`: isolated experiment outputs and configs.

## V1 Principle

The baseline generator is intentionally simple. It accepts only finite, simple,
positive-area single-ring polygons (a repeated closing vertex is normalized).
Holes, multipolygons, self-intersections, and zero-area rings are outside the
V1 contract. The important contract is that future Graph2Plan, HouseDiffusion,
DiffPlanner, FMLM, or RLVR modules can replace the generator without changing
the geometry, validation, search, or artifact schemas.

## Visual Review Loop

Use `python -m backend.app.cli loop-review --input datasets/manifests/sample_mass_office_commercial.json --floor 1 --use-type neighborhood_commercial --output-dir logs/runs/sample_review --max-iterations 5`.

Each iteration writes artifacts for the search `best_so_far` candidate:

- `*.svg`: browser-readable vector floor plan.
- `*.png`: raster snapshot for quick inspection.
- `*.html`: browser review page linking the artifacts.
- `*.review.json`: machine-readable pass/fail checks.
- `review.index.json`: deterministic run summary, per-iteration fingerprints,
  lineage, score and hard-failure trends, termination, and relative artifact links.
- `index.html`: accessible history table backed by the same run index.

The run index records aggregate `evaluation_count` and deduplication-aware
search history separately. It does not create visual artifacts for every
evaluated candidate.

Hard validity is separate from soft quality. A candidate is accepted only when
all hard gates pass: room identity and per-room area, valid contained geometry,
no interior overlap, and connected circulation with positive shared-wall access.
Adjacency, frontage, coverage, efficiency, and compactness remain advisory
scores. Ranking is deterministic: accepted state, hard-failure count, violation
score, total score, then the SHA-256 geometry fingerprint. Duplicate
fingerprints are not evaluated twice. Termination is one of `accepted`,
`search_exhausted`, `stagnated`, `evaluation_budget_exhausted`,
`iteration_budget_exhausted`, or `failed`; budget outcomes never imply
acceptance.
