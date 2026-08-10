# Concept Basic Design Implementation Plan

> **For agentic workers:** Use subagent-driven development, TDD, task review,
> and scoped fix loops. Do not render any feature that is absent from the model
> or unchecked by validation.

**Goal:** Produce and verify a reviewable concept/basic-design plan rather than
a colored zoning diagram.

**Architecture:** Add explicit basic-design feature records to layouts,
generate them deterministically from the validated use-specific plan, enforce
an opt-in strict completeness policy, then render identical feature layers to
SVG/PNG/HTML.

**Tech Stack:** Python 3.11 dataclasses, Shapely isolated in `engine.geometry`,
dependency-free PNG canvas, pytest, Playwright.

## Global Constraints

- Use RED/GREEN/REFACTOR and record the intended RED failure.
- Preserve all 167 passing tests before this plan.
- Do not weaken area, room form, frontage, door, or circulation gates.
- Keep Shapely objects out of backend schemas and application services.
- Preserve vertically identical core and structure geometry across all floors.
- Treat all numerical defaults as `concept-basic-v1`, not legal compliance.
- Keep unsupported legal checks explicitly `not_checked`.
- Do not touch unrelated `.playwright-mcp/` or `dwg-controls-settings.png`.

---

### Task 1: Feature Schema And Deterministic Generation

**Files:**
- Modify: `backend/app/schemas/layout.py`
- Create: `backend/app/modules/basic_design/service.py`
- Modify: `backend/app/modules/generation_loop/service.py`
- Test: `backend/tests/test_basic_design.py`
- Test: `backend/tests/test_building_generation.py`

- [ ] Write RED tests for explicit feature schema, core subdivision, two exits,
  two routes per occupied room, grid/columns, windows/entrance, required
  furniture/fixtures, dimensions/site, and vertical alignment.
- [ ] Generate deterministic finite geometry after the role-driven layout.
- [ ] Keep all features in separate collections from rooms/circulation.
- [ ] Run focused tests and Ruff; commit.

### Task 2: Strict Basic-Design Validation

**Files:**
- Modify: `backend/app/schemas/metrics.py`
- Modify: `backend/app/modules/validator/service.py`
- Modify as needed: `engine/geometry/access.py`
- Test: `backend/tests/test_basic_design_validation.py`
- Test: `backend/tests/test_validator.py`

- [ ] Write RED tests for every strict gate and unchecked policy state.
- [ ] Validate references, containment, overlap, exits/routes, structure,
  envelope, objects, and dimensions independently of the generator.
- [ ] Record `BasicDesignMetric` and structured violations.
- [ ] Make building generation opt into strict policy.
- [ ] Run focused/full validator tests and Ruff; commit.

### Task 3: SVG, PNG, Text, And Review Controls

**Files:**
- Modify: `engine/io/png.py`
- Modify: `backend/app/modules/visual_review/service.py`
- Modify: `backend/tests/test_visual_review.py`
- Modify: `tests/browser/visual_review.spec.js`

- [ ] Write RED SVG DOM, PNG pixel/text, report, and Playwright tests.
- [ ] Add deterministic 5x7 PNG text and basic drawing primitives.
- [ ] Render every feature layer with stable `data-id`/`data-kind`.
- [ ] Add completeness checks/metrics and synchronized controls.
- [ ] Fix the corrupted building-index separator.
- [ ] Run focused Python/browser tests, Ruff, and commit.

### Task 4: Actual Five-Floor Loop And Visual Repair

**Files:**
- Modify as needed based on verified failures only.
- Update: `resources/research/paper_cards/llm_hybrid_floorplan_generation.md`
- Test: `backend/tests/test_cli.py`

- [ ] Run actual OpenAI five-floor building review into
  `logs/runs/sample_basic_design_llm`.
- [ ] Open commercial and office PNGs at original resolution.
- [ ] Check feature visibility, collision, labels, dimensions, clipping, and
  room readability; repair with regression tests and repeat.
- [ ] Verify index and detail HTML at 1440x900 and 390x844, all controls, links,
  and zero browser errors.
- [ ] Run full pytest, browser tests, Ruff, compileall, and diff check.
- [ ] Commit, then run final whole-branch review.
