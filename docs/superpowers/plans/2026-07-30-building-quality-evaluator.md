# Building Quality Evaluator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent, deterministic building-quality evaluator that measures daylight proxy, room form, vertical stacking, egress, and alternative diversity, then makes the structural composer and review artifacts consume the same versioned report.

**Architecture:** A new `building_quality` package consumes immutable `BuildingGenerationResult` evidence and returns a frozen `BuildingQualityReport`. It never calls or imports a generator. `alternative_composer` is the first policy consumer, while the CLI only serializes the report and retained artifacts.

**Tech Stack:** Python 3.11+, frozen dataclasses, Shapely 2.1+, pytest, Ruff, existing PLAN schemas and visual-review renderer.

## Global Constraints

- Preserve the dependency direction documented in `docs/superpowers/specs/2026-07-30-building-quality-design.md`.
- Do not add quality rules to `validator/service.py`.
- Do not import private validator functions.
- Do not let a generator import `building_quality`.
- Reuse existing `ValidationReport`, `BasicDesignFeatures`, `RegulatoryScreening`, and `FloorEgressGraphResult` evidence.
- Treat legal context that is not explicitly supplied as unresolved; never infer compliance.
- A hard failure cannot be offset by a weighted score.
- Use deterministic ordering and stable numeric rounding.
- Use TDD for every behavior change and commit each completed task separately.
- Leave unrelated untracked artifacts untouched.

## Test Fixture Contract

Unit tests use a shared factory rather than invoking the expensive real
generator:

```text
backend/tests/building_quality_fixtures.py
```

It exposes:

```python
def make_floor_result(
    *,
    floor_index: int = 1,
    use_type: str = "office",
    boundary: tuple[Point, ...],
    rooms: tuple[RoomPolygon, ...],
    room_areas: tuple[RoomAreaMetric, ...],
    room_shapes: tuple[RoomShapeMetric, ...],
    basic_design: BasicDesignFeatures,
    coverage: float = 1.0,
    screening: RegulatoryScreening | None = None,
    egress_graph: FloorEgressGraphResult | None = None,
) -> GenerationResult: ...


def make_building_result(
    floors: tuple[GenerationResult, ...],
    *,
    vertical_core_aligned: bool = True,
    vertical_basic_design_aligned: bool = True,
    vertical_structure_aligned: bool = True,
) -> BuildingGenerationResult: ...


def shifted_polygon(
    polygon: tuple[Point, ...],
    dx: float,
    dy: float,
) -> tuple[Point, ...]: ...
```

Each test file may define named wrappers such as `_office_floor` or
`_passing_building`, but those wrappers must call these factories and show all
geometry/evidence relevant to the assertion. Tests must not monkeypatch a
measurement function merely to make a policy test pass.

---

### Task 1: Immutable Contracts and Versioned Policy

**Files:**
- Create: `backend/app/modules/building_quality/__init__.py`
- Create: `backend/app/modules/building_quality/contracts.py`
- Create: `backend/app/modules/building_quality/policy.py`
- Create: `backend/tests/test_building_quality_contracts.py`
- Create: `backend/tests/building_quality_fixtures.py`

**Interfaces:**
- Produces: `QualityPolicy`, `QualityIssue`, `FloorQualityMetrics`, `VerticalQualityMetrics`, `BuildingQualityReport`, `AlternativeDiversityReport`.
- Produces: `DEFAULT_QUALITY_POLICY`.
- Consumes: no planning-module implementation.

- [ ] **Step 1: Write failing contract tests**

