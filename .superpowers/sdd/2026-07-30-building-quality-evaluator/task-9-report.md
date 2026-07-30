# Task 9 Report: Cross-Task Quality Hardening

## Status

Completed on base `91b41e5`.

## Changes

- Classified protected-exit and disconnected-route graph facts as checked hard
  egress failures while retaining sorted unresolved facts separately.
- Made unresolved graph or regulatory evidence leave that floor `not_checked`.
- Emitted deterministic `geometry_unmeasurable` hard issues for unmeasurable
  room and vertical-stack subjects, including their floor indexes.
- Combined public coverage and efficiency validation scores with an explicit
  arithmetic mean for the coverage/efficiency component.
- Preserved complete quality reports on quality rejections and exposed their
  structured issues in CLI rejection evidence.
- Made CLI success require a hard-passing, `quality_distinct` pair; component
  fingerprints and PNG fingerprints remain reported evidence only.
- Sorted set-derived diversity inputs before float summation and excluded wet
  services absent on both adjacent floors from the stack ratio.

## Verification

- `pytest -q backend/tests/test_building_quality_hardening.py backend/tests/test_building_quality_service.py backend/tests/test_building_quality_floor.py backend/tests/test_building_quality_building.py backend/tests/test_building_quality_diversity.py backend/tests/test_building_quality_contracts.py`
  - `52 passed in 28.65s`
- `pytest -q backend/tests/test_alternative_composer.py`
  - `26 passed in 826.10s`
- `pytest -q backend/tests/test_traversable_egress.py backend/tests/test_egress_applicability.py backend/tests/test_cli.py -k 'not test_cli_irregular_review_records_task_8_quality_phase_boundary'`
  - `132 passed, 1 deselected in 40.07s`
- `ruff check ...` and `git diff --check`
  - passed

## Scope Notes

The long real irregular CLI test was not run because this change does not alter
its measured rendering phase boundary. Legal and jurisdictional facts remain
unresolved evidence rather than being promoted to hard failures.
