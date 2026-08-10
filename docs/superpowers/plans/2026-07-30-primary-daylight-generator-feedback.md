# Primary Daylight Generator Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep `building-quality/v1` unchanged while deterministically repairing the measured `long_edge_adjacent` floor-3 primary-daylight failure so the irregular fixture emits at least two hard-pass, pairwise quality-distinct alternatives.

**Architecture:** `building_quality` remains an independent read-only evaluator and exposes its existing typed `PrimaryDaylightMeasurement` through the package boundary without changing the v1 report wire schema. `alternative_composer` matches the exact structured hard issue, asks `generation_loop` for one bounded exterior-allocation retry, re-runs the same evaluator, and records typed before/after provenance; `layout_generator` receives only room IDs and geometry, never a quality policy or report.

**Tech Stack:** Python 3.11+, frozen dataclasses, Shapely 2.1+, pytest, Ruff, existing deterministic generator/evaluator/CLI/visual-review stack.

## Global Constraints

- Start from commit `480640d0d42fa2b3fe8a645e40ce648cf7170209`.
- Do not change `DEFAULT_QUALITY_POLICY`, `building-quality/v1`, or its `0.70` primary-daylight hard threshold.
- Keep the v1 `FloorQualityMetrics`, `VerticalQualityMetrics`, and `BuildingQualityReport` field sets byte-for-byte compatible at the serialization boundary.
- Do not add quality rules to `validator`, and do not make `generation_loop` or `layout_generator` import `building_quality`.
- `alternative_composer` may import public names from `backend.app.modules.building_quality`; it must not import `building_quality.daylight` or any other quality submodule directly.
- Trigger feedback from `QualityIssue.code`, `severity`, `floor_index`, `subject_id`, `measured_value`, and `threshold`; never parse `reason`, `message`, or other prose.
- Pass exact room IDs from the existing `PrimaryDaylightMeasurement`, not from fixture names, room labels, or LLM output.
- Apply at most one primary-daylight retry per core/circulation/variant attempt.
- Preserve the supplied core and circulation geometry exactly during retry.
- Re-run normal basic-design generation, validation, building-quality evaluation, and pairwise diversity after repair.
- Do not count rendering-only variation as diversity.
- Do not weaken room-area, room-form, coverage, structural, circulation, egress, or render gates to obtain the second alternative.
- Keep all new ordering and tie-breaks deterministic.
- Use TDD for each behavior change and commit each completed task separately.
- Leave the retained baseline and unrelated worktree changes untouched.

---

## Measured Baseline

The retained source of truth is:

- Aggregate: `docs/building-quality-baseline-2026-07-30/source-run/alternatives.review.json`
- Aggregate SHA-256: `1a1b0390d7ed01e6293b31af786d60207ec2e6028fb2bd3c09c1e574ca5bff69`
- Task report: `.superpowers/sdd/2026-07-30-building-quality/task-1-report.md`
- Fixture: `resources/datasets/manifests/sample_mass_irregular_12v_setback_office.json`

The aggregate records:

```text
accepted_count=1
accepted strategy=notch_adjacent
rejected strategy=long_edge_adjacent
reason_type=BuildingQualityRejected
issue.code=primary_daylight_ratio
issue.severity=hard
issue.floor_index=3
issue.subject_id=floor-3
issue.measured_value=0.6625309657157782
issue.threshold=0.7
rejected candidate score=0.77
```

A read-only diagnostic through the same composer/evaluator path at `480640d`
confirmed the affected floor evidence:

```text
floor=3
served_room_ids=("open_work",)
unserved_room_ids=("focus", "meeting")
focus area=14.042697116519998, exterior contact=0.0
meeting area=95.5413509604031, exterior contact=0.0
open_work valid windows=(one exterior window)
```

The accepted `notch_adjacent` alternative is not a repair target. It may have
unserved primary rooms on individual floors, but all floor ratios already
hard-pass. Feedback activates only for the structured hard issue.

## File And Ownership Map

**Create**

- `backend/app/modules/generation_loop/contracts.py`
  - Own the quality-agnostic `ExteriorAllocationRequest`.
- `docs/primary-daylight-feedback-2026-07-30/`
  - Retain exact post-change CLI artifacts, SHA-256 manifest, and inspection report.

**Modify**

- `backend/app/modules/building_quality/__init__.py`
  - Re-export the existing daylight measurement type/function; no evaluator or wire-field change.
- `backend/app/modules/layout_generator/orthogonal.py`
  - Reserve exterior-capable cells for explicitly requested room IDs.
- `backend/app/modules/generation_loop/service.py`
  - Validate and route per-floor exterior-allocation requests.
- `backend/app/modules/alternative_composer/contracts.py`
  - Own immutable `GeneratorRepairProvenance` and attach it to alternatives/rejections.
- `backend/app/modules/alternative_composer/service.py`
  - Convert exact quality issues into one retry and re-evaluate.
- `backend/app/cli.py`
  - Serialize repair provenance and render it in comparison HTML.
- `backend/tests/test_building_quality_hardening.py`
- `backend/tests/test_orthogonal_layout_generator.py`
- `backend/tests/test_generation_loop.py`
- `backend/tests/test_alternative_composer.py`
- `backend/tests/test_cli.py`

**Must Not Change**

- `backend/app/modules/building_quality/contracts.py`
- `backend/app/modules/building_quality/policy.py`
- `backend/app/modules/building_quality/service.py`
- `backend/app/modules/building_quality/daylight.py`
- `backend/app/modules/validator/`
- `resources/datasets/manifests/sample_mass_irregular_12v_setback_office.json`
- `docs/building-quality-baseline-2026-07-30/`

## Interface Contract

`generation_loop` owns a geometry-only request:

```python
@dataclass(frozen=True)
class ExteriorAllocationRequest:
    floor_index: int
    room_ids: tuple[str, ...]
```

`run_building_generation` keeps all current parameters and gains this
keyword-only parameter:

```python
exterior_allocation_requests: Iterable[ExteriorAllocationRequest] = ()
```

The orthogonal allocator keeps all current parameters and gains this
quality-agnostic keyword-only parameter:

```python
exterior_priority_room_ids: Iterable[str] = ()
```

`alternative_composer` owns provenance; it is not part of
`BuildingQualityReport`:

```python
@dataclass(frozen=True)
class GeneratorRepairProvenance:
    operator_id: Literal["primary_daylight_exterior_allocation/v1"]
    issue_code: Literal["primary_daylight_ratio"]
    policy_version: str
    floor_index: int
    subject_id: str
    room_ids: tuple[str, ...]
    before_value: float
    threshold: float
    after_value: float
```

Add the following backward-compatible tuple defaults to the existing classes:

```python
generator_repairs: tuple[GeneratorRepairProvenance, ...] = ()
```

The aggregate JSON remains `schema_version: 1`. Existing fields are unchanged;
accepted alternatives and repaired rejections gain an additive
`generator_repairs` array.

---

### Task 1: Freeze The V1 Wire Contract And Expose Typed Daylight Evidence

**Files:**
- Modify: `backend/app/modules/building_quality/__init__.py`
- Test: `backend/tests/test_building_quality_hardening.py`

**Interfaces:**
- Consumes: existing `PrimaryDaylightMeasurement` and `measure_primary_daylight` from `building_quality/daylight.py`.
- Produces: public package imports used by `alternative_composer`.
- Preserves: exact v1 fields for `FloorQualityMetrics`, `VerticalQualityMetrics`, and `BuildingQualityReport`.

- [ ] **Step 1: Add failing public-boundary and wire-schema tests**

Add imports:

```python
from dataclasses import fields

from backend.app.modules.building_quality import (
    PrimaryDaylightMeasurement,
    measure_primary_daylight,
)
from backend.app.modules.building_quality.contracts import (
    BuildingQualityReport,
    FloorQualityMetrics,
    VerticalQualityMetrics,
)
```

Add these tests:

```python
def test_daylight_measurement_is_public_feedback_evidence() -> None:
    assert PrimaryDaylightMeasurement.__module__.endswith(".daylight")
    assert callable(measure_primary_daylight)


def test_building_quality_v1_wire_fields_remain_frozen() -> None:
    assert tuple(field.name for field in fields(FloorQualityMetrics)) == (
        "floor_index",
        "coverage",
        "primary_daylight_ratio",
        "room_form_pass_ratio",
        "worst_aspect_ratio",
        "narrowest_room_width_m",
        "egress_status",
    )
    assert tuple(field.name for field in fields(VerticalQualityMetrics)) == (
        "core_stack_ratio",
        "shaft_stack_ratio",
        "wet_service_stack_ratio",
        "maximum_service_centroid_shift_m",
    )
    assert tuple(field.name for field in fields(BuildingQualityReport)) == (
        "policy_version",
        "hard_pass",
        "score",
        "component_scores",
        "floors",
        "vertical",
        "issues",
        "unresolved_facts",
    )
```

- [ ] **Step 2: Run the focused test and verify the public import fails**

Run:

```powershell
python -m pytest -q backend/tests/test_building_quality_hardening.py::test_daylight_measurement_is_public_feedback_evidence backend/tests/test_building_quality_hardening.py::test_building_quality_v1_wire_fields_remain_frozen
```

Expected: collection fails because `PrimaryDaylightMeasurement` and
`measure_primary_daylight` are not exported from the package.

- [ ] **Step 3: Re-export existing daylight evidence without changing contracts**

In `backend/app/modules/building_quality/__init__.py`, add:

```python
from backend.app.modules.building_quality.daylight import (
    PrimaryDaylightMeasurement,
    measure_primary_daylight,
)
```

Add both names to `__all__`. Do not edit `contracts.py`, `service.py`,
`daylight.py`, or `policy.py`.

- [ ] **Step 4: Run quality tests**

Run:

```powershell
python -m pytest -q backend/tests/test_building_quality_contracts.py backend/tests/test_building_quality_floor.py backend/tests/test_building_quality_building.py backend/tests/test_building_quality_service.py backend/tests/test_building_quality_diversity.py backend/tests/test_building_quality_hardening.py
```

Expected: all pass, including the exact v1 wire-field guard.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/modules/building_quality/__init__.py backend/tests/test_building_quality_hardening.py
git commit -m "feat: expose daylight measurement for feedback"
```

---

### Task 2: Add A Typed Exterior-Allocation Request And Deterministic Cell Reservation

**Files:**
- Create: `backend/app/modules/generation_loop/contracts.py`
- Modify: `backend/app/modules/layout_generator/orthogonal.py`
- Test: `backend/tests/test_orthogonal_layout_generator.py`

**Interfaces:**
- Consumes: floor index and exact room IDs only.
- Produces: a layout where every requested room retains at least `0.6m` of real floor-exterior boundary, sufficient for the existing deterministic window generator.
- Does not consume: quality issues, thresholds, policy versions, fixture IDs, or LLM output.

- [ ] **Step 1: Write failing request-contract tests**

Add:

```python
from backend.app.modules.generation_loop.contracts import ExteriorAllocationRequest
```

Add:

```python
def test_exterior_allocation_request_requires_sorted_unique_room_ids() -> None:
    request = ExteriorAllocationRequest(
        floor_index=3,
        room_ids=("focus", "meeting"),
    )

    assert request.floor_index == 3
    assert request.room_ids == ("focus", "meeting")
    with pytest.raises(ValueError, match="sorted and unique"):
        ExteriorAllocationRequest(3, ("meeting", "focus"))
    with pytest.raises(ValueError, match="room_ids"):
        ExteriorAllocationRequest(3, ())
    with pytest.raises((TypeError, ValueError), match="floor_index"):
        ExteriorAllocationRequest(True, ("focus",))
```

- [ ] **Step 2: Run the contract test and verify it fails**

Run:

```powershell
python -m pytest -q backend/tests/test_orthogonal_layout_generator.py::test_exterior_allocation_request_requires_sorted_unique_room_ids
```

Expected: collection fails because `generation_loop.contracts` does not exist.

- [ ] **Step 3: Implement the immutable request**

Create `backend/app/modules/generation_loop/contracts.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExteriorAllocationRequest:
    floor_index: int
    room_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.floor_index, int)
            or isinstance(self.floor_index, bool)
            or self.floor_index < 1
        ):
            raise ValueError("exterior allocation floor_index must be positive")
        if (
            not isinstance(self.room_ids, tuple)
            or not self.room_ids
            or any(
                not isinstance(room_id, str) or not room_id.strip()
                for room_id in self.room_ids
            )
        ):
            raise ValueError("exterior allocation room_ids must be non-empty strings")
        if self.room_ids != tuple(sorted(set(self.room_ids))):
            raise ValueError(
                "exterior allocation room_ids must be sorted and unique"
            )