```python
def test_default_policy_is_frozen_complete_and_normalized():
    policy = DEFAULT_QUALITY_POLICY

    assert policy.version == "building-quality/v1"
    assert policy.minimum_floor_coverage == 0.60
    assert policy.minimum_primary_daylight_ratio == 0.70
    assert policy.minimum_room_form_pass_ratio == 0.90
    assert policy.minimum_core_stack_ratio == 0.95
    assert policy.minimum_service_stack_ratio == 0.70
    assert policy.minimum_pairwise_diversity == 0.25
    assert sum(policy.weights.values()) == pytest.approx(1.0)
    with pytest.raises(TypeError):
        policy.weights["daylight"] = 0.0


@pytest.mark.parametrize("value", [True, math.nan, math.inf, -0.1, 1.1])
def test_policy_rejects_invalid_ratio(value):
    with pytest.raises((TypeError, ValueError)):
        replace(DEFAULT_QUALITY_POLICY, minimum_floor_coverage=value)


def test_report_rejects_hard_pass_when_a_hard_issue_exists():
    issue = QualityIssue(
        code="daylight_proxy",
        severity="hard",
        floor_index=1,
        subject_id="open_work",
        measured_value=0.4,
        threshold=0.7,
        message="primary daylight proxy is below policy",
    )

    with pytest.raises(ValueError, match="hard_pass"):
        _report(hard_pass=True, issues=(issue,))
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest -q backend/tests/test_building_quality_contracts.py
```

Expected: import failure because `building_quality` does not exist.

- [ ] **Step 3: Implement exact immutable contracts**

Implement frozen dataclasses with these exact fields:

```python
@dataclass(frozen=True)
class QualityPolicy:
    version: str
    minimum_floor_coverage: float
    minimum_primary_daylight_ratio: float
    minimum_room_form_pass_ratio: float
    minimum_core_stack_ratio: float
    minimum_shaft_stack_ratio: float
    minimum_service_stack_ratio: float
    minimum_pairwise_diversity: float
    weights: Mapping[str, float]


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: Literal["hard", "soft", "unresolved"]
    floor_index: int | None
    subject_id: str | None
    measured_value: float | None
    threshold: float | None
    message: str


@dataclass(frozen=True)
class FloorQualityMetrics:
    floor_index: int
    coverage: float
    primary_daylight_ratio: float
    room_form_pass_ratio: float
    worst_aspect_ratio: float | None
    narrowest_room_width_m: float | None
    egress_status: Literal["pass", "fail", "not_checked"]


@dataclass(frozen=True)
class VerticalQualityMetrics:
    core_stack_ratio: float
    shaft_stack_ratio: float
    wet_service_stack_ratio: float
    maximum_service_centroid_shift_m: float | None


@dataclass(frozen=True)
class BuildingQualityReport:
    policy_version: str
    hard_pass: bool
    score: float
    component_scores: Mapping[str, float]
    floors: tuple[FloorQualityMetrics, ...]
    vertical: VerticalQualityMetrics
    issues: tuple[QualityIssue, ...]
    unresolved_facts: tuple[str, ...]


@dataclass(frozen=True)
class AlternativeDiversityReport:
    first_fingerprint: str
    second_fingerprint: str
    core_distance: float
    circulation_distance: float
    topology_distance: float
    area_distribution_distance: float
    total_distance: float
    nonzero_component_count: int
    quality_distinct: bool
```

Validate every string, tuple member, finite number, range, floor ordering, and
hard-pass consistency. Convert mapping inputs to `_ImmutableJsonDict`, following
the existing pattern in `backend/app/schemas/metrics.py`, so reports remain JSON
serializable without custom encoders.

- [ ] **Step 4: Define the default policy**

Use these exact weights:

```python
DEFAULT_QUALITY_POLICY = QualityPolicy(
    version="building-quality/v1",
    minimum_floor_coverage=0.60,
    minimum_primary_daylight_ratio=0.70,
    minimum_room_form_pass_ratio=0.90,
    minimum_core_stack_ratio=0.95,
    minimum_shaft_stack_ratio=0.90,
    minimum_service_stack_ratio=0.70,
    minimum_pairwise_diversity=0.25,
    weights={
        "daylight": 0.25,
        "room_form": 0.20,
        "vertical_stacking": 0.20,
        "egress": 0.20,
        "coverage_efficiency": 0.15,
    },
)
```

- [ ] **Step 5: Run focused tests and static checks**

