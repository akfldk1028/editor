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
