# Task 1 Report: Feature Schema And Deterministic Generation

## Scope

- Added frozen typed `PlanElement`, `PlanLine`, and `BasicDesignFeatures` records.
- Added optional `LayoutCandidate.basic_design` without changing existing room, circulation, or opening fields.
- Added deterministic basic-design generation to building generation only.

## RED

Focused command:

```text
pytest backend/tests/test_basic_design.py -q
ImportError: cannot import name 'BasicDesignFeatures' from 'backend.app.schemas.layout'
```

The focused contract test was added before the schema and generator implementation.

## Delivered

- Finite-coordinate typed feature records and descriptive placement failures.
- Core subdivision: two stairs, elevator, lobby, shaft; two protected 0.9 m exits; two routes from each non-core room door midpoint.
- Deterministic 6 m planning grids, collision-avoiding 0.4 m columns, windows, commercial entrance, room contents, dimensions, street, north arrow, and scale line.
- Five-floor focused test verifies feature completeness, footprint non-overlap, egress starts/targets, required program content, dimensions/site annotations, and vertically identical core/structure geometry.

## Verification

```text
pytest backend/tests/test_basic_design.py backend/tests/test_building_generation.py -q  16 passed
pytest -q                                                               169 passed
ruff check backend engine                                                All checks passed
python -m compileall -q backend engine                                  passed
git diff --check                                                        passed
```

## Boundaries

- No validator or renderer behavior was changed; strict basic-design validation and rendering remain Task 2 and Task 3 scope.

## Review Fix Round

Focused RED output before the fixes:

```text
FAILED test_sales_window_is_disjoint_from_the_commercial_entrance
assert 1.5 == 0.0
FAILED test_basic_design_rejects_duplicate_and_nonrectangular_cores
Failed: DID NOT RAISE <class 'ValueError'>
FAILED test_office_basic_design_requires_exactly_one_street_edge
Failed: DID NOT RAISE <class 'ValueError'>
```

- Street-facing sales edges now use containment within the supplied street segment. Sales windows prefer a non-street exterior edge; storefront fallback reserves a 0.1 m separation from the entrance and fails descriptively when no valid segment remains.
- Basic-design generation now requires exactly one core and one supplied street edge. Core geometry must be an axis-aligned rectangle; generated core subspaces are checked for containment and overlap.
- Building generation derives one `StructureSet` from collision-free grid-column candidates common to every floor layout, then applies the identical set to all floors.
- Added regressions for entrance/window separation, duplicate and nonrectangular core rejection, office-only street requirements, and shared structure over distinct commercial/office circulation geometry.

```text
pytest backend/tests/test_basic_design.py backend/tests/test_building_generation.py -q  20 passed
pytest -q                                                               173 passed
ruff check backend engine                                                All checks passed
python -m compileall -q backend engine                                  passed
git diff --check                                                        passed
```