```powershell
python -m pytest -q backend/tests/test_building_quality_contracts.py
python -m ruff check backend/app/modules/building_quality backend/tests/test_building_quality_contracts.py
git diff --check
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/modules/building_quality backend/tests/test_building_quality_contracts.py backend/tests/building_quality_fixtures.py
git commit -m "feat: define building quality policy"
```

---

### Task 2: Daylight Proxy and Room-Form Measurements

**Files:**
- Create: `backend/app/modules/building_quality/daylight.py`
- Create: `backend/app/modules/building_quality/room_form.py`
- Create: `backend/tests/test_building_quality_floor.py`

**Interfaces:**
- Consumes: `GenerationResult`.
- Produces: `measure_primary_daylight(floor) -> PrimaryDaylightMeasurement`.
- Produces: `measure_room_form(floor) -> RoomFormMeasurement`.
- Does not consume: `QualityPolicy`.

- [ ] **Step 1: Write failing daylight tests**

Construct a one-floor office `GenerationResult` with `open_work`, `meeting`,
`focus`, `core`, and one non-primary support room. Add window `PlanLine`
instances hosted by selected rooms.

```python
def test_daylight_proxy_is_area_weighted_and_requires_valid_exterior_window():
    floor = _office_floor(
        primary_areas={"open_work": 70, "meeting": 20, "focus": 10},
        exterior_windows={"open_work", "focus"},
    )

    measured = measure_primary_daylight(floor)

    assert measured.total_primary_area == pytest.approx(100)
    assert measured.served_primary_area == pytest.approx(80)
    assert measured.ratio == pytest.approx(0.80)
    assert measured.unserved_room_ids == ("meeting",)


def test_interior_or_mis_hosted_window_does_not_serve_primary_room():
    floor = _office_floor(
        primary_areas={"open_work": 70, "meeting": 20, "focus": 10},
        exterior_windows={"open_work"},
        invalid_windows={"meeting"},
    )

    measured = measure_primary_daylight(floor)

    assert measured.ratio == pytest.approx(0.70)
    assert measured.unserved_room_ids == ("focus", "meeting")


def test_missing_primary_program_area_is_rejected():
    with pytest.raises(ValueError, match="primary"):
        measure_primary_daylight(_floor_without_primary_rooms())
```

- [ ] **Step 2: Write failing room-form tests**

```python
def test_room_form_ratio_uses_actual_room_area_weighting():
    floor = _floor_with_shape_metrics(
        rooms={"open_work": 80, "meeting": 20},
        passing={"open_work"},
    )

    measured = measure_room_form(floor)

    assert measured.measured_area == pytest.approx(100)
    assert measured.passing_area == pytest.approx(80)
    assert measured.ratio == pytest.approx(0.80)
    assert measured.failing_room_ids == ("meeting",)


def test_unmeasurable_non_core_room_fails_room_form_measurement():
    floor = _floor_with_unmeasurable_shape("meeting")

    measured = measure_room_form(floor)

    assert measured.ratio < 1.0
    assert measured.unmeasurable_room_ids == ("meeting",)
```

- [ ] **Step 3: Run the tests and verify RED**

```powershell
python -m pytest -q backend/tests/test_building_quality_floor.py
```

Expected: imports fail because the measurement modules do not exist.

- [ ] **Step 4: Implement daylight measurement**

Define immutable internal result:

```python
@dataclass(frozen=True)
class PrimaryDaylightMeasurement:
    total_primary_area: float
    served_primary_area: float
    ratio: float
    served_room_ids: tuple[str, ...]
    unserved_room_ids: tuple[str, ...]
```

Primary types:

```python
_PRIMARY_TYPES = {
    "office": frozenset({"open_work", "meeting", "focus"}),
    "neighborhood_commercial": frozenset({"sales"}),
}
```

Use Shapely to check:

1. The room polygon is valid and has positive area.
2. A hosted `window` line exists.
3. The complete window line lies within the intersection of the room boundary
   and floor boundary, with `1e-6` tolerance.

Area comes from matching `ValidationReport.room_areas`, not a second polygon
area calculation.

- [ ] **Step 5: Implement room-form measurement**

Define:

