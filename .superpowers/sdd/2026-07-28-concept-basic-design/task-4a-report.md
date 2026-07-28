# Task 4a Report

## Scope

- Corridor-routed schematic egress polylines
- Independent strict route validation
- `concept-basic-v1` primary-room furniture density

## Behavior

- Rectilinear circulation polygons are decomposed into connected rectangular
  cells.
- Each route starts at the real room-door midpoint, traverses cell portals with
  orthogonal segments inside the circulation union, and ends at one of two
  distinct protected-exit midpoints.
- Non-axis-aligned or disconnected circulation geometry fails generation.
- Strict validation independently rejects diagonal, zero-length, non-finite,
  endpoint-mismatched, and circulation-leaving route geometry.
- `sales_shelf` and `workstation` counts use
  `max(2, floor(room_area / 30 m2))`.
- Primary objects use a deterministic spread grid and preserve 0.6 m schematic
  clearance from doors, entrances, and egress routes.

This is a corridor-routed schematic and concept furniture-density policy. It
does not establish code compliance, travel distance, fire rating, or detailed
furniture design.

## Verification

- Focused: `46 passed`
- Full: `246 passed`
- Ruff: passed
- `compileall`: passed
- `git diff --check`: passed
- 30 m x 12 m sample: F1 sales shelves `5`, F2 workstations `5`

## Visual Evidence

- Deterministic building review:
  `logs/runs/sample_basic_design_routed/index.html`
- F1 PNG:
  `logs/runs/sample_basic_design_routed/floor_001/sample-office-commercial-a8290018982a4b2c-f1.png`
- F2 PNG:
  `logs/runs/sample_basic_design_routed/floor_002/sample-office-commercial-a8290018982a4b2c-f2.png`
- All five floors: accepted, `needs_iteration=false`, all review checks pass
- Direct PNG inspection: F1 sales shelves and F2 workstations are visibly
  distributed across both room axes; route strokes remain inside the rendered
  circulation band and terminate at both protected exits.

Primary-room route points:

```text
F1 sales -> exit 1:
(14.1075, 6.0) -> (15.3075, 6.0) -> (15.3075, 6.28)
-> (22.907747, 6.28) -> (22.907747, 5.68)

F1 sales -> exit 2:
(14.1075, 6.0) -> (15.3075, 6.0) -> (15.3075, 6.28)
-> (28.219014, 6.28) -> (28.219014, 5.68)

F2 open_work -> exit 1:
(13.338, 6.0) -> (14.538, 6.0) -> (14.538, 6.28)
-> (22.907747, 6.28) -> (22.907747, 5.68)

F2 open_work -> exit 2:
(13.338, 6.0) -> (14.538, 6.0) -> (14.538, 6.28)
-> (28.219014, 6.28) -> (28.219014, 5.68)
```
