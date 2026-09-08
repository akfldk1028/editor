# Task 5a Report

## Scope

- Replaced undersized core symbols with separated representative stair footprints.
- Added a contained concave lobby, two stair doors, and two protected-exit-to-stair lobby routes.
- Added strict independent checks for stair size/separation, stair-door references/boundaries, and lobby-route endpoints/containment.
- Added furniture/fixture clearance checks for host-room doors, entrances, egress routes, and windows.
- Added clearance metrics and malformed independent-candidate tests.

## Concept Policy

- Target core geometry uses 2.8 x 4.8 m representative stair footprints.
- Geometry-constrained legacy inputs preserve at least a 1.2 m central bank and 0.6 m lobby depth, with a bounded 2.4 x 4.0 m minimum fallback.
- Object clearance is 0.6 m, or 0.3 m for rooms below 12 m2 or 3 m minimum bounding-box width.
- These are `concept-basic-v1` review policies, not legal-compliance claims.

## Verification

- RED:
  - Existing generated stair dimensions failed the new 2.8 x 4.8 m contract.
  - A sales shelf intersecting its room door was accepted before the validator change.
- GREEN:
  - `pytest -q backend/tests/test_basic_design.py backend/tests/test_basic_design_validation.py` -> 52 passed.
  - `pytest -q backend/tests/test_building_generation.py::test_building_generation_assigns_all_floors_and_aligns_vertical_core` -> 1 passed.
  - `ruff check ...` for all owned Python files -> passed.
  - `python -m compileall -q backend/app/modules/basic_design backend/app/modules/validator backend/app/schemas` -> passed.
  - `git diff --check` -> passed.

## Deferred To Root Integration

- Full suite rerun after shared renderer changes.
- Regenerate `logs/runs/sample_basic_design_core_fixed`.
- Open original F1/F2 PNGs and verify visible stairs, lobby, stair doors, lobby routes, and unobstructed objects.