```python
@dataclass(frozen=True)
class RoomFormMeasurement:
    measured_area: float
    passing_area: float
    ratio: float
    worst_aspect_ratio: float | None
    narrowest_width_m: float | None
    failing_room_ids: tuple[str, ...]
    unmeasurable_room_ids: tuple[str, ...]
```

Exclude only `space_type == "core"`. Match shapes and areas by `room_id`.
A room passes when both existing shape booleans are true and all applicable
measurements are finite.

- [ ] **Step 6: Run focused and existing validator tests**

```powershell
python -m pytest -q backend/tests/test_building_quality_floor.py
python -m pytest -q backend/tests/test_validator.py
python -m ruff check backend/app/modules/building_quality backend/tests/test_building_quality_floor.py
git diff --check
```

Expected: all pass.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/modules/building_quality backend/tests/test_building_quality_floor.py
git commit -m "feat: measure floor plan quality"
```

---

### Task 3: Vertical Stack and Egress Aggregation

**Files:**
- Create: `backend/app/modules/building_quality/vertical_stack.py`
- Create: `backend/app/modules/building_quality/egress.py`
- Create: `backend/tests/test_building_quality_building.py`

**Interfaces:**
- Consumes: `BuildingGenerationResult`.
- Produces: `measure_vertical_quality(building) -> VerticalQualityMetrics`.
- Produces: `aggregate_egress_quality(building) -> EgressQualityMeasurement`.

- [ ] **Step 1: Write failing stack tests**

```python
def test_vertical_stack_uses_worst_adjacent_floor_overlap():
    building = _three_floor_building(
        core_offsets=((0, 0), (0, 0), (1, 0)),
        shaft_offsets=((0, 0), (0, 0), (0.5, 0)),
        restroom_offsets=((0, 0), (0.5, 0), (3, 0)),
    )

    measured = measure_vertical_quality(building)

    assert measured.core_stack_ratio < 1.0
    assert measured.shaft_stack_ratio < 1.0
    assert measured.wet_service_stack_ratio < measured.core_stack_ratio
    assert measured.maximum_service_centroid_shift_m == pytest.approx(2.5)


def test_missing_required_shaft_scores_zero():
    building = _building_with_missing_shaft_on_floor(2)

    assert measure_vertical_quality(building).shaft_stack_ratio == 0.0
```

- [ ] **Step 2: Write failing egress tests**

```python
def test_checked_egress_failure_is_preserved():
    building = _building_with_screening(
        checks=("pass", "fail", "pass"),
        unresolved=(),
    )

    measured = aggregate_egress_quality(building)

    assert measured.status == "fail"
    assert measured.failed_floor_indexes == (1,)


def test_not_checked_egress_remains_unresolved():
    building = _building_with_screening(
        checks=("pass", "not_checked", "not_checked"),
        unresolved=("jurisdiction", "measured_travel_distance"),
    )

    measured = aggregate_egress_quality(building)

    assert measured.status == "not_checked"
    assert measured.unresolved_facts == (
        "jurisdiction",
        "measured_travel_distance",
    )
```

- [ ] **Step 3: Run the tests and verify RED**

```powershell
python -m pytest -q backend/tests/test_building_quality_building.py
```

Expected: missing-module import failures.

- [ ] **Step 4: Implement adjacent-floor stack measurement**

Use Shapely polygon intersection:

```python
ratio = intersection_area / min(first_area, second_area)
```

Measure core from `RoomPolygon.space_type == "core"`, shaft from
`BasicDesignFeatures.elements` where `kind == "shaft"`, and wet services from
room types `restroom`, `utility`, and `pantry`. Match multiple rooms by stable
space type and minimum centroid distance. The final ratio is the minimum over
adjacent floor pairs.

- [ ] **Step 5: Implement egress aggregation**

Define:

```python
@dataclass(frozen=True)
class EgressQualityMeasurement:
    status: Literal["pass", "fail", "not_checked"]
    checked_floor_indexes: tuple[int, ...]
    failed_floor_indexes: tuple[int, ...]
    unresolved_facts: tuple[str, ...]
