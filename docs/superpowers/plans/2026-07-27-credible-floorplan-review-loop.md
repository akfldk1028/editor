# Credible Floorplan Review Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic floorplan search loop whose exact polygon validator, structured feedback, and review artifacts distinguish invalid stripe layouts from improving candidates.

**Architecture:** Shapely is isolated behind `engine.geometry` and supplies reliable simple-polygon predicates. The application layer generates deterministic slicing candidates, ranks them by structured validation, and writes canonical per-iteration and run-level review artifacts.

**Tech Stack:** Python 3.11+, dataclasses, Shapely 2.1.x, pytest, standard-library HTML/SVG/PNG generation.

## Global Constraints

- Preserve the existing CLI commands and score fields unless this plan explicitly extends them.
- Use TDD: add a failing behavior test and observe the expected failure before production changes.
- Search, ranking, fingerprints, and JSON output must be deterministic.
- Do not use timestamps or Python's randomized `hash()` in deterministic data.
- Support simple polygons only; reject holes, multipolygons, NaN, infinity, self-intersection, and zero-area rings.
- Hard validity and soft quality must remain separate.
- Human-readable messages must not control candidate selection.
- Do not add a learned model or dataset download.
- Do not modify or delete `.remember/`.

---

### Task 1: Exact Geometry And Structured Validator

**Files:**
- Modify: `pyproject.toml`
- Modify: `engine/geometry/polygon.py`
- Modify: `backend/app/schemas/metrics.py`
- Modify: `backend/app/modules/validator/service.py`
- Modify: `backend/tests/test_validator.py`
- Create: `backend/tests/test_geometry.py`

**Interfaces:**
- Produces: `validate_polygon(points, *, label="polygon") -> None`
- Produces: `contains_polygon(container, candidate) -> bool`
- Produces: `polygon_overlap_area(a, b) -> float`
- Produces: `shared_boundary_length(a, b) -> float`
- Produces: `union_area(polygons) -> float`
- Produces: `ValidationViolation`, `RoomAreaMetric`, and extended `ValidationReport`
- Preserves: `validate_layout(layout, program, boundary) -> ValidationReport`

- [ ] **Step 1: Add failing geometry tests**

Add tests proving that an L-shaped boundary rejects a room in its missing
corner, two triangles with overlapping bounding boxes but disjoint interiors
do not overlap, shared walls have zero overlap and positive shared length, and
self-intersecting/non-finite/zero-area polygons raise `ValueError`.

- [ ] **Step 2: Run geometry tests and verify the expected failures**

Run: `pytest backend/tests/test_geometry.py -q`
Expected: FAIL because the new polygon functions do not exist.

- [ ] **Step 3: Declare and implement the geometry boundary**

Declare `shapely>=2.1,<3` in `pyproject.toml`. Convert point lists to Shapely
polygons only inside `engine/geometry/polygon.py`; reject invalid inputs and
return Python numbers and booleans.

- [ ] **Step 4: Run geometry tests**

Run: `pytest backend/tests/test_geometry.py -q`
Expected: PASS.

- [ ] **Step 5: Add failing validator tests**

Add tests for per-room area cancellation, missing/extra/duplicate room IDs,
room and circulation boundary escape, missing/disconnected circulation,
positive shared-wall access, structured violation codes, and the current
generated stripe candidate being rejected for missing circulation.

- [ ] **Step 6: Run validator tests and verify expected failures**

Run: `pytest backend/tests/test_validator.py -q`
Expected: FAIL on the new hard-gate and structured-report assertions.

- [ ] **Step 7: Implement structured validation**

Add violation codes `invalid_geometry`, `room_identity`, `room_area`,
`boundary`, `overlap`, `circulation_missing`, `circulation_disconnected`, and
`room_inaccessible`. Preserve existing score fields. Set `accepted` and
`is_valid` only when every hard gate passes.

- [ ] **Step 8: Run focused and full tests**

Run: `pytest backend/tests/test_geometry.py backend/tests/test_validator.py -q`
Expected: PASS.

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 9: Commit**

Commit message: `feat: add exact floorplan validation`

### Task 2: Polygon Artifact Rendering And Safety

