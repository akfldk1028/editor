# Use-Specific Space Program And Form

## Goal

Replace the current one-room office/shop baseline with schematic plans whose
space mix, proportions, placement, and circulation reflect the selected use.

## Research Position

The ratios below are explicit baseline priors for this prototype, not universal
design rules or building-code compliance. The hard geometric checks follow the
research pattern of combining area, minimum dimension, aspect ratio,
adjacency, frontage, and connectivity constraints instead of judging a plan by
image plausibility alone.

## Program Profiles

Office uses:

| Space | Ratio | Minimum width | Maximum aspect | Zone |
| --- | ---: | ---: | ---: | --- |
| `open_work` | 0.52 | 6.0 m | 2.5 | workplace |
| `meeting` | 0.10 | 2.7 m | 2.0 | public |
| `reception` | 0.05 | 2.4 m | 2.5 | public |
| `focus` | 0.06 | 1.8 m | 1.8 | workplace |
| `pantry` | 0.03 | 1.8 m | 2.0 | service |
| `restroom` | 0.05 | 1.8 m | 2.5 | service |
| `core` | 0.14 | 3.0 m | 2.0 | core |
| `it_storage` | 0.05 | 1.5 m | 2.5 | service |

Neighborhood commercial uses:

| Space | Ratio | Minimum width | Maximum aspect | Zone |
| --- | ---: | ---: | ---: | --- |
| `sales` | 0.57 | 5.0 m | 3.0 | frontage |
| `checkout` | 0.04 | 2.4 m | 3.0 | public |
| `stock` | 0.10 | 2.4 m | 2.5 | service |
| `staff` | 0.05 | 2.4 m | 2.0 | service |
| `restroom` | 0.05 | 1.8 m | 2.5 | service |
| `core` | 0.12 | 3.0 m | 2.0 | core |
| `utility` | 0.07 | 1.5 m | 2.5 | service |

All ratios sum to 1.0. Area tolerance remains minus/plus 15 percent. `sales`
requires real street frontage. Office reception requires a public circulation
relationship, not exterior frontage.

## Relationships

Office prioritizes reception-meeting, open_work-focus, open_work-meeting,
core-restroom, core-it_storage, and pantry-open_work relationships.

Commercial prioritizes sales-street, checkout-sales, stock-sales, staff-stock,
core-restroom, and core-utility relationships.

## Layout Topology

The use-specific generator keeps the vertically shared core fixed and reserves
a 1.2 m circulation spine plus a connector to the core. It deterministically
sorts rooms by role so program node input order cannot change the layout.

Commercial places `sales` as the large street-facing room, `checkout` at the
public front, and `stock`, `staff`, restroom, and utility away from the street.
Office places `open_work` as the largest perimeter room and places meeting,
reception, focus, pantry, restroom, and storage on circulation-facing stacks.
Every room and the core receives one 0.9 m door on a positive shared
circulation boundary.

Candidate geometry must satisfy target area tolerance, program minimum width,
program maximum bounding-box aspect ratio, frontage/rear-service rules, door
length, 1.2 m circulation throat and junction width, no overlap, and mass
containment. An infeasible program raises a descriptive error rather than
silently distorting rooms.

## Validation And Review

`ProgramNode` gains optional `min_width`, `max_aspect_ratio`, and `zone`
metadata. The validator rejects invalid metadata and emits hard
`room_min_width` and `room_aspect_ratio` violations for generated rooms.
Review JSON and the HTML page expose measured minimum room width, maximum room
aspect ratio, and failed room IDs. SVG labels retain room type and area so the
space program can be inspected directly.

## Acceptance

- The 30 m by 12 m sample generates seven commercial rooms and eight office
  rooms with the exact profile types above.
- All five floors preserve the identical core polygon.
- Every room is inside the mass, non-overlapping, within area tolerance, within
  width/aspect limits, and connected by a valid door.
- Commercial sales has positive street frontage; stock and staff do not.
- The OpenAI five-floor building run is accepted and its HTML/PNG/SVG/JSON
  artifacts visibly differ between commercial and office floors.

## Limits

This loop remains schematic. It does not establish occupant load, travel
distance, multiple exits, stair count, accessibility turning clearances,
structure, MEP, daylight performance, furniture fit, or Korean code
compliance.

## Research Basis

- Automated dimensioned rectangular floor plans with minimum width and aspect
  constraints: https://arxiv.org/abs/1910.00081
- Graph-conditioned room layout generation:
  https://arxiv.org/abs/2004.13204
- High-level specifications including orientation, aspect, and adjacency:
  https://www.sciencedirect.com/science/article/pii/S0926580520301199
- Function-feasible evaluation beyond visual plausibility:
  https://openaccess.thecvf.com/content/CVPR2026F/html/Zeng_GreenPlanner_Practical_Floorplan_Layout_Generation_via_an_Energy-Aware_and_Function-Feasible_CVPRF_2026_paper.html