```

- [ ] **Step 4: Add a failing allocator test with explicit exterior geometry**

Add a focused unit test around `_assign_rectangles`:

```python
def test_exterior_priority_rooms_receive_window_bearing_boundary_cells() -> None:
    nodes = [
        ProgramNode("meeting", "meeting", 8.0, max_area=10.0, min_width=2.0),
        ProgramNode("focus", "focus", 8.0, max_area=10.0, min_width=2.0),
        ProgramNode("reception", "reception", 8.0, max_area=10.0, min_width=2.0),
    ]
    rectangles = [
        orthogonal_service._canonical_rectangle((0, 0, 4, 2)),
        orthogonal_service._canonical_rectangle((4, 0, 8, 2)),
        orthogonal_service._canonical_rectangle((0, 2, 4, 4)),
    ]
    exterior_segments = (((0.0, 0.0), (8.0, 0.0)),)

    assigned = orthogonal_service._assign_rectangles(
        nodes,
        rectangles,
        exterior_segments=exterior_segments,
        exterior_priority_room_ids=("focus", "meeting"),
    )
    polygons = {node.node_id: Polygon(points) for node, points in assigned}
    exterior = LineString(exterior_segments[0])

    assert polygons["focus"].boundary.intersection(exterior).length >= 0.6
    assert polygons["meeting"].boundary.intersection(exterior).length >= 0.6
    assert polygons["reception"].boundary.intersection(exterior).length == 0.0
```

Import `LineString` from `shapely.geometry`.

- [ ] **Step 5: Run the allocator test and verify the keyword failure**

Run:

```powershell
python -m pytest -q backend/tests/test_orthogonal_layout_generator.py::test_exterior_priority_rooms_receive_window_bearing_boundary_cells
```

Expected: fail because `_assign_rectangles` does not accept
`exterior_segments` or `exterior_priority_room_ids`.

- [ ] **Step 6: Implement deterministic exterior reservation**

Extend `generate_orthogonal_office_layout` and `_assign_rectangles` with the
interfaces declared above.

Normalize and validate request IDs before geometry work:

```python
exterior_priority_room_ids = tuple(exterior_priority_room_ids)
if exterior_priority_room_ids != tuple(
    sorted(set(exterior_priority_room_ids))
):
    raise ValueError("exterior priority room ids must be sorted and unique")
known_room_ids = {node.node_id for node in non_core_nodes}
unknown_room_ids = sorted(set(exterior_priority_room_ids) - known_room_ids)
if unknown_room_ids:
    raise ValueError(
        "exterior priority room ids are absent from program: "
        + ", ".join(unknown_room_ids)
    )
```

Build exterior segments from the real floor boundary:

```python
exterior_segments = tuple(
    (
        boundary_points[index],
        boundary_points[(index + 1) % len(boundary_points)],
    )
    for index in range(len(boundary_points))
)
```

Inside `_assign_rectangles`:

1. Sort requested nodes ahead of all non-requested nodes.
2. For each requested node, filter candidates to rectangles whose boundary
   shares at least `0.6m` with `exterior_segments`.
3. Before accepting a candidate, run deterministic augmenting-path bipartite
   matching over the remaining requested nodes and remaining exterior-capable
   rectangles. Reject the candidate unless every later requested node can
   still be matched. Traverse room IDs and `_rectangle_sort_key` values in
   sorted order.
4. Select with the existing `_room_fit_score`, then longest exterior contact,
   then `_rectangle_sort_key` as stable tie-breaks.
5. Raise
   `ValueError("orthogonal layout cannot reserve exterior allocation for <id>")`
   when no valid candidate remains.
6. Leave `_absorb_residual_cells` unchanged; the exterior-bearing seed ensures
   the final connected room retains its exterior segment.

Use a helper that measures real shared length rather than bbox contact:

```python
def _exterior_contact_length(
    rectangle: tuple[Point, ...],
    exterior_segments: tuple[tuple[Point, Point], ...],
) -> float:
    boundary = Polygon(rectangle).boundary
    return sum(
        boundary.intersection(LineString(segment)).length
        for segment in exterior_segments
    )
```

The capacity helper uses each node's existing `min_width` and the `0.6m`
contact minimum:

```python
def _has_exterior_seed_capacity(
    nodes: list[ProgramNode],
    rectangles: list[tuple[Point, ...]],
    *,
    exterior_segments: tuple[tuple[Point, Point], ...],
) -> bool:
    ordered_rectangle_indexes = sorted(
        range(len(rectangles)),
        key=lambda index: _rectangle_sort_key(rectangles[index]),
    )
    options = {
        node.node_id: tuple(
            index
            for index in ordered_rectangle_indexes
            if _exterior_contact_length(
                rectangles[index],
                exterior_segments,
            )
            >= 0.6
            and min(
                _bounds(rectangles[index])[2] - _bounds(rectangles[index])[0],
                _bounds(rectangles[index])[3] - _bounds(rectangles[index])[1],
            )
            + _TOLERANCE
            >= float(node.min_width or 0)
        )
        for node in nodes
    }
    matched: dict[int, str] = {}

    def assign(room_id: str, visited: set[int]) -> bool:
        for rectangle_index in options[room_id]:
            if rectangle_index in visited:
                continue
            visited.add(rectangle_index)
            incumbent = matched.get(rectangle_index)
            if incumbent is None or assign(incumbent, visited):
                matched[rectangle_index] = room_id
                return True
        return False

    ordered_room_ids = sorted(
        options,
        key=lambda room_id: (len(options[room_id]), room_id),
    )
    return all(assign(room_id, set()) for room_id in ordered_room_ids)
```

Do not change existing street `frontage_segments` semantics.

- [ ] **Step 7: Prove default geometry is unchanged and requested geometry is deterministic**

Extend the allocator test:

```python
first = orthogonal_service._assign_rectangles(
    nodes,
    rectangles,
    exterior_segments=exterior_segments,
    exterior_priority_room_ids=("focus", "meeting"),
)
second = orthogonal_service._assign_rectangles(
    nodes,
    rectangles,
    exterior_segments=tuple(reversed(exterior_segments)),
    exterior_priority_room_ids=("focus", "meeting"),
)
assert first == second
```

Run:

```powershell
python -m pytest -q backend/tests/test_orthogonal_layout_generator.py::test_exterior_allocation_request_requires_sorted_unique_room_ids backend/tests/test_orthogonal_layout_generator.py::test_exterior_priority_rooms_receive_window_bearing_boundary_cells backend/tests/test_orthogonal_layout_generator.py::test_legacy_layout_preserves_literal_room_geometry_and_unbounded_subdivision
```

Expected: all pass. The literal legacy geometry proves the empty-default path
did not move existing rooms.

- [ ] **Step 8: Run the complete orthogonal layout suite**

```powershell
python -m pytest -q backend/tests/test_orthogonal_layout_generator.py
```

Expected: all pass.

- [ ] **Step 9: Commit**

```powershell
git add backend/app/modules/generation_loop/contracts.py backend/app/modules/layout_generator/orthogonal.py backend/tests/test_orthogonal_layout_generator.py
git commit -m "feat: add exterior allocation operator"
```

---

### Task 3: Route Exterior Requests Through Building Generation

**Files:**
- Modify: `backend/app/modules/generation_loop/service.py`
- Test: `backend/tests/test_generation_loop.py`

**Interfaces:**
- Consumes: `Iterable[ExteriorAllocationRequest]`.
- Produces: the existing `BuildingGenerationResult`; no result-schema field is added.
- Preserves: all core/circulation override fingerprint validation.

- [ ] **Step 1: Write failing request-routing validation tests**

Add:

```python
from backend.app.modules.generation_loop.contracts import ExteriorAllocationRequest
```

Add tests for this small one-floor nonrectangular office mass:

```python
def _exterior_routing_mass() -> MassInput:
    return MassInput(
        project_id="exterior-routing",
        floors=1,
        footprint_polygon=[
            (0.0, 0.0),
            (30.0, 0.0),
            (30.0, 20.0),
            (20.0, 20.0),
            (20.0, 12.0),
            (0.0, 12.0),
        ],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
    )


