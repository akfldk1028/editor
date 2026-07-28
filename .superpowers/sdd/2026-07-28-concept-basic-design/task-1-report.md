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