```

Rules:

- Any contained `RegulatoryCheck.status == "fail"` produces aggregate `fail`.
- Aggregate `pass` requires every check on every floor to be `pass` and every
  screening to have no unresolved facts.
- Otherwise aggregate is `not_checked`.
- Preserve sorted, unique unresolved facts exactly.
- Missing `egress_graph` adds `measured_travel_distance`.

- [ ] **Step 6: Run relevant tests**

```powershell
python -m pytest -q backend/tests/test_building_quality_building.py
python -m pytest -q backend/tests/test_floor_evidence_integration.py backend/tests/test_egress_applicability.py
python -m ruff check backend/app/modules/building_quality backend/tests/test_building_quality_building.py
git diff --check
```

- [ ] **Step 7: Commit**

```powershell
git add backend/app/modules/building_quality backend/tests/test_building_quality_building.py
git commit -m "feat: measure building stack and egress"
```

---

### Task 4: Building Quality Service

**Files:**
- Create: `backend/app/modules/building_quality/service.py`
- Create: `backend/tests/test_building_quality_service.py`
- Modify: `backend/app/modules/building_quality/__init__.py`

**Interfaces:**
- Consumes: measurement functions from Tasks 2 and 3.
- Produces: `evaluate_building_quality(building, policy=DEFAULT_QUALITY_POLICY)`.

- [ ] **Step 1: Write failing service tests**

```python
def test_evaluator_returns_versioned_component_scores_and_hard_pass():
    building = _passing_building()

    report = evaluate_building_quality(building)

    assert report.policy_version == "building-quality/v1"
    assert report.hard_pass is True
    assert 0.0 <= report.score <= 1.0
    assert set(report.component_scores) == {
        "daylight",
        "room_form",
        "vertical_stacking",
        "egress",
        "coverage_efficiency",
    }
    assert not [issue for issue in report.issues if issue.severity == "hard"]


def test_hard_daylight_failure_cannot_be_offset_by_other_scores():
    building = _building_with_daylight_ratio(0.69)

    report = evaluate_building_quality(building)

    assert report.hard_pass is False
    assert any(
        issue.code == "primary_daylight_ratio"
        and issue.severity == "hard"
        and issue.measured_value == pytest.approx(0.69)
        and issue.threshold == pytest.approx(0.70)
        for issue in report.issues
    )


def test_unresolved_legal_context_does_not_become_pass_or_hard_failure():
    report = evaluate_building_quality(_building_with_unresolved_egress())

    assert "jurisdiction" in report.unresolved_facts
    assert any(issue.severity == "unresolved" for issue in report.issues)
    assert report.floors[0].egress_status == "not_checked"
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest -q backend/tests/test_building_quality_service.py
```

Expected: `evaluate_building_quality` import failure.

- [ ] **Step 3: Implement orchestration and issues**

For every floor, create hard issues for:

- `floor_coverage`
- `primary_daylight_ratio`
- `room_form_pass_ratio`
- `egress_checked_failure`

For the building, create hard issues for:

- `core_stack_ratio`
- `shaft_stack_ratio`

Create a soft issue for `wet_service_stack_ratio`. Convert unresolved egress
facts to `QualityIssue(severity="unresolved")`.

Component scores are normalized to `[0, 1]`. Egress component score is `1.0`
for pass, `0.0` for fail, and `0.5` for not checked. This numeric value does not
change the reported `not_checked` state.

Round public scores to four decimals after all comparisons. Keep raw
measurements for threshold comparisons.

- [ ] **Step 4: Run all building-quality tests**

```powershell
python -m pytest -q backend/tests/test_building_quality_contracts.py backend/tests/test_building_quality_floor.py backend/tests/test_building_quality_building.py backend/tests/test_building_quality_service.py
python -m ruff check backend/app/modules/building_quality backend/tests/test_building_quality_*.py
git diff --check
```

- [ ] **Step 5: Commit**

```powershell
git add backend/app/modules/building_quality backend/tests/test_building_quality_service.py
git commit -m "feat: evaluate building quality"
```

---

### Task 5: Semantic Alternative Diversity

**Files:**
- Create: `backend/app/modules/building_quality/diversity.py`
- Create: `backend/tests/test_building_quality_diversity.py`
- Modify: `backend/app/modules/building_quality/__init__.py`

**Interfaces:**
- Produces: `compare_building_diversity(first, second, policy=...)`.

- [ ] **Step 1: Write failing diversity tests**

```python
def test_coordinate_order_only_does_not_create_diversity():
    first = _building()
    second = _same_building_with_reversed_polygon_rings(first)

    report = compare_building_diversity(first, second)

    assert report.total_distance == 0.0
    assert report.nonzero_component_count == 0
    assert report.quality_distinct is False