def test_building_generation_routes_exterior_allocation_to_requested_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = []
    original = generation_service.generate_orthogonal_office_layout

    def capture(*args, **kwargs):
        observed.append(tuple(kwargs["exterior_priority_room_ids"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(
        generation_service,
        "generate_orthogonal_office_layout",
        capture,
    )
    mass = _exterior_routing_mass()
    run_building_generation(
        mass,
        exterior_allocation_requests=(
            ExteriorAllocationRequest(1, ("focus", "meeting")),
        ),
    )

    assert observed == [("focus", "meeting")]


def test_building_generation_rejects_duplicate_or_unknown_exterior_requests() -> None:
    mass = _exterior_routing_mass()
    request = ExteriorAllocationRequest(1, ("focus",))

    with pytest.raises(ValueError, match="one exterior allocation request per floor"):
        run_building_generation(
            mass,
            exterior_allocation_requests=(request, request),
        )
    with pytest.raises(ValueError, match="absent from floor program"):
        run_building_generation(
            mass,
            exterior_allocation_requests=(
                ExteriorAllocationRequest(1, ("fixture-only-room",)),
            ),
        )
```

Use the module import:

```python
import pytest

import backend.app.modules.generation_loop.service as generation_service
from backend.app.modules.generation_loop.service import run_building_generation
```

- [ ] **Step 2: Run the routing tests and verify the API failure**

Run:

```powershell
python -m pytest -q backend/tests/test_generation_loop.py::test_building_generation_routes_exterior_allocation_to_requested_floor backend/tests/test_generation_loop.py::test_building_generation_rejects_duplicate_or_unknown_exterior_requests
```

Expected: fail because `run_building_generation` does not accept
`exterior_allocation_requests`.

- [ ] **Step 3: Implement bounded request validation and routing**

Add the declared optional keyword to `run_building_generation`.

Normalize once:

```python
requests = tuple(exterior_allocation_requests)
if not all(isinstance(item, ExteriorAllocationRequest) for item in requests):
    raise TypeError(
        "exterior allocation requests must be ExteriorAllocationRequest records"
    )
if len({item.floor_index for item in requests}) != len(requests):
    raise ValueError("one exterior allocation request per floor is required")
requests_by_floor = {item.floor_index: item for item in requests}
```

Reject requests on a path that would not call the orthogonal allocator:

```python
if requests and not (has_nonrectangular_floor or has_structural_override):
    raise ValueError(
        "exterior allocation requests require orthogonal building generation"
    )
```

After the per-floor `ProgramGraph` values exist, validate:

```python
if set(requests_by_floor) - {
    program.floor_index for program in programs
}:
    raise ValueError("exterior allocation request floor is outside building")
for program in programs:
    request = requests_by_floor.get(program.floor_index)
    if request is None:
        continue
    known = {node.node_id for node in program.nodes if node.space_type != "core"}
    missing = sorted(set(request.room_ids) - known)
    if missing:
        raise ValueError(
            "exterior allocation room ids are absent from floor program: "
            + ", ".join(missing)
        )
```

Pass only the floor-specific IDs in the existing orthogonal call:

```python
request = requests_by_floor.get(program.floor_index)
layout = generate_orthogonal_office_layout(
    layout_boundary,
    program,
    core_polygon=shared_core,
    remote_stair_polygon=(
        None if circulation_candidate is not None else shared_remote_stair
    ),
    circulation_candidate=circulation_candidate,
    frontage_segments=(
        _street_segments_for_boundary(
            mass,
            floor_analysis.boundary_for_floor(program.floor_index),
        )
        if program.use_type == "neighborhood_commercial"
        else ()
    ),
    respect_program_order=program.source.startswith(
        "local_qwen_topology:"
    ),
    exterior_priority_room_ids=(
        request.room_ids if request is not None else ()
    ),
)
```

Do not mutate `ProgramGraph`, append `ProgramAdjustment`, resize rooms, change
core/circulation data, or expose the request on `BuildingGenerationResult`.

- [ ] **Step 4: Run routing and default-compatibility tests**

```powershell
python -m pytest -q backend/tests/test_generation_loop.py::test_building_generation_routes_exterior_allocation_to_requested_floor backend/tests/test_generation_loop.py::test_building_generation_rejects_duplicate_or_unknown_exterior_requests backend/tests/test_alternative_composer.py::test_rectangular_omitted_structural_overrides_preserve_default backend/tests/test_alternative_composer.py::test_building_generation_uses_exact_floor_circulation_overrides
```

Expected: all pass.

- [ ] **Step 5: Run generation and orthogonal suites**

```powershell
python -m pytest -q backend/tests/test_generation_loop.py backend/tests/test_orthogonal_layout_generator.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/modules/generation_loop/service.py backend/tests/test_generation_loop.py
git commit -m "feat: route exterior allocation requests"
```

---

### Task 4: Add One-Shot Composer Feedback And Structured Before/After Provenance

**Files:**
- Modify: `backend/app/modules/alternative_composer/contracts.py`
- Modify: `backend/app/modules/alternative_composer/service.py`
- Test: `backend/tests/test_alternative_composer.py`

**Interfaces:**
- Consumes: public `measure_primary_daylight`, hard `QualityIssue` records, and the original building.
- Produces: at most one repaired building for a failed core/circulation/variant attempt.
- Produces: immutable `GeneratorRepairProvenance` on accepted or post-retry rejected records.

- [ ] **Step 1: Write failing provenance-contract tests**

Import `GeneratorRepairProvenance` and add:

```python
def _repair_evidence(*, after_value: float = 0.75) -> GeneratorRepairProvenance:
    return GeneratorRepairProvenance(
        operator_id="primary_daylight_exterior_allocation/v1",
        issue_code="primary_daylight_ratio",
        policy_version="building-quality/v1",
        floor_index=3,
        subject_id="floor-3",
        room_ids=("focus", "meeting"),
        before_value=0.6625309657157782,
        threshold=0.7,
        after_value=after_value,
    )


def test_generator_repair_provenance_is_typed_and_immutable() -> None:
    evidence = _repair_evidence()

    assert evidence.room_ids == ("focus", "meeting")
    with pytest.raises(ValueError, match="operator_id"):
        replace(evidence, operator_id="fixture-repair")
    with pytest.raises(ValueError, match="room_ids"):
        replace(evidence, room_ids=("meeting", "focus"))
    with pytest.raises(ValueError, match="before_value"):
        replace(evidence, before_value=math.nan)
```

- [ ] **Step 2: Run the contract test and verify it fails**

```powershell
python -m pytest -q backend/tests/test_alternative_composer.py::test_generator_repair_provenance_is_typed_and_immutable
```

Expected: collection fails because `GeneratorRepairProvenance` does not exist.

- [ ] **Step 3: Implement provenance without changing quality contracts**

Add `GeneratorRepairProvenance` exactly as declared in the interface section.
Validate:

- exact `operator_id`
- exact `issue_code`
- non-empty `policy_version` and `subject_id`
- positive non-bool `floor_index`
- sorted, unique, non-empty `room_ids`
- finite `before_value`, `threshold`, and `after_value`, each in `[0, 1]`

Add `generator_repairs=()` to both structural records and validate that every
item is a `GeneratorRepairProvenance`. For every attached repair, require:

- `repair.policy_version == quality_report.policy_version`;
- one matching `quality_report.floors` record by `floor_index`;
- `repair.after_value` matches that floor's `primary_daylight_ratio` with
  `rel_tol=0.0, abs_tol=1e-12`.

A rejection with repairs must have a `quality_report`. Existing constructors
with an empty tuple must continue to work unchanged.

- [ ] **Step 4: Write a failing no-prose-parsing unit test**

Add a helper-level test for the request mapper:

```python
def test_daylight_feedback_uses_issue_code_not_reason_or_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    building = _alternatives()[0].building
    misleading = replace(
        _quality_report(
            hard_pass=False,
            hard_issue=("room_form_pass_ratio", 0.69, 0.70),
        ),
        issues=(
            QualityIssue(
                code="room_form_pass_ratio",
                severity="hard",
                floor_index=1,
                subject_id="floor-1",
                measured_value=0.69,
                threshold=0.70,
                message="primary_daylight_ratio should appear only as prose",
            ),
        ),
    )
    called = False

    def forbidden(_floor):
        nonlocal called
        called = True
        raise AssertionError("daylight measurement must not run")

    monkeypatch.setattr(alternative_service, "measure_primary_daylight", forbidden)

    assert alternative_service._primary_daylight_requests(
        building,
        misleading,
    ) == ()
    assert called is False
```

- [ ] **Step 5: Write a failing structured request-mapping test**

Use a floor with the existing measurement result:

```python
def test_primary_daylight_request_uses_typed_unserved_room_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    building = _alternatives()[0].building
    report = _quality_report(
        hard_pass=False,
        hard_issue=("primary_daylight_ratio", 0.69, 0.70),
    )
    report = replace(
        report,
        issues=(
            replace(
                report.issues[0],
                floor_index=1,
                subject_id="floor-1",
            ),
        ),
    )
    monkeypatch.setattr(
        alternative_service,
        "measure_primary_daylight",
        lambda _floor: PrimaryDaylightMeasurement(
            total_primary_area=100.0,
            served_primary_area=69.0,
            ratio=0.69,
            served_room_ids=("open_work",),
            unserved_room_ids=("focus", "meeting"),
        ),
    )

    request, = alternative_service._primary_daylight_requests(building, report)

    assert request == ExteriorAllocationRequest(
        floor_index=1,
        room_ids=("focus", "meeting"),
    )
```

- [ ] **Step 6: Run mapper tests and verify helper failures**

```powershell
python -m pytest -q backend/tests/test_alternative_composer.py::test_daylight_feedback_uses_issue_code_not_reason_or_message backend/tests/test_alternative_composer.py::test_primary_daylight_request_uses_typed_unserved_room_ids
```

Expected: fail because `_primary_daylight_requests` is missing.

- [ ] **Step 7: Implement exact issue-to-request mapping**

Import only public quality names:

```python
from backend.app.modules.building_quality import (
    AlternativeDiversityReport,
    BuildingQualityReport,
    PrimaryDaylightMeasurement,
    compare_building_diversity,
    evaluate_building_quality,
    measure_primary_daylight,
)
```

Implement `_primary_daylight_requests(building, report)`:

1. Select only issues where
   `code == "primary_daylight_ratio"` and `severity == "hard"`.
2. Require non-null `floor_index`, `subject_id`, `measured_value`, and
   `threshold`.
3. Match the floor by `floor.program.floor_index`.
4. Require `subject_id == f"floor-{floor_index}"`.
5. Call public `measure_primary_daylight(floor)`.
6. Require its ratio to match `issue.measured_value` with
   `rel_tol=0.0, abs_tol=1e-12`.
7. Use the typed, already sorted `unserved_room_ids`.
8. Return one `ExteriorAllocationRequest` per failing floor in floor order.
9. Return `()` for all other hard issue codes.

Raise a typed `ValueError` on inconsistent structured evidence; never fall back
to parsing `reason` or `message`.

- [ ] **Step 8: Write a failing bounded-retry test**

Extract the per-attempt behavior into
`_evaluate_with_primary_daylight_retry`. Its keyword inputs are
`mass: MassInput`, `assignments: tuple[FloorAssignment, ...]`,
`programs: Mapping[int, ProgramGraph]`, `core: CoreCandidate`,
`circulation: Mapping[int, CirculationCandidate]`,
`building: BuildingGenerationResult`, and
`quality_report: BuildingQualityReport`. It returns either `None` or a tuple of
`BuildingGenerationResult`, `BuildingQualityReport`, and
`tuple[GeneratorRepairProvenance, ...]`.

Test with monkeypatched generation/evaluation:

```python
def test_primary_daylight_retry_is_one_shot_and_re_evaluated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _quality_report(
        hard_pass=False,
        hard_issue=("primary_daylight_ratio", 0.69, 0.70),
    )
    after = _quality_report(hard_pass=True, score=0.81)
    calls = []

    monkeypatch.setattr(
        alternative_service,
        "_primary_daylight_requests",
        lambda _building, _report: (
            ExteriorAllocationRequest(1, ("focus", "meeting")),
        ),
    )
    monkeypatch.setattr(
        alternative_service,
        "run_building_generation",
        lambda *_args, **kwargs: calls.append(kwargs) or _alternatives()[0].building,
    )
    monkeypatch.setattr(
        alternative_service,
        "evaluate_building_quality",
        lambda _building: after,
    )

    repaired = alternative_service._evaluate_with_primary_daylight_retry(
        _mass(),
        assignments=(),
        programs={},
        core=object(),
        circulation={},
        building=_alternatives()[0].building,
        quality_report=before,
    )

    assert repaired is not None
    assert len(calls) == 1
    assert calls[0]["exterior_allocation_requests"] == (
        ExteriorAllocationRequest(1, ("focus", "meeting")),
    )
```

- [ ] **Step 9: Implement one retry and provenance construction**

The retry helper must:

1. Return `None` when there is no supported primary-daylight request.
2. Call `run_building_generation` once with the same assignments, program
   overrides, core override, and circulation overrides plus the requests.
3. Reject a regenerated building that does not pass normal building validation.
4. Call `evaluate_building_quality` exactly once on the regenerated building.
5. Look up each repaired floor's `FloorQualityMetrics.primary_daylight_ratio`
   from the new report.
6. Create `GeneratorRepairProvenance` from the original issue and new metric.
7. Return the repaired tuple even when another hard issue remains; the caller
   records that post-retry rejection with the same evidence.

In `compose_structural_alternatives`:

- keep the original `BuildingQualityRejected` record and its original
  `quality_report`;
- attempt the retry only after the original building passed validation and the
  evaluator returned a supported hard daylight issue;
- accept only when the repaired building passes validation and its re-run
  report has `hard_pass=True`;
- otherwise append one post-retry rejection;
- never call the retry helper recursively;
- attach provenance to the accepted `StructuralAlternative` or post-retry
  `StructuralAlternativeRejection`.

- [ ] **Step 10: Convert the measured irregular regression from one to two alternatives**

Rename
`test_irregular_mass_produces_quality_passed_structural_families` to
`test_irregular_mass_produces_two_hard_pass_quality_distinct_families` and
update the real cached-fixture assertions:

```python
def test_irregular_mass_produces_two_hard_pass_quality_distinct_families() -> None:
    composition = _composition()

    assert {item.strategy for item in composition.alternatives} == {
        "long_edge_adjacent",
        "notch_adjacent",
    }
    assert len(composition.alternatives) >= 2
    assert all(item.building.accepted for item in composition.alternatives)
    assert all(item.quality_report.hard_pass for item in composition.alternatives)
    long_edge = next(
        item
        for item in composition.alternatives
        if item.strategy == "long_edge_adjacent"
    )
    floor_3 = next(
        floor
        for floor in long_edge.quality_report.floors
        if floor.floor_index == 3
    )
    repair, = long_edge.generator_repairs

    assert floor_3.primary_daylight_ratio >= 0.70
    assert repair.operator_id == "primary_daylight_exterior_allocation/v1"
    assert repair.issue_code == "primary_daylight_ratio"
    assert repair.floor_index == 3
    assert repair.subject_id == "floor-3"
    assert repair.room_ids == ("focus", "meeting")
    assert repair.before_value == pytest.approx(0.6625309657157782)
    assert repair.threshold == pytest.approx(0.70)
    assert repair.after_value == pytest.approx(
        floor_3.primary_daylight_ratio
    )
    assert any(
        rejection.strategy == "long_edge_adjacent"
        and rejection.reason_type == "BuildingQualityRejected"
        and rejection.quality_report is not None
        and rejection.quality_report.floors[2].primary_daylight_ratio
        == pytest.approx(0.6625309657157782)
        for rejection in composition.rejections
    )
```

Also compare the two accepted buildings through
`compare_building_diversity` and assert `quality_distinct=True`; do not assert
only unequal hashes.

Update `test_composition_keeps_one_result_per_core_and_typed_rejections` so its
accepted strategy set is `{"long_edge_adjacent", "notch_adjacent"}`. Keep the
assertion for the original typed `long_edge_adjacent`
`BuildingQualityRejected` attempt, because successful repair does not erase
before evidence.

- [ ] **Step 11: Run the measured regression and verify it is initially red**

Before implementing the retry, run:

```powershell
python -m pytest -q backend/tests/test_alternative_composer.py::test_irregular_mass_produces_two_hard_pass_quality_distinct_families
```

Expected: fail because only `notch_adjacent` is accepted and the original
`long_edge_adjacent` floor-3 ratio is `0.6625309657157782`.

- [ ] **Step 12: Run composer tests after implementation**

```powershell
python -m pytest -q backend/tests/test_alternative_composer.py
```

Expected: all pass. The real fixture test may take several minutes.

- [ ] **Step 13: Commit**

```powershell
git add backend/app/modules/alternative_composer/contracts.py backend/app/modules/alternative_composer/service.py backend/tests/test_alternative_composer.py
git commit -m "feat: repair primary daylight alternatives"
```

---

### Task 5: Serialize Repair Evidence And Make The Irregular CLI A Success Gate

**Files:**
- Modify: `backend/app/cli.py`
- Test: `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `StructuralAlternative.generator_repairs` and rejection provenance.
- Produces: additive `generator_repairs` arrays in JSON and an exact before/after table in HTML.
- Preserves: aggregate `schema_version=1`, all existing keys, and exit success only for a hard-pass quality-distinct pair.

- [ ] **Step 1: Add failing unit serialization assertions**

Import `GeneratorRepairProvenance` and
`StructuralAlternativeRejection`. Add this local helper to `test_cli.py`:

```python
def repair_evidence(after_value: float) -> GeneratorRepairProvenance:
    return GeneratorRepairProvenance(
        operator_id="primary_daylight_exterior_allocation/v1",
        issue_code="primary_daylight_ratio",
        policy_version="building-quality/v1",
        floor_index=1,
        subject_id="floor-1",
        room_ids=("focus", "meeting"),
        before_value=0.69,
        threshold=0.7,
        after_value=after_value,
    )
```

Extend the fake-alternative helper with a
`generator_repairs: tuple[GeneratorRepairProvenance, ...] = ()` parameter and
pass it to `StructuralAlternative`. Attach `repair_evidence(daylight)` to one
alternative. Assert:

```python
assert report["alternatives"][0]["generator_repairs"] == [
    {
        "operator_id": "primary_daylight_exterior_allocation/v1",
        "issue_code": "primary_daylight_ratio",
        "policy_version": "building-quality/v1",
        "floor_index": 1,
        "subject_id": "floor-1",
        "room_ids": ["focus", "meeting"],
        "before_value": 0.69,
        "threshold": 0.7,
        "after_value": 0.7123456789,
    }
]
assert "primary_daylight_exterior_allocation/v1" in index_html
assert "0.69" in index_html
assert "0.7123456789" in index_html
```

Add a direct serializer assertion:

```python
rejection = StructuralAlternativeRejection(
    strategy="test",
    reason_type="BuildingQualityRejected",
    reason="structured test rejection",
    quality_report=alternatives[0].quality_report,
    generator_repairs=(repair_evidence(0.7123456789),),
)
serialized_rejection = cli_module._serialize_rejected_strategy(rejection)
assert serialized_rejection["generator_repairs"][0]["before_value"] == 0.69
assert serialized_rejection["generator_repairs"][0]["after_value"] == 0.7123456789
```

- [ ] **Step 2: Run the serialization test and verify the key is absent**

Run the existing fake irregular-review test by exact node name:

```powershell
python -m pytest -q backend/tests/test_cli.py -k "quality_evidence"
```

Expected: fail because accepted summaries and rejection JSON do not serialize
`generator_repairs`.

- [ ] **Step 3: Implement additive JSON and HTML evidence**

Add:

```python
"generator_repairs": to_jsonable(alternative.generator_repairs),
```

to every accepted summary. In `_serialize_rejected_strategy`, add the key only
when the tuple is non-empty, preserving current JSON for unrepaired rejections.

Render a compact table for repaired alternatives with these columns:

```text
operator | issue | floor | rooms | before | threshold | after
```

Use `html.escape` on all string values and `repr(float(value))` for retained
measurement precision. Do not infer repair state from `reason` text.

- [ ] **Step 4: Rewrite the stale Task 8 subprocess regression as the new success gate**

Rename
`test_cli_irregular_review_records_task_8_quality_phase_boundary` to
`test_cli_irregular_review_emits_two_repaired_quality_distinct_alternatives`.

Change assertions to:

```python
assert completed.returncode == 0, completed.stderr
assert report["schema_version"] == 1
assert report["quality_policy_version"] == "building-quality/v1"
assert report["accepted_count"] >= 2
assert report["distinct_structural_count"] >= 2
assert report["distinct_core_count"] >= 2
assert report["distinct_circulation_count"] >= 2
assert report["distinct_candidate_png_count"] >= 2
assert report["pairwise_diversity"]
assert any(item["quality_distinct"] for item in report["pairwise_diversity"])

long_edge = next(
    item
    for item in report["alternatives"]
    if item["strategy"] == "long_edge_adjacent"
)
floor_3 = next(
    floor
    for floor in long_edge["building_quality"]["floors"]
    if floor["floor_index"] == 3
)
repair, = long_edge["generator_repairs"]

assert long_edge["building_quality"]["hard_pass"] is True
assert floor_3["primary_daylight_ratio"] >= 0.70
assert repair["room_ids"] == ["focus", "meeting"]
assert repair["before_value"] == pytest.approx(0.6625309657157782)
assert repair["threshold"] == pytest.approx(0.70)
assert repair["after_value"] == pytest.approx(
    floor_3["primary_daylight_ratio"]
)
```

Retain an assertion that the original `BuildingQualityRejected` record still
contains the exact pre-repair report. Do not assert the obsolete floor-1 issue
or the obsolete one-item `issues` array; the refreshed source of truth is floor
3 and also contains soft/unresolved evidence.

- [ ] **Step 5: Run the real CLI regression and verify it is red before the complete implementation**

```powershell
python -m pytest -q backend/tests/test_cli.py::test_cli_irregular_review_emits_two_repaired_quality_distinct_alternatives
```

Expected before repair: return code `1`, `accepted_count=1`, and no pairwise
diversity. Expected after repair: pass with return code `0`.

- [ ] **Step 6: Run CLI and composer suites**

```powershell
python -m pytest -q backend/tests/test_alternative_composer.py
python -m pytest -q backend/tests/test_cli.py
```

Run sequentially so the expensive real fixture is not duplicated concurrently.
Expected: all pass.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/cli.py backend/tests/test_cli.py
git commit -m "feat: serialize generator repair provenance"
```

---

### Task 6: Run The Real Workflow And Retain Numeric, PNG, And HTML Proof

**Files:**
- Create: `docs/primary-daylight-feedback-2026-07-30/source-run/`
- Create: `docs/primary-daylight-feedback-2026-07-30/sha256-manifest.json`
- Create: `docs/primary-daylight-feedback-2026-07-30/inspection-report.md`
- Modify: `docs/primary-daylight-feedback-2026-07-30/.gitattributes` only if an exact generated artifact contains unavoidable whitespace that fails Git checks.
- Test: no production test changes.

**Interfaces:**
- Consumes: unchanged retained before-run evidence and the post-change CLI.
- Produces: immutable after-run evidence and a human-inspected comparison.

- [ ] **Step 1: Run all focused suites sequentially**

```powershell
python -m pytest -q backend/tests/test_building_quality_contracts.py backend/tests/test_building_quality_floor.py backend/tests/test_building_quality_building.py backend/tests/test_building_quality_service.py backend/tests/test_building_quality_diversity.py backend/tests/test_building_quality_hardening.py
python -m pytest -q backend/tests/test_orthogonal_layout_generator.py
python -m pytest -q backend/tests/test_generation_loop.py
python -m pytest -q backend/tests/test_alternative_composer.py
python -m pytest -q backend/tests/test_cli.py
python -m pytest -q backend/tests/test_visual_review.py
```

Expected: every command passes.

- [ ] **Step 2: Run the real irregular review into a new directory**

```powershell
python -m backend.app.cli irregular-alternatives-review `
  --input resources/datasets/manifests/sample_mass_irregular_12v_setback_office.json `
  --output-dir logs/runs/primary_daylight_feedback_after `
  --limit 3
```

Expected: exit `0`. Do not overwrite
`logs/runs/building_quality_irregular_refresh_d095f4a` or the retained baseline.

- [ ] **Step 3: Assert the aggregate numerically before visual review**

```powershell
$report = Get-Content -LiteralPath `
  'logs/runs/primary_daylight_feedback_after/alternatives.review.json' `
  -Raw | ConvertFrom-Json
if ($report.schema_version -ne 1) { throw 'aggregate schema changed' }
if ($report.quality_policy_version -ne 'building-quality/v1') {
  throw 'quality policy changed'
}
if ($report.accepted_count -lt 2) { throw 'fewer than two alternatives' }
if (-not ($report.pairwise_diversity | Where-Object quality_distinct)) {
  throw 'no quality-distinct pair'
}
$longEdge = $report.alternatives |
  Where-Object strategy -eq 'long_edge_adjacent' |
  Select-Object -First 1
if (-not $longEdge) { throw 'repaired long_edge_adjacent missing' }
$floor3 = $longEdge.building_quality.floors |
  Where-Object floor_index -eq 3 |
  Select-Object -First 1
if ($floor3.primary_daylight_ratio -lt 0.7) {
  throw 'floor 3 daylight remains below policy'
}
$repair = $longEdge.generator_repairs | Select-Object -First 1
if ($repair.before_value -ne 0.6625309657157782) {
  throw 'before evidence changed'
}
if ($repair.after_value -ne $floor3.primary_daylight_ratio) {
  throw 'after evidence does not match re-evaluation'
}
```

- [ ] **Step 4: Retain exact after-run files and hashes**

Copy the complete CLI output tree byte-for-byte to:

```text
docs/primary-daylight-feedback-2026-07-30/source-run/
```

Create a SHA-256 manifest with, for every file, the string fields
`relative_path`, `source_sha256`, and `retained_sha256`, plus
`bytes_match: true`. Both hashes must be lowercase 64-character SHA-256 values
computed from the actual files.

The manifest must also record:

- source commit
- fixture path and SHA-256
- CLI command
- `DEFAULT_QUALITY_POLICY` version and thresholds
- aggregate accepted/distinct counts
- before aggregate path and SHA-256

Verify every source/retained pair after copying. Do not synthesize a comparison
PNG when the CLI did not emit one.

- [ ] **Step 5: Inspect every unique retained PNG at original resolution**

Use the image viewer on all six top-level floor PNGs for the first two accepted
alternatives. Record:

- floor boundary is visible and matches the explicit floor footprint;
- labels are readable and do not overlap incoherently;
- repaired `long_edge_adjacent` floor-3 `focus` and `meeting` visibly touch the
  exterior and have window lines;
- `open_work` remains the largest non-core room;
- core and circulation geometry visibly remain in the `long_edge_adjacent`
  family;
- no room, circulation, stair, or core escapes the boundary;
- the two alternatives are visibly planning-distinct, not merely rendered
  differently.

Compare against:

```text
docs/building-quality-baseline-2026-07-30/source-run/index.html
docs/building-quality-baseline-2026-07-30/source-run/alternative-01-floor-001.png
docs/building-quality-baseline-2026-07-30/source-run/alternative-01-floor-002.png
docs/building-quality-baseline-2026-07-30/source-run/alternative-01-floor-003.png
```

The retained baseline has no rejected `long_edge_adjacent` PNG. State this
limit explicitly: numeric before/after proof is same-strategy; visual
before/after proof is accepted-set comparison plus the repaired after geometry.

- [ ] **Step 6: Verify the real comparison HTML interactively**

Serve the retained output:

```powershell
python -m http.server 8765 `
  --directory docs/primary-daylight-feedback-2026-07-30/source-run
```

Use Playwright against:

```text
http://127.0.0.1:8765/index.html
```

Verify:

- two accepted alternative sections render;
- `long_edge_adjacent` shows operator, rooms, exact before, threshold, and after;
- all six top-level floor images load with non-zero natural width/height;
- no console errors or page errors occur.

For one floor HTML per accepted alternative, repeat the stable layer flow:

```text
all-off -> enable rooms/core/envelope -> isolate core -> all-on
```

Assert SVG visibility changes at each step and all layers restore.

- [ ] **Step 7: Write the inspection report**

`inspection-report.md` must include:

- source commit and dirty-state check
- exact commands and exit codes
- before and after primary-daylight values
- requested room IDs
- all accepted strategies and scores
- pairwise diversity components and `quality_distinct`
- every retained PNG hash
- HTML interaction results
- console/page error counts
- the missing pre-repair `long_edge_adjacent` PNG limitation
- unresolved regulatory facts, still labeled unresolved
- any residual soft quality issues

- [ ] **Step 8: Run the full repository verification**

```powershell
python -m pytest -q
python -m ruff check backend
git diff --check
```

Expected: all pass. The pre-existing `requests` dependency warning may remain;
record it without treating it as a new failure.

Verify ownership and immutable inputs explicitly:

```powershell
$generatorImports = rg -n "modules\.building_quality" `
  backend/app/modules/generation_loop `
  backend/app/modules/layout_generator
if ($LASTEXITCODE -eq 0) { throw $generatorImports }
git diff 480640d -- `
  backend/app/modules/building_quality/contracts.py `
  backend/app/modules/building_quality/policy.py `
  backend/app/modules/building_quality/service.py `
  backend/app/modules/building_quality/daylight.py `
  resources/datasets/manifests/sample_mass_irregular_12v_setback_office.json `
  docs/building-quality-baseline-2026-07-30
```

Expected: `rg` finds no generator-to-quality import and `git diff` emits
nothing for the frozen policy/report/evaluator/fixture/baseline files.

- [ ] **Step 9: Commit retained proof**

```powershell
git add docs/primary-daylight-feedback-2026-07-30
git commit -m "docs: retain primary daylight feedback evidence"
```

---

## Termination Limits

Stop the implementation and retain the failed aggregate for diagnosis when any
of these occurs:

- the exterior allocator cannot reserve cells for every typed unserved room;
- the repaired building fails an existing validator or structural override gate;
- the re-run floor-3 ratio remains below `0.70`;
- a different hard quality issue appears after repair;
- fewer than two hard-pass alternatives remain;
- the pair is not quality-distinct under the unchanged v1 diversity policy;
- a repaired room has no valid exterior window in rendered/basic-design evidence;
- PNG inspection exposes boundary escape, overlap, unreadable labels, or a
  rendering-only distinction;
- a focused or full test fails for reasons introduced by the change.

Do not add a second repair iteration, resize the program, change the fixture,
lower thresholds, reinterpret unresolved egress as pass, or add a
`long_edge_adjacent`/floor-3 special case. Those are separate measured plans.

## Rollback Boundaries

Each implementation commit is independently reversible:

1. Revert `docs: retain primary daylight feedback evidence` to remove only retained proof.
2. Revert `feat: serialize generator repair provenance` to remove additive CLI/HTML evidence while leaving generator behavior.
3. Revert `feat: repair primary daylight alternatives` to restore reject-only composer behavior.
4. Revert `feat: route exterior allocation requests` to remove building-generation routing.
5. Revert `feat: add exterior allocation operator` to remove the geometry request and allocator.
6. Revert `feat: expose daylight measurement for feedback` to restore the original package exports.

Never revert the retained
`docs/building-quality-baseline-2026-07-30/` evidence or Task 9 quality-wire
hardening when rolling back this feature.