**Files:**
- Modify: `engine/io/png.py`
- Modify: `backend/app/schemas/visual.py`
- Modify: `backend/app/modules/visual_review/service.py`
- Modify: `backend/tests/test_visual_review.py`

**Interfaces:**
- Produces: `SimplePngCanvas.fill_polygon(points, color) -> None`
- Produces: `SimplePngCanvas.stroke_polygon(points, color, thickness=1) -> None`
- Preserves: `create_visual_review_artifacts(...) -> VisualReviewArtifacts`
- Consumes: existing `GenerationResult` and polygon point lists

- [ ] **Step 1: Add failing polygon raster and escaping tests**

Create an L-shaped room fixture. Assert that a pixel inside its bounding box
but outside the polygon remains white, a pixel inside is filled, SVG contains
the real points, injected room/project text is escaped, and artifact paths
cannot escape the output root.

- [ ] **Step 2: Run the focused tests and verify expected failures**

Run: `pytest backend/tests/test_visual_review.py -q`
Expected: FAIL because PNG uses rectangles and output text/path handling is
unsafe.

- [ ] **Step 3: Implement polygon rasterization and safe output**

Use an even-odd scanline fill and integer line drawing in `engine/io/png.py`.
Render boundary and rooms from their actual points in both PNG and SVG. Escape
HTML/XML text with the standard library, slug file stems, validate positive
viewport dimensions, and keep artifact links relative.

- [ ] **Step 4: Run focused and full tests**

Run: `pytest backend/tests/test_visual_review.py -q`
Expected: PASS.

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: render safe polygon review artifacts`

### Task 3: Deterministic Candidate Search

**Files:**
- Create: `backend/app/schemas/loop.py`
- Modify: `backend/app/schemas/result.py`
- Modify: `backend/app/modules/layout_generator/service.py`
- Create: `backend/app/modules/generation_loop/operators.py`
- Create: `backend/app/modules/generation_loop/selector.py`
- Modify: `backend/app/modules/generation_loop/service.py`
- Modify: `backend/tests/test_generation_loop.py`
- Create: `backend/tests/test_generation_operators.py`

**Interfaces:**
- Produces: `LoopConfig`, `CandidateRecord`, `IterationRecord`, `LoopResult`
- Produces: `layout_fingerprint(layout) -> str`
- Produces: `generate_initial_candidates(analysis, program) -> list[LayoutCandidate]`
- Produces: `refine_candidates(frontier, reports, analysis, program, iteration) -> list[LayoutCandidate]`
- Produces: `rank_candidate(record) -> tuple`
- Produces: `run_candidate_search(mass, floor_index, use_type, config) -> LoopResult`
- Consumes: Task 1 `ValidationReport.accepted`, violations, scores

- [ ] **Step 1: Add failing operator, fingerprint, and ranking tests**

Assert stable fingerprints across repeated processes, different fingerprints
for different geometry, duplicate elimination, accepted-first
lexicographic ranking, stable fingerprint tie-breaks, and distinct X/Y,
reversed, and balanced-guillotine candidates.

- [ ] **Step 2: Run the focused tests and verify expected failures**

Run: `pytest backend/tests/test_generation_operators.py -q`
Expected: FAIL because the search contracts and operators do not exist.

- [ ] **Step 3: Implement deterministic candidates and selection**

Canonicalize room IDs and rounded coordinates before SHA-256 fingerprinting.
Generate stripe and balanced recursive guillotine candidates with explicit
lineage. Rank by accepted state, hard violation count, violation score,
negative total score, and fingerprint.

- [ ] **Step 4: Run operator tests**

Run: `pytest backend/tests/test_generation_operators.py -q`
Expected: PASS.

- [ ] **Step 5: Add failing search-loop tests**

Use small deterministic fixtures to assert feedback-directed refinement,
best-so-far monotonicity, no duplicate evaluation, and termination reasons
`accepted`, `search_exhausted`, `stagnated`,
`evaluation_budget_exhausted`, and `iteration_budget_exhausted`.

- [ ] **Step 6: Run search tests and verify expected failures**

Run: `pytest backend/tests/test_generation_loop.py -q`
Expected: FAIL because `run_candidate_search` is not implemented.

- [ ] **Step 7: Implement the search state machine**

Analyze mass and program once. Evaluate each novel candidate once, retain a
stable beam, pass frontier reports into refinement, track lineage and
iteration records, and return best-so-far without marking budget exhaustion
as accepted.

- [ ] **Step 8: Run focused and full tests**

Run: `pytest backend/tests/test_generation_operators.py backend/tests/test_generation_loop.py -q`
Expected: PASS.

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 9: Commit**

Commit message: `feat: add deterministic layout search`

### Task 4: Review Loop Integration And Run Index

**Files:**
- Modify: `backend/app/schemas/visual.py`
- Modify: `backend/app/modules/visual_review/service.py`
- Modify: `backend/app/cli.py`
- Modify: `backend/tests/test_visual_review.py`
- Modify: `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: Task 3 `LoopResult` and iteration/candidate records
- Produces: per-iteration canonical `*.review.json`
- Produces: run-level `review.index.json` and `index.html`
- Preserves: CLI `review` and `loop-review`

