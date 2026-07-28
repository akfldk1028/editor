# Task 2 Report

## RED

- Command: `pytest -q backend/tests/test_basic_design_validation.py`
- Result: `26 failed`
- Intended failures:
  - `ValidationReport` has no `basic_design_checked`
  - `validate_layout()` rejects unknown `require_basic_design`
  - JSON-loaded manifest reaches `TypeError: unhashable type: 'list'` at the
    commercial street-edge comparison
- Added contract RED:
  - Command:
    `pytest -q backend/tests/test_basic_design_validation.py::test_protected_exits_reference_two_distinct_stairs`
  - Result: `1 failed`; a valid distinct-stair reference was rejected because
    protected exits had no stair-target contract yet.

## Verification

- Focused strict tests:
  - `pytest -q backend/tests/test_basic_design_validation.py`
  - `27 passed`
- Focused validator and generation regression:
  - `pytest -q backend/tests/test_validator.py backend/tests/test_basic_design.py backend/tests/test_building_generation.py backend/tests/test_basic_design_validation.py`
  - `88 passed`
- Full suite:
  - `pytest -q`
  - `207 passed`
- Ruff:
  - `ruff check backend/app/schemas/metrics.py backend/app/modules/validator/service.py backend/app/modules/generation_loop/service.py backend/app/modules/basic_design/service.py backend/tests/test_basic_design_validation.py`
  - passed
- Compile:
  - `python -m compileall -q backend engine`
  - passed
- Diff check:
  - `git diff --check`
  - passed; only Git's existing LF-to-CRLF working-copy warnings were emitted

## Additional Fixes

- Protected exits now reference two distinct generated stair elements.
- JSON-loaded list points are normalized to finite float tuples before street
  comparison and downstream geometry use.
- Circulation dimensions now use `orthogonal_min_width`, including L-shaped
  circulation, instead of a bounding-box short side.

## Deliberately Unsupported

- Statutory two-stair applicability
- Occupant load and legal travel distance
- Fire-resistance ratings
- Elevator traffic/capacity analysis
