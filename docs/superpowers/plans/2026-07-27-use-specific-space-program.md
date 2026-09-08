# Use-Specific Space Program Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development to implement this plan task-by-task.
> Every production change follows RED, GREEN, REFACTOR.

**Goal:** Generate and validate office and neighborhood-commercial layouts
with use-appropriate space ratios and room forms.

**Architecture:** Program profiles own ratios and form metadata. A
role-driven layout generator consumes those nodes around the existing shared
core and circulation contract. The validator independently enforces room
shape and frontage requirements, and review artifacts expose the measurements.

**Tech Stack:** Python 3.11, dataclasses, Shapely isolated in
`engine.geometry`, pytest, existing SVG/PNG/HTML review pipeline.

## Global Constraints

- Use TDD and record the intended RED failure before production edits.
- Ratios are prototype research priors, not universal or legal requirements.
- Keep Shapely objects out of backend schemas and application services.
- Preserve the validated 0.9 m door and 1.2 m circulation policies.
- Preserve vertically identical core polygons across every generated floor.
- Node input order must not change deterministic geometry.
- Fail explicitly when a program cannot satisfy its geometric constraints.
- Leave unrelated `.playwright-mcp/` and `dwg-controls-settings.png` untouched.

---

### Task 1: Program Profiles And Form Metadata

**Files:**
- Modify: `backend/app/schemas/program.py`
- Modify: `backend/app/modules/program_prior/service.py`
- Modify as needed: `backend/app/schemas/llm.py`
- Modify as needed: `backend/app/modules/llm_planner/contracts.py`
- Test: `backend/tests/test_program_prior.py`
- Test as needed: `backend/tests/test_llm_contracts.py`

**Interfaces:**
- Produces optional `ProgramNode.min_width`, `max_aspect_ratio`, and `zone`.
- Produces the exact office and commercial profiles from the design spec.

- [ ] Write RED tests for exact types, ratios, metadata, and relationships.
- [ ] Run focused tests and record expected failures.
- [ ] Implement immutable typology profiles and node generation.
- [ ] Keep office reception non-frontage and commercial sales frontage.
- [ ] Run focused tests, Ruff, and commit.

### Task 2: Hard Room Form Validation

**Files:**
- Modify: `backend/app/modules/validator/service.py`
- Modify: `backend/app/schemas/metrics.py`
- Modify as needed: `engine/geometry/access.py`
- Test: `backend/tests/test_validator.py`
- Test as needed: `backend/tests/test_access_geometry.py`

**Interfaces:**
- Consumes `ProgramNode.min_width` and `max_aspect_ratio`.
- Produces `room_min_width` and `room_aspect_ratio` hard violations and
  measurements.

- [ ] Write RED tests for width/aspect pass, fail, boundary, invalid, and
  non-finite cases.
- [ ] Run focused tests and record expected failures.
- [ ] Implement orthogonal room width and bounding-box aspect checks.
- [ ] Ensure missing metadata remains backward compatible.
- [ ] Run focused tests, full validator tests, Ruff, and commit.

### Task 3: Role-Driven Typology Layouts

**Files:**
- Modify: `backend/app/modules/layout_generator/service.py`
- Modify: `backend/app/modules/generation_loop/service.py`
- Test: `backend/tests/test_building_generation.py`
- Test as needed: `backend/tests/test_generation_loop.py`

**Interfaces:**
- Consumes the profile roles, form constraints, fixed core, door, and corridor
  contracts.
- Produces deterministic multi-room office and commercial floor plans.

- [ ] Write RED tests for exact room sets, street/rear placement, largest
  primary room, core identity, node-order invariance, doors, width/aspect,
  and infeasible programs.
- [ ] Run focused tests and record expected failures.
- [ ] Replace the one-primary assumption with a role-driven spine/connector
  layout and explicit `sales`/`open_work` residual normalization.
- [ ] Preserve one valid door per room and the corridor/core connection.
- [ ] Run building, generation-loop, validator, Ruff, and full tests; commit.

### Task 4: Shape Review And Five-Floor Verification

**Files:**
- Modify: `backend/app/modules/visual_review/service.py`
- Modify: `backend/app/schemas/visual.py`
- Modify: `backend/tests/test_visual_review.py`
- Modify as needed: `backend/tests/test_cli.py`
- Modify: `resources/research/paper_cards/llm_hybrid_floorplan_generation.md`

**Interfaces:**
- Consumes validated form measurements.
- Produces review checks and browser-visible room program/form evidence.

- [ ] Write RED tests for room width/aspect review fields and failed room IDs.
- [ ] Run focused tests and record expected failures.
- [ ] Add measurements without duplicating validator geometry policy.
- [ ] Run the actual OpenAI five-floor sample and inspect commercial and office
  pages plus PNG output.
- [ ] Verify buttons and browser console on the PLAN review server.
- [ ] Run `pytest -q`, Ruff, compileall, and `git diff --check`; commit.
