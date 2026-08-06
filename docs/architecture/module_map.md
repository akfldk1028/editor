# PLAN Module Map

PLAN is organized around a replaceable `Mass -> Program -> Precedent -> Layout -> Validation` loop.

The canonical folder ownership and dependency rules are defined in
`docs/architecture/repository_layout.md`.

## Product Ownership

- `frontend`: PLANM user interface. It calls only the Backend HTTP API.
- `backend/app/api`: versioned HTTP routes and DTO boundaries.
- `backend/app/modules`: PLAN product logic, run ownership, artifacts, and stage execution.
- `backend/app/adapters`: thin process or loopback clients for PLANM Agent and DWG.
- `agents/planm`: PLANM identity, contracts, skills, workflows, memory, and process bridge.
- `external/gitagent-runtime`: generic Agent runtime; it imports no PLANM or DWG product code.
- `external/dwg-intelligence`: independent DWG Git submodule and process.
- `engine`: reusable geometry, graph, constraint, metric, and image primitives.

Deterministic product dependency direction:

`Frontend -> Backend -> PLANM GitAgent host -> discovered PLANM skill -> process bridge -> injected Backend execution service`

`Backend -> optional DWG process`

Always-on Agent hosting direction:

`generic GitAgent runtime API -> discover agents/planm workflow and stage skill`

The product API does not require an LLM provider. All PLANM stages traverse the
generic runtime discovery boundary. PLANM receives its Backend
engine command through the versioned process environment. It does not import
Backend modules or contain a Backend path.

## Runtime Boundary

- `backend/app/schemas`: stable data contracts.
- `backend/app/modules`: application services that orchestrate one capability each.
- `engine`: reusable geometry, graph, constraint, metric, and IO primitives.
- `backend/app/api`: thin route wrappers. V1 keeps them framework-neutral.
- `backend/app/cli.py`: CLI entrypoint for running the V1 loop.
- `backend/app/modules/generation_loop`: deterministic candidate operators, canonical geometry fingerprints, lexicographic ranking, lineage, and budget-aware termination.
- `backend/app/modules/llm_planner`: strict LLM JSON contracts, building-level
  floor assignment orchestration, and an OpenAI Responses API adapter.
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

Whole-building input may supply `floor_footprints` for every floor. When the
field is absent, the reference `footprint_polygon` is broadcast for backward
compatibility. The current deterministic office path supports simple
straight-edge single-ring floor plates, including L/U shapes, sloped
pentagons/hexagons, and floor-by-floor setbacks. Orthogonal plates use exact
cell decomposition. Plates with diagonal edges select one shared core, remote
stair, and axis-aligned planning region from the all-floor intersection while
retaining each floor's actual polygon for containment, review, and regulatory
measurements. The diagonal fringe outside that planning region can remain
unassigned, so this is a validated concept-basic fallback rather than full
polygon area planning. Holes, disconnected plates, curved edges, overhangs
outside the reference envelope, and automatic 3D-mass slicing remain
unsupported.

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

The run index records aggregate `evaluation_count` plus the rendered
per-iteration `best_so_far` history. It does not create visual artifacts or
per-candidate search history for every evaluated candidate.

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

## Whole-Building Review

Use the deterministic use-mix allocator:

`python -m backend.app.cli building-review --input datasets/manifests/sample_mass_office_commercial.json --output-dir logs/runs/sample_building_review`

Run the retained three-floor L-shaped setback fixture:

`python -m backend.app.cli building-review --input datasets/manifests/sample_mass_l_setback_office.json --output-dir docs/l-setback-review`

Run the retained two-floor sloped hexagonal setback fixture:

`python -m backend.app.cli building-review --input datasets/manifests/sample_mass_polygon_setback_office.json --output-dir docs/polygon-setback-review`

Use the OpenAI structured planner:

`python -m backend.app.cli building-review --input datasets/manifests/sample_mass_office_commercial.json --output-dir logs/runs/sample_building_review_llm --planner openai`

The LLM assigns one supported use type to every floor through strict JSON.
PLAN independently validates the response, generates all floors, aligns one
core polygon vertically, validates each floor, and writes a building index plus
per-floor SVG, PNG, HTML, and review JSON. LLM failure is not silently replaced
with deterministic output. See
`research/paper_cards/llm_hybrid_floorplan_generation.md` for the paper-code
evidence and current limits.
