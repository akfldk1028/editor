# Irregular Mass Alternatives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce at least two validated concept-basic office alternatives with different core and circulation geometry for one concave, non-orthogonal, three-floor mass, then retain PNG comparison evidence.

**Architecture:** Extract shared-core candidate ownership from the monolithic generation loop into `core_planner`, extract corridor and stair topology ownership into `circulation_planner`, and combine bounded structural strategies in `alternative_composer`. Existing program, basic-design, validator, and renderer modules remain the downstream authorities.

**Tech Stack:** Python 3.11, dataclasses, Shapely, pytest, existing PLAN SVG/PNG/HTML renderers.

## Global Constraints

- Use one deterministic three-floor, concave, non-orthogonal 12-vertex mass with floor-specific setbacks.
- Produce at most three candidate families: `central`, `notch_adjacent`, and `long_edge_adjacent`.
- A distinct alternative requires a different `(core, circulation, room)` fingerprint triple.
- Keep the local LLM outside geometry authority; deterministic geometry and validators remain authoritative.
- Fewer than two accepted structural families makes the irregular review command exit nonzero.
- Save white-background PNG/HTML/JSON evidence under `docs/irregular-mass-alternative-review-2026-07-29/`.
- Preserve existing unrelated untracked files.
- Add no external runtime dependency.

---

### Task 1: Irregular Fixture And Core Planner

**Files:**
- Create: `resources/datasets/manifests/sample_mass_irregular_12v_setback_office.json`
- Create: `backend/app/modules/core_planner/__init__.py`
- Create: `backend/app/modules/core_planner/contracts.py`
- Create: `backend/app/modules/core_planner/service.py`
- Create: `backend/tests/test_core_planner.py`

**Interfaces:**
- Consumes: `tuple[tuple[Point, ...], ...]` floor boundaries, `required_area: float`, `minimum_width: float`, `minimum_depth: float`.
- Produces: `CoreCandidate(strategy: str, polygon: tuple[Point, ...], fingerprint: str, contained_floor_indices: tuple[int, ...])`.
- Produces: `generate_shared_core_candidates(...) -> tuple[CoreCandidate, ...]`.

- [ ] **Step 1: Write the failing fixture and core-candidate tests**

```python
def test_irregular_fixture_has_three_distinct_nonorthogonal_concave_floors():
    mass = load_manifest("sample_mass_irregular_12v_setback_office.json")
    boundaries = tuple(mass.footprint_for_floor(i) for i in range(1, 4))
    assert all(len(boundary) == 12 for boundary in boundaries)
    assert all(not is_axis_aligned(boundary) for boundary in boundaries)
    assert all(Polygon(boundary).is_valid and not Polygon(boundary).equals(Polygon(boundary).convex_hull) for boundary in boundaries)


def test_core_planner_returns_structurally_distinct_shared_candidates():
    candidates = generate_shared_core_candidates(
        boundaries,
        required_area=72.0,
        minimum_width=7.6,
        minimum_depth=5.2,
    )
    assert len(candidates) >= 2
    assert len({candidate.fingerprint for candidate in candidates}) == len(candidates)
    assert all(
        all(Polygon(boundary).covers(Polygon(candidate.polygon)) for boundary in boundaries)
        for candidate in candidates
    )
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest -q backend/tests/test_core_planner.py
```

Expected: collection fails because `core_planner` does not exist.

- [ ] **Step 3: Implement immutable contracts and bounded candidate strategies**

Implement `CoreCandidate.__post_init__` validation for supported strategy ids,
valid rectangular polygons, non-empty SHA-256 fingerprint, and complete floor
containment evidence. Generate representative feasible rectangles from the
common polygon region, classify them by centroid distance to common centroid,
distance to concave notch vertices, and distance to the longest exterior edge,
then keep at most one candidate per strategy.

- [ ] **Step 4: Run tests and verify GREEN**

```powershell
python -m pytest -q backend/tests/test_core_planner.py
python -m ruff check backend/app/modules/core_planner backend/tests/test_core_planner.py
```

- [ ] **Step 5: Commit**

```powershell
git add resources/datasets/manifests/sample_mass_irregular_12v_setback_office.json backend/app/modules/core_planner backend/tests/test_core_planner.py
git commit -m "feat: add irregular shared core planner"
```

---

### Task 2: Circulation Planner

