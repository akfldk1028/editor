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

## Compatibility Fix Evidence

### Implemented

- The role-driven generator now uses a deterministic 1.2 m vertical spine and
  horizontal branch as two connected circulation polygons for commercial
  layouts. Doors select the longest shared boundary across the network.
- The 24x12 shared core uses the deterministic compatible height; commercial
  lower roles stack beside the core, while constrained office lower roles use
  their area, minimum-width, and aspect constraints when sizing.
- Role-driven refinement falls back to the generic corridor proposals when a
  small or concave plate cannot host the fixed shared-core topology.

### Verification

```powershell
python -m pytest backend/tests/test_building_generation.py backend/tests/test_generation_loop.py -q
```

Output: `17 passed`.

```powershell
ruff check .
python -m compileall backend engine
git diff --check
```

Output: all passed.

```powershell
python -m pytest -q
```

Output: `148 passed, 8 failed`. The remaining failures are legacy CLI and
visual-review assertions that require the former single rectangular corridor,
legacy `corridor-*` operator label, and legacy corridor render measurements.
They are outside the two compatibility regressions and conflict with the new
connected-circulation contract.

### Lineage Compatibility Follow-up

- Renamed the role-driven proposal operator to `corridor-role-driven` so
  structured proposal lineage retains the established `corridor-*` contract.
- The compact 20x10 commercial program remains a truthful rejected candidate:
  its sales aspect and checkout/staff minimum dimensions cannot satisfy the
  profile simultaneously. It must not be forced into acceptance.