- [ ] **Step 1: Add failing review-index and CLI tests**

Assert per-iteration candidate fingerprint and lineage, structured checks,
score delta, hard-failure count, run termination reason, relative links, and
that a failing first candidate followed by an improved candidate produces two
distinct artifact sets.

- [ ] **Step 2: Run focused tests and verify expected failures**

Run: `pytest backend/tests/test_visual_review.py backend/tests/test_cli.py -q`
Expected: FAIL because no run index or search lineage exists.

- [ ] **Step 3: Integrate candidate search with artifact generation**

Make `loop-review` consume `run_candidate_search`. Write one artifact set per
recorded best candidate, derive `needs_iteration` only from hard validity, and
write deterministic run-level JSON plus an accessible HTML score/history
table.

- [ ] **Step 4: Run focused and full tests**

Run: `pytest backend/tests/test_visual_review.py backend/tests/test_cli.py -q`
Expected: PASS.

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: integrate iterative review history`

### Task 5: Research Notes And End-To-End Acceptance

**Files:**
- Modify: `docs/architecture/module_map.md`
- Modify: `docs/research_plan/v1_research_loop.md`
- Modify: `docs/schemas/v1_contracts.md`
- Create: `research/paper_cards/floorplan_evaluation_baseline.md`
- Create: `datasets/manifests/sample_mass_concave.json`
- Modify: `backend/tests/test_cli.py`

**Interfaces:**
- Documents: geometry policy, hard/soft metrics, search policy, termination,
  artifact schema, and deferred ML benchmark
- Verifies: rectangular and concave sample CLI runs

- [ ] **Step 1: Add failing end-to-end CLI assertions**

Assert both sample manifests produce parseable `review.index.json`, distinct
candidate fingerprints when iteration occurs, a truthful acceptance state,
and existing SVG/PNG/HTML/JSON paths.

- [ ] **Step 2: Run the CLI tests and verify expected failures**

Run: `pytest backend/tests/test_cli.py -q`
Expected: FAIL until the concave fixture and final contracts exist.

- [ ] **Step 3: Add the concave fixture and research documentation**

Document Graph2Plan boundary/graph conditioning, HouseDiffusion vector loops,
House-GAN++ compatibility/refinement, DiffPlanner vector iteration, and FMLM
IoU/GED evaluation. Clearly mark residential-dataset metrics as research
proxies rather than office/commercial product truth.

- [ ] **Step 4: Run all automated verification**

Run: `pytest -q`
Expected: PASS with no failures.

Run:
`python -m backend.app.cli loop-review --input datasets/manifests/sample_mass_office_commercial.json --floor 1 --use-type neighborhood_commercial --output-dir logs/runs/final_rect --max-iterations 5`

Run:
`python -m backend.app.cli loop-review --input datasets/manifests/sample_mass_concave.json --floor 1 --use-type office --output-dir logs/runs/final_concave --max-iterations 5`

Expected: both commands exit zero, write run indexes, and do not award a
perfect hard-validity report to a candidate with missing circulation.

- [ ] **Step 5: Inspect generated PNG and JSON**

Open both final PNGs and confirm non-empty polygon rendering. Read both run
indexes and confirm termination reason, hard failures, score trend, lineage,
and artifact links agree with the files on disk.

- [ ] **Step 6: Commit**

Commit message: `docs: define credible floorplan evaluation baseline`