**Files:**
- Create: `backend/app/modules/circulation_planner/__init__.py`
- Create: `backend/app/modules/circulation_planner/contracts.py`
- Create: `backend/app/modules/circulation_planner/service.py`
- Create: `backend/tests/test_circulation_planner.py`
- Modify: `backend/app/modules/layout_generator/orthogonal.py`

**Interfaces:**
- Consumes: exact floor boundary, `CoreCandidate`, street/access segments, `minimum_width=1.2`, and stair dimensions.
- Produces: `CirculationCandidate(strategy: str, polygons: tuple[tuple[Point, ...], ...], remote_stair_polygon: tuple[Point, ...], fingerprint: str, entrance_connected: bool, core_connected: bool, stair_connected: bool)`.
- Produces: `generate_circulation_candidate(...) -> CirculationCandidate`.
- Existing orthogonal layout receives an optional fixed `CirculationCandidate`; when supplied it must not regenerate corridor/stair geometry.

- [ ] **Step 1: Write failing connectivity and fingerprint tests**

```python
@pytest.mark.parametrize("core_index", [0, 1])
def test_circulation_connects_entrance_core_and_remote_stair(core_index):
    candidate = generate_circulation_candidate(
        floor_boundary=BOUNDARIES[0],
        core=CORE_CANDIDATES[core_index],
        street_segments=STREETS,
        minimum_width=1.2,
        stair_dimensions=((2.8, 4.92), (4.92, 2.8)),
    )
    assert candidate.entrance_connected
    assert candidate.core_connected
    assert candidate.stair_connected
    assert Polygon(BOUNDARIES[0]).covers(Polygon(candidate.remote_stair_polygon))


def test_different_core_families_produce_different_circulation_fingerprints():
    assert first.fingerprint != second.fingerprint
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest -q backend/tests/test_circulation_planner.py
```

Expected: collection fails because `circulation_planner` does not exist.

- [ ] **Step 3: Implement corridor and stair topology extraction**

Move reusable corridor-network and remote-stair selection behavior behind
`generate_circulation_candidate`. Keep rectangle decomposition helpers in
`layout_generator` until a second consumer needs them. Canonicalize corridor
polygons before hashing. Reject disconnected or boundary-crossing candidates
with `CirculationPlanningError`.

- [ ] **Step 4: Add fixed-circulation adapter support**

Add:

```python
generate_orthogonal_office_layout(
    ...,
    circulation_candidate: CirculationCandidate | None = None,
) -> LayoutCandidate
```

When supplied, use its polygons and remote stair exactly. Existing calls with
`None` preserve current behavior.

- [ ] **Step 5: Run focused regressions**

```powershell
python -m pytest -q backend/tests/test_circulation_planner.py backend/tests/test_orthogonal_layout_generator.py backend/tests/test_building_generation.py
python -m ruff check backend/app/modules/circulation_planner backend/app/modules/layout_generator/orthogonal.py backend/tests/test_circulation_planner.py
```

- [ ] **Step 6: Commit**

```powershell
git add backend/app/modules/circulation_planner backend/app/modules/layout_generator/orthogonal.py backend/tests/test_circulation_planner.py
git commit -m "feat: extract circulation candidate planner"
```

---

### Task 3: Structural Alternative Composer

**Files:**
- Create: `backend/app/modules/alternative_composer/__init__.py`
- Create: `backend/app/modules/alternative_composer/contracts.py`
- Create: `backend/app/modules/alternative_composer/service.py`
- Create: `backend/tests/test_alternative_composer.py`
- Modify: `backend/app/modules/generation_loop/service.py`

**Interfaces:**
- Consumes: `MassInput`, office `ProgramGraph`, `CoreCandidate` records, and per-floor `CirculationCandidate` records.
- Produces: `StructuralAlternative(strategy, building, core_fingerprint, circulation_fingerprint, room_fingerprint, structural_fingerprint)`.
- Produces: `generate_structural_alternatives(mass, *, use_type="office", limit=3) -> tuple[StructuralAlternative, ...]`.
- `run_building_generation` gains optional immutable core/circulation overrides and remains the single building validator path.

- [ ] **Step 1: Write failing structural-distinctness tests**

```python
def test_irregular_mass_produces_two_accepted_structural_families():
    alternatives = generate_structural_alternatives(MASS, use_type="office", limit=3)
    assert len(alternatives) >= 2
    assert all(item.building.accepted for item in alternatives)
    assert len({item.core_fingerprint for item in alternatives}) >= 2
    assert len({item.circulation_fingerprint for item in alternatives}) >= 2


def test_room_label_swap_does_not_create_structural_family():
    deduplicated = deduplicate_structural_alternatives((original, label_swap))
    assert deduplicated == (original,)
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest -q backend/tests/test_alternative_composer.py
```

