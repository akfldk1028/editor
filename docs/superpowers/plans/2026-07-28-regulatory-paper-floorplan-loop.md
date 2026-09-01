# Regulatory And Paper Floorplan Loop Implementation Plan

> Use subagent-driven TDD, independent review, and repeated artifact inspection.
> Root owns web/paper/legal research; agents do not perform web research.

## Task 1: Compliance Facts And Honest Status

- Add immutable optional code context to mass schema and CLI loading.
- Add structured regulatory check/result schemas with source evidence.
- Preserve old manifests and emit `not_checked` for missing facts.
- Replace `passes hard validation` with separate internal/regulatory labels.
- Add RED tests, implement, run focused/full tests, independently review.

## Task 2: Korean Egress Applicability And Separation

- Encode supported Article 34 applicability branches with explicit inputs.
- Use diagonal/2 by default and diagonal/3 only for explicit qualifying
  sprinkler protection.
- Separate required stair count from conservative generated stair count.
- Record unsupported branches and missing facts as `not_checked`.
- Add boundary cases for use, floor, area, and sprinkler state.

## Task 3: Parametric Stair Geometry

- Add stair flight, riser, tread, landing, height, width, door, and headroom
  records.
- Derive enclosure footprint from parameters and validate recomputation.
- Render derived stair geometry in SVG/PNG/HTML without fixed tread symbols.
- Visually inspect compact and wide masses and repair collisions.

## Task 4: Traversable Egress And Area Accounting

- Build route graph from rooms, openings, corridors, lobbies, and exits.
- Measure farthest-point travel distance, common path, and dead ends where the
  model supports them; otherwise report `not_checked`.
- Report gross/core/circulation/service/net areas with provenance.
- Produce code-minimum and redundant-egress families when applicable.

## Task 5: Paper Adapter Harness

- Define canonical request/response and isolated subprocess adapter protocol.
- Implement deterministic adapter and conformance tests first.
- Add Graph2Plan and HouseDiffusion official-code runners with environment,
  checkpoint, dataset, license, and domain records.
- Add RLVR proposal/verifier adapter with a hardware-aware unavailable path.
- Add MANSION as downstream multi-floor evaluation only.
- Benchmark identical normalized inputs and retain raw plus normalized outputs.

## Task 6: End-To-End Review Loop

- Run at least three alternatives for rectangular, narrow, and irregular
  multi-floor masses.
- Retain every JSON/SVG/PNG/HTML artifact under versioned run directories.
- Open PNGs at original resolution and exercise every CAD layer control in
  desktop and mobile browser tests.
- Run full pytest, Ruff, compileall, browser tests, and artifact consistency
  checks.
- Repeat failed tasks through implementation/review/fix loops; claim only the
  checked scope.