def test_core_and_circulation_change_is_quality_distinct():
    first = _building(core_offset=(0, 0), corridor="horizontal")
    second = _building(core_offset=(8, 0), corridor="vertical")

    report = compare_building_diversity(first, second)

    assert report.core_distance > 0
    assert report.circulation_distance > 0
    assert report.nonzero_component_count >= 2
    assert report.total_distance >= DEFAULT_QUALITY_POLICY.minimum_pairwise_diversity
    assert report.quality_distinct is True


```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest -q backend/tests/test_building_quality_diversity.py
```

- [ ] **Step 3: Implement normalized components**

- Core: centroid distance normalized by the governing floor diagonal, averaged
  with normalized symmetric-difference area.
- Circulation: edge-set Jaccard distance, using sorted rounded endpoint pairs,
  averaged with a `0` or `1` orientation difference.
- Topology: Jaccard distance of room adjacency edges by `space_type`, ignoring
  room IDs.
- Area distribution: total variation distance of normalized area by
  `space_type`.

Use weights `0.30`, `0.25`, `0.25`, and `0.20`. Require total distance at least
the policy threshold and at least two component distances above `1e-6`.

- [ ] **Step 4: Run tests and checks**

```powershell
python -m pytest -q backend/tests/test_building_quality_diversity.py
python -m pytest -q backend/tests/test_core_planner.py backend/tests/test_circulation_planner.py
python -m ruff check backend/app/modules/building_quality backend/tests/test_building_quality_diversity.py
git diff --check
```

- [ ] **Step 5: Commit**

```powershell
git add backend/app/modules/building_quality backend/tests/test_building_quality_diversity.py
git commit -m "feat: measure alternative diversity"
```

---

### Task 6: Structural Composer Quality Integration

**Files:**
- Modify: `backend/app/modules/alternative_composer/contracts.py`
- Modify: `backend/app/modules/alternative_composer/service.py`
- Modify: `backend/app/modules/alternative_composer/__init__.py`
- Modify: `backend/tests/test_alternative_composer.py`

**Interfaces:**
- Consumes: `evaluate_building_quality`, `compare_building_diversity`.
- Produces: every `StructuralAlternative` with a required
  `quality_report: BuildingQualityReport`.
- Produces: quality rejection records through existing
  `StructuralAlternativeRejection`.

- [ ] **Step 1: Write failing integration tests**

```python
def test_composer_rejects_building_quality_hard_failure(monkeypatch):
    building = _alternatives()[0].building
    failing = _quality_report(
        hard_pass=False,
        hard_issue=("primary_daylight_ratio", 0.69, 0.70),
    )
    monkeypatch.setattr(
        alternative_service,
        "evaluate_building_quality",
        lambda building: failing,
    )

    composition = compose_structural_alternatives(_mass(), limit=3)

    assert not composition.alternatives
    assert any(
        rejection.reason_type == "BuildingQualityRejected"
        and "primary_daylight_ratio" in rejection.reason
        for rejection in composition.rejections
    )


def test_composer_ranks_quality_before_structural_tie_breaker():
    lower = _structural_alternative(quality_score=0.71)
    higher = _structural_alternative(quality_score=0.88)

    assert sorted((lower, higher), key=alternative_service._rank_key) == [
        higher,
        lower,
    ]


def test_composer_keeps_only_pairwise_quality_distinct_results(monkeypatch):
    monkeypatch.setattr(
        alternative_service,
        "compare_building_diversity",
        _controlled_diversity,
    )

    composition = compose_structural_alternatives(_mass(), limit=3)

    assert len(composition.alternatives) == 2
    assert all(item.quality_report.hard_pass for item in composition.alternatives)
```

