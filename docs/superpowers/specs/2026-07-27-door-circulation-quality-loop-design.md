# Door And Circulation Quality Loop

## Goal

Move PLAN from room zoning toward a connected schematic floor plan by making
doors and corridor width explicit, validated geometry.

## Scope

- Add door openings as line segments with explicit endpoints and connected
  space IDs.
- Generate one corridor door for every room in the core-aligned building
  layout.
- Validate that each door lies on the shared boundary of both connected
  spaces and meets a configurable research minimum width.
- Validate the minimum thickness of axis-aligned rectangular or orthogonal
  circulation polygons.
- Render doors in SVG and PNG and report opening/corridor checks in review JSON.
- Re-run the five-floor OpenAI sample and inspect the browser artifacts.

## Contracts

`OpeningSegment` contains `opening_id`, `kind`, `connects`, `start`, `end`, and
`clear_width`. `LayoutCandidate.openings` defaults to an empty list so existing
generators remain compatible.

`validate_layout` accepts opt-in `require_openings`, `min_door_width`, and
`min_circulation_width` keyword policy values. Defaults are research baselines,
not jurisdiction-specific code claims. The validator emits structured
`door_missing`, `door_geometry`, `door_width`, and
`circulation_too_narrow` violations.

## Geometry

Door placement uses the longest positive shared boundary between a room and
circulation, centered on that boundary. The door segment cannot extend beyond
the shared boundary. Orthogonal corridor thickness is measured from scan bands
formed by unique polygon coordinates; non-orthogonal circulation is rejected
by this V1 quality gate instead of receiving a guessed width.

## Acceptance

Building layouts produced by `generate_core_aligned_layout` must have one valid
corridor door per room and circulation width at or above the configured
threshold. Existing single-floor search candidates without openings retain
their existing acceptance policy until they opt into the new building quality
policy.

## Visual Review

SVG and PNG draw door openings as high-contrast wall breaks/segments. SVG adds
the measured clear width as accessible text. Review JSON exposes door count,
minimum door width, minimum corridor width, and pass/fail checks.

## Limits

This loop does not model swing clearance, door handing, fire ratings, occupant
load, travel distance, multiple exits, stairs, structure, MEP, or Korean
building-code compliance. Those require a jurisdiction and occupancy profile.

## Research Basis

- HouseDiffusion represents rooms and doors as vector polygon loops:
  https://openaccess.thecvf.com/content/CVPR2023/html/Shabani_HouseDiffusion_Vector_Floorplan_Generation_via_a_Diffusion_Model_With_Discrete_CVPR_2023_paper.html
- DPLAN treats door connectivity and non-adjacency as primary graph
  constraints: https://arxiv.org/abs/2606.21159
- MSD models room shapes and connectivity types together on a graph:
  https://github.com/caspervanengelenburg/msd
