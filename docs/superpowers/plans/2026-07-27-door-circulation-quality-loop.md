# Door And Circulation Quality Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit, geometrically validated doors and minimum corridor width to core-aligned multi-floor plans.

**Architecture:** Extend the layout schema with opening segments, keep geometric operations in `engine.geometry`, and make building generation opt into a stricter validation policy. Render the same validated data in SVG, PNG, HTML, and JSON.

**Tech Stack:** Python 3.11, dataclasses, Shapely isolated in `engine.geometry`, pytest, existing dependency-free PNG canvas.

## Global Constraints

- Use TDD and verify every new test fails for the intended reason.
- Keep Shapely objects out of backend schemas and application services.
- Treat width defaults as research policy, not legal compliance.
- Preserve current single-floor candidate-search behavior.
- Preserve vertically identical core polygons across all floors.

---

### Task 1: Opening And Width Geometry Contracts

**Files:**
- Modify: `backend/app/schemas/layout.py`
- Create: `engine/geometry/access.py`
- Modify: `engine/geometry/__init__.py`
- Test: `backend/tests/test_access_geometry.py`

**Interfaces:**
- Produces: `OpeningSegment` and `shared_boundary_segments(left, right)`.
- Produces: `orthogonal_min_width(polygon) -> float`.

- [ ] Write RED tests for horizontal/vertical shared boundaries, centered
  segment inputs, rectangular width, L-shaped width, and non-orthogonal error.
- [ ] Run `pytest -q backend/tests/test_access_geometry.py` and confirm failure.
- [ ] Add the dataclass and geometry functions using plain point tuples at the
  public boundary.
- [ ] Run the focused tests and `python -m ruff check backend engine`.
- [ ] Commit the task.

### Task 2: Door Generation And Hard Validation

**Files:**
- Modify: `backend/app/modules/layout_generator/service.py`
- Modify: `backend/app/modules/validator/service.py`
- Modify: `backend/app/schemas/metrics.py`
- Modify: `backend/app/modules/generation_loop/service.py`
- Test: `backend/tests/test_validator.py`
- Test: `backend/tests/test_building_generation.py`

**Interfaces:**
- Consumes: `OpeningSegment`, `shared_boundary_segments`,
  `orthogonal_min_width`.
- Produces: valid room-to-corridor doors on core-aligned layouts and structured
  width/geometry violations.

- [ ] Write RED tests proving missing, short, and off-boundary doors fail and a
  centered shared-boundary door passes.
- [ ] Write a RED building test requiring one valid door per generated room on
  all five floors.
- [ ] Run focused tests and confirm expected failures.
- [ ] Generate centered openings from the longest shared boundary and add
  configurable research thresholds to validation.
- [ ] Run focused tests, full validator tests, and Ruff.
- [ ] Commit the task.

### Task 3: Door And Width Review Artifacts

**Files:**
- Modify: `backend/app/modules/visual_review/service.py`
- Modify: `backend/app/schemas/visual.py`
- Test: `backend/tests/test_visual_review.py`

**Interfaces:**
- Consumes: validated openings and measured widths.
- Produces: SVG/PNG door graphics and review JSON door/corridor fields.

- [ ] Write RED tests for SVG door elements, non-background PNG door pixels,
  and report width/check fields.
- [ ] Run the focused tests and confirm expected failures.
- [ ] Draw door segments with stable dimensions and serialize the measurements.
- [ ] Run visual tests, inspect generated PNG/SVG, and run Ruff.
- [ ] Commit the task.

### Task 4: End-To-End LLM Building Review

**Files:**
- Modify: `research/paper_cards/llm_hybrid_floorplan_generation.md`
- Test: `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: the existing `building-review --planner openai` CLI.
- Produces: a five-floor accepted artifact set with explicit doors and width
  checks.

- [ ] Extend the CLI integration assertion to require the new checks.
- [ ] Run the test and confirm failure before implementation integration.
- [ ] Run the actual OpenAI sample into
  `logs/runs/sample_building_review_llm`.
- [ ] Verify the index and a floor detail page in Playwright with no console
  errors.
- [ ] Run `pytest -q`, Ruff, compileall, and `git diff --check`.
- [ ] Commit the task.