- [ ] **Step 2: Run targeted tests and verify RED**

```powershell
python -m pytest -q backend/tests/test_alternative_composer.py -k "quality"
```

- [ ] **Step 3: Add report to the alternative contract**

Add:

```python
quality_report: BuildingQualityReport
```

Validate the type and require `quality_report.hard_pass is True`.

- [ ] **Step 4: Replace the composer-local coverage gate**

After `run_building_generation`, call `evaluate_building_quality`. When
`hard_pass` is false, append a `BuildingQualityRejected` rejection with sorted
`code:measured/threshold` evidence and continue. Do not retain the old duplicate
coverage block.

After core-family deduplication, select pairwise quality-distinct alternatives.
If fewer than two remain, preserve rejected families with
`AlternativeDiversityRejected`.

Selection starts with the highest building-quality score, then repeatedly
chooses the candidate maximizing its minimum diversity from already selected
candidates. Use `structural_fingerprint` as the final tie-breaker.

Update `_rank_key` to order by:

```python
(
    -alternative.quality_report.score,
    -building_total_validation_score,
    alternative.structural_fingerprint,
)
```

- [ ] **Step 5: Run composer and generation regression tests**

```powershell
python -m pytest -q backend/tests/test_alternative_composer.py
python -m pytest -q backend/tests/test_building_generation.py backend/tests/test_building_alternatives.py
python -m ruff check backend/app/modules/alternative_composer backend/tests/test_alternative_composer.py
git diff --check
```

- [ ] **Step 6: Commit**

```powershell
git add backend/app/modules/alternative_composer backend/tests/test_alternative_composer.py
git commit -m "feat: gate structural alternatives by quality"
```

---

### Task 7: Review JSON and HTML Evidence

**Files:**
- Modify: `backend/app/cli.py`
- Modify: `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `StructuralAlternative.quality_report`.
- Produces: JSON-safe `building_quality` and `pairwise_diversity` evidence.
- Keeps: existing PNG geometry and 1920 x 1080 output.

- [ ] **Step 1: Write failing CLI assertions**

Extend `test_cli_irregular_review_writes_two_structurally_distinct_pngs`:

```python
assert report["quality_policy_version"] == "building-quality/v1"
assert report["pairwise_diversity"]
for alternative in report["alternatives"]:
    quality = alternative["building_quality"]
    assert quality["hard_pass"] is True
    assert 0 <= quality["score"] <= 1
    assert set(quality["component_scores"]) == {
        "daylight",
        "room_form",
        "vertical_stacking",
        "egress",
        "coverage_efficiency",
    }
    assert quality["vertical"]["core_stack_ratio"] >= 0.95
    assert quality["vertical"]["shaft_stack_ratio"] >= 0.90
    for floor in quality["floors"]:
        assert floor["primary_daylight_ratio"] >= 0.70
        assert floor["room_form_pass_ratio"] >= 0.90