Expected: collection fails because `alternative_composer` does not exist.

- [ ] **Step 3: Add building-generation overrides**

Add keyword-only override contracts to `run_building_generation`:

```python
core_override: CoreCandidate | None = None
circulation_overrides: Mapping[int, CirculationCandidate] | None = None
```

Validate identity, containment, floor keys, and shared-core equality before
layout generation. Route supplied circulation polygons to the orthogonal
adapter.

- [ ] **Step 4: Implement bounded composition and fingerprints**

Generate one building per core strategy, reject failed strategies with typed
reason records, and deduplicate by structural fingerprint:

```python
sha256(
    f"{core_fingerprint}:{circulation_fingerprint}:{room_fingerprint}".encode()
).hexdigest()
```

Sort accepted alternatives by hard violations, violation score, negative total
score, and strategy id.

- [ ] **Step 5: Run focused and broad regressions**

```powershell
python -m pytest -q backend/tests/test_alternative_composer.py backend/tests/test_building_generation.py backend/tests/test_orthogonal_layout_generator.py
python -m ruff check backend/app/modules/alternative_composer backend/app/modules/generation_loop/service.py backend/tests/test_alternative_composer.py
```

- [ ] **Step 6: Commit**

```powershell
git add backend/app/modules/alternative_composer backend/app/modules/generation_loop/service.py backend/tests/test_alternative_composer.py
git commit -m "feat: compose structural floor plan alternatives"
```

---

### Task 4: Irregular Review CLI And PNG Evidence

**Files:**
- Modify: `backend/app/cli.py`
- Modify: `backend/tests/test_cli.py`
- Create: `docs/irregular-mass-alternative-review-2026-07-29/index.html`
- Create: `docs/irregular-mass-alternative-review-2026-07-29/comparison.png`
- Create: `docs/irregular-mass-alternative-review-2026-07-29/alternatives.review.json`
- Create: candidate PNG files under the same directory.

**Interfaces:**
- Adds CLI command:

```powershell
python -m backend.app.cli irregular-alternatives-review `
  --input resources/datasets/manifests/sample_mass_irregular_12v_setback_office.json `
  --output-dir logs/runs/irregular_structural_alternatives `
  --limit 3
```

- Exits zero only when at least two accepted structural fingerprints and two PNG hashes exist.

- [ ] **Step 1: Write the failing CLI artifact test**

```python
def test_cli_irregular_review_writes_two_structurally_distinct_pngs(...):
    cli_module.main()
    report = json.loads((output / "alternatives.review.json").read_text())
    assert report["accepted_count"] >= 2
    assert report["distinct_core_count"] >= 2
    assert report["distinct_circulation_count"] >= 2
    assert len({sha256(path.read_bytes()).hexdigest() for path in output.glob("alternative-*.png")}) >= 2
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest -q backend/tests/test_cli.py -k irregular
```

Expected: argparse rejects unknown command `irregular-alternatives-review`.

- [ ] **Step 3: Implement CLI and review report**

Write per-candidate PNG/SVG/HTML/JSON through existing visual-review services.
The aggregate report records strategy ids, all three fingerprints, validation
scores, PNG paths, PNG SHA-256 hashes, rejected strategies, and unresolved
regulatory facts.

- [ ] **Step 4: Run real workflow**

```powershell
python -m backend.app.cli irregular-alternatives-review `
  --input resources/datasets/manifests/sample_mass_irregular_12v_setback_office.json `
  --output-dir logs/runs/irregular_structural_alternatives `
  --limit 3
```

Inspect every PNG. Do not accept the run based on exit status alone.

- [ ] **Step 5: Build and inspect comparison PNG**

Create a white-background HTML comparison page and capture it at 1600 px width.
Copy the exact run PNGs and aggregate JSON into
`docs/irregular-mass-alternative-review-2026-07-29/`. Confirm copied SHA-256
values match the run artifacts.

- [ ] **Step 6: Run verification**

```powershell
python -m pytest -q
python -m ruff check backend
git diff --check
```

- [ ] **Step 7: Commit**

```powershell
git add backend/app/cli.py backend/tests/test_cli.py docs/irregular-mass-alternative-review-2026-07-29
git commit -m "feat: review irregular structural alternatives"
```
