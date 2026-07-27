# Task 3 Report

## RED

Command:

```powershell
python -m pytest backend/tests/test_building_generation.py -q
```

Output: `4 failed, 4 passed`. The intended failure was the legacy
`StopIteration` from `_normalize_program_core`, which only looked for
`shop_unit`/`office_area` and could not identify `sales` or `open_work`.

## GREEN

Command:

```powershell
python -m pytest backend/tests/test_building_generation.py -q -k "role_driven_profiles or assigns_all"
```

Output: `2 passed, 6 deselected`.

The 30x12 five-floor mixed-use test verifies exact role sets, identical core
geometry, valid doors, validator area/form metrics, commercial street contact,
and non-street stock/staff placement.

## Files Changed

- `backend/app/modules/layout_generator/service.py`
- `backend/app/modules/generation_loop/service.py`
- `backend/app/modules/generation_loop/operators.py`
- `backend/tests/test_building_generation.py`

## Commit

Pending.

## Self-Review

- Core normalization now selects exactly one residual role: `sales` for
  commercial and `open_work` for office.
- The role layout uses a deterministic vertical spine and horizontal core
  branch, one centered 0.9 m door per room, and profile-specific room order.
- Commercial generation rejects zero or ambiguous street edges.
- Candidate search gains a deterministic role-driven refinement proposal.

## Concerns

- The existing 24x12 structured-floor test is currently infeasible for this
  fixed profile/core/spine topology and raises a descriptive `ValueError`.
- One legacy candidate-search assertion expects a simple corridor with rooms
  on both bounding-box sides; the accepted role-driven branch topology does
  not satisfy that geometric heuristic although all rooms have corridor
  contact and valid doors.
- Full pytest, Ruff, compileall, and diff check remain to be run after these
  compatibility cases are resolved.