```

- [ ] **Step 2: Write failing HTML assertions**

```python
assert "building-quality/v1" in index_html
assert "Daylight proxy" in index_html
assert "Room form" in index_html
assert "Core stack" in index_html
assert "Shaft stack" in index_html
assert "Regulatory: not_checked" in index_html
```

- [ ] **Step 3: Run targeted tests and verify RED**

Avoid the long real CLI test initially:

```powershell
python -m pytest -q backend/tests/test_cli.py -k "irregular and not writes_two"
```

- [ ] **Step 4: Add one JSON serializer**

Create a private CLI serializer that converts immutable reports to plain JSON
structures. Keep exact raw measured values; round only displayed HTML values.
Do not duplicate quality calculations in CLI or visual review.

- [ ] **Step 5: Extend comparison HTML**

Add a compact quality table per alternative:

- total score
- daylight
- room form
- vertical stacking
- egress
- coverage/efficiency
- core, shaft, and wet-service stack ratios
- unresolved regulatory facts

Keep the white comparison layout and three floor PNGs per row.

- [ ] **Step 6: Run focused tests and checks**

```powershell
python -m pytest -q backend/tests/test_cli.py -k "irregular and not writes_two"
python -m ruff check backend/app/cli.py backend/tests/test_cli.py
git diff --check
```

- [ ] **Step 7: Commit**

```powershell
git add backend/app/cli.py backend/tests/test_cli.py
git commit -m "feat: expose building quality review evidence"
```

---

### Task 8: Real Irregular-Mass Evaluation and Phase Boundary

**Files:**
- Create: `docs/building-quality-baseline-2026-07-30/`
- Create: `.superpowers/sdd/2026-07-30-building-quality/task-1-report.md`
- Modify: no production code unless a preceding test exposes a defect.

**Interfaces:**
- Consumes: completed evaluator, composer, CLI, and review artifacts.
- Produces: retained exact evidence for the generation-feedback plan.

- [ ] **Step 1: Run the complete focused suites**

```powershell
python -m pytest -q backend/tests/test_building_quality_contracts.py backend/tests/test_building_quality_floor.py backend/tests/test_building_quality_building.py backend/tests/test_building_quality_service.py backend/tests/test_building_quality_diversity.py
python -m pytest -q backend/tests/test_alternative_composer.py
python -m pytest -q backend/tests/test_cli.py
python -m pytest -q backend/tests/test_visual_review.py
```

- [ ] **Step 2: Run the real irregular review**

```powershell
python -m backend.app.cli irregular-alternatives-review `
  --input datasets/manifests/sample_mass_irregular_12v_setback_office.json `
  --output-dir logs/runs/building_quality_irregular `
  --limit 3
```

Expected outcomes are both valid phase-boundary results:

- Exit `0`: at least two alternatives already meet the new quality policy.
- Non-zero: the aggregate report contains exact quality rejection issues that
  the next generation-feedback plan must target.

The command must never return `0` with fewer than two hard-pass,
quality-distinct alternatives.

- [ ] **Step 3: Retain exact artifacts**

Copy, without modifying bytes:

- aggregate JSON
- comparison HTML
- comparison PNG
- all six floor PNGs when two alternatives pass
- all available candidate/rejection evidence when fewer than two pass

Write a SHA-256 manifest and verify source/output hashes match.

- [ ] **Step 4: Inspect visual and numeric evidence**

For every retained floor verify:

- explicit floor boundary is visible
- labels remain readable
- primary spaces counted as daylight-served visibly touch a valid exterior
  window
- reported room-form failures correspond to visibly narrow or elongated rooms
- core, shaft, restroom, and service-stack evidence matches floor geometry

Record every confirmed failure code and subject in the task report. Do not
change thresholds to make the fixture pass.

- [ ] **Step 5: Verify interactive HTML**

Use Playwright against one retained floor per alternative:

- click `전체 끄기`
- enable `rooms`, `core`, and `envelope`
- isolate `core`
- restore all layers
- assert SVG visibility changes and zero console/page errors

- [ ] **Step 6: Run the full repository suite**

```powershell
python -m pytest -q
python -m ruff check backend
git diff --check
```

- [ ] **Step 7: Commit retained evidence**

```powershell
git add docs/building-quality-baseline-2026-07-30 .superpowers/sdd/2026-07-30-building-quality/task-1-report.md
git commit -m "docs: retain building quality baseline"
```

- [ ] **Step 8: Create the next implementation plan from measured failures**

If two alternatives pass, the next plan improves the lowest measured component
without weakening policy. If fewer than two pass, the next plan implements
deterministic generator feedback for each hard failure code in priority order:

1. primary daylight
2. room form
3. core/shaft stacking
4. checked egress failure
5. pairwise diversity

The separate BIM/IFC plan begins only after `BuildingQualityReport` is stable,
so IFC property mappings do not chase changing field names.
